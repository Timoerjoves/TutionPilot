# App
| File | What |
|---|---|
| `server.py` | JSON API + static UI. `python -m app.server`, then open http://127.0.0.1:8000. Sessions are bound to an HttpOnly, SameSite=Strict cookie and expire after `session_idle_minutes` idle |
| `static/` | Landing page, sign-in, and the app: 8 guided steps with a step bar, Assistant (`/assistant`), Student money (`/money`), Vault, Attack lab, the Agent live panel and Settings |
| `family.py` | Device enrolment, passwordless sign-in challenges and the encrypted vault store |
| `sandbox.py` | Sandbox bank: quotes from three synthetic providers with settlement times, family account, ledger, idempotent payments, payment records signed with the bank's (synthetic) key |
| `policy.py` | Policy engine: tiers T0-T4, PIN, per-payment cap, emergency stop, circuit breaker |
| `audit.py` | Hash-chained audit log; `python -m app.audit verify PATH` |
| `lab.py` | Attack lab: runs one attack scenario against a fresh agent and names the defence that stopped it |
| `demo_run.py` | Scripted run that writes the evidence logs to `data/evidence/demo/` |
| `demo_config.json` | Demo PIN, cap, breaker threshold, session idle minutes, host and port (synthetic, sandbox only) |
