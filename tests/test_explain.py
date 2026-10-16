"""Explanations: every line's amount matches the engine, wording is deterministic, rule trace attached."""
import unittest
from decimal import Decimal as D

from rules import RulePack, Route, compare_routes, compute_tcs, landed_cost
from rules.explain import explain_comparison, explain_landed_cost, explain_markup, inr, tcs_sentence

PACK = RulePack.load()
LAKH = D(100000)
A = Route("Provider A", D("90.50"), fee_inr=D(1500))
B = Route("Provider B", D("90.20"), fee_inr=D(3000))


class TestFormatting(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(inr(D("1823080")), "Rs 18,23,080")
        self.assertEqual(inr(D("1000")), "Rs 1,000")
        self.assertEqual(inr(D("500")), "Rs 500")
        self.assertEqual(inr(D("1234.5")), "Rs 1,234.50")
        self.assertEqual(inr(D("-4620")), "-Rs 4,620")


class TestLandedCostLines(unittest.TestCase):
    def test_lines_add_up_to_total(self):
        c = landed_cost(PACK, A, 20000)
        lines = explain_landed_cost(c, A, 20000)
        parts = sum(D(l["amount_inr"]) for l in lines if l["label"] != "Total")
        self.assertEqual(parts, c.total_inr)
        self.assertEqual(lines[-1]["amount_inr"], "1827700.00")

    def test_tcs_line_carries_rule_trace_and_unverified_flags(self):
        c = landed_cost(PACK, A, 20000)
        tcs_line = next(l for l in explain_landed_cost(c, A, 20000) if l["label"] == "TCS")
        self.assertIn("tcs_rate_education_self_funded", tcs_line["rules"])
        self.assertIn("tcs_base_excludes_fees", tcs_line["unverified"])

    def test_gst_line_only_when_charged(self):
        r = Route("With GST", D("90.00"), fee_inr=D(1000), gst_rate=D("0.18"))
        lines = explain_landed_cost(landed_cost(PACK, r, 10000), r, 10000)
        gst = next(l for l in lines if l["label"] == "GST on fee")
        self.assertEqual(gst["amount_inr"], "180.00")
        self.assertIn("18%", gst["text"])
        self.assertNotIn("GST on fee", [l["label"] for l in explain_landed_cost(landed_cost(PACK, A, 20000), A, 20000)])


class TestTcsSentence(unittest.TestCase):
    def test_under_threshold(self):
        self.assertIn("within the Rs 10,00,000 threshold", tcs_sentence(compute_tcs(PACK, 8 * LAKH)))

    def test_partly_over(self):
        s = tcs_sentence(compute_tcs(PACK, 15 * LAKH))
        self.assertIn("TCS at 2% on Rs 5,00,000", s)
        self.assertIn("above Rs 10,00,000", s)

    def test_prior_used_threshold(self):
        self.assertIn("already used up the threshold", tcs_sentence(compute_tcs(PACK, 5 * LAKH, prior_lrs_inr=12 * LAKH)))

    def test_loan(self):
        self.assertIn("0%", tcs_sentence(compute_tcs(PACK, 15 * LAKH, funding="loan")))


class TestComparison(unittest.TestCase):
    def test_summary_and_why_match_engine(self):
        ranked = compare_routes(PACK, [A, B], 20000)
        e = explain_comparison(ranked, [A, B], 20000)
        self.assertEqual(e["summary"],
                         "Cheapest: Provider B at Rs 18,23,080, Rs 4,620 less than Provider A (Rs 18,27,700).")
        net = sum(D(l["amount_inr"]) for l in e["why"])
        self.assertEqual(net, ranked[0]["saving_vs_next_inr"])  # the reasons add up to the saving
        labels = {l["label"] for l in e["why"]}
        self.assertEqual(labels, {"Exchange rate", "Provider fee", "TCS"})

    def test_single_route(self):
        e = explain_comparison(compare_routes(PACK, [A], 20000), [A], 20000)
        self.assertTrue(e["summary"].startswith("Only one route"))


class TestMarkup(unittest.TestCase):
    def test_markup_explained(self):
        c = landed_cost(PACK, A, 20000, mid_market_rate=D("90.00"))
        line = explain_markup(c, A, D("90.00"), 20000)
        self.assertEqual(line["amount_inr"], "10000.00")
        self.assertIn("Rs 10,000", line["text"])
        self.assertIn("0.56%", line["text"])  # 10,000 / (90.00 x 20,000)

    def test_no_markup_when_rate_at_or_below_mid(self):
        c = landed_cost(PACK, A, 20000, mid_market_rate=D("90.50"))
        self.assertIn("no hidden markup", explain_markup(c, A, D("90.50"), 20000)["text"])

    def test_none_without_mid_market(self):
        self.assertIsNone(explain_markup(landed_cost(PACK, A, 20000), A, None, 20000))


if __name__ == "__main__":
    unittest.main()
