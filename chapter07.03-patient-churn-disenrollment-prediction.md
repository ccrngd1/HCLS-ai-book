# Recipe 7.3: Patient Churn / Disenrollment Prediction

**Complexity:** Simple-Medium · **Phase:** Growth · **Estimated Cost:** ~$0.002 per member per month (scoring)

---

## The Problem

Here's a scenario that plays out every January at health plans across the country. Open enrollment closes. The dust settles. And then the membership reports come in: 8% of your commercial book walked. 12% of your Medicare Advantage members switched plans. The network team is scrambling because two high-volume PCPs just lost enough patients to drop below panel minimums. The finance team is re-forecasting revenue. Everyone is asking the same question: "Could we have seen this coming?"

The answer, frustratingly, is usually yes. The signals were there months ago. The member who stopped filling prescriptions through your pharmacy benefit. The one who called three times about a denied claim and never got a satisfying answer. The family that moved to a zip code where your network is thin. The member who didn't schedule their annual wellness visit for the first time in four years.

Patient churn (or disenrollment, depending on whether you're a health plan or a provider organization) is one of those problems where the business impact is enormous and the data signals are surprisingly readable. A single Medicare Advantage member represents $12,000-$15,000 in annual revenue. A commercial family of four might be $25,000-$40,000. When you lose them, you don't just lose this year's revenue; you lose the lifetime value of a relationship you've already invested in building.

The cruel part: retention interventions actually work. A well-timed outreach from a care coordinator, a resolved grievance, a proactive network adequacy fix, a personalized benefits reminder during open enrollment. These things move the needle. But they only work if you know who to target and when to act. By the time someone submits a disenrollment form, it's too late. The decision was made weeks or months earlier.

This is a prediction problem. And it's one where the ROI math is straightforward enough that even skeptical CFOs will fund it.

---

## The Technology: Predicting Who Will Leave

### Churn Prediction as a Classification Problem

At its core, churn prediction is binary classification: will this member leave (1) or stay (0) within a defined future window? You train a model on historical data where you know the outcome (who actually left last year), and then apply it to current members to estimate their probability of leaving.

This sounds simple. It's not. Let me explain why.

The first challenge is defining "churn" precisely. In a health plan context, disenrollment is a discrete event: the member submits a form, or they fail to re-enroll during open enrollment, or their employer switches carriers. You have a clear timestamp. For provider organizations, "churn" is fuzzier. Did the patient leave, or did they just not need care for six months? A patient who hasn't visited in 18 months might be perfectly healthy, or they might have switched to a competitor. You need a working definition, and that definition shapes everything downstream.

The second challenge is the time horizon. Are you predicting churn in the next 30 days? 90 days? Before next open enrollment? Shorter horizons give you more actionable predictions but less time to intervene. Longer horizons are noisier but give your retention team room to work. Most health plan implementations target a 60-90 day window before open enrollment, because that's when interventions have the highest impact.

### Feature Engineering: What Signals Matter

The features that predict churn fall into several categories, and the best models use all of them:

**Engagement signals.** How is the member interacting with your organization? Declining appointment frequency, fewer portal logins, reduced prescription fills through your pharmacy benefit, fewer preventive care visits. These behavioral shifts often precede a conscious decision to leave. The absence of expected activity is as informative as the presence of unusual activity.

**Satisfaction signals.** Grievances filed, appeals submitted, call center contacts (especially repeated contacts about the same issue), survey scores (if you have them), time-to-resolution on complaints. A member who filed two grievances in the last quarter is not a happy member.

**Network adequacy signals.** Did the member's PCP leave your network? Did they move to a zip code where your nearest in-network specialist is 45 minutes away? Are they consistently going out-of-network for a specific service category? Network gaps are one of the strongest churn predictors, and they're often fixable.

**Financial signals.** Out-of-pocket cost trajectory, denied claims (especially for services the member expected to be covered), premium increases relative to competitors, cost-sharing surprises. Money is a powerful motivator for switching.

**Demographic and life event signals.** Age (Medicare members aging into different plan eligibility), employment changes (for employer-sponsored plans), address changes, family composition changes. These are often available from claims data or eligibility files.

**Competitive signals.** This is the hardest category to capture, but it matters. Are competitors entering your market with lower premiums? Did a new plan launch with a popular provider group in-network? Market-level data won't tell you about individual members, but it helps calibrate your baseline churn rate.

### The Model: Gradient Boosting Dominates Here

For tabular data with mixed feature types (numeric, categorical, temporal), gradient boosted trees (XGBoost, LightGBM, CatBoost) consistently outperform other approaches for churn prediction. They handle missing values gracefully (common in healthcare data), capture non-linear relationships without explicit feature engineering, and produce feature importance scores that help explain predictions to business stakeholders.

Deep learning approaches (LSTMs, transformers on event sequences) can capture temporal patterns that tree models miss, but they require substantially more data, more engineering effort, and more compute. For most health plan populations (tens of thousands to low millions of members), gradient boosting is the right starting point.

The model outputs a probability: "This member has a 73% chance of disenrolling before next open enrollment." That probability drives everything downstream: who gets outreach, what kind of outreach, and how urgently.

### Calibration Matters More Than Accuracy

Here's something that trips up teams new to churn prediction: raw accuracy is a terrible metric for this problem. If your baseline churn rate is 8%, a model that predicts "no churn" for everyone achieves 92% accuracy. Useless.

What you actually need is good calibration. When your model says "70% churn probability," roughly 70% of those members should actually churn. Calibrated probabilities let you set meaningful thresholds: "Intervene on everyone above 60%" becomes a statement with predictable volume and expected yield.

Precision-recall tradeoffs matter here too. A false positive (predicting churn for a member who would have stayed) costs you an unnecessary outreach call. A false negative (missing a member who actually leaves) costs you $12,000+ in lost revenue. The asymmetry is extreme. Most implementations optimize for recall (catch as many churners as possible) and accept lower precision (some unnecessary outreach is fine).

### The Cold Start Problem

New members are the hardest to score. A member who joined three months ago has almost no behavioral history with your organization. You can't measure "declining engagement" when you don't have a baseline. Most models handle this by either excluding members below a tenure threshold (e.g., less than 6 months) or using a separate model trained specifically on early-tenure features (demographics, plan selection patterns, initial engagement velocity).

---

## General Architecture Pattern

The churn prediction pipeline has four logical stages:

```
[Feature Store Assembly] → [Model Training / Scoring] → [Risk Stratification] → [Intervention Routing]
```

**Feature Store Assembly.** Aggregate raw data from multiple source systems (claims, eligibility, call center, portal activity, grievances, network directories) into a unified member-level feature set. This runs on a schedule (daily or weekly) and produces a wide table: one row per member, hundreds of columns representing their behavioral, financial, and demographic signals. The feature engineering here is the bulk of the work. Expect 60-70% of your development time to be spent getting features right.

**Model Training / Scoring.** Train the classification model on historical labeled data (members who churned vs. stayed in prior periods). Then score the current population on a regular cadence (weekly or monthly, depending on your intervention timeline). The output is a probability per member. Retraining happens less frequently (quarterly or when performance degrades), but scoring is ongoing.

**Risk Stratification.** Convert raw probabilities into actionable tiers. "High risk" (top 10%), "medium risk" (next 20%), "low risk" (everyone else). The tier boundaries are calibrated against your retention team's capacity: there's no point flagging 5,000 members as high-risk if your team can only handle 200 outreach calls per week.

**Intervention Routing.** Route high-risk members to the appropriate intervention based on their predicted churn reason. Network adequacy issues go to the network team. Grievance-related churn goes to member services. Cost-related churn might trigger a benefits counseling call. The routing logic is often rule-based on top of the model's feature importance: "This member is high-risk, and their top contributing features are out-of-network utilization and PCP departure."

The feedback loop is critical. Track which interventions were attempted, which members were retained, and feed that outcome data back into the next training cycle. Without this loop, you can't measure whether your model (or your interventions) are actually working.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.03-architecture). The Python example is linked from there.

## The Honest Take

I'll be direct about what surprised me building these systems.

The model is the easy part. Seriously. You can get a decent XGBoost model trained in an afternoon. The feature engineering takes weeks. Getting clean, timely data from six different source systems, each with its own update cadence, data quality issues, and access controls? That's the real project. Plan accordingly.

Calibration is non-negotiable but often skipped. I've seen teams deploy models where a "0.8 probability" actually corresponds to 30% churn. The business makes decisions based on those numbers. If your probabilities aren't calibrated, your intervention thresholds are meaningless and your ROI calculations are fiction.

The intervention matters more than the model. A perfect churn prediction with no retention program is just an expensive way to watch members leave. Before you build the model, make sure you have answers to: "What will we do differently for high-risk members?" If the answer is "nothing," save your money.

Seasonality will fool you. Churn in healthcare is heavily seasonal (open enrollment periods, annual renewal cycles). A model trained on January-March data and deployed in October will underperform because the feature distributions shift. Train on full annual cycles and include time-of-year features.

The ethical dimension is real. Churn models can inadvertently encode discrimination. If members in underserved zip codes have worse network adequacy and higher churn, your model learns "zip code predicts churn." The intervention might then focus retention efforts on members who are already well-served while ignoring the root cause (network gaps) for those who aren't. Monitor your model's predictions across demographic groups and ensure interventions address root causes, not just symptoms. Document your model's fairness characteristics in a model card: which features are included, which were excluded and why, and how predictions distribute across demographic groups. CMS and state regulators are increasingly scrutinizing algorithmic decision-making in health plans. Having a documented fairness analysis before you're asked for one is significantly less painful than producing one under regulatory pressure.

<!-- TODO (TechWriter): Expert review A1 (MEDIUM). Add a Step 6 for model monitoring: monthly ground truth join comparing predictions from 90 days ago against actual disenrollment outcomes, rolling AUC-PR and ECE computation published to CloudWatch, retraining trigger when AUC-PR drops below 0.40 or ECE exceeds 0.10. Especially important around open enrollment periods when population composition shifts. -->

---

## Related Recipes

- **Recipe 7.1 (Appointment No-Show Prediction):** Simpler binary classification problem that shares the same modeling infrastructure and feature engineering patterns
- **Recipe 7.2 (Propensity to Pay Scoring):** Similar survival/classification approach applied to financial outcomes rather than membership retention
- **Recipe 7.6 (Rising Risk Identification):** Extends the temporal trend features used here into a full trajectory model for clinical risk
- **Recipe 6.2 (Utilization Pattern Segmentation):** The clustering approach from 6.2 can feed churn models as a feature (which utilization segment does this member belong to?)
- **Recipe 4.6 (Care Gap Prioritization):** Retention interventions often involve closing care gaps; this recipe provides the prioritization logic

---

## Tags

`predictive-analytics` · `churn` · `disenrollment` · `retention` · `xgboost` · `sagemaker` · `glue` · `classification` · `health-plan` · `member-engagement` · `hipaa` · `simple-medium`

---

*← [Recipe 7.2: Propensity to Pay Scoring](chapter07.02-propensity-to-pay-scoring) · [Chapter 7 Index](chapter07-preface) · [Next: Recipe 7.4: ED Visit Prediction →](chapter07.04-ed-visit-prediction)*
