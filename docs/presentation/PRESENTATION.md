# Presentation (10 slides, about 10 minutes)

- **For the judges:** [TuitionPilot_deck.pptx](TuitionPilot_deck.pptx) (PowerPoint, with speaker notes on every slide) and [TuitionPilot_deck.pdf](TuitionPilot_deck.pdf) (same deck as PDF). Built 18 Oct 2026; fonts are Cambria and Calibri, which ship with Office.
- **Architecture diagram used on slide 4:** [../architecture.svg](../architecture.svg) / [../architecture.png](../architecture.png).
- **Web version (9 slides, 18 Oct):** the live deck at https://claude.ai/artifact/E9FusU8285LxbRy6PXmtm6 (private, Chandan's account), its PDF export [TuitionPilot_web_deck.pdf](TuitionPilot_web_deck.pdf), and its slide sources with speaker notes in `slides/`. Its slide 7 ("Built for families: sign-in, vault, next action") covers what this deck spreads over slides 3 and 8.

| # | Slide | Time | Key message |
|---|---|---|---|
| 1 | **TuitionPilot** (cover) | 0:45 | An AI agent that checks the invoice is genuine, explains every rupee, and pays only after the parent's own device signs the exact plan. |
| 2 | **Four hard questions, one big fraud risk** | 1:00 | LRS limit, TCS, real cost, papers; the "bank details have changed" scam fails by design. |
| 3 | **One guided flow, from invoice to receipt** | 1:00 | Six steps; live agent panel; attack lab; family devices and vault. Code computes, the AI explains (offline stand-in today). |
| 4 | **Architecture** | 1:00 | Keys stay with people (orange), the AI step sees masked text (dashed), money moves only on the navy path inside the sandbox. |
| 5 | **India's LRS and TCS rules** | 1:15 | Rule table with status; A2 worked: Rs 15 lakh → TCS Rs 10,000 (loan: Rs 0). Unverified rules flagged. |
| 6 | **Route comparison** | 1:15 | Stacked chart of markup + fee + TCS; B is Rs 4,620 cheaper (rate +6,000, fee −1,500, TCS +120). |
| 7 | **Signatures instead of payee lists** | 1:15 | University chain (root → certificate → invoice → bank → printed text); parent device signing. |
| 8 | **Defence in depth** | 1:00 | Tiers T0–T4; masking, grounding, scanner, breaker + emergency stop, audit chain, encrypted vault. |
| 9 | **Evidence** | 1:00 | 227 tests, 27/27 scenarios, 16/16 attacks stopped, 153 audit entries verify; finance audit of 400 cases. |
| 10 | **Honest limits, and what comes next** | 1:00 | Unverified tax rules; offline AI stand-in; un-hardened Ed25519; synthetic keys; next steps. |

## Before presenting
- [ ] Rerun `python -m unittest discover -s tests -t .`, `python -m scenarios.runner` and `python -m app.demo_run`; update slide 9 if any number changed.
- [ ] Nishanth checks slides 3, 4, 7 and 8 against the app.
- [ ] If any tax rule gets verified, update slides 5 and 10 and the rule pack (with its source).
