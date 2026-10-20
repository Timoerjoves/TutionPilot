"""Build the submission folder the organisers asked for: the team name in every file name, documents as PDF.

    python tools/make_submission.py                      # -> submission/ (committed: the public link) and
                                                         #    submission_build/TuitionPilot_Submission.zip (one ZIP)
    python tools/make_submission.py --video URL          # adds the demo-video link (item 03)

submission/ is published through GitHub: https://github.com/Timoerjoves/TutionPilot/tree/main/submission
Markdown documents become PDFs: GitHub's public Markdown API renders them (the repository is public anyway), then
headless Microsoft Edge prints them. Run it from PowerShell on Windows; Edge does not print from Git Bash.
"""
import argparse
import json
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEAM = "TuitionPilot"
REPO = "Timoerjoves/TutionPilot"
GITHUB = f"https://github.com/{REPO}"
BLOB = f"{GITHUB}/blob/main/"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
OUT = ROOT / "submission"          # what judges open
BUILD = ROOT / "submission_build"  # scratch pages and the one-ZIP copy (not committed)
INDEX = f"{TEAM}_00_Submission_Index"

DOCS = [  # (file name after the team name, title, Markdown sources)
    (INDEX, "Submission index", [f"submission/{INDEX}.md"]),
    ("01_Technical_Documentation", "Technical documentation", ["docs/TECHNICAL.md"]),
    ("04_README", "README", ["README.md"]),
    ("05_Security_Self_Assessment", "Security self-assessment", ["docs/SECURITY_SELF_ASSESSMENT.md"]),
    ("06_Execution_Evidence_Summary", "Execution evidence",
     ["data/evidence/README.md", "data/evidence/scenario_results.md", "data/evidence/demo/demo_run.md"]),
]
CSS = """
@page { size: A4; margin: 16mm 15mm 18mm; }
body { font: 10.5pt/1.5 "Segoe UI", Arial, sans-serif; color: #111; }
.run { color: #666; font-size: 8.5pt; border-bottom: 1px solid #ddd; padding-bottom: 6px; margin-bottom: 14px; }
h1 { font-size: 20pt; margin: 0 0 8px; } h2 { font-size: 14pt; margin: 20px 0 6px; border-bottom: 1px solid #eee; padding-bottom: 3px; }
h3 { font-size: 11.5pt; margin: 14px 0 4px; } h2, h3 { break-after: avoid; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; break-inside: auto; }
th, td { border: 1px solid #ccc; padding: 4px 6px; vertical-align: top; text-align: left; }
th { background: #f3f3f3; } tr { break-inside: avoid; }
code { font: 8.8pt Consolas, monospace; background: #f4f4f4; padding: 0 3px; border-radius: 3px; }
pre { background: #f6f6f6; padding: 8px 10px; border-radius: 4px; white-space: pre-wrap; font-size: 8.5pt; }
pre code { background: none; padding: 0; }
img { max-width: 100%; } a { color: #1f5fa8; text-decoration: none; }
blockquote { border-left: 3px solid #ccc; margin: 8px 0; padding: 2px 10px; color: #444; }
.part { break-before: page; }
"""


def index_md(video):
    f = lambda name: f"[{TEAM}_{name}]({TEAM}_{name})"
    video_cell = f"[Watch the demo video]({video})" if video else "Link to be added"
    return f"""# {TEAM}: project submission

2026 Shenzhen International FinTech Competition · International Track · Topic C (Cross-border & Student Finance)
Team **{TEAM}**: Chandan (lead), Nishanth · Source code: [{GITHUB}]({GITHUB})

> Synthetic data only. Payments run in a simulated bank; no real money moves. Not tax advice. Not RBI-approved.

{TEAM} is an AI agent that helps an Indian family pay university tuition abroad: it verifies the university's signed invoice,
works out the LRS limit, TCS and the real cost of each route, plans when to send, drafts the A2-style form, and pays inside a
sandbox bank only after a parent's own device signs the exact plan.

## Deliverables

| # | Deliverable | Required | Files (click to open) |
|---|---|---|---|
| 01 | Technical documentation | Mandatory | {f("01_Technical_Documentation.pdf")} |
| 02 | Presentation deck (designed for 10 minutes; 11 slides, about 9 minutes) | Mandatory | {f("02_Presentation_Deck.pdf")} · {f("02_Presentation_Deck.pptx")} |
| 03 | Demo video (up to 5 minutes) | Optional | {video_cell} |
| 04 | Source code with README and GitHub link | Optional | Repository: [{GITHUB}]({GITHUB}) · {f("04_README.pdf")} · [Download all code as ZIP]({GITHUB}/archive/refs/heads/main.zip) |
| 05 | Security self-assessment report | Optional | {f("05_Security_Self_Assessment.pdf")} |
| 06 | Execution evidence | Optional | {f("06_Execution_Evidence_Summary.pdf")} · {f("06_Execution_Evidence.zip")} (sandbox ledger, hash-chained audit log, what-the-model-saw log, scenario results) |

## Run it yourself (Python 3.10 or newer, nothing to install)

    python -m app.server                               # then open http://127.0.0.1:8000, demo PIN 2468
    python -m unittest discover -s tests -t .          # 271 tests
    python -m scenarios.runner                         # 27 of 27 scenarios
    python -m app.audit verify data/evidence/demo/audit_log.jsonl

## At a glance

- 271 tests pass; 27 of 27 scripted scenarios pass; the attack lab stops 16 of 16 attacks; the demo audit chain verifies.
- Every number comes from tested code with a rule trace (rule id, pack version, effective date, source); 10 rules are verified
  against RBI and the Income-tax Act 2025, and the rest are flagged as unverified in every output.
- Permission tiers T0 to T4; a payment needs the parent's PIN and the parent device's Ed25519 signature over the plan hash.
"""


def render(md_path):
    """Markdown -> HTML as GitHub renders a README (tables, task lists), with links that work outside the repository."""
    text = (ROOT / md_path).read_text(encoding="utf-8")
    req = urllib.request.Request("https://api.github.com/markdown", method="POST",
                                 data=json.dumps({"text": text, "mode": "markdown"}).encode(),
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "tuitionpilot-submission"})
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8")
    base = Path(md_path).parent

    def fix(m):
        attr, url = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#)", url):
            return m.group(0)
        path, _, frag = url.partition("#")
        target = re.sub(r"[^/]+/\.\./", "", (base / path).as_posix())  # docs/../README.md -> README.md
        if attr == "src":
            return f'src="{(ROOT / target).resolve().as_uri()}"'
        return f'href="{BLOB}{target}{"#" + frag if frag else ""}"'
    return re.sub(r'(href|src)="([^"]+)"', fix, html)


def to_pdf(name, title, sources):
    parts = "".join(f'<section class="{"part" if i else ""}">{render(s)}</section>' for i, s in enumerate(sources))
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>{TEAM} - {title}</title><style>{CSS}</style></head>'
            f'<body><div class="run">{TEAM} · 2026 Shenzhen FinTechathon, International Track, Topic C · '
            f'Synthetic data only · github.com/{REPO}</div>{parts}</body></html>')
    page = BUILD / f"{name}.html"
    page.write_text(html, encoding="utf-8")
    pdf = OUT / f"{name if name.startswith(TEAM) else TEAM + '_' + name}.pdf"
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={BUILD / 'edge'}", f"--print-to-pdf={pdf}", page.as_uri()],
                   check=True, timeout=180)
    assert pdf.exists() and pdf.stat().st_size > 10_000, f"{pdf.name} was not printed"
    return pdf


def zip_tree(dest, folder, prefix, skip=()):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            rel = f.relative_to(folder)
            if f.is_file() and not any(part in skip for part in rel.parts):
                z.write(f, f"{prefix}/{rel.as_posix()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--video", help="public link to the demo video (item 03)")
    args = ap.parse_args()
    for d in (OUT, BUILD):
        shutil.rmtree(d, ignore_errors=True)  # a folder open in a shell or viewer survives; empty it instead
        d.mkdir(exist_ok=True)
        for f in d.iterdir():
            shutil.rmtree(f) if f.is_dir() else f.unlink()
    (OUT / f"{INDEX}.md").write_text(index_md(args.video), encoding="utf-8")
    for name, title, sources in DOCS:
        print("PDF", to_pdf(name, title, sources).name)
    for ext in ("pdf", "pptx"):
        shutil.copy(ROOT / "docs" / "presentation" / f"TuitionPilot_deck.{ext}", OUT / f"{TEAM}_02_Presentation_Deck.{ext}")
    zip_tree(OUT / f"{TEAM}_06_Execution_Evidence.zip", ROOT / "data" / "evidence", f"{TEAM}_Execution_Evidence",
             skip={"runs"})
    # one-ZIP copy for an e-mail attachment: the folder above plus exactly the committed source code
    src = BUILD / f"{TEAM}_04_Source_Code.zip"
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", f"--prefix={TEAM}_Source/", "-o", str(src), "HEAD"],
                   check=True)
    pack = BUILD / f"{TEAM}_Submission"
    shutil.copytree(OUT, pack)
    shutil.copy(src, pack / src.name)
    final = BUILD / f"{TEAM}_Submission.zip"
    zip_tree(final, pack, pack.name)
    print(f"{OUT}  (public via {GITHUB}/tree/main/submission)")
    print(f"{final}  {final.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
