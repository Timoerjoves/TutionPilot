# TuitionPilot: technical documentation

Draft v0.1, 16 Oct 2026. Official deliverable: system architecture, core algorithm, security design.
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
 [1 Intake] -> [2 Mask] -> [3 Extract (model)] -> [4 Validate + payee registry]
                                                         |
                       [5 Rules: LRS, TCS, landed cost] <-+
                                     |
                       [6 Compare routes + explain] -> [Form A2 draft + checklist]
                                     |
                       [7 Plan (multi-step, asks when data is missing)]
                                     |
                       [8 Policy gate: tier, caps, emergency stop]
                                     |
                       [9 Approve: parent PIN, bound to plan hash]
                                     |
                       [10 Execute in sandbox bank] -> [11 Receipt + audit log] -> [12 Timeline]
```

| Stage | Module | Owner | Status |
|---|---|---|---|
| 2 Mask | `security/masking.py` | Chandan | Built |
| 4 Payee check | `security/guard.py: payee_mismatch()` (registry itself: Nishanth) | Both | Check built; registry planned |
| 5 Rules | `rules/engine.py`, `rulepack/india_lrs_tcs.json` | Chandan | Built |
| 6 Compare + explain | `rules/engine.py: compare_routes()`, `rules/explain.py` | Chandan | Built |
| Form | `forms/a2.py`, `corridors/*.json` | Chandan | Built |
| Untrusted-text scan | `security/guard.py: scan()` | Chandan | Built |
| Grounding check | `security/grounding.py` | Chandan | Built |
| Messages between parts | `contract/__init__.py`, `docs/CONTRACT.md` | Both | Built |
| 1, 3, 7-12 | `agent/`, `app/` | Nishanth | Planned |

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
- **Blocked:** the payee details do not match the registry, or the currency does not match the corridor.

The missing-documents checklist is taken from the corridor. For example, the visa document is the I-20 for the USA and the CAS for the UK, and the loan letter is only asked for when the payment is loan-funded.

### 3.6 Corridors as config
`corridors/in_us.json` and `corridors/in_gb.json` hold destination facts only: currency, purpose code and the student-visa document.

Switching from India→USA to India→UK is a file swap. The India rule pack is the same for both. New facts in the corridor files are marked `unverified`.

## 4. Security design

The full self-assessment and known-risk list are in [SECURITY_SELF_ASSESSMENT.md](SECURITY_SELF_ASSESSMENT.md).

### 4.1 Permission tiers
| Tier | Allowed | Approval |
|---|---|---|
| T0 | Read (invoice, registry, history) | None |
| T1 | Compute and draft | None |
| T2 | Save or share drafts | Click |
| T3 | Sandbox payment to a verified payee | PIN, bound to plan hash |
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

**`payee_mismatch()`** compares the invoice payee and bank details with the verified registry. A changed account or SWIFT code blocks the draft.

### 4.5 Plan-bound approval
`contract.plan_hash()` is the SHA-256 of the plan as sorted, compact JSON. An approval names the hash of the exact plan it approved. Any edit changes the hash, which voids the approval.

## 5. Testing and evidence

```
python -m unittest discover -s tests -t . -v     # unit, contract, attack and scenario tests
python -m scenarios.runner                        # 25 scenarios -> data/evidence/scenario_results.md
```

| Test file | Covers |
|---|---|
| `test_rules.py` | TCS cases A1-A6, LRS cap A7, routes A8, year-to-date, dates, rounding |
| `test_explain.py` | Explanation lines add up to the engine's totals; Indian number format |
| `test_contract.py` | Samples valid, plan hash, validation |
| `test_security.py` | Masking, model log, scanner, grounding |
| `test_attacks.py` | 8 attack cases (injection, induced transfer, data extraction, privilege escalation) |
| `test_forms.py` | Corridors, A2 draft, checklist, A9/A10 |
| `test_scenarios.py` | Runner: 25 scenarios, no failures, pending never counted as pass |

## 6. Limits and open items
- Several tax rules are still secondary-source or unverified (see the rule pack and the self-assessment).
- The agent, sandbox bank, policy engine, audit log and screens are Nishanth's and still planned. Their scenarios show as PENDING.
- The scanner is pattern-based. It is a first line of defence; the policy engine must also refuse on its own.
