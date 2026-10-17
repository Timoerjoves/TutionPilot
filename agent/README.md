# Agent
`agent.py` runs the 12-stage pipeline for one family: consent, intake, masking, extraction, payee check,
questions instead of guesses, rules, route comparison, A2 draft, plan, escalation, PIN approval, sandbox payment,
receipt and timeline. Every tool call goes through `app/policy.py` and is written to `app/audit.py`.

`model.py` is the model adapter: the only two jobs a language model does (read the invoice, word explanations).
`OfflineModel` does them deterministically, so the demo needs no API key. A hosted model can replace it behind the
same two methods; it still sees masked text only, and its numbers still pass the grounding check.
