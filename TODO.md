# To do (as of Sat 17 Oct 2026)

- **Deadline:** Tue 20 Oct, **21:29 IST** (23:59 Beijing).
- **First complete submission:** Sun 18 Oct night. Updates are allowed until the deadline, and the latest version counts.
- **Full plan with status:** [docs/team/TEAM_PLAN.md](docs/team/TEAM_PLAN.md).

## 19 Oct changes (branch `claude/vigorous-leakey-2e8f90`)
- Attack lab: each result opens a step-by-step trace (attacker input, every audit entry with its hash, policy Decision tier/code/reason, where the defence fired, scenario check). C1, C3 and C4 now run through a real agent.
- Invoice: the paste `prompt()` is now an inline paste box; file upload and drag-and-drop (PDF, JSON, text) stay.
- Receipt: printable A4 document with a text heading (no logo), payer, payee, FX rate, fee, TCS, rule trace with sources, ids, audit head hash and a sandbox note.
- Rule pack 2026.10.19-r1: four RBI LRS rules verified against the Master Direction (purpose, PAN mandatory, Form A2, above-cap on the institution's estimate); `compliance_checks()` shown on the Documents step and the receipt.
- Fix: the Payment tab no longer returns to the Attack lab.

## Open decisions (19 Oct)
- [ ] OCR for scanned PDFs and photos: Tesseract run directly (Apache-2.0, local; recommended), pytesseract, or a hosted vision model (sends unmasked images; not advised). Needs the team's OK before adding anything.
- [ ] Logo: remove the swirl and favicon across the whole app, or only on the receipt (done)?
- [ ] Missing PAN: the rule pack says PAN is mandatory under LRS, but the app still allows a no-PAN payment at the higher TCS rate. Block it?
- [ ] Slimmer student view (upload, check, send to parent, read-only status, no settings drawer): build or not?

## Urgent
- [ ] **Chandan: send the registration email.** It was due Fri 16, and registration can close early.
  - Fill the [brackets] in `docs/team/REGISTRATION_EMAIL.md`.
  - Attach the watermarked passport bio pages, but **never commit passports to this repo**.
  - Check fintechathon.g-ican.com for an official form.
- [ ] **Nishanth: review the code in your area.** Chandan built first versions of `agent/`, `app/` (bank, policy, audit, server, UI), the README and CI so the draft is complete. Change anything you planned differently. Run:
  ```
  python -m unittest discover -s tests -t . -v
  python -m app.server        # then open http://127.0.0.1:8000
  ```

## Before the first submission (Sun 18 night)
- [ ] Both: walk through the app end to end (genuine invoice → sign → receipt; then every attack sample and the attack lab).
- [ ] Nishanth: fix the two security findings from the 17 Oct audit (`docs/SECURITY_SELF_ASSESSMENT.md`):
  - R19 (High): the PIN alone can register a new signing key. Enrol the first device only; later devices need a signature from a registered key; refuse PIN checks while frozen.
  - R20 (Medium): `app/server.py` should check `Host`/`Origin` and require JSON.
- [ ] Nishanth: small hand-offs from SPEC.md (Chandan already added `remember_name` for the remitter name and the unmasking of the extracted invoice in `agent/agent.py`):
  - Optionally switch `_compute` to `rules.explain.compare_quotes()`.
  - Optionally show each line's new `source` in the UI (e.g. as a tooltip).
- [ ] Nishanth: review slides 2 and 6 of the deck ([docs/presentation/PRESENTATION.md](docs/presentation/PRESENTATION.md)).
- [ ] Chandan: export the deck as PPTX or PDF into `docs/presentation/`.
- [ ] Decide repo visibility for judges (public link, or share access) and check that GitHub Actions runs green.
- [ ] Rerun the numbers and update the deck if any changed:
  ```
  python -m unittest discover -s tests -t .
  python -m scenarios.runner
  python -m app.demo_run
  ```
- [ ] Submit the first version.

## Before the final submission (Tue 20, aim for the afternoon)
- [ ] **Verify the tax rules against primary sources** (RBI Master Direction on LRS; Income-tax Act 2025 s.394 / Finance Act 2026). Never change a rate without a source.
  - [ ] LRS cap USD 250,000 (unverified)
  - [ ] No-PAN rate 5% (unverified)
  - [ ] Earlier other-purpose remittances count toward Rs 10 lakh (unverified)
  - [ ] TCS on the amount sent, not fees (unverified)
  - [ ] Rs 10 lakh threshold, 2% self-funded and 0% loan-funded education rates (secondary source)
  - [ ] No-PAN + loan-funded case: the rule pack has no rule (shown as a warning)
  - [ ] GST on the currency conversion itself: not modelled; needs a source
  - [ ] A2 purpose code S0305, I-20 / CAS names, document checklist (unverified)
- [ ] Nishanth: record the demo video, 3–5 minutes ([docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)).
- [ ] Both: final check of every deliverable against the official requirements ([docs/team/TEAM_PLAN.md](docs/team/TEAM_PLAN.md#official-deliverables-pbcsf-appendix-2)).
- [ ] Final submission before 21:29 IST.

## Nice to have (only if time allows)
- [ ] Connect a hosted AI model behind `agent/model.py`. Keep masking, the grounding check and the policy gate in front of it.
- [ ] Mask names and addresses too (known risk R2).
- [ ] Show the ranking with and without TCS, since TCS can be claimed against income tax (needs a source for the wording).

## Finals
- [ ] At least one member must attend in person. Check passport validity and visa early; don't assume both members' travel is covered.
