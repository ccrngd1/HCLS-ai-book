# Review Tracker

Single place to track feedback from all reviewers. One row per finding.

**Status values:** `DONE` · `OPEN` · `IN PROGRESS` · `WONTFIX` (with reason) ·
`NEEDS DECISION` (author call required) · `NEEDS EXPERT` (coder, counsel, clinician)

**Conventions**
- Never delete a row. Flip it to `DONE` with the commit SHA so we keep the audit trail.
- `Sev` is the reviewer's severity where given, otherwise mine.
- "Pre-existing" in Notes means it was already fixed before the review arrived, because
  the reviewer read an older build. Worth recording so we do not redo it.

## Reviewers

| ID | Reviewer | Role | Artifact reviewed | Received | Notes |
|----|----------|------|-------------------|----------|-------|
| V | Vince Skinner (vskin) | Sr TAM, AWS HCLS | `book.pdf`, 268pp, 57,466 words | 2026-08-11 | Reviewed the 2026-07-30 build, so a number of findings were already fixed. Retracted two of his own findings unprompted. |
| R | (radwin) | — | — | pending | `reviews/peers/ext-review-radwin.md` is currently empty. |

---

## Status summary

| Status | Count |
|--------|------:|
| DONE | 21 |
| OPEN | 57 |
| NEEDS DECISION | 3 |
| WONTFIX | 2 |
| **total** | **83** |

---

## 1. Factual and coding errors

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-1.1a | Ch8: `N18.3` invalid since 2021-10-01; use `N18.32` (matches Linda's stage 3b, eGFR 39) | Critical | OPEN | Confirmed present in the print-bound main file. |
| V-1.1b | Ch8: hypertension + CKD is `I12`, not `I10` | Critical | OPEN | Two `I10` occurrences confirmed. |
| V-1.1c | Ch8: diabetes + CKD needs combination code `E11.22` | Critical | OPEN | `E11.22` appears nowhere. Target set: `E11.22 + E11.4x + I12.9 + N18.3x`. |
| V-1.2 | Ch8: "rule out = do not code" is outpatient-only (IV.H); inpatient II.H/III.C says code it as confirmed | Critical | OPEN | |
| V-1.3a | Ch14: "no more than 60 hours per week (labor law)" — no such US federal law | Critical | OPEN | Line 36. Replace with state mandatory-overtime limits (PA Act 102, NY Labor Law 167). |
| V-1.3b | Ch14: "minimum 11 hours between shifts (union rule)" is the EU Working Time Directive figure | Significant | OPEN | Line 34. |
| V-1.4 | Ch13: "these two drugs both inhibit CYP2C9" is backwards; needs one inhibitor + one substrate | Critical | OPEN | Line 15, confirmed verbatim. The graph three lines later is already correct. |
| V-1.5 | Ch9: business case predates CPT 92229 (autonomous retinal analysis, ~$45.75 non-facility, HEDIS-eligible) | Significant | OPEN | |
| V-1.6 | Ch14: MIP conflates coverage with the variable index; 42x2x14=1,176 binaries + coverage constraint, not 42x18x14=10,584 | Significant | OPEN | An earlier pass "fixed" the arithmetic and left the formulation wrong. |
| V-1.7a | Ch2: AFib vignette uses warfarin as default; 2023 ACC/AHA/ACCP/HRS prefers a DOAC | Significant | OPEN | |
| V-1.7b | Ch1: "OCR goes back to the 1970s" — Tauschek 1929, GISMO 1951 | Minor | OPEN | |
| V-1.7c | Ch3: edit distance 0.846 should be 0.857 (14 chars, not 13); "Garcia"/"Gracia" is two substitutions or one transposition, not an insertion | Minor | OPEN | |
| V-1.7d | Ch3: "two character transpositions" for 91→19 is one adjacent transposition | Minor | OPEN | |
| V-1.7e | Ch4: Cumulative Complexity Model is Shippee et al. 2012, not May/Montori/Mair | Minor | OPEN | Our own `chapter04.09-todo.md` recorded the same wrong attribution. Fix both. |
| V-1.7f | Ch10: Sinsky finding misstated as "2 hours per 8 hours clinical" | Significant | DONE | Pre-existing fix, commit `423cb4f6`. Corrected to ~2h per 1h face time plus 1-2h nightly. |
| V-1.7g | Ch10: "FDA has signaled ... productivity software" is not a citable FDA position | Critical | DONE | Pre-existing fix, `423cb4f6`. Reattributed to MHRA/NHS England 2026-07-29, with the RCP dissent. |
| V-1.7h | Ch12: LOS math — bed count is algebraically irrelevant; 8% implies LOS 3.75d | Minor | OPEN | |
| V-1.7i | Currency drift: 37M→38.4M diabetes; 21→22 ICD-10-CM chapters; sepsis deaths "at least 350,000" | Minor | OPEN | |

## 2. Model soundness

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-2.1 | Ch7 contradicts itself: argues calibration over discrimination, then assigns by percentile tiers (rank-only) | Significant | OPEN | |
| V-2.2 | Ch7 claims-lag train/serve skew not mentioned | Significant | OPEN | |
| V-2.3 | Ch7 readmission C-statistic 0.684 was death-or-readmission, not readmission alone | Minor | OPEN | |
| V-2.4 | Ch6: z-scoring does not decorrelate; K-means/GMM clusters are unordered so they need no monotonic severity | Significant | OPEN | |
| V-2.5 | Ch12: Monte Carlo intervals falsely narrow (flows sampled independently) | Significant | OPEN | |
| V-2.6 | Ch12: no forecasting evaluation methodology (rolling-origin, pinball, per-horizon skill, coverage) | Significant | OPEN | |
| V-2.7 | Ch12: Poisson vs negative binomial applied inconsistently to ED admits | Minor | OPEN | |
| V-2.8 | Ch12: "discharge order written" is near-label leakage; add point-in-time warning | Significant | OPEN | |

## 3. Production and accessibility

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-3.1 | Nav footer prints as live blue links on p133 | Critical | DONE | Regex matched only the italic form; 5 shapes exist. Broadened to arrow + chapter-link. 19 footers were leaking corpus-wide. |
| V-3.2 | Those links leak the local build path (`file:///...`) | Critical | DONE | 4 `file://` annotations → 0. Added `absolutise_links()` as a safety net. Path had already changed to the cloud-desktop one, so it regenerated on every build. |
| V-3.3 | Blue underlined links print throughout | Minor | DONE | `a{color:inherit;text-decoration:none}` in print.css. |
| V-3.4 | 15 `PGMK<N>ENDPGMK` markers live in the text layer | Significant | DONE | Anchor made `position:absolute` so it is layout-neutral, then stripped on the final render. 15 → 0, pagination unchanged at 254pp. |
| V-3.5 | No PDF bookmarks, no clickable navigation | Significant | DONE | `outline:true` in `page.pdf()`. 40 bookmark entries now present. |
| V-3.6 | Document properties leak toolchain (HeadlessChrome / Skia); no Author, Subject, Keywords | Significant | DONE | `set_pdf_metadata()` via pypdf. Title, Author, Subject, Creator, Producer, Keywords all set. |
| V-3.7 | Justification without hyphenation | Significant | DONE | `hyphens:auto` was already in print.css but inert: `<html>` had no `lang`. Added `lang='en'`. |
| V-3.8 | Tagged-PDF quality low; no figure/table/TOC tagging | Significant | OPEN | `tagged:true` now set and `/MarkInfo` + `/StructTreeRoot` are present, but semantic tag quality is unverified. Needs a real accessibility checker against PDF/UA. |
| V-3.9 | Six typos | Minor | DONE | All six fixed. `eadmitted` was mid-word ("are eadmitted"), not the standalone token it looked like. |
| V-3.10 | Bold body font embedded twice | Minor | OPEN | |
| V-3.11 | Front matter uses arabic, not roman, numerals | Minor | OPEN | |
| V-3.12 | Digital edition on a personal GitHub Pages repo; 80 annotations point at `ccrngd1.github.io` | Critical | DONE | Moved to `https://health-ai.lawson.engineer/`. Manifest updated, QR regenerated and verified to encode the new URL, 78 PDF annotations repointed, 0 references to the old handle remain. |

## 4. Chapter 11 patient safety and standalone readability

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-4.1 | Bot gives a drug and dose (chew 325mg aspirin) pre-EMS, no anticoagulant/bleeding/dissection check | Critical | OPEN | Confirmed verbatim. Crosses the SaMD line the chapter says it will not cross. |
| V-4.2 | Escalation logic self-contradictory: architecture says chest pain routes immediately to 911, exemplar escalates "by turn ten" | Critical | OPEN | |
| V-4.3 | HEART and Wells presented as conversationally gatherable; both need ECG/troponin/exam | Significant | OPEN | Replace with pre-hospital red-flag stratification. |
| V-4.4 | Ch11 Honest Take references five bots absent from this volume; other dangling refs 5.5, 5.7, 5.9, 2.8, 10.4, 10.6 | Significant | OPEN | Violates the Preface promise to describe rather than cross-reference. |

## 5. Regulatory layer (2024-2026)

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-5.1 | ONC/ASTP HTI-1 DSI criteria (31 transparency attributes, eff. 2025-01-01) | Critical | DONE | In-place HTI-1 awareness note added to 7.5 and 13.4. Did not assert the source-attribute count, which I could not verify. Author constraint 2026-08-11: we are not compliance experts, so the book names what exists and why it touches the recipe, and routes the reader to their own legal and compliance teams. It does not say how to comply. |
| V-5.2 | California AB 3030 (GenAI patient communications, eff. 2025-01-01) | Critical | DONE | In-place AB 3030 note added to 2.5. Verified the clinician-review exemption, which is the useful fact here: 2.5's existing review step is the pivot the rule turns on. Author constraint 2026-08-11: we are not compliance experts, so the book names what exists and why it touches the recipe, and routes the reader to their own legal and compliance teams. It does not say how to comply. |
| V-5.3 | Section 1557 final rule (compliance 2025-05-01) | Critical | DONE | In-place Section 1557 note added to 9.6 and 10.7, tied to the per-cohort accuracy monitoring already in both. Author constraint 2026-08-11: we are not compliance experts, so the book names what exists and why it touches the recipe, and routes the reader to their own legal and compliance teams. It does not say how to comply. |
| V-5.4 | EU AI Act timeline: Annex I → 2028-08-02, Annex III → 2027-12-02 (2026 Digital Omnibus) | Critical | WONTFIX | US-only scope per author decision 2026-08-11. Also moot as written: the book states no EU AI Act date, so there is no incorrect date to correct. |
| V-5.5 | 42 CFR Part 2 final rule (compliance 2026-02-16) | Significant | OPEN | Ch5's no-link flags predate it. |
| V-5.6 | FDA PCCP guidance (final 2024-12) | Significant | DONE | In-place PCCP note added to 9.6, framed as a vendor question for a cleared device. Not added to 7.5: PCCP scope is AI-enabled device software functions, and 7.5's model is non-device CDS when clinician-mediated, so citing it there would mislead. Author constraint 2026-08-11: we are not compliance experts, so the book names what exists and why it touches the recipe, and routes the reader to their own legal and compliance teams. It does not say how to comply. |
| V-5.7 | CMS-0057-F prior authorization | Significant | OPEN | |
| V-5.8 | Joint Commission + CHAI Responsible Use of AI (2025-09-17) | Significant | OPEN | |
| V-5.9 | NIST AI RMF + GenAI Profile (AI 600-1) | Significant | OPEN | |
| V-5.10 | Recommendation: one cross-cutting "The Regulatory Layer" chapter | — | WONTFIX | Author decision 2026-08-11: no 16th chapter. It would change the manifest, pipeline, page count and spine, and the flagship-15 structure is locked. **This declines the mechanism, not the substance** — V-5.1 to V-5.9 stay open and, if addressed, go in-place in the recipes they touch. |

## 6. Missing technical layer

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-6.1 | Agentic AI absent (MCP, prior-auth agents, revenue-cycle agents) | Significant | NEEDS DECISION | Book-scope call, not a fix. |
| V-6.2 | No coherent evaluation story (LLM-as-judge reliability, golden datasets, red-teaming, MedHELM, HealthBench) | Significant | OPEN | |
| V-6.3 | No governance artifacts (CHAI model cards, AI use inventories) | Significant | OPEN | |
| V-6.4 | No LLM security (prompt injection, jailbreaks, PHI in prompts/logs, OWASP LLM Top 10) | Significant | OPEN | |
| V-6.5 | CDS Hooks missing from the body (Appendix B only) | Significant | OPEN | Standard integration point for Ch7 and Ch13 alerting. |
| V-6.6 | Epic Sepsis Model external-validation failure (Wong 2021, AUC 0.63 vs claimed 0.76-0.83) omitted from Ch7 and Ch15 | Significant | OPEN | |
| V-6.7 | Prenosis Sepsis ImmunoScore (first FDA De Novo sepsis AI, 2024-04) omitted from Ch15 | Significant | DONE | Pre-existing fix, `646a6818`. Added to 15.4's buy-vs-build verdict with DEN230036. |

## 7. Enterprise readiness

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-7.1 | No vendor data-handling posture (BAA, no-train/no-retain, data residency) for cloud LLM and speech services | Critical | OPEN | Table stakes for this audience. |
| V-7.2 | Secondary use / training on historical PHI lacks minimum-necessary, de-identification, IRB/DUA governance | Critical | OPEN | RL trajectories especially re-identifiable. |
| V-7.3 | Ch5: a wrong automatic MPI merge is a reportable breach (60-day clock), not just data quality | Critical | OPEN | |
| V-7.4 | No model change-control or rollback (version pinning in the audit record, champion-challenger) | Significant | OPEN | |
| V-7.5 | No security incident-response or breach-notification runbook for serving chapters | Significant | OPEN | |
| V-7.6 | Automation bias unmonitored (no reviewer edit-rate tracking, no seeded errors) | Significant | OPEN | Safety argument rests on human review the book itself shows decaying. |
| V-7.7 | Tool-using LLMs have no enforced authorization boundary; frame as OWASP "excessive agency" | Critical | OPEN | "Conservative by default" is a prompt property, not a control. |
| V-7.8 | Ch9 liability overclaims ("absorbed the medico-legal liability", "simplifies regulatory compliance") | Significant | OPEN | |
| V-7.9 | Ch8 specificity bias is potential False Claims Act / OIG upcoding exposure, not just training noise | Significant | OPEN | |

## 8. Chapter 14 optimization

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-8.1 | Fairness as a summed penalty can concentrate bad shifts on a few nurses; use max-min or bounded-spread | Significant | OPEN | |
| V-8.2 | No infeasibility handling despite a scenario that makes it likely; add IIS or elastic constraints | Significant | OPEN | |

## 9-11. Positioning, front/back matter, structure

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-9.1 | "Vendor-agnostic" claim contradicted by named AWS services, 15 AWS callouts, AWS service index | Significant | NEEDS DECISION | His fix: drop the claim, retitle Appendix B "AWS Service Index", reword the callouts. |
| V-10.1 | No About the Author | Critical | OPEN | His "would fix today". The book's authority rests on first-person claims. |
| V-10.2 | No ISBN | Minor | OPEN | Required only for library/bookstore/catalogue discoverability. |
| V-10.3 | Appendix B unusable as a print index (recipe numbers, not pages) | Significant | DONE | Pre-existing fix, `68704943`. Now generated from tags with 120 page-numbered entries. |
| V-10.4 | Appendix B casing errors (Rxnorm, Sns, Sqs, Waf, Cloudtrail, Samd, Elasticache, Gpu, Shap, Transcribe medical) | Minor | DONE | Pre-existing fix, `68704943`, via the `DISPLAY` map. All ten verified. |
| V-10.5 | Appendix B Fairness entry omits 14.4 | Minor | DONE | Index now derived from tags, so it cannot drift. |
| V-10.6 | Ch13 placeholder citations ("[RCT: Smith et al. 2018]") look like real citations | Significant | OPEN | Cite two real papers or label the box illustrative. |
| V-10.7 | Disclaimer lacks not-medical-advice, no clinician-patient disclaimer, no drug-dosing carve-out | Critical | OPEN | Book prints a specific aspirin dose, DDI severities, sepsis treatment. Add per-chapter safety banners on 11, 13, 15. |
| V-10.8 | AI content disclosure (KDP), trademark acknowledgment, employer clearance, "views are my own" | Critical | NEEDS DECISION | Employer review has the longest lead time of anything on this list. |
| V-11.1 | Per-recipe header fields not comparable ("Phase" mixes three taxonomies) | Significant | DONE | Field removed entirely, `1ef700f7`. |
| V-11.2 | "Estimated Cost" mixes units; Ch1 "~$0.05 per" truncated; Ch14 renders "~$100200/month" | Significant | DONE | Field removed entirely, `1ef700f7`. |
| V-11.3 | Body chapter titles use recipe names, Appendix A uses capability areas | Minor | OPEN | |
| V-11.4 | Define the header fields in "How to Use This Book" | Minor | OPEN | Now documented in RECIPE-GUIDE.md, but not in the book itself. |

## Retracted by the reviewer

| ID | Finding | Notes |
|----|---------|-------|
| V-R1 | QR code on p6 missing | Retracted. Present and scannable; drawn as vector paths, which is why an image-listing tool missed it. |
| V-R2 | PGMK markers visibly printed atop every chapter | Retracted as stated. 0.87pt against a 24.7pt title, so invisible in print. Real at lower severity as a text-layer issue — tracked as V-3.4. |

## Explicitly not defects

- Inline attribution style (Kessels 2003, Fellegi and Sunter 1969) is a legitimate practitioner-book convention.
- Absence of a back-matter bibliography is a nice-to-have.
- Typo rate of 8-12 across 57,466 words is clean for self-published technical work.

## What the reviewer said not to touch

Recorded so no future edit quietly removes it: the problem statements (Dr. Patel at 6:47pm,
Devon at 2:14am, Linda in a second-floor walk-up); Ch9's buy-do-not-build verdict; Ch10's
biometric governance section; Ch5's Fellegi-Sunter content; "the model is a writer, not a
decision maker"; equity as first-class; Ch15's restraint on sepsis RL.
