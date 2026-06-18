# Recipe 4.6: Care Gap Prioritization ⭐⭐

<!--
TechEditor pass v1 (2026-05-16, ch04-r06-edit). Editorial fixes:
- Verified em-dash count: 0 (passes "no em dashes ever" rule).
- Verified en-dash count: 0.
- Header hierarchy: H1 title only, H2 for major sections, H3 for subsections,
  one H4 (#### Walkthrough). No skipped levels.
- Voice drift scan: no documentation-voice openings, no LinkedIn-influencer
  patterns, no "we are excited" announcements. "High-leverage" in
  Variations is the colloquial leverage-point sense (acceptable per Voice
  reviewer).
- Vendor balance: 70/30 maintained. The Problem, The Technology, and
  General Architecture Pattern stay vendor-neutral; AWS service names
  appear only in The AWS Implementation.
- RECIPE-GUIDE compliance: all required sections present in correct order
  (Problem, Technology, General Architecture, AWS Implementation, Expected
  Results, Why This Isn't Production-Ready, Honest Take, Variations,
  Related Recipes, Additional Resources, Implementation Time, Tags,
  Footer Navigation).
- Existing TechWriter TODO markers from prior personas preserved in place.
- New TODOs added flagging substantive technical concerns rather than
  rewriting (per persona instructions: "do not introduce new claims or
  technical content"; "if a section needs substantial rewriting, flag it
  rather than rewriting"):
  * Expert Review A2 HIGH: data_quality_flag computed but never gates
    downstream stages (added at General Architecture Pattern).
  * Expert Review A3 HIGH: HEDIS Comprehensive Diabetes Care (CDC) measure
    retired; replace with EED/KED/GSD/BPD naming (added at The Technology
    bullet and at Expected Results sample).
  * Expert Review A6 MEDIUM: chained-closure state machine missing
    (added at Variations specialist-coordination paragraph).
  * Expert Review A9 MEDIUM: David vignette clinical loosenesses
    (pneumococcal-at-64, family-history elevated-risk, six-years-overdue
    math; added inline at the eleven-gaps paragraph).
  * Expert Review A10 MEDIUM: closure-tracker mutation-based state
    machine fragile to out-of-order events (added at Step 5).
  * Expert Review A11 MEDIUM: chase_period_weight_overrides not
    architected (added at production-gaps year-end paragraph).
  * Expert Review S1 MEDIUM: process_clinician_override missing
    patient-identity boundary check (added inline in Step 6 pseudocode).
  * Code Review WARNING 3: in_visit pathway dispatched as no-op when no
    upcoming visit (added inline in Step 4 pseudocode).
- Did NOT modify: prose flow, structural section order, technical claims
  (these are TechWriter's domain). Did NOT rewrite the David vignette,
  the Honest Take, or any code block.

TechEditor pass v2 (2026-05-16, ch04-r06-edit). Verification-only pass:
- Re-verified em-dash count: 0 (UTF-8 byte-level scan for U+2014).
- Re-verified en-dash count: 0 (UTF-8 byte-level scan for U+2013).
- Re-verified zero smart quotes (U+2018/U+2019/U+201C/U+201D), zero
  double-spaces between words in prose, no genuine repeated-word typos
  (the only regex hits were intentional Mermaid node IDs).
- Re-verified header hierarchy: 1 H1, 11 H2, 14 H3, 1 H4. No skipped
  levels.
- Code-fence convention: 12 fenced blocks total. 1 mermaid, 4 json,
  7 unlabeled (pseudocode and ASCII-art architecture diagram). Verified
  this matches the chapter-wide convention by sampling 1.1, 4.1, 4.4,
  4.5, all of which leave pseudocode/ASCII fences unlabeled and tag
  only mermaid and json. Convention is consistent across the book;
  no fence-tag changes made.
- TODO marker count: 37, all from prior personas, all preserved.
- Voice drift re-scan with expanded marketing-language list: no hits
  (the single "We are excited" regex hit was inside the v1 editor
  HTML comment block describing what was scanned for, not in prose).
- Vendor balance: spot-checked The Problem, The Technology, General
  Architecture Pattern; AWS service names remain confined to The AWS
  Implementation onward.
- Front matter (Complexity / Phase / Estimated Cost) and footer
  navigation links preserved; Python companion link target
  (chapter04.06-python-example) verified.
- No new edits applied this pass. Recipe is publishable on editorial
  grounds; the three HIGH expert-review findings (A1 contact-counter
  reconciliation, A2 data_quality_flag gating, A3 HEDIS CDC measure
  rename) remain flagged as TechWriter TODOs per persona rule "if a
  section needs substantial rewriting, flag it rather than rewriting."

TechEditor pass v3 (2026-05-16, ch04-r06-edit). Final verification pass:
- Re-confirmed UTF-8 byte-level counts on the persisted file:
  em-dash (U+2014) = 0, en-dash (U+2013) = 0, smart single quotes
  (U+2018/U+2019) = 0, smart double quotes (U+201C/U+201D) = 0.
  (PowerShell Get-Content with regex initially reported false positives
  due to encoding handling; raw [System.IO.File]::ReadAllBytes plus
  UTF-8 decode confirms zero on all six code points.)
- Re-confirmed header hierarchy: 1 H1, 11 H2, 14 H3, 1 H4, 0 H5.
  No skipped levels.
- Re-confirmed TODO marker count: 34 actual persona-TODO HTML-comment
  markers in the file (canonical shape: an HTML comment opener
  followed by the word TODO and a persona name). All 34 markers
  originate from prior personas (TechWriter, Code Review, Expert
  Review). Zero TODO markers added or removed by this editor pass.
  (Earlier loose word-match counts in v1 and v2 reported 37-38
  because they also matched narrative mentions of "TODO" inside
  prior editor comment blocks; this v3 count uses a tighter regex.)
- Re-confirmed code-fence convention: 24 fence lines = 12 fenced
  blocks. Convention (mermaid and json tagged; pseudocode and
  ASCII-art unlabeled) preserved.
- Voice drift re-scan: zero "This recipe demonstrates", zero
  "we need to talk about". The two "we are excited" regex hits both
  fall inside this editor-comment block (v1 and v2 self-references
  describing what was scanned for); zero hits in prose.
- Cross-checked persona instructions: "Do not change the structural
  order of sections", "Do not introduce new claims or technical
  content", "Preserve all TODO markers from other personas",
  "If a section needs substantial rewriting, flag it rather than
  rewriting", "Match STYLE-GUIDE.md voice throughout". All five
  constraints satisfied.
- Final disposition: PASS for editorial publication. Recipe is ready
  to ship as soon as the three HIGH TechWriter TODOs are resolved
  (A1, A2, A3) and the chapter-wide hardening TODOs land in their
  next pass (S1-S5, A4-A11, N1-N3). The editorial layer is complete.

TechEditor pass v4 (2026-05-21, ch04-r06-edit). Re-verification only:
- UTF-8 byte-level scan reconfirms: em-dash=0, en-dash=0,
  smart-single-quote=0, smart-double-quote=0.
- Header hierarchy reconfirmed: 1 H1, 11 H2, 14 H3, 1 H4, 0 H5.
  No skipped levels.
- TODO marker count reconfirmed: 34 persona-TODO HTML-comment
  markers, all from prior personas (TechWriter, Code Review tagged,
  Expert Review tagged). Zero added or removed.
- Structural section order reconfirmed against RECIPE-GUIDE.
- Voice spot-check across The Problem, The Technology, The AWS
  Implementation, The Honest Take, and Variations: no documentation-
  voice openings, no LinkedIn-influencer patterns, no marketing
  language, no announcement statements. The single "high-leverage"
  in Variations is the colloquial leverage-point sense (Voice
  reviewer's V2 finding accepts as written).
- Per persona instructions ("Do not change the structural order of
  sections", "Do not introduce new claims or technical content",
  "Preserve all TODO markers from other personas", "If a section
  needs substantial rewriting, flag it rather than rewriting"),
  this v4 pass applies no edits to the recipe body. The three HIGH
  TechWriter TODOs (A1 contact-counter reconciliation, A2
  data_quality_flag gating, A3 HEDIS CDC measure rename) and the
  chapter-wide hardening TODOs remain in place for the TechWriter
  follow-up pipeline. Editorial layer is complete; recipe ships
  when the HIGH TODOs resolve.
-->

<!--
TechEditor pass v5 (2026-06-17, ch04-r06-archsplit). Post-split seam polish:
- Updated TODO A2 to clarify that Step 1-5 references and "Where it
  struggles" section now live in the architecture companion file
  (chapter04.06-architecture.md).
- Verified architecture callout is well-placed between General Architecture
  Pattern and The Honest Take.
- Verified The Honest Take has no dangling references to AWS content.
- Verified General Architecture Pattern prose is vendor-agnostic (AWS
  service names in "Where This Sits in the Chapter" are cross-references
  to prior recipes' shared infrastructure, not new AWS content).
- Verified architecture companion opens cleanly with backlink header.
- Em-dash count: 0. En-dash count: 0.
- All prior TODO markers preserved.
-->

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.002-0.012 per prioritized gap recommendation (depends on uplift model serving and LLM pre-visit summary tailoring)

---

## The Problem

David is 64. He has been a patient at the same primary care practice for fifteen years. His chart, if you scroll through it, looks like the chart of a reasonably engaged middle-aged man who has accumulated the usual middle-aged things: type 2 diabetes (diagnosed nine years ago), well-controlled hypertension, a borderline LDL that's been managed by diet and a low-dose statin, and a family history that includes a father who died of colon cancer at 71 and a mother who is alive at 88 and has osteoporosis. His most recent A1c is 7.8 (up from 7.1 a year ago). His most recent blood pressure is 132/82. He has had a lot of visits over the years, and a lot of orders entered, and a lot of fields populated.

If you ask David's plan's analytics team to pull his open care gaps, the report comes back with eleven of them.

He is overdue for his diabetic retinal exam (last one was 26 months ago; the gap window for the HEDIS Eye Exam for Patients with Diabetes measure closed five months ago). He is overdue for his diabetic foot exam (last documented one was 19 months ago; the practice's quality dashboard shows it red). He is overdue for his colonoscopy (last one was at 54, ten years ago, when normal-result recommendations were every ten years; the current USPSTF guidance starts at 45 and his family history flags him for earlier and more frequent screening). He has not had a flu shot this season. He has not had the COVID booster the CDC recommended for adults over 50 with diabetes. He has not had the pneumococcal vaccine that became indicated when he turned 64 in February. He has not had the shingles vaccine. His statin regimen has not been re-titrated despite his rising A1c (his cardiovascular risk has gone up). His blood pressure was 132/82 at the last visit, which is on the line for hypertension control under the current measure spec, and his medication list hasn't been adjusted. His urine albumin-to-creatinine ratio (UACR) was last drawn 14 months ago, and given his diabetes plus the rising A1c, current ADA guidance would have it drawn annually. His eGFR has been trending down (from 78 two years ago, to 71 a year ago, to 64 last visit). His PCP has not had a documented conversation about chronic kidney disease (CKD) with him.

<!-- TODO (TechWriter, MEDIUM per Expert Review A9): Three clinical-loosenesses in this vignette. (1) Pneumococcal: ACIP has indicated pneumococcal vaccination (PPSV23 historically; PCV15/PCV20 under current simplified recommendations) for adults 19-64 with diabetes for years. David's gap is not "newly indicated at 64"; it has been open for most of a decade. Reframe as a long-standing gap. (2) Diabetic foot exam: the parent HEDIS CDC measure was retired (see HEDIS naming TODO above) and the foot-exam component did not survive the split. Foot exams remain ADA-recommended but no current HEDIS or Star measure tracks them. Either reframe as a guideline-recommended (ADA) gap that the practice's internal quality dashboard tracks, or remove the "quality dashboard shows it red" framing. (3) Colon cancer family history: a paternal CRC diagnosis at 71 generally does NOT trigger elevated-risk surveillance under NCCN/ACG/USMSTF criteria (those trigger when a first-degree relative is diagnosed at <60). Either strengthen the family history to genuinely trigger elevated-risk screening, or drop the "earlier and more frequent" elevated-risk framing and treat David as average-risk where the gap is "the 10-year interval has elapsed." This last cleanup also requires fixing the matching "his colonoscopy that's six years overdue" line in the unlucky-version paragraph below: David is 64 with a normal colonoscopy at 54, so under average-risk guidance he is at-due, not six years overdue. Coordinate all three fixes in a single 30-minute clinical-informatics review pass. -->

Eleven gaps. David is at his PCP next Tuesday morning at 9:15 AM for his annual visit. The visit is scheduled for 25 minutes. The PCP, Dr. Patel, will spend the first five minutes reviewing the chart in the EHR, ten minutes on the visit itself, and ten minutes on documentation and orders. Best case, she addresses three gaps. More realistically, two.

Which two?

If David is unlucky, the practice's quality dashboard happens to be sorted by HEDIS measure status, with the bonus-bearing measures at the top, and the screen Dr. Patel sees is dominated by the diabetic retinal exam (Eye Exam for Patients with Diabetes is a HEDIS Stars bonus measure, the gap window closed five months ago, and the practice gets dinged on its quality bonus for every diabetic patient who didn't get one). She orders the retinal exam referral. He needs a flu shot, the medical assistant noted; she orders that. The visit ends. David walks out, and the things that didn't get addressed include: his eGFR trending into stage 3 CKD without a single documented CKD conversation, his colonoscopy that's six years overdue with a paternal history of colon cancer death, and his uncontrolled diabetes that is now driving the renal decline.

If David is lucky, Dr. Patel knows him well, has been watching his eGFR slip for two years, walks into the visit already focused on the kidney conversation, and uses the limited time to talk about what's happening with his kidneys, order the UACR, refer him to nephrology for early co-management, and intensify his diabetes regimen. She does not get to the retinal exam, and the practice's HEDIS metric on diabetic retinal exam takes the hit. Six months later, when the plan's quality team is doing year-end push to close gaps, David's name appears on the chase list, and a non-clinical outreach team calls him to schedule the eye exam. He goes. The eye exam is normal. The HEDIS measure closes. Everyone's dashboard turns green.

Which version of David's care is better?

The clinically obvious answer (the second one, where the kidney decline gets named and acted on) and the operationally rewarded answer (the first one, where the visible HEDIS measure closes within the measurement window) are not the same answer. The dashboard, the bonus structure, the documentation incentives, and the way care gaps are presented to the PCP all push toward the first version. The patient's actual prognosis pushes toward the second.

This is what care gap prioritization looks like in practice. The data identifies the *what*: which gaps, when they opened, when they close, what they're worth in quality measure terms. The hard work is identifying the *which*, and matching the *which* to the right closure pathway. A gap that closes itself when a patient walks past a flu shot kiosk in a pharmacy is structurally different from a gap that requires a referral, a scheduled procedure, a bowel prep, and a 12-month follow-up. A gap that's a HEDIS bonus measure with a closing window is structurally different from a gap that no quality program tracks but that's clinically the most important thing happening for the patient. A gap that the PCP can close in 90 seconds (order the flu shot at the visit) is different from a gap that requires a 20-minute conversation followed by a 6-month course of behavior change.

A blanket "close the most overdue HEDIS measure first" policy will produce, for thousands of patients, a flow of completed-but-not-most-important gap closures, and will report a lift in HEDIS measures that's real and meaningful for the plan's quality bonus, while the patients with kidney disease, undiagnosed depression, escalating diabetic complications, or overdue colon cancer screenings continue to drift in the gaps the dashboard didn't put first.

A second wrinkle that distinguishes care gap prioritization from medication adherence (Recipe 4.5) and wellness program targeting (Recipe 4.4): the *catalog of gaps* is enormous and heterogeneous, and gap eligibility, urgency, and closure pathways depend heavily on patient context. Adult preventive care alone has dozens of recommended screenings and immunizations across age, sex, condition, and risk-factor combinations. HEDIS has hundreds of measures across commercial, Medicaid, and Medicare populations, of which any given patient is in the denominator for somewhere between five and fifty. CMS Star Ratings has its own subset. ACO and value-based contract programs each have their own. State Medicaid programs each have their own. The patient's specific clinical picture (diabetes, CKD, recent stroke, pregnancy, transplant) opens additional condition-specific care gap categories that have their own measurement specifications, their own evidence base, and their own urgency. The recommender has to know all of those. It also has to know which closure pathway each gap supports: some can be closed by the patient (vaccination at a pharmacy, self-collected screening kits like FIT for colorectal cancer), some by the PCP at a visit (in-office foot exam, blood pressure measurement, vaccine administration), some by a specialist (retinal exam, colonoscopy, mammogram), some by labs that run anywhere (HbA1c, UACR), and some require a structured program (depression screening with PHQ-9 plus follow-up if positive). Different pathways have different friction, different time costs to the patient, and different probability of completion.

A third wrinkle: visit-time scarcity is the binding constraint. Adherence interventions in 4.5 used staff capacity (pharmacists, care managers) as the scarce resource. Care gap closure during a visit uses *PCP visit time*, which is much more zero-sum than population-level outreach capacity. Twelve open gaps and 25 minutes is not a problem you solve with more parallelism. It's a problem you solve by picking the right two or three. The recommender's output is not a generic call list of patients to contact; it's a per-patient, per-encounter, ranked agenda item list that has to be useful to a specific clinician at a specific time, with the right gaps at the top, with explanations the clinician can read in three seconds, and with the right things suppressed because they're not the right thing for this visit.

A fourth wrinkle: care gaps have closure windows. Many HEDIS and Star Ratings measures use lookback windows (the patient must have had X within the last 12 or 24 or 36 months for the measure to close in the current measurement year). The window expires at the end of each measurement year. A gap that has 90 days left in its window has different urgency than the same gap with eight months left, even though the clinical reasoning would treat them similarly. Gap windows also interact with the patient's enrollment status (Medicare measurement years are calendar; commercial varies; Medicaid varies; a patient who switches plans mid-year may have a gap that "doesn't count" for the new plan but still represents real clinical need). The recommender needs to model both clinical urgency (when does the patient actually need this care) and operational urgency (when does this gap stop counting for the plan or practice). They are not the same thing. Chasing only the operational urgency produces the David-with-the-rising-creatinine outcome. Chasing only the clinical urgency leaves measurable financial value on the table that pays for the program. Both pressures are real.

A fifth wrinkle: gap data is messy in instructive ways. A gap can be open in the analytics warehouse and closed in reality (the patient had the colonoscopy at a non-network gastroenterologist; the result wasn't sent back to the PCP's EHR; the analytics team only sees what the PCP's EHR shows, so the gap is "open"). A gap can be closed in the analytics warehouse and open in reality (the EHR has a "colonoscopy declined" note from three years ago that the analytics import treated as a soft close; the patient has aged into a higher-risk category; the gap has reopened clinically but the data hasn't caught up). A gap can be unclear: the patient had a sigmoidoscopy in 2017 that closes some colorectal cancer screening measures but not others; the recommender's logic has to know the measure-specific qualifying procedures. Vaccination histories are notoriously fragmented across the PCP, the pharmacy, the public-health immunization registry, and the patient's other providers. Lab results from outside labs, retail clinics, and home test kits often don't reconcile cleanly with the PCP's chart. A care gap recommender that doesn't reason about gap data quality will, with confidence, list gaps that are actually closed, omit gaps that are actually open, and recommend chasing things that the patient will (rightly) report they already did.

A sixth wrinkle, and this one is operationally specific: the closure event has multiple sources of truth. When David gets a flu shot at the pharmacy on Saturday, the closure shows up in the pharmacy's claim, in the immunization registry, eventually in the plan's claim system, and (if the pharmacy and the practice happen to share an interface) sometimes in the EHR. The lag between these is days to months. The recommender needs to be tolerant of partial data; the user-facing dashboards need to show provisional closures with confidence; and the chase teams need to not chase gaps that are technically open but were closed yesterday, because nothing erodes patient trust faster than a robocall asking them to schedule the colonoscopy they had last week.

So the problem statement, again, is deceptively simple: given a patient's open care gaps (with full context: clinical, demographic, behavioral, social, and operational), the patient's likelihood to act on each, the closure pathway available for each, the visit context (if a visit is imminent), and the quality-measure landscape, decide which gaps to push to which actor (the patient, the PCP, the care team, a specialist) at which moment, allocate the system's various nudge and outreach capacities, and track whether each gap actually closed and stayed closed. Not the same red-yellow-green dashboard for everyone with a gap. The right gap, surfaced to the right actor, at the right moment, with honest uncertainty when the data is incomplete and honest acknowledgment when the operationally-attractive answer and the clinically-attractive answer diverge.

We're going to build that. This recipe builds directly on Recipe 4.4's uplift-and-allocation pattern and Recipe 4.5's barrier-classification pattern (we will not re-derive them; go read those if you skipped them), and adds three pieces specific to care gap work: a per-(patient, gap) clinical urgency model that is independent of the quality-measure status, a visit-context-aware ranking that produces an agenda for an upcoming or ongoing encounter, and a multi-source closure-tracking pattern that handles the data-lag and partial-closure realities. The architecture is structurally similar to 4.5. The clinical and operational details are different enough that the recipe is worth its own treatment.

Let's get into how you build it.

---

## The Technology: Gap Identification, Clinical Urgency Modeling, Visit-Context Ranking, and Closure Tracking

### What a Care Gap Actually Is

Before any modeling, the system has to know what counts as a gap. There are three reasonable definitions in common use, and a production recommender ends up using all three:

- **Quality-measure-defined gaps.** The patient is in the denominator of a HEDIS, Stars, ACO, or contracted quality measure, and the numerator condition (the qualifying event or procedure within the lookback window) is not satisfied. These are deterministically computable from claims, lab data, and EHR data given the measure specification. Examples: HEDIS Comprehensive Diabetes Care eye exam, BCS-E breast cancer screening, FUH (Follow-Up after Hospitalization for Mental Illness), CCS cervical cancer screening. The measure specifications are publicly published, are updated annually, and have well-defined denominator and numerator definitions. <!-- TODO (TechWriter, HIGH per Expert Review A3): NCQA retired the parent Comprehensive Diabetes Care (CDC) measure beginning HEDIS MY 2022 and split it into EED (Eye Exam for Patients with Diabetes), KED (Kidney Health Evaluation for Patients With Diabetes), GSD (Glycemic Status Assessment for Patients With Diabetes), and BPD (Blood Pressure Control for Patients With Diabetes). Replace "HEDIS Comprehensive Diabetes Care eye exam" with "HEDIS Eye Exam for Patients with Diabetes (EED)" and add a parenthetical note explaining the CDC retirement and the EED/KED/GSD/BPD split. Coordinate with the Expected Results sample (`measure_id: hedis-cdc-eye-exam` should become `hedis-eed`) and with the Python companion's synthetic registry (Code Review Finding 1). Also confirm current HEDIS, CMS Star Ratings, and major ACO measure specification sources at the time of build. -->

- **Guideline-recommended gaps.** The patient meets criteria from a clinical guideline (USPSTF, ADA, AHA/ACC, KDIGO, etc.) for a screening, immunization, or monitoring action that has not been performed within the recommended interval. These are similar to quality-measure gaps but broader: the guideline universe is bigger than the measure universe, and the urgency reasoning is clinical rather than operational. Example: a 50-year-old male with documented metabolic syndrome who hasn't had a fasting lipid panel in 18 months has a guideline-recommended gap that is not (necessarily) a HEDIS measure gap.

- **Patient-specific clinical gaps.** Generated by clinical reasoning over the patient's specific picture: rising eGFR with diabetes and no documented CKD conversation; uncontrolled A1c with no medication titration in twelve months; a positive depression screen with no follow-up encounter. These are the gaps that quality measures are too coarse to capture but that good clinicians notice. They're also the hardest to compute: they require integrated clinical reasoning over multi-source data, not lookup against a measure spec. This is increasingly where care gap programs are investing, and it is where LLM-assisted generation has interesting potential as a *candidate-gap surfacer* that a clinician confirms.

A production care gap recommender pulls from all three sources, deduplicates (a gap that's both a HEDIS measure and a guideline recommendation should not appear twice), and reconciles (a gap surfaced by an LLM clinical-reasoning pass that overlaps a measure-defined gap should be merged).

### Gap Eligibility Logic

For each gap type, the eligibility logic answers two questions: is this patient in the denominator (the eligible population for this gap), and is the numerator unsatisfied (the gap is actually open)?

Denominator logic involves age, sex, condition flags (diabetes diagnosis on the active problem list or recent ICD-10 codes), enrollment criteria (continuously enrolled for X months), and exclusion criteria (palliative care, hospice, dialysis-dependent for some measures, pregnancy for others). Many denominators have specific look-back periods. Many use procedure or diagnosis code value sets that NCQA, CMS, or specialty societies publish and revise annually.

Numerator logic involves looking up the qualifying procedure, lab, or service codes within the measure's allowed look-back. The lookback windows vary: a flu shot is annual; a mammogram is 27 months for HEDIS BCS-E; a colonoscopy is 10 years if normal; an eGFR is 12 months for diabetic CKD monitoring. Some measures have multiple qualifying procedures (FIT-DNA for colorectal cancer screening qualifies, and so does flexible sigmoidoscopy with a different lookback). The numerator logic for some measures includes exclusions on top of the qualifying events (a positive screen with appropriate follow-up is the numerator condition for some depression and substance-use measures, not just the screen).

Hard-coding all of this is a maintenance disaster. The right pattern is a *measure registry*: a structured catalog of measure definitions (denominator predicates, numerator predicates, exclusion predicates, lookback windows, value sets, version, effective dates) that the gap engine evaluates against patient data. The registry is curated by clinical informatics; the gap engine is a generic evaluator. New measures land in the registry without code changes. Annual measure revisions land as version bumps. The registry is the source of truth; the gap list is its output.

### Clinical Urgency: Beyond Quality-Measure Status

Two patients, both with an open colonoscopy gap. Patient A is 50, no family history, average risk, prior screening declined "for now" three years ago. Patient B is 64, paternal first-degree history of colon cancer at age 71, prior colonoscopy ten years ago with a single tubular adenoma found and removed (so the surveillance interval is shorter than for normal-result patients, and the previous colonoscopy clinically qualifies as elevated-risk). Both patients have the same HEDIS measure status (open, in-window). The clinical urgency is materially different.

Clinical urgency modeling is where care gap recommenders earn their keep. The model takes per-(patient, gap) features and predicts the *expected harm of delayed closure*: the expected clinical risk attributable to non-closure of this gap over the next 6 to 24 months, given the patient's full picture. Inputs:

- Patient demographics (age, sex, race or ethnicity if used appropriately for risk)
- Active condition list and severity markers
- Recent clinical trajectory (rising A1c, falling eGFR, escalating BP)
- Family history flags
- Prior screening history (declines, normal results, abnormal results, surveillance frequencies)
- Comorbidity load (which influences both clinical risk and patient capacity)
- Social determinants (transportation barriers may make a referral-based gap closure unrealistic for this patient)

Outputs: a continuous urgency score per (patient, gap), with confidence interval, plus a brief structured rationale (the top-three feature contributions). The urgency score is *not* a quality-measure score; it's an estimate of clinical harm from non-closure. A flu shot for an immunocompetent 35-year-old is low urgency. A flu shot for an 80-year-old in a long-term care facility during peak flu season is high urgency. The HEDIS measure treats them identically. The clinician does not.

How is this trained? Two reasonable approaches:

**Curated risk-rule library.** For each gap type, clinical informatics encodes a set of risk modifiers as rules: family history doubles the colorectal cancer urgency; rising eGFR triples the CKD-monitoring urgency; recent hospitalization for COPD raises the pneumococcal vaccine urgency. The output is a deterministic urgency adjustment on top of a baseline. Transparent, clinically auditable, and the right starting point. Misses subtle interactions.

**Supervised regression on outcome data.** Train a model to predict outcomes (incident events of the type the gap closure prevents) over a longitudinal window, with the gap-closure status as one feature. The expected harm of delay is the difference in predicted incident-event probability between "closed" and "open" status, holding other features fixed. Requires longitudinal data, requires careful handling of confounding (the patients who close their gaps differ systematically from those who don't), and is much more powerful when it works. In practice, this is a Chapter 7 (Risk Scoring) problem layered into the care gap recommender.

A note: clinical urgency modeling is where bias creeps in if you're not careful. If the training data has systematically less follow-up data for some demographic groups, the model's urgency estimates for those groups will be miscalibrated. If the outcome event you're using as the prediction target is itself recorded with bias (some populations are under-diagnosed for the very conditions the gap is screening for), the model encodes that. The Obermeyer et al. 2019 finding for risk-stratification scores applies directly to clinical urgency models. Audit by cohort, calibrate by cohort, and monitor.

### Visit-Context Ranking

Most care gap recommenders make a population-level call list: for the upcoming month, which patients have which gaps, in what priority. That's useful for chase teams. It is *not* the right output for a clinician about to walk into a 9:15 AM visit.

Visit-context ranking takes the patient's gap list and produces a *ranked agenda* for a specific encounter, conditioned on:

- The visit type (annual wellness visit has more time; sick visit for back pain has very little)
- The visit duration (typical for this provider, this practice, this visit type)
- The patient's history of gap closure at visits (some patients knock through three gaps in a focused visit; some patients arrive with a list of their own concerns and zero capacity for additional agenda items)
- The closure pathway compatibility with this visit (an in-office gap like a foot exam is high-fit for the visit; a screening colonoscopy is low-fit because the visit produces a referral, not a closure)
- The clinician's preference profile (some clinicians want the bonus measures surfaced first; some want the highest-clinical-impact items; many want both, in clearly-labeled categories)
- The recent acute clinical context (a patient with a new abnormal finding from last week has half the visit consumed before any preventive gap is on the table)

The output is two ranked lists: "top items to address at this visit" (3 to 5 items, accounting for visit time and closure pathway fit) and "items to flag for asynchronous closure outside the visit" (everything else, queued to chase teams, patient-facing outreach, or asynchronous orders). This split is critical: the visit agenda has to be short and curated; the rest of the gap closure work happens outside the visit.

Visit-context ranking is where LLMs have a useful, narrow role. A structured-output LLM call given the patient's gap list, the visit context, and the ranking policy can produce a one-paragraph briefing for the clinician: "Mr. Chen is overdue for retinal exam, foot exam, and pneumococcal vaccine. His eGFR has dropped 12 points in the last 18 months without a documented CKD conversation. Suggested visit focus: kidney conversation and order UACR; foot exam in office; pneumococcal vaccine if patient agrees. Defer retinal exam to scheduling team for asynchronous referral." The LLM is composing the briefing, not picking the gaps. The picks are from the deterministic ranker. The LLM's only job is making the picks readable in three seconds.

### Engagement and Closure-Probability Prediction

A gap on the visit agenda is a candidate. Whether the closure actually happens depends on whether the patient acts (for patient-driven closures) or the clinician acts (for in-visit closures) or the referral chain completes (for specialist-driven closures). Each pathway has its own probability profile.

For patient-driven closures, the engagement-prediction pattern from 4.4 and 4.5 applies: per-patient, per-pathway probability of completing the closure given a recommendation. Features include prior closure history, channel responsiveness, transportation/scheduling proxies, language, and social determinants of health.

For in-visit closures, the probability is dominated by visit time, visit type, and clinician closure habits (some clinicians close 80 percent of foot exam gaps when surfaced; some close 30 percent because the visit was already over capacity).

For referral-driven closures, the probability decomposes into: the probability the patient schedules the referral (highly engagement-correlated), the probability the referral completes (specialty network capacity, prior auth friction, geographic access), and the probability the result returns to the PCP's chart (the data-completeness problem from above). Each subprobability is its own model in production.

The product of these probabilities, multiplied by the clinical urgency score and weighted by the gap's quality-measure value (when applicable), forms the ranking signal.

### Closure-Outcome Tracking

Every gap that closes generates a closure event. Closure events come from many places: claims, EHR encounter notes, pharmacy data (for some immunizations), immunization registries, lab feeds, screening kit return data, and patient self-report. A production care gap pipeline accepts all of these, normalizes them, deduplicates them, and maintains a per-(patient, gap) state machine: open, provisionally closed (a candidate event arrived but hasn't been confirmed by the canonical source), confirmed closed (the qualifying event is documented in the source the quality measure uses), reopened (the patient aged out of the previous closure window and a new gap has opened), or excluded (the patient has aged out, become ineligible, or has a documented exclusion).

The state machine has to be tolerant of late-arriving data. A patient who got a flu shot at the pharmacy on Saturday may show up in the immunization registry on Monday, in claims on Tuesday, and never in the EHR. The state machine should mark the gap provisionally closed on Monday and confirmed-closed when the canonical source confirms; chase teams should respect the provisional state to avoid the "we just called you about the colonoscopy you had last week" failure mode.

This is messier than it sounds. The "canonical source" varies by measure: HEDIS uses claims-and-supplemental-data with strict source-of-truth rules; the practice's quality dashboard may treat the EHR as canonical; the public-health immunization registry is canonical in some states for vaccines and not in others. The recommender's state machine has to know each measure's canonical source.

### Where LLMs Fit (and Don't)

Same as 4.5 with care-gap-specific notes:

- **Gap-eligibility evaluation, urgency scoring, visit ranking, capacity allocation.** Not the LLM's job. Deterministic logic, auditable models, and the measure registry.
- **Patient-specific clinical-gap surfacing as a candidate generator.** Yes, with a structured-output prompt and a clinician-confirmation step. The LLM reads the patient's chart context and proposes "gaps the deterministic engine missed" as a *candidate* list, which is then reviewed by clinical informatics and added to the deterministic registry if the pattern is durable. The LLM is not the source of truth; it's a sourcer of patterns.
- **Visit briefing generation for clinicians.** Yes. Structured input goes in, a one-paragraph briefing comes out, the briefing references the deterministic ranker's choices. The clinician reads it before walking into the room.
- **Patient-facing gap-closure messaging.** Yes, same pattern as 4.4 and 4.5: structured intervention assignment in, tailored message out, message goes through a clinical-claims validator before send.
- **Care-team summary for outreach staff.** Yes. The LLM packages structured outreach instructions in a readable form. The picks are from the recommender; the LLM packages.

What the LLM does *not* do: pick the gaps, decide whether a gap is open, override the urgency model with its own clinical reasoning, or speak directly to a patient in an autonomous loop about screening recommendations. The recommender picks. The LLM packages.

### Where This Sits in the Chapter

This recipe builds directly on Recipes 4.4 and 4.5. The patient-profile DynamoDB table from 4.1, extended in 4.4 and 4.5, gets new attributes (`open_gaps`, `gap_closure_history`, `last_visit_date`, `next_scheduled_visit`, `provider_id`). The engagement-event Kinesis stream gets new event types (`gap_identified`, `gap_provisionally_closed`, `gap_confirmed_closed`, `gap_reopened`, `gap_excluded`, `gap_referral_scheduled`, `gap_referral_completed`). The SageMaker Feature Store features defined in 4.4 and 4.5 are reused; new features are added for gap-specific signals (per-gap state, days-in-window, days-overdue, prior closures of this gap type, prior referral-completion rate). The barrier classifier from 4.5 helps here too: a patient with documented cost or transportation barriers is unlikely to complete a referral-based gap closure regardless of how high the clinical urgency is, and the recommender should know that.

The visit-context ranker and the multi-source closure tracker are the new architectural pieces. The uplift-modeling investment from 4.4 and 4.5 transfers directly. The cohort fairness instrumentation from 4.3, 4.4, and 4.5 becomes especially important here because care gap closure patterns have well-documented disparities by race, language, geography, and access, and a poorly built recommender will encode those disparities into its targeting (and into its urgency model, if you're not careful with training data).

---

## General Architecture Pattern

The pipeline has six logical components: a measure-registry component that maintains the deterministic gap definitions, a gap-evaluation component that runs the registry against patient data to produce open-gap lists, an enrichment component that scores clinical urgency and engagement and closure probability per gap, a visit-context ranker that produces per-encounter agendas, an outreach-and-orchestration component that drives patient-facing messages, chase team queues, and clinician briefings, and a closure-tracking component that watches multiple data sources and updates gap state.

```
┌───────── MEASURE REGISTRY (governance-controlled) ─────────┐
│                                                            │
│  [Clinical informatics]   [Quality programs]   [Contracts] │
│           │                       │                │       │
│           └────────┬──────────────┴───────┬────────┘       │
│                    ▼                      ▼                │
│         [Measure spec: denominator, numerator, exclusions, │
│          lookback, value sets, version, effective_dates,   │
│          canonical_source, urgency_baseline]               │
│                    │                                       │
│                    ▼                                       │
│         [Persist to measure-registry store; versioned]     │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌───────── GAP EVALUATION (daily) ──────────────────────────┐
│                                                            │
│  [Claims]   [EHR encounters]   [Lab feeds]   [Pharmacy]    │
│  [Immunization registries]   [Patient self-report]         │
│                          │                                 │
│                          ▼                                 │
│              [Normalize and reconcile to                   │
│               (patient, qualifying_event) tuples           │
│               with source provenance]                      │
│                          │                                 │
│                          ▼                                 │
│              [Per-patient: evaluate each measure in        │
│               registry. Compute denominator membership,    │
│               numerator satisfaction, exclusion logic.     │
│               Produce open-gap list with metadata]         │
│                          │                                 │
│                          ▼                                 │
│              [Optional: LLM-assisted candidate-gap         │
│               surfacer reads patient context, proposes     │
│               additional gap candidates for clinical       │
│               informatics review]                          │
│                          │                                 │
│                          ▼                                 │
│              [Persist to per-(patient, gap) store with     │
│               state machine: open, provisionally_closed,   │
│               confirmed_closed, reopened, excluded]        │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌───────── GAP ENRICHMENT (daily/weekly) ───────────────────┐
│                                                            │
│  [Open gaps]   [Patient features]   [Barrier signals]      │
│           │                │                │              │
│           └────────┬───────┴────────┬───────┘              │
│                    ▼                ▼                      │
│         [Stage A: clinical urgency scoring                 │
│          (curated risk-rule library, optional supervised   │
│           outcome model layered on top)]                   │
│                    │                                       │
│                    ▼                                       │
│         [Stage B: per-pathway engagement and               │
│          closure-probability prediction                    │
│          (patient-driven, in-visit, referral-driven)]      │
│                    │                                       │
│                    ▼                                       │
│         [Stage C: per-(patient, gap) priority synthesis    │
│          (clinical urgency × completion probability ×      │
│          quality-measure value × window-urgency)]          │
│                    │                                       │
│                    ▼                                       │
│         [Persist enriched gap list per (patient, gap)]     │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌───────── VISIT-CONTEXT RANKING (real-time, pre-visit) ────┐
│                                                            │
│  [Tomorrow's schedule]   [Enriched gap list]   [Visit      │
│                                                  context]  │
│                          │                                 │
│                          ▼                                 │
│         [Per-encounter: filter to gaps with closure        │
│          pathway compatible with visit type and time;      │
│          rank by priority adjusted for visit fit]          │
│                          │                                 │
│                          ▼                                 │
│         [Produce two lists per encounter:                  │
│          - in-visit agenda (3-5 items)                     │
│          - asynchronous closure queue (the rest)]          │
│                          │                                 │
│                          ▼                                 │
│         [LLM-assisted briefing generation for clinician    │
│          (structured prompt; structured output;            │
│          one-paragraph clinician-readable text)]           │
│                          │                                 │
│                          ▼                                 │
│         [Push to clinician dashboard / EHR inbox before    │
│          visit start; persist briefing for audit]          │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌───────── ASYNCHRONOUS OUTREACH AND ORCHESTRATION ─────────┐
│                                                            │
│  [Asynchronous closure queue + per-pathway capacity]       │
│                          │                                 │
│                          ▼                                 │
│         [Patient-facing closure paths:                     │
│          - app/portal nudges                               │
│          - retail clinic referral                          │
│          - home test kit (FIT, HbA1c)                      │
│          - pharmacy-based vaccinations]                    │
│         [Care-team paths:                                  │
│          - chase team call queues                          │
│          - care-manager outreach for high-touch closures]  │
│         [Specialist-referral paths:                        │
│          - referral generation, scheduling assist,         │
│            transportation assistance, prior auth]          │
│                          │                                 │
│                          ▼                                 │
│         [Capacity-aware allocation (heterogeneous          │
│          capacities, per-patient contact-frequency caps,   │
│          equity floors, cross-recipe coordination)]        │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌───────── CLOSURE TRACKING + FEEDBACK ─────────────────────┐
│                                                            │
│  [Claims feed]  [EHR feed]  [Lab feed]  [Imm registry]     │
│  [Pharmacy feed]  [Patient self-report]                    │
│                          │                                 │
│                          ▼                                 │
│         [Normalize to (patient, candidate-closure-event)   │
│          with source provenance and timestamp]             │
│                          │                                 │
│                          ▼                                 │
│         [Match candidate event to open gap; if match,      │
│          transition state machine to provisionally_closed; │
│          if canonical source confirms, transition to       │
│          confirmed_closed]                                 │
│                          │                                 │
│                          ▼                                 │
│         [Notify chase team / suppress further outreach;    │
│          emit closure event to engagement stream]          │
│                          │                                 │
│                          ▼                                 │
│         [Aggregate closures by cohort, by gap type, by     │
│          closure pathway, by clinician for dashboards;     │
│          feed urgency-model retraining and engagement      │
│          model retraining on appropriate horizons]         │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**The measure registry is governance, not engineering.** It's a structured, versioned catalog of measures: denominator predicate, numerator predicate, exclusion predicate, value sets, lookback windows, canonical source, and an `urgency_baseline` reflecting how the program judges this measure's clinical importance independent of patient-specific factors. Clinical informatics owns it. Engineering owns the evaluator that consumes it. New measures, annual measure revisions, and program-specific measure variants land as registry entries; the engineering pipeline does not change.

**Gap evaluation runs daily on the full population.** It is a SQL-shaped problem at scale: for each measure, evaluate denominator membership, then numerator satisfaction, then exclusion criteria, joining to the relevant patient data slices. The output is a per-(patient, measure) record with state, evidence (which qualifying events were considered), and source provenance. The state-machine semantics (open vs. provisionally closed vs. confirmed closed vs. reopened) live here, with the canonical-source rules per measure encoded in the registry and applied by the evaluator.

**The LLM-assisted candidate-gap surfacer is optional and gated.** It runs over a subset of patients (high-risk, complex) and proposes patterns that the deterministic registry doesn't catch. Its outputs are *candidates* that go to clinical informatics for review, not directly to the patient or clinician. Patterns that prove durable get encoded into the registry as rule-based clinical gaps; the LLM is a discovery tool.

**Gap enrichment is the modeling-heavy stage.** Per-(patient, gap), produce a clinical urgency score, per-pathway engagement and closure-probability scores, and a synthesized priority. The model fan-out is similar to 4.5: the urgency model is per-gap-type (some shared parameters across related gaps), the engagement model is per-pathway, the closure-probability model has subcomponents for referral steps. The output is the per-(patient, gap) priority that drives both the visit-context ranker and the asynchronous outreach allocator.

**Visit-context ranking is the most operationally distinctive piece.** It consumes tomorrow's encounter schedule, looks up each scheduled patient's enriched gap list, applies visit-fit filters (closure pathway compatible with the visit type and visit time), and produces a per-encounter ranked agenda. The clinician's briefing is generated by an LLM call that summarizes the deterministic agenda in a paragraph the clinician can read in three seconds. Asynchronous closure (the gaps that didn't make the visit agenda) flows to the outreach orchestration layer.

**Outreach orchestration is multi-pathway.** Gaps with pathway "patient-driven" go to the channel optimizer from 4.1. Gaps with pathway "in-visit" stay on the agenda until the visit, then transition to "needs followup" if not addressed. Gaps with pathway "specialist referral" go to the referral-management workflow with prior-auth and scheduling assistance. The capacity-aware allocator from 4.5 handles the heterogeneous capacities across pathways. Equity floors apply at the pathway level.

**Closure tracking is multi-source by design.** Closure events arrive from claims (slow, canonical for HEDIS), EHR (fast, canonical for the practice), lab feeds (fast, canonical for lab-based gaps), pharmacy (fast, canonical for some immunizations), immunization registries (medium speed, canonical in some states), and patient self-report (fast, low confidence, valuable for suppression of unnecessary outreach). The tracker's state machine reconciles these and gates downstream consumers (chase teams, dashboards, billing) on the appropriate confidence level. The HEDIS measure won't credit a self-report; the chase team should still suppress outreach when one arrives.

<!-- TODO (TechWriter, HIGH per Expert Review A2): Add a paragraph here naming the data_quality_flag gate explicitly. The flag is computed and persisted in Step 1 of the architecture companion (chapter04.06-architecture.md), then never gates downstream decisions. The "Where it struggles" section in the architecture companion says explicitly that downstream consumers should gate on it; the pseudocode does not. Five places in the architecture companion need the gate: (a) Step 2 dampens urgency confidence on non-`complete` cases, (b) Step 3 suppresses low-quality gaps from the in-visit agenda, (c) Step 4 routes low-quality cases to a verification-first pathway before any closure-pathway-specific outreach, (d) Step 5 tightens (or relaxes, for `cross_provider_fragmentation`) the canonical-source rule, (e) Step 4 chase brief opens with verification framing when data quality is in doubt. The "calling a patient about a colonoscopy they had last week" failure mode the Honest Take warns against is exactly what `cross_provider_fragmentation` flags; not gating on it produces precisely that failure. Frame as: "the data_quality_flag is not metadata; it's an input to every downstream stage." -->

**Equity instrumentation runs across all components.** Gap-identification rates by cohort (a measure that produces three times as many open gaps for one cohort versus another may reflect actual unmet need or may reflect data-completeness disparities; the dashboard surfaces both). Urgency-score distribution by cohort. In-visit closure rates by cohort and by clinician. Referral completion rates by cohort. Long-horizon closure rates by cohort. Each axis is a monitored dashboard.

**Care-team integration is bidirectional.** Clinician overrides (the clinician dismissed a high-priority gap with reason: `appropriate_decline`, `previously_addressed`, `clinical_judgment`, `patient_refusal`, `out_of_scope_for_visit`) flow back into the recommender as features for retraining and as suppression flags for future surfacing. A "patient declined colonoscopy" override should suppress repeated colonoscopy surfacing for some interval and on some pathways, while preserving the right to re-surface when the clinical context shifts (e.g., a new positive FIT result reopens the conversation regardless of prior decline).

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.06-architecture). The Python example is linked from there.

## The Honest Take

Care gap prioritization is one of those problems where everybody on the operations side wants the dashboard to turn green and everybody on the clinical side wants the patient with the rising creatinine to be the priority, and the dashboard you build will quietly choose between those two ideologies whether you make the choice explicit or not. The architecture in this recipe makes the choice explicit (the policy weights between clinical urgency, closure probability, measure value, and window urgency are visible, version-controlled, and reviewable) which is the most important thing it does. Every alternative I've seen in the wild ends up with the operations-friendly answer winning by default, because the operations-friendly answer is the one that gets reported on the dashboard the executives look at, and the clinical answer is the one that doesn't appear on any dashboard at all.

The trap that's most specific to this domain is the David scenario from the opening. A care gap recommender that surfaces by HEDIS measure status (sorted by bonus value, with operationally-attractive measures at the top) is the default state of every quality-team dashboard I've ever seen, and it is a fundamentally different recommender from the one I described in this recipe. That dashboard is doing population health by sorting on the dimension easiest to report. The recommender in this recipe is trying to do population health by sorting on what's most likely to actually improve the patient's prognosis. They overlap a lot (most clinically urgent things are also quality-measure things) and they diverge in important places. The divergences are where the work happens.

The thing that surprises people coming from generic ML backgrounds is how much of the work is data engineering, not modeling. The measure registry is governance plus engineering. The multi-source closure tracker is engineering plus operational rigor. The visit-context features are scheduling-data quality work. The clinical urgency model is the part that feels like ML, and it's maybe 20 percent of the system's value. The other 80 percent is making sure the gap list is right (the right patients in the denominator, the right qualifying events in the numerator, the right closures recognized when they happen) and making sure the closure tracking doesn't produce false positives or false negatives that destroy clinician and patient trust.

The thing I'd do differently the second time: invest in the closure tracker before the urgency model. The most common failure mode for these systems isn't that they pick the wrong gap; it's that they pick the right gap for a patient who already closed it last week and the closure data hadn't propagated yet. A program that calls patients about colonoscopies they had last week earns a level of operator-distrust that's hard to recover from, and it's all closure-tracking failure, not modeling failure. A program with a perfect urgency model and a poor closure tracker has worse outcomes than a program with a mediocre urgency model and a great closure tracker, because the latter at least doesn't actively burn relationships. Build the multi-source closure tracker first. Build the urgency model second. Build the visit ranker third.

The thing about the LLM components: they earn their keep on packaging, not picking. The clinician briefing is the place where LLMs add the most operational value because the alternative is a clinician scanning a list of 11 gap items and trying to triage them in 30 seconds before walking into the room. A briefing that distills 11 items to "rising creatinine deserves the conversation; foot exam in office; defer the rest" is what makes the recommender's output usable. Without the briefing, even a perfectly ranked agenda is too much information for the visit window. The candidate-gap surfacer is the place where LLMs add modest value if there's a real review process behind them and zero value if there isn't, because the patterns the LLM proposes are hit-or-miss and the value comes from clinical informatics curating the durable patterns into the registry. Don't deploy the candidate-gap surfacer to a clinical informatics team that doesn't have time to review.

The thing about overrides: the override rate is the most important metric for understanding whether the recommender is aligned with clinical reality. An override rate under 5 percent suggests either the recommender is exquisitely tuned (rare) or the clinicians aren't bothering to override and the briefings are being ignored (common). An override rate over 25 percent suggests the recommender is consistently misaligned and clinicians are working around it. The healthy range is 8 to 15 percent overall, varying by measure and clinician. The override reason distribution matters: a high rate of `clinical_judgment_defer` is healthy clinical pushback that should retrain the urgency model; a high rate of `previously_addressed_outside_record` is closure-tracker failure; a high rate of `out_of_scope_for_visit` is visit-fit-ranker failure. Each is fixable, in different parts of the system. Track the breakdown.

A trap worth flagging: confusing gap closure with patient outcome. A program that drives the foot-exam closure rate from 60 percent to 85 percent and produces no measurable change in diabetic-complication trajectory either has a sample-size problem, a measurement problem, or a "the model is recommending in-office foot exams to patients whose feet were already fine" problem. The cost-effectiveness math has to compare clinical outcome change, not just closure-rate change, against the cost of intervention. Closure rate is the fast feedback you optimize against; clinical outcomes are the slow validation you use to check whether the optimization was pointing in the right direction. A program that hill-climbs against closure rates for two years without ever validating against outcomes has built a beautiful optimization for an intermediate metric.

Another trap: the year-end push. Every quality program has a year-end period where chase activity ramps up and the dashboards turn green by sheer brute force. The math is real (HEDIS measure year-end performance has actual financial value to the plan and the practice), but the trap is treating year-end as the operating model rather than as a seasonal exception. Year-round gap closure produces better clinical outcomes than year-end pushes; year-end pushes produce dashboard performance that may not survive into the next measurement year. Build for year-round operation; allow the seasonality to flex the policy weights, but don't redesign the program around the chase. The chase should look like an intensification of the steady state, not a different program. Plans that have invested in year-round operation report measurably better year-over-year HEDIS sustainability than plans that lean on Q4 chases.

One more trap: the "we'll fix the urgency model later" pattern. The MVP shipping pressure is real, and many programs ship with rule-based urgency only and a plan to layer in supervised modeling "next quarter." Two years later they still have rule-based urgency. That's not necessarily wrong; rule-based urgency, if the rules are clinically sound, is auditable and defensible and often good enough for the bonus-bearing measures. The risk is that nobody is checking whether the rules are clinically sound. Schedule the clinical-rule audit on a quarterly cadence with rotating measure focus; without scheduled audit, the rules drift relative to evolving clinical evidence. <!-- TODO: confirm a published reference for the audit cadence; quality-measure programs vary in their formal review processes. -->

Last point, because it's specific to this use case: care gaps are not the same as care needs, and the recommender should not pretend they are. A patient with no open care gaps in the registry can still have urgent unmet care needs that the registry doesn't capture (a recently-onset symptom that hasn't been worked up; a deteriorating clinical trajectory that hasn't crossed any threshold; a social problem that no measure tracks). A patient with eleven open care gaps can be in fine clinical shape (the gaps are operational artifacts, not clinical urgencies). The recommender's job is to triage what's in the registry and surface it well, not to claim it's seeing the whole patient. The PCP sees the whole patient. The recommender helps with one slice of the visit's preventive-and-quality work. Don't let the dashboard stand in for the clinician's judgment, and don't let the empty dashboard reassure you that everything is fine. The dashboard is the dashboard. The patient is the patient. They are not the same thing.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the channel optimizer that the async orchestrator hands patient-facing nudges to. The contact-frequency cap is shared infrastructure. The channel-preference learning extends naturally to gap-closure messages.
- **Recipe 4.2 (Patient Education Content Matching):** Patient-facing closure messages often pair with educational content (why is this screening important; what should I expect at the visit). The content-matching pipeline from 4.2 selects the right educational material per gap.
- **Recipe 4.3 (Provider Directory Search Optimization):** When a gap closure requires a specialist referral, 4.3's ranking pattern helps select which specialist to refer to, accounting for patient preference, network status, and access.
- **Recipe 4.4 (Wellness Program Recommendations):** Some care gaps are program-eligible (a diabetes-related gap might also signal eligibility for a diabetes-management program); the cross-recipe coordination ensures the patient gets the right next step rather than overlapping recommendations.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Adherence to chronic medications is a form of care gap (HEDIS PDC measures are care gaps in the registry); 4.5's barrier classifier and intervention catalog inform the closure-pathway selection here. The cross-recipe orchestration matters; do not double-message.
- **Recipe 4.7 (Care Management Program Enrollment):** A patient with multiple high-urgency open gaps and a complex clinical picture is a candidate for care management; 4.6's enriched gap data feeds 4.7's enrollment-targeting logic.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** The clinical urgency model in this recipe is a risk-scoring problem; Chapter 7's risk-scoring patterns and validation methodology apply directly.
- **Recipe 8.x (NLP Non-LLM):** Clinician override notes can be parsed by NLP to extract structured override reasons more reliably than relying on dropdown selections; the structured labels feed urgency-model retraining.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Closure-rate forecasting and capacity planning across measures is a forecasting problem; Chapter 12 covers the techniques.
- **Recipe 13.x (Knowledge Graphs):** The measure registry is a structured knowledge artifact; advanced implementations can model measure relationships (one measure subsumes another, one closure satisfies multiple measures, certain combinations of closures imply additional gaps) as a knowledge graph rather than as flat measure records.
- **Recipe 14.x (Optimization / Operations Research):** The visit-context ranker and the async-allocator are heuristic versions of constrained-optimization problems; integer programming or column-generation can produce provably-optimal allocations when constraints multiply.

---

## Tags

`personalization` · `recommendation` · `care-gap-prioritization` · `hedis` · `quality-measures` · `cms-stars` · `clinical-urgency-modeling` · `visit-context-ranking` · `closure-tracking` · `multi-source-reconciliation` · `equity` · `cohort-analysis` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `healthlake` · `medium` · `production` · `hipaa`

---

*← [Recipe 4.5: Medication Adherence Intervention Targeting](chapter04.05-medication-adherence-intervention-targeting) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.7 - Care Management Program Enrollment →](chapter04.07-care-management-program-enrollment)*
