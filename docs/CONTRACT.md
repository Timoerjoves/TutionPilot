# Interface contract v1.0

The agreed shape of every message passed between the rules engine (Chandan) and the app/agent (Nishanth).
Code: `contract/__init__.py`. Examples: `data/samples/`. Tests: `tests/test_contract.py`.
Change a field only after both of you agree, then bump `CONTRACT_VERSION`.

## Rules for every message

| Rule | Why |
|---|---|
| Has `"type"` and `"contract_version": "1.0"` | So code knows what it got |
| Money is a decimal **string**: `"1500000.00"` | Floats lose paise |
| Dates `"2026-10-16"`; timestamps `"2026-10-16T17:00:00+05:30"` | One format everywhere |
| Synthetic data only; bank accounts are masked | Competition rule and privacy |
| Check with `contract.validate(msg)` before sending or using | Fail early with a clear message |

## The five messages

| Type | Who makes it | Who uses it | Key fields |
|---|---|---|---|
| `invoice` | App (invoice reader) | Agent, rules | `payee.registry_id`, `amount`, `due_on` |
| `quote` | Sandbox bank | Rules engine | `fx_rate`, `fee_inr`, `gst_rate`, `foreign_amount` |
| `rule_result` | Rules engine | Agent, explain panel | `kind`, `outputs`, `trace`, `needs_verification` |
| `plan` | Agent | Policy engine, user | `steps[].tier`, `max_tier`, `plan_hash` |
| `approval` | User (parent/student) | Policy engine, sandbox | `plan_hash`, `tier`, `decision`, `method` |

### invoice — see `data/samples/invoice.json`
`invoice_id`, `issued_on`, `due_on`, `payee {name, registry_id, country, bank {account_masked, swift}}`,
`student {name, student_id}`, `amount {value, currency}`, `purpose` = `"education"`.

### quote — see `data/samples/quote.json`
`quote_id`, `route_name`, `provider`, `foreign_amount {value, currency}`, `fx_rate` (INR per 1 unit),
`fee_inr`, `gst_rate` (e.g. `"0.18"`), `correspondent_inr`, `valid_until`.

### rule_result — see `data/samples/rule_result_*.json`
`kind` = `tcs` | `lrs_headroom` | `landed_cost`, `pack_id`, `pack_version`, `inputs {}`, `outputs {}`,
`trace [ {rule_id, pack_version, value, effective_from, status, source} ]`, `needs_verification [rule_id]`.
Built by `contract.tcs_result()`, `lrs_result()`, `landed_cost_result()` from engine output.
**The model may explain these numbers but must never change them.** Anything in `needs_verification` must be shown as "unverified" in the UI.

### plan — see `data/samples/plan.json`
`plan_id`, `created_at`, `goal`, `steps [ {n, action, tool, tier, inputs} ]`, `max_tier`, `plan_hash`.
- `max_tier` must equal the highest step tier.
- `plan_hash` = `contract.plan_hash(plan)`: SHA-256 of the plan (without `plan_hash`) as sorted, compact JSON.

### approval — see `data/samples/approval.json`
`approval_id`, `plan_id`, `plan_hash`, `tier`, `approver {role}` (`parent` | `student`),
`decision` (`approved` | `rejected`), `method` (`pin` | `click`), `decided_at`.
- The sandbox pays only if `approval.plan_hash == plan_hash(current plan)`. Edit the plan → approval is void.
- T3 (payment) needs `method: "pin"`. T4 is never approvable.

## Permission tiers

| Tier | Allowed | Approval |
|---|---|---|
| T0 | Read (invoice, registry, history) | None |
| T1 | Compute and draft | None |
| T2 | Save or share drafts | Click |
| T3 | Sandbox payment to a verified payee | PIN, bound to plan hash |
| T4 | New/unverified payee, raise or change limits, skip approval | Never |
