"""Payment planning, the student budget, sanctions screening, source of funds, the signed payment record and
free-form answers from the hosted model."""
import unittest
from datetime import date, datetime
from decimal import Decimal as D

from agent.agent import Agent
from agent.model import HostedModel
from app.sandbox import IST, SandboxBank, verify_statement
from rules import RulePack
from rules.budget import living_budget
from rules.planner import loan_option, minus_working_days, new_year_option, next_fee, split_options, timing
from scenarios import fixtures as fx
from security.screening import load, normalise, screen
from tests.test_app import FAMILY, PIN
from tests.test_model import FakeClient

PACK = RulePack.load()
USD_ROUTES = SandboxBank.routes("USD")
MID = SandboxBank.mid_market("USD")
TODAY = date(2026, 10, 19)  # a Monday


class TestTiming(unittest.TestCase):
    def test_send_by_skips_weekends_and_keeps_a_spare_day(self):
        t = timing(date(2026, 11, 16), 3, TODAY)  # due Monday; 3 working days + 1 spare -> Tuesday the 10th
        self.assertEqual(t["send_by"], "2026-11-10")
        self.assertEqual((t["days_left"], t["status"]), (22, "on_track"))
        self.assertEqual(minus_working_days(date(2026, 10, 19), 1), date(2026, 10, 16))  # Monday -> Friday

    def test_tight_and_late(self):
        self.assertEqual(timing(date(2026, 10, 23), 1, TODAY)["status"], "tight")
        self.assertEqual(timing(date(2026, 10, 20), 3, TODAY)["status"], "late")


class TestPlanner(unittest.TestCase):
    def test_new_financial_year_resets_the_threshold(self):
        b = next(r for r in USD_ROUTES if r.name == "Provider B")
        kw = dict(settle_days=3, prior_inr=D(1200000), prior_usd=D(13500), amount_usd=D(20000), funding="self",
                  has_pan=True, mid_market_rate=MID)
        ny = new_year_option(PACK, b, D(20000), due_on=date(2027, 4, 20), today=date(2027, 2, 1), **kw)
        self.assertEqual(ny["send_from"], "2027-04-01")
        self.assertEqual(ny["tcs_now_inr"], D(36080))  # all Rs 18,04,000 above the threshold already used
        self.assertEqual(ny["tcs_new_year_inr"], D(16080))  # 2% of the Rs 8,04,000 above a fresh Rs 10 lakh
        self.assertEqual(ny["tcs_saving_inr"], D(20000))
        self.assertIsNone(new_year_option(PACK, b, D(20000), due_on=date(2027, 4, 2), today=date(2027, 2, 1), **kw))

    def test_loan_means_no_tcs(self):
        r = loan_option(PACK, D(1804000), funding="self", prior_inr=D(0), has_pan=True, on=TODAY)
        self.assertEqual((r["tcs_own_money_inr"], r["tcs_loan_inr"], r["difference_inr"]), (D(16080), D(0), D(16080)))

    def test_split_for_the_cap_and_the_yearly_limit(self):
        s = split_options(PACK, D(120000), headroom_usd=D(250000), per_payment_cap_usd=D(50000))
        self.assertEqual([(x["reason"], x["payments"]) for x in s], [("per_payment_cap", 3)])
        s = split_options(PACK, D(30000), headroom_usd=D(10000), per_payment_cap_usd=D(50000))
        self.assertEqual([(x["reason"], x["now_usd"], x["rest_usd"]) for x in s], [("lrs_cap", D(10000), D(20000))])
        self.assertEqual(split_options(PACK, D(20000), headroom_usd=D(250000), per_payment_cap_usd=D(50000)), [])

    def test_next_fee_same_year_and_new_year(self):
        kw = dict(amount_usd=D(20000), today=TODAY, this_payment_inr=D(1804000), this_payment_usd=D(20000),
                  prior_inr=D(0), prior_usd=D(0), funding="self", has_pan=True)
        same = next_fee(PACK, USD_ROUTES, D(20000), MID, due_on=date(2027, 1, 15), **kw)
        self.assertTrue(same["same_financial_year"])
        self.assertEqual((same["route"], same["tcs_inr"]), ("Provider B", D(36080)))
        later = next_fee(PACK, USD_ROUTES, D(20000), MID, due_on=date(2027, 5, 15), **kw)
        self.assertFalse(later["same_financial_year"])
        self.assertEqual((later["tcs_inr"], later["financial_year"]), (D(16080), "2027-28"))


class TestBudget(unittest.TestCase):
    def test_quarterly_is_cheaper_by_the_fees_saved(self):
        b = living_budget(PACK, USD_ROUTES, MID, D(1500), 10, usd_per_unit=D(1), prior_inr=D(1804000), prior_usd=D(20000),
                          funding="self", has_pan=True, on=TODAY)
        m, q = b["plans"]["monthly"], b["plans"]["quarterly"]
        self.assertEqual((m["transfers"], q["transfers"]), (10, 4))
        self.assertEqual(sum(t["months"] for t in q["schedule"]), 10)
        self.assertEqual(m["remitted_inr"], q["remitted_inr"])  # same money sent either way
        self.assertGreater(m["charges_inr"], q["charges_inr"])
        self.assertEqual(b["saving_quarterly_inr"], m["total_inr"] - q["total_inr"])
        self.assertEqual(m["tcs_inr"] - q["tcs_inr"], D(3))  # only rounding differs: all of it is above the threshold
        self.assertTrue(b["lrs_within_cap"])
        self.assertEqual(b["needs_verification"], ["tcs_living_costs_abroad_education_rate"])

    def test_bad_input_refused(self):
        for monthly, months in ((0, 10), (100, 0), (100, 30)):
            with self.assertRaises(ValueError):
                living_budget(PACK, USD_ROUTES, MID, D(monthly), months, usd_per_unit=D(1), prior_inr=0, prior_usd=0,
                              funding="self", has_pan=True, on=TODAY)


class TestScreening(unittest.TestCase):
    W = load()

    def test_exact_reordered_and_suffixed_names_match(self):
        for name in ("Zarvok Pellinor", "PELLINOR, Zarvok", "Ravenmoor Trading FZE", "ravenmoor trading"):
            with self.subTest(name=name):
                self.assertEqual(screen({"payee": name}, self.W)["status"], "match")

    def test_spelling_variant_needs_a_person(self):
        r = screen({"remitter": "Zarvock Pellinor"}, self.W)
        self.assertEqual(r["status"], "possible")
        self.assertEqual(r["hits"][0]["entry_id"], "SYN-I-0001")

    def test_sample_parties_are_clear(self):
        r = screen({"remitter": "Ravi Parent (synthetic)", "student": "Asha Student (synthetic)",
                    "payee": "Northbridge University (synthetic)"}, self.W)
        self.assertEqual((r["status"], r["screened"]), ("clear", ["remitter", "student", "payee"]))
        self.assertEqual(normalise("Ravenmoor Trading, F.Z.E."), normalise("ravenmoor trading f z e"))


def flow(a, family=FAMILY, sample="valid_us"):
    s = a.new_session()
    a.consent(s["id"], True)
    a.upload_invoice(s["id"], sample=sample)
    for field, value in family:
        a.answer(s["id"], field, value)
    return s["id"]


class TestAgentPlanning(unittest.TestCase):
    def setUp(self):
        self.a = Agent(clock=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=IST))
        self.a.register_parent_key(PIN, fx.PARENT_PUBLIC)

    def test_source_of_funds_is_asked_and_on_the_draft(self):
        sid = flow(self.a)
        v = self.a.view(sid)
        self.assertEqual(v["draft"]["sections"]["remitter"]["source_of_funds"], "Savings")
        checks = {c["rule_id"]: c["ok"] for c in v["draft"]["compliance"]}
        self.assertEqual((checks["lrs_source_of_funds_declared"], checks["aml_sanctions_screening"]), (True, True))
        s = self.a.new_session()  # an education loan is its own source: no extra question
        self.a.consent(s["id"], True)
        self.a.upload_invoice(s["id"], sample="valid_us")
        asked = []
        for field, value in FAMILY[:3] + [("funding", "Education loan"), ("prior_inr", "0")]:
            asked.append(self.a.pending_question(s)["field"])
            self.a.answer(s["id"], field, value)
        self.assertNotIn("source_of_funds", asked)
        self.assertIsNone(self.a.pending_question(s))
        sid = flow(self.a, FAMILY[:4])
        self.a.answer(sid, "source_of_funds", "found it on the street")
        s = self.a.get(sid)
        self.assertIn("Please choose one of", s["chat"][-1]["text"])
        self.assertEqual(self.a.pending_question(s)["field"], "source_of_funds")

    def test_a_listed_remitter_stops_the_payment(self):
        family = [("remitter_name", "Zarvok Pellinor")] + FAMILY[1:]
        sid = flow(self.a, family)
        v = self.a.view(sid)
        self.assertEqual(v["screening"]["status"], "match")
        self.assertIn("sanctions_match", [e["code"] for e in v["escalations"]])
        self.assertEqual((v["plan"]["max_tier"], v["plan"]["steps"][-1]["tool"]), ("T4", "pay_sanctioned_party"))
        self.assertFalse(self.a.approve(sid, PIN, fx.parent_approval(v["plan"]))["ok"])
        self.assertFalse(self.a.pay(sid)["ok"])

    def test_spelling_variant_is_escalated_not_paid(self):
        sid = flow(self.a, [("remitter_name", "Zarvock Pellinor")] + FAMILY[1:])
        v = self.a.view(sid)
        self.assertIn("sanctions_review", [e["code"] for e in v["escalations"]])
        self.assertEqual(self.a.approve(sid, PIN, fx.parent_approval(v["plan"]))["code"], "escalated")

    def test_advice_and_next_action_know_the_date(self):
        sid = flow(self.a)
        adv = self.a.view(sid)["advice"]
        self.assertEqual((adv["timing"]["send_by"], adv["timing"]["status"]), ("2026-11-10", "on_track"))
        self.assertIn("Rs 16,080", adv["notes"]["loan"])
        self.assertIn("Send by 2026-11-10", self.a.next_action(self.a.get(sid))["why"])

    def test_plan_ahead_budget_and_signed_record(self):
        sid = flow(self.a)
        r = self.a.plan_ahead(sid, "20,000", "2027-01-15")
        self.assertEqual((r["tcs_inr"], r["same_financial_year"]), ("36080", True))
        for bad in (("0", "2027-01-15"), ("20000", "2026-01-01"), ("20000", "soon")):
            with self.assertRaises(ValueError):
                self.a.plan_ahead(sid, *bad)
        b = self.a.budget(sid, "1500", 10)
        self.assertEqual((b["currency"], b["plans"]["quarterly"]["transfers"]), ("USD", 4))
        with self.assertRaises(ValueError):
            self.a.payment_record(sid)  # nothing paid yet
        self.assertTrue(self.a.approve(sid, PIN, fx.parent_approval(self.a.view(sid)["plan"]))["ok"])
        self.assertTrue(self.a.pay(sid)["ok"])
        rec = self.a.payment_record(sid)
        self.assertEqual((rec["payments_count"], rec["on_time_count"]), (1, 1))
        self.assertEqual(rec["payments"][0]["expected_arrival"], "2026-10-22")
        self.assertTrue(verify_statement(rec))
        forged = {**rec, "on_time_count": 5}
        self.assertFalse(verify_statement(forged))
        self.a.chat(sid, "When should I send it?")  # after paying, the answer is about the payment, not a send-by date
        self.assertIn("Already paid on 2026-10-19", self.a.get(sid)["chat"][-1]["text"])

    def test_chat_answers_planning_questions(self):
        sid = flow(self.a)
        for q, expect in (("When should I send it?", "Send by 2026-11-10"), ("Would a loan help?", "Rs 0 instead of Rs 16,080"),
                          ("Any sanctions issue?", "no match"), ("Do I need to split it?", "No split is needed")):
            self.a.chat(sid, q)
            self.assertIn(expect, self.a.get(sid)["chat"][-1]["text"], q)


class TestHostedAnswers(unittest.TestCase):
    def ask(self, *replies, question="Please sum up the whole payment in two lines for my mother."):
        client = FakeClient("Provider B is the cheapest route.", *replies)  # the first reply words the route comparison
        a = Agent(model=HostedModel(client), clock=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=IST))
        sid = flow(a)
        client.requests.clear()
        a.chat(sid, question)
        return a, sid, client

    def test_grounded_answer_is_shown_with_its_source(self):
        a, sid, client = self.ask("Yes. Provider B costs Rs 18,23,080 in total, Rs 1,238.82 less than Provider C.")
        last = a.get(sid)["chat"][-1]
        self.assertEqual(last.get("source"), "model")
        self.assertIn("Rs 18,23,080", last["text"])
        sent = client.requests[-1]["messages"][0]["content"]
        self.assertIn("Facts:", sent)
        self.assertNotIn("Ravi", sent)  # people's names never reach the model
        self.assertNotIn(fx.SYN_PAN, sent)

    def test_invented_number_is_rejected(self):
        a, sid, _ = self.ask("Provider B costs Rs 17,00,000, so you save Rs 1,00,000.")
        last = a.get(sid)["chat"][-1]
        self.assertNotIn("17,00,000", last["text"])
        self.assertIsNone(last.get("source"))

    def test_model_failure_falls_back(self):
        a, sid, _ = self.ask(ConnectionError("offline"))
        self.assertIn("I can explain the costs", a.get(sid)["chat"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
