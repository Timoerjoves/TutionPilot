"""Masking layer and the "what the model saw" log.

Identifiers (person names, PAN, Aadhaar, passport, account, email, phone) become tokens like <PAN_1>
before any text reaches the model. The token -> value vault stays in memory, is never logged,
and is used only to put real values back into drafts the user sees.
ModelSawLog records exactly what was sent to the model and refuses to record (or send) raw identifiers.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

# Order matters: longer and more specific patterns first, so a 12-digit Aadhaar is not taken as an account.
PATTERNS = [
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.I)),
    ("AADHAAR", re.compile(r"\b[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")),
    ("PHONE", re.compile(r"(?:\+91[ -]?)?\b[6-9][0-9]{9}\b")),
    ("ACCOUNT", re.compile(r"\b[0-9]{9,18}\b")),
    ("PASSPORT", re.compile(r"\b[A-Z][0-9]{7}\b")),
]
TOKEN = re.compile(r"<(?:NAME|PAN|AADHAAR|EMAIL|PHONE|ACCOUNT|PASSPORT)_\d+>")
# A person's name is the value after a label at the start of a line, up to the line end or " (".
# The label is followed by ":" or a spaced " - ", so "Student-ID: ..." is not a name.
# No bare "Name:" label: invoices use it for the university, which stays visible (public, needed to read the payee).
# shortcut: only labelled or remembered names are found; a name first seen in free text gets through.
# Upgrade if invoices or chat start carrying names in prose.
NAME_LINE = re.compile(
    r"(?im)^([ \t]*(?:student|parent|father|mother|guardian|remitter|sender)(?:'s)?(?: name)?(?:[ \t]*:|[ \t]+-)[ \t]*)"
    r"([^\s(<][^\n(<]*?)(?=[ \t]*\(|[ \t]*$)")


class LeakError(ValueError):
    """Raised when text about to reach the model still contains a raw identifier."""


def find_identifiers(text):
    """Return [(kind, value)] for every raw identifier in text (tokens are ignored)."""
    found = [("NAME", m.group(2)) for m in NAME_LINE.finditer(TOKEN.sub(" ", text))]
    for kind, pat in PATTERNS:
        for m in pat.finditer(TOKEN.sub(" ", text)):
            found.append((kind, m.group(0)))
    return found


class Masker:
    def __init__(self):
        self._vault = {}     # token -> value
        self._tokens = {}    # normalised value -> token
        self._counts = {}
        self._names = []     # every name masked so far, so later mentions are masked too

    def _token_for(self, kind, value):
        key = (kind, re.sub(r"[ -]", "", value).upper())
        if key not in self._tokens:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = f"<{kind}_{self._counts[kind]}>"
            self._tokens[key] = token
            self._vault[token] = value
        return self._tokens[key]

    def remember_name(self, value):
        """Mask this name wherever it appears from now on (for names the family types in)."""
        value = " ".join(value.split())
        if not value:
            return None
        if value.lower() not in (n.lower() for n in self._names):
            self._names.append(value)
        return self._token_for("NAME", value)

    def _labelled_name(self, m):
        value = " ".join(m.group(2).split())
        # Remember only full names (two or more words) for later mentions: a one-word value such as
        # "self" or "Fee" would otherwise mask that word everywhere. One-word values are masked here only.
        token = self.remember_name(value) if " " in value else self._token_for("NAME", value)
        return m.group(1) + token

    def mask(self, text):
        text = NAME_LINE.sub(self._labelled_name, text)
        for name in sorted(self._names, key=len, reverse=True):
            # any spacing or line break between the words; (?<!\w)/(?!\w) also work when the name ends in "."
            pattern = r"(?<!\w)" + r"\s+".join(map(re.escape, name.split())) + r"(?!\w)"
            text = re.sub(pattern, self._token_for("NAME", name), text, flags=re.I)
        for kind, pat in PATTERNS:
            text = pat.sub(lambda m, k=kind: self._token_for(k, m.group(0)), text)
        return text

    def mask_obj(self, obj):
        """Mask every string inside a dict/list structure (keys are left alone)."""
        if isinstance(obj, str):
            return self.mask(obj)
        if isinstance(obj, dict):
            return {k: self.mask_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask_obj(v) for v in obj]
        return obj

    def unmask(self, text):
        return TOKEN.sub(lambda m: self._vault.get(m.group(0), m.group(0)), text)

    def unmask_obj(self, obj):
        """Put real values back into every string of a dict/list (for what the user sees, never for the model)."""
        if isinstance(obj, str):
            return self.unmask(obj)
        if isinstance(obj, dict):
            return {k: self.unmask_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.unmask_obj(v) for v in obj]
        return obj

    def __repr__(self):  # never print the vault
        return f"Masker({len(self._vault)} tokens)"


class ModelSawLog:
    """Append-only JSON-lines log of everything sent to the model, after masking."""

    def __init__(self, path=None):
        self.path = Path(path) if path else None  # None: keep entries in memory only
        self.entries = []

    def record(self, purpose, masked_text):
        leaks = find_identifiers(masked_text)
        if leaks:
            # Do not echo the values: name only the kinds.
            raise LeakError(f"refusing to send unmasked identifiers to the model: {sorted({k for k, _ in leaks})}")
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "purpose": purpose,
            "sha256": hashlib.sha256(masked_text.encode("utf-8")).hexdigest(),
            "text": masked_text,
        }
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry


def prepare_for_model(masker, log, purpose, text):
    """The one door to the model: mask, check nothing raw is left, log, return what may be sent."""
    masked = masker.mask(text)
    log.record(purpose, masked)
    return masked
