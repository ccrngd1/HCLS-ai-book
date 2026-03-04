# Category 7: Predictive Analytics / Risk Scoring

**Healthcare Use Cases — Simple → Complex**

---

## 7.1 Appointment No-Show Prediction (Simple)

**What:** Predict which patients are likely to no-show for scheduled appointments to enable targeted reminders or overbooking strategies.

**Why simple:** Clear binary outcome. Abundant historical data. Low-stakes intervention (reminder). Model errors have minimal harm. Easy to measure and iterate.

---

## 7.2 Propensity to Pay Scoring (Simple)

**What:** Predict likelihood of patient self-pay collection to optimize collection efforts and early payment plan offers.

**Why simple:** Objective outcome (paid vs. not). Standard credit-scoring-like methodology. Ethical considerations exist but well-understood. Supports revenue cycle efficiency.

---

## 7.3 Patient Churn / Disenrollment Prediction (Simple-Medium)

**What:** Predict which patients are likely to leave the practice or health plan to enable retention interventions.

**Why this complexity:** Must infer intent from behavior. Intervention effectiveness varies. Competitive dynamics. Data may be sparse for new patients.

---

## 7.4 ED Visit Prediction (Medium)

**What:** Predict which patients are likely to have emergency department visits in the next 30-90 days for proactive outreach.

**Why medium:** Must distinguish avoidable vs. unavoidable ED use. Intervention requires care management capacity. Many social/behavioral factors beyond clinical data.

---

## 7.5 30-Day Readmission Risk (Medium)

**What:** Score patients at discharge for risk of 30-day hospital readmission to trigger care transition interventions.

**Why medium:** Well-studied problem with established benchmarks. Regulatory/quality measure implications. Intervention pathways exist. Must calibrate for case mix. Some factors are social, not clinical.

---

## 7.6 Rising Risk Identification (Medium-Complex)

**What:** Identify patients whose risk trajectory is increasing (not just high-risk) for earlier intervention before they become high-cost.

**Why this complexity:** Requires longitudinal modeling. Rate of change is harder than point-in-time risk. Earlier intervention = more uncertainty. Must optimize intervention timing.

---

## 7.7 Length of Stay Prediction (Medium-Complex)

**What:** Predict expected hospital length of stay at admission for discharge planning, bed management, and resource allocation.

**Why this complexity:** Many confounders (complications, social placement issues). Must update predictions as stay progresses. Operational integration with bed management. Accuracy expectations are high.

---

## 7.8 Disease Progression Modeling (Complex)

**What:** Predict trajectory of chronic disease progression (e.g., CKD stage progression, diabetes complications) to inform treatment intensity.

**Why complex:** Multi-year time horizons. Must account for treatment effects. Competes with clinical judgment. Requires explaining uncertainty. Model must be clinically credible.

---

## 7.9 Mortality Risk Scoring (ICU) (Complex)

**What:** Predict short-term mortality risk for ICU patients to support goals-of-care conversations and resource allocation.

**Why complex:** Highest-stakes prediction. Must be carefully calibrated across subgroups. Ethical considerations in use. Clinician trust essential. Self-fulfilling prophecy risks.

---

## 7.10 Optimal Intervention Timing Prediction (Complex)

**What:** Predict not just who is at risk but when is the optimal moment to intervene for maximum effectiveness.

**Why complex:** Requires causal reasoning. Must balance intervention burden with benefit. Limited data on intervention timing experiments. Pushes toward reinforcement learning territory.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Outcome stakes | Higher stakes = more validation |
| Time horizon | Longer horizons = more uncertainty |
| Intervention pathway | Must have action to take |
| Calibration needs | Probabilities must be meaningful |
| Fairness/bias | Risk scores often encode disparities |
| Clinician trust | High-stakes models need buy-in |

---

*Category 7 complete. Next: Category 8 (Natural Language Processing - non-LLM)*
