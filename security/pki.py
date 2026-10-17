"""Signed invoices and signed approvals: who said what, provably.

Universities: instead of a hand-kept list of "good" payees, TuitionPilot trusts ONE root key
(data/trust/root.json). The root signs a certificate for each university that names its bank account and
SWIFT and carries the university's public key. The university signs each invoice with its own key. The agent
accepts a payee only if:
  1. the certificate is signed by the root, in date, and not on the root-signed revocation list;
  2. the invoice is signed by the key in that certificate (any edit to the invoice breaks it);
  3. the invoice's payee and bank details equal the certificate's (a changed account cannot be signed).

Parents: the parent's device holds a private key the agent never sees. The parent signs the approval, which
contains the exact plan hash, so the agent can neither forge an approval nor change the plan after signing.
"""
import base64
import hashlib
import json
from datetime import date
from pathlib import Path

from contract import canonical_json, signed_bytes

from . import ed25519

TRUST = Path(__file__).resolve().parent.parent / "data" / "trust"
BEGIN = "-----BEGIN TUITIONPILOT SIGNED INVOICE-----"
END = "-----END TUITIONPILOT SIGNED INVOICE-----"


def b64e(b):
    return base64.b64encode(b).decode("ascii")


def b64d(s):
    return base64.b64decode(s, validate=True)


def key_id(public):
    return "ed25519:" + hashlib.sha256(public).hexdigest()[:16]


def demo_secret(label):
    """Synthetic demo keys are derived from public labels so the samples can be rebuilt. Never do this for real keys."""
    return hashlib.sha256(b"tuitionpilot-demo-key:" + label.encode()).digest()


def sign_bytes(secret, data):
    return b64e(ed25519.sign(secret, data))


def verify_b64(public_b64, data, sig_b64):
    try:
        return ed25519.verify(b64d(public_b64), data, b64d(sig_b64))
    except (ValueError, TypeError):
        return False


# ---------- certificates ----------

def issue_certificate(root_secret, serial, subject, public, valid_from, valid_to):
    cert = {"type": "payee_certificate", "serial": serial, "issuer": key_id(ed25519.public_key(root_secret)),
            "subject": subject, "public_key": b64e(public), "key_id": key_id(public),
            "valid_from": valid_from, "valid_to": valid_to}
    return {"certificate": cert, "signature": sign_bytes(root_secret, canonical_json(cert))}


def sign_invoice(secret, signed_cert, invoice):
    body = {k: v for k, v in invoice.items() if k != "attestation"}
    return {**body, "attestation": {"alg": "Ed25519", "certificate": signed_cert,
                                    "signature": sign_bytes(secret, signed_bytes(body))}}


def sign_approval(secret, approval):
    body = {k: v for k, v in approval.items() if k != "signature"}
    pub = ed25519.public_key(secret)
    return {**body, "signature": {"alg": "Ed25519", "key_id": key_id(pub), "value": sign_bytes(secret, signed_bytes(body))}}


# ---------- invoice text with an embedded signed invoice ----------

def embed(visible_text, signed_invoice):
    blob = b64e(json.dumps(signed_invoice, sort_keys=True).encode("utf-8"))
    lines = [blob[i:i + 64] for i in range(0, len(blob), 64)]
    return visible_text.rstrip("\n") + "\n\n" + "\n".join([BEGIN, *lines, END]) + "\n"


def split(text):
    """(visible_text, signed_invoice or None, error or None)."""
    if BEGIN not in text:
        return text, None, None
    head, _, rest = text.partition(BEGIN)
    blob, _, _ = rest.partition(END)
    try:
        return head.rstrip(), json.loads(b64d("".join(blob.split()))), None
    except (ValueError, json.JSONDecodeError):
        return head.rstrip(), None, "the signature block is damaged"


# ---------- the trust store ----------

def _subject_of_invoice(inv):
    p = inv.get("payee", {})
    return {"payee_id": p.get("registry_id"), "name": p.get("name"), "country": p.get("country"),
            "bank": {"account_masked": p.get("bank", {}).get("account_masked"), "swift": p.get("bank", {}).get("swift")}}


class TrustStore:
    def __init__(self, folder=TRUST):
        root = json.loads((Path(folder) / "root.json").read_text(encoding="utf-8"))
        self.root = root
        self.root_public = root["public_key"]
        self.root_key_id = key_id(b64d(self.root_public))
        rev = json.loads((Path(folder) / "revoked.json").read_text(encoding="utf-8"))
        if not verify_b64(self.root_public, canonical_json(rev["list"]), rev["signature"]):
            raise ValueError("revocation list is not signed by the trust root")
        self.revoked = set(rev["list"]["revoked_serials"])

    def check_certificate(self, signed_cert, on):
        """(ok, reason, certificate)."""
        try:
            cert, sig = signed_cert["certificate"], signed_cert["signature"]
        except (KeyError, TypeError):
            return False, "certificate missing", None
        if cert.get("issuer") != self.root_key_id or not verify_b64(self.root_public, canonical_json(cert), sig):
            return False, "certificate not issued by the TuitionPilot trust root", cert
        if cert.get("serial") in self.revoked:
            return False, f"certificate {cert.get('serial')} has been revoked", cert
        if not (cert["valid_from"] <= on.isoformat() <= cert["valid_to"]):
            return False, "certificate is not valid on this date", cert
        return True, "certificate issued by the trust root, in date, not revoked", cert

    def check_invoice(self, signed_invoice, on=None):
        """Every link of the chain, for the agent and for the UI."""
        on = on or date.today()
        chain = [{"step": "Trust root", "ok": True, "detail": self.root.get("name", "TuitionPilot trust root")}]
        out = {"verified": False, "signed": signed_invoice is not None, "chain": chain, "subject": None,
               "mismatch": [], "certificate": None, "reason": None}
        if signed_invoice is None:
            chain.append({"step": "University signature", "ok": False, "detail": "the invoice is not signed"})
            out["reason"] = "the invoice is not signed by the university"
            out["mismatch"] = ["signature"]
            return out
        att = signed_invoice.get("attestation") or {}
        ok, why, cert = self.check_certificate(att.get("certificate"), on)
        chain.append({"step": "University certificate", "ok": ok,
                      "detail": f"{cert['subject']['name']} ({cert['serial']}): {why}" if cert else why})
        if not ok:
            out["reason"], out["mismatch"] = why, ["certificate"]
            return out
        out["subject"], out["certificate"] = cert["subject"], att["certificate"]
        sig_ok = verify_b64(cert["public_key"], signed_bytes(signed_invoice), att.get("signature", ""))
        chain.append({"step": "Invoice signature", "ok": sig_ok,
                      "detail": "signed by the university's key; not changed since" if sig_ok
                      else "signature does not match: the invoice was changed after signing"})
        if not sig_ok:
            out["reason"], out["mismatch"] = "invoice changed after the university signed it", ["signature"]
            return out
        mine, theirs = _subject_of_invoice(signed_invoice), cert["subject"]
        mismatch = [k for k in ("payee_id", "name", "country") if mine[k] != theirs[k]]
        mismatch += [f"bank.{k}" for k in ("account_masked", "swift") if mine["bank"][k] != theirs["bank"][k]]
        if signed_invoice.get("amount", {}).get("currency") != theirs.get("currency"):
            mismatch.append("currency")
        chain.append({"step": "Payee and bank match certificate", "ok": not mismatch,
                      "detail": "account and SWIFT are the ones the trust root certified" if not mismatch
                      else "differs: " + ", ".join(mismatch)})
        out["mismatch"] = mismatch
        out["verified"] = not mismatch
        out["reason"] = None if not mismatch else "payee details differ from the certificate"
        return out

    def check_payee_certificate(self, signed_cert, payee, on=None):
        """The bank's own check before paying: certificate valid and the payee is exactly its subject."""
        ok, why, cert = self.check_certificate(signed_cert, on or date.today())
        if not ok:
            return False, why
        if _subject_of_invoice({"payee": payee}) != {k: cert["subject"][k] for k in ("payee_id", "name", "country", "bank")}:
            return False, "payee details differ from the certificate"
        return True, why


def verify_approval(approval, parent_keys):
    """parent_keys: {key_id: public_key_b64}. True only if a registered parent key signed exactly this approval."""
    sig = approval.get("signature") or {}
    pub = parent_keys.get(sig.get("key_id"))
    return bool(pub) and sig.get("alg") == "Ed25519" and verify_b64(pub, signed_bytes(approval), sig.get("value", ""))
