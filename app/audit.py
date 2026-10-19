"""Hash-chained audit log with a verify command.

Each entry stores the hash of the one before it, so changing, deleting or reordering any entry breaks the chain.
Entries hold masked data only.

Verify a saved log from the repo root:   python -m app.audit verify data/evidence/audit_log.jsonl
"""
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contract import canonical_json

GENESIS = "0" * 64
IST = timezone(timedelta(hours=5, minutes=30))


def entry_hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


class AuditLog:
    tap = None  # the attack lab sets a list here to collect every entry a lab run writes (server calls hold one lock)

    def __init__(self, path=None):
        self.entries = []
        self.path = Path(path) if path else None

    @property
    def head(self):
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, event, data=None, session=None):
        e = {"seq": len(self.entries) + 1, "at": datetime.now(IST).isoformat(timespec="seconds"),
             "event": event, "session": session, "data": data or {}, "prev": self.head}
        e["hash"] = entry_hash(e)
        self.entries.append(e)
        if AuditLog.tap is not None:
            AuditLog.tap.append(e)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        return e

    def verify(self):
        return verify(self.entries)

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.entries), encoding="utf-8")


def verify(entries):
    """{"ok": bool, "entries": n, "first_bad_seq": int or None, "reason": str}."""
    prev = GENESIS
    for i, e in enumerate(entries, start=1):
        if e.get("seq") != i:
            return {"ok": False, "entries": len(entries), "first_bad_seq": i, "reason": "entry missing or out of order"}
        if e.get("prev") != prev:
            return {"ok": False, "entries": len(entries), "first_bad_seq": i, "reason": "chain broken (prev hash)"}
        if e.get("hash") != entry_hash(e):
            return {"ok": False, "entries": len(entries), "first_bad_seq": i, "reason": "entry contents changed"}
        prev = e["hash"]
    return {"ok": True, "entries": len(entries), "first_bad_seq": None, "reason": "chain intact"}


def load(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "verify":
        print("usage: python -m app.audit verify PATH")
        return 2
    r = verify(load(argv[1]))
    print(("OK: " if r["ok"] else "TAMPERED: ") + f"{r['entries']} entries, {r['reason']}"
          + (f" at entry {r['first_bad_seq']}" if r["first_bad_seq"] else ""))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
