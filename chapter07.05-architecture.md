# Recipe 7.5 Architecture and Implementation: 30-Day Readmission Risk

*Companion to [Recipe 7.5: 30-Day Readmission Risk](chapter07.05-30-day-readmission-risk). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## Why These Services

**Amazon SageMaker for model training and real-time inference.** Readmission scoring needs to happen within hours of discharge, which means you need a model endpoint that can score individual patients on demand. SageMaker gives you managed real-time endpoints that auto-scale, plus the training infrastructure for periodic retraining. The built-in XGBoost container is well-suited for the gradient boosted tree approach that dominates this problem space.

**Amazon HealthLake for clinical data aggregation.** HealthLake provides a FHIR-native data store that can ingest clinical data from EHR systems and normalize it into a queryable format. For readmission prediction, you need to pull together diagnoses, procedures, medications, labs, and encounter history for each patient at discharge time. HealthLake's FHIR search capabilities make this feature assembly step cleaner than querying raw EHR databases directly.

**AWS Glue for feature engineering pipelines.** The batch feature engineering (computing rolling utilization metrics, comorbidity indices, medication complexity scores) runs as scheduled ETL jobs. Glue handles the heavy transformations on historical data that feed model training, while real-time features are assembled at scoring time from HealthLake queries.

**Amazon EventBridge for discharge event processing.** ADT discharge events flow into EventBridge, which triggers the scoring pipeline. EventBridge's event filtering ensures only qualifying inpatient discharges (not observation stays or planned returns) trigger the model. This event-driven architecture means scores are generated automatically without manual intervention.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add dead letter queue guidance: SQS DLQ for failed scoring events, CloudWatch alarm on DLQ depth > 0, daily retry Lambda, and manual review fallback for patients not scored within 24 hours. -->

**AWS Step Functions for pipeline orchestration.** The scoring workflow (detect discharge, assemble features, invoke model, stratify risk, route intervention, store results) has multiple steps with error handling and retry logic. Step Functions coordinates this sequence and provides visibility into failures. If the feature assembly step fails (e.g., a source system is down), the workflow retries with backoff rather than silently dropping the patient.

**Amazon DynamoDB for risk score storage and lookup.** Scored patients need their risk tier accessible to downstream systems (care management platforms, EHR dashboards, nurse worklists) in real time. DynamoDB provides single-digit-millisecond lookups by patient ID. Scores are written at discharge and read by operational systems throughout the 30-day window.

**Amazon SNS for intervention notifications.** When a patient is scored as high-risk, the appropriate care team needs to be notified immediately. SNS delivers notifications to care transition nurses, case managers, or automated workflow systems based on the risk tier and contributing factors. Important: SNS messages containing patient identifiers and clinical indicators constitute PHI. Restrict topic subscriptions to HIPAA-compliant endpoints only (Lambda functions, SQS queues within your VPC, or HTTPS endpoints covered under your BAA). Do not use email or SMS subscriptions for messages containing patient-level data. If email notification is needed, send a minimal alert ("1 new high-risk discharge requires review") with a link to the secure care management dashboard.

## Architecture Diagram

```mermaid
flowchart TD
    subgraph Data Sources
        A[ADT Feed\nHL7/FHIR]
        B[EHR Clinical Data]
        C[Claims History]
        D[Lab Results]
        E[Pharmacy Data]
    end

    subgraph Event Processing
        A -->|Discharge Event| F[EventBridge\nDischarge Filter]
        F -->|Qualified Discharge| G[Step Functions\nScoring Workflow]
    end

    subgraph Feature Assembly
        G -->|Query Patient Data| H[HealthLake\nFHIR Store]
        G -->|Historical Features| I[S3 Feature Store\nParquet]
        H --> J[Feature Vector\nAssembly]
        I --> J
    end

    subgraph Model Scoring
        J -->|Feature Vector| K[SageMaker Endpoint\nXGBoost Model]
        K -->|Probability| L[Risk Stratification\nLambda]
    end

    subgraph Action
        L -->|High Risk| M[SNS\nCare Team Alert]
        L -->|All Scores| N[DynamoDB\nRisk Score Store]
        L -->|Dashboard| O[QuickSight\nReadmission Analytics]
    end

    subgraph Model Lifecycle
        P[Glue\nFeature Engineering] -->|Training Data| Q[S3\nTraining Dataset]
        Q --> R[SageMaker Training\nMonthly Retrain]
        R -->|New Model| K
    end

    style F fill:#f9f,stroke:#333
    style K fill:#ff9,stroke:#333
    style N fill:#9ff,stroke:#333
```
**Model versioning and rollback.** Before promoting a retrained model to the production endpoint, run shadow scoring for one to two weeks: score each discharge with both the current and candidate models, compare predictions, and validate that the candidate's calibration and discrimination meet minimum thresholds (AUC >= current model AUC - 0.02, calibration slope between 0.85 and 1.15). SageMaker Model Registry tracks model versions and approval status. Use SageMaker endpoint production variants for canary deployments. Always maintain the ability to roll back to the previous model version within minutes. A bad model deployment here has direct patient impact: under-prediction means high-risk patients miss interventions; over-prediction causes alert fatigue that erodes clinical trust.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon SageMaker, Amazon HealthLake, AWS Glue, Amazon EventBridge, AWS Step Functions, Amazon DynamoDB, Amazon SNS, Amazon S3, Amazon QuickSight |
| **IAM Permissions** | `sagemaker:InvokeEndpoint`, `healthlake:SearchWithGet`, `healthlake:ReadResource`, `glue:StartJobRun`, `dynamodb:PutItem`, `dynamodb:GetItem`, `sns:Publish`, `s3:GetObject`, `s3:PutObject`, `states:StartExecution`. All permissions should be scoped to specific resource ARNs (e.g., `sagemaker:InvokeEndpoint` targeting `arn:aws:sagemaker:{region}:{account}:endpoint/readmission-risk-*`). Use separate IAM roles for the scoring Lambda, training pipeline, and monitoring functions with distinct permission boundaries. |
| **BAA** | Required. All services handling PHI must be covered under your AWS BAA. HealthLake, SageMaker, DynamoDB, S3, Glue, Step Functions, EventBridge, SNS, and QuickSight are all HIPAA-eligible. |
| **Encryption** | S3: SSE-KMS for feature stores and model artifacts. DynamoDB: encryption at rest (default). HealthLake: AWS-managed or customer-managed KMS keys. SageMaker: KMS encryption for training data, model artifacts, and endpoint traffic. All inter-service communication over TLS. |
| **VPC** | Production: SageMaker endpoints, Glue jobs, and Lambda functions in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), SageMaker Runtime (interface), CloudWatch Logs (interface), Step Functions/states (interface), and SNS (interface). HealthLake accessed via interface endpoint (verify regional availability; HealthLake has more limited regional availability than other services in this architecture). |
| **CloudTrail** | Enabled for all API calls. Critical for HIPAA audit trail: who accessed which patient's risk score, when, and from where. Note: DynamoDB data events log table name and API action but not item keys. Implement application-level audit logging (patient_id, requesting identity, timestamp) for patient-level access auditing required by HIPAA. |
| **Sample Data** | MIMIC-III or MIMIC-IV (publicly available ICU dataset with readmission outcomes). CMS Synthetic Public Use Files for claims-based features. Never use real PHI in development. Model validation on real patient data requires a HIPAA-compliant environment with the same security controls as production. |
| **Cost Estimate** | SageMaker real-time endpoint (ml.m5.large): ~$0.115/hour (~$83/month). Scoring latency: <200ms per patient. At 100 discharges/day, the per-discharge cost is ~$0.003. HealthLake: $0.60/GB stored + $0.09 per 1000 read operations. Glue: $0.44/DPU-hour for batch feature engineering. Feature assembly involves 5-7 FHIR queries per patient; parallelize independent queries to keep assembly latency under 1 second. |

## Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon SageMaker** | Model training (monthly), real-time scoring endpoint, model registry |
| **Amazon HealthLake** | FHIR-native clinical data store for real-time feature queries |
| **AWS Glue** | Batch feature engineering, historical feature computation, training data preparation |
| **Amazon EventBridge** | Discharge event ingestion and filtering |
| **AWS Step Functions** | Orchestrates the scoring workflow with error handling and retries |
| **Amazon DynamoDB** | Stores risk scores for real-time lookup by downstream systems |
| **Amazon SNS** | Delivers high-risk alerts to care transition teams |
| **Amazon S3** | Feature store (Parquet), model artifacts, training datasets, scoring audit logs |
| **Amazon QuickSight** | Readmission analytics dashboards for leadership and quality teams |
| **AWS KMS** | Encryption key management for all PHI-containing stores |
| **Amazon CloudWatch** | Monitoring, alerting on scoring failures, model performance metrics |

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Clarify feature store architecture: for >100 discharges/day, pre-compute historical utilization features nightly via Glue into DynamoDB keyed by patient_id. Scoring workflow queries HealthLake only for current-encounter features + DynamoDB for pre-computed historical features. This hybrid keeps latency under 500ms. -->

## Pseudocode Walkthrough

> **Reference implementations:** The following AWS sample repos demonstrate patterns used in this recipe:
>
> - [`amazon-healthlake-server-cdk`](https://github.com/aws-samples/amazon-healthlake-server-cdk): CDK constructs for deploying HealthLake with proper security configuration
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker training and deployment patterns including XGBoost for healthcare use cases

### Step 1: Discharge Event Detection and Filtering

**What this does:** Listens for ADT discharge events and filters to only qualified inpatient discharges that should be scored. Observation stays, planned readmissions, and transfers to other acute facilities are excluded.

**What goes wrong if you skip it:** You score patients who shouldn't be scored (observation stays aren't subject to readmission penalties), waste compute on irrelevant events, and pollute your outcome tracking with non-qualifying encounters.

```pseudocode
FUNCTION handle_discharge_event(event):
    // Parse the ADT message (HL7 A03 or FHIR Encounter update)
    patient_id = event.patient_identifier
    encounter_type = event.encounter_class
    discharge_disposition = event.disposition
    length_of_stay = event.discharge_date - event.admit_date

    // Filter: only score qualifying inpatient discharges
    IF encounter_type NOT IN ["inpatient", "acute"]:
        LOG "Skipping non-inpatient encounter for patient {patient_id}"
        RETURN null

    // Exclude transfers to other acute facilities (not true discharges)
    IF discharge_disposition IN ["transfer_acute", "left_ama"]:
        LOG "Skipping transfer/AMA for patient {patient_id}"
        RETURN null

    // Exclude very short stays (likely observation misclassified)
    IF length_of_stay < 1 day:
        LOG "Skipping sub-24hr stay for patient {patient_id}"
        RETURN null

    // Qualified discharge: trigger scoring workflow
    RETURN {
        patient_id: patient_id,
        encounter_id: event.encounter_id,
        discharge_date: event.discharge_date,
        primary_diagnosis: event.primary_diagnosis,
        discharge_disposition: discharge_disposition
    }
```
### Step 2: Feature Assembly from Clinical Data

**What this does:** Queries multiple data sources to assemble the complete feature vector for the discharged patient. Combines real-time clinical data from the current encounter with historical utilization patterns.

**What goes wrong if you skip it:** The model receives incomplete or stale data, producing unreliable risk scores. Missing features (especially prior utilization history) dramatically reduce predictive accuracy.

```pseudocode
FUNCTION assemble_features(discharge_info):
    patient_id = discharge_info.patient_id
    encounter_id = discharge_info.encounter_id

    // --- Current Encounter Features ---
    // Query HealthLake for the index admission details
    encounter = FHIR_SEARCH("Encounter", id=encounter_id)
    conditions = FHIR_SEARCH("Condition", encounter=encounter_id)
    medications = FHIR_SEARCH("MedicationRequest", encounter=encounter_id)
    labs = FHIR_SEARCH("Observation", encounter=encounter_id, category="laboratory")
    procedures = FHIR_SEARCH("Procedure", encounter=encounter_id)

    current_features = {
        length_of_stay: encounter.length_of_stay_days,
        admission_source: encounter.admission_source,  // ED, elective, transfer
        discharge_disposition: encounter.discharge_disposition,
        primary_diagnosis_code: encounter.primary_diagnosis.icd10,
        diagnosis_count: COUNT(conditions),
        procedure_count: COUNT(procedures),
        icu_days: calculate_icu_days(encounter),
        discharge_medication_count: COUNT(medications WHERE status="active"),
        high_risk_medications: COUNT(medications WHERE code IN HIGH_RISK_MED_LIST),
        // Lab values at discharge (most recent)
        albumin_last: most_recent_value(labs, code="1751-7"),
        creatinine_last: most_recent_value(labs, code="2160-0"),
        hemoglobin_last: most_recent_value(labs, code="718-7"),
        sodium_last: most_recent_value(labs, code="2951-2"),
        bnp_last: most_recent_value(labs, code="42637-9")
    }

    // --- Historical Utilization Features ---
    // Look back 12 months for prior utilization patterns
    lookback_start = discharge_info.discharge_date - 365 days
    prior_encounters = FHIR_SEARCH("Encounter",
        patient=patient_id,
        date_range=[lookback_start, discharge_info.discharge_date],
        type="inpatient")
    prior_ed_visits = FHIR_SEARCH("Encounter",
        patient=patient_id,
        date_range=[lookback_start, discharge_info.discharge_date],
        type="emergency")

    history_features = {
        admissions_past_6mo: COUNT(prior_encounters WHERE date > now - 180 days),
        admissions_past_12mo: COUNT(prior_encounters),
        ed_visits_past_6mo: COUNT(prior_ed_visits WHERE date > now - 180 days),
        prior_30day_readmission: ANY(prior_encounters WHERE
            days_since_prior_discharge <= 30),
        days_since_last_admission: days_between(
            most_recent(prior_encounters).discharge_date,
            discharge_info.discharge_date)
    }

    // --- Comorbidity Features ---
    // Calculate Elixhauser comorbidity index from all active conditions
    all_conditions = FHIR_SEARCH("Condition", patient=patient_id, status="active")
    comorbidity_features = {
        elixhauser_score: calculate_elixhauser(all_conditions),
        has_chf: any_condition_in_group(all_conditions, "CHF"),
        has_diabetes: any_condition_in_group(all_conditions, "DIABETES"),
        has_copd: any_condition_in_group(all_conditions, "COPD"),
        has_ckd: any_condition_in_group(all_conditions, "CKD"),
        has_depression: any_condition_in_group(all_conditions, "DEPRESSION"),
        total_chronic_conditions: COUNT(all_conditions WHERE category="chronic")
    }

    // --- Demographic Features ---
    patient = FHIR_SEARCH("Patient", id=patient_id)
    demographic_features = {
        age: calculate_age(patient.birth_date),
        sex: patient.gender,
        insurance_type: patient.coverage_type,  // Medicare, Medicaid, Commercial
        zip_deprivation_index: lookup_adi(patient.address.postal_code)
    }

    // Combine all feature groups into single vector
    RETURN merge(current_features, history_features,
                 comorbidity_features, demographic_features)
```
### Step 3: Model Scoring

**What this does:** Passes the assembled feature vector to the trained XGBoost model and returns a readmission probability between 0 and 1.

**What goes wrong if you skip it:** Obviously you don't get a risk score. But more subtly, if you skip the preprocessing and validation step, you'll send malformed features to the model and get garbage predictions without any error signal.

```pseudocode
FUNCTION score_patient(feature_vector):
    // Validate feature completeness
    required_features = ["length_of_stay", "admissions_past_6mo",
                         "elixhauser_score", "age", "discharge_medication_count"]
    missing = [f FOR f IN required_features IF feature_vector[f] IS NULL]

    IF COUNT(missing) > 2:
        LOG_WARNING "Too many missing features for patient, using fallback score"
        RETURN {probability: null, method: "insufficient_data", missing: missing}

    // Handle missing values (model expects specific sentinel values)
    FOR each feature IN feature_vector:
        IF feature.value IS NULL:
            feature.value = -999  // XGBoost handles this as missing

    // Invoke the SageMaker endpoint
    response = SAGEMAKER_INVOKE(
        endpoint_name = "readmission-risk-v2",
        content_type = "text/csv",
        body = feature_vector_to_csv(feature_vector)
    )

    raw_probability = PARSE_FLOAT(response.body)

    // Apply calibration (Platt scaling learned during training)
    calibrated_probability = platt_scale(raw_probability,
        A = CALIBRATION_PARAMS.A,
        B = CALIBRATION_PARAMS.B)

    RETURN {
        probability: calibrated_probability,
        raw_score: raw_probability,
        method: "xgboost_v2",
        model_version: response.model_version,
        scored_at: NOW()
    }
```
### Step 4: Risk Stratification and Intervention Routing

**What this does:** Converts the raw probability into an actionable risk tier and determines which intervention pathway the patient should receive based on their risk level and contributing factors.

**What goes wrong if you skip it:** A probability of 0.42 means nothing to a care transition nurse. They need "high risk, prioritize for home health referral." Without stratification and routing, the model output sits in a database and nobody acts on it.

```pseudocode
FUNCTION stratify_and_route(score_result, feature_vector, discharge_info):
    probability = score_result.probability

    // Stratify into tiers based on calibrated thresholds
    // Thresholds are set based on intervention capacity and cost-effectiveness
    IF probability >= 0.35:
        risk_tier = "HIGH"
        intervention_level = "intensive"
    ELSE IF probability >= 0.20:
        risk_tier = "MEDIUM"
        intervention_level = "standard"
    ELSE:
        risk_tier = "LOW"
        intervention_level = "routine"

    // Determine primary risk drivers for intervention targeting
    // (from model feature importance for this specific patient)
    risk_drivers = get_top_contributing_features(feature_vector, top_n=5)

    // Route to appropriate intervention based on tier + drivers
    interventions = []

    IF risk_tier == "HIGH":
        // All high-risk patients get a nurse follow-up call within 48 hours
        interventions.ADD("nurse_callback_48hr")

        // Specific interventions based on risk drivers
        IF "discharge_medication_count" IN risk_drivers OR
           "high_risk_medications" IN risk_drivers:
            interventions.ADD("pharmacist_med_reconciliation")

        IF "admissions_past_6mo" IN risk_drivers:
            interventions.ADD("care_transition_program_enrollment")

        IF discharge_info.primary_diagnosis IN CHF_CODES:
            interventions.ADD("remote_weight_monitoring")

        IF feature_vector.zip_deprivation_index > 8:
            interventions.ADD("social_work_assessment")

    ELSE IF risk_tier == "MEDIUM":
        interventions.ADD("automated_check_in_call_day_7")
        interventions.ADD("ensure_followup_scheduled")

    // Store the complete risk assessment
    risk_assessment = {
        patient_id: discharge_info.patient_id,
        encounter_id: discharge_info.encounter_id,
        discharge_date: discharge_info.discharge_date,
        probability: probability,
        risk_tier: risk_tier,
        risk_drivers: risk_drivers,
        interventions: interventions,
        model_version: score_result.model_version,
        scored_at: score_result.scored_at,
        ttl: discharge_info.discharge_date + 45 days  // Keep 15 days past window
        // TODO (TechWriter): Expert review S4 (MEDIUM). Add note about compliance
        // retention requirements. 45-day TTL is operationally sound but scores that
        // influenced clinical decisions may need 6-10 year retention. Consider
        // archiving to S3 before TTL deletion.
    }

    // Write to DynamoDB for downstream system access
    DYNAMODB_PUT("readmission-risk-scores", risk_assessment)

    // Notify care team for high-risk patients
    // IMPORTANT: SNS messages with patient IDs + clinical indicators = PHI.
    // Restrict topic subscriptions to HIPAA-compliant endpoints only
    // (Lambda, SQS within VPC, or HTTPS endpoints under your BAA).
    // Never use email/SMS subscriptions for messages containing patient data.
    // If email alerts are needed, send minimal content ("1 new high-risk
    // discharge requires review") with a link to the secure dashboard.
    IF risk_tier == "HIGH":
        SNS_PUBLISH(
            topic = "high-risk-discharge-alerts",
            message = format_alert(risk_assessment),
            attributes = {
                "risk_tier": "HIGH",
                "primary_diagnosis": discharge_info.primary_diagnosis,
                "facility": discharge_info.facility_id
            }
        )

    RETURN risk_assessment
```
### Step 5: Outcome Tracking and Model Monitoring

**What this does:** Monitors actual 30-day readmission outcomes against predictions, detects model drift, and triggers retraining when performance degrades.

**What goes wrong if you skip it:** Your model silently degrades over time as patient populations shift, coding practices change, or new care programs alter readmission patterns. Without monitoring, you won't know your predictions are wrong until someone manually audits them months later.

```pseudocode
FUNCTION track_outcomes_and_monitor():
    // Run daily: check for readmissions among previously scored patients
    scored_patients = DYNAMODB_QUERY("readmission-risk-scores",
        discharge_date BETWEEN (today - 31 days) AND (today - 30 days))

    FOR each scored_patient IN scored_patients:
        // Check if patient was readmitted within 30 days
        readmissions = FHIR_SEARCH("Encounter",
            patient = scored_patient.patient_id,
            type = "inpatient",
            date_range = [scored_patient.discharge_date,
                         scored_patient.discharge_date + 30 days])

        // Exclude planned readmissions using CMS algorithm
        unplanned = FILTER(readmissions, is_unplanned_readmission)

        actual_outcome = 1 IF COUNT(unplanned) > 0 ELSE 0

        // Store outcome for model evaluation
        DYNAMODB_UPDATE("readmission-risk-scores",
            key = scored_patient.encounter_id,
            set actual_readmitted = actual_outcome,
            set outcome_date = NOW())

    // Weekly: calculate model performance metrics
    recent_scores = QUERY_LAST_30_DAYS_WITH_OUTCOMES()

    metrics = {
        auc_roc: calculate_auc(recent_scores.probability, recent_scores.actual),
        calibration_slope: calculate_calibration(recent_scores),
        brier_score: calculate_brier(recent_scores),
        observed_rate_high_tier: rate(recent_scores WHERE tier="HIGH"),
        observed_rate_low_tier: rate(recent_scores WHERE tier="LOW"),
        total_scored: COUNT(recent_scores),
        total_readmitted: SUM(recent_scores.actual)
    }

    // Publish metrics to CloudWatch
    CLOUDWATCH_PUT_METRICS("ReadmissionModel", metrics)

    // Alert if performance degrades
    IF metrics.auc_roc < 0.65 OR metrics.calibration_slope < 0.8:
        SNS_PUBLISH("model-performance-alerts",
            "Readmission model performance degraded. AUC: {metrics.auc_roc}. "
            "Consider retraining.")

    RETURN metrics
```
> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter07.05-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

## Variations and Extensions

### Condition-Specific Models

Instead of one general readmission model, train separate models for high-volume conditions (CHF, COPD, pneumonia, surgical). Condition-specific models can use disease-specific features (ejection fraction for CHF, FEV1 for COPD, surgical site details for orthopedic) that a general model would dilute. The tradeoff: you need enough volume per condition to train reliable models, and you need to maintain multiple model endpoints. For large hospital systems with 500+ discharges per condition per year, this approach typically adds 2-5 points of AUC over a general model.

### Real-Time Risk Updating

Rather than scoring once at discharge, update the risk score as post-discharge information becomes available. Did the patient fill their prescriptions? (Pharmacy claims data, available within 24-48 hours.) Did they attend their follow-up? (Scheduling system data.) Did they call the nurse line with concerning symptoms? Each new data point can update the probability, allowing you to escalate or de-escalate interventions dynamically. This requires a streaming architecture (Kinesis or Kafka) rather than batch, but it catches the patients who were medium-risk at discharge but became high-risk three days later.

### Integration with Remote Patient Monitoring

For high-risk patients with connected devices (weight scales for CHF, pulse oximeters for COPD, blood pressure cuffs for hypertension), combine the discharge risk score with real-time physiological data. A patient who was scored as medium-risk at discharge but shows a 5-pound weight gain over 3 days should be escalated to high-risk immediately. This bridges the gap between the discharge-time prediction and the post-discharge reality.

---

## Additional Resources

### AWS Documentation

- [Amazon SageMaker XGBoost Algorithm](https://docs.aws.amazon.com/sagemaker/latest/dg/xgboost.html) - Built-in XGBoost container configuration, hyperparameter tuning, and deployment patterns
- [Amazon HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html) - FHIR data store setup, data ingestion, and search capabilities
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html) - Workflow orchestration patterns, error handling, and retry configuration
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html) - Event-driven architecture patterns and event filtering
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html) - Automated model quality monitoring and drift detection
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) - Current list of services covered under AWS BAA

### AWS Sample Repos

- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples) - Comprehensive SageMaker examples including XGBoost training, deployment, and monitoring patterns
- [`amazon-healthlake-server-cdk`](https://github.com/aws-samples/amazon-healthlake-server-cdk) - CDK constructs for deploying HealthLake with security best practices
- [`aws-step-functions-data-science-sdk-python`](https://github.com/aws/aws-step-functions-data-science-sdk-python) - Python SDK for building ML workflows with Step Functions

### Industry References

- [CMS Hospital Readmissions Reduction Program](https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/hospital-readmissions-reduction-program-hrrp) - Official program documentation, penalty methodology, and condition-specific measures
- [MIMIC-IV Clinical Database](https://physionet.org/content/mimiciv/) - Publicly available ICU dataset commonly used for readmission prediction research and model development
- [CMS Quality Measures - Hospital Inpatient Quality Reporting](https://qualitynet.cms.gov/) - Detailed risk-adjustment methodology for each HRRP condition, including the Yale/CORE readmission measures

---

## Estimated Implementation Time

| Phase | Duration | What You Get |
|-------|----------|--------------|
| **Basic** | 6-8 weeks | LACE-based scoring at discharge, manual worklist generation, retrospective validation |
| **Production-ready** | 4-6 months | ML model with real-time scoring, automated intervention routing, EHR integration, outcome tracking |
| **With variations** | 8-12 months | Condition-specific models, real-time risk updating, RPM integration, multi-site deployment |

---

**Tags:** `predictive-analytics`, `readmission`, `risk-scoring`, `care-transitions`, `quality-measures`, `HRRP`, `XGBoost`, `SageMaker`, `HealthLake`, `HIPAA`

---

[← Recipe 7.4: ED Visit Prediction](chapter07.04-ed-visit-prediction) | [Chapter 7 Index](chapter07-preface) | [Recipe 7.6: Rising Risk Identification →](chapter07.06-rising-risk-identification)


---

*← [Main Recipe 7.5](chapter07.05-30-day-readmission-risk) · [Python Example](chapter07.05-python-example) · [Chapter Preface](chapter07-preface)*
