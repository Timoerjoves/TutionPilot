"""Sandbox bank, policy engine, audit log, signed-invoice checks, invoice reader and the agent flow."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal as D
from pathlib import Path

from agent.agent import Agent, parse_amount
from agent.model import OfflineModel, json_to_text
from app import audit
from app.policy import Policy
from app.sandbox import BankError, SandboxBank, now_ist
from contract import plan_hash, validate
from scenarios import fixtures as fx
from security.pki import TrustStore, split

ROOT = Path(__file__).resolve().parent.parent
PIN = json.loads((ROOT / "app" / "demo_config.json").read_text(encoding="utf-8"))["demo_pin"]
FAMILY = [("remitter_name", "Ravi Parent (synthetic)"), ("pan", fx.SYN_PAN), ("relationship", "Father"),
          ("funding", "Own money"), ("prior_inr", "0")]


def plan_and_approval(**approval_changes):
    """The sample plan and an approval of it signed by the (simulated) parent device."""
    plan = fx.load_sample("plan")
    return plan, fx.parent_approval(plan, **approval_changes)


def signed_sample(name="valid_us"):
    return split((ROOT / "data" / "invoices" / f"{name}.txt").read_text(encoding="utf-8"))[1]


class TestInvoiceReader(unittest.TestCase):
    def test_every_sample_invoice_is_read(self):
        for f in sorted((ROOT / "data" / "invoices").glob("*.txt")):
            with self.subTest(invoice=f.name):
                inv, _ = OfflineModel().extract(split(f.read_text(encoding="utf-8"))[0])
                self.assertTrue(inv["invoice_id"].startswith("INV-SYN-"))
                if f.stem != "missing_due_date":
                    validate(inv)

    def test_valid_invoice_matches_sample_message(self):
        inv, uncertain = OfflineModel().extract(split((ROOT / "data/invoices/valid_us.txt").read_text(encoding="utf-8"))[0])
        sample = fx.load_sample("invoice")
        self.assertEqual(inv["amount"], sample["amount"])
        self.assertEqual(inv["payee"], sample["payee"])
        self.assertEqual(uncertain, [])

    def test_non_iso_date_is_flagged_uncertain(self):
        inv, uncertain = OfflineModel().extract("Invoice No: X-1\nDue date: 15 Nov 2026")
        self.assertEqual(inv["due_on"], "2026-11-15")
        self.assertIn("due_on", uncertain)

    def test_json_invoice_files_are_read(self):
        sample = fx.load_sample("invoice")
        for f in sorted((ROOT / "data" / "invoices").glob("INV-*.json")) + [ROOT / "data/samples/invoice.json"]:
            with self.subTest(invoice=f.name):
                text, obj = json_to_text(f.read_text(encoding="utf-8"))
                self.assertNotIn("attestation", text)  # the signature block never reaches the model
                inv, uncertain = OfflineModel().extract(text)
                self.assertEqual((inv["invoice_id"], inv["amount"], inv["payee"]),
                                 (obj["invoice_id"], obj["amount"], obj["payee"]))
                self.assertEqual(uncertain, [])
        self.assertEqual(json_to_text(json.dumps(sample))[1]["payee"], sample["payee"])

    def test_json_invoice_with_other_key_names(self):
        text, _ = json_to_text('[{"invoiceId": "X-9", "dueDate": "2026-11-15", "university": {"name": "U", '
                               '"country": "gb", "bankDetails": {"swiftCode": "AB", "accountNumber": "XX12"}}, '
                               '"totalDue": {"amount": 1234.5, "currency": "GBP"}}]')
        inv, _ = OfflineModel().extract(text)
        self.assertEqual(inv["invoice_id"], "X-9")
        self.assertEqual(inv["amount"], {"value": "1234.50", "currency": "GBP"})
        self.assertEqual(inv["payee"], {"name": "U", "country": "GB", "bank": {"swift": "AB", "account_masked": "XX12"}})

    def test_bad_json_is_refused(self):
        for bad in ("{not json", "[1, 2]", "[]"):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                json_to_text(bad)

    def test_parse_amount(self):
        self.assertEqual(parse_amount("6,00,000"), 600000)
        self.assertEqual(parse_amount("6 lakh"), 600000)
        self.assertEqual(parse_amount("0"), 0)
        self.assertIsNone(parse_amount("lots"))


class TestSignedInvoices(unittest.TestCase):
    def test_sample_invoices(self):
        t = TrustStore()
        expect = {"valid_us": None, "valid_uk": None, "injected": None, "over_cap": None, "missing_due_date": None,
                  "tampered_bank": "changed after", "unknown_payee": "not issued by", "revoked_key": "revoked",
                  "unsigned": "not signed"}
        for name, why in expect.items():
            with self.subTest(invoice=name):
                r = t.check_invoice(signed_sample(name))
                self.assertEqual(r["verified"], why is None, r["reason"])
                if why:
                    self.assertIn(why, r["reason"])


class TestSandboxBank(unittest.TestCase):
    def setUp(self):
        self.trust = TrustStore()
        self.bank = SandboxBank(self.trust)
        self.cert = signed_sample()["attestation"]["certificate"]
        self.q = self.bank.quote_all(D("20000"), "USD")

    def test_quotes_are_valid_contract_messages(self):
        self.assertEqual([q["route_name"] for q in self.q], ["Provider A", "Provider B", "Provider C"])
        for q in self.q:
            validate(q)

    def test_execute_debits_once_per_approval(self):
        args = dict(approval_id="APR-1", quote_id=self.q[1]["quote_id"], payee=fx.invoice()["payee"],
                    total_inr="1823080.00", plan_hash="sha256:x", payee_certificate=self.cert)
        t1, t2 = self.bank.execute(**args), self.bank.execute(**args)
        self.assertEqual(t1, t2)
        self.assertEqual(len(self.bank.ledger), 1)
        self.assertEqual(self.bank.account["balance_inr"], D("5000000") - D("1823080"))

    def test_bank_refuses_unverified_payee_expired_quote_and_overdraft(self):
        base = dict(quote_id=self.q[0]["quote_id"], total_inr="1.00", plan_hash="sha256:x", payee_certificate=self.cert)
        with self.assertRaises(BankError):
            self.bank.execute(approval_id="A", payee=fx.tampered_invoice()["payee"], **base)
        with self.assertRaises(BankError):
            self.bank.execute(approval_id="A2", payee=fx.invoice()["payee"], **{**base, "payee_certificate": None})
        with self.assertRaises(BankError):
            self.bank.execute(approval_id="B", payee=fx.invoice()["payee"], **{**base, "total_inr": "99999999"})
        later = SandboxBank(self.trust, clock=lambda: now_ist() + timedelta(hours=2))
        later.quotes = self.bank.quotes
        with self.assertRaises(BankError):
            later.execute(approval_id="C", payee=fx.invoice()["payee"], **base)


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.p = Policy(PIN)
        self.p.register_parent_key(PIN, fx.PARENT_PUBLIC)

    def test_low_tiers_need_no_approval(self):
        self.assertTrue(self.p.check("read_invoice").allowed)
        self.assertTrue(self.p.check("compare_routes").allowed)

    def test_t4_is_never_allowed(self):
        for action in ("add_payee", "raise_limit", "skip_approval", "change_own_limits", "launch_rockets"):
            self.assertFalse(self.p.check(action).allowed)

    def test_valid_pin_approval_of_exact_plan_allowed(self):
        plan, approval = plan_and_approval()
        self.assertTrue(self.p.check("sandbox_pay", plan=plan, approval=approval, payee_verified=True, amount_usd=20000).allowed)

    def test_denials(self):
        plan, approval = plan_and_approval()
        edited = json.loads(json.dumps(plan))
        edited["steps"][3]["inputs"]["amount"] = "25000.00"
        edited["plan_hash"] = plan_hash(edited)
        cases = {
            "plan_changed": dict(plan=edited, approval=approval, payee_verified=True),
            "pin_required": dict(plan=plan, approval=fx.parent_approval(plan, method="click"), payee_verified=True),
            "role": dict(plan=plan, approval=fx.parent_approval(plan, approver={"role": "student"}), payee_verified=True),
            "bad_signature": dict(plan=plan, approval={**approval, "tier": "T1"}, payee_verified=True),
            "unverified_payee": dict(plan=plan, approval=approval, payee_verified=False),
            "over_cap": dict(plan=plan, approval=approval, payee_verified=True, amount_usd=60000),
            "no_approval": dict(plan=plan, approval=None, payee_verified=True),
        }
        for code, kw in cases.items():
            with self.subTest(code=code):
                p = Policy(PIN)
                p.register_parent_key(PIN, fx.PARENT_PUBLIC)
                self.assertEqual(p.check("sandbox_pay", **kw).code, code)

    def test_parent_key_needs_pin_and_a_real_key(self):
        p = Policy(PIN)
        self.assertFalse(p.register_parent_key("0000", fx.PARENT_PUBLIC).allowed)
        self.assertEqual(p.register_parent_key(PIN, "bm90IGEga2V5").code, "bad_key")
        self.assertTrue(p.register_parent_key(PIN, fx.PARENT_PUBLIC).allowed)

    def test_settings_need_pin_and_breaker_freezes(self):
        self.assertFalse(self.p.change_settings("0000", emergency_stop=True).allowed)
        self.assertFalse(self.p.emergency_stop)
        for _ in range(2):
            self.p.check("raise_limit")
        self.assertTrue(self.p.frozen)  # wrong PIN + 2 denials = 3 in a row
        plan, approval = plan_and_approval()
        self.assertEqual(self.p.check("sandbox_pay", plan=plan, approval=approval, payee_verified=True).code, "circuit_breaker")
        self.assertTrue(self.p.change_settings(PIN, reset_breaker=True).allowed)
        self.assertFalse(self.p.frozen)


class TestAuditLog(unittest.TestCase):
    def test_chain_verifies_and_detects_edit_delete_reorder(self):
        log = audit.AuditLog()
        for i in range(4):
            log.append("event", {"i": i})
        self.assertTrue(log.verify()["ok"])
        edited = json.loads(json.dumps(log.entries))
        edited[1]["data"]["i"] = 99
        self.assertEqual(audit.verify(edited)["first_bad_seq"], 2)
        self.assertFalse(audit.verify(log.entries[:1] + log.entries[2:])["ok"])
        self.assertFalse(audit.verify([log.entries[1], log.entries[0]] + log.entries[2:])["ok"])

    def test_verify_command(self):
        with tempfile.TemporaryDirectory() as d:
            log = audit.AuditLog(Path(d) / "a.jsonl")
            log.append("x")
            log.append("y")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(audit.main(["verify", str(log.path)]), 0)
                self.assertEqual(audit.main(["bad"]), 2)
            self.assertIn("OK: 2 entries", out.getvalue())


class TestAgentFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Agent(evidence_dir=self.tmp.name)
        self.a.register_parent_key(PIN, fx.PARENT_PUBLIC)
        self.sid = self.a.new_session("parent")["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def approve(self, pin=PIN):
        return self.a.approve(self.sid, pin, fx.parent_approval(self.a.get(self.sid)["plan"]))

    def complete(self, sample="valid_us"):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample=sample)
        for field, value in FAMILY:
            self.a.answer(self.sid, field, value)

    def test_signed_json_invoice_upload_is_verified(self):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, text=(ROOT / "data/samples/invoice.json").read_text(encoding="utf-8"))
        for field, value in FAMILY:
            self.a.answer(self.sid, field, value)
        s = self.a.get(self.sid)
        self.assertTrue(s["trust"]["verified"])
        self.assertEqual(s["escalations"], [])
        self.assertIsNotNone(s["plan"])

    def test_canada_and_australia_corridors_end_to_end(self):
        import corridors
        self.assertEqual(corridors.available(), ["IN-AU", "IN-CA", "IN-GB", "IN-US"])
        for sample, currency, visa in (("valid_ca", "CAD", "Designated Learning Institution"), ("valid_au", "AUD", "Confirmation of Enrolment")):
            with self.subTest(sample=sample):
                self.sid = self.a.new_session("parent")["id"]
                self.complete(sample)
                s = self.a.get(self.sid)
                self.assertTrue(s["trust"]["verified"])
                self.assertEqual(s["escalations"], [])
                self.assertEqual(s["plan"]["steps"][-1]["inputs"]["currency"], currency)
                self.assertEqual(len(s["ranked"]), 3)
                self.assertIn(visa, json.dumps(s["draft"]))
                self.assertEqual(self.approve(), {"ok": True})
                self.assertTrue(self.a.pay(self.sid)["ok"])

    def test_consent_required_before_upload(self):
        with self.assertRaises(PermissionError):
            self.a.upload_invoice(self.sid, sample="valid_us")

    def test_questions_asked_in_order_then_plan_ready(self):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample="valid_us")
        asked = []
        for field, value in FAMILY:
            asked.append(self.a.pending_question(self.a.get(self.sid))["field"])
            self.a.answer(self.sid, field, value)
        self.assertEqual(asked, [f for f, _ in FAMILY])
        v = self.a.view(self.sid)
        self.assertEqual(v["ranked"][0]["route"], "Provider B")
        self.assertEqual(v["plan"]["max_tier"], "T3")
        self.assertEqual(v["explanation"]["source"], "model")
        json.dumps(v)

    def test_pan_never_stored_or_shown_raw(self):
        self.complete()
        v = json.dumps(self.a.view(self.sid))
        self.assertNotIn(fx.SYN_PAN, v)
        self.assertIn("ABXXX1234F", v)
        self.assertNotIn(fx.SYN_PAN, (Path(self.tmp.name) / "audit_log.jsonl").read_text(encoding="utf-8"))

    def test_student_cannot_approve(self):
        self.complete()
        self.a.set_role(self.sid, "student")
        self.assertEqual(self.approve()["code"], "role")

    def test_full_payment_writes_receipt_ledger_and_audit(self):
        self.complete()
        self.assertTrue(self.approve()["ok"])
        r = self.a.pay(self.sid)
        self.assertTrue(r["ok"])
        v = self.a.view(self.sid)
        self.assertEqual(v["receipt"]["txn_id"], r["txn"]["txn_id"])
        self.assertTrue(v["audit"]["ok"])
        self.assertTrue(all(t["status"] == "done" for t in v["timeline"]))
        rc = v["receipt"]  # the printable receipt needs these
        self.assertTrue(rc["payer"]["name"] and rc["fx_rate"] and rc["fee_inr"] and rc["payee_bank"]["swift"])
        used = {u["rule_id"]: u for u in rc["rules_used"]}
        self.assertIn("lrs_pan_mandatory", used)
        self.assertTrue(used["lrs_pan_mandatory"]["source"].startswith("https://www.rbi.org.in/"))
        self.assertTrue(all(c["ok"] for c in v["draft"]["compliance"]))
        self.assertTrue((Path(self.tmp.name) / "sandbox_ledger.log").exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main(["verify", str(Path(self.tmp.name) / "audit_log.jsonl")]), 0)

    def test_changing_route_voids_approval(self):
        self.complete()
        self.approve()
        other = self.a.view(self.sid)["ranked"][1]["quote"]["quote_id"]
        self.a.choose_route(self.sid, other)
        self.assertIsNone(self.a.get(self.sid)["approval"])
        self.assertEqual(self.a.pay(self.sid)["code"], "no_approval")

    def test_missing_due_date_question(self):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample="missing_due_date")
        self.assertEqual(self.a.pending_question(self.a.get(self.sid))["field"], "due_on")
        self.a.answer(self.sid, "due_on", "2026-11-15")
        self.assertEqual(self.a.get(self.sid)["invoice"]["due_on"], "2026-11-15")

    def test_next_action_follows_state_and_resume_skips_done_checks(self):
        s = self.a.get(self.sid)
        self.assertEqual(self.a.next_action(s)["action"], "Ask for consent")
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample="missing_due_date")
        n = self.a.next_action(s)
        self.assertIn("When does the university need the payment", n["action"])  # one targeted question
        self.assertIn("check_payee", [d["check"] for d in n["done"]])
        self.a.answer(self.sid, "due_on", "2026-11-15")
        resumed = [e for e in self.a.audit.entries if e["event"] == "resumed"][-1]["data"]
        self.assertEqual(resumed["after_answer"], "due_on")
        self.assertIn("check_payee", resumed["skipped_done"])
        self.assertIn("Who is sending the money", self.a.next_action(s)["action"])  # moves on, not back
        for field, value in FAMILY:
            self.a.answer(self.sid, field, value)
        self.assertEqual(self.a.next_action(s)["action"], "Wait for the parent's signature")
        checks = [e for e in self.a.audit.entries if e["event"] == "tool_call" and e["data"].get("tool") == "check_payee"]
        self.assertEqual(len(checks), 1)  # the signature chain ran once, never again on resume

    def test_payment_made_here_counts_toward_the_next_invoice(self):
        # regression: a second invoice must see the first payment in this year's total (TCS and LRS)
        self.complete()
        self.approve()
        self.a.pay(self.sid)
        self.a.upload_invoice(self.sid, sample="valid_uk")
        v = self.a.view(self.sid)
        best = v["ranked"][0]
        remitted = D(best["lines"][0]["amount_inr"])
        tcs = D(next(l for l in best["lines"] if l["label"] == "TCS")["amount_inr"])
        self.assertEqual(tcs, (remitted * D("0.02")).quantize(D("1")))  # all of it is above the threshold now
        self.assertEqual(D(v["lrs"]["headroom_before_usd"]), D(250000) - D(20000))
        self.assertEqual(v["prior_used"]["paid_here_inr"], "1804000.00")

    def test_inconsistent_earlier_usd_is_questioned(self):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample="valid_us")
        for field, value in FAMILY[:4] + [("prior_inr", "6 lakh")]:
            self.a.answer(self.sid, field, value)
        self.a.answer(self.sid, "prior_usd", "0")
        self.assertEqual(self.a.pending_question(self.a.get(self.sid))["field"], "prior_usd")
        self.a.answer(self.sid, "prior_usd", "7000")
        self.assertEqual(self.a.pending_question(self.a.get(self.sid))["field"], "prior_other")

    def test_no_pan_with_loan_is_flagged(self):
        self.a.consent(self.sid, True)
        self.a.upload_invoice(self.sid, sample="valid_us")
        for field, value in [("remitter_name", "R"), ("pan", "No PAN"), ("relationship", "Father"),
                             ("funding", "Education loan"), ("prior_inr", "0")]:
            self.a.answer(self.sid, field, value)
        self.assertTrue(self.a.view(self.sid)["warnings"])

    def test_chat_attack_is_denied_and_logged(self):
        self.complete()
        self.a.chat(self.sid, fx.ADMIN_CLAIM)
        last = self.a.get(self.sid)["chat"][-1]
        self.assertEqual(last["tone"], "deny")
        self.assertIn("Denied (T4)", last["text"])

    def test_assistant_answers_from_session_state(self):
        self.complete()
        s = self.a.get(self.sid)
        ask = lambda q: (self.a.chat(self.sid, q), s["chat"][-1])[1]
        self.assertIn(s["invoice"]["due_on"], ask("When is it due?")["text"])
        self.assertEqual(ask("Is the signature genuine?")["tone"], "ok")
        self.assertIn(self.a.next_action(s)["action"], ask("What next?")["text"])
        self.assertTrue(ask("Which documents do I need?")["text"].startswith(("Still missing", "All listed")))
        self.assertIn("mid-market", ask("Is there a hidden markup?")["text"])



class TestAttackLab(unittest.TestCase):
    def test_trace_shows_the_defence_that_fired(self):
        from app import lab
        r = lab.run("C4")
        self.assertTrue(r["stopped"])
        self.assertEqual(r["input"], fx.ADMIN_CLAIM)
        fired = [t for t in r["trace"] if t["fired"]]
        self.assertIn("untrusted_text_flagged", [t["event"] for t in fired])
        self.assertTrue(any(t["decision"] and t["decision"]["code"] == "never" and not t["decision"]["allowed"] for t in fired))
        self.assertIsNone(audit.AuditLog.tap)  # the tap is removed after the run

    def test_duplicate_click_trace(self):
        from app import lab
        r = lab.run("B5")
        self.assertEqual([t["event"] for t in r["trace"] if t["fired"]], ["duplicate_click"])
        self.assertEqual(sum(t["event"] == "payment_executed" for t in r["trace"]), 1)

if __name__ == "__main__":
    unittest.main()
