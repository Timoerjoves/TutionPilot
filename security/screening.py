"""Sanctions screening: are the remitter, the student or the payee on a sanctions list?

Run before a plan can be signed (rule aml_sanctions_screening). Names are compared after normalising case,
punctuation, word order and legal suffixes, so "PELLINOR, Zarvok" and "Zarvok Pellinor" match. A close but
not exact name (a spelling variant) is a possible match: a person at the bank must clear it; the agent never
decides that alone.
The list shipped here is SYNTHETIC (data/screening/watchlist_synthetic.json): invented names only.
"""
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

WATCHLIST = Path(__file__).resolve().parent.parent / "data" / "screening" / "watchlist_synthetic.json"
POSSIBLE = 0.80  # similarity of the normalised names; only an exact normalised name is a confirmed match
SUFFIXES = {"ltd", "limited", "llc", "inc", "fze", "pvt", "private", "co", "corp", "plc", "synthetic"}


def normalise(name):
    words = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower()).split()
    return " ".join(sorted(w for w in words if w not in SUFFIXES))


def load(path=WATCHLIST):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def screen(parties, watchlist):
    """parties: {role: name}. Returns {"status": clear|possible|match, "hits": [...], "screened": [roles]}."""
    hits = []
    for role, name in parties.items():
        n = normalise(name or "")
        if not n:
            continue
        best = max(((SequenceMatcher(None, n, normalise(alias)).ratio(), e)
                    for e in watchlist["entries"] for alias in [e["name"], *e["aliases"]]), key=lambda t: t[0])
        if best[0] >= POSSIBLE:
            hits.append({"role": role, "entry_id": best[1]["id"], "list": best[1]["list"], "listed_name": best[1]["name"],
                         "score": round(best[0], 2), "status": "match" if best[0] == 1 else "possible"})
    status = "match" if any(h["status"] == "match" for h in hits) else "possible" if hits else "clear"
    return {"status": status, "hits": hits, "screened": [r for r, n in parties.items() if normalise(n or "")],
            "list": watchlist["name"], "list_updated_on": watchlist["updated_on"]}
