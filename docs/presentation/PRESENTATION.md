# Presentation (8 slides, about 9 minutes)

- **Live deck (private, Chandan's account):** https://claude.ai/artifact/E9FusU8285LxbRy6PXmtm6
- **Export:** open the deck → Share › Export to get PowerPoint (.pptx) or PDF, then add the file to this folder.
- **Slide sources:** `slides/` holds each slide as it was on 17 Oct (`slides/deck.json` is the order).
- **To review:** Nishanth reviews slides 2 and 6. Rerun the numbers on slide 7 just before submitting.

| # | Slide | Time | Key message |
|---|---|---|---|
| 1 | **TuitionPilot** (cover) | 1:00 | Families work out four things alone (LRS limit, TCS, real cost, papers); one mistake costs money. TuitionPilot does it, explains every number, and pays only after the parent's device signs. |
| 2 | **Product: a guided six-step story** | 1:15 | Welcome → Invoice (signature chain) → Questions → Best route (chart, what-if, LRS gauge) → Review & sign → Receipt; live agent panel; attack lab. Code computes, the model explains; the model is an offline stand-in today. |
| 3 | **LRS and TCS: the rules the engine uses** | 1:15 | A rule table with value, date, source and status. TCS = rate × (this year's total − the larger of earlier payments or Rs 10 lakh). Four rules are still unverified and are flagged. |
| 4 | **Worked examples, step by step** | 1:15 | A2: Rs 15 lakh self-funded → TCS Rs 10,000 (loan: Rs 0). A8: USD 20,000 at 90.20 → Rs 18,04,000 + TCS 16,080 + fee 3,000 = Rs 18,23,080. Also A1, A4, A5, A6. |
| 5 | **Route comparison: why Provider B wins** | 1:15 | A has the lower fee, but B is Rs 4,620 cheaper (rate +6,000, fee −1,500, TCS +120). Hidden markup at A: Rs 10,000 (0.56%). |
| 6 | **Security: signatures instead of lists** | 1:15 | University: trust root → certificate (bank account) → invoice signature → bank match → printed text. Parent: device key → register with PIN → recompute hash → sign → policy verifies. Tiers T0–T4. |
| 7 | **Evidence: 27 scenarios, one command** | 1:00 | 27/27 scenarios, 156 tests, 16/16 attacks stopped, 108 audit entries verify. The finance audit (400 cases) found 3 agent bugs, all fixed. |
| 8 | **Limits, stated plainly** | 1:00 | Unverified tax rules; GST on conversion not modelled; offline AI stand-in; un-hardened Ed25519; synthetic keys; names not masked; fixed demo PIN; audit log is tamper-evident, not tamper-proof. |

Full speaker notes are inside each slide file (`<aside>` at the end of each `slides/*.html`) and in the live deck.

## Before presenting
- [ ] Rerun `python -m unittest discover -s tests -t .`, `python -m scenarios.runner` and `python -m app.demo_run`, and update slide 7 if any number changed.
- [ ] Nishanth checks slides 2 and 6 against the app.
- [ ] If any tax rule gets verified, update slides 3 and 8 and the rule pack (with its source).
- [ ] Export PPTX/PDF into this folder for the submission.
