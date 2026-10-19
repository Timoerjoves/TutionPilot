"""Payment planning: when to send, whether to wait for the new financial year, loan versus own money, how to
split a payment that is too large, and what the next fee will cost.

Code computes every amount with compute_tcs / landed_cost, so each one carries its rule trace; the model only
words the result. Dates are calendar dates; "working days" skip Saturdays and Sundays (bank holidays are not
modelled). Not tax advice.
"""
import math
from datetime import date, timedelta
from decimal import Decimal as D

from .engine import compute_tcs, financial_year, landed_cost, lrs_headroom, money

BUFFER_WORKING_DAYS = 1  # one spare working day on top of the provider's own settlement time


def minus_working_days(d, n):
    while n > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def plus_working_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def next_fy_start(d):
    return date(d.year if d.month < 4 else d.year + 1, 4, 1)


def timing(due_on, settle_days, today):
    """Latest day to send so the money arrives by the due date."""
    send_by = minus_working_days(due_on, settle_days + BUFFER_WORKING_DAYS)
    days = (send_by - today).days
    status = "late" if days < 0 else "tight" if days <= 2 else "on_track"
    return {"due_on": due_on.isoformat(), "send_by": send_by.isoformat(), "days_left": days, "status": status,
            "settle_working_days": settle_days, "buffer_working_days": BUFFER_WORKING_DAYS}


def new_year_option(pack, route, foreign, *, due_on, settle_days, today, prior_inr, prior_usd, amount_usd, funding,
                    has_pan, mid_market_rate):
    """If the money can be sent on 1 April and still arrive by the due date, compare paying now with paying in the
    new financial year, when the TCS threshold and the LRS limit start again. None if waiting is not possible."""
    start = next_fy_start(today)
    if minus_working_days(due_on, settle_days + BUFFER_WORKING_DAYS) < start:
        return None
    now = landed_cost(pack, route, foreign, funding=funding, prior_lrs_inr=prior_inr, has_pan=has_pan,
                      mid_market_rate=mid_market_rate, on=today)
    later = landed_cost(pack, route, foreign, funding=funding, prior_lrs_inr=0, has_pan=has_pan,
                        mid_market_rate=mid_market_rate, on=start)
    return {"send_from": start.isoformat(), "financial_year": financial_year(start),
            "tcs_now_inr": now.tcs.tcs, "tcs_new_year_inr": later.tcs.tcs, "tcs_saving_inr": now.tcs.tcs - later.tcs.tcs,
            "fits_lrs_now": lrs_headroom(pack, prior_usd, amount_usd).within_cap,
            "assumes": "no other remittances in the new financial year before this one",
            "trace": [pack.trace("tcs_threshold_inr"), pack.trace("lrs_annual_cap_usd")]}


def loan_option(pack, remitted_inr, *, funding, prior_inr, has_pan, on):
    """TCS on this payment from own money versus from an education loan by a financial institution."""
    own = compute_tcs(pack, remitted_inr, "self", prior_inr, has_pan, on=on)
    loan = compute_tcs(pack, remitted_inr, "loan", prior_inr, has_pan, on=on)
    return {"current": funding, "tcs_own_money_inr": own.tcs, "tcs_loan_inr": loan.tcs,
            "difference_inr": own.tcs - loan.tcs, "trace": own.trace + loan.trace}


def split_options(pack, amount_usd, *, headroom_usd, per_payment_cap_usd):
    """How a payment that is too large could be split. Each part is its own plan with its own parent signature."""
    out = []
    if amount_usd > per_payment_cap_usd:
        n = math.ceil(amount_usd / per_payment_cap_usd)
        out.append({"reason": "per_payment_cap", "payments": n, "each_up_to_usd": per_payment_cap_usd,
                    "text": f"Split into {n} payments of at most USD {per_payment_cap_usd:,.0f}; each needs its own "
                            "parent signature. Or a parent raises the cap in PIN-protected settings."})
    if amount_usd > headroom_usd:
        now = max(D(0), headroom_usd)
        out.append({"reason": "lrs_cap", "now_usd": now, "rest_usd": amount_usd - now,
                    "text": f"Only USD {now:,.0f} fits within this year's LRS limit. Pay that now and the rest from "
                            "1 April, or ask the bank to allow more on the university's estimate (studies abroad).",
                    "trace": [pack.trace("lrs_annual_cap_usd"), pack.trace("lrs_studies_above_cap_on_institution_estimate")]})
    return out


def next_fee(pack, routes, foreign, mid_market_rate, *, amount_usd, due_on, today, this_payment_inr,
             this_payment_usd, prior_inr, prior_usd, funding, has_pan):
    """Project a later fee (for example next semester) after this payment: same financial year or a new one."""
    same_year = financial_year(due_on) == financial_year(today)
    p_inr = prior_inr + this_payment_inr if same_year else D(0)
    p_usd = prior_usd + this_payment_usd if same_year else D(0)
    on = today if same_year else due_on
    costs = sorted((landed_cost(pack, r, foreign, funding=funding, prior_lrs_inr=p_inr, has_pan=has_pan,
                                mid_market_rate=mid_market_rate, on=on) for r in routes), key=lambda c: c.total_inr)
    best, lrs = costs[0], lrs_headroom(pack, p_usd, amount_usd)
    return {"due_on": due_on.isoformat(), "same_financial_year": same_year, "financial_year": financial_year(due_on),
            "prior_inr_counted": p_inr, "route": best.route, "total_inr": best.total_inr, "tcs_inr": best.tcs.tcs,
            "taxable_inr": best.tcs.taxable_base, "remitted_inr": best.remitted_inr, "amount_usd": amount_usd,
            "lrs_within_cap": lrs.within_cap, "lrs_headroom_after_usd": lrs.headroom_after_usd,
            "assumes": "no other remittances in that financial year" if not same_year
                       else "this payment is made first, and no other remittances in between",
            "trace": best.trace + lrs.trace, "needs_verification": best.needs_verification}
