"""Grounding check: every number the model writes must come from the rules engine.

The model explains; it never computes. Before an explanation is shown, every rupee/dollar amount
and every percentage in it is matched against the numbers in the rule_result messages it was given.
Anything that does not match is rejected and the engine's own wording is shown instead.
"""
import re
from decimal import Decimal, InvalidOperation

NUM = r"[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?"  # ends on a digit, so "Rs 75,000, which" gives 75,000
AMOUNT = re.compile(
    rf"(?:(?P<cur>rs\.?|inr|₹|usd|us\$|\$|gbp|£)\s?(?P<a>{NUM})(?:\s?(?P<u1>lakh|lakhs|crore|crores))?)"
    rf"|(?:(?P<b>{NUM})\s?(?P<u2>lakh|lakhs|crore|crores))",
    re.I)
PERCENT = re.compile(r"(?P<p>[0-9]+(?:\.[0-9]+)?)\s?%")
UNITS = {"lakh": 100000, "lakhs": 100000, "crore": 10000000, "crores": 10000000}


def _num(s):
    try:
        return Decimal(str(s).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def allowed_numbers(results):
    """All numeric values in the inputs, outputs and trace of the given rule_result messages."""
    amounts, rates = set(), set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, (str, int, Decimal)) and not isinstance(v, bool):
            n = _num(v)
            if n is not None and n.is_finite():
                amounts.add(abs(n).quantize(Decimal("0.01")))  # text states size, sign is in the words ("costs more")
                if 0 <= n <= 1:
                    rates.add((n * 100).normalize())
    for r in results:
        walk(r.get("inputs", {}))
        walk(r.get("outputs", {}))
        walk([t.get("value") for t in r.get("trace", [])])
    return amounts, rates


def check(text, results):
    """Return {"grounded": bool, "unsupported": [what the model wrote that the engine did not produce]}."""
    amounts, rates = allowed_numbers(results)
    bad = []
    for m in AMOUNT.finditer(text):
        raw = m.group("a") or m.group("b")
        unit = (m.group("u1") or m.group("u2") or "").lower()
        n = _num(raw)
        if n is None:
            continue
        n = abs(n * UNITS.get(unit, 1)).quantize(Decimal("0.01"))
        if n not in amounts:
            bad.append(m.group(0).strip())
    for m in PERCENT.finditer(text):
        if Decimal(m.group("p")).normalize() not in rates:
            bad.append(m.group(0))
    return {"grounded": not bad, "unsupported": bad}


def ground_or_replace(model_text, results, engine_text):
    """Show the model's words only if every number checks out; otherwise show the engine's own text."""
    c = check(model_text, results)
    return {"shown": model_text if c["grounded"] else engine_text,
            "source": "model" if c["grounded"] else "engine", **c}
