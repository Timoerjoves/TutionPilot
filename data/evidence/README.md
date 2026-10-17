# Execution evidence

Official deliverable: "simulated-account / sandbox operation logs" plus results. Everything here is synthetic.

| File | What | Made by |
|---|---|---|
| `scenario_results.md` / `.json` | The 25 scripted scenarios with expected vs actual result | `python -m scenarios.runner` |
| `demo/demo_run.md` | Summary of a scripted run: payments, attacks, breaker | `python -m app.demo_run` |
| `demo/sandbox_ledger.log` | Every sandbox bank transfer (JSON lines) | sandbox bank |
| `demo/audit_log.jsonl` | Hash-chained audit log of every step and policy decision | audit log |
| `demo/model_saw.log` | Exactly what the model saw, after masking | `security.ModelSawLog` |

Check the audit chain yourself:

    python -m app.audit verify data/evidence/demo/audit_log.jsonl

Logs from interactive server runs go to `data/evidence/runs/` and are not committed.
