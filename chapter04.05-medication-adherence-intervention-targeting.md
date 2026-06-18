# Recipe 4.5: Medication Adherence Intervention Targeting ⭐⭐

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.003-0.015 per intervention recommendation (depends on uplift model serving and LLM tailoring)

---

## The Problem

Maria is 58. She has type 2 diabetes, hypertension, and high cholesterol. Her medication list, in plan-formulary terms, is unremarkable: metformin twice daily, lisinopril once daily, atorvastatin once daily, and (added six months ago after a cardiology consult) a once-daily SGLT2 inhibitor. Her PCP wrote those prescriptions confident that Maria would take them, because Maria is a careful person who shows up for appointments and asks good questions. The PCP also has 1,800 other patients and does not have the bandwidth to track whether Maria's pharmacy refills are happening on schedule.

The plan's pharmacy benefit manager has the data, of course. Maria's metformin is being filled monthly, on time, every time. Her lisinopril is being filled monthly, on time, every time. Her atorvastatin is being filled, on average, once every 47 days. Her SGLT2 inhibitor was filled once, six months ago, and never again. If you computed her proportion of days covered (PDC) for each medication, metformin would be 98 percent, lisinopril would be 96 percent, atorvastatin would be 64 percent, and the SGLT2 would be 14 percent.

If you ranked Maria's medications by adherence problem, the SGLT2 inhibitor is the obvious crisis. The atorvastatin is a slower problem that's been quietly developing for years. The two she takes well are doing what they're supposed to. So far so good: the data tells you what's wrong, and any halfway competent analytics team can produce that ranking.

What the data does not tell you is *why*. The atorvastatin: Maria's brother had muscle pain on a statin and told her to be careful, so she takes it three or four days a week instead of seven. She thinks she's being prudent. The SGLT2 inhibitor: the copay was $84 a month, Maria filled it once, walked out of the pharmacy stunned, and decided she would talk to the doctor about it at her next visit. The next visit was four months out. She forgot to bring it up at the visit. The doctor assumed she was taking it.

Now imagine an adherence-intervention program that, on the basis of "Maria's PDC for the SGLT2 is 14 percent," sends her a text message reminder to take her medication. The text arrives. Maria does not have the medication. She has not had it for five months. The text is irrelevant. Worse, the text is mildly insulting: it implies Maria forgot to take a medication she could not have taken because she could not afford it. She unsubscribes from the plan's text messages. The plan now has lost its outreach channel for the next intervention.

The atorvastatin gets a different text: "remember to take your atorvastatin daily." Maria reads it, thinks "I am taking it carefully on purpose," and ignores it. The text doesn't address the actual barrier (she has a belief about side effects from a family member's experience), so it doesn't move the behavior. The plan logs it as "delivered" and "no response," which counts as a successful outreach in the operations dashboard, and counts as nothing in the actual world where Maria still has uncontrolled cholesterol.

Six months later, Maria's HbA1c has drifted up. Her LDL is 142. Her cardiologist's note from her recent visit is direct: she is not on the medications they prescribed. The cardiologist increases her metformin (the one she's actually taking), adds a referral to a clinical pharmacist, and writes in the chart that adherence is a problem. The plan's adherence dashboard, separately, marks Maria as "non-adherent across multiple chronic medications" and the case is escalated to a care manager, who has seventy other cases and will get to Maria in three weeks.

This is what medication adherence intervention looks like in practice. The data identifies the *what*: which medications, which patients, which adherence levels. The hard work is identifying the *why*, and matching the *why* to the right intervention. Reminders work for forgetfulness. They do not work for cost barriers or belief barriers or side-effect concerns or "the medication makes me dizzy and I haven't told anyone." A blanket reminder campaign for everyone with a PDC under 80 percent will produce reminders for thousands of Marias, most of which are irrelevant to the actual barrier, and the program will report a 2 to 4 percent improvement in PDC in the cohort that did get a behavior change, while the other 96 to 98 percent of the campaign was at best wasted effort and at worst counterproductive.

A second wrinkle that makes adherence intervention distinct from wellness program targeting (Recipe 4.4) and from the rest of this chapter: the catalog of interventions is *heterogeneous*. Wellness programs are similarly shaped objects (a multi-week curriculum, with sessions, with a coach or app). Adherence interventions are not. The plan's intervention slate typically includes:

- Behavioral reminders (text, app push, automated voice, mailed reminder cards)
- Pharmacist outreach (telephonic, in-store at retail pharmacies, video-visit with a clinical pharmacist)
- Cost-assistance navigation (manufacturer copay cards, foundation grants, formulary alternatives, switching from brand to generic, switching from retail to mail-order, switching from 30-day to 90-day fills, Low-Income Subsidy enrollment for Medicare members)
- Regimen simplification (combination pills, once-daily versus twice-daily formulations, blister packs, pill organizers)
- Education interventions (printed material, video, motivational interviewing scripts, peer-support groups)
- Care-team escalation (PCP outreach, care manager assignment, social work referral)
- Synchronized refill programs (med sync at the pharmacy so all chronic meds refill on the same day)

These have wildly different costs, different operational requirements, different evidence bases, and different patient experiences. A text reminder costs cents. A clinical pharmacist video visit costs $40 to $80 of staff time. A manufacturer copay card application costs staff time but no marginal medication cost. A regimen simplification requires a prescriber action. The recommender has to choose not just *whether* to intervene but *which* intervention, and the choice has to be matched to the underlying barrier, not just to the patient's PDC.

A third wrinkle: Star Ratings and HEDIS pressure. CMS Medicare Advantage Star Ratings include three Pharmacy Quality Alliance (PQA) medication adherence measures (Adherence to Cholesterol Statins, Adherence to Hypertension RAS Antagonists, and Adherence to Diabetes Medications), all with denominators based on use of the medication class regardless of indication. (Note: a separate HEDIS Part C measure, Statin Therapy for Patients with Cardiovascular Disease, evaluates statin *use* in CVD patients rather than adherence; the two are easy to conflate and aren't the same thing.) The cut points are unforgiving: a patient with a PDC of 79 percent and a patient with a PDC of 81 percent count differently for the plan even though their clinical risk is essentially identical. This produces a real organizational temptation to optimize for the cohort just below the cut point ("if we can get these 4,000 members from 78 to 81 percent, we move the Star score") at the expense of the cohort with PDCs in the 30 to 50 percent range, where the clinical lift is much larger but the Star Ratings improvement per member is smaller. The recipe is going to flag this trap explicitly, because it is one of the most common ways adherence-intervention programs end up doing the wrong thing very efficiently. 

A fourth wrinkle: pharmacy data is messy. Claims arrive on a 1 to 30 day lag (retail pharmacy claims are usually within 48 hours; mail-order can be a week; specialty pharmacy can be longer). Cash-paying members, members using manufacturer-direct programs, and members using GoodRx or similar discount programs may not show up in PBM data at all. Patients with multiple pharmacies have fragmented data. 90-day mail-order fills can look like 30-day non-adherence if the calculation isn't careful. Therapeutic substitutions (a patient swaps from atorvastatin to rosuvastatin) can look like non-adherence if you're computing PDC by NDC instead of by therapeutic class. None of these are exotic edge cases. They affect 10 to 30 percent of the population in a typical plan, and they tilt the recommender's view of who is non-adherent in directions that correlate with socioeconomic status.

So the problem statement, again, is deceptively simple: given a patient's medication regimen, their fill history, their clinical context, their cost-sharing situation, and their prior engagement history, decide which adherence intervention (or sequence of interventions) is most likely to actually change their behavior, allocate finite intervention capacity across the population, and track whether the intervention worked. Not the same text message blast for everyone with a PDC under 80. The right intervention, for the right patient, at the right time, with honest measurement of whether it changed anything.

We're going to build that. This recipe leans heavily on Recipe 4.4's uplift-and-allocation pattern (we won't re-derive it; go read 4.4 if you skipped it), and adds three new pieces specific to adherence: barrier classification (figuring out the *why*), heterogeneous intervention scoring (different intervention types compete for the same patient), and pharmacy-data-aware adherence measurement (PDC done correctly, with the data lag and fragmentation handled honestly). The architecture is structurally similar to 4.4. The clinical and operational details are different enough that the recipe is worth its own treatment.

Let's get into how you build it.

---

## The Technology: Adherence Measurement, Barrier Classification, and Heterogeneous Intervention Uplift

### Adherence Measurement, Done Honestly

Before any modeling, the system has to compute adherence. The two metrics that matter:

- **Proportion of Days Covered (PDC).** Over an evaluation window (commonly 365 days, sometimes shorter), the fraction of days the patient had medication on hand based on fill dates and days-supply. PDC is the metric CMS uses for Star Ratings and HEDIS uses for adherence measures. PDC of 0.80 is the canonical "adherent" threshold; the plan-population number that matters for Star Ratings is the percentage of patients with PDC at or above 0.80.
- **Medication Possession Ratio (MPR).** Similar to PDC but computed as total days supplied divided by days in the window. MPR can exceed 1.0 (overlapping fills, stockpiling). Most modern programs use PDC because it caps at 1.0 and behaves better at the boundary.

Both metrics depend entirely on having clean fill data. Two non-obvious complications that wreck the calculation if you ignore them:

**Therapeutic class versus molecule.** A patient on atorvastatin who switches to rosuvastatin should not be marked non-adherent for the gap. Compute PDC at the therapeutic-class level (statins, RAS antagonists, oral diabetes medications) using the AHFS or NDF-RT classifications, not at the NDC level. The CMS Part D Star Ratings methodology, via the PQA measure specifications, defines the canonical class membership for the three adherence measures; use those definitions to keep your numbers comparable to the Star Ratings reporting your plan will be measured on. 

**Fill cadence and overlapping supplies.** A patient who fills a 90-day supply in January doesn't need to fill again until April. If you compute PDC monthly, January looks like 100 percent adherence and February looks like 0 percent, when actually the patient is fine. The standard fix is "carry forward" days-supply: track running days-on-hand on a daily basis, and PDC is the count of days where days-on-hand was greater than zero.

**Mail-order and synchronization.** Patients on mail-order receive their meds in 90-day batches. Patients on med-sync at retail get all their chronic meds aligned to a single refill day, which can shift fill dates around the calendar in ways that look like non-adherence to a naive computation but are actually a sign of *good* adherence (the program worked).

**Data lag.** Retail pharmacy claims typically arrive within 48 hours. Mail-order can be 5 to 14 days. Specialty pharmacy varies wildly. Cash payments via discount programs may never arrive. The recommender has to reason about "the most recent fill the system can see" versus "the most recent fill that may have happened." A common pattern: compute PDC with a 30-day lag (PDC as of 30 days ago) for stable measurement, and a "best-effort current PDC" with explicit uncertainty for real-time targeting.

**Cash-pay and discount-card invisibility.** A meaningful fraction of members fill at least one chronic medication outside the PBM's data feed: GoodRx for cheaper generics, manufacturer assistance programs for branded drugs, supermarket $4 generic lists. The recommender will see "no fill" for these and conclude non-adherence, when actually the patient is filling but the data isn't there. The mitigation is partial at best: prompt the patient periodically about cash-pay fills (low-friction in-app survey), use clinical signals (continued PCP visits, repeat prescriptions written) as a sanity check, and tag patients with known cash-pay history so the recommender weights claims-derived adherence less heavily for them. Don't pretend the data is complete when it isn't.

### Barrier Classification: Why Aren't They Adherent?

This is the part most adherence programs skip. Without a barrier, the intervention is a guess.

The standard barrier taxonomy, simplified, has six rough categories:

- **Cost.** The patient can't or won't pay the copay. Often correlated with high-cost branded medications, members in deductible phases, members at low-income thresholds without LIS enrollment.
- **Forgetfulness.** The patient intends to take the medication but misses doses or fills. Often correlated with complex regimens (more than three chronic meds), older patients, patients with cognitive concerns.
- **Beliefs and concerns.** The patient has concerns about side effects, has heard things from family or social media, doesn't believe the medication is necessary, or has cultural concerns about long-term medication use. Often surfaces in symptomatic conditions where the patient feels fine without the medication (hypertension, dyslipidemia).
- **Side effects.** The patient is experiencing actual side effects and has self-reduced or stopped. Rarely volunteered to providers without prompting. The right answer is not "remind them to take it"; the right answer is "schedule a clinical conversation about alternatives."
- **Complexity.** The regimen itself is too complex to manage. Multiple times per day, food restrictions, drug-drug interactions the patient is trying to navigate alone. The right intervention is regimen simplification, not reminders.
- **Access.** The patient can't get to the pharmacy, can't navigate prior authorization, can't get the prescription written without a visit they can't get scheduled. The right intervention is care-team or pharmacist outreach, not patient-facing nudges.

How do you classify? Three approaches in practice, in increasing order of ambition:

**Rule-based.** Engineered features feed an explicit decision tree. Cost-sharing is high and the gap started after a copay change → cost barrier. Patient is on more than four chronic medications and the gaps are sporadic → forgetfulness or complexity. Patient discontinued shortly after fill, never refilled → beliefs/concerns or side effects. Transparent, auditable, and the right starting point. Misses subtle cases.

**Supervised classification.** Train a classifier on labeled non-adherence episodes where the barrier was identified through later patient outreach (call, survey, MTM session). Features: pharmacy claims patterns, copay levels, formulary changes, demographic and clinical context, prior engagement responses. The training labels are scarce (you need a barrier-elicitation program running in parallel) but the lift over rules can be material. Accuracy of the classifier is bounded by the quality of the labels: if pharmacist outreach calls preferentially elicit barriers from English-speaking, phone-comfortable members, the classifier will learn those patterns more confidently and be less reliable for everyone else.

**LLM-assisted classification.** A small LLM call given the patient's structured medication history, claims, and prior outreach notes can produce a reasoned barrier hypothesis with explicit uncertainty. This works best as a *second opinion* on the rule-based classifier rather than as a primary decision: a structured-output prompt that returns the predicted barrier, its confidence, and a one-paragraph rationale. The rationale is auditable, the structured output is consumable, and the human (clinical pharmacist or care manager) can review the LLM's reasoning when the stakes warrant it. Don't put the LLM in the autonomous decision path; keep it as augmentation.

A note on barrier ambiguity. Most patients do not have a single barrier. Maria from the opening had three: a belief barrier on the statin, a cost barrier on the SGLT2, and a communication-with-prescriber barrier underlying both. The barrier classifier should produce a *ranked list* of likely barriers with probabilities, not a single label, and the intervention recommender should be allowed to recommend a sequence (cost-assistance first to get the SGLT2 in the patient's hand, then a clinical conversation about the statin concern). Single-label barrier classification is a useful simplification for the first pass; multi-label barrier classification is the right long-term target.

### Heterogeneous Intervention Scoring

In Recipe 4.4, all the items in the catalog were similarly shaped (multi-week wellness programs). Here they aren't. A text reminder, a clinical pharmacist video visit, a manufacturer copay-card application, and a med-sync enrollment are different in cost, in evidence base, in operational footprint, and in patient experience. The recommender has to score each (patient, intervention, medication) triple, where the intervention is from a heterogeneous catalog.

Three scoring components per (patient, intervention, medication):

**Need score.** Is this patient's adherence problem real and clinically meaningful for this medication? A PDC of 78 percent on a statin in a primary-prevention 45-year-old is a different problem from a PDC of 78 percent on a statin in a post-MI 70-year-old. The need score is a clinical risk model (essentially a small Chapter 7 risk-scoring problem) that estimates the marginal clinical harm of continued non-adherence over the next 6 to 12 months given the patient's full clinical context.

**Barrier-fit score.** Does this intervention type address this patient's likely barrier? A reminder is a high-fit intervention for forgetfulness, a low-fit intervention for cost, and an actively counterproductive intervention for side-effect-driven non-adherence. The barrier-fit score is the conditional probability that this intervention type works for this barrier type, learned from historical (intervention, barrier, outcome) data and seeded with literature priors where data is sparse.

**Engagement-and-uplift score.** Same pattern as Recipe 4.4: predict the probability the patient will engage with this intervention if recommended, and predict the causal change in adherence (and downstream clinical outcome) from recommending it. Per-intervention-type engagement models (engagement with a text reminder is a different prediction from engagement with a clinical pharmacist call), per-intervention-type uplift models. The uplift model here is even more critical than in 4.4 because the intervention catalog includes some interventions that are nearly free (a text message) and some that are expensive (a clinical pharmacist consult), and the cost-effectiveness math depends on getting the uplift estimates right per intervention type.

The combined per-(patient, intervention, medication) priority score is a documented policy: weights on need, barrier-fit, engagement, and uplift, plus a cost-effectiveness term that incorporates the intervention's marginal cost. Different organizations weight these differently. A health plan focused on Star Ratings will weight uplift in the 75 to 85 percent PDC band heavily. An accountable care organization focused on total cost of care will weight clinical-need and uplift in the 30 to 60 percent PDC band heavily, where the clinical risk of continued non-adherence is largest. Both are defensible. Make the policy explicit, version it, review it quarterly. Don't bury it in the model.

### Allocation Across Heterogeneous Capacities

Capacity constraints are even more granular here than in 4.4. Each intervention type has its own capacity profile:

- Text reminders: nearly unbounded daily capacity, soft-bounded by per-patient contact-frequency caps.
- Telephonic pharmacist outreach: bounded by FTE capacity, typically 15 to 25 patients per pharmacist per day for substantive consults.
- Clinical pharmacist video visits: similar bound, plus appointment-scheduling overhead.
- Cost-assistance navigation: bounded by case-management capacity (each application takes 30 to 90 minutes of staff time, longer for foundation grants).
- Med-sync enrollment: bounded by retail pharmacy partnership capacity and the patient's pharmacy choice.
- Care-team escalation: bounded by PCP and care-manager bandwidth.

The allocator has to respect each intervention's per-day capacity, the cumulative per-patient contact-frequency cap, and any cross-intervention exclusions (a patient referred for a clinical pharmacist consult does not also get the text-reminder enrollment for the same medication; the pharmacist will handle the reminder framing). A greedy allocator sorted by priority is a fine starter, with two adjustments from 4.4:

- **Multi-intervention assignment per patient.** Unlike 4.4 where each patient was allocated one program per run, an adherence run may allocate multiple interventions to one patient when their barriers warrant it (cost-assistance navigation for the SGLT2 plus a belief-conversation pharmacist call for the statin). The allocator's per-patient cap is policy: typical defaults are at most 2 interventions per patient per run, at most 1 high-touch intervention (pharmacist or care manager), at most 3 patient-facing contacts in any 30-day window.
- **Sequencing within a patient.** Some interventions chain. Cost-assistance navigation is typically a prerequisite to "patient now has the medication"; a reminder enrollment chained after the navigation completes is more likely to land. The allocator can either assign in sequence with the chain explicit, or assign the first link only and let a state machine reschedule the next link when the first completes. The state-machine version is more robust; the sequence version is simpler and acceptable for early implementations. 

### Where LLMs Fit (and Don't)

Same as 4.4 with adherence-specific notes:

- **Adherence measurement, barrier rules, intervention scoring, capacity allocation.** Not the LLM's job. Auditable models and rules, not generation.
- **Barrier classification as second opinion.** Yes, with structured output and explicit confidence. Frame it as a hypothesis the rule-based or supervised classifier can be checked against, not as the primary signal.
- **Outreach message tailoring.** Yes, for patient-facing reminders, education, and motivational content. The same pattern as 4.4: structured input goes in, tailored content comes out, the message goes through a clinical-claims validator before send.
- **Pharmacist call preparation.** When a clinical pharmacist is going to call a patient, an LLM can generate a structured pre-call brief: the patient's medication regimen, the suspected barrier, the prior fill history, suggested talking points, contraindications to flag. This saves the pharmacist 5 to 10 minutes per call and improves call quality, with the pharmacist always in the decision loop.
- **PCP and care-team summaries.** Same pattern as 4.4's PCP briefings. A structured summary of the patient's adherence picture, the recommended intervention, and the rationale, written into the EHR inbox or care-team dashboard.

What the LLM does *not* do: pick the intervention. Decide whether to escalate to a pharmacist. Override the cost-barrier path with a cheaper reminder because the LLM thought the patient seemed compliant. The recommender picks. The LLM packages.

### Where This Sits in the Chapter

This recipe builds directly on Recipe 4.4. The patient-profile DynamoDB table from 4.1, extended in 4.4, gets new attributes (`pharmacy_data_quality`, `cash_pay_history`, `cost_sharing_tier`, `med_sync_enrolled`). The engagement-event Kinesis stream gets new event types (`adherence_intervention_recommended`, `intervention_engaged`, `intervention_completed`, `pharmacy_fill_observed`, `barrier_elicited`). The SageMaker Feature Store features defined in 4.4 are reused; new features are added for medication-specific signals (per-medication PDC, days since last fill, cost-sharing for the specific drug, formulary tier, days-supply pattern).

The uplift-modeling investment from 4.4 transfers directly. The capacity-aware allocator gains a multi-intervention-per-patient mode and a per-intervention-capacity model. The cohort fairness instrumentation from 4.3 and 4.4 becomes more important here because adherence outcomes have well-documented disparities by race, language, geography, and socioeconomic status, and a poorly built recommender will encode those disparities into its targeting. Recipe 4.6 (Care Gap Prioritization) and Recipe 4.7 (Care Management Program Enrollment) reuse this recipe's barrier-classification and multi-intervention scoring patterns.

---

## General Architecture Pattern

The pipeline has five logical components: a pharmacy-data ingestion path that computes adherence metrics correctly, a barrier-classification path that turns adherence gaps into hypothesized "why" labels, an intervention-catalog ingestion path that maintains the slate of intervention types and capacities, a batch recommendation path that runs frequently to produce (patient, intervention, medication) allocations, and a feedback path that captures fill outcomes, intervention engagement, and downstream clinical change.

```text
┌──────── PHARMACY DATA INGESTION (continuous) ─────────────┐
│                                                            │
│  [Retail pharmacy]   [Mail-order]   [Specialty pharmacy]   │
│           │                │                │              │
│           └────────┬───────┴────────┬───────┘              │
│                    ▼                ▼                      │
│         [Normalize fills: NDC -> therapeutic class,        │
│          days-supply, fill date, copay paid, channel]      │
│                    │                                       │
│                    ▼                                       │
│         [Compute per-medication PDC (carry-forward,        │
│          therapeutic-class level, lag-aware)               │
│          Compute regimen complexity (n meds, n doses)]     │
│                    │                                       │
│                    ▼                                       │
│         [Persist to feature store keyed on                 │
│          (patient_id, therapeutic_class)]                  │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────── BARRIER CLASSIFICATION (daily/weekly) ────────────┐
│                                                            │
│  [Adherence features]   [Claims context]   [Engagement]    │
│           │                    │                │          │
│           └─────────┬──────────┴────────┬───────┘          │
│                     ▼                   ▼                  │
│         [Stage A: rule-based barrier classifier            │
│          (cost, forgetfulness, beliefs, side-effects,      │
│           complexity, access)]                             │
│                     │                                      │
│                     ▼                                      │
│         [Stage B: supervised classifier (when labels       │
│          available) refines confidence per barrier]        │
│                     │                                      │
│                     ▼                                      │
│         [Stage C (optional): LLM second-opinion             │
│          structured-output review for high-stakes cases]   │
│                     │                                      │
│                     ▼                                      │
│         [Persist ranked barriers + confidences per         │
│          (patient, medication)]                            │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──── INTERVENTION CATALOG INGESTION (low cadence) ─────────┐
│                                                            │
│  [Plan config]  [Vendor partners]  [PBM tools]             │
│         │              │                │                  │
│         └──────┬───────┴──────────┬─────┘                  │
│                ▼                  ▼                        │
│      [Intervention record: type, supported barriers,       │
│       evidence base, marginal cost, daily capacity,        │
│       eligibility (e.g., LIS-eligible only,                │
│       brand-only, retail-pharmacy-only)]                   │
│                │                                           │
│                ▼                                           │
│      [Persist to intervention-catalog store]               │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌────── BATCH RECOMMENDATION RUN (e.g., weekly) ────────────┐
│                                                            │
│  [Trigger: schedule + Star Ratings cycle awareness]        │
│           │                                                │
│           ▼                                                │
│  [Stage 1: target set (patients with >= 1 medication       │
│   below adherence threshold for the run)]                  │
│           │                                                │
│           ▼                                                │
│  [Stage 2: per-(patient, medication) need scoring          │
│   (clinical risk of continued non-adherence)]              │
│           │                                                │
│           ▼                                                │
│  [Stage 3: intervention eligibility filter                 │
│   per (patient, intervention, medication)                  │
│   (LIS status, formulary tier, channel, exclusions)]       │
│           │                                                │
│           ▼                                                │
│  [Stage 4: per-(patient, intervention, medication)         │
│   barrier-fit scoring + engagement prediction              │
│   + uplift estimation]                                     │
│           │                                                │
│           ▼                                                │
│  [Stage 5: combined priority + cost-effectiveness          │
│   per documented policy weights]                           │
│           │                                                │
│           ▼                                                │
│  [Stage 6: capacity-aware allocation                       │
│   (heterogeneous capacities, equity floors,                │
│    multi-intervention-per-patient cap, sequencing)]        │
│           │                                                │
│           ▼                                                │
│  [Stage 7: outreach + pharmacist scheduling +              │
│   care-team alerts (channel optimizer + structured         │
│   handoffs to staff queues)]                               │
│           │                                                │
└───────────┼────────────────────────────────────────────────┘
            │
            ▼
     [Patient receives intervention / pharmacist call /
      cost-assistance navigation / med-sync enrollment]
            │
┌───────────┼────────────────────────────────────────────────┐
│           ▼                                                │
│  [Engagement events: opened, scheduled, completed,         │
│   barrier_elicited, intervention_outcome,                  │
│   pharmacy_fill_observed]                                  │
│           │                                                │
│           ▼                                                │
│  [Short-horizon: feed engagement-prediction + barrier      │
│   classifier (when staff elicit ground-truth barrier)]     │
│           │                                                │
│           ▼                                                │
│  [Medium-horizon (months): observed PDC change feeds       │
│   uplift training and intervention-effectiveness model]    │
│           │                                                │
│           ▼                                                │
│  [Long-horizon (months-years): clinical outcomes           │
│   (HbA1c, BP, LDL, hospitalization) feed program-level     │
│   cost-effectiveness evaluation]                           │
│           │                                                │
│           ▼                                                │
│  [Cohort dashboards: PDC trends by cohort,                 │
│   per-intervention completion + uplift,                    │
│   barrier-distribution by cohort,                          │
│   capacity utilization, equity-floor utilization]          │
│                                                            │
└──────────────────── FEEDBACK PATH ─────────────────────────┘
```

**Pharmacy data ingestion is the foundation.** Every other component depends on the adherence numbers being right. The ingestion job consumes claims feeds from the PBM (retail and mail-order in one stream, specialty in a separate stream because the data shape and lag profile differ), normalizes NDCs to therapeutic classes (using AHFS and the CMS PQA measure specifications for the Star Ratings classes), computes per-medication PDC with carry-forward days-supply, and emits both a "lag-aware stable" PDC (as of 30 days ago, when claims are settled) and a "best-effort current" PDC for real-time targeting. Per-patient features include each chronic medication's PDC, days since last fill, fill cadence, channel mix (retail vs mail-order), copay paid distribution, and regimen complexity (number of chronic medications, number of doses per day).

**Barrier classification runs on the same cadence as the recommendation run, or slightly ahead.** The output (ranked barriers per patient-medication with confidences) is consumed by the intervention scoring step. The classifier is staged: a rule-based pass for transparency and a deterministic baseline; a supervised classifier where labels exist; an optional LLM second opinion for high-stakes cases (high need score, high uplift potential, ambiguous barrier). The LLM second opinion's output is structured (predicted barrier, confidence, rationale) and flagged for human review when the suggested barrier conflicts materially with the rule-based prediction.

**Intervention catalog is small and human-curated.** The catalog is dozens of intervention records, not thousands. Each record has structured eligibility (some interventions are LIS-eligible only, some are brand-formulary-tier-only, some require the patient's pharmacy to be a partner), supported barriers (text reminders are a fit for forgetfulness; cost-assistance is a fit for cost barriers; pharmacist consults are general-purpose), capacity (daily slots per intervention, per-patient frequency caps), and marginal cost. Catalog updates are change-managed: a new intervention added requires clinical and contracting review, just like new wellness programs in 4.4.

**Batch recommendation runs frequently.** Adherence is a faster-moving target than wellness program enrollment. Weekly is the default for most programs; some plans run daily for the highest-priority Star Ratings cohorts. The batch run consumes the per-patient-medication adherence features, the barrier classification, and the intervention catalog, and produces a (patient, intervention, medication, priority, allocated) table that drives outreach and staff queuing.

**Outreach orchestration is multi-modal.** Patient-facing interventions (reminders, education, app push) flow through the channel optimizer from Recipe 4.1. Staff-facing interventions (pharmacist outreach, cost-assistance navigation, care-team escalation) flow into staff work queues with structured pre-work (the LLM-generated pre-call brief, the patient's adherence history, the suggested intervention rationale). Some interventions (med-sync enrollment) flow into pharmacy partner systems via the partner's API or through a flagged-for-action work queue if the partnership is manual.

**Feedback is multi-horizon, again.** Short-horizon engagement (text opened, call scheduled, copay-card application started) feeds the engagement-prediction model. Medium-horizon adherence change (PDC at 90 days post-intervention versus matched controls) feeds the uplift model and the per-intervention effectiveness estimates. Long-horizon clinical outcomes (HbA1c trajectory, blood pressure control, LDL trajectory, ED visits and hospitalizations for adherence-sensitive conditions) feed the program-level cost-effectiveness evaluation and inform whether each intervention type stays in the catalog. Star Ratings impact (movement of patients across the 80 percent PDC threshold) is tracked separately because it has business consequences distinct from clinical impact.

**Equity instrumentation is structural.** Every batch run produces cohort-sliced metrics: barrier-distribution by demographic cohort (a barrier classifier that disproportionately flags Spanish-speaking members as "forgetfulness" instead of "access" is a fairness problem; surface that), intervention allocation by cohort (capacity reserved for under-engaged cohorts), and PDC change by cohort. Persistent disparities surface as alarms on the cohort dashboard.

**Care-team integration is bidirectional.** PCP and pharmacist actions flow back into the system as structured events. A pharmacist who completes a consult and elicits a "side-effect concern" barrier writes that finding back to the engagement stream as a `barrier_elicited` event with the barrier and the source. That ground-truth label is gold for retraining the barrier classifier.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.05-architecture). The Python example is linked from there.

## The Honest Take

Medication adherence is one of those problems where the data is rich and the data is wrong in ways that take years to learn. The PDC numbers are easy to compute and easy to misuse. The barrier classification is the hard part, the part that distinguishes a good adherence program from a reminder spam campaign, and it's also the part that is most data-starved at launch. Most plans I've seen go straight from "we have PDC numbers" to "let's send reminders to everyone with PDC under 80," skip the barrier work, and spend the next two years discovering that reminders only address one of six barriers and the patients who needed something else either ignored the reminders, opted out of all communications, or wrote off the plan as "the people who keep texting me about a medication I can't afford."

The trap that's most specific to this domain is the Star Ratings cut-point distortion. If your plan is in a competitive Medicare Advantage market, the financial pressure to optimize for the 75 to 79 PDC cohort is enormous: a few percent movement of that cohort across the 80 percent line can be worth tens of millions of dollars in plan revenue, and the math is auditable. The math is also a moral hazard. The patient at PDC 35 percent has more clinical room to improve, and the population health benefit of moving them to PDC 65 is much larger than moving the 78-percent patient to 81 percent. The plan-revenue benefit is the opposite. Both can't win when capacity is finite. The recipe's policy weights make this explicit; teams should make the trade-off conscious, document it, and accept that "we are optimizing primarily for Star Ratings" is a defensible answer if it's said out loud and reviewed, while "we are not thinking about it and our model converged on the 75-79 band because that's where the engagement data was densest" is not.

The thing that surprises people coming from retail recommendation backgrounds is how much of adherence is about *staff capacity*, not patient targeting. A plan with 2 clinical pharmacists has a different optimal allocation than a plan with 20. A plan that contracts pharmacist outreach to a vendor at $40 per consult has different cost-effectiveness math than a plan with in-house pharmacists at allocated cost. The recommender's policy and capacity constraints must reflect actual operational reality. A model that perfectly predicts who would benefit from a pharmacist consult is useless if the pharmacist queue has been at capacity for three months. The best recommenders I've seen treat capacity as a first-class input that the operations team can adjust without a code deploy, and they show capacity utilization as prominently as they show targeting precision.

The thing I'd do differently the second time: invest in the pharmacist-elicited barrier dataset from day one, even before the recommender is targeting at scale. Pharmacist consults are the gold-label source for the supervised barrier classifier. If the consults aren't structured (open-ended notes, no consistent barrier capture), the labels are too noisy to train on, and the classifier never gets better than the rule-based baseline. A small upfront investment in a guided pharmacist-consult protocol with structured barrier capture pays back across the entire program lifecycle. The pharmacists are usually fine with this; their notes get more useful and their performance reviews get easier to defend.

The trap worth flagging: confusing "the patient took the pill" with "the patient is healthy." A statin program that drives PDC from 60 percent to 85 percent and produces no measurable change in LDL trajectory has either a sample size problem, a measurement problem, or (most likely) a "the model is recommending interventions to people whose baseline LDL was already controlled" problem. The cost-effectiveness math has to compare clinical outcome change, not just PDC change, against the cost of intervention. Intermediate metrics (PDC, fill counts, engagement rates) are the fast feedback you optimize against; clinical outcomes are the slow validation you use to check whether the optimization was pointing in the right direction. A program that hill-climbs against PDC for two years without ever validating against outcomes has built a beautiful optimization for a metric that may not be the metric.

Another trap: confusing intervention completion with intervention success. A pharmacist consult that completed (the pharmacist talked to the patient, the patient said "thanks") is not the same as a successful intervention (the patient subsequently changed their behavior and adherence improved). Some plans count completed consults as the success metric and report 95 percent success rates. The honest metric is: among completed consults, what fraction produced a measurable PDC change in the next 90 days versus a propensity-matched control. That number is usually 30 to 50 percent for high-quality programs, much lower for poor ones. Don't let the operational metric become the success metric.

One more piece of personal opinion. The adherence space has a long history of vendors with strong claims and weak methodology, and a long history of plans buying programs because the vendor's case study showed a 20 percent PDC improvement that turns out, on inspection, to compare a self-selected enrolled cohort against an unmatched control. The architecture in this recipe is built for plans that want honest evaluation. Whether the team commits to running the honest evaluation, with randomized hold-outs and propensity-matched controls and pre-registered methodology and clinical-outcomes verification, is a cultural choice. The technology supports it. The discipline is the rare resource.

Last point, because it's specific to this use case: medication non-adherence is often *rational* from the patient's perspective. A patient who can't afford the medication, or who is having side effects they haven't told anyone about, or who has lost trust in the prescriber, or who is exhausted and managing eight chronic conditions and has decided to triage which medications matter most: these patients are not failing. They are coping. The right response to non-adherence is rarely "remind harder." It's "find out what's going on, and address that." The recommender's job is to figure out what's going on as well as data permits, route the patient to the right intervention, and trust the human at the other end of the intervention to listen. The most expensive failure mode is treating non-adherence as a behavioral defect to be corrected rather than a signal to be understood. Build the system to listen; don't build it to nag.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the channel optimizer the orchestrator hands off to. The contact-frequency cap is shared infrastructure. The channel-preference learning extends naturally to adherence reminders.
- **Recipe 4.2 (Patient Education Content Matching):** The education intervention type in this recipe's catalog uses 4.2's content-matching pipeline to select the right educational material for the patient and medication.
- **Recipe 4.3 (Provider Directory Search Optimization):** Shares the fairness-instrumentation pattern (cohort-sliced metrics, equity floors).
- **Recipe 4.4 (Wellness Program Recommendations):** This recipe reuses 4.4's uplift-and-allocation pattern. The capacity-aware allocator is structurally the same; the multi-intervention-per-patient extension is new.
- **Recipe 4.6 (Care Gap Prioritization):** Adherence is one form of care gap; the prioritization patterns from 4.6 apply to selecting which adherence target to address first when a patient has multiple non-adherent medications.
- **Recipe 4.7 (Care Management Program Enrollment):** A patient with multiple non-adherent medications and high clinical risk is a candidate for care-management enrollment; this recipe and 4.7 share inputs and patients, and the cross-recipe orchestration matters.
- **Recipe 4.10 (Dynamic Treatment Regime Recommendation):** The sequential-intervention extension above is a small step toward 4.10; both share the multi-time-step decision pattern.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** The clinical-need model in this recipe is a risk-scoring problem; Chapter 7's risk-scoring patterns and validation methodology apply directly.
- **Recipe 8.x (NLP Non-LLM):** Pharmacist consult notes can be parsed by NLP techniques to extract structured barrier labels; the labels feed the supervised barrier classifier. Free-text-to-structured-label pipelines are a Chapter 8 problem.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** Member-facing assistants can call this recommender to answer "why am I getting reminders for X" or to capture a member-reported barrier directly through conversation.
- **Recipe 14.x (Optimization / Operations Research):** The heterogeneous-capacity allocator graduates to integer programming or column-generation when constraints multiply; Chapter 14 covers the formal techniques.

---

## Tags

`personalization` · `recommendation` · `medication-adherence` · `pdc` · `barrier-classification` · `uplift-modeling` · `causal-inference` · `heterogeneous-allocation` · `star-ratings` · `pharmacy` · `equity` · `cohort-analysis` · `bedrock` · `sagemaker` · `feature-store` · `dynamodb` · `step-functions` · `lambda` · `medium` · `production` · `hipaa`

---

*← [Recipe 4.4: Wellness Program Recommendations](chapter04.04-wellness-program-recommendations) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.6 - Care Gap Prioritization →](chapter04.06-care-gap-prioritization)*
