"""The hosted model adapter (Claude), tested with a stand-in client: no network, no API key."""
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from agent.agent import Agent
from agent.model import HostedModel, OfflineModel, make_model
from scenarios import fixtures as fx
from tests.test_app import FAMILY


class FakeClient:
    """Records every request and answers with the queued replies (a string, or an exception to raise)."""

    def __init__(self, *replies, stop_reason="end_turn"):
        self.replies, self.stop_reason, self.requests = list(replies), stop_reason, []
        self.messages = self

    def create(self, **kw):
        self.requests.append(kw)
        r = self.replies.pop(0) if self.replies else ""
        if isinstance(r, Exception):
            raise r
        return NS(stop_reason=self.stop_reason, content=[NS(type="text", text=r)])


def fields(**got):
    keys = ("payee_name", "invoice_id", "issued_on", "due_on", "student_name", "student_id", "amount", "registry_id",
            "country", "account_masked", "swift")
    return json.dumps({k: got.get(k, "") for k in keys})


UNLABELLED = "Invoice No: INV-9\nPlease remit USD 1,250.00 to Northbridge University before 2026-11-15."


class TestHostedModel(unittest.TestCase):
    def test_fills_only_missed_fields_with_values_copied_from_the_text(self):
        client = FakeClient(fields(amount="USD 1,250.00", payee_name="Northbridge University", invoice_id="WRONG-1",
                                   due_on="2026-11-15"))
        inv, uncertain = HostedModel(client).extract(UNLABELLED)
        self.assertEqual(inv["invoice_id"], "INV-9")  # the offline reader found it: never overridden
        self.assertEqual(inv["amount"], {"value": "1250.00", "currency": "USD"})
        self.assertEqual(inv["payee"]["name"], "Northbridge University")
        self.assertEqual(inv["due_on"], "2026-11-15")
        self.assertEqual(set(uncertain), {"amount", "payee_name", "due_on"})  # the family confirms what the model read
        sent = client.requests[0]
        self.assertEqual(sent["model"], "claude-opus-5-5")
        self.assertEqual(sent["output_config"]["format"]["type"], "json_schema")

    def test_invented_values_are_dropped(self):
        inv, _ = HostedModel(FakeClient(fields(amount="USD 99,999.00", swift="FAKEUS33"))).extract(UNLABELLED)
        self.assertEqual(inv["amount"], {})
        self.assertNotIn("swift", inv["payee"]["bank"])

    def test_no_call_when_the_offline_reader_found_everything(self):
        text = ("Payee: U\nInvoice No: X-1\nIssue date: 2026-10-01\nDue date: 2026-11-15\nStudent: S\nStudent ID: 1\n"
                "Amount due: USD 10.00\nRegistry ID: R\nCountry: US\nBank account: XX12\nSWIFT: AB")
        client = FakeClient()
        HostedModel(client).extract(text)
        self.assertEqual(client.requests, [])

    def test_failures_fall_back_to_the_offline_result(self):
        for client in (FakeClient(ConnectionError("offline")), FakeClient("not json"),
                       FakeClient(fields(amount="USD 1,250.00"), stop_reason="refusal")):
            with self.subTest(client=client.replies or client.stop_reason):
                model = HostedModel(client)
                self.assertEqual(model.extract(UNLABELLED), OfflineModel().extract(UNLABELLED))
                self.assertEqual(model.explain([{"text": "B is Rs 4,620 cheaper."}]), "B is Rs 4,620 cheaper.")

    def test_make_model_is_offline_unless_asked(self):
        with mock.patch.dict(os.environ, {"TUITIONPILOT_MODEL": ""}):
            self.assertIsInstance(make_model(), OfflineModel)
        with mock.patch.dict(os.environ, {"TUITIONPILOT_MODEL": "claude"}), mock.patch.dict("sys.modules", {"anthropic": None}):
            self.assertIsInstance(make_model(), OfflineModel)  # SDK not installed: still runs


class TestHostedModelInTheAgent(unittest.TestCase):
    def run_flow(self, client):
        a = Agent(model=HostedModel(client))
        s = a.new_session()
        a.consent(s["id"], True)
        a.upload_invoice(s["id"], sample="valid_us")
        for field, value in FAMILY:
            a.answer(s["id"], field, value)
        return s

    def test_model_sees_masked_text_only(self):
        client = FakeClient("Provider B is the cheapest route.")
        s = self.run_flow(client)
        sent = json.dumps(client.requests)
        self.assertNotIn(fx.SYN_PAN, sent)  # the synthetic PAN the family typed
        self.assertNotIn("Asha Student", sent)  # names are masked before any model call
        self.assertIsNotNone(s["plan"])

    def test_wrong_number_in_the_wording_is_replaced_by_the_engine(self):
        client = FakeClient("Provider B wins and TCS is Rs 75,000.")
        s = self.run_flow(client)
        self.assertFalse(s["explanation"]["grounded"])
        self.assertNotIn("75,000", s["explanation"]["shown"])


if __name__ == "__main__":
    unittest.main()
