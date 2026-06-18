# Recipe 7.7: Length of Stay Prediction

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.02 per prediction (batch); ~$0.08 per real-time inference

---

## The Problem

A patient is admitted to the hospital at 2 AM with acute pancreatitis. The admitting physician writes "anticipated LOS: 3-5 days" in the chart. The bed management team allocates resources accordingly. The discharge planner starts working on day 3.

On day 4, the patient develops a complication. Now it's 8-10 days. But the discharge planner didn't find out until day 5. The bed that was supposed to free up on day 5 for a scheduled surgical admission? Still occupied. The surgical case gets bumped. The OR schedule cascades. Downstream, a patient waiting in the ED for an inpatient bed waits six extra hours.

This is not an edge case. This is Tuesday.

Hospital length of stay (LOS) prediction is one of those problems that sounds like it should be straightforward. You have decades of historical data. You know the diagnosis. You know the patient's age and comorbidities. Just train a model, right?

The reality is messier. LOS is driven by a tangled web of clinical factors (disease severity, complications, response to treatment), operational factors (discharge planning efficiency, specialist availability, imaging backlogs), and social factors (does the patient have a safe place to go? Is there a skilled nursing facility bed available? Does the family need to arrange home care?). A model that only sees clinical data will systematically underpredict for patients with social barriers to discharge. A model that doesn't update as the stay progresses becomes useless after day 2.

The operational stakes are real. Hospitals run at 85-95% occupancy. Every bed-day costs $2,000-$4,000 in direct costs. Accurate LOS prediction enables proactive discharge planning (start the SNF referral on day 1, not day 5), better bed management (know which beds are freeing up tomorrow), staffing optimization (predict nursing ratios 48 hours out), and surgical scheduling (don't schedule an admission into a bed that won't be empty).

The financial incentive is also direct: under DRG-based payment, the hospital gets paid a fixed amount regardless of how long the patient stays. Every day beyond the geometric mean LOS for that DRG is a day the hospital is losing money. Predicting which patients will exceed their expected LOS early enough to intervene is worth millions annually for a mid-size hospital.

The goal is a system that updates as reality unfolds, not one that guesses at admission and hopes for the best.

---

## The Technology: Predicting How Long Patients Stay

### What We're Actually Predicting

LOS prediction is a regression problem on the surface: given a set of patient and encounter features at some point in time, predict the number of remaining days until discharge. But it's more nuanced than a simple regression because:

1. **The prediction needs to update.** An admission-time prediction is useful for initial planning, but it becomes stale as the stay progresses. You need a model that can re-score daily (or more frequently) as new clinical data arrives.

2. **The distribution is skewed.** Most patients stay 2-4 days. Some stay 30+. The mean is pulled by outliers. Predicting the median or a confidence interval is often more useful than predicting the mean.

3. **The outcome is censored in real-time.** For current inpatients, you don't know the actual LOS yet. You're predicting remaining LOS, which is a different target than total LOS.

4. **It's partly a classification problem.** Operations teams often care more about "will this patient exceed 7 days?" than "will this patient stay 5.3 days?" Framing it as a probability of exceeding a threshold can be more actionable.

### Feature Categories That Matter

The features that drive LOS prediction fall into distinct categories, and understanding them helps you design the data pipeline:

**Admission features (available at time zero):**
- Demographics: age, sex (older patients stay longer, on average)
- Admission source: ED vs. direct admit vs. transfer (ED admits tend to be sicker)
- Admission type: emergent vs. elective (elective cases have tighter LOS distributions)
- Primary diagnosis (ICD-10) and DRG assignment
- Comorbidity burden: Charlson or Elixhauser index scores
- Prior utilization: hospitalizations in the last 12 months, ED visits
- Insurance type (a proxy for social complexity, unfortunately)

**Dynamic features (accumulate during the stay):**
- Lab results: trending values, abnormal flags, rate of normalization
- Vital signs: stability, trajectory
- Medications: escalation vs. de-escalation of treatment intensity
- Procedures performed: surgeries, imaging, consults ordered
- Nursing assessments: mobility scores, pain scores, functional status
- Current day of stay (the strongest single predictor of remaining LOS, ironically)

**Social/disposition features (often the hardest to capture):**
- Discharge disposition: home vs. SNF vs. rehab vs. LTACH
- Social work involvement: housing instability, lack of caregiver
- Prior authorization status for post-acute care
- DME (durable medical equipment) orders pending
- Patient/family readiness for discharge

The social features are where models consistently underperform. They're poorly documented in structured data, often buried in free-text notes, and represent the actual bottleneck for a large percentage of patients who are "medically ready" but can't leave.

### Modeling Approaches

Several approaches work for LOS prediction, each with tradeoffs:

**Gradient boosted trees (XGBoost, LightGBM).** The workhorse. Handles mixed feature types naturally, deals with missing data gracefully, and produces interpretable feature importances. For admission-time prediction with structured features, this is usually the best starting point. Typical performance: MAE of 1.5-2.5 days for general medical/surgical populations.

**Survival analysis models.** Instead of predicting a point estimate, model the probability of discharge at each future time point. Cox proportional hazards or accelerated failure time models give you a full survival curve. This is more informative for operations: "there's a 70% chance this patient discharges by day 4, 90% by day 7." The downside is that traditional survival models assume proportional hazards, which doesn't hold well for heterogeneous hospital populations.

**Deep learning (LSTM/Transformer on time series).** For the dynamic prediction problem (updating predictions as the stay progresses), recurrent or attention-based models can ingest the sequence of clinical events and learn temporal patterns. More complex to train and deploy, harder to explain, but can capture non-linear interactions between evolving clinical states. Worth it for ICU populations where the clinical trajectory is highly dynamic.

**Ensemble approaches.** In practice, the best systems combine an admission-time model (gradient boosted trees on structured features) with a daily-update model (that incorporates the clinical trajectory) and blend their outputs. The admission model provides the baseline; the daily model adjusts as reality unfolds.

### Why This Is Harder Than It Looks

**Complications are the killer.** A straightforward appendectomy has a tight LOS distribution (1-2 days). But if the patient develops a surgical site infection on day 2, the distribution shifts dramatically. Predicting complications before they happen is a different (harder) problem. The LOS model needs to update rapidly when complications occur, which means it needs near-real-time access to clinical data.

**Social barriers are invisible to the model.** A patient who is medically ready for discharge on day 3 but waits until day 7 for a SNF bed is not a clinical prediction failure. It's a social/operational prediction failure. Unless your model has features representing SNF bed availability, insurance authorization status, and family readiness, it will systematically underpredict for these patients. And those features are rarely available in structured form.

**Case mix matters enormously.** A model trained on a general medical population will perform poorly on cardiac surgery patients, and vice versa. The feature importances, the LOS distributions, and the relevant complications are all different. Most production systems train separate models per service line or DRG family.

**The target is moving.** Hospital processes change. A new discharge planning initiative, a new hospitalist staffing model, a new SNF partnership: all of these shift the LOS distribution. Models need regular retraining (monthly or quarterly) to stay calibrated.

**Accuracy expectations are unrealistic.** Clinicians expect the model to be right. But LOS has inherent irreducible uncertainty. Even a perfect model can't predict that a patient will fall on day 3 and fracture their hip. Setting expectations around confidence intervals rather than point predictions is essential for adoption.

### The General Architecture Pattern

```text
[EHR Data Extract] → [Feature Engineering] → [Model Training Pipeline]
                                                        ↓
[Real-time Clinical Feed] → [Feature Store] → [Inference Engine] → [Prediction Store]
                                                                          ↓
                                                              [Bed Management Dashboard]
                                                              [Discharge Planning Alerts]
                                                              [Capacity Forecasting]
```

The architecture has two modes:

**Batch mode (training and daily refresh):** Extract historical encounters with known outcomes. Engineer features at multiple time points during each stay. Train models per service line. Evaluate on held-out data. Deploy the best model.

**Real-time mode (operational predictions):** For current inpatients, pull the latest clinical data from the EHR feed. Compute current features. Run inference. Store the prediction. Push to operational dashboards and alerting systems.

The feature store is the critical piece that bridges both modes. Training features and inference features must be computed identically, or you get training-serving skew (the model sees different feature distributions in production than it saw during training, and accuracy degrades silently).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.07-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you when you build this:

The model's biggest errors are almost never clinical. They're social. The patient who is medically ready on day 4 but waits until day 9 because there's no SNF bed, or because the family can't arrange home oxygen, or because the patient is homeless and there's nowhere safe to discharge them. Your model will learn that Medicaid patients stay longer (because they do, on average), but it won't understand why. And that "why" is where the intervention opportunity lives.

The DRG geometric mean LOS is both your best feature and your biggest trap. It's the single strongest predictor of actual LOS (because DRGs are designed to group clinically similar patients). But it also encodes historical patterns that may not reflect your hospital's current processes. If your hospital is systematically faster or slower than the national average for a given DRG, the model needs to learn that local calibration.

Clinician trust is the adoption bottleneck, not model accuracy. A model that's right 75% of the time but wrong in ways that feel random to clinicians will be ignored. A model that's right 70% of the time but explains its reasoning (top contributing features) and acknowledges uncertainty (confidence intervals) will be used. Invest in explainability.

The daily update is where the real value lives. An admission-time prediction is a starting point. The prediction that updates on day 2 when the patient spikes a fever and gets started on IV antibiotics, that's what changes operational decisions. Build the real-time pipeline from day one, not as a phase 2.

Retraining cadence matters more than you'd think. Hospital operations change seasonally (flu season, summer trauma), with new initiatives (discharge by noon programs), and with staffing changes. A model trained on 2024 data may be poorly calibrated for 2026 operations. Monthly retraining with a 12-month rolling window is a reasonable starting point.

---

## Related Recipes

- **Recipe 7.5 (30-Day Readmission Risk):** Complementary prediction; patients discharged too early may readmit, creating a tension between LOS reduction and readmission prevention
- **Recipe 7.6 (Rising Risk Identification):** Identifies patients whose trajectory is worsening, which directly impacts LOS predictions
- **Recipe 12.5 (Hospital Census Forecasting):** Consumes LOS predictions as inputs to forecast hospital-wide bed availability
- **Recipe 14.3 (Operating Room Scheduling Optimization):** Uses predicted bed availability (from LOS predictions) to optimize surgical scheduling
- **Recipe 6.4 (Disease Severity Stratification):** Severity scores serve as features in LOS models

---
