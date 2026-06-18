# Recipe 7.9: Mortality Risk Scoring (ICU)

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$0.02-$0.08 per prediction

---

## The Problem

An intensivist is standing at the bedside of a 72-year-old patient on day three of a medical ICU admission. The patient has multi-organ dysfunction: kidneys failing, blood pressure requiring vasopressors, ventilator settings climbing. The family is asking "what are the chances?" The physician has clinical intuition built from years of experience, but translating that into a calibrated probability is something humans are genuinely bad at. Studies consistently show that clinicians overestimate survival in critically ill patients. They anchor on the patient they remember who beat the odds, not the twenty who didn't.

This isn't an academic problem. Goals-of-care conversations happen every day in ICUs, and they happen better when everyone has a shared, honest understanding of prognosis. Families making decisions about code status, tracheostomy, or transition to comfort care deserve the best information available. Clinicians making triage decisions during surge capacity need objective severity signals. Quality teams benchmarking ICU performance need risk-adjusted mortality rates to distinguish "this unit has sicker patients" from "this unit has worse outcomes."

The traditional approach is severity-of-illness scoring systems: APACHE (Acute Physiology and Chronic Health Evaluation), SOFA (Sequential Organ Failure Assessment), SAPS (Simplified Acute Physiology Score). These have been workhorses since the 1980s. They use a fixed set of physiological variables, assign points, and map to a mortality probability. They work. They're also frozen in time: the coefficients were derived from patient populations decades ago, they use a limited variable set, and they can't incorporate the rich longitudinal data that modern EHRs capture every few minutes.

Machine learning mortality models can do better. They can ingest hundreds of features, update predictions as new data arrives, account for temporal patterns in vital signs, and recalibrate continuously against your specific patient population. But "can do better" and "should be deployed" are separated by a canyon of ethical, technical, and operational challenges that make this one of the hardest prediction problems in healthcare.

Let's talk about why.

---

## The Technology: Predicting Death (Carefully)

### What We're Actually Predicting

Let's be precise about the prediction target, because ambiguity here causes real harm. "Mortality risk" can mean:

- **ICU mortality:** probability of dying during the current ICU stay
- **Hospital mortality:** probability of dying during the current hospitalization (including after ICU discharge)
- **30-day mortality:** probability of dying within 30 days of ICU admission, regardless of location
- **Time-to-event:** a survival curve showing probability of being alive at each future time point

Each target has different clinical utility. ICU mortality is most relevant for immediate triage decisions. Hospital mortality matters for goals-of-care conversations. 30-day mortality is the standard for quality benchmarking. Time-to-event models are the most informative but hardest to build and explain.

Most production systems predict hospital mortality or 30-day mortality, because those align with how clinicians think about prognosis and how quality programs measure outcomes.

### The Feature Space

ICU patients generate an extraordinary volume of data. A single patient-day in a modern ICU might produce:

- **Vital signs:** Heart rate, blood pressure (systolic, diastolic, mean arterial), respiratory rate, SpO2, temperature. Recorded every 1-5 minutes by bedside monitors. That's 1,000+ data points per vital per day.
- **Laboratory values:** Arterial blood gases, metabolic panels, complete blood counts, lactate, coagulation studies. Typically 4-12 lab draws per day.
- **Ventilator parameters:** FiO2, PEEP, tidal volume, peak pressure, minute ventilation. Continuous or near-continuous.
- **Medications:** Vasopressor doses (and dose changes), sedation levels, antibiotic timing, fluid volumes.
- **Clinical assessments:** Glasgow Coma Scale, Richmond Agitation-Sedation Scale, nursing assessments.
- **Demographics and history:** Age, sex, admission diagnosis, comorbidities, surgical status.

The challenge isn't having enough data. It's having too much, with too much noise, too many missing values, and too many spurious correlations.

### Modeling Approaches

**Traditional scoring systems (APACHE, SOFA, SAPS)** use logistic regression on a curated set of 15-30 variables, typically the worst values in the first 24 hours. They're interpretable, well-validated, and limited. APACHE IV uses 142 variables but still relies on first-24-hour snapshots.

**Gradient boosted trees (XGBoost, LightGBM)** are the workhorse of tabular clinical prediction. They handle missing values natively, capture non-linear relationships, and produce feature importance rankings. For a point-in-time prediction using structured features, they're hard to beat. Most production ICU mortality models use this approach.

**Deep learning (RNNs, Transformers)** can model the temporal sequence of vital signs and lab values directly. Instead of summarizing "worst heart rate in 24 hours," they can learn that "heart rate variability decreased over the last 6 hours" is prognostically meaningful. The tradeoff: they require more data, more compute, and are harder to explain. Google's work on FHIR-based deep learning models showed promise, but deployment in production ICUs remains rare.

**Survival models (Cox proportional hazards, deep survival)** predict time-to-event rather than a binary outcome. They handle censoring (patients who are discharged alive but might die later) correctly. They're the right choice for quality benchmarking but add complexity to real-time clinical use.

For most organizations starting out, gradient boosted trees on structured features are the right first model. They're accurate enough, interpretable enough, and deployable enough to provide real clinical value while you build the infrastructure for more sophisticated approaches.

### Calibration: The Thing That Actually Matters

Here's the part that trips up most ML teams: discrimination is not calibration.

**Discrimination** (measured by AUC/c-statistic) tells you whether the model ranks patients correctly. A patient who dies should have a higher predicted risk than a patient who survives. Most modern models achieve AUC 0.85-0.92 on ICU mortality. That sounds great.

**Calibration** tells you whether the predicted probabilities are accurate. If you predict 30% mortality for a group of patients, do 30% of them actually die? This is what matters for clinical decision-making. A family hearing "your father has a 70% chance of dying" needs that number to be honest, not just relatively correct.

Models trained on one population and deployed on another are almost always miscalibrated. A model trained at an academic medical center will overestimate mortality at a community hospital (because the academic center's patients are sicker on average, and the model learned that baseline). Recalibration on your local population is not optional. It's the difference between a useful tool and a harmful one.

### The Self-Fulfilling Prophecy Problem

This is the deepest challenge in mortality prediction, and it doesn't have a clean technical solution.

If a model predicts high mortality risk, and that prediction influences a decision to transition to comfort care, and the patient subsequently dies, was the prediction correct? Or did the prediction cause the outcome? This is called the "self-fulfilling prophecy" or "treatment paradox" in clinical prediction.

The practical implications: you cannot naively retrain on outcomes that were influenced by your own predictions. You need to carefully track whether goals-of-care decisions changed after the prediction was surfaced, and either exclude those cases from retraining or model the treatment decision explicitly.

There's no perfect answer here. The honest approach is to be transparent about it: the model predicts what would happen under current standard of care, not what would happen if all possible interventions were pursued indefinitely.

### Fairness and Subgroup Performance

Mortality models trained on general ICU populations often perform differently across subgroups:

- **Age:** Calibration may drift for very elderly patients (85+) where the training data is sparse.
- **Race/ethnicity:** Historical disparities in care intensity mean that observed mortality rates reflect both biology and treatment decisions. A model that learns "Black patients have higher mortality" may be learning "Black patients historically received less aggressive care," which is a bias to correct, not a pattern to perpetuate.
- **Diagnosis:** A model trained predominantly on medical ICU patients may miscalibrate for surgical or cardiac ICU populations.
- **Hospital type:** Academic vs. community, urban vs. rural, teaching vs. non-teaching.

Subgroup calibration analysis is mandatory before deployment. Not just overall AUC, but calibration curves stratified by every demographic and clinical subgroup you can identify.

### The General Architecture Pattern

```text
[EHR Data Stream] → [Feature Engineering] → [Model Inference] → [Calibration] → [Clinical Display]
                                                                        ↓
                                                              [Outcome Tracking]
                                                                        ↓
                                                              [Model Monitoring & Retraining]
```

**EHR Data Stream:** Real-time or near-real-time extraction of vital signs, labs, medications, and assessments from the EHR. This is the hardest integration piece. Most EHRs support HL7 FHIR or ADT/ORU feeds, but the data quality and latency vary enormously.

**Feature Engineering:** Transform raw clinical data into model-ready features. This includes temporal aggregations (worst value in last 6 hours, trend over last 12 hours, variability metrics), missing value handling (is the lab missing because it wasn't ordered, or because the result isn't back yet?), and derived features (P/F ratio from PaO2 and FiO2, shock index from HR and SBP).

**Model Inference:** Score the patient using the trained model. For real-time use, this needs to complete in seconds. For batch quality reporting, latency is less critical.

**Calibration:** Apply a calibration layer (Platt scaling, isotonic regression) trained on your local population. This adjusts the raw model output to produce honest probabilities for your specific patient mix.

**Clinical Display:** Surface the prediction in a way that supports (not replaces) clinical judgment. This means: showing the score alongside the key contributing factors, providing uncertainty bounds, and making it clear this is a statistical estimate, not a diagnosis.

**Outcome Tracking:** Record what actually happened to each patient. Did they survive? Were goals of care changed? Was the prediction surfaced to the clinical team? This feeds model monitoring and retraining.

**Model Monitoring:** Track discrimination and calibration over time. Detect drift. Alert when performance degrades. Trigger retraining when needed.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.09-architecture). The Python example is linked from there.

## The Honest Take

This is the recipe I'm most conflicted about writing. The technology works. Gradient boosted trees on structured ICU data genuinely outperform APACHE and SOFA for discrimination, and with proper calibration they produce honest probabilities. The infrastructure is straightforward. The math is well-understood.

The hard part is everything around the model. Who sees the score? When? How is it framed? What decisions does it influence? A mortality probability displayed prominently on a patient's chart changes behavior in ways that are difficult to measure and impossible to fully control. A nurse who sees "82% mortality risk" may unconsciously deprioritize that patient's comfort measures. A family who hears "the computer says 70%" may anchor on that number in ways that override nuanced clinical discussion.

The self-fulfilling prophecy problem is real and unsolved. If your model influences transitions to comfort care, and those patients die (as expected when aggressive treatment is withdrawn), your model looks accurate in retrospect. But you can't know what would have happened with continued aggressive care. The honest answer is: we don't know, and we should be transparent about that limitation with every stakeholder.

Calibration drift is the operational challenge that will consume the most ongoing effort. Patient populations change. Treatment patterns evolve. New therapies shift survival curves. A model calibrated in January may be miscalibrated by June. Monthly recalibration is the minimum; continuous monitoring with automated alerts is better.

The thing that surprised me most: clinicians don't want a single number. They want to know why. "68% mortality" is less useful than "68% mortality, primarily driven by worsening organ failure trajectory and escalating vasopressor requirements." The explainability layer (SHAP values translated to plain language) is not a nice-to-have. It's the difference between a tool clinicians trust and one they ignore.

Start with quality benchmarking (risk-adjusted mortality rates for your ICU) before attempting real-time clinical decision support. The benchmarking use case has lower stakes, builds institutional familiarity with the model, and generates the outcome data you need for calibration. Real-time bedside predictions are the end state, not the starting point.

---

## Related Recipes

- **Recipe 7.5 (30-Day Readmission Risk):** Shares the feature engineering and calibration patterns but with a different prediction target and lower clinical stakes
- **Recipe 7.6 (Rising Risk Identification):** The trajectory-based features (SOFA trend, vital sign slopes) used here are the core of rising risk detection
- **Recipe 7.8 (Disease Progression Modeling):** Extends the temporal modeling approach to longer time horizons with chronic disease trajectories
- **Recipe 12.10 (Physiological Waveform Analysis):** Provides the high-frequency vital sign features that can feed into mortality models for enhanced temporal resolution
- **Recipe 3.7 (Patient Deterioration Early Warning):** Complementary approach using anomaly detection rather than supervised prediction for acute deterioration

---

## Tags

`predictive-analytics` · `risk-scoring` · `mortality` · `icu` · `sagemaker` · `healthlake` · `calibration` · `complex` · `production` · `clinical-decision-support` · `hipaa` · `xgboost` · `shap` · `explainability`

---

*← [Recipe 7.8: Disease Progression Modeling](chapter07.08-disease-progression-modeling) · [Chapter 7 Index](chapter07-preface) · [Next: Recipe 7.10 - Optimal Intervention Timing Prediction →](chapter07.10-optimal-intervention-timing-prediction)*
