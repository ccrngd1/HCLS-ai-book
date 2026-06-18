# Recipe 7.10 Architecture and Implementation: Optimal Intervention Timing Prediction

*Companion to [Recipe 7.10: Optimal Intervention Timing Prediction](chapter07.10-optimal-intervention-timing-prediction). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for model training and hosting.** Dynamic survival models require custom architectures (RNNs, transformers) trained on longitudinal patient data. SageMaker handles the GPU training infrastructure you need for sequence models, plus experiment tracking and real-time inference endpoints. The model registry handles versioning as you retrain on new outcome data, which matters here because timing models need frequent recalibration.

**AWS Glue and Amazon S3 for longitudinal data assembly.** Building patient timelines from disparate source systems (EHR extracts, claims feeds, pharmacy data, ADT feeds) is an ETL-heavy workload. Glue handles the transformation logic; S3 provides the durable data lake layer. Glue's support for incremental processing matters here because patient timelines need daily updates, not full rebuilds.

**Amazon Kinesis Data Streams for real-time event ingestion.** Intervention timing is time-sensitive. If a patient's lab result comes back critically abnormal at 2 PM, you don't want to wait for tomorrow's batch run to flag them. Kinesis ingests real-time clinical events (ADT messages, lab results, medication fills) and feeds them to the scoring pipeline with sub-minute latency. Configure a dead letter queue (SQS) on the Lambda event source mapping so failed records aren't silently dropped; for a clinical system, a missed scoring event means a patient who should have been flagged is invisible.

**AWS Lambda for intervention window scoring.** The scoring logic (apply decision rules to model output, check operational constraints, generate recommendations) is stateless and event-driven. Lambda processes each patient's updated trajectory and determines whether to surface an intervention recommendation.

**Amazon DynamoDB for patient state and recommendation storage.** Each patient has a current state (latest risk trajectory, last intervention date, engagement history) that needs fast point lookups and frequent updates. DynamoDB's key-value model with TTL support handles this cleanly. Recommendations are written here for the care team interface to consume.

**Amazon EventBridge for orchestration.** The pipeline has multiple triggers: batch model retraining (weekly), incremental feature updates (daily), real-time event scoring (continuous). EventBridge coordinates these schedules and routes events between components without tight coupling.

### Architecture Diagram

```mermaid
flowchart TD
    subgraph Data Sources
        A[EHR Extract] 
        B[Claims Feed]
        C[ADT Feed]
        D[Pharmacy Data]
        E[Lab Results]
    end

    subgraph Ingestion
        F[AWS Glue\nBatch ETL]
        G[Kinesis Data Streams\nReal-time Events]
    end

    subgraph Storage
        H[S3 Data Lake\nPatient Timelines]
        I[DynamoDB\nPatient State]
    end

    subgraph ML Pipeline
        J[SageMaker Training\nDynamic Survival Model]
        K[SageMaker Endpoint\nReal-time Inference]
    end

    subgraph Scoring
        L[Lambda\nIntervention Window Scorer]
        M[EventBridge\nOrchestration]
    end

    subgraph Delivery
        N[Care Management Platform\nActionable Worklist]
    end

    A --> F
    B --> F
    D --> F
    C --> G
    E --> G
    F --> H
    G --> I
    H --> J
    J --> K
    G --> L
    K --> L
    I --> L
    L --> I
    M --> F
    M --> L
    I --> N
```
### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker, Amazon S3, AWS Glue, Amazon Kinesis Data Streams, AWS Lambda, Amazon DynamoDB, Amazon EventBridge, Amazon CloudWatch |
| **IAM Permissions** | `sagemaker:CreateTrainingJob`, `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `kinesis:GetRecords`, `kinesis:PutRecord`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `events:PutRule`, `events:PutTargets`. Note: these represent the aggregate across all components. Each Lambda function should have a dedicated execution role scoped to only the permissions it needs (e.g., the scoring Lambda needs `sagemaker:InvokeEndpoint` and `dynamodb:GetItem/PutItem` but not `sagemaker:CreateTrainingJob` or `glue:StartJobRun`). |
| **BAA** | AWS BAA signed (required: all patient clinical data is PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest (default); Kinesis: server-side encryption with KMS (24-hour retention, minimum sufficient for this use case); SageMaker: KMS for training volumes and model artifacts; all API calls over TLS |
| **VPC** | Production: SageMaker training and endpoints in VPC (enable `EnableNetworkIsolation=True` on inference endpoints to prevent outbound calls from model containers); Lambda in VPC with endpoints for S3, DynamoDB, SageMaker Runtime, Kinesis, CloudWatch Logs, KMS, STS, and EventBridge; VPC Flow Logs enabled |
| **CloudTrail** | Enabled: log all SageMaker, S3, DynamoDB, Kinesis, and Lambda API calls for HIPAA audit trail. Set CloudWatch Logs retention policy (e.g., 90 days) rather than indefinite retention. |
| **Sample Data** | Synthetic longitudinal patient data with timestamped events. MIMIC-IV provides realistic ICU timelines. CMS Synthetic Public Use Files provide claims-level longitudinal data. Never use real PHI in development. |
| **Cost Estimate** | SageMaker training: ~$500-2,000/run (GPU instances, depends on data volume). SageMaker endpoint: ~$800-3,000/month (ml.m5.xlarge or larger). Kinesis: ~$50-200/month. Glue: ~$100-500/month. DynamoDB: ~$50-200/month. VPC endpoints and data transfer: ~$50-150/month. Lambda: negligible. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Trains dynamic survival model on longitudinal patient data; hosts real-time inference endpoint |
| **Amazon S3** | Stores patient timeline datasets, model artifacts, and training outputs |
| **AWS Glue** | Assembles patient timelines from disparate source systems; runs incremental daily updates |
| **Amazon Kinesis Data Streams** | Ingests real-time clinical events (ADT, labs, medication fills) for immediate scoring |
| **AWS Lambda** | Applies intervention window decision logic to model predictions; generates recommendations |
| **Amazon DynamoDB** | Stores current patient state, risk trajectories, and intervention recommendations |
| **Amazon EventBridge** | Orchestrates batch retraining, daily feature updates, and real-time scoring triggers |
| **Amazon CloudWatch** | Monitors model latency, prediction drift, scoring throughput, and alerting |
| **AWS KMS** | Manages encryption keys for all data stores and model artifacts |

### Pseudocode Walkthrough

**Step 1: Assemble patient timelines.** The foundation of any timing model is a complete, time-ordered sequence of clinical events for each patient. This step pulls data from multiple source systems (EHR, claims, pharmacy, labs) and aligns everything on a unified timeline. Each event gets a timestamp, an event type, and relevant attributes. The output is one record per patient containing their full event history, sorted chronologically. This is the hardest engineering step in the entire pipeline. Healthcare data is fragmented across systems with different identifiers, different time zones, and different update frequencies. Getting this right is 60% of the work. Skip this step or do it poorly, and your model trains on incomplete or misaligned data, producing timing predictions that are systematically wrong.

```pseudocode
FUNCTION assemble_patient_timeline(patient_id, lookback_days=730):
    // Pull events from each source system for this patient.
    // lookback_days controls how far back we look (2 years is typical for chronic conditions).
    // Each source returns events in its own format; we normalize to a common schema.

    encounters   = query EHR for encounters where patient = patient_id
                   AND date >= (today - lookback_days)

    claims       = query claims warehouse for claims where member_id = patient_id
                   AND service_date >= (today - lookback_days)

    medications  = query pharmacy system for fills where patient = patient_id
                   AND fill_date >= (today - lookback_days)

    labs         = query lab system for results where patient = patient_id
                   AND result_date >= (today - lookback_days)

    vitals       = query EHR for vital signs where patient = patient_id
                   AND measurement_date >= (today - lookback_days)

    // Normalize each event to a common schema:
    // { timestamp, event_type, event_subtype, attributes: {} }
    all_events = []

    FOR each encounter in encounters:
        append to all_events: {
            timestamp: encounter.date,
            event_type: "encounter",
            event_subtype: encounter.type,       // "inpatient", "outpatient", "ED", "telehealth"
            attributes: {
                diagnosis_codes: encounter.diagnoses,
                provider_type: encounter.provider_specialty,
                length_of_stay: encounter.los_days    // null for outpatient
            }
        }

    FOR each claim in claims:
        append to all_events: {
            timestamp: claim.service_date,
            event_type: "claim",
            event_subtype: claim.claim_type,     // "professional", "facility", "pharmacy"
            attributes: {
                procedure_codes: claim.procedures,
                total_charge: claim.billed_amount
            }
        }

    FOR each med in medications:
        append to all_events: {
            timestamp: med.fill_date,
            event_type: "medication",
            event_subtype: "fill",
            attributes: {
                drug_name: med.drug_name,
                days_supply: med.days_supply,
                refill_number: med.refill_num
            }
        }

    FOR each lab in labs:
        append to all_events: {
            timestamp: lab.result_date,
            event_type: "lab",
            event_subtype: lab.test_code,
            attributes: {
                value: lab.result_value,
                reference_low: lab.ref_range_low,
                reference_high: lab.ref_range_high,
                abnormal_flag: lab.abnormal_flag
            }
        }

    // Sort all events chronologically. This ordering is critical:
    // the model learns from the sequence, not just the values.
    sort all_events by timestamp ascending

    RETURN {
        patient_id: patient_id,
        timeline: all_events,
        event_count: length of all_events,
        span_days: (latest timestamp - earliest timestamp) in days
    }
```
**Step 2: Engineer temporal features.** Raw events aren't directly useful for a timing model. You need features that capture temporal dynamics: how fast things are changing, how long since key events occurred, whether patterns are accelerating or decelerating. This step transforms the raw timeline into a feature vector at each time step, creating the input the survival model needs. The features here are specifically designed to capture inflection points, not just current state. A patient whose A1C has been 8.5 for two years is different from a patient whose A1C just jumped from 7.0 to 8.5 in one quarter, even though their current value is similar. Skip this step and feed raw events directly to the model, and it will struggle to learn timing patterns because the signal is buried in noise.

```pseudocode
FUNCTION engineer_temporal_features(timeline, observation_date):
    // Compute features that capture the temporal dynamics at a specific observation point.
    // These features are computed for each "time step" during training,
    // and for the current date during inference.

    features = {}

    // --- Recency features: how long since key events ---
    features["days_since_last_encounter"]    = days between observation_date
                                               and most recent encounter in timeline
    features["days_since_last_ed_visit"]     = days between observation_date
                                               and most recent ED encounter (null if none)
    features["days_since_last_inpatient"]    = days between observation_date
                                               and most recent inpatient stay (null if none)
    features["days_since_last_med_fill"]     = days between observation_date
                                               and most recent medication fill
    features["days_since_last_lab"]          = days between observation_date
                                               and most recent lab result

    // --- Velocity features: rate of change ---
    // For key lab values, compute the slope over the last 90 days.
    // A rising A1C slope signals deteriorating glycemic control.
    a1c_values = extract lab values where test_code = "A1C"
                 AND timestamp within (observation_date - 365, observation_date)
    IF length of a1c_values >= 2:
        features["a1c_slope_90d"] = linear regression slope of a1c_values
                                    over last 90 days
        features["a1c_current"]   = most recent a1c value
    ELSE:
        features["a1c_slope_90d"] = null
        features["a1c_current"]   = null

    // --- Acceleration features: is the rate of change itself changing? ---
    // Compare recent utilization rate to historical baseline.
    encounters_last_30d  = count encounters in (observation_date - 30, observation_date)
    encounters_prior_30d = count encounters in (observation_date - 60, observation_date - 30)
    features["encounter_acceleration"] = encounters_last_30d - encounters_prior_30d

    // --- Gap features: missed expected events ---
    // If a patient has a 90-day medication supply and hasn't refilled in 100 days,
    // that gap is a strong timing signal.
    FOR each active medication:
        expected_refill_date = last_fill_date + days_supply
        IF observation_date > expected_refill_date:
            features["med_gap_days_" + drug_class] = observation_date - expected_refill_date
        ELSE:
            features["med_gap_days_" + drug_class] = 0

    // --- Pattern features: behavioral signals ---
    features["missed_appointments_90d"]  = count of no-shows in last 90 days
    features["cancelled_appointments_90d"] = count of cancellations in last 90 days
    features["total_encounters_180d"]    = count of all encounters in last 180 days
    features["ed_visits_365d"]           = count of ED visits in last 365 days

    // --- Intervention history: when was the patient last contacted? ---
    features["days_since_last_intervention"] = days since last care management outreach
    features["interventions_90d"]            = count of interventions in last 90 days
    features["last_intervention_outcome"]    = outcome of most recent intervention
                                               // "engaged", "no_answer", "declined"

    RETURN features
```
**Step 3: Train the dynamic survival model.** This is where the temporal features become a timing prediction. The model learns, from historical patient trajectories and their outcomes, to estimate the hazard function at each time step. During training, it sees thousands of patient timelines with known event times and learns which feature patterns precede events, and crucially, how far in advance those patterns appear. The output is a model that can take any patient's current feature vector and predict their hazard trajectory over the next N days. This trajectory is what enables timing decisions: a flat trajectory means "no urgency," a rising trajectory means "window is opening," and a peaked trajectory means "window may be closing."

```pseudocode
FUNCTION train_survival_model(training_data):
    // training_data contains:
    //   - patient timelines (feature sequences)
    //   - event indicators (did the patient have the target event?)
    //   - event times (when did it happen, relative to each observation point?)
    //   - censoring indicators (did we lose track of the patient before observing an event?)

    // Define model architecture: LSTM-based survival network.
    // The LSTM processes the feature sequence and outputs a hazard estimate at each step.
    model = create LSTM survival network with:
        input_dim    = number of temporal features
        hidden_dim   = 128                    // capacity to learn complex temporal patterns
        num_layers   = 2                      // depth for capturing hierarchical patterns
        output_dim   = forecast_horizon_days  // predict hazard for each of the next N days
        dropout      = 0.3                    // regularization to prevent overfitting

    // Loss function: negative log-likelihood of the observed survival times.
    // This is the standard survival analysis loss that handles censored observations
    // (patients who didn't have an event during the observation window).
    loss_function = negative_log_partial_likelihood

    // Training loop
    FOR each epoch in 1..100:
        FOR each batch of patient sequences:
            // Forward pass: model predicts hazard at each time step
            predicted_hazards = model(batch.feature_sequences)

            // Compute loss against actual event times
            loss = loss_function(predicted_hazards, batch.event_times,
                                 batch.event_indicators, batch.censoring_indicators)

            // Backward pass: update model weights
            update model weights using loss gradient

        // Evaluate on validation set: concordance index (C-index)
        // C-index measures whether patients with higher predicted hazard
        // actually have events sooner. 0.5 = random, 1.0 = perfect.
        c_index = evaluate concordance on validation_set
        log("Epoch {epoch}: C-index = {c_index}")

        // Early stopping if validation performance plateaus
        IF c_index has not improved for 10 epochs:
            BREAK

    // Save trained model for deployment
    save model to model_registry with:
        version    = current timestamp
        c_index    = best validation c_index
        features   = list of input feature names
        horizon    = forecast_horizon_days

    RETURN model
```
**Step 4: Score intervention windows.** This is the decision layer. Given a patient's predicted hazard trajectory, determine whether now is the right time to intervene. The logic encodes clinical beliefs about intervention effectiveness: interventions work best when risk is rising but hasn't peaked (the patient is deteriorating but hasn't yet reached crisis). Too early and the intervention is premature; too late and it's reactive rather than preventive. The scoring function produces an "intervention urgency" score and a recommended action window (e.g., "intervene within the next 3-5 days"). Skip this step and you're back to static risk scoring: you know who's at risk but not when to act.

```pseudocode
FUNCTION score_intervention_window(patient_id, hazard_trajectory):
    // hazard_trajectory is an array of predicted daily hazard values
    // for the next N days (e.g., 30 days).
    // Each value represents the probability of the target event on that specific day,
    // given survival to that day.

    // Compute trajectory characteristics
    current_hazard     = hazard_trajectory[0]           // today's hazard
    peak_hazard        = maximum value in hazard_trajectory
    peak_day           = index of peak_hazard           // which day the peak occurs
    hazard_slope       = slope of hazard_trajectory over first 7 days
    hazard_acceleration = second derivative of trajectory over first 14 days

    // Retrieve patient's intervention history
    patient_state = lookup patient_id in patient state store
    days_since_last_intervention = today - patient_state.last_intervention_date
    recent_intervention_outcome  = patient_state.last_intervention_outcome

    // --- Decision logic ---
    // The intervention window is optimal when:
    // 1. Risk is rising (positive slope) - the patient is deteriorating
    // 2. Peak is still ahead (not behind us) - we haven't missed the window
    // 3. Enough time since last intervention - avoid outreach fatigue
    // 4. Previous intervention wasn't recently declined - respect patient preferences

    intervention_score = 0.0
    recommended_action = "monitor"
    action_window_days = null

    // Rising risk with peak ahead: prime intervention window
    IF hazard_slope > 0.01 AND peak_day > 2 AND peak_day < 14:
        intervention_score = hazard_slope * 100 * (peak_hazard / current_hazard)
        // Scale by how much worse it's going to get (peak/current ratio)

    // Already at or past peak: window may be closing
    ELSE IF peak_day <= 2 AND current_hazard > HIGH_RISK_THRESHOLD:
        intervention_score = current_hazard * 50  // urgent but possibly too late
        recommended_action = "urgent_outreach"
        action_window_days = 1

    // Flat high risk: chronic elevation, timing is less critical
    ELSE IF current_hazard > MODERATE_RISK_THRESHOLD AND hazard_slope < 0.005:
        intervention_score = current_hazard * 20  // important but not time-sensitive
        recommended_action = "scheduled_outreach"
        action_window_days = 7

    // Apply intervention fatigue dampening
    IF days_since_last_intervention < 14:
        intervention_score = intervention_score * 0.3  // reduce urgency if recently contacted
    IF recent_intervention_outcome == "declined":
        intervention_score = intervention_score * 0.1  // strongly reduce if patient declined

    // Determine recommended action based on final score
    IF intervention_score > URGENT_THRESHOLD:
        recommended_action = "immediate_outreach"
        action_window_days = 2
    ELSE IF intervention_score > ACTION_THRESHOLD:
        recommended_action = "outreach_this_week"
        action_window_days = peak_day - 1  // intervene before the predicted peak

    RETURN {
        patient_id: patient_id,
        intervention_score: intervention_score,
        recommended_action: recommended_action,
        action_window_days: action_window_days,
        current_hazard: current_hazard,
        predicted_peak_day: peak_day,
        peak_hazard: peak_hazard,
        trajectory_slope: hazard_slope,
        scored_at: current UTC timestamp
    }
```
**Step 5: Generate and deliver recommendations.** The final step assembles the scored patients into an actionable worklist for the care team. It applies operational constraints (care manager capacity, patient contact preferences, time of day), ranks patients by intervention urgency, and writes the recommendations to the delivery layer. The "why now" explanation is critical: care managers won't act on a score without understanding what changed. This step generates a human-readable explanation of why this patient, why today. Skip this step and you have a model that produces numbers but doesn't change behavior.

```pseudocode
FUNCTION generate_recommendations(scored_patients, care_team_capacity):
    // scored_patients: list of intervention window scores from Step 4
    // care_team_capacity: how many outreach slots are available today

    // Filter to actionable recommendations only
    actionable = filter scored_patients where recommended_action != "monitor"

    // Sort by intervention score descending (most urgent first)
    sort actionable by intervention_score descending

    // Apply capacity constraint: only recommend what the team can handle
    recommendations = take first care_team_capacity items from actionable

    FOR each rec in recommendations:
        // Generate "why now" explanation for the care manager
        explanation = generate_explanation(rec)

        // Write recommendation to patient state store
        write to patient state store:
            patient_id: rec.patient_id,
            recommendation: rec.recommended_action,
            urgency_score: rec.intervention_score,
            action_window: rec.action_window_days,
            explanation: explanation,
            generated_at: current UTC timestamp,
            expires_at: current timestamp + (rec.action_window_days * 24 hours),
            status: "pending"    // care manager hasn't acted yet

    RETURN recommendations

FUNCTION generate_explanation(scored_result):
    // Build a human-readable explanation of why this patient needs outreach now.
    // Care managers need to understand the "why" to trust and act on the recommendation.

    parts = []

    IF scored_result.trajectory_slope > 0.02:
        append to parts: "Risk trajectory is rising sharply"

    IF scored_result.predicted_peak_day < 7:
        append to parts: "Predicted risk peak within {peak_day} days"

    IF scored_result.current_hazard > HIGH_RISK_THRESHOLD:
        append to parts: "Current risk level is elevated"

    // Add the specific clinical drivers (from the feature importance)
    // These come from the model's attention weights or SHAP values
    top_drivers = get top 3 feature contributors for this patient
    FOR each driver in top_drivers:
        append to parts: driver.description
        // e.g., "A1C increased from 7.8 to 9.1 over last 90 days"
        // e.g., "Missed medication refill (12 days overdue)"
        // e.g., "No PCP visit in 180 days"

    RETURN join parts with ". "
```
> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter07.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a diabetes care management panel:**

```json
{
  "patient_id": "PAT-2847193",
  "recommendation": "outreach_this_week",
  "urgency_score": 72.4,
  "action_window_days": 4,
  "explanation": "Risk trajectory is rising sharply. A1C increased from 7.8 to 9.1 over last 90 days. Missed medication refill (metformin, 12 days overdue). Predicted risk peak within 6 days.",
  "current_hazard": 0.034,
  "predicted_peak_day": 6,
  "peak_hazard": 0.089,
  "generated_at": "2026-05-31T08:00:00Z",
  "expires_at": "2026-06-04T08:00:00Z",
  "status": "pending"
}
```
**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Model C-index (discrimination) | 0.72-0.78 |
| Timing accuracy (event within predicted window) | 45-60% |
| End-to-end scoring latency (real-time path) | 3-8 seconds (with provisioned concurrency on scoring Lambda) |
| Batch scoring throughput | ~5,000 patients/minute |
| Intervention effectiveness lift vs. static risk | 15-30% improvement in event prevention |
| False urgency rate (flagged but no event within 30 days) | 30-45% |
| Cost per patient scored | ~$0.02 (inference + compute) |

Without provisioned concurrency, Lambda cold starts in VPC can push real-time path latency to 10-15 seconds. For this use case, single-digit-second latency is acceptable because recommendations land on a care manager worklist, not in a real-time clinical workflow. The batch path (daily scoring) handles the majority of patients; the real-time path is for acute events only.

**Where it struggles:**

- Patients with very sparse data (new enrollees, infrequent utilizers) produce unreliable trajectories
- Sudden-onset events (trauma, stroke) that don't have a gradual risk buildup are inherently unpredictable
- Patients whose behavior changes abruptly (new stressor, job loss, family crisis) without corresponding clinical data
- Conditions where the intervention itself changes the trajectory in ways the model hasn't seen (novel treatments)
- Populations underrepresented in training data produce poorly calibrated timing estimates

---

## Variations and Extensions

**Multi-intervention timing.** Instead of a single "intervene or wait" decision, model the optimal timing for different intervention types: phone call, text message, home visit, medication adjustment, specialist referral. Each intervention type has different effectiveness curves at different risk levels. A text reminder might work at moderate risk; a home visit might be needed at high risk. The model outputs a recommended intervention type alongside the timing.

**Channel-aware scheduling.** Integrate patient communication preferences and historical response patterns. Some patients answer calls in the morning. Some respond to texts but ignore calls. Some only engage after the second attempt. Layer these behavioral patterns onto the timing model to optimize not just when to intervene but how to reach the patient when you do.

**Outcome-driven retraining with causal correction.** Implement a continuous learning loop where intervention outcomes (did the patient engage? did the event occur anyway?) feed back into model retraining. Use inverse probability weighting to correct for the selection bias introduced by the model's own recommendations. This is the path toward true causal timing optimization, but requires careful statistical methodology and sufficient data volume.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Real-time Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints.html)
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)
- [Amazon SageMaker Pricing](https://aws.amazon.com/sagemaker/pricing/)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Comprehensive SageMaker examples including custom training scripts, real-time inference, and model monitoring
- [`aws-healthcare-lifescience-ai-ml`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml): Healthcare and life science ML examples on AWS including patient outcome prediction patterns

**AWS Solutions and Blogs:**
- [Machine Learning Best Practices in Healthcare and Life Sciences](https://aws.amazon.com/blogs/machine-learning/category/artificial-intelligence/): AWS ML blog posts covering healthcare-specific ML architectures and deployment patterns
- [AWS Solutions Library (Healthcare)](https://aws.amazon.com/solutions/?solutions-all.sort-by=item.additionalFields.sortDate&solutions-all.sort-order=desc&awsf.content-type=*all&awsf.methodology=*all&awsf.tech-category=tech-category%23ai-ml&awsf.industries=industry%23healthcare): Deployable healthcare AI/ML solutions and reference architectures

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| **Basic** (static risk + velocity heuristic) | 8-12 weeks |
| **Production-ready** (dynamic survival model, real-time scoring, care team integration) | 16-24 weeks |
| **With variations** (multi-intervention, causal correction, continuous learning) | 30-40+ weeks |

---

---

*← [Main Recipe 7.10](chapter07.10-optimal-intervention-timing-prediction) · [Python Example](chapter07.10-python-example) · [Chapter Preface](chapter07-preface)*
