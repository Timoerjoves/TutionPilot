"""Attack test set: 8 cases across prompt injection, induced transfer, privilege escalation and data extraction.
Plan v2 item 17. AT1, AT3, AT5, AT6, AT7, AT8 are scenarios C1, C2, C3, D1, C4, C5 on the team sheet.
These test Chandan's layer (scanner, payee check, masking, grounding). The policy engine (Nishanth)
must also deny these actions on its own; the scanner is a first line, not the only one.
"""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from contract import tcs_result
from rules import RulePack, compute_tcs
from scenarios import fixtures as fx
from security import (Masker, ModelSawLog, ground_or_replace, payee_mismatch, prepare_for_model, scan)

PACK = RulePack.load()


def categories(result):
    return {f["category"] for f in result["findings"]}


class TestPromptInjection(unittest.TestCase):
    def test_AT1_C1_invoice_says_ignore_rules_and_approve(self):
        r = scan(fx.INJECTED_INVOICE_TEXT)
        self.assertEqual(r["action"], "block")
        self.assertTrue({"prompt_injection", "auto_approve"} <= categories(r))

    def test_AT2_disguised_injection_zero_width_and_spacing(self):
        r = scan(fx.DISGUISED_INJECTION)
        self.assertEqual(r["action"], "block")
        self.assertIn("prompt_injection", categories(r))


class TestInducedTransfer(unittest.TestCase):
    def test_AT3_C2_invoice_with_changed_bank_account(self):
        mismatch = payee_mismatch(fx.tampered_invoice(), fx.REGISTRY["PAYEE-US-0007"])
        self.assertEqual(mismatch, ["bank.account_masked", "bank.swift"])
        self.assertEqual(payee_mismatch(fx.invoice(), fx.REGISTRY["PAYEE-US-0007"]), [])

    def test_AT4_email_urges_payment_to_new_account(self):
        r = scan(fx.BANK_CHANGE_TEXT)
        self.assertEqual(r["action"], "block")
        self.assertTrue({"payee_change", "pressure"} <= categories(r))

    def test_unknown_payee_is_a_mismatch(self):
        self.assertEqual(payee_mismatch(fx.invoice(), None), ["registry_id"])


class TestDataExtraction(unittest.TestCase):
    def test_AT5_C3_asks_for_another_persons_pan(self):
        r = scan(fx.OTHER_PAN_REQUEST)
        self.assertEqual(r["action"], "block")
        self.assertIn("data_extraction", categories(r))

    def test_AT6_D1_identifiers_never_reach_the_model_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = ModelSawLog(Path(d) / "model_saw.log")
            prepare_for_model(Masker(), log, "intake",
                              f"Remitter PAN {fx.SYN_PAN}, student passport {fx.SYN_PASSPORT}, "
                              f"Aadhaar {fx.SYN_AADHAAR}, account {fx.SYN_ACCOUNT}")
            saved = log.path.read_text(encoding="utf-8")
        for raw in (fx.SYN_PAN, fx.SYN_PASSPORT, fx.SYN_AADHAAR, fx.SYN_ACCOUNT):
            self.assertNotIn(raw, saved)


class TestPrivilegeEscalation(unittest.TestCase):
    def test_AT7_C4_admin_claim_to_skip_approval(self):
        r = scan(fx.ADMIN_CLAIM)
        self.assertEqual(r["action"], "block")
        self.assertTrue({"privilege_escalation", "auto_approve"} <= categories(r))

    def test_limit_raise_request_flagged(self):
        self.assertIn("privilege_escalation", categories(scan(fx.LIMIT_RAISE)))


class TestModelOutput(unittest.TestCase):
    def test_AT8_C5_model_states_wrong_tcs(self):
        results = [tcs_result(PACK, compute_tcs(PACK, D(1500000)), D(1500000))]
        r = ground_or_replace("Your TCS will be Rs 75,000 (5%).", results, "TCS at 2% on Rs 5,00,000: Rs 10,000.")
        self.assertEqual(r["source"], "engine")
        self.assertIn("Rs 10,000", r["shown"])


if __name__ == "__main__":
    unittest.main()
