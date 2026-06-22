# Recipe 12.8 Architecture and Implementation: Disease Progression Trajectory Modeling

*Companion to [Recipe 12.8: Disease Progression Trajectory Modeling](chapter12.08-disease-progression-trajectory-modeling). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

The AWS implementation centers on three platform choices that shape everything else: HealthLake as the longitudinal patient store, SageMaker as the model training and hosting environment, and Step Functions as the orchestration backbone. The other services support specific stages.

### Why These Services

**Amazon HealthLake for longitudinal FHIR storage.** Disease progression trajectory modeling lives or dies on the quality of its longitudinal patient record. A patient's eGFR over nine years, their kidney volume measurements, their medication history, their problem list, and their outcomes need to be queryable as a single longitudinal bundle, not stitched together from a dozen source systems on every inference. [HealthLake](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html) is built to be exactly that store: ingest FHIR resources from any source, normalize, index, expose through a queryable FHIR API. For trajectory work, it is the right primary store.

**Amazon S3 for derived datasets, models, and forecasts.** The cohort-defined harmonized training datasets live in S3 partitioned by disease cohort. Trained model artifacts (mixed-effects model parameters, Bayesian posterior samples, hierarchical model state, trial-literature effect-size tables) live in S3. Per-patient forecasts and counterfactual scenarios are written to S3 as the analytic record before being summarized into the serving store. S3 is also the durable archive for cohort-definition logic, treatment-effect priors, and model version metadata.

**AWS Glue for cohort definition and harmonization.** Glue ETL jobs handle the heavy lifting: phenotype-based cohort identification, longitudinal harmonization (canonical units, canonical LOINC codes, time-frame normalization), acute-versus-chronic tagging, and the construction of training and inference-ready datasets. The jobs run on a cadence (weekly is typical for chronic-disease cohorts) and their output is the input to the trajectory model.

**Amazon SageMaker for trajectory model training and inference.** Trajectory models are not one-size-fits-all; the choice of mixed-effects, Bayesian hierarchical, joint model, or Gaussian process depends on the disease. SageMaker's flexibility on container images is what makes per-disease method choice tractable. Training runs as SageMaker Training jobs (often using PyMC, Stan, NumPyro, or statsmodels containers); inference is hosted on real-time endpoints for fast counterfactual scenario evaluation, or run as Batch Transform jobs for the nightly per-patient forecast refresh.

**AWS Step Functions for orchestration.** The training and inference pipelines have multiple steps with explicit retry and partial-failure semantics: refresh cohort, harmonize, train (or refresh) the disease-specific model, run per-patient inference, compute counterfactuals, write results to the serving store. Step Functions makes this orchestrable, auditable, and resumable.

**AWS Lambda for counterfactual scenario evaluation.** Once the trajectory model is hosted on a SageMaker endpoint, Lambda fronts the counterfactual API: clinician requests "what does this patient's trajectory look like if we start tolvaptan in three months," the Lambda composes the request (current trajectory, treatment-effect prior, time horizon), calls the SageMaker endpoint, post-processes the result, and returns a payload to the clinical surface. The counterfactual composer is functionally equivalent to ordering a clinical analytic test: it consumes patient PHI, runs a SaMD-adjacent computation, and returns a clinical-decision-supporting output. The privileged-action posture requires authentication (Cognito or institutional IdP via API Gateway), authorization (the requesting clinician must have a clinical relationship to the patient, validated against the EHR's relationship-of-care store), audit logging (every counterfactual request and response stored with patient_id, clinician_id, scenario_spec, model_version, and timestamp), and rate limiting (per-clinician, per-patient, per-day caps to prevent scenario-mining patterns that could indicate inappropriate data access or model probing).

**Amazon DynamoDB for low-latency clinical surfaces.** Per-patient forecasts and time-to-endpoint hazards get written to DynamoDB keyed by patient and disease cohort. The EHR integration, the population-health dashboard, and the patient-facing portal all read from DynamoDB at single-digit-millisecond latency.

**Amazon EventBridge for scheduling.** Weekly cohort refresh, monthly model retraining, daily per-patient inference: EventBridge Scheduler triggers each cadence. For high-priority changes (a new clinical trial publishes a definitive effect-size update for tolvaptan), EventBridge can trigger an immediate priors-and-retrain pipeline.

**AWS KMS for customer-managed encryption.** Disease cohort data is PHI of the highest sensitivity (rare-disease cohorts can be re-identifiable even with standard de-identification, and progression data tied to specific phenotypes is genetically suggestive). Customer-managed CMKs per data class are non-negotiable.

**Amazon CloudWatch for monitoring and alarming.** Pipeline health, training-job convergence diagnostics, inference latency, calibration metrics on backtested forecasts, and drift in cohort distributions all get logged. Calibration drift is the single most important operational metric: a trajectory system whose 90% credible intervals stop containing 90% of out-of-sample observations has a calibration problem that must be detected and remediated.

**Multi-disease parallelism.** The architecture as drawn shows one pipeline for one disease cohort. At institutional scale (five to fifteen disease cohorts is typical for a large academic medical center), each disease has its own cohort-definition config, its own training Step Functions state machine, its own model-artifact prefix (with per-disease KMS CMKs), its own DynamoDB partition prefix, and its own EventBridge schedule. The Step Functions and SageMaker layers are reused across diseases: one trajectory-pipeline state machine template, parameterized by disease; one set of training-and-inference container images that read disease-specific configs at runtime. Per-disease isolation is implemented at the IAM role level (one role per disease-pipeline, scoped to the disease's CMKs and S3 prefixes) and at the audit-log level (every record carries the disease name as a top-level attribute). Expect five-to-fifteen Step Functions executions in parallel on a typical schedule, with per-disease independent failure recovery so a training convergence problem in one cohort does not block inference for others.

### Architecture Diagram

```mermaid
flowchart LR
    A[EHR Sources<br/>FHIR / HL7 / Imaging] -->|Ingest| B[Amazon HealthLake<br/>FHIR Datastore]
    B -->|FHIR Query| C[Glue ETL<br/>Cohort + Harmonization]
    C -->|Training dataset| D[S3 Bucket<br/>cohort-datasets/]
    D -->|Train| E[SageMaker Training<br/>per-disease model]
    E -->|Model artifacts| F[S3 Bucket<br/>model-artifacts/]
    F -->|Deploy| G[SageMaker Endpoint<br/>trajectory inference]
    H[EventBridge Schedule<br/>nightly + weekly + monthly] -->|Trigger| I[Step Functions<br/>trajectory-pipeline]
    I -->|Invoke| G
    I -->|Per-patient forecasts| J[S3 Bucket<br/>forecasts/]
    J -->|Lambda| K[Counterfactual<br/>Composer]
    K -->|Surfaced trajectories| L[DynamoDB<br/>patient-trajectories]
    L -->|Query| M[EHR CDS Hooks /<br/>Specialist Dashboard /<br/>Patient Portal]
    I -->|Errors / metrics| N[CloudWatch<br/>Alarms + SNS]
    O[Clinical Trial<br/>Effect-Size Priors] -->|S3| F

    style B fill:#ff9,stroke:#333
    style E fill:#9f9,stroke:#333
    style G fill:#9f9,stroke:#333
    style L fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon HealthLake, Amazon S3, AWS Glue, Amazon SageMaker, AWS Lambda, Amazon DynamoDB, AWS Step Functions, Amazon EventBridge, AWS KMS, Amazon CloudWatch |
| **IAM Permissions** | `healthlake:SearchWithGet`, `healthlake:ReadResource`, `s3:GetObject`, `s3:PutObject`, `glue:StartJobRun`, `sagemaker:CreateTrainingJob`, `sagemaker:InvokeEndpoint`, `sagemaker:CreateTransformJob`, `lambda:InvokeFunction`, `dynamodb:BatchWriteItem`, `dynamodb:Query`, `states:StartExecution`, `kms:Decrypt`, `kms:Encrypt`. Each pipeline component runs under a least-privilege role scoped to its data class. |
| **BAA** | AWS BAA signed. Trajectory data is PHI in the strongest sense: longitudinal disease-specific records tied to genetic phenotypes are inherently re-identifiable. Every storage and compute service touching this pipeline must be on the [HIPAA eligible services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) list. |
| **Encryption** | S3: SSE-KMS with customer-managed CMKs per data class (cohort datasets, model artifacts, forecasts, priors). HealthLake: KMS-encrypted datastore. DynamoDB: encryption at rest with customer-managed CMK. SageMaker training and inference: KMS-encrypted EBS volumes and KMS-encrypted output. CloudWatch log groups: explicit KMS encryption. TLS 1.2 minimum in transit. |
| **VPC** | Production: SageMaker training, inference, and processing in private subnets with VPC endpoints for S3 (gateway), HealthLake (interface), DynamoDB (gateway), KMS (interface), Step Functions (interface), CloudWatch Logs (interface), CloudWatch Monitoring (interface), SageMaker API/Runtime (interface), EventBridge (interface), Lambda (interface), Glue (interface), and Secrets Manager (interface, required for external API credentials such as EHR integration credentials and clinical-trial-literature feed credentials). No NAT egress for PHI-touching workloads; restrictive egress on Lambda VPCs and SageMaker endpoint subnets. Required posture for HIPAA workloads with PHI of this sensitivity. |
| **Availability** | Multi-AZ deployment for SageMaker real-time endpoints, DynamoDB (multi-AZ by default), and Lambda compute fronting clinician-facing surfaces. Trajectory inference pipeline: RTO of 4 hours, RPO of 24 hours (surfaced trajectories are recomputed nightly; one-day staleness during a regional incident is clinically tolerable since the underlying disease progression operates on a multi-month-to-multi-year horizon). Cohort-and-training pipeline: RTO of 24 hours, RPO of 7 days (training cadence is monthly; a week of staleness is acceptable during recovery). |
| **Time** | Amazon Time Sync Service for all AWS-hosted compute. Observation timestamps stored in UTC in the durable archive (HealthLake and S3). Clinical surfaces display institution-local time when shown to a clinician at the bedside. Time-zone handling is explicit in the harmonization layer to prevent off-by-one-day errors in time-since-diagnosis calculations. |
| **CloudTrail** | Enabled for all data-plane services, with CloudTrail data events on every PHI-bearing S3 bucket and the DynamoDB serving table. The audit trail of who accessed which patient's trajectory is non-negotiable, especially for rare-disease cohorts. CloudTrail logs land in a dedicated S3 bucket with Object Lock in compliance mode. |
| **Sample Data** | Synthetic FHIR data from [Synthea](https://github.com/synthetichealth/synthea) supplemented with disease-specific synthetic generators (Synthea's CKD module produces longitudinal eGFR trajectories suitable for development). [MIMIC-IV](https://physionet.org/content/mimiciv/) provides de-identified inpatient labs through PhysioNet credentialing; useful for validation but limited for chronic outpatient trajectories. Disease-specific registry data are gold standard for validation but require formal data-use agreements. Never use real PHI in dev. |
| **Cost Estimate** | HealthLake: ~$200-$800/month depending on cohort size and data volume. SageMaker training (Bayesian hierarchical model, monthly retrain): ~$200-$600/month. SageMaker inference endpoint: ~$100-$400/month. Glue ETL (weekly cohort refresh): ~$50-$150/month. Lambda, DynamoDB, S3, Step Functions, EventBridge: ~$100/month combined. KMS, CloudWatch, audit: ~$50/month. Total: ~$800-$3,500/month per disease-cohort workload depending on cohort size, data density, and model complexity. Multi-disease scaling note: costs do not multiply linearly. HealthLake storage and Glue ETL scale roughly linearly with cohort size; SageMaker training scales sub-linearly when on-demand training jobs reuse one container image across multiple disease-specific training runs; SageMaker inference and the Lambda/DynamoDB serving layer scale roughly linearly with active-patient count. Five cohorts at the smaller end is closer to ~$2,500/month total than five times $800; five cohorts at the larger end is closer to ~$14,000/month total than five times $3,500. Engage AWS Solutions Architecture for a worked sizing exercise before committing to a multi-disease rollout. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon HealthLake** | Longitudinal FHIR datastore for the patient record; primary source for cohort definition queries and inference inputs |
| **Amazon S3** | Stores cohort-defined training datasets, trained model artifacts, per-patient forecasts, counterfactual scenarios, treatment-effect priors, and clinical-trial-derived metadata |
| **AWS Glue** | Cohort identification jobs (phenotype-based), longitudinal harmonization (units, codes, time frames), acute-versus-chronic tagging, training-dataset construction |
| **Amazon SageMaker** | Hosts per-disease trajectory models (mixed-effects, Bayesian hierarchical, joint, GP); supports training, real-time endpoints for counterfactual evaluation, and Batch Transform for nightly population-scale forecasting |
| **AWS Lambda** | Counterfactual scenario composer (compose treatment-modifier requests, call SageMaker endpoint, post-process); CDS Hooks responder; calibration-monitor jobs |
| **Amazon DynamoDB** | Serves per-patient trajectory forecasts and time-to-endpoint hazards to clinical surfaces at low latency |
| **AWS Step Functions** | Orchestrates the training pipeline (cohort -> harmonize -> train -> validate -> deploy) and the inference pipeline (refresh -> infer -> counterfactual -> deliver) with explicit retry and error handling |
| **Amazon EventBridge** | Triggers the weekly cohort refresh, the monthly model retrain, the nightly per-patient inference, and ad-hoc priors-update pipelines |
| **AWS KMS** | Manages customer-managed CMKs per data class (cohort data, model artifacts, forecasts, serving table, audit logs) |
| **Amazon CloudWatch** | Logs, metrics, alarms for pipeline health, training convergence diagnostics, inference latency, and calibration drift on backtested forecasts |

### Code

> **Reference implementations:** The following AWS sample resources demonstrate the patterns used in this recipe:
>
> - [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html): The FHIR datastore that backs the longitudinal patient record
> - [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Official SageMaker examples including custom inference container patterns and Bayesian model deployment
> - [AWS Step Functions Workflow Studio](https://docs.aws.amazon.com/step-functions/latest/dg/workflow-studio.html): For visually composing the training and inference pipelines

#### Walkthrough

**Step 1: Define the disease cohort.** The pipeline starts by identifying which patients in the longitudinal store belong in the disease cohort. This is more involved than running a single ICD-10 query. Real cohorts blend ICD codes, lab thresholds, problem-list entries, sometimes confirmatory imaging or genetic testing, and almost always exclude patients with conflicting diagnoses or incomplete histories. The cohort definition is itself a clinical artifact that must be reviewed by a disease specialist and versioned as code, because changes to the cohort definition retroactively change every downstream forecast.

```text
FUNCTION define_disease_cohort(disease_definition, healthlake_datastore):
    // The disease_definition is a versioned, clinician-reviewed configuration.
    // For ADPKD it might look like:
    //   inclusion_icd10:    ["Q61.2", "Q61.3"]                   // ADPKD codes
    //   inclusion_problems: ["polycystic kidney disease"]
    //   confirmatory_genetic: optional but increases confidence
    //   exclusion_icd10:    ["Q61.4", "Q61.5"]                   // other cystic diseases
    //   minimum_observation_window_months: 12
    //   minimum_egfr_measurements: 3

    candidate_patients = query_healthlake(
        datastore = healthlake_datastore,
        filter    = "Condition.code IN disease_definition.inclusion_icd10
                     OR Condition.code IN disease_definition.inclusion_problems"
    )

    cohort = []
    FOR patient IN candidate_patients:
        // Pull the relevant longitudinal data for cohort qualification.
        history = query_patient_history(
            datastore = healthlake_datastore,
            patient_id = patient.id,
            resource_types = [Condition, Observation, MedicationRequest, Procedure, DiagnosticReport]
        )

        // Apply exclusions (other cystic kidney diseases, transplant status, etc.).
        IF has_any_exclusion(history, disease_definition.exclusion_icd10):
            continue

        // Require minimum observation window so trajectory analysis is meaningful.
        observation_span_months = compute_observation_span(history)
        IF observation_span_months < disease_definition.minimum_observation_window_months:
            continue

        // Require minimum density of trajectory-relevant measurements.
        egfr_count = count_chronic_context(history, loinc_code="48642-3")  // eGFR
        IF egfr_count < disease_definition.minimum_egfr_measurements:
            continue

        // Capture the qualifying signals so they are auditable.
        cohort.append({
            patient_id:           patient.id,
            qualified_by_icd:     intersection(history.icd_codes, disease_definition.inclusion_icd10),
            qualified_by_problem: intersection(history.problems, disease_definition.inclusion_problems),
            confirmatory_genetic: has_confirmatory_genetic_test(history),
            observation_span:     observation_span_months,
            cohort_definition_version: disease_definition.version,
            qualified_at_ts:      now()
        })

    write cohort to S3 cohort-datasets/{disease_definition.name}/{disease_definition.version}/
    RETURN cohort
```

**Step 2: Harmonize the longitudinal trajectory data.** Once a patient is in the cohort, their longitudinal data must be transformed into a clean, harmonized matrix that the trajectory model can consume. Units are converted to canonical UCUM codes per LOINC. Time is anchored to a meaningful reference frame (often time-since-diagnosis, sometimes time-since-treatment-start, sometimes calendar time). Acute-context measurements are tagged and excluded from the chronic trajectory. Treatment history is aligned to the same time frame. Genetic and imaging data are joined where available.

```text
FUNCTION harmonize_trajectory_data(cohort_member, healthlake_datastore):
    history = query_patient_history(
        datastore = healthlake_datastore,
        patient_id = cohort_member.patient_id
    )

    // Identify the time-zero anchor. For ADPKD it might be earliest qualifying ICD-10 date;
    // for CKD it might be earliest eGFR < 60; the choice is disease-specific.
    time_zero = compute_time_zero(history, cohort_member.disease_definition_version)

    harmonized_observations = []
    FOR obs IN history.observations:
        // Map to canonical LOINC code.
        canonical_loinc = lookup_loinc_mapping(obs.system, obs.code)
        IF canonical_loinc is null:
            log "unmapped" and continue

        // Convert units to canonical UCUM unit.
        canonical_value = convert_units(obs.value, obs.unit, canonical_loinc)
        IF canonical_value is null:
            log "unit conversion failed" and continue

        // Tag context. Outpatient clinic visits and routine outpatient labs are chronic.
        // Inpatient and emergency are acute and excluded from trajectory training.
        context_tag = classify_encounter_context(obs.encounter_id, history.encounters)

        // Compute time-since-diagnosis in months for trajectory modeling.
        months_from_zero = (obs.collection_ts - time_zero) / months

        harmonized_observations.append({
            patient_id:        cohort_member.patient_id,
            loinc_code:        canonical_loinc,
            value:             canonical_value,
            collection_ts:     obs.collection_ts,
            months_from_zero:  months_from_zero,
            context_tag:       context_tag
        })

    // Treatment history aligned to the same time frame.
    harmonized_treatments = []
    FOR med IN history.medications:
        canonical_drug = lookup_rxnorm_mapping(med.code)
        IF canonical_drug in disease_relevant_drugs(cohort_member.disease_definition_version):
            harmonized_treatments.append({
                patient_id:          cohort_member.patient_id,
                drug:                canonical_drug,
                drug_class:          lookup_drug_class(canonical_drug),
                start_months_from_zero: (med.start_ts - time_zero) / months,
                end_months_from_zero:   (med.end_ts - time_zero) / months IF med.end_ts ELSE null,
                dose:                med.dose
            })

    harmonized = {
        patient_id:                cohort_member.patient_id,
        time_zero:                 time_zero,
        observations:              harmonized_observations,
        treatments:                harmonized_treatments,
        cohort_definition_version: cohort_member.cohort_definition_version
    }

    write harmonized to S3 cohort-datasets/{disease}/harmonized/

    RETURN harmonized
```

**Step 3: Train the disease-specific trajectory model.** The model captures the population-level disease shape, the per-patient deviations, and the effects of interventions. The choice of model family is disease-specific (linear mixed-effects for CKD on eGFR, non-linear for ADPKD on kidney volume, joint model when time-to-endpoint is the primary clinical question, Bayesian hierarchical when explicit uncertainty is needed). Training runs on the harmonized cohort dataset. Disease-specific priors from the clinical literature anchor the model.

```text
FUNCTION train_trajectory_model(disease_name, harmonized_cohort, model_config, priors):
    // model_config is a versioned, clinically-reviewed configuration:
    //   model_family:          "bayesian_hierarchical_linear_mixed_effects"
    //   outcome_loinc:         "48642-3"  // eGFR
    //   outcome_transform:     "identity" or "log" or "logit"
    //   covariates:            ["age_at_time_zero", "sex", "baseline_egfr", "diabetes_status"]
    //   treatment_covariates:  ["acei_arb_active", "sglt2_active", "tolvaptan_active"]
    //   random_effects:        ["intercept", "slope"]
    //   endpoint_definitions:  [
    //       { name: "transplant_evaluation",    loinc: "48642-3", threshold: 20, direction: "below" },
    //       { name: "vascular_access_planning", loinc: "48642-3", threshold: 17, direction: "below" },
    //       { name: "rrt_consideration",        loinc: "48642-3", threshold: 15, direction: "below" }
    //   ]
    //   prior_population_slope: -3.0                  // mL/min/1.73m^2/year, from CKD literature
    //   prior_population_slope_sd: 1.0
    //   prior_per_patient_slope_sd: 4.0               // patient heterogeneity
    //   prior_treatment_effect_acei_arb: -0.5         // slope modifier per published trial evidence
    //   prior_treatment_effect_sglt2:    -1.5

    training_dataset = build_training_matrix(harmonized_cohort, model_config)

    // Hold out a temporal validation slice so calibration can be measured honestly.
    train_slice, validation_slice = temporal_holdout_split(
        dataset            = training_dataset,
        holdout_fraction   = 0.2,
        holdout_strategy   = "last_n_visits_per_patient"
    )

    // Fit the model. The actual call depends on the family. For a Bayesian
    // hierarchical mixed-effects model in PyMC or Stan, this is a sampling
    // step (NUTS) that produces posterior samples for population and per-patient
    // parameters, plus treatment-effect modifiers.
    model = fit_model(
        family    = model_config.model_family,
        data      = train_slice,
        priors    = priors,
        config    = model_config
    )

    // Validate calibration on the temporal holdout.
    calibration = compute_calibration_metrics(
        model       = model,
        validation  = validation_slice,
        intervals   = [50, 80, 90, 95]
    )
    // Calibration metrics include: empirical coverage of credible intervals
    // (does the 90% interval actually contain 90% of held-out observations?),
    // continuous ranked probability score, mean absolute error of point forecasts.

    // Validate against published clinical-literature benchmarks for this disease.
    literature_consistency = compare_to_literature(
        model_population_slope = model.population_slope,
        published_slope_range  = priors.published_population_slope_range
    )

    artifact = {
        model_state:          serialize_model(model),
        calibration:          calibration,
        literature_consistency: literature_consistency,
        cohort_size:          count(harmonized_cohort),
        model_config:         model_config,
        priors:               priors,
        trained_at_ts:        now(),
        cohort_definition_version: model_config.cohort_definition_version,
        model_version:        compute_version_hash(model_config, priors, cohort_size)
    }

    write artifact to S3 model-artifacts/{disease_name}/{artifact.model_version}/

    RETURN artifact
```

**Step 4: Per-patient trajectory inference.** With the trained model in hand, the pipeline produces a fitted trajectory through each patient's observed history and a forward forecast under the assumption of "current treatment continued." The forecast is a posterior distribution, not a point estimate; the uncertainty bands are first-class outputs.

```text
FUNCTION infer_patient_trajectory(patient_harmonized_data, trained_model, forecast_horizon_months = 60):
    // Generate the fitted trajectory through the observed history.
    fitted_trajectory = model_predict(
        model      = trained_model,
        patient    = patient_harmonized_data,
        time_grid  = patient_harmonized_data.observation_times
    )
    // fitted_trajectory contains posterior median + credible intervals at each observed time.

    // Generate the forward forecast under "current treatment continued".
    forecast_time_grid = build_forecast_grid(
        from_months = patient_harmonized_data.last_observation_months,
        to_months   = patient_harmonized_data.last_observation_months + forecast_horizon_months,
        grid_step   = 3                                  // months
    )
    forecast = model_predict(
        model            = trained_model,
        patient          = patient_harmonized_data,
        time_grid        = forecast_time_grid,
        treatment_assumption = "current_treatment_continued"
    )

    // Compute time-to-endpoint hazards for each clinical endpoint defined
    // in the model config. Real ADPKD trajectory modeling at this fidelity
    // tracks multiple milestones: transplant evaluation, vascular access
    // planning, and RRT consideration each have distinct thresholds and
    // distinct clinical actions.
    IF trained_model.has_endpoint_component:
        time_to_endpoints = {}
        FOR endpoint IN trained_model.endpoint_definitions:
            time_to_endpoints[endpoint.name] = compute_time_to_endpoint(
                model     = trained_model,
                patient   = patient_harmonized_data,
                endpoint  = endpoint,
                time_grid = forecast_time_grid
            )
            // Each entry contains: P(endpoint by month T) curves with credible
            // intervals, median time to endpoint, P10 and P90 time to endpoint.
    ELSE:
        time_to_endpoints = null

    inference_result = {
        patient_id:         patient_harmonized_data.patient_id,
        cohort_definition_version: patient_harmonized_data.cohort_definition_version,
        model_version:      trained_model.model_version,
        fitted_trajectory:  fitted_trajectory,
        forecast:           forecast,
        time_to_endpoints:  time_to_endpoints,
        inferred_at_ts:     now()
    }

    write inference_result to S3 forecasts/{disease}/{patient_id}/{inferred_at_ts}/

    RETURN inference_result
```

**Step 5: Counterfactual treatment scenario evaluation.** This is the architecturally distinctive step for trajectory modeling, and it is where most of the clinical value sits. The clinician asks "what does this patient's trajectory look like if we start tolvaptan in three months versus continuing current therapy?" The pipeline composes both scenarios, calls the model with the corresponding treatment-modifier specifications, and returns the comparison. The trial-literature-derived effect-size priors live in the model and propagate into the counterfactual forecasts as calibrated uncertainty.

```text
FUNCTION evaluate_counterfactual_scenarios(
    patient_harmonized_data,
    trained_model,
    scenarios,
    forecast_horizon_months = 60
):
    // scenarios is a list of treatment-change specifications:
    //   [ { name: "current_continued",        change: null },
    //     { name: "start_tolvaptan_now",      change: { drug: "tolvaptan", start_offset_months: 0 } },
    //     { name: "start_tolvaptan_in_6mo",   change: { drug: "tolvaptan", start_offset_months: 6 } },
    //     { name: "switch_acei_to_arb",       change: { drug_class_swap: ["acei", "arb"], start_offset_months: 0 } } ]

    forecast_time_grid = build_forecast_grid(
        from_months = patient_harmonized_data.last_observation_months,
        to_months   = patient_harmonized_data.last_observation_months + forecast_horizon_months,
        grid_step   = 3
    )

    counterfactual_results = []
    FOR scenario IN scenarios:
        // Apply the treatment change to the patient's projected treatment timeline.
        // IMPORTANT: apply_treatment_change must reconcile pre-existing exposure.
        // If the patient is already on the requested drug class, the function
        // returns the base timeline unchanged with a "already_on_class" flag
        // rather than appending a duplicate entry. Without this reconciliation,
        // duplicate entries compound multiplicatively in the treatment-effect
        // modifier: (1 - 0.30) * (1 - 0.30) = 0.49 instead of the correct 0.70,
        // producing a 25% over-attribution of treatment benefit. Production
        // implementations must check for pre-existing class exposure before
        // any append and surface the no-op to the clinical interface.
        modified_treatment_timeline, change_applied = apply_treatment_change(
            base_timeline = patient_harmonized_data.treatments,
            change        = scenario.change,
            anchor_time   = patient_harmonized_data.last_observation_months
        )
        // change_applied is false when the patient is already on the requested
        // drug class; the scenario result carries a flag so the clinical surface
        // can explain "patient is already on this therapy."

        // Predict under the modified scenario. The model uses the trial-literature-derived
        // effect-size posterior for the relevant drug or drug-class change. Uncertainty
        // propagates from both the trajectory model and the treatment-effect prior.
        scenario_forecast = model_predict(
            model              = trained_model,
            patient            = patient_harmonized_data,
            time_grid          = forecast_time_grid,
            treatment_timeline = modified_treatment_timeline
        )

        // Time-to-endpoint under the scenario, for each defined endpoint.
        IF trained_model.has_endpoint_component:
            scenario_time_to_endpoints = {}
            FOR endpoint IN trained_model.endpoint_definitions:
                scenario_time_to_endpoints[endpoint.name] = compute_time_to_endpoint(
                    model              = trained_model,
                    patient            = patient_harmonized_data,
                    treatment_timeline = modified_treatment_timeline,
                    endpoint           = endpoint,
                    time_grid          = forecast_time_grid
                )
        ELSE:
            scenario_time_to_endpoints = null

        counterfactual_results.append({
            scenario_name:       scenario.name,
            forecast:            scenario_forecast,
            time_to_endpoints:   scenario_time_to_endpoints,
            assumption_disclosure: build_assumption_disclosure(scenario, trained_model)
        })

    // Compose a comparison payload with explicit assumption disclosure.
    payload = {
        patient_id:           patient_harmonized_data.patient_id,
        scenarios:            counterfactual_results,
        baseline_scenario:    "current_continued",
        model_version:        trained_model.model_version,
        cohort_definition_version: patient_harmonized_data.cohort_definition_version,
        generated_at_ts:      now()
    }

    write payload to S3 counterfactuals/{disease}/{patient_id}/
    write summary to DynamoDB patient-trajectories with:
        partition_key = patient_id
        sort_key      = disease_name + "#" + generated_at_ts

    RETURN payload
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, PyMC for Bayesian hierarchical modeling, and statsmodels for mixed-effects fits, check out the [Python Example](chapter12.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample counterfactual trajectory payload for an ADPKD patient:**

```json
{
  "patient_id": "patient-9d2f481a",
  "disease_name": "adpkd",
  "model_version": "adpkd-bayesian-hierarchical-v4:priors-2026q1",
  "cohort_definition_version": "adpkd-cohort-v3",
  "time_zero_anchor": "diagnosis_date",
  "time_zero_ts": "2017-03-08",
  "last_observation_ts": "2026-04-08",
  "current_egfr": 58.2,
  "scenarios": [
    {
      "scenario_name": "current_continued",
      "forecast_5yr_egfr": {
        "p10": 24.1,
        "p50": 36.4,
        "p90": 48.2
      },
      "time_to_endpoints": {
        "transplant_evaluation": {
          "p10_months": 60,
          "p50_months": 96,
          "p90_months": 156
        },
        "vascular_access_planning": {
          "p10_months": 72,
          "p50_months": 114,
          "p90_months": 180
        },
        "rrt_consideration": {
          "p10_months": 84,
          "p50_months": 126,
          "p90_months": 192
        }
      }
    },
    {
      "scenario_name": "start_tolvaptan_now",
      "forecast_5yr_egfr": {
        "p10": 28.6,
        "p50": 40.9,
        "p90": 52.4
      },
      "time_to_endpoints": {
        "transplant_evaluation": {
          "p10_months": 78,
          "p50_months": 120,
          "p90_months": 192
        },
        "vascular_access_planning": {
          "p10_months": 90,
          "p50_months": 144,
          "p90_months": 216
        },
        "rrt_consideration": {
          "p10_months": 102,
          "p50_months": 156,
          "p90_months": 228
        }
      },
      "assumption_disclosure": "Effect size prior derived from TEMPO 3:4 trial (NCT00428948) and REPRISE trial (NCT02160145). 30% relative reduction in eGFR slope, 95% credible interval (0.18, 0.42). Assumes treatment continuation through forecast horizon."
    }
  ],
  "explanation_text": "Without intervention, this patient's eGFR is projected to cross the transplant-evaluation threshold (eGFR < 20) between 5 and 13 years from now (median 8 years), the vascular-access-planning threshold (eGFR ~15-20) between 6 and 15 years (median 9.5 years), and the renal-replacement-therapy consideration threshold (eGFR < 15) between 7 and 16 years (median 10.5 years). Starting tolvaptan now would shift the RRT median to approximately 13 years, with proportional improvements at each earlier milestone. Forecasts assume current treatment continued or the specified change, no acute events, and continued cohort-comparable disease behavior.",
  "uncertainty_disclosure": "Forecasts are statistical projections from a population model anchored to disease-specific clinical literature. Individual outcomes vary substantially. The model is informational; clinical decisions require integrated judgment.",
  "generated_at_ts": "2026-04-09T14:22:00Z"
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Cohort identification (50,000 candidate patients per disease) | 1-3 hours weekly |
| Harmonization (per qualified patient) | 200-800 ms |
| Model training (Bayesian hierarchical, 2,000-10,000 patient cohort) | 2-8 hours monthly |
| Per-patient inference latency (single scenario) | 100-500 ms |
| Counterfactual scenario evaluation (3-5 scenarios) | 300 ms-2 s |
| Calibration on temporal holdout (90% credible interval coverage) | 85-93% |
| Cost per disease-cohort workload per month | $800-$3,500 |

**Where it struggles:** Patients with fewer than three or four trajectory-relevant measurements (the per-patient layer cannot be estimated from too few observations). Patients with fewer than 12 months of observation history (the trajectory has not yet established a meaningful baseline). Patients undergoing active medication titration where the trajectory is changing for known reasons (the model may produce confidently wrong forecasts during the titration phase). Diseases with weak clinical research foundations (the literature priors are unreliable, and pure data-driven models extrapolate poorly). Rare diseases with cohorts under a few hundred patients (the population-level model is too noisy). Patients on combinations of interventions for which trial-derived effect sizes do not exist (the treatment-effect layer has to extrapolate). Acute episodes mixed into chronic-context training data (the model becomes whipsawed). Forecasts beyond 60-84 months for most chronic diseases (long-horizon extrapolation is fundamentally limited by the support of training data).

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. Deploying this to a real population requires addressing several gaps that are intentionally outside the scope of a cookbook recipe.

**Cohort definition governance.** The cohort definition is a clinical artifact that drifts. As clinical guidelines evolve, as new evidence shifts inclusion criteria, as the institution's coding practices change, the cohort definition must be updated. Without a governance process (versioning, clinician review, controlled rollout, retroactive recomputation of affected forecasts), the trajectory pipeline silently degrades. Production systems treat cohort definitions as code: stored in a versioned config repository, reviewed by both engineering and the disease specialty, and deployed with explicit migration paths for downstream forecasts. Skip this and the cohort definition will be six versions behind reality within two years.

**Treatment-effect prior maintenance.** The clinical-trial-derived effect sizes that anchor the counterfactual layer are not static. New trials publish, meta-analyses update, post-marketing studies refine the estimates. A production system has a maintained registry of relevant priors per disease, with sources, last-update dates, and confidence intervals, reviewed at a defensible cadence (quarterly is typical) by a disease-specific clinical advisor. The registry is itself a clinical artifact under change control. Without this, the counterfactual layer ages out of clinical alignment in eighteen to twenty-four months.

**Calibration drift detection.** A trajectory system whose 90% credible intervals stop containing 90% of out-of-sample observations has lost calibration. Production systems run a continuous calibration-monitoring job that backtests recent forecasts against subsequently observed outcomes and alarms when coverage drops below a configured threshold. Without this, the system can be wrong for months before anyone notices, and clinician trust takes years to rebuild.

**Loss-to-follow-up monitoring.** In chronic-disease cohorts, patients who progress fast are more likely to leave follow-up (transfer to specialty care, hospitalize, decease) and patients who feel well are more likely to stop coming in. Both directions of dropout produce informative censoring that biases the population-level prior estimation. Production systems run a continuous loss-to-follow-up monitor that compares the trajectory distribution of patients who left the cohort recently to the trajectory distribution of patients who remain; persistent divergence is the operational signal of informative censoring and triggers a model-and-prior review. Without this, the cohort's apparent disease behavior drifts away from the true disease behavior in subtle, slow ways that are extremely difficult to detect once they have accumulated.

**Multi-modal data integration.** Trajectory models gain meaningfully from integrating imaging-derived measurements (kidney volume on MRI for ADPKD, brain volumetrics for neurodegenerative diseases, tumor volumes for oncology), genetic markers (PKD1 versus PKD2 mutation, APOE genotype, tumor mutational burden), and structured assessments (UPDRS, MMSE, EDSS). The pipeline as drawn handles structured EHR data well; integrating imaging and genetics requires additional ingestion paths, additional harmonization (DICOM-derived measurements via Recipe 9.x; genomic data through specialized stores), and additional joins in the cohort harmonization step. Production systems for diseases where these modalities matter must have these integrations or they leave the most informative signals on the floor.

Multi-modal integration brings additional regulatory layers. Genetic data is covered by the Genetic Information Nondiscrimination Act (GINA) at the federal level and by stricter state laws in California, Florida, and several others. Institutional consent for genetic testing typically scopes data use narrowly (clinical care versus research versus prognostic modeling), and the trajectory pipeline must respect those scopes: a patient who consented to genetic testing for clinical-care purposes may not have consented to its use in a population-derived prognostic model. Imaging-derived measurements are HIPAA PHI plus the structural-imaging re-identifiability concern that complicates de-identification (facial structure in head MRIs, body habitus in abdominal imaging). The BAA and consent-and-authorization framing differs meaningfully between structured EHR data, genetic data, and imaging data. Engage the privacy office, genetic-counseling team, and imaging-informatics team before engineering work begins on any multi-modal extension.

**Patient-facing communication.** Surfacing a trajectory and its uncertainty to a patient is a fundamentally different problem than surfacing it to a clinician. The clinician understands that "P50 time to renal replacement therapy = 126 months, P10 = 84 months" means something specific. The patient needs the same information rendered as "we believe there is roughly a 50% chance you will need dialysis sometime in the next ten to fifteen years, and a 10% chance you will need it in the next seven years; treatments may shift these timelines." The translation is hard, the failure modes are unfamiliar to engineers, and the regulatory framing is more sensitive (patient-facing prognostic outputs are scrutinized more carefully than clinician-facing ones). Production systems either have a dedicated patient-communication layer designed by a clinical communication specialist or they explicitly restrict the surfaces to clinicians.

**Counterfactual assumption disclosure.** Every counterfactual forecast embeds assumptions: the treatment is taken as prescribed, the effect-size posterior is correctly specified, no other interventions occur, no acute events disrupt the trajectory, the disease behavior in this patient remains comparable to the cohort. Production systems make these assumptions explicit in the surfaced output (the "assumption_disclosure" field in the example payload above is a starting point, not a finished design). Clinicians and patients are entitled to know what the forecast is conditional on. Hiding the assumptions produces forecasts that look more authoritative than they should.

**Regulatory framing.** A trajectory system that triggers actionable clinical decisions sits squarely in the FDA software-as-a-medical-device (SaMD) regulatory landscape. A system that surfaces "your patient's trajectory suggests considering nephrology referral within twelve months" is plausibly clinical decision support and may qualify for the 21st Century Cures Act exemption from premarket review if it meets specific transparency and explainability requirements. A system that produces a "diagnosis" or "prognosis" output without those guardrails is not exempt. Working with regulatory counsel on the framing of the surfaced output and on the documentation supporting the transparency-and-explainability claim is non-negotiable for any deployment beyond a research pilot.

**Equity and bias auditing.** Trajectory models trained on a cohort that is not demographically representative produce forecasts that are miscalibrated for under-represented groups. The standard practice is to evaluate model calibration separately for major demographic subgroups (race, ethnicity, sex, age band, insurance type) and to publish the per-subgroup calibration as part of the model documentation. Where calibration differs meaningfully across subgroups, the model needs subgroup-specific recalibration or the deployment scope needs to be narrowed. Without this, the system silently underserves some populations more than others, which is a clinical failure even before it becomes a regulatory or ethical one.

**Model versioning and retroactive updates.** When the model is retrained or the cohort definition changes, every patient's forecasts implicitly change. A patient whose current displayed forecast was generated by model version v3 and whose v4 forecast differs materially needs a controlled update path. Production systems maintain model and cohort version metadata on every stored forecast, support side-by-side comparison of new and old forecasts, and have a defensible policy for when to surface the new forecast to the clinical team versus when to suppress it pending review. Without this, the trajectory you saw at the patient's last visit is not necessarily the trajectory you will see at their next visit, even if no new data has arrived.

**Idempotency and rerun safety.** The training and inference pipelines must be safe to repeat. Training is deterministic given the same dataset, model config, and priors (or, for stochastic training, reproducible given a fixed seed). Inference is deterministic given the same trained model and patient data. Counterfactual scenario evaluation is deterministic given the same model and treatment-change specification. DynamoDB writes are idempotent on (patient_id, disease_name, generated_at_ts). Without these properties, a pipeline rerun produces drift that is impossible to debug.

---

## Variations and Extensions

**Joint models for time-to-endpoint with informative censoring.** The basic pipeline above models the longitudinal trajectory and the time-to-endpoint as related but distinct components. A joint model fits them simultaneously, using the trajectory as a time-varying predictor of the hazard. For diseases where the time-to-endpoint is the clinically primary question (CKD progression to dialysis, ALS progression to ventilator dependence, IPF progression to transplant evaluation), joint models substantially improve the time-to-endpoint forecasts and tighten their credible intervals. Implementations in JM, JMbayes2 (R), or custom PyMC code; the engineering cost is moderate, the clinical value is high.

**Disease-specific multimodal integration.** For diseases where imaging or genetics carries strong signal (ADPKD with kidney volume on MRI, multiple sclerosis with brain atrophy, oncology with tumor volumes, neurodegenerative diseases with PET-derived biomarkers), extending the cohort harmonization to include these modalities improves trajectory forecasts substantially. The engineering work is in the ingestion path (Recipe 9.x covers DICOM-derived measurement extraction; genetics requires specialized stores) and in the joint trajectory model that consumes mixed-modality inputs.

**Continuous learning with new trial evidence.** When a new clinical trial publishes (or a meta-analysis updates), the treatment-effect priors should reflect the updated evidence. A continuous-learning pipeline ingests trial results into the prior registry, triggers an evaluation of which counterfactual scenarios are affected, and either rebuilds the priors automatically (for routine updates) or surfaces the change for clinical review (for material shifts). This is essentially Recipe 2.7 (Literature Search and Evidence Synthesis) wired into the trajectory pipeline as a continuously-updated input.

**Patient-facing explanation generation.** A safe patient-facing surface translates the model's forecasts and uncertainty into language a patient can understand and act on without overstating the certainty or the actionability. This is harder than it looks; the standard practice is to template the explanations against a clinically-reviewed library of permitted statements per disease and per scenario type, with explicit guardrails against generating statements that look like a diagnosis or a guarantee. LLMs (Recipe 2.x) can power the templating but should not be permitted to free-form generate the substantive content.

**Federated learning across institutions.** For rare diseases or for institutions whose cohort is too small to train a robust model alone, federated learning lets multiple institutions contribute to the same model without sharing patient data. The engineering work is real (secure aggregation, differential privacy, the federated training plane itself); the regulatory work is more real (the BAA structure for cross-institutional federated learning is genuinely novel territory in 2026, and most legal teams will not have a template). For the right disease cohorts, federated learning is the only credible path to a useful trajectory model. Plan on a multi-year, multi-institution effort, not an internal sprint.

---

## Additional Resources

**AWS Documentation:**
- [Amazon HealthLake Documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [Amazon HealthLake Pricing](https://aws.amazon.com/healthlake/pricing/)
- [Amazon SageMaker Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Bring Your Own Container](https://docs.aws.amazon.com/sagemaker/latest/dg/your-algorithms.html)
- [Amazon SageMaker Batch Transform](https://docs.aws.amazon.com/sagemaker/latest/dg/batch-transform.html)
- [AWS Step Functions Documentation](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon DynamoDB Documentation](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA Security and Compliance on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Official SageMaker examples including custom container patterns useful for hosting Bayesian or mixed-effects models
- [`aws-samples` GitHub Organization](https://github.com/aws-samples): Search for HealthLake and FHIR-related samples relevant to longitudinal patient data

**External Resources:**
- [Synthea Synthetic Patient Generator](https://github.com/synthetichealth/synthea): Realistic synthetic FHIR patient records including longitudinal disease progression for several chronic conditions
- [MIMIC-IV on PhysioNet](https://physionet.org/content/mimiciv/): De-identified hospital data for credentialed researchers; useful for validation of acute-versus-chronic discrimination logic
- [JM R package](https://cran.r-project.org/web/packages/JM/index.html) and [JMbayes2 R package](https://github.com/drizopoulos/JMbayes2): The standard implementations for joint models of longitudinal trajectories and time-to-event outcomes
- [PyMC](https://www.pymc.io/) and [Stan](https://mc-stan.org/): Bayesian modeling frameworks suitable for hierarchical trajectory models
- [statsmodels mixed-effects models](https://www.statsmodels.org/stable/mixed_linear.html): Python implementation of linear mixed-effects models suitable for trajectory work
- [lifelines](https://lifelines.readthedocs.io/): Python survival analysis library with growing support for joint models
- [CKD Prognosis Consortium tools](https://ckdpcrisk.org/): Clinical risk-prediction tools that demonstrate population-derived eGFR-decline modeling at scale
- [Forecasting: Principles and Practice (Hyndman & Athanasopoulos)](https://otexts.com/fpp3/): Free online textbook with strong chapters on hierarchical time series and state-space models
- [21st Century Cures Act Section 3060 (Clinical Decision Support)](https://www.fda.gov/medical-devices/software-medical-device-samd/clinical-decision-support-software): The FDA guidance that frames the regulatory exemption for transparent, explainable clinical decision support
- [TEMPO 3:4 trial publication](https://pubmed.ncbi.nlm.nih.gov/23121379/) and [REPRISE trial publication](https://pubmed.ncbi.nlm.nih.gov/29105594/): Foundational trials whose effect-size estimates anchor counterfactual scenarios for tolvaptan in ADPKD; example of the trial-literature-derived priors discussed in the recipe

**AWS Solutions and Blogs:**
- [AWS Solutions Library (Healthcare and AI/ML)](https://aws.amazon.com/solutions/): Filter by Healthcare and AI/ML for reference architectures
- [AWS Machine Learning Blog (Healthcare tag)](https://aws.amazon.com/blogs/machine-learning/category/industries/healthcare/): Search for FHIR, HealthLake, and longitudinal patient analytics posts

---

## Estimated Implementation Time

- **Basic pipeline (one disease cohort, mixed-effects trajectory, no counterfactuals, monthly cadence):** 8-12 weeks
- **Production-ready (Bayesian hierarchical model, counterfactual scenarios, joint time-to-endpoint, calibration monitoring, governance):** 24-36 weeks
- **With variations (multimodal integration, continuous-learning priors, patient-facing surface, federated learning):** 40-60 weeks

---

---

*← [Main Recipe 12.8](chapter12.08-disease-progression-trajectory-modeling) · [Python Example](chapter12.08-python-example) · [Chapter Preface](chapter12-preface)*
