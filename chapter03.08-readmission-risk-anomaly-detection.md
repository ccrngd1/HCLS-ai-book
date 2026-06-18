# Recipe 3.8: Readmission Risk Anomaly Detection ⭐

**Complexity:** Complex · **Phase:** Production (with care management governance) · **Estimated Cost:** ~$0.0005 to $0.003 per patient-day monitored (mostly compute, feature joins, and RPM ingest; outreach staff time dwarfs infrastructure cost)

---

## The Problem

Mr. Alvarez is 71. He was admitted ten days ago with a heart failure exacerbation, ejection fraction 30%, two days in the step-down unit, six days on the cardiology floor, diuresed gently, optimized on guideline-directed medical therapy, taught how to weigh himself daily, given a pillbox with the new med list, scheduled for cardiology follow-up in seven days, and discharged home Thursday afternoon. The discharge summary is solid. The medication reconciliation is clean. The post-discharge plan looks good on paper.

Friday: he weighs himself. 198 lbs. Same as discharge. He logs it on the patient portal because the discharge nurse showed him how. He feels okay, takes his meds, eats some chicken and rice his daughter brought.

Saturday: 199. He notices his ankles are a little puffier than yesterday. He logs the weight, doesn't mention the swelling because nobody asked about ankles.

Sunday: 201. He's a little short of breath walking up the stairs. He sleeps on two pillows because lying flat feels weird. Doesn't call anybody because it's Sunday and he doesn't want to bother anyone.

Monday: 204. He's up most of the night propped on three pillows, wakes up wheezing. His daughter takes him to the emergency department in the morning. He gets readmitted with acute decompensated heart failure, IV diuretics, three more days in the hospital, another twelve thousand dollars of inpatient cost, and a meaningful hit to his quality of life and his trust in the system.

Look at the data trail. The weights were going up. From 198 to 199 to 201 to 204 in four days. That's three pounds in three days, which is the textbook trigger for "call your doctor" in heart failure self-management materials. He logged every weight on the patient portal. The portal stored them. Nobody acted on them. The cardiologist's office had thirty new patient messages that morning. The hospital's care management team was understaffed and prioritizing patients who'd just been discharged in the last 48 hours, not day-three or day-four post-discharge. The data was there. The signal was clear in retrospect. It just didn't reach a human who could act on it in time.

That's readmission risk anomaly detection. Not the well-studied "score this patient at discharge for likelihood of 30-day readmission" problem (though that matters too, and it's mostly Chapter 7 territory). The harder, more operational question is: of all the patients we discharged in the last 30 days, whose post-discharge trajectory right now is deviating from what successful recovery looks like, and where can a phone call, a home visit, or a same-day clinic slot keep them out of the ED?

The Hospital Readmissions Reduction Program (HRRP), which CMS started in 2012, made this expensive. Hospitals with higher-than-expected 30-day readmission rates for specific conditions (heart failure, AMI, pneumonia, COPD, CABG, total hip/knee arthroplasty) get their Medicare payments reduced.  The financial pressure put readmission reduction on the C-suite agenda, which means the project gets funded, which means there's a real market for tools that help. The clinical pressure is older and arguably more important: readmissions are bad for patients. They're expensive, they're disruptive, they're often preventable, and they signal that something about the discharge transition didn't work.

The reason this problem lands at the complex end of the chapter, despite years of academic work on readmission prediction, comes down to a few intertwined things.

**The signal is diffuse and slow.** Patient deterioration on an inpatient floor (Recipe 3.7) shows up in vitals and labs over hours. Post-discharge deterioration shows up in patient-reported weights, blood pressures, glucose readings, symptom check-ins, medication adherence, and missed appointments, often over days. Some of those signals are continuous (a Bluetooth scale that uploads daily). Some are intermittent (a patient who fills out a symptom survey twice a week). Some are absent for entirely benign reasons (the scale's battery died) and entirely concerning reasons (the patient is too short of breath to get on the scale). The pipeline has to handle missing-data ambiguity gracefully, because missing data is itself the most common signal.

**Baselines are deeply personal and the post-discharge baseline isn't the inpatient baseline.** A patient discharged at 198 lbs is at their target dry weight. A weight of 200 a week later is fine. A weight of 200 in a patient discharged at 175 is a four-alarm fire. Population thresholds are nearly useless; patient-specific baselines are essential. The baseline has to be established quickly (the first few post-discharge days are the highest-risk window) and adjusted as the patient stabilizes (their dry weight may drift over time as their heart failure regimen optimizes).

**Intervention capacity is the binding constraint.** Unlike inpatient deterioration where the rapid response team is on shift 24/7, post-discharge intervention requires care managers, transition-of-care nurses, pharmacists, social workers, and community health workers, almost always operating during business hours, almost always understaffed, and almost always managing a queue. A model that says "five hundred of your discharged patients are at elevated risk this week" is operationally useless unless it ranks them sharply enough that the care management team can work the top of the list and trust that the bottom is genuinely lower-priority. Precision at the top of the ranking matters more than overall AUROC.

**Causality and correlation are tangled.** A patient whose weight went up and got readmitted shows the model that weight gain predicts readmission. A patient whose weight went up, got a phone call, got a same-day diuretic adjustment, and didn't get readmitted shows the model that weight gain doesn't predict readmission. The intervention itself disrupts the prediction problem. This is the fundamental "treatment effect on prediction" issue, and naive supervised learning on observational data produces models that quietly absorb the historical intervention pattern. You end up predicting "patient who would have been readmitted in the absence of an intervention" using a model that was trained on a world where interventions happened.

**The outcome label is operationally messy.** "Readmission within 30 days" sounds clean. In practice: readmission to which hospital (your hospital, any hospital, any acute care facility)? Planned readmissions for staged procedures (CABG followed by valve replacement) that CMS excludes? Observation stays that aren't technically admissions but are clinically the same event? ED visits that almost-but-didn't-quite become admissions? Skilled nursing facility transfers that are technically discharges-to-SNF? Each definition produces a different label, and the choice shapes what your model learns. 

**Patient-reported data is messy, sparse, and biased.** A patient who's well enough to weigh themselves every morning is healthier in expectation than a patient who skips three days. A patient who's tech-savvy enough to use the patient portal differs from one who isn't. A patient with a supportive family member helping with logging differs from one who lives alone. Models trained on patient-reported data can encode digital-engagement bias in ways that map onto socioeconomic and demographic disparities. Subgroup performance audits are not optional.

**Workflow integration is, again, the actual product.** A risk score in a dashboard that nobody opens is worse than no score. The output has to flow into the care management team's daily worklist, the transition-of-care nurse's outreach queue, the pharmacist's medication-reconciliation review list, and (for the highest-risk patients) the cardiologist's same-day add-on list. Each of those integrations is its own project. The pipeline is half the system; the workflow is the other half. Sound familiar? It should. This is the same lesson as Recipe 3.7, applied to a different timescale.

**Equity is a first-order concern, not a side note.** Readmission rates differ across demographic and socioeconomic groups for reasons that are mostly not about clinical risk: housing stability, food security, transportation, social support, English-language proficiency, prior healthcare experiences. Models that predict readmission well in aggregate can perform meaningfully worse on subgroups, and the operational response (more outreach to predicted-higher-risk patients) can either reduce or amplify existing disparities depending on how it's deployed. The CMS HRRP program added Medicaid stratification in 2019 partly in response to evidence that the original methodology penalized safety-net hospitals serving more vulnerable populations. 

What you actually want to build is a continuously-running monitoring service that tracks every recently-discharged patient, ingests patient-reported outcomes and remote monitoring data alongside the EHR feed, computes a per-patient deviation-from-expected-recovery score on a daily (or more frequent) cadence, surfaces the patients whose trajectories are deviating most concerningly to the care management team in priority order with enough explanation to act on, and feeds the outcomes back so the model and the operational thresholds keep improving. Underneath sit a cold-start strategy for patients who just discharged, a missing-data-aware feature pipeline, a calibration and subgroup-monitoring framework, and a tight integration with whatever care management workflow tool the organization actually uses (Salesforce Health Cloud, Epic Healthy Planet, Cerner HealtheRegistries, custom-built worklists, or the spreadsheet a care manager built and refuses to give up).

Let's get into how.

---

## The Technology

### Why "Anomaly Detection" Instead of "Just Predict Readmission"

A first-time builder might reasonably ask: isn't this just a 30-day readmission prediction model? Why are we calling it anomaly detection?

The answer is that this chapter is about *operational, ongoing* anomaly detection, not *one-shot* discharge-time risk scoring. Both exist, both are useful, and they answer different questions.

**Discharge-time readmission risk scoring** asks: at the moment of discharge, given everything we know about this patient, what's their probability of readmission in the next 30 days? The output goes into discharge planning: which patients get the standard transition of care, which get the enhanced bundle (home health, transitions clinic, pharmacist follow-up), which get the high-touch program (daily outreach, RPM enrollment, expedited specialist follow-up). The classic published models in this space (LACE, LACE+, HOSPITAL, the Epic readmission risk model, various commercial models) live here. This is mostly a Chapter 7 problem; we'll cover it there.

**Post-discharge anomaly detection** asks: of all the patients we discharged in the last 30 days, whose trajectory right now is deviating from what their expected recovery should look like? This is what you need when the day-three weight is up, when the patient stopped checking in, when the new medication regimen produced a side effect that's not yet a readmission but is heading there. The output goes into the care management team's daily worklist. This is what Recipe 3.8 covers.

The two are complementary. Discharge-time scoring sets up the monitoring intensity (high-risk patients get RPM, daily outreach, and tight feedback loops; lower-risk patients get the standard touchpoints). Post-discharge anomaly detection consumes the monitoring data and surfaces the patients whose actual trajectories are diverging from the expected ones. A well-designed program does both. A program that only does discharge-time scoring tells you who to worry about at the moment of discharge and then loses the thread; a program that only does post-discharge anomaly detection has nothing to do with patients who don't generate post-discharge data at all.

The framing as "anomaly detection" is deliberate because the question is fundamentally *deviation from expected*, not *absolute level of risk*. A patient discharged at 198 lbs whose weight is 200 on day three is normal. The same patient at 204 on day three is anomalous. The signal isn't the weight. It's the deviation from the expected weight trajectory for this patient given their condition, their discharge status, and their personal baseline.

### The Operational Anatomy of a Post-Discharge Episode

Before getting into models, a builder should know the rough shape of what happens after a patient is discharged from a typical inpatient stay, because the data sources and intervention windows shape everything that follows.

**Day 0: Discharge.** The patient leaves the hospital with a discharge summary, a medication list, follow-up appointments, education materials, and (if they're enrolled in a transitions program) an introduction to the care management team. Pharmacy reconciliation should have happened. The patient may or may not understand any of it; teach-back is the right tool, often skipped.

**Day 1-3: The highest-risk window.** Most preventable readmissions trace back to issues that were detectable in the first 72 hours: medication errors (the patient took the old list plus the new list, didn't pick up the prescription, can't afford the new medication), symptom changes that warranted a check-in, missed first follow-up, transportation issues, post-op complications (wound infection, post-op pain), social issues (no caregiver at home, food insecurity).

**Day 4-7: The integration window.** The patient settles into the new routine, picks up prescriptions, attends the first follow-up appointment, and either stabilizes or doesn't. RPM data, if it's flowing, starts producing useful trajectory information. The first symptom check-in (usually on day 3-5) provides patient-reported information.

**Day 8-21: The drift window.** Patients who were doing fine can deteriorate slowly. Heart failure patients can creep into volume overload over a couple of weeks. COPD patients can develop a brewing exacerbation. Post-surgical patients can develop late wound complications. This window is the one where existing programs do less well, because the highest-touch outreach is concentrated in the first week.

**Day 22-30: The end-of-window risk.** Some readmissions cluster late in the 30-day window. These are often related to medication non-adherence, gradual decompensation, or social issues that took weeks to surface.

**Day 30+: The post-window observation.** The 30-day cutoff is a CMS construct. From a clinical perspective, readmissions on day 31, 35, 60 still represent transition-of-care failures. Some hospital programs track 60- and 90-day windows for internal quality metrics even though CMS only penalizes the 30-day metric. 

The pipeline has to produce useful output at every point in this timeline, not just at the moment of discharge. That's the operational requirement that makes this a streaming problem, not a batch one.

### Data Sources That Actually Drive Signal

The signal-to-noise ratio depends entirely on what data you can pull and at what cadence. Some categories matter a lot more than the literature on discharge-time scoring suggests.

**Patient-reported outcomes (PROs).** Symptom check-ins, pain scores, energy/wellbeing assessments, medication adherence self-reports. Usually delivered through a patient-facing app, an SMS-based check-in, or an IVR phone call. Cadence varies by program (daily for high-risk patients, weekly for moderate-risk). When the patient stops responding, that's also a signal.

**Remote patient monitoring (RPM) device data.** Bluetooth-enabled scales, blood pressure cuffs, pulse oximeters, glucose monitors, peak flow meters. The device transmits to a vendor cloud (BodyTrace, A&D Medical, iHealth, Withings, Roche, Abbott, several others), which transmits to your aggregation platform. Cadence is per-measurement; a daily-weight cohort produces a measurement per day per patient.

**Continuous glucose monitor (CGM) data.** A specific sub-category of RPM that produces high-cadence data (5-15 minute readings). Mostly relevant for diabetes-focused readmission prevention.

**Wearable data.** Apple Watch, Fitbit, Garmin, Oura, etc. Heart rate, activity counts, sleep patterns, blood oxygen (when available), atrial fibrillation detection (Apple Watch). Lower data quality and harder integration than dedicated medical devices, but increasingly common because patients already wear them.

**EHR feeds.** ED visits at your facility, lab orders that came through, medication refill history (when integrated with the pharmacy), care team messages, post-discharge clinic visits. These are the most accurate signals when they happen, but they're often delayed (a refill might happen days before it's reflected in your data) and incomplete (a patient who fills a prescription at a community pharmacy not connected to your network is invisible).

**Health Information Exchange (HIE) data.** ED visits and admissions at other facilities. Critical for "did this patient get readmitted somewhere else" questions and for early-warning when your patient is at another ED right now. HIE coverage varies enormously by region; some states have robust HIEs, others have nothing usable. 

**Claims feed.** When the hospital is part of an ACO or risk-sharing arrangement, near-real-time claims data flows through (ACO REACH, MSSP, commercial value-based contracts). This is the highest-quality "did this patient get care anywhere" signal but lags by days to weeks depending on the payer.

**Pharmacy data.** Prescription fills, especially of new medications. Surescripts, RxHistory, pharmacy benefit manager feeds. A patient who didn't fill their new heart failure medication on day three is a high-priority case.

**Social determinants of health (SDOH) data.** Housing stability, food security, transportation barriers, social support, language preferences. Captured through screening tools (PRAPARE, AHC HRSN, Z-codes), through community resource referrals, or inferred from address-level data (food deserts, transit access). Often the most predictive features that nobody is measuring.

**Care management notes.** When the care manager has spoken to the patient, what came up. Free-text, often in a different system than the EHR (Salesforce Health Cloud, custom CMS tools, Epic Healthy Planet). Substantial signal locked in unstructured text; NLP feature extraction can surface it.

**Caregiver-reported data.** Especially for elderly patients with cognitive impairment. The caregiver is the actual reporter of weights, symptoms, and concerns. The caregiver's responsiveness and accuracy is its own variable.

A useful program doesn't need all of these. It does need to be honest about which it has, which it can act on, and which it's not getting and therefore not modeling. Some of the highest-value data (SDOH, caregiver-reported) is the hardest to operationalize.

### Statistical and ML Methods That Fit

Post-discharge anomaly detection has a different methodological palette than discharge-time risk scoring because the data structure is fundamentally different: you're looking at ongoing time-series with sparse, irregular observations across multiple modalities, rather than a single feature vector at a single point in time.

**Patient-specific control charts.** The simplest and often surprisingly effective approach. For each tracked metric (weight, blood pressure, symptom score), compute the patient's baseline (mean, median, or trimmed mean of the first several days post-discharge), set control limits (often a hybrid of population-derived limits and patient-specific variability), and flag deviations that exceed the limits. Variants include CUSUM (cumulative sum) for catching gradual drift, EWMA (exponentially weighted moving average) for smoothing noisy series, and Shewhart charts for point anomalies. These are the techniques that the heart failure self-management literature operationalizes as "weigh yourself daily, call if up 3 lbs in 3 days." Easy to explain, easy to deploy, easy to audit. Hard to make sensitive enough on multi-modal data.

**Forecasting plus residual analysis.** Build a per-patient forecast of the expected trajectory (a smooth recovery curve, a flat steady state, or whatever the recovery pattern for that condition looks like) and flag observations whose residual from the forecast exceeds a threshold. ARIMA, exponential smoothing, state-space models, or simple linear regression with patient-specific slopes. Works well when the recovery trajectory has predictable shape; struggles when there's no signal in the early data and the patient just discharged.

**Multivariate change-point detection.** PELT, Bayesian online change-point detection, and related methods identify points in a time series where the underlying distribution shifts. Useful for detecting "the patient was on a stable trajectory, and then something changed." Requires enough pre-change data to establish the baseline, which is hard for newly-discharged patients.

**Recurrent neural networks (LSTM, GRU) on multi-modal time series.** Train on patient sequences with multiple modalities (vitals, symptoms, medication adherence) and predict the probability of readmission in the next N days. The model implicitly learns the trajectory shape and the deviations that matter. Strong performance when training data is abundant; data-hungry, less interpretable, and sensitive to data quality issues. Used in academic research more than production deployments as of 2026. 

**Transformer-based clinical time series models.** Foundation models for clinical data (BEHRT, Med-BERT, the various clinical time-series transformers) are starting to show strong results on readmission and post-discharge tasks. Production deployment is still rare. Worth experimenting with on retrospective data; probably not the right choice for a first production deployment.

**Survival analysis.** Frame the problem as time-to-event (readmission). Cox proportional hazards models, accelerated failure time models, deep survival networks (DeepSurv, DeepHit). The output is a hazard function or a survival curve, which conveys information about both whether and when readmission is likely. Aligns better with operational use than binary classification (the 60% likelihood of readmission tomorrow drives different action than 60% likelihood of readmission in three weeks).

**Gradient-boosted trees on engineered time-window features.** The workhorse approach. Compute features over rolling windows (last 3 days, last 7 days, last 14 days), feed them into XGBoost or LightGBM, score every patient daily. SHAP values produce per-prediction explanations. Most production-grade post-discharge programs are some flavor of this; the sophistication is in the feature engineering, not the model.

**Hybrid scoring.** A practical pattern: combine a discharge-time risk score (the patient's intrinsic risk at the moment of discharge), a per-modality control-chart deviation score (weight is up, BP is unstable), and an engagement score (the patient stopped checking in). The composite ranks the worklist; the per-component scores drive the explanation. Easy to deploy, easy to explain, easy to tune.

**Causal-inference-aware models.** A growing body of work tries to handle the treatment-effect-on-prediction problem by modeling the intervention explicitly: counterfactual estimators, target-trial-emulation, instrumental variables, propensity-matched controls. These are research-grade as of 2026; most production deployments accept the bias and validate prospectively.

A reasonable progression: start with patient-specific control charts on the high-signal modalities (weight for heart failure, blood pressure for hypertension, glucose for diabetes), augmented by an engagement-decay flag (the patient stopped checking in) and the discharge-time risk score as a tier modifier. Validate that the worklist generated by this simple system matches care management judgment about which patients to call. Add a gradient-boosted model on top once you have outcome labels from the simple system. Add LSTM or transformer layers only if the marginal gain justifies the operational complexity.

### Outcome Definition Is, Again, Surprisingly Hard

The same lesson from Recipe 3.7 applies: the choice of outcome shapes what your model learns, and "30-day readmission" is not a single label.

**All-cause readmission within 30 days, all-facilities.** The HRRP-relevant definition. Requires HIE or claims data to capture readmissions to other facilities. Without that, you're modeling "readmission to our hospital," which biases toward patients who would have come back here anyway.

**Condition-specific readmission within 30 days.** A heart failure patient readmitted with heart failure vs. readmitted with anything. CMS uses condition-specific definitions for the HRRP penalty calculation. 

**ED visits without admission.** Often clinically equivalent to readmission (same trip, the difference was whether the ED admitted) but doesn't trigger HRRP penalties. Some programs include ED visits in their internal outcome metric for clinical relevance, even if they're excluded from the formal HRRP calculation.

**Observation stays.** A patient kept in observation for 23 hours and discharged is technically not a readmission. Clinically often equivalent. Definitions vary.

**Intermediate clinical events.** New diuretic dose, new oxygen prescription, new clinic visit, all-system message volume changes. These are pre-readmission events that the model can predict, and that the care management team can act on. Some programs use these as proxies for readmission risk in a tighter feedback loop. They're not the formal outcome but they're operationally useful.

**Mortality.** Some patients die at home in the post-discharge window, or get re-admitted and die. Mortality is a competing risk for readmission and the analysis has to handle that. Survival analysis with competing risks (Fine-Gray, multi-state models) is the technically clean approach; many production models simply censor at death and accept the mild bias.

The teams that ship working post-discharge programs typically use a composite outcome: 30-day all-cause readmission OR ED visit OR death OR observation stay, with secondary analyses on the condition-specific HRRP-relevant subset. Pick something defensible, validate it, deploy it, refine.

### Features That Actually Matter

The features cluster into several categories that map onto the data sources.

**Discharge-time features (snapshot).** Age, sex, primary diagnosis, comorbidities, prior admissions, length of stay, ICU stay during admission, discharge disposition (home, home with services, SNF), polypharmacy count, new medications added during admission, discharge medications including high-risk classes (anticoagulants, insulin, opioids), social work flags, language, insurance type, distance from home to hospital, payor.

**RPM trajectory features (per modality).** Latest value, trend over last 3/7/14 days, deviation from patient-specific baseline (which is established in the first several days), variability, missing-data indicator (when was the last reading), engagement decay (number of days with at least one reading, recent vs. baseline).

**PRO-derived features.** Latest symptom score, symptom score trend, response rate to check-ins, free-text concerns extracted via NLP, medication adherence self-report, caregiver concerns documented.

**EHR-derived features.** ED visits since discharge, post-discharge clinic visits attended vs. scheduled, medication refills (filled, not filled, partial fill), new orders, new lab results in the post-discharge window.

**Care management interaction features.** Number of outreach attempts since discharge, successful contact rate, escalations made, interventions delivered (medication titration, same-day appointment scheduling, home health activation, transportation arranged).

**Social and behavioral features.** SDOH screening results, caregiver presence, language, transportation flags, food security flags, housing stability flags. Where SDOH data is unavailable, area-level proxies (Area Deprivation Index, Census-tract-level features) are sometimes used as approximations, though they're noisy and contain their own equity considerations.

**Time-since-discharge features.** Day in the post-discharge window. Patient-specific timeline relative to scheduled follow-up appointments. Whether the patient has reached the day-3, day-7, day-14 milestones.

**Engagement features.** Patient portal log-in frequency, message read receipts, check-in completion rate. Engagement decay is one of the strongest signals; a previously-engaged patient who suddenly stops checking in often warrants outreach.

**Patient-specific baselines and deviations.** For every numeric metric, the patient's own baseline and the current deviation. The single most important feature class for separating "this number is normal for them" from "this number is concerning."

A useful model has 50-200 features, similar to Recipe 3.7. The complexity budget needs to leave headroom for ongoing tuning and feature retirement; not every feature pays for itself in maintenance cost.

### Cold-Start Is the Default State

Patients enter the monitoring program at discharge. They have zero post-discharge data points. The model has to produce a useful score from day zero, when the only available features are discharge-time features and population priors. This is the classic cold-start problem, and it's the default state for at least the first several days.

Common approaches:

- **Tier-based monitoring.** Discharge-time risk score sets the initial tier; the tier defines monitoring intensity and outreach cadence. The post-discharge anomaly detection layer activates as data flows in.
- **Cohort-based priors.** For patients in the same condition cohort, the expected trajectory in the first few days has known shape; deviations from the cohort-typical trajectory can be flagged even with only a couple of data points.
- **Engagement-first triage.** A patient who hasn't logged a single weight by day 3 is escalated to the care management team for outreach, regardless of any other signal. The absence of data is treated as a signal.
- **Hybrid scoring with backoff.** When patient-specific baseline data is insufficient, fall back to population baselines with appropriate uncertainty inflation. As the patient generates more data, smoothly transition to patient-specific baselines.

### Calibration, Subgroup Performance, and the Equity Question

The same operational rules from Recipe 3.7 apply, with an additional twist: post-discharge programs operate in a setting where intervention capacity is the binding constraint, and the question of "who gets the limited intervention capacity" is fundamentally an equity question.

**Calibration.** A score of 0.4 should mean "40% chance of readmission in the prediction window." Operational thresholds for outreach intensity depend on calibration. Recalibrate per subgroup if subgroup-stratified calibration differs.

**Subgroup performance audits.** Age band, sex, race and ethnicity (where structurally captured), insurance status, language, neighborhood SES, primary diagnosis, discharge disposition. Track AUROC, PRAUC, calibration ECE, alert rate, intervention rate, and (when measurable) the change in readmission rate per subgroup attributable to the program.

**Equity-aware deployment.** A program that surfaces predicted-higher-risk patients for more intervention can either reduce disparities (by directing resources to underserved patients) or amplify them (by directing resources to patients who are easier to engage). The deployment design matters as much as the model design. Some programs explicitly weight intervention prioritization by social vulnerability indices to counter bias in the underlying data; others use subgroup-stratified thresholds; others use post-hoc fairness-aware allocation. Pick one approach deliberately and document the rationale.

### Workflow Integration Is, Again, the Actual Product

Same lesson, different chapter. The score is one component. The worklist UI, the outreach call scripts, the escalation pathways, and the documentation back into the EHR are the other components. A program that gets the workflow right with a mediocre model outperforms a program that gets the model right with a mediocre workflow. The teams that ship working systems do both.

The specific workflows that matter:

- **Daily care management worklist.** Sorted by composite score, with the explanation visible inline. Filtering by team, by condition, by recent contact status. Click-through to the patient's RPM trends, recent encounters, and discharge plan.
- **Outreach scripts and decision support.** When the care manager calls, what should they ask? What interventions are they empowered to deliver (medication titration via standing orders, same-day appointment slots, home health activation)?
- **Escalation pathways.** When the call surfaces a clinical concern that exceeds the care manager's scope, who do they escalate to? On-call provider, transitions clinic, ED if urgent? The pathway needs to exist in writing and be tested in practice.
- **Documentation back into the EHR.** The intervention delivered, the patient's response, the clinical assessment, the next-step plan. Without round-trip documentation, the model loses the labels it needs to learn from.
- **Closed-loop with discharge planning.** Patterns of post-discharge anomaly that persist across multiple patients should feed back into discharge planning: which patient education materials are insufficient, which medication-reconciliation gaps recur, which transitions consistently produce problems.

---

## General Architecture Pattern

At a conceptual level, the post-discharge anomaly detection pipeline ingests RPM device data, patient-reported outcomes, EHR events, and care management interactions for every recently-discharged patient, computes per-patient features (current values, trajectories, deviations from expected), scores every patient on a daily (or more frequent) cadence, ranks the resulting risk-stratified worklist, and delivers it to the care management team with explanations and suggested next actions. Underneath sit the discharge-time risk scoring layer (which sets the monitoring tier), the cold-start cohort priors, the calibration and subgroup-monitoring infrastructure, the outcome capture loop, and the audit logging required for clinical safety review.

```text
┌────────── POST-DISCHARGE ANOMALY DETECTION PIPELINE ─────────────┐
│                                                                  │
│   [Discharge event       [RPM device feeds:    [Patient-         │
│    + risk score]          weight, BP, SpO2,     reported          │
│                           glucose, peak flow]   outcomes]         │
│   [EHR feed: ED visits,  [HIE / claims:        [Pharmacy         │
│    clinic visits, orders]  external admissions]  refill data]    │
│   [Care management       [Caregiver-reported   [Engagement       │
│    interaction logs]      data]                  signals]         │
│                                                                  │
│           │                                                      │
│           ▼                                                      │
│   [Streaming Ingest and Normalization]                           │
│   (canonical patient event format, unit conversions,             │
│    timestamp reconciliation, deduplication)                      │
│           │                                                      │
│           ▼                                                      │
│   [Post-Discharge Patient State Store]                           │
│   (current snapshot of every patient in the post-discharge       │
│    window; enrollment status; condition cohort; tier)            │
│           │                                                      │
│           ▼                                                      │
│   [Trajectory History Store]                                     │
│   (time-series of weights, BPs, glucoses, symptoms, etc.;        │
│    multi-week retention for baseline computation)                │
│           │                                                      │
│           ▼                                                      │
│   [Feature Engine]                                               │
│   (current values, trajectory features, patient-specific         │
│    baselines, deviation scores, engagement features,             │
│    cohort priors for cold-start)                                 │
│           │                                                      │
│           ▼                                                      │
│   [Scoring Service]                                              │
│   (anomaly score per modality + composite score; calibration     │
│    layer; subgroup-stratified thresholds)                        │
│           │                                                      │
│           ▼                                                      │
│   [Worklist Builder]                                             │
│   (rank patients by composite score; apply suppression and       │
│    de-duplication; attach explanations and suggested actions)    │
│           │                                                      │
│           ▼                                                      │
│   [Care Management Workflow Tools]                               │
│   (daily worklist UI; outreach call queue; pharmacist review     │
│    list; provider escalation list; transitions-clinic queue)     │
│           │                                                      │
│           ▼                                                      │
│   [Intervention Capture]                                         │
│   (outreach attempted, contact succeeded, intervention           │
│    delivered, patient response, escalations made)                │
│           │                                                      │
│           ▼                                                      │
│   [Outcome Capture]                                              │
│   (readmission events, ED visits, post-discharge mortality,      │
│    program graduation; linked to upstream alerts)                │
│           │                                                      │
│           ▼                                                      │
│   [Monitoring + Governance]                                      │
│   (subgroup performance, calibration drift, alert volume vs.     │
│    capacity, intervention success rates, equity audits)          │
│           │                                                      │
│           ▼                                                      │
│   [Periodic Retraining + Threshold Review]                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Ingest and normalization.** RPM data flows from device-vendor APIs (BodyTrace, A&D Medical, iHealth, Withings, etc.) usually via webhook or pull. PRO data flows from the patient-facing app or SMS/IVR vendor. EHR events flow from the EHR integration platform (HL7, FHIR). Care management interactions flow from the care management tool. The normalizer produces a canonical patient event with a small number of event types (measurement, symptom report, ED visit, refill, outreach, escalation, etc.).

**Post-discharge patient state store.** Every patient currently in the post-discharge monitoring program has a state record: enrollment date, condition cohort, discharge-time tier, current monitoring tier, last contact date, intervention history, and pointers to the trajectory history. The state store is the substrate the worklist UI reads.

**Trajectory history store.** Time-series of weights, blood pressures, glucoses, symptom scores, and the like. Retention covers multiple weeks for baseline computation. Per-patient indices for fast retrieval.

**Feature engine.** Computes per-modality features (current value, last 3-day slope, last 7-day slope, deviation from baseline, missing-data indicator) and patient-level features (engagement decay, time since last contact, days post-discharge, condition cohort, discharge-time tier). For cold-start patients, feature values fall back to cohort priors.

**Scoring service.** Hosts the per-modality anomaly detectors (control charts, residual-based detectors) and the composite scoring model (gradient-boosted trees on the engineered features). Produces calibrated scores and per-feature SHAP contributions for the explanation layer.

**Worklist builder.** Ranks patients by composite score, applies suppression rules (recently-contacted patients are de-prioritized; patients who are already in active intervention are tracked separately), de-duplicates across overlapping cohorts, and attaches the explanation and suggested next action to each row.

**Care management workflow tools.** The product. The actual UI the care managers, transitions nurses, pharmacists, and providers interact with. Often a separate vendor system (Salesforce Health Cloud, Epic Healthy Planet, Innovaccer, Lumeris, custom-built) consuming the worklist data via API.

**Intervention capture.** Every outreach attempt, every contact, every intervention is recorded with timestamps. The capture data flows back to the scoring service for tier adjustment (a patient who just got a same-day visit is lower priority for the next 24 hours) and to the retraining pipeline as features.

**Outcome capture.** Readmissions, ED visits, deaths, and program graduations are captured from the EHR feed, the HIE, and (for ACO/risk-bearing arrangements) the claims feed. Outcomes are linked to alerts and interventions for label assembly.

**Monitoring and governance.** Subgroup performance dashboards, alert volume by team and tier, intervention success rates (call connected, intervention delivered, downstream outcome avoided), equity audits across demographic groups. The governance committee reviews these dashboards on a defined cadence (often monthly for clinical leadership, quarterly for executive review).

**Retraining and threshold review.** Quarterly is typical. Use accumulated outcome labels. Compare candidate models against current production. Subgroup performance check. Calibration check. Shadow deployment for a defined period before promotion. Threshold review independent of retraining: alert volume targets shift as care management capacity shifts.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.08-architecture). The Python example is linked from there.

## The Honest Take

The model is the small part. Same lesson as Recipe 3.7, said again because it's the lesson that bites every team. In post-discharge programs, the workflow piece is even more important, because the intervention capacity is more constrained and the intervention specifics matter more than they do for inpatient deterioration. A great model with a 25-patient daily worklist that nobody works has zero value. A simple control-chart system with a small worklist that the care management team works religiously, and that has good intervention protocols and tight feedback loops, has substantial value. Build the workflow first. Build the model into it second. (The Basic tier in the [Architecture companion's](chapter03.08-architecture) Estimated Implementation Time table reflects exactly this discipline: a control-chart-only deployment with full workflow and governance in 4-8 months, before the gradient-boosted composite model enters the picture.)

Patient-reported data is gold and most programs underuse it. The thing that surprised me the first time I worked on a post-discharge program: patient symptom check-ins, when designed well and delivered through a low-friction channel, are often the highest-signal feature in the model. Higher than the RPM device data. Higher than the EHR features. Patients know how they're feeling. They'll tell you if you ask. The trick is making the asking low-friction (SMS or IVR check-ins of 3-5 questions, not 20-question portal surveys) and timing the asks well (day 3, day 7, day 14, day 21 covers most of the window). The data quality is variable, but the signal is real, and it scales in a way RPM doesn't (no devices to ship, no batteries to fail, no Bluetooth pairing issues).

Engagement decay is one of the strongest signals. A patient who was engaged and stops engaging is doing one of three things: getting better and not bothering anymore (about half of them); getting worse and not feeling up to engagement (some meaningful fraction); or has a logistical problem (battery, phone broken, traveling). The model can't distinguish these, but the care manager can with a phone call. "We noticed you stopped checking in; everything okay?" is a script that converts disengagement into a conversation, and the conversation surfaces whichever of the three is happening. Build engagement decay into the model and into the worklist as its own first-class feature.

Cold-start is the default state and you can't shortcut it. Every newly-discharged patient is a cold-start patient. The first few days of monitoring rely on discharge-time features and cohort priors. There's no clever feature engineering that makes this go away; the patient simply doesn't have post-discharge data yet. The right response is uniform high-touch outreach in the first 72 hours regardless of model output, with the model output kicking in for the day 4+ stratification. Programs that try to use the model to ration day-1 outreach are operating in a regime where the model doesn't have the inputs to be reliable, and the false-negative cost is large.

Equity is a deployment design problem, not a model problem. Subgroup performance monitoring catches model-level disparities. The bigger and harder issue is the upstream availability of data: digital engagement varies across populations, RPM device adoption varies, English-language proficiency affects the patient-facing communication channels, social support affects whether the family can help with logging. Models trained on the data-rich subset don't generalize to the data-poor subset, and the data-poor subset often has the highest clinical risk. The deployment design has to acknowledge this. Some programs explicitly weight outreach toward higher-vulnerability populations regardless of model output; some run parallel non-digital monitoring tracks (community health workers, in-home check-ins) for populations that don't use digital channels well; some provide devices and language-appropriate engagement materials proactively. The right answer depends on the population. The wrong answer is to ignore it and hope the model handles it.

Causal inference is the biggest research-to-production gap. The published literature on post-discharge interventions has the same problem: most evidence comes from observational studies where intervention assignment correlated with risk. The cleanest evidence for program effectiveness comes from randomized trials, which are rare. If your program supports it, run a randomized rollout: half the eligible patients get the program, half get usual care. The result is defensible evidence for executive review and protects the program from "we don't know if it's working" challenges in the next budget cycle. If randomization isn't feasible, target-trial-emulation with propensity matching is the next best thing.

The biggest mistake I see: optimizing for the wrong metric. AUROC is the model team's metric. Top-decile capture is the operations team's metric. Successful contact rate is the workflow metric. Intervention rate is the program metric. Reduced 30-day readmission rate (vs. matched controls) is the outcome metric. Cost per readmission avoided is the financial metric. Cost per quality-adjusted life-year is the value-based-care metric. If you can't tell me what your program looks like across all seven, you have a science project, not a program. The transition from science project to program is the hardest single transition in this work, and it's exactly the same lesson as Recipe 3.7 because the underlying structure is the same.

The political reality: post-discharge programs compete with other quality initiatives for funding. The CFO's question is "what's the ROI?" The ROI math: average cost of a 30-day readmission is in the $10,000-20,000 range depending on payer mix. A program that prevents one to two readmissions per care manager per month covers the care manager's loaded cost. The financial story works for hospitals at risk under HRRP penalties or in value-based-care arrangements. It works less well for fee-for-service hospitals where readmissions are revenue. The latter case is harder; the program has to compete on quality metrics and patient experience rather than direct ROI. Be honest about which case you're in.

The thing nobody talks about: program graduation criteria. When does a patient stop being in the post-discharge monitoring program? At 30 days because that's the HRRP window? At 60 or 90 days because clinical risk persists? When the patient meets specific stability criteria (stable weight, stable symptoms, stable engagement)? When the patient explicitly opts out? When their devices stop reporting for some defined period? Each program makes a choice. Programs without explicit graduation criteria end up monitoring patients indefinitely, which dilutes care manager capacity and produces alert fatigue. Programs with graduation criteria need to handle the off-ramp: hand-off back to primary care, education materials about ongoing self-monitoring, clear messaging about when to call.

Closed-loop is not the right answer for most programs. Standing orders for medication titration, automated diuretic adjustments triggered by weight trends, automated home health activations: these can work in narrow scenarios with strong governance, but they raise the regulatory bar substantially (FDA SaMD considerations, scope-of-practice issues for the standing-order delegation, patient consent considerations). Most programs stop short of full closed-loop and keep the human in the loop for the actual care decision. The pipeline surfaces; the care manager decides. Closed-loop is an extension worth designing for in narrow scenarios after the human-in-the-loop program is mature, not a starting point.

The thing I'd do differently: I'd start narrower than I usually have. A heart failure transitions program with a single cohort, a single device program (Bluetooth scale), a single PRO check-in cadence, and a defined intervention protocol scales better and produces clearer evidence than a multi-cohort everything-at-once program. Pilot, validate, scale. The hospitals that try to launch a post-discharge program for everyone simultaneously usually end up with a program that's mediocre for everyone; the hospitals that pilot with heart failure, prove it works, and then add COPD and post-op cardiac in sequence end up with multiple programs that each work well.

Lives are saved here too, just less dramatically than in Recipe 3.7. The signal is slower and the impact is harder to attribute, but the published evidence on transitions-of-care interventions is genuine. The Coleman Care Transitions Intervention, Naylor's Transitional Care Model, the Project RED protocol, and various integrated RPM programs have all shown reductions in 30-day readmission rates in randomized or quasi-experimental studies.  The work is hard, but it's worth doing. Just go in with eyes open about what "doing it" actually requires: the workflow, the staffing, the governance, the equity considerations, and the ongoing operational discipline.

---

## Related Recipes

- **Recipe 3.5 (Lab Result Outlier Detection):** Patient-specific baseline establishment for labs is a closely related problem; the techniques for identifying patient-specific normal ranges transfer.
- **Recipe 3.7 (Patient Deterioration Early Warning):** Inpatient deterioration is the same fundamental problem on a different timescale, with different sensors and different intervention windows. Many architectural patterns transfer.
- **Recipe 3.9 (Cybersecurity / Access Pattern Anomalies):** Behavioral baseline establishment and engagement-decay detection share statistical foundations.
- **Recipe 4.x (Personalization / Recommendation):** Outreach channel optimization, message timing, and content personalization for patient-facing communication overlap with personalization patterns in Chapter 4.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** The discharge-time readmission risk score that feeds this recipe is a Chapter 7 problem. The composite scoring layer in this recipe is also predictive analytics, and many of the validation patterns transfer.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Trajectory forecasting and residual-based anomaly detection are core time-series patterns covered in Chapter 12.
- **Recipe 2.x (LLM / Generative AI):** Outreach script generation, narrative explanations, and case summaries use patterns from Chapter 2.
- **Recipe 8.x (NLP / Traditional):** Care management note extraction uses NLP patterns from Chapter 8.
- **Recipe 11.x (Conversational AI):** Patient-facing conversational check-ins use patterns from Chapter 11.

---

## Tags

`anomaly-detection` · `readmission-risk` · `post-discharge-monitoring` · `transitions-of-care` · `remote-patient-monitoring` · `rpm` · `patient-reported-outcomes` · `pro` · `heart-failure` · `copd` · `hrrp` · `cms-readmission-program` · `lace` · `hospital-score` · `time-series` · `xgboost` · `lightgbm` · `survival-analysis` · `feature-store` · `clarify` · `model-monitor` · `model-registry` · `bedrock` · `comprehend-medical` · `kinesis` · `timestream` · `dynamodb` · `opensearch` · `eventbridge` · `sagemaker` · `appsync` · `step-functions` · `care-management` · `local-validation` · `subgroup-performance` · `equity` · `sdoh` · `calibration` · `shap` · `engagement-decay` · `cold-start` · `causal-inference` · `fda-cds` · `samd` · `hipaa` · `complex` · `production` · `provider`

---

*← [Recipe 3.7: Patient Deterioration Early Warning](chapter03.07-patient-deterioration-early-warning) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.9 - Cybersecurity / Access Pattern Anomalies →](chapter03.09-cybersecurity-access-pattern-anomalies)*
