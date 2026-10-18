# SPEC: Route comparison, line-by-line explanation, hidden markup, masking

Status: built 17 Oct 2026 (tests: tests/test_route_lines.py, test_markup.py, test_masking.py; all acceptance boxes below covered). Owner: Chandan. Team plan items 3, 16, 25.

## 1. Objective
A parent paying tuition abroad sees every route ranked by what actually leaves their account, and why, rupee by rupee.
Each figure shows where it came from (a rule in the pack or a bank quote), and unverified rules are flagged.
The AI only words the explanation, and it never sees a name, account number or PAN.

Most of this already exists and is tested:

| Part | Where | State |
|---|---|---|
| Rank routes by landed cost | `rules/engine.py: landed_cost, compare_routes` | Done |
| Line-by-line breakdown, "why the cheapest wins" | `rules/explain.py: explain_landed_cost, explain_comparison` | Done, but quote-derived lines have no trace |
| Hidden-markup explainer | `rules/explain.py: explain_markup` | Done, but doesn't name its mid-market source |
| Masking + what-the-model-saw log | `security/masking.py` | Done for PAN, Aadhaar, email, phone, account, passport. **Names are not masked** (the model sees `Student: Asha Student` in `data/evidence/demo/model_saw.log`) |

This spec covers the three gaps only. Nothing is rebuilt.

## 2. Modules (build in this order)

| Id | Module | Depends on | Files |
|---|---|---|---|
| M1 | Name masking | none | `security/masking.py`, `tests/test_security.py` |
| M2 | A source on every line | engine | `rules/explain.py`, `tests/test_explain.py` |
| M3 | `compare_quotes()`: invoice + 2-4 quote messages | M2, `contract.validate` | `rules/explain.py`, `data/samples/quote_{a,b,c}.json`, `tests/test_explain.py` |

### M1: Name masking
- New token kind `NAME` (`<NAME_1>`), added to `TOKEN`.
- **Labelled lines:** the value after a person label is masked: `Student`, `Student name`, `Name`, `Parent`, `Father`, `Mother`, `Guardian`, `Remitter`, `Sender`.
  The label match ignores case and allows a `:` or `-`. The value ends at the line end or at ` (`, so `Asha Student (synthetic)` becomes `<NAME_1> (synthetic)`.
- **Known names:** once a name has been masked, the same name is masked everywhere else in later text from that Masker (whole word, any case).
  New method `Masker.remember_name(value)` for names the family types, such as the remitter name. Wiring it into the agent is a one-line change in Nishanth's area (see §6).
- Not masked: university/payee names (public, and needed to extract the payee), student IDs, invoice numbers, SWIFT codes.
- **Leak check:** `find_identifiers()` also reports a person label followed by anything other than a token, so `ModelSawLog.record()` refuses it (`LeakError`) and the error names only the kind.

Acceptance:
- [x] Masking the demo invoice text turns `Student: Asha Student (synthetic)` into `Student: <NAME_1> (synthetic)`; `Payee: Northbridge University (synthetic)` is unchanged.
- [x] "Asha Student" later in free text in the same session becomes `<NAME_1>`; `unmask()` gives it back.
- [x] `ModelSawLog.record("x", "Student: Asha Student")` raises `LeakError`, and the message does not contain "Asha".
- [x] After `python -m app.demo_run`, no student or remitter name appears in `data/evidence/demo/model_saw.log`.
- [x] Existing masking tests still pass: no other kind is affected.

### M2: A source on every line
Every line from `explain_landed_cost`, `explain_markup` and `explain_comparison` gains a `source` string. This is additive: existing keys (`label, amount_inr, text, rules, unverified`) are unchanged.

| Line | `rules` | `source` |
|---|---|---|
| Amount sent, Provider fee, Correspondent charges | none | `quote <quote_id> from <provider>, valid until <valid_until>`, or `<route name>'s quote` if no quote message was given |
| GST on fee | `gst_on_service_charge` | the quote (as above) plus the rule's pack source |
| TCS | TCS rule ids | `rule pack <version>: <source of each rule>` |
| Hidden markup | none | `mid-market reference rate <rate> INR per <cur> (<mid_source>)`, default `mid_source` = `synthetic sandbox reference` |
| Total | rule ids of the parts | `sum of the lines above` |

- Rules marked `unverified` keep appearing in `unverified` (unchanged behaviour); the UI already badges them.
- `explain_landed_cost(..., quote=None)` and `explain_markup(..., mid_source=...)` take optional arguments, so the agent's current calls keep working.

Acceptance:
- [x] Every line in every output has a non-empty `source`.
- [x] The TCS line's `source` names pack version `PACK.version`; any unverified TCS rule is in `unverified`.
- [x] Line amounts (excluding Total) add up to Total for every route (the property test exists in `test_finance_audit.py`; extend it to the lines).

### M3: `compare_quotes(pack, invoice, quotes, mid_market_rate=None, mid_source=..., **kw)`
In `rules/explain.py`. `kw` is passed to `compare_routes` (funding, prior_lrs_inr, has_pan, on, ...).
- Validates the invoice and each quote with `contract.validate()`.
- Refuses (`ValueError` with a plain message) when: fewer than 2 or more than 4 quotes; a quote's `foreign_amount` currency or value differs from the invoice amount; two quotes have the same `route_name`.
- Builds `Route`s from the quotes (same mapping as `SandboxBank.route_of`), then calls `compare_routes` and `explain_comparison`.
- Returns `{"summary", "why", "routes": [{rank, route, quote_id, total_inr, saving_vs_next_inr, lines, markup, trace, needs_verification}]}`. All money is a decimal string.
- Adds samples `data/samples/quote_a.json`, `quote_b.json` and `quote_c.json` for the sample invoice (USD 20,000), with different rate/fee mixes so that the route with the lowest fee is *not* the cheapest overall. All synthetic and valid under the contract.
- The agent is unchanged. Nishanth can switch `agent._compute` to it later.

Acceptance:
- [x] Sample invoice + three sample quotes → three routes ranked by `total_inr`, cheapest first; `saving_vs_next_inr` is correct.
- [x] 1 quote, 5 quotes, a currency mismatch, an amount mismatch and a duplicate route name are each refused with a clear message.
- [x] An invalid quote message (e.g. float money) is refused by `validate()`.
- [x] Each route's `markup` equals `(fx_rate − mid) × amount`, and says "no hidden markup" when the rate is at or below mid-market.
- [x] Results match the agent's inline path for the same inputs (same totals and ranking).

## 3. Commands
    python -m unittest discover -s tests -t . -v     # after every change
    python -m scenarios.runner                        # scenarios still pass
    python -m app.demo_run                            # regenerate evidence; check model_saw.log for names

## 4. Code style
- Standard library only. `Decimal` for money, rounded with `money()`; strings at the boundary.
- Code writes every sentence and number; the model only relays them (the grounding check stays in front).
- Match the existing modules: small functions, short docstrings, comments only for the why.

## 5. Testing
- New tests go in `tests/test_security.py` (M1) and `tests/test_explain.py` (M2, M3); the property check goes in `tests/test_finance_audit.py`.
- Each acceptance box above is one test.
- Regression: the full suite (227 tests now) stays green, and the scenario runner and demo run succeed.

## 6. Boundaries
- **Always:** synthetic data; a rule trace or source on every number; flag unverified rules; run the tests after each module.
- **Ask first:** any change to `contract/` or `docs/CONTRACT.md` (none planned: M2 and M3 only add fields to explain output, which is not a contract message); any rate or rule in `rulepack/` (none planned).
- **Hand to Nishanth (agent/, app/):** call `masker.remember_name()` when the family answers the remitter-name question; optionally switch `agent._compute` to `compare_quotes()`; optionally show `source` in the UI line tooltip.
- **Never:** let the model produce or change a number; send unmasked text to the model; real names, PANs or bank details in samples.

## Out of scope
Live FX feeds, real provider quotes, multi-currency splits, NLP name detection beyond labels and remembered names.
