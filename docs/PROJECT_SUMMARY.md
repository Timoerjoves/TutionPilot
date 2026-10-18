# TuitionPilot: project summary

**2026 Shenzhen FinTechathon · International Track · Topic C (Cross-border & Student Finance)**
Team: Chandan and Nishanth · Status on 18 Oct 2026: complete, all checks green.

> Synthetic data only. No real money. Not tax advice. Not RBI-approved.

## The problem
Every year Indian families send lakhs of rupees abroad for university fees. Before paying, they must work out four things on their own:

1. **How much of the yearly LRS limit is left?** The Liberalised Remittance Scheme allows USD 250,000 per person per financial year, counting all purposes together.
2. **How much TCS will the bank add?** Tax collected at source is 2% on the part above Rs 10 lakh for self-funded education and 0% for a loan from a notified institution. Every earlier remittance this year counts toward the threshold.
3. **Which route is really cheapest?** A low fee can hide a worse exchange rate, and the markup never shows up as a fee.
4. **Which papers does the bank want?** The A2 form, PAN, invoice, admission letter, passport and visa document.

On top of that, tuition fraud is real: an e-mail saying "our bank details have changed" is a classic way to steal fees.

## Our idea
**An AI agent that does all of this, explains every rupee, and can pay only after the parent's own device signs the exact plan, inside a simulated bank.**

Four design rules:
- **Code computes, the AI explains.** Tax, cost and limits come from tested Python with a versioned, sourced rule pack. The AI only reads the invoice and words explanations, and any number it writes must match the engine.
- **Signatures instead of lists.** We keep no list of "good" universities. One trust root certifies each university *and its bank account*. Universities sign their invoices, so a changed account breaks the signature.
- **The parent signs, not the agent.** The parent's browser holds a signing key the agent never sees. It signs the plan's hash, so the agent can neither forge an approval nor change the plan afterwards.
- **Permission tiers.**
  - T0: read.
  - T1: compute and draft.
  - T2: save or share, needs a click.
  - T3: sandbox payment, needs the PIN plus the device signature.
  - T4: never. That covers a new or unverified payee, changing limits and skipping approval.

## What the user sees: a guided story in six steps
1. **Welcome:** two consents before any data is read.
2. **Invoice:** an animated check of the signature chain, link by link.
3. **Questions:** one at a time; the agent asks instead of guessing.
4. **Best route:**
   - a chart of what each route costs on top of the real exchange value;
   - why the winner wins;
   - the hidden markup;
   - an LRS gauge;
   - what-if sliders that change the tax live.
5. **Review & sign:** a PIN pad; the device recomputes the plan hash and signs.
6. **Receipt:** the transaction, the university's certificate, the parent's signature and the audit entry.

Next to the story, an **Agent, live** panel shows every step and policy decision, the rule trace with sources, exactly what the AI saw (masked), and the audit chain. An **Attack lab** runs 16 attacks and shows which defence stopped each one.

## What is built (all in this repository)

| Part | Where |
|---|---|
| Rules engine: LRS, TCS, year-to-date, landed cost, route ranking, line-by-line explanations | `rules/`, `rulepack/` |
| Signatures (Ed25519 per RFC 8032, plain Python), trust root, certificates, revocation | `security/ed25519.py`, `security/pki.py`, `data/trust/` |
| Masking, "what the AI saw" log, attack scanner, grounding check | `security/` |
| A2-style form draft and document checklist; India→USA and India→UK corridors | `forms/`, `corridors/` |
| Agent (plan, questions, escalation, receipt) | `agent/` |
| Sandbox bank, policy engine, hash-chained audit log, attack lab, web app | `app/` |
| Shared message contract v1.1 | `contract/`, `docs/CONTRACT.md` |
| 27 scripted scenarios + evidence logs | `scenarios/`, `data/evidence/` |

**Added on 18 Oct 2026:**
- Passwordless sign-in for parent and student devices; roles are fixed at sign-in. A new device needs the PIN **and** an enrolled parent device's signature (risk R19, fixed).
- An encrypted family document vault: files are locked in the browser, and the server holds ciphertext only.
- PDF and JSON invoice intake, and nine drag-and-drop test invoices (`data/invoices/upload/`).
- A visible **Next action**: the agent picks its next step from the session's state, asks one targeted question when a field is missing, and resumes without repeating completed checks.
- A landing page and a calmer, minimal interface.

**Numbers (18 Oct 2026):**
- 239 tests pass.
- 27 of 27 scenarios pass.
- 16 of 16 attacks are stopped in the lab.
- The demo audit chain has 153 entries and verifies.
- A finance audit of 400 random cases matched an independent formula.

## Why it should score well

| Judging area | Weight | What we show |
|---|---|---|
| Task completion | 40% | End-to-end payment: invoice → checks → routes → A2 draft → signed approval → sandbox payment → receipt; 27 scenarios pass |
| Security & compliance | 30% | Signed invoices and approvals, tiers T0–T4, masking, grounding, audit chain, circuit breaker, emergency stop; sourced rule pack with "unverified" flags; honest self-assessment |
| Innovation & interaction | 30% | Signatures replace payee lists; India-specific TCS/LRS engine; guided UI with live agent panel, what-if sliders and an attack lab |

## Honest limits
- **Tax rules:** six verified against RBI and the Income-tax Act 2025 on 18 Oct; two still need a bank's confirmation, and outputs say so.
- **The AI step:** an offline stand-in; no hosted model is connected yet.
- **Signing code:** our Ed25519 is not hardened, and the demo keys are synthetic.

Full list: [SECURITY_SELF_ASSESSMENT.md](SECURITY_SELF_ASSESSMENT.md).

## Where to go next
- **Try it:** `python -m app.server`, then open http://127.0.0.1:8000 (see the [README](../README.md)).
- **What is left:** [TODO.md](../TODO.md).
- **Team plan and status:** [team/TEAM_PLAN.md](team/TEAM_PLAN.md).
- **Presentation:** [presentation/PRESENTATION.md](presentation/PRESENTATION.md).
