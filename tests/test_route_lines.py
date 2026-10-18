"""Route comparison from an invoice and 2-4 quote messages: ranking, a source on every line, refusals."""
import copy
import json
import unittest
from decimal import Decimal as D
from pathlib import Path

from contract import ContractError
from rules import RulePack, Route, compare_routes
from datetime import datetime, timedelta, timezone

from rules.explain import compare_quotes as _compare_quotes

# the sample quotes are valid until 2026-10-16 18:00 IST; compare them half an hour before that
NOW = datetime(2026, 10, 16, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def compare_quotes(*args, **kwargs):
    return _compare_quotes(*args, now=kwargs.pop("now", NOW), **kwargs)

PACK = RulePack.load()
SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"


def load(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


INVOICE = load("invoice.json")
QUOTES = [load(f"quote_{x}.json") for x in "abc"]


class TestRanking(unittest.TestCase):
    def setUp(self):
        self.r = compare_quotes(PACK, INVOICE, QUOTES)

    def test_ranked_cheapest_first(self):
        totals = [D(x["total_inr"]) for x in self.r["routes"]]
        self.assertEqual(totals, sorted(totals))
        self.assertEqual([x["rank"] for x in self.r["routes"]], [1, 2, 3])

    def test_lowest_fee_is_not_cheapest(self):
        # Provider A has the lowest fee but the worst rate: the samples exist to show this
        self.assertEqual(self.r["routes"][0]["route"], "Provider B")
        self.assertEqual(self.r["routes"][-1]["route"], "Provider A")

    def test_saving_vs_next(self):
        rs = self.r["routes"]
        for a, b in zip(rs, rs[1:]):
            self.assertEqual(D(a["saving_vs_next_inr"]), D(b["total_inr"]) - D(a["total_inr"]))
        self.assertIsNone(rs[-1]["saving_vs_next_inr"])

    def test_same_totals_as_engine(self):
        routes = [Route(q["route_name"], D(q["fx_rate"]), fee_inr=D(q["fee_inr"]), gst_rate=D(q["gst_rate"]),
                        correspondent_inr=D(q["correspondent_inr"])) for q in QUOTES]
        engine = {row["cost"].route: str(row["cost"].total_inr) for row in compare_routes(PACK, routes, 20000)}
        self.assertEqual({x["route"]: x["total_inr"] for x in self.r["routes"]}, engine)

    def test_quote_id_carried(self):
        ids = {q["route_name"]: q["quote_id"] for q in QUOTES}
        for x in self.r["routes"]:
            self.assertEqual(x["quote_id"], ids[x["route"]])


class TestLines(unittest.TestCase):
    def setUp(self):
        self.r = compare_quotes(PACK, INVOICE, QUOTES)

    def test_every_line_has_a_source(self):
        for x in self.r["routes"]:
            for line in x["lines"]:
                self.assertTrue(line["source"], f"{x['route']} / {line['label']} has no source")
        for line in self.r["why"]:
            self.assertTrue(line["source"])

    def test_quote_lines_name_the_quote(self):
        for x in self.r["routes"]:
            sent = next(l for l in x["lines"] if l["label"] == "Amount sent")
            self.assertIn(x["quote_id"], sent["source"])

    def test_tcs_line_names_pack_version_and_flags(self):
        for x in self.r["routes"]:
            tcs = next(l for l in x["lines"] if l["label"] == "TCS")
            self.assertIn(PACK.version, tcs["source"])
            self.assertIn("effective", tcs["source"])
            self.assertEqual(sorted(tcs["unverified"]), sorted(set(tcs["rules"]) & set(x["needs_verification"])))

    def test_gst_line_cites_rule_and_is_flagged_if_unverified(self):
        a = next(x for x in self.r["routes"] if x["route"] == "Provider A")
        gst = next(l for l in a["lines"] if l["label"] == "GST on fee")
        self.assertIn("gst_on_service_charge", gst["source"])
        if PACK.rules["gst_on_service_charge"]["status"] == "unverified":
            self.assertIn("gst_on_service_charge", gst["unverified"])

    def test_total_carries_every_flag(self):
        for x in self.r["routes"]:
            total = x["lines"][-1]
            self.assertEqual(total["label"], "Total")
            self.assertEqual(sorted(total["unverified"]), sorted(x["needs_verification"]))

    def test_lines_add_up_to_total(self):
        for x in self.r["routes"]:
            parts = sum(D(l["amount_inr"]) for l in x["lines"] if l["label"] != "Total")
            self.assertEqual(parts, D(x["total_inr"]))


class TestRefusals(unittest.TestCase):
    def test_too_few_or_too_many_quotes(self):
        with self.assertRaises(ValueError):
            compare_quotes(PACK, INVOICE, QUOTES[:1])
        five = [dict(QUOTES[0], route_name=f"R{i}", quote_id=f"Q-{i}") for i in range(5)]
        with self.assertRaises(ValueError):
            compare_quotes(PACK, INVOICE, five)

    def test_currency_mismatch(self):
        q = copy.deepcopy(QUOTES)
        q[1]["foreign_amount"]["currency"] = "GBP"
        with self.assertRaisesRegex(ValueError, q[1]["quote_id"]):
            compare_quotes(PACK, INVOICE, q)

    def test_amount_mismatch(self):
        q = copy.deepcopy(QUOTES)
        q[2]["foreign_amount"]["value"] = "19999.00"
        with self.assertRaisesRegex(ValueError, q[2]["quote_id"]):
            compare_quotes(PACK, INVOICE, q)

    def test_duplicate_route_name(self):
        q = copy.deepcopy(QUOTES)
        q[1]["route_name"] = q[0]["route_name"]
        with self.assertRaisesRegex(ValueError, "same route name"):
            compare_quotes(PACK, INVOICE, q)

    def test_impossible_terms_refused(self):
        for field, value in (("fee_inr", "-900000.00"), ("fx_rate", "0"), ("correspondent_inr", "-1.00"),
                             ("gst_rate", "1.5")):
            q = copy.deepcopy(QUOTES)
            q[1][field] = value
            with self.assertRaisesRegex(ValueError, "impossible terms", msg=field):
                compare_quotes(PACK, INVOICE, q)

    def test_expired_quote_refused(self):
        with self.assertRaisesRegex(ValueError, "expired"):
            compare_quotes(PACK, INVOICE, QUOTES, now=NOW + timedelta(hours=1))
        with self.assertRaisesRegex(ValueError, "expired"):
            _compare_quotes(PACK, INVOICE, QUOTES)  # default is the real clock: the samples are past their time

    def test_invalid_message_refused_by_contract(self):
        q = copy.deepcopy(QUOTES)
        q[0]["fee_inr"] = 1500.0  # float money
        with self.assertRaises(ContractError):
            compare_quotes(PACK, INVOICE, q)


if __name__ == "__main__":
    unittest.main()
