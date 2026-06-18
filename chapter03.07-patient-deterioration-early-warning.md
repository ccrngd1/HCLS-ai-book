# Recipe 3.7: Patient Deterioration Early Warning ⭐

**Complexity:** Complex · **Phase:** Production (with clinical governance) · **Estimated Cost:** ~$0.0008 to $0.005 per patient-hour scored (mostly compute and feature joins; vendor models often run as separate licensed costs)

---

## The Problem

It's 3:14 a.m. on a 32-bed medical-surgical floor. Bed 17 is a 67-year-old woman, two days post-op from a colon resection, recovering uneventfully. The night shift charge nurse has eight patients on her side of the unit, the other charge nurse has six, and they're sharing a CNA. Vitals on bed 17 were charted at 11 p.m.: temp 37.8, HR 92, BP 118/72, RR 18, SpO2 96% on room air, mentation appropriate, pain 3/10. A little febrile, mild tachycardia, otherwise unremarkable. The next vitals aren't due until 3 a.m.

At 1:40 a.m., the patient's daughter (who's staying overnight in the chair) presses the call button because Mom is "not making sense." The nurse comes in, the patient is oriented to person but not place, vitals get retaken: temp 38.6, HR 118, BP 92/54, RR 24, SpO2 91% on room air. The hospitalist is paged, sepsis protocol activates, blood cultures and lactate are drawn (lactate comes back at 4.2), the patient gets her first dose of broad-spectrum antibiotics at 2:38 a.m. and is transferred to the ICU at 4:15 a.m. for vasopressors. She survives. Length of stay extends by nine days. Three weeks of inpatient rehab follow.

Now look at the data trail before the daughter pressed the button. Vitals at 11 p.m. were "mostly normal" by any single-threshold rule. But: the heart rate had been climbing for eight hours (78 at 3 p.m., 84 at 7 p.m., 92 at 11 p.m.). The respiratory rate had crept from 14 at 3 p.m. to 18 at 11 p.m. The temperature had risen from 37.1 at 3 p.m. to 37.8 at 11 p.m. The morning labs had a white count of 14.2 and a creatinine that was 0.3 above her baseline. The nursing note from 9 p.m. mentioned "patient appears slightly more somnolent than earlier shift, easily arousable." None of these individual data points crossed a threshold. All of them, together, were the early signature of sepsis.

That's patient deterioration early warning. Not "is this patient critically ill right now?" The hospital's existing critical value rules and rapid response triggers handle the obvious. The harder question is: which patients on the floor right now are showing the early signs of deterioration, hours before they hit any single alarm threshold, so the team can intervene before the call button gets pressed at 1:40 a.m.?

The clinical literature has been making this point for thirty years. Most in-hospital deterioration events (cardiac arrests, ICU transfers, unplanned intubations, unexpected deaths) are preceded by hours of physiologic warning signs that get missed in routine charting. Track-and-trigger systems, originally developed in the UK in the 1990s, encode some of this insight as scoring tools (NEWS, NEWS2, MEWS, PEWS for pediatrics, qSOFA for sepsis screening). They work better than nothing. They miss a lot, and they fire often on patients who don't deteriorate. 

The reason the problem is hard, and the reason it lands at the complex end of this chapter, comes down to a few intertwined pressures.

**Time is asymmetric.** A false negative (missed deterioration) costs hours of delayed treatment, ICU transfer instead of floor management, sometimes death. A false positive (rapid response activation that turns out to be nothing) costs a few minutes of the rapid response team's time and some patient-and-family anxiety. These are not symmetric, but the false positive has a sneakier cost: alert fatigue. A system that fires twenty times per shift on patients who are fine teaches the staff to ignore the alerts, and the one true positive in the middle gets ignored alongside the noise. The cost function is asymmetric in both directions, with a non-linear interaction term, and that's before you start thinking about the operational reality of how the alert actually reaches a human who can act on it.

**Baselines are deeply personal.** A heart rate of 92 in an athlete with a resting baseline of 50 is a bigger deal than the same 92 in an elderly patient on no medications whose baseline runs in the 80s. A blood pressure of 100/60 in a patient whose normal is 160/95 is a bigger deal than the same number in a young woman whose normal is 110/65. Population thresholds throw away information; patient-specific baselines require enough history to establish them and a sensible cold-start strategy when there isn't enough history yet.

**Context is everything.** A respiratory rate of 24 means very different things on a stable medical floor, in a patient who just got a dose of IV opioids, on a step-down unit immediately post-extubation, or in an ED patient who walked in three hours ago. Same number, completely different prognosis. The model has to know where the patient is, what was just done, what's running through their IV right now, what time of day it is, and what their trajectory looks like over the last several hours.

**Multiple deterioration phenotypes look different.** Sepsis presents as warm, tachycardic, hypotensive, with rising lactate. Heart failure decompensation presents as cool, sometimes bradycardic, hypoxic, with rising BNP. Pulmonary embolism presents as tachycardic, tachypneic, often with sudden desaturation, with elevated D-dimer. GI bleeding presents as tachycardic, hypotensive, with falling hemoglobin and hemodynamic responses to bleeding. A single "deterioration score" trying to catch all of these is necessarily generic; phenotype-specific models perform better but multiply the operational complexity.

**Workflow integration is the actual product.** A score number in a chart that nobody looks at is worse than no score: you now have documentation that the deterioration was predictable. The output of the model has to flow into pager systems, clinical communication platforms, the rapid response team workflow, the charge nurse's situational awareness display, and the bedside nurse's task list. Each of those integrations has its own protocols, its own latency tolerances, and its own failure modes. The pipeline is half the system; the workflow is the other half.

**Regulatory and legal exposure is real.** Clinical decision support that influences treatment decisions can fall under FDA medical device regulation as Software as a Medical Device (SaMD) depending on the autonomy level and the clinical scenario. The 21st Century Cures Act and the FDA's CDS guidance carve out specific exemptions, but the boundaries are non-obvious and have shifted over the last few years. Hospital clinical governance committees, biomedical engineering, and risk management all have a stake in the deployment. 

**Bias and equity are first-order concerns.** Deterioration models trained on historical data can encode care disparities (patients who got more attention got more vitals charted, which produced richer feature vectors, which produced better predictions for them). They can encode population-level differences in baseline vitals (heart rate, blood pressure distributions vary across demographics). They can fail silently on subgroups whose deterioration phenotypes are under-represented in training data. Subgroup performance monitoring is not optional and not a one-time validation exercise; it's continuous operational work.

What you actually want to build is a continuously-running scoring service that ingests vitals, labs, medications, and nursing assessments as they're charted, computes a deterioration risk score (or several phenotype-specific scores) for every admitted patient on a frequent cadence, accounts for patient-specific baselines and unit-specific context, surfaces the highest-risk patients to the right humans through the right channels with enough explanation to act on, and feeds outcomes back so the model and the operational thresholds keep improving. Underneath sits a streaming feature pipeline that's robust to missing data (vitals are sometimes hours apart on stable patients), a clinical governance process that's been involved since requirements gathering, and an audit trail that would satisfy the hospital's regulatory affairs team.

Let's get into how.

---

## The Technology

### Track-and-Trigger Systems Are the Starting Point, Not the End

Before getting into machine learning, a first-time builder should internalize the lineage of what's already in use, because the ML systems either replace or augment these and the comparison is the whole conversation.

**MEWS (Modified Early Warning Score)** is the original. Five physiologic parameters (systolic BP, heart rate, respiratory rate, temperature, level of consciousness), each scored 0-3 based on how far from "normal" they are, summed for a single number. Threshold breach (typically MEWS ≥ 5 or any single parameter at 3) triggers an escalation protocol. Easy to compute, easy to chart, well-validated for its era, in use across thousands of hospitals.

**NEWS / NEWS2 (National Early Warning Score)** evolved from MEWS, developed by the Royal College of Physicians in the UK. Adds SpO2, supplemental oxygen, and a more nuanced consciousness score. NEWS2 (the 2017 revision) added separate handling for patients with chronic hypoxic respiratory disease (Type 2 oxygen targets). Better calibrated than MEWS, particularly for sepsis.

**qSOFA (quick Sequential Organ Failure Assessment)** is sepsis-specific. Three criteria (respiratory rate ≥ 22, altered mental status, systolic BP ≤ 100). Two or more positive triggers high suspicion for sepsis. Less sensitive than NEWS2 but more specific for sepsis.

**PEWS (Pediatric Early Warning Score)** is the pediatric counterpart. Different vital sign norms by age, behavior and play assessment, and parental concern as a formal criterion. Multiple variants in use; no single version dominates.

**SIRS (Systemic Inflammatory Response Syndrome)** criteria (HR > 90, RR > 20, temp > 38 or < 36, WBC abnormal). Older than the others, criticized for being non-specific (most post-op patients meet SIRS criteria). Included here because it shows up in sepsis screening logic and hospital protocols still reference it.

These are useful because they're explainable, auditable, and clinicians know what they mean. They're limited because they're additive scoring systems with hand-crafted thresholds, which throws away most of the trajectory information and treats every patient identically. A heart rate of 110 contributes the same score whether the patient's baseline is 60 or 95. A score of 4 from "two parameters slightly off" is treated the same as a 4 from "one parameter way off." The math is intentionally blunt because clinicians have to compute it manually at the bedside; the question is what's available when a computer does the math instead.

### What ML Adds (And Where It Adds Less Than Vendors Suggest)

Machine learning approaches to deterioration prediction generally do three things track-and-trigger systems can't.

**Patient-specific baselines.** Use the patient's own history to define what "normal" means for them, instead of applying population thresholds. This alone reclaims a lot of signal because population thresholds are calibrated for the average patient.

**Trajectory awareness.** Look at the rate of change and the pattern of change, not just the current value. A heart rate that has climbed from 75 to 95 over six hours carries more information than a single heart rate of 95.

**Multivariate fusion.** Combine vitals, labs, medications, demographics, and clinical context into a single risk score. Track-and-trigger systems can do this only by stapling multiple separate scores together; ML models can learn the interactions natively.

What ML does not magically do is replace the underlying clinical reasoning or the operational integration challenges. A model that's marginally better on retrospective AUROC than NEWS2 still has to fire alerts that humans act on, in a workflow that doesn't already overwhelm them, with explanations they trust. The vendor literature talks a lot about model performance and not enough about the workflow problem; the published peer-reviewed literature is more honest about it. 

### The Two Big Vendor Models, And Why You Should Know Their Reputations

Two ML-based deterioration models have meaningful market presence, and any hospital deployment is happening in their shadow. A first-time builder should know what they are and what's been published about them, because procurement conversations and clinical governance reviews will reference them.

**Epic's Deterioration Index (EDI).** Built into Epic, runs natively in the EHR, scores admitted patients periodically. Originally rolled out around 2017-2018, used by many hospital systems, and the subject of substantial published validation work. The 2021 University of Michigan study (Wong et al.) found EDI's performance during COVID-19 was meaningfully worse than vendor-reported figures, particularly on subgroups. Epic has updated the model since. The takeaway from the literature is that vendor-reported performance often doesn't match local-population performance, and that local validation is essential. 

**eCART (Electronic Cardiac Arrest Risk Triage).** Originally developed at the University of Chicago, commercialized through AgileMD. Strong published validation literature, often outperforms NEWS2 in head-to-head studies. Used at a number of academic medical centers. Available as either a vendor service or, in some configurations, a deployable model.

There are also others (PeraHealth's Rothman Index based on nursing assessments; Bernoulli's models; institutional in-house models like the one at Kaiser Permanente). The point is not to cover all of them; the point is that "build your own deterioration model" is a viable path but it's a path that runs alongside several mature commercial alternatives, and the right answer for many hospitals is to deploy a commercial model with strong local validation rather than build from scratch.

That said, building (or at least understanding the architecture of) a deterioration model is valuable even when the production system is vendor-supplied, because the operational integration, the alert workflow, the explainability layer, and the feedback infrastructure all have to be local regardless of where the model lives.

### Statistical and ML Methods That Fit

Deterioration prediction has been a productive ML problem for fifteen years. The methods cluster into a few families.

**Logistic regression with hand-crafted features.** Surprisingly competitive baseline. Features include current vitals, trends over the last several hours, recent labs, medications, demographics, and unit context. Highly interpretable, easy to deploy, easy to explain to clinicians. Often within a few percentage points of more complex models on AUROC and PRAUC. Many published deterioration models are essentially logistic regression with careful feature engineering, including some of the early NEWS-replacement studies.

**Gradient-boosted trees (XGBoost, LightGBM).** The default workhorse for this kind of tabular healthcare prediction problem. Handles missing data gracefully (vitals charts have gaps). Captures non-linear interactions. SHAP values produce per-prediction explanations that clinicians can usually parse. Almost every modern deterioration model uses GBT either as the primary model or as a strong baseline.

**Recurrent neural networks (LSTM, GRU).** Naturally handles the time-series structure of vitals and labs. Can model variable-length sequences, irregular sampling, and trajectory patterns. Stronger than tabular models on rapidly-changing patients but more sensitive to data quality issues. Requires more training data. Less interpretable. Used in some commercial models including Epic EDI.

**Transformer-based time series models.** The current research frontier. Models like Temporal Fusion Transformer, PatchTST, and clinical-time-series-specific architectures (BEHRT, Med-BERT, and various foundation models for clinical time series) are showing strong results on deterioration tasks, but production deployment is still relatively rare as of 2026. Worth watching and worth experimenting with on retrospective data, but probably not the right choice for your first production deployment.

**Survival analysis (time-to-event models).** Cox proportional hazards models and related survival approaches frame deterioration as a time-to-event problem rather than a binary prediction. The output is "expected hours until deterioration" or "probability of deterioration in the next 6 hours conditional on current state," which maps better to clinical action than a binary score. Used in some research deterioration models; less common in production deployments.

**Multi-task learning and phenotype-specific models.** Rather than one generic deterioration score, train models for specific outcomes (sepsis onset, respiratory failure, cardiac arrest, ICU transfer, unexpected death). Often performed jointly so the models share representations. Phenotype-specific scores typically outperform generic scores for the specific phenotype but require more training data per outcome and complicate the alert workflow (which model fires? what does the alert mean?). Common in academic medical centers, less common in community hospitals.

**Ensemble combinations.** A practical pattern: a logistic regression for explainability, a GBT for performance, an LSTM for trajectory awareness, combined with a meta-learner. The combined model often performs slightly better than any single model and gives the explainability layer something to work with. Operationally heavier; worth it when the marginal performance matters clinically.

A reasonable progression: start with a track-and-trigger baseline (NEWS2) running on your data so you have a comparator. Build a feature-engineered logistic regression and a gradient-boosted trees model on retrospective data. Compare against the NEWS2 baseline. Iterate on features, time windows, and outcome definitions. Validate prospectively before any clinical deployment. Add LSTM or transformer layers only if the marginal gain justifies the operational complexity.

### Outcome Definition Is Surprisingly Hard

The data scientist's question "what are we predicting?" sounds straightforward and isn't. The clinical literature has multiple competing outcome definitions, and the choice of outcome shapes what your model learns.

**ICU transfer.** Easy to extract, well-coded, captures something clinically meaningful. Issue: ICU transfer policies vary by hospital, by service, by time of day, and by bed availability. A patient who would have been transferred but wasn't because the ICU was full doesn't show up as a positive case but probably should have. Conversely, an ICU transfer for "we're worried about him, let's watch him in a higher-acuity setting" is a lower-acuity event than one for "he's failing, transfer now." The label is noisy.

**Cardiac arrest, code blue, rapid response activation.** Strong clinical events, well-documented. Lower base rate than ICU transfers, which means harder modeling. Code blues happen at all acuity levels and the precipitating event is sometimes captured (PEA arrest from an underlying physiologic deterioration that was missed) and sometimes not (acute MI, sudden arrhythmia, unexpected event).

**Composite endpoints.** Combine multiple events: ICU transfer, code blue, unexpected death, transfer to step-down unit. Increases the positive case rate, which helps modeling, at the cost of mixing different clinical phenotypes into one outcome.

**Mortality.** Inpatient death or 30-day mortality. Very strong outcome but lagging (the patient's already deteriorated by the time death is the relevant prediction window). Better as a prognostic marker than as an early warning signal.

**Phenotype-specific outcomes.** Sepsis onset (new antibiotics within X hours of new vital sign criteria), respiratory failure (intubation), shock (vasopressor initiation), and so on. More clinically meaningful but each has its own labeling challenges. The Sepsis-3 definition requires retrospective lactate values and SOFA score deltas; the practical implementation in a real hospital usually approximates rather than perfectly recreates Sepsis-3.

**Time-windowed prediction.** Rather than "will this patient deteriorate?" the question becomes "will this patient deteriorate within the next 6 hours / 12 hours / 24 hours?" This is the operationally useful framing because clinical action has a time horizon; predicting deterioration that happens five days later isn't useful for the night shift. The choice of window is a clinical decision driven by how fast the team can intervene; 6-12 hours is common.

The teams that ship working deterioration models almost always use a composite endpoint (ICU transfer, code blue, unexpected death) on a 6-24 hour prediction window, with phenotype-specific stratification done as a secondary analysis after the primary model is in production. Don't try to nail outcome definition perfectly in version one. Pick something defensible, validate it, deploy it, and refine.

### Features That Actually Matter

The feature space is where most of the actual modeling work lives. Some categories of features are universally useful; some are surprisingly important; some are easy to overthink.

**Current vitals.** Heart rate, respiratory rate, blood pressure (systolic, diastolic, mean arterial pressure), temperature, SpO2, supplemental oxygen requirement (FiO2 if available), level of consciousness (Glasgow Coma Scale or AVPU). The starting point.

**Vitals trajectory features.** Slope and acceleration over the last 1, 4, 12, 24 hours. Maximum and minimum values in the last several hours. Variability metrics (standard deviation, coefficient of variation). The trajectory carries more signal than the current value alone for many patients.

**Vitals-derived composites.** Shock index (HR / SBP), pulse pressure (SBP - DBP), MAP, ROX index (SpO2/FiO2/RR for respiratory failure), modified shock index. These hand-crafted composites encode clinical reasoning that pure ML sometimes has to learn from scratch and sometimes never quite does.

**Recent labs.** White count, hemoglobin, platelets, creatinine, BUN, glucose, lactate (when available), bicarbonate, sodium, potassium, troponin (when available), procalcitonin (when ordered), liver function panels, BNP. The labs that are available depend on what was ordered; missing-data handling becomes important.

**Lab trajectory features.** Same idea as vitals: slope of creatinine over recent days, hemoglobin trend, lactate trajectory if drawn serially. Catches subtle organ dysfunction.

**Medications.** Active medication list (antibiotics, vasopressors, sedatives, anticoagulants, insulin, oxygen). Recent administrations (the dose of opioid the patient just got might explain the respiratory rate change). Some medications are markers of clinical concern (a vasopressor was just started) and some are confounders for the vitals (a beta-blocker masks tachycardia).

**Patient context.** Age, sex, weight, BMI. Admission diagnosis, problem list. Surgical status (post-op day if relevant). Code status. Comorbidities. The clinical context conditions everything: a heart rate of 105 in a post-op CABG patient on day one means something different than the same heart rate in a stable medical patient on day six.

**Unit context.** What unit is the patient on (medical floor, surgical floor, telemetry, step-down, ICU). Time of day. Day of the week. Recent transfer activity (just transferred from ICU? just transferred to floor?). Where the patient is physically being cared for shifts the prior probability of deterioration substantially.

**Nursing assessments.** Mental status documentation, pain scores, intake and output, nursing concerns. The "nursing concern" category sometimes shows up as a structured field, sometimes as a free-text note. The Rothman Index famously builds primarily on nursing-recorded data points and outperforms vitals-only models in some studies; the trade-off is that nursing-charted data is more variable and dependent on charting practices.

**Patient-specific baselines.** The patient's own median or trimmed-mean values for each vital and lab over the last 24-72 hours, and the deviation of the current value from that baseline. The single biggest accuracy gain over population thresholds.

**Time since admission.** Day of stay, time since transfer to current unit, time since last vital sign. Patients early in their stay deteriorate from different causes than patients late in their stay; the model has to know.

**Order patterns.** New orders (especially blood cultures, lactate, antibiotics, oxygen titrations) often precede formal deterioration recognition by hours, because the bedside team is acting on suspicion before they call rapid response. The "the team has just ordered a lactate" feature is sometimes one of the highest-importance features in production models.

A useful model has 50-200 features. More is not better; complexity makes drift detection harder, makes feature pipeline maintenance harder, and provides marginal gains beyond a certain point.

### Sampling, Time Windows, and Right-Censoring

Deterioration data is irregularly sampled (vitals every 4 hours on a stable patient, every 15 minutes on an unstable one), heavily right-censored (the patient who didn't deteriorate during their stay is censored at discharge), and contains both event-driven and time-driven sampling biases. These structural properties shape what you can do with the data.

**Time grids.** A common trick: snap the irregular data onto a regular hourly (or 15-minute, or 5-minute) grid. Forward-fill or last-observation-carry-forward for vitals. Roll-forward for labs. The grid makes the time-series structure tractable, but it introduces artifacts because a patient with a missing 4-hour stretch of vitals is now indistinguishable from a patient who's been stable. Some models handle the missingness explicitly (Phased LSTM, irregularly-sampled time series transformers, missingness-as-a-feature); others use the grid and accept the artifacts.

**Prediction windows.** The model asks "given what I know at time T, what's the risk of deterioration in [T, T+6 hours]?" The training data is constructed by taking every prediction-time point T, computing features as of T (no future leakage), and labeling with whether deterioration occurred in the window. Patients contribute multiple training examples (one per prediction time), which has implications for evaluation: independent train/test splits should be at the patient level, not at the time-point level, because correlation across a patient's time points inflates apparent performance.

**Right censoring.** Patients who are discharged before deterioration are not "negative cases" in the absolute sense; they're censored. Survival-style modeling handles this naturally; binary classification sometimes treats them as negatives, which biases toward over-confident "no deterioration" predictions for patients who would have deteriorated if they'd stayed longer. Discharge disposition matters: patients discharged home are likely true negatives; patients discharged to hospice are not.

**Event leakage.** Be very careful about feature engineering that uses post-event data. The vitals charted right before a code blue may include resuscitation interventions; including those vitals as predictors of the code blue produces models that "predict" the code from the resuscitation. Cutting off features at a clinically appropriate lookahead boundary (often 30-60 minutes before the event) is essential.

**Treatment leakage.** A patient who got broad-spectrum antibiotics started at hour 18 of their stay may not deteriorate further because the antibiotics worked. The model that predicts deterioration without knowing antibiotics were started will look like it predicted survival; the model that knows about the antibiotics is at risk of learning "antibiotics → no deterioration" which isn't quite right. This is the fundamental "treatment effect on prediction" problem, and the cleanest mitigations are either restricting the model to features available at decision time only, or framing the problem as causal inference (not what most production deterioration models do).

### Calibration Matters As Much As Discrimination

Most ML model evaluations focus on discrimination (AUROC, PRAUC). For deterioration models, calibration matters as much or more. A clinician who sees a "deterioration risk: 23%" needs to know that, across patients with that score, roughly 23% really do deteriorate. If the score is poorly calibrated (a score of 23% really corresponds to 8% actual deterioration risk, or 45%), the clinician's mental model of "what does this number mean" is wrong, and the operational threshold for action is wrong.

Calibration plots, Brier score, and reliability diagrams should be reported alongside AUROC. Models that discriminate well but calibrate poorly can be recalibrated post-hoc (Platt scaling, isotonic regression). Calibration drift over time is a real production issue: a model calibrated on training data may shift as practice patterns change, and ongoing monitoring of calibration is part of operations.

### Subgroup Performance Is Operations Work, Not a One-Time Audit

Every production deterioration model must monitor performance across clinically meaningful subgroups: age bands, sex, race and ethnicity (where structurally captured), insurance status (a useful proxy for SES), unit, service line, primary diagnosis, time of day, day of week. Models that perform well overall but worse on specific subgroups produce harm patterns that map onto existing care disparities.

Mitigations include subgroup-stratified threshold tuning, subgroup-specific recalibration, fairness-aware training (adversarial debiasing, reweighing), and ongoing audit cycles that flag subgroups whose performance has drifted out of acceptable bounds. The mitigation strategy must be picked deliberately because the wrong mitigation can degrade overall performance without improving the subgroup that motivated it. 

### Alert Fatigue Is a Design Constraint

Every section of this recipe touches alert fatigue, but it deserves its own treatment because it's the single biggest reason deterioration systems fail in production.

The math: a hospital with 300 inpatients running a deterioration score every hour produces 7,200 score evaluations per day. A 95% specific model still produces 360 false positives per day. If the alert threshold turns those into pages, the rapid response team gets a false-positive page every four minutes. They will stop responding to the pages. This is not a model performance problem; it's an alert design problem.

The design implications:

- **Tiered alerting.** Reserve the page for the highest-risk tier. Use lower-tier alerting (charge nurse dashboard, EHR banner, end-of-shift review) for the middle tier. Most of the value of the model is captured in the dashboard tier, not the page tier.
- **Suppression of non-actionable alerts.** A patient already in the ICU getting an "increased deterioration risk" alert is not actionable. A patient with active comfort-care orders getting a "probable deterioration" alert is not actionable. A patient who already had a rapid response activation in the last 4 hours is already being watched. These should be filtered, not just lower-priority.
- **Differential routing.** A "rising sepsis risk" alert routes to the bedside nurse and the hospitalist, not to the rapid response team. A "high probability of imminent ICU transfer" alert routes to the rapid response team and the bed coordinator. Different alert types have different correct destinations.
- **Time-based gating.** An alert that fires for the same patient every hour doesn't tell the team anything new. A "this patient's risk just increased substantially" delta alert is more actionable than a "this patient is high risk" steady-state alert.
- **Acknowledgment and feedback.** Every alert should require an acknowledgment (looked at, dismissed-with-reason, escalated). The acknowledgment data feeds back into model and threshold tuning. Alerts that are routinely dismissed-as-noise indicate threshold or feature problems.
- **Operational threshold tuning.** The decision threshold should be tuned to the operational capacity of the responding team. A hospital with a robust rapid response team can tolerate a lower threshold; a hospital with a limited team needs a higher threshold. This is not a model parameter; it's a deployment parameter, and it varies by site.

The teams that ship working deterioration systems get the workflow design right. The teams that don't, ship technically-correct systems that nobody uses.

---

## General Architecture Pattern

At a conceptual level, the deterioration early warning pipeline ingests vitals, labs, medications, and clinical notes from the EHR continuously, computes features (current values, trajectories, patient-specific baselines), scores every admitted patient on a frequent cadence, and routes the resulting alerts through tiered destinations to the right humans at the right time. Underneath sit the model training pipeline, the calibration and subgroup monitoring infrastructure, the feedback capture for outcomes, and the audit logging required for clinical safety review.

```
┌────────── DETERIORATION EARLY WARNING PIPELINE ──────────────────┐
│                                                                  │
│   [EHR vitals feed]      [Lab results feed]    [Medication      │
│                                                  administration] │
│   [Nursing assessments]  [Order events]        [Admit/transfer  │
│                                                  events]         │
│           │                                                      │
│           ▼                                                      │
│   [Streaming Ingest and Normalization]                           │
│   (clinical event harmonization, unit conversions,               │
│    timestamp reconciliation, deduplication)                      │
│           │                                                      │
│           ▼                                                      │
│   [Patient State Store]                                          │
│   (current snapshot of all admitted patients;                    │
│    rolling history for feature computation)                      │
│           │                                                      │
│           ▼                                                      │
│   [Feature Engine]                                               │
│   (current vitals, trajectory features, patient-specific        │
│    baselines, lab features, medication context, unit context)    │
│           │                                                      │
│           ▼                                                      │
│   [Scoring Service]                                              │
│   (deterioration model, optional phenotype-specific models;      │
│    calibration layer; subgroup-stratified thresholds)            │
│           │                                                      │
│           ▼                                                      │
│   [Alert Router]                                                 │
│   (tiered routing, suppression rules, delta detection,           │
│    acknowledgment tracking)                                      │
│           │                                                      │
│    ┌──────┼──────────────┬─────────────────┬──────────────┐      │
│    ▼      ▼              ▼                 ▼              ▼      │
│  Pager  Charge nurse   Bedside         EHR banner    End-of-    │
│  RRT    dashboard      nurse task       in chart     shift      │
│         (situational   list                          report     │
│         awareness)                                              │
│                                                                  │
│           │                                                      │
│           ▼                                                      │
│   [Acknowledgment + Outcome Capture]                             │
│   (alert disposition, intervention recorded, eventual            │
│    deterioration outcome, feedback to retraining)                │
│           │                                                      │
│           ▼                                                      │
│   [Monitoring + Governance]                                      │
│   (subgroup performance, calibration drift, alert volume,        │
│    operational metrics, clinical governance dashboards)          │
│                                                                  │
│           │                                                      │
│           ▼                                                      │
│   [Periodic Retraining + Threshold Review]                       │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**Streaming ingest.** Vitals come from the EHR as they're charted (or from bedside monitor streams if you're integrating below the EHR layer, which adds substantial complexity for the benefit of more granular data). Labs come as result events. Medications come as administration events. Orders come as new-order events. The ingest layer normalizes the heterogeneous events into a canonical clinical event format, handles unit conversions (the same lab can be reported in different units across facilities), reconciles timestamps (charted time vs. observation time vs. result time vs. release time), and deduplicates re-issued events.

**Patient state store.** A continuously-updated snapshot of every admitted patient: current vitals, recent vitals history (the lookback window for trajectory features), recent labs, active medications, current location, current orders. This is the substrate the feature engine reads from. Storage technology choice depends on volume and access pattern, but the operational requirement is that retrieving a patient's full feature vector should take tens of milliseconds.

**Feature engine.** Stateless transformations that read from the patient state store and produce the model's input feature vector. Current vitals are direct. Trajectory features (slopes, deltas, max/min over windows) are computed on the fly. Patient-specific baselines (the patient's own median over the last several days) are maintained either in the state store as rolling aggregates or computed on demand. Lab features, medication context features, and unit context features pull from their respective sub-stores. The feature vector that goes into the model has a fixed schema that's versioned; feature vector schema changes require model retraining.

**Scoring service.** Hosts the trained model. Receives feature vectors, returns calibrated probabilities (or risk tier assignments). Often hosts multiple models simultaneously (the generic deterioration model, sepsis-specific, respiratory failure-specific) for phenotype-aware deployments. Returns per-prediction explanations alongside the score, because alerts without explanations don't get acted on.

**Alert router.** The product. Receives scores for every patient, applies tiered thresholds, applies suppression rules (active comfort care, already in ICU, recent rapid response, model uncertainty too high to alert), detects deltas (this patient's score just jumped substantially), and routes alerts to the appropriate destination(s). The destinations are the actual integration points: pager systems, clinical communication platforms (Vocera, TigerConnect), EHR banner displays, charge nurse dashboards, end-of-shift reports.

**Acknowledgment and outcome capture.** Every alert generates an acknowledgment requirement. The clinician who looked at the alert dispositioned it (acknowledged-monitoring, escalated, intervened, dismissed-as-noise). The disposition is recorded. Subsequent clinical outcome (did the patient actually deteriorate, get transferred, get a code blue, have a sepsis bundle initiated) is captured from the EHR over the following hours and days. The combined alert + disposition + outcome record is the labeled data that drives retraining and threshold tuning.

**Monitoring and governance.** Real-time dashboards for the model team and the clinical governance committee. Alert volume by unit, by tier, by hour. Subgroup performance metrics (AUROC, PRAUC, calibration) refreshed weekly or monthly. Alert disposition distributions (how often is the page tier dismissed as noise vs. acted on). Subgroup-stratified outcome rates. The governance dashboards are where the clinical leadership team lives; the model team monitors the technical metrics; both share the alert volume views.

**Retraining and threshold review.** Quarterly (sometimes more often) retraining cadence. Use accumulated outcome labels. Compare candidate model against current production model on held-out data. Subgroup performance comparison. Calibration check. Shadow deployment for a defined period before promotion. Threshold review independent of retraining: the operational thresholds may need adjustment even when the model itself doesn't change, because alert volume targets shift as care patterns shift.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.07-architecture). The Python example is linked from there.

## The Honest Take

The model is the smaller half of this problem. I keep saying this in different ways across this chapter, and it's especially true here: the workflow integration, the alert design, the governance committee, and the clinical change management dwarf the modeling effort in time, cost, and risk. I've watched teams spend nine months building a beautiful model and three weeks on alert routing, then wonder why nobody on the floor uses the alerts. It's the alert routing. Build the workflow first, even if it has to be wired to a NEWS2 score initially, and add the better model into it once the workflow is working. The Implementation-Time table in the [architecture companion](chapter03.07-architecture) encodes the same discipline: the Basic tier (4-6 months) is a NEWS2-engine-and-workflow-only deployment with full governance and dashboard wiring, before any ML work begins; the Production-ready tier adds the ML model into a workflow that already works.

Vendor models versus build-your-own is mostly a false choice. The real choice is "do we deploy a vendor model with strong local validation, monitoring, and integration, or do we build the same operational infrastructure plus the model?" The model itself is rarely the differentiator. The team that's good at workflow integration and clinical governance gets value from any reasonable model; the team that's not, fails with the best model in the world. If a vendor model that locally validates well is available and your team's strength is workflow and governance, take the vendor model. If your team has deep clinical ML capability and is willing to take on the model lifecycle, building can be the right call. Most hospitals should not build from scratch.

Local validation is not optional and it's not "we ran AUROC on a hold-out set." Real local validation looks like: held-out time period, subgroup-stratified analysis, comparison against the existing track-and-trigger baseline, manual review of the top false positives and false negatives by clinicians who understand the population, and a written safety case for clinical governance. Most published validation work is more rigorous than what hospitals do in practice; tighten this up. The Epic Deterioration Index COVID-era underperformance was a public lesson that the field is still digesting; don't be the next case study.

NEWS2 is harder to beat than the literature suggests. NEWS2 is often a stronger baseline than first appears, especially when the comparison ML model isn't carefully calibrated for the population. A model that beats NEWS2 by 3 AUROC points on retrospective data may not beat it operationally because the calibration is worse, the subgroup performance is worse, or the alerts are less actionable. Treat the NEWS2 baseline with respect and don't assume it's a low bar.

Calibration is more important than discrimination. I'd rather deploy a slightly less discriminating model that's well-calibrated than a more discriminating model that's miscalibrated, because the operational thresholds depend on calibration. A score of 0.6 has to mean "60% chance of deterioration in the prediction window" if the threshold is going to be set sensibly. Models that aren't calibrated produce thresholds that are arbitrary, and arbitrary thresholds produce alert volumes that don't match operational capacity.

Alert disposition data is gold and most teams don't capture it well. Every alert that fires gets dispositioned: acknowledged-monitoring, escalated, intervention, dismissed-as-noise. The dismissed-as-noise category is the gold mine. The patterns in dismissed alerts tell you which features fire when they shouldn't, which subgroups produce alerts that don't translate to action, and which thresholds are too aggressive. Teams that don't capture disposition data are flying blind on operational tuning. Build this capture into the alert acknowledgment UI from day one.

Subgroup monitoring is exhausting and necessary. The number of subgroups and metrics adds up fast. AUROC by age band by sex by service line by unit by time-of-day is hundreds of cells, most of which are noise. The framework I've seen work: pick a small set of clinically meaningful subgroups (3-7), pick a small set of metrics (AUROC, calibration ECE, alert rate, dismissed-as-noise rate), monitor weekly, investigate when a metric for a subgroup is more than X standard deviations from baseline. Don't try to monitor everything; monitor the things that have clear mitigation paths.

Bedside monitor integration is sometimes worth it and sometimes not. The case for: continuous waveforms, sub-minute granularity, fewer charting gaps, richer trajectory features. The case against: substantial integration project, often requires biomedical engineering involvement, often requires bridge appliances or vendor middleware, the marginal performance gain may not justify the complexity. I've worked on programs that went both ways. The right answer depends on the specific population and workflow; it's not "always do bedside" and it's not "never do bedside."

The thing I'd do differently: I'd start with a smaller scope. A medication-overdose-respiratory-depression model on a specific surgical floor, or a sepsis-onset model on the medical floor, scoped narrow enough that the workflow integration is manageable and the governance committee can stay focused. Hospitals that try to deploy a single generic deterioration model across the entire facility often end up with an alert system that's 60% useful in 100% of places; hospitals that deploy phenotype-specific models in specific units often end up with alerts that are 90% useful in 30% of places. The latter compounds; the former plateaus.

The political reality: clinical staff are tired of new systems and tired of alerts. They've seen alert pilots come and go. They have institutional memory of the last "AI deterioration system" that fired constantly and was eventually turned off. The first thing they're going to ask is "is this another thing that's going to interrupt my sleep at 2 a.m. for nothing?" The answer matters. The answer needs to be backed by shadow-mode evidence, by genuine workflow design, by alert volume targets, and by a leadership commitment that the system will be turned off if it doesn't deliver. Make those commitments and keep them.

The thing nobody talks about: pilot studies that work in the pilot unit don't always generalize. The pilot unit is usually a high-engagement environment with motivated staff and active model team support. When the system rolls out to the rest of the facility, the staff are less engaged, the model team is stretched thinner, and the operational metrics drift. Plan for the rollout phase as carefully as the pilot phase. Document the engagement requirements explicitly.

The trap I see most often: optimizing for the wrong metric. AUROC is the academic ML community's metric. Calibrated probability above threshold is the deployment metric. Time-to-acknowledge is the workflow metric. Cases of preventable deterioration prevented per quarter is the program metric. Cases of confirmed deterioration with appropriate intervention is the outcome metric. Hours of clinical staff time consumed per case prevented is the cost metric. If you can't tell me what your program looks like across all six metrics, you don't have a program; you have a science project. The transition from science project to program is the hardest single transition in this work.

Lives are saved sometimes. I want to say this clearly because it's easy to get lost in the operational difficulty: when these systems work, they work. They catch sepsis early, they prevent code blues, they get patients to the ICU before they crash, they save lives. The peer-reviewed literature on this is genuine. The Kaiser Permanente AAM (Advance Alert Monitor) system has published outcomes data showing real reductions in mortality. The eCART program at the University of Chicago has similar evidence. The work is hard, but it's worth doing. Just go in with eyes open about what "doing it" actually requires.

---

## Related Recipes

- **Recipe 3.4 (Medication Dispensing Anomalies):** Some deterioration events are medication-related (opioid-induced respiratory depression, insulin-induced hypoglycemia). Integration of medication-event signals into deterioration prediction overlaps with anomaly detection on dispensing patterns.
- **Recipe 3.5 (Lab Result Outlier Detection):** Lab outliers are a feature class for deterioration prediction. The lab outlier detection pipeline produces clean, contextualized lab features that the deterioration model consumes.
- **Recipe 3.8 (Readmission Risk Anomaly Detection):** Post-discharge deterioration is the same phenomenon, monitored on a different timescale and through different sensors. Many architectural patterns transfer.
- **Recipe 7.x (Predictive Analytics / Risk Scoring):** Deterioration prediction is a specific application of clinical risk scoring. Chapter 7 covers the broader patterns for risk model construction and validation that apply here.
- **Recipe 12.x (Time Series Analysis / Forecasting):** Trajectory features and time-series modeling techniques for deterioration overlap heavily with time-series forecasting patterns.
- **Recipe 2.x (LLM / Generative AI):** LLM-based explanation generation, end-of-shift summaries, and case narrative drafting use patterns from Chapter 2.
- **Recipe 8.x (NLP / Traditional):** Nursing note feature extraction (Rothman-Index-style) uses NLP techniques covered in Chapter 8.
- **Recipe 11.x (Conversational AI):** Some deterioration alerts are surfaced via clinical chatbot interfaces ("What's going on with bed 17?"); patterns in Chapter 11 apply.

---

## Tags

`anomaly-detection` · `early-warning-system` · `clinical-deterioration` · `sepsis-prediction` · `news2` · `mews` · `ews` · `track-and-trigger` · `vital-signs` · `time-series` · `xgboost` · `lstm` · `lightgbm` · `feature-store` · `clarify` · `model-monitor` · `model-registry` · `bedrock` · `comprehend-medical` · `kinesis` · `timestream` · `dynamodb` · `opensearch` · `eventbridge` · `sagemaker` · `clinical-governance` · `local-validation` · `subgroup-performance` · `calibration` · `shap` · `alert-fatigue` · `fda-cds` · `samd` · `hipaa` · `complex` · `production` · `provider`

---

*← [Recipe 3.6: Healthcare Fraud, Waste, and Abuse Detection](chapter03.06-healthcare-fraud-waste-abuse-detection) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.8 - Readmission Risk Anomaly Detection →](chapter03.08-readmission-risk-anomaly-detection)*
