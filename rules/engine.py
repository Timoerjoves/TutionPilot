"""TuitionPilot rules engine.

India outbound education remittances: LRS cap, TCS, year-to-date tracking and landed cost.
Code computes every number. The model only explains the results.
All money values use Decimal. Data is synthetic. Not tax advice.
"""
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

D = Decimal
DEFAULT_PACK = Path(__file__).resolve().parent.parent / "rulepack" / "india_lrs_tcs.json"


def money(x):
    """Round to paise."""
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def rupee(x):
    """Round to the nearest rupee (used for TCS)."""
    return D(x).quantize(D("1"), rounding=ROUND_HALF_UP)


class RulePack:
    """A versioned set of rules, each with a source and a verification status."""

    def __init__(self, data):
        self.data = data
        self.rules = data["rules"]
        self.version = data["version"]

    @classmethod
    def load(cls, path=DEFAULT_PACK):
        with open(path, encoding="utf-8") as f:
            data = json.load(f, parse_float=D)
        return cls(data)

    def value(self, rule_id):
        v = self.rules[rule_id]["value"]
        return D(v) if isinstance(v, (int, float, D)) and not isinstance(v, bool) else v

    def trace(self, rule_id):
        r = self.rules[rule_id]
        return {
            "rule_id": rule_id,
            "pack_version": self.version,
            "value": r["value"],
            "effective_from": r.get("effective_from"),
            "status": r["status"],
            "source": r["source"],
        }


def _flags(entries):
    return sorted({e["rule_id"] for e in entries if e["status"] == "unverified"})


# ---------- Financial year and year-to-date tracking ----------

def financial_year(d: date) -> str:
    """Indian financial year, April to March. 2026-04-01 is in '2026-27'."""
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


@dataclass
class Remittance:
    on: date
    purpose: str
    amount_inr: Decimal
    amount_usd: Decimal
    funding: str = "self"


@dataclass
class YTDTracker:
    """Tracks LRS usage per PAN across all purposes within one financial year."""
    entries: list = field(default_factory=list)

    def add(self, on, purpose, amount_inr, amount_usd, funding="self"):
        self.entries.append(Remittance(on, purpose, D(amount_inr), D(amount_usd), funding))

    def usage(self, as_of: date):
        fy = financial_year(as_of)
        rows = [e for e in self.entries if financial_year(e.on) == fy and e.on <= as_of]
        return {
            "financial_year": fy,
            "inr": sum((e.amount_inr for e in rows), D(0)),
            "usd": sum((e.amount_usd for e in rows), D(0)),
            "other_purposes_inr": sum((e.amount_inr for e in rows if e.purpose != "education"), D(0)),
        }


# ---------- LRS cap ----------

@dataclass
class LrsResult:
    within_cap: bool
    cap_usd: Decimal
    headroom_before_usd: Decimal
    headroom_after_usd: Decimal
    trace: list
    needs_verification: list


def lrs_headroom(pack, prior_usd, amount_usd):
    prior, amount = D(prior_usd), D(amount_usd)
    if prior < 0 or amount < 0:
        raise ValueError("amounts cannot be negative")
    cap = pack.value("lrs_annual_cap_usd")
    before = cap - prior
    after = before - amount
    trace = [pack.trace("lrs_annual_cap_usd")]
    return LrsResult(after >= 0, cap, before, after, trace, _flags(trace))


# ---------- TCS ----------

@dataclass
class TcsResult:
    tcs: Decimal
    taxable_base: Decimal
    rate: Decimal
    funding: str
    cumulative_after_inr: Decimal
    trace: list
    needs_verification: list


def check_effective(pack, rule_ids, on):
    """Refuse to compute for a date before any rule used took effect."""
    if on is None:
        return
    for rid in rule_ids:
        eff = pack.rules[rid].get("effective_from")
        if eff and on < date.fromisoformat(eff):
            raise ValueError(f"rule {rid} applies from {eff}; pack {pack.version} does not cover {on}")


def compute_tcs(pack, amount_inr, funding="self", prior_lrs_inr=0, has_pan=True,
                prior_includes_other_purposes=False, on=None):
    """TCS on an education remittance.

    funding: 'self' (self-funded) or 'loan' (loan from a notified institution).
    prior_lrs_inr: LRS remittances already made this financial year, all purposes.
    """
    if funding not in ("self", "loan"):
        raise ValueError("funding must be 'self' or 'loan'")
    amount, prior = D(amount_inr), D(prior_lrs_inr)
    if amount < 0 or prior < 0:
        raise ValueError("amounts cannot be negative")
    threshold = pack.value("tcs_threshold_inr")
    used = ["tcs_threshold_inr"]
    if prior > 0:
        used.append("tcs_threshold_aggregates_all_purposes")
    if prior_includes_other_purposes:
        used.append("tcs_prior_other_purposes_count_toward_threshold")
    used.append("tcs_base_excludes_fees")
    cumulative_after = prior + amount

    if funding == "loan":
        rate_id, taxable = "tcs_rate_education_loan_funded", D(0)
    else:
        rate_id = "tcs_rate_education_self_funded" if has_pan else "tcs_rate_no_pan"
        taxable = max(D(0), cumulative_after - max(prior, threshold))
    used.append(rate_id)
    check_effective(pack, used, on)
    rate = pack.value(rate_id)
    trace = [pack.trace(r) for r in used]
    return TcsResult(rupee(taxable * rate), taxable, rate, funding, cumulative_after, trace, _flags(trace))


# ---------- Landed cost and route comparison ----------

@dataclass
class Route:
    name: str
    rate: Decimal            # INR per unit of foreign currency applied by the provider
    fee_inr: Decimal = D(0)
    gst_rate: Decimal = D(0)  # GST on the fee; take from the provider's fee schedule
    correspondent_inr: Decimal = D(0)


@dataclass
class LandedCost:
    route: str
    remitted_inr: Decimal
    fee_inr: Decimal
    gst_inr: Decimal
    correspondent_inr: Decimal
    tcs: TcsResult
    total_inr: Decimal
    markup_inr: Decimal  # hidden cost versus mid-market, or None if no mid-market rate given
    trace: list
    needs_verification: list


def landed_cost(pack, route, foreign_amount, funding="self", prior_lrs_inr=0, has_pan=True,
                mid_market_rate=None, prior_includes_other_purposes=False, on=None):
    foreign = D(foreign_amount)
    remitted = money(foreign * D(route.rate))
    tcs = compute_tcs(pack, remitted, funding, prior_lrs_inr, has_pan, prior_includes_other_purposes, on)
    fee, corr = money(route.fee_inr), money(route.correspondent_inr)
    gst = money(fee * D(route.gst_rate))
    total = money(remitted + fee + gst + corr + tcs.tcs)
    markup = money((D(route.rate) - D(mid_market_rate)) * foreign) if mid_market_rate is not None else None
    trace = tcs.trace + [pack.trace("gst_on_service_charge")] if gst > 0 else list(tcs.trace)
    return LandedCost(route.name, remitted, fee, gst, corr, tcs, total, markup, trace, _flags(trace))


def compare_routes(pack, routes, foreign_amount, **kwargs):
    """Rank routes by total landed cost, cheapest first, with the saving against the next route."""
    costs = sorted((landed_cost(pack, r, foreign_amount, **kwargs) for r in routes), key=lambda c: c.total_inr)
    out = []
    for i, c in enumerate(costs):
        saving = (costs[i + 1].total_inr - c.total_inr) if i + 1 < len(costs) else None
        out.append({"rank": i + 1, "cost": c, "saving_vs_next_inr": saving})
    return out
