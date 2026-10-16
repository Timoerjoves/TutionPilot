# Demo video script (target 4 minutes, hard limit 5)

Written by Chandan; recorded by Nishanth (Plan v2 item 36). All data on screen is synthetic.
Numbers below come from the engine with rule pack `2026.10.16-r1`; re-check them against the screen before recording.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00-0:20 | Title: TuitionPilot | "Every year, Indian families send lakhs of rupees abroad for tuition. They have to work out the yearly LRS limit, the TCS tax, and which bank is really cheapest. One mistake costs money. TuitionPilot is an AI agent that does this safely." |
| 0:20-0:45 | Intake chat; upload the synthetic Northbridge University invoice for USD 20,000 | "A parent uploads the fee invoice. Before any AI sees it, PAN, passport and account numbers are replaced with tokens. Here is the log of exactly what the model saw." Show `model_saw.log` with `<PAN_1>`. |
| 0:45-1:15 | Payee check and plan | "The agent checks the university against a verified registry, then shows its plan step by step. Each step has a permission tier. Paying is tier 3: it needs the parent's PIN." |
| 1:15-2:00 | Comparison screen | "Two routes. Provider A has the lower fee, but Provider B wins: Rs 18,23,080 against Rs 18,27,700, Rs 4,620 cheaper. The explanation shows why: a better exchange rate saves Rs 6,000, Provider A's fee is Rs 1,500 lower, and TCS is Rs 120 less. TCS here is 2% on the amount above the Rs 10 lakh threshold. Every number has a rule trace with its source, and rules we have not yet verified say so." |
| 2:00-2:20 | Hidden-markup line | "Compared to the mid-market rate, Provider A's rate hides Rs 10,000 of cost that never appears as a fee." |
| 2:20-2:45 | A2 draft and checklist | "The agent drafts an A2-style form and lists the missing documents: here, the I-20. If the invoice had no due date, it would ask, not guess." |
| 2:45-3:15 | Approval with PIN, sandbox payment, receipt | "The parent approves the exact plan with a PIN. The approval is tied to a hash of that plan. The payment runs in a simulated bank only, and a receipt and audit log entry are written." |
| 3:15-3:45 | Attack demo: tampered invoice and injected text | "Now an attacker. This invoice says the university's bank account has changed, and hides an instruction telling the AI to approve. The account does not match the registry, so the payment is blocked, and the injection is flagged. If the model ever states a wrong tax figure, the grounding check replaces it with the engine's number." |
| 3:45-4:00 | Scenario report: 25 scenarios | "Twenty-five scripted scenarios run with one command, and the results are part of our evidence. Synthetic data only, no real money, and not tax advice." |

Check before recording:
- Rs 6,000 rate saving = (90.50 - 90.20) x 20,000 (shown under "why" in `explain_comparison`).
- Rs 120 TCS difference = 2% of Rs 6,000 more remitted via Provider A.
- 6,000 - 1,500 + 120 = 4,620 saving.
