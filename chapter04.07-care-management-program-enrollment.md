# Recipe 4.7: Care Management Program Enrollment ⭐⭐⭐

<!--
TechEditor pass v1 (2026-05-16, ch04-r07-edit). Editorial fixes:
- Verified em-dash count: 0 (passes "no em dashes ever" rule).
- Verified en-dash count: 0.
- Header hierarchy: H1 title only, H2 for major sections, H3 for
  subsections, one H4 (#### Walkthrough). No skipped levels.
- Voice drift scan: no documentation-voice openings in body prose, no
  LinkedIn-influencer patterns, no "we are excited" announcements.
  "High-leverage" appears twice (Step 3 pseudocode comment, Variations)
  in the colloquial leverage-point sense (acceptable per Voice
  Reviewer V3 finding, consistent with 4.6 final edit). The Linda
  vignette and the closing "Build the second one" paragraph are
  preserved verbatim per Voice Reviewer V1.
- Vendor balance: 70/30 maintained. The Problem, The Technology, and
  General Architecture Pattern stay vendor-neutral; AWS service names
  appear only in The AWS Implementation, Why This Isn't
  Production-Ready, and Variations.
- RECIPE-GUIDE compliance: all required sections present in correct
  order (Problem, Technology, General Architecture, AWS Implementation,
  Expected Results, Why This Isn't Production-Ready, Honest Take,
  Variations, Related Recipes, Additional Resources, Implementation
  Time, Tags, Footer Navigation).
- Existing TechWriter / prior-editor TODO markers preserved verbatim
  (TCM CPT codes, SageMaker Batch Transform HIPAA, Bedrock service
  terms, SES/Pinpoint scope, HealthLake pricing, Cost Estimate
  validation, validate_briefing four-layer spec, validate_rationale
  spec, model-promotion path, tracking-ID privacy, cross-recipe
  arbitration, SDOH-cohort PHI promotion, DLQ coverage, caseload
  literature citation, predictive-disenrollment literature,
  aws-samples repo confirmation, AWS blog URLs, CMS landing pages,
  NCQA/Care Continuum URL, performance-benchmark range citations,
  briefing social-context reconciliation note from prior editor pass).
- New TODOs added flagging substantive technical concerns rather than
  rewriting (per persona instructions: "do not introduce new claims or
  technical content"; "if a section needs substantial rewriting, flag
  it rather than rewriting"):
  * Expert Review A1 HIGH: cm_outreach_recent_30d_count optimistic
    increment lacks decrement on terminal-unreachable, declined,
    deferred outcomes (added at Step 4 record_outreach_attempt
    pseudocode). Code Review ERROR 2 names the same gap in the
    Python implementation's :zero placeholder.
  * Expert Review A2 HIGH: data_quality_flag is computed in Step 1
    and named in Where It Struggles as a gating signal for the
    disenrollment evaluator, but the disenrollment evaluator
    pseudocode in Step 5 does not gate (added at Step 5
    evaluate_disenrollment).
  * Expert Review A3 HIGH: human_review_pending workflow on
    disenrollment-decisions and cross-program-transitions has no
    SLA, no escalation, no default action; uniquely 4.7-specific
    gap (added at Why This Isn't Production-Ready, in the
    Disenrollment governance and review paragraph).
  * Code Review ERROR 1: ADD state_history :history_event is invalid
    DynamoDB UpdateExpression syntax (ADD supports only Number and
    Set, not List). Pattern propagated chapter-wide. Flagged at the
    pseudocode preamble for Step 1 and at the Why This Isn't
    Production-Ready Idempotency paragraph; the fix is in the
    Python companion file, but a note in the main recipe ensures
    a reader copying the pseudocode pattern does not reproduce the
    bug.
- No code-block language tags changed; the unlabeled fenced blocks
  carry pseudocode and ASCII architecture diagrams per chapter-wide
  convention. Mermaid and JSON blocks are tagged.

TechEditor pass v2 (2026-05-21, ch04-r07-edit). Re-verification of
v1 pass against the editorial checklist:
- Em-dash count: 0 (re-verified). En-dash count: 0 (re-verified).
- Header hierarchy: H1 title only; H2 for major sections (The Problem,
  The Technology, General Architecture Pattern, The AWS Implementation,
  Why This Isn't Production-Ready, The Honest Take, Variations and
  Extensions, Related Recipes, Additional Resources, Estimated
  Implementation Time, Tags); H3 for subsections inside The Technology
  and The AWS Implementation; one H4 (Walkthrough). No skipped levels.
- All four HIGH/ERROR finding TODOs confirmed present with their
  finding IDs on the same TODO line so the follow-up task generator
  can track them: A1 at the record_outreach_attempt pseudocode block,
  A2 at the evaluate_disenrollment pseudocode block, A3 at the
  Disenrollment governance and review paragraph in Why This Isn't
  Production-Ready, and ERROR 1 at the Idempotency paragraph.
- All prior TechWriter and editor TODOs preserved verbatim.
- Voice drift sentinel scan: no documentation-voice openings, no
  LinkedIn-influencer patterns, no announcement statements. The two
  "high-leverage" hits flagged by Voice V3 are colloquial leverage-
  point sense and acceptable per the persona instructions.
- Vendor balance: 70/30 maintained. AWS service names confined to
  The AWS Implementation, Why This Isn't Production-Ready, and
  Variations.
- Footer navigation present and well-formed (Recipe 4.6 back-link,
  Chapter 4 Preface, Recipe 4.8 forward-link).
- Linda continuity: vignette-to-briefing patient name reconciliation
  was addressed in v1 (Mr. Garcia renamed to Linda). The remaining
  briefing-vs-vignette social-context reconciliation is correctly
  deferred to TechWriter via the existing TODO at the briefing JSON.
- No structural rewrites. No new claims or technical content. No
  changes to the recipe in this v2 pass beyond this verification
  note; the v1 pass produced a publishable artifact and the
  remaining open items are TODOs waiting on TechWriter follow-up
  (HIGH findings) or external verification (TODO links and pricing).
-->


**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.005-0.025 per enrollment recommendation (depends on uplift model serving, LLM-generated enrollment briefings, and longitudinal outcome tracking)

---

## The Problem

Linda is 72. She has heart failure (HFrEF, EF 35 percent at last echo), type 2 diabetes (A1c 8.4 percent), chronic kidney disease (stage 3b, eGFR 38 mL/min/1.73m²), and atrial fibrillation on apixaban. She lives alone in a two-bedroom apartment on the fourth floor of a building with a temperamental elevator. Her daughter lives 90 minutes away and visits on weekends. She has been hospitalized twice in the last twelve months: once in February for a heart-failure decompensation that started, in retrospect, when she ran out of furosemide for four days and didn't tell anyone, and once in August for a syncopal episode that turned out to be a medication interaction between a new antibiotic and her warfarin (she was switched to apixaban after that admission). Both admissions were preceded, in the chart, by signals that the system noticed too late: weight gain of seven pounds over ten days before the February admission, three missed medication refills before the August admission, and a phone call to the practice three weeks before each admission about "feeling off" that triaged to a routine appointment four weeks out.

Linda's plan runs four care management programs. There is a disease-specific heart-failure program (twelve-week curriculum, weekly check-ins with a nurse, weight-and-symptom monitoring, medication reconciliation at week one and week six, total per-patient cost approximately $1,800). There is a high-risk complex-care management program (longitudinal, no defined end date, nurse plus social-work plus pharmacist, monthly home visits or televisits, total per-patient cost approximately $400 per month indefinite). There is a transitional care management program for the first 30 days post-discharge (RN coordinator, two scheduled calls and one home visit, medication reconciliation, follow-up appointment scheduling, total per-patient cost approximately $350 per episode). And there is a polypharmacy and medication management program (clinical pharmacist, telephonic, six sessions over twelve weeks, total per-patient cost approximately $600).

The plan has 240,000 members. About 18,000 of those members would, by some reasonable definition, be eligible for at least one care management program. The combined capacity across all four programs is approximately 1,400 active enrolled patients at any given time. The math is not subtle: about one in thirteen eligible members will get a program slot in any given enrollment window. The other twelve will not.

Linda is, by any reasonable measure, the kind of patient these programs were designed for. She is also one of 18,000.

The plan's risk-stratification model gives Linda a 12-month admission probability of 41 percent. That puts her in the top 8 percent of the population by predicted admission risk. Three thousand patients are above her in the risk-stratification ranking. Five thousand more are within five percentage points of her. The risk model alone does not pick Linda out of that crowd. The risk model, in fact, will overweight some patients who are unlikely to engage with care management (chronically ill but disengaged, multiple prior unsuccessful enrollment attempts, complex social barriers that the program structure cannot address) and underweight some patients who would benefit greatly (recently destabilized, currently engaged, ready for help, but historically lower-risk so they don't surface above the cutoff). The risk model is a necessary input. It is not the answer.

What the plan needs, but its current process does not produce, is an answer to a different question: among the 18,000 eligible patients, which 1,400 should we enroll in which program, given each program's specific theory of change, each patient's likelihood of responding to that program, the patient's clinical trajectory, and the operational reality that we have to make this allocation every month without re-litigating it from scratch?

If Linda is unlucky, the plan's enrollment process is a population health analytics report that spits out the top 5,000 patients ranked by 12-month admission risk and routes the top 1,400 to whichever care manager has capacity that month. The disease-specific heart-failure program ends up with patients who have heart failure plus eight other things going on, and the program's twelve-week heart-failure curriculum doesn't touch the other eight things. Care managers spend half their week on patients who don't respond to outreach. The plan reports "1,400 patients enrolled" at year end and a 4 percent reduction in admissions across the enrolled cohort, which sounds good until you compare it to a matched control cohort and discover that 80 percent of the reduction would have happened anyway because the cohort was selected on regression-to-the-mean (those patients had unusually high admission rates in the prior year that were going to drop in the current year regardless of intervention). The program looks like it works. The math, looked at carefully, says it barely does.

If Linda is lucky, the plan's enrollment process recognizes three things about her: she has heart failure with a recent destabilization that maps cleanly onto the heart-failure program's theory of change, she has a history of medication-related events that the polypharmacy program could address in parallel, and she has the kind of social context (lives alone, daughter at distance, mobility limited by the apartment building) that suggests transitional-care support after each admission may be more durable than longitudinal complex-care management. She gets enrolled in the heart-failure program after her August admission. The polypharmacy program runs in parallel. The transitional-care nurse handled the first 30 days post-discharge in the August admission and has already built rapport. The complex-care program is reserved for patients whose problems are less program-tractable; Linda's are. Twelve weeks later, Linda is on a stable diuretic regimen, has a daily-weight monitoring routine she's actually following, and her A1c is starting to come down because the polypharmacy pharmacist found that her metformin dose hadn't been adjusted for her current eGFR. She does not get readmitted in the following six months. The program's dollars worked.

Both versions of Linda's story are real. The first version is, regrettably, more common.

This is what care management program enrollment looks like in practice. The data identifies the *who-is-eligible*. The hard work is identifying the *who-and-which*: which of the eligible members should we enroll, into which program, with what sequencing, when, with what intensity, and how do we track whether the enrollment was the right call. Programs have limited slots. Slots are expensive. The patients who are easiest to enroll (already engaged with the practice, comfortable on the phone, English-preferring, suburban, retired) are also the patients least in need of the program's structural support. The patients hardest to enroll (transient housing, multiple jobs, language barriers, low health literacy, mistrust of the medical system) are often the ones the program could help most. A blanket "highest risk first" enrollment policy concentrates on patients with the highest predicted clinical events and ignores whether those patients will actually engage with the program. A blanket "most engaged first" enrollment policy concentrates on patients who are easiest to manage and may not need management at all. Neither is correct.

A second wrinkle that distinguishes care management enrollment from earlier recipes: the unit of decision is *enrollment in a specific program for a specific duration*, not "send a message" or "surface a gap" or "queue an outreach contact." Enrollment is a multi-month commitment of staff and patient time. The decision to enroll Linda in the heart-failure program for twelve weeks is not just a recommendation; it consumes a slot that 17,999 other people don't get this month. Disenrolling Linda midway is operationally expensive, ethically fraught, and signals to the patient that the program failed them. The decision needs to be more right than a recommendation engine for clicks needs to be.

A third wrinkle: programs have *theories of change*. The heart-failure program assumes the patient has heart failure as the primary clinical problem, can engage with weekly check-ins, and will benefit from weight-and-symptom monitoring. The complex-care program assumes the patient has multi-condition complexity that requires longitudinal coordination across specialties. The transitional-care program assumes the patient has just been discharged and will benefit from intensive support during the high-risk first 30 days. The polypharmacy program assumes medication issues are the primary lever. A patient enrolled in the wrong program for their actual problem profile will not benefit, will appear to be a "non-responder," and will be coded in the program data as "patient did not engage" when actually the program did not match the patient. Selecting the right program is not a categorization afterthought; it is the central decision.

A fourth wrinkle: response prediction is harder than risk prediction, and they're not the same thing. Risk prediction asks "what is the probability of an adverse event in the next 12 months?" Response prediction asks "what is the probability that this patient's outcome will be better if we enroll them than if we don't?" The difference is the counterfactual: a high-risk patient who would experience the adverse event whether or not the program intervenes is not a good response candidate even though they are a high-risk patient. A medium-risk patient whose adverse event the program would prevent is a great response candidate even though they don't dominate the risk-ranking. This is the uplift-modeling pattern from Recipes 4.4 and 4.5 again, with much higher stakes because the resource cost per intervention is 10 to 100 times higher and the duration is 10 to 30 times longer.

A fifth wrinkle: ROI math is real and is a regulatory and contractual reality, not a footnote. CMS Medicare Advantage plans, ACOs, and value-based contracts reimburse care management activities under specific structures (CCM, PCM, TCM CPT codes; capitated arrangements; shared-savings calculations). The plan's care management program has a budget. The budget is justified by an expected return: prevented admissions, prevented ED visits, improved quality measures, improved member retention. The recommender's enrollment decisions cumulatively determine whether the program returns its budget. A program full of low-response patients runs at a loss, gets cut at the next budget cycle, and the patients with chronic conditions who needed it lose access entirely. Selection matters not just for individual patients but for the program's continued existence.

A sixth wrinkle, and this one is the most ethically loaded: care management is *rationing*. There are 18,000 eligible patients and 1,400 slots. The recommender is making the choice. Rationing decisions in healthcare are subject to scrutiny under disability-rights frameworks, civil-rights frameworks, and contract terms that may require non-discrimination in program access. A recommender that systematically under-enrolls patients in protected groups (because the response model was trained on historical engagement data that itself reflects unequal access) replicates the disparity at scale. The Obermeyer et al. 2019 finding (an algorithm used to manage population health systematically under-prioritized Black patients because the proxy variable for need, healthcare costs, was lower for Black patients with the same actual clinical need) is the canonical cautionary tale for this exact use case. The fix is not the algorithm alone; it is the combined design of the eligibility logic, the response model, the allocation rules, and the equity instrumentation. None of these by itself solves the problem; together, they make it tractable.

A seventh wrinkle: enrollment is not a one-time decision. Patients graduate from programs (the heart-failure program ends after twelve weeks; the patient may need re-enrollment six months later when their condition shifts). Patients disenroll (for cause or for failure to engage). Patients re-engage (after a hospitalization, after a clinical change, after a life-circumstances change). The system has to handle the longitudinal cycle: not just the initial assignment, but the re-evaluation, the re-enrollment decision, the disenrollment decision, the post-graduation surveillance, and the cross-program transitions (graduating from heart-failure into a maintenance pathway; transitioning from transitional-care to disease-specific; escalating from disease-specific to complex-care if condition deteriorates).

So the problem statement, again, is deceptively simple: given a population of eligible patients, a portfolio of programs each with its own theory of change and capacity, and a steady stream of clinical and engagement data, decide which patients to enroll in which programs at which times, allocate finite program capacity across the population, track engagement and outcomes, and adjust enrollment over time. Not a top-1400-by-risk list every month. The right patient, in the right program, at the right time, with honest tracking of whether the enrollment changed the trajectory and honest acknowledgment of when capacity constraints force trade-offs that no algorithm can make cleanly.

We're going to build that. This recipe builds on the uplift-and-allocation pattern from 4.4 and 4.5, the multi-pathway orchestration from 4.6, and adds three pieces specific to care management: a multi-program response-prediction stack (per-program uplift models, calibrated against historical enrollment outcomes), an enrollment-decision orchestrator that handles capacity-constrained assignment with longitudinal state, and an in-program engagement-and-escalation tracker that handles the disenrollment, graduation, and cross-program-transition decisions. The architecture is structurally similar to 4.5 and 4.6. The clinical, operational, and ethical stakes are higher, and the recipe takes those seriously.

Let's get into how you build it.

---

## The Technology: Eligibility, Per-Program Response Modeling, Capacity-Constrained Allocation, and Longitudinal State Tracking

### What Counts as a Care Management Program

Before any modeling, the system has to know what programs exist and what each program is for. The four common archetypes are:

- **Disease-specific programs.** Time-bounded curricula focused on a single condition: heart failure (typically 8 to 16 weeks), diabetes self-management (typically 12 to 26 weeks), COPD (typically 12 weeks), CKD (variable, often longitudinal at later stages). The theory of change is condition-specific behavior change plus medication and monitoring optimization. Best fit: patients whose primary actionable problem is the program's target condition.
- **Complex-care management.** Longitudinal, multi-condition, multi-disciplinary. Nurse plus social worker plus pharmacist; monthly check-ins or home visits; explicit care plan with quarterly reassessment. Theory of change: the patient's problems are heterogeneous enough that no single-condition program addresses them, and the durable improvement comes from sustained coordination. Best fit: high-risk patients with multi-system disease, behavioral health comorbidity, social complexity.
- **Transitional care management.** Episodic, post-discharge, focused on the high-risk first 30 days after a hospital stay. RN coordinator, scheduled telephonic check-ins, in-home or televisit medication reconciliation, follow-up appointment scheduling. Theory of change: most readmissions are preventable with structured early support. CMS reimburses TCM (CPT 99495 / 99496) under specific documentation requirements, so the program structure is operationally constrained by billing rules. <!-- TODO: confirm current CMS TCM CPT code definitions and documentation requirements at the time of build. -->
- **Specialized programs.** Polypharmacy/medication-management (clinical pharmacist), behavioral-health integration (BHI codes), maternal/perinatal care management, palliative care management, oncology navigation. Each has its own theory of change and its own staffing model.

A production care management portfolio typically includes three to seven of these, with overlapping eligibility (a patient with heart failure post-discharge is eligible for both heart-failure and transitional-care programs; the orchestrator decides whether to enroll in one, both, or sequence them).

### Eligibility Logic

For each program, the eligibility logic answers: is this patient in the program's denominator (the eligible population), and does the patient meet inclusion and not-meet-exclusion criteria?

Denominator is typically defined by clinical conditions (active HF diagnosis on the problem list within X months, ICD-10 codes from a defined value set), recent events (discharge from inpatient stay within Y days), risk thresholds (predicted admission probability above a threshold), or contractual triggers (members under a specific contract who become high-cost-claimant flagged). Multiple programs can have overlapping denominators; the orchestrator handles that.

Exclusions vary: hospice or palliative care for some programs, active oncology treatment for some, current enrollment in another program for many, prior disenrollment for cause within the last 12 months, language preferences not supported by the program's staffing.

Hard-coding eligibility is a maintenance disaster as the portfolio evolves. The right pattern is the same registry pattern from Recipe 4.6: a structured, versioned catalog of programs (denominator predicates, inclusion predicates, exclusion predicates, capacity, theory-of-change tags, target enrollment duration, expected per-patient cost, expected per-patient impact magnitude), evaluated by a generic eligibility engine. Clinical operations and program leadership own the registry; engineering owns the evaluator. New programs land as registry entries.

### Risk Stratification (the Necessary But Insufficient Input)

Most care management programs use a population risk score as a starting filter. The classic approach is a 12-month-admission probability model trained on claims and clinical features. The output is a per-patient probability or risk band. CMS HCC-derived risk scores (from the same RAF score that drives MA payment) are sometimes used; commercial alternatives (Verisk, Optum Impact Pro, Milliman MARA) are also common. Many plans also build their own admission and ED-utilization models.

The risk score answers "who is likely to have an event?" It does not answer "who would benefit from the program?" Two patients with identical risk scores can have radically different program-response profiles: a patient whose risk is driven by progressive disease where the program has limited ability to alter trajectory, versus a patient whose risk is driven by recent destabilization where the program's monitoring and medication optimization can plausibly intervene. The risk score is necessary because you can't enroll out-of-distribution low-risk patients into a program designed for high-risk patients; it is insufficient because risk alone does not predict response.

A common pitfall: regression-to-the-mean. The patients with the highest admission rates in the *prior* year will, on average, have *lower* admission rates in the next year regardless of intervention, simply because they were unusually high in the prior year. A care management program that selects on prior-year utilization and reports next-year-utilization reduction will see a reduction even if the program does nothing. This is the canonical "without a control group, you can't tell" trap. Production programs handle this with matched-control evaluation (propensity-matched difference-in-differences) and, ideally, with randomized enrollment in a fraction of the eligible population to support unbiased uplift evaluation.

### Per-Program Response Prediction (Uplift)

For each (patient, program) pair, the response model predicts the conditional average treatment effect: how much better does this patient's outcome look if enrolled versus not enrolled, accounting for the patient's specific features. The outcome variable is program-specific:

- For disease-specific programs: condition-specific outcomes (HF program target: 90-day readmission rate, weight-stability, NYHA class change; DM program target: A1c change, hypoglycemic events).
- For complex-care management: total-cost-of-care change, ED visit rate change, hospital admission rate change, member-experience and PROMs change.
- For transitional care management: 30-day all-cause readmission rate, 30-day ED visit rate, follow-up appointment completion rate.
- For polypharmacy/medication management: medication-related adverse event rate, adherence rate (PDC, from Recipe 4.5), prescriber-driven medication changes following pharmacist recommendations.

Training the response model on observational data (which is what every plan has) is hard. The patients who got enrolled differ systematically from the patients who didn't (selection bias, by clinician referral, by prior engagement, by geographic accessibility of the program). Naive supervised learning ("predict the outcome given features and enrollment status") confounds program effect with selection. Standard mitigations:

**Propensity-score matching or weighting.** Estimate the probability of enrollment given features, then match enrolled to non-enrolled patients with similar propensity. The ATE estimate within matched pairs is less confounded. Useful for evaluation. Sensitive to unmeasured confounders.

**Doubly-robust estimation.** Combines a propensity model with an outcome model; consistent if either is correctly specified. Workhorses include the EconML library and the DoWhy library. The CATE (Conditional Average Treatment Effect) estimators from EconML (DML, DR-Learner, Causal Forest) are appropriate when you want per-(patient, program) uplift estimates rather than population averages.

**Randomized enrollment in a fraction of the eligible population.** Operationally controversial but methodologically pristine. Reserve, say, 10 percent of program slots for randomly selected eligible patients (stratified by clinical risk). The randomized cohort is the unbiased reference; it bounds bias in the targeted-enrollment cohort.

**Quasi-experimental designs.** Regression discontinuity around enrollment thresholds, instrumental variables based on clinician referral patterns, difference-in-differences on natural experiments (program rolled out region by region). When randomization is operationally infeasible, these can recover causal estimates with stated assumptions.

The uplift output is per-(patient, program), with a confidence interval. A program with a positive uplift point estimate but a confidence interval that includes zero is a maybe-helpful candidate; a program with a confidently-positive uplift is a high-value enrollment. The orchestrator uses both the point estimate and the uncertainty.

### Capacity-Constrained Assignment

Once the response model produces per-(patient, program) uplift estimates, the assignment problem is: select a subset of (patient, program) pairs that maximizes total expected benefit, subject to per-program capacity constraints, per-patient enrollment constraints (a patient should typically not be in two overlapping programs simultaneously), equity constraints, and operational constraints (geographic feasibility, language match with program staffing).

This is a constrained optimization problem. A few useful patterns:

**Greedy by uplift, with pruning.** Sort all (patient, program) candidates by predicted uplift descending. Assign top candidates to slots, skipping candidates whose patient is already assigned or whose program is full. Simple, fast, near-optimal in many practical settings, easy to explain. Accommodates equity floors as reserved capacity per cohort.

**Linear programming or integer programming.** Optimal under stated objectives. Useful when constraints are complex (per-region capacity, per-clinician load balancing, multi-program-per-patient sequencing). Requires more care to keep the policy explainable to operations.

**Multi-stage allocation.** Allocate transitional-care slots first (time-sensitive, post-discharge); then disease-specific to patients with clear theory-of-change fit; then complex-care to patients who didn't fit a disease-specific program but show high response uplift; then polypharmacy as a parallel-eligible add-on. Multi-stage allocation respects program semantics and produces interpretable allocation logs.

**Equity floors.** Reserved capacity per cohort, defined a priori, with allocation policies that prevent the high-uplift sort from systematically under-serving cohorts the historical data has under-represented. Same pattern as 4.5 and 4.6, with higher stakes because the resource is more valuable.

**Operational feasibility filters.** A patient eligible for the heart-failure program but in a region without HF-program staffing capacity that month is filtered out; a patient whose preferred language is not supported by any care manager currently scheduled is routed to an outsourced or interpreter-supported pathway, or held for a future enrollment cycle. The recommender doesn't pretend operational reality away.

### Longitudinal State Tracking and the Re-Enrollment Cycle

Care management is an episodic-and-longitudinal mix, and the system needs to track patient state over time:

- **Eligible.** Meets denominator and inclusion criteria; not currently enrolled or excluded.
- **Recommended.** The recommender has surfaced this patient for enrollment; awaiting clinical operations review or outreach.
- **Outreach in progress.** Care management staff has begun enrollment outreach; not yet enrolled.
- **Enrolled.** Patient has consented and is actively in the program.
- **Engaged.** Patient is actively participating (attending check-ins, completing education modules, reporting back).
- **At-risk-of-disengagement.** Engagement has dropped below program threshold; intervention to retain.
- **Disenrolled.** Program ended, by graduation (curriculum completed, goals met), patient request, or for-cause (failure to engage after retention attempts, became ineligible mid-program due to clinical change).
- **In observation post-graduation.** Recently graduated; system watches for relapse signals (new admission, new abnormal lab, re-emergence of triggering condition).
- **Re-eligible for re-enrollment.** Has been out of program for an interval and now meets re-enrollment criteria (clinical deterioration, new event, time-based reassessment).

Each state transition is an event. The state machine is the source of truth for downstream consumers (program dashboards, clinician inboxes, billing, equity monitoring, outcome evaluation). State-machine drift between the recommender's view and the care management team's operational view is a chronic source of confusion in production deployments; the integration with the program's case-management system has to be tight enough that both sides agree on every patient's current state.

### Engagement Tracking and Mid-Program Decisions

Once a patient is enrolled, the system tracks per-patient engagement: scheduled-call attendance, education-module completion, self-reported metrics (weight, blood pressure, symptom check-ins), responses to nurse outreach, and clinical signals (new fills, missed fills, new diagnoses, new admissions). An engagement-decline signal triggers a structured retention attempt: a different care manager attempting outreach, a switched modality (telephonic to text-based check-ins, or video to in-home visit), a paused-but-not-disenrolled state with a defined re-engagement window.

The disenrollment decision, when retention fails, has cost, equity, and clinical implications. A patient who has been enrolled for ten weeks of a twelve-week program and is at risk of disengagement at week eleven should not be automatically disenrolled; the cost of completing the program is small and the partial credit may matter. A patient who has been enrolled for two weeks and never engaged after the initial enrollment call is, frankly, taking a slot that could have gone to a different patient who would engage. The decision policy needs to balance these.

Cross-program transitions are their own modeling problem. A patient who completes the heart-failure program but whose A1c has drifted up during enrollment is a candidate for the diabetes-management program; the recommender should surface this transition rather than wait for the patient to re-enter the eligibility queue from scratch. Sequencing is part of the program experience.

### Outcome Evaluation Done Honestly

Evaluation is where most care management programs fail to be honest with themselves. The temptation is to compute "enrolled-cohort outcome change minus prior-year baseline" and call it impact. As noted above, this conflates regression-to-the-mean with program effect.

Done honestly:

**Propensity-matched difference-in-differences.** Match enrolled patients to comparable non-enrolled patients on risk score, condition mix, prior utilization, demographics, and SDOH features. Compute the change in outcome for both cohorts; the difference of the changes is the program's estimated impact, with bias bounded by the matching quality and the residual unmeasured confounders.

**Uplift validation against held-out data.** The uplift model's predictions for each patient are compared against actual outcomes on a held-out evaluation cohort. Calibration plots (predicted uplift quintile versus realized uplift) tell you whether the model is well-calibrated, and the area-under-the-uplift-curve tells you whether the ranking is informative.

**Cohort-stratified evaluation.** Total-cohort impact estimates can mask cohort-specific failures. A program with strong effect on English-preferring suburban patients and zero effect on Spanish-preferring rural patients has a problem the total estimate hides. Evaluation is per-cohort, with explicit fairness reporting.

**Cost-of-program versus value-of-impact.** Program impact in dollar terms (avoided admissions × average admission cost), against program cost (staff time × loaded hourly rate), per-cohort. The ratio is the per-cohort ROI. Programs that pencil out at the population level but lose money on the cohorts that need them most are programs that are slowly contracting away from the patients that justified them.

### Where LLMs Fit (and Don't)

Same pattern as Recipes 4.5 and 4.6, with care-management-specific notes:

- **Eligibility evaluation, response prediction, capacity allocation, disenrollment decisions.** Not the LLM's job. Deterministic logic, auditable models, and the program registry.
- **Care-manager-facing enrollment briefings.** Yes. A structured-output prompt takes the patient's clinical context, the recommended program, the per-program uplift estimates, and recent clinical events, and produces a paragraph briefing for the care manager doing initial outreach: what to lead with, what concerns to anticipate, what social context matters. The care manager reads it before the call.
- **Patient-facing enrollment messaging.** Yes, same pattern as 4.4 through 4.6: structured assignment in, tailored message out, validator before send. Care management enrollment messaging is regulated communication; the validator enforces required disclosures and approved-claim language.
- **Mid-program engagement summaries for case-rounds.** Yes. The LLM packages structured engagement data (last contact date, missed-check-in count, recent clinical events, outstanding goals) into a one-paragraph summary for case rounds. The data comes from the deterministic engagement tracker; the LLM packages.
- **Disenrollment-decision-support narratives.** Yes, with care. When the deterministic policy recommends disenrollment, the LLM generates a clinician-readable rationale that lists the engagement-history evidence and the policy-rule that triggered. This is decision support for a human who makes the actual disenrollment call, not autonomous disenrollment.
- **Open-ended clinical reasoning about which program to recommend.** No. The deterministic uplift models pick. The LLM packages the picks.

### Where This Sits in the Chapter

This recipe is the apex of the targeting recipes in Chapter 4 in operational complexity. The patient-profile DynamoDB table from 4.1, extended through 4.4, 4.5, 4.6, gets new attributes (`program_eligibility`, `program_state`, `program_history`, `engagement_history_per_program`, `cross_program_coordination_state`). The engagement-event Kinesis stream gains program-specific event types (`program_recommended`, `program_outreach_initiated`, `program_enrolled`, `program_engaged`, `program_at_risk`, `program_disenrolled`, `program_graduated`, `program_re_eligible`). The SageMaker Feature Store features from earlier recipes are reused; new feature groups capture program-specific features (per-program enrollment history, per-program response history, cross-program coordination state). The barrier classifier from 4.5 is reused; some care management enrollment failures are barrier-explained (a patient with a transportation barrier who is recommended into a program that requires in-person visits is a structural mismatch; the recommender should account for it). The care-gap state from 4.6 is reused; multiple open high-urgency gaps are a feature of complex-care eligibility.

The new architectural pieces are the multi-program response stack (per-program uplift models trained against program-specific outcomes), the multi-stage enrollment-decision orchestrator, the longitudinal state tracker with cross-program transition logic, and the engagement-and-retention worker. The cohort fairness instrumentation from 4.3 through 4.6 is here too, with higher operational consequences because every misallocated slot is a patient who could have benefited and didn't.

---

## General Architecture Pattern

The pipeline has seven logical components: a program-registry component that maintains program definitions and capacity, an eligibility-evaluation component that determines which patients qualify for which programs, an enrichment component that scores per-program response uplift and engagement likelihood, an enrollment-decision orchestrator that performs capacity-constrained allocation with equity floors, an outreach-and-enrollment workflow that handles patient consent and program intake, an in-program engagement-and-retention tracker that monitors program participation, and a longitudinal-state-and-transition manager that handles graduation, disenrollment, and cross-program transitions.

```
┌───────── PROGRAM REGISTRY (governance-controlled) ────────────┐
│                                                                │
│  [Program leadership]   [Clinical operations]   [Contracts]    │
│           │                       │                  │         │
│           └──────────┬────────────┴────────┬─────────┘         │
│                      ▼                     ▼                   │
│         [Program spec: denominator, inclusion, exclusion,      │
│          capacity, theory_of_change, target_outcomes,          │
│          target_duration, expected_cost_per_patient,           │
│          expected_per_patient_uplift, language_support,        │
│          geographic_support, version, effective_dates]         │
│                      │                                         │
│                      ▼                                         │
│         [Persist to program-registry store; versioned]         │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── ELIGIBILITY EVALUATION (daily) ──────────────────────┐
│                                                                │
│  [Claims]  [EHR]  [Lab]  [Pharmacy]  [Discharge feeds]         │
│  [Risk-stratification scores]  [Care-gap state from 4.6]       │
│  [Adherence state from 4.5]                                    │
│                          │                                     │
│                          ▼                                     │
│              [Normalize patient feature snapshot]              │
│                          │                                     │
│                          ▼                                     │
│              [Per-patient: evaluate each program's             │
│               denominator, inclusion, exclusion predicates;    │
│               produce per-(patient, program) eligibility       │
│               with reason]                                     │
│                          │                                     │
│                          ▼                                     │
│              [Persist eligibility records; emit                │
│               eligibility-change events]                       │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── PER-PROGRAM RESPONSE ENRICHMENT (daily/weekly) ──────┐
│                                                                │
│  [Eligibility records]  [Patient features]  [Risk scores]      │
│  [Barrier signals]  [Engagement history]                       │
│           │                │                  │                │
│           └──────────┬─────┴────────┬─────────┘                │
│                      ▼              ▼                          │
│         [Stage A: per-program uplift score                     │
│          (per-program model: gradient-boosted CATE             │
│           or causal-forest, calibrated against                 │
│           historical enrollment outcomes)]                     │
│                      │                                         │
│                      ▼                                         │
│         [Stage B: enrollment-likelihood score                  │
│          (per-program model: probability the patient           │
│           accepts enrollment given outreach;                   │
│           barrier-aware)]                                      │
│                      │                                         │
│                      ▼                                         │
│         [Stage C: program-fit score                            │
│          (alignment between patient's clinical                 │
│           profile and program's theory-of-change;              │
│           hard-coded plus learned components)]                 │
│                      │                                         │
│                      ▼                                         │
│         [Stage D: per-(patient, program) priority synthesis    │
│          (uplift × enrollment-likelihood × program-fit ×       │
│          equity-floor-eligibility)]                            │
│                      │                                         │
│                      ▼                                         │
│         [Persist enriched candidate slate]                     │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── ENROLLMENT-DECISION ORCHESTRATOR (weekly/monthly) ───┐
│                                                                │
│  [Enriched candidate slate]  [Current program state]           │
│  [Per-program capacity]  [Equity floors]  [Operational         │
│   feasibility filters]                                         │
│                          │                                     │
│                          ▼                                     │
│         [Multi-stage allocation:                               │
│          - Stage 1: time-sensitive (transitional care,         │
│            post-discharge)                                     │
│          - Stage 2: disease-specific high-fit                  │
│          - Stage 3: complex-care for unfit-for-disease         │
│          - Stage 4: parallel add-ons (polypharmacy,            │
│            behavioral-health)]                                 │
│                          │                                     │
│                          ▼                                     │
│         [Per-stage: greedy-by-uplift with capacity, equity     │
│          floors, per-patient single-program constraint,        │
│          operational feasibility filters]                      │
│                          │                                     │
│                          ▼                                     │
│         [Persist enrollment recommendations to                 │
│          recommendation-log; transition state machine          │
│          to recommended; emit events]                          │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── OUTREACH AND ENROLLMENT WORKFLOW ────────────────────┐
│                                                                │
│  [Recommended-state patients]                                  │
│                          │                                     │
│                          ▼                                     │
│         [Care-manager-facing enrollment briefing               │
│          (deterministic ranker output + LLM-generated          │
│           one-paragraph briefing)]                             │
│                          │                                     │
│                          ▼                                     │
│         [Outreach attempt (telephonic, SMS-then-call,          │
│          mailed letter, video for some programs)]              │
│         [State transitions: outreach_in_progress,              │
│          consented, declined, unreachable, deferred]           │
│                          │                                     │
│                          ▼                                     │
│         [Consent and enrollment intake (HIPAA                  │
│          authorization, program-specific consent,              │
│          baseline assessment)]                                 │
│                          │                                     │
│                          ▼                                     │
│         [State transition to enrolled; care-management         │
│          system handoff; engagement tracker armed]             │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── ENGAGEMENT AND RETENTION TRACKING ───────────────────┐
│                                                                │
│  [Care management system events]  [Patient self-report]        │
│  [Clinical events during enrollment]                           │
│                          │                                     │
│                          ▼                                     │
│         [Per-patient engagement scoring against                │
│          program-specific engagement profile;                  │
│          at-risk-of-disengagement flagging]                    │
│                          │                                     │
│                          ▼                                     │
│         [Retention worker: structured retention attempts       │
│          (modality switch, care-manager swap, paused           │
│          re-engagement); state transitions]                    │
│                          │                                     │
│                          ▼                                     │
│         [Mid-program clinical-deterioration detection;         │
│          escalation to higher-acuity program; cross-program    │
│          transition recommendation]                            │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── LONGITUDINAL STATE AND OUTCOME EVALUATION ───────────┐
│                                                                │
│  [Engagement events]  [Clinical events]  [Discharge events]    │
│  [Disenrollment decisions]                                     │
│                          │                                     │
│                          ▼                                     │
│         [State machine transitions: enrolled, engaged,         │
│          at_risk, disenrolled, graduated, in_observation,      │
│          re_eligible]                                          │
│                          │                                     │
│                          ▼                                     │
│         [Outcome evaluation pipeline (propensity-matched       │
│          difference-in-differences; per-program,               │
│          per-cohort; uplift-model calibration)]                │
│                          │                                     │
│                          ▼                                     │
│         [Feed retraining: response models, enrollment-         │
│          likelihood models; flag drift]                        │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**The program registry is governance, not engineering.** A structured, versioned catalog of programs: denominator predicate, inclusion/exclusion predicates, capacity, language and geographic support, theory-of-change tags, target duration, expected per-patient cost, expected per-patient uplift magnitude. Program leadership and clinical operations own it. Engineering owns the evaluator. New programs, capacity changes, and program retirements land as registry entries; the engineering pipeline does not change.

**Eligibility evaluation runs daily.** For each program, evaluate denominator and inclusion and exclusion predicates against the patient feature snapshot. The evaluation is SQL-shaped at scale, similar to 4.6's gap evaluator. The output is a per-(patient, program) eligibility record with reason; events fire when a patient newly qualifies for or is newly excluded from a program (a discharge event triggers transitional-care eligibility; a hospice election triggers exclusion across most programs).

**Per-program response enrichment is the modeling-heavy stage.** The uplift model is per-program (the heart-failure program's uplift drivers differ from the polypharmacy program's). The enrollment-likelihood model is per-program (a patient may be willing to enroll in a low-friction program and decline a high-friction one). The program-fit score combines a hard-coded theory-of-change-alignment heuristic with a learned component (some patients respond to disease-specific structure better than complex-care; some are the reverse). The synthesized priority feeds the orchestrator.

**The enrollment-decision orchestrator is the most operationally distinctive piece.** Multi-stage allocation respects program semantics: time-sensitive transitional care goes first, disease-specific programs second for patients with clean theory-of-change fit, complex-care third for the residual high-uplift complex patients, parallel add-ons fourth. Within each stage, allocation is greedy-by-uplift with per-program capacity, per-cohort equity floors, per-patient single-active-primary-program constraint (a patient is not in two competing primary programs at once, but parallel add-ons like polypharmacy can stack on top of a primary), and operational feasibility filters. The orchestrator's output is auditable and explainable per-decision.

**Outreach and enrollment is human-in-the-loop.** The recommender's output is the candidate list; the actual enrollment decision goes through the care management team. The team's outreach attempt may succeed (patient consents, enrolled), partially succeed (patient declines, deferred), or fail (unreachable, no consent obtained). State transitions are deterministic; the LLM generates the human-readable briefing for the care manager and the patient-facing outreach message.

**Engagement tracking runs continuously during enrollment.** The patient's program-specific engagement profile (calls attended, modules completed, self-reported data submitted) plus clinical events (admissions, ED visits, new diagnoses) plus medication and adherence signals (Recipe 4.5) feed a per-patient engagement score. Below threshold, the retention worker activates; above threshold, the patient continues. Mid-program escalation logic handles deterioration: a heart-failure-program patient who is admitted twice during the twelve-week curriculum is a candidate for escalation to complex-care, with a seamless transition rather than restart-from-eligibility.

**Outcome evaluation is per-program, per-cohort, and explicitly causal-inference-aware.** Propensity-matched difference-in-differences on the enrolled-versus-matched-non-enrolled cohorts produces per-program impact estimates with cohort breakdowns. Uplift-model calibration plots track whether the response models are well-calibrated. Cost-versus-value math informs program-level decisions about expanding, contracting, or sunsetting programs. The evaluation is the feedback loop that prevents the program from drifting toward the cohorts that selection-bias makes look good but are not who the program is supposed to serve.

**Equity instrumentation is non-negotiable.** Enrollment-rate parity by cohort (language, race-ethnicity, SDOH cohort, geography, age-band). Per-cohort uplift (the model's predicted uplift varies by cohort; the enrollment rate should not be discordant with the uplift in ways that systematically under-serve cohorts). Per-cohort engagement, retention, and graduation rates. Per-cohort outcome (post-program admission rate, ED rate, total cost change). Each axis is a monitored dashboard, with thresholds that trigger committee review when crossed.

**Care-team integration is bidirectional.** Care managers' notes, clinical observations, and disenrollment reasons flow back into the recommender as features and as labels. A care manager who flags a patient as "not a fit for this program because of X" provides structured signal that retraining should incorporate. The integration is a structured-feedback API on the case-management system, not a free-text-to-NLP pipeline.

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for the model training and serving stack.** Three model families per program: the per-program response (uplift) model, the per-program enrollment-likelihood model, and the per-program engagement-prediction model (predicting whether an enrolled patient will engage). With four to seven programs in the portfolio, the model count multiplies; SageMaker Pipelines (or Step Functions orchestration over SageMaker training jobs) handles the per-program retraining cadence. Inference uses Batch Transform on a weekly or monthly cadence aligned with enrollment cycles; same cost reasoning as 4.4, 4.5, 4.6 (batch is dramatically cheaper than idle real-time endpoints, and enrollment decisions don't run in real-time). SageMaker is HIPAA-eligible under BAA. <!-- TODO: confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here. -->

**Amazon SageMaker Feature Store for per-patient and per-(patient, program) features.** Patient-level features (clinical risk, engagement history, demographics, SDOH proxies) reused from earlier recipes. Per-(patient, program) features specific to this recipe: prior enrollment in the program, prior engagement during enrollment, prior disenrollment reason, time since last enrollment, cross-program coordination state. The offline store powers daily/weekly batch enrichment; the online store supports the lower-latency lookups used during outreach when a care manager pulls up a patient and the system surfaces the current recommendation context.

**Amazon DynamoDB for the program registry, eligibility records, recommendation log, patient program state, engagement state, and outreach state.** Same `patient-profile` table from prior recipes, extended with program-related attributes. New table `program-registry` keyed on `program_id` and `version`. New table `patient-program-state` keyed on (patient_id, program_id) for the per-(patient, program) state machine, with attributes: `state`, `state_history`, `eligibility_reason`, `priority`, `priority_components`, `current_enrollment_metadata`, `last_evaluation_date`. New table `outreach-state` for in-flight outreach attempts. New table `engagement-state` for in-program engagement scoring.

**Amazon S3 for the data lake, evaluation outputs, and longitudinal storage.** Source data feeds (claims, EHR, lab, pharmacy, discharge feeds, care management system events) land in S3 via Kinesis Firehose for streaming and Glue for batch. Offline feature store backed by S3. Eligibility evaluation outputs land in S3 per run. Per-program evaluation cohorts (treated and matched-control) land in S3 for outcome evaluation. Long-horizon engagement and outcome history accumulate for retraining.

**AWS Glue and Amazon Athena for eligibility evaluation, propensity matching, and outcome evaluation.** Eligibility is a SQL-shaped problem at scale, identical pattern to 4.6's gap evaluator. Glue jobs run nightly to evaluate every program in the registry against every eligible-population patient. Athena powers the per-program, per-cohort, per-clinician dashboards and the outcome-evaluation pipeline. Propensity matching for the difference-in-differences evaluator runs in Glue with logistic-regression or gradient-boosted propensity models, joining matched pairs into evaluation cohorts.

**AWS Step Functions for batch orchestration.** Same pattern as 4.5 and 4.6. The daily eligibility evaluation pipeline is a Step Functions workflow. The weekly/monthly enrollment-decision orchestration is a separate Step Functions workflow that runs the multi-stage allocation, persists recommendations, and triggers outreach generation. The post-enrollment monthly outcome-evaluation pipeline is a third Step Functions workflow.

**Amazon EventBridge for scheduling and event-driven triggers.** EventBridge schedules the daily eligibility run and the enrollment-decision run. EventBridge rules handle event-driven triggers: a discharge event triggers transitional-care eligibility evaluation for that patient outside the daily cycle (transitional care is time-sensitive); a clinical-deterioration event during enrollment triggers cross-program transition evaluation; a graduation event triggers post-graduation observation entry.

**Amazon Kinesis Data Streams for engagement, enrollment-state, and clinical events.** Same engagement-event bus from 4.1 through 4.6. New event types specific to this recipe: `program_recommended`, `program_outreach_initiated`, `program_outreach_attempted`, `program_consent_obtained`, `program_enrolled`, `program_engagement_event`, `program_at_risk`, `program_retention_attempted`, `program_disenrolled`, `program_graduated`, `program_re_eligible`, `cross_program_transition_recommended`. The state-machine worker consumes these and updates `patient-program-state`.

**Amazon Bedrock for care-manager-facing briefings, patient-facing enrollment messages, mid-program engagement summaries, and disenrollment-decision narratives.** Four distinct LLM use cases:

1. **Enrollment briefing for the care manager.** A structured-output prompt takes the patient's clinical context, the recommended program, the per-program uplift estimates with confidence intervals, recent clinical events, and the suspected barriers, and returns a one-paragraph briefing the care manager reads before initial outreach. Includes "what to lead with," "anticipated concerns," and "social context that matters."

2. **Patient-facing enrollment message tailoring.** Same pattern as 4.4 through 4.6: structured assignment in, tailored message out, validator before send. Care management enrollment messaging requires plan-sponsorship identification and program-specific consent language; the validator enforces both.

3. **Mid-program engagement summary for case rounds.** A weekly or monthly per-(patient, program) summary distilling structured engagement data (last contact, missed check-ins, recent clinical events, outstanding goals) into a paragraph for case-rounds discussion. Care managers triage from the summaries.

4. **Disenrollment-decision rationale.** When the deterministic policy recommends disenrollment, an LLM-generated rationale lists the engagement-history evidence, the policy-rule that triggered the recommendation, and any countervailing factors. The clinical lead reviews the rationale and makes the actual disenrollment call. The LLM is decision support for a human, not autonomous disenrollment.

Bedrock is HIPAA-eligible under BAA. Confirm in service terms that prompts and completions are not used to train the underlying foundation models. <!-- TODO: confirm current Bedrock service terms and the eligible-model list at the time of build. -->

**AWS Lambda for per-stage glue logic.** The eligibility evaluator dispatcher, the response-model invocation orchestrator, the priority synthesizer, the multi-stage allocation runner, the briefing-generation orchestrator, the state-machine worker, the engagement-scoring worker, the retention-trigger worker, the cross-program-transition recommender, and the post-graduation observation worker all run as Lambdas.

**Amazon Connect (or contracted outreach platform) for care-manager telephonic outreach.** Care management programs are predominantly telephonic and televisit. Plans with in-house care management teams often build on Amazon Connect; plans with vendor care management use the vendor's queue and a structured-event integration. The AWS-specific piece is HIPAA-eligible call recording, the contact-flow-to-engagement-event integration, and the per-care-manager work-queue routing that respects language, condition, and program-specialization match.

**Amazon SES for member-facing email and Pinpoint (or contracted vendor) for SMS.** Same as prior chapters; both under BAA. <!-- TODO: confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility. -->

**Amazon QuickSight for operations dashboards.** Per-program enrollment funnels (eligible -> recommended -> outreach -> consented -> enrolled -> engaged -> graduated). Per-cohort equity dashboards. Per-care-manager workload and outcome dashboards. Per-program ROI dashboards (cost-versus-value, with cohort breakdowns). Outcome-evaluation dashboards (per-program propensity-matched difference-in-differences, with cohort stratification). QuickSight on Athena, with row-level security for cohort-specific filters.

**AWS HealthLake (optional, for FHIR-based clinical data integration).** When the program needs fine-grained clinical data (problem list, observations, encounters, medications) for the response model and the program-fit score, HealthLake provides FHIR-native storage with built-in normalization. The lighter pattern is direct FHIR-to-S3 integration; HealthLake is the heavier pattern for plans operating across multiple EHR vendors. <!-- TODO: confirm AWS HealthLake's current pricing and HIPAA eligibility at the time of build. -->

**AWS KMS, CloudTrail, CloudWatch.** Same PHI infrastructure pattern as prior recipes. Customer-managed keys, CloudTrail data events on PHI tables, CloudWatch alarms on batch-run failures, eligibility-volume drift, enrollment-pipeline backups, and cohort-metric drift.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Sources
      A1[Claims Feed]
      A2[EHR / FHIR]
      A3[Lab Results]
      A4[Pharmacy / Adherence from 4.5]
      A5[Discharge Feeds]
      A6[Care Gap State from 4.6]
      A7[Risk Stratification Scores]
      A8[Care Management System Events]
      A9[Patient Self-Report]
    end

    A1 -->|Streaming| B1[Kinesis Firehose\ncm-source-events]
    A2 -->|Daily/streaming| B1
    A3 -->|Streaming| B1
    A4 -->|Daily| B1
    A5 -->|Streaming| B1
    A6 -->|Daily| B1
    A7 -->|Daily| B1
    A8 -->|Streaming| L1[Kinesis\ncm-engagement-stream]
    A9 -->|Portal/app| L1

    B1 --> S1[S3\ncm-data-lake]
    S1 --> C1[Glue\neligibility-evaluation]
    PR1[Lambda\nregistry-sync] --> D1[DynamoDB\nprogram-registry]
    D1 --> C1
    C1 --> F1[SageMaker Feature Store\npatient-program features]
    C1 --> G1[DynamoDB\npatient-program-state]

    F1 --> H1[Step Functions\nresponse-enrichment]
    H1 --> H2[SageMaker Batch Transform\nuplift-models per program]
    H1 --> H3[SageMaker Batch Transform\nenrollment-likelihood\nmodels per program]
    H1 --> H4[SageMaker Batch Transform\nengagement-prediction\nmodels per program]
    H1 --> H5[Lambda\npriority-synthesizer]
    H2 --> H5
    H3 --> H5
    H4 --> H5
    H5 --> G1

    SF1[Step Functions\nenrollment-decision] --> EO1[Lambda\nmulti-stage-allocator]
    EO1 --> G1
    EO1 --> R1[Lambda\nbriefing-generator]
    R1 --> R2[Bedrock\nenrollment briefings]
    R2 --> R3[DynamoDB\nenrollment-briefings]
    R3 --> R4[Care Manager Queue]

    R4 --> AC1[Amazon Connect\noutreach]
    AC1 --> AO1[DynamoDB\noutreach-state]
    AC1 --> AO2[Bedrock\npatient-message tailoring]
    AO2 --> AO3[SES / SMS / Portal]

    AC1 -.Outreach events.-> L1
    AO3 -.Engagement events.-> L1
    A8 -.Program events.-> L1

    L1 --> SM1[Lambda\nstate-machine-worker]
    SM1 --> G1
    SM1 --> ET1[Lambda\nengagement-scorer]
    ET1 --> EG1[DynamoDB\nengagement-state]
    EG1 --> RT1[Lambda\nretention-trigger]
    RT1 --> R4

    SM1 --> CT1[Lambda\ncross-program-transition]
    CT1 --> SF1

    L1 --> L3[Kinesis Firehose]
    L3 --> S2[S3\ncm-event-lake]
    S2 --> L4[Glue + Athena\noutcome-evaluation]
    S2 --> L5[QuickSight\nprogram-and-equity dashboards]
    L4 --> M1[SageMaker Training\nperiodic retrain]
    M1 --> H2
    M1 --> H3
    M1 --> H4

    style F1 fill:#9ff,stroke:#333
    style D1 fill:#9ff,stroke:#333
    style G1 fill:#9ff,stroke:#333
    style EG1 fill:#9ff,stroke:#333
    style AO1 fill:#9ff,stroke:#333
    style R3 fill:#9ff,stroke:#333
    style S1 fill:#cfc,stroke:#333
    style S2 fill:#cfc,stroke:#333
    style L1 fill:#f9f,stroke:#333
```


### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker (Training, Batch Transform, Feature Store, Pipelines), Amazon DynamoDB, Amazon S3, AWS Glue, Amazon Athena, AWS Step Functions, Amazon EventBridge, Amazon Kinesis Data Streams, Amazon Kinesis Data Firehose, AWS Lambda, Amazon Bedrock, Amazon Connect, Amazon SES, Amazon Pinpoint or contracted SMS provider, Amazon QuickSight, AWS HealthLake (optional), AWS KMS, Amazon CloudWatch, AWS CloudTrail. |
| **IAM Permissions** | Per-Lambda least-privilege: `sagemaker:CreateTransformJob` / `DescribeTransformJob` scoped to specific model ARNs; `dynamodb:GetItem` / `BatchWriteItem` / `UpdateItem` scoped to specific tables (especially `patient-program-state`, `engagement-state`, `outreach-state`); `bedrock:InvokeModel` on specific foundation-model ARNs; `s3:GetObject` / `PutObject` scoped to enrollment, eligibility, evaluation, and briefing buckets; `kinesis:PutRecord` on the cm-engagement-stream; `connect:*` scoped to the care-management contact flow; `ses:SendEmail` and `pinpoint:SendMessages` scoped to BAA-covered identities. Never `*`. <!-- TODO: pair these actions with one or two scoped Resource ARN examples. Same chapter-wide pattern flagged in 4.1 through 4.6 reviews. --> |
| **BAA** | AWS BAA signed. All services in the architecture must be HIPAA-eligible: SageMaker, DynamoDB, S3, Glue, Athena, Step Functions, EventBridge, Kinesis, Firehose, Lambda, Bedrock, Connect, SES, Pinpoint, KMS, HealthLake. <!-- TODO: confirm Bedrock + selected models, Pinpoint, Connect, and HealthLake eligibility at the time of build. --> |
| **Encryption** | DynamoDB: customer-managed KMS at rest (especially `patient-program-state`, `engagement-state`, and `enrollment-briefings`; the per-(patient, program) state plus engagement scoring is highly inferential PHI). S3: SSE-KMS with bucket-level keys. Kinesis and Firehose: server-side encryption. SageMaker training, Batch Transform, and Feature Store: VPC-only, with KMS keys for model artifacts and Feature Store offline storage. Lambda log groups KMS-encrypted. Briefing text stored in DynamoDB is PHI; the briefing contains diagnoses, social context, and clinical-trajectory framing. |
| **VPC** | Production: Lambdas in VPC. SageMaker training, Batch Transform, and Feature Store online store run in VPC. VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock, Kinesis, Firehose, KMS, CloudWatch Logs, SageMaker Runtime, Step Functions (`states`), EventBridge (`events`), Glue, Athena, STS, SES, Pinpoint, Connect, HealthLake. NAT Gateway only for external services without VPC endpoints; restrict egress with security groups. EHR FHIR feeds typically arrive via PrivateLink, Direct Connect, or SFTP-over-VPN. Care management system integrations vary by vendor; PrivateLink or VPN preferred. VPC Flow Logs enabled. |
| **CloudTrail** | Enabled with data events on the `patient-program-state`, `program-registry`, `enrollment-briefings`, `outreach-state`, `engagement-state`, `recommendation-log`, and `patient-profile` tables. Data events on the S3 buckets containing source feeds, eligibility outputs, evaluation cohorts, and briefing outputs. |
| **Equity Governance** | Document priority synthesis weights, the multi-stage allocation policy, the equity floors per program, the per-cohort enrollment-rate parity targets, and the disenrollment-decision policy before launch. Cross-functional review committee (medical director, program leadership, equity lead, data science, operations, member-experience lead, legal/compliance) signs off on the policy and reviews quarterly. Disenrollment-for-cause decisions go through committee review on a monthly cadence; individual cases that affect protected populations get heightened review. The Obermeyer-style failure mode is the canonical concern; instrumentation and governance are how you avoid it. |
| **Sample Data** | A starter set of synthetic patients with realistic risk profiles, condition mixes, prior-year utilization, and SDOH features (Synthea provides good baseline data; augment with synthesized engagement and enrollment-history fields). A small program registry (3-5 programs covering disease-specific, complex-care, transitional, and polypharmacy archetypes). Synthetic engagement and outcome labels to support uplift-model training scaffolding. Synthetic care-management-system events. |
| **Cost Estimate** | At a 250,000-member health plan with ~18,000 eligible patients, ~5 programs, and ~1,400 active enrollment slots: SageMaker Batch Transform (3 model families × 5 programs, weekly): roughly $250-500/month at modest instance sizes. SageMaker Feature Store offline store: $100-200/month. SageMaker training (monthly retrain of 15 model artifacts): $200-400/month. DynamoDB on-demand: $300-700/month (the per-(patient, program) state and engagement-state tables are the largest). Lambda + Step Functions: $100-250/month. Bedrock for enrollment briefings (~1,400 active per month plus outreach attempts), patient-message tailoring (~2,000/month), engagement summaries (~5,000/month), disenrollment rationales (~200/month), Haiku-class: $1,500-3,500/month. SES + Pinpoint SMS: $50-150/month. Connect for in-house care management team (15-30 FTE depending on caseload): $1,500-4,500/month plus telephony. S3 + Glue + Athena: $400-800/month. QuickSight: $50/user/month authors plus reader fees. HealthLake (if used): $500-2,500/month. Estimated infrastructure total: $5,000-12,000/month for a regional plan, before staff time, telephony, and outsourced care management contracts (which dwarf the AWS line items). <!-- TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Hosts the per-program response (uplift), enrollment-likelihood, and engagement-prediction models; runs training and Batch Transform jobs |
| **Amazon SageMaker Feature Store** | Per-patient and per-(patient, program) features (eligibility, prior enrollment history, prior engagement history, SDOH proxies, cross-program coordination state) reused across this recipe and prior chapter recipes |
| **Amazon DynamoDB** | Stores program registry, per-(patient, program) state machine, recommendation log, outreach state, engagement state, enrollment briefings, and clinician/care-manager overrides |
| **Amazon S3** | Hosts the cm-data-lake, offline feature store, eligibility outputs, evaluation cohorts, briefings audit trail, training data, and engagement-event lake |
| **AWS Glue** | Daily eligibility evaluation against the program registry, propensity-matching for outcome evaluation, schedule import, outcome-evaluation jobs |
| **Amazon Athena** | SQL access to the data lake; powers per-program funnels, per-cohort dashboards, and outcome-evaluation queries |
| **AWS Step Functions** | Orchestrates the daily eligibility pipeline, the weekly/monthly enrollment-decision pipeline, the per-discharge transitional-care evaluation pipeline, and the monthly outcome-evaluation pipeline |
| **Amazon EventBridge** | Schedules batch runs; routes discharge, clinical-deterioration, graduation, disenrollment, and re-eligibility events |
| **Amazon Kinesis Data Streams** | Carries care-management engagement, outreach, clinical, and self-report events into the state-machine worker and engagement scorer |
| **Amazon Kinesis Data Firehose** | Lands engagement events into S3 Parquet for long-horizon evaluation and retraining |
| **AWS Lambda** | Runs the registry sync, eligibility dispatcher, response-model invocation orchestrator, priority synthesizer, multi-stage allocator, briefing generator, state-machine worker, engagement scorer, retention trigger, cross-program transition recommender, and outcome-evaluation orchestrator |
| **Amazon Bedrock** | Hosts the LLM for enrollment briefings, patient-facing enrollment messages, mid-program engagement summaries, and disenrollment-decision rationales |
| **Amazon Connect** | Care-manager telephonic outreach with HIPAA-eligible call recording, work-queue routing, and integration with the engagement event stream |
| **Amazon SES** | Bulk email delivery under BAA for patient-facing enrollment outreach |
| **Amazon Pinpoint** | SMS delivery for enrollment outreach and check-in reminders |
| **AWS HealthLake** | Optional FHIR-native data store when fine-grained clinical data is needed for response models and program-fit scoring |
| **Amazon QuickSight** | Operational dashboards: per-program funnels, per-cohort equity, per-care-manager workload and outcomes, per-program ROI, propensity-matched outcome evaluation |
| **AWS KMS** | Customer-managed encryption keys for all PHI-containing stores |
| **Amazon CloudWatch** | Operational metrics, cohort-sliced enrollment dashboards, alarms on enrollment volume drift and outcome-metric drift |
| **AWS CloudTrail** | Audit logging for all PHI-related API calls |

---

### Code

> **Reference implementations:** Useful aws-samples patterns for this recipe:
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): XGBoost and SageMaker Pipelines notebooks that mirror per-program model training and inference patterns.
> - [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): End-to-end Feature Store usage that maps onto the per-(patient, program) feature pipeline.
> - [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Demonstrates structured-output prompting applicable to enrollment briefings, engagement summaries, and disenrollment-decision rationales.
> <!-- TODO: confirm the current names and locations of these aws-samples repos. -->

#### Walkthrough

**Step 1: Evaluate the program registry against patient data to produce per-(patient, program) eligibility records.** Eligibility runs nightly. For each program in the registry, evaluate denominator, inclusion, and exclusion predicates against the patient feature snapshot. Skip the registry abstraction and you end up hard-coding program logic, which becomes unmaintainable as the portfolio evolves.

```
FUNCTION evaluate_program_eligibility(patients, run_date):
    // Load every active program version. The registry is the source
    // of truth; engineering does not hard-code program logic. New
    // programs and capacity changes land as new registry versions.
    active_programs = DynamoDB.Query(
        "program-registry",
        filter = "effective_start <= :rd AND effective_end >= :rd",
        params = { :rd = run_date }
    )

    FOR each program in active_programs:
        // Step 1A: denominator. Determine which patients are eligible
        // for this program as of run_date. Denominator predicates use
        // condition flags, recent events, risk-score thresholds, and
        // continuous-enrollment criteria expressed in the registry's
        // predicate language.
        denominator = Athena.Query(
            program.denominator_query_template,
            params = { run_date: run_date,
                       lookback_start: run_date - program.denominator_lookback_days }
        )

        // Step 1B: inclusion criteria. Some programs have additional
        // inclusion logic on top of the denominator (e.g., HF program
        // requires not just an HF diagnosis but also at least one
        // HF-related encounter or admission in the last 6 months).
        inclusion_passing = Athena.Query(
            program.inclusion_query_template,
            params = { run_date: run_date,
                       denominator_population: denominator }
        )

        // Step 1C: exclusion criteria. Hospice election, active oncology
        // treatment, current enrollment in a competing program, prior
        // disenrollment for cause within the lookback, language not
        // supported by program staffing.
        excluded = Athena.Query(
            program.exclusion_query_template,
            params = { run_date: run_date }
        )

        // Step 1D: per-patient eligibility determination.
        FOR each patient_id in inclusion_passing:
            IF patient_id in excluded:
                eligibility = "excluded"
                exclusion_reason = lookup_exclusion_reason(patient_id, program, excluded)
            ELSE:
                eligibility = "eligible"
                exclusion_reason = null

            previous_record = DynamoDB.GetItem("patient-program-state",
                                                key = (patient_id, program.program_id))

            // State-machine semantics for eligibility transitions.
            IF previous_record.eligibility != eligibility:
                eligibility_event = "transitioned_" + previous_record.eligibility +
                                     "_to_" + eligibility
            ELSE:
                eligibility_event = "unchanged"

            DynamoDB.PutItem("patient-program-state", {
                patient_id:           patient_id,
                program_id:           program.program_id,
                program_version:      program.version,
                eligibility:          eligibility,
                exclusion_reason:     exclusion_reason,
                state:                derive_state(previous_record, eligibility),
                state_history:        previous_record.state_history.append({
                                          event: eligibility_event,
                                          timestamp: run_date,
                                          source: "eligibility_evaluation"
                                      }),
                last_evaluation_date: run_date,
                data_quality_flag:    assess_source_completeness(patient_id, program)
                    // values: 'complete', 'sparse_history',
                    // 'recent_plan_change', 'cross_provider_fragmentation'.
                    // Downstream consumers should gate on this when the
                    // data is unreliable, mirroring the pattern from 4.5
                    // and 4.6.
            })

        // Emit eligibility-change events for downstream consumers.
        // Time-sensitive eligibility changes (transitional care after
        // a discharge) trigger the per-discharge evaluation flow rather
        // than waiting for the next enrollment-decision cycle.
        FOR each newly_eligible_patient in newly_eligible(inclusion_passing,
                                                          program, run_date):
            Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
                event_type:  "eligibility_acquired",
                patient_id:  newly_eligible_patient,
                program_id:  program.program_id,
                run_date:    run_date,
                time_sensitive: program.is_time_sensitive,
                timestamp:   current UTC timestamp
            })
```

**Step 2: Score per-program response (uplift), enrollment likelihood, and program-fit per (patient, program).** The response model predicts the conditional treatment effect; the enrollment-likelihood model predicts whether the patient will accept enrollment given outreach; the program-fit score combines hard-coded theory-of-change alignment with a learned component. Skip per-program modeling and you treat all programs as interchangeable, which is the trap of "highest risk first" enrollment that ignores program semantics.

```
FUNCTION enrich_eligible_candidates(eligibility_records, run_date):
    eligible = filter(eligibility_records, eligibility = "eligible")

    // Group by program_id so each program's models run on the relevant
    // subset; per-program models are different artifacts.
    eligible_by_program = group_by(eligible, "program_id")

    job_handles = []
    FOR each program_id, program_eligible in eligible_by_program:
        candidate_path = "s3://cm-enrichment/run_date=" + run_date +
                         "/program=" + program_id + "/candidates.parquet"
        write_parquet(program_eligible, candidate_path)

        // Stage A: per-program uplift (response) scoring. The model
        // takes patient features, recent clinical trajectory, prior
        // engagement signals, barrier flags, and SDOH features and
        // returns a per-patient predicted uplift estimate (the
        // expected change in the program's primary outcome from
        // enrollment, versus no enrollment), with a confidence
        // interval. Trained against propensity-matched historical
        // enrollment data, ideally augmented with randomized-enrollment
        // data when available.
        uplift_job = SageMaker.CreateTransformJob(
            transform_job_name = "uplift-" + program_id + "-" + run_date,
            model_name         = UPLIFT_MODEL_NAMES[program_id],
            transform_input    = candidate_path,
            transform_output   = "s3://cm-scores/run_date=" + run_date +
                                 "/uplift/" + program_id + "/",
            instance_type      = "ml.m5.large",
            instance_count     = 1
        )
        job_handles.append(uplift_job)

        // Stage B: enrollment-likelihood scoring. Per-program model
        // predicting probability the patient accepts enrollment given
        // outreach. Inputs include barrier flags from 4.5 (transportation,
        // language, cost-sensitivity), prior enrollment-attempt history,
        // recent engagement responsiveness, and care-team-relationship
        // signals.
        likelihood_job = SageMaker.CreateTransformJob(
            transform_job_name = "likelihood-" + program_id + "-" + run_date,
            model_name         = LIKELIHOOD_MODEL_NAMES[program_id],
            transform_input    = candidate_path,
            transform_output   = "s3://cm-scores/run_date=" + run_date +
                                 "/likelihood/" + program_id + "/",
            instance_type      = "ml.m5.large",
            instance_count     = 1
        )
        job_handles.append(likelihood_job)

        // Stage C: engagement-prediction scoring (post-enrollment).
        // Per-program model predicting probability the patient remains
        // engaged through program completion given enrollment. Used
        // both for priority synthesis and for setting expectations
        // during enrollment outreach.
        engagement_job = SageMaker.CreateTransformJob(
            transform_job_name = "engagement-" + program_id + "-" + run_date,
            model_name         = ENGAGEMENT_MODEL_NAMES[program_id],
            transform_input    = candidate_path,
            transform_output   = "s3://cm-scores/run_date=" + run_date +
                                 "/engagement/" + program_id + "/",
            instance_type      = "ml.m5.large",
            instance_count     = 1
        )
        job_handles.append(engagement_job)

    wait_for_jobs(job_handles)

    // Stage D: program-fit scoring. Combines a hard-coded
    // theory-of-change-alignment score with a learned component.
    // The hard-coded part encodes program semantics: a patient with
    // primary HF as the actionable problem has high HF-program fit;
    // a patient with multi-system complexity has high complex-care
    // fit; a recently-discharged patient has high transitional-care
    // fit during the post-discharge window.
    FOR each candidate in eligible:
        uplift = read_uplift_score(candidate, run_date)
            // { point_estimate, ci_low, ci_high }
        likelihood = read_likelihood_score(candidate, run_date)
        engagement = read_engagement_score(candidate, run_date)
        fit_score = compute_program_fit(candidate, candidate.program_id)
            // hard-coded + learned; values [0, 1]
            // examples of hard-coded rules:
            //   transitional_care: fit = 1.0 if discharge < 7 days,
            //                          0.7 if 7-14, 0.3 if 14-30, 0.0 if >30
            //   heart_failure_program: fit = 0.9 if HF is the primary
            //                              actionable problem;
            //                          0.4 if HF + 3+ other major
            //                              actionable problems (consider
            //                              complex-care instead)
            //   complex_care: fit ranges with multi-system score

        cohort_features = lookup_cohort_features(candidate.patient_id)

        // Priority synthesis. Policy weights live in versioned config:
        // {
        //   uplift:               0.45,  // dominant: this is the
        //                                  // counterfactual benefit
        //   enrollment_likelihood: 0.20,  // can't help if not enrolled
        //   program_fit:          0.20,  // matters for downstream
        //                                  // engagement and outcome
        //   post_enrollment_engagement: 0.15
        // }
        priority = (policy.weights.uplift              * normalize(uplift.point_estimate) +
                    policy.weights.enrollment_likelihood * likelihood +
                    policy.weights.program_fit         * fit_score +
                    policy.weights.post_enrollment_engagement * engagement)

        priority_components = {
            uplift_contrib:             policy.weights.uplift * normalize(uplift.point_estimate),
            uplift_uncertainty:         uplift.ci_high - uplift.ci_low,
            likelihood_contrib:         policy.weights.enrollment_likelihood * likelihood,
            fit_contrib:                policy.weights.program_fit * fit_score,
            engagement_contrib:         policy.weights.post_enrollment_engagement * engagement
        }

        DynamoDB.UpdateItem("patient-program-state",
            key = (candidate.patient_id, candidate.program_id),
            updates = {
                uplift_score:         uplift,
                enrollment_likelihood: likelihood,
                engagement_prediction: engagement,
                fit_score:            fit_score,
                priority:             priority,
                priority_components:  priority_components,
                cohort_features:      cohort_features,
                policy_version:       policy.policy_version,
                last_enrichment_date: run_date
            })

    RETURN read_enriched_candidates(eligible, run_date)
```


**Step 3: Multi-stage enrollment allocation with capacity, equity, and operational-feasibility constraints.** The orchestrator runs in stages so program semantics are respected: time-sensitive transitional-care first, disease-specific high-fit second, complex-care third, parallel add-ons fourth. Within each stage, allocation is greedy-by-priority subject to capacity and equity constraints. Skip the multi-stage structure and you produce allocations that ignore the most important property of care management: that programs are designed for specific theories of change.

```
FUNCTION allocate_enrollments(enriched_candidates, run_date, policy):
    // Per-program capacity counters from registry-stated capacity minus
    // current active enrollments.
    capacity_remaining = {}
    equity_remaining = {}
    FOR each program in policy.programs:
        active_enrollments = count_active_enrollments(program.program_id)
        capacity_remaining[program.program_id] = (program.target_active_capacity -
                                                   active_enrollments)
        equity_remaining[program.program_id] = {}
        FOR floor_cohort, floor_count in policy.equity_floors[program.program_id]:
            equity_remaining[program.program_id][floor_cohort] = floor_count

    // Per-patient single-active-primary-program counter. A patient is
    // not in two competing primary programs simultaneously, but parallel
    // add-ons (polypharmacy, behavioral-health) can stack on top of a
    // primary. The registry tags each program as 'primary' or 'add_on'.
    patient_primary_assigned = {}
    patient_add_on_count = {}

    allocated = []

    // Stage 1: time-sensitive programs (transitional care after
    // discharge). Time-sensitive programs are prioritized because a
    // delayed enrollment is a structurally weaker enrollment (the
    // first 7-14 days post-discharge are the highest-leverage window).
    time_sensitive_programs = filter(policy.programs, is_time_sensitive = true)
    stage1_candidates = filter(enriched_candidates,
                                program_id in time_sensitive_programs)
    stage1_sorted = sort stage1_candidates by priority DESC

    allocated += allocate_stage(stage1_sorted, capacity_remaining,
                                equity_remaining, patient_primary_assigned,
                                patient_add_on_count, policy,
                                stage_name = "time_sensitive")

    // Stage 2: disease-specific programs for patients with high
    // theory-of-change fit. The fit score is the gating filter:
    // a patient with HF among many other things has lower HF-program
    // fit and is held for stage 3 (complex-care).
    disease_programs = filter(policy.programs,
                               category = "disease_specific",
                               is_time_sensitive = false)
    stage2_candidates = filter(enriched_candidates,
                                program_id in disease_programs,
                                fit_score >= policy.disease_fit_threshold,
                                patient_id NOT IN patient_primary_assigned)
    stage2_sorted = sort stage2_candidates by priority DESC

    allocated += allocate_stage(stage2_sorted, capacity_remaining,
                                equity_remaining, patient_primary_assigned,
                                patient_add_on_count, policy,
                                stage_name = "disease_specific")

    // Stage 3: complex-care for residual high-uplift patients who
    // didn't fit a disease-specific program. These are the patients
    // whose problem profile is heterogeneous enough that complex-care
    // is the right fit.
    complex_programs = filter(policy.programs, category = "complex_care")
    stage3_candidates = filter(enriched_candidates,
                                program_id in complex_programs,
                                patient_id NOT IN patient_primary_assigned)
    stage3_sorted = sort stage3_candidates by priority DESC

    allocated += allocate_stage(stage3_sorted, capacity_remaining,
                                equity_remaining, patient_primary_assigned,
                                patient_add_on_count, policy,
                                stage_name = "complex_care")

    // Stage 4: parallel add-on programs (polypharmacy, behavioral-health
    // integration). Add-ons stack on top of a primary enrollment, with
    // a per-patient cap on total parallel programs (typically 1-2 at
    // most beyond the primary).
    add_on_programs = filter(policy.programs, category = "add_on")
    stage4_candidates = filter(enriched_candidates,
                                program_id in add_on_programs)
    stage4_sorted = sort stage4_candidates by priority DESC

    allocated += allocate_stage(stage4_sorted, capacity_remaining,
                                equity_remaining, patient_primary_assigned,
                                patient_add_on_count, policy,
                                stage_name = "add_on")

    // Persist recommendations and transition state machine to
    // 'recommended' for downstream outreach.
    FOR row in allocated:
        DynamoDB.UpdateItem("patient-program-state",
            key = (row.patient_id, row.program_id),
            updates = {
                state:                "recommended",
                state_history:        previous_state_history.append({
                                          event: "transitioned_eligible_to_recommended",
                                          timestamp: run_date,
                                          stage: row.stage_name,
                                          allocation_reason: row.allocation_reason
                                      }),
                recommended_run_date: run_date,
                allocation_reason:    row.allocation_reason,
                policy_version:       policy.policy_version
            })

        Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
            event_type:        "program_recommended",
            patient_id:        row.patient_id,
            program_id:        row.program_id,
            stage:             row.stage_name,
            priority:          row.priority,
            priority_components: row.priority_components,
            allocation_reason: row.allocation_reason,
            cohort_features:   row.cohort_features,
            policy_version:    policy.policy_version,
            run_date:          run_date,
            timestamp:         current UTC timestamp
        })

    DynamoDB.BatchWriteItem("recommendation-log", allocated)
    RETURN allocated


FUNCTION allocate_stage(candidates_sorted, capacity_remaining,
                         equity_remaining, patient_primary_assigned,
                         patient_add_on_count, policy, stage_name):
    stage_allocated = []
    FOR candidate in candidates_sorted:
        program = lookup_program(candidate.program_id)

        // Capacity check.
        IF capacity_remaining[program.program_id] <= 0:
            CONTINUE

        // Per-patient primary-program constraint.
        IF program.category != "add_on" AND
           candidate.patient_id in patient_primary_assigned:
            CONTINUE

        // Per-patient add-on cap.
        IF program.category == "add_on" AND
           patient_add_on_count.get(candidate.patient_id, 0) >= policy.max_add_ons_per_patient:
            CONTINUE

        // Operational feasibility: language, geography, modality.
        IF NOT operational_feasible(candidate, program):
            CONTINUE

        // Cross-recipe coordination check (4.4 wellness, 4.5 adherence,
        // 4.6 care-gap). Some combinations should not be enrolled
        // simultaneously. The cross-recipe coordination policy lives
        // in shared chapter-level config.
        IF cross_recipe_conflicts(candidate, program):
            CONTINUE

        // Equity floor: if the candidate is in a floor cohort and there
        // is reserved capacity, prefer using floor capacity.
        cohort_features = candidate.cohort_features
        applicable_floors = applicable_floor_cohorts(cohort_features,
                                                      policy.equity_floors[program.program_id])
        used_floor = null
        FOR floor_cohort in applicable_floors:
            IF equity_remaining[program.program_id][floor_cohort] > 0:
                equity_remaining[program.program_id][floor_cohort] -= 1
                used_floor = floor_cohort
                BREAK

        // Allocate.
        capacity_remaining[program.program_id] -= 1
        IF program.category == "add_on":
            patient_add_on_count[candidate.patient_id] = (
                patient_add_on_count.get(candidate.patient_id, 0) + 1)
        ELSE:
            patient_primary_assigned[candidate.patient_id] = program.program_id

        stage_allocated.append({
            patient_id:        candidate.patient_id,
            program_id:        program.program_id,
            stage_name:        stage_name,
            priority:          candidate.priority,
            priority_components: candidate.priority_components,
            allocation_reason: reason_string(candidate, used_floor, stage_name),
            cohort_features:   cohort_features,
            uplift_estimate:   candidate.uplift_score
        })

    RETURN stage_allocated
```

**Step 4: Generate the care-manager enrollment briefing and dispatch outreach.** Once a recommendation is made, the care management team needs a readable briefing before the initial outreach call. The briefing distills the deterministic ranker's choice plus the patient's clinical and social context into a paragraph the care manager can read in 30 seconds. Skip the briefing and the care manager goes into the call cold, which produces lower enrollment-conversion and worse rapport on the calls that succeed.

```
FUNCTION dispatch_outreach(allocated_recommendations, run_date):
    FOR row in allocated_recommendations:
        // Build the structured briefing context. De-identify before
        // the LLM call; re-attach identifiers in the persisted briefing.
        briefing_context = {
            patient_summary:           build_clinical_summary(row.patient_id),
                // de-identified: condition list, recent trajectory,
                // key recent events, current medications, SDOH proxies
            program_id:                row.program_id,
            program_name:              lookup_program_name(row.program_id),
            program_theory_of_change:  lookup_program_theory_of_change(row.program_id),
            uplift_estimate:           row.uplift_estimate,
                // includes confidence interval; the briefing should
                // communicate uncertainty honestly
            enrollment_likelihood:     row.priority_components.likelihood_contrib,
            anticipated_barriers:      lookup_barriers(row.patient_id),
                // from 4.5: cost, language, transportation, beliefs
            recent_clinical_events:    lookup_recent_events(row.patient_id, days = 90),
            cross_program_context:     lookup_other_program_state(row.patient_id),
            allocation_reason:         row.allocation_reason
        }

        briefing = Bedrock.InvokeModel(
            model_id = ENROLLMENT_BRIEFING_MODEL_ID,
            body     = build_briefing_prompt(briefing_context, BRIEFING_OUTPUT_SCHEMA)
        )
        briefing_parsed = parse_json(briefing.completion)
            // { headline, lead_with, anticipated_concerns,
            //   social_context_that_matters, suggested_modality,
            //   suggested_outreach_window, confidence_notes }

        validate_briefing(briefing_parsed, observed_context = briefing_context)
            // <!-- TODO (TechWriter): Specify validate_briefing's
            // four-layer structure: (1) schema and length, (2) every
            // referenced clinical fact must appear in observed_context
            // (the LLM cannot hallucinate diagnoses or events), (3)
            // prohibited content (PHI not in source, prescriber names
            // other than the patient's, suggestions that override the
            // deterministic program assignment), (4) required notes
            // ("subject to clinical judgment", briefing is advisory,
            // patient consent required for enrollment). Failure
            // handling: replace with templated fallback that lists
            // the structured context without LLM narration; log for
            // prompt-engineering review. -->

        DynamoDB.PutItem("enrollment-briefings", {
            briefing_id:        build_briefing_id(row, run_date),
            patient_id:         row.patient_id,
            program_id:         row.program_id,
            briefing_text:      briefing_parsed,
            briefing_context:   briefing_context,
            allocation_reason:  row.allocation_reason,
            policy_version:     row.policy_version,
            generated_at:       run_date
        })

        // Route to care-management work queue. Routing respects
        // language, condition specialization, and per-care-manager
        // workload.
        cm_assignment = route_to_care_manager(row, lookup_cm_pool(row.program_id))

        DynamoDB.PutItem("outreach-state", {
            outreach_id:        new UUID,
            patient_id:         row.patient_id,
            program_id:         row.program_id,
            briefing_id:        build_briefing_id(row, run_date),
            assigned_to:        cm_assignment.cm_id,
            state:              "queued",
            attempts:           [],
            created_at:         run_date,
            policy_version:     row.policy_version
        })

        DynamoDB.UpdateItem("patient-program-state",
            key = (row.patient_id, row.program_id),
            updates = {
                state:                "outreach_in_progress",
                state_history:        previous_state_history.append({
                                          event: "transitioned_recommended_to_outreach",
                                          timestamp: run_date,
                                          assigned_to: cm_assignment.cm_id
                                      })
            })

        Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
            event_type:    "program_outreach_initiated",
            patient_id:    row.patient_id,
            program_id:    row.program_id,
            assigned_to:   cm_assignment.cm_id,
            briefing_id:   build_briefing_id(row, run_date),
            timestamp:     current UTC timestamp
        })


FUNCTION record_outreach_attempt(outreach_id, attempt_result):
    // attempt_result is one of:
    //   { result: "consented", consent_form_id, baseline_assessment_id }
    //   { result: "declined", reason }
    //   { result: "unreachable", attempt_count, next_attempt_scheduled }
    //   { result: "deferred", reason, defer_until }
    //
    // <!-- TODO (TechWriter): Expert Review HIGH A1 (chapter-wide
    // pattern propagated unresolved through 4.4-4.7). Add a counter
    // decrement on the patient-profile attribute
    // cm_outreach_recent_30d_count for the terminal-unreachable,
    // declined, and deferred outcomes; otherwise the 4.7-specific
    // outreach budget accumulates phantom counter consumption that
    // silences the patient from future enrollment outreach for 30
    // days when the original outreach never reached the patient.
    // The pathology disproportionately affects cohorts with flaky
    // channels (transient housing, prepaid phones with intermittent
    // service, language-mismatch with assigned care manager) which
    // correlate with the cohorts the equity floors are trying to
    // protect. Coordinate the implementation with the parallel 4.4,
    // 4.5, 4.6 fixes; the chapter editor should land all four
    // together. The Python companion's record_outreach_attempt
    // unreachable-terminal branch already attempts the decrement but
    // currently fails (Code Review ERROR 2: missing :zero placeholder
    // and ExpressionAttributeNames=None); fix both at once. Also add
    // a stale-pending sweep Lambda (hourly): for outreach-state rows
    // where state == "queued" or state == "outreach_in_progress" and
    // created_at > 7 days ago with no engagement-event activity, mark
    // state = "stale_no_activity" and decrement the counter. -->
    outreach = DynamoDB.GetItem("outreach-state", outreach_id)
    outreach.attempts.append({
        attempt_at:  current UTC timestamp,
        result:      attempt_result.result,
        details:     attempt_result
    })

    BRANCH on attempt_result.result:
        CASE "consented":
            outreach.state = "consented"
            DynamoDB.UpdateItem("patient-program-state",
                key = (outreach.patient_id, outreach.program_id),
                updates = {
                    state: "enrolled",
                    state_history: previous_state_history.append({
                        event: "transitioned_outreach_to_enrolled",
                        timestamp: current UTC timestamp,
                        consent_form_id: attempt_result.consent_form_id
                    }),
                    enrollment_metadata: {
                        enrolled_at: current UTC timestamp,
                        consent_form_id: attempt_result.consent_form_id,
                        baseline_assessment_id: attempt_result.baseline_assessment_id,
                        target_duration: lookup_target_duration(outreach.program_id)
                    }
                })

        CASE "declined":
            outreach.state = "declined"
            DynamoDB.UpdateItem("patient-program-state",
                key = (outreach.patient_id, outreach.program_id),
                updates = {
                    state: "declined",
                    state_history: previous_state_history.append({
                        event: "transitioned_outreach_to_declined",
                        timestamp: current UTC timestamp,
                        decline_reason: attempt_result.reason
                    })
                })

        CASE "unreachable":
            outreach.state = "unreachable_pending_retry"
            IF attempt_result.attempt_count >= POLICY.max_outreach_attempts:
                outreach.state = "unreachable_terminal"
                DynamoDB.UpdateItem("patient-program-state",
                    key = (outreach.patient_id, outreach.program_id),
                    updates = {
                        state: "outreach_failed",
                        state_history: previous_state_history.append({
                            event: "transitioned_outreach_to_failed",
                            timestamp: current UTC timestamp,
                            attempts: attempt_result.attempt_count
                        })
                    })

        CASE "deferred":
            outreach.state = "deferred"
            DynamoDB.UpdateItem("patient-program-state",
                key = (outreach.patient_id, outreach.program_id),
                updates = {
                    state: "deferred",
                    deferred_until: attempt_result.defer_until,
                    state_history: previous_state_history.append({
                        event: "transitioned_outreach_to_deferred",
                        timestamp: current UTC timestamp,
                        defer_until: attempt_result.defer_until,
                        defer_reason: attempt_result.reason
                    })
                })

    DynamoDB.PutItem("outreach-state", outreach)

    Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
        event_type:    "program_outreach_attempted",
        outreach_id:   outreach_id,
        patient_id:    outreach.patient_id,
        program_id:    outreach.program_id,
        result:        attempt_result.result,
        timestamp:     current UTC timestamp
    })
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter04.07-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.


**Step 5: Track in-program engagement and trigger retention when engagement declines.** Once a patient is enrolled, the engagement scorer runs against the program-specific engagement profile. Below threshold, the retention worker activates. Skip the engagement tracking and you discover at month three that the patient stopped engaging at month one and the program slot has been wasted.

```
FUNCTION score_engagement(patient_id, program_id, run_date):
    enrollment = DynamoDB.GetItem("patient-program-state",
                                   key = (patient_id, program_id)).enrollment_metadata
    program = lookup_program(program_id)

    // Pull the engagement profile for this (patient, program). Profiles
    // are program-specific: HF program profile is weekly check-in
    // attendance + weight-monitoring submission rate; complex-care
    // profile is monthly visit attendance + care-plan-goal progress;
    // polypharmacy profile is session attendance + prescriber-action
    // follow-through.
    profile = build_engagement_profile(patient_id, program_id, run_date)
        // {
        //   scheduled_contacts:           [...],
        //   completed_contacts:           [...],
        //   missed_contacts:              [...],
        //   self_reported_data_submissions: [...],
        //   education_modules_completed:  [...],
        //   recent_clinical_events:       [...]
        // }

    // Compute engagement score per program's scoring function.
    engagement_score = program.engagement_scoring_function(profile)
        // continuous, [0, 1]; 0 = no engagement, 1 = full engagement

    // Threshold check.
    threshold = program.at_risk_threshold
    is_at_risk = engagement_score < threshold

    // Classification of engagement decline (if at-risk):
    decline_pattern = null
    IF is_at_risk:
        decline_pattern = classify_decline(profile)
            // values:
            //   'no_initial_engagement': never engaged after enrollment
            //   'gradual_drop_off': engagement declined steadily
            //   'event_driven_drop': engagement dropped after specific event
            //                       (admission, life event, season change)
            //   'modality_mismatch': engagement low on assigned modality;
            //                        signal that a different modality might work
            //   'staffing_disruption': care-manager change, vacation, transition

    DynamoDB.UpdateItem("engagement-state",
        key = (patient_id, program_id),
        updates = {
            engagement_score:    engagement_score,
            engagement_profile:  profile,
            is_at_risk:          is_at_risk,
            decline_pattern:     decline_pattern,
            last_scored_at:      run_date
        })

    IF is_at_risk:
        Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
            event_type:        "program_at_risk",
            patient_id:        patient_id,
            program_id:        program_id,
            engagement_score:  engagement_score,
            decline_pattern:   decline_pattern,
            timestamp:         current UTC timestamp
        })
        trigger_retention(patient_id, program_id, decline_pattern)


FUNCTION trigger_retention(patient_id, program_id, decline_pattern):
    // Retention strategies are program-specific and decline-pattern-specific.
    BRANCH on decline_pattern:
        CASE "no_initial_engagement":
            // The patient consented but never engaged after the first
            // outreach. Try once with a different care manager and a
            // different modality before giving up.
            schedule_retention_attempt(patient_id, program_id,
                strategy = "fresh_cm_different_modality",
                attempt_within_days = 7)

        CASE "gradual_drop_off":
            // Engagement is fading. A direct check-in conversation
            // about whether the program is still useful is the right
            // move; the conversation may surface barriers that can
            // be addressed.
            schedule_retention_attempt(patient_id, program_id,
                strategy = "engagement_check_in_conversation",
                attempt_within_days = 5)

        CASE "event_driven_drop":
            // Something happened (admission, family crisis, change in
            // condition). The retention attempt addresses the event,
            // not the engagement metric directly.
            schedule_retention_attempt(patient_id, program_id,
                strategy = "event_acknowledgment_and_recalibration",
                attempt_within_days = 3)

        CASE "modality_mismatch":
            // The patient consented to telephonic but isn't picking up;
            // try video, SMS-first, or in-person if available.
            schedule_retention_attempt(patient_id, program_id,
                strategy = "modality_switch",
                attempt_within_days = 7)

        CASE "staffing_disruption":
            // The disruption is on the program side. Address it
            // operationally rather than treating it as patient
            // disengagement.
            schedule_continuity_recovery(patient_id, program_id)


FUNCTION evaluate_disenrollment(patient_id, program_id, run_date):
    // Disenrollment decisions are run on a separate cadence (typically
    // weekly) for at-risk patients whose retention attempts have not
    // succeeded. The decision is decision-supported, not autonomous;
    // a human (clinical lead, program manager) makes the actual call.
    //
    // <!-- TODO (TechWriter): Expert Review HIGH A2. The
    // data_quality_flag is computed in Step 1, persisted to
    // patient-program-state, and named in Where It Struggles as a
    // signal that "downstream consumers (specifically the
    // disenrollment evaluator) should gate harder when quality is
    // low." The pseudocode below does not gate. For
    // cross_provider_fragmentation and multi_source_disagreement
    // patients, the engagement profile may appear worse than it
    // actually is because the patient is engaging through encounters
    // the recommender's data feed does not see; a
    // disenroll_for_no_engagement recommendation against fragmented
    // data has civil-rights implications when it concentrates in
    // protected cohorts (mobile populations, recent plan-changers,
    // patients seen across multiple practices). Add a
    // verify_engagement_first action that runs before
    // disenroll_for_no_engagement when state.data_quality_flag is in
    // {"cross_provider_fragmentation", "multi_source_disagreement"}.
    // Mirror the gating language at five additional sites: Step 2
    // response enrichment (widen uplift CI on non-complete cases),
    // Step 3 orchestrator (route fragmented-data patients through
    // verification-first allocation), Step 4 briefing
    // (data_quality_caveat in confidence_notes), Step 5 engagement
    // scoring (widen CI on the score; require multi-source
    // consistency for is_at_risk = true), and Step 6 cross-program
    // transition recommender (flag the recommendation with
    // data_quality_caveat). Same chapter-wide pattern as 4.5
    // Finding A2 and 4.6 Finding A2; the chapter editor should land
    // all three together. -->
    state = DynamoDB.GetItem("patient-program-state",
                              key = (patient_id, program_id))
    engagement = DynamoDB.GetItem("engagement-state",
                                   key = (patient_id, program_id))
    enrollment = state.enrollment_metadata

    days_since_enrollment = run_date - enrollment.enrolled_at.date
    days_since_last_engagement = run_date - last_engagement_date(engagement)

    // Decision policy. Earlier in the program, retention is preferred;
    // later, partial-credit graduation may be appropriate. For-cause
    // disenrollment is reserved for sustained no-engagement after
    // multiple retention attempts.
    IF engagement.is_at_risk AND
       count_failed_retention_attempts(patient_id, program_id) >= POLICY.max_retention_attempts AND
       days_since_last_engagement >= POLICY.disenroll_no_engagement_days:
        recommended_action = "disenroll_for_no_engagement"
    ELSE IF days_since_enrollment >= enrollment.target_duration:
        // Program duration met or exceeded.
        IF goals_substantially_met(patient_id, program_id):
            recommended_action = "graduate"
        ELSE IF engagement.is_at_risk:
            recommended_action = "disenroll_did_not_complete"
        ELSE:
            recommended_action = "extend_or_transition"
                // engaged but not yet meeting goals; consider extension
                // or cross-program transition to a maintenance pathway
    ELSE IF clinical_deterioration_detected(patient_id, program_id):
        // Patient deteriorated during enrollment beyond the program's
        // theory of change; consider transition to higher-acuity
        // program (e.g., disease-specific to complex-care).
        recommended_action = "transition_to_higher_acuity"
    ELSE:
        recommended_action = "continue"

    IF recommended_action != "continue":
        // Generate a decision-support rationale via LLM.
        rationale_context = {
            patient_summary:           build_clinical_summary(patient_id),
            program_id:                program_id,
            enrollment_metadata:       enrollment,
            engagement_history:        engagement.engagement_profile,
            recent_clinical_events:    lookup_recent_events(patient_id, days = 90),
            recommended_action:        recommended_action,
            policy_rule_triggered:     describe_triggering_rule(recommended_action,
                                                                   engagement,
                                                                   enrollment, run_date)
        }
        rationale = Bedrock.InvokeModel(
            model_id = DISENROLLMENT_RATIONALE_MODEL_ID,
            body     = build_rationale_prompt(rationale_context, RATIONALE_OUTPUT_SCHEMA)
        )
        rationale_parsed = parse_json(rationale.completion)
            // { headline, evidence_summary, countervailing_factors,
            //   policy_rule, suggested_human_review_questions }

        validate_rationale(rationale_parsed, observed_context = rationale_context)
            // <!-- TODO (TechWriter): Specify validate_rationale layers
            // mirroring the chapter-wide validator pattern. Failures
            // fall back to a templated rationale that lists the
            // policy-rule trigger and the engagement-history evidence
            // without LLM narration. -->

        DynamoDB.PutItem("disenrollment-decisions", {
            decision_id:           new UUID,
            patient_id:            patient_id,
            program_id:            program_id,
            recommended_action:    recommended_action,
            rationale:             rationale_parsed,
            rationale_context:     rationale_context,
            human_review_pending:  true,
            recommended_at:        run_date
        })

        Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
            event_type:        "disenrollment_decision_recommended",
            patient_id:        patient_id,
            program_id:        program_id,
            recommended_action: recommended_action,
            timestamp:         current UTC timestamp
        })
```

**Step 6: Process the human disenrollment decision and handle cross-program transitions and post-graduation observation.** A clinical lead or program manager reviews the recommendation and decides; the system then transitions state and triggers downstream cross-program logic. Skip the post-graduation observation and you lose patients to relapse without any visibility, undermining the whole point of program graduation.

```
FUNCTION process_disenrollment_decision(decision_id, human_decision):
    // human_decision is one of:
    //   { decision: "approve", recommended_action }
    //   { decision: "override", actual_action, override_reason }
    decision = DynamoDB.GetItem("disenrollment-decisions", decision_id)
    final_action = (decision.recommended_action if human_decision.decision == "approve"
                                                  else human_decision.actual_action)

    BRANCH on final_action:
        CASE "graduate":
            DynamoDB.UpdateItem("patient-program-state",
                key = (decision.patient_id, decision.program_id),
                updates = {
                    state: "graduated",
                    state_history: previous_state_history.append({
                        event: "transitioned_enrolled_to_graduated",
                        timestamp: current UTC timestamp,
                        decision_id: decision_id
                    }),
                    graduation_metadata: {
                        graduated_at: current UTC timestamp,
                        post_graduation_observation_window:
                            POLICY.post_graduation_observation_days,
                        post_graduation_relapse_signals: []
                    }
                })
            // Trigger cross-program transition recommendation: the
            // graduate may benefit from a maintenance pathway (e.g., HF
            // graduate -> light-touch-monitoring) or a complementary
            // program (e.g., HF graduate with new diabetes signals ->
            // DM program).
            recommend_cross_program_transitions(decision.patient_id,
                                                  prior_program_id = decision.program_id,
                                                  context = "graduation")

        CASE "disenroll_for_no_engagement":
            DynamoDB.UpdateItem("patient-program-state",
                key = (decision.patient_id, decision.program_id),
                updates = {
                    state: "disenrolled_for_cause",
                    state_history: previous_state_history.append({
                        event: "transitioned_enrolled_to_disenrolled_for_cause",
                        timestamp: current UTC timestamp,
                        decision_id: decision_id
                    }),
                    disenrollment_metadata: {
                        disenrolled_at: current UTC timestamp,
                        reason: "no_engagement_after_retention",
                        re_eligibility_window_days: POLICY.re_eligibility_window_for_no_engagement
                    }
                })

        CASE "disenroll_did_not_complete":
            DynamoDB.UpdateItem("patient-program-state",
                key = (decision.patient_id, decision.program_id),
                updates = {
                    state: "disenrolled_incomplete",
                    state_history: previous_state_history.append({
                        event: "transitioned_enrolled_to_disenrolled_incomplete",
                        timestamp: current UTC timestamp,
                        decision_id: decision_id
                    })
                })

        CASE "transition_to_higher_acuity":
            // Mid-program escalation. Disenroll from current program
            // (with completed-portion noted) and immediately recommend
            // higher-acuity program enrollment.
            DynamoDB.UpdateItem("patient-program-state",
                key = (decision.patient_id, decision.program_id),
                updates = {
                    state: "transitioned_out",
                    state_history: previous_state_history.append({
                        event: "transitioned_enrolled_to_transitioned_out",
                        timestamp: current UTC timestamp,
                        decision_id: decision_id,
                        reason: "deterioration_during_enrollment"
                    })
                })
            recommend_cross_program_transitions(decision.patient_id,
                                                  prior_program_id = decision.program_id,
                                                  context = "deterioration")

        CASE "extend_or_transition":
            DynamoDB.UpdateItem("patient-program-state",
                key = (decision.patient_id, decision.program_id),
                updates = {
                    state: "enrolled_extended",
                    enrollment_metadata.target_duration:
                        enrollment_metadata.target_duration + POLICY.extension_days,
                    state_history: previous_state_history.append({
                        event: "extended",
                        timestamp: current UTC timestamp,
                        decision_id: decision_id
                    })
                })

    DynamoDB.UpdateItem("disenrollment-decisions",
        key = decision_id,
        updates = {
            human_review_pending: false,
            human_decision:       human_decision,
            final_action:         final_action,
            resolved_at:          current UTC timestamp
        })


FUNCTION post_graduation_observation(run_date):
    // Daily sweep of recently graduated patients within their
    // observation window. Watch for relapse signals (admission,
    // ED visit, abnormal lab, missed follow-up appointment, sharp
    // engagement drop on related ongoing programs).
    recently_graduated = DynamoDB.Query(
        "patient-program-state",
        filter = "state = :graduated AND graduation_metadata.graduated_at >= :cutoff",
        params = { :graduated: "graduated",
                   :cutoff: run_date - MAX_OBSERVATION_DAYS }
    )

    FOR each row in recently_graduated:
        relapse_signals = detect_relapse_signals(row.patient_id,
                                                   row.program_id,
                                                   row.graduation_metadata.graduated_at)
            // signals: admission, ED visit, abnormal lab,
            //          missed follow-up, adherence drop, weight gain
            //          (HF), sharp engagement drop on parallel programs

        IF len(relapse_signals) > 0:
            DynamoDB.UpdateItem("patient-program-state",
                key = (row.patient_id, row.program_id),
                updates = {
                    state: "in_observation_relapse_detected",
                    graduation_metadata.post_graduation_relapse_signals:
                        relapse_signals
                })

            // Re-eligibility evaluation runs immediately rather than
            // waiting for the next eligibility cycle. The patient may
            // be a candidate for re-enrollment, transition to a
            // higher-acuity program, or temporary watchful waiting.
            Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
                event_type:        "post_graduation_relapse_detected",
                patient_id:        row.patient_id,
                prior_program_id:  row.program_id,
                relapse_signals:   relapse_signals,
                timestamp:         current UTC timestamp
            })


FUNCTION recommend_cross_program_transitions(patient_id, prior_program_id, context):
    // Evaluate the patient's current eligibility and uplift across all
    // programs. Identify candidate transitions and surface them to the
    // care management team for decisioning.
    current_eligibility = read_current_eligibility(patient_id)
    current_uplifts = read_current_uplifts(patient_id)
    candidates = []
    FOR each program_id, eligibility in current_eligibility:
        IF eligibility != "eligible":
            CONTINUE
        IF program_id == prior_program_id:
            CONTINUE
        priority = synthesize_priority(current_uplifts[program_id], context)
        candidates.append({
            program_id: program_id,
            priority:   priority,
            context:    context
        })
    candidates_sorted = sort candidates by priority DESC

    IF len(candidates_sorted) > 0:
        top_candidate = candidates_sorted[0]
        DynamoDB.PutItem("cross-program-transitions", {
            transition_id:       new UUID,
            patient_id:          patient_id,
            prior_program_id:    prior_program_id,
            recommended_program_id: top_candidate.program_id,
            context:             context,
            priority:            top_candidate.priority,
            recommended_at:      current UTC timestamp,
            human_review_pending: true
        })
        Kinesis.PutRecord(stream = "cm-engagement-stream", record = {
            event_type:               "cross_program_transition_recommended",
            patient_id:               patient_id,
            prior_program_id:         prior_program_id,
            recommended_program_id:   top_candidate.program_id,
            context:                  context,
            timestamp:                current UTC timestamp
        })
```

---

### Expected Results

**Sample patient program state record:**

```json
{
  "patient_id": "pat-002148",
  "program_id": "heart-failure-program",
  "program_version": "2026-v2",
  "eligibility": "eligible",
  "state": "enrolled",
  "state_history": [
    { "event": "transitioned_eligible_to_recommended", "timestamp": "2026-04-12", "stage": "disease_specific", "allocation_reason": "high_uplift_disease_fit" },
    { "event": "transitioned_recommended_to_outreach", "timestamp": "2026-04-15", "assigned_to": "cm-007" },
    { "event": "transitioned_outreach_to_enrolled", "timestamp": "2026-04-19", "consent_form_id": "consent-2026-04-19-pat-002148-hf" }
  ],
  "uplift_score": {
    "point_estimate": 0.18,
    "ci_low": 0.09,
    "ci_high": 0.27,
    "outcome": "90_day_readmission_probability_reduction"
  },
  "enrollment_likelihood": 0.62,
  "engagement_prediction": 0.71,
  "fit_score": 0.85,
  "priority": 0.62,
  "priority_components": {
    "uplift_contrib": 0.30,
    "uplift_uncertainty": 0.18,
    "likelihood_contrib": 0.12,
    "fit_contrib": 0.17,
    "engagement_contrib": 0.11
  },
  "enrollment_metadata": {
    "enrolled_at": "2026-04-19",
    "consent_form_id": "consent-2026-04-19-pat-002148-hf",
    "baseline_assessment_id": "baseline-2026-04-19-pat-002148-hf",
    "target_duration": 84
  },
  "cohort_features": {
    "engagement_history_quartile": "q3",
    "language": "en",
    "sdoh_cohort": "moderate_food_security",
    "age_band": "65-74"
  },
  "data_quality_flag": "complete",
  "policy_version": "cm-policy-v0.6"
}
```

**Sample care manager enrollment briefing:**

<!-- TODO (TechWriter): the briefing's social-context details (Medicare donut hole, grandchildren-care responsibilities, no home scale, Spanish-preferred written materials) are additive context not present in the opening vignette of Linda. Either fold the corresponding details into the vignette so the briefing reads as a faithful synthesis, or add a one-line note in The Problem section that the briefing in Expected Results includes care-management-relevant context surfaced from the patient profile beyond what the vignette establishes. Editor renamed Mr. Garcia to Linda for continuity (per expert review V2); the social-context reconciliation is the remaining piece. -->

```json
{
  "briefing_id": "brief-2026-04-15-pat-002148-hf",
  "patient_id": "pat-002148",
  "program_id": "heart-failure-program",
  "headline": "HF program candidate after recent decompensation; cost concerns likely; daughter is engaged.",
  "lead_with": "Linda was admitted in February for HF decompensation that started after she ran out of furosemide. The HF program's weekly check-ins and daily-weight monitoring directly address that pattern. Lead with the connection to keeping her out of the hospital, not with the program structure.",
  "anticipated_concerns": [
    "Cost of additional medications (she's a Medicare beneficiary in donut hole most of the year; LIS not enrolled).",
    "Concern about additional appointments competing with grandchildren-care responsibilities.",
    "Uncertainty about whether she can do daily weights reliably (no scale at home; the program covers a Bluetooth scale)."
  ],
  "social_context_that_matters": "Lives alone in a fourth-floor walkup with intermittent elevator. Daughter visits weekends and is documented as a willing care partner. Spanish is preferred for written materials; verbal communication in English is fine.",
  "suggested_modality": "telephonic for first contact; transition to video for week-three care-plan review when daughter can participate.",
  "suggested_outreach_window": "weekday mornings; she's typically home then.",
  "confidence_notes": "Uplift estimate has wide CI (0.09-0.27); the recommendation is to enroll, but expectations should be calibrated to a probabilistic improvement, not a guaranteed prevention.",
  "policy_version": "cm-policy-v0.6"
}
```

**Sample mid-program engagement record:**

```json
{
  "engagement_record_id": "eng-2026-05-10-pat-002148-hf",
  "patient_id": "pat-002148",
  "program_id": "heart-failure-program",
  "scoring_window": "2026-04-19_to_2026-05-10",
  "engagement_score": 0.78,
  "is_at_risk": false,
  "decline_pattern": null,
  "engagement_profile": {
    "scheduled_contacts": 4,
    "completed_contacts": 4,
    "missed_contacts": 0,
    "weight_submission_rate": 0.86,
    "education_modules_completed": 3,
    "recent_clinical_events": [
      { "event": "lab_BNP", "value": "412 pg/mL", "date": "2026-05-02", "trend": "down_from_baseline" }
    ]
  },
  "decision_support_summary": "Engagement is strong. BNP trending down. No retention action needed. Continue weekly check-ins; plan week-six medication-reconciliation visit on schedule."
}
```

**Sample quarterly outcome evaluation:**

```json
{
  "evaluation_id": "eval-2026Q1-heart-failure-program",
  "program_id": "heart-failure-program",
  "evaluation_window": "2025-10-01_to_2026-03-31",
  "method": "propensity_matched_difference_in_differences",
  "primary_outcome": "90_day_all_cause_readmission_rate",
  "ate": {
    "estimate": -0.064,
    "ci_95_low": -0.092,
    "ci_95_high": -0.036,
    "p_value": 0.0001,
    "interpretation": "Enrolled patients had a 90-day readmission rate ~6.4 percentage points lower than matched non-enrolled patients."
  },
  "ate_by_cohort": [
    { "cohort": "language=en", "estimate": -0.071, "ci_95_low": -0.103, "ci_95_high": -0.039 },
    { "cohort": "language=es", "estimate": -0.038, "ci_95_low": -0.082, "ci_95_high": 0.006 },
    { "cohort": "sdoh_cohort=transportation_barrier", "estimate": -0.024, "ci_95_low": -0.062, "ci_95_high": 0.014 }
  ],
  "secondary_outcomes": {
    "90_day_ed_visit_rate": { "estimate": -0.029, "ci_95": [-0.054, -0.004] },
    "180_day_total_cost_change": { "estimate": -1240, "ci_95": [-2110, -370], "currency": "USD" }
  },
  "uplift_calibration": {
    "predicted_uplift_quintiles": [0.04, 0.10, 0.16, 0.22, 0.31],
    "realized_uplift_quintiles": [0.02, 0.08, 0.15, 0.20, 0.27],
    "calibration_slope": 0.91,
    "interpretation": "Model is reasonably well-calibrated; mild over-estimation in higher quintiles."
  },
  "sample_size_treated": 412,
  "sample_size_control": 412,
  "program_cost": 740000,
  "value_of_avoided_admissions_180d": 1180000,
  "net_estimated_value": 440000,
  "roi_ratio": 1.59
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Risk-rank-only enrollment baseline | Recipe pipeline |
|--------|-----------------------------------|-----------------|
| Enrollment-conversion rate (recommended -> consented) | 25-40% | 45-60% |
| Per-program engagement rate at week 4 (enrolled patients still engaged) | 50-65% | 70-85% |
| Per-program graduation rate (enrolled patients reaching program completion) | 35-55% | 55-75% |
| Propensity-matched difference-in-differences in 90-day readmissions (HF program) | -1 to -3 pp | -4 to -8 pp |
| Per-cohort enrollment-rate parity (worst-served cohort vs. best-served) | 35-55% gap | 5-15% gap |
| End-to-end batch run time (250K members, 5 programs, weekly enrichment) | n/a | 3-5 hours |
| Care-manager outreach-to-enrollment conversion improvement | reference | +30 to +60% relative |
| Disenrollment-for-no-engagement rate | 15-25% | 6-12% |
| Cross-program transition recommendation acceptance rate | n/a | 60-80% |

<!-- TODO: the benchmarks above are illustrative ranges informed by published care management and HEDIS-program literature; replace with measured results from your deployment. Be wary of vendor-published numbers that report "X% reduction in admissions" without matched-control comparison and without confidence intervals. -->

**Where it struggles:**

- **Patients with sparse historical data.** A patient newly attributed to the practice or recently joined the plan has minimal prior engagement, prior enrollment, or prior outcome data. Cold-start cohort defaults are essential, and the recommender should weight patient-specific predictions less heavily for these patients until enough history accumulates. The `data_quality_flag` exposes this; downstream consumers (specifically the disenrollment evaluator) should gate harder when quality is low.
- **Programs with overlapping eligibility but conflicting theories of change.** A patient eligible for both heart-failure and complex-care programs can be a hard call: HF is the most actionable single condition, but the patient also has CKD, depression, and social complexity that complex-care addresses better. The fit-score logic forces a choice, but the choice is genuinely hard, and clinician override of the recommendation is appropriate often. Track override rate by (patient-profile, program-pair) to identify systematic miscalibration.
- **Recently graduated patients with relapse signals.** Post-graduation observation surfaces relapse signals, but the action is ambiguous: re-enroll the patient (capacity-cost), transition to a maintenance pathway (may not exist), or escalate to higher-acuity (consumes a complex-care slot). The system flags; the human decides; the failure mode is that the flag arrives but no slot is available.
- **Programs whose target outcomes are slow to materialize.** Diabetes management's primary outcome (A1c change) takes 3 to 6 months to read out; the response model trained on it has a long feedback loop. During the loop, the model is trained on stale data. Confidence intervals widen for slow-outcome programs; the orchestrator should apply additional uplift-uncertainty penalties for programs with delayed outcomes.
- **Cohort fairness in the response model.** If the historical enrollment data has systematically different engagement patterns by cohort (because the program structure historically didn't fit some cohorts), the response model encodes those patterns and predicts low uplift for cohorts the program could have served better with operational adjustments. Cohort-aware calibration and ongoing fairness monitoring are not nice-to-haves; they are how you avoid the Obermeyer failure mode at scale.
- **Program capacity that flexes during the year.** Care management staffing flexes (maternity leaves, vacations, hiring cycles, contract renegotiations). Capacity reductions can happen mid-cycle, leaving patients in the recommended state with no slot to enroll into. The orchestrator needs to handle capacity contraction gracefully rather than producing recommendations that operations cannot fulfill.
- **Cross-program coordination across vendor and in-house programs.** Plans often run a mix of in-house programs (Connect-based, internal staff) and vendor-delivered programs (third-party care management vendors). Cross-vendor visibility into engagement and outcomes can be poor, and the recommender's view of program state can diverge from the vendor's actual record. Contractual data-feed requirements are the durable fix.
- **Disenrollment-for-cause concentrated in protected cohorts.** If the disenrollment-for-no-engagement rate is materially higher in some cohorts than others, that disparity is a fairness concern and may have civil-rights implications. Equity instrumentation on disenrollment rates is required, and the disenrollment policy may need cohort-aware retention budget adjustments.
- **Operational fatigue from too many transition recommendations.** Cross-program transition recommendations after every graduation, every disenrollment, and every relapse signal can flood the care management team. Apply per-care-manager and per-program throttles; only the highest-priority transitions should reach the human review queue.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Program-registry curation as an ongoing program.** Like the measure registry in 4.6, the program registry is a living artifact. New programs launch, old programs sunset, capacities change quarterly with staffing, contractual obligations evolve, and clinical evidence shifts what each program does. Plan for at least 0.25 to 0.5 FTE of program-leadership and clinical-informatics time on registry maintenance ongoing, plus a structured change-management process with parallel evaluation against the prior version when significant changes ship.

**Causal-inference rigor for response models.** Most plans have observational data only (selection-biased enrollment history). Training response models on observational data without causal-inference tooling (propensity matching at minimum, doubly-robust estimation when feasible, randomized evaluation cohorts when possible) produces uplift estimates that are systematically biased toward the patient profiles that historically got selected for enrollment. The downstream effect is a recommender that recommends what the historical selection process recommended, with extra steps. Plan for a data science investment in causal inference: skills, tooling (EconML, DoWhy, causaldata), and the operational willingness to randomize a fraction of enrollment slots for unbiased evaluation. Without this, the program drifts toward serving the cohorts the historical bias served.

<!-- TODO (TechWriter): Specify the SageMaker training-job trigger mechanism and model-promotion path for the response, enrollment-likelihood, and engagement-prediction models. With 3 model families × 5 programs = 15 model artifacts, the model registry and promotion automation matter more here than in earlier recipes. Mirror the EventBridge-trigger plus SageMaker-Model-Registry-with-canary-run pattern flagged in 4.4 through 4.6. -->

**Multi-source state-machine reconciliation.** The patient's program state lives in multiple systems: the recommender's `patient-program-state` table, the care management vendor's case-management system, the EHR's care-plan view, and the patient's portal. Drift across these is a chronic operational pain. Plan for tight integration with the case-management system (event-driven sync, not periodic batch reconciliation), explicit conflict-resolution rules when sources disagree, and periodic full-reconciliation runs that flag drift for human review.

**Outreach attempt management with humane defaults.** The pseudocode handles outreach-attempt counting and terminal-unreachable transitions, but a production system needs more nuance: rest periods between attempts, time-of-day modeling per patient, opt-out registry integration, suppression after specific patient signals (missed appointment plus declined first outreach is a stronger signal than two unanswered calls), and integration with TCPA and state telephone-consumer-protection rules. The outreach worker is the most patient-facing component; treat it accordingly.

**Patient consent, HIPAA authorization, and program-specific consent forms.** Care management enrollment requires multiple consent artifacts: HIPAA authorization for data sharing across program staff, program-specific informed consent describing what the patient is enrolling into, and (for some programs) consent for data sharing with external entities (community resources, social-work referrals). The consent capture and storage flow needs to be tightly designed and tightly audited; consent-form-version mismatches and missing consent are compliance issues that produce disenrollment-and-restart cycles.

<!-- TODO (TechWriter): Replace the string-concatenation tracking_id, briefing_id, decision_id with opaque, non-reversible identifiers (UUID or HMAC-SHA256 over the composite with a per-environment secret). Plain-text patient_ids embedded in identifiers carried in care-manager queues, EHR inboxes, and engagement events are PHI leakage. Mirror the language flagged in 4.4, 4.5, 4.6. Update Expected Results sample identifiers accordingly. -->

**Cross-recipe orchestration with Recipes 4.4, 4.5, and 4.6.** A patient who's a candidate for adherence intervention (4.5), care-gap closure (4.6), wellness program (4.4), and care management (4.7) gets too many touches if each recipe orchestrates independently. The shared `outreach_recent_total_30d_count` on the patient-profile table is the foundation; the cross-recipe coordination policy that decides which recipe wins when caps would be exceeded needs to be explicit, version-controlled, and committee-reviewed. For 4.7 specifically, care management enrollment outreach should typically *not* be capped against routine engagement messages from 4.4-4.6 because the enrollment conversation is a distinct, infrequent interaction; document the exception in the cross-recipe policy.

<!-- TODO (TechWriter): Add a paragraph specifying the cross-recipe priority arbitration for 4.7 specifically. Default proposal: 4.7 enrollment outreach has a separate contact budget from 4.4-4.6 routine outreach, with a hard cap on combined contacts within a rolling 30 days. The enrollment conversation is the highest-priority interaction in chapter 4 and should not be routinely deferred for adherence reminders. Document the cross-recipe arbitration in shared chapter-level config. -->

**Disenrollment governance and review.** Disenrollment-for-cause decisions have member-experience implications and may have civil-rights implications if they concentrate in protected populations. Build a monthly disenrollment-review cadence: a cross-functional committee reviews the prior month's disenrollment-for-cause cases, with cohort breakdowns, looking for patterns that suggest the policy is mis-targeting, the retention attempts are inadequate, or the program structure is unfit for some cohorts. Build the review cadence into the policy from day one, not as an afterthought.

<!-- TODO (TechWriter): Expert Review HIGH A3 (uniquely 4.7-specific).
The disenrollment-decisions and cross-program-transitions queues both
hold rows with human_review_pending: true and no SLA, no escalation,
no default action. Three pathologies follow: (a) patient remains
enrolled indefinitely while the disenrollment recommendation sits
unreviewed, consuming a slot another patient could use; (b) patient
is silently disenrolled when stale review eventually happens against
out-of-date engagement and clinical-event data; (c) clinical leads
with high case-load triage easy cases first, so complex cases (which
correlate with the cohorts the equity floors protect) sit longer in
the pending queue, producing disparate review-latency that the
disenrollment-rate equity dashboard does not catch. Add SLA-and-
escalation specification with per-action defaults that err toward
retention rather than disenrollment: 7-day review SLA for
disenroll_for_no_engagement (auto-defer 7 more days then
auto-default to extend_for_review with current data); 14-day review
SLA for disenroll_did_not_complete (auto-default to
graduate_with_partial_credit); 72-hour review SLA for
transition_to_higher_acuity (clinical-urgency driven; escalate to
medical director on miss); 14-day SLA for graduation transitions
(auto-expire); 7-day SLA for relapse transitions (escalate to
program manager on miss). Per-cohort review-latency monitoring goes
into the equity instrumentation alongside per-cohort disenrollment-
rate metrics; disparities in review latency are fairness signals
just like disparities in eventual outcome. Specify in the
architecture pattern; add the sweep_pending_decisions Lambda to
the pseudocode as a daily run. -->

**Equity floor design.** The equity floors implemented in Step 3 reserve capacity for cohorts with documented enrollment-rate disparities. Designing the floors well requires baseline cohort data (which you don't have until operating for some time), explicit policy on which disparities trigger floors, and willingness to revisit floors quarterly. The Obermeyer failure mode is the canonical concern: a recommender trained on historical data with under-represented cohorts will systematically under-enroll those cohorts unless the design explicitly compensates. Equity floors are one mechanism; cohort-aware retraining with reweighting is another; cohort-stratified outcome evaluation is the validation.

<!-- TODO (TechWriter): Add a paragraph on the SDOH-cohort PHI boundary. Cohort labels like "transportation_barrier" and "low_food_security" are PHI-equivalent and should follow the minimum-necessary principle. Engagement events should carry only the cohort axes the equity dashboard actually consumes, with narrower IAM scope than for general engagement data. Mirror the language flagged in 4.4 through 4.6. -->

**Privacy in program state and enrollment briefings.** The `patient-program-state` table joins (patient_id, program_id, state, uplift_score, priority_components) and is highly inferential. A row indicating "patient recommended for high-risk complex-care program" is more sensitive than a row indicating "patient eligible for wellness program." Apply tighter controls to program state for stigmatized or high-sensitivity programs (behavioral health, substance use, palliative care, HIV-related): narrower IAM read scopes, optional separate-table partitioning, additional CloudTrail data event capture, and a documented minimum-necessary access policy. Enrollment briefings stored in DynamoDB are PHI; the briefing text contains diagnoses, social context, and trajectory framing. Treat them with the same encryption, IAM, and audit posture as clinical notes.

**Idempotency and retry semantics.** Same pattern as 4.4 through 4.6. Each stage's outputs are addressed by deterministic keys (run_date, program_id, patient_id) and writes are conditional, so a Step Functions retry that re-attempts a completed step is a no-op rather than a duplicate. The Step Functions Catch should distinguish retryable infrastructure failures from terminal logic failures and route terminal failures to the DLQ.

<!-- TODO (TechWriter): Code Review ERROR 1 (chapter-wide pattern in
the Python companion files for 4.6 and 4.7). The pseudocode
state_history.append(...) semantics are correct, but the
straightforward DynamoDB translation is *not* "ADD state_history
:history_event" because the ADD action only supports Number and Set
data types, not List. The correct UpdateExpression is
"SET state_history = list_append(if_not_exists(state_history, :empty),
:history_event)" with :empty defined as []. Update the Python
companion (chapter04.07-python-example.md) for all ten state-
transition update_item call sites; propagate the same fix to 4.6's
Python example. Add a one-line note here in the recipe's
Idempotency paragraph (or in a dedicated DynamoDB-gotchas paragraph)
warning readers who copy the pseudocode pattern that the literal
"append to history list" idiom requires the list_append +
if_not_exists pattern, not ADD. -->

<!-- TODO (TechWriter): Specify DLQ coverage on all Lambda paths in the architecture. (a) Step Functions to Lambda pipeline: Catch on each Lambda task pointing to an SQS failure queue keyed on (run_date, stage, failure_reason); (b) Kinesis to state-machine-worker Lambda: configure an OnFailure destination on the event source mapping pointing to SQS or SNS, with a CloudWatch alarm on DLQ depth; (c) Batch Transform job failures: SageMaker doesn't surface failures via DLQ; wire the Step Functions Catch to handle TransformJob failed states explicitly. A silently-dropped state-transition event is operationally damaging in this recipe (a missed program_at_risk event delays retention; a missed program_enrolled event leaves the engagement scorer unarmed), so DLQ coverage matters substantively. Mirror the language from 4.4 through 4.6. -->

**Cost-per-enrollment and cost-per-prevented-event tracking.** The cost numbers in the prerequisites table are infrastructure only. Production reporting needs end-to-end cost (infrastructure + care-manager loaded hours + telephony + program-specific costs like Bluetooth scales for HF or pharmacist time for polypharmacy) divided by confirmed prevented events attributable to the program (above the matched-control baseline). That number compared to the value of prevented events (avoided admission cost, avoided ED visit cost, plan-quality-bonus value) determines whether the program returns its budget. The data engineering to track this end-to-end with attribution is its own project and is essential for program-level decisions about expansion or contraction.

**Annual and contractual reporting requirements.** CMS Medicare Advantage care management activities have specific reporting requirements (CCM and PCM CPT code documentation, care plan structure, time-tracking for billable activities). State Medicaid programs often have their own care management reporting structures. Value-based contracts have their own. Build the reporting layer into the system from the beginning; retrofitting reporting onto a system that wasn't designed for it is painful and produces compliance gaps.

**Patient-friendly enrollment visibility.** Patients should be able to see their own program enrollment status, upcoming activities, and progress in the patient portal, with explanations they can understand. "Your heart-failure care management program" is more useful than "HF-CMP-2026-v2." Patient-facing summaries are a separate UX project, with content review by health-literacy specialists, but the program state machine in this recipe is the source data. Plan for the patient-facing layer as a parallel deliverable.

**Care-manager workload modeling.** Care managers don't have uniform capacity: a complex-care manager handling 50 patients with multi-system disease has different bandwidth than a transitional-care nurse running 20 active 30-day episodes. The work-queue routing in Step 4 needs to model per-care-manager realistic loaded hours, not just headcount. Without this, the routing produces care-manager burnout, attrition, and a slow-moving operations problem that undermines the entire program. <!-- TODO: cite published care-management caseload-and-burnout literature; the ratios vary by acuity but the patterns are consistent. -->

**Member-experience and PROMs measurement.** Beyond clinical outcomes, care management programs should measure member experience (CG-CAHPS for the care management interaction specifically; not the overall plan CAHPS) and patient-reported outcome measures (PROMs) where available. Member experience is often the leading indicator that diverges from clinical outcome metrics; a program that improves admissions but produces low member experience is sustainable for a quarter and politically untenable thereafter.

---

## The Honest Take

Care management program enrollment is the recipe in Chapter 4 where the gap between "the algorithm picks well" and "the program actually works" is widest, and where the temptation to confuse the two is strongest. Every plan I've worked with has, somewhere in its analytics infrastructure, a "high-risk patient list" that got generated last quarter, ranked by some flavor of admission probability, used to allocate program slots, and produced a cohort report at year-end showing some apparent improvement that was 60 to 90 percent regression-to-the-mean. The number in the report is real. The improvement attributable to the program is much smaller and may, in some cohorts, be zero or negative. The architecture in this recipe makes the difference observable, which is the most important thing it does, because once the difference is observable the program leadership has to decide whether to do the work to close the gap or to keep reporting the gap-inclusive number and hoping nobody asks too many questions.

The trap that's most specific to this domain is the Obermeyer scenario from the opening. A response model trained on observational enrollment data, where enrollment was historically allocated by clinician referral and patient engagement responsiveness, will encode the demographic and access patterns of who got referred and who got reached. Those patterns are not random. The patients who got referred and reached historically were disproportionately the patients the program was easiest to enroll, which were disproportionately the patients with stronger PCP relationships, fewer language barriers, more transportation access, and lower distrust of the medical system. The patients the program would benefit most are often the patients in the opposite quadrants. A model trained on historical enrollment labels will confidently predict low uplift for those patients, because they have low engagement-likelihood and the model conflates likelihood-of-enrollment with likelihood-of-benefit. The instruments that correct this (causal-inference tooling, randomized enrollment in a fraction of slots, equity floors, cohort-stratified evaluation) are not optional. They are how you prevent the model from quietly serving the cohorts the historical bias served.

The thing that surprises people coming from generic ML backgrounds is how much of the work is operational, not modeling. The program registry is governance plus engineering. The care-management-system integration is engineering plus contracts. The outreach worker is engineering plus member-experience. The disenrollment policy is governance plus equity review plus legal. The response model is the part that feels like ML, and it's maybe 25 percent of the system's value. The other 75 percent is making sure the right patients get reached, the engagement is tracked honestly, the disenrollment is humane, and the outcome evaluation is causal and cohort-stratified. A program with an excellent uplift model and poor operations under-delivers. A program with mediocre modeling and excellent operations over-delivers. The order of investment is operations first, modeling second.

The thing I'd do differently the second time: invest in the post-graduation observation pathway before the initial enrollment optimization. Most care management programs spend 90 percent of their attention on the enrollment funnel and 10 percent on what happens after graduation. The result is a population with a good first run through the program and a relapse-without-anyone-noticing problem afterward. A patient who graduates from the heart-failure program and gets readmitted seven months later was, almost certainly, demonstrating relapse signals during the post-graduation observation window. A program with a tight observation-to-re-enrollment loop catches them; a program with no observation pathway watches them go through the same hospitalization, gets re-eligible, and starts the funnel from scratch. The observation pathway is cheaper than re-enrollment and much cheaper than the avoidable readmission. Build it early.

The thing about the LLM components: they earn their keep on packaging and on rationale generation. The enrollment briefing is the place where LLMs add the most value because the alternative is a care manager opening a chart and trying to absorb a complex patient's history before a phone call that needs to start with rapport-building rather than chart-review. A briefing that distills "rising creatinine, lives alone, daughter is the natural care partner, cost is likely the unstated barrier" into 30 seconds of preparation is what makes the call go well. The disenrollment-rationale generation is similar: a clinical lead reviewing twenty disenrollment recommendations doesn't have time to chart-review each one; a structured rationale with the policy-rule trigger, the engagement-history evidence, and the countervailing factors makes the review tractable. The LLM is decision support for the human; the deterministic policy is the source of truth. Don't blur that line.

The thing about overrides and disenrollment: the override and disenrollment patterns are the most important fairness signals the program produces. A program with override rates that are higher in some cohorts than others is telling you the recommender is mis-targeting those cohorts. A program with disenrollment-for-cause rates that are higher in some cohorts than others is telling you the program structure is unfit for those cohorts and the retention strategies aren't compensating. Both patterns can be true simultaneously: under-enrollment of some cohorts and over-disenrollment of those same cohorts when they do enroll. The cohort dashboard surfacing these patterns is not nice-to-have; it is the program's conscience. Read it monthly.

A trap worth flagging: confusing program completion with program success. A program that drives the graduation rate from 40 percent to 70 percent and produces no measurable change in clinical outcomes either has a sample-size problem, a measurement problem, or a "the program graduated patients who didn't need the program" problem. Graduation rate is a fast-feedback intermediate metric; clinical outcome change is the slow validation. Optimize against graduation; validate against outcomes. A program that hill-climbs against graduation for two years without ever validating against outcomes is optimizing for a metric that may be entirely uncorrelated with the value it claims to produce.

Another trap: the "we'll do randomization later" pattern. The MVP shipping pressure is real, and many programs ship with observational uplift models and a plan to randomize a fraction of enrollment slots "next quarter." Two years later they still haven't randomized. That's a defensible choice in some contexts (operational pushback against random selection is real, especially when capacity is severely constrained), but it has a cost: the response model's calibration cannot be validated against an unbiased reference, and the difference-in-differences evaluation is bounded by propensity-matching quality and untestable assumptions about unmeasured confounders. If full randomization is operationally infeasible, smaller experiments (regression discontinuity around a threshold, randomized retention strategies, randomized outreach modalities) recover meaningful causal information. Don't accept "no randomization" as the durable state; it's the worst version of the program's measurement.

One more trap: the "highest-risk-first" reflex when capacity gets squeezed. When budget pressure or staffing reductions cut program capacity, the operational instinct is to "focus on the highest-risk patients" because the framing is intuitive and politically safe. The mathematical reality is that under capacity constraint, the patients you should prioritize are the ones with highest uplift, which is not necessarily the highest-risk patients. The highest-risk patients with low predicted uplift are patients whose adverse events the program will not prevent; allocating scarce capacity to them produces the same adverse events while excluding the lower-risk-but-higher-uplift patients whose events the program would have prevented. The conversation with operations leadership when capacity contracts is one of the hardest in this work. Have it explicitly, with the math, with the cohort instrumentation showing what each allocation strategy produces. Don't let the highest-risk-first framing win by default just because it's easier to explain.

Last point, because it's specific to this use case: care management is rationing, and rationing decisions in healthcare deserve more rigor than retail recommendation decisions. There are 18,000 eligible patients and 1,400 slots; the recommender is making the choice. The way that choice gets made (the response model's training, the equity floors, the cohort instrumentation, the disenrollment policy, the cross-program coordination) is the choice itself. A program that optimizes for the easiest-to-enroll, easiest-to-retain, easiest-to-graduate cohort produces a beautiful dashboard and quietly rations away from the cohorts the program was supposed to serve. A program that optimizes thoughtfully, with explicit equity instrumentation and randomized validation, may have a less impressive dashboard and produce more durable value over time. The two are not the same. Build the second one.

---

## Variations and Extensions

**Real-time post-discharge transitional care enrollment.** Beyond the daily eligibility cycle, an EventBridge rule can fire on incoming discharge events and trigger immediate transitional-care eligibility evaluation, response scoring, and enrollment recommendation, with care-manager assignment within hours of discharge. The 30-day TCM window is time-sensitive; reducing the time-to-outreach from days to hours captures more of the high-leverage early window.

**Hospital-at-home and remote-monitoring program integration.** Plans increasingly offer hospital-at-home and high-acuity-at-home programs as alternatives to admission. The recommender can layer these into the program portfolio, with response models predicting which patients would benefit and which patients are operationally feasible (caregiver availability, home environment, technology comfort). The overall pattern is the same; the eligibility and response models are program-specific.

**Behavioral-health integration.** Behavioral-health needs intersect heavily with care management for chronic conditions; depression in the heart-failure population, anxiety in the diabetes population, substance-use comorbidity in the chronic-pain population. Adding a behavioral-health-integration pathway as an add-on program (the add_on category in the multi-stage allocator) catches these patients without requiring separate eligibility flow. The validator and consent framework matter more here because behavioral-health communications have additional regulatory requirements.

**SDOH-focused care management.** Some plans run dedicated SDOH-focused programs (housing instability, food insecurity, transportation, social isolation) staffed by community health workers and social workers. These have different denominators (less driven by clinical risk, more by SDOH-screening positives), different theories of change (resource navigation rather than clinical care), and different outcomes (housing stability, food-security improvement, social-connectedness improvement). The architecture extends naturally; the metrics extend less naturally and are worth their own evaluation pipeline.

**Dynamic enrollment-cycle cadence.** A monthly enrollment cycle is operationally simple but imposes a one-month wait for any patient who becomes eligible day-after-the-cycle. A more sophisticated approach: weekly cycles for non-time-sensitive programs, daily cycles for time-sensitive programs (transitional care, post-deterioration escalation), with capacity reservation logic that holds slots across cycles to prevent depletion in early-cycle weeks.

**Care-team coordination across provider organizations.** A patient who is enrolled in a plan-run heart-failure program but also followed by an ACO-run primary-care medical home and a specialty-cardiology practice is being managed by three different teams with three different views. Cross-organization care-coordination layers (often vendor-supplied or built on FHIR-based shared care plans) become the integration substrate; the recommender's program-state events flow into the shared care plan rather than living in isolation.

**Predictive disenrollment-prevention.** Beyond the at-risk threshold, a per-patient model can predict the probability of disengagement over the next 14 days, surfacing patients for retention attention before the threshold crosses. This is a separate model family with the engagement-decline event as the prediction target; trained on enrollment cohorts, validated against held-out enrollments. <!-- TODO: cite published literature on predictive disenrollment-prevention; the patterns are documented in some plan publications but the evidence base is mixed. -->

**Cross-recipe orchestration with Recipes 4.4, 4.5, 4.6.** A patient who's a candidate for adherence intervention (4.5), care management (4.7), care-gap closure (4.6), and a wellness program (4.4) gets too many independent recommendations if each recipe orchestrates alone. Cross-recipe orchestration: shared contact-frequency budget (Chapter 4-wide), shared priority arbitration when caps would be exceeded, per-patient orchestration that picks the right recipe for the right moment. For 4.7 specifically, care management enrollment outreach typically should not be capped against routine engagement messages because the enrollment conversation is a distinct, infrequent interaction; document the exception in the cross-recipe policy.

**Cohort-specific program variants.** Some patient cohorts benefit from cohort-specific program structures: Spanish-language disease-specific programs, programs adapted for low-health-literacy populations, programs with home-visit options for mobility-limited patients, programs with extended-hour staffing for working-age members who can't engage during business hours. Variants are added to the registry as separate programs with their own capacity; the multi-stage allocator handles them as siblings.

**Member-incentive integration.** Some plans offer member-facing incentives for care-management engagement (gift cards for completing baseline assessment, premium discounts for program graduation) within regulatory limits. The recommender can route incentive-eligible recommendations with a different message frame and track incentive uptake as an enrollment-conversion-lift signal. Beware: incentive programs can introduce unintended behavioral patterns and may complicate compliance reporting; legal review before launch.

**Cost-aware uplift optimization.** Beyond per-(patient, program) uplift, a more sophisticated allocator optimizes total expected value subject to total budget rather than per-program capacity. This requires per-program cost models (per-patient loaded cost varies by program and by patient acuity within program), per-program impact-in-dollars models, and an integer-programming formulation. Useful when the plan has flexibility to reallocate budget across programs in response to demand. Crosses into Chapter 14 (operations research) territory.

**Closure of the loop with provider performance.** Care management programs intersect with provider performance: a patient enrolled in a care management program because their PCP was missing the boat on heart-failure management is a pattern; a high-volume of patients in care management for the same provider is a signal. The recommender's outputs can feed provider-performance dashboards, with the appropriate caveats about confounding (sicker panels generate more care-management referrals).

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the channel optimizer for patient-facing enrollment messages and check-in reminders. The contact-frequency cap is shared infrastructure (with the 4.7 exception that enrollment outreach uses a separate budget).
- **Recipe 4.2 (Patient Education Content Matching):** Patient-facing enrollment messages and program-progress updates often pair with educational content; the content-matching pipeline from 4.2 selects program-relevant materials.
- **Recipe 4.3 (Provider Directory Search Optimization):** When a care management program requires a specialist referral or a new PCP relationship, 4.3's ranking pattern helps select the right provider for the patient's preferences and access.
- **Recipe 4.4 (Wellness Program Recommendations):** Wellness programs and care management programs overlap in eligibility for some patients; cross-recipe coordination determines the right next step. A patient with prediabetes may be a DPP (4.4) candidate; a patient with diabetes plus complications may be a care-management (4.7) candidate.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** The barrier classifier from 4.5 is reused here. Adherence intervention is sometimes a precursor to care management (the simpler intervention) and sometimes a parallel add-on (polypharmacy program inside care management).
- **Recipe 4.6 (Care Gap Prioritization):** Multiple high-urgency open gaps are a feature of complex-care eligibility; the gap state from 4.6 feeds the care management response model. Care management staff often use the gap-prioritization output as their working agenda for enrolled patients.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** The risk-stratification input is a Chapter 7 problem; the response model in this recipe is also a risk-scoring-with-causal-inference problem. Chapter 7's risk-modeling patterns and validation methodology apply.
- **Recipe 8.x (NLP Non-LLM):** Care manager notes can be parsed by NLP to extract structured engagement signals, barrier flags, and care-plan-progress markers more reliably than relying on structured-form data alone.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Capacity planning for care management staffing across programs and the year-over-year demand forecasting are Chapter 12 problems.
- **Recipe 13.x (Knowledge Graphs):** The program registry, with relationships between programs (substitutable, sequential, complementary), the care-plan goal taxonomy, and the cross-program transition logic, is naturally modeled as a knowledge graph at higher sophistication levels.
- **Recipe 14.x (Optimization / Operations Research):** The multi-stage allocator is a constrained-optimization problem; integer programming, column-generation, or assignment-algorithm formulations produce provably-optimal allocations when constraints multiply. The cost-aware variation above is an explicit OR formulation.
- **Recipe 15.x (Reinforcement Learning):** The longitudinal enrollment-graduation-re-enrollment cycle, with state transitions and rewards (clinical outcomes), is a reinforcement-learning problem at the most sophisticated level. The recipe in this chapter handles it with deterministic policy and supervised modeling; full RL formulations are research-grade.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Batch Transform](https://docs.aws.amazon.com/sagemaker/latest/dg/batch-transform.html)
- [Amazon SageMaker Feature Store](https://docs.aws.amazon.com/sagemaker/latest/dg/feature-store.html)
- [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
- [Amazon SageMaker Pipelines](https://docs.aws.amazon.com/sagemaker/latest/dg/pipelines.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock structured output and function calling](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-call-tools.html)
- [Amazon EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [Amazon SES Developer Guide](https://docs.aws.amazon.com/ses/latest/dg/Welcome.html)
- [Amazon Pinpoint User Guide](https://docs.aws.amazon.com/pinpoint/latest/userguide/welcome.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Reference notebooks for XGBoost, Batch Transform, SageMaker Pipelines, and Model Registry workflows applicable to per-program model lifecycles
- [`amazon-sagemaker-feature-store-end-to-end-workshop`](https://github.com/aws-samples/amazon-sagemaker-feature-store-end-to-end-workshop): End-to-end Feature Store usage that maps to the per-(patient, program) feature pipeline
- [`amazon-bedrock-workshop`](https://github.com/aws-samples/amazon-bedrock-workshop): Hands-on labs covering structured-output prompting that informs enrollment briefings, engagement summaries, and disenrollment-decision rationales

<!-- TODO: confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing. -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter AI/ML and Healthcare): browse for healthcare personalization and population-health reference architectures
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "SageMaker Pipelines," "Feature Store," and "uplift modeling" for relevant deep-dives
- [AWS for Industries Blog](https://aws.amazon.com/blogs/industries/) (Healthcare and Life Sciences): search "care management," "population health," and "value-based care" for end-to-end customer architectures

<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. -->

**External References (Conceptual and Methodological):**
- [`econml`](https://github.com/py-why/EconML): Microsoft Research's library for heterogeneous treatment effect estimation, the workhorse for per-(patient, program) uplift modeling
- [`DoWhy`](https://github.com/py-why/dowhy): causal-inference framework for structuring assumptions and running sensitivity analysis
- [`causaldata`](https://github.com/NickCH-K/causaldata): example datasets for causal-inference workflows useful in scaffolding response-model training pipelines
- [Obermeyer et al. 2019, Dissecting Racial Bias in an Algorithm Used to Manage the Health of Populations](https://www.science.org/doi/10.1126/science.aax2342): the canonical cautionary tale for response-modeling failures in care management; required reading
- [CMS Chronic Care Management (CCM) Services](https://www.cms.gov/medicare/medicare-fee-for-service-payment/physicianfeesched/chronic-care-management): Medicare fee-for-service CCM billing structure, including the 99490, 99491, 99437, 99439 CPT codes and documentation requirements <!-- TODO: confirm current CMS landing page; CMS reorganizes URLs frequently. -->
- [CMS Transitional Care Management (TCM) Services](https://www.cms.gov/files/document/mln908628-transitional-care-management-services.pdf): TCM CPT codes 99495 / 99496 and documentation requirements <!-- TODO: confirm the current published-document URL at the time of build. -->
- [NCQA Care Management Standards](https://www.ncqa.org/): NCQA's care-management accreditation standards, applicable for plans pursuing accreditation
- [Synthea](https://github.com/synthetichealth/synthea): synthetic patient data generator including realistic conditions, encounters, and procedures useful for non-PHI development of care management pipelines
- [Care Continuum Alliance Care Management Outcomes Standards](https://www.populationhealthalliance.org/): the population-health-alliance care-management outcome standards <!-- TODO: confirm the current URL at the time of build; the alliance has rebranded multiple times. -->

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Program registry with 2-3 high-volume programs + risk-stratification-based eligibility + observational uplift models per program + single-stage greedy allocator + manual outreach workflow + minimal cohort dashboard | 14-18 weeks |
| Production-ready | Full pipeline: 4-7 program registry + multi-source eligibility + per-program response, enrollment-likelihood, and engagement-prediction models with propensity-matched evaluation + multi-stage capacity-aware allocator + LLM-generated enrollment briefings + Connect-integrated outreach workflow + engagement-and-retention worker + disenrollment governance + cross-program transition logic + post-graduation observation + outcome-evaluation pipeline + cohort and equity dashboards + cross-recipe orchestration | 12-16 months |
| With variations | Add real-time post-discharge enrollment, hospital-at-home integration, behavioral-health pathway, SDOH-focused programs, randomized-evaluation cohort, predictive disenrollment-prevention, member-incentive integration, cost-aware uplift optimization, provider-performance feedback | 10-16 months beyond production-ready |

---

## Tags

`personalization` · `recommendation` · `care-management` · `program-enrollment` · `uplift-modeling` · `causal-inference` · `propensity-matching` · `capacity-constrained-allocation` · `equity` · `cohort-analysis` · `longitudinal-state-tracking` · `engagement-prediction` · `disenrollment-governance` · `cross-program-transitions` · `post-graduation-observation` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `connect` · `medium-complex` · `production` · `hipaa`

---

*← [Recipe 4.6: Care Gap Prioritization](chapter04.06-care-gap-prioritization) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.8 - Treatment Response Prediction →](chapter04.08-treatment-response-prediction)*
