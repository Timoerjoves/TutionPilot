# TuitionPilot: project submission

2026 Shenzhen International FinTech Competition · International Track · Topic C (Cross-border & Student Finance)
Team **TuitionPilot**: Chandan (lead), Nishanth · Source code: [https://github.com/Timoerjoves/TutionPilot](https://github.com/Timoerjoves/TutionPilot)

> Synthetic data only. Payments run in a simulated bank; no real money moves. Not tax advice. Not RBI-approved.

TuitionPilot is an AI agent that helps an Indian family pay university tuition abroad: it verifies the university's signed invoice,
works out the LRS limit, TCS and the real cost of each route, plans when to send, drafts the A2-style form, and pays inside a
sandbox bank only after a parent's own device signs the exact plan.

## Deliverables

| # | Deliverable | Required | Files (click to open) |
|---|---|---|---|
| 01 | Technical documentation | Mandatory | [TuitionPilot_01_Technical_Documentation.pdf](TuitionPilot_01_Technical_Documentation.pdf) |
| 02 | Presentation deck (designed for 10 minutes; 11 slides, about 9 minutes) | Mandatory | [TuitionPilot_02_Presentation_Deck.pdf](TuitionPilot_02_Presentation_Deck.pdf) · [TuitionPilot_02_Presentation_Deck.pptx](TuitionPilot_02_Presentation_Deck.pptx) |
| 03 | Demo video (up to 5 minutes) | Optional | [Watch the demo video](https://drive.google.com/file/d/1fHZ_CLmVwT3-i_xDXy14E2ADuA9uPnxF/view?usp=sharing) |
| 04 | Source code with README and GitHub link | Optional | Repository: [https://github.com/Timoerjoves/TutionPilot](https://github.com/Timoerjoves/TutionPilot) · [TuitionPilot_04_README.pdf](TuitionPilot_04_README.pdf) · [Download all code as ZIP](https://github.com/Timoerjoves/TutionPilot/archive/refs/heads/main.zip) |
| 05 | Security self-assessment report | Optional | [TuitionPilot_05_Security_Self_Assessment.pdf](TuitionPilot_05_Security_Self_Assessment.pdf) |
| 06 | Execution evidence | Optional | [TuitionPilot_06_Execution_Evidence_Summary.pdf](TuitionPilot_06_Execution_Evidence_Summary.pdf) · [TuitionPilot_06_Execution_Evidence.zip](TuitionPilot_06_Execution_Evidence.zip) (sandbox ledger, hash-chained audit log, what-the-model-saw log, scenario results) |

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
