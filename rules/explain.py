"""Line-by-line explanations of engine results.

Code writes every sentence and every number here; the model may only relay them.
Each line carries the rule ids it relies on and which of those are unverified,
so the explain panel can show the rule trace next to the words.
"""
from .engine import D, money


def inr(x):
    """Format rupees the Indian way: 1823080 -> 'Rs 18,23,080'; paise shown only if not zero."""
    q = money(x)
    sign = "-" if q < 0 else ""
    whole, paise = f"{abs(q):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}Rs {','.join(groups + [tail])}" + ("" if paise == "00" else f".{paise}")


def pct(rate):
    """0.02 -> '2%', 0.185 -> '18.5%'."""
    return f"{(D(rate) * 100).normalize():f}%"


def fx(amount, currency):
    """20000 -> 'USD 20,000'."""
    a = D(amount)
    return f"{currency} {a:,.2f}".replace(".00", "") if a == a.to_integral() else f"{currency} {a:,.2f}"


def _line(label, amount, text, rules=(), flags=()):
    rules = list(rules)
    return {"label": label, "amount_inr": None if amount is None else str(money(amount)),
            "text": text, "rules": rules, "unverified": [r for r in rules if r in flags]}


def _trace_value(trace, rule_id):
    for t in trace:
        if t["rule_id"] == rule_id:
            return t["value"]
    return None


def tcs_sentence(tcs):
    """Why TCS is what it is, in one sentence."""
    if tcs.funding == "loan":
        return "No TCS: education paid from a loan by a notified financial institution is charged 0%."
    threshold = _trace_value(tcs.trace, "tcs_threshold_inr")
    if tcs.taxable_base == 0:
        return (f"No TCS: your total this financial year ({inr(tcs.cumulative_after_inr)}) "
                f"stays within the {inr(threshold)} threshold.")
    # cumulative - taxable = max(earlier remittances, threshold); above the threshold means all of it is taxed
    whole_amount = tcs.cumulative_after_inr - tcs.taxable_base > threshold
    reason = ("your earlier remittances this year already used up the threshold, so all of this payment is taxed"
              if whole_amount else f"only the part of this year's total above {inr(threshold)} is taxed")
    return f"TCS at {pct(tcs.rate)} on {inr(tcs.taxable_base)}: {reason}."


def explain_landed_cost(cost, route, foreign_amount, currency="USD"):
    """Every rupee of one route's landed cost, one line per component."""
    flags = cost.needs_verification
    tcs_rules = [t["rule_id"] for t in cost.tcs.trace]
    lines = [_line("Amount sent", cost.remitted_inr,
                   f"{fx(foreign_amount, currency)} at {route.name}'s rate of {D(route.rate)} INR per {currency}.")]
    lines.append(_line("Provider fee", cost.fee_inr, f"{route.name}'s published fee."))
    if cost.gst_inr > 0:
        lines.append(_line("GST on fee", cost.gst_inr,
                           f"GST at {pct(route.gst_rate)} of the fee, from {route.name}'s fee schedule.",
                           ["gst_on_service_charge"], flags))
    if cost.correspondent_inr > 0:
        lines.append(_line("Correspondent charges", cost.correspondent_inr,
                           "Charges by intermediary banks, as quoted by the provider."))
    lines.append(_line("TCS", cost.tcs.tcs, tcs_sentence(cost.tcs), tcs_rules, flags))
    lines.append(_line("Total", cost.total_inr, f"What leaves your account for this payment via {route.name}."))
    return lines


def explain_markup(cost, route, mid_market_rate, foreign_amount, currency="USD"):
    """The cost hidden inside the exchange rate. None if no mid-market rate was given."""
    if mid_market_rate is None or cost.markup_inr is None:
        return None
    rate, mid, foreign = D(route.rate), D(mid_market_rate), D(foreign_amount)
    diff = rate - mid
    share = (cost.markup_inr / (mid * foreign) * 100).quantize(D("0.01")) if mid * foreign else D(0)
    if diff <= 0:
        text = (f"{route.name}'s rate ({rate}) is at or better than the mid-market rate ({mid}), "
                f"so there is no hidden markup.")
    else:
        text = (f"{route.name} uses {rate} INR per {currency}; the mid-market rate is {mid}. "
                f"The gap of {diff} x {fx(foreign, currency)} = {inr(cost.markup_inr)} ({share}% of the payment) "
                f"is a cost built into the rate. It is not listed as a fee.")
    return _line("Hidden markup", cost.markup_inr, text)


def explain_comparison(ranked, routes, foreign_amount, currency="USD"):
    """Summary of compare_routes() output plus why the winner wins, component by component."""
    by_name = {r.name: r for r in routes}
    best = ranked[0]["cost"]
    out = {"summary": None, "why": [], "routes": []}
    for row in ranked:
        c = row["cost"]
        out["routes"].append({"rank": row["rank"], "route": c.route, "total_inr": str(c.total_inr),
                              "lines": explain_landed_cost(c, by_name[c.route], foreign_amount, currency)})
    if len(ranked) == 1:
        out["summary"] = f"Only one route: {best.route} at {inr(best.total_inr)}."
        return out
    nxt = ranked[1]["cost"]
    saving = ranked[0]["saving_vs_next_inr"]
    out["summary"] = (f"Cheapest: {best.route} at {inr(best.total_inr)}, "
                      f"{inr(saving)} less than {nxt.route} ({inr(nxt.total_inr)}).")
    parts = [("Exchange rate", best.remitted_inr, nxt.remitted_inr),
             ("Provider fee", best.fee_inr, nxt.fee_inr),
             ("GST on fee", best.gst_inr, nxt.gst_inr),
             ("Correspondent charges", best.correspondent_inr, nxt.correspondent_inr),
             ("TCS", best.tcs.tcs, nxt.tcs.tcs)]
    for label, a, b in parts:
        d = b - a
        if d == 0:
            continue
        side = f"{best.route} saves {inr(d)}" if d > 0 else f"{best.route} costs {inr(-d)} more"
        out["why"].append(_line(label, d, f"{label}: {side}.",
                                [t["rule_id"] for t in best.tcs.trace] if label == "TCS" else
                                ["gst_on_service_charge"] if label == "GST on fee" else [],
                                best.needs_verification))
    return out
