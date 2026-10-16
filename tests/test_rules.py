"""Tests for the rules engine. Test names match scenario IDs on the Scenarios tab of the team sheet.
Run from the repo root:  python -m unittest discover -s tests -t . -v
"""
import unittest
from datetime import date
from decimal import Decimal as D

from rules import (RulePack, YTDTracker, Route, compute_tcs, lrs_headroom, landed_cost,
                   compare_routes, financial_year)

LAKH = D(100000)
PACK = RulePack.load()


class TestRulePack(unittest.TestCase):
    def test_every_rule_has_source_status_and_note(self):
        for rule_id, r in PACK.rules.items():
            with self.subTest(rule=rule_id):
                self.assertTrue(r["source"])
                self.assertIn(r["status"], ("secondary-source", "unverified"))
                self.assertTrue(r["check_against"])
                self.assertTrue(r["note"])

    def test_pack_has_version(self):
        self.assertTrue(PACK.version)


class TestTcs(unittest.TestCase):
    def test_A1_self_funded_8_lakh_no_prior_is_nil(self):
        self.assertEqual(compute_tcs(PACK, 8 * LAKH).tcs, 0)

    def test_A2_self_funded_15_lakh_no_prior(self):
        r = compute_tcs(PACK, 15 * LAKH)
        self.assertEqual(r.tcs, 10000)
        self.assertEqual(r.taxable_base, 5 * LAKH)

    def test_A3_loan_funded_15_lakh_is_nil(self):
        self.assertEqual(compute_tcs(PACK, 15 * LAKH, funding="loan").tcs, 0)

    def test_A4_prior_6_lakh_plus_7_lakh(self):
        r = compute_tcs(PACK, 7 * LAKH, prior_lrs_inr=6 * LAKH)
        self.assertEqual(r.tcs, 6000)
        self.assertEqual(r.taxable_base, 3 * LAKH)

    def test_A5_prior_other_purposes_12_lakh_plus_5_lakh(self):
        r = compute_tcs(PACK, 5 * LAKH, prior_lrs_inr=12 * LAKH, prior_includes_other_purposes=True)
        self.assertEqual(r.tcs, 10000)
        self.assertIn("tcs_prior_other_purposes_count_toward_threshold", r.needs_verification)

    def test_A6_no_pan_uses_no_pan_rate_and_is_flagged(self):
        r = compute_tcs(PACK, 15 * LAKH, has_pan=False)
        self.assertEqual(r.tcs, 25000)
        self.assertIn("tcs_rate_no_pan", r.needs_verification)

    def test_exactly_at_threshold_is_nil(self):
        self.assertEqual(compute_tcs(PACK, 10 * LAKH).tcs, 0)

    def test_one_rupee_over_threshold(self):
        r = compute_tcs(PACK, 10 * LAKH + 1)
        self.assertEqual(r.taxable_base, 1)
        self.assertEqual(r.tcs, 0)  # 2% of Rs 1 rounds to Rs 0

    def test_prior_already_above_threshold_taxes_whole_amount(self):
        self.assertEqual(compute_tcs(PACK, 5 * LAKH, prior_lrs_inr=20 * LAKH).tcs, 10000)

    def test_trace_lists_rules_used_with_pack_version(self):
        r = compute_tcs(PACK, 15 * LAKH, prior_lrs_inr=2 * LAKH)
        ids = {t["rule_id"] for t in r.trace}
        self.assertIn("tcs_threshold_inr", ids)
        self.assertIn("tcs_rate_education_self_funded", ids)
        self.assertIn("tcs_threshold_aggregates_all_purposes", ids)
        self.assertTrue(all(t["pack_version"] == PACK.version for t in r.trace))

    def test_invalid_funding_rejected(self):
        with self.assertRaises(ValueError):
            compute_tcs(PACK, LAKH, funding="gift")

    def test_date_before_2pc_rate_is_refused(self):
        with self.assertRaises(ValueError):
            compute_tcs(PACK, 15 * LAKH, on=date(2026, 3, 31))

    def test_date_on_or_after_effective_is_allowed(self):
        self.assertEqual(compute_tcs(PACK, 15 * LAKH, on=date(2026, 4, 1)).tcs, 10000)

    def test_tcs_rules_cite_2025_act(self):
        for rid in ("tcs_threshold_inr", "tcs_rate_education_self_funded", "tcs_rate_education_loan_funded"):
            self.assertIn("s.394", PACK.rules[rid]["check_against"])

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            compute_tcs(PACK, -1)


class TestLrsCap(unittest.TestCase):
    def test_A7_payment_over_cap_is_flagged(self):
        r = lrs_headroom(PACK, prior_usd=240000, amount_usd=20000)
        self.assertFalse(r.within_cap)
        self.assertEqual(r.headroom_before_usd, 10000)
        self.assertEqual(r.headroom_after_usd, -10000)

    def test_payment_exactly_at_cap_is_allowed(self):
        self.assertTrue(lrs_headroom(PACK, prior_usd=230000, amount_usd=20000).within_cap)

    def test_cap_rule_is_marked_unverified(self):
        self.assertIn("lrs_annual_cap_usd", lrs_headroom(PACK, 0, 1000).needs_verification)

    def test_negative_usd_rejected(self):
        with self.assertRaises(ValueError):
            lrs_headroom(PACK, prior_usd=-1, amount_usd=1000)
        with self.assertRaises(ValueError):
            lrs_headroom(PACK, prior_usd=0, amount_usd=-1000)


class TestYearToDate(unittest.TestCase):
    def test_financial_year_boundaries(self):
        self.assertEqual(financial_year(date(2026, 3, 31)), "2025-26")
        self.assertEqual(financial_year(date(2026, 4, 1)), "2026-27")
        self.assertEqual(financial_year(date(2026, 10, 16)), "2026-27")

    def test_usage_sums_all_purposes_in_same_year_only(self):
        t = YTDTracker()
        t.add(date(2026, 3, 30), "travel", 3 * LAKH, 3500)       # previous year, ignored
        t.add(date(2026, 5, 10), "travel", 4 * LAKH, 4700)
        t.add(date(2026, 8, 1), "education", 2 * LAKH, 2300)
        u = t.usage(date(2026, 10, 16))
        self.assertEqual(u["financial_year"], "2026-27")
        self.assertEqual(u["inr"], 6 * LAKH)
        self.assertEqual(u["usd"], 7000)
        self.assertEqual(u["other_purposes_inr"], 4 * LAKH)

    def test_usage_ignores_future_entries(self):
        t = YTDTracker()
        t.add(date(2026, 12, 1), "travel", LAKH, 1200)
        self.assertEqual(t.usage(date(2026, 10, 16))["inr"], 0)

    def test_tracker_feeds_tcs(self):
        t = YTDTracker()
        t.add(date(2026, 5, 10), "travel", 6 * LAKH, 7000)
        prior = t.usage(date(2026, 10, 16))["inr"]
        self.assertEqual(compute_tcs(PACK, 7 * LAKH, prior_lrs_inr=prior).tcs, 6000)


class TestLandedCost(unittest.TestCase):
    A = Route("Provider A", D("90.50"), fee_inr=D(1500))
    B = Route("Provider B", D("90.20"), fee_inr=D(3000))

    def test_A8_two_routes_ranked_by_total(self):
        ranked = compare_routes(PACK, [self.A, self.B], 20000)
        self.assertEqual(ranked[0]["cost"].route, "Provider B")
        self.assertEqual(ranked[0]["cost"].total_inr, D("1823080"))
        self.assertEqual(ranked[1]["cost"].total_inr, D("1827700"))
        self.assertEqual(ranked[0]["saving_vs_next_inr"], D("4620"))

    def test_components_for_provider_a(self):
        c = landed_cost(PACK, self.A, 20000)
        self.assertEqual(c.remitted_inr, D("1810000"))
        self.assertEqual(c.tcs.tcs, 16200)
        self.assertEqual(c.fee_inr, 1500)
        self.assertEqual(c.total_inr, D("1827700"))

    def test_markup_versus_mid_market(self):
        c = landed_cost(PACK, self.A, 20000, mid_market_rate=D("90.00"))
        self.assertEqual(c.markup_inr, D("10000"))  # (90.50 - 90.00) x 20,000

    def test_no_mid_market_rate_gives_no_markup(self):
        self.assertIsNone(landed_cost(PACK, self.A, 20000).markup_inr)

    def test_gst_on_fee_added_and_flagged(self):
        r = Route("With GST", D("90.00"), fee_inr=D(1000), gst_rate=D("0.18"))
        c = landed_cost(PACK, r, 10000)
        self.assertEqual(c.gst_inr, D("180"))
        self.assertEqual(c.total_inr, D("900000") + D(1000) + D(180) + c.tcs.tcs)
        self.assertIn("gst_on_service_charge", c.needs_verification)

    def test_loan_funded_route_has_no_tcs(self):
        c = landed_cost(PACK, self.A, 20000, funding="loan")
        self.assertEqual(c.tcs.tcs, 0)
        self.assertEqual(c.total_inr, D("1811500"))

    def test_route_comparison_refuses_date_before_rules(self):
        with self.assertRaises(ValueError):
            compare_routes(PACK, [self.A, self.B], 20000, on=date(2026, 3, 31))
        self.assertEqual(len(compare_routes(PACK, [self.A, self.B], 20000, on=date(2026, 10, 16))), 2)

    def test_prior_usage_raises_tcs_on_route(self):
        c = landed_cost(PACK, self.A, 20000, prior_lrs_inr=6 * LAKH)
        self.assertEqual(c.tcs.tcs, 28200)  # taxable = 6,00,000 + 18,10,000 - 10,00,000 = 14,10,000; 2% = 28,200


if __name__ == "__main__":
    unittest.main()
