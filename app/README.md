# App
| File | What |
|---|---|
| `server.py` | JSON API + static UI. `python -m app.server`, then open http://127.0.0.1:8000 |
| `static/` | The single-page UI: intake chat, comparison, approval and receipt, explain panel, settings |
| `sandbox.py` | Sandbox bank: quotes from three synthetic providers, family account, ledger, idempotent payments |
| `policy.py` | Policy engine: tiers T0-T4, PIN, per-payment cap, emergency stop, circuit breaker |
| `audit.py` | Hash-chained audit log; `python -m app.audit verify PATH` |
| `lab.py` | Attack lab: runs one attack scenario against a fresh agent and names the defence that stopped it |
| `demo_run.py` | Scripted run that writes the evidence logs to `data/evidence/demo/` |
| `demo_config.json` | Demo PIN, cap, breaker threshold, host and port (synthetic, sandbox only) |
