# Interface contract v1.1

**What changed from 1.0 (17 Oct 2026):** two optional signature fields.
- `invoice.attestation`: the university's signature and its certificate.
- `approval.signature`: the parent's device signature.

Signed messages carry `"contract_version": "1.1"`. `validate()` still accepts 1.0 messages, so nothing that worked before breaks. The policy engine now *requires* a parent signature for T3 payments. See "Signatures" below.

The agreed shape of every message passed between the rules engine (Chandan) and the app/agent (Nishanth).
Code: `contract/__init__.py`. Examples: `data/samples/`. Tests: `tests/test_contract.py`.
Change a field only after both of you agree, then bump `CONTRACT_VERSION`.

## Rules for every message

| Rule | Why |
|---|---|
| Has `"type"` and `"contract_version": "1.1"` (1.0 still accepted) | So code knows what it got |
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
Optional (1.1): `attestation {alg: "Ed25519", certificate {certificate, signature}, signature}`. This is the university's signature over the invoice, plus the root-signed certificate of its key and bank details.

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
Optional (1.1): `signature {alg: "Ed25519", key_id, value}`, made on the parent's device.
- The sandbox pays only if `approval.plan_hash == plan_hash(current plan)`. Edit the plan → approval is void.
- T3 (payment) needs `method: "pin"` **and** a valid `signature` from a parent key registered with the PIN. T4 is never approvable.

## Signatures (1.1)

**The rule.** A signature always covers the message **without its own signature field**, as `contract.canonical_json()`: sorted keys, no spaces, UTF-8. `contract.signed_bytes(msg)` returns exactly those bytes. The algorithm is Ed25519 (RFC 8032), and keys and signatures are base64.

**Parts:**

| Part | Who holds the private key | Where |
|---|---|---|
| Trust root | The (synthetic) payee trust: certifies universities and their bank accounts | Public key in `data/trust/root.json` |
| Payee certificate | Signed by the root: `{type: "payee_certificate", serial, issuer, subject {payee_id, name, country, currency, bank}, public_key, key_id, valid_from, valid_to}` | `invoice.attestation.certificate` |
| Revocation list | Signed by the root | `data/trust/revoked.json` |
| Invoice signature | The university | `invoice.attestation.signature` |
| Approval signature | The parent's device (browser WebCrypto key, never sent anywhere) | `approval.signature` |

**An invoice is verified only when all of these hold:**
- the certificate is signed by the root, in date, and not revoked;
- the invoice signature verifies with the certificate's key;
- the payee and bank details on the invoice equal the certificate's subject.

The agent then pays the **signed** data, never the printed text.

**Text format.** Signed invoices travel as text with the signed invoice embedded between `-----BEGIN TUITIONPILOT SIGNED INVOICE-----` and `-----END TUITIONPILOT SIGNED INVOICE-----` (base64 JSON). See `security/pki.py: embed(), split()`.

## Permission tiers

| Tier | Allowed | Approval |
|---|---|---|
| T0 | Read (invoice, registry, history) | None |
| T1 | Compute and draft | None |
| T2 | Save or share drafts | Click |
| T3 | Sandbox payment to a verified (certificate-signed) payee | PIN + parent device signature, bound to plan hash |
| T4 | New/unverified payee, raise or change limits, skip approval | Never |
