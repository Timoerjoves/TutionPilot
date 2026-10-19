"""Student living-cost budget: what it costs to send a student's monthly money abroad, and whether sending it
once a quarter instead of every month is cheaper.

Each transfer pays the provider's fixed fee again, so fewer, larger transfers cost less in fees; the hidden FX
markup and TCS scale with the amount and barely change. Every transfer is costed with landed_cost against the
year's running total, so TCS follows the threshold exactly. Living costs are treated as an education remittance
(rule tcs_living_costs_abroad_education_rate, unverified). Not tax advice.
"""
import math
from decimal import Decimal as D

from .engine import landed_cost, lrs_headroom, money

CADENCES = (("monthly", 1), ("quarterly", 3))


def living_budget(pack, routes, mid_market_rate, monthly_foreign, months, *, usd_per_unit, prior_inr, prior_usd,
                  funding, has_pan, on):
    monthly_foreign, months = D(monthly_foreign), int(months)
    if monthly_foreign <= 0 or not 1 <= months <= 24:
        raise ValueError("give a monthly amount above zero and between 1 and 24 months")
    plans = {}
    for name, every in CADENCES:
        running, left, transfers = D(prior_inr), months, []
        sums = dict.fromkeys(("remitted_inr", "charges_inr", "markup_inr", "tcs_inr", "total_inr"), D(0))
        for _ in range(math.ceil(months / every)):
            m = min(every, left)
            left -= m
            best = min((landed_cost(pack, r, monthly_foreign * m, funding=funding, prior_lrs_inr=running,
                                    has_pan=has_pan, mid_market_rate=mid_market_rate, on=on) for r in routes),
                       key=lambda c: c.total_inr)
            running += best.remitted_inr
            transfers.append({"months": m, "foreign": monthly_foreign * m, "route": best.route,
                              "total_inr": best.total_inr, "tcs_inr": best.tcs.tcs})
            for k, v in (("remitted_inr", best.remitted_inr), ("charges_inr", best.fee_inr + best.gst_inr + best.correspondent_inr),
                         ("markup_inr", best.markup_inr or D(0)), ("tcs_inr", best.tcs.tcs), ("total_inr", best.total_inr)):
                sums[k] += v
        plans[name] = {"transfers": len(transfers), "schedule": transfers, **sums}
    total_foreign = monthly_foreign * months
    lrs = lrs_headroom(pack, prior_usd, money(total_foreign * D(usd_per_unit)))
    trace = [pack.trace("tcs_living_costs_abroad_education_rate"), *lrs.trace]
    return {"monthly_foreign": monthly_foreign, "months": months, "total_foreign": total_foreign,
            "plans": plans, "saving_quarterly_inr": plans["monthly"]["total_inr"] - plans["quarterly"]["total_inr"],
            "lrs_within_cap": lrs.within_cap, "lrs_headroom_after_usd": lrs.headroom_after_usd,
            "prior_inr_counted": D(prior_inr), "trace": trace,
            "needs_verification": sorted({t["rule_id"] for t in trace if t["status"] == "unverified"})}
