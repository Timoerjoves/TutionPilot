"""Ed25519 against RFC 8032 and the browser, the university trust chain, and parent-signed approvals."""
import copy
import unittest
from datetime import date
from pathlib import Path

from contract import ContractError, validate
from scenarios import fixtures as fx
from security import ed25519
from security.pki import (TrustStore, b64e, demo_secret, embed, issue_certificate, key_id, sign_invoice, split,
                          verify_approval)

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 17)


def sample(name):
    return split((ROOT / "data" / "invoices" / f"{name}.txt").read_text(encoding="utf-8"))[1]


class TestEd25519(unittest.TestCase):
    # RFC 8032 section 7.1, tests 1 and 2
    VECTORS = [
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]

    def test_rfc8032_vectors(self):
        for sk, pk, msg, sig in self.VECTORS:
            sk, pk, msg, sig = (bytes.fromhex(x) for x in (sk, pk, msg, sig))
            self.assertEqual(ed25519.public_key(sk), pk)
            self.assertEqual(ed25519.sign(sk, msg), sig)
            self.assertTrue(ed25519.verify(pk, msg, sig))

    def test_signature_made_by_browser_webcrypto(self):
        pub = bytes.fromhex("3c33118f0d46fa9cad6ca4e0e0e7eac7314ff15e46e7a120f85b79895ce2319a")
        sig = bytes.fromhex("de09929a8b678f0257ef11f7d61ae072743760dbab91b36fb47b9f98e2c9d005"
                            "dd2c366922b36287b8a7fe6389b29a0c68a74444181517b816f620a667eed700")
        self.assertTrue(ed25519.verify(pub, b"hello", sig))

    def test_any_change_fails(self):
        sk = demo_secret("test")
        pk, sig = ed25519.public_key(sk), ed25519.sign(sk, b"pay Rs 18,23,080")
        self.assertFalse(ed25519.verify(pk, b"pay Rs 18,23,081", sig))
        self.assertFalse(ed25519.verify(pk, b"pay Rs 18,23,080", sig[:-1] + bytes([sig[-1] ^ 1])))
        self.assertFalse(ed25519.verify(ed25519.public_key(demo_secret("other")), b"pay Rs 18,23,080", sig))
        self.assertFalse(ed25519.verify(pk, b"x", b"short"))


class TestTrustChain(unittest.TestCase):
    def setUp(self):
        self.t = TrustStore()
        self.good = sample("valid_us")

    def test_valid_chain_lists_every_link(self):
        r = self.t.check_invoice(self.good, TODAY)
        self.assertTrue(r["verified"])
        self.assertEqual([c["step"] for c in r["chain"]],
                         ["Trust root", "University certificate", "Invoice signature", "Payee and bank match certificate"])
        self.assertTrue(all(c["ok"] for c in r["chain"]))

    def test_any_edit_to_a_signed_invoice_breaks_it(self):
        for path, value in [(("amount", "value"), "20001.00"), (("due_on",), "2026-12-31"),
                            (("payee", "bank", "swift"), "NEWBUS44"), (("student", "name"), "Someone Else")]:
            with self.subTest(field=".".join(path)):
                inv = copy.deepcopy(self.good)
                target = inv
                for k in path[:-1]:
                    target = target[k]
                target[path[-1]] = value
                self.assertFalse(self.t.check_invoice(inv, TODAY)["verified"])

    def test_university_cannot_certify_itself_a_new_bank_account(self):
        # a genuinely signed invoice whose bank details differ from the certificate
        inv = copy.deepcopy({k: v for k, v in self.good.items() if k != "attestation"})
        inv["payee"]["bank"]["account_masked"] = "XXXX-XXXX-0000"
        resigned = sign_invoice(demo_secret("university:northbridge"), self.good["attestation"]["certificate"], inv)
        r = self.t.check_invoice(resigned, TODAY)
        self.assertFalse(r["verified"])
        self.assertEqual(r["mismatch"], ["bank.account_masked"])

    def test_certificate_dates_and_forged_issuer(self):
        self.assertFalse(self.t.check_invoice(self.good, date(2028, 1, 1))["verified"])
        cert = copy.deepcopy(self.good["attestation"]["certificate"])
        cert["certificate"]["subject"]["bank"]["swift"] = "NEWBUS44"  # edit the root-signed certificate
        ok, why, _ = self.t.check_certificate(cert, TODAY)
        self.assertFalse(ok)
        self.assertIn("not issued", why)

    def test_unknown_root_rejected(self):
        other_root = demo_secret("another-root")
        subj = self.good["attestation"]["certificate"]["certificate"]["subject"]
        cert = issue_certificate(other_root, "X", subj, ed25519.public_key(demo_secret("u")), "2026-01-01", "2027-12-31")
        self.assertFalse(self.t.check_certificate(cert, TODAY)[0])

    def test_embed_and_split_round_trip(self):
        visible, signed, err = split(embed("Invoice text", self.good))
        self.assertEqual((visible, signed, err), ("Invoice text", self.good, None))
        self.assertIsNotNone(split(embed("x", self.good).replace("A", "?", 3))[2])


class TestSignedApprovals(unittest.TestCase):
    def setUp(self):
        self.plan = fx.load_sample("plan")
        self.keys = {key_id(ed25519.public_key(fx.PARENT_SECRET)): fx.PARENT_PUBLIC}

    def test_parent_signed_approval_verifies_and_is_valid_contract(self):
        a = fx.parent_approval(self.plan)
        validate(a)
        self.assertTrue(verify_approval(a, self.keys))

    def test_edit_or_other_key_fails(self):
        a = fx.parent_approval(self.plan)
        for field, value in [("plan_hash", "sha256:" + "0" * 64), ("tier", "T1"), ("decision", "rejected")]:
            with self.subTest(field=field):
                self.assertFalse(verify_approval({**a, field: value}, self.keys))
        self.assertFalse(verify_approval(fx.parent_approval(self.plan, secret=demo_secret("agent")), self.keys))
        unsigned = {k: v for k, v in a.items() if k != "signature"}
        self.assertFalse(verify_approval(unsigned, self.keys))

    def test_contract_checks_signature_shape(self):
        bad = {**fx.parent_approval(self.plan), "signature": {"alg": "RSA", "key_id": "x", "value": "y"}}
        with self.assertRaises(ContractError):
            validate(bad)

    def test_samples_are_signed(self):
        self.assertTrue(verify_approval(fx.load_sample("approval"), self.keys))
        self.assertTrue(TrustStore().check_invoice(fx.load_sample("invoice"), TODAY)["verified"])
        self.assertEqual(b64e(ed25519.public_key(fx.PARENT_SECRET)), fx.PARENT_PUBLIC)


if __name__ == "__main__":
    unittest.main()
