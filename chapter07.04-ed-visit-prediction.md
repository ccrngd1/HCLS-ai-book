# Recipe 7.4: ED Visit Prediction

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.03 per patient per scoring cycle

---

## The Problem

Here's a frustrating fact about emergency departments in the United States: somewhere between 30% and 70% of ED visits (depending on the study and definition) are for conditions that could have been managed in a primary care or urgent care setting. Not all of them. Not even most of them. But a significant chunk. A patient with poorly controlled diabetes shows up at 2 AM because their blood sugar is at 400 and they ran out of insulin three days ago. A COPD patient who missed their last two pulmonary rehab appointments comes in gasping because their exacerbation wasn't caught early. A kid with recurrent asthma arrives by ambulance because the family didn't have a nebulizer at home and the after-hours clinic was closed.

These visits are expensive (the average ED visit costs 5-10x the equivalent outpatient encounter), disruptive to the patient's life, and often signal a failure of the care delivery system upstream. The ED didn't fail the patient. The system around the patient failed to catch a worsening trajectory before it became a crisis.

This is where ED visit prediction comes in. The goal is not to predict who will have a car accident or an acute MI. Those are genuinely unpredictable emergencies. The goal is to identify the patients whose utilization pattern, clinical history, medication adherence, and social circumstances make them likely to show up in the ED in the next 30 to 90 days for a condition that, with the right outreach, might have been prevented.

The stakes are real on both sides. If you identify these patients accurately, a care manager can reach out: adjust medications, schedule a same-week appointment, connect them to transportation, set up a home health check. If you identify them inaccurately, you waste scarce care management resources on patients who were never at risk, while the actual high-utilizers slip through.

And here's the part nobody tells you upfront: the hardest problem isn't building the model. It's building the system that turns a prediction into an action that actually changes the outcome. A perfect score means nothing without an intervention pathway.

---

## The Technology: How ED Risk Prediction Works

### The Prediction Problem

At its core, ED visit prediction is a supervised binary classification problem with a time horizon. You're asking: "Will this patient have at least one ED visit within the next N days?" where N is typically 30, 60, or 90 days depending on your intervention capacity and turnaround time.

The choice of time horizon matters more than most teams realize at the start. A 30-day window gives you the most actionable predictions (you know the risk is imminent, so outreach feels urgent), but it also gives you the least time to intervene effectively. A 90-day window gives you more time to act, but the predictions are necessarily less precise because you're forecasting further into the future. Most production systems settle on 30 or 60 days, scoring patients weekly or biweekly.

The output isn't binary in practice. You don't want "yes/no." You want a calibrated probability: "This patient has a 34% likelihood of an ED visit in the next 60 days." Calibration matters because care managers need to prioritize a list. A patient at 34% and a patient at 78% both need outreach, but in different order and with different urgency.

### What Makes This Different From Other Risk Models

ED visit prediction sits at an awkward intersection that makes it harder than, say, readmission prediction or no-show prediction:

**The outcome is partially preventable.** Not all ED visits can be prevented, and you can't easily label historical data as "preventable" or "non-preventable" after the fact. Your model is trained on all ED visits, but your intervention only matters for the preventable subset. This creates a fundamental ceiling on useful accuracy.

**The drivers are multi-dimensional.** Clinical factors (disease burden, medication complexity, recent hospitalizations) matter, but so do behavioral factors (appointment adherence, refill patterns) and social factors (transportation access, housing stability, food security). Most healthcare data systems capture the clinical piece well, the behavioral piece partially, and the social piece barely at all.

**The base rate is low-ish.** In a general insured population, maybe 5-15% of members will have an ED visit in any given 60-day window. In a high-risk chronic disease panel, it might be 20-30%. Either way, you're dealing with class imbalance, which means naive accuracy metrics are misleading. A model that says "nobody will go to the ED" is 85% accurate and completely useless.

### Feature Engineering: What Actually Predicts ED Use

The literature on ED utilization prediction is fairly mature. Here are the feature families that consistently show up in published models, roughly ordered by predictive importance:

**Prior utilization history.** The single strongest predictor of a future ED visit is having had a prior ED visit. Frequency, recency, and pattern (escalating vs. stable vs. declining) all matter. Patients with 3+ ED visits in the past 12 months are a qualitatively different population than patients with zero.

**Chronic disease burden.** Number of active chronic conditions, their severity (HCC scores, Charlson/Elixhauser indices), and their control status (is the diabetes well-managed or poorly-managed based on recent labs). Not just presence of conditions, but trajectory of those conditions.

**Medication adherence signals.** Proportion of Days Covered (PDC) for key medications. Gap days between fills. Number of active prescriptions (polypharmacy is a risk factor). Whether the patient has filled their maintenance medications on schedule.

**Care engagement patterns.** Missed appointments, gaps in preventive care, time since last PCP visit. Patients who are disengaging from routine care are often the ones who show up in the ED because they have nowhere else to go when things get bad.

**Social determinants (when available).** Homelessness indicators, food insecurity flags, transportation barriers, social isolation, dual-eligible status (Medicare + Medicaid), neighborhood-level deprivation indices. These are powerful predictors but often missing from structured data. Area-level proxies (using census data linked by zip code) partially fill the gap.

**Temporal patterns.** Seasonality (respiratory conditions spike in winter), time since last major clinical event (surgery, hospitalization, diagnosis), and acceleration of utilization (is the patient's visit frequency increasing month over month).

### Model Architecture Choices

Several model families work well for this problem:

**Gradient-boosted trees (XGBoost, LightGBM, CatBoost).** The workhorse of healthcare risk prediction. Handle mixed feature types, missing values, and non-linear relationships naturally. Interpretable via SHAP values. Train quickly on tabular data. This is where most production systems land.

**Logistic regression.** Simpler, fully interpretable, easier to explain to clinical stakeholders. Works well when features are carefully engineered. Still a reasonable choice when you need maximum transparency or have regulatory requirements for full model explainability.

**Survival models (Cox proportional hazards, random survival forests).** Better at modeling time-to-event rather than binary classification. If "when will this patient go to the ED?" matters more than "will they?", survival models are worth the added complexity.

**Deep learning (LSTM, Transformers on longitudinal claims).** Can learn temporal patterns from raw event sequences without manual feature engineering. More data-hungry, harder to explain, and often only marginally better than well-engineered gradient-boosted models for this task. Worth exploring if you have millions of members and strong engineering talent.

For most organizations starting out, gradient-boosted trees with carefully engineered features are the right answer. You get 90% of the achievable performance with 30% of the complexity.

### Calibration: Why Raw Scores Aren't Enough

A model might output "0.72" for a patient. What does that mean? If the model is well-calibrated, it means that among all patients the model scores at 0.72, approximately 72% actually have an ED visit in the prediction window. Calibration is the property that makes probability estimates trustworthy.

Most ML models are not naturally well-calibrated. They rank patients correctly (higher-risk patients get higher scores) but the absolute probabilities are often wrong. Platt scaling or isotonic regression applied after model training can fix this. It sounds minor, but care managers need to trust that "high risk" actually means high risk, especially when they're deciding how to spend limited outreach time.

### The General Architecture Pattern

```text
[Data Aggregation] -> [Feature Engineering] -> [Model Scoring] -> [Risk Stratification] -> [Intervention Routing]
```

**Data Aggregation.** Pull together the raw ingredients: claims history, EHR encounters, pharmacy fills, lab results, demographic data, and (if available) social determinant indicators. This typically means a nightly or weekly ETL pipeline that consolidates data from multiple source systems into a unified patient-level feature store.

**Feature Engineering.** Transform raw events into predictive signals: count ED visits in the past 6 months, calculate medication adherence ratios, compute time since last PCP visit, flag accelerating utilization patterns. This is where domain expertise makes the biggest difference. A data scientist who understands healthcare operations will build better features than one who doesn't, even with the same algorithms.

**Model Scoring.** Run the trained model against the current feature set for all active patients. This produces a raw probability estimate for each patient. Scoring typically runs on a batch schedule (weekly or biweekly) rather than real-time, because the features themselves don't change moment-to-moment.

**Risk Stratification.** Apply calibration, assign patients to risk tiers (high/medium/low), and generate a prioritized outreach list. The stratification thresholds should be set based on your care management capacity: if you can reach out to 200 patients per week, set the "high-risk" threshold so it captures roughly 200 patients.

**Intervention Routing.** Route high-risk patients to the appropriate intervention: care management outreach, pharmacy consultation, social work referral, or automated patient engagement (text reminders, portal messages). The routing logic is often rule-based on top of the risk score, incorporating what the model identified as the primary risk driver for each patient.

This is not a real-time system. The prediction window is 30-90 days. Running weekly batch scoring is appropriate for the tempo of the interventions you're trying to trigger. Note that weekly scoring creates a blind spot for rapid-onset risk. Some implementations add event-triggered rescoring for critical transitions (hospital discharge, medication discontinuation) to capture acute risk between batch cycles. The [Architecture companion](chapter07.04-architecture) covers this variation in detail.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.04-architecture). The Python example is linked from there.

## The Honest Take

Here's what I've learned from watching ED prediction models in the real world:

The model accuracy ceiling is lower than you expect. Published AUROCs of 0.72-0.80 sound mediocre, and they are, compared to something like fraud detection. But the ceiling is low because a large fraction of ED visits are genuinely unpredictable from historical data. You're not predicting car accidents. You're predicting the subset of ED visits that have precursors visible in claims and pharmacy data. That's a smaller set than "all ED visits."

The hardest problem is not technical. It's operational. I've seen models with perfectly good discrimination sit unused because nobody built the workflow that turns a risk score into a care manager's Monday morning list. The model is 20% of the work. The integration with care management platforms, the outreach protocols, the staffing models, and the outcome tracking are the other 80%.

Feature engineering matters more than algorithm choice. I've watched teams spend months tuning XGBoost hyperparameters for a 0.3% AUC improvement, while ignoring the fact that they hadn't incorporated medication adherence data (which would have given them 3-5% improvement). The features are the model. The algorithm is just the container.

Social determinants are the biggest untapped signal and the hardest to operationalize. ZIP code-level deprivation indices add meaningful lift. But patient-level SDOH data (from screenings, community health worker notes, social service referrals) is transformative when available. The problem is that it's available for maybe 10-20% of patients in most health systems.

The "preventable" question never goes away. Stakeholders will always ask "what percent of these ED visits were actually preventable?" And the honest answer is "we don't know for certain, because the counterfactual doesn't exist." You can approximate with studies that categorize ED visits by AHRQ criteria (primary-care-sensitive conditions), but there will always be uncertainty about which specific visits the intervention actually prevented.

---

## Related Recipes

- **Recipe 7.1 (Appointment No-Show Prediction):** Shares feature engineering patterns (utilization history, engagement signals) and the same batch scoring architecture at lower stakes
- **Recipe 7.3 (Patient Churn / Disenrollment Prediction):** Similar behavioral signal detection; patients disengaging from care are at risk for both churn and ED utilization
- **Recipe 7.5 (30-Day Readmission Risk):** Closely related model architecture; readmission models often share features with ED prediction models and can be trained jointly
- **Recipe 7.6 (Rising Risk Identification):** The trajectory version of this problem; identifies patients whose ED risk is accelerating rather than just currently high
- **Recipe 6.2 (Utilization Pattern Segmentation):** Upstream clustering that can feed into ED prediction as a feature (which utilization segment does this patient belong to?)

---

## Tags

`predictive-analytics` · `risk-scoring` · `emergency-department` · `ed-prediction` · `gradient-boosted-trees` · `xgboost` · `sagemaker` · `batch-transform` · `glue` · `step-functions` · `care-management` · `population-health` · `medium-complexity` · `hipaa`

---

*← [Recipe 7.3: Patient Churn / Disenrollment Prediction](chapter07.03-patient-churn-disenrollment-prediction) · [Chapter 7 Index](chapter07-preface) · [Next: Recipe 7.5: 30-Day Readmission Risk →](chapter07.05-30-day-readmission-risk)*
