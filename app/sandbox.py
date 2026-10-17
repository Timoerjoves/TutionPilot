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

from rules import Route

IST = timezone(timedelta(hours=5, minutes=30))

PROVIDERS = [
    {"route_name": "Provider A", "provider": "Sandbox Bank A", "rates": {"USD": "90.50", "GBP": "114.80"},
     "fee_inr": "1500.00", "gst_rate": "0", "correspondent_inr": "0"},
    {"route_name": "Provider B", "provider": "Sandbox Bank B", "rates": {"USD": "90.20", "GBP": "114.40"},
     "fee_inr": "3000.00", "gst_rate": "0", "correspondent_inr": "0"},
    {"route_name": "Provider C", "provider": "Sandbox Remit C", "rates": {"USD": "90.35", "GBP": "114.55"},
     "fee_inr": "999.00", "gst_rate": "0.18", "correspondent_inr": "0"},
]
MID_MARKET = {"USD": "90.00", "GBP": "114.20"}  # illustrative mid-market INR per unit
QUOTE_MINUTES = 30


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
