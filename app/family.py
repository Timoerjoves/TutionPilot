"""Family devices, passwordless sign-in and the encrypted document vault.

Each parent or student device makes two key pairs in its own browser and keeps the private halves there:
  - Ed25519 (signing): proves "this is that device" at sign-in, and signs payment approvals (parents only).
  - X25519 (encryption): vault files are locked to this public key; only the device's private key can unlock them.
The server stores public keys and ciphertext only. It cannot read a vault file or sign in as anyone.
Enrolling a device (parent's or student's) needs the parent's PIN.
"""
import secrets
import time

from security.pki import b64d, key_id, verify_b64

SIGN_IN_CONTEXT = b"tuitionpilot-sign-in:"  # domain separation: a sign-in signature can never pass as an approval
CHALLENGE_TTL = 120  # seconds
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DOCS = 50
ROLES = ("parent", "student")


class FamilyError(ValueError):
    pass


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
        self.docs = {}         # doc_id -> sealed document (ciphertext + one wrapped key per allowed device)

    # ---------- devices ----------
    def register(self, pin, role, public_key, box_key, label=""):
        """Enrol a device. Needs the parent's PIN for either role. Returns a policy Decision."""
        if role not in ROLES:
            raise FamilyError("role must be parent or student")
        _raw(box_key, "encryption key", size=32)
        label = str(label or f"{role} device")[:40]
        if role == "parent":
            d = self.policy.register_parent_key(pin, public_key, label)  # also lets this key sign approvals
        else:
            d = self.policy.register_student_key(pin, public_key, label)
        if d.allowed:
            self.devices[key_id(b64d(public_key))] = {"role": role, "public_key": public_key, "box_key": box_key,
                                                      "label": label}
        return d

    def listing(self):
        return [{"key_id": k, **v} for k, v in sorted(self.devices.items())]

    # ---------- sign-in: sign a one-time challenge with the device key ----------
    def challenge(self):
        now = self.clock()
        self._challenges = {n: t for n, t in self._challenges.items() if t > now}
        nonce = secrets.token_hex(16)
        self._challenges[nonce] = now + CHALLENGE_TTL
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
