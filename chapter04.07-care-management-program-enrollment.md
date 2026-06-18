# Recipe 4.7: Care Management Program Enrollment ⭐⭐⭐

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
- **Transitional care management.** Episodic, post-discharge, focused on the high-risk first 30 days after a hospital stay. RN coordinator, scheduled telephonic check-ins, in-home or televisit medication reconciliation, follow-up appointment scheduling. Theory of change: most readmissions are preventable with structured early support. CMS reimburses TCM (CPT 99495 / 99496) under specific documentation requirements, so the program structure is operationally constrained by billing rules. 
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

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.07-architecture). The Python example is linked from there.

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

## Tags

`personalization` · `recommendation` · `care-management` · `program-enrollment` · `uplift-modeling` · `causal-inference` · `propensity-matching` · `capacity-constrained-allocation` · `equity` · `cohort-analysis` · `longitudinal-state-tracking` · `engagement-prediction` · `disenrollment-governance` · `cross-program-transitions` · `post-graduation-observation` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `connect` · `medium-complex` · `production` · `hipaa`

---

*← [Recipe 4.6: Care Gap Prioritization](chapter04.06-care-gap-prioritization) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.8 - Treatment Response Prediction →](chapter04.08-treatment-response-prediction)*
