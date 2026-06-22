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

**AWS HealthLake for FHIR-based biomarker observation storage.** The biomarker score is an Observation resource in FHIR terms. HealthLake stores the FHIR Observations and supports the longitudinal-trajectory queries the workflow needs. For non-FHIR EHR integrations, the institutional EHR-integration layer translates the FHIR Observation into the EHR-specific representation. 

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
| **Validated Models** | Per-indication validated voice-biomarker models. For most institutions this means selecting commercial vendors with FDA clearances or strong published evidence (cough analysis, Parkinson's screening) rather than building from scratch. Building from scratch requires a multi-year validation study with the cohort, evidence, and regulatory work that implies. The architecture supports either pattern: third-party model integration through SageMaker endpoint or vendor API; institutionally-built models hosted on SageMaker endpoints.  |
| **External Inputs** | Capture-protocol scripts and prompts (per indication). Microphone characterization data for the supported capture-device classes. Per-cohort calibration data per validated model. Per-cohort threshold maps. Per-language linguistic-feature configurations where applicable. Validation cohort data for ongoing post-market surveillance. EHR FHIR write surface for biomarker Observation resources. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The capture-ingest Lambda has S3 write to the audio bucket only and SQS or EventBridge publish for the pipeline trigger. The feature-extraction Lambda has S3 read on the audio bucket and write on the feature bucket plus Transcribe and Comprehend Medical permissions. The scoring Lambda has SageMaker invoke-endpoint permissions for the validated indication endpoints only. The packaging Lambda has DynamoDB write, HealthLake write, Bedrock invoke-model, and EventBridge publish permissions. The EHR integration Lambda has Secrets Manager access for the EHR credentials and the EHR-specific egress only. Avoid wildcard actions and resources in production. |
| **BAA and Compliance** | AWS BAA signed. Amazon S3, SageMaker, Lambda, Step Functions, Transcribe (general and Medical), Comprehend Medical, Bedrock (verify the specific models and regions covered), HealthLake, DynamoDB, API Gateway, Cognito, KMS, Secrets Manager, EventBridge, CloudWatch Logs, CloudTrail, Kinesis Firehose, Glue, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference).  Voice samples are biometric data; biometric-data law (Illinois BIPA, Texas, Washington, and similar) applies in addition to HIPAA where the patient's jurisdiction triggers it. SaMD regulatory consideration for any model that produces clinical claims; pre-deployment FDA strategy review for indications where a SaMD pathway is relevant. IRB or institutional review for research-track deployments and for cohort-development data collection. State-specific regulatory rules for any indication that intersects controlled-substance management, mental-health crisis response, or other regulated domains. |
| **Encryption** | Audio samples: SSE-KMS with customer-managed keys, retention bound to the consent terms (often hours to days, occasionally longer with explicit consent). Feature vectors: SSE-KMS with separate customer-managed keys, retention as needed for surveillance and re-validation per institutional policy. Biomarker results: SSE-KMS with customer-managed keys, retention aligned with the medical-record retention. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements (which can be longer than HIPAA's), state medical-records-retention rules, and institutional regulatory floor. DynamoDB tables, HealthLake datastore, Lambda environment variables, and Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all API calls. |
| **VPC** | Production: Lambdas that call back-office APIs (EHR FHIR, patient portal) run in VPC with controlled egress. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SageMaker Runtime, Transcribe, Comprehend Medical, Bedrock, Lambda. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where supported by the chosen container. |
| **CloudTrail** | Enabled with data events on the audio bucket, the feature bucket, the audit-archive bucket, the DynamoDB tables, the Secrets Manager secrets, and the customer-managed KMS keys. SageMaker invocations logged. Bedrock invocations logged with metadata only (not full input/output, to avoid persisting biometric or PHI content in CloudTrail). Lambda invocations logged. API Gateway access logs enabled. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. |
| **Sample Data** | Public voice-biomarker datasets for development and feature-pipeline validation. Examples include the mPower Parkinson's voice dataset, the Coswara cough dataset, and the DementiaBank speech corpora; each has its own access terms that must be reviewed before integration.  Synthetic capture-quality test signals for the audio QA pipeline (recordings of known-quality test tones, swept sines, or reference speech samples for microphone characterization). Never use uncoded production patient voice samples in development without explicit consent and IRB or institutional review; voice samples are biometric data with non-trivial governance implications. |
| **Cost Estimate** | At a mid-sized institution scale (50,000 voice samples per year, mixed across two or three indications): SageMaker endpoint hosting and inference at typically $25,000-100,000 per year depending on real-time vs. asynchronous and instance class. Transcribe Medical and Comprehend Medical at typically $5,000-15,000 per year. Bedrock at typically $1,000-5,000 per year for natural-language interpretation packaging. Lambda, Step Functions, S3, DynamoDB, HealthLake, CloudWatch, KMS, Secrets Manager, EventBridge, Kinesis Firehose, Glue, Athena total approximately $10,000-25,000 per year combined. Total AWS infrastructure typically $40,000-150,000 per year at this scale. The per-sample cost is dominated by the SageMaker model inference. The validation, regulatory, and clinical-evidence costs are typically much larger than the infrastructure costs at this scale.  |

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
            lookup_patient_jurisdiction(patient_id),
        mental_health_profile:
            protocol.is_mental_health_indication,
        part_2_eligible:
            protocol.is_42_cfr_part_2_eligible
    })

    // Step 1C-ii: disclosure-accounting log entry for
    // the initial biometric-data collection event.
    disclosure_accounting_log.append({
        event_type: "biometric_data_collection",
        session_id: session_id,
        patient_id_hash: hash(patient_id),
        jurisdiction:
            lookup_patient_jurisdiction(patient_id),
        data_elements: ["voice_audio"],
        purpose: indication,
        consent_id: consent_outcome.consent_id,
        accessor: "voice_biomarker_pipeline",
        timestamp: now()
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
            // Linguistic-feature extraction uses a
            // wait-for-callback pattern so the Lambda
            // does not block (and bill) during the
            // Transcribe Medical job. The feature-
            // extraction Lambda starts the transcription
            // job and returns a task token to Step
            // Functions. Step Functions pauses the
            // execution until an EventBridge rule
            // detects the Transcribe job-completion
            // event and calls back with the task token.
            // A separate Lambda step then retrieves the
            // transcript and runs the linguistic-feature
            // extractor. This avoids the 15-minute
            // Lambda timeout ceiling on long samples
            // and eliminates idle-billing waste.
            transcribe_job = transcribe_medical.start_job(
                audio_ref: segment.audio_ref,
                language: state.protocol.language,
                show_speaker_labels: false,
                output_bucket: FEATURE_BUCKET,
                output_key:
                    f"{session_id}/{segment.task_id}/transcript.json")

            // Return the job name to Step Functions.
            // The state machine uses a
            // .waitForTaskToken integration to pause
            // until the Transcribe completion event
            // triggers the callback Lambda.
            RETURN {
                status: "AWAITING_TRANSCRIPTION",
                transcribe_job_name:
                    transcribe_job.job_name,
                task_token: step_functions_task_token,
                segment_task_id: segment.task_id
            }

        // --- Resumed after Transcribe completion callback ---
        // Step Functions invokes this continuation Lambda
        // with the completed transcript reference.
        IF resuming_after_transcription:
            transcript_text = retrieve_transcript(
                transcribe_job_name)

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

    // Archive-reference pattern: write full scores
    // content (including per-feature patient values and
    // cohort baselines, which are biometric-derived
    // data) to the score-archive S3 bucket under a
    // biometric-derived KMS key class. The metadata
    // table holds only structural metadata and the S3
    // reference, never the raw biometric-derived values.
    score_archive_key = f"{session_id}/scores.json"
    s3.put_object(
        bucket: SCORE_ARCHIVE_BUCKET,
        key: score_archive_key,
        body: serialize(scores),
        sse_kms_key_id: BIOMETRIC_DERIVED_KMS_KEY)

    capture_session_table.update(
        session_id: session_id,
        score_archive_ref:
            f"s3://{SCORE_ARCHIVE_BUCKET}/{score_archive_key}",
        per_indication_metadata: {
            indication: {
                status: sc.status,
                category: (sc.category
                    if sc.status == "SCORED" else NULL),
                cohort: (sc.cohort
                    if sc.status == "SCORED" else NULL),
                model_version: (sc.model_version
                    if sc.status == "SCORED" else NULL),
                calibration_version: (sc.calibration_version
                    if sc.status == "SCORED" else NULL)
            }
            FOR indication, sc IN scores
        },
        scoring_completed_at: now(),
        status: "scored")

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
        // Prompt-injection defense: transcript content
        // is delimited with explicit boundary markers
        // so the model treats it as data, not as
        // instruction. Structured-output schema
        // validation enforces the expected response
        // shape. A secondary deterministic check
        // validates that numeric claims in the summary
        // match the source biomarker fields.
        clinician_summary_raw = bedrock.invoke_model(
            model_id: SUMMARY_MODEL,
            prompt: build_summary_prompt(
                indication: indication,
                score: score,
                trajectory: trajectory,
                clinical_action: clinical_action,
                template: CLINICIAN_SUMMARY_TEMPLATE,
                // Delimited-input framing for any
                // transcript-derived content to prevent
                // prompt injection from patient speech.
                transcript_delimiter: "<transcript>",
                transcript_close: "</transcript>"),
            guardrail_id: BIOMARKER_GUARDRAIL_ID,
            response_format: {
                type: "json_schema",
                schema: SUMMARY_SCHEMA
            },
            max_tokens: 800)

        // Step 5C-ii: faithfulness check on the
        // LLM-generated summary. Structured-output
        // schema validation is first (reject malformed
        // responses). Citation grounding checks that
        // each claim in the summary traces to a source
        // biomarker field. Rule-based contradiction
        // detection catches numeric mismatches. For
        // high-stakes indications, an LLM-judge
        // faithfulness scorer provides a secondary
        // check. On faithfulness failure, fall back to
        // a deterministic structured-summary renderer.
        schema_valid = validate_schema(
            clinician_summary_raw.content, SUMMARY_SCHEMA)
        citation_grounded = check_citation_grounding(
            summary: clinician_summary_raw.content,
            source_fields: {
                score: score,
                trajectory: trajectory,
                clinical_action: clinical_action
            })
        numeric_consistent = check_numeric_consistency(
            summary: clinician_summary_raw.content,
            score: score,
            trajectory: trajectory)

        faithfulness_pass = (
            schema_valid AND
            citation_grounded AND
            numeric_consistent)

        IF NOT faithfulness_pass:
            clinician_summary = render_structured_summary(
                indication, score, trajectory,
                clinical_action)
            log_faithfulness_failure(
                session_id, indication,
                schema_valid, citation_grounded,
                numeric_consistent)
            cloudwatch.put_metric(
                namespace: "VoiceBiomarker",
                metric_name: "FaithfulnessFailureRate",
                value: 1,
                dimensions: {
                    indication: indication,
                    cohort: score.cohort
                })
        ELSE:
            clinician_summary = clinician_summary_raw.content

        // Step 5D: store the trajectory record.
        // The trajectory table is classified as a
        // biometric-derived data store. Encryption
        // uses the biometric-derived KMS key class.
        // Biometric-data governance (right-to-deletion,
        // disclosure-accounting) applies.
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
            clinician_summary: clinician_summary,
            faithfulness_pass: faithfulness_pass,
            packaged_at: now()
        }

    // Archive-reference pattern for interpretations:
    // write full content (including LLM-generated
    // clinician_summary) to the interpretation-archive
    // S3 bucket under the biometric-derived KMS key.
    // The metadata table holds only structural
    // references, not raw biometric-derived values.
    interp_archive_key = f"{session_id}/interpretations.json"
    s3.put_object(
        bucket: INTERPRETATION_ARCHIVE_BUCKET,
        key: interp_archive_key,
        body: serialize(interpretations),
        sse_kms_key_id: BIOMETRIC_DERIVED_KMS_KEY)

    capture_session_table.update(
        session_id: session_id,
        interpretation_archive_ref:
            f"s3://{INTERPRETATION_ARCHIVE_BUCKET}/{interp_archive_key}",
        per_indication_interpretation_metadata: {
            indication: {
                status: interp.status,
                clinical_action: (interp.clinical_action
                    if interp.status == "INTERPRETED"
                    else NULL),
                faithfulness_pass: (interp.faithfulness_pass
                    if interp.status == "INTERPRETED"
                    else NULL)
            }
            FOR indication, interp IN interpretations
        },
        packaging_completed_at: now(),
        status: "interpreted")

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
        // applicable. Idempotency: use a conditional
        // create with an idempotency key composed of
        // (session_id, indication). On duplicate write,
        // return the prior resource_id rather than
        // creating a second Observation, which would
        // trigger duplicate decision-support alerts
        // and corrupt the longitudinal baseline.
        observation_resource = build_fhir_observation(
            patient_id: lookup_patient_id(
                state.patient_id_hash),
            indication: indication,
            interpretation: interpretation,
            performed_at: state.started_at)

        idempotency_identifier = {
            system: "urn:institution:voice-biomarker",
            value: f"{session_id}:{indication}"
        }
        observation_resource.identifier = [
            idempotency_identifier]

        // FHIR conditional-create: If-None-Exist
        // header checks against the identifier.
        // HealthLake returns 200 with the existing
        // resource if one matches; 201 if created.
        healthlake_response = healthlake_client.create_resource(
            resource_type: "Observation",
            resource: observation_resource,
            conditional_create_criteria:
                f"identifier={idempotency_identifier.system}|"
                f"{idempotency_identifier.value}")

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
        mental_health_profile: state.mental_health_profile,
        part_2_eligible: state.part_2_eligible,
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
                     else NULL),
                model_card_version:
                    (interp.score.model_card_version
                     if interp.status == "INTERPRETED"
                     else NULL),
                clinical_action_mapping_version:
                    CLINICAL_ACTION_MAPPING_VERSION
            }
            FOR indication, interp IN interpretations
        },
        recording_chain_metadata:
            state.feature_set.recording_chain_metadata,
        consent_id: state.consent_id,
        protocol_version: state.protocol_version,
        feature_pipeline_version: FEATURE_PIPELINE_VERSION,
        eligibility_rules_version:
            ELIGIBILITY_RULES_VERSION,
        summary_prompt_version: SUMMARY_PROMPT_VERSION
    }

    // Route to appropriate audit-archive prefix based
    // on mental-health-profile and Part 2 flags.
    audit_prefix = determine_audit_prefix(
        mental_health_profile: state.mental_health_profile,
        part_2_eligible: state.part_2_eligible,
        jurisdiction: state.jurisdiction)
    audit_archive_kinesis_firehose.put(
        audit_record, prefix: audit_prefix)

    // Disclosure-accounting log entry for the audit
    // event itself.
    disclosure_accounting_log.append({
        event_type: "session_audit_complete",
        session_id: session_id,
        patient_id_hash: state.patient_id_hash,
        jurisdiction: state.jurisdiction,
        data_elements: ["audit_record"],
        purpose: "post_market_surveillance",
        accessor: "voice_biomarker_pipeline",
        timestamp: now()
    })

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

### Cross-Cutting Architectural Primitives

The following subsections specify architectural primitives that the pseudocode references but that require more detail than inline comments can carry. Each elevates a concern from "passing prose reference" to "named, enforceable architectural decision."

#### Voice-as-Biometric-Data Governance

Voice samples are biometric identifiers under multiple legal frameworks simultaneously. The architecture treats biometric-data governance as a first-class primitive, not a compliance afterthought.

**Disclosure-accounting log.** Every operation that accesses, processes, or discloses a voice sample or its biometric derivatives (feature vectors, scores, trajectory entries) appends an entry to a disclosure-accounting log. The log records: who accessed, what was accessed (audio, features, score, trajectory), when, for what purpose, and which patient and jurisdiction the data belongs to. The log is append-only, stored in the audit-archive bucket with Object Lock in compliance mode, encrypted under its own KMS key. Step 1B captures the initial collection entry. Every subsequent pipeline step (feature extraction, scoring, interpretation, EHR write-back, clinician view, patient view) appends its own disclosure-accounting entry. The disclosure-accounting log supports GDPR Article 30 record-of-processing, BIPA disclosure-accounting, and institutional audit requirements.

**Right-to-deletion workflow with feature-vector propagation.** When a patient exercises their right to deletion (GDPR Article 17, BIPA, or institutional policy), the deletion workflow propagates across all biometric-derived data: raw audio (S3), feature vectors (S3), scores stored in the score-archive bucket, interpretation-archive entries, trajectory-table entries (DynamoDB), HealthLake FHIR Observations, and any disclosure-accounting entries that are not themselves required for regulatory retention. Cryptographic erasure serves as the deletion primitive: the per-patient or per-session KMS key is scheduled for deletion, rendering all encrypted artifacts unrecoverable without requiring individual object deletion across every store. The workflow is triggered by a patient-portal request or a privacy-officer action, validated against jurisdiction-specific retention floors (some jurisdictions require minimum retention that overrides deletion requests), and produces a deletion-confirmation artifact in the audit archive.

**Per-jurisdiction key management.** Patients in different jurisdictions trigger different biometric-data governance rules. The architecture supports per-jurisdiction KMS key classes so that cryptographic erasure for one jurisdiction's data does not affect another's. The S3 prefix structure partitions data by `/jurisdiction/<jur>/profile/<prof>/...` to enable per-jurisdiction lifecycle policies and per-jurisdiction key association.

**Feature-vector biometric classification.** Feature vectors extracted from voice samples are themselves biometric data (they can be used for speaker identification). The architecture classifies feature vectors as biometric-derived data, applies the same governance as raw audio (encryption with biometric-data KMS key class, disclosure-accounting, right-to-deletion propagation), and applies retention policies independently of audio retention (feature vectors may be retained longer than audio, per consent terms, for surveillance and re-validation purposes).

**Synthetic-voice-detection and voice-cloning defense.** The capture-quality-assessment stage includes a synthetic-voice-detection check that flags audio exhibiting characteristics of text-to-speech synthesis or voice-cloning artifacts. Flagged samples produce an ineligibility result ("capture authenticity not confirmed") rather than entering the biomarker pipeline. This defends against adversarial inputs in research-enrollment and disability-assessment contexts.

**GDPR Article 9 per-region deployment.** For patients whose jurisdiction triggers GDPR, voice samples are special-category biometric data under Article 9. The architecture enforces explicit consent (not legitimate-interest) as the lawful basis, data-residency within the EU/EEA region for EU patients (separate S3 buckets, separate SageMaker endpoints in eu-west-1 or eu-central-1), and right-to-erasure with the 30-day response window. Per-region deployment configuration is a deploy-time parameter, not a runtime branching decision.

**Pediatric-profile biometric governance.** Pediatric voice samples carry additional governance requirements: parental/guardian consent rather than patient consent, extended retention-floor rules (state pediatric-records retention statutes often extend to age-of-majority plus additional years), and stricter access controls. The architecture tags pediatric sessions at capture time and applies the pediatric governance profile throughout the pipeline.

**Operational ownership.** Voice-as-biometric-data governance is co-owned by the institutional privacy officer and the institutional records-management function. Technical implementation is engineering-owned; policy decisions (retention terms, disclosure language, deletion-request adjudication) are privacy-officer-owned.

#### Per-Device-Pattern Audio Path Authentication and Encryption

Voice biomarker audio traverses different capture paths depending on the device class. Each path has specific authentication and encryption requirements.

**TLS minimum, mTLS preferred for dedicated clinic microphones.** All audio in transit uses TLS 1.2+ minimum. Dedicated clinic-microphone devices (which have a known identity and can hold a client certificate) use mutual TLS (mTLS) to authenticate both ends of the connection. This prevents a rogue device on the clinic network from submitting audio to the biomarker pipeline.

**Per-encounter session tokens for smartphone-app and web-app capture.** Smartphone apps and browser-based capture use per-encounter session tokens tied to the authenticated patient session. The token is scoped to a single capture session, expires at session completion or after a short timeout (15 minutes), and is non-replayable.

**Device-attestation for smartphone-app and kiosk patterns.** Where the platform supports it (iOS DeviceCheck, Android SafetyNet/Play Integrity, kiosk-specific attestation), device-attestation tokens are submitted with the audio. The pipeline validates attestation before accepting the sample. Failed attestation produces a capture-rejection with a prompt to use an alternative capture path.

**Per-device-class BAA scope.** The BAA with AWS covers audio in transit and at rest within AWS. For device-class patterns that involve non-AWS intermediaries (e.g., a telehealth platform's audio path before it reaches the pipeline API), the BAA scope extends to the intermediary via a separate BAA or subprocessor agreement. The architecture documents which device-class patterns require which BAA coverage.

**Per-device-class certification.** Each supported device class has a certification record in the model-card configuration: the device class name, the validated microphone characteristics, the expected codec, the validated bandwidth, and the date of last certification review. Uncertified device classes produce a capture-rejection.

**Audit-record propagation of device-attestation context.** The capture-session record and the audit archive include the device-attestation context (attestation result, device class, device token hash) for every sample. Post-market surveillance can stratify by device class to detect device-specific performance degradation.

#### External-Vendor Biomarker-Model API Data-in-Transit Posture

When the pipeline calls an external vendor's biomarker-model API (rather than hosting the model on SageMaker), the data-in-transit posture for biometric-data export requires explicit specification.

**Vendor API authentication.** mTLS where the vendor supports it; otherwise API key plus scoped IAM credentials with per-call rotation via Secrets Manager. The credentials are pinned to the specific vendor endpoint and cannot be used for any other purpose.

**TLS-in-transit minimum with certificate pinning.** TLS 1.2+ minimum for vendor API calls. Where the vendor provides a stable certificate chain, certificate pinning prevents MITM attacks on the vendor connection. The pinned certificate set is maintained as a deploy-time configuration artifact with an explicit rotation cadence.

**Per-call disclosure-accounting log entry.** Every call to an external vendor API produces a disclosure-accounting log entry recording: the vendor name, the data elements transmitted (audio reference or feature-vector reference), the patient jurisdiction, and the timestamp. This supports the patient's right to know who has processed their biometric data.

**Vendor BAA scope.** The vendor BAA covers audio data in transit to the vendor, at rest within the vendor's pipeline, and within the vendor's subprocessors. The architecture verifies BAA coverage at contract time and re-validates annually.

**Vendor data-residency commitment.** The vendor's data-processing location is aligned with the patient's jurisdiction. For EU patients, the vendor processes within EU/EEA unless explicit consent covers cross-border transfer. The vendor's data-residency commitment is documented in the vendor configuration.

**Egress hierarchy.** The architecture prefers the most isolated network path available: PrivateLink (where the vendor exposes a VPC endpoint service) > Direct Connect or VPN (where a dedicated private connection exists) > public Internet with TLS (as a last resort with the mitigations above). The choice is per-vendor and documented in the vendor configuration.

#### Per-Cohort Accuracy and Adoption Monitoring with Launch-Gate Discipline

The recipe's prose elevates cross-cohort generalization as the single largest gap between published voice-biomarker accuracy and real-world deployment accuracy. This section promotes per-cohort monitoring from prose to architectural primitive.

**Single-axis cohorts.** The surveillance system tracks per-cohort metrics along each individual axis: age-band, sex, language, recording-chain (device class plus codec), jurisdiction, indication, and confound-flag-pattern.

**Two-axis cohorts.** For the interaction effects that single-axis monitoring misses, the system also tracks two-axis cohorts: language-by-recording-chain, age-band-by-indication, sex-by-language, and jurisdiction-by-recording-chain. These capture the performance failures that occur only at the intersection of two axes.

**Per-cohort minimum sample size.** A cohort's metrics are only reported (and only used for launch-gate decisions) when the cohort has accumulated at least the minimum sample size (configurable per indication; typical floor is 50-100 scored samples per cohort per quarter). Below-threshold cohorts are flagged as "insufficient data for cohort evaluation."

**Per-cohort threshold metrics.** Each cohort is evaluated against: AUC, sensitivity, specificity, indeterminate-rate, cross-cohort generalization gap (delta between this cohort's AUC and the overall AUC), sustained-utilization rate (what fraction of eligible patients in this cohort actually complete the biomarker workflow), and score-distribution drift (KL divergence or similar between the current quarter's score distribution and the validation-time distribution).

**Launch gate.** Every cohort that has met minimum sample size must meet the institutional per-cohort performance threshold before the indication is deployed to that cohort. Cohorts that fail the gate are disabled for that indication: eligible patients in that cohort receive a "biomarker not available for your profile" result rather than a potentially-misleading score. The gate is evaluated quarterly and re-evaluated after model or calibration updates.

**Cohort-disabled-feature workflow.** When a cohort fails the launch gate, the eligibility-check step automatically excludes patients matching that cohort. The exclusion is logged, surfaced on the operational dashboard, and reported to the clinical-quality review meeting. Re-enablement requires a corrective-action plan (additional calibration data, model retraining, or cohort-specific threshold adjustment) and re-validation.

**Mental-health-profile tighter thresholds.** For mental-health indications (depression severity, suicidality risk), per-cohort thresholds are tighter than for lower-stakes indications (respiratory monitoring, Parkinson's trajectory). The justification is that false-positive mental-health biomarker results carry higher trust-damage risk and that the clinical-action mapping for mental-health biomarkers is higher-stakes.

**Per-jurisdiction cohort segmentation.** Cohort segmentation aligns with biometric-data governance jurisdiction boundaries. A cohort defined by jurisdiction can be independently enabled or disabled without affecting other jurisdictions, supporting the per-jurisdiction regulatory posture.

#### Mental-Health, Substance-Use, and 42 CFR Part 2 Biomarker Profile

Voice biomarkers for depression severity, suicidality risk, and substance-use-related indicators require a more restrictive governance profile than physical-health biomarkers. 42 CFR Part 2 applies when the biomarker indication intersects with substance-use treatment records.

**Shorter retention.** Audio and feature-vector retention for mental-health-profile biomarkers defaults to shorter windows than physical-health indications (24-48 hours for audio vs. 24-72 hours for physical-health biomarkers; feature vectors follow proportionally). The shorter window reflects the higher sensitivity of mental-health voice data and the narrower consent terms appropriate to the use case.

**Narrower access controls with separate KMS key class.** Mental-health biomarker results are encrypted under a separate KMS key class from physical-health results. Access to the mental-health key class requires additional IAM conditions (membership in the mental-health-clinical-team group, explicit per-session justification logging). This prevents incidental access by clinicians or staff who are not part of the patient's mental-health care team.

**Clinical-action mapping capped at decision_support_only.** Mental-health biomarker results are never routed directly to patient-facing channels without clinician review. The clinical-action mapping for mental-health indications is capped at `decision_support_only` with mandatory clinician acknowledgement before any downstream action. No automated patient messaging based on mental-health biomarker scores.

**Crisis-response workflow integration.** For high-suicidality scores that exceed the institutional crisis threshold, the system integrates with the established crisis-response workflow (immediate clinician notification via the highest-priority channel, linkage to crisis counselor on-call). The integration is pre-configured and tested quarterly. The biomarker does not replace the crisis-response workflow; it triggers entry into it.

**No patient-facing direct release.** Mental-health biomarker scores are never surfaced to the patient without clinician mediation. The patient-facing summary for mental-health indications, if rendered at all, is clinician-approved before delivery.

**Separate audit-archive prefix with mental-health-record disclosure-accounting metadata.** Mental-health biomarker audit records use a separate S3 prefix (`/mental-health-profile/...`) with tighter access controls and separate disclosure-accounting metadata that tracks mental-health-specific access patterns.

**Cross-encounter analytics exclusion.** Mental-health biomarker data is excluded from cross-encounter aggregate analytics unless the analytics are specifically authorized for mental-health-quality-improvement purposes with appropriate IRB or privacy-officer review. This prevents incidental surfacing of mental-health biomarker patterns in institutional dashboards that are not designed for mental-health data.

**42 CFR Part 2 flags.** When the biomarker indication is eligible for 42 CFR Part 2 protection (substance-use-related indications), the capture-session record is flagged at Step 1 and the flag propagates through all subsequent records. The 42 CFR Part 2 flag triggers: more restrictive disclosure rules (no re-disclosure without explicit patient authorization), separate disclosure-accounting log entries, and integration with the institution's Part 2 compliance infrastructure.

**Step 1 and Step 7 audit-record updates.** The capture-session record (Step 1) includes `mental_health_profile: true/false` and `part_2_eligible: true/false` flags set at capture initiation based on the indication. The audit record (Step 7) carries these flags and routes to the appropriate audit-archive prefix and disclosure-accounting pathway.

#### Foundation-Model and Per-Cohort-Calibration Versioning via Inference Profiles

Every artifact that influences scoring (model weights, prompts, model cards, calibration curves) is versioned, stamped on every encounter, and subject to change-management discipline.

**Versioned definitions in source control.** Model cards, summary prompts, calibration curves, eligibility rules, and clinical-action mappings live as versioned artifacts in the institution's configuration repository. Every change produces a new version tag. Deployments reference specific version tags, never "latest."

**SageMaker endpoint canary deployment with traffic-shift.** New per-indication model versions deploy to a canary variant receiving a small percentage of traffic (typically 5-10%). The canary's per-cohort metrics are compared against the production variant's established baseline. Traffic shifts to the new variant only when the canary meets all per-cohort launch-gate thresholds. Regression triggers automatic rollback.

**Bedrock inference profile for prompt-and-model versioning with rollback-on-regression.** Clinician-summary rendering uses a Bedrock inference profile that pins the foundation model version and the prompt template version. Prompt updates deploy through the same canary pattern: a new inference profile receives a fraction of traffic; faithfulness-failure-rate and clinician-satisfaction metrics are compared against baseline; rollback triggers automatically on regression.

**Held-out evaluation set with per-cohort coverage.** Each per-indication model maintains a held-out evaluation set that spans all validated cohorts. The evaluation set runs against every canary deployment before traffic-shift approval. The evaluation set includes prompt-injection test cases for the LLM paths.

**Version stamping on every encounter audit record.** The audit record produced at Step 7 includes: `model_version`, `calibration_version`, `model_card_version`, `clinical_action_mapping_version`, `summary_prompt_version`, `feature_pipeline_version`, and `eligibility_rules_version`. A future audit reconstructs exactly which configuration produced a given score.

**SaMD-specific change-management discipline.** For indications with FDA clearance (or pending clearance), model and calibration changes that affect the device's intended use or performance characteristics trigger the SaMD change-management process. The version-control system tags clearance-affecting changes, and the deployment pipeline enforces a regulatory-affairs review gate before those changes enter production.

#### Multi-Language Pipeline Pattern

The architecture supports multi-language deployment from day one rather than treating non-English languages as a later add-on.

**Per-language ASR configuration with custom vocabulary.** Each supported language has its own Transcribe Medical (or Transcribe) configuration with language-specific custom vocabularies for medical terminology. The custom vocabulary is maintained by clinical-informatics staff with native-speaker input for each language.

**Per-language acoustic-feature calibration data.** Acoustic features (fundamental frequency range, formant positions, articulation-rate norms) differ by language. Each supported language has its own calibration dataset that establishes language-specific norms. Models that use acoustic features are either language-specific or include language as an explicit input feature with per-language calibration.

**Per-language linguistic-feature LLM-judge prompts with native-speaker clinical-informatics input.** For cognitive biomarkers that use LLM-judged linguistic features (semantic coherence, topic adherence), the LLM prompts are language-specific, developed with native-speaker clinical-informatics expertise, and validated against a per-language gold-standard annotation set.

**Per-language template definitions and faithfulness rule catalogs.** Clinician-summary templates, patient-facing message templates, and faithfulness-check rules are per-language. Translation is not a post-hoc step on English templates; each language has its own clinical-informatics-reviewed templates.

**Per-language validation cohort.** Each language has its own validation cohort with the same rigor as the English cohort (speaker-disjoint splits, confound-controlled design, per-cohort reporting). A new language is not deployed until its validation cohort meets the launch-gate thresholds.

**Per-language consent disclosure.** Consent disclosures and biometric-data notifications are rendered in the patient's preferred language, reviewed by the legal team for per-jurisdiction accuracy in that language.

#### Audio Retention Configuration with Per-Jurisdiction Differentiation

Audio retention is not a single global setting. It varies by jurisdiction, by consent terms, by indication profile, and by regulatory context.

**Configurable retention windows.** Default retention windows are: 24-72 hours for physical-health biomarkers, 24-48 hours for mental-health-profile biomarkers, 24 hours for 42-CFR-Part-2-eligible indications. Per-jurisdiction adjustments override the defaults where biometric-data law specifies shorter maximum retention (or where specific consent terms authorize longer retention for research purposes).

**Per-jurisdiction adjustments.** Illinois (BIPA): retention capped at the shorter of consent terms and the purpose-fulfillment window (typically 24 hours for clinical scoring, longer only with explicit written consent). Washington: similar purpose-limitation constraint. GDPR (EU patients): retention limited to the minimum necessary for the stated purpose, with explicit data-minimization documentation. Per-jurisdiction rules are maintained as configuration, not code, with legal-team review on the update cadence.

**Per-prefix S3 lifecycle policies.** The audio bucket's S3 lifecycle policies are configured per-prefix on the `/jurisdiction/<jur>/profile/<prof>/...` structure. Each prefix has its own lifecycle rule that enforces the jurisdiction-and-profile-specific retention window. Lifecycle actions are: transition to Glacier Instant Retrieval at 50% of retention window (for cost savings while retaining recoverability), permanent deletion at retention-window expiry. Object Lock in governance mode prevents accidental early deletion during the retention window.

#### Audit-Log Retention Floors

Audit-log retention is sized to the longest applicable retention requirement across all regulatory and institutional frameworks. The retention floor is not a single number; it is the maximum of:

- **HIPAA six-year minimum:** applies to all PHI-related audit records.
- **State-specific medical-records retention:** some states require longer than six years. Pediatric records often extend to age-of-majority plus additional years (varies by state; some require retention until age 21 or 25).
- **Per-jurisdiction biometric-records retention:** BIPA requires retention documentation for three years after last collection or last use (whichever is later). GDPR Article 9 requires documentation of processing basis for the life of the processing activity plus a reasonable buffer. Washington and similar statutes have their own floors.
- **FDA SaMD post-market surveillance retention:** for cleared devices, retention sized to the post-market surveillance plan (often 10+ years for long-term safety monitoring).
- **Mental-health-record-specific retention statutes:** many states have mental-health-record retention floors that exceed the general medical-records retention (often 10-15 years).
- **42 CFR Part 2 disclosure-accounting log retention:** for substance-use-eligible visits, the disclosure-accounting log must be retained for the life of the patient record.
- **Institutional regulatory floor:** the institution's own retention policy, which is often the most conservative (longest) of all applicable requirements.

The S3 lifecycle policy on the audit-archive bucket enforces the longest-of calculation. The calculation is per-session (based on the patient's jurisdiction, age at time of capture, indication profile, and any applicable SaMD clearance status) and is recorded as a retention-floor-expiry field on the audit record at Step 7.

#### Lambda Invocation Authentication

Each Lambda function in the pipeline is invoked only by its intended caller. Resource-based policies on each Lambda pin the invoking principal to specific source ARNs.

**API-Gateway-to-Lambda:** The capture-ingest Lambda's resource-based policy allows invocation only from the production API Gateway stage ARN. No other principal can invoke it directly.

**Step-Functions-to-Lambda:** Pipeline-stage Lambdas (feature-extraction, eligibility-check, scoring, calibration, interpretation-packaging, audit) allow invocation only from the specific Step Functions state-machine ARN that orchestrates the pipeline.

**EventBridge-to-Lambda:** Event-driven Lambdas (clinician-feedback handler, surveillance-metric emitter) allow invocation only from the specific EventBridge rule ARNs that trigger them.

**Defense-in-depth event-payload validation.** In addition to IAM-level invocation control, each Lambda validates incoming event payloads against production constants (expected source, expected detail-type, expected schema version) before processing. An event that passes IAM checks but fails payload validation is logged and rejected.

#### Disaster Recovery and Partial-Failure Topology

When individual services fail, the pipeline degrades gracefully rather than failing completely. The biomarker is decision support; its unavailability does not block clinical care.

**SageMaker endpoint outage.** Primary mitigation: cross-region fallback endpoint in a secondary region (with the same model version and calibration). If cross-region is not available, graceful degradation: the system returns "biomarker not currently available" for the affected indication, logs the outage, and does not produce a score. The clinical workflow proceeds without the biomarker.

**Bedrock unavailability.** The clinician-summary rendering falls back to `render_structured_summary` (a deterministic template-based renderer that produces a less-natural but factually-correct summary from the structured score data). The structured-output-only summary is marked as "template-rendered" in the audit record.

**Transcribe Medical unavailability.** Cognitive-biomarker indications that depend on linguistic features become ineligible. The eligibility-check step returns "cognitive biomarker not assessable: transcription service unavailable." Acoustic-only indications (Parkinson's, cough) continue to score normally.

**HealthLake unavailability.** The FHIR Observation write-back fails. The interpretation is stored durably in the interpretation-archive bucket and in the trajectory table. A retry mechanism (EventBridge scheduled rule) re-attempts the HealthLake write on a backoff cadence until HealthLake recovers. The clinician alert is delivered independently of the FHIR write (it does not depend on HealthLake).

**EHR API unreachable.** The EHR write-back for clinician alerting fails. The system stores the pending alert in a DynamoDB queue with exponential-backoff retry. The alert is delayed but not lost. If the EHR remains unreachable beyond a threshold (configurable; typically 4 hours), an operational alarm fires and the on-call team is notified.

**Failover detection and failover-back triggers.** Health checks on each upstream service run at 60-second intervals. Three consecutive failures trigger failover to the degraded-mode behavior. Three consecutive successes after a failover trigger failover-back to the primary behavior. The failover state is observable on the operational dashboard.

**Quarterly testing cadence.** Each failure mode is tested in staging on a quarterly cadence. The test validates that the degraded behavior produces the expected outputs (correct status codes, correct audit records, correct operational alarms) and that failover-back restores normal operation cleanly.

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

**Patient-facing communication design.** When voice-biomarker results are communicated to patients (rather than only to clinicians), the messaging design is part of clinical safety. A patient receiving a biomarker score without context may misinterpret it as a diagnosis. The patient-facing interface design, the explicit framing of the biomarker as not-a-diagnosis, and the clear path to clinician follow-up are part of the deployment workstream. For SaMD-cleared devices, the patient-facing communications are part of the regulatory submission.

**Equity-focused validation that goes beyond demographic categories.** Demographic categories (age band, sex, race, ethnicity) are starting points for equity analysis, not endpoints. Voice biomarkers can fail along axes that the standard demographic categories do not capture: speakers with denture status, with smoking history, with hearing loss that affects their speech monitoring, with non-native-language English usage, with regional accents not represented in the training data. Equity validation needs to push beyond the demographic categories that are easy to measure to the speaker-property axes that actually drive performance variation.

**Integration with clinical research workflows.** Voice biomarker work in healthcare often spans the clinical-care boundary: research data can inform clinical care, and clinical-care data can inform research-track validation. The architecture for moving data between research and clinical contexts (with appropriate consent, IRB approval, and de-identification) is complex and needs explicit governance. Without it, the institution either silos the research and clinical work (limiting scientific progress and clinical improvement) or blurs the boundary improperly (creating compliance and trust risks).

**Disaster recovery and degraded-mode operation.** When upstream services fail (SageMaker endpoint outage, Bedrock outage, HealthLake outage), the system must degrade gracefully. The biomarker is decision support; its absence does not block clinical care. Document the per-mode behavior and test the failure modes in staging. See the Disaster Recovery and Partial-Failure Topology subsection in the Cross-Cutting Architectural Primitives section for the per-service failover specification.

**Voice-as-Biometric-Data Governance Operations.** The biometric-data governance primitives specified in the Cross-Cutting Architectural Primitives section require named operational owners. The institutional privacy officer owns the policy decisions: consent disclosure language, retention terms, deletion-request adjudication, per-jurisdiction compliance posture. The institutional records-management function owns the retention-floor calculations, audit-log lifecycle enforcement, and disclosure-accounting log integrity. Engineering owns the technical implementation of both. Without these named owners, the biometric-data governance primitives decay into documentation that no one enforces.

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
- [`aws-samples/amazon-sagemaker-asr-and-audio-samples`](https://github.com/aws-samples/amazon-sagemaker-asr-and-audio-samples): audio-processing samples on SageMaker 
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including grounded generation and Guardrails
- [`aws-samples/amazon-comprehend-medical-samples`](https://github.com/aws-samples/amazon-comprehend-medical-samples): clinical-entity extraction patterns
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): healthcare AI/ML sample notebooks

**AWS Solutions and Blogs:**
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "voice," "audio," "biomarker," "SageMaker" for implementation deep dives
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AI/ML case studies
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for clinical-decision-support and post-market-surveillance reference architectures

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
- [mPower Parkinson's Voice Dataset](https://www.synapse.org/#!Synapse:syn4993293): public Parkinson's voice dataset for research 
- [Coswara Cough Dataset](https://github.com/iiscleap/Coswara-Data): public cough dataset for respiratory-disease research 
- [DementiaBank](https://dementia.talkbank.org/): research corpus of speech samples from individuals with dementia, with appropriate access controls 
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
