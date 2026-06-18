# Recipe 7.10: Optimal Intervention Timing Prediction

**Complexity:** Complex · **Phase:** Research/Pilot · **Estimated Cost:** ~$2,500-8,000/month (model training + inference)

---

## The Problem

Here's the scenario that plays out thousands of times a day across every health system in the country: a care manager has a panel of 200 patients with diabetes. She knows 30 of them are "high risk." She has capacity to make maybe 8 meaningful outreach calls this week. The question isn't who to call. She already knows who's struggling. The question is *when* to call.

Call too early, and the patient isn't ready to engage. They feel fine. They haven't missed a refill yet. Your intervention lands on deaf ears and you've burned a slot. Call too late, and the patient is already in the ED with DKA. Your intervention would have mattered three weeks ago. The window closed.

This is the timing problem, and it's one of the hardest unsolved challenges in population health. Most predictive models in healthcare answer "who is at risk?" That's table stakes at this point. The genuinely hard question is "when is the right moment to act?" And the answer changes for every patient, every condition, and every type of intervention.

The stakes are real. A well-timed phone call from a care manager can prevent a hospitalization that costs $15,000. A poorly timed one wastes $50 of staff time and, worse, trains the patient to ignore future outreach. The difference between those outcomes often comes down to days or weeks of timing.

Traditional risk scoring gives you a static snapshot: this patient is high risk right now. But risk isn't static. It fluctuates. A patient's risk might be elevated for months without anything bad happening, then spike sharply in the 72 hours before a crisis. If you could detect that inflection point, that transition from "chronically elevated" to "acutely deteriorating," you'd know exactly when to intervene.

This is where we're headed. Not just predicting risk, but predicting the optimal intervention window.

---

## The Technology: Predicting When to Act

### Beyond Point-in-Time Risk Scores

Most healthcare risk models produce a single number: "this patient has a 23% probability of readmission in the next 30 days." That's useful for prioritization, but it tells you nothing about timing. Is that 23% evenly distributed across the 30 days? Or is there a 2% daily risk for the first 25 days that spikes to 15% daily risk in the final 5? Those two scenarios demand completely different intervention strategies.

Optimal intervention timing requires modeling risk as a trajectory, not a point. You need to understand how risk evolves over time for each individual patient, and you need to identify the moments where that trajectory is most amenable to change.

### Survival Analysis and Hazard Functions

The mathematical foundation here is survival analysis, specifically time-to-event modeling. Instead of asking "will this patient have an event?" you ask "when will this patient have an event, and how does that timing change based on what we observe?"

The hazard function is the key concept. It represents the instantaneous rate of event occurrence at any given time, conditional on the patient having survived to that point. A rising hazard means the patient is entering a danger zone. A stable hazard means they're in a steady state. The derivative of the hazard (is it accelerating?) tells you whether the window for intervention is opening or closing.

Classical survival models (Cox proportional hazards) assume the effect of covariates is constant over time. That's a terrible assumption for healthcare. The impact of a missed medication refill on readmission risk isn't constant; it grows over time as the patient's condition destabilizes. Modern approaches use time-varying covariates and non-proportional hazard models to capture these dynamics.

### Dynamic Survival Models

The state of the art for this problem uses recurrent neural networks or transformer architectures applied to longitudinal patient data. The idea is straightforward: feed the model a sequence of clinical events (lab results, medication fills, vital signs, encounters) ordered by time, and have it predict the hazard function at each time step.

These models learn temporal patterns that static models miss entirely. They can detect that a patient whose A1C has been rising for three consecutive quarters, who just had a medication change, and who missed their last endocrinology appointment is entering a critical window. Not because any single factor is alarming, but because the combination and sequence signal an inflection point.

The key architectures:

**Recurrent Neural Survival Models.** LSTM or GRU networks that process event sequences and output a hazard estimate at each time step. They naturally handle irregular time intervals (common in healthcare data) and can incorporate both continuous features (lab values) and discrete events (encounters, prescriptions).

**Transformer-based Event Models.** Self-attention mechanisms that can look across the entire patient history to identify relevant patterns. Better at capturing long-range dependencies (that hospitalization 18 months ago is relevant to today's risk) but more computationally expensive.

**Counterfactual Timing Models.** This is where it gets genuinely interesting. These models don't just predict when an event will happen; they estimate what would happen if you intervened at different time points. "If we call this patient today, their 30-day event probability drops by X%. If we wait a week, it drops by Y%." This requires causal inference techniques layered on top of the survival model.

### The Causal Inference Challenge

Here's the fundamental difficulty: you want to know the optimal time to intervene, but you can only observe what actually happened. If you intervened on day 5 and the patient did fine, you don't know whether they would have done fine anyway, or whether your intervention prevented a crisis. If you didn't intervene and the patient had an event on day 12, you don't know whether intervening on day 5 would have prevented it.

This is the counterfactual problem, and it's why optimal timing prediction pushes toward causal reasoning rather than pure prediction.

Approaches to handle this:

**Inverse probability of treatment weighting (IPTW).** Reweight historical observations to simulate what would have happened under different intervention timing strategies. Requires strong assumptions about what drove historical intervention decisions.

**G-computation and structural marginal models.** Estimate the causal effect of intervention at each time point by modeling the full data-generating process. More flexible than IPTW but computationally intensive.

**Reinforcement learning framing.** Treat the intervention timing decision as a sequential decision problem where the "agent" (care manager) takes actions (intervene or wait) at each time step and receives rewards (patient outcomes). This is the most natural framing but requires the most data and the most careful validation. (See Chapter 15 for full RL treatment.)

For most healthcare organizations starting this work, the practical approach is a hybrid: use a dynamic survival model to predict risk trajectories, then apply simple decision rules about when the trajectory crosses actionable thresholds. Save the full causal/RL approach for when you have the data volume and the organizational maturity to validate it properly.

### What Makes Timing Prediction Uniquely Hard

**Sparse positive events.** The events you're trying to time (hospitalizations, ED visits, crises) are relatively rare for any individual patient. You might have years of longitudinal data with only one or two events per patient. Training models on sparse events with precise timing requirements is significantly harder than training binary classifiers.

**Irregular observation intervals.** Patients don't generate data on a regular schedule. A healthy patient might have one encounter per year. A complex patient might have weekly labs, monthly visits, and daily medication fills. Your model needs to handle both, and it needs to reason about the absence of data (no lab results for 6 months might itself be a signal).

**Intervention effects are heterogeneous.** A phone call works differently for different patients at different times. Some patients respond to early outreach. Others only engage when they're already feeling the consequences of non-adherence. The optimal timing depends on the patient's engagement style, which you may not observe directly.

**The self-fulfilling prophecy problem.** If your model successfully identifies patients at the right time and you intervene, those patients won't have events. Your training data then shows "model flagged patient, patient was fine" which looks like a false positive. Over time, successful intervention erodes the signal your model was trained on. This is a well-known problem in healthcare ML and requires careful study design to avoid.

---

## General Architecture Pattern

```text
[Longitudinal Data Assembly] → [Feature Engineering (Temporal)] → [Dynamic Survival Model] → [Intervention Window Scoring] → [Decision Engine] → [Care Team Delivery]
```
**Longitudinal Data Assembly.** Collect and align all patient events on a unified timeline: encounters, labs, medications, vitals, claims, social determinants. This is the hardest engineering step. Healthcare data lives in dozens of systems with different identifiers, different time granularities, and different latencies. You need a patient-level event stream that's reasonably complete and reasonably current.

**Feature Engineering (Temporal).** Transform raw events into features that capture temporal dynamics: rate of change in lab values, days since last medication fill, gap between scheduled and actual appointments, acceleration of utilization. These temporal features are what distinguish timing models from static risk scores.

**Dynamic Survival Model.** Train a model that takes the temporal feature sequence as input and outputs a hazard estimate at each time step. The model should produce both a point estimate (current hazard) and a trajectory forecast (predicted hazard over the next N days). The trajectory is what enables timing decisions.

**Intervention Window Scoring.** Apply decision logic to the model output: when is the hazard rising fast enough to warrant intervention, but not so high that the window has already closed? This is where clinical judgment meets model output. The scoring function encodes beliefs about intervention effectiveness at different risk levels.

**Decision Engine.** Combine the intervention window score with operational constraints: care manager capacity, patient preferences, channel availability (phone, text, in-person), time of day. The output is a prioritized, actionable worklist with recommended timing.

<!-- TODO (TechWriter): Expert review SEC-1 (HIGH). Add data minimization guidance for the delivery layer: (1) row-level access control so care managers see only their assigned patients; (2) consider coded explanations with deep links to the patient chart rather than embedding full clinical detail in the worklist; (3) if full clinical detail is included, the care management platform must meet the same encryption and access logging requirements as the EHR. -->

**Care Team Delivery.** Surface the recommendation to the care team through their existing workflow tools (EHR task lists, care management platforms, mobile apps). Include the "why now" explanation: what changed in this patient's trajectory that makes today the right day to act.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter07.10-architecture). The Python example is linked from there.

## The Honest Take

This is one of the hardest problems in healthcare ML, and I want to be upfront about that. Most organizations that attempt optimal timing prediction end up building a really good risk score and calling it a timing model. That's not nothing. A good risk score with a velocity component (is risk rising?) gets you 70% of the value of true timing optimization. But it's not the same thing.

The causal inference piece is where everyone gets stuck. You want to know "if I intervene on day 5, what happens?" but your historical data only shows you what happened when someone did or didn't intervene based on whatever ad hoc criteria they were using at the time. Disentangling the causal effect of intervention timing from the selection bias in who got intervened on and when is genuinely hard. Most teams punt on this and use the simpler "rising risk" heuristic. That's a reasonable choice.

The part that surprised me most: intervention fatigue is a bigger deal than most models account for. If you call a patient every week because your model keeps flagging them, they stop answering. The optimal timing model needs to account for its own previous recommendations, which creates a feedback loop that's tricky to handle correctly.

The self-fulfilling prophecy problem is real and insidious. Your model gets better at identifying the right patients at the right time. You intervene. They don't have events. Your next training cycle sees "model flagged, no event" and learns to flag less aggressively. Over 2-3 retraining cycles, the model can degrade significantly. You need a holdout strategy (randomly withhold intervention for a small percentage of flagged patients) to maintain the training signal, and that raises ethical questions about withholding care from patients you believe are at risk.

A few guardrails on holdout designs: they're only appropriate for low-intensity interventions (outreach calls, reminders) where standard of care is already met without the model. IRB review is required for any prospective holdout. Natural variation in care manager capacity creates quasi-experimental conditions without deliberate withholding, and that's often sufficient. Never withhold clinical interventions (medication changes, referrals) for model training purposes.

Start with the hybrid approach: dynamic survival model for trajectory prediction, simple decision rules for timing. Get that working, measure whether it improves outcomes compared to static risk scoring, and only then invest in the full causal/RL approach. The infrastructure you build for the simple version is the same infrastructure the complex version needs.

One more thing: deploy in shadow mode first. Generate recommendations without surfacing them to the care team, and compare against actual care team decisions. Have a clinical advisory board review the threshold settings and decision logic. Run a prospective pilot with defined success metrics (intervention acceptance rate, event prevention rate) before full rollout. The model needs to earn trust before it gets to influence care delivery.

---

## Related Recipes

- **Recipe 7.6 (Rising Risk Identification):** Identifies patients whose risk trajectory is increasing; this recipe extends that concept to determine the optimal moment to act on that rising risk
- **Recipe 7.5 (30-Day Readmission Risk):** Provides the foundational risk scoring that timing prediction builds upon; timing adds the "when" to readmission's "who"
- **Recipe 7.8 (Disease Progression Modeling):** Models long-term disease trajectories; timing prediction uses similar longitudinal modeling but focuses on short-term intervention windows
- **Recipe 12.8 (Disease Progression Trajectory Modeling):** Time series approach to trajectory modeling that complements the survival analysis approach used here
- **Recipe 15.1 (Adaptive Treatment Policies):** Full reinforcement learning treatment of the sequential intervention decision problem that this recipe's simpler heuristics approximate

---

## Tags

`predictive-analytics` · `risk-scoring` · `survival-analysis` · `intervention-timing` · `causal-inference` · `sagemaker` · `kinesis` · `glue` · `dynamodb` · `complex` · `research` · `longitudinal` · `care-management` · `population-health` · `hipaa`

---

*← [Recipe 7.9: Mortality Risk Scoring (ICU)](chapter07.09-mortality-risk-scoring-icu) · [Chapter 7 Index](chapter07-preface) · [Next: Chapter 8 →](chapter08-preface)*
