"""Policy engine: permission tiers T0-T4, PIN, per-payment cap, emergency stop, circuit breaker.

Every tool call the agent makes goes through check(). Nothing the user or a document *says* can change a tier,
a payee or a limit: limits change only in change_settings() with the parent's PIN, never from chat.
"""
import hashlib
import hmac
import os
from dataclasses import asdict, dataclass
from decimal import Decimal as D

from contract import ContractError, plan_hash, validate
from security.pki import b64d, key_id, verify_approval

TOOL_TIERS = {
    "read_invoice": "T0", "check_payee": "T0", "read_history": "T0", "sanctions_screening": "T0",
    "compare_routes": "T1", "draft_form": "T1",
    "save_draft": "T2", "share_draft": "T2",
    "sandbox_pay": "T3",
    # T4: never allowed from the agent, whatever the approval
    "add_payee": "T4", "pay_unverified_payee": "T4", "pay_sanctioned_party": "T4", "raise_limit": "T4", "change_own_limits": "T4",
    "skip_approval": "T4",
}
MONEY_TIERS = ("T3", "T4")


@dataclass
class Decision:
    allowed: bool
    action: str
    tier: str
    code: str
    reason: str
    escalate: bool = False

    def to_dict(self):
        return asdict(self)


def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", str(pin).encode(), salt, 100_000)


class Policy:
    def __init__(self, pin, per_payment_cap_usd="50000", breaker_threshold=3):
        self._salt = os.urandom(16)
        self._pin_hash = _hash_pin(pin, self._salt)
        self.per_payment_cap_usd = D(per_payment_cap_usd)
        self.emergency_stop = False
        self.breaker_threshold = breaker_threshold
        self.denied_in_a_row = 0
        self.frozen = False
        self.parent_keys = {}  # key_id -> public key (base64). Private keys never leave the parent's device.
        self.student_keys = {}  # student devices: may sign in and use the vault, never approve a payment

    # ----- PIN and settings (the only way limits change) -----
    def register_parent_key(self, pin, public_key_b64, label="parent device"):
        return self._register_key(pin, public_key_b64, label, self.parent_keys, "Parent")

    def register_student_key(self, pin, public_key_b64, label="student device"):
        return self._register_key(pin, public_key_b64, label, self.student_keys, "Student")

    def _register_key(self, pin, public_key_b64, label, keys, who):
        action = f"register_{who.lower()}_key"
        if self.frozen:
            return Decision(False, action, "T4", "circuit_breaker", "The agent is frozen: reset it with the PIN first.")
        if not self.verify_pin(pin):
            self._count_denial("T4")
            return Decision(False, action, "T4", "bad_pin", "Wrong PIN: device not registered.")
        try:
            raw = b64d(public_key_b64)
        except (ValueError, TypeError):
            raw = b""
        if len(raw) != 32:
            return Decision(False, action, "T2", "bad_key", "That is not an Ed25519 public key.")
        kid = key_id(raw)
        keys[kid] = public_key_b64
        return Decision(True, action, "T2", "ok", f"{who} signing key {kid} registered ({label}).")

    def verify_pin(self, pin, *, frozen_ok=False):
        """While the breaker is frozen every PIN check fails, except the reset in change_settings()."""
        if self.frozen and not frozen_ok:
            return False
        return pin is not None and hmac.compare_digest(_hash_pin(pin, self._salt), self._pin_hash)

    def change_settings(self, pin, *, per_payment_cap_usd=None, emergency_stop=None, reset_breaker=False):
        if self.frozen and not reset_breaker:
            return Decision(False, "change_settings", "T4", "circuit_breaker",
                            "The agent is frozen: the only change allowed is a breaker reset with the PIN.")
        if not self.verify_pin(pin, frozen_ok=True):
            self._count_denial("T4")
            return Decision(False, "change_settings", "T4", "bad_pin", "Wrong PIN: settings unchanged.")
        changed = []
        if per_payment_cap_usd is not None:
            self.per_payment_cap_usd = D(per_payment_cap_usd)
            changed.append(f"per-payment cap USD {self.per_payment_cap_usd}")
        if emergency_stop is not None:
            self.emergency_stop = bool(emergency_stop)
            changed.append(f"emergency stop {'on' if self.emergency_stop else 'off'}")
        if reset_breaker:
            self.frozen, self.denied_in_a_row = False, 0
            changed.append("circuit breaker reset")
        return Decision(True, "change_settings", "T2", "ok", "Settings changed with PIN: " + (", ".join(changed) or "nothing"))

    def status(self):
        return {"per_payment_cap_usd": str(self.per_payment_cap_usd), "emergency_stop": self.emergency_stop,
                "parent_keys": sorted(self.parent_keys),
                "student_keys": sorted(self.student_keys),
                "frozen": self.frozen, "denied_in_a_row": self.denied_in_a_row,
                "breaker_threshold": self.breaker_threshold}

    # ----- the gate -----
    def _count_denial(self, tier):
        if tier in MONEY_TIERS:
            self.denied_in_a_row += 1
            if self.denied_in_a_row >= self.breaker_threshold:
                self.frozen = True

    def _deny(self, action, tier, code, reason, escalate=False):
        self._count_denial(tier)
        return Decision(False, action, tier, code, reason, escalate)

    def check(self, action, *, plan=None, approval=None, payee_verified=False, amount_usd=None):
        tier = TOOL_TIERS.get(action)
        if tier is None:
            return self._deny(action, "T4", "unknown_action", f"'{action}' is not a known tool.")
        if tier == "T4":
            return self._deny(action, tier, "never", "Tier T4 actions are never allowed for the agent "
                              "(new or unverified payee, raising or changing limits, skipping approval).", True)
        if tier in ("T0", "T1"):
            return Decision(True, action, tier, "ok", f"Tier {tier}: no approval needed.")
        if tier == "T2":
            if not approval or approval.get("decision") != "approved":
                return Decision(False, action, tier, "no_approval", "Saving or sharing needs a click to approve.")
            return Decision(True, action, tier, "ok", "Tier T2 approved.")

        # T3: sandbox payment
        if self.frozen:
            return self._deny(action, tier, "circuit_breaker",
                              "The agent is frozen after repeated denied attempts. A parent must reset it with the PIN.", True)
        if self.emergency_stop:
            return self._deny(action, tier, "emergency_stop", "Emergency stop is on: all money actions are denied.")
        if not payee_verified:
            return self._deny("pay_unverified_payee", "T4", "unverified_payee",
                              "The payee is not verified in the registry. Paying them is tier T4: never allowed.", True)
        if amount_usd is not None and D(amount_usd) > self.per_payment_cap_usd:
            return self._deny(action, tier, "over_cap",
                              f"USD {D(amount_usd):,.2f} is above the per-payment cap of USD {self.per_payment_cap_usd:,.2f}. "
                              "Escalated to a human.", True)
        if plan is None or approval is None:
            return self._deny(action, tier, "no_approval", "A payment needs the parent's PIN approval of this exact plan.")
        try:
            validate(plan)
            validate(approval)
        except ContractError as e:
            return self._deny(action, tier, "invalid_message", f"Plan or approval is malformed: {e}")
        if approval["decision"] != "approved":
            return self._deny(action, tier, "rejected", "The approval was a rejection.")
        if approval["plan_id"] != plan["plan_id"] or approval["plan_hash"] != plan_hash(plan):
            return self._deny(action, tier, "plan_changed",
                              "The plan changed after it was approved, so the approval is void. Approve the new plan.")
        if not verify_approval(approval, self.parent_keys):
            return self._deny(action, tier, "bad_signature",
                              "The approval is not signed by a registered parent device key, or was changed after signing.")
        if approval["method"] != "pin":
            return self._deny(action, tier, "pin_required", "Tier T3 needs PIN approval, not a click.")
        if approval["approver"]["role"] != "parent":
            return self._deny(action, tier, "role", "Only the parent can approve a payment.")
        if approval["tier"] != plan["max_tier"]:
            return self._deny(action, tier, "tier_mismatch", "The approval does not cover the plan's highest tier.")
        self.denied_in_a_row = 0
        return Decision(True, action, tier, "ok", "Tier T3: verified payee, within cap, parent-signed PIN approval "
                        "of this exact plan.")
