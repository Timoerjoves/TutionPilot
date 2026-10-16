"""Shared interface contract between the rules engine (Chandan) and the app/agent (Nishanth).

Five message types: invoice, quote, rule_result, plan, approval. See docs/CONTRACT.md.
Rules every message follows:
- Money is a decimal STRING ("1500000.00"), never a float.
- Dates are ISO 8601 strings ("2026-10-16"); timestamps add time and offset.
- Every message has "type" and "contract_version".
Standard library only.
"""
import hashlib
import json
from decimal import Decimal, InvalidOperation

CONTRACT_VERSION = "1.0"

TIERS = ("T0", "T1", "T2", "T3", "T4")

# field name -> expected kind. "money" = decimal string, "date" = ISO date string,
# "tier" = one of TIERS, a tuple = allowed values, dict = nested object spec, [spec] = list of spec.
SPECS = {
    "invoice": {
        "invoice_id": str, "issued_on": "date", "due_on": "date",
        "payee": {"name": str, "registry_id": str, "country": str,
                  "bank": {"account_masked": str, "swift": str}},
        "student": {"name": str, "student_id": str},
        "amount": {"value": "money", "currency": str},
        "purpose": ("education",),
    },
    "quote": {
        "quote_id": str, "route_name": str, "provider": str,
        "foreign_amount": {"value": "money", "currency": str},
        "fx_rate": "money", "fee_inr": "money", "gst_rate": "money",
        "correspondent_inr": "money", "valid_until": str,
    },
    "rule_result": {
        "kind": ("tcs", "lrs_headroom", "landed_cost"),
        "pack_id": str, "pack_version": str,
        "inputs": dict, "outputs": dict,
        "trace": [{"rule_id": str, "pack_version": str, "status": str, "source": str}],
        "needs_verification": list,
    },
    "plan": {
        "plan_id": str, "created_at": str, "goal": str,
        "steps": [{"n": int, "action": str, "tool": str, "tier": "tier", "inputs": dict}],
        "max_tier": "tier", "plan_hash": str,
    },
    "approval": {
        "approval_id": str, "plan_id": str, "plan_hash": str, "tier": "tier",
        "approver": {"role": ("parent", "student")},
        "decision": ("approved", "rejected"), "method": ("pin", "click"),
        "decided_at": str,
    },
}


class ContractError(ValueError):
    pass


def _check(value, spec, path, errors):
    if spec is str:
        if not isinstance(value, str) or not value:
            errors.append(f"{path}: expected non-empty string")
    elif spec is int:
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path}: expected integer")
    elif spec is dict:
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
    elif spec is list:
        if not isinstance(value, list):
            errors.append(f"{path}: expected list")
    elif spec == "money":
        try:
            if not isinstance(value, str) or not Decimal(value).is_finite():
                raise InvalidOperation
        except InvalidOperation:
            errors.append(f"{path}: expected decimal string like \"1500000.00\"")
    elif spec == "date":
        import datetime
        try:
            datetime.date.fromisoformat(value)
        except (TypeError, ValueError):
            errors.append(f"{path}: expected ISO date YYYY-MM-DD")
    elif spec == "tier":
        if value not in TIERS:
            errors.append(f"{path}: expected one of {TIERS}")
    elif isinstance(spec, tuple):
        if value not in spec:
            errors.append(f"{path}: expected one of {spec}")
    elif isinstance(spec, list):
        if not isinstance(value, list) or not value:
            errors.append(f"{path}: expected non-empty list")
        else:
            for i, item in enumerate(value):
                _check(item, spec[0], f"{path}[{i}]", errors)
    elif isinstance(spec, dict):
        if not isinstance(value, dict):
            errors.append(f"{path}: expected object")
            return
        for key, sub in spec.items():
            if key not in value:
                errors.append(f"{path}.{key}: missing")
            else:
                _check(value[key], sub, f"{path}.{key}", errors)


def validate(msg):
    """Raise ContractError listing every problem; return msg if valid."""
    errors = []
    kind = msg.get("type") if isinstance(msg, dict) else None
    if kind not in SPECS:
        raise ContractError(f"unknown or missing type: {kind!r}")
    if msg.get("contract_version") != CONTRACT_VERSION:
        errors.append(f"contract_version: expected {CONTRACT_VERSION}")
    _check(msg, SPECS[kind], kind, errors)
    if kind == "plan" and not errors:
        if msg["plan_hash"] != plan_hash(msg):
            errors.append("plan.plan_hash: does not match plan contents")
        if msg["max_tier"] != max(s["tier"] for s in msg["steps"]):
            errors.append("plan.max_tier: must equal the highest step tier")
    if errors:
        raise ContractError("; ".join(errors))
    return msg


def canonical_json(obj):
    """One exact byte form for hashing: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def plan_hash(plan):
    """SHA-256 of the plan without its own plan_hash field. Any edit to the plan changes it."""
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    return "sha256:" + hashlib.sha256(canonical_json(body)).hexdigest()


# ---------- Engine results -> rule_result messages ----------

def _s(x):
    return None if x is None else str(x)


def _envelope(kind, pack, inputs, outputs, trace, flags):
    return {
        "type": "rule_result", "contract_version": CONTRACT_VERSION, "kind": kind,
        "pack_id": pack.data["pack_id"], "pack_version": pack.version,
        "inputs": inputs, "outputs": outputs,
        "trace": [{**t, "value": _s(t["value"])} for t in trace],
        "needs_verification": list(flags),
    }


def tcs_result(pack, r, amount_inr, prior_lrs_inr=0, has_pan=True):
    return _envelope("tcs", pack,
                     {"amount_inr": _s(amount_inr), "funding": r.funding,
                      "prior_lrs_inr": _s(prior_lrs_inr), "has_pan": has_pan},
                     {"tcs_inr": _s(r.tcs), "taxable_base_inr": _s(r.taxable_base), "rate": _s(r.rate),
                      "cumulative_after_inr": _s(r.cumulative_after_inr)},
                     r.trace, r.needs_verification)


def lrs_result(pack, r, prior_usd, amount_usd):
    return _envelope("lrs_headroom", pack,
                     {"prior_usd": _s(prior_usd), "amount_usd": _s(amount_usd)},
                     {"within_cap": r.within_cap, "cap_usd": _s(r.cap_usd),
                      "headroom_before_usd": _s(r.headroom_before_usd),
                      "headroom_after_usd": _s(r.headroom_after_usd)},
                     r.trace, r.needs_verification)


def landed_cost_result(pack, c, foreign_amount):
    return _envelope("landed_cost", pack,
                     {"route_name": c.route, "foreign_amount": _s(foreign_amount)},
                     {"remitted_inr": _s(c.remitted_inr), "fee_inr": _s(c.fee_inr), "gst_inr": _s(c.gst_inr),
                      "correspondent_inr": _s(c.correspondent_inr), "tcs_inr": _s(c.tcs.tcs),
                      "total_inr": _s(c.total_inr), "markup_inr": _s(c.markup_inr)},
                     c.trace, c.needs_verification)
