"""The model adapter: the only two jobs a language model does in TuitionPilot.

1. extract(masked_text) -> invoice fields, with uncertain fields flagged
2. explain(engine_lines) -> words for the user

OfflineModel does both deterministically so the demo runs with no API key and no network.
A hosted model can replace it later behind the same two methods; it would receive only masked text
(through security.prepare_for_model) and its explanation would still pass the grounding check.
"""
import re
from datetime import datetime
from decimal import Decimal

LABELS = {
    "payee_name": r"payee",
    "invoice_id": r"invoice (?:no|number|#)",
    "issued_on": r"issue(?:d)? date",
    "due_on": r"due date|payment due|due by",
    "student_name": r"student(?: name)?",
    "student_id": r"student id|student number",
    "amount": r"amount due|total due|amount",
    "registry_id": r"payee registry id|registry id",
    "country": r"country",
    "account_masked": r"bank account|account",
    "swift": r"swift(?:/bic)?|bic",
}
DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%B %d, %Y", "%b %d, %Y")
AMOUNT = re.compile(r"(?P<cur>[A-Z]{3})\s*(?P<val>[0-9][0-9,]*(?:\.[0-9]{1,2})?)")


def _date(value):
    """(iso_date, uncertain). Non-ISO dates are converted but flagged so the user confirms them."""
    for i, fmt in enumerate(DATE_FORMATS):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat(), i > 0
        except ValueError:
            continue
    return None, True


class OfflineModel:
    name = "offline-deterministic"

    def extract(self, masked_text):
        """Read 'Label: value' lines. Returns (invoice_message, uncertain_fields)."""
        found = {}
        for line in masked_text.splitlines():
            if ":" not in line:
                continue
            label, value = (s.strip() for s in line.split(":", 1))
            for key, pat in LABELS.items():
                if key not in found and re.fullmatch(pat, label, re.I) and value:
                    found[key] = value
                    break
        uncertain = []
        inv = {"type": "invoice", "contract_version": "1.0", "purpose": "education",
               "payee": {"bank": {}}, "student": {}, "amount": {}}
        for key in ("invoice_id",):
            if key in found:
                inv[key] = found[key]
        for key in ("issued_on", "due_on"):
            if key in found:
                iso, unsure = _date(found[key])
                if iso:
                    inv[key] = iso
                if unsure:
                    uncertain.append(key)
        if "payee_name" in found:
            inv["payee"]["name"] = found["payee_name"]
        if "registry_id" in found:
            inv["payee"]["registry_id"] = found["registry_id"]
        if "country" in found:
            inv["payee"]["country"] = found["country"].upper()
        if "account_masked" in found:
            inv["payee"]["bank"]["account_masked"] = found["account_masked"]
        if "swift" in found:
            inv["payee"]["bank"]["swift"] = found["swift"].upper()
        if "student_name" in found:
            inv["student"]["name"] = found["student_name"]
        if "student_id" in found:
            inv["student"]["student_id"] = found["student_id"]
        if "amount" in found:
            m = AMOUNT.search(found["amount"].upper())
            if m:
                value = Decimal(m.group("val").replace(",", "")).quantize(Decimal("0.01"))
                inv["amount"] = {"value": str(value), "currency": m.group("cur")}
            else:
                uncertain.append("amount")
        return inv, uncertain

    def explain(self, engine_lines):
        """Relay the engine's own sentences. A hosted model could rephrase; the grounding check still applies."""
        return " ".join(line["text"] for line in engine_lines)
