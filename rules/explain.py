"""Line-by-line explanations of engine results.

Code writes every sentence and every number here; the model may only relay them.
Each line carries the rule ids it relies on and which of those are unverified,
so the explain panel can show the rule trace next to the words.
"""
from datetime import datetime, timezone

from contract import validate

from .engine import D, Route, compare_routes, money


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


def _line(label, amount, text, rules=(), flags=(), source=""):
    rules = list(rules)
    return {"label": label, "amount_inr": None if amount is None else str(money(amount)),
            "text": text, "rules": rules, "unverified": [r for r in rules if r in flags], "source": source}


def _quote_source(route, quote):
    if quote is None:
        return f"{route.name}'s quote"
    return f"quote {quote['quote_id']} from {quote['provider']}, valid until {quote['valid_until']}"


def _pack_source(trace, rule_ids):
    entries = [t for t in trace if t["rule_id"] in rule_ids]
    if not entries:
        return ""
    return f"rule pack {entries[0]['pack_version']}: " + "; ".join(
        f"{t['rule_id']} (effective {t['effective_from'] or 'date not set'}, {t['source']})" for t in entries)


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


def explain_landed_cost(cost, route, foreign_amount, currency="USD", quote=None):
    """Every rupee of one route's landed cost, one line per component, each with its source."""
    flags = cost.needs_verification
    tcs_rules = [t["rule_id"] for t in cost.tcs.trace]
    q = _quote_source(route, quote)
    lines = [_line("Amount sent", cost.remitted_inr,
                   f"{fx(foreign_amount, currency)} at {route.name}'s rate of {D(route.rate)} INR per {currency}.",
                   source=q)]
    lines.append(_line("Provider fee", cost.fee_inr, f"{route.name}'s published fee.", source=q))
    if cost.gst_inr > 0:
        lines.append(_line("GST on fee", cost.gst_inr,
                           f"GST at {pct(route.gst_rate)} of the fee, from {route.name}'s fee schedule.",
                           ["gst_on_service_charge"], flags,
                           "; ".join(filter(None, [q, _pack_source(cost.trace, ["gst_on_service_charge"])]))))
    if cost.correspondent_inr > 0:
        lines.append(_line("Correspondent charges", cost.correspondent_inr,
                           "Charges by intermediary banks, as quoted by the provider.", source=q))
    lines.append(_line("TCS", cost.tcs.tcs, tcs_sentence(cost.tcs), tcs_rules, flags,
                       _pack_source(cost.tcs.trace, tcs_rules)))
    used = list(dict.fromkeys(r for l in lines for r in l["rules"]))
    lines.append(_line("Total", cost.total_inr, f"What leaves your account for this payment via {route.name}.",
                       used, flags, "sum of the lines above"))
    return lines


def explain_markup(cost, route, mid_market_rate, foreign_amount, currency="USD", mid_source="synthetic sandbox reference"):
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
                f"is a cost built into the rate. It is not listed as a fee, and it is already inside "
                f"\"Amount sent\", so it is not added to the total again.")
    return _line("Hidden markup", cost.markup_inr, text,
                 source=f"mid-market reference rate {mid} INR per {currency} ({mid_source})")


def explain_comparison(ranked, routes, foreign_amount, currency="USD", quotes=None):
    """Summary of compare_routes() output plus why the winner wins, component by component."""
    by_name = {r.name: r for r in routes}
    quote_of = {q["route_name"]: q for q in quotes or []}
    best = ranked[0]["cost"]
    out = {"summary": None, "why": [], "routes": []}
    for row in ranked:
        c = row["cost"]
        out["routes"].append({"rank": row["rank"], "route": c.route, "total_inr": str(c.total_inr),
                              "lines": explain_landed_cost(c, by_name[c.route], foreign_amount, currency,
                                                           quote_of.get(c.route))})
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
                                best.needs_verification,
                                f"difference between the {label} lines of {best.route} and {nxt.route}"))
    return out


def compare_quotes(pack, invoice, quotes, mid_market_rate=None, mid_source="synthetic sandbox reference",
                   now=None, **kwargs):
    """Rank 2-4 contract quotes for one invoice and explain each route line by line.

    Refuses expired quotes (checked against `now`, default the current time) and impossible terms.
    kwargs go to compare_routes (funding, prior_lrs_inr, has_pan, on, ...). Money in the result is strings.
    """
    validate(invoice)
    for q in quotes:
        validate(q)
    if not 2 <= len(quotes) <= 4:
        raise ValueError(f"compare 2 to 4 quotes, not {len(quotes)}")
    names = [q["route_name"] for q in quotes]
    if len(set(names)) != len(names):
        raise ValueError("two quotes have the same route name")
    now = now or datetime.now(timezone.utc)
    amount, currency = D(invoice["amount"]["value"]), invoice["amount"]["currency"]
    for q in quotes:
        fa = q["foreign_amount"]
        if fa["currency"] != currency or D(fa["value"]) != amount:
            raise ValueError(f"quote {q['quote_id']} is for {fa['currency']} {fa['value']}, "
                             f"but the invoice is for {currency} {invoice['amount']['value']}")
        # the contract only checks that these are decimals; a negative fee or zero rate would rank first
        if D(q["fx_rate"]) <= 0 or min(D(q["fee_inr"]), D(q["correspondent_inr"])) < 0 or not 0 <= D(q["gst_rate"]) <= 1:
            raise ValueError(f"quote {q['quote_id']} has impossible terms (rate must be > 0, "
                             f"fees >= 0, GST rate between 0 and 1)")
        if now > datetime.fromisoformat(q["valid_until"]):
            raise ValueError(f"quote {q['quote_id']} expired at {q['valid_until']}; get a new quote")
    routes = [Route(q["route_name"], D(q["fx_rate"]), fee_inr=D(q["fee_inr"]), gst_rate=D(q["gst_rate"]),
                    correspondent_inr=D(q["correspondent_inr"])) for q in quotes]
    ranked = compare_routes(pack, routes, amount, mid_market_rate=mid_market_rate, **kwargs)
    expl = explain_comparison(ranked, routes, amount, currency, quotes)
    quote_of = {q["route_name"]: q for q in quotes}
    out = {"summary": expl["summary"], "why": expl["why"], "routes": []}
    route_of = {r.name: r for r in routes}
    for row, ex in zip(ranked, expl["routes"]):
        c, saving = row["cost"], row["saving_vs_next_inr"]
        out["routes"].append({"rank": row["rank"], "route": c.route, "quote_id": quote_of[c.route]["quote_id"],
                              "total_inr": str(c.total_inr),
                              "saving_vs_next_inr": None if saving is None else str(saving),
                              "lines": ex["lines"],
                              "markup": explain_markup(c, route_of[c.route], mid_market_rate, amount, currency, mid_source),
                              "trace": c.trace, "needs_verification": c.needs_verification})
    return out
