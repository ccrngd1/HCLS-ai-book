# Recipe 10.9 Architecture and Implementation: Speech Therapy Assessment and Monitoring

*Companion to [Recipe 10.9: Speech Therapy Assessment and Monitoring](chapter10.09-speech-therapy-assessment-monitoring). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon S3 for audio sample storage with task-segmented organization.** Each session produces task-segmented audio clips: one per articulation-inventory stimulus, one continuous capture per connected-speech task, one per fluency probe, one per voice-quality task. S3 holds the audio with SSE-KMS encryption using customer-managed keys. The bucket structure organizes audio by session, task, and stimulus to support per-task feature extraction and SLP playback. Lifecycle rules enforce per-consent retention; a separate audit archive holds derived data for surveillance.

**Amazon SageMaker for disordered-speech-aware acoustic models.** The acoustic-model substrate for forced alignment, phoneme classification, and acoustic feature extraction is custom rather than catalog. Most production speech-therapy AI vendors ship models built on top of self-supervised speech representations (wav2vec 2.0, HuBERT, WavLM) fine-tuned on disordered-speech corpora and SLP-labeled clinical data. SageMaker hosts these models as endpoints, with per-population (pediatric, adult, dysarthric, fluent-disordered) endpoints reflecting the per-population validation. SageMaker Asynchronous Inference suits the per-session batch-scoring workload; real-time endpoints support the immediate-feedback use cases like home-practice apps.

**Amazon Transcribe Medical for connected-speech transcription where appropriate.** When the assessment includes connected-speech tasks (story retell, picture description, conversation) and the system extracts linguistic features from the transcript, Transcribe Medical produces the transcript. For typical-speech adults this works well; for severely disordered speech the off-the-shelf transcription accuracy is limited, and the system either accepts the limitation, uses a disordered-speech-fine-tuned ASR (typically deployed as a custom SageMaker endpoint), or flags transcription items for SLP review. Recipe 10.4 covers the medical-dictation transcribe pipeline; the lessons there about custom vocabulary and per-cohort accuracy apply here at lower volume but with the additional disordered-speech challenge.

**Amazon Bedrock for natural-language report generation and patient-friendly summary generation.** The SLP-facing assessment report (which combines the per-instrument scores, the longitudinal context, the clinical interpretation, and the goals and recommendations) is a natural-language artifact. Bedrock generates the prose around the structured scoring. The same model also generates the parent-and-patient-friendly summary at appropriate reading level. Recipe 2.5 (after-visit summary generation) and recipe 2.6 (clinical note summarization) cover the summarization patterns that apply here.

**Amazon Bedrock Guardrails for content filtering on patient-facing communications.** Patient and parent-facing summaries pass through Guardrails to ensure appropriate framing (this is an assessment, not a diagnosis), appropriate reading level, and absence of hallucinated content beyond what the structured scoring supports.

**AWS Lambda and AWS Step Functions for pipeline orchestration.** Per-stage Lambdas handle session setup, audio ingest, per-task feature extraction, per-instrument scoring, longitudinal comparison, SLP review handoff, documentation generation, and EHR/SIS write-back. Step Functions coordinates the stages with durable state. Per-task scoring fans out across stimulus items and fans back in for per-instrument aggregation; Step Functions Map state handles this naturally.

**AWS HealthLake for FHIR-based assessment storage.** Speech-therapy assessment results are Observation resources in FHIR terms (with per-instrument scores), DocumentReference resources for the assessment-report PDFs, and Goal resources for therapy goals. HealthLake stores the FHIR resources. For non-FHIR EHR integrations and school SIS integrations, the institutional integration layer translates the FHIR representation into the target system's format. 

**Amazon DynamoDB for per-patient session state and longitudinal feature history.** The per-patient longitudinal store holds session-by-session feature vectors, per-goal progress trajectories, per-target-sound mastery curves, and per-instrument score histories. DynamoDB's partition-key-by-patient and sort-key-by-session-timestamp model supports the trajectory queries efficiently.

**Amazon API Gateway for SLP, patient, and parent-facing applications.** The SLP-facing assessment-and-review interface, the patient-facing or parent-facing home-practice app, and the administrative dashboards all access the system through API Gateway endpoints. Cognito or institutional IdP authentication applies, with per-role scopes (SLP, patient, parent, administrator).

**Amazon Cognito or institutional IdP via OIDC/SAML for authentication.** SLP authentication through the institutional identity provider with appropriate clinical-application scopes. Patient and parent authentication for home-practice and parent-coaching applications uses a patient-or-parent-identity flow with appropriate scopes. Pediatric users typically access the system under parent-account supervision rather than with their own credentials.

**AWS KMS for cryptographic key custody.** Customer-managed keys for the audio bucket, the feature-vector bucket, the longitudinal-store DynamoDB tables, the assessment-archive bucket, the documentation PDFs, and the audit archive. Voice samples and feature vectors use separate KMS keys for blast-radius containment.

**AWS Secrets Manager for EHR, SIS, and external-vendor API credentials.** The Lambdas that integrate with external documentation systems, with school SIS systems, and with any external speech-therapy vendor APIs hold their credentials in Secrets Manager with rotation per the institutional cadence.

**Amazon EventBridge for cross-system event flow.** Session-completed, scoring-completed, SLP-reviewed, and report-delivered events flow through EventBridge. Downstream consumers (the longitudinal-analytics pipeline, the practice-level dashboard, the home-practice prompt scheduler) react to events without coupling to the orchestration Lambdas.

**Amazon CloudWatch for operational metrics and alarms.** Per-stage latency, per-population scoring distributions, SLP-override rates per item type, indeterminate-result rates, audio-quality scores, post-deployment accuracy proxies. Alarms on per-population drift thresholds, on SLP-override-rate spikes, on indeterminate-result-rate spikes.

**AWS CloudTrail for API-level audit.** All access to PHI-bearing and biometric-bearing resources logged. SageMaker invocations logged. KMS key uses logged. CloudTrail logs in a dedicated bucket with Object Lock and lifecycle to S3 Glacier Deep Archive after 90 days.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon QuickSight (optional) for analytics and surveillance.** Audit and surveillance data streams to S3 via Firehose. Glue catalogs the data. Athena provides SQL access for the operational and post-market surveillance analytics. QuickSight renders the SLP-facing caseload dashboards and the practice-leadership outcomes dashboards.

**Amazon SageMaker Model Monitor and Clarify for ongoing model surveillance.** Model Monitor compares production inference against the training-time baseline for data-quality drift and model-quality drift. Clarify produces feature-attribution and bias reports per population on a scheduled cadence. Together, they support the per-population surveillance the clinical-quality posture requires. SLP-override data feeds back as a real-world performance signal alongside the model-monitor metrics.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Capture
      SLP[SLP or<br/>Patient Device]
      SETUP[Session Setup<br/>and Stimulus<br/>Selection]
      QA[Per-Task<br/>Audio QA]
    end

    subgraph Ingest
      APIGW_IN[API Gateway<br/>Capture API]
      L_INGEST[Lambda<br/>Session Ingest]
      S3_AUDIO[(S3 Audio<br/>Task-Segmented<br/>SSE-KMS)]
    end

    subgraph Pipeline
      SF[Step Functions<br/>Pipeline Orchestrator]
      L_FEAT[Lambda<br/>Feature Extraction]
      SM_ALIGN[(SageMaker<br/>Forced Alignment)]
      SM_PHON[(SageMaker<br/>Phoneme Classification)]
      SM_FLU[(SageMaker<br/>Fluency Detection)]
      SM_VQ[(SageMaker<br/>Voice Quality)]
      TS_MED[Transcribe Medical<br/>(connected speech)]
      L_SCORE[Lambda<br/>Per-Instrument<br/>Scoring]
      L_NORM[Lambda<br/>Norm-Referenced<br/>Comparison]
      L_LONG[Lambda<br/>Longitudinal<br/>Comparison]
      L_DOC[Lambda<br/>Documentation<br/>Generation]
      BR[Bedrock<br/>Report Generation]
      BR_GR[Bedrock<br/>Guardrails]
    end

    subgraph Storage
      S3_FEAT[(S3 Feature Vectors<br/>SSE-KMS)]
      DDB_LONG[(DynamoDB<br/>Longitudinal Store)]
      HL[HealthLake<br/>FHIR Observations<br/>and Goals]
      S3_REPORT[(S3 Report Archive<br/>SSE-KMS)]
      S3_AUDIT[(S3 Audit Archive<br/>Object Lock)]
    end

    subgraph Workflow
      APIGW_OUT[API Gateway<br/>SLP and Patient APIs]
      COGNITO[Cognito or<br/>Institutional IdP]
      EHR[EHR or SIS<br/>Integration]
      SLP_UI[SLP Review and<br/>Edit Interface]
      PATIENT_UI[Patient/Parent<br/>Home-Practice App]
      DASH[Practice<br/>Dashboard]
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
      SM_SEC[(Secrets Manager<br/>EHR/SIS Creds)]
    end

    SLP --> SETUP
    SETUP --> QA
    QA --> APIGW_IN
    APIGW_IN --> L_INGEST
    L_INGEST --> S3_AUDIO
    S3_AUDIO --> SF
    SF --> L_FEAT
    L_FEAT --> SM_ALIGN
    L_FEAT --> SM_PHON
    L_FEAT --> SM_FLU
    L_FEAT --> SM_VQ
    L_FEAT --> TS_MED
    L_FEAT --> S3_FEAT
    SF --> L_SCORE
    L_SCORE --> L_NORM
    L_NORM --> L_LONG
    L_LONG --> DDB_LONG
    L_LONG --> L_DOC
    L_DOC --> BR
    BR --> BR_GR
    L_DOC --> S3_REPORT
    L_DOC --> HL
    L_DOC --> APIGW_OUT
    APIGW_OUT --> COGNITO
    APIGW_OUT --> SLP_UI
    APIGW_OUT --> PATIENT_UI
    APIGW_OUT --> DASH
    APIGW_OUT --> EHR
    EHR --> SM_SEC
    SF --> EB
    L_DOC --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    SM_ALIGN --> MM
    SM_PHON --> MM
    SM_FLU --> MM
    SM_VQ --> MM
    MM --> CLAR
    SF --> CW
    APIGW_OUT --> CT
    KMS --> S3_AUDIO
    KMS --> S3_FEAT
    KMS --> S3_REPORT
    KMS --> S3_AUDIT
    KMS --> DDB_LONG
    KMS --> SM_SEC

    style SM_ALIGN fill:#fcf,stroke:#333
    style SM_PHON fill:#fcf,stroke:#333
    style SM_FLU fill:#fcf,stroke:#333
    style SM_VQ fill:#fcf,stroke:#333
    style TS_MED fill:#fcf,stroke:#333
    style BR fill:#fcf,stroke:#333
    style BR_GR fill:#fcf,stroke:#333
    style MM fill:#fcf,stroke:#333
    style CLAR fill:#fcf,stroke:#333
    style DDB_LONG fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_FEAT fill:#cfc,stroke:#333
    style S3_REPORT fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
    style HL fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon S3, Amazon SageMaker (real-time and asynchronous endpoints, Model Monitor, Clarify), AWS Lambda, AWS Step Functions, Amazon Transcribe Medical, Amazon Bedrock (with Guardrails), AWS HealthLake, Amazon DynamoDB, Amazon API Gateway, Amazon Cognito, AWS KMS, AWS Secrets Manager, Amazon EventBridge, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally Amazon QuickSight for dashboards. |
| **Validated Models** | Disordered-speech-aware acoustic models per target population (pediatric articulation, adult dysarthria, fluency, voice quality). For most institutions this means selecting commercial vendors with appropriate validation evidence rather than building from scratch. Building requires multi-year clinical-research validation studies, IRB-approved cohort development, and SLP-graded labeled data. The architecture supports either pattern: third-party model integration through SageMaker endpoint or vendor API; institutionally-built models hosted on SageMaker endpoints.  |
| **External Inputs** | Stimulus sets per assessment instrument (Goldman-Fristoe-aligned, Hodson-aligned, SSI-aligned, CAPE-V protocols, etc.); these are typically licensed from the assessment-instrument publishers. Population norms per age band, sex, and language background. SLP-labeled validation data per assessment instrument and per population. EHR or SIS write surface for assessment results. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The session-ingest Lambda has S3 write to the audio bucket only and Step Functions or EventBridge publish for the pipeline trigger. The feature-extraction Lambda has S3 read on the audio bucket and write on the feature bucket plus Transcribe Medical permissions and SageMaker invoke-endpoint for the alignment, phoneme-classification, fluency-detection, and voice-quality endpoints. The scoring Lambda has DynamoDB read access to norms tables and write access to per-session scoring tables. The documentation Lambda has Bedrock invoke-model permissions, S3 write to the report archive, and HealthLake write permissions. The EHR or SIS integration Lambda has Secrets Manager access for credentials and the system-specific egress. Avoid wildcard actions and resources in production.  |
| **BAA and Compliance** | AWS BAA signed. Amazon S3, SageMaker, Lambda, Step Functions, Transcribe Medical, Bedrock (verify the specific models and regions covered), HealthLake, DynamoDB, API Gateway, Cognito, KMS, Secrets Manager, EventBridge, CloudWatch Logs, CloudTrail, Kinesis Firehose, Glue, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference).  Voice samples are biometric data; biometric-data law (Illinois BIPA, Texas, Washington) applies in addition to HIPAA where the patient's jurisdiction triggers it. School deployments add FERPA considerations. Pediatric deployments add COPPA considerations for any direct-to-child interface elements. SaMD regulatory consideration for any model that produces autonomous diagnostic claims; pre-deployment FDA strategy review for indications where a SaMD pathway is relevant. IRB or institutional review for research-track deployments and for cohort-development data collection. |
| **Encryption** | Audio samples: SSE-KMS with customer-managed keys, retention bound to the consent terms (typically days to weeks for active therapy support, optionally longer with explicit consent). Feature vectors: SSE-KMS with separate customer-managed keys, retention as needed for longitudinal analysis and model improvement. Assessment reports and scoring records: SSE-KMS with customer-managed keys, retention aligned with medical-record retention or educational-record retention as applicable. Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, biometric-data law retention requirements, FERPA educational-record retention where applicable, state medical-records-retention rules including pediatric-extending-to-age-of-majority-plus-X, and institutional regulatory floor.  DynamoDB tables, HealthLake datastore, Lambda environment variables, and Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all API calls. |
| **VPC** | Production: Lambdas that call back-office APIs (EHR FHIR, SIS systems, patient portal) run in VPC with controlled egress. VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SageMaker Runtime, Transcribe Medical, Bedrock, Lambda. Endpoint policies pin access to the specific resources the pipeline uses. SageMaker endpoints in VPC mode where supported by the chosen container. |
| **CloudTrail** | Enabled with data events on the audio bucket, the feature bucket, the report archive bucket, the audit archive bucket, the DynamoDB tables, the Secrets Manager secrets, and the customer-managed KMS keys. SageMaker invocations logged. Bedrock invocations logged with metadata only (not full input/output, to avoid persisting biometric or PHI content in CloudTrail). Lambda invocations logged. API Gateway access logs enabled. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. |
| **Sample Data** | Public disordered-speech corpora for development and feature-pipeline validation. Examples include the TORGO database (dysarthric speech), the UASpeech corpus (cerebral-palsy-related speech), the FluencyBank corpus (stuttering), the AphasiaBank corpus (post-stroke aphasia), and the LANNA pediatric speech corpus; each has its own access terms that must be reviewed before integration.  Synthetic capture-quality test signals for the audio QA pipeline. Never use uncoded production patient voice samples in development without explicit consent and IRB or institutional review. |
| **Cost Estimate** | At a mid-sized SLP practice or hospital outpatient SLP department scale (5,000 assessment sessions per year, mixed across pediatric articulation, adult dysarthria, and fluency assessments): SageMaker endpoint hosting and inference at typically $20,000-80,000 per year depending on real-time vs. asynchronous and instance class. Transcribe Medical at typically $2,000-8,000 per year. Bedrock at typically $1,000-4,000 per year for natural-language report generation. Lambda, Step Functions, S3, DynamoDB, HealthLake, CloudWatch, KMS, Secrets Manager, EventBridge, Kinesis Firehose, Glue, Athena total approximately $8,000-20,000 per year combined. Total AWS infrastructure typically $30,000-110,000 per year at this scale. The per-session cost is dominated by SageMaker model inference. The validation and clinical-evidence costs are typically much larger than the infrastructure costs at this scale.  |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon S3** | Task-segmented audio storage with consent-bounded retention; feature-vector storage; assessment-report PDF archive; audit archive with Object Lock |
| **Amazon SageMaker** | Per-population disordered-speech-aware model hosting (forced alignment, phoneme classification, fluency event detection, voice-quality scoring), real-time and asynchronous endpoints, post-deployment surveillance via Model Monitor and Clarify |
| **Amazon Transcribe Medical** | Connected-speech transcription for linguistic-feature extraction in language-assessment and connected-speech tasks |
| **Amazon Bedrock** | Natural-language assessment-report generation for SLP review; patient-and-parent-friendly summary generation at appropriate reading level |
| **Amazon Bedrock Guardrails** | Content filtering and contextual-grounding checks on patient-and-parent-facing communications |
| **AWS Lambda** | Per-stage orchestration for session ingest, feature extraction, per-instrument scoring, longitudinal comparison, documentation generation, EHR/SIS write |
| **AWS Step Functions** | Pipeline orchestration with Map state for per-stimulus parallel processing, durable state, retry semantics |
| **AWS HealthLake** | FHIR-based assessment Observation, Goal, and CarePlan resource storage with longitudinal-trajectory queries |
| **Amazon DynamoDB** | Per-patient longitudinal feature history, per-goal progress trajectories, per-target-sound mastery curves, per-session state |
| **Amazon API Gateway** | SLP-facing assessment-and-review API; patient-and-parent-facing home-practice API; administrative dashboard API |
| **Amazon Cognito** | SLP, patient, and parent authentication federated through institutional IdP with appropriate per-role scopes |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing and biometric-bearing data stores; separate keys per data class for blast-radius containment |
| **AWS Secrets Manager** | EHR, SIS, and external-vendor API credentials with rotation |
| **Amazon EventBridge** | Cross-system event flow for session, scoring, review, and report-delivery events |
| **Amazon CloudWatch** | Operational metrics, per-population drift alarms, SLP-override-rate alarms, indeterminate-result-rate alarms |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing and biometric-bearing resources and AI/ML service invocations |
| **Amazon Kinesis Data Firehose** | Streaming audit and surveillance data into the audit archive |
| **AWS Glue + Amazon Athena** | SQL access to audit and surveillance data for operational and clinical-quality analytics |
| **Amazon QuickSight (optional)** | SLP-facing caseload dashboards and practice-leadership outcomes dashboards |

---

### Code

#### Walkthrough

**Step 1: Set up the assessment session with the SLP-selected instruments, stimuli, and patient context.** When the SLP initiates an assessment, the system records which assessment instruments she has selected, generates the per-instrument stimulus list, captures patient context (age, language background, prior assessment history, current goals), and records the consent terms. Skip any of these and the resulting audio cannot be reliably scored: the system does not know which phonemes to expect, which norms to apply, or whether the SLP has the authorization to capture the audio.

```pseudocode
ON session_initiated(slp_id, patient_id, selected_instruments,
                     deployment_context):

    // Step 1A: load patient context.
    patient_context = patient_table.get(patient_id)
    // patient_context includes age (derived from DOB),
    // primary language, dialect, prior assessment
    // history reference, current active therapy goals,
    // and patient-specific stimulus customizations.

    IF patient_context IS NULL:
        // Patient must be registered before assessment.
        RETURN { status: "PATIENT_NOT_FOUND" }

    // Step 1B: validate instrument applicability for
    // patient profile.
    applicable_instruments = []
    FOR instrument IN selected_instruments:
        instrument_def = lookup_instrument_definition(
            instrument_id: instrument)
        applicability = check_instrument_applicability(
            patient_context: patient_context,
            instrument_validation_envelope:
                instrument_def.validation_envelope)
        IF applicability.applicable:
            applicable_instruments.append({
                instrument_id: instrument,
                stimulus_list: customize_stimuli(
                    instrument_def.stimulus_list,
                    patient_context.stimulus_customizations),
                norm_reference: select_norm_reference(
                    instrument_def.available_norms,
                    patient_context.age,
                    patient_context.sex,
                    patient_context.primary_language)
            })
        ELSE:
            log_instrument_inapplicable(
                slp_id, patient_id, instrument,
                applicability.reason)

    IF len(applicable_instruments) == 0:
        RETURN { status: "NO_APPLICABLE_INSTRUMENTS" }

    // Step 1C: capture consent.
    // For minors, the parent or guardian provides
    // consent and the child provides developmentally-
    // appropriate assent. School deployments include
    // FERPA-aligned consent.
    consent_outcome = capture_consent(
        patient_id: patient_id,
        consent_type: "speech_therapy_assessment",
        deployment_context: deployment_context,
        // School deployments use FERPA-aligned consent;
        // clinic deployments use HIPAA-aligned consent;
        // both jurisdictions when applicable.
        applicable_frameworks:
            determine_consent_frameworks(
                patient_context, deployment_context),
        retention_terms: institutional_retention_policy,
        is_minor: patient_context.is_minor)

    IF NOT consent_outcome.granted:
        log_consent_decline(patient_id, consent_outcome)
        RETURN { status: "CONSENT_DECLINED" }

    // Step 1D: bootstrap the session record.
    session_id = generate_uuid()
    session_table.put({
        session_id: session_id,
        patient_id_hash: hash(patient_id),
        slp_id: slp_id,
        deployment_context: deployment_context,
        applicable_instruments: applicable_instruments,
        consent_id: consent_outcome.consent_id,
        prior_session_ref:
            lookup_most_recent_session(patient_id),
        active_goals:
            lookup_active_goals(patient_id),
        started_at: now(),
        status: "setup_complete"
    })

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_setup_complete",
        detail: {
            session_id: session_id,
            instrument_count: len(applicable_instruments)
        }
    }])

    RETURN {
        session_id: session_id,
        instruments: applicable_instruments,
        status: "READY_TO_CAPTURE"
    }
```

**Step 2: Capture audio per task with task-aware quality assessment and recapture prompts on failure.** Each instrument has its own task structure: articulation inventories elicit one stimulus at a time, fluency probes capture continuous speech segments, voice-quality tasks elicit sustained vowels. The capture system handles each task type appropriately, runs quality checks, and prompts for recapture on failure. Skip the per-task quality gating and the system silently scores low-quality audio, producing unreliable results that the SLP has to manually override.

```pseudocode
FUNCTION capture_session_audio(session_id):
    state = session_table.get(session_id)
    captured_tasks = []

    FOR instrument IN state.applicable_instruments:
        FOR task IN instrument.stimulus_list:
            // Step 2A: present stimulus to patient.
            // The presentation may be a picture, a
            // recorded prompt, a written word, or an
            // SLP-spoken cue depending on instrument
            // and task.
            present_stimulus(task)

            // Step 2B: capture audio with task-aware
            // configuration.
            captured_audio =
                capture_audio_with_task_quality(
                    expected_duration_range:
                        task.expected_duration,
                    expected_speaker: "patient_only",
                    quality_thresholds:
                        task.quality_thresholds,
                    max_retries: task.max_retries,
                    recapture_prompt:
                        task.recapture_prompt_text)

            IF captured_audio.quality_score <
               task.minimum_quality:
                IF task.required:
                    log_capture_failure(
                        session_id, task, captured_audio)
                    RETURN {
                        status: "INSUFFICIENT_QUALITY",
                        failed_task: task.task_id
                    }
                ELSE:
                    // Optional task with insufficient
                    // quality is skipped; instrument
                    // scoring will mark the affected
                    // items as unscorable.
                    log_optional_task_skipped(
                        session_id, task, captured_audio)
                    CONTINUE

            captured_tasks.append({
                instrument_id: instrument.instrument_id,
                task_id: task.task_id,
                expected_target: task.expected_target,
                audio_ref: captured_audio.s3_uri,
                duration_seconds: captured_audio.duration,
                quality_score: captured_audio.quality_score,
                sample_rate: captured_audio.sample_rate,
                codec: captured_audio.codec,
                snr_db: captured_audio.snr_db,
                clipping_detected: captured_audio.clipping,
                speaker_only_verified:
                    captured_audio.speaker_only_verified
            })

    // Step 2C: persist captured tasks and emit pipeline
    // trigger.
    session_table.update(
        session_id: session_id,
        captured_tasks: captured_tasks,
        capture_completed_at: now(),
        status: "captured")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_captured",
        detail: {
            session_id: session_id,
            task_count: len(captured_tasks)
        }
    }])

    RETURN {
        session_id: session_id,
        status: "CAPTURED"
    }
```

**Step 3: Extract acoustic, phonetic, and linguistic features per task, with disordered-speech-tolerant alignment and confidence scoring.** Each task is processed through the appropriate feature pipeline: articulation tasks run through forced alignment and phoneme classification with substitution and omission detection; fluency tasks run through fluency-event detection; voice-quality tasks run through acoustic-feature extraction; connected-speech tasks add transcription and linguistic-feature extraction. Per-feature confidence is captured throughout. Skip the disordered-speech-tolerant configurations and the alignment fails on the population the system is meant to serve.

```pseudocode
FUNCTION extract_features(session_id):
    state = session_table.get(session_id)
    feature_set = {
        session_id: session_id,
        per_task_features: {}
    }

    FOR captured_task IN state.captured_tasks:
        instrument_id = captured_task.instrument_id
        task_id = captured_task.task_id
        instrument_def = lookup_instrument_definition(
            instrument_id)
        task_def = lookup_task_definition(
            instrument_id, task_id)

        per_task = { task_id: task_id }

        // Step 3A: forced alignment.
        // Disordered-speech-aware alignment models are
        // selected based on patient population profile.
        alignment_endpoint = select_alignment_endpoint(
            patient_population:
                state.patient_population_profile,
            task_type: task_def.task_type)

        alignment_result = sagemaker_runtime.invoke_endpoint(
            endpoint_name: alignment_endpoint,
            content_type: "application/json",
            body: serialize({
                audio_ref: captured_task.audio_ref,
                expected_target:
                    captured_task.expected_target,
                language: state.patient_context.primary_language
            }))
        per_task.alignment = parse_alignment(
            alignment_result)

        // Step 3B: phoneme classification with
        // substitution, omission, and distortion
        // detection (for articulation tasks).
        IF task_def.task_type IN
                ["single_word_articulation",
                 "phonological_pattern_probe",
                 "diadochokinetic_rate"]:
            phoneme_endpoint =
                select_phoneme_endpoint(
                    patient_population:
                        state.patient_population_profile)
            phoneme_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: phoneme_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref,
                        alignment: per_task.alignment,
                        expected_phonemes:
                            task_def.expected_phonemes
                    }))
            per_task.phoneme_classification =
                parse_phoneme_classification(
                    phoneme_result)
            // Per-phoneme confidence captured for SLP-
            // review flagging at scoring step.

        // Step 3C: fluency event detection (for
        // fluency tasks).
        IF task_def.task_type IN
                ["fluency_probe_reading",
                 "fluency_probe_conversation",
                 "fluency_probe_picture_description"]:
            fluency_endpoint =
                select_fluency_endpoint()
            fluency_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: fluency_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref
                    }))
            per_task.fluency_events =
                parse_fluency_events(fluency_result)

        // Step 3D: voice-quality acoustic features
        // (for voice-quality tasks and any
        // sustained-vowel tasks).
        IF task_def.captures_voice_quality:
            vq_endpoint = select_voice_quality_endpoint()
            vq_result =
                sagemaker_runtime.invoke_endpoint(
                    endpoint_name: vq_endpoint,
                    content_type: "application/json",
                    body: serialize({
                        audio_ref: captured_task.audio_ref
                    }))
            per_task.voice_quality =
                parse_voice_quality(vq_result)

        // Step 3E: prosodic and rate features.
        per_task.prosodic =
            compute_prosodic_features(
                audio_ref: captured_task.audio_ref,
                alignment: per_task.alignment)

        // Step 3F: linguistic features for
        // connected-speech tasks.
        IF task_def.task_type IN
                ["connected_speech_story_retell",
                 "connected_speech_picture_description",
                 "connected_speech_conversation"]:
            transcript_job =
                transcribe_medical.start_job(
                    audio_ref: captured_task.audio_ref,
                    language:
                        state.patient_context.primary_language,
                    show_speaker_labels: false)
            // Note: in production, the transcribe job
            // should be handled asynchronously via
            // Step Functions wait-for-callback rather
            // than blocking inside this Lambda.
            // TODO (TechWriter): Expert review A7 (MEDIUM).
            // Decompose this step into two Step Functions
            // states: Lambda-invokes-start_job-and-returns,
            // then Step Functions waits for the Transcribe
            // job-completion event (or polls with backoff),
            // then a separate Lambda step retrieves the
            // transcript and runs extract_linguistic_features.
            // Update the architecture diagram to show the
            // two-step decomposition and remove the
            // synchronous wait inside the feature-extraction
            // Lambda.
            wait_for_transcribe(transcript_job.job_name)
            transcript_text = retrieve_transcript(
                transcript_job.job_name)

            per_task.transcript = transcript_text
            per_task.linguistic_features =
                extract_linguistic_features(
                    transcript: transcript_text,
                    patient_age: state.patient_context.age,
                    requested_features:
                        task_def.linguistic_features)

        feature_set.per_task_features[task_id] = per_task

    // Step 3G: persist features.
    feature_set_archive.put(
        session_id: session_id,
        feature_set: feature_set)

    session_table.update(
        session_id: session_id,
        feature_set_archive_ref:
            f"s3://{FEATURE_BUCKET}/{session_id}/features.json",
        features_extracted_at: now(),
        status: "features_extracted")

    RETURN {
        feature_set_ref:
            session_table.get(session_id).feature_set_archive_ref
    }
```

**Step 4: Score each instrument with population-norm comparison and per-item confidence-based SLP-review flagging.** For each assessment instrument, the scoring engine combines per-task features into instrument-aligned scores (percent-consonants-correct for articulation, percent-syllables-stuttered for fluency, CAPE-V dimensions for voice quality, and so on). Items with model confidence below the threshold are flagged for SLP review rather than auto-scored. Population norms are applied to interpret the raw scores against age-and-sex-appropriate benchmarks. Skip the confidence-based flagging and the system silently misclassifies the items where it is uncertain, producing systematic errors that erode SLP trust.

```pseudocode
FUNCTION score_instruments(session_id):
    state = session_table.get(session_id)
    feature_set = feature_set_archive.get(session_id)
    scores = {}

    FOR instrument IN state.applicable_instruments:
        instrument_def = lookup_instrument_definition(
            instrument.instrument_id)
        instrument_features = collect_features_for_instrument(
            feature_set, instrument)

        // Step 4A: per-item scoring with confidence.
        per_item_scores = []
        FOR item IN instrument_def.scoring_items:
            item_features = extract_item_features(
                instrument_features, item)
            item_score_result = score_item(
                item: item,
                features: item_features,
                scoring_rubric:
                    instrument_def.scoring_rubric)

            per_item_scores.append({
                item_id: item.item_id,
                expected_target: item.expected_target,
                observed:
                    item_score_result.observed,
                score_value:
                    item_score_result.score_value,
                model_confidence:
                    item_score_result.confidence,
                slp_review_flag:
                    item_score_result.confidence <
                    instrument_def.confidence_threshold,
                supporting_evidence:
                    item_score_result.evidence
            })

        // Step 4B: aggregate per-instrument summary
        // scores from auto-scored items and SLP-review-
        // pending items. Items pending SLP review are
        // excluded from the auto-summary; the final
        // summary is computed after SLP review.
        auto_scored_items = [
            i FOR i IN per_item_scores
            IF NOT i.slp_review_flag
        ]
        review_pending_items = [
            i FOR i IN per_item_scores
            IF i.slp_review_flag
        ]
        auto_summary = compute_instrument_summary(
            summary_method:
                instrument_def.summary_method,
            items: auto_scored_items)

        // Step 4C: norm-referenced comparison.
        // The norm reference was selected at session
        // setup; here we apply it to the auto-summary.
        norm_comparison = apply_norms(
            instrument_id: instrument.instrument_id,
            auto_summary: auto_summary,
            norm_reference: instrument.norm_reference)

        // Step 4D: severity classification per
        // instrument-defined cutoffs.
        severity_classification = classify_severity(
            instrument_id: instrument.instrument_id,
            auto_summary: auto_summary,
            norm_comparison: norm_comparison,
            severity_cutoffs:
                instrument_def.severity_cutoffs)

        // Step 4E: phonological-pattern detection
        // (specifically for articulation instruments).
        phonological_patterns = NULL
        IF instrument_def.detects_phonological_patterns:
            phonological_patterns =
                detect_phonological_patterns(
                    per_item_scores: per_item_scores,
                    pattern_definitions:
                        instrument_def.pattern_definitions,
                    patient_age:
                        state.patient_context.age)

        scores[instrument.instrument_id] = {
            per_item_scores: per_item_scores,
            review_pending_count:
                len(review_pending_items),
            auto_summary: auto_summary,
            norm_comparison: norm_comparison,
            severity_classification:
                severity_classification,
            phonological_patterns:
                phonological_patterns,
            norm_reference_used:
                instrument.norm_reference.reference_id,
            scoring_model_versions:
                feature_set.model_versions,
            scored_at: now()
        }

    session_table.update(
        session_id: session_id,
        instrument_scores: scores,
        scoring_completed_at: now(),
        status: "scored")

    // TODO (TechWriter): Expert review S2 (HIGH). Adopt
    // archive-reference discipline uniformly. Per-instrument
    // score content (per_item_scores with per-phoneme
    // expected_target / observed / score_value /
    // supporting_evidence) is biometric-derived data
    // classified as PHI; write the full instrument_scores
    // structure to a per-session score-archive S3 bucket
    // with the biometric-derived KMS key class and persist
    // only the archive ref plus structural metadata in the
    // session_table. Apply the same pattern to the Step 5D
    // longitudinal / goal_progress / trajectory_patterns
    // writes and the Step 6C edited_scores / final_summaries
    // / edit_history (with free-text slp_reasoning) /
    // clinical_record (with free-text free_text_observations)
    // writes. Classify the longitudinal_table as a biometric-
    // derived data store with the pediatric-records-
    // extending-to-age-of-majority retention floor per
    // Finding S1.
    RETURN scores
```

**Step 5: Compute longitudinal comparison against the patient's prior sessions and against the active therapy goals.** Within-patient progress is the clinically richest signal. The system computes per-instrument deltas against the prior session and trend lines across all prior sessions, evaluates progress against each active therapy goal, and detects trajectory patterns (plateau, regression, acceleration). Skip the longitudinal layer and the SLP loses the comparison that is most useful for therapy-planning decisions.

```pseudocode
FUNCTION compute_longitudinal(session_id):
    state = session_table.get(session_id)
    current_scores = state.instrument_scores
    longitudinal = {}

    // Step 5A: load prior sessions for this patient.
    prior_sessions = longitudinal_table.get_history(
        patient_id_hash: state.patient_id_hash,
        window_months: 24,
        limit: 20)

    // Step 5B: per-instrument longitudinal comparison.
    FOR instrument_id, current IN current_scores:
        prior_for_instrument = [
            s FOR s IN prior_sessions
            IF instrument_id IN s.instrument_scores
        ]
        IF len(prior_for_instrument) == 0:
            longitudinal[instrument_id] = {
                first_assessment: true,
                trajectory: NULL,
                most_recent_delta: NULL
            }
            CONTINUE

        most_recent = prior_for_instrument[0]
        most_recent_delta =
            compute_score_delta(
                current.auto_summary,
                most_recent.instrument_scores
                    [instrument_id].auto_summary,
                instrument_id: instrument_id)

        trajectory_analysis = analyze_trajectory(
            history: prior_for_instrument + [
                {
                    session_id: session_id,
                    timestamp: state.started_at,
                    instrument_scores: current_scores
                }
            ],
            instrument_id: instrument_id,
            within_patient_typical_variation:
                lookup_within_patient_variation(
                    state.patient_id_hash,
                    instrument_id))

        longitudinal[instrument_id] = {
            first_assessment: false,
            trajectory: trajectory_analysis,
            most_recent_delta: most_recent_delta,
            sessions_in_baseline:
                len(prior_for_instrument)
        }

    // Step 5C: per-goal progress evaluation.
    goal_progress = {}
    FOR goal IN state.active_goals:
        progress = evaluate_goal_progress(
            goal: goal,
            current_scores: current_scores,
            goal_evaluation_rubric:
                goal.evaluation_rubric)

        goal_progress[goal.goal_id] = {
            goal_text: goal.goal_text,
            target_metric: goal.target_metric,
            current_value: progress.current_value,
            baseline_value: goal.baseline_value,
            target_value: goal.target_value,
            percent_progress: progress.percent_progress,
            on_track: progress.on_track,
            recommended_action: progress.recommended_action
        }

    // Step 5D: trajectory pattern detection across
    // instruments and goals.
    trajectory_patterns = detect_trajectory_patterns(
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        pattern_thresholds: TRAJECTORY_PATTERN_THRESHOLDS)
    // trajectory_patterns may include flags such as
    // "plateau_across_multiple_instruments,"
    // "regression_in_specific_target_sounds,"
    // "acceleration_post_intervention_change," etc.

    session_table.update(
        session_id: session_id,
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        trajectory_patterns: trajectory_patterns,
        longitudinal_completed_at: now(),
        status: "longitudinal_computed")

    RETURN {
        longitudinal: longitudinal,
        goal_progress: goal_progress,
        trajectory_patterns: trajectory_patterns
    }
```

**Step 6: Hand off to the SLP for review, override, and clinical interpretation.** The SLP-facing review interface presents the per-item scores with confidence values, highlights items flagged for review, supports audio playback for any item, and shows the longitudinal comparison alongside. The SLP can override individual item scores with a reasoning capture, accept high-confidence items in bulk, add free-text observations, and provide the clinical interpretation (working diagnosis, goal modifications, recommended therapy frequency, discharge readiness assessment). Skip the SLP-in-the-loop step and the system ships uncertain items as confident-looking auto-scores and loses the feedback signal for ongoing model improvement.

```pseudocode
ON slp_review_initiated(session_id, slp_id):
    state = session_table.get(session_id)

    // Step 6A: build the SLP-facing review package.
    review_package = build_slp_review_package(
        session_id: session_id,
        instrument_scores: state.instrument_scores,
        longitudinal: state.longitudinal,
        goal_progress: state.goal_progress,
        trajectory_patterns: state.trajectory_patterns,
        captured_tasks: state.captured_tasks)

    // Per-item review prioritization: SLP-review-
    // flagged items appear first.

    session_table.update(
        session_id: session_id,
        slp_review_initiated_at: now(),
        reviewing_slp_id: slp_id,
        status: "slp_reviewing")

    RETURN review_package

ON slp_submits_review(session_id, slp_id, edits,
                      clinical_interpretation):
    state = session_table.get(session_id)

    // Step 6B: apply the SLP's per-item edits.
    edited_scores = state.instrument_scores
    edit_history = []
    FOR edit IN edits:
        original_value = lookup_item_score(
            edited_scores,
            edit.instrument_id,
            edit.item_id)
        apply_item_edit(edited_scores, edit)
        edit_history.append({
            instrument_id: edit.instrument_id,
            item_id: edit.item_id,
            original_value: original_value,
            new_value: edit.new_value,
            slp_reasoning: edit.reasoning,
            edited_by: slp_id,
            edited_at: now()
        })

    // Step 6C: recompute per-instrument summaries
    // including all items (auto-scored plus SLP-
    // edited).
    final_summaries = {}
    FOR instrument_id, scores IN edited_scores:
        instrument_def = lookup_instrument_definition(
            instrument_id)
        final_summary = compute_instrument_summary(
            summary_method:
                instrument_def.summary_method,
            items: scores.per_item_scores)
        final_norm_comparison = apply_norms(
            instrument_id: instrument_id,
            auto_summary: final_summary,
            norm_reference: scores.norm_reference_used)
        final_severity = classify_severity(
            instrument_id: instrument_id,
            auto_summary: final_summary,
            norm_comparison: final_norm_comparison,
            severity_cutoffs:
                instrument_def.severity_cutoffs)
        final_summaries[instrument_id] = {
            final_summary: final_summary,
            final_norm_comparison: final_norm_comparison,
            final_severity: final_severity
        }

    // Step 6D: capture the clinical interpretation.
    clinical_record = {
        working_diagnosis_or_hypothesis:
            clinical_interpretation.diagnosis,
        goal_modifications:
            clinical_interpretation.goal_modifications,
        new_goals:
            clinical_interpretation.new_goals,
        recommended_therapy_frequency:
            clinical_interpretation.therapy_frequency,
        recommended_therapy_modality:
            clinical_interpretation.therapy_modality,
        discharge_readiness:
            clinical_interpretation.discharge_readiness,
        free_text_observations:
            clinical_interpretation.observations,
        finalized_by_slp: slp_id,
        finalized_at: now()
    }

    session_table.update(
        session_id: session_id,
        edited_scores: edited_scores,
        final_summaries: final_summaries,
        edit_history: edit_history,
        clinical_record: clinical_record,
        slp_review_completed_at: now(),
        status: "slp_review_complete")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "slp_review_complete",
        detail: {
            session_id: session_id,
            edit_count: len(edit_history)
        }
    }])

    RETURN { status: "REVIEW_COMPLETE" }
```

**Step 7: Generate the assessment-report documentation, the patient-and-parent-friendly summary, and the EHR or SIS write-back.** The system generates a structured assessment report from the SLP-validated scores, the clinical interpretation, and the longitudinal context. It also generates a parent-and-patient-friendly summary at appropriate reading level, with home-practice recommendations. The documentation flows to the EHR (for clinical settings) or the school SIS (for school deployments) as discrete data, FHIR resources, and PDF artifacts. Skip the structured documentation and the SLP loses the productivity benefit; skip the patient-friendly summary and parents and patients are left with clinical-jargon outputs they cannot act on.

```pseudocode
FUNCTION generate_documentation(session_id):
    state = session_table.get(session_id)

    // Step 7A: SLP-facing assessment report.
    slp_report_input = {
        session_metadata: extract_metadata(state),
        instrument_results: state.final_summaries,
        per_item_detail: state.edited_scores,
        longitudinal: state.longitudinal,
        goal_progress: state.goal_progress,
        clinical_record: state.clinical_record,
        edit_history: state.edit_history
    }

    slp_report = bedrock.invoke_model(
        model_id: REPORT_GENERATION_MODEL,
        prompt: build_report_prompt(
            input: slp_report_input,
            template: SLP_REPORT_TEMPLATE,
            // Style guide: structured, profession-
            // standard SLP assessment-report format
            // (history, instruments-administered,
            // results-by-instrument, clinical-impressions,
            // goals-and-recommendations).
            ),
        guardrail_id: REPORT_GUARDRAIL_ID,
        response_format: {
            type: "json_schema",
            schema: SLP_REPORT_SCHEMA
        },
        max_tokens: 3000)

    // TODO (TechWriter): Expert review S5 (MEDIUM) and
    // A2 (MEDIUM). Add prompt-injection mitigation and
    // a faithfulness check between Bedrock generation
    // and documentation persistence. Delimit patient-
    // speech content, SLP free-text content
    // (clinical_record, edit_history with slp_reasoning),
    // and structured scoring output in the prompt with
    // explicit tags (<patient_speech>, <slp_clinical_text>)
    // and instruct the model to treat all delimited
    // content as untrusted source material to be
    // summarized, not as instructions. Add a
    // run_report_faithfulness_check that validates the
    // output against the structured scoring data with
    // citation grounding, schema validation, contradiction
    // detection, and (for family-summary) reading-level
    // validation. On block, fall back to
    // render_structured_report. Track per-population
    // faithfulness-failure-rate as a launch gate per A1.

    // Step 7B: parent-and-patient-friendly summary.
    family_summary_input = {
        session_metadata: extract_metadata(state),
        instrument_results_simplified:
            simplify_for_family(state.final_summaries),
        progress_highlights:
            extract_progress_highlights(
                state.goal_progress),
        home_practice_recommendations:
            derive_home_practice(state.clinical_record),
        target_reading_level:
            determine_reading_level_for_family(
                state.patient_context)
    }

    family_summary = bedrock.invoke_model(
        model_id: SUMMARY_GENERATION_MODEL,
        prompt: build_family_summary_prompt(
            input: family_summary_input,
            template: FAMILY_SUMMARY_TEMPLATE),
        guardrail_id: FAMILY_COMMUNICATION_GUARDRAIL,
        response_format: {
            type: "json_schema",
            schema: FAMILY_SUMMARY_SCHEMA
        },
        max_tokens: 800)

    // Step 7C: assemble structured FHIR resources.
    fhir_resources = build_fhir_resources(
        observation_per_instrument:
            state.final_summaries,
        goal_resources:
            state.clinical_record.new_goals +
            state.clinical_record.goal_modifications,
        document_reference_for_report: slp_report,
        patient_id:
            lookup_patient_id(state.patient_id_hash))

    // Step 7D: persist artifacts.
    report_archive.put(
        session_id: session_id,
        slp_report: slp_report,
        family_summary: family_summary,
        fhir_resources: fhir_resources,
        archived_at: now())

    // Step 7E: write to EHR or SIS as appropriate.
    IF state.deployment_context.documentation_target ==
       "fhir_ehr":
        FOR resource IN fhir_resources:
            healthlake_client.create_resource(
                resource_type: resource.resource_type,
                resource: resource.body)
    // TODO (TechWriter): Expert review A3 (MEDIUM). Specify
    // per-resource-type idempotency key for HealthLake FHIR
    // write-back: Observation (session_id, instrument_id);
    // Goal (session_id, goal_id, modification_type);
    // CarePlan (session_id, careplan_revision);
    // DocumentReference (session_id, document_type). Hold
    // a recently-submitted-writes list per patient and
    // return prior resource_id on idempotency-match. Use
    // FHIR conditional-create (If-None-Exist) where
    // HealthLake supports it.
    ELIF state.deployment_context.documentation_target ==
         "school_sis":
            sis_integration.write_assessment(
                student_id: state.patient_context.student_id,
                assessment_record:
                    convert_to_sis_format(
                        slp_report, fhir_resources),
                iep_alignment:
                    state.deployment_context.iep_context)
    ELSE:
        // Standalone deployment; PDF and structured
        // export delivered through the result API.
        PASS

    session_table.update(
        session_id: session_id,
        slp_report_ref: report_archive.get_ref(
            session_id, "slp_report"),
        family_summary_ref: report_archive.get_ref(
            session_id, "family_summary"),
        documentation_completed_at: now(),
        status: "documented")

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "documentation_complete",
        detail: { session_id: session_id }
    }])

    RETURN {
        slp_report_ref: state.slp_report_ref,
        family_summary_ref: state.family_summary_ref
    }
```

**Step 8: Audit, retain audio per consent, and feed post-deployment surveillance.** Every session produces a durable audit record with the SLP's edits, the per-item confidence values, the model versions used, and the linked patient outcomes where available. Audio is retained per the consent terms and then deleted; feature vectors are retained longer for model improvement and longitudinal analysis. Per-population surveillance metrics feed the dashboards that track the system's performance against SLP gold-standard scoring over time. Skip the surveillance pipeline and per-population drift surfaces only through SLP complaints.

```pseudocode
FUNCTION audit_and_surveillance(session_id):
    state = session_table.get(session_id)

    audit_record = {
        session_id: session_id,
        patient_id_hash: state.patient_id_hash,
        patient_population_profile:
            state.patient_population_profile,
        slp_id: state.reviewing_slp_id,
        deployment_context: state.deployment_context,
        captured_at: state.started_at,
        slp_review_completed_at:
            state.slp_review_completed_at,
        documentation_completed_at:
            state.documentation_completed_at,
        instruments_administered:
            list(state.final_summaries.keys()),
        per_instrument_outcomes: {
            instrument_id: {
                final_severity: summary.final_severity,
                norm_reference_used:
                    state.instrument_scores
                        [instrument_id].norm_reference_used,
                review_pending_count_pre_slp:
                    state.instrument_scores
                        [instrument_id].review_pending_count,
                slp_edit_count_for_instrument:
                    count_edits_for_instrument(
                        state.edit_history, instrument_id),
                model_versions:
                    state.instrument_scores
                        [instrument_id].scoring_model_versions
            }
            FOR instrument_id, summary IN
                state.final_summaries
        },
        goal_progress_summary:
            summarize_goal_progress(state.goal_progress),
        consent_id: state.consent_id
    }

    audit_archive_kinesis_firehose.put(audit_record)

    // Step 8A: schedule audio deletion per consent
    // terms.
    schedule_audio_deletion(
        audio_refs: [
            t.audio_ref FOR t IN state.captured_tasks
        ],
        delete_after: lookup_audio_retention(
            consent_id: state.consent_id,
            deployment_context: state.deployment_context))

    // Step 8B: per-population surveillance metrics.
    FOR instrument_id, outcome IN
            audit_record.per_instrument_outcomes:
        cloudwatch.put_metric(
            namespace: "SpeechTherapyAssessment",
            metric_name: "SLPEditRate",
            value: outcome.slp_edit_count_for_instrument,
            dimensions: {
                instrument_id: instrument_id,
                population_profile:
                    audit_record.patient_population_profile,
                deployment_context:
                    audit_record.deployment_context.context_type
            })
        cloudwatch.put_metric(
            namespace: "SpeechTherapyAssessment",
            metric_name: "ReviewPendingRate",
            value: outcome.review_pending_count_pre_slp,
            dimensions: {
                instrument_id: instrument_id,
                population_profile:
                    audit_record.patient_population_profile
            })

    // TODO (TechWriter): Expert review A1 (HIGH). Promote
    // per-population accuracy monitoring with launch-gate
    // discipline from prose to architectural primitive.
    // Specify single-axis populations (age-band, sex,
    // language, dialect, deployment-context, severity-band,
    // instrument, clinical-population) and two-axis
    // populations (language-by-age-band, severity-by-
    // instrument, deployment-context-by-population, dialect-
    // by-instrument). Specify per-population minimum sample
    // size (typically N=100+ over the monitoring window),
    // per-population threshold metrics (per-item agreement
    // with SLP gold-standard, SLP-review-flag rate, SLP edit
    // rate, cross-population generalization gap, sustained-
    // utilization rate, per-instrument score-distribution
    // drift), launch-gate logic (every population must meet
    // its threshold; institution-wide average is
    // informational only), and a population-disabled-feature
    // workflow when a population drifts below threshold.
    // Tighter thresholds for severe-impairment and pediatric
    // populations per the recipe's own central-trap diagnoses.

    // Step 8C: SageMaker Model Monitor and Clarify
    // jobs run on a scheduled cadence against the
    // inference traffic. SLP edit data feeds back as
    // a real-world performance signal alongside the
    // model-monitor metrics.

    // Step 8D: longitudinal-store update with this
    // session's data.
    longitudinal_table.put({
        patient_id_hash: state.patient_id_hash,
        session_id: session_id,
        timestamp: state.started_at,
        instrument_scores: state.final_summaries,
        edited_scores_summary:
            summarize_edited_scores(state.edited_scores),
        goal_progress: state.goal_progress,
        trajectory_patterns: state.trajectory_patterns,
        capture_metadata: extract_capture_metadata(state)
    })

    EventBridge.PutEvents([{
        source: "speech_therapy_assessment",
        detail_type: "session_audited",
        detail: {
            session_id: session_id,
            audited_at: now()
        }
    }])
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.09-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample assessment output (illustrative, synthetic patient):**

```json
{
  "session_id": "sta-7f3c8d2a-1e4b-4a89",
  "patient_id_hash": "p_4e2c8a91...",
  "captured_at": "2026-05-23T10:15:08Z",
  "patient_context": {
    "age_years": 6,
    "sex": "female",
    "primary_language": "en-US",
    "deployment_context": "outpatient_clinic"
  },
  "instruments_administered": [
    "articulation_inventory_gfta_aligned",
    "phonological_pattern_analysis",
    "connected_speech_picture_description"
  ],
  "results": {
    "articulation_inventory_gfta_aligned": {
      "auto_summary": {
        "items_administered": 53,
        "items_correct_auto": 31,
        "items_substituted_auto": 14,
        "items_omitted_auto": 4,
        "items_distorted_auto": 2,
        "items_pending_slp_review": 2,
        "percent_consonants_correct_auto": 0.585
      },
      "post_slp_summary": {
        "items_correct": 32,
        "items_substituted": 14,
        "items_omitted": 4,
        "items_distorted": 3,
        "percent_consonants_correct": 0.604,
        "slp_edits_count": 1
      },
      "norm_comparison": {
        "norm_reference": "gfta3_age_6_0_to_6_5_female",
        "percentile_rank": 12,
        "standard_score": 82,
        "severity_classification": "mild_to_moderate"
      }
    },
    "phonological_pattern_analysis": {
      "patterns_detected": [
        {
          "pattern": "final_consonant_deletion",
          "percent_occurrence": 0.31,
          "age_appropriateness": "atypical_for_age",
          "target_for_therapy": true
        },
        {
          "pattern": "gliding_of_liquids",
          "percent_occurrence": 0.78,
          "age_appropriateness": "typical_for_age",
          "target_for_therapy": false
        },
        {
          "pattern": "stopping_of_fricatives",
          "percent_occurrence": 0.22,
          "age_appropriateness": "atypical_for_age",
          "target_for_therapy": true
        }
      ]
    },
    "connected_speech_picture_description": {
      "duration_seconds": 87,
      "transcript_word_count": 92,
      "intelligibility_estimate": 0.74,
      "linguistic_features": {
        "mean_length_of_utterance_morphemes": 4.8,
        "mean_length_of_utterance_norm_percentile": 35,
        "lexical_diversity_ttr": 0.61,
        "syntactic_complexity_index": 2.3,
        "narrative_structure_score": "complete_with_some_omissions"
      }
    }
  },
  "longitudinal": {
    "prior_session_count": 3,
    "most_recent_prior_session": "2026-02-14T11:00:00Z",
    "deltas": {
      "percent_consonants_correct": {
        "prior": 0.532,
        "current": 0.604,
        "delta": 0.072,
        "interpretation": "improvement_outside_typical_variation"
      },
      "final_consonant_deletion_percent_occurrence": {
        "prior": 0.41,
        "current": 0.31,
        "delta": -0.10,
        "interpretation": "improvement_outside_typical_variation"
      },
      "stopping_of_fricatives_percent_occurrence": {
        "prior": 0.24,
        "current": 0.22,
        "delta": -0.02,
        "interpretation": "stable_within_typical_variation"
      }
    }
  },
  "goal_progress": [
    {
      "goal_text": "Maya will produce final consonants in single words with 80% accuracy",
      "baseline_value": 0.42,
      "current_value": 0.69,
      "target_value": 0.80,
      "percent_progress": 0.71,
      "on_track": true,
      "recommended_action": "continue_current_therapy_plan"
    },
    {
      "goal_text": "Maya will produce /s/, /f/ in initial position with 80% accuracy",
      "baseline_value": 0.55,
      "current_value": 0.78,
      "target_value": 0.80,
      "percent_progress": 0.92,
      "on_track": true,
      "recommended_action": "near_target_consider_generalization_phase"
    }
  ],
  "trajectory_patterns": [
    "improvement_in_targeted_sounds",
    "near_target_attainment_for_one_active_goal"
  ],
  "clinical_record": {
    "working_diagnosis_or_hypothesis": "moderate_phonological_disorder_responding_to_intervention",
    "goal_modifications": [
      {
        "goal_id": "goal_002_initial_fricatives",
        "modification": "advance_to_generalization_phase_in_connected_speech"
      }
    ],
    "recommended_therapy_frequency": "twice_weekly_45_minutes",
    "recommended_therapy_modality": "in_clinic_with_home_practice",
    "discharge_readiness": "not_yet"
  }
}
```

**Performance benchmarks (illustrative; ranges depend heavily on instrument, population, and recording conditions; your mileage will vary):**

| Metric | Pediatric Articulation Scoring | Adult Dysarthria Severity | Stuttering Event Detection | Voice Quality (CAPE-V-aligned) | Connected-Speech Linguistic Features |
|--------|-------------------------------|---------------------------|----------------------------|--------------------------------|---------------------------------------|
| Per-item agreement with SLP gold-standard (typical-speech-trained acoustic model) | 65-75% | 55-70% | 60-72% | 60-72% | N/A (different metric structure) |
| Per-item agreement with SLP gold-standard (disordered-speech-fine-tuned model) | 80-92% | 75-88% | 78-90% | 75-88% | N/A |
| Cross-population generalization (model trained on one age band, applied to another) | 60-78% | 60-78% | 65-80% | 65-80% | 55-72% |
| SLP-review-flag rate (typical clinical population) | 8-18% | 12-22% | 10-20% | 12-22% | 15-25% |
| SLP edit rate (post-flag, indicating false-positive flags) | 25-40% of flagged items | 30-45% | 25-40% | 30-45% | 20-35% |
| Per-session latency (asynchronous endpoint) | 2-5 minutes | 3-7 minutes | 2-5 minutes | 1-3 minutes | 3-8 minutes |
| Per-session AWS infrastructure cost | $0.10-0.25 | $0.15-0.35 | $0.10-0.25 | $0.05-0.15 | $0.15-0.40 |

**Where it struggles:**

- **Severely impaired speech.** As speech impairment severity increases, model performance decreases. The most-impaired patients (severe dysarthria, severe apraxia, severe stuttering) are exactly the population the SLP most needs help with, and they are the population where the system performs worst. Mitigations: severity-stratified validation with explicit per-severity-band performance reporting, lower confidence thresholds (more SLP-review flags) for severe-impairment patients, conservative auto-scoring with deference to the SLP for ambiguous items, no autonomous-scoring deployment for severe-impairment populations until per-severity validation supports it.

- **Cross-dialect and cross-language generalization.** A model trained on General American English does not transfer cleanly to African American English, to Spanish-influenced English, to other regional dialects, or to other languages. Articulation-pattern interpretation depends on the speaker's dialect; what is a "substitution error" in one dialect is a typical realization in another. Mitigations: per-dialect-and-per-language validation, explicit dialect identification at session setup, dialect-aware norm references, conservative classification for out-of-validated-dialect speakers, ongoing dialect coverage expansion.

- **Pediatric-specific challenges.** Pediatric speech is acoustically different from adult speech, pediatric attention spans are shorter (which limits task length), pediatric cooperation varies (the patient might rush through, get distracted, mumble), and pediatric phonology is developmental (a sound that is "wrong" at age 8 may be "developmentally typical" at age 4). Mitigations: pediatric-specific acoustic models, age-appropriate task design, age-specific norms with developmental-appropriateness flags, conservative classification for younger pediatric patients.

- **Pediatric assent and age-appropriate consent.** Older pediatric patients (typically age 7+) provide assent in addition to parent consent; younger patients are bound by parent consent alone. The consent infrastructure has to handle the developmental gradient, the dual-signature requirement for school-and-clinic dual jurisdictions, and the changing-consent-as-the-patient-ages workstream. Mitigations: developmentally-appropriate assent language, robust dual-signature handling, regular consent refresh on developmental milestones.

- **Telepractice audio quality.** Telepractice audio is captured through whatever microphone the patient or family has, in whatever environment they are in, through whatever video-call platform the practice uses. The acoustic features the system measures are sensitive to all of these variables. Mitigations: telepractice-specific recording-quality guidance, telepractice-fine-tuned acoustic models, conservative classification for poor-quality telepractice audio, recapture prompts when audio quality is below threshold.

- **Home-practice context.** Home-practice apps capture audio outside the structured assessment context. Background noise, family member speech, the patient practicing without supervision and possibly incorrectly all contaminate the audio. Mitigations: home-practice-specific quality assessment, speaker-only verification, simpler scoring rubrics for home-practice (target/not-target rather than full instrument scoring), explicit framing as practice rather than assessment.

- **Stimulus-set licensing and IP.** Established assessment instruments are often copyrighted and licensed by their publishers. Building a system that uses a specific instrument requires licensing or a clearly-distinct stimulus set with separate norm validation. Mitigations: licensing agreements with instrument publishers where the system uses copyrighted instruments, institutionally-validated alternative stimulus sets where licensing is not available, transparent disclosure of which instrument is used and any deviations from the published version. 

- **Norm-reference availability and currency.** Population norms are central to the clinical interpretation. Norms vary by age band, sex, language, dialect, and clinical population, and they are updated periodically. Norms for some populations (especially non-English-speaking, multi-dialect, and rare clinical populations) may not exist or may be outdated. Mitigations: explicit norm-reference disclosure on every result, conservative classification when norms are not well-established for the patient profile, ongoing investment in norm development for underserved populations.

- **SLP workflow disruption.** A system that adds friction to the SLP's workflow gets used reluctantly or not at all. Mitigations: SLP-led workflow design, iterative deployment with SLP feedback, integration with the SLP's existing documentation system rather than as a parallel system, productivity measurement that demonstrates time savings rather than time additions.

- **Reimbursement and outcome-tracking integration.** Speech therapy reimbursement is often tied to outcomes documentation that the SLP must produce regardless of the AI tool. Mitigations: outcomes-aligned documentation generation, CPT-code-specific documentation requirements built into the report templates, IEP-aligned formats for school deployments, value-based-contract outcome-measure support.

- **Pediatric data privacy and the long retention horizon.** A six-year-old being assessed today has data that may need to be retained until age 25 or longer depending on state pediatric-records law. The biometric voice samples are part of that long-horizon data. Mitigations: explicit pediatric-records-retention policies, audit-archive infrastructure that supports the long retention floor, explicit deletion-on-request workflow that respects pediatric protections including parent-on-behalf-of-minor and patient-once-of-age requests.

- **The autonomous-scoring temptation.** The most attractive product framing is full-autonomous scoring (the SLP records audio and a complete report drops out the other end). The clinically-defensible framing is SLP-in-the-loop with confidence-based review flags. The marketing-vs-clinical-reality gap is similar to what voice biomarker products face. Mitigations: explicit positioning as SLP augmentation rather than SLP replacement, SLP-review interfaces that make the in-the-loop work efficient, clinical-quality monitoring that demonstrates the SLP-in-the-loop accuracy advantage over autonomous scoring.

- **Deployment-context heterogeneity.** Hospital outpatient SLP, school SLP, private practice SLP, early-intervention SLP, telepractice SLP, and inpatient acute-care SLP have different documentation systems, different reimbursement models, different consent requirements, different population skews, and different clinical-workflow patterns. Mitigations: per-deployment-context configuration, validation evidence per context, dedicated implementation effort per context (not a single deployment that pretends to fit everywhere).

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment for any specific instrument and population needs to close substantial gaps that are out of scope for a recipe.

**Per-instrument-and-per-population validation evidence.** This is the dominant gap. Disordered-speech-aware models for each assessment instrument and each target population (pediatric articulation, adult dysarthria, fluency, voice quality) require validation studies with appropriate cohorts, SLP-graded reference data, and per-population performance evidence. Building this evidence is a multi-year clinical-research undertaking; most institutions should be buying validated commercial models with appropriate evidence packages rather than building from scratch.

**Stimulus-set licensing and norm-reference data.** Many established assessment instruments are copyrighted; using them requires licensing agreements with the publishers. Population norms for specific instruments and populations are similarly licensed or institutionally developed. Production deployment requires the licensing arrangements, the norm reference data in machine-readable form, and the change-management process for instrument updates and norm refreshes.

**SLP-review interface design and clinical-workflow integration.** The SLP-facing review interface is the primary surface where the system either succeeds or fails. Production deployment requires extensive SLP-led design, iterative usability testing, and integration with the SLP's existing documentation tools. The interface design is the system's single biggest determinant of clinician adoption.

**Per-deployment-context configuration and integration.** Hospital-outpatient, school-based, private-practice, early-intervention, telepractice, and inpatient-acute-care contexts each have different documentation system targets, different consent requirements, different reimbursement models, and different population profiles. Production deployment in each context requires its own integration and configuration work; a single deployment does not fit all contexts.

**Pediatric-specific consent infrastructure.** Pediatric deployments require parent or guardian consent plus age-appropriate assent, with developmentally-graduated assent language, dual-signature handling, FERPA alignment for school deployments, COPPA alignment for any direct-to-child interface, and the long-horizon pediatric-records-retention infrastructure. The consent infrastructure is more substantial than typical adult HIPAA-only consent.

**Disordered-speech corpus expansion.** Public disordered-speech corpora are limited in size and population coverage. Production deployment benefits from institutional disordered-speech corpus expansion, with appropriate IRB approval, consent infrastructure, and SLP-graded labeling. Plan corpus expansion as a multi-year, named clinical-research-team workstream.

**Per-population performance gates.** Per-population performance must meet the institutional threshold for that population before deployment to that population. Populations where per-population performance is inadequate either get the system disabled or get it deployed with explicit caveats and adjusted SLP-review thresholds. Without these gates, the institution silently underserves the populations where the system performs poorly.

**FDA SaMD strategy where applicable.** Speech-therapy AI tools that produce autonomous diagnostic claims are potentially subject to FDA's SaMD framework. The strategy decision (pursue clearance, deploy as SLP-augmentation, deploy as practice-and-monitoring tool) is upstream of the technical work and varies by instrument and clinical claim. Most current speech-therapy AI products position themselves outside the regulatory perimeter; that positioning constrains the clinical claims and the workflow placement.

**Faithfulness and grounding for LLM-generated reports.** The Bedrock-generated SLP report and family summary need explicit faithfulness checks: structured-output validation against the schema, citation grounding to the underlying scoring data, secondary checks that verify the report does not invent items or scores beyond what the system measured. Family-facing summaries also need reading-level validation and Guardrails coverage.

**Clinical-quality review cadence for ongoing deployment.** Voice biomarker work in recipe 10.8 covered the post-deployment surveillance discipline; the same applies here. Per-population accuracy against SLP gold-standard scoring, drift detection over time, re-validation triggers, and clinical-quality review meetings on a regular cadence are operational requirements rather than nice-to-haves. Plan a quarterly per-instrument clinical-quality review meeting at minimum.

**Multilingual deployment.** Monolingual English deployment is the easier starting point; multilingual deployment requires per-language acoustic models, per-language norm references, per-language stimulus sets, per-language linguistic-feature extraction, per-language Bedrock prompting, and per-language clinical validation. Multilingual deployment is a substantial expansion, not a configuration toggle.

**Home-practice and parent-coaching applications.** When the system extends beyond clinical assessment into home-practice apps and parent-coaching tools, the consent, workflow, scoring rubric, and clinical-action mapping all change. A home-practice app deployed with assessment-grade scoring rubrics will produce frustrating false positives; a home-practice app with appropriate practice-grade rubrics is a different product than the assessment system, sharing infrastructure but with distinct user experience and clinical positioning.

**Outcome-tracking and value-based-care alignment.** Speech-therapy reimbursement is increasingly tied to outcomes data. Production deployment benefits from explicit alignment with the relevant outcome measures (FOTO, NOMS, school-district progress-monitoring requirements, IEP goal-attainment measures). The outcome-measure integration is part of the workflow value, not just the clinical value.

**Disaster recovery and degraded-mode operation.** When upstream services fail (SageMaker endpoint outage, Bedrock outage, HealthLake outage), the SLP must be able to continue clinical work. The system must degrade gracefully: pure manual capture and SLP-only documentation when the AI is unavailable, durable session state that survives transient failures, queued processing for delayed scoring when the inference pipeline is degraded.

---

## Architectural Governance and Operational Primitives

The subsections below specify governance, security, and operational patterns that cross-cut the pseudocode walkthrough. Each is an architectural primitive that a production deployment must implement.

### Voice-as-Biometric-Data Governance Scaffolding with Pediatric-Records, FERPA, and COPPA Layering

Voice samples are biometric data under Illinois BIPA, Texas CUBI, Washington's biometric-data law, and GDPR Article 9 for EU patients. This governance scaffolding treats voice-as-biometric as an architectural primitive rather than a footnote.

**Per-jurisdiction biometric-data consent at collection.** At Step 1C (consent capture), the system identifies the patient's jurisdiction and presents the applicable biometric-data consent disclosure. For minors, the parent or legal guardian provides consent on behalf of the child. The consent record stores the jurisdiction, the specific statutory basis (BIPA written informed consent, CUBI notice-and-consent, Washington biometric-data law consent, GDPR Article 9 explicit consent), and the identity of the consenting party. When the patient reaches age of majority, the system triggers a consent-authority handoff: the patient receives notice and the opportunity to provide or withdraw consent on their own behalf.

**Disclosure-accounting log per use.** Every use of biometric data (audio playback, feature-vector computation, model inference, vendor-API export, SLP review of audio, longitudinal-comparison computation) appends an entry to the disclosure-accounting log. Each entry records the timestamp, the identity of the accessor or system component, the purpose category, the data elements accessed, and the statutory basis. Step 8 audit records include a reference to the disclosure-accounting log entries generated during the session. The disclosure-accounting log is a separate data store from the audit archive and follows its own retention regime (typically the longer of the statutory retention floor and the patient's records-retention horizon).

**Right-to-deletion workflow with deletion-propagation.** A deletion request (from the patient, or from the parent on behalf of a minor, or from the patient after reaching age of majority) triggers propagation across: audio samples in S3, feature vectors in S3, per-item scores in DynamoDB, longitudinal-trajectory entries in DynamoDB, goal-attainment data, any vendor-side copies covered by the BAA, and the corresponding disclosure-accounting log entries. Cryptographic erasure (destroying the per-patient KMS data key) is the deletion primitive for encrypted stores. The deletion workflow respects pediatric-records-retention floors: if a state requires retention until age-of-majority-plus-X, the deletion request is queued until the floor is reached unless a court order or explicit statutory override applies.

**Feature-vector biometric classification.** Feature vectors derived from voice samples (formant trajectories, MFCC representations, speaker-embedding vectors) are classified as biometric data because they can re-identify the speaker. The same consent, disclosure-accounting, and deletion-propagation rules apply to feature vectors as to raw audio.

**Pediatric-records-extending-to-age-of-majority-plus-X retention.** The architecture treats pediatric-records retention as a per-state configuration: California requires retention until age-of-majority-plus-1-year; New York requires 6 years from majority; Texas requires until age 25; other states vary. The per-patient retention-floor calculation uses the patient's date of birth, the applicable state rule, and the institutional regulatory floor. Audio, feature vectors, scoring records, and disclosure-accounting log entries all honor this calculated floor.

**Synthetic-voice-detection and voice-cloning defense.** The capture pipeline includes a synthetic-voice-detection guard that flags audio samples with characteristics consistent with text-to-speech synthesis or voice cloning. For pediatric patients, the detection threshold is lowered (more conservative) because pediatric voice samples have higher value as targets for misuse. Flagged samples are quarantined for SLP review before entering the scoring pipeline.

**FERPA-aligned access controls for school deployments.** In the school deployment context, access control follows FERPA's legitimate-educational-interest standard: school employees with a legitimate educational interest can access the student's records, and parents have access-by-default. The architecture maps FERPA access rules to Cognito or institutional-IdP scopes, with school-employee role verification at the API Gateway authorizer.

**COPPA-aligned verifiable parental consent for direct-to-child interfaces.** Home-practice apps and other interfaces directed at children under 13 require verifiable parental consent under COPPA. The consent mechanism meets the FTC's standards for verifiable consent (not merely click-through). The architecture stores the COPPA consent evidence alongside the HIPAA and biometric-data consent records.

**Step 9 deletion-propagation pseudocode pattern:**

```pseudocode
FUNCTION process_deletion_request(
        patient_id_hash, requestor_id, requestor_authority):

    // Verify authority: parent-on-behalf for minors,
    // patient-on-own-behalf for adults or patients past
    // age of majority.
    patient_record = longitudinal_table.get(patient_id_hash)
    retention_floor = compute_retention_floor(
        date_of_birth: patient_record.date_of_birth,
        state: patient_record.jurisdiction_state)

    IF now() < retention_floor:
        queue_deletion_at(
            patient_id_hash: patient_id_hash,
            execute_after: retention_floor,
            requestor_id: requestor_id)
        RETURN {status: "queued_until_retention_floor",
                execute_after: retention_floor}

    // Propagate deletion via cryptographic erasure.
    destroy_patient_data_key(patient_id_hash)

    // Explicit object deletion for non-KMS-encrypted
    // stores and vendor-side copies.
    delete_audio_objects(patient_id_hash)
    delete_feature_vectors(patient_id_hash)
    delete_longitudinal_entries(patient_id_hash)
    delete_scoring_records(patient_id_hash)
    notify_vendor_deletion(patient_id_hash)
    append_disclosure_log(
        patient_id_hash: patient_id_hash,
        action: "deletion_executed",
        requestor: requestor_id,
        authority: requestor_authority)

    RETURN {status: "deleted"}
```

**Production-gaps owners.** The biometric-governance scaffolding requires named owners: the institutional privacy officer (policy authority), the institutional records-management officer (retention-floor authority), the FERPA records officer for school deployments (educational-records authority), and the engineering lead responsible for the deletion-propagation and disclosure-accounting-log implementations.

### Pediatric, FERPA, COPPA, and School-Context Profile

Four overlapping deployment contexts trigger different consent, access-control, and documentation regimes. The architecture supports per-profile configuration.

**Clinic-based pediatric.** The standard pediatric clinical context. Consent flow: HIPAA-aligned parent or guardian authorization with age-appropriate assent for children typically age 7 and older. Access control: treating-provider access plus patient/legal-representative access. Documentation: standard HIPAA-aligned clinical documentation. Age-of-majority handoff: at the per-state age-of-majority threshold, the system generates a notice to the patient (now an adult), transitions consent authority from parent-on-behalf to patient-on-own-behalf, and updates access-control scopes accordingly.

**School-based pediatric.** School SLP services create dual-jurisdiction complexity. Consent flow: FERPA-aligned consent with per-state educational-records retention rules; when the school bills Medicaid or commercial insurance for the service, HIPAA also applies and both consent surfaces are required. Access control: school-employee-legitimate-educational-interest (FERPA standard) plus parent-access-by-default; when HIPAA applies, treating-provider plus patient/legal-representative access layers on top. The architecture supports dual-access-control evaluation. Documentation: IEP-aligned output for school deployments (progress toward IEP goals, goal-attainment data formatted for the IEP review meeting) alongside HIPAA-aligned clinical documentation where the service is billed to a health plan.

**Direct-to-child interface (home-practice apps for children under 13).** Consent flow: COPPA-aligned verifiable parental consent before the child interacts with the app. The consent mechanism meets FTC standards (signed consent form, credit-card verification, or equivalent approved method). Access control: parent supervises and can access all data; the child's access is mediated through the parent's account. No direct marketing or behavioral targeting of the child. Data retention: COPPA requires that data not be retained longer than reasonably necessary for the purpose; the architecture enforces a tighter retention schedule for direct-to-child data than for clinician-facing data unless the longer pediatric-medical-records floor applies.

**Adult speech-therapy.** The simplest profile. Consent flow: HIPAA-aligned patient authorization with biometric-data disclosure where jurisdiction requires. Access control: treating-provider plus patient access. Documentation: standard clinical documentation. No FERPA or COPPA applicability.

**Per-profile differences in Step 1C consent capture.** The session-setup Lambda reads the `deployment_context` flag and presents the applicable consent surface(s). The consent record stores which profiles applied and the per-profile consent evidence. The audit record at Step 8 includes the `deployment_context` flag and per-profile consent references.

**Age-of-majority handoff.** The system monitors patient age against the per-state age-of-majority threshold. When the threshold is reached, the system generates a notice to the patient, offers consent-on-own-behalf, and transitions access-control authority. For school-based deployments that span the age-of-majority boundary (a student receiving services from age 16 through age 19), the handoff includes both FERPA and HIPAA authority transitions.

**Pediatric-assent gradient.** For older pediatric patients (typically age 7+, but developmentally determined), assent is captured alongside parent consent. The assent language is developmentally appropriate. The architecture stores assent as a separate record from parent consent, with the understanding that assent is a respect-for-persons principle rather than a legal authorization.

### Per-Device-Pattern Audio Path Authentication and Encryption

Different capture devices have different security postures. The architecture specifies per-device-pattern requirements.

**In-clinic dedicated microphone.** TLS in transit as a minimum. Mutual TLS (mTLS) preferred for dedicated hardware with provisioned client certificates. Per-encounter session tokens bind the audio stream to the assessment session. Device-attestation using hardware-backed credentials where the microphone system supports it. BAA scope: the microphone vendor's processing path (if any signal processing occurs on-device before transmission) is covered by the institutional BAA.

**Telepractice video-call audio.** TLS in transit via the video-call platform's encryption. Per-session patient-pairing: the system verifies that the audio stream corresponds to the correct patient session before scoring. For pediatric telepractice, parent-co-presence verification is required (the parent or guardian is confirmed present at the start of the session). Device-attestation is limited to what the video-call platform supports.

**Home-practice mobile-app capture.** Device-attestation for the mobile app using platform-specific attestation APIs (Android SafetyNet/Play Integrity, iOS DeviceCheck/App Attest). Per-encounter session tokens with short expiry. For pediatric direct-to-child interfaces, verifiable parental consent per COPPA finding above, plus parent-co-presence verification for younger children. Audio is encrypted on-device before upload using a per-session key derived from the session token.

**School-based shared equipment.** Per-session patient-pairing under FERPA-aligned access controls. The device may be shared among multiple students; the system verifies student identity at session start and ensures audio from one student's session is not accessible to another student's session. School-employee-legitimate-educational-interest access control applies.

**Per-device-class certification expectations.** In-clinic dedicated microphones: HITRUST or SOC 2 Type II certification for the vendor. Mobile apps: SOC 2 Type II for the app vendor. For devices that are part of an FDA-cleared SaMD pathway, the device is included in the SaMD regulatory submission.

**Audit-record propagation.** The device-attestation context (device class, attestation status, session-token validity, patient-pairing verification, parent-co-presence verification for pediatric telepractice) is recorded in the session metadata and propagated into the Step 8 audit record.

### Vendor-API Integration Security for Biometric-Data Export

When audio or feature vectors cross the institutional-vendor boundary (for example, invoking a third-party speech-scoring API), the export constitutes a biometric-data disclosure event.

**Authentication.** Vendor API authentication via mTLS where the vendor supports it, or API key plus scoped IAM credentials with per-call rotation via Secrets Manager. TLS 1.2+ in transit with certificate pinning where supported.

**Disclosure-accounting.** Each vendor API call that transmits audio or feature vectors appends a disclosure-accounting log entry per the S1 governance scaffolding. The entry records the vendor identity, the data elements transmitted, the statutory basis, and the timestamp.

**BAA scope.** The vendor BAA covers audio data in transit to the vendor, at rest within the vendor's pipeline, and within the vendor's subprocessors. The BAA specifies the vendor's data-retention and deletion obligations.

**Data residency.** For EU patients, audio routes to EU-resident vendor endpoints under GDPR Article 9 requirements. The architecture supports per-patient-jurisdiction routing: the vendor-integration Lambda reads the patient's jurisdiction from the session metadata and selects the appropriate vendor endpoint region.

**Egress hierarchy.** PrivateLink (preferred, where the vendor exposes a PrivateLink endpoint) > Direct Connect or VPN (for vendors with dedicated connectivity) > public-Internet-with-TLS (acceptable for vendors without private connectivity, with additional controls: certificate pinning, WAF egress rules, per-call logging).

### Lambda Resource-Based Policy and Event-Payload Validation

Each Lambda in the pipeline has a resource-based policy that pins the invoking principal to the specific production resource ARN.

**Resource-based policy pinning.** The session-setup Lambda's resource-based policy allows invocation only from the production API Gateway stage ARN. The feature-extraction Lambda allows invocation only from the production Step Functions state-machine ARN. The scoring Lambda allows invocation only from the production Step Functions state-machine ARN. The documentation-generation Lambda allows invocation only from the production Step Functions state-machine ARN or the production EventBridge rule ARN (for event-driven report generation). No Lambda allows invocation from wildcard principals.

**Event-payload validation guard.** Each Lambda includes a defense-in-depth guard at the start of execution that validates the invoking context against production constants. The guard checks: (1) the source ARN from the Lambda context matches the expected invoker; (2) the event payload contains the expected schema fields for the pipeline stage; (3) the session_id in the payload corresponds to an active session in the session table. If any check fails, the Lambda logs the validation failure, emits a CloudWatch alarm metric, and returns an error without processing the event.

### Audit-Log Retention Floor

The audit-log retention floor is the longest of the following per-patient:

1. **HIPAA minimum:** six years from the date of creation or the date when the policy was last in effect, whichever is later.
2. **State medical-records retention:** including pediatric-extending-to-age-of-majority-plus-X rules. Examples: California requires pediatric records until age-of-majority-plus-1-year; New York requires 6 years from age of majority; Texas requires retention until age 25. The per-patient calculation uses date of birth and applicable state rule.
3. **Biometric-records retention:** BIPA requires retention policies to specify a maximum retention period (typically 3 years from last interaction or purpose completion); CUBI and Washington's biometric-data law have analogous requirements; GDPR Article 9 requires retention only as long as the processing purpose persists plus the applicable legal obligation floor.
4. **FERPA educational-record retention:** for school-based deployments, per-state educational-records-retention rules apply (typically 5-7 years from last attendance, but varies).
5. **COPPA-related retention:** for direct-to-child interface elements, data is retained no longer than reasonably necessary for the purpose unless a longer medical-records or educational-records floor applies.
6. **FDA SaMD post-market surveillance retention:** for cleared devices, the FDA expects post-market surveillance records to be maintained for the useful life of the device plus any post-market study commitments (typically 5-10 years).
7. **Institutional regulatory floor:** the institution's own records-management policy, which may exceed all statutory floors.

The disclosure-accounting log (per S1 governance) follows a separate retention regime: it is retained at least as long as any of the data it describes is retained, plus a configurable buffer (typically 2 years) to support deletion-verification auditing.

### Stimulus-Set IP and License Attribution

Assessment instruments and their stimulus sets are intellectual property. The architecture manages licensing as an operational concern.

**Per-stimulus license-attribution log.** Each stimulus presented to the patient is logged with the instrument version, the stimulus identifier, the license under which the stimulus is used, and a reference to the institutional license agreement. This log is appended to the disclosure-accounting log per the S1 governance scaffolding.

**Per-instrument-version tracking with version-mismatch detection.** The session-setup Lambda loads the current instrument definition (including the stimulus set version) from DynamoDB. If the instrument definition has been updated since the patient's last assessment, the longitudinal-comparison Lambda flags the version mismatch so the SLP can interpret score deltas in context (a stimulus-set change can shift baseline scores independent of patient progress).

**Per-norm-reference licensing distinction.** Norm-reference data may be licensed separately from the stimulus set. The architecture tracks norm-reference provenance (publisher, version, license agreement reference) and includes norm-reference attribution in the assessment output.

**Deviation-from-published-stimulus tracking.** When the SLP customizes stimuli at session setup (adding patient-specific target words, adjusting stimulus difficulty), the system records the deviations from the published stimulus set. The scoring engine accounts for the deviation when applying published norms (norms validated on the published stimulus set may not apply directly to customized stimuli; the system flags this limitation).

**License-key management.** Stimulus-set and norm-reference license keys are stored in Secrets Manager with rotation per the publisher's terms. The session-setup Lambda validates the license key at session start and logs the validation result.

**Institutional-license-compliance audit surface.** The analytics layer provides a dashboard showing license utilization (sessions per instrument, per month), license expiration dates, and compliance status. This supports institutional procurement and renewal workflows.

### Deployment Pattern (Versioning and Canary Deployment)

Every component that affects clinical output is version-controlled with commit-SHA-tied builds and canary-deployed with rollback-on-regression.

**Version-controlled artifacts.** Models (SageMaker model artifacts with version tags), prompts (Bedrock inference profile with prompt templates versioned in source control), stimulus sets (instrument definition versions in DynamoDB with change history), per-population norm references (versioned alongside instrument definitions), per-population thresholds (confidence thresholds, severity cutoffs, eligibility gates), and clinical-action mappings (what actions the system recommends based on score patterns).

**SageMaker endpoint canary deployment.** New model versions deploy as canary endpoints with a traffic-shift schedule (typically 5% initial, 25% after 24 hours, 100% after 72 hours if no regression). Regression detection uses per-population SLP-agreement metrics from the canary traffic. Rollback is automatic on regression detection.

**Bedrock inference profile for prompt versioning.** Report-generation prompts and family-summary prompts are versioned through Bedrock inference profiles. A new prompt version deploys to a test cohort first; the faithfulness-check pass rate on the test cohort gates promotion to production. Rollback-on-regression is automated.

**Held-out evaluation set.** A per-population held-out evaluation set (SLP-graded reference assessments not used in training) runs against every new model version, prompt version, and threshold configuration before promotion. The evaluation set includes per-population coverage (each validated population has representation) and prompt-injection test cases (adversarial inputs that should not produce clinical-looking output).

**Version stamping on every assessment session.** The audit record for each session includes: `scoring_model_versions` (one per instrument and per model), `stimulus_set_version`, `per_population_norm_reference_version`, `per_population_threshold_version`, `clinical_action_mapping_version`, `slp_report_prompt_version`, and `family_summary_prompt_version`. This supports traceability: for any historical assessment, the institution can identify exactly which versions of every component produced the result.

**SaMD-specific change-management.** For deployments where one or more instruments operate under an FDA SaMD clearance, version changes to clearance-affecting components (the scoring model, the severity thresholds, the clinical-action mappings) follow the SaMD change-management discipline. Minor changes (prompt wording, UI layout) may fall under the cleared device's change plan; major changes (new model architecture, new population expansion, new clinical claim) require a regulatory submission. The version-control infrastructure distinguishes clearance-affecting from non-clearance-affecting changes.

### Per-Language Pipeline Pattern

Multilingual deployment is a substantial expansion built on a language-aware architecture from day one, even when shipping English-first.

**Per-language acoustic-feature calibration data.** Each supported language has its own acoustic-feature calibration corpus (language-specific phoneme distributions, language-specific formant ranges, language-specific prosodic patterns). The calibration data gates per-language deployment: a language is not enabled until its calibration data meets the institutional quality threshold.

**Per-language linguistic-feature LLM-judge prompts.** Connected-speech linguistic-feature extraction uses Bedrock with language-specific prompts developed with native-speaker SLP-clinical input. The prompt templates are versioned per language and validated against SLP-graded reference transcripts in that language.

**Per-language template definitions.** SLP-report templates and family-summary templates are language-specific. A Spanish-language report uses Spanish clinical terminology and culturally appropriate framing, not a machine translation of the English template.

**Per-language faithfulness rule catalogs.** The Guardrails configuration includes per-language rules for content filtering, clinical-claim boundaries, and reading-level validation.

**Per-language validation cohort.** Each language has its own validation cohort with appropriate demographic representation (age bands, dialects, severity bands, clinical populations). The per-language validation evidence is separate from the English validation evidence; cross-language transfer is not assumed.

**Per-language consent disclosure.** HIPAA, FERPA, COPPA, and biometric-data-law consent disclosures are provided in the patient's or parent's preferred language.

**Per-language stimulus-set licensing.** Stimulus sets for non-English instruments may be licensed from different publishers or developed institutionally. Per the S4 finding, license attribution applies per language.

**Per-dialect calibration within each language.** Within a supported language (for example, Spanish), dialect variation (Mexican Spanish, Caribbean Spanish, Central American Spanish) affects phonological-pattern interpretation. The architecture supports per-dialect calibration data and per-dialect norm references where they exist.

**Code-switching handling.** Bilingual speakers frequently code-switch during assessment. The pipeline detects code-switching events, scores each language segment against the appropriate language model, and presents the bilingual profile to the SLP. Code-switching is not treated as an error; it is treated as a feature of the speaker's linguistic repertoire.

**Per-language deployment gating.** A new language is deployed only when all per-language assets (acoustic calibration, linguistic-feature prompts, templates, faithfulness rules, validation cohort, consent disclosures, stimulus-set licensing) meet the institutional quality threshold and the per-population validation for that language passes the launch gate.

### Disaster Recovery Topology

Each upstream service has a defined failover policy. The SLP must be able to continue clinical work regardless of infrastructure failures.

**SageMaker endpoint outage.** Primary: cross-region fallback to a secondary endpoint in a paired region with the same model version. Secondary (if cross-region is also unavailable): graceful degradation to "scoring not currently available, continue with SLP-only assessment" mode. The SLP records the session; audio is stored; scoring runs when the endpoint recovers. The session state machine in Step Functions enters a "pending-scoring" durable state.

**Bedrock unavailability.** Fallback: structured-output-only rendering of the SLP report and family summary. The system populates the report template with the structured scoring data (tables, per-item results, norm comparisons) without the LLM-generated narrative prose. The SLP can add narrative manually. The family summary uses a pre-authored template with fill-in-the-blank structured data rather than LLM-generated prose.

**Transcribe Medical unavailability.** Linguistic-feature pipelines are disabled for connected-speech tasks. Connected-speech instrument scoring fails gracefully with a clear status ("transcription unavailable, linguistic features not computed"). Acoustic-only instruments (articulation, fluency, voice quality) continue to score normally.

**HealthLake unavailability.** Assessment results are stored durably in the longitudinal DynamoDB table and the score-archive S3 bucket. FHIR write-back is queued with EventBridge retry. The SLP sees results in the application immediately; EHR synchronization catches up when HealthLake recovers.

**School SIS integration unavailability.** IEP-aligned documentation is stored locally and queued for SIS write-back with durable retry. The SLP can export the documentation manually if needed before the retry succeeds.

**EHR API unreachable.** Same pattern as SIS: durable storage with retry. The documentation Lambda stores the FHIR resources in S3 and queues a retry event on EventBridge with exponential backoff.

**Failover-detection triggers.** Health checks run every 60 seconds against each upstream service. Three consecutive failures trigger failover. Failover-back triggers on five consecutive successful health checks after recovery.

**Quarterly testing cadence.** The institution runs a disaster-recovery exercise quarterly, verifying each failover path by simulating the corresponding upstream outage and confirming that the SLP-facing workflow degrades gracefully.

---

## Variations and Extensions

**School-based SLP deployment with IEP integration.** A focused deployment for school SLPs, with FERPA-aligned consent, IEP-aligned documentation, school SIS integration, and progress-monitoring outputs that feed the IEP review process. School SLPs handle a large share of pediatric speech-therapy caseloads, and the school deployment context is sufficiently different from the clinical context that it warrants its own product configuration.

**Telepractice-optimized workflow.** A deployment optimized for telepractice with telepractice-specific recording-quality guidance, telepractice-fine-tuned acoustic models, parent-supported capture for pediatric telepractice, and integration with the SLP's telepractice platform of choice. The COVID-era shift to telepractice has not fully reverted; many SLPs maintain hybrid practices, and the telepractice-specific tooling is a sustained-demand product.

**Home-practice and parent-coaching app.** A patient-and-parent-facing app that supports between-session home practice with immediate feedback on target-sound production, parent-coaching prompts on how to support practice, gamification appropriate for pediatric users, and progress reporting that the SLP can review between visits. The clinical positioning is practice-and-monitoring rather than assessment, with corresponding consent and regulatory implications.

**Stuttering severity tracking with longitudinal trajectory.** A focused deployment for fluency assessment and tracking, with SSI-4-aligned scoring, longitudinal trajectory analysis, treatment-response monitoring, and integration with established stuttering-therapy programs (Lidcombe, Camperdown, fluency shaping, stuttering modification). Stuttering is a high-value indication because the assessment is structured, the longitudinal tracking is clinically meaningful, and the patient population includes both children and adults.

**Voice quality assessment for laryngeal pathology.** A focused deployment for voice-quality assessment, with CAPE-V-aligned and VHI-aligned scoring, integration with otolaryngology and voice-disorder clinics, and longitudinal tracking for post-surgical and post-radiation voice recovery. The voice-quality use case is a natural fit for the architecture and has well-established clinical pathways.

**Post-stroke aphasia and dysarthria recovery monitoring.** A deployment focused on post-stroke speech recovery, with dysarthria assessment for motor-speech recovery, aphasia-related linguistic-feature tracking, and longitudinal monitoring across the recovery trajectory. Integration with stroke-recovery clinical programs and rehabilitation hospitals. The within-patient longitudinal pattern is particularly clinically useful here because each patient's pre-stroke baseline (where available) provides a strong reference.

**Pediatric autism spectrum disorder assessment support.** Voice-and-prosody features for pediatric autism assessment, supporting the SLP and developmental-pediatrics team's diagnostic workup. The diagnostic pathway is more nuanced than articulation or fluency, the AI's role is more clearly augmentation than autonomous scoring, and the consent and family-coaching considerations are substantial.

**Cleft-palate and resonance assessment.** Resonance-focused assessment for cleft-palate-and-craniofacial patients, with hypernasality and hyponasality scoring, post-surgical recovery tracking, and integration with craniofacial team workflows. A specialty deployment with a small but high-value patient population.

**Transgender voice-training assessment.** Voice-quality and pitch-modification tracking for transgender voice training, supporting the SLP and the patient through the longitudinal voice-modification process. A growing service area with specific clinical and cultural considerations; the architectural pattern fits well with the longitudinal-tracking emphasis.

**Multilingual articulation assessment for Spanish-English bilingual children.** A multilingual deployment with Spanish phonological norms, code-switching-aware capture, dialect-aware scoring, and bilingual-clinical SLP workflow integration. Bilingual articulation assessment is a recognized gap in available tools, and a successful multilingual deployment serves an underserved population.

**Real-time SLP feedback during therapy sessions.** A real-time-during-therapy use case where the system provides the SLP with in-session feedback on target-sound production, fluency events, or voice-quality dimensions as the therapy is happening. The latency requirements are tighter than the asynchronous assessment workflow, and the SLP-facing interface is built for in-session use rather than post-session review.

**Caseload-level analytics for SLP practice management.** A practice-level dashboard that aggregates across the SLP's caseload, surfacing patients with stalled progress for goal review, patients near discharge readiness, patients with concerning trajectory patterns, and overall practice outcome metrics. The analytics are a productivity multiplier for the SLP and a quality-of-care signal for the practice leadership.

**Outcome-tracking integration for value-based-care contracts.** Explicit integration with value-based-care outcome measures (FOTO, NOMS, school-district progress measures) so that the SLP's documentation automatically populates the outcome-tracking systems that drive reimbursement. A workflow value proposition that complements the clinical value proposition.

**Integration with augmentative-and-alternative communication assessment.** For patients with severe expressive-language impairment, AAC assessment is part of the SLP's work. Voice-and-speech AI can support AAC assessment by tracking the patient's residual speech production alongside their AAC use, supporting the multi-modal communication assessment.

**Continuing education and SLP training support.** The corpus of SLP-graded assessments produced by the system supports continuing-education content, SLP-trainee feedback (where the trainee's scoring is compared with the SLP-validated AI scoring as a learning aid), and inter-rater-reliability training. This is an extension of the data the system collects, with explicit IRB and consent considerations for data use beyond direct clinical care.

**Per-population norm development for underserved populations.** The longitudinal data the system collects supports norm development for populations where established norms are limited (specific age bands, specific dialects, specific clinical populations). This is a research-track use of the data with explicit IRB approval, but it can extend the system's clinical utility for populations the off-the-shelf norms do not serve.

---

## Additional Resources

**AWS Documentation:**
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon SageMaker Asynchronous Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html)
- [Amazon SageMaker Model Monitor](https://docs.aws.amazon.com/sagemaker/latest/dg/model-monitor.html)
- [Amazon SageMaker Clarify](https://docs.aws.amazon.com/sagemaker/latest/dg/clarify-fairness-and-explainability.html)
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): SageMaker examples including model-hosting, Model Monitor, and Clarify patterns
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including grounded generation and Guardrails
- [`aws-samples/amazon-transcribe-streaming-python`](https://github.com/aws-samples/amazon-transcribe-streaming-python): Transcribe streaming and async-job samples
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): healthcare AI/ML sample notebooks

**AWS Solutions and Blogs:**
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "speech," "audio," "SageMaker," "Transcribe Medical" for implementation deep dives
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): healthcare-specific AI/ML case studies
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for clinical-decision-support reference architectures

**External References (Standards, Frameworks, and Regulatory):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model for assessment-result EHR integration
- [FHIR Observation Resource](https://www.hl7.org/fhir/observation.html): canonical FHIR resource for assessment-score write-back
- [FHIR Goal Resource](https://www.hl7.org/fhir/goal.html): canonical FHIR resource for therapy-goal representation
- [FHIR CarePlan Resource](https://www.hl7.org/fhir/careplan.html): canonical FHIR resource for therapy-plan representation
- [LOINC](https://loinc.org/): standard codes for clinical observations, including some speech-and-language assessment items
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in speech-therapy workflows
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [FERPA](https://www2.ed.gov/policy/gen/guid/fpco/ferpa/index.html): governs educational records, applicable for school-based SLP work
- [COPPA](https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa): governs online services directed at children under 13, applicable for direct-to-child interfaces
- [Illinois Biometric Information Privacy Act (BIPA)](https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004): biometric-data law applicable to voice samples in Illinois
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): regulatory framework for software medical devices, potentially applicable to autonomous-scoring speech-therapy AI

**Research and Datasets:**
- [TORGO Database](http://www.cs.toronto.edu/~complingweb/data/TORGO/torgo.html): dysarthric speech corpus for research 
- [UASpeech Corpus](http://www.isle.illinois.edu/sst/data/UASpeech/): cerebral-palsy-related speech impairment corpus 
- [AphasiaBank](https://aphasia.talkbank.org/): research corpus for post-stroke aphasia 
- [FluencyBank](https://fluency.talkbank.org/): research corpus for stuttering 
- [LANNA / TalkBank Phon resources](https://phon.talkbank.org/): pediatric speech corpora and analysis tools 
- [INTERSPEECH Conference](https://www.interspeech2024.org/): primary speech-and-audio research venue; speech-therapy AI work appears regularly
- [Journal of Speech, Language, and Hearing Research](https://pubs.asha.org/journal/jslhr): peer-reviewed clinical journal for SLP research
- [American Journal of Speech-Language Pathology](https://pubs.asha.org/journal/ajslp): peer-reviewed clinical journal for SLP practice

**Industry and Clinical Resources:**
- [American Speech-Language-Hearing Association (ASHA)](https://www.asha.org/): the primary professional organization for SLPs; clinical-practice guidelines, code of ethics, and continuing education
- [ASHA Practice Portal](https://www.asha.org/practice-portal/): clinical-practice guidance covering disorders, populations, and assessment instruments
- [ASHA Clinical Topics on Telepractice](https://www.asha.org/practice-portal/professional-issues/telepractice/): telepractice-specific guidance
- [Stuttering Foundation](https://www.stutteringhelp.org/): clinical resources for fluency disorders
- [National Stuttering Association](https://westutter.org/): patient-facing resources and clinical-research support
- [Cleft Palate-Craniofacial Association](https://acpa-cpf.org/): clinical resources for craniofacial speech disorders
- [HHS Office for Civil Rights HIPAA Guidance](https://www.hhs.gov/hipaa/index.html): HIPAA Privacy and Security Rule guidance
- [Department of Education FERPA Guidance](https://studentprivacy.ed.gov/): FERPA implementation guidance for school-based deployments

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single instrument (typically pediatric articulation), single population (typical-development pediatric, age 4-8), commercial-vendor model integration through SageMaker endpoint or vendor API, single deployment context (outpatient clinic), SLP-review interface with confidence-based flagging, FHIR Observation write-back to the EHR, brief-retention audio policy, English-only, pilot with one or two clinical sites | 4-6 months |
| Production-ready | Multiple validated instruments (articulation, phonological-pattern analysis, fluency assessment, voice-quality assessment), multiple populations (pediatric typical-development, pediatric speech-disorder, adult typical, adult dysarthric), multiple deployment contexts (outpatient clinic, school-based, telepractice), full per-population validation with eligibility gates, longitudinal trajectory tracking with per-patient baselines, layered post-deployment surveillance with SageMaker Model Monitor and Clarify plus regular clinical-quality review, biometric-data consent infrastructure with right-to-deletion workflow including pediatric-records protection, full HIPAA-and-FERPA-and-COPPA compliance review, multi-context rollout with named operational owners, English plus at least one additional language (typically Spanish), SLP training and feedback program, per-jurisdiction regulatory analysis, IEP integration for school deployments, outcome-tracking integration for value-based-care contracts | 14-22 months |
| With variations | School-based deployment with full IEP integration, telepractice-optimized workflow, home-practice and parent-coaching app, stuttering severity tracking with longitudinal trajectory, voice-quality assessment for laryngeal pathology, post-stroke aphasia and dysarthria recovery monitoring, pediatric autism spectrum disorder assessment support, cleft-palate resonance assessment, transgender voice-training assessment, multilingual articulation assessment, real-time SLP feedback during therapy sessions, caseload-level analytics, AAC assessment integration, per-population norm development | 10-18 months beyond production-ready |

---

---

*← [Main Recipe 10.9](chapter10.09-speech-therapy-assessment-monitoring) · [Python Example](chapter10.09-python-example) · [Chapter Preface](chapter10-preface)*
