# Execution evidence

Official deliverable: "simulated-account / sandbox operation logs" plus results. Everything here is synthetic.

| File | What | Made by |
|---|---|---|
| `scenario_results.md` | The 25 scripted scenarios with expected vs actual result | `python -m scenarios.runner` |
| `scenario_results.json` | Same results, machine-readable | `python -m scenarios.runner` |
| `sandbox_ledger.log` | Sandbox bank operations (to come) | Nishanth's sandbox bank |
| `audit_log.jsonl` + verify output | Hash-chained audit log and its verify result (to come) | Nishanth's audit log |
| `model_saw.log` | What the model saw, after masking (to come from a demo run) | `security.ModelSawLog` |

To regenerate the scenario results from the repo root:

    python -m scenarios.runner

PENDING rows need parts not built yet and are never counted as passes. Rerun the runner after each
of those parts lands, then commit the new results.
