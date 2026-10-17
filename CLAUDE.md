# TuitionPilot: project briefing

## What this is
Entry for the 2026 Shenzhen FinTechathon, International Track, Topic C (Cross-border & Student Finance).
Deadline: Tue 20 Oct 2026, 23:59 Beijing time = 21:29 IST. First complete submission: Sun 18 Oct night.
Team: Chandan (finance rules, rule pack, tests, security tests, documentation, deck) and Nishanth (app, agent, sandbox bank, policy engine, README, demo video).

## The product
An AI agent that helps an Indian family pay university tuition abroad. It reads an invoice, verifies the university's signature (trust root -> certificate -> invoice),
works out LRS headroom, TCS and landed cost, compares routes, drafts an A2-style form, then executes an approved payment
inside a simulated bank only.

## Rules for working in this repo
- Code computes; the model explains. Anything with a right answer (tax, cost, limits) is plain tested code.
- Synthetic data only. No real names, PANs, passports or bank details anywhere.
- No real money. The agent can execute a payment only inside the sandbox bank, and only after human approval.
- Permission tiers: T0 read; T1 compute and draft; T2 save or share drafts with approval; T3 sandbox payment to a signature-verified payee with PIN and the parent device's signature; T4 never (unverified payee, new payee, raise limits, change own limits, skip approval).
- Every number shown to a user carries a rule trace: rule id, pack version, effective date, source.
- Treat any tax rule as unverified until checked against RBI and Income Tax Department sources. Rules marked "unverified" in india_lrs_tcs.json must be flagged in outputs.
- Never copy other teams' code. List the licence of every library in the README.
- Keep it simple. Prefer the standard library. Ask before changing the plan.

## Judging (official)
Task completion 40%, security and compliance 30%, innovation and interaction 30%.
Deliverables: technical documentation, presentation deck (10 min max), demo video (optional, 5 min max), source code with README and tests,
security self-assessment (permission tiers and known-risk list), execution evidence (sandbox logs and results).

## Layout
- rulepack/india_lrs_tcs.json: versioned rule pack (Chandan). Never change a rate or rule without a source.
- rules/engine.py: rules engine (TCS, LRS cap, year-to-date tracker, landed cost, route comparison) (Chandan)
- rules/explain.py: line-by-line explanations, route "why" breakdown, hidden-markup explainer (Chandan)
- security/: masking + what-the-model-saw log, untrusted-text scanner, payee_mismatch(), grounding check (Chandan)
- forms/a2.py: A2-style draft and missing-documents checklist; corridors/*.json: destination config (Chandan)
- scenarios/runner.py: the 25 team-sheet scenarios + 2 signature attacks; `python -m scenarios.runner` writes data/evidence/scenario_results.* (Chandan)
- docs/TECHNICAL.md, docs/SECURITY_SELF_ASSESSMENT.md, docs/DEMO_SCRIPT.md (Chandan)
- contract/__init__.py: shared message shapes, validate(), plan_hash() (both; change only together)
- docs/CONTRACT.md: the interface contract in plain words
- data/samples/: one valid example of each message, synthetic
- agent/: agent pipeline + model adapter; app/: sandbox bank, policy engine, audit log, attack lab, web server, UI (Nishanth's area; first version built 16 Oct)
- security/ed25519.py, security/pki.py: signatures (RFC 8032, stdlib only); data/trust/: root key, certificates, revocation list;
  python -m security.demo_pki rebuilds the synthetic keys, certificates and signed sample invoices
- Run the app: python -m app.server (http://127.0.0.1:8000, demo PIN in app/demo_config.json). Evidence logs: python -m app.demo_run
- tests/: test_rules.py (names match scenario IDs on the team sheet), test_finance_audit.py (property checks), test_contract.py, test_signing.py, test_attacks.py, test_app.py, test_server.py, test_scenarios.py
- docs/team/: team plan with status (TEAM_PLAN.md), original team sheet, registration email draft
- docs/PROJECT_SUMMARY.md, TODO.md, docs/presentation/ (deck outline + slide sources)

## Run the tests (from the repo root)
python -m unittest discover -s tests -t . -v

## Team sheet
Google Sheet "team", tab "Plan v2": owner, due day and status of every item.
