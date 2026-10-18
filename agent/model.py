"""The model adapter: the only two jobs a language model does in TuitionPilot.

1. extract(masked_text) -> invoice fields, with uncertain fields flagged
2. explain(engine_lines) -> words for the user

OfflineModel does both deterministically so the demo runs with no API key and no network.
A hosted model can replace it later behind the same two methods; it would receive only masked text
(through security.prepare_for_model) and its explanation would still pass the grounding check.
"""
import json
import re
from datetime import datetime
from decimal import Decimal

LABELS = {  # matched against the label, then its shorter endings ("payee bank swift" -> "bank swift" -> "swift")
    "payee_name": r"payee(?: name)?|(?:university|institution|school|beneficiary)(?: name)?",
    "invoice_id": r"invoice (?:no|number|#|id|ref|reference)|invoice",
    "issued_on": r"issue(?:d)? (?:date|on)|invoice date|date issued",
    "due_on": r"due (?:date|on|by)|payment due|due",
    "student_name": r"student(?: name)?",
    "student_id": r"student id|student number",
    "amount": r"amount due|total due|total amount|amount|total",
    "registry_id": r"payee registry id|registry id",
    "country": r"country",
    "account_masked": r"bank account|account(?: masked| number)?",
    "swift": r"swift(?:/bic)?|bic|swift code",
}
AMOUNT_KEYS = ("value", "amount", "total", "amount_due", "total_due")
SKIP_KEYS = {"attestation"}  # the signature block: checked by the trust store, never shown to the model


def json_to_text(obj):
    """An uploaded JSON invoice (any nesting, snake_case or camelCase keys) -> ('Label: value' lines for extract(),
    the parsed object). Raises ValueError if it is not one JSON object."""
    try:
        obj = json.loads(obj)
    except json.JSONDecodeError as e:
        raise ValueError(f"the file looks like JSON but is not valid JSON ({e.msg}, line {e.lineno})")
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]
    if not isinstance(obj, dict):
        raise ValueError("upload one invoice at a time: the JSON must be a single object")
    lines = []

    def label(path):
        words = " ".join(re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", k) for k in path)
        return re.sub(r"[_.\-]+", " ", words).strip()

    def walk(node, path):
        if isinstance(node, dict):
            keys = {k.lower(): k for k in node}
            cur, val = keys.get("currency"), next((keys[k] for k in AMOUNT_KEYS if k in keys), None)
            if cur and val and not isinstance(node[val], (dict, list)):  # {"value": 20000, "currency": "USD"}
                lines.append(f"{label(path if val.lower() == 'value' else path + [val]) or 'amount'}: "
                             f"{node[cur]} {node[val]}")
                node = {k: v for k, v in node.items() if k not in (cur, val)}
            for k, v in node.items():
                if k.lower() not in SKIP_KEYS:
                    walk(v, path + [k])
        elif isinstance(node, list):
            for v in node:
                walk(v, path)
        elif node is not None and path:
            lines.append(f"{label(path)}: {node}")

    walk(obj, [])
    return "\n".join(lines), obj


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
            words = label.split()
            key = next((k for i in range(len(words)) for k, pat in LABELS.items()
                        if re.fullmatch(pat, " ".join(words[i:]), re.I)), None)
            if key and key not in found and value:
                found[key] = value
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
