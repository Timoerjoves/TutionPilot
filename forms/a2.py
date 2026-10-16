"""A2-style remittance draft and missing-documents checklist (Plan v2 item 7, scenarios A6, A9, A10).

This is a DRAFT in the shape of the bank's Form A2, not the official form. Code fills every field from the
invoice, the remitter's answers and the engine's numbers. Anything missing becomes a question: the agent
asks, it never guesses. Identifiers are kept as given (pass masked tokens when the draft goes near the model).
"""
from rules.explain import fx, inr

LABELS = ["Synthetic data", "Draft only: not an official RBI or bank form", "Not tax advice"]

# (key, what it is, when it is needed). The list is typical of Indian banks; each bank's own list may differ.
CHECKLIST = [
    ("a2_form_signed", "Form A2 signed by the remitter", "always"),
    ("remitter_pan", "Remitter's PAN card copy", "always"),
    ("fee_invoice", "University fee invoice or demand letter", "always"),
    ("admission_letter", "Student's admission or offer letter", "always"),
    ("student_passport", "Student's passport copy", "always"),
    ("student_visa_document", None, "always"),  # name comes from the corridor
    ("lrs_declaration", "Declaration of LRS remittances made this financial year", "always"),
    ("loan_sanction_letter", "Education loan sanction letter", "loan"),
]
CHECKLIST_SOURCE = {"status": "unverified", "source": "Typical bank requirements for education remittances",
                    "check_against": "Your bank's own A2 document list"}


def _get(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d or d[k] in (None, ""):
            return None
        d = d[k]
    return d


# (field path in the inputs, label, question if missing)
REQUIRED = [
    ("invoice.invoice_id", "Invoice number", "What is the invoice number on the university's fee invoice?"),
    ("invoice.due_on", "Payment due date", "The invoice has no due date. When does the university need the payment?"),
    ("invoice.amount.value", "Amount", "How much does the invoice ask you to pay?"),
    ("invoice.amount.currency", "Currency", "Which currency is the invoice in?"),
    ("invoice.payee.name", "Beneficiary name", "What is the university's name on the invoice?"),
    ("invoice.payee.country", "Beneficiary country", "Which country is the university in?"),
    ("invoice.payee.bank.account_masked", "Beneficiary account", "The invoice has no bank account. Please upload the page with the university's bank details."),
    ("invoice.payee.bank.swift", "Beneficiary SWIFT/BIC", "The invoice has no SWIFT/BIC code. Please upload the page with the university's bank details."),
    ("invoice.student.name", "Student name", "What is the student's name as on the passport?"),
    ("invoice.student.student_id", "Student ID", "What is the student's university ID number?"),
    ("remitter.name", "Remitter name", "Who is sending the money (name as on the PAN card)?"),
    ("remitter.pan", "Remitter PAN", "Please give the remitter's PAN. Without a PAN, TCS is charged at a higher rate."),
    ("remitter.relationship", "Relationship to student", "How is the remitter related to the student (for example father, mother, self)?"),
]


def build_a2_draft(invoice, remitter, corridor, funding="self", landed=None, documents=frozenset(),
                   registry_mismatch=()):
    """Return the draft: status, questions, sections, checklist, labels and flags.

    invoice: invoice message (may be incomplete), remitter: {name, pan, relationship, address},
    corridor: from corridors.load(), landed: LandedCost for the chosen route (optional),
    documents: keys of CHECKLIST already provided, registry_mismatch: output of security.payee_mismatch().
    """
    inputs = {"invoice": invoice or {}, "remitter": remitter or {}}
    questions = [{"field": label, "question": q} for path, label, q in REQUIRED if _get(inputs, path) is None]
    if funding not in ("self", "loan"):
        questions.append({"field": "Funding", "question": "Is this paid from your own money or an education loan?"})
    blockers = []
    if registry_mismatch:
        blockers.append("The invoice's payee details do not match the verified registry "
                        f"({', '.join(registry_mismatch)}). Do not pay; confirm with the university by phone "
                        "using a number from its official website.")
    currency = _get(inputs, "invoice.amount.currency")
    if currency and currency != corridor["currency"]:
        blockers.append(f"Invoice currency {currency} does not match the {corridor['corridor_id']} corridor "
                        f"({corridor['currency']}).")

    amount = _get(inputs, "invoice.amount.value")
    remittance = {
        "foreign_amount": fx(amount, currency) if amount and currency else None,
        "due_on": _get(inputs, "invoice.due_on"),
        "funding": {"self": "Own funds", "loan": "Education loan"}.get(funding),
    }
    if landed is not None:
        remittance.update({"route": landed.route, "inr_equivalent": inr(landed.remitted_inr),
                           "tcs": inr(landed.tcs.tcs), "total_debit": inr(landed.total_inr)})

    sections = {
        "remitter": {"name": _get(inputs, "remitter.name"), "pan": _get(inputs, "remitter.pan"),
                     "address": _get(inputs, "remitter.address"),
                     "relationship_to_student": _get(inputs, "remitter.relationship")},
        "beneficiary": {"name": _get(inputs, "invoice.payee.name"), "country": _get(inputs, "invoice.payee.country"),
                        "account": _get(inputs, "invoice.payee.bank.account_masked"),
                        "swift_bic": _get(inputs, "invoice.payee.bank.swift"),
                        "registry_id": _get(inputs, "invoice.payee.registry_id")},
        "student": {"name": _get(inputs, "invoice.student.name"),
                    "student_id": _get(inputs, "invoice.student.student_id")},
        "remittance": remittance,
        "purpose": {"code": corridor["purpose"]["value"], "description": corridor["purpose"]["description"],
                    "invoice_reference": _get(inputs, "invoice.invoice_id")},
        "declaration": ("I declare that the total amount of foreign exchange purchased or remitted by me in this "
                        "financial year, including this remittance, is within the limit of the Liberalised "
                        "Remittance Scheme, and that the money is not for any prohibited purpose."),
    }

    checklist = []
    for key, what, when in CHECKLIST:
        if when == "loan" and funding != "loan":
            continue
        if key == "student_visa_document":
            what = f"Student visa document: {corridor['student_visa_document']['value']}"
        checklist.append({"key": key, "item": what, "status": "have" if key in documents else "missing"})

    flags = sorted({f"corridor.{k}" for k, v in corridor.items()
                    if isinstance(v, dict) and v.get("status") == "unverified"} | {"checklist"})
    if landed is not None:
        flags = sorted(set(flags) | set(landed.needs_verification))

    status = "blocked" if blockers else "needs_information" if questions else "ready"
    return {
        "title": "A2-style remittance draft",
        "status": status,
        "blockers": blockers,
        "questions": questions,
        "sections": sections,
        "checklist": checklist,
        "checklist_source": CHECKLIST_SOURCE,
        "missing_documents": [c["item"] for c in checklist if c["status"] == "missing"],
        "needs_verification": flags,
        "labels": LABELS,
    }


def render_text(draft):
    """Plain-text view of the draft for the screen or a PDF export."""
    out = [draft["title"].upper(), " | ".join(draft["labels"]), f"Status: {draft['status']}", ""]
    for b in draft["blockers"]:
        out.append(f"STOP: {b}")
    for q in draft["questions"]:
        out.append(f"QUESTION ({q['field']}): {q['question']}")
    for name, sec in draft["sections"].items():
        out.append("")
        out.append(name.replace("_", " ").title())
        if isinstance(sec, str):
            out.append(f"  {sec}")
            continue
        for k, v in sec.items():
            out.append(f"  {k.replace('_', ' ')}: {v if v is not None else '[missing]'}")
    out.append("")
    out.append("Documents (typical list; confirm with your bank)")
    for c in draft["checklist"]:
        out.append(f"  [{'x' if c['status'] == 'have' else ' '}] {c['item']}")
    if draft["needs_verification"]:
        out.append("")
        out.append("Unverified: " + ", ".join(draft["needs_verification"]))
    return "\n".join(out)
