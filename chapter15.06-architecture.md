# Recipe 15.6 Architecture and Implementation: Glucose Control in ICU

*Companion to [Recipe 15.6: Glucose Control in ICU](chapter15.06-glucose-control-icu). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## Why These Services

**Amazon SageMaker for model training and hosting.** RL model training requires GPU instances for batch processing of historical episodes, hyperparameter tuning across reward formulations, and model versioning. SageMaker provides managed training jobs with spot instance support (RL training is fault-tolerant and restartable), model registry for versioning policies, and real-time endpoints for inference. The SageMaker RL toolkit supports custom environments, which you'll need for the glucose simulator integration.

**Amazon S3 for episode storage.** Historical patient episodes (state-action-reward sequences) are large, immutable datasets that get reprocessed as you iterate on state representations and reward functions. S3 is the natural landing zone: durable, versioned, and directly accessible from SageMaker training jobs.

**AWS Lambda for real-time inference orchestration.** When a nurse enters a new glucose reading, the system needs to construct the current state, call the policy endpoint, apply safety constraints, and return a recommendation within seconds. Lambda handles this stateless orchestration cleanly.

**Amazon DynamoDB for patient state tracking.** The RL agent needs the patient's recent history (last N glucose readings, current insulin infusion rate, nutrition status) to construct the state vector. DynamoDB provides low-latency key-value access for per-patient state that updates with each new measurement.

**Amazon CloudWatch for monitoring and alerting.** Track recommendation acceptance rates, override patterns, glucose outcomes for patients where recommendations were followed vs. overridden, and model drift indicators. Alert on anomalous recommendation patterns (e.g., consistently recommending maximum doses).

**AWS Step Functions for the training pipeline.** The offline training pipeline (data extraction, episode construction, training, evaluation, model registration) is a multi-step workflow that runs periodically as new data accumulates. Step Functions orchestrates this cleanly with error handling and retry logic.

## Architecture Diagram

```mermaid
flowchart TB
    subgraph Data Pipeline
        A[EHR Data Lake\nS3] -->|Extract Episodes| B[Step Functions\nEpisode Builder]
        B --> C[S3\nTraining Episodes]
    end

    subgraph Training
        C --> D[SageMaker Training\nOffline RL]
        D --> E[SageMaker Model Registry\nPolicy Versions]
        D --> F[SageMaker Endpoint\nPolicy Inference]
    end

    subgraph Real-Time Inference
        G[New Glucose Reading] --> H[Lambda\nState Constructor]
        H -->|Fetch History| I[DynamoDB\nPatient State]
        H -->|Get Recommendation| F
        F --> J[Lambda\nSafety Constraints]
        J --> K[Recommendation\nto Clinician]
    end

    subgraph Monitoring
        K --> L[CloudWatch\nOutcome Tracking]
        L --> M[Alarm\nDrift Detection]
    end

    style C fill:#f9f,stroke:#333
    style F fill:#ff9,stroke:#333
    style I fill:#9ff,stroke:#333
```

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker, Amazon S3, AWS Lambda, Amazon DynamoDB, AWS Step Functions, Amazon CloudWatch |
| **IAM Permissions** | `sagemaker:CreateTrainingJob`, `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:GetItem`, `dynamodb:PutItem`, `states:StartExecution` |
| **BAA** | AWS BAA signed (required: glucose readings and insulin doses are PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest; SageMaker: KMS for training volumes and endpoints; all API calls over TLS |
| **VPC** | Production: Lambda and SageMaker in VPC with VPC endpoints for S3, DynamoDB, SageMaker Runtime, CloudWatch Logs, Step Functions, and KMS |
| **CloudTrail** | Enabled: log all SageMaker and DynamoDB API calls for audit trail |
| **Historical Data** | Minimum 5,000-10,000 ICU stays with hourly glucose measurements, insulin administration records, nutrition data, and outcome labels. De-identified for development; BAA-covered for production. |
| **Cost Estimate** | Training: ~$50-200 per training run (ml.g4dn.xlarge spot instances, 4-8 hours). Inference endpoint: ~$100/month (ml.m5.large). DynamoDB and Lambda: negligible at clinical volumes. |

## Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Trains offline RL policy, hosts inference endpoint, manages model versions |
| **Amazon S3** | Stores training episodes, model artifacts, evaluation results |
| **AWS Lambda** | Constructs patient state, orchestrates inference, applies safety constraints |
| **Amazon DynamoDB** | Tracks per-patient state history for real-time state construction |
| **AWS Step Functions** | Orchestrates periodic retraining pipeline |
| **Amazon CloudWatch** | Monitors recommendation patterns, outcome tracking, drift detection |
| **AWS KMS** | Manages encryption keys for all PHI-containing services |

## Pseudocode Walkthrough

**Step 1: Episode construction from EHR data.** The first challenge is transforming raw EHR data into RL episodes. An episode is one ICU stay, discretized into decision intervals (typically 1-4 hours). At each timestep, you need the state (what the clinician observed), the action (what they did), and the reward (how things turned out). This step is where most of the engineering effort lives. EHR data is messy: glucose measurements come from different sources (point-of-care meters, arterial blood gas analyzers, continuous glucose monitors) with different accuracies and different timestamps. Insulin orders don't always align with administration times, and nutrition changes happen asynchronously. You need to bin everything into consistent time windows and handle missing data gracefully. Skip this step or do it poorly, and your RL agent learns from garbage.

```pseudocode
FUNCTION build_episode(patient_icu_stay):
    // Discretize the ICU stay into fixed-length decision intervals.
    // 4 hours is common: it matches typical glucose check frequency.
    timestep_hours = 4
    episode = empty list

    FOR each interval in partition_stay(patient_icu_stay, timestep_hours):

        // Construct the state vector: everything the clinician could observe
        // at the start of this interval.
        state = {
            glucose_current:     most recent glucose in this interval (mg/dL),
            glucose_prev_1:      glucose from previous interval,
            glucose_prev_2:      glucose from 2 intervals ago,
            glucose_velocity:    (glucose_current - glucose_prev_1) / timestep_hours,
            insulin_on_board:    total insulin given in last 4 hours (units),
            insulin_infusion:    current insulin drip rate (units/hour) or 0 if subcutaneous,
            nutrition_rate:      current enteral/parenteral nutrition (kcal/hour),
            vasopressor_dose:    norepinephrine equivalent dose (mcg/kg/min),
            steroid_flag:        1 if on corticosteroids (these spike glucose), 0 otherwise,
            creatinine:          most recent value (renal function affects insulin clearance),
            bmi:                 patient BMI (affects insulin sensitivity),
            apache_score:        illness severity score at admission
        }

        // The action: what insulin dose was actually given during this interval.
        // Discretize into bins for tabular RL, or keep continuous for actor-critic methods.
        action = total_insulin_given_in_interval(interval)  // units

        // The reward: how good was the glucose outcome?
        // Heavily penalize hypoglycemia. Mildly penalize hyperglycemia.
        // Reward time in target range.
        next_glucose = first glucose measurement in next interval
        reward = compute_reward(next_glucose)

        append to episode: (state, action, reward)

    RETURN episode
```

**Step 2: Reward function design.** This is the most consequential design decision in the entire system. The reward function encodes what "good glucose control" means numerically. Get it wrong and your agent optimizes for the wrong thing. The key insight: hypoglycemia and hyperglycemia are not symmetric risks. A glucose of 60 mg/dL is immediately life-threatening. A glucose of 200 mg/dL is harmful over hours but not acutely dangerous. Your reward function must reflect this asymmetry. Most published work uses a piecewise function with a steep penalty below 70 mg/dL, a mild penalty above 180 mg/dL, and a positive reward in the 80-180 mg/dL range. The exact shape matters enormously and should be calibrated with clinical input.

```pseudocode
FUNCTION compute_reward(glucose_mg_dl):
    // Asymmetric reward function reflecting clinical risk.
    // Hypoglycemia is immediately dangerous; hyperglycemia is gradually harmful.

    IF glucose_mg_dl < 40:
        // Severe hypoglycemia. Seizures, brain damage, death.
        // Maximum penalty. This should almost never happen.
        RETURN -100

    ELSE IF glucose_mg_dl < 70:
        // Hypoglycemia. Dangerous. Requires immediate intervention.
        // Steep penalty proportional to severity.
        RETURN -50 * (70 - glucose_mg_dl) / 30

    ELSE IF glucose_mg_dl < 80:
        // Below target but not hypoglycemic. Mild concern.
        RETURN -5

    ELSE IF glucose_mg_dl >= 80 AND glucose_mg_dl <= 180:
        // Target range. Reward proportional to how centered the value is.
        // Peak reward at 120-140 mg/dL (the "sweet spot").
        center = 130
        distance_from_center = abs(glucose_mg_dl - center)
        RETURN 10 - (distance_from_center / 50) * 5

    ELSE IF glucose_mg_dl <= 250:
        // Mild hyperglycemia. Harmful over time but not acutely dangerous.
        RETURN -2 * (glucose_mg_dl - 180) / 70

    ELSE:
        // Severe hyperglycemia. Osmotic complications, DKA risk.
        RETURN -10 - (glucose_mg_dl - 250) / 50
```

**Step 3: Offline RL training with safety constraints.** Standard RL algorithms (DQN, PPO) assume online interaction with the environment. We can't do that. We need offline RL: learning a policy purely from historical data without additional environment interaction. The key challenge is distributional shift. If the historical clinicians never gave 20 units of insulin to a patient with glucose of 150, your agent has no data to evaluate that action. Naive offline RL might still recommend it if the Q-function extrapolates incorrectly. Conservative Q-Learning (CQL) addresses this by adding a penalty for actions that are far from the historical data distribution. Batch Constrained Q-Learning (BCQ) restricts the policy to only recommend actions that were actually observed in similar states. Either approach prevents the dangerous extrapolation problem.

```pseudocode
FUNCTION train_offline_rl_policy(episodes, safety_constraints):
    // Use Conservative Q-Learning (CQL) to learn a policy
    // that stays close to the historical data distribution.

    // Initialize Q-network (maps state-action pairs to expected cumulative reward)
    Q_network = initialize_neural_network(
        input_size  = state_dimension + action_dimension,
        hidden_layers = [256, 256, 128],
        output_size = 1
    )

    // Initialize policy network (maps states to action distributions)
    policy_network = initialize_neural_network(
        input_size  = state_dimension,
        hidden_layers = [256, 256],
        output_size = action_dimension  // continuous: mean and std of dose
    )

    FOR each training_iteration in range(num_iterations):

        // Sample a batch of transitions from the historical episodes
        batch = sample_random_transitions(episodes, batch_size=256)

        // Standard Bellman backup: estimate Q-values for observed transitions
        bellman_loss = compute_bellman_error(Q_network, batch, discount=0.99)

        // CQL penalty: push down Q-values for actions NOT in the dataset.
        // This prevents the policy from recommending untested actions.
        // Sample random actions and penalize their Q-values.
        random_actions = sample_uniform_actions(batch_size=256)
        cql_penalty = mean(Q_network(batch.states, random_actions))
                    - mean(Q_network(batch.states, batch.actions))

        // Combined loss: standard RL + conservative penalty
        total_loss = bellman_loss + alpha * cql_penalty
        // alpha controls how conservative the policy is.
        // Higher alpha = stays closer to historical behavior.
        // Lower alpha = more willing to deviate (riskier but potentially better).

        update Q_network to minimize total_loss

        // Update policy to maximize Q-values subject to safety constraints
        policy_loss = -mean(Q_network(batch.states, policy_network(batch.states)))

        // Safety constraint: penalize policies that produce hypoglycemia
        // in the training data (using a learned dynamics model or historical outcomes)
        safety_penalty = estimate_hypoglycemia_probability(
            policy_network, batch.states, safety_constraints
        )

        update policy_network to minimize (policy_loss + lambda * safety_penalty)

    RETURN policy_network
```

**Step 4: Off-policy evaluation.** Before deploying any learned policy, you need to estimate how it would have performed on historical patients. This is off-policy evaluation (OPE). The core idea: if the learned policy would have recommended the same action the clinician took, we can directly use the observed outcome. If it would have recommended a different action, we need to reweight the observation using importance sampling. OPE is imperfect (high variance, relies on overlap between policies), but it's the best tool available for safety validation without live experimentation. Run OPE on a held-out test set of episodes that were not used for training.

```pseudocode
FUNCTION evaluate_policy_offline(learned_policy, test_episodes, behavior_policy):
    // Weighted Importance Sampling (WIS) estimator for policy value.
    // Estimates what the cumulative reward would have been if the learned
    // policy had been followed instead of the historical clinician policy.

    episode_returns = empty list

    FOR each episode in test_episodes:
        cumulative_importance_weight = 1.0
        cumulative_reward = 0.0

        FOR each (state, action, reward) in episode:
            // How likely is this action under the learned policy?
            pi_prob = learned_policy.probability(action | state)

            // How likely was this action under the historical clinician behavior?
            mu_prob = behavior_policy.probability(action | state)

            // Importance ratio: reweights this transition
            // If learned policy strongly agrees with clinician: ratio near 1
            // If learned policy disagrees: ratio far from 1 (high variance)
            ratio = pi_prob / mu_prob

            // Clip ratio to prevent extreme weights (variance reduction)
            ratio = clip(ratio, 0.01, 100.0)

            cumulative_importance_weight = cumulative_importance_weight * ratio
            cumulative_reward = cumulative_reward + (discount ^ timestep) * reward

        // Weighted return for this episode
        append cumulative_importance_weight * cumulative_reward to episode_returns

    // Normalize by sum of weights (self-normalized importance sampling)
    estimated_policy_value = sum(episode_returns) / sum(weights)

    // Also compute per-metric estimates
    estimated_time_in_range = compute_weighted_metric("time_in_range", ...)
    estimated_hypo_rate     = compute_weighted_metric("hypoglycemia_rate", ...)

    RETURN {
        policy_value:   estimated_policy_value,
        time_in_range:  estimated_time_in_range,
        hypo_rate:      estimated_hypo_rate,
        confidence_interval: bootstrap_ci(episode_returns, alpha=0.05)
    }
```

**Step 5: Safety constraint layer.** Even after training with safety-aware objectives and validating with OPE, the deployed system needs a hard safety layer. This is the last line of defense: regardless of what the RL policy recommends, certain actions are never allowed. Think of it as a safety envelope around the policy. The policy operates freely within the envelope; anything outside gets clipped or rejected. This layer encodes clinical knowledge that should never be violated, even if the data-driven policy disagrees.

```pseudocode
FUNCTION apply_safety_constraints(recommended_dose, patient_state, constraints):
    // Hard safety constraints that override the RL policy.
    // These are non-negotiable clinical rules.

    safe_dose = recommended_dose

    // Constraint 1: Maximum single dose cap.
    // No matter what the policy says, never exceed this.
    // Clinical rationale: prevents catastrophic hypoglycemia from a single error.
    IF safe_dose > constraints.max_single_dose:  // e.g., 20 units
        safe_dose = constraints.max_single_dose
        log_constraint_activation("max_dose_cap", recommended_dose, safe_dose)

    // Constraint 2: If glucose is already trending down rapidly, reduce dose.
    // Clinical rationale: insulin already on board will continue lowering glucose.
    IF patient_state.glucose_velocity < constraints.rapid_decline_threshold:  // e.g., -30 mg/dL/hr
        safe_dose = safe_dose * 0.5
        log_constraint_activation("rapid_decline_reduction", recommended_dose, safe_dose)

    // Constraint 3: If glucose is near hypoglycemic range, no insulin.
    // Clinical rationale: giving insulin to someone at 85 mg/dL is reckless.
    IF patient_state.glucose_current < constraints.no_insulin_threshold:  // e.g., 100 mg/dL
        safe_dose = 0
        log_constraint_activation("hypo_prevention_hold", recommended_dose, safe_dose)

    // Constraint 4: Maximum dose change from previous interval.
    // Clinical rationale: prevents wild swings in dosing.
    max_change = constraints.max_dose_change_per_interval  // e.g., 5 units
    IF abs(safe_dose - patient_state.previous_dose) > max_change:
        safe_dose = patient_state.previous_dose + sign(safe_dose - patient_state.previous_dose) * max_change
        log_constraint_activation("max_change_cap", recommended_dose, safe_dose)

    // Constraint 5: If renal function is severely impaired, reduce dose.
    // Clinical rationale: kidneys clear insulin; impaired clearance means longer effect.
    IF patient_state.creatinine > constraints.renal_impairment_threshold:  // e.g., 3.0 mg/dL
        safe_dose = safe_dose * 0.7
        log_constraint_activation("renal_adjustment", recommended_dose, safe_dose)

    RETURN {
        final_dose:         safe_dose,
        original_recommendation: recommended_dose,
        constraints_activated: get_activated_constraints(),
        confidence:         compute_recommendation_confidence(patient_state)
    }
```

**Step 6: Clinical decision support interface.** The RL policy is deployed as a recommendation system, not an autonomous controller. The clinician sees the recommendation, the reasoning behind it, and can accept, modify, or override. Every interaction is logged for ongoing evaluation. This is critical: the system learns from clinician overrides (they indicate where the policy disagrees with expert judgment) and the outcomes of both followed and overridden recommendations provide ongoing validation data.

```pseudocode
FUNCTION generate_recommendation(patient_id, new_glucose_reading):
    // Called when a new glucose measurement is entered for an ICU patient.

    // Fetch the patient's recent history from the state store
    patient_history = fetch_from_dynamodb(table="patient-glucose-state", key=patient_id)

    // Update history with new reading
    update_patient_state(patient_history, new_glucose_reading)

    // Construct the state vector for the RL policy
    state_vector = build_state_vector(patient_history)

    // Get the RL policy's recommendation
    raw_recommendation = invoke_sagemaker_endpoint(
        endpoint = "glucose-rl-policy-v2",
        payload  = state_vector
    )

    // Apply hard safety constraints
    safe_recommendation = apply_safety_constraints(
        raw_recommendation.dose,
        patient_history,
        SAFETY_CONSTRAINTS
    )

    // Package for clinical display
    recommendation = {
        patient_id:          patient_id,
        timestamp:           current_utc_timestamp(),
        recommended_dose:    safe_recommendation.final_dose,
        dose_units:          "units insulin (regular)",
        confidence:          safe_recommendation.confidence,
        reasoning: {
            current_glucose:     new_glucose_reading,
            trend:               patient_history.glucose_velocity,
            insulin_on_board:    patient_history.insulin_on_board,
            constraints_active:  safe_recommendation.constraints_activated
        },
        clinician_action:    "PENDING"  // updated when clinician responds
    }

    // Store recommendation for audit and outcome tracking
    store_recommendation(recommendation)

    RETURN recommendation
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter15.06-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

## Expected Results

**Sample recommendation output:**

```json
{
  "patient_id": "ICU-2026-04821",
  "timestamp": "2026-03-15T14:30:00Z",
  "recommended_dose": 6.0,
  "dose_units": "units insulin (regular)",
  "confidence": 0.82,
  "reasoning": {
    "current_glucose": 195,
    "trend": -8.5,
    "insulin_on_board": 4.0,
    "constraints_active": []
  },
  "clinician_action": "PENDING"
}
```

**Performance benchmarks (retrospective evaluation):**

| Metric | Historical Protocol | RL Policy (OPE Estimate) |
|--------|--------------------|-----------------------------|
| Time in range (80-180 mg/dL) | 55-65% | 70-78% |
| Hypoglycemia rate (< 70 mg/dL) | 5-8% of measurements | 2-3% of measurements |
| Severe hypoglycemia (< 40 mg/dL) | 0.5-1% | < 0.2% |
| Glucose variability (CV) | 35-45% | 25-35% |
| Mean glucose | 160-180 mg/dL | 140-160 mg/dL |

**Where it struggles:**

- Patients with rapidly changing insulin sensitivity (new steroid initiation, sepsis resolution)
- Transitions between enteral nutrition and NPO status (nutrition changes dominate glucose dynamics)
- Patients on insulin drips vs. subcutaneous insulin (different pharmacokinetics)
- Very short ICU stays (< 24 hours) where there's insufficient data to personalize
- Patients with Type 1 diabetes in the ICU (fundamentally different physiology)

---

## Why This Isn't Production-Ready

**Regulatory pathway is unclear.** An RL-based dosing recommendation system likely falls under FDA regulation as a clinical decision support tool. The regulatory pathway for adaptive/learning systems is still evolving. You'd need to demonstrate safety through extensive retrospective validation, simulation testing, and likely a prospective clinical trial.

**Off-policy evaluation has high variance.** OPE estimates are noisy, especially for policies that deviate significantly from historical behavior. The confidence intervals on "time in range improvement" may be wide enough to be clinically meaningless. You need large datasets (thousands of ICU stays) to get tight estimates.

**Behavior policy estimation is hard.** Importance sampling requires knowing the probability of each historical action under the clinician's behavior policy. Clinicians don't follow a single policy; they vary by experience, shift, patient acuity, and institutional culture. Estimating the behavior policy from data introduces its own errors.

**Model drift.** Clinical practice changes over time (new protocols, new medications, different patient populations). A policy trained on 2020-2023 data may not be optimal for 2026 patients. You need ongoing monitoring and periodic retraining.

---

## Variations and Extensions

**Continuous glucose monitor (CGM) integration.** If your ICU uses CGMs (increasingly common), you get glucose readings every 5 minutes instead of every 4 hours. This dramatically changes the state representation (you have a full glucose trajectory, not point measurements) and enables much tighter control. The RL formulation shifts from "what dose to give every 4 hours" to "what infusion rate to set every 15-30 minutes." The action space becomes continuous rate adjustments rather than discrete bolus doses.

**Multi-objective optimization.** Beyond glucose control, consider jointly optimizing for nutrition delivery (patients need calories for healing) and insulin minimization (less insulin means fewer hypoglycemic events and less nursing workload). This becomes a constrained multi-objective RL problem where you're balancing glucose control, nutritional adequacy, and intervention burden.

**Transfer learning across patient populations.** Train a base policy on your general ICU population, then fine-tune for specific subpopulations (cardiac surgery patients, trauma patients, diabetic ketoacidosis patients) who have distinct glucose dynamics. This addresses the "one policy doesn't fit all" problem without requiring massive datasets for each subpopulation.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker RL Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/reinforcement-learning.html)
- [Amazon SageMaker Model Registry](https://docs.aws.amazon.com/sagemaker/latest/dg/model-registry.html)
- [Amazon SageMaker Real-Time Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)

**Research References:**
- NICE-SUGAR Study Investigators. "Intensive versus Conventional Glucose Control in Critically Ill Patients." *New England Journal of Medicine* 360 (2009): 1283-1297.
- Kumar, A., Zhou, A., Tucker, G., Levine, S. "Conservative Q-Learning for Offline Reinforcement Learning." *NeurIPS* (2020).
- Fujimoto, S., Meger, D., Precup, D. "Off-Policy Deep Reinforcement Learning without Exploration." *ICML* (2019).
- UVA/Padova Type 1 Diabetes Metabolic Simulator (FDA-accepted research platform for glucose control algorithm development).

**Clinical Context:**
- Society of Critical Care Medicine (SCCM). Guidelines for the Use of an Insulin Infusion for the Management of Hyperglycemia in Critically Ill Patients.
- American Diabetes Association. Standards of Care in Diabetes: Diabetes Care in the Hospital (updated annually).

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| **Basic** (data pipeline + offline RL training + retrospective evaluation) | 4-6 months |
| **Production-ready** (safety constraints + OPE validation + shadow mode deployment + clinician interface) | 12-18 months |
| **With variations** (CGM integration + multi-objective + transfer learning + prospective validation) | 24-36 months |

---

**Tags:** `reinforcement-learning`, `offline-rl`, `glucose-control`, `icu`, `insulin-dosing`, `safety-constraints`, `clinical-decision-support`, `sequential-decision-making`, `off-policy-evaluation`

---

| [← 15.5: Ventilator Weaning Protocols](chapter15.05-ventilator-weaning-protocols) | [Chapter 15 Index](chapter15-preface) | [15.7: Chronic Disease Treatment Personalization →](chapter15.07-chronic-disease-treatment-personalization) |
|:---|:---:|---:|

---

*← [Main Recipe 15.6](chapter15.06-glucose-control-icu) · [Python Example](chapter15.06-python-example) · [Chapter Preface](chapter15-preface)*
