# To do (as of Mon 19 Oct 2026)

- **Deadline:** Tue 20 Oct, **21:29 IST** (23:59 Beijing).
- **How to submit:** email the deliverables to the organisers' address that confirmed our registration (19 Oct). Items 1 and 2 are mandatory; the rest are optional.
- **Full plan with status:** [docs/team/TEAM_PLAN.md](docs/team/TEAM_PLAN.md). Where each deliverable is: [SUBMISSION.md](SUBMISSION.md).

## Done
- [x] Registration: confirmed by the organisers on 19 Oct.
- [x] Technical documentation, presentation deck (PPTX and PDF), security self-assessment, execution evidence, README with tests and CI.
- [x] Six tax and limit rules verified on 18 Oct; four RBI LRS compliance rules verified on 19 Oct (purpose, PAN, Form A2, above-cap studies).
- [x] Security fixes R19 (device enrolment) and R20 (cross-site requests).
- [x] Repository public; GitHub Actions green.
- [x] 19 Oct: attack-lab traces, inline paste box, printable receipt, RBI compliance checks, Payment-tab fix.

## Before the final submission (Tue 20, aim for the afternoon)
- [ ] Merge the 19 Oct work into `main` (judges see `main`).
- [ ] Nishanth: record the demo video, up to 5 minutes ([docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)), and add its link to [SUBMISSION.md](SUBMISSION.md).
- [ ] Rerun the numbers just before sending and update the docs and deck if any changed:
  ```
  python -m unittest discover -s tests -t .
  python -m scenarios.runner
  python -m app.demo_run
  ```
- [ ] Send the submission email before 21:29 IST.

## Open decisions
- [ ] OCR for scanned PDFs and photos: Tesseract run directly (Apache-2.0, local; recommended), pytesseract, or a hosted vision model (sends unmasked images; not advised). Needs the team's OK before adding anything.
- [ ] Logo: remove the swirl and favicon across the whole app, or only on the receipt (done)?
- [ ] Missing PAN: the rule pack says PAN is mandatory under LRS, but the app still allows a no-PAN payment at the higher TCS rate. Block it?
- [ ] Slimmer student view (upload, check, send to parent, read-only status, no settings drawer): build or not?

## Still open in the rules (flagged in every output)
- [ ] Earlier other-purpose remittances count toward the Rs 10 lakh threshold (the Act supports it but does not say it outright).
- [ ] TCS on the amount sent, not on fees (needs a bank's confirmation).
- [ ] GST on the currency conversion itself: not modelled; needs a source.
- [ ] A2 purpose code S0305, I-20 / CAS names, document checklist (unverified).

## Nice to have (only if time allows)
- [ ] Mask names and addresses too (known risk R2).
- [ ] Show the ranking with and without TCS, since TCS can be claimed against income tax (needs a source for the wording).

## Finals
- [ ] At least one member must attend in person. Check passport validity and visa early; don't assume both members' travel is covered.
