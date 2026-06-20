# Recipe 4.9: Personalized Care Plan Generation ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Research-to-Production · **Estimated Cost:** ~$0.05-0.20 per generated care plan (depends on number of recommended actions assembled, LLM tokens for tailored narrative, and the breadth of care-team review surfaces)

---

## The Problem

Linda is 67. She has type 2 diabetes (last A1c 8.4, on metformin and a GLP-1), congestive heart failure with reduced ejection fraction (last echo EF 38%, on guideline-directed medical therapy), chronic kidney disease stage 3b (eGFR 39 and trending down), depression that her PCP has been managing since her husband died two years ago, mild cognitive impairment that her family has started noticing on the harder days, osteoarthritis in both knees that she manages with topical NSAIDs because her cardiologist has asked her to stay off the oral ones, hypertension that is mostly controlled, and a colonoscopy that is two years overdue. She lives alone in a second-floor walk-up in a neighborhood where the closest grocery store is a thirty-minute bus ride away. Her daughter, who lives in another state, has been calling more often. Linda has six prescriptions, sees four specialists, has a once-monthly care manager check-in through her Medicare Advantage plan, and was just discharged from a three-day hospital stay for a CHF exacerbation that her care team thinks may have been triggered by a missed diuretic dose.

Linda needs a care plan. While Linda does have a document in her electronic health record with that label, the document is sixteen pages long. It was generated from a template at the time of her CHF diagnosis four years ago and has been amended exactly twice since then; once when she started the GLP-1, once when her depression diagnosis was added. The plan lists her diagnoses, her medications, her appointment cadence, her preferred pharmacy, her emergency contact, and the boilerplate language her health system uses for "follow heart-healthy diet" and "monitor symptoms." The plan does not say what Linda should do tomorrow morning when she wakes up. The plan does not say what to do if she gains three pounds in a week. The plan does not say which appointment to keep when both her cardiologist and her endocrinologist offer her a slot on the same Thursday. The plan does not connect her social isolation to her CHF readmission risk, although her care team would, if asked, agree that the connection is real and probably important. The existing "plan", in short, is a document, not a true plan that is useful to her.

What Linda's care team actually wants is a different artifact. They want a working document that, looking at Linda's diagnoses, medications, recent labs, recent encounters, social context, stated preferences, and current goals, produces a prioritized, time-bounded, accountability-assigned set of actions: this week, take the diuretic at the same time every morning, weigh yourself daily, call the care manager if you gain three pounds in three days. This month, complete the deferred colonoscopy with transportation arranged through the plan's benefit. This quarter, attend the cardiac rehab program your cardiologist referred you to and that your insurance covers but that nobody at the practice has ever told you starts within walking distance. Going forward, work with your care manager on a goals-of-care conversation about what living-well-at-home looks like for you over the next several years. Each action has an owner (Linda, the care manager, the cardiologist, the PCP, the social worker), a due date, a measurable outcome, and a fallback if the primary action fails. The plan adapts as Linda's clinical state changes, as her preferences change, and as her care team learns what is and is not working.

That artifact does not exist for most patients with multiple chronic conditions, even though every health system, every payer, and every quality program nominally requires one. The reasons are well-rehearsed: the underlying clinical guidelines are written one condition at a time, and combining them for a patient with five active conditions creates inconsistencies that the guidelines do not resolve. The patient's preferences and social context are scattered across visit notes, social work assessments, patient-portal questionnaires, and the back of the care manager's notepad, never in a single structured place. The accountability and timing structure that turns recommendations into actions is implicit in clinician minds, not explicit in any system. The output, when it exists, is a paragraph in a discharge summary that the patient skims and the next clinician overlooks. The "personalized" part of "personalized care plan" is doing a lot of work that the systems do not actually do.

Personalized care plan generation is the practice of producing that working artifact. A structured, prioritized, accountability-assigned, adaptive action plan that synthesizes the patient's clinical conditions, social context, preferences, and goals into something the care team and the patient can use. It is not a single recommendation, the way a medication-adherence intervention or a care-management enrollment is a recommendation. It is an ensemble of recommendations, sequenced and weighted, with explicit reasoning and explicit tradeoffs visible to the people who will use it.

The reason this is a Complex recipe rather than a Medium one is that it is not the same problem as other use cases in this category. Most other Recommendation and Personalization use cases return a channel, a piece of content, a provider, a wellness program, a care management enrollment, a treatment from a comparator pair, etc. Care plan generation picks all of them, simultaneously, for the same patient, and reconciles the picks into a coherent whole. The clinical-evidence layer is broader (every condition's guidelines, plus geriatric-specific principles, plus end-of-life-care principles where applicable). The personalization layer is denser (preferences, goals, social determinants, family situation, cognitive status, prior plan adherence). The orchestration layer is multi-actor (the patient, the PCP, multiple specialists, the care manager, the social worker, the pharmacy, the family caregiver). The output is structured but consumable by humans (the clinician scans it in two minutes and Linda understands the relevant pieces in three). And the maintenance loop is ongoing. A care plan that does not update with the patient's state is a static document, which is what the system is trying to escape from in the first place.

The other reason it is Complex is because this where the LLM stops being a packaging layer and starts being structurally load-bearing. Many other use cases leverage the LLM to produce a paragraph or two of clinician-facing or patient-facing prose. Here, the LLM is doing more: it is sequencing actions, drafting goal statements, tailoring instructions to the patient's reading level and stated preferences, and assembling the narrative that holds the structured action set together. You also need a validator pattern that keeps the LLM from freelancing on the clinical decisions is much of the work.

We are going to build the architecture for this. Care plan generation is the synthesis layer that turns channel preference, educational content, the provider relationships, medication adherence interventions, treatment-response predictions, and more into a single, coherent, evolving plan. The architecture has several moving parts and the governance is heavy. The hard parts are not the AWS services. The hard parts are the clinical-content modeling, the multi-condition reconciliation, the patient-engagement design, and the LLM discipline.

Let's get into how you build it.

---

## The Technology: Multi-Condition Synthesis, Goal-Action-Owner Modeling, and the LLM as Load-Bearing Component

### What a Care Plan Actually Is, in Structured Terms

Strip away the document layout, the cover sheet, the boilerplate, and what is left of a useful care plan is a directed graph of *goals*, *actions*, and *owners*, with timing, dependencies, and accountability metadata.

A *goal* is a desired clinical, functional, or quality-of-life outcome the patient is working toward. "A1c under 7.5 by next quarter." "Avoid heart-failure-related hospitalization for the next twelve months." "Walk to the corner store and back without significant shortness of breath." "Have a documented advance care planning conversation by year-end." Goals have horizons (this week, this quarter, by year-end, ongoing), priority weights (which goal yields if two of them conflict), and a connection to evidence (which guideline or which clinical reasoning supports the goal). Goals are owned by the patient ultimately, but co-owned operationally by clinicians and care team members.

An *action* is a specific, time-bounded, executable step that advances a goal. "Take the diuretic at 8 AM each morning." "Complete the colonoscopy by April 30 with transportation booked through the plan's benefit." "Attend three cardiac rehab sessions per week for twelve weeks starting next Monday." "Call the care manager if you gain three pounds in three days, or if you become more short of breath." Actions have owners (who is doing this), due dates, success criteria (how we know it happened and worked), fallback paths (what we do if the primary action fails), and dependencies (this action depends on transportation being booked first). Actions roll up to goals; one goal usually has multiple actions, and one action can serve multiple goals.

An *owner* is a person or role accountable for an action. The patient is an owner of self-care actions. The PCP, the cardiologist, the endocrinologist, the care manager, the social worker, the pharmacist, the home-health agency, and the family caregiver are all potential owners. Owners have communication preferences, escalation paths, and capacity constraints that the plan respects.

These three primitives, with their relationships and metadata, are the structured representation that the rest of the system manipulates. The narrative layer (the prose the patient and clinicians read) is rendered from this structured representation, not the other way around. The structured-then-narrative direction is critical: it is what makes the plan auditable, queryable, updatable, and amenable to fairness analysis. It is also what keeps the LLM from being the system of record for clinical decisions; the LLM produces the narrative, but the narrative is grounded in structured data that has been through deterministic clinical-rule, prediction, and validation logic.

Different fields have converged on similar primitives from different directions. The HL7 FHIR resources `Goal`, `CarePlan`, and `ServiceRequest` (with `Task` for assignment and tracking) implement essentially this graph. The HL7 C-CDA care plan template uses similar structure with different field names. The IHE Personal Health Record content profile and CMS care-plan documentation requirements all map to the same underlying graph. The point is that the structured representation is well-trodden ground; what differs across implementations is the richness of the graph and how dynamically it is maintained.

### The Multi-Condition Reconciliation Problem

Most clinical guidelines are written one condition at a time. The diabetes guidelines say "for a patient with type 2 diabetes and CKD, prefer SGLT2 inhibitors and GLP-1 receptor agonists." The CHF guidelines say "for a patient with HFrEF, prefer ARNI plus beta-blocker plus MRA plus SGLT2 inhibitor." The CKD guidelines say "for a patient with CKD stage 3b, prefer SGLT2 inhibitors and avoid metformin if eGFR drops below 30." The geriatric guidelines say "for a patient over 65 with polypharmacy, beware of adding medications without simultaneously deprescribing where appropriate, and weigh therapeutic burden against quality of life." Linda is all of these patients.

The single-condition guidelines, applied separately, point in mostly compatible directions (SGLT2 inhibitor is a winner across the diabetes, CHF, and CKD guidelines), but they do not natively reconcile when they conflict, and they do not natively prioritize when the patient cannot do all of the recommended actions at the same time. Reconciliation across conditions is the work that historically happens implicitly in clinician heads. Making it explicit, in a structured way that a system can produce and a clinical team can review, is one of the central technical challenges of care plan generation.

There are several methodological pieces:

**Drug-drug and drug-disease interaction checking.** The simplest reconciliation. Standard drug-interaction databases (First Databank, Lexicomp, Wolters Kluwer Medi-Span, the FDA's RxNorm-linked drug-interaction APIs) flag the obvious conflicts. Drug-disease checks (e.g., NSAIDs in CHF, metformin in advanced CKD, sulfonylureas in elderly with cognitive impairment) are similarly catalogued. These are baseline checks every modern e-prescribing system already does; the care plan layer surfaces them as constraints on the action set rather than as point-of-prescribe alerts.

**Care-gap conflict reconciliation.** Two guideline-based actions can conflict on patient time, patient finances, patient cognitive load, or care-team capacity. Linda's cardiologist wants her in cardiac rehab three times a week; Linda's endocrinologist wants her in diabetes self-management education two times a week; her care manager wants her in a depression group once a week. Linda is one person with one schedule and limited stamina. The care-gap conflict reconciliation layer recognizes that the actions, individually clinically correct, may not fit together in practice and needs to either prioritize, sequence, or substitute.

**Therapeutic-burden weighting.** A growing body of geriatric and chronic-care literature describes therapeutic burden (sometimes called treatment burden, sometimes patient work) as the load placed on the patient by their treatment regimen. The prescriptions to fill, the appointments to attend, the lab draws, the self-monitoring tasks, the dietary restrictions, the financial costs, the cognitive load. Care plans for patients with multiple chronic conditions and limited resources should account for therapeutic burden, not just clinical efficacy. The Cumulative Complexity Model (May, Montori, and Mair) is the canonical framework. Implementations explicitly compute a per-patient burden estimate and use it as a constraint in the prioritization layer.

**Goals-of-care alignment.** A patient with multiple advanced conditions may have explicit preferences that override the disease-specific clinical maximization. "I want to stay home as long as possible." "I do not want any more hospitalizations if they can be avoided." "I want to be alert enough to interact with my grandchildren even if it costs me some life expectancy." A care plan that does not reflect these preferences fails the patient even if every individual recommendation is guideline-consistent. The goals-of-care layer captures these preferences (often through structured advance-care-planning conversations, but also through inferred-from-portal-engagement signals), translates them into priority weights and constraints, and propagates them through the plan generation logic.

**Cohort-stratified appropriateness.** Beyond the patient's individual goals, the appropriateness of a recommendation may vary across cohorts that the guidelines do not stratify on. Pregnant patients, patients with intellectual or developmental disabilities, patients with significant cognitive impairment, patients in palliative or hospice care, patients with limited English proficiency, patients with documented preferences against specific care types (faith-based, cultural, prior trauma), all of these change which recommendations are appropriate without changing the underlying disease management. The cohort-aware reconciliation layer applies these adjustments before the plan is finalized.

**Conflict-resolution defaults.** Even with all of the above, some conflicts will not resolve. The system needs explicit defaults: when goals conflict, prioritize the higher-acuity goal. When actions conflict on patient time, sequence them rather than parallelize. When actions conflict on patient cost, surface the cost transparently rather than silently picking the cheaper option. The defaults are policy choices, not implementation choices, and they should be reviewed by the clinical leadership that operates the program.

### Personalization: Beyond "Patient Preference Field"

Personalization in care plan generation is denser than in any prior recipe in this category. The relevant features include but are not limited to:

- **Stated preferences** captured through structured advance-care-planning, patient-portal questionnaires, or visit-note dot phrases. "I prefer not to start any injectable medications." "I will not consent to any procedure under general anesthesia." "I want to avoid hospitalizations whenever possible." "I want all major decisions to be discussed with my daughter before I commit."
- **Implied preferences** inferred from prior plan adherence, prior interaction patterns, and prior choices when given options. A patient who has cancelled three colonoscopy appointments has revealed something about their preferences even if they have not stated it explicitly.
- **Social determinants of health.** Transportation access, food security, housing stability, financial strain, internet access, social support. These directly constrain which actions are feasible. A care plan that requires Linda to attend an outpatient program in a building she cannot get to without transportation she does not have is not a care plan.
- **Clinical complexity and trajectory.** Number of active conditions, polypharmacy count, recent hospitalizations, recent emergency department visits, recent major life events (bereavement, job loss, housing change). The plan's tempo and ambition should match the patient's current resilience, not an idealized profile.
- **Cognitive and functional status.** Self-care capacity (can the patient manage their medications?), cognitive function (can the patient track multi-step instructions?), functional status (can the patient walk to the bus stop?), language and literacy (can the patient read the plan in their preferred language at their reading level?), digital literacy (does the patient use the portal, text messages, or print mail?). All of these change what kinds of actions are realistic and how the plan should be communicated.
- **Family and caregiver involvement.** Who else is involved in the patient's care, what is their relationship, and what do they know and own? A plan that does not coordinate with the patient's adult daughter who manages the medication list is a plan that will be quietly subverted by the daughter's reasonable interventions.
- **Cultural and faith context.** Religious observances that affect timing of fasts, lab draws, or medication schedules. Cultural attitudes toward specific care types, family decision-making norms, language and idiomatic preferences. Care plans that ignore these are care plans that the patient does not engage with.

Capturing this density of personalization requires structured intake (the more structured, the better), longitudinal tracking (preferences change), and explicit consent for the system to use the information. The pattern that fails is when the system has rich preference data and does not use it because the planning logic was built before the preference data was structured; the patient experiences the plan as ignoring everything they have told the system, and trust is lost.

### LLMs as Load-Bearing, with Strict Constraints

Care plan generation is where the LLM moves from "package the structured output" to "structurally contribute to the assembly of the plan." That sounds dangerous, and it is, if not done carefully. Done carefully, it works for several specific tasks:

**Sequencing of actions.** Given a set of recommended actions from the upstream recommendation systems (medication adjustments, care-gap closures, program enrollments, and educational content), the LLM can propose an ordering that respects clinical urgency, patient capacity, and dependencies. The LLM doesn't invent actions; it sequences the actions it is given. The output is validated against the structured action set and any reordering rules in the catalog.

**Drafting of patient-facing goal statements.** "Avoid CHF readmission" is the clinical goal. The patient-facing version is something like "Stay home and out of the hospital by paying close attention to your weight and how you feel each day, and calling the care manager early if something changes." The LLM drafts that. The validator enforces reading-level compliance, plain-language clinical accuracy, and approved-claim language.

**Tailoring of action instructions.** "Take furosemide 40 mg by mouth daily in the morning" is the prescription. The patient-facing instruction, tailored to Linda specifically, is "Take your water pill at 8 in the morning, with breakfast, every day. Set a phone alarm if it helps. If you forget and remember the same morning, take it. If you have already gotten to the afternoon, skip that day and take the next one as scheduled. Call the care manager if you miss two days in a row." The LLM drafts that. The validator checks every clinical claim against the structured action and the approved patient-instruction templates for the medication.

**Assembling the narrative layer.** The plan's prose summary, the section introductions, the transitions between goals, the explanation of what changed since the last plan version. The LLM writes this. The validator checks that every clinical fact in the narrative traces to a structured action, goal, or observation in the plan; the LLM does not introduce clinical claims absent from the structured plan.

**Disagreement and escalation narratives for the care team.** When the planning logic produces a conflict that the deterministic reconciliation layer could not resolve, the LLM generates an internal-facing summary of the conflict, the candidate resolutions, and the recommended escalation path. This narrative goes to the clinical team for human review, not to the patient.

What the LLM does not do, and the validator enforces it does not do:

- The LLM does not introduce new clinical recommendations not present in the structured action set.
- The LLM does not change the priority weights of goals.
- The LLM does not change the clinical content of action instructions; it can rephrase, add tailored framing, and adjust reading level, but the underlying medication, dose, schedule, and clinical guidance is fixed by the structured action.
- The LLM does not select among comparator treatments 
- The LLM does not generate prognostic statements about the patient's outcomes beyond the templates approved by the clinical-content team.
- The LLM does not produce content that crosses into recommendation language for treatments where the clinical evidence does not support a recommendation.

This division of labor (deterministic structured-action assembly with LLM-produced narrative on top) is what makes the recipe defensible. The structured plan is auditable. The narrative is checkable against the structured plan. The personalization is in the narrative tailoring and the structured personalization features (preferences, SDOH, goals); it is not in the LLM freelancing on what should be in the plan.

### Where the Field Has Moved

Several recent developments shape what a care plan generation system can do well today versus a few years ago:

- **Foundation-model-based clinical reasoning** has matured to the point where LLMs can produce clinically coherent narrative when grounded in structured input. The grounding is the operative word: ungrounded LLM output for clinical content is unsafe. Structured-input-with-narrative-output patterns, with rigorous validators, are now a defensible design.
- **FHIR-native care plan storage** is increasingly standard. The `CarePlan`, `Goal`, `Task`, and `ServiceRequest` resources, with their relationships, give the structured graph a standard representation. Most modern EHRs and care management platforms can produce and consume these resources, which makes plan portability across care settings tractable for the first time.
- **Structured advance-care-planning** (5 Wishes, the National POLST Paradigm, increasingly ePOLST registries) has put more goals-of-care information into structured form. The plan generation logic can consume it as a first-class input rather than guessing from free-text notes.
- **Cohort-aware fairness instrumentation** has moved from research-paper territory to operational territory. The cohort-fairness infrastructure built for the upstream personalization use cases can be extended to monitor care plan generation for cohort-specific differences in plan ambition, plan complexity, action assignment, and outcome trajectories.
- **Patient-reported outcome measures and patient-reported experience measures** (PROMs, PREMs) are increasingly captured in EHRs and patient portals. They feed both the personalization layer (what the patient says they want and how their function is changing) and the evaluation layer (whether the plan is actually working from the patient's perspective).
- **Teach-back and shared decision-making frameworks** have produced structured instruments (Ottawa Personal Decision Guide, SDM-Q-9) that can be integrated into the plan generation and review loop. These are not just UX patterns; they produce structured signals about the patient's understanding and engagement that the plan generation system can use.

---

## General Architecture Pattern

The pipeline has seven logical components: a clinical-content component that maintains the structured guideline content, action templates, and goal templates; an inputs-aggregation component that pulls in upstream signals from the systems that produce them (the personalization recipes earlier in this chapter, or equivalent capabilities your organization already runs) and from source clinical and social data; a goal-derivation component that produces the patient's goal set from condition-specific guidelines, goals-of-care preferences, and quality-program requirements; an action-assembly component that produces candidate actions per goal and reconciles conflicts; a plan-finalization component that prioritizes and sequences the action set into a coherent plan with assigned owners and due dates; a narrative-and-rendering component that produces the clinician-facing and patient-facing artifacts with the LLM and the validator; and a feedback-and-adaptation component that captures plan adherence, plan effectiveness, and patient feedback and drives plan revisions.

```text
┌───────── CLINICAL CONTENT (governance-controlled) ────────────┐
│                                                                │
│  [Clinical guideline curation]   [Pharmacy and Therapeutics]   │
│  [Patient education library]   [Care management programs]     │
│  [Quality measure library]   [Geriatric / palliative]          │
│           │                       │                  │         │
│           └──────────┬────────────┴────────┬─────────┘         │
│                      ▼                     ▼                   │
│         [Goal templates: condition_id, goal_id, horizon,       │
│          measurable_outcome, evidence_level, priority_weight,  │
│          cohort_overrides, version, effective_dates]           │
│                                                                │
│         [Action templates: action_id, goal_link, owner_role,   │
│          duration, due_date_logic, success_criteria,           │
│          fallback_chain, dependencies, burden_score,           │
│          contraindications, cohort_overrides, version]         │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── INPUTS AGGREGATION (per care-plan run) ──────────────┐
│                                                                │
│  [Condition list and severity (FHIR Conditions)]               │
│  [Medication list (FHIR MedicationRequest)]                    │
│  [Recent labs and trajectories]                                │
│  [Recent encounters and admissions]                            │
│  [Care gap inventory]                                          │
│  [Adherence intervention recommendations]                      │
│  [Care management enrollment]                                  │
│  [Treatment-response predictions]                              │
│  [Wellness program candidates]                                 │
│  [Educational content matches]                                 │
│  [Provider relationships]                                      │
│  [Channel preferences]                                         │
│  [Goals-of-care preferences (POLST, advance directive)]        │
│  [Stated preferences (portal, intake forms)]                   │
│  [Social determinants of health]                               │
│  [Functional and cognitive status]                             │
│  [Family and caregiver involvement]                            │
│                          │                                     │
│                          ▼                                     │
│              [Persist normalized inputs to plan-input          │
│               record; freeze for plan reproducibility]         │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── GOAL DERIVATION ─────────────────────────────────────┐
│                                                                │
│  [Plan-input record]  [Goal templates]                         │
│                          │                                     │
│                          ▼                                     │
│              [Match conditions to goal templates,              │
│               apply cohort overrides, compute baseline         │
│               priority weights]                                │
│                          │                                     │
│                          ▼                                     │
│              [Apply goals-of-care alignment:                   │
│               re-weight goals against patient preferences      │
│               and POLST]                                       │
│                          │                                     │
│                          ▼                                     │
│              [Apply quality-program requirements:              │
│               attach measure references to applicable          │
│               goals]                                           │
│                          │                                     │
│                          ▼                                     │
│              [Persist goal_set with provenance per goal]       │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── ACTION ASSEMBLY AND RECONCILIATION ──────────────────┐
│                                                                │
│  [Goal set]  [Action templates]  [Plan inputs]                 │
│                          │                                     │
│                          ▼                                     │
│              [For each goal, generate candidate actions        │
│               from action templates, applying cohort           │
│               overrides and contraindication filters]          │
│                          │                                     │
│                          ▼                                     │
│              [Drug-drug, drug-disease, drug-allergy            │
│               interaction filters; suppress contraindicated    │
│               actions and surface deprescribing candidates]    │
│                          │                                     │
│                          ▼                                     │
│              [Burden estimation: compute cumulative            │
│               burden of the action set; if above threshold,    │
│               trigger prioritization compression]              │
│                          │                                     │
│                          ▼                                     │
│              [Capacity reconciliation: actions whose owner     │
│               is at capacity (e.g., a care manager with        │
│               a full panel) are flagged for substitution       │
│               or deferral]                                     │
│                          │                                     │
│                          ▼                                     │
│              [Schedule reconciliation: actions whose timing    │
│               conflicts with the patient's stated capacity     │
│               are sequenced rather than parallelized]          │
│                          │                                     │
│                          ▼                                     │
│              [Persist reconciled_action_set with provenance    │
│               and reconciliation decisions per action]         │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── PLAN FINALIZATION ───────────────────────────────────┐
│                                                                │
│  [Reconciled action set]  [Goal set]  [Plan inputs]            │
│                          │                                     │
│                          ▼                                     │
│              [Sequence actions: this-week,                     │
│               this-month, this-quarter, ongoing]               │
│                          │                                     │
│                          ▼                                     │
│              [Assign owners per action; verify each action     │
│               has an owner and a fallback path]                │
│                          │                                     │
│                          ▼                                     │
│              [Assemble plan_record: goals, actions, owners,    │
│               due dates, success criteria, fallback chains,    │
│               dependencies, provenance, plan_version]          │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── NARRATIVE GENERATION AND VALIDATION ─────────────────┐
│                                                                │
│  [Plan record]  [Patient communication preferences]            │
│  [Reading level]  [Language]                                   │
│                          │                                     │
│                          ▼                                     │
│              [Clinician-facing narrative: structured           │
│               summary plus prose; LLM-generated, validator-    │
│               protected; flags conflicts and changes]          │
│                          │                                     │
│                          ▼                                     │
│              [Patient-facing narrative: tailored,              │
│               reading-level matched, language matched,         │
│               channel-formatted; LLM-generated; validator-     │
│               protected]                                       │
│                          │                                     │
│                          ▼                                     │
│              [Care-team-internal disagreement narrative        │
│               where reconciliation could not resolve]          │
│                          │                                     │
│                          ▼                                     │
│              [Persist narratives keyed to plan_version]        │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── REVIEW, DELIVERY, AND ACTIVATION ────────────────────┐
│                                                                │
│  [Plan record + narratives]                                    │
│                          │                                     │
│                          ▼                                     │
│              [Clinical-team review surface: PCP,               │
│               care manager, relevant specialists; suggest      │
│               edits, override actions, approve]                │
│                          │                                     │
│                          ▼                                     │
│              [Patient review: present plan in preferred        │
│               channel; capture acknowledgment, questions,      │
│               and edits; teach-back where appropriate]         │
│                          │                                     │
│                          ▼                                     │
│              [Activation: actions become live tasks,           │
│               owners are notified, dependencies resolved,      │
│               communications are scheduled]                    │
│                                                                │
└────────────────────────────────────────────────────────────────┘

┌───────── FEEDBACK, ADAPTATION, EVALUATION ────────────────────┐
│                                                                │
│  [Action completion events]  [Outcome events]                  │
│  [Patient-reported feedback]  [Adverse events]                 │
│                          │                                     │
│                          ▼                                     │
│              [Update action statuses; compute plan adherence   │
│               and effectiveness metrics]                       │
│                          │                                     │
│                          ▼                                     │
│              [Trigger plan revision when conditions change,    │
│               actions fail, or scheduled review interval       │
│               elapses]                                         │
│                          │                                     │
│                          ▼                                     │
│              [Cohort-stratified plan-quality monitoring;       │
│               outcome-trajectory monitoring]                   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

**The clinical content layer is governance, not engineering.** Goal templates and action templates are clinical artifacts that the clinical-content team (clinical informatics, pharmacy and therapeutics, care management, quality, patient education) curates and approves. The templates are versioned, with effective dates, with cohort overrides, and with explicit provenance back to the source guideline. Updates go through the same kind of change-management process used for any versioned clinical catalog: changes that affect plan content are reviewed, parallel-evaluated against the prior version, and rolled out with a defined cutover window. The pattern that fails is when the templates are owned by engineering and updated as part of feature work; the clinical content drifts away from the current state of clinical practice and the system is shipping advice that the clinicians no longer endorse.

**The inputs aggregation layer is where the upstream signals compound.** Each input is produced by an upstream personalization system, whether that is one of the earlier recipes in this chapter or an equivalent capability your organization already runs: channel preferences, matched educational content, provider relationships, wellness program candidates, adherence intervention recommendations, the care gap inventory, care management enrollment status, and treatment-response predictions. The aggregation layer fetches the latest signals and freezes them in a plan-input record so the plan can be reproduced; reproducibility is a requirement for audit and for adverse-event investigation. The aggregation layer also pulls source clinical data (conditions, medications, labs, encounters), goals-of-care preferences (POLST, advance directives), stated preferences (portal questionnaires, intake forms), social determinants of health, functional and cognitive status, and family and caregiver involvement. The breadth of inputs is the personalization density that distinguishes 4.9 from prior recipes.

**The goal derivation layer is where condition-specific clinical guidelines meet patient-specific goals of care.** Goal templates are matched to the patient's active conditions, applying cohort overrides for pediatric, geriatric, palliative, pregnancy, and other populations where the disease-specific defaults do not apply unmodified. Baseline priority weights are computed from clinical urgency and from quality-program weighting (a goal that is also a quality measure may carry additional weight depending on the program). Goals-of-care alignment then re-weights the goals against the patient's stated preferences: a patient who has explicitly elected comfort-focused care has different goal weights than a patient who is pursuing aggressive disease management. The output is the goal set, with explicit provenance per goal so a clinician reviewing the plan can see why each goal is present and why it is weighted as it is.

**The action assembly and reconciliation layer is the heaviest synthesis work.** For each goal, the action templates produce candidate actions. Cohort overrides and contraindication filters remove the actions that do not apply to the patient. Drug-drug, drug-disease, and drug-allergy interaction checks filter further; the action assembly layer also surfaces deprescribing candidates as actions in their own right (a polypharmacy-aware care plan deprescribes proactively, not just prescribes). The burden estimation step computes the cumulative therapeutic burden of the candidate action set and triggers prioritization compression if the total burden exceeds a threshold; the threshold is patient-specific and reflects the patient's documented capacity. Capacity reconciliation flags actions whose owner is at capacity, suggesting substitution or deferral. Schedule reconciliation sequences actions that conflict on the patient's time. Each reconciliation decision is logged with provenance so the care team can review and override.

**The plan finalization layer produces the structured plan that is the system of record.** Actions are sequenced into time horizons (this-week, this-month, this-quarter, ongoing). Each action is assigned an owner; actions without an owner are surfaced to the care team for assignment rather than silently shipped without accountability. Each action has a fallback path; actions without a fallback are similarly surfaced. The plan record is assembled with goals, actions, owners, due dates, success criteria, fallback chains, dependencies, provenance, and a plan_version. The plan record is the structured artifact that downstream rendering, review, and activation operates on.

**The narrative generation and validation layer produces the human-readable artifacts.** Three narratives are produced per plan: the clinician-facing narrative (structured summary plus prose, surfacing conflicts, changes since prior plan, and any care-team-action-required items), the patient-facing narrative (tailored to the patient's reading level, language, channel preferences, and stated preferences), and the care-team-internal disagreement narrative (when reconciliation could not resolve a conflict, the narrative describes the conflict, candidate resolutions, and recommended escalation path). Each narrative goes through the LLM with a strict validator: the validator checks reading-level compliance, fact grounding (every clinical claim in the narrative must trace to a structured action, goal, or observation in the plan), prohibited-language patterns (no recommendation language for treatments not in the structured plan, no probabilistic claims framed as guarantees), required content (the patient-facing narrative must include the shared-decision framing, the contact information for questions, and the next-action callout), and approved-claim language enforcement. Failed validations regenerate with feedback or fall back to a templated narrative that is deterministic and always passes.

**The review, delivery, and activation layer is where the plan meets humans.** The clinical-team review surface presents the plan to the appropriate clinicians (PCP always, care manager always, relevant specialists per the active conditions). The clinicians can approve, suggest edits, override specific actions, or send the plan back for regeneration with structured feedback. The patient review presents the plan in the preferred channel (portal, mailed letter, in-person review with the care manager). Teach-back is offered where the clinical-content team has flagged it as appropriate. The patient's acknowledgment, questions, and edits are captured in structured form. Activation flips approved actions into live tasks: the medication change goes to the e-prescribing system, the appointment goes to the scheduling system, the program enrollment goes to the program registry, the patient-facing reminder goes to the channel-appropriate sender, and the care manager's outreach is queued.

**The feedback, adaptation, and evaluation layer is what turns this from a one-shot artifact into a living plan.** Action-completion events (the colonoscopy was completed, the cardiac rehab session was attended, the medication was filled) and outcome events (the A1c at three months, the weight trend, the blood pressure trend, the readmission status) feed back into the plan. The patient's self-reported feedback (PROMs, PREMs, portal messages) feeds back. Adverse events (a fall, a hospitalization, a medication side effect) feed back. The update layer changes action statuses, computes plan adherence and effectiveness metrics, and triggers plan revision when conditions change, actions fail, or the scheduled review interval elapses. The cohort-stratified plan-quality monitoring layer watches for differential plan ambition, complexity, and outcome trajectories across cohorts; differential plan complexity that correlates with race, language, or insurance is a fairness signal that needs investigation, not a cohort-specific feature.

**Equity instrumentation is non-negotiable.** Plan ambition parity across cohorts (the plan does not systematically aim lower for some cohorts than others). Plan complexity parity (the plan is not systematically simpler or more burdensome for some cohorts than others). Action assignment parity (some cohorts are not systematically assigned more self-management actions while other cohorts get more clinician-led actions). Outcome trajectory parity (plan-attributable outcome improvements are not concentrated in some cohorts). Each axis is monitored, with thresholds that trigger committee review when crossed. The Obermeyer pattern (proxies that encode access disparities driving differential recommendations) applies here in a slightly different form: a care plan generation system that aims its plans at what the model thinks the patient can do, where what-the-patient-can-do is conflated with what-the-patient-has-historically-had-access-to, will produce systematically less ambitious plans for patients in under-resourced cohorts. That is exactly the disparity the system should be working against, not reinforcing.

**Regulatory posture is set early.** In implementations where the care plan is reviewed and modified by the care team before activation, the clinical decision support is mediated by clinician judgment and the regulatory framing is similar to other care-management workflows. In implementations where the plan is presented to the patient with minimal clinical review (a chronic-disease self-management plan delivered through a patient portal, for example), the regulatory analysis tightens; depending on jurisdiction and the clinical claims made in the patient-facing narrative, FDA SaMD regulation may apply. Most production deployments err toward the reviewed-by-care-team posture; teams attempting more direct-to-patient delivery should invest in regulatory analysis early. 

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.09-architecture). The Python example is linked from there.

## The Honest Take

Personalized care plan generation is the recipe in this chapter where the gap between "the system produces a plan" and "the system produces a plan that meaningfully changes care" is the widest. Every health system, every payer, and every care management vendor has, at some point, shipped a care plan generator. Most of those generators produce a document. The document goes into the EHR. The document is opened occasionally. The document is updated rarely. The document does not, in any honest accounting, change what happens to the patient. The architecture in this recipe is largely about the operational, content, and engagement discipline that distinguishes a plan that changes care from a plan that occupies disk space. Most of that discipline is not AWS-specific. Most of it is clinical content choices made well, governance applied seriously, multi-actor orchestration designed deliberately, and LLM constraints enforced strictly. The cloud infrastructure is comparatively easy.

The trap most specific to this domain is treating the LLM as the structural assembly engine. A team that hands the LLM the patient's record, the guidelines, and the prompt "generate a personalized care plan" will get a plausible-looking output that is not auditable, not reproducible, and not safe to act on without thorough clinical review every time. The structured-then-narrative direction (the goal-derivation, action-assembly, and plan-finalization stages produce the structured plan; the narrative stage wraps it in prose) is the difference between a system that compounds clinical content investment and a system that re-litigates every plan from scratch. The discipline is to keep the LLM from making clinical decisions; the LLM produces words about decisions that the structured logic has already made. That sounds like a small distinction. It is the recipe.

A trap I keep seeing fresh teams fall into: skimping on the goals-of-care alignment because the data is messier than the disease-specific guidelines. Goals-of-care preferences are partially structured (POLST, advance directives), partially semi-structured (patient-portal questionnaires, structured ACP conversation notes), and partially unstructured (free-text notes about what the patient said in the visit). Building the pipeline that elevates these signals into structured goal-weighting inputs is not glamorous work, but it is the work that makes the plan reflect the patient rather than reflect the algorithm's best guess about a typical patient. Skip it and the plan optimizes for clinical outcomes the patient did not pick, which is a category of failure the patient experiences as the system not listening.

Another trap, related: treating the burden estimation as a footnote. Burden compression decides which actions get dropped or deferred when the action set exceeds the patient's feasible total. That decision affects what the patient actually does. A naive burden score (count of actions, sum of touch points) misses that some actions are higher-burden in a specific patient's life (the colonoscopy is high-burden for a patient without transportation; low-burden for one with), and the compression decisions made on a naive score will systematically defer the wrong actions for the patients with the least support. Patient-specific, social-context-aware burden scoring is meaningful work; the alternative is compression decisions that quietly disadvantage the patients who most need a thoughtful plan.

The thing that surprises people coming from generic ML backgrounds is how much of the work is content and operations rather than modeling. The clinical-content library, the multi-condition reconciliation rules, the cohort overrides, the burden scoring, the activation integrations, the channel integrations, the consent posture, the regulatory analysis: each is multi-month work. The ML and the LLM are the easier parts. The pattern that fails is a team that frames care plan generation as "an LLM problem with some data plumbing" and ships a system that produces fluent narrative on top of a thin clinical-content layer. The narrative reads well. The clinical content is shallow. The clinical team notices within a month.

The thing about the LLM specifically: the four-layer validator is non-negotiable, and the templated fallback should be a respectable artifact. A team that under-invests in the templated fallback ends up shipping LLM output even when the validator wants to fall back, because the fallback looks worse. The fix is to invest in the templated path so the fallback is a clean, scannable, structured presentation that is less narrative-rich but never crosses into prohibited territory. A clean templated narrative is better than a polished LLM narrative that the validator was uncertain about. Calibrate accordingly.

The thing I would do differently the second time: invest more heavily in the upstream event flow before the launch. Care plan generation pulls signals from every upstream personalization system; the assumption is that those signals are present and current. The reality is that any one of those upstream pipelines can be stale, partial, or wrong, and the plan should be resilient to that. Build the upstream-signal-quality monitoring before the plan generator is in production; do not let the plan generator silently degrade because an upstream signal source has been emitting nulls for a week.

The thing about clinician engagement: the plan's value depends on the care team treating it as a working document, not a checkbox. The systems that succeed are ones where the care manager opens the plan at the start of every patient interaction and the PCP looks at it before every visit; the systems that fail are ones where the plan is generated, filed, and ignored. The technical work makes the latter possible; the operational work makes the former real. Invest in the rollout discipline: small clinical pilots with deliberate framing, iterative feedback collection, willingness to redesign the review surface, and explicit success metrics that measure plan engagement, not plan generation volume. The pattern that fails is launching to the entire care team and discovering after six months that engagement is sporadic.

The thing about patient engagement: the patient-facing narrative is the surface area where the system meets the patient's life. A narrative that reads as bureaucratic, confusing, or condescending is one that the patient skims and forgets. The reading-level enforcement, the language preference, the cultural sensitivity, and the channel preference are not nice-to-haves; they are the difference between a narrative that the patient actually engages with and one that they discard. The work of getting the patient-facing narrative right is collaborative with patient advocates, clinical educators, and (ideally) actual patients who review the output before it ships. A patient-facing narrative that has not been reviewed by patients is one that has not been validated; the LLM and the validator catch the technical failures, not the lived-experience failures.

The thing about cohort fairness: plan ambition parity is the headline metric, and it is necessary but not sufficient. Even a system with cohort-fair plan ambition can produce systematically different outcomes if the underlying access, support, and engagement infrastructure differs across cohorts. A plan that aims at the same ambition for all patients but provides effective transportation only for some is a plan that produces unequal outcomes. The fairness analysis must extend past the plan content to the activation integrations, the channel preferences, the family-caregiver involvement, and the outcome trajectories. Plan for fairness as an ongoing analysis discipline, not a launch-time check.

A trap worth flagging: the difference between plans for one patient and plans for a population. A plan for Linda is a personalized artifact; the population of Linda-like patients is a portfolio that the care management program is responsible for. A plan that is well-personalized for Linda but inconsistent with the plans of the other patients in her cohort produces operational chaos for the care manager and the social worker. The pattern that works is per-patient personalization within a portfolio-aware framework: the cohort-level priorities (CHF readmission reduction, A1c control, COL screening) inform the goal weighting, and the per-patient personalization is on top. Both layers matter; neither is sufficient alone.

Last point, because it is specific to this use case: care plan generation is the recipe in this chapter where the patient's life intersects most directly with the system's output. Every recipe in this chapter affects the patient, but this one is where the patient reads the system's output and acts on it (or doesn't). That means the system is, in a real sense, a co-author of the patient's care. The seriousness with which the team treats that authorship is the difference between a system that earns the patient's trust and one that erodes it. The clinical content has to be right. The personalization has to be honest. The narrative has to be readable in the patient's language, at the patient's reading level, in the patient's preferred channel. The feedback loop has to be respected (a patient who said "this didn't work for me" should see the system change, not repeat the same suggestion at the next review). The operational discipline has to back the technical work. The system that gets these right does not produce a wow; it produces a quiet "this works for me" that, scaled across thousands of patients, is the version of healthcare personalization the chapter has been pointing at all along. Build for that.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Channel preferences from 4.1 drive the patient-facing narrative delivery in 4.9. The infrastructure compounds: 4.1 establishes the channel preference store; 4.9 reads from it.
- **Recipe 4.2 (Patient Education Content Matching):** Educational content matches from 4.2 surface as content-link actions in 4.9. The reading-level enforcement pattern from 4.2 applies directly to the patient-facing narrative in 4.9.
- **Recipe 4.3 (Provider Directory Search Optimization):** Provider relationships from 4.3 inform action ownership assignments in 4.9 (the patient's preferred specialists are the default owners for specialist-related actions).
- **Recipe 4.4 (Wellness Program Recommendations):** Wellness program candidates from 4.4 surface as program-enrollment actions in 4.9.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Adherence interventions from 4.5 surface as adherence-support actions in 4.9. The intervention-targeting CATE estimates inform the action-priority weighting.
- **Recipe 4.6 (Care Gap Prioritization):** The care gap inventory from 4.6 is a primary input to the goal derivation in 4.9. Care gaps become measure-linked goals; care-gap-closure actions become this-month or this-quarter actions.
- **Recipe 4.7 (Care Management Program Enrollment):** Care management enrollment status from 4.7 determines the care manager's role in the plan; an enrolled patient has the care manager as a primary owner; an unenrolled patient sees the program as a candidate action.
- **Recipe 4.8 (Treatment Response Prediction):** CATE estimates from 4.8 inform treatment-related actions in 4.9. The plan integrates the comparison-briefing output for treatment-decision actions; the regulatory posture from 4.8 carries into the treatment-related sections of the plan.
- **Recipe 4.10 (Dynamic Treatment Regime Recommendation):** 4.9 is the substrate for 4.10. 4.9 produces the plan at a point in time; 4.10 produces sequences of plan adjustments over time as the patient's state evolves.
- **Recipe 2.x (LLM / Generative AI):** The narrative generation and validator pattern uses techniques developed across Chapter 2; the validator pattern from 2.5 (After-Visit Summary) and 2.9 (Clinical Decision Support Synthesis) applies directly.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** Risk-stratification scores feed the plan input record; high-risk patients get more frequent plan review cadences and more action-focused plans.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Disease-trajectory forecasting from Chapter 12 informs the goal horizons and the action timing.
- **Recipe 13.x (Knowledge Graphs):** The clinical content library, with relationships between conditions, goals, actions, contraindications, and guideline references, is naturally modeled as a knowledge graph at higher sophistication levels.
- **Recipe 11.x (Conversational AI):** Patient-facing conversational interfaces can deliver and adapt the plan interactively, leveraging the structured plan as the source of truth for the conversation.

---

## Tags

`personalization` · `care-plan-generation` · `multi-condition-reconciliation` · `goals-of-care` · `therapeutic-burden` · `polypharmacy` · `deprescribing` · `equity` · `cohort-analysis` · `fhir` · `careplan-resource` · `clinical-decision-support` · `smart-on-fhir` · `bedrock` · `dynamodb` · `feature-store` · `step-functions` · `lambda` · `pinpoint` · `healthlake` · `complex` · `research-to-production` · `hipaa`

---

*← [Recipe 4.8: Treatment Response Prediction](chapter04.08-treatment-response-prediction) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.10 - Dynamic Treatment Regime Recommendation →](chapter04.10-dynamic-treatment-regime-recommendation)*
