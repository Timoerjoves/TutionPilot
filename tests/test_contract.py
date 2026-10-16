"""Contract tests: sample messages are valid, engine output fits the contract, plan hash catches edits.
Run from the repo root:  python -m unittest discover -s tests -t . -v
"""
import copy
import json
import unittest
from decimal import Decimal as D
from pathlib import Path

from contract import (ContractError, plan_hash, validate, tcs_result, lrs_result, landed_cost_result)
from rules import RulePack, compute_tcs, lrs_headroom, landed_cost, Route

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
PACK = RulePack.load()


def load(name):
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


class TestSamples(unittest.TestCase):
    def test_every_sample_is_valid(self):
        files = sorted(SAMPLES.glob("*.json"))
        self.assertGreaterEqual(len(files), 6)
        for f in files:
            with self.subTest(file=f.name):
                validate(json.loads(f.read_text(encoding="utf-8")))

    def test_approval_matches_plan_hash(self):
        self.assertEqual(load("approval")["plan_hash"], load("plan")["plan_hash"])


class TestPlanHash(unittest.TestCase):
    def test_editing_a_step_breaks_the_hash(self):
        plan = load("plan")
        edited = copy.deepcopy(plan)
        edited["steps"][3]["inputs"]["amount"] = "25000.00"
        self.assertNotEqual(plan_hash(edited), plan["plan_hash"])
        with self.assertRaises(ContractError):
            validate(edited)

    def test_hash_ignores_key_order(self):
        plan = load("plan")
        reordered = dict(reversed(list(plan.items())))
        self.assertEqual(plan_hash(reordered), plan["plan_hash"])

    def test_max_tier_must_match_steps(self):
        plan = load("plan")
        plan["max_tier"] = "T1"
        plan["plan_hash"] = plan_hash(plan)
        with self.assertRaises(ContractError):
            validate(plan)


class TestValidation(unittest.TestCase):
    def test_float_money_rejected(self):
        inv = load("invoice")
        inv["amount"]["value"] = 20000.0
        with self.assertRaises(ContractError):
            validate(inv)

    def test_missing_field_rejected(self):
        q = load("quote")
        del q["fx_rate"]
        with self.assertRaisesRegex(ContractError, "fx_rate"):
            validate(q)

    def test_unknown_tier_rejected(self):
        a = load("approval")
        a["tier"] = "T9"
        with self.assertRaises(ContractError):
            validate(a)

    def test_unknown_type_rejected(self):
        with self.assertRaises(ContractError):
            validate({"type": "wire_transfer"})


class TestEngineToContract(unittest.TestCase):
    def test_tcs_result_is_valid(self):
        msg = validate(tcs_result(PACK, compute_tcs(PACK, D(1500000)), D(1500000)))
        self.assertEqual(msg["outputs"]["tcs_inr"], "10000")

    def test_lrs_result_is_valid_and_flags_unverified_cap(self):
        msg = validate(lrs_result(PACK, lrs_headroom(PACK, 240000, 20000), 240000, 20000))
        self.assertFalse(msg["outputs"]["within_cap"])
        self.assertIn("lrs_annual_cap_usd", msg["needs_verification"])

    def test_landed_cost_result_is_valid(self):
        c = landed_cost(PACK, Route("Provider B", D("90.20"), fee_inr=D(3000)), 20000)
        msg = validate(landed_cost_result(PACK, c, 20000))
        self.assertEqual(msg["outputs"]["total_inr"], "1823080.00")

    def test_results_are_json_serialisable(self):
        json.dumps(tcs_result(PACK, compute_tcs(PACK, D(1500000)), D(1500000)))


if __name__ == "__main__":
    unittest.main()
