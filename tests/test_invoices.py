"""The 5 synthetic test invoices in data/invoices/ behave as manifest.json expects.
Run from the repo root:  python -m unittest discover -s tests -t . -v
"""
import json
import unittest
from decimal import Decimal as D
from pathlib import Path

from contract import ContractError, validate
from rules import RulePack, lrs_headroom

ROOT = Path(__file__).resolve().parent.parent
INV = ROOT / "data" / "invoices"
REGISTRY = json.loads((ROOT / "data" / "registry" / "payees.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((INV / "manifest.json").read_text(encoding="utf-8"))
PACK = RulePack.load()

# Simple USD conversion for the LRS check in tests only (synthetic rate).
USD_PER = {"USD": D("1"), "GBP": D("1.27")}


def load(name):
    return json.loads((INV / f"{name}.json").read_text(encoding="utf-8"))


def payee_verified(inv):
    """Minimal reference check: registry id exists and bank details match exactly."""
    for p in REGISTRY["payees"]:
        if p["registry_id"] == inv["payee"]["registry_id"]:
            return p["verified"] and p["bank"] == inv["payee"]["bank"]
    return False


class TestInvoices(unittest.TestCase):
    def test_five_cases_each_with_pdf_and_json(self):
        self.assertEqual(len(MANIFEST), 5)
        for case in MANIFEST:
            with self.subTest(case=case["file"]):
                self.assertTrue((INV / f"{case['file']}.pdf").exists())
                self.assertTrue((INV / f"{case['file']}.json").exists())

    def test_contract_validity_matches_expectation(self):
        for case in MANIFEST:
            with self.subTest(case=case["file"]):
                inv = load(case["file"])
                if case["expect"]["contract_valid"]:
                    validate(inv)
                else:
                    with self.assertRaises(ContractError) as e:
                        validate(inv)
                    for field in case["expect"]["missing"]:
                        self.assertIn(field, str(e.exception))

    def test_payee_check_matches_expectation(self):
        for case in MANIFEST:
            with self.subTest(case=case["file"]):
                self.assertEqual(payee_verified(load(case["file"])), case["expect"]["payee_verified"])

    def test_lrs_cap_matches_expectation(self):
        for case in MANIFEST:
            with self.subTest(case=case["file"]):
                inv = load(case["file"])
                usd = D(inv["amount"]["value"]) * USD_PER[inv["amount"]["currency"]]
                r = lrs_headroom(PACK, D(case["context"]["prior_lrs_usd"]), usd)
                self.assertEqual(r.within_cap, case["expect"]["within_lrs_cap"])
                if "lrs_headroom_usd" in case["expect"]:
                    self.assertEqual(r.headroom_before_usd, D(case["expect"]["lrs_headroom_usd"]))

    def test_all_data_is_marked_synthetic(self):
        for case in MANIFEST:
            with self.subTest(case=case["file"]):
                inv = load(case["file"])
                self.assertIn("synthetic", inv["payee"]["name"])
                self.assertIn("synthetic", inv["student"]["name"])


if __name__ == "__main__":
    unittest.main()
