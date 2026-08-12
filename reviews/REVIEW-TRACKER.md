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
| R | (radwin) | — | Digital edition (site) | 2026-08-11 | Short-form feedback, 110 words, 5 findings. Focused on reader accessibility and site structure rather than technical content. |

---

## Status summary

| Status | Count |
|--------|------:|
| DONE | 36 |
| OPEN | 53 |
| NEEDS DECISION | 1 |
| WONTFIX | 3 |
| **total** | **93** |

---

## 1. Factual and coding errors

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| V-1.1a | Ch8: `N18.3` invalid since 2021-10-01; use `N18.32` (matches Linda's stage 3b, eGFR 39) | Critical | DONE | Fixed. Used `N18.30` (stage 3 unspecified), **not** the `N18.32` the reviewer asked for: he conflated two patients. Linda with eGFR 39 is the Ch4.09 persona; Ch8's patient is documented "stage 3" with no sub-stage, and AAPC confirms a coder may not infer the stage from eGFR. Added that constraint to the passage as a teaching point. **Closed by author 2026-08-12 without certified-coder review.** Basis: each code was verified against professional coding sources (AAPC coding-alert guidance and icd10data) rather than only against the reviewer's claim, and Chapter 8 already tells the reader the code set is revised annually, so the codes read as a worked example inside a chapter about maintenance rather than as a coding authority. Residual risk accepted: verification was secondary-source, not a coder sign-off. |
| V-1.1b | Ch8: hypertension + CKD is `I12`, not `I10` | Critical | DONE | Fixed. Line 9 now takes `I12.9`. Deliberately left line 31's "Hypertension maps to I10" alone: that line describes what a rule-based dictionary does, and I10 is correct for essential hypertension alone, so changing it would be an over-correction. Only one of the two occurrences was a defect. **Closed by author 2026-08-12 without certified-coder review.** Basis: each code was verified against professional coding sources (AAPC coding-alert guidance and icd10data) rather than only against the reviewer's claim, and Chapter 8 already tells the reader the code set is revised annually, so the codes read as a worked example inside a chapter about maintenance rather than as a coding authority. Residual risk accepted: verification was secondary-source, not a coder sign-off. |
| V-1.1c | Ch8: diabetes + CKD needs combination code `E11.22` | Critical | DONE | Fixed. `E11.22` added and sequenced ahead of the hypertensive code, per the I12 "code first" note. Verified the "with" convention presumes the causal link. **Closed by author 2026-08-12 without certified-coder review.** Basis: each code was verified against professional coding sources (AAPC coding-alert guidance and icd10data) rather than only against the reviewer's claim, and Chapter 8 already tells the reader the code set is revised annually, so the codes read as a worked example inside a chapter about maintenance rather than as a coding authority. Residual risk accepted: verification was secondary-source, not a coder sign-off. |
| V-1.2 | Ch8: "rule out = do not code" is outpatient-only (IV.H); inpatient II.H/III.C says code it as confirmed | Critical | DONE | Fixed. Verified against ICD-10-CM guidance that the two settings genuinely disagree: IV.H says do not code an uncertain outpatient diagnosis, II.H and III.C say code it as established for an inpatient stay *if the uncertainty is still documented at discharge*. Rewrote the bullet to be setting-dependent and added the consequence the reviewer did not draw out: the label is a property of the encounter, not the sentence, so one classifier trained across both settings is being taught two contradictory labels for identical text and the result looks like model noise. Also recorded that the inpatient rule is a facility-billing rule, so one admission can yield different answers on the facility and professional claims. |
| V-1.3a | Ch14: "no more than 60 hours per week (labor law)" — no such US federal law | Critical | DONE | Replaced with what the law actually says. No US federal weekly hour ceiling exists for adults; FLSA governs overtime pay, not hours. Verified against pa.gov and dol.ny.gov that Act 102 and Labor Law 167 restrict *mandatory* overtime rather than capping hours, so the constraint is a consent flag per assignment, not a numeric bound. Author subsequently trimmed the accompanying modelling note, so the fix now rests entirely on the corrected bullets: the false federal-law attribution is gone and each constraint is attributed to policy, contract or state law. The consent-flag-versus-numeric-bound point is no longer in the text, by author choice. |
| V-1.3b | Ch14: "minimum 11 hours between shifts (union rule)" is the EU Working Time Directive figure | Significant | DONE | Rest between shifts is now attributed to the bargaining agreement or facility policy, The 11-hour figure and its European Working Time Directive origin were in the trimmed note and are no longer stated; the bullet no longer asserts a number at all, which resolves the defect. |
| V-1.4 | Ch13: "these two drugs both inhibit CYP2C9" is backwards; needs one inhibitor + one substrate | Critical | DONE | Rewritten as fluconazole inhibiting CYP2C9 with warfarin as substrate, matching the book's own graph at lines 42-44 rather than inventing a new drug pair. Added an explicit note that the mechanism needs one inhibitor and one substrate, and that two inhibitors of the same enzyme do not interact by it. |
| V-1.5 | Ch9: business case predates CPT 92229 (autonomous retinal analysis, ~$45.75 non-facility, HEDIS-eligible) | Significant | DONE | Business case rewritten around CPT 92229. Two corrections to the reviewer: the code is carrier-priced rather than paid off a national fee schedule, so his ~$45.75 is one carrier's number and is deliberately not quoted; and per payer guidance, billing 92229 alone does **not** close the HEDIS eye-exam measure, because it records that imaging happened, not what it found. Both caveats are now in the text. |
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
| V-3.1 | Nav footer prints as live blue links on p133 | Critical | DONE | Superseded by the R-3 root fix and now permanent. Footers no longer exist in source at all, so the print strip regex is a pure safety net that matches nothing: ch09, the chapter that leaked to page 133, now reports nav-0 because there is nothing left to strip. Print unchanged at 259 pages, 0 file:// annotations. |
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
| V-4.1 | Bot gives a drug and dose (chew 325mg aspirin) pre-EMS, no anticoagulant/bleeding/dissection check | Critical | DONE | Drug and dose removed. The bot now defers the aspirin question to the 911 dispatcher and says why: it cannot know whether the patient took an anticoagulant, and cannot see a dissection at all. Also reinforced the scope-discipline paragraph so a later edit does not restore the dose. |
| V-4.2 | Escalation logic self-contradictory: architecture says chest pain routes immediately to 911, exemplar escalates "by turn ten" | Critical | DONE | Resolved by correcting the architecture claim rather than the walkthrough. The walkthrough escalates after four questions, not ten as the review states, and that behaviour is clinically defensible; the defect was the screening step overclaiming that active chest pain routes immediately to 911. It now separates presentations needing no further questions from those needing a short red-flag pass. |
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
| V-6.1 | Agentic AI absent (MCP, prior-auth agents, revenue-cycle agents) | Significant | WONTFIX | Author decision 2026-08-12: agentic AI and MCP stay out. The print volume is a 15-recipe sampler, and it is reasonable for agentic patterns not to be a banner use case in a curated subset. No scope note added either, per instruction, so the book does not draw attention to the omission. The digital edition is expected to cover this eventually, which is where a new capability area belongs: it can be added there without touching the manifest, pagination or spine. |
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
| V-7.3 | Ch5: a wrong automatic MPI merge is a reportable breach (60-day clock), not just data quality | Critical | DONE | Fixed in the Reversibility section, which already said the compliance implications were large without saying what they were. Now names the exposure: a wrong merge is an impermissible disclosure, presumed reportable under the HIPAA Breach Notification Rule absent a documented risk assessment, with the clock running from discovery rather than from completing the unmerge. Framed to change the engineering requirement, since 'we can unmerge it' is weaker than 'which records were exposed, to whom, and for how long'. Held to the author's standing constraint: it routes the determination to the privacy officer and counsel and does not tell the reader what the rule requires of them. |
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
| V-9.1 | "Vendor-agnostic" claim contradicted by named AWS services, 15 AWS callouts, AWS service index | Significant | DONE | Resolved by making the claim precise rather than dropping it. The print volume now states plainly that everything in it is cloud-agnostic, that the digital companions are written against AWS because a worked example has to pick something concrete, and that each of those choices has an on-premises equivalent and a counterpart on the other hyperscalers. The word 'vendor-agnostic' no longer appears in the print book at all: it was doing double duty as both a design property and a marketing claim, and the new wording says what is actually true. The 15 per-recipe callouts changed from 'The AWS implementation lives in the digital edition' to 'The implementation lives in the digital edition ... for one concrete build of it, on AWS', which stops the print volume reading as an AWS book while keeping the pointer honest. KDP listing copy updated to match. **Author declined the reviewer's Appendix B rename**: it stays 'Topic and Service Index'. AWS is still named 39 times where naming it is accurate. |
| V-10.1 | No About the Author | Critical | OPEN | His "would fix today". The book's authority rests on first-person claims. |
| V-10.2 | No ISBN | Minor | OPEN | Required only for library/bookstore/catalogue discoverability. |
| V-10.3 | Appendix B unusable as a print index (recipe numbers, not pages) | Significant | DONE | Pre-existing fix, `68704943`. Now generated from tags with 120 page-numbered entries. |
| V-10.4 | Appendix B casing errors (Rxnorm, Sns, Sqs, Waf, Cloudtrail, Samd, Elasticache, Gpu, Shap, Transcribe medical) | Minor | DONE | Pre-existing fix, `68704943`, via the `DISPLAY` map. All ten verified. |
| V-10.5 | Appendix B Fairness entry omits 14.4 | Minor | DONE | Index now derived from tags, so it cannot drift. |
| V-10.6 | Ch13 placeholder citations ("[RCT: Smith et al. 2018]") look like real citations | Significant | OPEN | Cite two real papers or label the box illustrative. |
| V-10.7 | Disclaimer lacks not-medical-advice, no clinician-patient disclaimer, no drug-dosing carve-out | Critical | OPEN | Book prints a specific aspirin dose, DDI severities, sepsis treatment. Add per-chapter safety banners on 11, 13, 15. |
| V-10.8 | AI content disclosure (KDP), trademark acknowledgment, employer clearance, "views are my own" | Critical | DONE | Resolved 2026-08-12. Employer clearance **granted** by the author's employer. Added to the generated copyright page and mirrored on the digital edition landing page: (1) a views disclaimer that names both current *and former* employers plus any affiliated organization, per author instruction; (2) a trademark acknowledgment naming the 13 Amazon and AWS marks that actually appear in the print volume, with the standard editorial-use, no-affiliation and no-endorsement language. KDP's AI-content disclosure was completed on the KDP side. Per explicit author instruction, **no mention of AI use appears in the published content of either edition**, verified by grep across the print book, README and Home. Copyright page absorbed both additions without spilling: 259 pages unchanged. |
| V-11.1 | Per-recipe header fields not comparable ("Phase" mixes three taxonomies) | Significant | DONE | Field removed entirely, `1ef700f7`. |
| V-11.2 | "Estimated Cost" mixes units; Ch1 "~$0.05 per" truncated; Ch14 renders "~$100200/month" | Significant | DONE | Field removed entirely, `1ef700f7`. |
| V-11.3 | Body chapter titles use recipe names, Appendix A uses capability areas | Minor | OPEN | |
| V-11.4 | Define the header fields in "How to Use This Book" | Minor | OPEN | Now documented in RECIPE-GUIDE.md, but not in the book itself. |

## 12. Radwin: accessibility, register, site structure

| ID | Finding | Sev | Status | Notes |
|----|---------|-----|--------|-------|
| R-1 | Spell out technology and healthcare abbreviations and jargon on first use (OCR, X12, 4010, 277 given as examples) | Significant | OPEN | Measured, and the gap is wide: FHIR 1761 uses / 3 expansions, ASR 736/7, HL7 350/1, OCR 336/2, EOB 150/20, NER 105/17. Bare X12 transaction numbers: 837 (110), 271 (79), 835 (69), 270 (61), 277 (18). `4010` does not appear at all. Correct standard is first use *per recipe*, not per book, because recipes are read standalone. Best paired with a glossary appendix so print readers have one place to look. Large mechanical job, good ralph candidate. |
| R-2 | Overly informal register; colloquialisms should be rewritten while keeping it conversational (`bog standard` cited) | Significant | OPEN | Confirmed and concentrated: `bog-standard`, `low-hanging fruit` and `secret sauce` all sit in `chapter03.01-duplicate-claim-detection.md`, which is **print-bound**. Others: `punt on` x3 (7.10, 8.08, 8.09), `moving the needle` (4.04), `hand-wavy` (2.04), `secret sauce` (3.06). Deliberately excluded from scope: `adversarial` (44) is correct technical usage, `gotcha` (73) is standard technical register and appears in prose only, never as a heading. |
| R-3 | Digital edition bottom page navigation: missing on some pages, broken on others | Significant | DONE | Fixed at the root. Footers are now generated at render time from `_Sidebar.md` by `render_prev_next_html()` in md-to-html (commit 4e05d5d, 7 new tests), so they cannot drift from the sidebar. Removed 1,196 lines of hand-written footer from 297 source files with `strip_nav_footers.py`, which needed three passes because 17 files had two footers stacked. Coverage is now exactly the 322 sidebar entries, with 0 double footers. Python companions keep their hand-written footer deliberately: they are absent from the sidebar by design, so the generator emits nothing and stripping theirs would leave them with no way back. Diagnosis note: one of the four shapes put a table separator row after its content row, which renders as literal pipes, and that is most likely the "broken" the reviewer saw. |
| R-4 | Some chapters have both an overview and a preface; only one is needed, combine | Minor | OPEN | Chapter 1 only. It carries `chapter01-index.md` (sidebar "Overview"), `chapter01-preface.md`, and `chapter01-executive-summary.md`, where chapters 2-15 have a preface alone. All three share the identical H1 "Chapter 1: Document Intelligence", so the site shows three differently-scoped pages under one title. Note the content does not overlap: index is What You'll Learn / Prerequisites / Chapter Architecture / Recipes, preface is the conceptual essay, exec summary is for leadership. So this is a naming and navigation problem more than a duplication problem. |
| R-5 | Some chapters' overview is just the first recipe | Significant | NEEDS DECISION | Could not reproduce, need the reviewer to point at one. Ruled out: no chapter preface duplicates its first recipe (max text similarity 0.02 across all 15), `Home.md` and `README.md` contain no chapter links at all, and the sidebar links chapters only to prefaces and recipes. Two candidates for what was actually seen: the sidebar has no chapter landing page for 2-15, so a chapter name is unclickable text and the first thing under it is a recipe; or R-4's Ch1 "Overview" was read as the pattern and found missing elsewhere. |
| R-6 | Chapter titles disagree between the sidebar and the chapter pages | Significant | DONE | Fixed. Canonical set is the preface/manifest family, which already held 3 of the 4 sources and reads as book titles rather than ML taxonomy. Applied to `_Sidebar.md`, `README.md`, `Home.md`, `SUMMARY.md` and `print/manifest.json` (Ch15 `& RL` spelled out, which also serves R-1). All 15 chapters now agree across all four sources. Author kept the Family A titles for Ch2 and Ch8, with the searchable terms (`LLM`, `generative AI`, `non-LLM`) moved into the description column so discoverability is preserved. Also normalized 120 chapter cross-references across 46 recipes that used 29 different names for the 15 chapters; guarded by requiring the reference's chapter number to match the name, so 1,038 legitimate recipe titles in the same idiom were left untouched, and 0 mismatches were found. |
| R-10 | `chapter01-executive-summary` is a content page absent from the sidebar | Minor | OPEN | Found when generated-footer coverage came to 322 of 479 pages and this was one of four non-companion pages missing one. It is real content, rendered to `docs/chapter01-executive-summary.html`, but it is not in `_Sidebar.md`, so it is unreachable by navigation and gets no prev/next. Relates to R-4: Ch1 is the only chapter with an executive summary at all. Either add it to the nav or fold it into the chapter, alongside the R-4 decision. |
| R-7 | Complexity labels leak into the `**Recipe N.x (...)**` cross-reference idiom | Minor | OPEN | Found while normalizing R-6. The parenthetical should carry a recipe title or chapter name, but ~20 references carry a complexity value instead: `Complex` (8), `Medium-Complex` (5), `Simple-Medium` (4), `Medium` (3). Almost certainly residue from the retired Complexity field. Reader-facing in the digital edition. Mechanical to fix once each is mapped to the intended target. |
| R-8 | `SUMMARY.md` is an internal project-status document but is published to the site | Significant | OPEN | Found while fixing R-6. It renders to `docs/SUMMARY.html`, and its content is authoring status: a "Planning Doc" column pointing at `categories/*.md`, per-chapter DONE flags, and writing rules. A reader arriving from search sees the book's construction scaffolding. Either exclude it from the site build the way `plan_docs` is excluded, or rewrite it as reader-facing front matter. |
| R-9 | `categories/` is tracked in git but is not published and is superseded | Minor | OPEN | 15 files from the pre-split structure, tracked but absent from `docs/`. It is the target of several broken cross-references already logged as `[NEEDS HUMAN]` findings in the todo files, so it actively misleads. Decide whether to delete it or move it under an ignored path. |

---

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
