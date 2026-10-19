# Demo video script (target 4:50, hard limit 5:00)

Written by Chandan; recorded by Nishanth (Plan v2 item 36). All data on screen is synthetic.
Numbers below come from the engine with rule pack `2026.10.19-r2`; re-check them against the screen before recording.

**Before recording:** start a fresh server (`python -m app.server`), so no devices are enrolled. Use one browser profile for the parent and another for the student, or one browser holding both keys (risk R26, demo only). The demo PIN is in `app/demo_config.json`. Record at 1280x800 or larger so the agent panel stays on the right.

| Time | Screen | Voice-over |
|---|---|---|
| 0:00-0:20 | Landing page, scroll slowly through the eight-step story | "Every year, Indian families send lakhs of rupees abroad for tuition. They must work out the yearly LRS limit, the TCS tax, and which bank is really cheapest. One mistake costs money, and a fake 'new bank details' email can steal the fees. TuitionPilot is an AI agent that does this safely." |
| 0:20-0:40 | Sign-in: the parent sets up the first device; then the student's device asks to join and the parent approves it in Settings | "There are no passwords. Each device makes its own key, which never leaves the browser. The first parent device enrols with the PIN; every later device also needs a signature from a parent device that is already signed in." |
| 0:40-1:00 | Student: step 1 Consent, step 2 Upload invoice (drop the Northbridge PDF, USD 20,000) | "The student does the work. Two consents, then the invoice. Before any AI reads it, PAN, passport and account numbers become tokens; the AI saw tab shows exactly what it saw." |
| 1:00-1:20 | Step 3 Verify signature | "There is no list of 'good' universities. A trust root certified this university and its bank account, and the university signed the invoice. Each link turns green; change one digit of the account and the signature breaks." |
| 1:20-1:40 | Step 4 Questions | "The agent asks only what the invoice can't tell it, one question at a time, including where the money comes from. PAN is mandatory for LRS, so with no PAN the agent stops. The sender, the student and the university are screened against a sanctions list." |
| 1:40-2:25 | Step 5 Compare routes: the cost chart, then the what-if panel | "Three routes, each measured against the real exchange rate. Provider B wins at Rs 18,23,080; Provider A, with the lowest fee, costs Rs 4,620 more at Rs 18,27,700, because its rate hides Rs 10,000 that never appears as a fee. TCS is 2% on the amount above the Rs 10 lakh threshold. The payment plan adapts to the dates: send by 10 November for Provider B to arrive in time; an education loan would make TCS zero; and next semester's fee, in the same financial year, would carry Rs 36,080 of TCS. Every number has a rule trace with its source." |
| 2:25-2:45 | Step 6 Documents & A2 | "The agent drafts an A2-style form, checks the four RBI rules for this payment (purpose, PAN, Form A2, the yearly limit), and lists the papers still missing. Tick them off as you gather them." |
| 2:45-3:00 | Step 7 as the student: tap "Ask a parent to sign" | "A student can never sign or pay. One tap sends it to the parents." |
| 3:00-3:35 | Parent: the "Prepared by your student" banner, Open and review, the PIN pad, Send payment, step 8 Receipt | "The parent opens it on their own device; the student's session is retired. The parent's browser recomputes the plan hash itself, then signs that exact plan with the PIN and its own key. The sandbox bank re-checks the university's certificate, pays once, and prints a receipt with the signature and the audit entry." |
| 3:35-3:55 | Assistant page: tap "Is there a hidden markup?" and "What should I do next?" | "The assistant answers from the rules engine and this session, never from guesses. Text that tries to give it instructions is refused and logged." |
| 3:55-4:10 | Student money page: cost USD 1,500 a month for 10 months; show the signed payment record | "For the student's life abroad: sending living money every quarter instead of every month saves about Rs 7,076 in fees, and every payment goes on a record signed by the bank that a landlord or lender can check." |
| 4:10-4:35 | Attack lab: run all attacks, open one trace (changed bank details) | "Now an attacker. Sixteen attacks, each against its own copy of the agent: changed bank details, hidden instructions, look-alike universities, a revoked key, a tampered plan, a forged approval. All stopped, and each shows the audit entries where its defence fired." |
| 4:35-4:50 | Terminal: `python -m unittest discover -s tests -t .` and `python -m scenarios.runner` | "271 tests and twenty-seven scripted scenarios pass with one command each. Synthetic data only, no real money, and not tax advice." |

Check before recording:
- Provider B: 20,000 x 90.20 = Rs 18,04,000; TCS 2% of 8,04,000 = Rs 16,080; fee Rs 3,000; total Rs 18,23,080.
- Provider A: 20,000 x 90.50 = Rs 18,10,000 (Rs 10,000 above the mid-market 90.00) + TCS 16,200 + fee 1,500 = Rs 18,27,700, so Rs 4,620 more than B.
- What-if: no PAN (5%) and Rs 12 lakh sent earlier, so all Rs 18,04,000 is taxed: TCS Rs 90,200.
- Next fee: USD 20,000 due 2027-01-15 (same financial year), so all Rs 18,04,000 is above the used threshold: TCS 2% = Rs 36,080, total Rs 18,43,080 via Provider B.
- Student budget: USD 1,500 a month for 10 months on Provider C; quarterly saves Rs 7,075.92 (six fewer fees of Rs 1,178.82, plus Rs 3 of TCS rounding).
- Test count: re-run the tests and use the number they print.
