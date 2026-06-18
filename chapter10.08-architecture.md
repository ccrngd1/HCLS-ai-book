# Recipe 10.8 Architecture and Implementation: Voice Biomarker Detection

*Companion to [Recipe 10.8: Voice Biomarker Detection](chapter10.08-voice-biomarker-detection). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon S3 for high-fidelity audio sample storage.** The biomarker pipeline benefits from preserving the original captured audio at full fidelity. S3 holds the audio with SSE-KMS encryption using customer-managed keys, with a lifecycle policy that enforces the institutional audio-retention window (often hours to days, occasionally longer with explicit consent). A separate S3 bucket holds extracted feature vectors with longer retention; the feature vectors are derived data with substantially smaller per-sample storage cost and lower re-identification risk than the raw audio. A third bucket holds the audit archive for regulatory and clinical-quality review with Object Lock in compliance mode.

**Amazon SageMaker for per-indication model hosting and per-cohort calibration.** Voice biomarker models are typically not standard-catalog services; they are research-derived models for specific indications, often built on top of pretrained speech embeddings, with per-cohort calibration layers. SageMaker provides the model-hosting substrate. Each validated indication is hosted as a separate SageMaker endpoint or as a multi-model endpoint, with per-cohort threshold maps applied at the inference orchestration layer. SageMaker's monitoring features support post-market surveillance with model-quality monitor and data-quality monitor jobs against the inference traffic.

**Amazon SageMaker Inference Recommender and Asynchronous Inference for cost-efficient scoring.** Voice biomarker inference is not always real-time. Many use cases (longitudinal monitoring, research workflows, post-encounter analysis) tolerate near-real-time scoring (minutes rather than seconds). SageMaker Asynchronous Inference reduces cost compared to real-time endpoints for these workloads. Real-time endpoints serve the use cases where in-encounter feedback is required.

**AWS Lambda and AWS Step Functions for pipeline orchestration.** Per-stage Lambdas implement the orchestration: capture-finalization handler, audio-quality-assessment Lambda, feature-extraction Lambda, eligibility-check Lambda, scoring Lambda, interpretation-packaging Lambda. Step Functions coordinates the multi-stage pipeline with durable state, retry semantics, and observable failure handling. For real-time use cases the orchestration runs within tighter latency budgets; for asynchronous use cases the orchestration tolerates longer per-stage latencies.

**Amazon Transcribe Medical for the speech-to-text path used in cognitive and linguistic biomarkers.** When the biomarker pipeline uses linguistic features (lexical diversity, idea density, word-finding patterns) extracted from spoken samples, Transcribe Medical produces the transcript that the linguistic-feature extractor consumes. The transcript is used for biomarker feature extraction; it is not the primary output. Recipe 10.4 covers the medical-dictation transcribe pipeline; the same primitives apply here at lower volume.

**Amazon Comprehend Medical for clinical-entity extraction from spontaneous-speech samples.** Spontaneous-speech tasks (describing a picture, telling a story) sometimes include clinical content the system can use for both biomarker features (semantic coherence, topic adherence) and incidental clinical-content capture. Comprehend Medical extracts the clinical entities; the biomarker pipeline uses them as features and the orchestration layer routes any clinically actionable content (a patient describing chest pain in their spontaneous-speech sample, for instance) to the appropriate clinical workflow.

**Amazon Bedrock for natural-language interpretation packaging and clinician communication.** When the biomarker output needs to be summarized into a clinician-facing or patient-facing communication, Bedrock provides the LLM layer that converts the structured score into natural-language explanations. Bedrock is also useful for the linguistic-feature extraction in cognitive-decline biomarker pipelines, where LLM-judged semantic coherence and topic adherence are part of the feature pipeline. Recipe 2.6 (clinical note summarization) and recipe 2.5 (after-visit summary generation) cover the LLM-driven summarization patterns that apply here.

**Amazon Bedrock Guardrails for safety filtering on patient-facing communications.** When the biomarker output is communicated to the patient directly (not as a diagnosis but as patient-facing context), Guardrails apply content filters and contextual-grounding checks against the underlying biomarker output, ensuring the patient communication does not over-claim what the biomarker supports.

**AWS HealthLake for FHIR-based biomarker observation storage.** The biomarker score is an Observation resource in FHIR terms. HealthLake stores the FHIR Observations and supports the longitudinal-trajectory queries the workflow needs. For non-FHIR EHR integrations, the institutional EHR-integration layer translates the FHIR Observation into the EHR-specific representation. <!-- TODO: verify HealthLake's current FHIR resource support and Observation pattern coverage -->

**Amazon DynamoDB for per-patient longitudinal-state storage.** The per-patient trajectory data (baseline scores, score history, calibration context, confound flags per sample) is well-shaped for DynamoDB. A per-patient table with the patient hash as partition key and the sample timestamp as sort key supports the trajectory queries efficiently. KMS at rest with customer-managed keys.

**Amazon API Gateway for the capture and result APIs.** The patient-facing or clinician-facing capture experience submits audio through an API Gateway endpoint. The clinician-facing result-retrieval experience reads the structured biomarker output through API Gateway endpoints backed by Lambda. Cognito or institutional-IdP authentication applies to all endpoints.

**Amazon Cognito or institutional IdP via OIDC/SAML for authentication.** Clinician access to results uses the institutional identity provider with appropriate clinical-application scopes. Patient access (where applicable) uses a patient-identity flow with appropriate scopes.

**AWS KMS for cryptographic key custody.** Customer-managed keys for the audio bucket, the feature-vector bucket, the audit archive, the DynamoDB tables, and Secrets Manager. Voice samples and feature vectors use separate KMS keys for blast-radius containment and finer retention control. Per-state biometric-data law sometimes requires distinct cryptographic isolation; the architecture supports per-jurisdiction key management where required.

**AWS Secrets Manager for EHR integration credentials and any external-vendor API credentials.** The Lambdas that write biomarker results back to the EHR or that call external clinical-validation services hold their credentials in Secrets Manager with rotation per the institutional cadence.

**Amazon EventBridge for cross-system event flow.** Sample-capture, scoring-complete, and result-delivered events flow through EventBridge. Downstream consumers (the post-market surveillance pipeline, the operational dashboards, the patient-portal release workflow) react to events without coupling to the orchestration Lambdas.

**Amazon CloudWatch for operational metrics and alarms.** Per-stage latency, per-cohort score distributions, eligibility-check pass rates, indeterminate-result rates, audio-quality scores, post-deployment accuracy proxies. Alarms on per-cohort drift thresholds, on indeterminate-result-rate spikes, on aggregate accuracy regressions.

**AWS CloudTrail for API-level audit.** All access to PHI-bearing and biometric-data-bearing resources logged. SageMaker invocations logged. KMS key uses logged. CloudTrail logs in a dedicated bucket with Object Lock and lifecycle to S3 Glacier Deep Archive after 90 days.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon QuickSight (optional) for analytics.** Audit and telemetry flow to S3 via Firehose. Glue catalogs the data. Athena provides SQL access for the operational and post-market surveillance analytics. QuickSight renders the dashboards.

**Amazon SageMaker Model Monitor and Clarify for post-market surveillance.** Model Monitor compares production inference against the training-time baseline for data-quality drift and model-quality drift. Clarify produces feature-attribution and bias reports per cohort on a scheduled cadence. Together, they provide the per-cohort surveillance the regulatory and clinical-quality posture requires.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Capture
      PATIENT[Patient or<br/>Clinician Device]
      CONSENT[Consent and<br/>Protocol Capture]
      QA[Real-Time<br/>Audio QA]
    end

    subgraph Ingest
      APIGW_IN[API Gateway<br/>Capture API]
      L_INGEST[Lambda<br/>Sample Ingest]
      S3_AUDIO[(S3 Audio<br/>Brief Retention<br/>SSE-KMS)]
    end

    subgraph Pipeline
      SF[Step Functions<br/>Pipeline Orchestrator]
      L_FEAT[Lambda<br/>Feature Extraction]
      TS_MED[Transcribe Medical<br/>(linguistic biomarkers)]
      COMP_MED[Comprehend Medical<br/>(clinical entities)]
      L_ELIG[Lambda<br/>Eligibility Check]
      SM_PARK[(SageMaker Endpoint<br/>Parkinson's Model)]
      SM_RESP[(SageMaker Endpoint<br/>Respiratory Model)]
      SM_COG[(SageMaker Endpoint<br/>Cognitive Model)]
      L_CAL[Lambda<br/>Per-Cohort<br/>Calibration]
      L_PKG[Lambda<br/>Interpretation<br/>Packaging]
      BR[Bedrock<br/>NL Communication]
      BR_GR[Bedrock<br/>Guardrails]
    end

    subgraph Storage
      S3_FEAT[(S3 Feature Vectors<br/>SSE-KMS)]
      DDB_TRAJ[(DynamoDB<br/>Patient Trajectory)]
      HL[HealthLake<br/>FHIR Observations]
      S3_AUDIT[(S3 Audit Archive<br/>Object Lock)]
    end

    subgraph Workflow
      APIGW_OUT[API Gateway<br/>Result API]
      COGNITO[Cognito +<br/>Institutional IdP]
      EHR[EHR FHIR<br/>Integration]
      CLINICIAN[Clinician<br/>Decision-Support UI]
      PATIENT_VIEW[Patient-Facing UI<br/>(where applicable)]
    end

    subgraph Surveillance
      EB[EventBridge]
      KIN[Kinesis Firehose]
      GLUE[Glue Catalog]
      ATH[Athena]
      QS[QuickSight]
      MM[SageMaker Model Monitor]
      CLAR[SageMaker Clarify]
      CW[CloudWatch]
      CT[CloudTrail]
    end

    subgraph Keys
      KMS[(AWS KMS<br/>Customer-Managed)]
      SM_SEC[(Secrets Manager<br/>EHR Creds)]
    end

    PATIENT --> CONSENT
    CONSENT --> QA
    QA --> APIGW_IN
    APIGW_IN --> L_INGEST
    L_INGEST --> S3_AUDIO
    S3_AUDIO --> SF
    SF --> L_FEAT
    L_FEAT --> TS_MED
    L_FEAT --> COMP_MED
    L_FEAT --> S3_FEAT
    SF --> L_ELIG
    L_ELIG --> SM_PARK
    L_ELIG --> SM_RESP
    L_ELIG --> SM_COG
    SM_PARK --> L_CAL
    SM_RESP --> L_CAL
    SM_COG --> L_CAL
    L_CAL --> L_PKG
    L_PKG --> BR
    BR --> BR_GR
    L_PKG --> DDB_TRAJ
    L_PKG --> HL
    L_PKG --> APIGW_OUT
    APIGW_OUT --> COGNITO
    APIGW_OUT --> CLINICIAN
    APIGW_OUT --> PATIENT_VIEW
    APIGW_OUT --> EHR
    EHR --> SM_SEC
    SF --> EB
    L_PKG --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    SM_PARK --> MM
    SM_RESP --> MM
    SM_COG --> MM
    MM --> CLAR
    SF --> CW
    APIGW_OUT --> CT
    KMS --> S3_AUDIO
    KMS --> S3_FEAT
    KMS --> S3_AUDIT
    KMS --> DDB_TRAJ
    KMS --> SM_SEC

    style SM_PARK fill:#fcf,stroke:#333
    style SM_RESP fill:#fcf,stroke:#333
    style SM_COG fill:#fcf,stroke:#333
    style TS_MED fill:#fcf,stroke:#333
    style COMP_MED fill:#fcf,stroke:#333
    style BR fill:#fcf,stroke:#333
    style BR_GR fill:#fcf,stroke:#333
    style MM fill:#fcf,stroke:#333
    style CLAR fill:#fcf,stroke:#333
    style DDB_TRAJ fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_FEAT fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
    style HL fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon S3, Amazon SageMaker (endpoints, Asynchronous Inference, Model Monitor, Clarify), AWS Lambda, AWS Step Functions, Amazon Transcribe Medical, Amazon Comprehend Medical, Amazon Bedrock (with Guardrails), AWS HealthLake, Amazon DynamoDB, Amazon API Gateway, Amazon Cognito, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally Amazon QuickSight for dashboards. |
| **Validated Models** | Per-indication validated voice-biomarker models. For most institutions this means selecting commercial vendors with FDA clearances or strong published evidence (cough analysis, Parkinson's screening) rather than building from scratch. Building from scratch requires a multi-year validation study with the cohort, evidence, and regulatory work that implies. The architecture supports either pattern: third-party model integration through SageMaker endpoint or vendor API; institutionally-built models hosted on SageMaker endpoints. <!-- TODO: verify; specific commercially available voice-biomarker products and their clearance status should be checked at build time --> |
| **External Inputs** | Capture-protocol scripts and prompts (per indication). Microphone characterization data for the supported capture-device classes. Per-cohort calibration data per validated model. Per-cohort threshold maps. Per-language linguistic-feature configurations where applicable. Validation cohort data for ongoing post-market surveillance. EHR FHIR write surface for biomarker Observation resources. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The capture-ingest Lambda has S3 write to the audio bucket only and SQS or EventBridge publish for the pipeline trigger. The feature-extraction Lambda has S3 read on the audio bucket and write on the feature bucket plus Transcribe and Comprehend Medical permissions. The scoring Lambda has SageMaker invoke-endpoint permissions for the validated indication endpoints only. The packaging Lambda has DynamoDB write, HealthLake write, Bedrock invoke-model, and EventBridge publish permissions. The EHR integration Lambda has Secrets Manager access for the EHR credentials and the EHR-specific egress only. Avoid wildcard actions and resources in production. |
| **BAA and Compliance** | AWS BAA signed. Amazon S3, SageMaker, Lambda, Step Functions, Transcribe (general and Medical), Comprehend Medical, Bedrock (verify the specific models and regions covered), HealthLake, DynamoDB, API Gateway, Cognito, KMS, Secrets Manager, EventBridge, CloudWatch Logs, CloudTrail, Kinesis Firehose, Glue, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference). <!-- TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continue to evolve --> Voice samples are biometric data; biometric-data law (Illinois BIPA, Texas, Washington, and similar) applies in addition to HIPAA where the patient's jurisdiction triggers it. SaMD regulatory consideration for any model that produces clinical claims; pre-deployment FDA strategy review for indications where a SaMD pathway is relevant. IRB or institutional review for research-track deployments and for cohort-development data collection. State-specific regulatory rules for any indication that intersects controlled-substance management, mental-health crisis response, or other regulated domains. |
| **Encryption** | Audio samples: SSE-KMS with customer-managed keys, retention bound to the consent terms (often hours to days, occasionally longer with explicit consent). Feature vectors: SSE-KMS with separate customer-managed keys, retention as needed for surveillance and re-validation per institutional policy. Biomarker results: SSE-KMS with customer-managed keys, retention aligned with the medical-record retention. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements (which can be longer than HIPAA's), state medical-records-retention rules, and institutional regulatory floor. DynamoDB tables, HealthLake datastore, Lambda environment variables, and Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all API calls. |
| **VPC** | Production: Lambdas that call back-office APIs (EHR FHIR, patient portal) run in VPC with controlled egress. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SageMaker Runtime, Transcribe, Comprehend Medical, Bedrock, Lambda. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where supported by the chosen container. |
| **CloudTrail** | Enabled with data events on the audio bucket, the feature bucket, the audit-archive bucket, the DynamoDB tables, the Secrets Manager secrets, and the customer-managed KMS keys. SageMaker invocations logged. Bedrock invocations logged with metadata only (not full input/output, to avoid persisting biometric or PHI content in CloudTrail). Lambda invocations logged. API Gateway access logs enabled. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. |
| **Sample Data** | Public voice-biomarker datasets for development and feature-pipeline validation. Examples include the mPower Parkinson's voice dataset, the Coswara cough dataset, and the DementiaBank speech corpora; each has its own access terms that must be reviewed before integration. <!-- TODO: verify dataset URLs, current availability, and license terms before integration; the public voice-biomarker dataset landscape evolves --> Synthetic capture-quality test signals for the audio QA pipeline (recordings of known-quality test tones, swept sines, or reference speech samples for microphone characterization). Never use uncoded production patient voice samples in development without explicit consent and IRB or institutional review; voice samples are biometric data with non-trivial governance implications. |
| **Cost Estimate** | At a mid-sized institution scale (50,000 voice samples per year, mixed across two or three indications): SageMaker endpoint hosting and inference at typically $25,000-100,000 per year depending on real-time vs. asynchronous and instance class. Transcribe Medical and Comprehend Medical at typically $5,000-15,000 per year. Bedrock at typically $1,000-5,000 per year for natural-language interpretation packaging. Lambda, Step Functions, S3, DynamoDB, HealthLake, CloudWatch, KMS, Secrets Manager, EventBridge, Kinesis Firehose, Glue, Athena total approximately $10,000-25,000 per year combined. Total AWS infrastructure typically $40,000-150,000 per year at this scale. The per-sample cost is dominated by the SageMaker model inference. The validation, regulatory, and clinical-evidence costs are typically much larger than the infrastructure costs at this scale. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon S3** | High-fidelity audio sample storage with brief-retention lifecycle; feature-vector storage with longer retention; audit archive with Object Lock |
| **Amazon SageMaker** | Per-indication validated model hosting (real-time and asynchronous endpoints), per-cohort calibration application, post-market surveillance via Model Monitor and Clarify |
| **Amazon Transcribe Medical** | Speech-to-text for linguistic-feature extraction in cognitive-decline biomarkers and other linguistic-feature pipelines |
| **Amazon Comprehend Medical** | Clinical-entity extraction from spontaneous-speech transcripts when used as biomarker features and for incidental clinical-content routing |
| **Amazon Bedrock** | Natural-language interpretation packaging for clinician communication; LLM-based linguistic-feature scoring (semantic coherence, topic adherence) where used in cognitive biomarkers |
| **Amazon Bedrock Guardrails** | Content filtering and contextual-grounding checks on patient-facing biomarker communications |
| **AWS Lambda** | Per-stage orchestration for capture-ingest, feature-extraction, eligibility-check, scoring, calibration, packaging, EHR write |
| **AWS Step Functions** | Pipeline orchestration with durable state, retry semantics, and observable failure handling |
| **AWS HealthLake** | FHIR-based biomarker Observation storage and longitudinal-trajectory queries |
| **Amazon DynamoDB** | Per-patient trajectory tables, per-sample state, per-cohort calibration lookup |
| **Amazon API Gateway** | Capture API for sample submission; result API for clinician and patient consumption |
| **Amazon Cognito** | Clinician and patient authentication federated through institutional IdP |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing and biometric-bearing data stores; separate keys per data class for blast-radius containment |
| **AWS Secrets Manager** | EHR API and external-vendor API credentials with rotation |
| **Amazon EventBridge** | Cross-system event flow for capture, scoring, and delivery events |
| **Amazon CloudWatch** | Operational metrics, per-cohort drift alarms, indeterminate-result-rate alarms |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing and biometric-bearing resources and AI/ML service invocations |
| **Amazon Kinesis Data Firehose** | Streaming audit and telemetry into the audit archive |
| **AWS Glue + Amazon Athena** | SQL access to audit and surveillance data for operational and clinical-quality analytics |
| **Amazon QuickSight (optional)** | Dashboards for clinical-quality and post-market surveillance teams |

---

### Code

#### Walkthrough

**Step 1: Capture the audio sample with the indication-specific protocol, real-time quality assessment, and explicit biometric-data consent.** When the patient or clinician initiates a capture, the system selects the indication-specific protocol, prompts the speaker through the tasks, runs real-time quality checks, and records the consent context including the biometric-data terms. Skip the per-protocol prompt design and the resulting audio cannot be reliably scored against the model's validation conditions. Skip the consent capture and the institution accumulates biometric data without proper authorization, which is a compliance and trust failure.

```pseudocode
ON capture_initiated(patient_id, indication, capture_context):

    // Step 1A: select the protocol for the indication.
    // The protocol defines the tasks, expected duration,
    // recording-quality minimums, and per-task quality
    // gates.
    protocol = lookup_protocol(
        indication: indication,
        patient_language: lookup_patient_language(patient_id),
        capture_context: capture_context)
    // capture_context includes device class (smartphone,
    // dedicated mic, telehealth call), environment
    // (clinic, home), and prior-visit baseline status.

    IF protocol IS NULL:
        // No validated protocol exists for this
        // combination. The system declines to capture
        // rather than capture out-of-protocol audio.
        RETURN { status: "PROTOCOL_NOT_AVAILABLE" }

    // Step 1B: capture biometric-data consent.
    // Voice samples are biometric data; the consent
    // disclosure is more specific than generic PHI
    // consent. Per-jurisdiction biometric-data law
    // (Illinois BIPA, Texas, Washington) determines
    // the disclosure requirements.
    consent_outcome = capture_consent(
        patient_id: patient_id,
        consent_type: "voice_biomarker_collection",
        disclosure: build_disclosure(
            indication: indication,
            retention_terms: protocol.retention,
            jurisdiction: lookup_patient_jurisdiction(
                patient_id),
            third_party_disclosure: protocol.disclosures),
        require_explicit: protocol.requires_explicit_consent)

    IF NOT consent_outcome.granted:
        log_consent_decline(
            patient_id, indication, consent_outcome)
        RETURN { status: "CONSENT_DECLINED" }

    // Step 1C: bootstrap the capture session.
    session_id = generate_uuid()
    capture_session_table.put({
        session_id: session_id,
        patient_id_hash: hash(patient_id),
        indication: indication,
        protocol_version: protocol.version,
        consent_id: consent_outcome.consent_id,
        capture_context: capture_context,
        device_class: capture_context.device_class,
        started_at: now(),
        jurisdiction:
            lookup_patient_jurisdiction(patient_id)
    })

    // Step 1D: walk the speaker through the protocol
    // tasks and capture audio for each.
    captured_segments = []
    FOR task IN protocol.tasks:
        prompt_speaker(task.prompt_text)
        segment_audio = capture_audio_with_quality_assessment(
            task: task,
            quality_thresholds: task.quality_thresholds,
            max_retries: task.max_retries)

        IF segment_audio.quality_score < task.minimum_quality:
            log_capture_quality_failure(
                session_id, task, segment_audio)
            // Indication may still be assessable on
            // partial-task data; the protocol determines
            // whether to proceed or abort.
            IF task.required:
                RETURN { status: "INSUFFICIENT_QUALITY",
                         failed_task: task.task_id }

        captured_segments.append({
            task_id: task.task_id,
            audio_ref: segment_audio.s3_uri,
            duration_seconds: segment_audio.duration,
            quality_score: segment_audio.quality_score,
            sample_rate: segment_audio.sample_rate,
            codec: segment_audio.codec,
            snr_db: segment_audio.snr_db,
            clipping_detected: segment_audio.clipping
        })

    // Step 1E: persist the capture-session record and
    // emit the pipeline trigger.
    capture_session_table.update(
        session_id: session_id,
        captured_segments: captured_segments,
        capture_completed_at: now(),
        status: "captured")

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "sample_captured",
        detail: {
            session_id: session_id,
            indication: indication,
            segment_count: len(captured_segments)
        }
    }])

    RETURN { session_id: session_id, status: "CAPTURED" }
```

**Step 2: Extract acoustic and linguistic features from each task segment, with bandwidth and codec-aware processing.** Each task segment is processed through the appropriate feature pipeline: sustained-vowel segments produce vocal-fold-function features; read-passage and spontaneous-speech segments produce timing, prosody, and articulation features plus optional linguistic features from the transcript; cough-collection segments produce acoustic-event features. The feature extraction is bandwidth-aware; features that depend on frequencies the recording chain does not preserve are flagged as unmeasurable rather than computed against missing signal. Skip the bandwidth-awareness and the resulting features include garbage values from frequencies that the codec discarded.

```pseudocode
FUNCTION extract_features(session_id):
    state = capture_session_table.get(session_id)
    feature_set = {
        session_id: session_id,
        indication: state.indication,
        per_segment_features: {},
        recording_chain_metadata: {
            device_class: state.device_class,
            min_codec_bandwidth_hz:
                determine_codec_bandwidth(state)
        }
    }

    // Step 2A: per-segment feature extraction.
    FOR segment IN state.captured_segments:
        task_def = lookup_task_definition(
            indication: state.indication,
            task_id: segment.task_id)

        // Bandwidth-aware feature selection. Some
        // features (high-frequency spectral tilt, for
        // instance) are not reliably measurable when the
        // codec aggressively compresses high frequencies.
        applicable_features = filter_features_by_bandwidth(
            requested_features: task_def.feature_list,
            available_bandwidth_hz:
                feature_set.recording_chain_metadata
                    .min_codec_bandwidth_hz)

        // Acoustic features.
        acoustic_features = compute_acoustic_features(
            audio_ref: segment.audio_ref,
            features: applicable_features.acoustic,
            // Per-feature confidence: features computed
            // on shorter or noisier segments get lower
            // per-feature confidence.
            return_confidence: true)

        // Pretrained-representation features (frozen
        // self-supervised speech embeddings) for the
        // downstream model's pretrained-rep inputs.
        embedding_features = compute_speech_embeddings(
            audio_ref: segment.audio_ref,
            model_id: task_def.embedding_model_id)

        // Linguistic features (if task is read-passage
        // or spontaneous-speech and indication uses
        // linguistic features, e.g., cognitive
        // biomarkers).
        linguistic_features = NULL
        IF task_def.uses_linguistic_features:
            transcript = transcribe_medical.start_job(
                audio_ref: segment.audio_ref,
                language: state.protocol.language,
                show_speaker_labels: false)
            wait_for_transcribe(transcript.job_name)
            transcript_text = retrieve_transcript(
                transcript.job_name)

            // TODO (TechWriter): Expert review A9 (MEDIUM). Transcribe Medical async job-wait inside the feature-extraction Lambda is a latency-and-reliability anti-pattern (Lambda billed for wait period, 15-minute maximum execution time may be exceeded for long samples). Split linguistic-feature extraction into separate Step Functions step or use wait-for-callback pattern; feature-extraction Lambda invokes start_job and returns job_name; Step Functions awaits job-completion event; separate Lambda step retrieves transcript and invokes extract_linguistic_features.

            linguistic_features = extract_linguistic_features(
                transcript: transcript_text,
                requested_features:
                    applicable_features.linguistic)

            // For spontaneous-speech samples that may
            // contain incidental clinical content,
            // route through Comprehend Medical to
            // surface anything that needs clinical
            // attention regardless of the biomarker
            // result.
            IF task_def.is_spontaneous_speech:
                clinical_entities =
                    comprehend_medical.detect_entities_v2(
                        text: transcript_text)
                IF has_actionable_clinical_content(
                       clinical_entities):
                    route_to_clinical_review(
                        session_id, clinical_entities)

        feature_set.per_segment_features[segment.task_id] = {
            acoustic: acoustic_features,
            embeddings: embedding_features,
            linguistic: linguistic_features,
            unmeasurable_features: applicable_features.excluded
        }

    // Step 2B: persist features.
    feature_set_archive.put(
        session_id: session_id,
        feature_set: feature_set)

    capture_session_table.update(
        session_id: session_id,
        feature_set_archive_ref:
            f"s3://{FEATURE_BUCKET}/{session_id}/features.json",
        features_extracted_at: now(),
        status: "features_extracted")

    RETURN { feature_set_ref: feature_set.archive_ref }
```

**Step 3: Check eligibility for each candidate biomarker model based on validation envelope.** Each per-indication model has a validation envelope: the demographic distributions, recording-chain conditions, and task-completion expectations the model was validated under. Before the model is invoked, the system checks whether the current sample fits the envelope. Out-of-envelope samples produce an "indication not assessable" result rather than a potentially-misleading score. Skip the eligibility check and the system silently produces scores on samples the model was not validated for, which is a clinical-safety failure mode.

```pseudocode
FUNCTION check_eligibility(session_id, candidate_indications):
    state = capture_session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    eligibility_results = {}

    FOR indication IN candidate_indications:
        model_card = lookup_model_card(indication)

        // Step 3A: demographic eligibility.
        patient_demographics = lookup_patient_demographics(
            state.patient_id_hash)
        demographic_fit = check_demographic_envelope(
            patient_demographics,
            model_card.validation_demographics)

        // Step 3B: recording-chain eligibility.
        recording_fit = check_recording_envelope(
            recording_metadata:
                feature_set.recording_chain_metadata,
            validation_envelope:
                model_card.validation_recording_envelope)

        // Step 3C: task-completion eligibility.
        task_fit = check_task_completion(
            captured_segments: state.captured_segments,
            required_tasks: model_card.required_tasks,
            min_per_task_quality:
                model_card.min_per_task_quality)

        // Step 3D: confound-flag check.
        confound_flags = check_confounds(
            patient_id_hash: state.patient_id_hash,
            recent_clinical_events: lookup_recent_events(
                state.patient_id_hash,
                window_days: 30),
            model_confounds: model_card.confounds_to_flag)

        eligibility_results[indication] = {
            eligible:
                demographic_fit.eligible AND
                recording_fit.eligible AND
                task_fit.eligible,
            demographic_fit: demographic_fit,
            recording_fit: recording_fit,
            task_fit: task_fit,
            confound_flags: confound_flags,
            // Cohort assignment for per-cohort
            // calibration at the next step.
            assigned_cohort: assign_cohort(
                patient_demographics,
                feature_set.recording_chain_metadata,
                model_card.cohort_definitions)
        }

    capture_session_table.update(
        session_id: session_id,
        eligibility: eligibility_results,
        eligibility_assessed_at: now())

    RETURN eligibility_results
```

**Step 4: Score the eligible biomarkers, applying per-cohort calibration and producing indeterminate results when uncertainty is high.** For each indication that passed eligibility, the system invokes the validated model, applies the per-cohort calibration to the raw model output, and packages the result. When the model's confidence is below the institutional threshold, the result is marked indeterminate rather than passed through as a confident score. Skip the per-cohort calibration and the system produces uncalibrated outputs that perform inconsistently across cohorts. Skip the indeterminate handling and edge-case samples produce confident-looking scores that the clinical workflow takes at face value.

```pseudocode
FUNCTION score_biomarkers(session_id):
    state = capture_session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    eligibility = state.eligibility
    scores = {}

    FOR indication, elig IN eligibility:
        IF NOT elig.eligible:
            scores[indication] = {
                status: "NOT_ASSESSABLE",
                ineligibility_reasons:
                    summarize_ineligibility(elig)
            }
            CONTINUE

        model_card = lookup_model_card(indication)
        endpoint_name = model_card.sagemaker_endpoint

        // Step 4A: assemble model inputs.
        model_input = assemble_model_input(
            feature_set: feature_set,
            model_card: model_card)

        // Step 4B: invoke the SageMaker endpoint.
        // Real-time endpoints for in-encounter use
        // cases; asynchronous endpoints for
        // longitudinal-monitoring use cases.
        IF model_card.inference_mode == "real_time":
            raw_response = sagemaker_runtime.invoke_endpoint(
                endpoint_name: endpoint_name,
                content_type: "application/json",
                body: serialize(model_input))
        ELSE:
            raw_response = sagemaker_runtime.invoke_endpoint_async(
                endpoint_name: endpoint_name,
                input_location: model_input.s3_uri)
            wait_for_async_response(raw_response.output_location)
            raw_response = retrieve_async_output(
                raw_response.output_location)

        raw_score = parse_score(raw_response)

        // Step 4C: apply per-cohort calibration.
        // The cohort was assigned at eligibility step.
        // Each cohort has its own calibration curve and
        // its own threshold map.
        calibration = lookup_cohort_calibration(
            indication: indication,
            cohort: elig.assigned_cohort)
        calibrated_score = apply_calibration(
            raw_score, calibration.curve)

        // Step 4D: indeterminate-result handling.
        // Calibrated confidence intervals beyond the
        // institutional threshold for actionable
        // results produce indeterminate output.
        confidence_interval = compute_confidence_interval(
            score: calibrated_score,
            cohort_size: calibration.cohort_size,
            calibration_uncertainty:
                calibration.calibration_uncertainty)

        IF confidence_interval.width >
           model_card.indeterminate_threshold:
            scores[indication] = {
                status: "INDETERMINATE",
                raw_score: raw_score,
                calibrated_score: calibrated_score,
                confidence_interval: confidence_interval,
                cohort: elig.assigned_cohort,
                confound_flags: elig.confound_flags,
                recommended_action: "recapture_or_clinician_review"
            }
            CONTINUE

        // Step 4E: threshold-based category assignment.
        category = assign_category(
            calibrated_score, calibration.thresholds)

        // Step 4F: feature-attribution explanation.
        // For models that support it, surface the
        // top contributing features for clinician
        // interpretation.
        feature_attribution = compute_attribution(
            model_card: model_card,
            model_input: model_input,
            raw_response: raw_response)

        scores[indication] = {
            status: "SCORED",
            raw_score: raw_score,
            calibrated_score: calibrated_score,
            confidence_interval: confidence_interval,
            category: category,
            cohort: elig.assigned_cohort,
            confound_flags: elig.confound_flags,
            top_features: feature_attribution.top_features,
            model_version: model_card.model_version,
            calibration_version: calibration.version,
            scored_at: now()
        }

    capture_session_table.update(
        session_id: session_id,
        scores: scores,
        scoring_completed_at: now(),
        status: "scored")

    // TODO (TechWriter): Expert review S2 (HIGH). capture_session_table accumulates biomarker scores with patient feature values (top_features.patient_value, cohort_baseline_mean) outside the archive-reference pattern; same chapter pattern as 10.1-10.7 with recipe-distinct biometric-derived-data extension. Adopt audit-record discipline uniformly: write full scores content to per-session score-archive S3 bucket with biometric-derived KMS key class; metadata table holds only references plus structural metadata (status, category, cohort, model_version, calibration_version, faithfulness_annotations_summary, archive_refs). Update Cross-Cutting Design Points to elevate working-store-as-archive-reference pattern.

    RETURN scores
```

**Step 5: Compute longitudinal trajectory and package the clinical interpretation.** For patients with prior samples, the system computes the trajectory delta against the patient's baseline. The packaged interpretation includes the score, the trajectory, the supporting features, the cohort context, the confound flags, and the institutionally-approved clinical-action mapping. Skip the trajectory computation and the system loses the per-patient longitudinal context that makes voice biomarkers most reliable. Skip the institutional clinical-action mapping and individual clinicians have to infer how to act on the score, which produces inconsistent and sometimes inappropriate clinical actions.

```pseudocode
FUNCTION package_interpretation(session_id):
    state = capture_session_table.get(session_id)
    scores = state.scores
    interpretations = {}

    FOR indication, score IN scores:
        IF score.status IN ["NOT_ASSESSABLE", "INDETERMINATE"]:
            interpretations[indication] = score
            CONTINUE

        // Step 5A: longitudinal trajectory.
        // Trajectory is more reliable than single-sample
        // scoring for many indications.
        prior_samples = trajectory_table.get_history(
            patient_id_hash: state.patient_id_hash,
            indication: indication,
            window_days: 730)

        trajectory = NULL
        IF len(prior_samples) >= MIN_SAMPLES_FOR_TRAJECTORY:
            baseline = compute_patient_baseline(
                prior_samples,
                exclude_recent_days: 30)
            trajectory = compute_trajectory_delta(
                current_score: score.calibrated_score,
                baseline: baseline,
                model_card: lookup_model_card(indication))

        // Step 5B: clinical-action mapping.
        // The institution-approved mapping translates
        // the score and trajectory into one of a small
        // set of clinical actions (clinician review,
        // patient communication, longitudinal store
        // only, no action).
        clinical_action = lookup_clinical_action_mapping(
            indication: indication,
            category: score.category,
            trajectory: trajectory,
            confound_flags: score.confound_flags,
            institutional_policy: INSTITUTIONAL_POLICY)

        // Step 5C: clinician-facing summary using
        // Bedrock for natural-language packaging.
        clinician_summary = bedrock.invoke_model(
            model_id: SUMMARY_MODEL,
            prompt: build_summary_prompt(
                indication: indication,
                score: score,
                trajectory: trajectory,
                clinical_action: clinical_action,
                template: CLINICIAN_SUMMARY_TEMPLATE),
            guardrail_id: BIOMARKER_GUARDRAIL_ID,
            response_format: {
                type: "json_schema",
                schema: SUMMARY_SCHEMA
            },
            max_tokens: 800)

        // Step 5D: store the trajectory record.
        trajectory_table.put({
            patient_id_hash: state.patient_id_hash,
            indication: indication,
            sample_timestamp: state.started_at,
            session_id: session_id,
            calibrated_score: score.calibrated_score,
            cohort: score.cohort,
            confound_flags: score.confound_flags,
            recording_chain:
                state.feature_set.recording_chain_metadata,
            trajectory_delta:
                (trajectory.delta if trajectory else NULL)
        })

        interpretations[indication] = {
            status: "INTERPRETED",
            score: score,
            trajectory: trajectory,
            clinical_action: clinical_action,
            clinician_summary: clinician_summary.content,
            packaged_at: now()
        }

    capture_session_table.update(
        session_id: session_id,
        interpretations: interpretations,
        packaging_completed_at: now(),
        status: "interpreted")

    // TODO (TechWriter): Expert review S2 (HIGH) continued. interpretations content (including LLM-generated clinician_summary) and trajectory_table entries (calibrated_score, cohort, confound_flags, recording_chain, trajectory_delta) need archive-reference pattern. Write interpretations content to per-session interpretation-archive S3 bucket with same KMS key class; metadata holds only references. Classify trajectory_table as biometric-derived data store with biometric-data governance.
    // TODO (TechWriter): Expert review A2 (MEDIUM). Faithfulness check on the LLM-generated clinician_summary architecturally implicit. Add faithfulness-check stage between Bedrock summary generation and interpretation packaging: structured-output schema validation, citation grounding for each summary section to source biomarker fields, LLM-judge faithfulness scoring as secondary check for high-stakes indications, rule-based contradiction detection. Fall back to render_structured_summary on faithfulness block. Per-cohort faithfulness-failure-rate as launch gate.
    // TODO (TechWriter): Expert review S4 (MEDIUM). Foundation-model prompt-injection risk for the LLM-judged linguistic-feature-extraction and clinician-summary-rendering paths underspecified. Add delimited-input framing for transcript content (<transcript>...</transcript>), strict structured-output validation, secondary deterministic-feature-engineering check; per-language and prompt-injection edge-case test discipline.

    RETURN interpretations
```

**Step 6: Deliver the result to the clinical workflow with explicit indeterminate handling and clinician override capture.** The clinician sees the biomarker result in their decision-support context, with the option to acknowledge, override, or request follow-up. The biomarker is decision support, not diagnosis; the clinician retains diagnostic authority. The result is also written to the EHR as a FHIR Observation for the longitudinal record. Skip the clinician override capture and the institution loses the feedback loop that supports post-market surveillance. Skip the EHR write and the result is invisible to the rest of the care team.

```pseudocode
FUNCTION deliver_to_workflow(session_id):
    state = capture_session_table.get(session_id)
    interpretations = state.interpretations

    FOR indication, interpretation IN interpretations:
        // Step 6A: write the biomarker as a FHIR
        // Observation. The Observation includes the
        // score, the cohort context, the confound flags,
        // and the indeterminate-result status where
        // applicable.
        observation_resource = build_fhir_observation(
            patient_id: lookup_patient_id(
                state.patient_id_hash),
            indication: indication,
            interpretation: interpretation,
            performed_at: state.started_at)

        healthlake_client.create_resource(
            resource_type: "Observation",
            resource: observation_resource)

        // TODO (TechWriter): Expert review A3 (MEDIUM). Idempotency for HealthLake FHIR Observation write-back architecturally implicit; duplicate write produces duplicate Observation triggering duplicate decision-support alert, mis-sized longitudinal baseline, mis-calibrated trajectory. Specify per-write idempotency key (session_id, indication) or (patient_id_hash, indication, captured_at_truncated_to_minute); on idempotency-match return prior resource_id; FHIR conditional-create where HealthLake supports.

        // Step 6B: surface the result to the clinical
        // workflow per the institutionally-approved
        // clinical-action mapping.
        IF interpretation.clinical_action == "clinician_review":
            create_decision_support_alert(
                patient_id_hash: state.patient_id_hash,
                indication: indication,
                interpretation: interpretation,
                priority:
                    interpretation.score.category)
        ELIF interpretation.clinical_action == "patient_communication":
            // Patient-facing message goes through
            // additional Guardrails check for
            // appropriate framing.
            patient_message = generate_patient_message(
                interpretation,
                guardrail_id: PATIENT_MESSAGING_GUARDRAIL)
            schedule_patient_communication(
                patient_id_hash: state.patient_id_hash,
                message: patient_message,
                channel: lookup_patient_preference(
                    state.patient_id_hash))
        ELIF interpretation.clinical_action == "longitudinal_only":
            // Result stored, not surfaced to clinician
            // for individual review. Aggregate trajectory
            // available in clinician's longitudinal view.
            log_longitudinal_only(session_id, indication)
        ELSE:
            // No-action mapping. Result stored only.
            log_no_action(session_id, indication)

        // Step 6C: emit the delivery event for
        // surveillance and feedback loops.
        EventBridge.PutEvents([{
            source: "voice_biomarker",
            detail_type: "result_delivered",
            detail: {
                session_id: session_id,
                indication: indication,
                clinical_action:
                    interpretation.clinical_action,
                category:
                    (interpretation.score.category if
                     interpretation.status == "INTERPRETED"
                     else interpretation.status)
            }
        }])

ON clinician_acknowledges_result(session_id, clinician_id,
                                  indication, action_taken,
                                  feedback):
    // Step 6D: capture the clinician's response. This
    // is the feedback loop for post-market surveillance:
    // did the clinician agree with the biomarker, did
    // they take an action, did the action match the
    // institutional clinical-action mapping?
    clinician_feedback_table.put({
        session_id: session_id,
        indication: indication,
        clinician_id: clinician_id,
        action_taken: action_taken,
        agreement_with_biomarker:
            (action_taken == interpretation.clinical_action),
        feedback: feedback,
        responded_at: now()
    })

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "clinician_feedback_captured",
        detail: {
            session_id: session_id,
            indication: indication,
            agreement: (action_taken ==
                        interpretation.clinical_action)
        }
    }])
```

**Step 7: Audit, retain audio per consent, and feed cohort-stratified post-market surveillance.** Every sample produces a durable audit record with the score, the cohort context, the confound flags, and the clinical-action linkage. Audio is retained per the consent terms and then deleted; feature vectors are retained longer for surveillance and re-validation. Cohort-stratified metrics feed the post-market surveillance dashboards that monitor the deployed biomarker's performance against ground-truth clinical outcomes. Skip the audio retention enforcement and the institution silently accumulates biometric data beyond its consent commitment. Skip the cohort-stratified surveillance and per-cohort drift surfaces only through complaints.

```pseudocode
FUNCTION audit_and_surveillance(session_id):
    state = capture_session_table.get(session_id)
    interpretations = state.interpretations

    audit_record = {
        session_id: session_id,
        patient_id_hash: state.patient_id_hash,
        captured_at: state.started_at,
        capture_completed_at: state.capture_completed_at,
        scoring_completed_at: state.scoring_completed_at,
        delivered_at: state.packaging_completed_at,
        indications_attempted:
            list(interpretations.keys()),
        per_indication_outcomes: {
            indication: {
                status: interp.status,
                category:
                    (interp.score.category
                     if interp.status == "INTERPRETED"
                     else NULL),
                cohort:
                    (interp.score.cohort
                     if interp.status == "INTERPRETED"
                     else NULL),
                clinical_action:
                    (interp.clinical_action
                     if interp.status == "INTERPRETED"
                     else NULL),
                confound_flags:
                    (interp.score.confound_flags
                     if interp.status == "INTERPRETED"
                     else NULL),
                model_version:
                    (interp.score.model_version
                     if interp.status == "INTERPRETED"
                     else NULL),
                calibration_version:
                    (interp.score.calibration_version
                     if interp.status == "INTERPRETED"
                     else NULL)
            }
            FOR indication, interp IN interpretations
        },
        recording_chain_metadata:
            state.feature_set.recording_chain_metadata,
        consent_id: state.consent_id,
        protocol_version: state.protocol_version
    }

    audit_archive_kinesis_firehose.put(audit_record)

    // Step 7A: schedule audio deletion per consent
    // terms. Feature-vector retention is configured
    // separately, typically longer than audio.
    schedule_audio_deletion(
        audio_refs:
            [seg.audio_ref for seg in state.captured_segments],
        delete_after: lookup_audio_retention(
            consent_id: state.consent_id,
            jurisdiction: state.jurisdiction))

    // Step 7B: per-cohort surveillance metrics.
    FOR indication, outcome IN audit_record.per_indication_outcomes:
        IF outcome.status == "INTERPRETED":
            cloudwatch.put_metric(
                namespace: "VoiceBiomarker",
                metric_name: "BiomarkerCategoryRate",
                value: 1,
                dimensions: {
                    indication: indication,
                    category: outcome.category,
                    cohort: outcome.cohort,
                    model_version: outcome.model_version
                })
        cloudwatch.put_metric(
            namespace: "VoiceBiomarker",
            metric_name: "PerOutcomeStatus",
            value: 1,
            dimensions: {
                indication: indication,
                outcome_status: outcome.status,
                cohort:
                    (outcome.cohort if outcome.cohort
                     else "not_eligible")
            })

    // Step 7C: SageMaker Model Monitor data-quality
    // and model-quality jobs run on a scheduled
    // cadence against the inference traffic. SageMaker
    // Clarify produces per-cohort attribution and bias
    // reports. Both feed the post-market surveillance
    // dashboard.

    EventBridge.PutEvents([{
        source: "voice_biomarker",
        detail_type: "session_audited",
        detail: {
            session_id: session_id,
            audited_at: now()
        }
    }])
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample biomarker output (illustrative, synthetic patient):**

```json
{
  "session_id": "vbm-3a8c4f9b-7d2e-4f1a",
  "patient_id_hash": "p_8bf7e1c4...",
  "captured_at": "2026-05-23T14:08:11Z",
  "indications": {
    "parkinsons_screening": {
      "status": "INTERPRETED",
      "score": {
        "raw_score": 0.71,
        "calibrated_score": 0.64,
        "confidence_interval": [0.57, 0.71],
        "category": "elevated_signal",
        "cohort": "65-74_male_english_clinic_recording",
        "model_version": "parkinsons_v3.2.1",
        "calibration_version": "calibration_v3.2.1_20260301",
        "top_features": [
          {"feature": "harmonic_to_noise_ratio_sustained_a",
           "patient_value_z": -1.8,
           "cohort_baseline_mean": 21.4,
           "patient_value": 14.2},
          {"feature": "pitch_range_passage",
           "patient_value_z": -1.4,
           "cohort_baseline_mean": 78.2,
           "patient_value": 51.0},
          {"feature": "articulation_rate_passage",
           "patient_value_z": -1.1,
           "cohort_baseline_mean": 5.1,
           "patient_value": 4.3}
        ],
        "confound_flags": []
      },
      "trajectory": {
        "baseline_score": 0.41,
        "current_score": 0.64,
        "delta": 0.23,
        "delta_significance": "outside_typical_variation",
        "samples_in_baseline": 4,
        "baseline_window": "2024-09-01_to_2025-09-01"
      },
      "clinical_action": "clinician_review",
      "clinician_summary": "Voice features show acoustic patterns associated with Parkinsonian speech: reduced harmonic-to-noise ratio, narrowed pitch range, and slowed articulation rate. The patient's score has increased meaningfully relative to their own baseline over the past 12 months. This is a decision-support signal, not a diagnosis. Consider movement-disorder workup if other clinical signs warrant; the biomarker does not establish or exclude a Parkinson's diagnosis on its own."
    },
    "respiratory_monitoring": {
      "status": "NOT_ASSESSABLE",
      "ineligibility_reasons": [
        "no_cough_segment_in_protocol"
      ]
    }
  },
  "recording_chain": {
    "device_class": "clinic_dedicated_microphone",
    "sample_rate_hz": 44100,
    "codec": "PCM_16",
    "min_codec_bandwidth_hz": 16000,
    "snr_db": 28,
    "environment": "exam_room"
  }
}
```

**Performance benchmarks (illustrative; ranges depend heavily on indication, validation cohort, and recording chain; your mileage will vary):**

| Metric | Cough Classification (productive cough vs. dry vs. URI vs. asthma exacerbation) | Parkinson's Screening (single-point) | Parkinson's Trajectory Monitoring (longitudinal) | Depression Severity (decision-support score) | Cognitive-Decline Screening |
|--------|----------------------------|-------------------------------------|-------------------------------------------------|-------------------------------------|------------------------------|
| AUC on validation cohort | 0.85-0.92 | 0.75-0.88 | 0.85-0.93 | 0.65-0.78 | 0.70-0.85 |
| AUC on out-of-distribution cohort (different population) | 0.65-0.85 | 0.55-0.75 | 0.70-0.85 | 0.50-0.65 | 0.55-0.75 |
| Sensitivity at clinically-actionable threshold | 70-85% | 60-78% | 75-88% | 50-70% | 55-75% |
| Specificity at clinically-actionable threshold | 75-90% | 65-82% | 78-90% | 60-78% | 65-80% |
| Indeterminate-result rate (typical clinical population) | 5-10% | 12-25% | 8-18% | 18-30% | 15-28% |
| Per-sample latency (real-time endpoint) | 1-3 seconds | 2-5 seconds | 3-8 seconds | 2-5 seconds | 3-8 seconds |
| Per-sample latency (asynchronous endpoint) | 1-3 minutes | 2-5 minutes | 3-7 minutes | 2-5 minutes | 3-7 minutes |
| Per-sample AWS infrastructure cost | $0.05-0.15 | $0.10-0.25 | $0.15-0.35 | $0.10-0.30 | $0.15-0.40 |

<!-- TODO: replace with verified figures from the deployed indications. The ranges above are typical for published voice-biomarker results but vary substantially with cohort design, recording protocol, and the specific commercial or institutional model used. Cross-cohort generalization is consistently weaker than within-cohort performance, which is the most important caveat for institutional planning. -->

**Where it struggles:**

- **Cross-cohort generalization.** A model validated on one population (often a clinical-research cohort with specific demographic skew) frequently underperforms on a deployment population that does not match. This is the single largest gap between published voice-biomarker accuracy and real-world deployment accuracy. Mitigations: per-cohort validation before per-cohort deployment, eligibility checking that refuses out-of-envelope samples, per-cohort calibration with explicit cohort disclosure on every result, ongoing post-market surveillance with per-cohort accuracy tracking against ground-truth outcomes.

- **Recording-chain variability.** Smartphone capture, telephony capture, telehealth video-call capture, and dedicated-microphone capture produce meaningfully different feature vectors. A model trained on one recording chain often fails on another. Mitigations: per-recording-chain validation, bandwidth-aware feature extraction, per-codec calibration where supported, recording-chain disclosure on every result.

- **State vs. trait confounds.** A patient with a cold has a different voice than the same patient without a cold; the difference can be larger than the disease-specific signal the biomarker is trying to measure. Mitigations: confound flagging at the eligibility step, asking the patient about recent respiratory illness or other relevant factors as part of the protocol, longitudinal analysis that filters transient state effects from durable trait changes, indeterminate-result handling for samples with high-impact confound flags.

- **Demographic confounds masquerading as disease signal.** Without careful experimental design, models can learn to predict the demographics of the speaker rather than the disease state, and the apparent accuracy is the consequence of demographic-disease correlation in the training data. Mitigations: speaker-disjoint train/test splits, propensity-matched cohort design, explicit demographic-fairness analysis at the validation step, per-demographic-cohort performance reporting.

- **Insufficient data for rare conditions.** Many candidate voice biomarkers target conditions with too little training data to support robust models (rare neurological conditions, early-stage diseases before diagnosis). Mitigations: focus initial deployment on indications with adequate published evidence and adequate validation cohorts; treat data-poor indications as research-track only; collaborate with academic medical centers to grow validation cohorts over time.

- **The reproducibility tail.** Some commercially-promoted voice biomarkers are based on published results that have not replicated or that survive only with weaker performance than originally claimed. Mitigations: vendor due diligence including review of replication studies, preference for indications with multiple independent validation studies, explicit institutional-quality review of vendor evidence packages before clinical deployment.

- **Patient acceptance and consent.** Voice samples are biometric data; patient comfort with their voice being recorded and analyzed varies substantially by population, age, prior privacy experience, and the specific indication. Mitigations: clear consent disclosures, explicit retention terms, patient-friendly explanations of what voice biomarkers can and cannot tell, easy opt-out, attentive privacy-officer involvement in patient-facing communications.

- **Clinician trust and workflow integration.** A voice biomarker that surfaces in the EHR with little context is a likely-to-be-ignored alert. The combined information density (a number plus a category plus a confound flag plus a cohort context plus a trajectory) is more than a typical EHR alert is designed to convey. Mitigations: thoughtful decision-support interface design, per-indication clinician training, careful clinical-action mapping that makes the response to the result obvious, ongoing clinician-feedback collection and adjustment.

- **The mental-health-specific concerns.** Voice biomarkers for depression severity and suicidality risk are clinically promising but methodologically delicate. The state-vs-trait problem is acute (a patient's voice changes when they are having a bad day independent of their underlying clinical state). The clinical-action mapping is high-stakes (acting on a false-positive suicidality flag may be helpful or may damage trust). Mitigations: deploy as decision-support to clinicians rather than as automated screens, conservative thresholds with high indeterminate rates, integration with established mental-health workflows that the biomarker informs but does not replace.

- **Voice-modification and active deception.** Voice samples can be intentionally modified by the speaker (clearing throat, deliberately slowing or speeding speech, changing voice quality consciously). This is rare in cooperative patient populations but is a consideration in some workflow contexts (e.g., disability assessments, research participation). Mitigations: protocol design that makes intentional modification harder (multi-task protocols with surprise tasks), longitudinal trajectory analysis that flags abrupt within-patient changes, explicit acknowledgment that voice biomarkers can be confounded by intentional modification.

- **Regulatory drift.** A model that is FDA-cleared today may have its clearance affected by post-market findings, regulatory framework updates, or changes in the standard of care. Models that are not FDA-cleared but are deployed in clinical workflows may attract regulatory scrutiny over time. Mitigations: explicit regulatory-strategy review at the start, ongoing engagement with the regulatory affairs team, willingness to pause or modify deployments based on regulatory developments.

- **Audio-storage and biometric-data-disclosure exposure.** Voice samples are biometric and can be re-identified from the audio itself, independent of any patient metadata. Storage breaches are biometric-data breaches with potentially distinct legal implications. Mitigations: short audio retention, feature-vector-only retention beyond the QA window, encryption at rest with separate keys, access controls, breach-response plans that explicitly address biometric data.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment for any specific indication needs to close substantial gaps that are out of scope for a recipe.

**Per-indication validation evidence.** This is the dominant gap. The architecture supports per-indication models; the institution needs to either select commercial vendors with appropriate validation evidence (and the contracts to back the institution's own due-diligence) or build models with their own validation studies. Building a clinically-defensible voice biomarker for a single indication is a multi-year, multi-million-dollar undertaking requiring clinical-research staff, IRB-approved cohort development, and biostatistical expertise. Most institutions should be buying validated models, not building them.

**FDA SaMD strategy.** Any voice biomarker that produces clinical claims (diagnosis, treatment recommendation, disease-state measurement) is potentially subject to FDA's SaMD regulatory framework. The strategy decision (pursue clearance, deploy as wellness tool, deploy as research instrument, deploy as decision-support without specific claims) is upstream of the technical work. The strategy decision is also indication-specific: the same architectural component might support an FDA-cleared cough-classification model and a research-only cognitive-decline model, with different clinical-action mappings, different consent terms, and different post-market surveillance obligations per indication.

**Cohort development and ongoing cohort expansion.** Whether buying or building, the institution needs validation cohort data that matches its deployed population. Cohort expansion over time (collecting voice samples with linked clinical outcomes, with explicit IRB-approved consent for biomarker development) is the long-term workstream that determines how robust the deployed biomarkers become. Plan cohort expansion as a multi-year, named-clinical-research-team workstream.

**Per-cohort validation gates.** Per-cohort accuracy must meet the institutional threshold for that cohort before the biomarker is deployed to that cohort. Cohorts where per-cohort performance is inadequate either get the biomarker disabled, or get it deployed with explicit caveats and adjusted clinical-action mapping. Without this gate, the institution silently underserves the cohorts where the biomarker performs poorly.

**Clinical-action mapping by named clinical-quality leadership.** What clinicians and patients should do with each possible biomarker output is an institutional clinical-quality decision, not a technical decision. The mapping (high-risk score triggers what; indeterminate triggers what; trajectory delta triggers what; specific confound combinations trigger what) is owned by the clinical-quality officer or equivalent, in collaboration with the clinical-informatics team and the relevant specialty leadership. Without this ownership, the biomarker outputs are interpreted inconsistently across clinicians, and the clinical-quality outcomes are unpredictable.

**Consent infrastructure for biometric data.** The architecture captures consent at protocol initiation. Production deployment requires the privacy officer's review of the consent disclosure language, the per-jurisdiction biometric-data terms, the retention policies, and the right-to-deletion workflow. The infrastructure for honoring biometric-data deletion requests (deleting audio, feature vectors, scores, longitudinal trajectory entries upon patient request, with disclosure-accounting for any prior uses) is a substantial workstream.

**Recording-chain control or characterization.** The biomarker performance depends on the recording chain. Production deployment either standardizes the recording chain (all samples captured with the institution's specified microphone class, in specified environments, with specified protocols) or characterizes and validates against the realistic distribution of recording chains in the actual deployment context. The first is more reliable but limits where the biomarker can be deployed; the second is more flexible but requires more validation work.

**Post-market surveillance with regulatory reporting.** Voice biomarker performance changes over time in production for many reasons. The architecture collects the surveillance data; the institution needs the analytical capacity to act on it. Re-validation triggers, model retraining cadences, FDA reporting obligations (for cleared SaMD devices), and institutional-quality review meetings all need to be operational. Plan a quarterly per-indication clinical-quality review meeting at minimum.

**Layered safety review for high-stakes indications.** Mental-health voice biomarkers, in particular, deserve a more cautious deployment path: small-cohort pilots with intensive clinician feedback before broad deployment, conservative thresholds, explicit override paths for clinicians, integration with established crisis-response workflows where applicable. The same care applies to any indication where false-positive or false-negative results have direct clinical-safety implications.

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Mental-health-voice-biomarker and 42 CFR Part 2 profile architecturally implicit despite explicit prose elevation in four separate places. Add "Mental-Health, Substance-Use, and 42 CFR Part 2 Biomarker Profile" subsection specifying retention shorter, access controls narrower with separate KMS key class, clinical-action mapping capped at decision_support_only with mandatory clinician acknowledgement, integration with crisis-response workflow for high-suicidality scores, no patient-facing direct release, separate audit-archive prefix with mental-health-record disclosure-accounting metadata, cross-encounter analytics exclusion. Update Step 1 and audit_record at Step 7 with mental-health and 42-CFR-Part-2 flags. -->
<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Foundation-model and prompt and model-card and per-cohort-calibration versioning via inference profiles and aliases not architecturally specified. Add Deployment Pattern subsection with versioned model and prompt and model-card and per-cohort-calibration definitions in version control, SageMaker endpoint canary deployment with traffic-shift, Bedrock inference profile for prompt-and-model versioning with rollback-on-regression, held-out evaluation set with per-cohort coverage and prompt-injection test cases, version stamping on every encounter audit record (extend to model_card_version and clinical_action_mapping_version), SaMD-specific change-management discipline for clearance-affected versions. -->
<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Multi-language pipeline build-for-day-one underspecified. Specify per-language pipeline pattern with per-language ASR configuration with custom vocabulary, acoustic-feature calibration data, linguistic-feature LLM-judge prompts with native-speaker clinical-informatics input, template definitions, faithfulness rule catalogs, validation cohort, consent disclosure language. -->
<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Audio retention configuration mechanism with per-jurisdiction and per-consent-terms differentiation not architecturally specified. Specify retain-briefly with configurable per-jurisdiction-and-per-consent-and-per-indication-profile retention window (default: 24-72 hours physical-health biomarkers, 24-48 hours mental-health profile, 24 hours 42-CFR-Part-2-eligible, per-jurisdiction adjustments per BIPA/CUBI/Washington/GDPR); per-prefix S3 lifecycle policies on /jurisdiction/<jur>/profile/<prof>/... prefix structure. -->
<!-- TODO (TechWriter): Expert review S5 (MEDIUM). Audit-log retention floor specified generically without explicit pediatric-records, biometric-records, per-jurisdiction GDPR, FDA SaMD post-market, mental-health-record-statute, and 42 CFR Part 2 disclosure-accounting floors. Name longest-of-(HIPAA-six-year, state-specific medical-records-retention including pediatric-extending-to-age-of-majority-plus-X, per-jurisdiction biometric-records retention including BIPA/CUBI/Washington/GDPR Article 9, FDA SaMD post-market surveillance retention for cleared devices, mental-health-record-specific retention statutes, 42 CFR Part 2 disclosure-accounting log retention for substance-use-eligible visits, institutional regulatory floor). -->
<!-- TODO (TechWriter): Expert review S6 (MEDIUM). Lambda invocation authentication across API Gateway-to-Lambda and Step-Functions-to-Lambda integration underspecified. Specify resource-based policy on each Lambda pinning invoking principal to production API Gateway stage ARN, Step Functions state-machine ARN, or EventBridge rule ARN as appropriate; defense-in-depth event-payload validation against production constants. -->

**Patient-facing communication design.** When voice-biomarker results are communicated to patients (rather than only to clinicians), the messaging design is part of clinical safety. A patient receiving a biomarker score without context may misinterpret it as a diagnosis. The patient-facing interface design, the explicit framing of the biomarker as not-a-diagnosis, and the clear path to clinician follow-up are part of the deployment workstream. For SaMD-cleared devices, the patient-facing communications are part of the regulatory submission.

**Equity-focused validation that goes beyond demographic categories.** Demographic categories (age band, sex, race, ethnicity) are starting points for equity analysis, not endpoints. Voice biomarkers can fail along axes that the standard demographic categories do not capture: speakers with denture status, with smoking history, with hearing loss that affects their speech monitoring, with non-native-language English usage, with regional accents not represented in the training data. Equity validation needs to push beyond the demographic categories that are easy to measure to the speaker-property axes that actually drive performance variation.

**Integration with clinical research workflows.** Voice biomarker work in healthcare often spans the clinical-care boundary: research data can inform clinical care, and clinical-care data can inform research-track validation. The architecture for moving data between research and clinical contexts (with appropriate consent, IRB approval, and de-identification) is complex and needs explicit governance. Without it, the institution either silos the research and clinical work (limiting scientific progress and clinical improvement) or blurs the boundary improperly (creating compliance and trust risks).

**Disaster recovery and degraded-mode operation.** When upstream services fail (SageMaker endpoint outage, Bedrock outage, HealthLake outage), the system must degrade gracefully. The biomarker is decision support; its absence does not block clinical care. Document the per-mode behavior and test the failure modes in staging.

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Disaster recovery and partial-failure topology architecturally implicit. Add Disaster Recovery Topology subsection with per-stage failover policy: SageMaker outage with cross-region fallback or graceful "biomarker not currently available"; Bedrock unavailability with structured-output-only summary rendering; Transcribe Medical unavailability with cognitive-biomarker eligibility failure; HealthLake unavailability with durable result storage and retry; EHR API unreachable with delayed clinician alert. Failover-detection-and-failover-back triggers; quarterly testing cadence. -->

---

## Variations and Extensions

**Cough-classification monitoring for COPD and asthma.** A focused deployment of cough-acoustic classification for chronic respiratory-disease management. Patients submit short cough samples through a mobile app or telehealth check-in; the system classifies cough type, tracks frequency and trajectory, and surfaces deterioration patterns to the care team. This is one of the most evidence-supported voice-biomarker indications and the easiest to deploy as a focused first capability.

**Parkinson's progression monitoring in established patients.** For patients with confirmed Parkinson's disease, voice biomarker tracking provides a non-invasive, frequent-sample method of monitoring disease progression and treatment response. The longitudinal trajectory is more clinically actionable than the single-sample score, and the deployment context (patients with established diagnosis, motivated to monitor their own condition) is more appropriate than population-level screening.

**Post-stroke aphasia recovery monitoring.** Voice and speech features track recovery from stroke-induced aphasia, supporting the speech-pathology team's assessment of progress between in-person therapy sessions. The patient's own pre-stroke voice (where available) provides a strong baseline; deltas from baseline are the primary clinical signal. Recipe 10.9 (speech therapy assessment and monitoring) covers the broader speech-pathology integration.

**ICU sedation depth and delirium monitoring.** ICU patients' voice and speech features can correlate with sedation depth and emerging delirium. The architecture is similar; the clinical-action mapping is more intensive (delirium triggers ICU-specific protocols). Validation in ICU populations is its own multi-year clinical-research undertaking.

**Anesthesia-recovery monitoring after surgery.** Voice features post-anesthesia track the patient's recovery trajectory. The clinical use case is post-operative discharge readiness assessment and identification of patients with prolonged anesthesia effects. Deployment is in PACU and recovery units with their specific workflow context.

**Suicide risk decision-support in mental-health settings.** Voice-based suicidality risk scoring as a decision-support signal to mental-health clinicians. This is one of the higher-stakes deployments and warrants the most cautious clinical-action mapping. Integration with established crisis-response workflows is essential. Most institutions deploying this are research-track or carefully-piloted clinical-research deployments rather than broad clinical deployments.

**At-home longitudinal monitoring for early-dementia detection.** Patients with mild cognitive impairment or family history of dementia perform short voice-and-speech tasks at home on a weekly cadence; the system tracks longitudinal trajectory and flags meaningful changes for clinician review. The infrastructure for at-home capture (apps, kiosks, devices) is its own engineering effort. Patient acceptance and adoption are the workflow challenges.

**Pediatric speech and developmental screening.** Voice biomarkers for pediatric populations (autism spectrum disorder screening, developmental language disorder identification) are an active research area. Pediatric cohorts require their own validation, and pediatric-specific consent and assent considerations layer on top of the standard biometric-data governance. Most current deployments are research-track.

**Language-specific deployment expansion.** Most published voice-biomarker research is in English-speaking cohorts. Deployment in other languages requires per-language validation, per-language calibration, and often per-language model retraining. The architecture supports per-language deployment; the validation work per language is its own undertaking.

**Multi-modal integration with EHR data, wearable data, and structured questionnaires.** Voice biomarkers combined with EHR data (medications, prior diagnoses, vitals trends), wearable data (movement, sleep patterns, heart rate variability), and structured questionnaire responses (PHQ-9, MoCA, ADAS-Cog) often produce stronger combined signals than voice alone. The architectural extension is the multi-modal feature combination layer and the per-modality eligibility checking.

**Voice-driven self-monitoring for chronic-disease patients.** Patients with chronic conditions (CHF, COPD, atrial fibrillation) record short voice samples on a defined cadence (daily, weekly); the system tracks trajectory and surfaces deterioration patterns to the care team for proactive outreach. The patient-empowerment framing changes the consent and workflow design from clinician-initiated to patient-initiated.

**Integration with ambient documentation pipelines (recipe 10.7).** The audio captured for ambient clinical documentation can also support voice-biomarker analysis, with appropriate consent and quality verification. The architectural extension is the shared audio infrastructure between the documentation and biomarker pipelines, with explicit governance for the dual use. Audio fidelity requirements are higher for biomarkers than for documentation, so the documentation pipeline's audio must be preserved at biomarker-grade fidelity, which is not the typical default.

**Real-time clinical-decision-support during telehealth visits.** During a telehealth encounter, voice features computed from the in-call audio surface decision-support signals to the clinician (the patient's voice acoustics suggest unusual respiratory effort, atypical articulation, or other clinically-relevant patterns). The architectural extension is the streaming-feature-extraction-and-scoring path. Clinical-action mapping during the encounter is more time-pressured than the asynchronous pattern, which raises the stakes for indeterminate handling and false-positive rates.

**Group-comparison cohort studies.** The same architecture supports retrospective cohort studies: applying validated biomarkers to a defined patient population to study disease epidemiology, treatment response, or other research questions. The research-track use of the same infrastructure as the clinical-track use requires governance for the data movement and the analytical separation, but the underlying infrastructure is the same.

**De-identified-cohort sharing for federated validation.** Multiple institutions can share de-identified cohort data (or, with privacy-preserving techniques, federated training) to build larger validation cohorts than any single institution could assemble. The architectural extension involves the privacy-preserving computation layer and the inter-institutional governance. Recipe 5.8 (privacy-preserving record linkage) covers analogous patterns.

**Linguistic-feature pipelines for cognitive assessment.** A cognitive-decline-focused deployment combines voice biomarkers with linguistic features extracted from the transcript: lexical diversity, idea density, semantic coherence, word-finding patterns. Recipe 8 (NLP) and recipe 2 (LLM) cover the linguistic-analysis primitives. The integration produces a richer cognitive-assessment signal than acoustic features alone.

**Patient-facing voice-biomarker self-tracking apps.** Some institutions offer patient-facing apps where the patient can capture voice samples themselves and see their own trajectory. This is a wellness-tool framing rather than a clinical-tool framing, with corresponding consent, regulatory, and clinical-action implications. The architectural extension is the patient-facing UI and the patient-friendly result presentation. The clinician is informed but not in the active loop for low-risk results.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Asynchronous Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon SageMaker Clarify](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-fairness-and-explainability.html)
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker examples including model-hosting, Model Monitor, and Clarify patterns
- [`aws-samples/amazon-sagemaker-asr-and-audio-samples`](https://github.com/aws-samples/amazon-sagemaker-asr-and-audio-samples): audio-processing samples on SageMaker <!-- TODO: verify exact repo name and current location at build time -->
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including grounded generation and Guardrails
- [`aws-samples/amazon-comprehend-medical-samples`](https://github.com/aws-samples/amazon-comprehend-medical-samples): clinical-entity extraction patterns
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): healthcare AI/ML sample notebooks
<!-- TODO: confirm the current names and locations of these repos at time of build -->

**AWS Solutions and Blogs:**
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "voice," "audio," "biomarker," "SageMaker" for implementation deep dives
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AI/ML case studies
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for clinical-decision-support and post-market-surveillance reference architectures
<!-- TODO: replace with two or three specific verified blog post URLs once confirmed to exist -->

**External References (Standards, Frameworks, and Regulatory):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model for biomarker-result EHR integration
- [FHIR Observation Resource](https://www.hl7.org/fhir/observation.html): canonical FHIR resource for biomarker-result write-back
- [LOINC](https://loinc.org/): standard codes for laboratory and clinical observations, including some voice-and-speech-derived measures
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in voice biomarker workflows
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [Illinois Biometric Information Privacy Act (BIPA)](https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004): biometric-data law applicable to voice samples in Illinois
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): regulatory framework for software medical devices, including voice-based biomarkers
- [FDA Clinical Decision Support Software Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): guidance on the regulatory boundary between clinical decision support and regulated medical devices
- [FDA Pre-Cert Program (Digital Health)](https://www.fda.gov/medical-devices/digital-health-center-excellence): FDA's framework for digital-health software regulation

**Research and Datasets:**
- [mPower Parkinson's Voice Dataset](https://www.synapse.org/#!Synapse:syn4993293): public Parkinson's voice dataset for research <!-- TODO: verify dataset URL and current access terms -->
- [Coswara Cough Dataset](https://github.com/iiscleap/Coswara-Data): public cough dataset for respiratory-disease research <!-- TODO: verify dataset URL and license -->
- [DementiaBank](https://dementia.talkbank.org/): research corpus of speech samples from individuals with dementia, with appropriate access controls <!-- TODO: verify access terms -->
- [INTERSPEECH and ICASSP Conferences](https://www.interspeech2024.org/): primary speech-and-audio research venues; voice-biomarker work appears regularly
- [Journal of Voice](https://www.jvoice.org/): peer-reviewed clinical journal covering voice-and-speech research
- [npj Digital Medicine](https://www.nature.com/npjdigitalmed/): peer-reviewed journal covering digital health and biomarkers including voice

**Industry and Clinical Resources:**
- [American Speech-Language-Hearing Association](https://www.asha.org/): professional organization for speech-language pathologists, with relevant clinical-practice guidance
- [American Academy of Neurology](https://www.aan.org/): professional organization for neurologists, with guidance on Parkinson's, dementia, and related conditions where voice biomarkers may apply
- [American Psychiatric Association](https://www.psychiatry.org/): professional organization with guidance on mental-health clinical practice, relevant for mental-health voice-biomarker deployments
- [HHS Office for Civil Rights HIPAA Guidance](https://www.hhs.gov/hipaa/index.html): HIPAA Privacy and Security Rule guidance applicable to biometric voice samples
- [International Association of Privacy Professionals (IAPP)](https://iapp.org/): industry resource on biometric-data law and emerging-technology privacy

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single indication (typically cough classification or Parkinson's monitoring), commercial-vendor model integration through SageMaker endpoint or vendor API, single capture-device class (e.g., dedicated clinic microphone or specific telehealth platform), per-cohort calibration for two or three cohorts, basic clinician-facing decision-support display, FHIR Observation write-back to the EHR, brief-retention audio policy, English-only, pilot with one or two clinical sites | 3-5 months |
| Production-ready | Multiple validated indications (cough, Parkinson's, perhaps one mental-health-specific indication as decision support), multiple capture-device classes with per-class validation, full per-cohort calibration with eligibility gates, indeterminate-result handling, longitudinal trajectory tracking with per-patient baselines, layered post-market surveillance with SageMaker Model Monitor and Clarify plus regular clinical-quality review, biometric-data consent infrastructure with right-to-deletion workflow, full HIPAA-and-biometric-data-law compliance review, structured rollout with named operational owners, multi-language support (English plus at least one additional language), clinician training and feedback program, per-jurisdiction regulatory analysis | 12-18 months |
| With variations | Cough monitoring deployment in chronic respiratory-disease management workflows, Parkinson's progression monitoring in established-patient cohorts, post-stroke aphasia recovery monitoring, ICU sedation and delirium monitoring, anesthesia recovery monitoring, suicide-risk decision-support pilots, at-home longitudinal cognitive-decline monitoring, pediatric speech-and-language screening, multi-modal integration with EHR plus wearable plus questionnaire data, integration with ambient documentation pipelines, real-time decision support during telehealth, federated cohort validation across institutions | 8-15 months beyond production-ready |

---


---

*← [Main Recipe 10.8](chapter10.08-voice-biomarker-detection) · [Python Example](chapter10.08-python-example) · [Chapter Preface](chapter10-preface)*
