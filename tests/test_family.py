"""Device enrolment, passwordless sign-in, locked roles and the encrypted vault (server side)."""
import os
import unittest

from agent.agent import CONFIG, Agent
from app.family import ENROL_CONTEXT, SIGN_IN_CONTEXT, FamilyError, enrolment_bytes
from contract import canonical_json
from scenarios import fixtures as fx
from security import ed25519
from security.pki import b64d, b64e, demo_secret, key_id, sign_bytes

PIN = CONFIG["demo_pin"]
STUDENT_SECRET = demo_secret("student-device")
STUDENT_PUBLIC = b64e(ed25519.public_key(STUDENT_SECRET))
OTHER_SECRET = demo_secret("second-student-device")
OTHER_PUBLIC = b64e(ed25519.public_key(OTHER_SECRET))


def box():
    return b64e(os.urandom(32))  # stands in for an X25519 public key: the server never uses it to encrypt


def key_of(public):
    return key_id(b64d(public))


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
        self.parent = kid_of(fx.PARENT_PUBLIC)
        self.assertTrue(self.enrol("student", STUDENT_PUBLIC, "laptop").allowed)
        self.student = kid_of(STUDENT_PUBLIC)

    def enrol(self, role, public, label="", pin=PIN):
        """A later device: request a code, the enrolled parent device signs it, the new device finishes with the PIN."""
        code = self.a.request_device(role, public, box(), label)
        req = self.a.family.enrolment_request(code)
        self.a.family.approve_enrolment(code, self.parent, sign_bytes(fx.PARENT_SECRET, enrolment_bytes(req)))
        return self.a.register_device(pin, None, None, None, code=code)

    def sign_in(self, secret, kid):
        nonce = self.a.family.challenge()
        return self.a.sign_in(nonce, kid, sign_bytes(secret, SIGN_IN_CONTEXT + nonce.encode())), nonce

    def test_enrolment_needs_the_parent_pin(self):
        d = self.enrol("student", OTHER_PUBLIC, pin="0000")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "bad_pin")
        with self.assertRaises(FamilyError):
            self.a.register_device(PIN, "admin", OTHER_PUBLIC, box())
        with self.assertRaises(FamilyError):
            self.a.register_device(PIN, "student", OTHER_PUBLIC, "not-a-key")

    def test_only_the_first_parent_device_enrols_with_the_pin_alone(self):
        fresh = Agent()
        self.assertEqual(fresh.register_device(PIN, "student", STUDENT_PUBLIC, box()).code, "no_parent")
        self.assertTrue(fresh.register_device(PIN, "parent", fx.PARENT_PUBLIC, box()).allowed)  # bootstrap
        for role, public in [("parent", OTHER_PUBLIC), ("student", OTHER_PUBLIC)]:
            d = fresh.register_device(PIN, role, public, box())  # right PIN, no parent signature
            self.assertEqual((d.allowed, d.code), (False, "stale_request"))
        self.assertNotIn(key_of(OTHER_PUBLIC), fresh.policy.parent_keys)

    def test_later_device_needs_a_parent_signature(self):
        code = self.a.request_device("parent", OTHER_PUBLIC, box(), "attacker")
        d = self.a.register_device(PIN, None, None, None, code=code)  # PIN but nobody approved it
        self.assertEqual((d.allowed, d.code), (False, "needs_parent_signature"))
        req = self.a.family.enrolment_request(code)
        bad = [(self.student, sign_bytes(STUDENT_SECRET, enrolment_bytes(req))),               # a student device
               (self.parent, sign_bytes(fx.PARENT_SECRET, canonical_json(req))),               # no enrol prefix
               (self.parent, sign_bytes(fx.PARENT_SECRET, SIGN_IN_CONTEXT + req["nonce"].encode())),  # a sign-in
               (self.parent, sign_bytes(fx.PARENT_SECRET, enrolment_bytes({**req, "role": "student"})))]
        for i, (kid, sig) in enumerate(bad):
            with self.subTest(case=i), self.assertRaises(PermissionError):
                self.a.family.approve_enrolment(code, kid, sig)
            d = self.a.family.register(PIN, "parent", OTHER_PUBLIC, req["box_key"], req["label"], req["nonce"], kid, sig)
            self.assertEqual(d.code, "needs_parent_signature")
        self.assertNotIn(key_of(OTHER_PUBLIC), self.a.policy.parent_keys)
        self.assertTrue(self.a.policy.frozen)  # forged enrolments count toward the circuit breaker
        self.a.settings(PIN, reset_breaker=True)
        self.a.family.approve_enrolment(code, self.parent, sign_bytes(fx.PARENT_SECRET, enrolment_bytes(req)))
        self.assertTrue(self.a.register_device(PIN, None, None, None, code=code).allowed)
        self.assertIn(key_of(OTHER_PUBLIC), self.a.policy.parent_keys)
        self.assertNotEqual(ENROL_CONTEXT, SIGN_IN_CONTEXT)

    def test_enrolment_request_works_once_and_expires(self):
        code = self.a.request_device("student", OTHER_PUBLIC, box(), "tablet")
        req = self.a.family.enrolment_request(code)
        sig = sign_bytes(fx.PARENT_SECRET, enrolment_bytes(req))
        self.a.family.approve_enrolment(code, self.parent, sig)
        self.assertTrue(self.a.register_device(PIN, None, None, None, code=code).allowed)
        replay = self.a.family.register(PIN, "student", OTHER_PUBLIC, req["box_key"], req["label"], req["nonce"],
                                        self.parent, sig)
        self.assertEqual(replay.code, "stale_request")
        with self.assertRaises(KeyError):
            self.a.register_device(PIN, None, None, None, code=code)
        code = self.a.request_device("parent", OTHER_PUBLIC, box(), "late")
        req = self.a.family.enrolment_request(code)
        self.now[0] += 601
        with self.assertRaises(KeyError):
            self.a.family.approve_enrolment(code, self.parent, sign_bytes(fx.PARENT_SECRET, enrolment_bytes(req)))
        d = self.a.family.register(PIN, "parent", OTHER_PUBLIC, req["box_key"], req["label"], req["nonce"],
                                   self.parent, sign_bytes(fx.PARENT_SECRET, enrolment_bytes(req)))
        self.assertEqual(d.code, "stale_request")

    def test_frozen_breaker_refuses_the_pin(self):
        for _ in range(self.a.policy.breaker_threshold):
            self.a.settings("0000")
        self.assertTrue(self.a.policy.frozen)
        self.assertEqual(self.enrol("student", OTHER_PUBLIC).code, "circuit_breaker")  # right PIN, signed, frozen
        self.assertEqual(self.a.policy.register_parent_key(PIN, OTHER_PUBLIC).code, "circuit_breaker")
        self.assertFalse(self.a.policy.verify_pin(PIN))
        self.assertEqual(self.a.settings(PIN, per_payment_cap_usd="99999").code, "circuit_breaker")
        self.assertTrue(self.a.settings(PIN, reset_breaker=True).allowed)  # the one PIN check allowed while frozen
        self.assertFalse(self.a.policy.frozen)
        self.assertTrue(self.enrol("student", OTHER_PUBLIC).allowed)

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
        self.assertTrue(self.enrol("student", OTHER_PUBLIC).allowed)
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
