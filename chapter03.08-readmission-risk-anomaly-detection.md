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

The Hospital Readmissions Reduction Program (HRRP), which CMS started in 2012, made this expensive. Hospitals with higher-than-expected 30-day readmission rates for specific conditions (heart failure, AMI, pneumonia, COPD, CABG, total hip/knee arthroplasty) get their Medicare payments reduced. <!-- TODO (TechWriter): verify the current HRRP penalty cap and the specific conditions in scope; CMS updates the program annually and the conditions and methodology have evolved since 2012. --> The financial pressure put readmission reduction on the C-suite agenda, which means the project gets funded, which means there's a real market for tools that help. The clinical pressure is older and arguably more important: readmissions are bad for patients. They're expensive, they're disruptive, they're often preventable, and they signal that something about the discharge transition didn't work.

The reason this problem lands at the complex end of the chapter, despite years of academic work on readmission prediction, comes down to a few intertwined things.

**The signal is diffuse and slow.** Patient deterioration on an inpatient floor (Recipe 3.7) shows up in vitals and labs over hours. Post-discharge deterioration shows up in patient-reported weights, blood pressures, glucose readings, symptom check-ins, medication adherence, and missed appointments, often over days. Some of those signals are continuous (a Bluetooth scale that uploads daily). Some are intermittent (a patient who fills out a symptom survey twice a week). Some are absent for entirely benign reasons (the scale's battery died) and entirely concerning reasons (the patient is too short of breath to get on the scale). The pipeline has to handle missing-data ambiguity gracefully, because missing data is itself the most common signal.

**Baselines are deeply personal and the post-discharge baseline isn't the inpatient baseline.** A patient discharged at 198 lbs is at their target dry weight. A weight of 200 a week later is fine. A weight of 200 in a patient discharged at 175 is a four-alarm fire. Population thresholds are nearly useless; patient-specific baselines are essential. The baseline has to be established quickly (the first few post-discharge days are the highest-risk window) and adjusted as the patient stabilizes (their dry weight may drift over time as their heart failure regimen optimizes).

**Intervention capacity is the binding constraint.** Unlike inpatient deterioration where the rapid response team is on shift 24/7, post-discharge intervention requires care managers, transition-of-care nurses, pharmacists, social workers, and community health workers, almost always operating during business hours, almost always understaffed, and almost always managing a queue. A model that says "five hundred of your discharged patients are at elevated risk this week" is operationally useless unless it ranks them sharply enough that the care management team can work the top of the list and trust that the bottom is genuinely lower-priority. Precision at the top of the ranking matters more than overall AUROC.

**Causality and correlation are tangled.** A patient whose weight went up and got readmitted shows the model that weight gain predicts readmission. A patient whose weight went up, got a phone call, got a same-day diuretic adjustment, and didn't get readmitted shows the model that weight gain doesn't predict readmission. The intervention itself disrupts the prediction problem. This is the fundamental "treatment effect on prediction" issue, and naive supervised learning on observational data produces models that quietly absorb the historical intervention pattern. You end up predicting "patient who would have been readmitted in the absence of an intervention" using a model that was trained on a world where interventions happened.

**The outcome label is operationally messy.** "Readmission within 30 days" sounds clean. In practice: readmission to which hospital (your hospital, any hospital, any acute care facility)? Planned readmissions for staged procedures (CABG followed by valve replacement) that CMS excludes? Observation stays that aren't technically admissions but are clinically the same event? ED visits that almost-but-didn't-quite become admissions? Skilled nursing facility transfers that are technically discharges-to-SNF? Each definition produces a different label, and the choice shapes what your model learns. <!-- TODO (TechWriter): verify the current CMS HRRP exclusion rules for planned readmissions and the specific operational definitions used in the methodology. -->

**Patient-reported data is messy, sparse, and biased.** A patient who's well enough to weigh themselves every morning is healthier in expectation than a patient who skips three days. A patient who's tech-savvy enough to use the patient portal differs from one who isn't. A patient with a supportive family member helping with logging differs from one who lives alone. Models trained on patient-reported data can encode digital-engagement bias in ways that map onto socioeconomic and demographic disparities. Subgroup performance audits are not optional.

**Workflow integration is, again, the actual product.** A risk score in a dashboard that nobody opens is worse than no score. The output has to flow into the care management team's daily worklist, the transition-of-care nurse's outreach queue, the pharmacist's medication-reconciliation review list, and (for the highest-risk patients) the cardiologist's same-day add-on list. Each of those integrations is its own project. The pipeline is half the system; the workflow is the other half. Sound familiar? It should. This is the same lesson as Recipe 3.7, applied to a different timescale.

**Equity is a first-order concern, not a side note.** Readmission rates differ across demographic and socioeconomic groups for reasons that are mostly not about clinical risk: housing stability, food security, transportation, social support, English-language proficiency, prior healthcare experiences. Models that predict readmission well in aggregate can perform meaningfully worse on subgroups, and the operational response (more outreach to predicted-higher-risk patients) can either reduce or amplify existing disparities depending on how it's deployed. The CMS HRRP program added Medicaid stratification in 2019 partly in response to evidence that the original methodology penalized safety-net hospitals serving more vulnerable populations. <!-- TODO (TechWriter): verify the specific year and details of the CMS HRRP peer-grouping and dual-eligibility stratification methodology change. -->

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

**Day 30+: The post-window observation.** The 30-day cutoff is a CMS construct. From a clinical perspective, readmissions on day 31, 35, 60 still represent transition-of-care failures. Some hospital programs track 60- and 90-day windows for internal quality metrics even though CMS only penalizes the 30-day metric. <!-- TODO (TechWriter): verify the typical clinical practice around extended-window tracking; this varies by organization and condition. -->

The pipeline has to produce useful output at every point in this timeline, not just at the moment of discharge. That's the operational requirement that makes this a streaming problem, not a batch one.

### Data Sources That Actually Drive Signal

The signal-to-noise ratio depends entirely on what data you can pull and at what cadence. Some categories matter a lot more than the literature on discharge-time scoring suggests.

**Patient-reported outcomes (PROs).** Symptom check-ins, pain scores, energy/wellbeing assessments, medication adherence self-reports. Usually delivered through a patient-facing app, an SMS-based check-in, or an IVR phone call. Cadence varies by program (daily for high-risk patients, weekly for moderate-risk). When the patient stops responding, that's also a signal.

**Remote patient monitoring (RPM) device data.** Bluetooth-enabled scales, blood pressure cuffs, pulse oximeters, glucose monitors, peak flow meters. The device transmits to a vendor cloud (BodyTrace, A&D Medical, iHealth, Withings, Roche, Abbott, several others), which transmits to your aggregation platform. Cadence is per-measurement; a daily-weight cohort produces a measurement per day per patient.

**Continuous glucose monitor (CGM) data.** A specific sub-category of RPM that produces high-cadence data (5-15 minute readings). Mostly relevant for diabetes-focused readmission prevention.

**Wearable data.** Apple Watch, Fitbit, Garmin, Oura, etc. Heart rate, activity counts, sleep patterns, blood oxygen (when available), atrial fibrillation detection (Apple Watch). Lower data quality and harder integration than dedicated medical devices, but increasingly common because patients already wear them.

**EHR feeds.** ED visits at your facility, lab orders that came through, medication refill history (when integrated with the pharmacy), care team messages, post-discharge clinic visits. These are the most accurate signals when they happen, but they're often delayed (a refill might happen days before it's reflected in your data) and incomplete (a patient who fills a prescription at a community pharmacy not connected to your network is invisible).

**Health Information Exchange (HIE) data.** ED visits and admissions at other facilities. Critical for "did this patient get readmitted somewhere else" questions and for early-warning when your patient is at another ED right now. HIE coverage varies enormously by region; some states have robust HIEs, others have nothing usable. <!-- TODO (TechWriter): verify the current state-level HIE coverage; CMS-funded TEFCA expansion has shifted the landscape. -->

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

**Recurrent neural networks (LSTM, GRU) on multi-modal time series.** Train on patient sequences with multiple modalities (vitals, symptoms, medication adherence) and predict the probability of readmission in the next N days. The model implicitly learns the trajectory shape and the deviations that matter. Strong performance when training data is abundant; data-hungry, less interpretable, and sensitive to data quality issues. Used in academic research more than production deployments as of 2026. <!-- TODO (TechWriter): verify the current published state-of-the-art for LSTM-based post-discharge readmission prediction; the literature is evolving. -->

**Transformer-based clinical time series models.** Foundation models for clinical data (BEHRT, Med-BERT, the various clinical time-series transformers) are starting to show strong results on readmission and post-discharge tasks. Production deployment is still rare. Worth experimenting with on retrospective data; probably not the right choice for a first production deployment.

**Survival analysis.** Frame the problem as time-to-event (readmission). Cox proportional hazards models, accelerated failure time models, deep survival networks (DeepSurv, DeepHit). The output is a hazard function or a survival curve, which conveys information about both whether and when readmission is likely. Aligns better with operational use than binary classification (the 60% likelihood of readmission tomorrow drives different action than 60% likelihood of readmission in three weeks).

**Gradient-boosted trees on engineered time-window features.** The workhorse approach. Compute features over rolling windows (last 3 days, last 7 days, last 14 days), feed them into XGBoost or LightGBM, score every patient daily. SHAP values produce per-prediction explanations. Most production-grade post-discharge programs are some flavor of this; the sophistication is in the feature engineering, not the model.

**Hybrid scoring.** A practical pattern: combine a discharge-time risk score (the patient's intrinsic risk at the moment of discharge), a per-modality control-chart deviation score (weight is up, BP is unstable), and an engagement score (the patient stopped checking in). The composite ranks the worklist; the per-component scores drive the explanation. Easy to deploy, easy to explain, easy to tune.

**Causal-inference-aware models.** A growing body of work tries to handle the treatment-effect-on-prediction problem by modeling the intervention explicitly: counterfactual estimators, target-trial-emulation, instrumental variables, propensity-matched controls. These are research-grade as of 2026; most production deployments accept the bias and validate prospectively.

A reasonable progression: start with patient-specific control charts on the high-signal modalities (weight for heart failure, blood pressure for hypertension, glucose for diabetes), augmented by an engagement-decay flag (the patient stopped checking in) and the discharge-time risk score as a tier modifier. Validate that the worklist generated by this simple system matches care management judgment about which patients to call. Add a gradient-boosted model on top once you have outcome labels from the simple system. Add LSTM or transformer layers only if the marginal gain justifies the operational complexity.

### Outcome Definition Is, Again, Surprisingly Hard

The same lesson from Recipe 3.7 applies: the choice of outcome shapes what your model learns, and "30-day readmission" is not a single label.

**All-cause readmission within 30 days, all-facilities.** The HRRP-relevant definition. Requires HIE or claims data to capture readmissions to other facilities. Without that, you're modeling "readmission to our hospital," which biases toward patients who would have come back here anyway.

**Condition-specific readmission within 30 days.** A heart failure patient readmitted with heart failure vs. readmitted with anything. CMS uses condition-specific definitions for the HRRP penalty calculation. <!-- TODO (TechWriter): verify CMS HRRP measure specifications; the methodology has evolved. -->

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

```
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

## The AWS Implementation

### Why These Services

**Amazon API Gateway and AWS Lambda for RPM device webhook ingestion.** RPM device vendors send measurements via webhook. API Gateway receives the webhook, Lambda validates and normalizes it, and the canonical event flows into the rest of the pipeline. For vendors that prefer pull-based integration, scheduled Lambdas pull from vendor APIs on the configured cadence.

**Amazon Kinesis Data Streams (or Amazon SQS) for the canonical event stream.** The normalized canonical events flow through Kinesis (when ordering and replay matter) or SQS (when simpler queueing is sufficient). The cadence is much lower than Recipe 3.7 (a moderate-sized program might see thousands of events per day per few hundred patients, not millions); the simpler queue often suffices.

**Amazon DynamoDB for the patient state store.** Single-digit-millisecond reads on the current patient snapshot. Each enrolled patient is a record with current monitoring tier, recent values, engagement metrics, and intervention history pointers. DynamoDB streams trigger feature recomputation when state changes.

**Amazon Timestream for the trajectory history store.** Patient-reported weights, blood pressures, glucoses, and symptom scores are time-series data. Timestream's purpose-built storage and query model fit naturally. Magnetic-tier retention covers the multi-week baseline window cost-effectively. <!-- TODO (TechWriter): verify the current HIPAA eligibility status of Amazon Timestream and the BAA coverage; some deployments may use DynamoDB or S3 with Athena instead. -->

**AWS HealthLake for the longitudinal patient record.** When the program needs FHIR-formatted patient records integrated with the wider health-system data, HealthLake provides storage, query, and integration. For programs with established FHIR infrastructure, HealthLake is a strong fit.

**Amazon SageMaker for model training, hosting, and feature management.** The composite scoring model trains as a SageMaker Training Job against retrospective data in S3, deploys to a SageMaker endpoint for daily scoring (batch transform is appropriate for daily cadence; real-time endpoint is appropriate for high-frequency rescoring on new data). SageMaker Feature Store keeps offline (training) and online (scoring) feature vectors consistent. SageMaker Clarify produces fairness reports across subgroups and per-prediction SHAP values.

**Amazon SageMaker Model Monitor.** Continuously monitors data drift, prediction drift, and (with labels) model quality. Critical for catching the gradual drift in patient population, intervention pattern, and device firmware that affects post-discharge programs.

**Amazon Bedrock for explanation narratives and outreach script suggestions.** SHAP values surface the technical drivers; Bedrock-hosted LLMs convert them and the patient context into care-manager-facing narratives ("This patient's weight has trended up 2.4 lbs over the last 3 days. They responded to symptom check-ins through Friday but not Saturday or Sunday. Their last care management contact was Wednesday. Suggested outreach: confirm weight trend, ask about diuretic adherence, ask about diet over the weekend, consider same-day clinic add-on.") Always with human review; the LLM is producing decision support, not decisions. <!-- TODO (TechWriter): confirm the set of HIPAA-eligible Bedrock foundation models as of the current year. -->

**Amazon Comprehend Medical for free-text feature extraction.** Care management notes contain substantial signal in free text. Comprehend Medical extracts conditions, symptoms, medications, and concerns. Optional but useful when the care management interaction feed is text-rich.

**AWS Step Functions for orchestration.** The daily scoring run, the worklist generation, and the periodic retraining are multi-step workflows. Step Functions handles orchestration with retry and error handling.

**Amazon EventBridge for routing.** Scoring outputs publish to EventBridge with patient context and tier. Subscribers include the worklist UI back end, the pharmacist review list back end, the provider escalation list, and the audit logger.

**Amazon API Gateway and AWS AppSync for the care management workflow back end.** The care management UI (whether built in-house or vendored) consumes the worklist via API. AppSync (GraphQL) is often a better fit when the UI needs flexible queries over patient state, intervention history, and trajectory data; API Gateway plus REST is fine for simpler integrations.

**Amazon OpenSearch Service for worklist audit and analytics.** Every score, every alert, every intervention, and every outcome is indexed in OpenSearch for governance queries, performance analytics, and ad-hoc clinical safety review. Data also flows to S3 for retraining.

**Amazon S3 for the data lake.** Historical RPM data, PRO data, EHR events, and outcome labels live here, partitioned by date and patient. Customer-managed KMS encryption. Used by SageMaker for training and Athena for ad-hoc analysis.

**Amazon QuickSight for governance dashboards.** Subgroup performance, intervention success rates, alert volume, capacity utilization, and program-level outcome metrics. The clinical leadership team and the program operations team consume these.

**Amazon Athena for ad-hoc analysis.** Care managers, analysts, and the program team query the lake for ad-hoc questions ("how many patients in this cohort had at least one successful contact in the first week"). Athena over partitioned S3 is the cheap, flexible answer.

**AWS HealthOmics or generic S3 for genomic data (rarely relevant).** Most readmission programs do not use genomic data. Mentioned only for completeness; usually skip.

**AWS End User Messaging or a third-party SMS/IVR vendor for patient outreach.** The outreach itself (SMS check-ins, IVR calls) is often delivered through specialist healthcare communication vendors (CipherHealth, GetWellNetwork, Memora Health, Cipher). For SMS-only, AWS End User Messaging (formerly Pinpoint SMS and Voice) works. The integration boundary matters: keep PHI in HIPAA-eligible services; the patient-facing channel needs a BAA.

**Amazon CloudWatch and AWS X-Ray.** Operational monitoring of the pipeline, scoring latency, end-to-end traces. Latency budgets matter less than Recipe 3.7 (the cadence is daily, not per-event), but data freshness matters: a worklist computed at 7 a.m. should reflect data through end-of-day yesterday plus any overnight events.

**AWS CloudTrail.** Audit logging on every PHI-bearing store and every API call against the scoring service. Every score, every worklist generation, every intervention is logged.

**AWS KMS.** Customer-managed keys on every PHI-bearing store: DynamoDB, Timestream, S3, OpenSearch, Kinesis/SQS, SageMaker volumes and Feature Store. Key rotation policies set per organizational requirements.

### Architecture Diagram

```mermaid
flowchart TB
    A[RPM device vendor<br/>webhooks: weight, BP,<br/>SpO2, glucose] --> B[API Gateway<br/>+ AWS Lambda<br/>device-ingest]
    C[Patient-reported<br/>outcomes / SMS / IVR<br/>vendor] --> B
    D[EHR feed<br/>HL7/FHIR:<br/>ED visits, clinics,<br/>orders, refills] --> E[AWS Lambda<br/>ehr-event-ingest]
    F[HIE / claims feed<br/>external admissions] --> E
    G[Care management<br/>interaction events] --> H[AWS Lambda<br/>cm-event-ingest]
    I[Discharge events<br/>+ tier assignment] --> J[AWS Lambda<br/>enrollment-handler]

    B --> K[Amazon Kinesis<br/>patient-events]
    E --> K
    H --> K
    J --> K

    K --> L[AWS Lambda<br/>event-normalizer]
    L --> M[(Amazon DynamoDB<br/>patient-state)]
    L --> N[(Amazon Timestream<br/>trajectory-history)]
    L --> O[(Amazon S3<br/>raw-events lake)]

    P[Amazon EventBridge<br/>daily-scoring-tick] --> Q[AWS Step Functions<br/>daily-scoring-pipeline]
    M -- DynamoDB Streams --> R[AWS Lambda<br/>event-driven-rescore]

    Q --> S[AWS Lambda<br/>feature-engine]
    R --> S
    S --> N
    S --> M
    S --> T[(SageMaker<br/>Feature Store)]

    S --> U[SageMaker Endpoint<br/>composite-anomaly-model]
    S --> V[AWS Lambda<br/>per-modality-detectors]

    U --> W[AWS Lambda<br/>calibration-and-tier]
    V --> W

    W --> X[AWS Lambda<br/>explanation-builder]
    X --> Y[Amazon Bedrock<br/>narrative-LLM]
    X --> Z[SageMaker Clarify<br/>SHAP values]

    W --> AA[AWS Lambda<br/>worklist-builder]
    AA --> AB[(Amazon DynamoDB<br/>worklist-state)]
    AA --> AC[Amazon EventBridge<br/>worklist-bus]

    AC --> AD[Care Management<br/>UI back end<br/>AppSync/API Gateway]
    AC --> AE[Pharmacist review<br/>list back end]
    AC --> AF[Provider escalation<br/>list back end]
    AC --> AG[(Amazon OpenSearch<br/>worklist-audit)]

    AH[Care manager / nurse /<br/>pharmacist actions] --> AI[AWS Lambda<br/>intervention-capture]
    AI --> AB
    AI --> AG
    AI --> M

    AJ[Readmission / ED visit /<br/>death events] --> AK[AWS Lambda<br/>outcome-capture]
    AK --> AG
    AK --> AL[(Amazon S3<br/>training-labels)]

    AL --> AM[AWS Step Functions<br/>retraining-pipeline]
    AM --> AN[SageMaker Training<br/>Job]
    AN --> AO[(SageMaker Model<br/>Registry)]
    AO --> U

    U --> AP[SageMaker Model<br/>Monitor]
    AP --> AQ[CloudWatch alarms<br/>+ governance dashboards]

    AG --> AR[Amazon Athena]
    AL --> AR
    AR --> AS[Amazon QuickSight<br/>governance dashboards]

    AT[CloudTrail<br/>data events] -.-> M
    AT -.-> N
    AT -.-> O
    AT -.-> AB
    AT -.-> AG
    AT -.-> AL

    style M fill:#9ff,stroke:#333
    style N fill:#9ff,stroke:#333
    style AB fill:#f9f,stroke:#333
    style AG fill:#f9f,stroke:#333
    style U fill:#ffc,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon API Gateway, AWS Lambda, Amazon Kinesis Data Streams (or Amazon SQS), Amazon DynamoDB, Amazon Timestream, AWS HealthLake (optional), Amazon S3, Amazon SageMaker (Training, Hosting, Feature Store, Clarify, Model Monitor, Model Registry), Amazon Comprehend Medical (optional, for note feature extraction), Amazon Bedrock, Amazon EventBridge, AWS Step Functions, AWS AppSync, Amazon OpenSearch Service, Amazon Athena, Amazon QuickSight, AWS End User Messaging (or third-party patient communication vendor), AWS Secrets Manager, AWS KMS, AWS CloudTrail, Amazon CloudWatch, AWS X-Ray. |
| **IAM Permissions** | Least-privilege per role. Device ingest Lambdas validate webhooks and write to the event stream. Feature engine reads from DynamoDB and Timestream, writes to Feature Store. Scoring orchestrator invokes the SageMaker endpoint, publishes to EventBridge. Worklist builder reads scores and writes worklist state. Care manager roles read worklist state and write intervention records only. Model team roles can train and deploy but cannot read PHI directly without explicit elevation. No `*` permissions; every action scoped to specific resources. |
| **BAA** | Signed AWS BAA. All services configured per BAA requirements. RPM vendors and PRO vendors must have their own BAAs with the hospital. See the [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/). |
| **Encryption** | Customer-managed KMS keys on every PHI-bearing store: Kinesis, DynamoDB, Timestream, S3, OpenSearch, SageMaker (volumes, Feature Store, model artifacts). TLS 1.2 or higher in transit. Webhook endpoints validate vendor signatures and reject unsigned traffic. |
| **VPC** | Production deployment in a VPC with VPC endpoints for S3, DynamoDB, KMS, SageMaker runtime, Bedrock, Comprehend Medical, EventBridge, and Step Functions. Lambdas that touch PHI run in the VPC. RPM vendor and PRO vendor integrations typically traverse the public internet (TLS-protected); some hospital networks require Direct Connect or PrivateLink-style routing for these integrations. |
| **CloudTrail and Data Events** | Enabled with data events on every PHI-bearing store and on the worklist and audit indexes. Every score, every worklist generation, every intervention capture, every outcome event is logged. Log retention per organizational policy and applicable regulations. |
| **Care Management Governance** | A care management governance committee (typically including transitions-of-care leadership, hospitalists, primary care leadership, pharmacy, social work, nursing leadership, patient experience, and quality leadership) must be established before deployment. The committee owns the program design, intervention protocols, escalation pathways, equity considerations, and decommissioning criteria. |
| **Regulatory Posture** | Most post-discharge anomaly detection systems are clinical workflow tools rather than FDA-regulated medical devices, but the determination depends on the level of autonomy and the clinical scenario. Systems that produce recommendations for human review with transparent reasoning typically qualify for the 21st Century Cures Act CDS exemption. Higher-autonomy or closed-loop systems may not. Regulatory affairs should opine before deployment. |
| **Local Validation Required** | Vendor or external models must be validated on local population before clinical deployment. Subgroup-stratified validation is essential. Validation should compare against the existing standard of care (typically the existing transitions-of-care program). Evaluation metrics should include not just discrimination and calibration, but operational metrics: patients flagged per care manager per day, intervention rate, intervention success rate, and (where measurable) the change in 30-day readmission rate per cohort attributable to the program. |
| **Sample Data** | [MIMIC-IV](https://physionet.org/content/mimiciv/) has post-discharge readmission labels but limited post-discharge data (the dataset is primarily inpatient). [eICU Collaborative Research Database](https://physionet.org/content/eicu-crd/) is similar. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic patient data with discharge-and-readmission events. RPM vendor sandboxes (BodyTrace, A&D Medical, Withings) provide test data feeds. Never use real PHI in development. |
| **EHR + RPM Vendor Integration** | The two longest dependencies in this project are typically the EHR ingestion (HL7/FHIR feeds for ED visits, clinic visits, refills, orders) and the RPM vendor integration (webhooks for measurements, device assignment, patient enrollment). Plan for 2-6 months of integration engineering for each, in parallel. Care management workflow integration (Salesforce Health Cloud, Epic Healthy Planet, etc.) is a third long dependency. |
| **Cost Estimate** | For a program monitoring 2,000 patients in the post-discharge window at any given time with daily scoring: device-vendor data through API Gateway and Lambda: ~$50-200/month. Kinesis or SQS: ~$50-150/month. DynamoDB patient state and worklist state: ~$200-400/month. Timestream trajectory history: ~$100-300/month. SageMaker endpoint hosting (modest instance class for daily-cadence scoring): ~$300-1,000/month. SageMaker training (monthly retraining): ~$100-300/month. Bedrock for explanation narratives (one per worklist row, daily): ~$100-300/month. OpenSearch for worklist audit: ~$300-700/month. Lambda, EventBridge, Step Functions, supporting services: ~$200-500/month. Total infrastructure: typically $1,500-4,000/month for a moderately-sized program. Outreach staffing (care managers, transitions nurses) is the dominant cost; one care manager at a typical loaded cost can cost more in a single month than the entire infrastructure. The infrastructure pays for itself if the program prevents one to two readmissions per year (typical readmission cost in the United States is in the $10,000-20,000 range depending on payer mix and condition mix). |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon API Gateway** | Receives RPM device webhooks; care management UI back-end fronting |
| **AWS Lambda (device-ingest)** | Validates and normalizes RPM webhook payloads |
| **AWS Lambda (ehr-event-ingest)** | Normalizes EHR events (ED visits, clinic visits, refills, orders) |
| **AWS Lambda (cm-event-ingest)** | Normalizes care management interaction events |
| **AWS Lambda (enrollment-handler)** | Handles discharge-event enrollment into the monitoring program |
| **AWS Lambda (event-normalizer)** | Stream processing of canonical events into state stores |
| **Amazon Kinesis Data Streams (or Amazon SQS)** | Canonical event stream |
| **Amazon DynamoDB (patient-state)** | Current snapshot of every enrolled patient |
| **Amazon DynamoDB (worklist-state)** | Active worklist rows, intervention status, suppression rules |
| **Amazon Timestream** | Trajectory time-series for weights, BPs, glucoses, symptoms |
| **AWS HealthLake (optional)** | FHIR-formatted longitudinal patient record |
| **Amazon S3** | Raw event lake, training data, retrospective analysis, audit log archive |
| **AWS Lambda (feature-engine)** | Computes the model's input feature vector |
| **AWS Lambda (per-modality-detectors)** | Control charts and per-modality anomaly scores |
| **AWS Lambda (calibration-and-tier)** | Applies calibration and assigns operational tier |
| **AWS Lambda (explanation-builder)** | Assembles SHAP values plus narrative explanations |
| **AWS Lambda (worklist-builder)** | Ranks and de-duplicates the daily worklist |
| **AWS Lambda (intervention-capture)** | Records care manager actions and intervention outcomes |
| **AWS Lambda (outcome-capture)** | Records readmission, ED visit, and other outcome events |
| **Amazon SageMaker Endpoint** | Hosts the composite anomaly scoring model |
| **Amazon SageMaker Training** | Model retraining pipeline against retrospective data |
| **Amazon SageMaker Feature Store** | Online and offline feature consistency with point-in-time correctness |
| **Amazon SageMaker Clarify** | Subgroup fairness reports and per-prediction SHAP explanations |
| **Amazon SageMaker Model Monitor** | Data drift, prediction drift, quality drift monitoring |
| **Amazon SageMaker Model Registry** | Versioning and approval workflow for model deployments |
| **Amazon Comprehend Medical** | Entity extraction from care management notes |
| **Amazon Bedrock** | Care-manager-facing narrative explanations and outreach script suggestions |
| **Amazon EventBridge** | Routes scoring events and worklist events to subscribers |
| **AWS AppSync / API Gateway** | Care management UI back end and integration APIs |
| **Amazon OpenSearch Service** | Worklist and intervention audit index |
| **Amazon Athena** | SQL-over-S3 for ad-hoc queries against historical data |
| **Amazon QuickSight** | Care management governance and operational dashboards |
| **AWS Step Functions** | Daily scoring pipeline and retraining pipeline orchestration |
| **AWS End User Messaging (or third-party vendor)** | Patient-facing SMS check-ins and outreach |
| **AWS Secrets Manager** | EHR credentials, device-vendor API keys, care management system credentials |
| **AWS KMS** | Customer-managed keys for every PHI-bearing store |
| **AWS CloudTrail** | Audit logging on every PHI store and every API operation |
| **Amazon CloudWatch + AWS X-Ray** | Pipeline health, scoring latency, end-to-end tracing |

---

### Code

> **Reference implementations:** These aws-samples repositories demonstrate patterns that apply here:
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Time-series modeling, XGBoost on tabular features, Feature Store with online and offline stores, Model Monitor configurations, Clarify SHAP examples.
> - [`aws-samples`](https://github.com/aws-samples): search for "FHIR," "HealthLake," "remote patient monitoring," and "care management" for healthcare-specific integration patterns.
> <!-- TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating remote patient monitoring, post-discharge anomaly detection, or care management automation on AWS. Adjacent examples exist (real-time scoring, healthcare ML pipelines); a direct match has not been confirmed at the time of writing. -->

#### Walkthrough

<!-- Editor note: the expert reviewer flagged several prose-vs-pseudocode asymmetries that need follow-up before the next pass. None block PASS, but each is a place where the prose makes a discipline claim that the canonical pseudocode walkthrough below does not architecturally enforce. Address by adding short architectural primitives in the relevant Steps and a one-line note in the General Architecture Pattern subsections; do not rewrite the prose. Per-finding TODOs follow. -->

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Cold-start uniform-high-touch in the first 72 hours regardless of model output. The Honest Take is unusually direct about this; Step 7's worklist construction does not enforce it. Add a cold-start-routing primitive in Step 7 that promotes cold-start patients with elevated discharge-time risk to at-least-tier_2 regardless of composite score; surface cold-start status in the worklist row; add a paragraph to the General Architecture Pattern's Worklist Builder subsection. -->

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Engagement-decay first-class worklist pathway. The prose treats engagement decay as a first-class signal warranting dedicated outreach; Step 4 routes it through the composite-score pathway only. Add an engagement-decay-specific worklist pathway in Step 7 that surfaces disengaged patients (no_data_in_first_72_hours, stopped_pro_check_ins, stopped_rpm_uploads, previously_engaged_now_silent) at tier_2 or higher regardless of composite score; surface engagement-decay flag in worklist row. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Randomized-rollout / target-trial-emulation primitive for causal evaluation. The Honest Take recommends randomized rollouts; pseudocode shows no `evaluation_track` field on the patient-state record and no track-aware filtering in the worklist build. Add `evaluation_track` attribute set at enrollment with stratified random assignment; worklist construction filters to `evaluation_track == "program"`; outcome-capture tracks both tracks; training-labels archive stratifies labels by track. -->

<!-- TODO (TechWriter): Expert review A1 (MEDIUM). Outcome-event and intervention-event idempotency at the EventBridge-driven capture Lambdas (recurring chapter-wide pattern; thirteenth consecutive recipe). Derive deterministic event keys (`outcome_event.event_id + outcome_event.type` for outcomes; `action_event.event_id` for interventions); conditional DynamoDB write to `processed-outcome-events` and `processed-intervention-events` tables before downstream operations. Strongly recommend a cookbook-wide trigger-idempotency appendix. -->

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). DLQ / poison-message handling for the device-ingest, ehr-event-ingest, cm-event-ingest, enrollment-handler, event-normalizer, feature-engine, worklist-builder, intervention-capture, outcome-capture, and event-driven-rescore Lambdas. Add SQS DLQs with `OnFailure` destinations on each Lambda; CloudWatch alarms on DLQ depth with alarm threshold 1 for device-ingest, event-normalizer, outcome-capture (single-event sensitivity); replay older than the post-discharge prediction window escalates to care-management-governance-committee review. -->

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Reference-data versioning propagation. Step 7's worklist row construction should explicitly carry the audit_trail block (feature_snapshot_id, scoring_record_id, model_version, calibration_version, cohort_thresholds_version) into both the DynamoDB worklist-state write and the OpenSearch worklist-audit index. -->

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Multi-cohort architecture. The Why-This-Isn't-Production-Ready bullet says "designing for multi-cohort from the start is easier than retrofitting"; the pseudocode shows a single composite-scoring pathway with cohort indicator features. Update the Scoring Service paragraph in General Architecture Pattern and Steps 4 and 7 to dispatch to per-cohort endpoints, calibrators, threshold sets, and worklists. -->

<!-- TODO (TechWriter): Expert review A8 (LOW). Suppression-rule expiry. Step 7 reads suppression state but no scheduled job walks the program-hold registry for expired entries; ADT-event-driven hold-review trigger also missing. Add a daily scheduled job that walks the program-hold registry for expired holds and a care-transition trigger via ADT events. -->

<!-- TODO (TechWriter): Expert review S1 (MEDIUM). Worklist row PHI minimization. The EventBridge worklist-bus carries the full narrative (a multi-sentence clinical paragraph naming the patient's deterioration phenotype, recent values, post-acute-event context, and clinical-recommendation-shaped outreach steps) to three subscribers (care-management UI back end, pharmacist review list back end, provider escalation list back end). This is the eighth distinct PHI-minimization-inside-the-BAA surface across the cookbook (Chapter 2: serialized prompt context; Recipes 3.1, 3.3, 3.4, 3.5, 3.6, 3.7: various). Update Step 7 so the per-row event carries only worklist_id, row_id, patient_id, tier, and assigned_care_team; subscribers fetch the full row from the worklist-state DynamoDB table or the OpenSearch worklist-audit index through an authenticated path. Add per-consumer scope to the Prerequisites IAM row: pharmacist role can read rows whose suggested intervention includes medication-related items only; provider escalation role can read rows where tier == tier_1 AND escalation_to_provider is non-null only; care-manager UI role can read rows for the care-team-assigned patient set only. -->

<!-- TODO (TechWriter): Expert review S2 (MEDIUM). Subgroup data governance for fairness monitoring. The "Calibration, Subgroup Performance, and the Equity Question" subsection has the most comprehensive subgroup taxonomy in the chapter (age band, sex, race and ethnicity, language, insurance status, neighborhood SES via ADI/SVI, dual-eligibility status, primary diagnosis, discharge disposition; plus SDOH attributes through PRAPARE / AHC HRSN / Z-codes). Add architectural artifacts to Prerequisites: restrict read access to the demographic-and-attribute store including SDOH attributes (which may be governed differently from clinical PHI under state law); CloudTrail data events on subgroup queries; QuickSight against an aggregated subgroup-metrics table (alert rate by subgroup, calibration ECE by subgroup, intervention rate by subgroup, change in 30-day readmission rate per subgroup attributable to the program), not the raw demographic-joined worklist archive. -->

<!-- TODO (TechWriter): Expert review S3 (LOW). Per-consumer IAM scoping for shared resources (patient-state, scoring-history, worklist-state, intervention-history DynamoDB tables; OpenSearch worklist-audit and intervention-audit indexes). -->

<!-- TODO (TechWriter): Expert review S4 (LOW). RPM device webhook signature-verification posture: per-vendor protocol variation (HMAC-SHA256, mutual TLS, OAuth 2.0, JWT validation), rotation cadence, replay protection via timestamp validation, IP allowlisting at the API Gateway resource policy where the vendor publishes a source-IP range. -->

<!-- TODO (TechWriter): Expert review S5 (LOW). Bedrock LLM-explanation BAA-discipline forward reference to Chapter 2's settled patterns; minimum-necessary prompt construction; output filtering for clinical-recommendation hallucinations vs. outreach-suggestion language; full prompt-and-response audit trail tied to worklist row ID. -->

<!-- TODO (TechWriter): Expert review S6 (LOW). Comprehend Medical care-management-note PHI handling: synchronous DetectEntitiesV2 with minimum-necessary excerpt, derived-feature-flag-only persistence (do not store full Comprehend Medical entity payload alongside feature flags), CloudTrail data events on DetectEntitiesV2 calls. -->

<!-- TODO (TechWriter): Expert review S7 (LOW). Patient-facing SMS/IVR vendor BAA + TCPA discipline: pre-approved templates by content category (PHI-bearing vs de-identified), patient-consent capture as a structured event in the patient-state record, opt-out revocation handled immediately, audit trail in worklist-audit and intervention-audit indexes for TCPA defense. -->

<!-- TODO (TechWriter): Expert review N1 (LOW). VPC endpoint precision: name CloudWatch monitoring (`PutMetricData`) separately from CloudWatch Logs; EventBridge events bus separately from EventBridge Scheduler; SageMaker api / runtime / featurestore-runtime; SNS, Athena, Glue, AppSync, Timestream (write and query), HealthLake, Secrets Manager, bedrock-runtime, comprehendmedical. -->

<!-- TODO (TechWriter): Expert review N2 (LOW). VPC Flow Logs explicitly required (network-level audit complements API-level audit, supports both clinical-safety-review documentation and RPM CPT code billing-defense documentation). -->

<!-- TODO (TechWriter): Expert review N3 (LOW). HealthLake networking and access-control posture (KMS, VPC endpoint, SMART-on-FHIR scope discipline, bulk export to S3 with KMS). -->

<!-- TODO (TechWriter): Expert review N4 (LOW). HIE/claims feed network path (per-source security: MLLPS, FHIR R4 with mutual TLS or SMART-on-FHIR, C-CDA over Direct Trust, EDI 837 over SFTP, near-real-time claims APIs; Direct Connect for HIE-side gateway bridging; per-source trading-partner agreement and audit trail). -->

**Step 1: Enroll the patient at discharge.** The discharge event triggers enrollment into the monitoring program. The discharge-time risk score (computed by a separate model, often the Chapter 7 readmission risk model) sets the initial monitoring tier. The condition cohort drives which trajectory metrics will be tracked.

```
FUNCTION on_discharge_event(discharge_event):
    // Discharge events come from the EHR feed when an ADT discharge fires.
    // Pull discharge-time features and the discharge-time risk score from the
    // Chapter 7 model (separate service); we use them as inputs here.
    discharge_features = pull_discharge_features(discharge_event.encounter_id)
    discharge_risk_score = pull_discharge_risk_score(discharge_event.encounter_id)

    // Determine condition cohort. Multiple cohorts can apply.
    cohorts = determine_cohorts(discharge_event)
    // cohorts: ["heart_failure", "diabetes", "post_op_cardiac"], etc.

    // Initial monitoring tier from discharge-time score.
    initial_tier = tier_from_discharge_score(
        score        = discharge_risk_score,
        cohorts      = cohorts,
        program_caps = current_program_capacity()
    )

    // Build the patient state record.
    state = {
        patient_id:               discharge_event.patient_id,
        encounter_id:             discharge_event.encounter_id,
        enrolled_at:              NOW(),
        discharge_at:             discharge_event.discharge_time,
        discharged_to:            discharge_event.discharge_disposition,
        cohorts:                  cohorts,
        discharge_risk_score:     discharge_risk_score,
        discharge_features:       discharge_features,
        current_tier:             initial_tier,
        is_active:                true,
        last_contact_at:          null,
        last_score_at:            null,
        intervention_history:     [],
        device_assignments:       discharge_event.assigned_devices,        // bluetooth scale, BP cuff, etc.
        program_end_at:            discharge_event.discharge_time + 30 days
    }

    DynamoDB.PutItem(table = "patient-state", item = state)

    // Notify the care management system that a new patient was enrolled.
    EventBridge.PutEvent(
        bus         = "post-discharge-events",
        source      = "enrollment-handler",
        detail_type = "PatientEnrolled",
        detail      = state
    )
```

**Step 2: Ingest RPM measurements and PRO check-ins.** RPM device vendors send measurements via webhook. The webhook handler validates the signature, normalizes the payload, and writes the canonical event into the stream.

```
FUNCTION on_rpm_webhook(webhook_request):
    // Validate the vendor's signature. Reject anything that doesn't validate.
    IF NOT verify_vendor_signature(webhook_request):
        return 401

    // Parse the vendor-specific payload into a canonical measurement event.
    parsed = parse_vendor_payload(webhook_request)
    canonical_event = {
        event_id:           generate_event_id(parsed),
        patient_id:         resolve_patient_id_from_device(parsed.device_id),
        event_type:         "rpm_measurement",
        modality:            parsed.modality,                    // weight, blood_pressure, spo2, glucose, peak_flow
        value:               convert_to_canonical_units(parsed.value, parsed.units),
        units:               canonical_units_for(parsed.modality),
        observed_at:         parsed.measurement_time,
        received_at:         NOW(),
        device_id:           parsed.device_id,
        quality_flags:       parsed.quality_flags                // sensor flags, posture flags, etc.
    }

    // Resolve patient. Devices are assigned to patients at enrollment.
    IF canonical_event.patient_id is null:
        send_to_quarantine(canonical_event, reason = "unknown_device")
        return 202

    Kinesis.PutRecord(
        stream_name = "patient-events",
        data        = canonical_event,
        partition_key = canonical_event.patient_id
    )
    return 200

FUNCTION on_pro_check_in(check_in_event):
    // Patient-reported outcomes from the patient-facing app, SMS, or IVR vendor.
    // Similar pattern: validate, normalize, route.
    canonical_event = {
        event_id:           generate_event_id(check_in_event),
        patient_id:         check_in_event.patient_id,
        event_type:         "pro_check_in",
        modality:            check_in_event.template_id,         // hf_symptom_check, post_op_symptom_check, etc.
        responses:           check_in_event.responses,
        symptom_score:       compute_symptom_score(check_in_event.responses, check_in_event.template_id),
        free_text:           check_in_event.free_text_concerns,
        observed_at:         check_in_event.submitted_at,
        received_at:         NOW()
    }
    Kinesis.PutRecord(
        stream_name = "patient-events",
        data        = canonical_event,
        partition_key = canonical_event.patient_id
    )
```

**Step 3: Update patient state and trajectory history.** The event normalizer reads from the stream, updates the patient state with the latest values, and writes time-series records to Timestream.

```
FUNCTION on_canonical_event(event):
    // Read current state. Skip events for patients not actively enrolled.
    state = DynamoDB.GetItem(
        table = "patient-state",
        key   = { patient_id: event.patient_id, encounter_id: resolve_encounter(event) }
    )
    IF state is null OR NOT state.is_active:
        log_skipped_event(event, reason = "not_active")
        return

    // Update the relevant fields based on event type.
    IF event.event_type == "rpm_measurement":
        state.latest_values[event.modality] = {
            value:       event.value,
            observed_at: event.observed_at,
            quality:     event.quality_flags
        }
        state.last_measurement_at = event.observed_at
        // Reset engagement counter; the patient just contributed data.
        state.last_data_at = event.observed_at

        // Append to Timestream for trajectory analysis.
        Timestream.WriteRecord(
            database  = "post-discharge",
            table     = "rpm_measurements",
            dimensions = {
                patient_id:    event.patient_id,
                modality:      event.modality
            },
            time_value = event.observed_at,
            value      = event.value
        )

    IF event.event_type == "pro_check_in":
        state.latest_pro = {
            template:      event.modality,
            symptom_score: event.symptom_score,
            free_text:     event.free_text,
            observed_at:   event.observed_at
        }
        state.last_pro_at = event.observed_at
        state.last_data_at = event.observed_at

        Timestream.WriteRecord(
            database  = "post-discharge",
            table     = "pro_symptom_scores",
            dimensions = {
                patient_id: event.patient_id,
                template:   event.modality
            },
            time_value = event.observed_at,
            value      = event.symptom_score
        )

    IF event.event_type == "ed_visit" OR event.event_type == "external_admission":
        // High-priority trigger; mark for immediate re-scoring and worklist surfacing.
        state.recent_acute_events.append({
            type:           event.event_type,
            facility:       event.facility,
            occurred_at:    event.occurred_at
        })
        state.urgent_rescore_requested = true

    IF event.event_type == "refill" OR event.event_type == "refill_missed":
        state.medication_events.append({
            rx_norm_code:    event.rx_norm_code,
            event_subtype:   event.event_type,
            occurred_at:     event.occurred_at,
            therapeutic_class: classify_medication(event.rx_norm_code)
        })

    IF event.event_type == "care_management_interaction":
        state.last_contact_at = event.occurred_at
        state.intervention_history.append({
            interaction_type: event.interaction_type,
            outcome:           event.contact_outcome,
            intervention:      event.intervention,
            notes:             event.notes,
            occurred_at:       event.occurred_at,
            staff_id:          event.staff_id
        })

    state.updated_at = NOW()
    DynamoDB.PutItem(table = "patient-state", item = state)

    // Some events trigger immediate re-scoring; others wait for the daily tick.
    IF should_rescore_immediately(event):
        EventBridge.PutEvent(
            bus         = "post-discharge-scoring",
            source      = "event-normalizer",
            detail_type = "RescoreRequest",
            detail      = { patient_id: state.patient_id, encounter_id: state.encounter_id, reason: event.event_type }
        )
```

**Step 4: Run the daily scoring pipeline.** Once a day (typically early morning), the scoring pipeline iterates every active patient, computes their feature vector, scores them, and produces the worklist.

```
FUNCTION daily_scoring_pipeline():
    // Step Functions orchestrates this; broken into stages for retry and observability.
    active_patients = DynamoDB.Query(
        table         = "patient-state",
        index         = "is_active-index",
        key_condition = "is_active = :true"
    )

    FOR each patient in active_patients:
        score_record = score_patient(patient.patient_id, patient.encounter_id, trigger = "daily")
        publish_for_worklist(score_record)

    // Build the worklist after all patients are scored.
    worklist = build_worklist(today)
    publish_worklist(worklist)

FUNCTION score_patient(patient_id, encounter_id, trigger):
    state = DynamoDB.GetItem(
        table = "patient-state",
        key   = { patient_id, encounter_id }
    )

    // Compute features (next step).
    features = compute_features(state)

    // Run per-modality anomaly detectors first; these produce per-modality
    // deviation scores that go in as features for the composite model AND
    // surface independently in the explanation layer.
    per_modality_scores = {}
    FOR each modality in MONITORED_MODALITIES_FOR(state.cohorts):
        per_modality_scores[modality] = run_modality_detector(
            modality:   modality,
            history:    fetch_modality_history(patient_id, modality, BASELINE_WINDOW_DAYS),
            baseline:   compute_patient_baseline(patient_id, modality),
            cohort_priors: cohort_prior_for(state.cohorts, modality)
        )
        features[f"{modality}_deviation_score"] = per_modality_scores[modality].deviation_score
        features[f"{modality}_baseline_age_days"] = per_modality_scores[modality].baseline_age_days

    // Composite scoring with the gradient-boosted model.
    composite_output = SageMaker.Runtime.InvokeEndpoint(
        endpoint_name = "post-discharge-anomaly-model",
        body          = serialize(features)
    )
    // composite_output: { score, model_version, feature_importance_top_k }

    // Calibration. Apply per-cohort calibration where calibration drift differs.
    calibrated = apply_calibration(
        raw_score    = composite_output.score,
        calibration  = CALIBRATION_FOR(state.cohorts),
        subgroup     = subgroup_for_calibration(features)
    )

    // Tier assignment. Tiers map to operational outreach intensity:
    //   tier_1: same-day outreach by transitions nurse / pharmacist
    //   tier_2: outreach within 24h by care manager
    //   tier_3: routine touchpoint per program protocol
    //   below_threshold: standard discharge follow-up only
    tier = tier_from_score_and_cohort(
        score:    calibrated,
        cohorts:  state.cohorts,
        capacity: current_program_capacity_for(state.cohorts),
        suppression_check: check_suppression(state)
    )

    score_record = {
        score_id:                generate_score_id(),
        patient_id:              patient_id,
        encounter_id:            encounter_id,
        scored_at:                NOW(),
        trigger:                  trigger,                              // daily, event_driven
        composite_raw:            composite_output.score,
        composite_calibrated:     calibrated,
        per_modality_scores:      per_modality_scores,
        tier:                     tier,
        days_post_discharge:      days_between(state.discharge_at, NOW()),
        feature_snapshot_id:      persist_feature_snapshot(features),
        model_version:            composite_output.model_version
    }

    DynamoDB.PutItem(table = "scoring-history", item = score_record)
    OpenSearch.Index("scoring-index", score_record)

    EventBridge.PutEvent(
        bus         = "post-discharge-scoring",
        source      = "scoring-service",
        detail_type = "ScoreProduced",
        detail      = score_record
    )

    return score_record
```

**Step 5: Compute the feature vector.** The feature engine reads patient state and trajectory history, and produces the model's input feature vector. The cold-start logic falls back to cohort priors when patient-specific baselines aren't established.

```
FUNCTION compute_features(state):
    features = {}

    // Discharge-time features (snapshot at enrollment).
    features.update(state.discharge_features)
    features["discharge_risk_score"]   = state.discharge_risk_score
    features["days_post_discharge"]    = days_between(state.discharge_at, NOW())
    features["discharge_disposition"]  = state.discharged_to

    // Cohort indicator features.
    FOR each cohort in ALL_COHORTS:
        features[f"cohort_{cohort}"] = cohort in state.cohorts

    // Per-modality trajectory features for each cohort-relevant modality.
    FOR each modality in MONITORED_MODALITIES_FOR(state.cohorts):
        history = Timestream.Query(
            f"""
            SELECT time, measure_value::double
            FROM "post-discharge"."rpm_measurements"
            WHERE patient_id = '{state.patient_id}'
              AND modality = '{modality}'
              AND time BETWEEN ago({TRAJECTORY_WINDOW_DAYS}d) AND now()
            ORDER BY time
            """
        )

        // Latest value, age of latest reading.
        latest = state.latest_values.get(modality)
        features[f"{modality}_current"] = latest.value IF latest else null
        features[f"{modality}_age_hours"] = hours_between(latest.observed_at, NOW()) IF latest else null

        // Trajectory features.
        FOR each window_days in [3, 7, 14]:
            window_values = filter_recent(history, window_days)
            features[f"{modality}_slope_{window_days}d"] = compute_slope(window_values)
            features[f"{modality}_max_{window_days}d"]   = max_of(window_values)
            features[f"{modality}_min_{window_days}d"]   = min_of(window_values)
            features[f"{modality}_count_{window_days}d"] = length(window_values)

        // Patient-specific baseline. Use the first several days of post-discharge
        // data IF available; otherwise fall back to cohort priors.
        patient_baseline_window = filter_recent(history, BASELINE_ESTABLISHMENT_DAYS)
        IF length(patient_baseline_window) >= MIN_BASELINE_OBSERVATIONS:
            features[f"{modality}_baseline"] = trimmed_mean_of(patient_baseline_window)
            features[f"{modality}_baseline_source"] = "patient_specific"
        ELSE:
            features[f"{modality}_baseline"] = cohort_prior_for(state.cohorts, modality).expected_value
            features[f"{modality}_baseline_source"] = "cohort_prior"

        // Deviation from baseline.
        IF features[f"{modality}_current"] is not null:
            features[f"{modality}_delta_from_baseline"] = features[f"{modality}_current"] - features[f"{modality}_baseline"]
            features[f"{modality}_pct_change_from_baseline"] = percent_change(features[f"{modality}_current"], features[f"{modality}_baseline"])

    // Cohort-specific composite features.
    IF "heart_failure" in state.cohorts:
        // The textbook heart failure deterioration signal.
        weight_3d_change = features.get("weight_max_3d", 0) - features.get("weight_min_3d", 0)
        features["hf_weight_3d_increase"] = weight_3d_change
        features["hf_weight_3lb_3d_alert"] = weight_3d_change >= 3       // textbook teaching threshold
        features["hf_dyspnea_score"] = state.latest_pro.responses.get("dyspnea_score") IF state.latest_pro else null

    IF "diabetes" in state.cohorts:
        features["dm_recent_high_glucose"] = recent_max("glucose", days=3, threshold=300)
        features["dm_recent_low_glucose"]   = recent_min("glucose", days=3, threshold=70)

    IF "copd" in state.cohorts:
        features["copd_peak_flow_decline"] = features.get("peak_flow_pct_change_from_baseline", 0) < -20
        features["copd_dyspnea_increase"]   = state.latest_pro.responses.get("dyspnea_score") IF state.latest_pro else null

    // Engagement features.
    features["days_since_last_data"]   = days_between(state.last_data_at, NOW()) IF state.last_data_at else state.days_post_discharge
    features["days_since_last_contact"] = days_between(state.last_contact_at, NOW()) IF state.last_contact_at else state.days_post_discharge
    features["pro_response_rate_7d"]    = compute_response_rate(state.patient_id, days=7)
    features["data_observations_7d"]    = count_observations(state.patient_id, days=7)
    features["engagement_decay"]         = compute_engagement_decay(state.patient_id)

    // EHR-derived features.
    features["ed_visits_since_discharge"]           = count(state.recent_acute_events, type="ed_visit")
    features["external_admissions_since_discharge"] = count(state.recent_acute_events, type="external_admission")
    features["clinic_visits_attended"]               = count_attended_visits(state.patient_id)
    features["clinic_visits_missed"]                  = count_missed_visits(state.patient_id)

    // Medication features.
    new_meds = filter_new_meds_since_discharge(state.medication_events, state.discharge_features.discharge_meds)
    features["new_meds_count"]        = length(new_meds)
    features["high_risk_meds_active"] = any_high_risk_meds(state.medication_events)
    features["missed_refills_count"]  = count(state.medication_events, subtype="refill_missed")

    // Care management interaction features.
    features["outreach_attempts_total"]   = count(state.intervention_history, "outreach_attempted")
    features["successful_contacts_total"] = count(state.intervention_history, "contact_made")
    features["interventions_delivered_total"] = count(state.intervention_history, "intervention_delivered")
    features["last_contact_outcome"]        = state.intervention_history[-1].outcome IF state.intervention_history else null

    // SDOH features (when available).
    sdoh = pull_sdoh_features(state.patient_id)
    features.update(sdoh)

    // Persist the feature vector for online and offline use.
    SageMaker.FeatureStore.PutRecord(
        feature_group = "post-discharge-features-online",
        record = {
            patient_encounter_id: f"{state.patient_id}:{state.encounter_id}",
            event_time:           NOW(),
            **features
        }
    )

    return features
```

**Step 6: Build the explanation layer.** SHAP values plus a Bedrock-generated narrative produce a care-manager-facing explanation. The narrative is decision support; it suggests outreach focus areas without prescribing treatment.

```
FUNCTION build_explanation(score_record, features, state):
    shap_values = SageMaker.Clarify.ExplainPrediction(
        endpoint_name = "post-discharge-anomaly-model",
        input_record  = features
    )

    top_drivers = top_n_by_value(shap_values, n = 5, direction = "positive")

    structured = {
        composite_score:        score_record.composite_calibrated,
        tier:                    score_record.tier,
        top_risk_drivers:        [
            {
                feature:          driver.feature,
                value:            features[driver.feature],
                contribution:     driver.shap_contribution,
                clinical_meaning: humanize_feature_name(driver.feature, features, state.cohorts)
            }
            for driver in top_drivers
        ],
        per_modality_scores:     score_record.per_modality_scores,
        engagement_status:       summarize_engagement(features),
        days_post_discharge:     score_record.days_post_discharge
    }

    // Narrative explanation. Constrained: cite features, suggest outreach focus,
    // never prescribe treatment.
    prompt = build_outreach_explanation_prompt(
        cohort:                  state.cohorts,
        days_post_discharge:     score_record.days_post_discharge,
        composite_tier:           score_record.tier,
        top_drivers:              structured.top_risk_drivers,
        per_modality_scores:     score_record.per_modality_scores,
        engagement_status:        structured.engagement_status,
        recent_interventions:    state.intervention_history[-3:]
    )
    bedrock_response = Bedrock.InvokeModel(
        model_id = "anthropic.claude-XX",       // HIPAA-eligible; select per current eligibility
        body     = { prompt: prompt, max_tokens: 500, temperature: 0.0 }
    )
    narrative = parse_bedrock_response(bedrock_response)

    return {
        structured:           structured,
        narrative:            narrative,
        suggested_outreach:   suggested_outreach_for(state.cohorts, structured.top_risk_drivers, structured.engagement_status),
        generated_at:         NOW(),
        bedrock_model_version: "claude-XX"
    }
```

**Step 7: Build and publish the worklist.** The worklist builder ranks patients by composite tier, applies suppression and de-duplication, and routes the result to the care management UI back end.

```
FUNCTION build_worklist(date):
    // Pull all scores produced in the last scoring run.
    scores = DynamoDB.Query(
        table         = "scoring-history",
        index         = "scored_at-index",
        key_condition = "scored_at >= :start AND scored_at < :end",
        values        = { ":start": start_of(date), ":end": start_of(date + 1) }
    )

    // For each patient, take the latest score from this run.
    latest_per_patient = group_by_patient_latest(scores)

    rows = []
    FOR each score in latest_per_patient:
        state = DynamoDB.GetItem(table = "patient-state", key = score.patient_key)

        // Suppression: patients in active high-touch intervention; patients
        // who graduated; patients we've contacted in the last suppression window.
        IF check_suppression(state, score).suppressed:
            log_suppressed_row(state, score)
            continue

        explanation = build_explanation(score, fetch_features(score.feature_snapshot_id), state)

        row = {
            patient_id:              score.patient_id,
            encounter_id:            score.encounter_id,
            cohort:                   state.cohorts,
            tier:                     score.tier,
            composite_score:          score.composite_calibrated,
            top_drivers:              explanation.structured.top_risk_drivers,
            narrative:                explanation.narrative,
            suggested_outreach:       explanation.suggested_outreach,
            days_post_discharge:      score.days_post_discharge,
            last_contact_at:          state.last_contact_at,
            last_data_at:             state.last_data_at,
            assigned_care_team:       state.assigned_care_team,
            scoring_record_id:        score.score_id
        }
        rows.append(row)

    // Sort by tier and composite score within tier.
    sorted_rows = sort_by_tier_then_score_desc(rows)

    // Apply program capacity caps. The top of the list goes to the
    // highest-touch teams; lower-tier rows go to broader outreach.
    capped_rows = apply_capacity_caps(sorted_rows, current_capacity())

    // Persist worklist for the day.
    worklist = {
        worklist_id:            generate_worklist_id(date),
        date:                    date,
        generated_at:            NOW(),
        rows:                    capped_rows,
        total_active_patients:   length(latest_per_patient),
        total_surfaced:           length(capped_rows)
    }
    DynamoDB.PutItem(table = "worklist-state", item = worklist)
    OpenSearch.Index("worklist-index", worklist)

    EventBridge.PutEvent(
        bus         = "post-discharge-events",
        source      = "worklist-builder",
        detail_type = "WorklistGenerated",
        detail      = { worklist_id: worklist.worklist_id, date: date, total_surfaced: worklist.total_surfaced }
    )

    return worklist

FUNCTION check_suppression(state, score):
    // Patients in observation status / readmitted: pause monitoring, the
    // inpatient team has them now.
    IF state.is_currently_inpatient:
        return { suppressed: true, reason: "patient_currently_inpatient" }

    // Patients within the cool-down window after a successful intervention.
    IF state.last_contact_at AND (NOW() - state.last_contact_at) < SUPPRESSION_AFTER_INTERVENTION:
        IF state.intervention_history[-1].outcome == "intervention_delivered":
            // Don't double-surface; the team is already on it.
            return { suppressed: true, reason: "recent_successful_intervention" }

    // Patients whose program window has ended.
    IF NOW() > state.program_end_at:
        return { suppressed: true, reason: "program_window_ended" }

    // Explicit hold (e.g., patient on hospice; explicit opt-out).
    IF state.has_active_program_hold:
        return { suppressed: true, reason: state.program_hold_reason }

    return { suppressed: false }
```

**Step 8: Capture interventions and outcomes.** Care managers act on the worklist; their actions are recorded. Subsequent outcomes (readmission, ED visit, mortality) are linked back to the alerts and interventions for label assembly.

```
FUNCTION on_care_manager_action(action_event):
    state = DynamoDB.GetItem(
        table = "patient-state",
        key   = { patient_id: action_event.patient_id, encounter_id: action_event.encounter_id }
    )

    intervention_record = {
        intervention_id:   generate_intervention_id(),
        patient_id:        action_event.patient_id,
        encounter_id:      action_event.encounter_id,
        worklist_id:       action_event.worklist_id,
        scoring_record_id: action_event.scoring_record_id,
        action_type:       action_event.action_type,           // outreach_attempted, contact_made, intervention_delivered, escalated
        intervention:      action_event.intervention,          // medication_titration, same_day_appointment, home_health_referral, etc.
        contact_outcome:   action_event.contact_outcome,        // connected, voicemail, no_answer, refused, etc.
        notes:              action_event.notes,
        staff_id:          action_event.staff_id,
        occurred_at:       action_event.occurred_at
    }

    // Update state.
    state.last_contact_at = action_event.occurred_at IF action_event.action_type in ["contact_made", "intervention_delivered"]
    state.intervention_history.append(intervention_record)
    DynamoDB.PutItem(table = "patient-state", item = state)

    // Record for audit and analytics.
    DynamoDB.PutItem(table = "intervention-history", item = intervention_record)
    OpenSearch.Index("intervention-index", intervention_record)

    // Link to the worklist row for closing the loop.
    update_worklist_row_status(action_event.worklist_id, action_event.scoring_record_id, intervention_record)

FUNCTION on_outcome_event(outcome_event):
    // outcome_event: { type: readmission | ed_visit | death | program_graduation,
    //                  patient_id, encounter_id, occurred_at, details }

    // Link to recent alerts and interventions for label assembly.
    state = DynamoDB.GetItem(
        table = "patient-state",
        key   = { patient_id: outcome_event.patient_id, encounter_id: outcome_event.encounter_id }
    )
    recent_scores = OpenSearch.Search(
        index = "scoring-index",
        query = {
            patient_id:        outcome_event.patient_id,
            encounter_id:      outcome_event.encounter_id,
            scored_at_gte:     outcome_event.occurred_at - OUTCOME_LINKAGE_WINDOW
        }
    )
    recent_interventions = OpenSearch.Search(
        index = "intervention-index",
        query = {
            patient_id:        outcome_event.patient_id,
            encounter_id:      outcome_event.encounter_id,
            occurred_at_gte:   outcome_event.occurred_at - OUTCOME_LINKAGE_WINDOW
        }
    )

    label_row = {
        patient_id:                outcome_event.patient_id,
        encounter_id:              outcome_event.encounter_id,
        outcome_type:               outcome_event.type,
        occurred_at:                outcome_event.occurred_at,
        days_post_discharge:        days_between(state.discharge_at, outcome_event.occurred_at),
        recent_score_ids:           [s.score_id for s in recent_scores],
        recent_intervention_ids:    [i.intervention_id for i in recent_interventions],
        feature_snapshots:          [s.feature_snapshot_id for s in recent_scores],
        cohort:                     state.cohorts,
        details:                    outcome_event.details
    }
    S3.PutObject(
        bucket = "post-discharge-training-labels",
        key    = f"outcomes/year={year(outcome_event.occurred_at)}/month={month(outcome_event.occurred_at)}/{generate_id()}.json",
        body   = label_row
    )

    // For readmissions, close the program window for this encounter.
    IF outcome_event.type == "readmission":
        state.is_active = false
        state.program_end_reason = "readmission"
        state.program_end_at = outcome_event.occurred_at
        DynamoDB.PutItem(table = "patient-state", item = state)
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter03.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

<!-- TODO (TechWriter): Expert review V1 (LOW). Sample timestamps and identifiers below (e.g., WL-2026-05-14, SCORE-2026-05-14-039218, INT-2026-05-14-008811, 2026-05-14T10:24:00Z) reflect the draft date and will read as backdated as the book ages. Either replace with placeholder patterns or keep with this disclaimer. Production output uses real ISO-8601 timestamps from the worklist-builder invocation time and UUID-style IDs from the scoring service. -->

<!-- TODO (TechWriter): Expert review V4 (LOW). The expert reviewer flagged the sample narrative phrase "a diuretic adjustment per standing orders" as sitting at the constraint boundary between "suggest outreach focus" and "prescribe treatment." Some clinical-governance committees prefer narratives that stop at outreach-focus suggestions and let the protocol-and-clinician chain handle the titration decision. Consider tightening to "connect with the cardiology transitions clinic for same-day clinical assessment per local heart-failure protocol" or similar. The exact phrasing is a clinical-governance decision; the LLM constraints are tuned per institution. -->

**Sample worklist row (high-tier, day 4 post-discharge, heart failure cohort):**

```json
{
  "worklist_id": "WL-2026-05-14",
  "patient_id": "PT-7724983",
  "encounter_id": "ENC-2026-04472",
  "cohort": ["heart_failure"],
  "tier": "tier_1",
  "composite_score": 0.78,
  "days_post_discharge": 4,
  "top_drivers": [
    {
      "feature": "weight_slope_3d",
      "value": 1.05,
      "contribution": 0.22,
      "clinical_meaning": "Weight has trended up ~1 lb/day for the last 3 days (198 → 199 → 201 → 204)"
    },
    {
      "feature": "hf_weight_3lb_3d_alert",
      "value": true,
      "contribution": 0.18,
      "clinical_meaning": "Cumulative weight increase exceeds the 3-lb-in-3-days teaching threshold (6 lbs since discharge)"
    },
    {
      "feature": "pro_response_rate_7d",
      "value": 0.58,
      "contribution": 0.10,
      "clinical_meaning": "Symptom check-in response rate has dropped from baseline (~85%) to 58% over the last 3 days"
    },
    {
      "feature": "days_since_last_contact",
      "value": 4,
      "contribution": 0.07,
      "clinical_meaning": "Last care management contact was on the day of discharge; no follow-up touchpoint yet"
    },
    {
      "feature": "discharge_risk_score",
      "value": 0.62,
      "contribution": 0.06,
      "clinical_meaning": "Discharge-time readmission risk score was elevated (62nd percentile in cohort)"
    }
  ],
  "narrative": "Patient is 4 days post-discharge from a heart failure exacerbation. Weight has trended up about 1 lb per day over the last 3 days (198 to 204; cumulative 6 lbs above the discharge dry weight). Symptom check-in response rate has dropped from a baseline near 85% to about 58%, suggesting the patient may be feeling worse or less engaged. No care management contact has occurred since the day of discharge. Suggested outreach: confirm the weight trend, ask about dyspnea on exertion and orthopnea, ask about diuretic adherence and any recent changes (skipped doses, side effects), ask about diet over the weekend, and consider a same-day add-on with the cardiology transitions clinic or a diuretic adjustment per standing orders.",
  "suggested_outreach": {
    "primary_focus": "weight_trend_with_engagement_drop",
    "key_questions": [
      "Are you taking your diuretic every morning as prescribed?",
      "Have you been more short of breath, especially walking or lying flat?",
      "How many pillows are you sleeping on?",
      "Any swelling in your ankles or legs?",
      "How's your appetite, and any salty meals over the weekend?"
    ],
    "intervention_options": [
      {
        "intervention": "diuretic_titration_per_standing_orders",
        "applicability": "if_pharmacy_protocol_in_place"
      },
      {
        "intervention": "same_day_transitions_clinic_add_on",
        "applicability": "if_capacity_today"
      },
      {
        "intervention": "home_health_visit_request",
        "applicability": "if_eligible"
      }
    ],
    "escalation_to_provider": "Suggest provider review if weight trajectory continues despite intervention or if patient reports dyspnea at rest."
  },
  "audit_trail": {
    "scoring_record_id": "SCORE-2026-05-14-039218",
    "feature_snapshot_id": "FEAT-2026-05-14-019283",
    "model_version": "post-discharge-anomaly-v2.4",
    "calibration_version": "calib-v2.4-2026-04",
    "cohort_thresholds_version": "thresh-HF-2026-04"
  }
}
```

**Sample intervention capture record (after the call):**

```json
{
  "intervention_id": "INT-2026-05-14-008811",
  "worklist_id": "WL-2026-05-14",
  "scoring_record_id": "SCORE-2026-05-14-039218",
  "patient_id": "PT-7724983",
  "encounter_id": "ENC-2026-04472",
  "action_type": "intervention_delivered",
  "occurred_at": "2026-05-14T10:24:00Z",
  "staff_id": "RN-49283",
  "intervention": "diuretic_titration",
  "intervention_details": {
    "protocol": "HF-transitions-diuretic-titration-2025-v3",
    "previous_dose": "Furosemide 40 mg PO daily",
    "new_dose": "Furosemide 60 mg PO daily x 3 days, then re-evaluate",
    "labs_drawn": ["BMP_in_48h"],
    "follow_up_call": "Tomorrow morning"
  },
  "contact_outcome": "connected",
  "patient_response": "Patient confirmed weight 204 this morning, dyspnea on exertion increased from baseline, orthopnea improved with extra pillow. Endorsed diuretic adherence. Restaurant meal Saturday night high-sodium. Agreed to titration plan.",
  "notes": "Daughter present, helping with logistics. Discussed teaching points: avoid restaurant meals; weigh daily before breakfast; call back if up another 2 lbs by tomorrow.",
  "next_steps": [
    "Follow-up call tomorrow morning",
    "BMP in 48 hours",
    "Re-score Saturday morning"
  ]
}
```

**Performance benchmarks (illustrative ranges from typical published readmission-program performance; specific figures vary substantially by population, outcome definition, program design, and data availability. Measure against your own data before clinical deployment.):**

| Metric | Discharge-time risk only | + Per-modality control charts | + GBT composite (engineered features) | + Engagement and SDOH features | LSTM / time-series model |
|--------|--------------------------|--------------------------------|----------------------------------------|---------------------------------|---------------------------|
| AUROC for 30-day all-cause readmission | 0.62-0.68 | 0.66-0.72 | 0.70-0.78 | 0.72-0.80 | 0.73-0.81 |
| AUROC for 7-day readmission | 0.65-0.70 | 0.70-0.76 | 0.74-0.82 | 0.76-0.83 | 0.77-0.84 |
| PRAUC at typical base rate | 0.15-0.22 | 0.18-0.27 | 0.22-0.32 | 0.24-0.34 | 0.25-0.35 |
| Calibration (ECE) | varies | 0.03-0.06 | 0.02-0.05 | 0.02-0.05 | 0.03-0.06 |
| Top-decile capture (% of readmissions in top 10% scored) | 25-35% | 30-40% | 35-50% | 40-55% | 40-55% |
| Worklist size per care manager per day (typical operational target) | n/a | n/a | 15-30 | 15-30 | 15-30 |
| Successful contact rate (workflow KPI) | n/a | n/a | 50-75% | 50-75% | 50-75% |
| Intervention rate (workflow KPI) | n/a | n/a | 30-55% | 30-55% | 30-55% |
| Subgroup AUROC range across protected categories | ±0.04-0.08 | ±0.04-0.07 | ±0.03-0.06 | ±0.03-0.06 | ±0.04-0.08 |
| End-to-end latency (event ingest to worklist update) | n/a | <30 minutes for daily run; <15 minutes for event-driven rescoring | same | same | same |

<!-- TODO (TechWriter): Expert review V2 (LOW). Benchmark ranges are directional from typical published readmission model performance and post-discharge program performance. Specific figures vary substantially by population, outcome definition, intervention model, and data sources available. The published literature on LACE, LACE+, HOSPITAL, the Epic readmission model, and various commercial models reports AUROC in the 0.6-0.75 range for all-cause 30-day readmission; programs that add post-discharge data and intervention capture report higher values. Replace with measured numbers from local validation before clinical deployment. -->

**Where it struggles:**

- **Cold-start patients.** Patients in their first 1-3 post-discharge days have minimal trajectory data; the model relies on discharge-time features and cohort priors. Performance is materially worse during this window. Many programs accept this and rely on uniform high-touch outreach for high-risk discharges in the first 72 hours.
- **Non-engaged patients.** Patients who don't use the patient portal, don't take RPM measurements, and don't respond to check-ins generate minimal data. The model can flag the engagement decay, but cannot characterize the underlying clinical state. These patients often need direct outreach by phone or home visit, not pipeline-driven monitoring.
- **Devices that fail silently.** A Bluetooth scale that stops syncing because the battery died produces "missing data" that looks like patient disengagement. Differentiating device failure from patient disengagement requires device-health telemetry from the device vendor, which not all vendors provide reliably.
- **External-facility readmissions.** Without HIE or claims data, readmissions to other hospitals are invisible. A model evaluating "did the patient come back to us" has a biased outcome label and a biased intervention target.
- **Equity gaps in data availability.** SDOH data, digital engagement data, and even basic RPM data availability vary across socioeconomic and demographic groups. Models trained on the data-rich subset can perform meaningfully worse on the data-poor subset, exactly the population that often has the highest clinical risk.
- **Treatment-effect-on-prediction issues.** A patient who got an intervention and didn't deteriorate teaches the model that the patient wasn't going to deteriorate. The model under-predicts risk for the subset of patients who would have deteriorated absent the intervention, which is the subset the model is supposed to be identifying.
- **Population shift over time.** Discharge practices change, RPM device adoption changes, the ACO/value-based-care landscape changes payer mix and incentives, all of which produce drift. Quarterly retraining with prospective validation is the operational baseline.
- **Workflow capacity drift.** A model calibrated to surface 25 patients per care manager per day produces a different operational reality when the team is short-staffed and can only get to 15. Threshold tuning has to track team capacity.
- **Intervention attribution.** The same patient often gets multiple touchpoints (a transitions nurse call on day 2, a pharmacist call on day 4, a clinic visit on day 7). Attributing the "did not readmit" outcome to a specific intervention is a hard causal inference problem.

---

## Why This Isn't Production-Ready

The pseudocode shows the shape. A production post-discharge program closes several gaps the recipe leaves intentionally light.

**Care management governance is the program.** Same lesson as Recipe 3.7. The detection pipeline is maybe 30% of the work; the workflow design, the protocols, the equity considerations, the staffing model, and the ongoing performance review are the other 70%. A pipeline without an active governance committee that owns the program design and meets monthly to review outcomes will not produce sustained results. Build the governance before the technology.

**Discharge-time risk scoring as a separate prerequisite.** This recipe assumes a discharge-time risk score exists (Chapter 7 territory). If your organization doesn't have one, building one is a separate prerequisite project, often taking months. Without it, the cold-start tier assignment is more uniform than it should be, which means more high-touch outreach to patients who don't need it and less to patients who do.

**RPM device program as a separate prerequisite.** Enrollment, device shipping, patient education, troubleshooting, device replacement, and reimbursement (RPM CPT codes 99453, 99454, 99457, 99458 in the US, with documentation requirements) are their own program. The infrastructure described here consumes RPM data; it doesn't establish the device program. Plan for a 6-12 month device program rollout in parallel with the technical work, or partner with an RPM-services vendor that handles enrollment and logistics.

**Outreach staffing is the binding constraint.** Most programs assume care manager-to-patient ratios in the 1:50 to 1:200 range depending on intensity. The model's effective output is bounded by the team's capacity. Operationalizing the program requires staffing models that match the projected worklist volume, which often means hiring (or contracting) before the program goes live. Underfunded programs produce unworked worklists; unworked worklists produce no outcome benefit; no outcome benefit kills the program.

**Local validation against the program goal, not just AUROC.** "AUROC of 0.78" tells leadership nothing useful. "Top-decile capture of 47%, with 38% of those patients receiving an intervention and a measured 18% absolute reduction in 30-day readmission rate among intervened patients vs. matched controls" tells leadership whether the program is working. The validation framework should match the operational metrics, not the model metrics.

**Causal evaluation is hard and necessary.** Interventions affect outcomes, which makes naive before-after comparisons unreliable. Acceptable evaluation approaches: matched-cohort analysis, target trial emulation, propensity-score weighting, stepped-wedge cluster designs, and (when feasible) randomized intervention allocation. The cleanest approach is randomized assignment to intervention vs. usual care during program ramp; this is increasingly common in research-affiliated programs and provides defensible evidence for executive review.

**Equity audit framework.** Same operational checklist as Recipe 3.7, with extra attention to digital-engagement bias. Subgroup performance monitoring across age bands, sex, race and ethnicity (where structurally captured), language, insurance status, neighborhood-level SES (Area Deprivation Index, social vulnerability index), and dual-eligibility status. The mitigation strategy must be picked deliberately because the wrong mitigation can amplify existing disparities. Consider explicitly weighting prioritization toward higher-social-vulnerability patients to counter both data and outcome biases; this is a policy decision that should be made consciously and documented.

**HIE and claims integration is a regional problem.** The TEFCA framework and CommonWell and Carequality interoperability networks are improving the situation, but it's still the case that regional HIE coverage varies enormously, and many programs have to build region-specific integrations. For ACO/risk-bearing arrangements, near-real-time claims feeds from CMS and commercial payers are available but require contract-specific data-sharing agreements. <!-- TODO (TechWriter): verify the current state of TEFCA implementation, CommonWell-Carequality unification, and the practical availability of near-real-time HIE feeds nationally. -->

**Care management workflow tool integration.** Salesforce Health Cloud, Epic Healthy Planet, Innovaccer, Lumeris, ZeOmega Jiva, Lightbeam, and various custom-built tools are the typical landing places for the worklist. Each has its own API patterns, data models, and configuration constraints. Plan for substantial integration engineering. Some programs choose to build a thin care-manager-facing UI directly on AppSync rather than integrate with an existing CMS platform; this is reasonable when the existing platform can't accommodate the data model but is its own significant build.

**Patient-facing communication channels.** SMS, IVR, app push notifications, secure portal messages, and email all have different reach, response rates, and PHI-handling considerations. Programs serving older populations often find IVR (automated phone calls) outperforms SMS. Programs serving working-age populations often find SMS outperforms IVR. Multi-channel programs that adapt to patient preference outperform single-channel programs. The infrastructure choices matter; HIPAA-eligible vendors are required.

**FDA regulatory determination.** Most post-discharge anomaly detection systems are workflow tools that surface clinical concerns for human review and qualify for the 21st Century Cures Act CDS exemption. Higher-autonomy variants (closed-loop diuretic titration via standing orders triggered automatically by the model, for example) move closer to FDA medical device territory. Get the regulatory determination in writing before deployment.

**Documentation and reimbursement.** RPM and chronic care management have specific CPT codes with specific documentation requirements (time spent, qualifying conditions, signed consents). The infrastructure should produce documentation that supports the billing requirements. This is operationally important; programs that don't capture RPM-billable activity correctly leave revenue on the table that often funds the program.

**Decommissioning criteria.** Same operational rule as Recipe 3.7. Pre-approved criteria for when the program (or specific cohorts within it) gets paused or decommissioned. Without pre-approved criteria, decommissioning becomes a political conversation; with them, it's a clinical-safety decision driven by data.

**Multi-tenant and multi-cohort considerations.** A real program serves multiple cohorts (heart failure, COPD, post-op cardiac, post-op orthopedic, diabetes, etc.) with different metrics, different baselines, and different intervention protocols. The architecture has to support cohort-specific scoring, cohort-specific calibration, cohort-specific worklists, and cohort-specific governance. Single-cohort programs that grow organically often hit a wall when they try to add a second cohort; designing for multi-cohort from the start is easier than retrofitting.

**Disaster recovery and continuity.** Post-discharge programs are less time-critical than inpatient deterioration, but they're still operationally important. Multi-AZ deployment is the minimum. The fallback is the existing transitions program (manual call lists from discharge planners), which the team needs to know how to activate when the system is down.

---

## The Honest Take

The model is the small part. Same lesson as Recipe 3.7, said again because it's the lesson that bites every team. In post-discharge programs, the workflow piece is even more important, because the intervention capacity is more constrained and the intervention specifics matter more than they do for inpatient deterioration. A great model with a 25-patient daily worklist that nobody works has zero value. A simple control-chart system with a small worklist that the care management team works religiously, and that has good intervention protocols and tight feedback loops, has substantial value. Build the workflow first. Build the model into it second. (The Basic tier in the Estimated Implementation Time table reflects exactly this discipline: a control-chart-only deployment with full workflow and governance in 4-8 months, before the gradient-boosted composite model enters the picture.)

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

Lives are saved here too, just less dramatically than in Recipe 3.7. The signal is slower and the impact is harder to attribute, but the published evidence on transitions-of-care interventions is genuine. The Coleman Care Transitions Intervention, Naylor's Transitional Care Model, the Project RED protocol, and various integrated RPM programs have all shown reductions in 30-day readmission rates in randomized or quasi-experimental studies. <!-- TODO (TechWriter): verify the specific citations and effect sizes for Coleman, Naylor, Project RED, and key RPM trials; the literature is rich and the specifics matter for honest claims. --> The work is hard, but it's worth doing. Just go in with eyes open about what "doing it" actually requires: the workflow, the staffing, the governance, the equity considerations, and the ongoing operational discipline.

---

## Variations and Extensions

The variations are listed in roughly the order most programs add them. Heart-failure-specific is the typical pilot for the reasons named in The Honest Take. COPD often follows because it shares the daily-monitoring cadence and self-management-protocol structure. Post-operative variations grow naturally from cardiac and orthopedic surgery service lines. Diabetes, maternal-infant, and behavioral health are typically later additions because their data structures and intervention protocols differ substantially from the cardiopulmonary core.

**Heart-failure-specific programs.** The single highest-value cohort. Heart failure has clear self-monitoring metrics (daily weight, dyspnea, edema), well-developed clinical protocols (diuretic titration, GDMT optimization), HRRP financial pressure, and substantial published evidence for transitions-of-care interventions. A heart-failure-specific program is often the right pilot.

**COPD-specific programs.** Peak flow tracking, dyspnea check-ins, action plans for exacerbations, smoking cessation support. Different metrics, different intervention palette, less well-developed RPM device ecosystem than heart failure. Often the second cohort added after heart failure.

**Post-operative programs.** Surgical site monitoring (photo upload from the patient), pain trajectory tracking, mobility milestones (steps from wearables), wound complication detection. Different feature engineering. Often a focus for orthopedic and cardiac surgery programs where the discharge transition is well-defined.

**Diabetes-specific programs.** Continuous glucose monitor data is the highest-cadence input in healthcare; the volume and feature engineering are different from intermittent measurements. Programs target post-acute-event patients (DKA, severe hypoglycemia) or newly-diagnosed patients in the first 30-90 days post-diagnosis.

**Maternal-infant transitions.** Post-partum monitoring for maternal health (blood pressure for postpartum hypertension and pre-eclampsia, mood scores for postpartum depression, breastfeeding tracking), and infant well-being monitoring. Different cohort dynamics; substantial public-health relevance for maternal mortality reduction.

**Behavioral health transitions.** Post-psychiatric-hospitalization monitoring with ecological momentary assessment, medication adherence tracking, social support engagement. Different infrastructure (no RPM devices in the typical sense; PRO and engagement signals dominate). Substantial unmet need; growing program area.

**Multi-condition longitudinal programs.** Beyond the 30-day window into ongoing chronic disease management. Many of the same architectural patterns extend, but the time scale shifts from weeks to years and the intervention model shifts from acute outreach to ongoing relationship.

**Pediatric and adolescent programs.** Age-specific normal ranges, caregiver-reported data as the primary input, adolescent privacy considerations. Specialized programs in pediatric centers; substantially different feature engineering.

**Caregiver-focused programs.** Especially for elderly patients with cognitive impairment. The caregiver is the actual user of the patient-facing app, the actual logger of weights, the actual receiver of education. Programs that explicitly support caregivers as a co-equal end user (separate caregiver app, caregiver-facing communication channels, caregiver burden monitoring) outperform programs that treat the caregiver as an incidental conduit.

**LLM-enhanced outreach script generation.** Beyond per-alert narratives, LLMs can generate personalized outreach scripts that incorporate the patient's specific situation (recent device data, recent symptoms, recent interventions, language preference). Care manager time savings can be substantial; the scripts must be reviewed and edited, not used verbatim.

**LLM-enhanced post-discharge documentation.** Care management notes, transitions summaries, hand-off documents for primary care. LLMs draft from structured data; clinicians review and edit. Reduces documentation burden significantly when integrated well.

**Conversational AI patient check-ins.** SMS or IVR-based check-ins delivered by an LLM-driven conversational agent rather than fixed scripts. Higher response rates and richer data; more guardrail engineering required (the agent must not give medical advice). Emerging in 2026; deployment is rare but growing. <!-- TODO (TechWriter): cite specific LLM-driven patient communication studies and vendors when the literature stabilizes. -->

**Federated learning across hospitals.** Joint training on multi-site data without raw data sharing. Addresses single-site population limitations and supports model generalization. Technically and governance-heavy; emerging in academic consortia.

**Patient-facing transparency and shared decision-making.** Some programs are starting to share the risk score and the trajectory data with patients (and caregivers) directly through the patient-facing app. The case for: patients with their own data engage more, ask better questions, and take more ownership of self-management. The case against: patients who see "high risk" labels can become anxious in counterproductive ways, and the disclosure raises informed-consent considerations. Some programs split the difference with structured "your trajectory is going well" or "let's connect with your care manager" messaging that doesn't expose the underlying score. Worth designing into the program intentionally.

**Closed-loop interventions in narrow scenarios.** Standing-order diuretic titration triggered automatically by the model in heart failure cohorts under specific conditions (within bounds, with safety features, with documented clinician oversight). Higher regulatory bar. Usually worth doing only in mature programs with strong governance.

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

## Additional Resources

**AWS Documentation:**
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [Amazon Timestream Developer Guide](https://docs.aws.amazon.com/timestream/latest/developerguide/what-is-timestream.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Feature Store](https://docs.aws.amazon.com/sagemaker/latest/dg/feature-store.html)
- [Amazon SageMaker Clarify](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-configure-processing-jobs.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS AppSync Developer Guide](https://docs.aws.amazon.com/appsync/latest/devguide/welcome.html)
- [Amazon OpenSearch Service Developer Guide](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/what-is.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Time-series modeling, XGBoost on tabular features, Feature Store examples, Model Monitor, and Clarify SHAP examples that apply to the scoring layer.
- [`aws-samples`](https://github.com/aws-samples): search for "FHIR," "HealthLake," "remote patient monitoring," "care management," and "real-time scoring" for adjacent integration patterns.
<!-- TODO (TechWriter): verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating remote patient monitoring, post-discharge anomaly detection, transitions of care, or care management automation on AWS. Adjacent examples exist; a direct match has not been confirmed at the time of writing. -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter by AI/ML + Healthcare): healthcare ML reference architectures.
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search for "readmission," "remote patient monitoring," "care management," and "transitions of care" for architectural deep-dives.
- [AWS Industries Blog (Healthcare)](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AWS architectures and customer stories including post-discharge programs.
<!-- TODO (TechWriter): verify and add specific AWS blog posts on remote patient monitoring, readmission reduction, or care management automation on AWS; confirm URLs exist before inclusion. -->

**Clinical and Research References:**
- [CMS Hospital Readmissions Reduction Program (HRRP)](https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/AcuteInpatientPPS/Readmissions-Reduction-Program): the regulatory framework that drove much of the readmission-reduction investment in the United States.
- [CMS Methodology for HRRP Payment Adjustment](https://qualitynet.cms.gov/inpatient/hrrp): the specific measure specifications and methodology details.
- [AHRQ: Re-Engineered Discharge (Project RED)](https://www.ahrq.gov/patient-safety/settings/hospital/red/index.html): widely-cited transitions-of-care intervention bundle.
- [The Care Transitions Program (Coleman)](https://caretransitions.health/): the Coleman Care Transitions Intervention.
- [Transitional Care Model (Naylor)](https://www.transitionalcare.info/): the Naylor Transitional Care Model, RN-led transitions-of-care intervention.
- [BOOST (Better Outcomes for Older adults through Safe Transitions)](https://www.hospitalmedicine.org/clinical-topics/care-transitions/): SHM's transitions-of-care toolkit.
- [LACE Index for Readmission Risk](https://en.wikipedia.org/wiki/LACE_index): a widely-used discharge-time readmission risk score.
- [HOSPITAL Score for Readmission Risk](https://pubmed.ncbi.nlm.nih.gov/24166084/): another well-validated discharge-time readmission risk score.
<!-- TODO (TechWriter): verify the LACE and HOSPITAL canonical citations and update if better URL anchors exist. -->
- [MIMIC-IV Clinical Database (PhysioNet)](https://physionet.org/content/mimiciv/): research dataset including discharge events and readmission labels.
- [Synthea](https://github.com/synthetichealth/synthea): synthetic patient data generator including discharge and readmission events.

**Regulatory and Reimbursement References:**
- [FDA Clinical Decision Support Software Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): FDA guidance on what CDS software requires clearance vs. is exempt.
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): SaMD framework for clinical software.
- [21st Century Cures Act, Section 3060](https://www.congress.gov/bill/114th-congress/house-bill/34): legislative basis for the CDS exemption.
- [CMS Remote Physiologic Monitoring (RPM) CPT Code Guidance](https://www.cms.gov/Medicare/Medicare-Fee-for-Service-Payment/PhysicianFeeSched/PFS-Federal-Regulation-Notices): annual physician fee schedule includes RPM coverage and code updates.
- [HHS ONC TEFCA](https://www.healthit.gov/topic/interoperability/policy/trusted-exchange-framework-and-common-agreement-tefca): the federal interoperability framework expanding HIE coverage.

**Equity and SDOH References:**
- [PRAPARE (Protocol for Responding to and Assessing Patient Assets, Risks, and Experiences)](https://prapare.org/): SDOH screening tool widely used in primary care and transitions programs.
- [CMS Accountable Health Communities Health-Related Social Needs (AHC HRSN) Screening Tool](https://www.cms.gov/priorities/innovation/files/worksheets/ahcm-screeningtool.pdf): another widely-used SDOH screening tool.
- [Area Deprivation Index](https://www.neighborhoodatlas.medicine.wisc.edu/): neighborhood-level SES proxy used in many post-discharge programs.
- [Social Vulnerability Index (CDC)](https://www.atsdr.cdc.gov/placeandhealth/svi/index.html): another neighborhood-level proxy capturing multiple SDOH dimensions.

**Academic Literature (Conceptual Foundations):**
<!-- TODO (TechWriter): Add specific peer-reviewed citations for:
  - LACE index development and validation: van Walraven C, et al.
  - HOSPITAL score: Donzé J, et al.
  - Coleman CTI: Coleman EA, et al. (2006). The Care Transitions Intervention. Arch Intern Med.
  - Naylor TCM: Naylor MD, et al.
  - Project RED: Jack BW, et al. (2009). A reengineered hospital discharge program. Ann Intern Med.
  - Telemonitoring trials in heart failure: Inglis SC, et al. (Cochrane); various RCTs.
  - HRRP impact studies: Wadhera RK, et al.
  Verify exact citations and DOIs before publication. -->
- [SHAP (SHapley Additive exPlanations)](https://github.com/shap/shap): per-prediction explanation library.
- [Statistical Process Control (Wikipedia)](https://en.wikipedia.org/wiki/Statistical_process_control): CUSUM, EWMA, and control chart background for trajectory monitoring.

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single cohort (heart failure), Bluetooth scale RPM only, weekly PRO check-ins, simple control-chart anomaly detection, manual care manager worklist, basic dashboard, retrospective comparison against existing transitions program | 4-8 months |
| Production-ready | Two to three cohorts, multi-modality RPM (scale, BP cuff), daily PRO check-ins for high-tier patients, gradient-boosted composite scoring with engineered features, calibrated outputs with subgroup-stratified thresholds, integrated worklist UI with explanation narratives, intervention capture with closed feedback loop, EHR integration for ED visits and clinic visits, full care management governance committee operating, subgroup performance monitoring, retraining pipeline, randomized or matched-cohort effectiveness evaluation | 12-18 months |
| With variations | Additional cohorts (post-op, diabetes, COPD, behavioral health), HIE integration for external readmissions, claims feed integration for ACO contexts, LLM-driven outreach script generation, conversational AI patient check-ins, time-series LSTM or transformer model, federated learning across multiple sites, RPM device program with patient enrollment and logistics, formal HRSN/SDOH screening integration, closed-loop interventions for specific narrow scenarios, pediatric or maternal specializations | 18-36 months beyond production-ready |

---

## Tags

`anomaly-detection` · `readmission-risk` · `post-discharge-monitoring` · `transitions-of-care` · `remote-patient-monitoring` · `rpm` · `patient-reported-outcomes` · `pro` · `heart-failure` · `copd` · `hrrp` · `cms-readmission-program` · `lace` · `hospital-score` · `time-series` · `xgboost` · `lightgbm` · `survival-analysis` · `feature-store` · `clarify` · `model-monitor` · `model-registry` · `bedrock` · `comprehend-medical` · `kinesis` · `timestream` · `dynamodb` · `opensearch` · `eventbridge` · `sagemaker` · `appsync` · `step-functions` · `care-management` · `local-validation` · `subgroup-performance` · `equity` · `sdoh` · `calibration` · `shap` · `engagement-decay` · `cold-start` · `causal-inference` · `fda-cds` · `samd` · `hipaa` · `complex` · `production` · `provider`

---

*← [Recipe 3.7: Patient Deterioration Early Warning](chapter03.07-patient-deterioration-early-warning) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.9 - Cybersecurity / Access Pattern Anomalies →](chapter03.09-cybersecurity-access-pattern-anomalies)*
