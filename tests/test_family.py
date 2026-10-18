"""Device enrolment, passwordless sign-in, locked roles and the encrypted vault (server side)."""
import os
import unittest

from agent.agent import CONFIG, Agent
from app.family import SIGN_IN_CONTEXT, FamilyError
from scenarios import fixtures as fx
from security import ed25519
from security.pki import b64e, demo_secret, sign_bytes

PIN = CONFIG["demo_pin"]
STUDENT_SECRET = demo_secret("student-device")
STUDENT_PUBLIC = b64e(ed25519.public_key(STUDENT_SECRET))
OTHER_SECRET = demo_secret("second-student-device")
OTHER_PUBLIC = b64e(ed25519.public_key(OTHER_SECRET))


def box():
    return b64e(os.urandom(32))  # stands in for an X25519 public key: the server never uses it to encrypt


def kid_of(public):
    return next(k for k, v in A.family.devices.items() if v["public_key"] == public)


def sealed(recipients, size=100):
    """What the browser uploads: random bytes stand in for ciphertext the server cannot read anyway."""
    return {"name": "admission_letter.pdf", "mime": "application/pdf", "iv": b64e(os.urandom(12)),
            "ciphertext": b64e(os.urandom(size + 16)), "ephemeral_key": box(),
            "wrapped": {k: {"iv": b64e(os.urandom(12)), "key": b64e(os.urandom(48))} for k in recipients}}


class TestFamily(unittest.TestCase):
    def setUp(self):
        global A
        self.now = [1_000_000.0]
        A = self.a = Agent()
        self.a.family.clock = lambda: self.now[0]
        self.assertTrue(self.a.register_device(PIN, "parent", fx.PARENT_PUBLIC, box(), "mum's phone").allowed)
        self.assertTrue(self.a.register_device(PIN, "student", STUDENT_PUBLIC, box(), "laptop").allowed)
        self.parent, self.student = kid_of(fx.PARENT_PUBLIC), kid_of(STUDENT_PUBLIC)

    def sign_in(self, secret, kid):
        nonce = self.a.family.challenge()
        return self.a.sign_in(nonce, kid, sign_bytes(secret, SIGN_IN_CONTEXT + nonce.encode())), nonce

    def test_enrolment_needs_the_parent_pin(self):
        d = self.a.register_device("0000", "student", OTHER_PUBLIC, box())
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "bad_pin")
        with self.assertRaises(FamilyError):
            self.a.register_device(PIN, "admin", OTHER_PUBLIC, box())
        with self.assertRaises(FamilyError):
            self.a.register_device(PIN, "student", OTHER_PUBLIC, "not-a-key")

    def test_only_parent_devices_can_sign_approvals(self):
        self.assertIn(self.parent, self.a.policy.parent_keys)
        self.assertNotIn(self.student, self.a.policy.parent_keys)

    def test_sign_in_gives_each_device_its_own_role(self):
        s, _ = self.sign_in(fx.PARENT_SECRET, self.parent)
        self.assertEqual((s["role"], s["signed_in"], s["device"]), ("parent", "parent", self.parent))
        s, _ = self.sign_in(STUDENT_SECRET, self.student)
        self.assertEqual((s["role"], s["device"]), ("student", self.student))

    def test_challenge_works_once_and_expires(self):
        s, nonce = self.sign_in(fx.PARENT_SECRET, self.parent)
        with self.assertRaises(PermissionError):  # replaying the same signed challenge
            self.a.sign_in(nonce, self.parent, sign_bytes(fx.PARENT_SECRET, SIGN_IN_CONTEXT + nonce.encode()))
        nonce = self.a.family.challenge()
        self.now[0] += 121
        with self.assertRaises(PermissionError):
            self.a.sign_in(nonce, self.parent, sign_bytes(fx.PARENT_SECRET, SIGN_IN_CONTEXT + nonce.encode()))

    def test_wrong_key_or_unenrolled_device_cannot_sign_in(self):
        nonce = self.a.family.challenge()
        with self.assertRaises(PermissionError):  # student's key claiming to be the parent device
            self.a.sign_in(nonce, self.parent, sign_bytes(STUDENT_SECRET, SIGN_IN_CONTEXT + nonce.encode()))
        nonce = self.a.family.challenge()
        with self.assertRaises(PermissionError):
            self.a.sign_in(nonce, "ed25519:0000000000000000", sign_bytes(OTHER_SECRET, SIGN_IN_CONTEXT + nonce.encode()))
        nonce = self.a.family.challenge()
        with self.assertRaises(PermissionError):  # signature without the sign-in context prefix
            self.a.sign_in(nonce, self.parent, sign_bytes(fx.PARENT_SECRET, nonce.encode()))
        self.assertIn("sign_in_refused", [e["event"] for e in self.a.audit.entries])

    def test_student_session_cannot_become_parent(self):
        s, _ = self.sign_in(STUDENT_SECRET, self.student)
        with self.assertRaises(PermissionError):
            self.a.set_role(s["id"], "parent")
        guest = self.a.new_session("student")
        with self.assertRaises(PermissionError):
            self.a.set_role(guest["id"], "parent")

    def test_vault_shares_only_with_listed_devices(self):
        p, _ = self.sign_in(fx.PARENT_SECRET, self.parent)
        st, _ = self.sign_in(STUDENT_SECRET, self.student)
        private = self.a.vault_put(p["id"], sealed([self.parent]))
        shared = self.a.vault_put(p["id"], sealed([self.parent, self.student]))
        self.assertEqual(shared["shared_with"], ["parent", "student"])
        self.assertNotIn("ciphertext", shared)
        self.assertEqual({d["doc_id"] for d in self.a.vault_list(st["id"])}, {shared["doc_id"]})
        with self.assertRaises(PermissionError):
            self.a.vault_get(st["id"], private["doc_id"])
        got = self.a.vault_get(st["id"], shared["doc_id"])
        self.assertEqual(set(got["wrapped_key"]), {"iv", "key"})  # only this device's wrapped key comes back
        self.assertEqual(self.a.family.docs[shared["doc_id"]]["wrapped"][self.student], got["wrapped_key"])

    def test_vault_refuses_bad_uploads(self):
        p, _ = self.sign_in(fx.PARENT_SECRET, self.parent)
        st, _ = self.sign_in(STUDENT_SECRET, self.student)
        self.assertTrue(self.a.register_device(PIN, "student", OTHER_PUBLIC, box()).allowed)
        other = kid_of(OTHER_PUBLIC)
        cases = [(p, sealed([self.student])),                                     # uploader left out
                 (p, sealed([self.parent, "ed25519:ffffffffffffffff"])),          # not an enrolled device
                 (st, sealed([self.student, other])),                             # student to another student
                 (p, sealed([self.parent], size=2 * 1024 * 1024 + 1)),            # over 2 MB
                 (p, {**sealed([self.parent]), "iv": b64e(b"short")})]           # malformed nonce
        for i, (s, doc) in enumerate(cases):
            with self.subTest(case=i), self.assertRaises(FamilyError):
                self.a.vault_put(s["id"], doc)
        with self.assertRaises(PermissionError):  # a session made without sign-in has no device
            self.a.vault_put(self.a.new_session("parent")["id"], sealed([self.parent]))


if __name__ == "__main__":
    unittest.main()
