"""Hidden-markup explainer: the cost inside the exchange rate, against a named mid-market reference."""
import json
import unittest
from decimal import Decimal as D
from pathlib import Path

from rules import RulePack, Route, landed_cost
from rules.explain import explain_markup
from tests.test_route_lines import compare_quotes  # pinned to a time the sample quotes are valid

PACK = RulePack.load()
SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
INVOICE = json.loads((SAMPLES / "invoice.json").read_text(encoding="utf-8"))
QUOTES = [json.loads((SAMPLES / f"quote_{x}.json").read_text(encoding="utf-8")) for x in "abc"]
MID = D("90.00")


class TestMarkupPerRoute(unittest.TestCase):
    def setUp(self):
        self.r = compare_quotes(PACK, INVOICE, QUOTES, mid_market_rate=MID, mid_source="test reference")
        self.rate = {q["route_name"]: D(q["fx_rate"]) for q in QUOTES}

    def test_markup_is_rate_gap_times_amount(self):
        for x in self.r["routes"]:
            expected = ((self.rate[x["route"]] - MID) * 20000).quantize(D("0.01"))
            self.assertEqual(D(x["markup"]["amount_inr"]), expected)

    def test_share_of_payment(self):
        a = next(x for x in self.r["routes"] if x["route"] == "Provider A")
        # (90.35 - 90.00) x 20,000 = 7,000 on a mid-market value of 18,00,000 = 0.39%
        self.assertIn("Rs 7,000", a["markup"]["text"])
        self.assertIn("(0.39% of the payment)", a["markup"]["text"])

    def test_source_names_rate_and_reference(self):
        for x in self.r["routes"]:
            self.assertEqual(x["markup"]["source"], "mid-market reference rate 90.00 INR per USD (test reference)")

    def test_says_it_is_not_added_twice(self):
        for x in self.r["routes"]:
            self.assertIn("not added to the total again", x["markup"]["text"])

    def test_total_unchanged_by_markup(self):
        without = compare_quotes(PACK, INVOICE, QUOTES)
        self.assertEqual([x["total_inr"] for x in self.r["routes"]], [x["total_inr"] for x in without["routes"]])

    def test_no_mid_market_rate_gives_none(self):
        for x in compare_quotes(PACK, INVOICE, QUOTES)["routes"]:
            self.assertIsNone(x["markup"])


class TestAtOrBelowMid(unittest.TestCase):
    def test_rate_at_mid_has_no_markup(self):
        r = Route("Fair", MID, fee_inr=D(1000))
        line = explain_markup(landed_cost(PACK, r, 20000, mid_market_rate=MID), r, MID, 20000)
        self.assertIn("no hidden markup", line["text"])
        self.assertEqual(D(line["amount_inr"]), 0)
        self.assertEqual(line["source"], "mid-market reference rate 90.00 INR per USD (synthetic sandbox reference)")

    def test_rate_below_mid_is_not_a_cost(self):
        r = Route("Generous", D("89.90"))
        line = explain_markup(landed_cost(PACK, r, 20000, mid_market_rate=MID), r, MID, 20000)
        self.assertIn("no hidden markup", line["text"])
        self.assertLess(D(line["amount_inr"]), 0)


if __name__ == "__main__":
    unittest.main()
