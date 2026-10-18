# Team plan and status

The source is the team sheet "Plan v2" (`TuitionPilot_Gap_Analysis_and_Plan_v3.xlsx` in this folder, as it was on 16 Oct). The **Status on 17 Oct** column is new. It says what is in this repository now.

- **Deadline:** Tue 20 Oct 2026, 23:59 Beijing = **21:29 IST**.
- **First complete submission:** Sun 18 Oct night.
- **Scoring:** task completion 40%, security & compliance 30%, innovation & interaction 30%.

> Note for Nishanth: on 16–17 Oct Chandan built first versions of the items in your area as well (agent, sandbox bank, policy engine, audit log, UI, README, CI), so the team has a complete draft. Please review them and change anything you planned differently. See [../../TODO.md](../../TODO.md).

## Plan v2 items

| # | Area | Item | Owner | Due | Status on 17 Oct | Where |
|---|---|---|---|---|---|---|
| 1 | Task completion | Rules engine with tests (LRS cap, TCS cases, landed cost) | Chandan | Sat 17 | ✅ Done | `rules/engine.py`, `tests/test_rules.py`, `tests/test_finance_audit.py` |
| 2 | Task completion | Year-to-date tracker across all LRS purposes | Chandan | Sat 17 | ✅ Done, and the agent now uses it | `rules/engine.py: YTDTracker` |
| 3 | Task completion | Route comparison with line-by-line explanation | Chandan | Sat 17 | ✅ Done; every line now has a source, and `compare_quotes()` takes an invoice + 2–4 quotes | `rules/explain.py`, `tests/test_route_lines.py` |
| 4 | Task completion | Sandbox bank and ledger | Nishanth | Sat 17 | ✅ First version | `app/sandbox.py` |
| 5 | Task completion | Multi-step plan with clarification questions | Nishanth | Sun 18 | ✅ First version | `agent/agent.py` |
| 6 | Task completion | Invoice extraction and payee check | Nishanth | Sat 17 | ✅ Done; payee check is now **signature-based** | `agent/model.py`, `security/pki.py` |
| 7 | Task completion | A2-style form draft and missing-documents checklist | Chandan | Mon 19 | ✅ Done | `forms/a2.py` |
| 8 | Task completion | Scenario runner with 25 scenarios and a results report | Chandan | Sun 18 | ✅ Done: 27 scenarios (25 + 2 signature attacks), all pass | `scenarios/runner.py` |
| 9 | Compliance | Rule pack JSON with source, effective date, version | Chandan | Fri 16 | ✅ Done; some rules still unverified (see TODO) | `rulepack/india_lrs_tcs.json` |
| 10 | Compliance | Rule trace on every number | Chandan | Sat 17 | ✅ Done | engine trace, UI "Rules" tab |
| 11 | Compliance | Labels: synthetic data, not tax advice, not RBI-approved | Nishanth | Sun 18 | ✅ Done | UI, receipt, A2 draft |
| 12 | Compliance | Escalate to a human when data is missing or unusual | Nishanth | Sun 18 | ✅ First version | `agent/agent.py` escalations |
| 13 | Compliance | Consent screen and delete-my-data | Nishanth | Mon 19 | ✅ First version | UI step 1, footer |
| 14 | Compliance | Corridor as a config file (USA, UK) | Chandan | Mon 19 | ✅ Done | `corridors/` |
| 15 | Security | Permission tiers T0–T4 in a policy engine | Nishanth | Sat 17 | ✅ First version | `app/policy.py` |
| 16 | Security | Masking layer plus what-the-model-saw log | Chandan | Sat 17 | ✅ Done; names now masked too | `security/masking.py`, `tests/test_masking.py` |
| 17 | Security | Attack test set of 8 cases | Chandan | Sun 18 | ✅ Done, plus 16-attack lab in the UI | `tests/test_attacks.py`, `app/lab.py` |
| 18 | Security | Model output checked against the rules engine | Chandan | Sun 18 | ✅ Done | `security/grounding.py` |
| 19 | Security | Approval bound to a hash of the exact plan | Nishanth | Sat 17 | ✅ Done, now **signed by the parent's device** | `security/pki.py`, `app/policy.py` |
| 20 | Security | Per-payment cap, emergency stop, circuit breaker | Nishanth | Sun 18 | ✅ First version | `app/policy.py` |
| 21 | Security | Hash-chained audit log with a verify command | Nishanth | Sat 17 | ✅ First version | `app/audit.py` |
| 22 | Security | Security self-assessment | Chandan | Sun 18 | ✅ Draft v0.3 | `docs/SECURITY_SELF_ASSESSMENT.md` |
| 23 | Innovation | Explain panel: live steps, policy decisions, rule trace | Nishanth | Mon 19 | ✅ First version ("Agent, live" panel) | `app/static/` |
| 24 | Innovation | Decision receipt | Nishanth | Sun 18 | ✅ First version | UI step 6 |
| 25 | Innovation | Hidden-markup explainer | Chandan | Sat 17 | ✅ Done; names its mid-market source | `rules/explain.py`, `tests/test_markup.py` |
| 26 | Innovation | Clear screens (planned: three) | Nishanth | Sun 18 | ✅ First version: a 6-step guided story + attack lab | `app/static/` |
| 27 | Innovation | Student and parent role switch | Nishanth | Mon 19 | ✅ First version | top bar |
| 28 | Innovation | Loan versus savings scenarios | – | – | Dropped (unverified rule) | |
| 29 | Innovation | FX timing advice | – | – | Dropped (advice-like) | |
| 30 | Deliverables | Registration email with form and watermarked passport pages | Chandan | Fri 16 | ⏳ **To do: send it** (draft ready) | `REGISTRATION_EMAIL.md` |
| 31 | Deliverables | Repo skeleton, tooling, folders | Nishanth | Fri 16 | ✅ Done | whole repo |
| 32 | Deliverables | Interface contract | Both | Fri 16 | ✅ Done, now **v1.1** with signatures | `docs/CONTRACT.md` |
| 33 | Deliverables | Technical documentation | Chandan | Sun 18 | ✅ Draft v0.3 | `docs/TECHNICAL.md` |
| 34 | Deliverables | README, deployment instructions, one-command test run | Nishanth | Sun 18 | ✅ First version | `README.md` |
| 35 | Deliverables | Presentation deck, 10 minutes or less | Chandan | Mon 19 | ✅ Draft, 8 slides; Nishanth to review slides 2 and 6 | `docs/presentation/` |
| 36 | Deliverables | Demo video, 3–5 minutes | Nishanth | Mon 19 | ⏳ To do: record (script ready) | `docs/DEMO_SCRIPT.md` |
| 37 | Deliverables | Execution evidence pack | Chandan | Mon 19 | ✅ Done | `data/evidence/` |
| 38 | Deliverables | First complete submission by Sun 18 night | Chandan | Sun 18 | ⏳ To do | |
| 39 | Deliverables | Final check and final submission | Both | Tue 20 | ⏳ To do | |
| 40 | Extras | GitHub Actions workflow that runs the tests | Nishanth | Mon 19 | ✅ File ready; runs once the repo is on GitHub | `.github/workflows/tests.yml` |
| 41 | Extras | Encryption vault, extra corridors, real integrations | – | – | Dropped | |

**Added on 17 Oct (not in Plan v2):**
- signed university invoices with a trust root and revocation;
- parent device signing;
- the finance audit;
- what-if sliders;
- the attack lab.

## Scenarios (team sheet "Test scenarios" + 2 new)

All 27 pass (`python -m scenarios.runner` → `data/evidence/scenario_results.md`).

| Group | IDs | Result |
|---|---|---|
| Task completion | A1–A10 | 10 / 10 pass (A5, A6 use unverified rules and are flagged) |
| Safe execution | B1–B6 | 6 / 6 pass |
| Attacks | C1–C7, **C8** forged approval, **C9** revoked key | 9 / 9 pass |
| Privacy | D1–D2 | 2 / 2 pass |

## Official deliverables (PBCSF Appendix 2)

| Deliverable | Status | Where |
|---|---|---|
| Technical documentation | Draft v0.3 | `docs/TECHNICAL.md` |
| Presentation deck (≤ 10 min) | Draft, 8 slides | `docs/presentation/` |
| Demo video (optional, ≤ 5 min) | Script ready, not recorded | `docs/DEMO_SCRIPT.md` |
| Source code with README and tests | Ready | this repo |
| Security self-assessment | Draft v0.3 | `docs/SECURITY_SELF_ASSESSMENT.md` |
| Execution evidence | Ready | `data/evidence/` |
