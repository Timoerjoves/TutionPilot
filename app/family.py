"""Family devices, passwordless sign-in and the encrypted document vault.

Each parent or student device makes two key pairs in its own browser and keeps the private halves there:
  - Ed25519 (signing): proves "this is that device" at sign-in, and signs payment approvals (parents only).
  - X25519 (encryption): vault files are locked to this public key; only the device's private key can unlock them.
The server stores public keys and ciphertext only. It cannot read a vault file or sign in as anyone.
Enrolling the first parent device needs the parent's PIN. Every later device (parent or student) needs the PIN
AND a signature from an already-enrolled parent device over the exact enrolment request (R19).
"""
import secrets
import time

from app.policy import Decision
from contract import canonical_json
from security.pki import b64d, key_id, verify_b64

SIGN_IN_CONTEXT = b"tuitionpilot-sign-in:"  # domain separation: a sign-in signature can never pass as an approval
ENROL_CONTEXT = b"tuitionpilot-enrol-device:"  # domain separation: never confused with a sign-in or an approval
CHALLENGE_TTL = 120  # seconds
ENROL_TTL = 600  # a person has to walk the code over to a parent's device
ENROL_FIELDS = ("role", "public_key", "box_key", "label", "nonce")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCS = 50
ROLES = ("parent", "student")


class FamilyError(ValueError):
    pass


def enrolment_bytes(req):
    """The exact bytes a parent device signs to approve a new device."""
    return ENROL_CONTEXT + canonical_json({k: req[k] for k in ENROL_FIELDS})


def _raw(value, what, size=None, max_size=None):
    """Base64 -> bytes of exactly `size`, or of 1..max_size bytes."""
    try:
        raw = b64d(value or "")
    except (ValueError, TypeError):
        raw = b""
    if (size is not None and len(raw) != size) or (max_size is not None and not 1 <= len(raw) <= max_size):
        raise FamilyError(f"{what} is malformed")
    return raw


class Family:
    def __init__(self, policy, clock=time.time):
        self.policy, self.clock = policy, clock
        self.devices = {}      # key_id -> {"role", "public_key", "box_key", "label"}
        self._challenges = {}  # nonce -> expiry time; each is used once
        self._requests = {}    # enrolment code -> request waiting for a parent device's signature
        self.docs = {}         # doc_id -> sealed document (ciphertext + one wrapped key per allowed device)

    # ---------- devices ----------
    def register(self, pin, role, public_key, box_key, label="", nonce=None, approver=None, signature=None):
        """Enrol a device. The PIN alone works only for the first parent device; after that an enrolled parent
        device must also have signed enrolment_bytes() of this request with a fresh nonce. Returns a policy Decision."""
        if role not in ROLES:
            raise FamilyError("role must be parent or student")
        _raw(box_key, "encryption key", size=32)
        label = str(label or f"{role} device")[:40]
        action = f"register_{role}_key"
        if self.policy.parent_keys:  # bootstrap is over
            req = {"role": role, "public_key": public_key, "box_key": box_key, "label": label, "nonce": str(nonce)}
            if self._challenges.get(req["nonce"], 0) < self.clock():
                return self.policy._deny(action, "T4", "stale_request",
                                         "The enrolment request expired or was already used. Start again.")
            if not self._parent_signed(req, approver, signature):
                return self.policy._deny(action, "T4", "needs_parent_signature",
                                         "A new device needs the PIN and approval from an enrolled parent device.")
        elif role != "parent":
            return Decision(False, action, "T2", "no_parent", "Set up a parent device first.")
        if role == "parent":
            d = self.policy.register_parent_key(pin, public_key, label)  # also lets this key sign approvals
        else:
            d = self.policy.register_student_key(pin, public_key, label)
        if d.allowed:
            self._challenges.pop(str(nonce), None)  # used once: a replay of this request is refused
            self.devices[key_id(b64d(public_key))] = {"role": role, "public_key": public_key, "box_key": box_key,
                                                      "label": label}
        return d

    def _parent_signed(self, req, approver, signature):
        parent = self.policy.parent_keys.get(str(approver))
        return parent is not None and verify_b64(parent, enrolment_bytes(req), signature or "")

    # ---------- enrolment requests: the new device shows a code, a signed-in parent device signs it ----------
    def request_enrolment(self, role, public_key, box_key, label=""):
        """Park a new device's request under a short code. Nothing is enrolled until finish_enrolment()."""
        if role not in ROLES:
            raise FamilyError("role must be parent or student")
        _raw(public_key, "signing key", size=32)
        _raw(box_key, "encryption key", size=32)
        code = secrets.token_hex(4).upper()
        self._requests[code] = {"role": role, "public_key": public_key, "box_key": box_key,
                                "label": str(label or f"{role} device")[:40], "nonce": self.challenge(ENROL_TTL)}
        return code

    def enrolment_request(self, code):
        """The fields a parent device must sign (plus the new key's id to show the parent)."""
        req = self._requests.get(str(code).replace("-", "").strip().upper())
        if req is None or self._challenges.get(req["nonce"], 0) < self.clock():
            raise KeyError("no such enrolment request, or it expired")
        return {k: req[k] for k in ENROL_FIELDS} | {"key_id": key_id(b64d(req["public_key"]))}

    def approve_enrolment(self, code, approver, signature):
        req = self.enrolment_request(code)
        if not self._parent_signed(req, approver, signature):
            raise PermissionError("That approval is not signed by an enrolled parent device.")
        self._requests[str(code).replace("-", "").strip().upper()] |= {"approver": approver, "signature": signature}

    def finish_enrolment(self, pin, code):
        """The new device completes its own request with the PIN, once a parent device has signed it."""
        code = str(code).replace("-", "").strip().upper()
        req = self._requests.get(code)
        if req is None:
            raise KeyError("no such enrolment request, or it expired")
        d = self.register(pin, req["role"], req["public_key"], req["box_key"], req["label"], req["nonce"],
                          req.get("approver"), req.get("signature"))
        if d.allowed:
            del self._requests[code]
        return d

    def listing(self):
        return [{"key_id": k, **v} for k, v in sorted(self.devices.items())]

    # ---------- sign-in: sign a one-time challenge with the device key ----------
    def challenge(self, ttl=CHALLENGE_TTL):
        now = self.clock()
        self._challenges = {n: t for n, t in self._challenges.items() if t > now}
        self._requests = {c: r for c, r in self._requests.items() if r["nonce"] in self._challenges}
        nonce = secrets.token_hex(16)
        self._challenges[nonce] = now + ttl
        return nonce

    def sign_in(self, nonce, kid, signature):
        """(role, key_id) if a registered device signed this fresh challenge. Raises PermissionError otherwise."""
        expiry = self._challenges.pop(str(nonce), None)  # popped first: a challenge never works twice
        if expiry is None or expiry < self.clock():
            raise PermissionError("The sign-in challenge expired or was already used. Try again.")
        dev = self.devices.get(kid)
        if dev is None:
            raise PermissionError("This device is not enrolled. Set it up with the parent's PIN first.")
        if not verify_b64(dev["public_key"], SIGN_IN_CONTEXT + nonce.encode(), signature or ""):
            raise PermissionError("The device signature did not verify.")
        return dev["role"], kid

    # ---------- vault: the server keeps ciphertext it cannot read ----------
    def put(self, uploader, doc):
        """doc: {name, mime, iv, ciphertext, ephemeral_key, wrapped: {key_id: {iv, key}}}, sealed in the browser."""
        if len(self.docs) >= MAX_DOCS:
            raise FamilyError("the vault is full")
        name = str(doc.get("name") or "").strip()[:120]
        if not name:
            raise FamilyError("the file needs a name")
        _raw(doc.get("iv"), "file nonce", size=12)
        _raw(doc.get("ephemeral_key"), "ephemeral key", size=32)
        size = len(_raw(doc.get("ciphertext"), "file (max 2 MB)", max_size=MAX_FILE_BYTES + 16)) - 16
        wrapped = doc.get("wrapped")
        if not isinstance(wrapped, dict) or uploader not in wrapped:
            raise FamilyError("the uploader must be able to open their own file")
        if not set(wrapped) <= set(self.devices):
            raise FamilyError("files can be shared only with enrolled family devices")
        if self.devices[uploader]["role"] == "student" and any(self.devices[k]["role"] == "student" and k != uploader
                                                               for k in wrapped):
            raise FamilyError("a student can share files only with the parents")
        for w in wrapped.values():
            _raw((w or {}).get("iv"), "key nonce", size=12)
            _raw((w or {}).get("key"), "wrapped key", size=48)  # 32-byte file key + 16-byte tag
        doc_id = "DOC-" + secrets.token_hex(6).upper()
        self.docs[doc_id] = {"doc_id": doc_id, "name": name, "mime": str(doc.get("mime") or "")[:80], "size": size,
                             "uploaded_by": self.devices[uploader]["role"], "uploader": uploader,
                             "uploaded_at": int(self.clock()), "iv": doc["iv"], "ciphertext": doc["ciphertext"],
                             "ephemeral_key": doc["ephemeral_key"],
                             "wrapped": {k: {"iv": w["iv"], "key": w["key"]} for k, w in wrapped.items()}}
        return self._meta(self.docs[doc_id])

    def _meta(self, d):
        return {k: v for k, v in d.items() if k not in ("ciphertext", "wrapped", "iv", "ephemeral_key")} | {
            "shared_with": sorted({self.devices[k]["role"] for k in d["wrapped"] if k in self.devices})}

    def list_for(self, kid):
        return [self._meta(d) for d in self.docs.values() if kid in d["wrapped"]]

    def get_for(self, kid, doc_id):
        d = self.docs.get(doc_id)
        if d is None or kid not in d["wrapped"]:
            raise PermissionError("This file was not shared with this device.")
        return self._meta(d) | {"iv": d["iv"], "ciphertext": d["ciphertext"], "ephemeral_key": d["ephemeral_key"],
                                "wrapped_key": d["wrapped"][kid]}
