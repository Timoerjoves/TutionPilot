"""Sandbox bank: quotes from three synthetic providers, one family account, and a ledger.

No real bank is connected anywhere. Rates are illustrative (Provider A and B match scenario A8).
The bank also defends itself: it refuses unknown or expired quotes, unverified payees, short balances,
and it executes each approval at most once (a second click returns the first transaction).
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

from contract import canonical_json
from rules import Route
from security import ed25519
from security.pki import b64e, demo_secret, key_id, sign_bytes, verify_b64

IST = timezone(timedelta(hours=5, minutes=30))

PROVIDERS = [
    {"route_name": "Provider A", "provider": "Sandbox Bank A", "rates": {"USD": "90.50", "GBP": "114.80", "CAD": "66.10", "AUD": "59.40"},
     "fee_inr": "1500.00", "gst_rate": "0", "correspondent_inr": "0", "settle_working_days": 2},
    {"route_name": "Provider B", "provider": "Sandbox Bank B", "rates": {"USD": "90.20", "GBP": "114.40", "CAD": "65.85", "AUD": "59.15"},
     "fee_inr": "3000.00", "gst_rate": "0", "correspondent_inr": "0", "settle_working_days": 3},
    {"route_name": "Provider C", "provider": "Sandbox Remit C", "rates": {"USD": "90.35", "GBP": "114.55", "CAD": "65.95", "AUD": "59.30"},
     "fee_inr": "999.00", "gst_rate": "0.18", "correspondent_inr": "0", "settle_working_days": 1},
]
MID_MARKET = {"USD": "90.00", "GBP": "114.20", "CAD": "65.70", "AUD": "59.00"}  # illustrative mid-market INR per unit
QUOTE_MINUTES = 30
STATEMENT_SECRET = demo_secret("sandbox-bank-statements")  # synthetic: derived from a public label, demo only
STATEMENT_KEY = b64e(ed25519.public_key(STATEMENT_SECRET))


class BankError(ValueError):
    pass


def now_ist():
    return datetime.now(IST)


class SandboxBank:
    def __init__(self, trust, balance_inr="5000000.00", ledger_path=None, clock=now_ist):
        self.trust = trust  # security.pki.TrustStore: the bank checks the payee's certificate itself
        self.clock = clock
        self.account = {"account_id": "SANDBOX-ACC-0001", "holder": "Synthetic family account",
                        "balance_inr": D(balance_inr)}
        self.quotes = {}
        self.ledger = []
        self.by_approval = {}
        self.ledger_path = Path(ledger_path) if ledger_path else None

    # ----- quotes -----
    def quote_all(self, foreign_amount, currency):
        """One contract 'quote' message per provider that supports the currency."""
        out = []
        valid_until = (self.clock() + timedelta(minutes=QUOTE_MINUTES)).isoformat(timespec="seconds")
        for p in PROVIDERS:
            if currency not in p["rates"]:
                continue
            q = {"type": "quote", "contract_version": "1.0",
                 "quote_id": f"Q-{uuid.uuid4().hex[:8].upper()}", "route_name": p["route_name"],
                 "provider": p["provider"], "foreign_amount": {"value": str(D(foreign_amount)), "currency": currency},
                 "fx_rate": p["rates"][currency], "fee_inr": p["fee_inr"], "gst_rate": p["gst_rate"],
                 "correspondent_inr": p["correspondent_inr"], "valid_until": valid_until}
            self.quotes[q["quote_id"]] = q
            out.append(q)
        return out

    @staticmethod
    def route_of(quote):
        return Route(quote["route_name"], D(quote["fx_rate"]), fee_inr=D(quote["fee_inr"]),
                     gst_rate=D(quote["gst_rate"]), correspondent_inr=D(quote["correspondent_inr"]))

    @staticmethod
    def mid_market(currency):
        return D(MID_MARKET[currency])

    @staticmethod
    def routes(currency):
        """Every provider's route for a currency, without issuing quotes (for budgets and projections)."""
        return [Route(p["route_name"], D(p["rates"][currency]), fee_inr=D(p["fee_inr"]), gst_rate=D(p["gst_rate"]),
                      correspondent_inr=D(p["correspondent_inr"])) for p in PROVIDERS if currency in p["rates"]]

    @staticmethod
    def settle_days(route_name):
        return next(p["settle_working_days"] for p in PROVIDERS if p["route_name"] == route_name)

    # ----- signed payment record -----
    def statement(self, holder, payments):
        """A payment record signed with the bank's key, so a landlord or lender abroad can check it. Not a credit score."""
        body = {"type": "payment_record", "issuer": "Sandbox Bank (synthetic)", "issuer_key_id": key_id(ed25519.public_key(STATEMENT_SECRET)),
                "issued_at": self.clock().isoformat(timespec="seconds"), "holder": holder, "payments": payments,
                "payments_count": len(payments), "on_time_count": sum(1 for p in payments if p["on_time"]),
                "labels": ["Synthetic data", "Sandbox only: no real money moved", "A record of payments, not a credit score"]}
        return {**body, "signature": {"alg": "Ed25519", "public_key": STATEMENT_KEY,
                                      "value": sign_bytes(STATEMENT_SECRET, canonical_json(body))}}

    # ----- payments -----
    def execute(self, *, approval_id, quote_id, payee, total_inr, plan_hash, payee_certificate=None):
        """Debit the account and record a transfer. Only the policy engine calls this, after its checks."""
        if approval_id in self.by_approval:  # idempotent: second click, same result
            return self.by_approval[approval_id]
        q = self.quotes.get(quote_id)
        if q is None:
            raise BankError("unknown quote")
        if self.clock() > datetime.fromisoformat(q["valid_until"]):
            raise BankError("quote expired; get a new quote and approve again")
        ok, why = self.trust.check_payee_certificate(payee_certificate, payee, self.clock().date())
        if not ok:
            raise BankError(f"payee not verified: {why}")
        total = D(total_inr)
        if total > self.account["balance_inr"]:
            raise BankError("insufficient sandbox balance")
        self.account["balance_inr"] -= total
        txn = {"txn_id": f"TXN-{uuid.uuid4().hex[:10].upper()}", "at": self.clock().isoformat(timespec="seconds"),
               "account_id": self.account["account_id"], "approval_id": approval_id, "plan_hash": plan_hash,
               "quote_id": quote_id, "provider": q["provider"], "payee_registry_id": payee["registry_id"],
               "foreign_amount": q["foreign_amount"], "debit_inr": str(total),
               "balance_after_inr": str(self.account["balance_inr"]), "status": "settled (sandbox)"}
        self.ledger.append(txn)
        self.by_approval[approval_id] = txn
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(txn) + "\n")
        return txn


def verify_statement(record, public_key=STATEMENT_KEY):
    """True only if the record is exactly what the bank signed, with the bank's key."""
    sig = record.get("signature") or {}
    body = {k: v for k, v in record.items() if k != "signature"}
    return sig.get("public_key") == public_key and verify_b64(public_key, canonical_json(body), sig.get("value", ""))
