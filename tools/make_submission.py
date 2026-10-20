"""Build the submission package the organisers asked for: one ZIP, the team name in every file name.

    python tools/make_submission.py                      # -> submission/TuitionPilot_Submission.zip
    python tools/make_submission.py --video URL          # also writes the demo-video link file (item 03)

Markdown documents become PDFs: GitHub's public Markdown API renders them (the repository is public anyway), then
headless Microsoft Edge prints them. Windows only for the PDF step; everything else is the standard library.
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
BLOB = f"https://github.com/{REPO}/blob/main/"
EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
OUT = ROOT / "submission"
PACK = OUT / f"{TEAM}_Submission"

DOCS = [  # (file name after the team name, title, Markdown sources)
    ("00_Submission_Index", "Submission index", ["SUBMISSION.md"]),
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
        target = (base / path).as_posix()
        target = re.sub(r"[^/]+/\.\./", "", target)  # docs/../README.md -> README.md
        if attr == "src":
            return f'src="{(ROOT / target).resolve().as_uri()}"'
        return f'href="{BLOB}{target}{"#" + frag if frag else ""}"'
    return re.sub(r'(href|src)="([^"]+)"', fix, html)


def to_pdf(name, title, sources):
    parts = "".join(f'<section class="{"part" if i else ""}">{render(s)}</section>' for i, s in enumerate(sources))
    html = (f'<!doctype html><html><head><meta charset="utf-8"><title>{TEAM} - {title}</title><style>{CSS}</style></head>'
            f'<body><div class="run">{TEAM} · 2026 Shenzhen FinTechathon, International Track, Topic C · '
            f'Synthetic data only · github.com/{REPO}</div>{parts}</body></html>')
    page = OUT / "build" / f"{TEAM}_{name}.html"
    page.write_text(html, encoding="utf-8")
    pdf = PACK / f"{TEAM}_{name}.pdf"
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--user-data-dir={OUT / 'build' / 'edge'}", f"--print-to-pdf={pdf}", page.as_uri()],
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
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "build").mkdir(parents=True)
    PACK.mkdir()
    for name, title, sources in DOCS:
        print("PDF", to_pdf(name, title, sources).name)
    for ext in ("pdf", "pptx"):
        shutil.copy(ROOT / "docs" / "presentation" / f"TuitionPilot_deck.{ext}", PACK / f"{TEAM}_02_Presentation_Deck.{ext}")
    if args.video:
        (PACK / f"{TEAM}_03_Demo_Video_Link.txt").write_text(
            f"{TEAM} demo video (up to 5 minutes): {args.video}\nScript: {BLOB}docs/DEMO_SCRIPT.md\n", encoding="utf-8")
    src = PACK / f"{TEAM}_04_Source_Code.zip"  # exactly the committed tree of HEAD
    subprocess.run(["git", "-C", str(ROOT), "archive", "--format=zip", f"--prefix={TEAM}_Source/", "-o", str(src), "HEAD"],
                   check=True)
    (PACK / f"{TEAM}_04_GitHub_Link.txt").write_text(
        f"{TEAM} source code: https://github.com/{REPO}\nRun: python -m app.server (Python 3.10+, standard library only)\n"
        f"Tests: python -m unittest discover -s tests -t .\n", encoding="utf-8")
    zip_tree(PACK / f"{TEAM}_06_Execution_Evidence.zip", ROOT / "data" / "evidence", f"{TEAM}_Execution_Evidence",
             skip={"runs"})
    final = OUT / f"{TEAM}_Submission.zip"
    zip_tree(final, PACK, PACK.name)
    print(f"{final}  {final.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
