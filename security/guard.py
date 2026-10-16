"""Scan untrusted text (invoice text, emails, chat) for attacks before the agent acts on it.

This is a pattern filter, not a proof: it catches the common phrasings in the attack test set.
The real protection is that the policy engine never lets text change tiers, payees or limits;
this scanner makes attempts visible and blocks them early. Known limits are in docs/SECURITY_SELF_ASSESSMENT.md.
"""
import re
import unicodedata

ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))

HIGH = "high"
LOW = "low"

# category -> (severity, [regex on normalised text])
RULES = {
    "prompt_injection": (HIGH, [
        r"\b(ignore|disregard|forget|override)\b.{0,30}\b(rules?|instructions?|polic(y|ies)|checks?|guidelines?|prompt)\b",
        r"\byou are now\b", r"\bnew instructions?\b", r"\bsystem prompt\b", r"\bact as\b.{0,20}\b(admin|bank|system)\b",
    ]),
    "auto_approve": (HIGH, [
        r"\b(skip|bypass|without|no need for|no)\b.{0,15}\b(approval|pin|verification|confirmation)\b",
        r"\b(auto[- ]?approve|approve (this|it|the payment|immediately|now))\b",
        r"\bmark (it|this|the payment) (as )?approved\b",
    ]),
    "privilege_escalation": (HIGH, [
        r"\bi am (the |an |a )?(admin|administrator|developer|bank (officer|manager)|system|supervisor)\b",
        r"\b(admin|root|developer|god) (mode|override|access|rights)\b",
        r"\b(raise|increase|change|remove|lift)\b.{0,20}\b(cap|limit|tier)s?\b",
    ]),
    "payee_change": (HIGH, [
        r"\b(new|updated|changed|different|alternate|alternative)\b.{0,20}\b(bank|account|beneficiary|payee|iban|swift)\b",
        r"\b(bank|account) (details|number) (has|have) (been )?changed\b",
        r"\bpay (to|into) (this|another|a different|the following) (account|bank)\b",
    ]),
    "data_extraction": (HIGH, [
        r"\b(pan|passport|aadhaar|aadhar|documents?|bank details)\b.{0,25}\b(of|for|belonging to)\b.{0,15}\b(another|other|someone|somebody|my (friend|classmate|roommate)|a different)\b",
        r"\b(another|other|someone else'?s?|somebody else'?s?|his|her|their) (student'?s? |person'?s? )?(pan|passport|aadhaar|aadhar|documents?)\b",
        r"\b(list|show|give|send|export|dump)\b.{0,20}\b(all|every)\b.{0,15}\b(pans?|passports?|users?|customers?|students?)\b",
    ]),
    "pressure": (LOW, [
        r"\burgent(ly)?\b", r"\bwithin \d+ (hours?|minutes?)\b", r"\b(seat|admission|enrol?ment) will be (cancelled|canceled|lost)\b",
        r"\bdo not tell\b", r"\bkeep (this|it) (secret|confidential)\b",
    ]),
}
COMPILED = {cat: (sev, [re.compile(p) for p in pats]) for cat, (sev, pats) in RULES.items()}


def normalise(text):
    """Undo common disguises: odd Unicode forms, zero-width characters, case, extra spaces, s p a c e d letters."""
    t = unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH).lower()
    t = re.sub(r"\b(?:\w ){3,}\w\b", lambda m: m.group(0).replace(" ", ""), t)  # "i g n o r e" -> "ignore"
    return re.sub(r"\s+", " ", t).strip()


def scan(text):
    """Return {"action": "block"|"warn"|"ok", "findings": [{category, severity, excerpt}]}."""
    t = normalise(text or "")
    findings = []
    for cat, (sev, pats) in COMPILED.items():
        for p in pats:
            m = p.search(t)
            if m:
                findings.append({"category": cat, "severity": sev, "excerpt": m.group(0)[:80]})
                break
    if any(f["severity"] == HIGH for f in findings):
        action = "block"
    elif findings:
        action = "warn"
    else:
        action = "ok"
    return {"action": action, "findings": findings}


def payee_mismatch(invoice, registry_entry):
    """Fields where the invoice payee differs from the registry record. Empty list = match.

    registry_entry: {"registry_id", "name", "country", "bank": {"account_masked", "swift"}}.
    A changed account or SWIFT on an invoice is the classic tuition-fraud pattern; the payment must stop.
    """
    if registry_entry is None:
        return ["registry_id"]
    p = invoice.get("payee", {})
    out = []
    for key in ("registry_id", "name", "country"):
        if p.get(key) != registry_entry.get(key):
            out.append(key)
    for key in ("account_masked", "swift"):
        if p.get("bank", {}).get(key) != registry_entry.get("bank", {}).get(key):
            out.append(f"bank.{key}")
    return out
