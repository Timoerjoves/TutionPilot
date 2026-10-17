# Demo video script (target 4 minutes, hard limit 5)

Written by Chandan; recorded by Nishanth (Plan v2 item 36). All data on screen is synthetic.
Numbers below come from the engine with rule pack `2026.10.16-r1`; re-check them against the screen before recording.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00-0:20 | Title: TuitionPilot | "Every year, Indian families send lakhs of rupees abroad for tuition. They have to work out the yearly LRS limit, the TCS tax, and which bank is really cheapest. One mistake costs money. TuitionPilot is an AI agent that does this safely." |
| 0:20-0:45 | Intake chat; upload the synthetic Northbridge University invoice for USD 20,000 | "A parent uploads the fee invoice. Before any AI sees it, PAN, passport and account numbers are replaced with tokens. Here is the log of exactly what the model saw." Show `model_saw.log` with `<PAN_1>`. |
| 0:45-1:15 | Payee check and plan | "There is no list of 'good' universities. The university digitally signed this invoice, and a trust root certified its bank account. Watch each link turn green. Then the agent asks only what it needs, one question at a time." |
| 1:15-2:00 | Best route: cost chart and what-if | "Three routes. The chart shows what each costs on top of the real exchange value. Provider B wins at Rs 18,23,080; Provider A, with the lowest fee, is Rs 4,620 dearer at Rs 18,27,700. TCS here is 2% on the amount above the Rs 10 lakh threshold. Now the what-if slider: if Rs 12 lakh had already gone abroad this year and there were no PAN, TCS jumps to Rs 90,200. Every number has a rule trace with its source, and rules we have not yet verified say so." |
| 2:00-2:20 | Hidden-markup line | "Compared to the mid-market rate, Provider A's rate hides Rs 10,000 of cost that never appears as a fee." |
| 2:20-2:45 | A2 draft and checklist | "The agent drafts an A2-style form and lists the missing documents: here, the I-20. If the invoice had no due date, it would ask, not guess." |
| 2:45-3:15 | Sign with PIN pad, sandbox payment, receipt | "The parent enters the PIN and this browser's own key signs the exact plan. The device recomputes the plan hash itself first. The bank re-checks the university's certificate, pays once, and writes a receipt with both signatures and the audit entry." |
| 3:15-3:45 | Attack demo: tampered invoice and injected text | "Now an attacker. This invoice says the university's bank account has changed, and hides an instruction telling the AI to approve. Changing the account breaks the university's signature, so the payment is blocked, and the injection is flagged. If the model ever states a wrong tax figure, the grounding check replaces it with the engine's number." |
| 3:45-4:00 | Signing, attack lab, scenario report | "The parent's browser holds its own signing key. It signs the exact plan, so not even the agent can change it afterwards. In the attack lab, all sixteen attacks are stopped, and twenty-seven scripted scenarios pass with one command. Synthetic data only, no real money, and not tax advice." |

Check before recording:
- Provider B: 20,000 x 90.20 = Rs 18,04,000; TCS 2% of 8,04,000 = Rs 16,080; fee Rs 3,000; total Rs 18,23,080.
- Provider A: 18,10,000 + TCS 16,200 + fee 1,500 = Rs 18,27,700, so Rs 4,620 more than B.
- What-if: no PAN (5%) and Rs 12 lakh sent earlier, so all Rs 18,04,000 is taxed: TCS Rs 90,200.
