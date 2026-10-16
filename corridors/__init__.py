"""Corridors as config: one JSON file per destination (India to USA, India to UK). Owner: Chandan.

A corridor holds destination facts only (currency, visa document, purpose code). Tax rules stay in the rule pack.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQUIRED = ("corridor_id", "version", "origin_country", "destination_country", "currency", "rule_pack",
            "purpose", "student_visa_document")


class CorridorError(ValueError):
    pass


def available():
    """Corridor ids found in this folder, e.g. ['IN-GB', 'IN-US']."""
    return sorted(load_file(p)["corridor_id"] for p in HERE.glob("*.json"))


def load_file(path):
    c = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in c]
    if missing:
        raise CorridorError(f"{Path(path).name}: missing {missing}")
    return c


def load(corridor_id):
    for p in HERE.glob("*.json"):
        c = load_file(p)
        if c["corridor_id"] == corridor_id:
            return c
    raise CorridorError(f"no corridor {corridor_id!r}; available: {available()}")


def for_invoice(invoice):
    """Pick the corridor from the invoice's payee country; refuse if the currency does not match."""
    country = invoice.get("payee", {}).get("country")
    currency = invoice.get("amount", {}).get("currency")
    c = load(f"IN-{country}")
    if currency != c["currency"]:
        raise CorridorError(f"invoice currency {currency} does not match corridor {c['corridor_id']} ({c['currency']})")
    return c


def unverified(corridor):
    """Names of corridor facts still marked unverified, to be flagged in outputs."""
    return sorted(k for k, v in corridor.items() if isinstance(v, dict) and v.get("status") == "unverified")
