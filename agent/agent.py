"""The TuitionPilot agent: runs the 12-stage pipeline for one family's tuition payment.

Code does every stage with a right answer; the model adapter (agent/model.py) only reads the invoice and words
explanations, and sees masked text only. Every tool call passes the policy engine and is written to the audit log.

    Intake -> Mask -> Extract -> Validate -> Rules -> Compare -> Plan -> Policy gate -> Approve -> Execute -> Record -> Track
"""
import base64
import binascii
import json
import re
import uuid
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal as D, InvalidOperation
from pathlib import Path

import corridors
from app.audit import AuditLog
from app.family import Family
from app.policy import Policy
from app.sandbox import IST, BankError, SandboxBank
from contract import ContractError, landed_cost_result, lrs_result, plan_hash, validate
from forms import build_a2_draft
from forms.a2 import CHECKLIST
from rules import RulePack, YTDTracker, compare_routes, lrs_headroom
from rules.explain import explain_comparison, explain_markup, inr, tcs_sentence
from security import Masker, ModelSawLog, ground_or_replace, prepare_for_model, scan
from security.pki import TrustStore, verify_approval, split as split_signed

from .model import OfflineModel, _date, json_to_text, make_model
from .pdf import pdf_to_text

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "app" / "demo_config.json").read_text(encoding="utf-8"))
SAMPLES = ROOT / "data" / "invoices"
LAKH = D(100000)

STAGES = ["Intake", "Mask", "Extract", "Validate", "Rules", "Compare", "Plan", "Policy gate", "Approve",
          "Execute (sandbox)", "Record", "Track"]

# Questions about the family, asked after the invoice gaps. (field, question, kind, options)
FAMILY_QUESTIONS = [
    ("remitter_name", "Who is sending the money? (name as on the PAN card)", "text", None),
    ("pan", "What is the sender's PAN? If there is no PAN, choose 'No PAN' (TCS is then charged at a higher rate).",
     "text", ["No PAN"]),
    ("relationship", "How is the sender related to the student?", "choice", ["Father", "Mother", "Guardian", "Self"]),
    ("funding", "Is this paid from your own money or from an education loan by a bank or notified institution?",
     "choice", ["Own money", "Education loan"]),
    ("prior_inr", "How much have you already sent abroad this financial year (since 1 April), in rupees? "
                  "All purposes count. Type 0 if none.", "number", ["0"]),
    ("prior_usd", "And roughly how much is that in US dollars? Type 0 if none.", "number", ["0"]),
    ("prior_other", "Was any of that for purposes other than education (travel, gifts, investment)?",
     "choice", ["Yes", "No"]),
]
INVOICE_QUESTIONS = {  # invoice field -> question when the reader could not find it
    "invoice_id": "What is the invoice number?",
    "due_on": "The invoice has no due date. When does the university need the payment? (YYYY-MM-DD)",
    "amount": "How much does the invoice ask for, with currency? (for example USD 20,000)",
    "payee_name": "What is the university's name on the invoice?",
    "registry_id": "The invoice has no payee registry ID. Please upload the full invoice.",
    "country": "Which country is the university in? (US or GB)",
}
REFUSALS = {
    "data_extraction": "I can't share anyone else's PAN, passport or documents, and I only ever see masked tokens myself.",
    "privilege_escalation": "Limits and approvals can't be changed from chat. A parent can change limits only in PIN-protected settings.",
    "auto_approve": "Every payment needs the parent's PIN approval of the exact plan. I can't skip or pre-approve it.",
    "prompt_injection": "I follow TuitionPilot's fixed rules, not instructions inside messages or documents.",
    "payee_change": "I can't add or change a payee from chat. The university's bank details come only from its signed certificate.",
}
CHAT_DENY_ACTION = {"privilege_escalation": "raise_limit", "auto_approve": "skip_approval",
                    "payee_change": "add_payee", "prompt_injection": "skip_approval"}


def jsonable(x):
    if isinstance(x, D):
        return str(x)
    if is_dataclass(x):
        return jsonable(asdict(x))
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    return x


def parse_amount(text):
    """'6,00,000' / '6 lakh' / '600000' / '0' -> Decimal, or None."""
    t = str(text).strip().lower().replace(",", "").replace("rs", "").replace("inr", "").replace("usd", "").replace("$", "")
    m = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*(lakh|lakhs|crore|crores|k)?\s*", t)
    if not m:
        return None
    try:
        n = D(m.group(1))
    except InvalidOperation:
        return None
    return n * {"lakh": LAKH, "lakhs": LAKH, "crore": 100 * LAKH, "crores": 100 * LAKH, "k": 1000}.get(m.group(2), 1)


def display_pan(token, masker):
    raw = masker.unmask(token) if token else ""
    return f"{raw[:2]}XXX{raw[5:9]}{raw[9:]}" if len(raw) == 10 else None


class Agent:
    def __init__(self, evidence_dir=None, pin=None, clock=None, model=None):
        self.pack = RulePack.load()
        self.trust = TrustStore()
        ev = Path(evidence_dir) if evidence_dir else None  # None: logs stay in memory only
        self.bank = SandboxBank(self.trust, ledger_path=ev and ev / "sandbox_ledger.log",
                                **({"clock": clock} if clock else {}))
        self.clock = self.bank.clock
        self.policy = Policy(pin or CONFIG["demo_pin"], CONFIG["per_payment_cap_usd"], CONFIG["breaker_threshold"])
        self.audit = AuditLog(ev and ev / "audit_log.jsonl")
        self.model_saw = ModelSawLog(ev and ev / "model_saw.log")
        self.model = model or make_model()  # offline unless TUITIONPILOT_MODEL=claude
        self.family = Family(self.policy)
        self.sessions = {}
        self.handoffs = {}  # one-time code -> session a student prepared and asked a parent to sign

    # ---------- sessions ----------
    def new_session(self, role="parent"):
        sid = uuid.uuid4().hex[:12]
        self.sessions[sid] = {
            "id": sid, "role": role if role in ("parent", "student") else "parent", "consent": False,
            "device": None,  # key_id of the enrolled device that signed in; None for sessions made in code
            "masker": Masker(), "invoice": None, "uncertain": [], "invoice_scan": None, "trust": None, "payee_certificate": None,
            "answers": {}, "documents": set(), "quotes": [], "chosen_quote_id": None, "ranked": None,
            "plan": None, "plan_seq": 0, "approval": None, "txn": None, "receipt": None,
            "chat": [], "model_saw": [], "flags": [], "escalations": [], "lrs": None, "draft": None,
            "ytd": YTDTracker(), "prior_used": None, "warnings": [],
        }
        self.sessions[sid]["signed_in"] = self.sessions[sid]["role"]  # the most this session may act as
        self._log("session_started", {"role": self.sessions[sid]["role"]}, sid)
        self._say(self.sessions[sid], "agent", "Hello! I help you pay university tuition abroad, step by step. "
                  "First, please read and accept how your data is used.")
        return self.sessions[sid]

    def get(self, sid):
        s = self.sessions.get(sid)
        if s is None:
            raise KeyError("session not found (it may have been deleted)")
        return s

    def _log(self, event, data, sid=None):
        return self.audit.append(event, jsonable(data), sid)

    def _say(self, s, who, text, **extra):
        s["chat"].append({"who": who, "text": text, "at": datetime.now(IST).strftime("%H:%M"), **extra})

    def _tool(self, s, action, **kw):
        """Every tool call: policy check first, logged either way."""
        d = self.policy.check(action, **kw)
        self._log("policy_decision", d.to_dict(), s["id"])
        return d

    def _to_model(self, s, purpose, text):
        masked = prepare_for_model(s["masker"], self.model_saw, purpose, text)
        s["model_saw"].append({"purpose": purpose, "text": masked})
        return masked

    # ---------- stage 1-4: consent, intake, mask, extract, validate ----------
    def set_role(self, sid, role):
        s = self.get(sid)
        if role not in ("parent", "student"):
            raise ValueError("role must be parent or student")
        if role == "parent" and s["signed_in"] != "parent":
            raise PermissionError("Sign in on a parent device to act as the parent.")
        s["role"] = role
        self._log("role_switched", {"role": role}, sid)
        return s

    def consent(self, sid, accept):
        s = self.get(sid)
        s["consent"] = bool(accept)
        self._log("consent", {"accepted": s["consent"]}, sid)
        if s["consent"]:
            self._say(s, "agent", "Thank you. Upload or paste the university's fee invoice, or pick a sample.")
        return s

    def upload_invoice(self, sid, text=None, sample=None, pdf=None):
        s = self.get(sid)
        if not s["consent"]:
            raise PermissionError("Please accept the data consent first.")
        if sample:
            path = SAMPLES / f"{sample}.txt"
            if not re.fullmatch(r"[a-z_]+", sample) or not path.exists():
                raise ValueError("unknown sample")
            text = path.read_text(encoding="utf-8")
        if pdf:  # base64 PDF bytes from the browser; read as printed text (an unsigned PDF can never be paid)
            try:
                text = pdf_to_text(base64.b64decode(pdf, validate=True))
            except (binascii.Error, TypeError):
                raise ValueError("the PDF upload is damaged; try again")
        if not text or not text.strip():
            raise ValueError("invoice text is empty")
        self._reset_from_invoice(s)
        self._log("tool_call", {"tool": "read_invoice", "tier": "T0"}, sid)
        if text.lstrip()[:1] in ("{", "["):  # a JSON invoice file; a signed one carries its own attestation
            visible, obj = json_to_text(text)
            signed, damaged = (obj if "attestation" in obj else None), None
        else:
            visible, signed, damaged = split_signed(text)
        s["invoice_scan"] = scan(visible)
        masked = self._to_model(s, "extract_invoice", visible)
        inv, uncertain = self.model.extract(masked)
        inv = s["masker"].unmask_obj(inv)  # the model saw tokens; the family's draft shows the real names
        s["invoice"], s["uncertain"] = inv, uncertain
        self._say(s, "user", f"Uploaded invoice {inv.get('invoice_id', '(no number)')}.")
        self._verify_invoice(s, signed, damaged)
        found = [f for f in s["invoice_scan"]["findings"]]
        if found:
            cats = ", ".join(sorted({f["category"].replace("_", " ") for f in found}))
            s["flags"].append({"source": "invoice", "categories": cats})
            self._say(s, "agent", f"Warning: the invoice contains text that looks like {cats}. I have ignored it: "
                      "documents can't give me instructions, change payees or skip approval.", tone="warn")
            self._log("untrusted_text_flagged", {"source": "invoice", "findings": found}, sid)
        return self._advance(s)

    def _reset_from_invoice(self, s):
        for k, v in {"invoice": None, "uncertain": [], "trust": None, "payee_certificate": None, "quotes": [], "chosen_quote_id": None,
                     "ranked": None, "plan": None, "approval": None, "txn": None, "receipt": None,
                     "flags": [], "escalations": [], "lrs": None, "draft": None,
                     "warnings": [], "prior_used": None}.items():  # s["ytd"] (payments made) is kept
            s[k] = v
        # family answers (sender, PAN, funding, earlier remittances) carry over to a new invoice

    def _verify_invoice(self, s, signed, damaged):
        """Check the university's signature chain; the signed data, not the visible text, is what gets paid."""
        self._tool(s, "check_payee")
        r = self.trust.check_invoice(signed, self.clock().date())
        if damaged:
            r["reason"] = damaged
        if r["verified"]:
            seen, ok = s["invoice"], signed
            fields = {"invoice number": (seen.get("invoice_id"), ok.get("invoice_id")),
                      "amount": (seen.get("amount", {}).get("value"), ok["amount"]["value"]),
                      "currency": (seen.get("amount", {}).get("currency"), ok["amount"]["currency"]),
                      "due date": (seen.get("due_on"), ok.get("due_on")),
                      "payee": (seen.get("payee", {}).get("name"), ok["payee"]["name"]),
                      "bank account": (seen.get("payee", {}).get("bank", {}).get("account_masked"),
                                       ok["payee"]["bank"]["account_masked"]),
                      "SWIFT": (seen.get("payee", {}).get("bank", {}).get("swift"), ok["payee"]["bank"]["swift"])}
            differ = [k for k, (a, b) in fields.items() if a != b]
            r["chain"].append({"step": "Visible text matches signed data", "ok": not differ,
                               "detail": "what you see is what the university signed" if not differ
                               else "the printed invoice differs from the signed data: " + ", ".join(differ)})
            if differ:
                r.update(verified=False, reason="the printed invoice differs from what the university signed",
                         mismatch=differ)
            else:
                s["invoice"] = {k: v for k, v in signed.items() if k != "attestation"}
                s["payee_certificate"] = r["certificate"]
                s["uncertain"] = []
        s["trust"] = r
        self._log("tool_call", {"tool": "check_payee", "tier": "T0", "verified": r["verified"],
                                "reason": r["reason"], "chain": [c["step"] + (" ok" if c["ok"] else " FAILED")
                                                                 for c in r["chain"]]}, s["id"])
        if r["verified"]:
            subj = r["subject"]
            self._say(s, "agent", f"Signature verified: {subj['name']} signed this invoice, and its bank account "
                      f"{subj['bank']['account_masked']} / {subj['bank']['swift']} is certified by the trust root.", tone="ok")
        else:
            self._say(s, "agent", f"I can't verify this invoice: {r['reason']}. I will not pay it.", tone="deny")

    # ---------- questions and answers ----------
    def _invoice_gaps(self, s):
        inv = s["invoice"] or {}
        gaps = []
        if not inv.get("invoice_id"):
            gaps.append("invoice_id")
        if not inv.get("due_on"):
            gaps.append("due_on")
        if not inv.get("amount", {}).get("value"):
            gaps.append("amount")
        if not inv.get("payee", {}).get("name"):
            gaps.append("payee_name")
        if not inv.get("payee", {}).get("country"):
            gaps.append("country")
        return gaps

    def pending_question(self, s):
        if not s["consent"] or s["invoice"] is None:
            return None
        for field in self._invoice_gaps(s):
            return {"field": field, "text": INVOICE_QUESTIONS[field], "kind": "date" if field == "due_on" else "text",
                    "options": None}
        a = s["answers"]
        for field, text, kind, options in FAMILY_QUESTIONS:
            if field == "prior_usd" and a.get("prior_inr") == "0":
                continue
            if field == "prior_other" and a.get("prior_inr") in (None, "0"):
                continue
            if field not in a:
                return {"field": field, "text": text, "kind": kind, "options": options}
        return None

    def answer(self, sid, field, value):
        s = self.get(sid)
        q = self.pending_question(s)
        if q is None or q["field"] != field:
            raise ValueError("that question is not open")
        value = (value or "").strip()
        err = self._store_answer(s, field, value)
        if err:
            self._say(s, "agent", err, tone="warn")
            return self._advance(s, ask=False)
        shown = "(PAN given, masked)" if field == "pan" and s["answers"].get("pan") else value
        self._say(s, "user", shown)
        self._log("resumed", {"after_answer": field, "skipped_done": [d["check"] for d in self._done(s)]}, sid)
        return self._advance(s)

    # ---------- what to do next, decided from the session's state (not a fixed script) ----------
    def _done(self, s):
        """Checks already completed for this invoice; the agent never repeats them on resume."""
        t = s["trust"]
        done = [("read_invoice", s["invoice"] is not None, "Invoice read and masked"),
                ("check_payee", t is not None, "Signature chain " + ("verified" if t and t["verified"] else "checked: not verified")),
                ("compare_routes", s["ranked"] is not None, "Routes compared and costs computed"),
                ("approval", s["approval"] is not None, "Parent's signature accepted"),
                ("sandbox_pay", s["txn"] is not None, "Paid in the sandbox")]
        return [{"check": c, "text": text} for c, ok, text in done if ok]

    def next_action(self, s):
        """The one most useful next step and why, from the current state."""
        q = self.pending_question(s)
        if not s["consent"]:
            act, why = "Ask for consent", "Nothing is read until the family agrees to how data is used."
        elif s["invoice"] is None:
            act, why = "Wait for the invoice", "Every number depends on the invoice."
        elif q and q["field"] in INVOICE_QUESTIONS:
            act, why = f"Ask one question: {q['text']}", "The invoice is missing this, and guessing could pay the wrong amount or date."
        elif q:
            act, why = f"Ask one question: {q['text']}", "TCS and the LRS limit depend on it; the invoice can't tell."
        elif s["escalations"]:
            act, why = "Hand over to a human", s["escalations"][0]["text"]
        elif s["txn"]:
            act, why = "Done: receipt issued", "Paid once in the sandbox; a second click does nothing."
        elif s["approval"]:
            act, why = "Pay in the sandbox", "The parent signed this exact plan; the policy gate checks it again before paying."
        else:
            act, why = "Wait for the parent's signature", "A payment is tier T3: it needs the PIN and the parent device's signature of this plan."
        return {"action": act, "why": why, "done": self._done(s)}

    def _store_answer(self, s, field, value):
        inv, a = s["invoice"], s["answers"]
        if field == "due_on":
            iso, _ = _date(value)
            if not iso:
                return "Please give the date as YYYY-MM-DD, for example 2026-11-15."
            inv["due_on"] = iso
        elif field == "invoice_id":
            inv["invoice_id"] = value
        elif field == "amount":
            m = re.fullmatch(r"([A-Za-z]{3})\s*([0-9][0-9,]*(?:\.[0-9]+)?)", value)
            if not m:
                return "Please write it like USD 20,000."
            inv["amount"] = {"value": str(D(m.group(2).replace(",", "")).quantize(D("0.01"))), "currency": m.group(1).upper()}
        elif field == "payee_name":
            inv["payee"]["name"] = value
        elif field == "country":
            inv["payee"]["country"] = value.upper()
        elif field == "pan":
            if value.lower() in ("no pan", "no", "none"):
                a["pan"] = ""
            else:
                if not re.fullmatch(r"[A-Za-z]{5}[0-9]{4}[A-Za-z]", value):
                    return "That doesn't look like a PAN (5 letters, 4 digits, 1 letter). Try again or choose 'No PAN'."
                a["pan"] = s["masker"].mask(value.upper())  # keep only the token
        elif field == "remitter_name":
            s["masker"].remember_name(value)  # so the name is masked if it comes up later in chat
            a[field] = value
        elif field in ("prior_inr", "prior_usd"):
            n = parse_amount(value)
            if n is None or n < 0:
                return "Please type a number, for example 600000, 6 lakh or 0."
            if field == "prior_usd" and D(a.get("prior_inr", "0")) > 0:
                implied = D(a["prior_inr"]) / n if n else None
                if implied is None or not (D(50) <= implied <= D(150)):
                    return (f"That doesn't match the {inr(D(a['prior_inr']))} you sent: it would mean "
                            f"{'no dollars' if not n else f'{implied:.0f} rupees per dollar'}. "
                            "Please give the US dollar amount again.")
            a[field] = str(n)
            if field == "prior_inr" and n == 0:
                a["prior_usd"], a["prior_other"] = "0", "No"
            return None
        elif field == "relationship":
            a[field] = value.capitalize()
        elif field == "funding":
            if value.lower().startswith("own") or value.lower() == "self":
                a[field] = "self"
            elif "loan" in value.lower():
                a[field] = "loan"
            else:
                return "Please choose 'Own money' or 'Education loan'."
        elif field == "prior_other":
            if value.lower() not in ("yes", "no"):
                return "Please answer Yes or No."
            a[field] = value.capitalize()
        else:
            a[field] = value
        return None

    def set_document(self, sid, key, have):
        s = self.get(sid)
        if key not in {k for k, _, _ in CHECKLIST}:
            raise ValueError("unknown document")
        (s["documents"].add if have else s["documents"].discard)(key)
        self._log("document_marked", {"key": key, "have": bool(have)}, sid)
        if s["invoice"] is not None and self.pending_question(s) is None:
            self._compute(s, keep_quotes=True)
        return s

    # ---------- free chat ----------
    def chat(self, sid, text):
        s = self.get(sid)
        text = (text or "").strip()
        if not text:
            return s
        r = scan(text)
        q = self.pending_question(s)
        if r["action"] == "block":
            masked = s["masker"].mask(text)
            self._say(s, "user", masked)
            cats = [f["category"] for f in r["findings"] if f["severity"] == "high"]
            self._log("untrusted_text_flagged", {"source": "chat", "findings": r["findings"]}, sid)
            replies = []
            for c in cats:
                if c in CHAT_DENY_ACTION:
                    d = self._tool(s, CHAT_DENY_ACTION[c])
                    replies.append(f"Denied ({d.tier}): {REFUSALS[c]}")
                elif c in REFUSALS:
                    replies.append(f"Refused: {REFUSALS[c]}")
            self._say(s, "agent", " ".join(dict.fromkeys(replies)), tone="deny")
            if self.policy.frozen:
                self._say(s, "agent", "Too many denied attempts: the agent is now frozen. A parent must reset it "
                          "with the PIN in Settings.", tone="deny")
            return s
        if q is not None:
            return self.answer(sid, q["field"], text)
        masked = self._to_model(s, "chat", text)
        self._say(s, "user", masked)
        self._reply(s, masked.lower())
        return s

    def _reply(self, s, t):
        has = lambda *ws: any(w in t for w in ws)
        inv, trust = s["invoice"], s["trust"]
        if has("next", "what now", "what should", "do now"):
            n = self.next_action(s)
            self._say(s, "agent", f"{n['action']}. {n['why']}", tone="info")
        elif inv and has("due", "deadline"):
            self._say(s, "agent", f"Invoice {inv.get('invoice_id') or ''} is due on {inv['due_on']}." if inv.get("due_on")
                      else "The invoice has no due date; I'll ask rather than guess.", tone="info")
        elif trust and has("signature", "signed", "verified", "genuine", "fraud", "safe", "trust"):
            self._say(s, "agent", "The university's signature checks out: root, certificate and invoice all match, so the bank "
                      "details are the ones the university signed." if trust["verified"] else
                      f"Not verified: {trust.get('reason') or 'the signature chain failed'}. I will not pay this payee (T4: never).",
                      tone="ok" if trust["verified"] else "deny")
        elif s["ranked"] is None:
            self._say(s, "agent", "Upload an invoice first; then I can compare routes and explain every rupee.")
        elif s["draft"] and has("document", "paper", "a2", "form", "checklist"):
            miss = s["draft"]["missing_documents"]
            self._say(s, "agent", ("Still missing: " + "; ".join(miss) + ". Typical list; confirm with your bank.") if miss
                      else "All listed documents are marked as ready. Typical list; confirm with your bank.", tone="info")
        elif has("markup", "hidden", "fx", "exchange"):
            r = next((r for r in s["ranked"] if r["quote"]["quote_id"] == s["chosen_quote_id"]), s["ranked"][0])
            self._say(s, "agent", r["markup"]["text"] if r.get("markup") else f"{r['route']} shows no markup over the mid-market rate.",
                      tone="info")
        elif has("why", "cheap", "explain", "compare", "route"):
            self._say(s, "agent", s["explanation"]["shown"], tone="info")
        elif "tcs" in t or "tax" in t:
            best = s["ranked"][0]
            line = next(l for l in best["lines"] if l["label"] == "TCS")
            self._say(s, "agent", line["text"] + " This is not tax advice.", tone="info")
        elif "limit" in t or "lrs" in t:
            l = s["lrs"]
            self._say(s, "agent", f"Your LRS headroom before this payment is about USD {D(l['headroom_before_usd']):,.0f}, "
                      f"and after it USD {D(l['headroom_after_usd']):,.0f}.", tone="info")
        else:
            self._say(s, "agent", "I can explain the costs ('why'), hidden markup, TCS ('tax'), your yearly limit ('limit'), "
                      "the documents, the due date or what happens next. A parent approves the plan with the PIN.")

    # ---------- stage 5-7: rules, compare, plan ----------
    def _advance(self, s, ask=True):
        q = self.pending_question(s)
        if q is not None:
            if ask:
                self._say(s, "agent", q["text"], question=q["field"], options=q["options"])
            return s
        self._compute(s)
        return s

    def _amount_usd(self, inv):
        amt, cur = D(inv["amount"]["value"]), inv["amount"]["currency"]
        if cur == "USD":
            return amt, False
        return (amt * self.bank.mid_market(cur) / self.bank.mid_market("USD")).quantize(D("0.01")), True

    def _compute(self, s, keep_quotes=False):
        inv, a = s["invoice"], s["answers"]
        s["escalations"] = []
        try:
            validate(inv)
        except ContractError as e:
            s["escalations"].append({"code": "invalid_invoice", "text": f"The invoice is incomplete: {e}"})
        try:
            corridor = corridors.for_invoice(inv)
        except corridors.CorridorError as e:
            s["escalations"].append({"code": "corridor", "text": str(e)})
            self._say(s, "agent", f"I can't handle this invoice: {e}. A human needs to look at it.", tone="deny")
            self._log("escalated", {"reason": "corridor"}, s["id"])
            return s
        cur, foreign = inv["amount"]["currency"], D(inv["amount"]["value"])
        if not (keep_quotes and s["quotes"]):
            s["quotes"] = self.bank.quote_all(foreign, cur)
            s["chosen_quote_id"] = None
        self._tool(s, "compare_routes")
        funding, has_pan = a.get("funding", "self"), bool(a.get("pan"))
        # earlier this year = what the family declared + what they paid through TuitionPilot since
        paid = s["ytd"].usage(self.clock().date())
        prior_inr = D(a.get("prior_inr", "0")) + paid["inr"]
        prior_usd = D(a.get("prior_usd", "0")) + paid["usd"]
        s["prior_used"] = {"declared_inr": a.get("prior_inr", "0"), "paid_here_inr": str(paid["inr"]),
                           "total_inr": str(prior_inr), "total_usd": str(prior_usd)}
        kw = {"funding": funding, "prior_lrs_inr": prior_inr, "has_pan": has_pan,
              "prior_includes_other_purposes": a.get("prior_other") == "Yes",
              "on": self.clock().date(), "mid_market_rate": self.bank.mid_market(cur)}
        routes = [self.bank.route_of(q) for q in s["quotes"]]
        ranked = compare_routes(self.pack, routes, foreign, **kw)
        expl = explain_comparison(ranked, routes, foreign, cur)
        by_name = {q["route_name"]: q for q in s["quotes"]}
        s["ranked"] = []
        results = []
        for row, ex in zip(ranked, expl["routes"]):
            c = row["cost"]
            route = next(r for r in routes if r.name == c.route)
            mk = explain_markup(c, route, kw["mid_market_rate"], foreign, cur)
            results.append(landed_cost_result(self.pack, c, foreign))
            s["ranked"].append({"rank": row["rank"], "route": c.route, "quote": by_name[c.route],
                                "total_inr": str(c.total_inr), "total_display": inr(c.total_inr),
                                "saving_vs_next": None if row["saving_vs_next_inr"] is None else inr(row["saving_vs_next_inr"]),
                                "lines": ex["lines"], "markup": mk, "trace": jsonable(c.trace),
                                "needs_verification": c.needs_verification, "cost": c})
        usd, estimated = self._amount_usd(inv)
        lrs = lrs_headroom(self.pack, prior_usd, usd)
        results.append(lrs_result(self.pack, lrs, prior_usd, usd))
        s["lrs"] = {**jsonable(lrs), "amount_usd": str(usd), "estimated": estimated}
        s["warnings"] = list(ranked[0]["cost"].tcs.warnings)
        for w in s["warnings"]:
            self._say(s, "agent", "Check: " + w, tone="warn")
        # numbers the engine derived for the comparison (savings, per-component differences, quote terms)
        results.append({"outputs": {"why": [w["amount_inr"] for w in expl["why"]],
                                    "savings": [str(r["saving_vs_next_inr"]) for r in ranked if r["saving_vs_next_inr"] is not None],
                                    "quotes": [{k: q[k] for k in ("fx_rate", "fee_inr", "gst_rate")} for q in s["quotes"]]}})
        s["explanation"] = {**ground_or_replace(self.model.explain([{"text": expl["summary"]}] + expl["why"]), results,
                                                " ".join([expl["summary"]] + [w["text"] for w in expl["why"]])),
                            "summary": expl["summary"], "why": expl["why"]}
        self._log("tool_call", {"tool": "compare_routes", "tier": "T1", "routes": len(ranked),
                                "cheapest": ranked[0]["cost"].route, "grounded": s["explanation"]["grounded"]}, s["id"])
        if s["chosen_quote_id"] not in [q["quote_id"] for q in s["quotes"]]:
            s["chosen_quote_id"] = s["ranked"][0]["quote"]["quote_id"]  # default: cheapest

        # escalations: the agent stops and hands over to a human
        reg = s["trust"] or {"verified": False, "mismatch": ["signature"], "reason": "not checked"}
        if not reg["verified"]:
            s["escalations"].append({"code": "unverified_payee", "text":
                f"The invoice could not be verified ({reg['reason']}). Paying an unverified payee is tier T4: "
                "never allowed. Call the university on a number from its official website before doing anything."})
        if not lrs.within_cap:
            s["escalations"].append({"code": "lrs_cap", "text":
                f"This payment would take you above the LRS limit of USD {lrs.cap_usd:,.0f} for the year "
                f"(headroom left: USD {lrs.headroom_before_usd:,.0f}). Stopped."})
        if usd > self.policy.per_payment_cap_usd:
            s["escalations"].append({"code": "over_cap", "text":
                f"USD {usd:,.2f} is above the per-payment cap of USD {self.policy.per_payment_cap_usd:,.0f}. "
                "A parent must raise the cap in PIN-protected settings, or split the payment."})

        chosen = self._chosen(s)
        reg_entry_mismatch = reg["mismatch"] if not reg["verified"] else []
        s["draft"] = build_a2_draft(inv, {"name": a.get("remitter_name"), "pan": a.get("pan") or None,
                                          "relationship": a.get("relationship"), "address": "On file (synthetic)"},
                                    corridor, funding=funding, landed=chosen["cost"], documents=s["documents"],
                                    registry_mismatch=reg_entry_mismatch)
        s["draft"]["sections"]["remitter"]["pan"] = display_pan(a.get("pan"), s["masker"]) or "[no PAN]"
        self._tool(s, "draft_form")
        self._build_plan(s)
        if s["escalations"]:
            for e in s["escalations"]:
                self._say(s, "agent", "Needs a human: " + e["text"], tone="deny")
            self._log("escalated", {"codes": [e["code"] for e in s["escalations"]]}, s["id"])
        else:
            self._say(s, "agent", f"Done. {expl['summary']} The A2-style draft and plan are ready. "
                      "Open 'Compare' to see every rupee, then 'Approve' for the parent's PIN.", tone="ok")
        return s

    def _chosen(self, s):
        return next(r for r in s["ranked"] if r["quote"]["quote_id"] == s["chosen_quote_id"])

    def choose_route(self, sid, quote_id):
        s = self.get(sid)
        if s["ranked"] is None or quote_id not in [r["quote"]["quote_id"] for r in s["ranked"]]:
            raise ValueError("unknown quote")
        s["chosen_quote_id"] = quote_id
        self._log("route_chosen", {"quote_id": quote_id, "route": self._chosen(s)["route"]}, sid)
        return self._compute(s, keep_quotes=True)

    def refresh_quotes(self, sid):
        s = self.get(sid)
        if s["invoice"] is None or self.pending_question(s) is not None:
            raise ValueError("nothing to quote yet")
        return self._compute(s)

    def whatif(self, sid, prior_inr=None, funding=None, has_pan=None):
        """Recompute TCS and every route's total for other answers. Read-only (T1): changes nothing in the plan."""
        s = self.get(sid)
        if not s["quotes"]:
            raise ValueError("nothing to compare yet")
        inv, a = s["invoice"], s["answers"]
        cur, foreign = inv["amount"]["currency"], D(inv["amount"]["value"])
        prior = D(s["prior_used"]["total_inr"]) if prior_inr is None else parse_amount(prior_inr)
        if prior is None or prior < 0:
            raise ValueError("earlier remittances must be a number")
        funding = a.get("funding", "self") if funding is None else funding
        has_pan = bool(a.get("pan")) if has_pan is None else bool(has_pan)
        routes = [self.bank.route_of(q) for q in s["quotes"]]
        ranked = compare_routes(self.pack, routes, foreign, funding=funding, prior_lrs_inr=prior, has_pan=has_pan,
                                on=self.clock().date(), mid_market_rate=self.bank.mid_market(cur))
        best = ranked[0]["cost"]
        return {"inputs": {"prior_inr": str(prior), "funding": funding, "has_pan": has_pan},
                "cheapest": best.route, "tcs_sentence": tcs_sentence(best.tcs), "warnings": best.tcs.warnings,
                "routes": [{"route": r["cost"].route, "total_inr": str(r["cost"].total_inr),
                            "remitted_inr": str(r["cost"].remitted_inr), "fee_inr": str(r["cost"].fee_inr),
                            "gst_inr": str(r["cost"].gst_inr), "tcs_inr": str(r["cost"].tcs.tcs),
                            "taxable_inr": str(r["cost"].tcs.taxable_base)} for r in ranked],
                "label": "What-if only: your plan and approval are unchanged."}

    def _build_plan(self, s):
        inv, chosen = s["invoice"], self._chosen(s)
        reg = s["trust"] or {"verified": False}
        s["plan_seq"] += 1
        pay_tool = "sandbox_pay" if reg["verified"] else "pay_unverified_payee"
        steps = [
            {"n": 1, "action": "Read invoice", "tool": "read_invoice", "tier": "T0",
             "inputs": {"invoice_id": inv.get("invoice_id", "")}},
            {"n": 2, "action": "Verify the university's signature and certificate", "tool": "check_payee", "tier": "T0",
             "inputs": {"registry_id": inv["payee"].get("registry_id", "")}},
            {"n": 3, "action": "Compute TCS, LRS headroom and compare routes", "tool": "compare_routes", "tier": "T1",
             "inputs": {"foreign_amount": inv["amount"]["value"], "currency": inv["amount"]["currency"]}},
            {"n": 4, "action": "Draft A2-style form and checklist", "tool": "draft_form", "tier": "T1",
             "inputs": {"form": "A2-style draft"}},
            {"n": 5, "action": f"Pay in sandbox bank via {chosen['route']}", "tool": pay_tool,
             "tier": "T3" if reg["verified"] else "T4",
             "inputs": {"quote_id": chosen["quote"]["quote_id"], "amount": inv["amount"]["value"],
                        "currency": inv["amount"]["currency"], "payee_registry_id": inv["payee"].get("registry_id", ""),
                        "total_inr": chosen["total_inr"]}},
        ]
        plan = {"type": "plan", "contract_version": "1.1", "plan_id": f"PLAN-{s['id'][:6].upper()}-{s['plan_seq']}",
                "created_at": self.clock().isoformat(timespec="seconds"),
                "goal": f"Pay {inv.get('invoice_id', 'the invoice')} tuition via {chosen['route']}",
                "steps": steps, "max_tier": max(st["tier"] for st in steps)}
        plan["plan_hash"] = plan_hash(plan)
        validate(plan)
        if s["approval"] and s["approval"]["plan_hash"] != plan["plan_hash"]:
            self._log("approval_void", {"reason": "plan changed", "old": s["approval"]["plan_hash"]}, s["id"])
            self._say(s, "agent", "The plan changed, so the earlier approval no longer counts.", tone="warn")
            s["approval"] = None
        s["plan"] = plan
        self._log("plan_built", {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"],
                                 "max_tier": plan["max_tier"]}, s["id"])

    # ---------- devices, sign-in, vault ----------
    def register_device(self, pin, role, public_key, box_key, label="", code=None):
        """Bootstrap (first parent device, PIN only) or finish a request a parent device signed (code + PIN)."""
        d = self.family.finish_enrolment(pin, code) if code else self.family.register(pin, role, public_key, box_key, label)
        self._log("device_registered" if d.allowed else "device_refused", {**d.to_dict(), "role": role})
        return d

    def request_device(self, role, public_key, box_key, label=""):
        code = self.family.request_enrolment(role, public_key, box_key, label)
        self._log("device_requested", {"role": role, "code": code})
        return code

    def approve_device(self, sid, code, signature):
        """A signed-in parent device signs a new device's enrolment request."""
        s = self.get(sid)
        if s["role"] != "parent" or not s["device"]:
            raise PermissionError("Only a signed-in parent device can approve a new device.")
        try:
            self.family.approve_enrolment(code, s["device"], signature)
        except PermissionError as e:
            self._log("device_approval_refused", {"code": str(code)[:12], "reason": str(e)}, sid)
            raise
        self._log("device_approved", {"code": str(code)[:12], "approver": s["device"]}, sid)

    # ---------- student prepares, parent signs ----------
    def request_parent(self, sid):
        """A signed-in student hands a prepared payment to the parents. Only a parent device can then open it."""
        s = self.get(sid)
        if s["role"] != "student" or not s["device"]:
            raise PermissionError("Only a signed-in student device can ask a parent to sign.")
        if s["plan"] is None:
            raise ValueError("finish the invoice and the questions first")
        if not any(v == sid for v in self.handoffs.values()):
            self.handoffs[uuid.uuid4().hex[:10]] = sid
        self._log("handoff_requested", {"plan_id": s["plan"]["plan_id"], "plan_hash": s["plan"]["plan_hash"]}, sid)
        self._say(s, "agent", "Sent to your parents: a signed-in parent device can now open this payment, review it and "
                  "sign. This device can't sign or pay.", tone="ok")
        return {"ok": True}

    def handoff_list(self, s):
        """What a signed-in parent sees: payments students prepared (no session ids)."""
        if s["role"] != "parent" or not s["device"]:
            return []
        out = []
        for code, sid in list(self.handoffs.items()):
            t = self.sessions.get(sid)
            if t is None or t["plan"] is None:
                del self.handoffs[code]
                continue
            out.append({"code": code, "invoice_id": t["invoice"].get("invoice_id"),
                        "amount": f"{t['invoice']['amount']['currency']} {D(t['invoice']['amount']['value']):,.2f}",
                        "payee": t["invoice"]["payee"].get("name"), "student_device": t["device"]})
        return out

    def take_over(self, sid, code):
        """A signed-in parent opens a student's prepared payment. It moves to a NEW session id, so the student's old id
        stops working and can never act with the parent's role."""
        parent = self.get(sid)
        if parent["role"] != "parent" or not parent["device"]:
            raise PermissionError("Only a signed-in parent device can open a student's payment.")
        old = self.handoffs.pop(str(code), None)
        s = self.sessions.pop(old, None) if old else None
        if s is None:
            raise KeyError("no such request, or it was already opened")
        new, student_device = uuid.uuid4().hex[:12], s["device"]
        s.update(id=new, role="parent", signed_in="parent", device=parent["device"], approval=None)
        self.sessions[new] = s
        self._log("handoff_taken", {"from_student_device": student_device, "parent_device": parent["device"]}, new)
        self._say(s, "agent", "A parent opened this payment. Review the plan, then sign it on this device.", tone="ok")
        self._build_plan(s)  # a fresh plan id for the parent's review; the hash covers the same exact plan content
        return {"ok": True, "session": new}

    def sign_in(self, nonce, kid, signature):
        """A new session for the device that signed the server's one-time challenge."""
        try:
            role, kid = self.family.sign_in(nonce, kid, signature)
        except PermissionError as e:
            self._log("sign_in_refused", {"key_id": str(kid)[:40], "reason": str(e)})
            raise
        s = self.new_session(role)
        s["device"] = kid
        self._log("signed_in", {"role": role, "key_id": kid}, s["id"])
        return s

    def _device(self, s):
        if not s["device"]:
            raise PermissionError("Sign in with an enrolled device to use the vault.")
        return s["device"]

    def vault_put(self, sid, doc):
        s = self.get(sid)
        meta = self.family.put(self._device(s), doc or {})
        self._log("vault_upload", {"doc_id": meta["doc_id"], "size": meta["size"], "shared_with": meta["shared_with"]}, sid)
        return meta

    def vault_list(self, sid):
        s = self.get(sid)
        return self.family.list_for(self._device(s))

    def vault_get(self, sid, doc_id):
        s = self.get(sid)
        doc = self.family.get_for(self._device(s), doc_id)
        self._log("vault_open", {"doc_id": doc_id, "note": "ciphertext sent; only this device can decrypt"}, sid)
        return doc

    # ---------- stage 8-11: policy gate, approve, execute, record ----------
    def register_parent_key(self, pin, public_key_b64, label="parent device"):
        """Enrol the parent's device key (made and kept on the device). Needs the PIN."""
        d = self.policy.register_parent_key(pin, public_key_b64, label)
        self._log("parent_key_registered" if d.allowed else "settings_change", d.to_dict())
        return d

    def approve(self, sid, pin, approval=None):
        """approval: the approval message signed on the parent's device. The agent cannot make or change it."""
        s = self.get(sid)
        if s["plan"] is None:
            raise ValueError("no plan to approve yet")
        if s["role"] != "parent":
            self._log("approval_refused", {"reason": "student role"}, sid)
            return {"ok": False, "code": "role", "reason": "Only the parent can approve. Switch to the parent view."}
        if s["plan"]["max_tier"] == "T4":
            d = self._tool(s, s["plan"]["steps"][-1]["tool"])
            return {"ok": False, "code": d.code, "reason": d.reason}
        if s["escalations"]:
            self._log("approval_refused", {"reason": "escalated", "codes": [e["code"] for e in s["escalations"]]}, sid)
            return {"ok": False, "code": "escalated",
                    "reason": "This plan needs a human first: " + " ".join(e["text"] for e in s["escalations"])}
        if self.policy.frozen:
            self._log("approval_refused", {"reason": "circuit breaker"}, sid)
            return {"ok": False, "code": "circuit_breaker", "reason": "The agent is frozen. A parent must reset it with the PIN."}
        if not self.policy.verify_pin(pin):
            self.policy._count_denial("T3")
            self._log("approval_refused", {"reason": "wrong PIN", "denied_in_a_row": self.policy.denied_in_a_row}, sid)
            return {"ok": False, "code": "bad_pin", "reason": "Wrong PIN." + (" The agent is now frozen." if self.policy.frozen else "")}
        p = s["plan"]
        refuse = None
        if not self.policy.parent_keys:
            refuse = ("no_parent_key", "No parent device is set up to sign. Set it up first (needs the PIN).")
        elif not isinstance(approval, dict):
            refuse = ("unsigned_approval", "The approval must be signed on the parent's device.")
        else:
            try:
                validate(approval)
            except ContractError as e:
                refuse = ("invalid_message", f"The approval is malformed: {e}")
        if refuse is None and (approval["plan_id"] != p["plan_id"] or approval["plan_hash"] != p["plan_hash"]):
            refuse = ("plan_changed", "The signed approval is for a different plan than the one now on file.")
        if refuse is None and not verify_approval(approval, self.policy.parent_keys):
            refuse = ("bad_signature", "The approval's signature does not verify against the parent's registered key.")
        if refuse is None and (approval["decision"] != "approved" or approval["approver"]["role"] != "parent"
                               or approval["method"] != "pin" or approval["tier"] != p["max_tier"]):
            refuse = ("invalid_approval", "The signed approval does not approve this plan's tier as the parent.")
        if refuse:
            if refuse[0] != "no_parent_key":  # setting up a device is not an attack
                self.policy._count_denial("T3")
            self._log("approval_refused", {"reason": refuse[1]}, sid)
            return {"ok": False, "code": refuse[0], "reason": refuse[1]}
        s["approval"] = approval
        self._log("approved", {"approval_id": approval["approval_id"], "plan_hash": p["plan_hash"],
                               "key_id": approval["signature"]["key_id"]}, sid)
        self._say(s, "agent", f"Approved: the parent's device signed plan {p['plan_hash'][7:19]}… with key "
                  f"{approval['signature']['key_id'][8:]}. I cannot change the plan without breaking that signature.", tone="ok")
        return {"ok": True}

    def pay(self, sid):
        s = self.get(sid)
        if s["plan"] is None:
            raise ValueError("no plan to pay yet")
        if s["txn"] and s["approval"] and s["txn"]["plan_hash"] == s["plan"]["plan_hash"]:
            self._log("duplicate_click", {"txn_id": s["txn"]["txn_id"]}, sid)
            return {"ok": True, "duplicate": True, "txn": s["txn"]}
        chosen, inv = self._chosen(s), s["invoice"]
        usd, _ = self._amount_usd(inv)
        d = self._tool(s, s["plan"]["steps"][-1]["tool"], plan=s["plan"], approval=s["approval"],
                       payee_verified=bool(s["trust"] and s["trust"]["verified"]), amount_usd=usd)
        if not d.allowed:
            self._say(s, "agent", f"Payment denied ({d.tier}): {d.reason}", tone="deny")
            return {"ok": False, "code": d.code, "reason": d.reason}
        if not s["lrs"]["within_cap"]:  # the agent's own LRS stop, on top of the policy gate
            self._log("payment_refused", {"reason": "lrs_cap"}, sid)
            return {"ok": False, "code": "lrs_cap", "reason": "Above the yearly LRS limit."}
        try:
            txn = self.bank.execute(approval_id=s["approval"]["approval_id"], quote_id=chosen["quote"]["quote_id"],
                                    payee=inv["payee"], total_inr=chosen["total_inr"], plan_hash=s["plan"]["plan_hash"],
                                    payee_certificate=s["payee_certificate"])
        except BankError as e:
            self._log("bank_refused", {"reason": str(e)}, sid)
            self._say(s, "agent", f"The sandbox bank refused: {e}.", tone="deny")
            return {"ok": False, "code": "bank", "reason": str(e)}
        s["txn"] = txn
        usd_paid, _ = self._amount_usd(inv)
        s["ytd"].add(self.clock().date(), "education", chosen["cost"].remitted_inr, usd_paid, s["answers"].get("funding", "self"))
        entry = self._log("payment_executed", {"txn_id": txn["txn_id"], "debit_inr": txn["debit_inr"],
                                               "payee": txn["payee_registry_id"], "plan_hash": txn["plan_hash"]}, sid)
        s["receipt"] = self._receipt(s, entry["hash"])
        self._log("receipt_written", {"receipt_id": s["receipt"]["receipt_id"]}, sid)
        self._say(s, "agent", f"Paid in the sandbox: {inr(D(txn['debit_inr']))} debited, transaction {txn['txn_id']}. "
                  "Your decision receipt is ready.", tone="ok")
        return {"ok": True, "txn": txn}

    def _receipt(self, s, audit_hash):
        chosen, a = self._chosen(s), s["answers"]
        return {
            "receipt_id": f"RCPT-{s['txn']['txn_id'][4:]}",
            "issued_at": self.clock().isoformat(timespec="seconds"),
            "labels": ["Synthetic data", "Sandbox only: no real money moved", "Not tax advice", "Not RBI-approved"],
            "inputs_masked": {"invoice_id": s["invoice"]["invoice_id"], "payee": s["invoice"]["payee"]["name"],
                              "payee_registry_id": s["invoice"]["payee"]["registry_id"],
                              "amount": f"{s['invoice']['amount']['currency']} {s['invoice']['amount']['value']}",
                              "remitter_pan": display_pan(a.get("pan"), s["masker"]) or "none",
                              "funding": a.get("funding"), "prior_lrs_inr": a.get("prior_inr")},
            "route": chosen["route"], "provider": chosen["quote"]["provider"],
            "lines": [{"label": l["label"], "amount_inr": l["amount_inr"]} for l in chosen["lines"]],
            "rules_used": [{"rule_id": t["rule_id"], "pack_version": t["pack_version"], "status": t["status"]}
                           for t in chosen["trace"]],
            "needs_verification": chosen["needs_verification"],
            "plan_id": s["plan"]["plan_id"], "plan_hash": s["plan"]["plan_hash"],
            "approval": {k: s["approval"][k] for k in ("approval_id", "method", "decided_at")} | {"role": "parent"}
                        | {"signed_by": s["approval"]["signature"]["key_id"], "signature": s["approval"]["signature"]["value"]},
            "payee_certificate": s["payee_certificate"]["certificate"]["serial"],
            "txn_id": s["txn"]["txn_id"], "audit_entry_hash": audit_hash,
        }

    # ---------- demo controls, settings, privacy ----------
    def tamper_plan(self, sid):
        """Demo of an attack: change the payment amount after approval (and recompute the plan's own hash)."""
        s = self.get(sid)
        p = json.loads(json.dumps(s["plan"]))
        p["steps"][-1]["inputs"]["amount"] = str(D(p["steps"][-1]["inputs"]["amount"]) + 5000)
        p["plan_hash"] = plan_hash(p)
        s["plan"] = p
        self._log("plan_tampered_demo", {"new_plan_hash": p["plan_hash"]}, sid)
        self._say(s, "agent", "Demo: someone changed the payment amount in the plan after approval.", tone="warn")
        return s

    def settings(self, pin, **changes):
        d = self.policy.change_settings(pin, **changes)
        self._log("settings_change", d.to_dict())
        return d

    def delete_data(self, sid):
        self.get(sid)
        del self.sessions[sid]
        self._log("session_deleted", {"note": "session data and masking vault removed"}, sid)
        return {"ok": True}

    def tamper_audit_demo(self):
        """Demo of an attack on the audit log: quietly edit an old entry."""
        if len(self.audit.entries) < 2:
            raise ValueError("audit log too short")
        e = self.audit.entries[1]
        e["data"] = {**e["data"], "tampered": True}
        return self.audit.verify()

    # ---------- view for the UI ----------
    def timeline(self, s):
        done = {
            "Intake": s["invoice"] is not None, "Mask": bool(s["model_saw"]), "Extract": s["invoice"] is not None,
            "Validate": s["trust"] is not None, "Rules": s["lrs"] is not None, "Compare": s["ranked"] is not None,
            "Plan": s["plan"] is not None, "Policy gate": s["txn"] is not None, "Approve": s["approval"] is not None,
            "Execute (sandbox)": s["txn"] is not None, "Record": s["receipt"] is not None, "Track": s["receipt"] is not None,
        }
        blocked = bool(s["escalations"])
        out, active_set = [], False
        for i, name in enumerate(STAGES, 1):
            if done[name]:
                st = "done"
            elif blocked and name in ("Policy gate", "Approve") and not active_set:
                st, active_set = "blocked", True
            elif not active_set:
                st, active_set = "active", True
            else:
                st = "pending"
            out.append({"n": i, "name": name, "status": st})
        return out

    def view(self, sid):
        s = self.get(sid)
        sid_events = [e for e in self.audit.entries if e["session"] == sid]
        ranked = None
        if s["ranked"]:
            ranked = [{k: v for k, v in r.items() if k != "cost"} for r in s["ranked"]]
        return jsonable({
            "id": s["id"], "role": s["role"], "consent": s["consent"], "signed_in": s["signed_in"], "device": s["device"],
            "invoice": s["invoice"], "uncertain": s["uncertain"], "invoice_scan": s["invoice_scan"],
            "trust": s["trust"] and {k: v for k, v in s["trust"].items() if k != "certificate"},
            "question": self.pending_question(s), "next": self.next_action(s), "chat": s["chat"], "flags": s["flags"],
            "escalations": s["escalations"], "warnings": s["warnings"], "prior_used": s["prior_used"],
            "ranked": ranked, "chosen_quote_id": s["chosen_quote_id"],
            "explanation": s.get("explanation"), "lrs": s["lrs"], "draft": s["draft"], "plan": s["plan"],
            "plan_hash_now": plan_hash(s["plan"]) if s["plan"] else None,
            "approval": s["approval"], "txn": s["txn"], "receipt": s["receipt"],
            "handoffs": self.handoff_list(s), "handoff_sent": any(v == sid for v in self.handoffs.values()),
            "documents": sorted(s["documents"]), "model_saw": s["model_saw"][-10:],
            "timeline": self.timeline(s), "policy": self.policy.status(),
            "events": [{"seq": e["seq"], "at": e["at"][11:19], "event": e["event"], "data": e["data"],
                        "hash": e["hash"][:12]} for e in sid_events[-40:]],
            "audit": {**self.audit.verify(), "head": self.audit.head[:16]},
            "balance_inr": str(self.bank.account["balance_inr"]),
            "pack": {"id": self.pack.data["pack_id"], "version": self.pack.version},
            "model": self.model.name,
            "samples": sorted(p.stem for p in SAMPLES.glob("*.txt")),
        })
