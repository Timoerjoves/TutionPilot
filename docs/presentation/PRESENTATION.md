# Presentation (11 slides, about 9 minutes; the official limit is 10 minutes)

- **For the judges:** [TuitionPilot_deck.pptx](TuitionPilot_deck.pptx) (PowerPoint, with speaker notes on every slide) and [TuitionPilot_deck.pdf](TuitionPilot_deck.pdf) (same deck as PDF). Built 18 Oct 2026 (evidence numbers updated 19 Oct); fonts are Cambria and Calibri, which ship with Office.
- **Architecture diagram used on slide 5:** [../architecture.svg](../architecture.svg) / [../architecture.png](../architecture.png).

| # | Slide | Time | Key message |
|---|---|---|---|
| 1 | **TuitionPilot** (cover) | 0:40 | An AI agent that checks the invoice is genuine, explains every rupee, and pays only after the parent's own device signs the exact plan. |
| 2 | **Four hard questions, one big fraud risk** | 0:50 | LRS limit, TCS, real cost, papers; the "bank details have changed" scam fails by design. |
| 3 | **Eight guided steps, from invoice to receipt** | 0:50 | Eight steps; live agent panel with the next action; code computes, the AI explains (offline by default, hosted Claude optional). |
| 4 | **Student prepares, parent signs: the real app** | 0:45 | Four app screenshots; the student does the work, only a parent device signs; the student's session is retired on handoff. |
| 5 | **Architecture** | 0:50 | Keys stay with people (orange), the AI step sees masked text (dashed), money moves only on the navy path inside the sandbox. |
| 6 | **India's LRS and TCS rules** | 0:55 | Six rules verified against RBI and the Income-tax Act 2025; A2 worked: Rs 15 lakh, TCS Rs 10,000 (loan: Rs 0). |
| 7 | **Route comparison** | 0:55 | B is Rs 4,620 cheaper (rate +6,000, fee -1,500, TCS +120). |
| 8 | **Signatures instead of payee lists** | 0:55 | University chain; parent device signing; new devices need the PIN and a parent device's approval. |
| 9 | **Defence in depth** | 0:50 | Tiers T0-T4 (T4 includes sanctioned parties); masking, grounding, scanner, breaker + emergency stop, audit chain, encrypted vault; cookie-bound sessions. |
| 10 | **Evidence** | 0:45 | 271 tests, 27/27 scenarios, 16/16 attacks stopped, 180 audit entries verify; finance audit of 400 cases. |
| 11 | **Honest limits, and what comes next** | 0:45 | Open rules flagged (incl. the new screening, source-of-funds and living-cost rules); offline AI by default; un-hardened Ed25519; synthetic keys and sanctions list. |

## Before presenting
- [ ] Rehearse with a timer: Appendix 2 caps the final presentation at 10 minutes, so aim for 9:30. Speaker notes are written for about 9 minutes.
- [ ] Rerun `python -m unittest discover -s tests -t .`, `python -m scenarios.runner` and `python -m app.demo_run`; update slide 10 if any number changed.
- [ ] Nishanth checks slides 3, 4, 7 and 8 against the app.
- [ ] If any tax rule gets verified, update slides 5 and 10 and the rule pack (with its source).
