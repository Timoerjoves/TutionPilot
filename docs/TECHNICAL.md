# TuitionPilot: technical documentation

Draft v0.3, 17 Oct 2026. Official deliverable: system architecture, core algorithm, security design.
Status marks: **Built** = in the repo with tests; **Planned** = designed, not built yet.

> Synthetic data only. No real money. Not tax advice. Tax rules marked "unverified" are flagged in every output.

## 1. What it does

An Indian family must pay a university abroad. Today they work out on their own:
- how much of the yearly Liberalised Remittance Scheme (LRS) limit they have left;
- how much tax collected at source (TCS) the bank will add;
- which bank or provider is really cheapest once the hidden exchange-rate markup is counted;
- which papers the bank wants.

TuitionPilot is an agent that reads the invoice, checks the payee, does those calculations, explains them line by line,
drafts the A2-style form, and pays only inside a simulated bank after a parent approves the exact plan with a PIN.

**Design rule: code computes, the model explains.** Every number with a right answer (tax, cost, limits) comes from
plain, tested Python. The language model only reads documents and puts the engine's results into words, and
even those words are checked (see 4.3).

## 2. Architecture

```
 Student / parent
       |  invoice + answers
       v
 [1 Intake] -> [2 Mask] -> [3 Extract (model)] -> [4 Verify university signature]
                                                         |
                       [5 Rules: LRS, TCS, landed cost] <-+
                                     |
                       [6 Compare routes + explain] -> [Form A2 draft + checklist]
                                     |
                       [7 Plan (multi-step, asks when data is missing)]
                                     |
                       [8 Policy gate: tier, caps, emergency stop]
                                     |
                       [9 Approve: parent device signs plan hash]
                                     |
                       [10 Execute in sandbox bank] -> [11 Receipt + audit log] -> [12 Timeline]
```

| Stage | Module | Owner | Status |
|---|---|---|---|
| 2 Mask | `security/masking.py` | Chandan | Built |
| 1 Intake, consent | `app/static/` UI, `agent/agent.py` | Nishanth | Built |
| 3 Extract | `agent/model.py` (offline deterministic adapter; a hosted model can plug in) | Nishanth | Built |
| 4 Payee check | `security/pki.py` (trust root → certificate → signed invoice), `security/ed25519.py` | Both | Built |
| 5 Rules | `rules/engine.py`, `rulepack/india_lrs_tcs.json` | Chandan | Built |
| 6 Compare + explain | `rules/engine.py: compare_routes()`, `rules/explain.py` | Chandan | Built |
| Form | `forms/a2.py`, `corridors/*.json` | Chandan | Built |
| Untrusted-text scan | `security/guard.py: scan()` | Chandan | Built |
| Grounding check | `security/grounding.py` | Chandan | Built |
| Messages between parts | `contract/__init__.py`, `docs/CONTRACT.md` | Both | Built |
| 7 Plan, questions, escalation | `agent/agent.py` | Nishanth | Built |
| 8 Policy gate | `app/policy.py` (tiers, PIN, cap, emergency stop, circuit breaker) | Nishanth | Built |
| 9 Approve | `agent/agent.py: approve()`: PIN + parent device signature over the plan hash | Both | Built |
| 10 Execute | `app/sandbox.py` (quotes, ledger, idempotent payments) | Nishanth | Built |
| 11 Record | `app/audit.py` (hash chain, verify command), decision receipt | Nishanth | Built |
| 12 Track | Timeline in the UI | Nishanth | Built |

Parts talk only through the five contract messages (`invoice`, `quote`, `rule_result`, `plan`, `approval`).
Every message is checked with `contract.validate()` before it is used. Money travels as a decimal string, never a float.

Standard library only (Python 3.10+). No third-party packages so far.

## 3. Core algorithms

All money uses Python `Decimal`. Rupee amounts are rounded to paise (half-up); TCS is rounded to the whole rupee.

### 3.1 Rule pack
`rulepack/india_lrs_tcs.json` holds every rate and threshold with:
- `value`
- `effective_from`
- `status` (`secondary-source` or `unverified`)
- `source`
- `check_against`: the primary source to confirm against
- the pack `version`

The engine never hard-codes a rate. Every result carries a **trace**: the rule id, pack version, effective date, status and source of each rule it used. Any rule marked `unverified` is listed in `needs_verification`, and the user interface must show it as unverified.

If a calculation is asked for a date before a rule took effect (for example, the 2% education rate before 1 April 2026), the engine refuses instead of guessing.

### 3.2 TCS on an education remittance
```
cumulative = earlier LRS remittances this financial year (all purposes) + this payment
taxable    = max(0, cumulative - max(earlier, threshold))      self-funded
taxable    = 0                                                 loan from a notified institution
TCS        = round_to_rupee(taxable x rate)
rate       = education self-funded rate, or the no-PAN rate if PAN is missing
```
`max(earlier, threshold)` means:
- if earlier payments already passed the threshold, the whole new payment is taxed;
- otherwise, only the part above the threshold is taxed.

The financial year runs from April to March (`financial_year()`).

`YTDTracker` adds up earlier remittances per person, for all purposes, within the same financial year. It ignores earlier years and future-dated entries.

### 3.3 LRS headroom
```
headroom_before = annual cap (USD) - earlier USD this year
headroom_after  = headroom_before - this payment (USD)
within_cap      = headroom_after >= 0       (false -> flag and stop)
```

### 3.4 Landed cost and route ranking
For each route (provider rate, fee, GST rate on the fee, correspondent charges):
```
remitted = foreign amount x provider rate
gst      = fee x GST rate (from the provider's fee schedule)
total    = remitted + fee + gst + correspondent + TCS on remitted
markup   = (provider rate - mid-market rate) x foreign amount      (the hidden cost)
```
Routes are ranked by `total`, cheapest first, and each route records its saving against the next one.

`rules/explain.py` turns the result into plain-English lines that code writes:
- one line per cost component;
- a summary ("Cheapest: Provider B at Rs 18,23,080, Rs 4,620 less than Provider A");
- a "why" breakdown (exchange rate, fee, GST, TCS) whose amounts add up exactly to the saving;
- a hidden-markup explainer.

Each line lists the rule ids it relied on and which of them are unverified.

### 3.5 A2-style draft and checklist
`forms/a2.py` fills an A2-shaped draft from:
- the invoice;
- the remitter's answers;
- the chosen route's numbers;
- the corridor file.

It always says it is a draft and not an official bank form.

The draft has three possible outcomes:
- **Ready:** all required fields are present.
- **Needs information:** a required field is missing. It becomes a question (for example the due date in scenario A9, or the PAN in A6), and the draft never guesses.
- **Blocked:** the invoice's signature chain fails, or the currency does not match the corridor.

The missing-documents checklist is taken from the corridor. For example, the visa document is the I-20 for the USA and the CAS for the UK, and the loan letter is only asked for when the payment is loan-funded.

### 3.6 Corridors as config
`corridors/in_us.json` and `corridors/in_gb.json` hold destination facts only: currency, purpose code and the student-visa document.

Switching from India→USA to India→UK is a file swap. The India rule pack is the same for both. New facts in the corridor files are marked `unverified`.

## 4. Security design

The full self-assessment and known-risk list are in [SECURITY_SELF_ASSESSMENT.md](SECURITY_SELF_ASSESSMENT.md).

### 4.1 Permission tiers
| Tier | Allowed | Approval |
|---|---|---|
| T0 | Read (invoice, signatures, history) | None |
| T1 | Compute and draft | None |
| T2 | Save or share drafts | Click |
| T3 | Sandbox payment to a signature-verified payee | PIN + parent device signature over the plan hash |
| T4 | New/unverified payee, raise or change limits, skip approval | Never |

### 4.2 Masking and the "what the model saw" log
`prepare_for_model()` is the only route to the model:
1. It replaces PAN, Aadhaar, passport, account, email and phone values with tokens such as `<PAN_1>`.
2. It checks that nothing raw is left.
3. It appends the masked text to `ModelSawLog`.

If a raw identifier remains, it raises `LeakError` and nothing is sent or logged. The token-to-value vault stays in memory, never in a log.

### 4.3 Grounding check
Before an explanation from the model is shown, `security.grounding.check()` pulls out every amount (Rs/INR/USD/GBP, lakh, crore) and every percentage.

Each one must match a number in the `rule_result` messages the model was given. Anything that does not match is rejected, and the engine's own wording is shown instead (scenario C5).

### 4.4 Untrusted text scanner and payee check
**`security.guard.scan()`** checks invoice, email and chat text before the agent acts on it. It flags:
- prompt injection;
- auto-approval requests;
- privilege escalation;
- payee changes;
- data extraction;
- pressure tactics.

It first undoes common disguises: Unicode tricks, zero-width characters and spaced-out letters.

**Signed invoices (4.6)** replace any list of payees. `payee_mismatch()` remains as a field-by-field comparison helper.

### 4.5 Plan-bound approval
`contract.plan_hash()` is the SHA-256 of the plan as sorted, compact JSON. An approval names the hash of the exact plan it approved. Any edit changes the hash, which voids the approval.

### 4.6 Signatures instead of lists

There is no list of "good" payees. TuitionPilot trusts **one root key** (`data/trust/root.json`).

**The chain of trust:**
- **Root:** signs a **certificate** for each university. The certificate names the university, its currency, its **bank account and SWIFT**, and the university's public key.
- **Revocation list:** root-signed (`data/trust/revoked.json`). It lists certificates that must no longer be trusted, for example after a leaked key.
- **University:** signs each invoice with its own key. The signed invoice travels inside the invoice text (`security/pki.py: embed / split`).

**`TrustStore.check_invoice()` checks every link in order:**
1. the certificate is signed by the root, in date, and not revoked;
2. the invoice signature verifies with the certificate's key;
3. the payee and bank details equal the certificate's subject;
4. the printed text matches the signed data (checked in the agent).

The agent then pays the signed data, never the printed text. The bank re-checks the certificate before moving money.

**Parent approvals.**
- **Set-up:** the parent's browser creates an Ed25519 key with WebCrypto. The key cannot be exported and stays in the browser's IndexedDB. Only the public key is registered, with the PIN.
- **Signing:** to approve, the browser recomputes the plan hash from the plan it shows, then signs the approval message (plan id, plan hash, tier, decision, method, time).
- **Checking:** the policy engine verifies that signature against the registered parent keys before any T3 payment.
- **Effect:** the agent never holds the parent's key, so it cannot forge an approval or change the plan after signing.

**The Ed25519 code.** `security/ed25519.py` is plain Python following RFC 8032. Tests check it against:
- the RFC's test vectors;
- a signature made by the browser's WebCrypto;
- many tamper cases.

Keys and signatures are base64. A signature always covers `contract.signed_bytes(msg)`: the canonical JSON of the message without its own signature field.

## 5. Testing and evidence

```
python -m unittest discover -s tests -t . -v     # unit, contract, attack and scenario tests
python -m scenarios.runner                        # 27 scenarios -> data/evidence/scenario_results.md
python -m app.demo_run                            # scripted run -> data/evidence/demo/ logs
python -m app.server                              # the app at http://127.0.0.1:8000
```

| Test file | Covers |
|---|---|
| `test_rules.py` | TCS cases A1-A6, LRS cap A7, routes A8, year-to-date, dates, rounding |
| `test_explain.py` | Explanation lines add up to the engine's totals; Indian number format |
| `test_contract.py` | Samples valid, plan hash, validation |
| `test_security.py` | Masking, model log, scanner, grounding |
| `test_attacks.py` | 8 attack cases (injection, induced transfer, data extraction, privilege escalation) |
| `test_forms.py` | Corridors, A2 draft, checklist, A9/A10 |
| `test_scenarios.py` | Runner: all 27 scenarios pass; pending is never counted as pass |
| `test_finance_audit.py` | 400-case property checks: TCS against an independent formula, split payments, totals, ranking, LRS, financial year |
| `test_signing.py` | Ed25519 (RFC 8032 vectors, browser WebCrypto signature), trust chain, revocation, signed approvals |
| `test_app.py` | Invoice reader, signed invoices, sandbox bank, policy engine, audit log, agent flow |
| `test_server.py` | Web server: static files, security headers, full payment over HTTP |

## 6. App, agent and sandbox

- **Sandbox bank** (`app/sandbox.py`): three synthetic providers quote as contract `quote` messages, valid for 30 minutes.
  - It pays at most once per approval id, so a second click returns the first transaction.
  - On its own, it refuses unknown or expired quotes, unverified payees and short balances.
- **Policy engine** (`app/policy.py`): every tool call is checked.
  - T0–T1 are allowed and T4 is always denied.
  - T3 needs, in order: not frozen, emergency stop off, a verified payee, an amount within the per-payment cap, a valid `approval` whose `plan_hash` matches the current plan, method `pin`, role `parent`, and a tier equal to the plan's highest tier.
  - Three denied money actions in a row freeze the agent until a parent resets it with the PIN.
  - Settings change only with the PIN; the PIN is stored as PBKDF2-SHA256 with a random salt.
- **Audit log** (`app/audit.py`): each entry stores the SHA-256 of the one before it.
  - `python -m app.audit verify FILE` names the first entry that was edited, removed or moved.
- **Agent** (`agent/agent.py`):
  - Asks a question for every missing fact instead of guessing.
  - Escalates to a human for an unverified payee, being over the LRS cap, being over the per-payment cap, or a corridor mismatch.
  - Changing the route or the plan voids the approval.
  - The receipt records masked inputs, rules used and their versions, the approval, the plan hash, the transaction and its audit-entry hash.
- **UI** (`app/static/`): plain HTML, CSS and JavaScript with three screens, an explain panel, a parent/student switch, consent, delete-my-data and a settings drawer.
  - Every value is HTML-escaped.
  - The server sends a strict Content-Security-Policy and listens on 127.0.0.1 only.

### 6.1 Finance audit (17 Oct)

`tests/test_finance_audit.py` checks the engine against an independent formula and against itself over 400 random cases:
- TCS equals the tax on the part crossing or above the threshold;
- paying *a* then *b* taxes exactly the same base as paying *a + b*;
- totals are exactly the sum of their parts;
- routes are sorted and savings are differences;
- every day of two years falls in the right financial year.

The engine passed all of these. The audit found three problems in the **agent**, now fixed with regression tests:
1. **Earlier payment ignored.** A payment made in TuitionPilot was not counted toward the next invoice's yearly total, which under-stated TCS by up to 2% of Rs 10 lakh. A year-to-date tracker now feeds both TCS and LRS.
2. **Inconsistent answers accepted.** Earlier remittances in rupees with no or inconsistent dollars were accepted. The agent now asks again.
3. **Silent rate.** No PAN with a loan-funded payment applied 0% silently. The rule pack has no rule for this, so it is now flagged as a warning.

Two finance questions remain open and need a source before any change:
- GST on the **currency conversion** itself (separate from GST on the bank's fee) is not modelled.
- The ranking includes TCS, which the family can later claim against their income tax.

## 7. Limits and open items
- Several tax rules are still secondary-source or unverified (see the rule pack and the self-assessment).
- The model adapter is an offline deterministic stand-in; a hosted model is not wired in yet.
- One shared policy (cap, emergency stop, breaker) for the whole server, which suits a one-family demo.
- The scanner is pattern-based. It is a first line of defence; the policy engine must also refuse on its own.
