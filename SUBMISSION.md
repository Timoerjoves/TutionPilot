# Submission index

2026 Shenzhen FinTechathon · International Track · Topic C (Cross-border & Student Finance Assistant)
Team: Chandan, Nishanth · Repository: https://github.com/Timoerjoves/TutionPilot

> Synthetic data only. No real money: payments run in a sandbox bank. Not tax advice. Not RBI-approved.

Each item below is one entry of the official submission checklist (PBCSF Appendix 2).

| # | Deliverable (Appendix 2) | What is required | Where |
|---|---|---|---|
| 01 | Technical documentation | System architecture, core algorithm description, security design | [docs/TECHNICAL.md](docs/TECHNICAL.md): architecture (section 2, with [diagram](docs/architecture.png)), core algorithms (section 3), security design (section 4) |
| 02 | Presentation deck | Final presentation no longer than 10 minutes | [TuitionPilot_deck.pptx](docs/presentation/TuitionPilot_deck.pptx) and [PDF](docs/presentation/TuitionPilot_deck.pdf), 11 slides, about 9 minutes, with app screenshots (also in [docs/screenshots/](docs/screenshots/)); outline and timings in [PRESENTATION.md](docs/presentation/PRESENTATION.md) |
| 03 | Demo video (optional) | No longer than 5 minutes | Script: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). Video link: *to be added* |
| 04 | Source code | README, GitHub repository link, deployment instructions, test cases | [README.md](README.md) (quick start: `python -m app.server`, standard library only); 249 tests in [tests/](tests/), run with `python -m unittest discover -s tests -t .`; CI in [.github/workflows/tests.yml](.github/workflows/tests.yml) |
| 05 | Security self-assessment report | Permission-tier implementation and known-risk list | [docs/SECURITY_SELF_ASSESSMENT.md](docs/SECURITY_SELF_ASSESSMENT.md): tiers T0–T4 (section 3), known risks R1–R26 (section 7) |
| 06 | Execution evidence | Simulated-account / sandbox operation logs and demo video | [data/evidence/](data/evidence/README.md): sandbox ledger, hash-chained audit log (153 entries, verifies), what-the-model-saw log, 27/27 scenario results; demo video as in 03 |

## Check it yourself in five minutes

    python -m unittest discover -s tests -t .              # 249 tests
    python -m scenarios.runner                              # 27 scenarios -> data/evidence/scenario_results.md
    python -m app.demo_run                                  # sandbox run -> data/evidence/demo/
    python -m app.audit verify data/evidence/demo/audit_log.jsonl
    python -m app.server                                    # app at http://127.0.0.1:8000, demo PIN 2468

Test invoices to drag into the app: [data/invoices/upload/](data/invoices/upload/) (four genuine signed invoices, five attacks).

## Integrity and licences

All code was written by the team for this competition. The app uses the Python standard library and the browser's built-in Web Crypto only; third-party licences are listed in the [README](README.md#licences). All data is synthetic.
