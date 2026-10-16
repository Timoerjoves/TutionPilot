# TuitionPilot

AI agent that helps an Indian family pay university tuition abroad: reads the invoice, verifies the payee,
computes LRS headroom, TCS and landed cost, compares routes, drafts an A2-style form, and executes an approved
payment **inside a simulated bank only**.

2026 Shenzhen FinTechathon, International Track, Topic C. Team: Chandan, Nishanth.

> Synthetic data only. No real money. Not tax advice. Tax rules marked "unverified" are flagged in every output.

## Run the tests
Python 3.10+ only, no installs needed:

    python -m unittest discover -s tests -t . -v

## Layout
| Folder | What | Owner |
|---|---|---|
| `rulepack/` | Versioned rules with source, status and effective date | Chandan |
| `rules/` | Rules engine and line-by-line explanations | Chandan |
| `security/` | Masking + what-the-model-saw log, attack scanner, payee check, grounding check | Chandan |
| `forms/` | A2-style draft and missing-documents checklist | Chandan |
| `corridors/` | Destination config (India to USA, India to UK) | Chandan |
| `scenarios/` | 25-scenario runner and synthetic fixtures | Chandan |
| `contract/` | Shared message shapes, validation, plan hash | Both |
| `agent/`, `app/` | Agent, sandbox bank, policy engine, UI | Nishanth |
| `data/samples/` | Synthetic example messages | Both |
| `data/evidence/` | Scenario results and sandbox logs (execution evidence) | Both |
| `tests/` | Unit, contract, attack and scenario tests | Chandan |
| `docs/` | Contract, [technical docs](docs/TECHNICAL.md), [security self-assessment](docs/SECURITY_SELF_ASSESSMENT.md), [demo script](docs/DEMO_SCRIPT.md) | Chandan |

## Run the 25 scenarios
Writes `data/evidence/scenario_results.md` and `.json`:

    python -m scenarios.runner

## Licences
Standard library only so far. List every added library and its licence here.
