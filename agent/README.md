# Agent
`agent.py` runs the 12-stage pipeline for one family: consent, intake, masking, extraction, payee check,
questions instead of guesses (including the source of funds), sanctions screening, rules, route comparison, the
payment plan (send-by date, financial-year timing, loan versus own money, split), A2 draft with RBI checks, plan,
escalation, PIN approval, sandbox payment, receipt, the family's payment record and timeline. Read-only extras:
`whatif`, `plan_ahead` (next fee), `budget` (student living costs) and `payment_record` (signed by the bank).
Every tool call goes through `app/policy.py` and is written to `app/audit.py`.

`model.py` is the model adapter: the only jobs a language model does (read the invoice, word explanations, and,
when hosted Claude is on, answer free-form questions from the engine's facts). `OfflineModel` does the first two
deterministically, so the demo needs no API key. `HostedModel` (opt-in, `TUITIONPILOT_MODEL=claude`) sees masked
text only; its values must appear in the invoice text and its numbers must pass the grounding check, or the
agent's own words are shown.
