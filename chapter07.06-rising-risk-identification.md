# Recipe 7.6: Rising Risk Identification

**Complexity:** Medium-Complex · **Phase:** Growth · **Estimated Cost:** ~$0.01 per patient per scoring cycle

---

## The Problem

Every health system has a list of high-risk patients. The sickest 5% of the population drives 50% of the cost. Care management teams know who these people are. They have names, diagnoses, care plans, and dedicated nurses assigned to them.

The problem is not identifying who is already high-risk. The problem is identifying who is *becoming* high-risk.

By the time a patient shows up on the high-cost list, the window for cost-effective intervention has usually closed. They've already had the hospitalization, the ED visit, the crisis event that pushed them over the threshold. The care management team inherits them after the damage is done, and the interventions available at that point are expensive, reactive, and often too late to change the trajectory.

Rising risk identification flips the timing. Instead of asking "who is sick right now?" you ask "who is getting sicker?" Instead of a point-in-time snapshot, you're looking at the slope of the line. A patient with well-controlled diabetes whose A1c has crept from 7.2 to 8.1 to 9.4 over three visits is not yet "high-risk" by most static scoring systems. But the trajectory is unmistakable. In six months, without intervention, they'll be in the ED with diabetic ketoacidosis.

This is the fundamental insight: the rate of change in risk is more actionable than the absolute level of risk. A patient at 60th percentile risk who was at 30th percentile six months ago is a better intervention target than a patient who has been stable at 80th percentile for three years. The first patient is deteriorating and might respond to intervention. The second patient is chronically complex but stable, and their care plan is probably already optimized.

Health plans and ACOs care about this intensely because of the economics. Intervening on a rising-risk patient before they cross into high-cost territory costs maybe $2,000-5,000 in care management resources. Letting them cross that threshold costs $50,000-100,000 in acute care. The ROI math is compelling, but only if you can identify the right patients early enough for the intervention to matter.

The challenge: this is a fundamentally harder prediction problem than static risk scoring. You're not just predicting an outcome. You're predicting a change in trajectory. That requires longitudinal data, temporal modeling, and a clear definition of what "rising" actually means in quantitative terms.

---

## The Technology: Detecting Trajectory Changes

### Why Static Risk Scores Miss This

Traditional risk scoring (HCC-based risk adjustment, LACE scores, Charlson comorbidity indices) produces a point-in-time estimate. It answers: "Given everything we know about this patient right now, what is their expected cost or utilization?" These scores are useful for population stratification, but they have a structural blind spot: they don't model change over time.

Consider two patients, both with a current HCC risk score of 1.8 (meaning expected cost is 1.8x the average). Patient A has been at 1.8 for three years. Patient B was at 0.9 twelve months ago and has climbed steadily to 1.8. Static scoring treats them identically. But operationally, they're completely different situations. Patient A is stable and probably already in a care management program. Patient B is deteriorating rapidly and may not be on anyone's radar yet.

Rising risk identification requires temporal awareness. You need to track risk over time and detect meaningful acceleration.

### Defining "Rising Risk" Mathematically

This is where it gets interesting, because "rising risk" is not a single well-defined concept. There are several reasonable definitions, and the right one depends on your intervention model:

**Absolute change.** The simplest: risk score increased by more than X points over Y months. Easy to compute, easy to explain. But it treats a change from 0.5 to 0.8 the same as a change from 2.0 to 2.3, even though the clinical implications are very different.

**Relative change.** Risk score increased by more than X% over Y months. Better at capturing proportional deterioration. A 50% increase from 0.6 to 0.9 is arguably more alarming than a 15% increase from 2.0 to 2.3. But relative change can be noisy for patients with very low baseline scores (a change from 0.1 to 0.2 is a 100% increase but clinically meaningless).

**Percentile migration.** The patient moved from one risk tier to a higher one (e.g., from the 40th to the 70th percentile of the population). This is intuitive for care managers because it maps directly to their stratification tiers. But it depends on the population distribution, which shifts over time.

**Slope of the trajectory.** Fit a line (or curve) to the patient's risk scores over multiple time points and use the slope as the "rising" indicator. This is the most statistically rigorous approach because it uses all available history, not just two endpoints. It's also more robust to noise: a single anomalous score won't trigger a false alarm if the overall trend is flat.

**Predicted future state.** Train a model to predict what the patient's risk score will be in 6-12 months, then flag patients whose predicted future score crosses a threshold. This is the most sophisticated approach but also the most complex to build and validate.

In practice, most production systems use a combination: slope-based detection for the primary signal, with absolute thresholds as guardrails (don't flag someone whose risk is rising but still very low in absolute terms).

### The Longitudinal Modeling Challenge

Rising risk detection requires multiple observations per patient over time. This creates several technical challenges that don't exist in point-in-time prediction:

**Irregular observation intervals.** Patients don't visit on a fixed schedule. One patient might have monthly lab draws; another might go a year between visits. You can't simply compare "this month's score" to "last month's score" because the time gaps vary wildly. Your model needs to handle irregular time series gracefully, either by interpolating to fixed intervals or by using methods that natively handle irregular spacing.

**Informative missingness.** A patient who stops showing up for appointments is not "missing data" in the traditional sense. The absence itself is informative. Patients who disengage from care often do so because they're getting sicker (too sick to come in, lost transportation, gave up). If your model only scores patients when new data arrives, you'll systematically miss the ones who are deteriorating silently. You need a mechanism to flag patients whose data has gone stale.

**Confounding events.** A patient's risk score might jump because they received a new diagnosis that was actually present for years but only recently documented. That's not true clinical deterioration; it's documentation catch-up. Similarly, a patient transitioning from one insurance plan to another might have their claims history reset, creating an artificial trajectory change. Your model needs to distinguish genuine clinical deterioration from data artifacts.

**Regression to the mean.** Patients identified as "rising risk" based on recent score increases will, on average, partially revert even without intervention. This is a statistical phenomenon, not a clinical one. It makes it genuinely hard to measure whether your interventions are working, because some of the "improvement" you observe would have happened anyway. Proper evaluation requires a control group or at minimum a regression-adjusted comparison.

### Equity and Bias Considerations

Rising risk models inherit the biases of their input data and underlying risk scores, and trajectory detection introduces additional equity concerns that are easy to overlook.

**Differential data density.** Patients with sparse visit histories (fewer than 3 scoring cycles) fall into the INSUFFICIENT_HISTORY category and are invisible to the trajectory model. This isn't random. Patients who face transportation barriers, lack insurance coverage, or distrust the healthcare system generate less data. The model systematically cannot detect rising risk in the populations that often need intervention most. If 15% of your Medicaid population has insufficient history compared to 3% of your commercial population, you have an equity problem baked into the detection threshold.

**Inherited model bias.** The underlying risk scores themselves carry bias. Obermeyer et al. (2019) demonstrated that a widely-used commercial risk algorithm systematically underestimated the health needs of Black patients because it used cost as a proxy for illness. If your trajectory model sits on top of a biased risk score, it will detect rising risk less reliably for the groups the base model underscores. A patient whose true risk is rising may show a flat trajectory because the base model never assigned them an appropriately high score to begin with.

**Threshold equity across demographic groups.** A single set of detection thresholds (slope > 0.05, delta > 0.20) may perform differently across demographic groups. If one population has systematically lower baseline scores due to model bias, the same absolute delta threshold is effectively harder for them to trigger. Relative thresholds help but don't fully solve this. You need to audit flag rates across race, ethnicity, age, gender, and payer type to confirm that the model flags proportional to true clinical need, not proportional to data availability.

**Intervention allocation fairness.** Even if detection is equitable, routing and prioritization may not be. If the prioritization algorithm ranks by absolute score (higher score = higher priority), patients from under-scored populations will consistently rank lower even when their trajectories are equally alarming. Prioritize by trajectory severity (slope, acceleration) rather than absolute score level to reduce this effect.

**Mitigation strategies:**

- Audit flag rates by demographic group at every threshold change. If flag rates diverge significantly from expected disease burden patterns, investigate whether the model or the thresholds are the source.
- Consider group-specific threshold calibration where justified by evidence of differential model performance. This is controversial but may be necessary if the base risk model has known calibration differences across groups.
- Implement proactive outreach for the INSUFFICIENT_HISTORY population. These patients cannot benefit from trajectory detection, so they need a separate pathway (e.g., outreach based on time since last engagement, or community health worker referral).
- Report equity metrics alongside operational metrics. Track the demographic composition of flagged patients, patients with insufficient history, and patients who received intervention. Surface disparities to clinical leadership alongside the pipeline's performance metrics.

### Feature Engineering for Trajectory Detection

The features that predict rising risk are different from those that predict current risk. You need both levels and changes:

**Score deltas.** Change in risk score over 3, 6, and 12-month windows. Both absolute and relative. The multi-window approach captures both rapid deterioration (3-month spike) and slow drift (12-month gradual increase).

**Utilization acceleration.** Not just "how many ED visits" but "are ED visits increasing?" A patient who went from 0 ED visits in Q1 to 1 in Q2 to 3 in Q3 is on a concerning trajectory even if their total count isn't alarming yet.

**Clinical marker trends.** Lab values trending in the wrong direction: rising A1c, declining eGFR, increasing BNP. These are leading indicators that often precede acute events by months. The slope of the lab trend is more predictive than the current value for rising risk detection.

**Care engagement changes.** Missed appointments increasing, medication refill gaps widening, time since last PCP visit growing. Disengagement from care is both a risk factor and a detectable signal.

**New diagnosis velocity.** The rate at which new chronic conditions are being added. A patient who picks up three new diagnoses in six months is on a different trajectory than one who has been stable for years.

**Social determinant shifts.** When available: address changes (especially to higher-deprivation areas), insurance coverage gaps, loss of caregiver support. These are powerful predictors but rarely captured in structured data.

### Model Architecture Options

**Sequential risk scoring with delta analysis.** The simplest approach: run your existing point-in-time risk model on a regular schedule (monthly or quarterly), store the scores, and compute deltas. Flag patients whose delta exceeds a threshold. This requires no new model training; it just adds a temporal layer on top of your existing risk stratification. The downside: it only captures what your existing model measures, and it's sensitive to model version changes (if you retrain the underlying model, all deltas become meaningless until the new scores stabilize).

**Dedicated trajectory model.** Train a separate model specifically to predict risk acceleration. The target variable is not "will this patient be high-cost?" but "will this patient's cost increase by more than X% in the next 12 months?" This model can use trajectory features (slopes, deltas, acceleration) as first-class inputs rather than bolting them on after the fact. It typically outperforms the delta approach but requires more engineering and a separate training pipeline.

**Recurrent or sequence models.** Use the full sequence of a patient's clinical events (encounters, diagnoses, labs, medications) as input to a recurrent neural network or transformer. These models can learn complex temporal patterns without explicit feature engineering. They're powerful but require large datasets, significant compute, and are harder to interpret. For most health systems, gradient boosting on engineered trajectory features is the practical choice.

**Survival analysis with time-varying covariates.** Model the time until a patient transitions from low/medium risk to high risk, with covariates that update over time. Cox proportional hazards with time-varying covariates or discrete-time survival models can capture the dynamics naturally. This framing is particularly useful when you care about *when* the transition will happen, not just *whether* it will.

### Intervention Timing: The Optimization Problem

Identifying rising-risk patients is only half the problem. The other half is deciding when to intervene. Too early, and you're spending resources on patients who might have stabilized on their own. Too late, and the intervention can't change the trajectory. The optimal intervention point depends on:

**Intervention lead time.** How long does it take for the intervention to have an effect? A care management enrollment might take 2-4 weeks to produce measurable behavior change. If you wait until the patient is 30 days from a hospitalization, you've missed the window.

**Trajectory confidence.** How many data points do you need before you're confident the trend is real and not noise? Two consecutive score increases might be random variation. Four consecutive increases over 12 months is a pattern. There's a tension between acting early (when you have less certainty) and acting late (when you have more certainty but less time).

**Intervention capacity.** Your care management team can handle N new enrollments per month. If your model flags 500 patients but you can only serve 50, you need to prioritize. The prioritization should consider both the severity of the trajectory and the likelihood that intervention will change it.

---

## General Architecture Pattern

The rising risk pipeline operates on a different cadence than real-time scoring. It's a batch process that runs periodically (weekly or monthly), compares current state to historical state, and produces a ranked list of patients whose trajectories warrant attention.

```text
[Periodic Risk Scoring] → [Score History Storage] → [Trajectory Computation] → [Rising Risk Detection] → [Prioritization & Routing]
```

**Periodic Risk Scoring.** On a regular schedule, compute risk scores for the entire managed population. This might use an existing risk model (HCC, proprietary, or custom ML) or a purpose-built trajectory model. The key requirement is consistency: the same model version must be used across scoring cycles, or score comparisons become meaningless.

**Score History Storage.** Every scoring cycle's results are stored with timestamps, creating a longitudinal record of each patient's risk trajectory. This is a time-series storage problem: millions of patients, each with a score at each cycle, potentially going back years. The storage must support efficient queries like "give me all scores for patient X over the last 24 months" and "give me all patients whose most recent score exceeds their score from 6 months ago by more than 0.5."

**Trajectory Computation.** For each patient, compute trajectory metrics: slope over multiple windows, acceleration (change in slope), percentile migration, and time since last significant change. This is computationally intensive at population scale but embarrassingly parallel (each patient's trajectory is independent).

**Rising Risk Detection.** Apply detection rules or a trained model to the trajectory metrics to identify patients whose risk is meaningfully increasing. This produces a candidate list with associated confidence scores and trajectory summaries.

**Prioritization and Routing.** Rank the candidates by intervention urgency and likelihood of benefit. Route to the appropriate care management program based on the nature of the risk increase (behavioral health escalation goes to BH care managers; chronic disease acceleration goes to disease management; social determinant deterioration goes to community health workers).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.06-architecture). The Python example is linked from there.

## The Honest Take

Rising risk identification is one of those problems that sounds straightforward until you try to measure whether it's working. The detection part is genuinely tractable: compute slopes, set thresholds, flag patients. You can build a working prototype in a few weeks. The hard part is everything that comes after.

The biggest surprise: regression to the mean is a much larger confounder than most teams realize. If you flag the top 5% of "risers" and intervene, roughly half of them would have reverted toward their baseline even without your intervention. That means your apparent 40% success rate might actually be a 20% success rate with 20% regression to the mean. Separating the two requires either a control group (which means deliberately not helping some patients, which is ethically fraught) or statistical methods that most care management teams don't have access to.

The second surprise: the definition of "rising risk" is a policy decision, not a technical one. Different thresholds produce wildly different patient lists. A slope threshold of 0.02/month flags 8% of your population. A threshold of 0.05/month flags 1.5%. Both are "correct" in a technical sense. The right answer depends on your intervention capacity, your cost-effectiveness threshold, and your organizational risk tolerance. Expect to spend more time calibrating thresholds with clinical and operational leadership than building the model.

The thing I'd do differently: start with the intervention capacity constraint and work backward. If your care management team can absorb 50 new patients per month, your model needs to produce approximately 50 high-confidence flags per month. Design the thresholds to match the operational reality, not the other way around.

---

## Related Recipes

- **Recipe 7.4 (ED Visit Prediction):** Rising risk patients often present with increased ED utilization as an early signal; the ED prediction model's features overlap significantly with rising risk trajectory features
- **Recipe 7.5 (30-Day Readmission Risk):** Readmission scoring is a point-in-time complement to trajectory analysis; patients flagged as rising risk who are then hospitalized should receive both scores at discharge
- **Recipe 7.8 (Disease Progression Modeling):** Disease-specific progression models provide more granular trajectory information for patients with identified chronic conditions
- **Recipe 12.4 (Lab Result Trend Analysis):** Lab trends are leading indicators for rising risk; the time series methods in 12.4 can feed directly into the trajectory features used here
- **Recipe 4.7 (Care Management Program Enrollment):** The downstream consumer of rising risk flags; defines how flagged patients are matched to appropriate intervention programs

---

## Tags

`predictive-analytics` · `risk-scoring` · `rising-risk` · `trajectory` · `longitudinal` · `care-management` · `population-health` · `sagemaker` · `glue` · `batch-processing` · `time-series` · `hipaa`

---

*← [Recipe 7.5: 30-Day Readmission Risk](chapter07.05-30-day-readmission-risk) · [Chapter 7 Index](chapter07-preface) · [Next: Recipe 7.7 →](chapter07.07-length-of-stay-prediction)*
