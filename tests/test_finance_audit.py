"""Finance audit: the engine checked against independent hand calculations and against itself.

Example tests (test_rules.py) check the team-sheet cases. These check properties that must hold for ANY input,
over hundreds of random cases with a fixed seed, so a slip in the formula cannot hide between examples.
No rate or threshold is hard-coded here except through the rule pack.
"""
import random
import unittest
from datetime import date
from decimal import Decimal as D, ROUND_HALF_UP

from rules import RulePack, Route, YTDTracker, compare_routes, compute_tcs, landed_cost, lrs_headroom, financial_year

PACK = RulePack.load()
THRESHOLD = PACK.value("tcs_threshold_inr")
RATE_SELF = PACK.value("tcs_rate_education_self_funded")
RATE_NO_PAN = PACK.value("tcs_rate_no_pan")
CAP = PACK.value("lrs_annual_cap_usd")
RNG = random.Random(20261017)
N = 400


def rand_inr(hi=40_00_000):
    return D(RNG.randint(0, hi * 100)) / 100


def hand_tcs(amount, prior, rate):
    """Independent formula: tax only what crosses or lies above the threshold this year."""
    before_taxable = max(D(0), prior - THRESHOLD)
    after_taxable = max(D(0), prior + amount - THRESHOLD)
    return (after_taxable - before_taxable) * rate


class TestTcsProperties(unittest.TestCase):
    def test_matches_independent_formula(self):
        for _ in range(N):
            amount, prior = rand_inr(), rand_inr()
            for has_pan, rate in ((True, RATE_SELF), (False, RATE_NO_PAN)):
                r = compute_tcs(PACK, amount, prior_lrs_inr=prior, has_pan=has_pan)
                expect = hand_tcs(amount, prior, rate).quantize(D("1"), rounding=ROUND_HALF_UP)
                self.assertEqual(r.tcs, expect, (amount, prior, has_pan))

    def test_splitting_a_payment_never_changes_the_taxable_base(self):
        # paying a then b (with a counted as earlier) must tax exactly what paying a+b at once taxes
        for _ in range(N):
            prior, a, b = rand_inr(), rand_inr(), rand_inr()
            first = compute_tcs(PACK, a, prior_lrs_inr=prior)
            second = compute_tcs(PACK, b, prior_lrs_inr=prior + a)
            together = compute_tcs(PACK, a + b, prior_lrs_inr=prior)
            self.assertEqual(first.taxable_base + second.taxable_base, together.taxable_base)
            self.assertLessEqual(abs(first.tcs + second.tcs - together.tcs), 1)  # each TCS rounds to the rupee

    def test_bounds_and_monotonic(self):
        for _ in range(N):
            amount, prior = rand_inr(), rand_inr()
            r = compute_tcs(PACK, amount, prior_lrs_inr=prior)
            self.assertGreaterEqual(r.taxable_base, 0)
            self.assertLessEqual(r.taxable_base, amount)
            self.assertLessEqual(r.tcs, (amount * RATE_SELF).quantize(D("1"), rounding=ROUND_HALF_UP))
            self.assertLessEqual(r.tcs, compute_tcs(PACK, amount + 1000, prior_lrs_inr=prior).tcs)
            self.assertLessEqual(r.tcs, compute_tcs(PACK, amount, prior_lrs_inr=prior + 1000).tcs)

    def test_loan_funded_is_always_nil(self):
        for _ in range(100):
            self.assertEqual(compute_tcs(PACK, rand_inr(), funding="loan", prior_lrs_inr=rand_inr()).tcs, 0)

    def test_no_pan_never_cheaper_than_pan(self):
        for _ in range(N):
            amount, prior = rand_inr(), rand_inr()
            self.assertGreaterEqual(compute_tcs(PACK, amount, prior_lrs_inr=prior, has_pan=False).tcs,
                                    compute_tcs(PACK, amount, prior_lrs_inr=prior).tcs)


class TestLandedCostProperties(unittest.TestCase):
    def random_route(self, i):
        return Route(f"R{i}", D(RNG.randint(8800, 9300)) / 100, fee_inr=D(RNG.randint(0, 5000)),
                     gst_rate=RNG.choice([D(0), D("0.18")]), correspondent_inr=D(RNG.choice([0, 0, 1250])))

    def test_total_is_exactly_the_sum_of_its_parts(self):
        for i in range(N):
            route, foreign = self.random_route(i), D(RNG.randint(1000, 60000))
            prior = rand_inr()
            c = landed_cost(PACK, route, foreign, prior_lrs_inr=prior)
            self.assertEqual(c.remitted_inr, (foreign * route.rate).quantize(D("0.01")))
            self.assertEqual(c.gst_inr, (route.fee_inr * route.gst_rate).quantize(D("0.01"), rounding=ROUND_HALF_UP))
            self.assertEqual(c.total_inr, c.remitted_inr + c.fee_inr + c.gst_inr + c.correspondent_inr + c.tcs.tcs)
            self.assertEqual(c.tcs.tcs, compute_tcs(PACK, c.remitted_inr, prior_lrs_inr=prior).tcs)

    def test_ranking_is_sorted_and_savings_are_differences(self):
        for i in range(100):
            routes = [self.random_route(10 * i + k) for k in range(RNG.randint(1, 5))]
            ranked = compare_routes(PACK, routes, D(RNG.randint(1000, 60000)))
            totals = [r["cost"].total_inr for r in ranked]
            self.assertEqual(totals, sorted(totals))
            for a, b in zip(ranked, ranked[1:]):
                self.assertEqual(a["saving_vs_next_inr"], b["cost"].total_inr - a["cost"].total_inr)
            self.assertIsNone(ranked[-1]["saving_vs_next_inr"])

    def test_markup_is_rate_gap_times_amount(self):
        for i in range(100):
            route, foreign, mid = self.random_route(i), D(RNG.randint(1000, 60000)), D("90.00")
            c = landed_cost(PACK, route, foreign, mid_market_rate=mid)
            self.assertEqual(c.markup_inr, ((route.rate - mid) * foreign).quantize(D("0.01")))

    def test_sheet_A8_by_hand(self):
        # Provider B: 20,000 x 90.20 = 18,04,000; TCS 2% of (18,04,000 - 10,00,000) = 16,080; + fee 3,000
        b = landed_cost(PACK, Route("B", D("90.20"), fee_inr=D(3000)), 20000)
        self.assertEqual((b.remitted_inr, b.tcs.tcs, b.total_inr), (D("1804000"), 16080, D("1823080")))
        # Provider C (sandbox): 20,000 x 90.35 = 18,07,000; TCS 16,140; fee 999; GST 18% of 999 = 179.82
        c = landed_cost(PACK, Route("C", D("90.35"), fee_inr=D(999), gst_rate=D("0.18")), 20000)
        self.assertEqual((c.tcs.tcs, c.gst_inr, c.total_inr), (16140, D("179.82"), D("1824318.82")))


class TestLrsAndYear(unittest.TestCase):
    def test_headroom_arithmetic(self):
        for _ in range(N):
            prior, amount = D(RNG.randint(0, 300000)), D(RNG.randint(0, 100000))
            r = lrs_headroom(PACK, prior, amount)
            self.assertEqual(r.headroom_before_usd, CAP - prior)
            self.assertEqual(r.headroom_after_usd, CAP - prior - amount)
            self.assertEqual(r.within_cap, prior + amount <= CAP)

    def test_financial_year_every_day_of_two_years(self):
        d = date(2025, 1, 1)
        while d < date(2027, 1, 1):
            start = d.year if d.month >= 4 else d.year - 1
            self.assertEqual(financial_year(d), f"{start}-{str(start + 1)[2:]}")
            d = date.fromordinal(d.toordinal() + 1)

    def test_tracker_feeds_both_tcs_and_lrs(self):
        t = YTDTracker()
        t.add(date(2026, 5, 1), "travel", 4 * 100000, 4800)
        t.add(date(2026, 8, 1), "education", 9 * 100000, 10800)
        u = t.usage(date(2026, 10, 17))
        self.assertEqual(compute_tcs(PACK, 3 * 100000, prior_lrs_inr=u["inr"]).taxable_base, 3 * 100000)
        self.assertEqual(lrs_headroom(PACK, u["usd"], 0).headroom_before_usd, CAP - 15600)


if __name__ == "__main__":
    unittest.main()
