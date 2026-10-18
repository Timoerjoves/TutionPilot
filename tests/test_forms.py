"""Corridor config and the A2-style draft with its missing-documents checklist."""
import unittest
from decimal import Decimal as D

import corridors
from forms import build_a2_draft, render_text
from rules import RulePack, Route, landed_cost
from scenarios import fixtures as fx
from security import payee_mismatch

PACK = RulePack.load()
US = corridors.load("IN-US")


class TestCorridors(unittest.TestCase):
    def test_both_corridors_load(self):
        self.assertEqual(corridors.available(), ["IN-AU", "IN-CA", "IN-GB", "IN-US"])
        self.assertEqual(corridors.load("IN-GB")["currency"], "GBP")

    def test_corridors_share_the_india_rule_pack(self):
        for cid in corridors.available():
            self.assertEqual(corridors.load(cid)["rule_pack"], PACK.data["pack_id"])

    def test_for_invoice_picks_destination_and_checks_currency(self):
        self.assertEqual(corridors.for_invoice(fx.invoice())["corridor_id"], "IN-US")
        with self.assertRaises(corridors.CorridorError):
            corridors.for_invoice(fx.invoice(amount={"value": "20000.00", "currency": "EUR"}))

    def test_unknown_corridor_rejected(self):
        with self.assertRaises(corridors.CorridorError):
            corridors.load("IN-XX")

    def test_new_facts_are_marked_unverified(self):
        self.assertEqual(corridors.unverified(US), ["purpose", "student_visa_document"])


class TestA2Draft(unittest.TestCase):
    def draft(self, inv=None, remitter=fx.REMITTER, **kw):
        return build_a2_draft(fx.invoice() if inv is None else inv, remitter, US, **kw)

    def test_A10_complete_invoice_is_ready(self):
        cost = landed_cost(PACK, Route("Provider B", D("90.20"), fee_inr=D(3000)), 20000)
        d = self.draft(landed=cost, documents=fx.ALL_DOCUMENTS)
        self.assertEqual(d["status"], "ready")
        self.assertEqual(d["questions"], [])
        self.assertEqual(d["missing_documents"], [])
        self.assertEqual(d["sections"]["remittance"]["total_debit"], "Rs 18,23,080")
        self.assertEqual(d["sections"]["purpose"]["code"], "S0305")
        self.assertIn("tcs_base_excludes_fees", d["needs_verification"])
        self.assertIn("corridor.purpose", d["needs_verification"])

    def test_A9_missing_due_date_asks_and_does_not_guess(self):
        d = self.draft(inv=fx.invoice(due_on=None))
        self.assertEqual(d["status"], "needs_information")
        self.assertEqual([q["field"] for q in d["questions"]], ["Payment due date"])
        self.assertIsNone(d["sections"]["remittance"]["due_on"])

    def test_A6_missing_pan_asks_for_pan(self):
        d = self.draft(remitter={**fx.REMITTER, "pan": ""})
        self.assertIn("Remitter PAN", [q["field"] for q in d["questions"]])
        self.assertIn("higher rate", d["questions"][0]["question"])

    def test_registry_mismatch_blocks(self):
        inv = fx.tampered_invoice()
        d = self.draft(inv=inv, registry_mismatch=payee_mismatch(inv, fx.REGISTRY["PAYEE-US-0007"]))
        self.assertEqual(d["status"], "blocked")
        self.assertIn("bank.swift", d["blockers"][0])

    def test_checklist_uses_corridor_visa_document_and_loan_letter_only_for_loans(self):
        items = [c["item"] for c in self.draft()["checklist"]]
        self.assertIn("Student visa document: Form I-20 (Certificate of Eligibility for F-1 student status)", items)
        self.assertNotIn("Education loan sanction letter", items)
        gb = build_a2_draft(fx.invoice(), fx.REMITTER, corridors.load("IN-GB"), funding="loan")
        gb_items = [c["item"] for c in gb["checklist"]]
        self.assertIn("Education loan sanction letter", gb_items)
        self.assertTrue(any("CAS" in i for i in gb_items))

    def test_missing_documents_listed(self):
        d = self.draft(documents={"remitter_pan", "fee_invoice"})
        self.assertIn("Student's passport copy", d["missing_documents"])
        self.assertNotIn("Remitter's PAN card copy", d["missing_documents"])

    def test_render_text_shows_labels_questions_and_missing(self):
        text = render_text(self.draft(inv=fx.invoice(due_on=None)))
        self.assertIn("Not tax advice", text)
        self.assertIn("QUESTION (Payment due date)", text)
        self.assertIn("due on: [missing]", text)


if __name__ == "__main__":
    unittest.main()
