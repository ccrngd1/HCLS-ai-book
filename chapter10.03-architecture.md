# Recipe 10.3 Architecture and Implementation: Voice-to-Text for EHR Navigation

*Companion to [Recipe 10.3: Voice-to-Text for EHR Navigation](chapter10.03-voice-to-text-ehr-navigation). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Transcribe (streaming) for ASR.** Transcribe's streaming API delivers low-latency partial transcripts over WebSocket, supports vocabulary biasing through custom vocabularies and custom language models, returns per-word confidence, and is HIPAA-eligible under BAA. For short-command navigation specifically, the streaming variant is the right default. Transcribe Medical is also an option when the command vocabulary includes substantial clinical terminology (medication names, lab panel names); for pure navigation without clinical entity slots, the general-purpose Transcribe with a custom vocabulary is usually sufficient and lower-cost. <!-- TODO: verify; Transcribe Medical streaming and the trade-off between Transcribe Medical and general-purpose Transcribe with custom vocabulary continues to evolve -->

**Amazon Lex for intent classification and slot filling.** Lex is the managed conversational-AI platform that ships with intent definition, slot types (built-in support for dates, numbers, person names; custom slot types for clinical entities), and dialog management. For an EHR navigation MVP, Lex is the pragmatic starting point: a small set of intents, a few sample utterances per intent, and the platform handles the NLU layer with sub-second latency. Lex bot builds are HIPAA-eligible under BAA. For institutions that prefer LLM-based classification, Bedrock is the alternative; the trade-offs were discussed above.

**Amazon Bedrock for fallback and complex slot extraction.** When the rule-based or Lex layer cannot confidently classify a command, a Bedrock-hosted foundation model can serve as a fallback that handles the long tail of unusual phrasings. Bedrock is also useful for complex slot extraction (extracting structured note metadata from a free-form date description, for example). The same caveats from recipe 10.2 apply: validate output against your taxonomy, treat the transcript as untrusted user input in the prompt, and instrument the disagreement-with-human-review metric.

**AWS Lambda for command execution and EHR integration.** The execution stage runs in a Lambda that authenticates as the clinician (typically via the SMART on FHIR launch context's access token), translates the structured command into one or more EHR API calls, and returns the result. Lambda's per-invocation isolation matches the per-command execution model; cold-start latency on Lambda's recent Java/Node/Python runtimes is acceptable for the latency budget when the function is warm.

**Amazon API Gateway for the client-facing endpoint.** The voice-navigation client (the SMART on FHIR app, the mobile app, the desktop client) calls API Gateway endpoints that proxy to the Lambda functions. API Gateway provides authentication enforcement, rate limiting, request logging, and a stable contract.

**Amazon Cognito (or institutional IdP via OIDC/SAML) for authentication.** Clinician identity is the audit-and-permissions backbone. Cognito federation with the institutional identity provider gives the voice navigation app authenticated clinician sessions; SMART on FHIR launch handles the additional context handoff with the EHR.

**Amazon DynamoDB for session state, command audit, and configuration.** A session-state table tracks the active command session per device (current patient context, last command, staleness timestamp). A command-audit table durably records every command issued, parsed, executed, with all confidences and outcomes. A configuration table holds the intent taxonomy, the read-write classification rules, the per-clinician preferences. All tables encrypted with customer-managed KMS.

**Amazon S3 for audio recordings (when retained) and audit-log archive.** Audio recordings of commands are PHI-class and must be encrypted with customer-managed KMS. Many deployments retain audio briefly for QA and disagreement review, then discard it; the architecture supports both retain-briefly and discard-immediately patterns. Audit logs flow to S3 via Kinesis Data Firehose for long-term retention with Object Lock in compliance mode.

**AWS KMS for cryptographic-key custody.** Customer-managed KMS keys for the audio bucket, the audit bucket, the DynamoDB tables, the Secrets Manager secrets. Different keys per data class for blast-radius containment.

**AWS Secrets Manager for EHR integration credentials and signing keys.** The Lambdas that call EHR APIs need credentials (client IDs, signing keys for SMART on FHIR backend services authentication, vendor-specific tokens). Secrets Manager stores them with rotation per the institutional cadence.

**Amazon CloudWatch and AWS CloudTrail for observability and audit.** CloudWatch tracks operational metrics (per-stage latency distributions, ASR confidence histograms, intent classifier confidence distributions, command success rates, EHR API success rates, disambiguation event counts). CloudTrail captures the API-level audit trail against PHI-bearing resources (DynamoDB audit table, S3 audio bucket, KMS keys, Secrets Manager secrets, Bedrock invocations, Transcribe streaming sessions, Lex bot invocations).

**Amazon EventBridge for cross-system events.** Command events (issued, executed, failed, disambiguated, abandoned) flow to EventBridge so downstream consumers (operational dashboards, the analytics layer, the EHR integration's audit overlay) can react without tight coupling to the execution Lambda.

**AWS Step Functions (optional) for multi-step commands.** Most navigation commands execute in a single Lambda call. A small subset of commands (e.g., "open the operative note from October fourteenth and scroll to the closure section") map to multi-step EHR operations that benefit from Step Functions orchestration with retry semantics and per-step audit. For MVP, single-Lambda execution is sufficient; Step Functions becomes useful as the supported command set grows.

**Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena for analytics.** Audit-log events flow through Kinesis Firehose into S3 for long-term retention; Glue catalogs them; Athena provides SQL access for the operational analytics (commands per clinician per day, success rate by intent, latency distributions, disambiguation rates). Amazon QuickSight (optional) renders the dashboards for clinical operations and IT operations consumers.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Client_Device
      MIC[Microphone]
      PTT[Push-to-talk button]
      UI[SMART on FHIR app<br/>or desktop client]
    end

    subgraph Auth
      COGNITO[Amazon Cognito<br/>+ Institutional IdP]
      SOF[SMART on FHIR<br/>launch context]
    end

    subgraph Edge
      APIGW[API Gateway<br/>WebSocket + REST]
    end

    subgraph Speech_and_NLU
      TRANS[Amazon Transcribe<br/>streaming<br/>+ custom vocabulary]
      LEX[Amazon Lex<br/>intent + slots]
      BEDROCK[Amazon Bedrock<br/>fallback classifier]
    end

    subgraph Execution
      EXEC[Lambda<br/>command-executor]
      SF[Step Functions<br/>multi-step commands<br/>optional]
    end

    subgraph EHR_Integration
      FHIR[EHR FHIR API]
      VENDOR[Vendor-specific<br/>integration platform]
    end

    subgraph State_and_Audit
      DDB_SESS[(DynamoDB<br/>session state)]
      DDB_AUD[(DynamoDB<br/>command audit)]
      DDB_CFG[(DynamoDB<br/>config: intents,<br/>read-write rules)]
      S3_AUDIO[(S3<br/>audio recordings<br/>SSE-KMS)]
      S3_AUDIT[(S3<br/>audit archive<br/>Object Lock)]
    end

    subgraph Events
      EB[EventBridge<br/>command-events bus]
    end

    subgraph Observability
      KIN[Kinesis Data<br/>Firehose]
      GLUE[Glue Data<br/>Catalog]
      ATH[Athena]
      QS[QuickSight]
      CW[CloudWatch<br/>metrics + alarms]
      CT[CloudTrail<br/>audit logs]
    end

    subgraph Secrets_and_Keys
      SM[(Secrets Manager<br/>EHR creds<br/>signing keys)]
      KMS[(AWS KMS<br/>customer-managed keys)]
    end

    MIC --> UI
    PTT --> UI
    UI --> COGNITO
    COGNITO --> APIGW
    UI --> SOF
    SOF --> APIGW
    UI --> APIGW
    APIGW --> TRANS
    TRANS --> APIGW
    APIGW --> LEX
    LEX --> APIGW
    LEX -.fallback.-> BEDROCK
    BEDROCK --> APIGW
    APIGW --> EXEC
    EXEC --> DDB_SESS
    EXEC --> DDB_CFG
    EXEC --> SF
    EXEC --> FHIR
    EXEC --> VENDOR
    EXEC --> SM
    EXEC --> DDB_AUD
    EXEC --> EB
    TRANS --> S3_AUDIO
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> GLUE
    GLUE --> ATH
    ATH --> QS
    EXEC --> CW
    LEX --> CW
    TRANS --> CW
    EXEC --> CT
    APIGW --> CT
    KMS --> S3_AUDIO
    KMS --> S3_AUDIT
    KMS --> DDB_SESS
    KMS --> DDB_AUD
    KMS --> DDB_CFG
    KMS --> SM

    style TRANS fill:#fcf,stroke:#333
    style LEX fill:#fcf,stroke:#333
    style BEDROCK fill:#fcf,stroke:#333
    style DDB_SESS fill:#9ff,stroke:#333
    style DDB_AUD fill:#9ff,stroke:#333
    style DDB_CFG fill:#9ff,stroke:#333
    style S3_AUDIO fill:#cfc,stroke:#333
    style S3_AUDIT fill:#cfc,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Transcribe (streaming, optionally Transcribe Medical), Amazon Lex, Amazon Bedrock (optional, for LLM fallback), AWS Lambda, Amazon API Gateway, Amazon Cognito, Amazon DynamoDB, Amazon S3, AWS KMS, AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon EventBridge, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena. Optionally: AWS Step Functions, Amazon QuickSight. |
| **External Inputs** | EHR integration surface: SMART on FHIR app launch context (preferred), vendor-specific extension platform (Epic App Orchard, Cerner Code Console, etc.), or UI-automation library (last resort). The day's schedule, the clinician's panel, and the active patient list per device for vocabulary biasing and patient-slot resolution. The clinical-command taxonomy and read-write classification rules, reviewed by clinical operations. A representative validation set of voice commands (ideally collected from pilot clinicians, labeled with intent and slot ground truth). Microphone hardware (beamforming preferred, headset for power users). Activation hardware (push-to-talk button, foot pedal, or wake-word-capable always-on capture). |
| **IAM Permissions** | Per-Lambda least-privilege roles. The command-executor Lambda has scoped invocation rights for Transcribe streaming sessions, Lex bot invocations, the specific Bedrock model and inference profile, the EHR FHIR endpoints (via Secrets Manager-stored credentials), the session-state and command-audit DynamoDB tables, and the EventBridge events bus. API Gateway-to-Lambda integration with Cognito authorizer pinned to the clinician identity scope. Avoid wildcard actions and resources in production. <!-- TODO (TechWriter): Expert review S3 (MEDIUM). Specify that the command-executor Lambda's resource-based policy pins the invoking principal to the production API Gateway's stage ARN with the production version. The Lambda rejects invocations from any other API Gateway, any other stage, or any other principal. Add a defense-in-depth event-payload check at the start of the Lambda validating requestContext.apiId against the production constant, with development environments deploying their own development command-executor Lambda. --> |
| **BAA and Compliance** | AWS BAA signed. Transcribe (and Transcribe Medical), Lex, Bedrock (verify the specific models and regions covered), Lambda, API Gateway, Cognito, DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, CloudTrail, EventBridge, Kinesis Firehose, Athena are HIPAA-eligible (verify the current list at build time against the AWS HIPAA Eligible Services Reference). <!-- TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continues to evolve --> EHR vendor agreements: confirm the EHR vendor's terms permit the SMART on FHIR app pattern with the read and (where applicable) write scopes you intend to use; some vendors restrict third-party app behavior for clinical-grade integrations. Patient-disclosure considerations: the practice may need to disclose to patients (signage in the room, informed-consent language at intake) that the rolling cart includes a voice-activated computing device, even though the device is only listening when activated. Specific disclosure obligations vary by jurisdiction and institutional policy. <!-- TODO: verify; recording-disclosure law for explicitly user-activated, command-only voice systems differs from continuous-recording disclosure law; institutional general counsel is the authoritative source --> |
| **Encryption** | Audio recordings (when retained): SSE-KMS with customer-managed keys, retention bound to the QA review window (typically a few days to a few weeks), then automatic deletion via lifecycle policy. Audit log archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum and the institution's regulatory floor. DynamoDB tables (session state, command audit, configuration): customer-managed KMS at rest. Lambda environment variables: KMS-encrypted. Lambda log groups: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all EHR API calls and all AWS API calls (default). <!-- TODO (TechWriter): Expert review A8 (MEDIUM). Specify retain-briefly with a 7-30 day window as the recommended default for audio recordings, and discard-immediately as the conservative alternative for institutions with strict PHI minimization. The choice is a deployment-time decision documented by clinical-operations and compliance review. The audit log (per S1's references-not-content discipline) is the long-term forensic-reconstruction substrate; audio retention is a short-term QA-and-disagreement-review substrate. --> |
| **VPC** | Production: Lambdas that call back-office APIs (the EHR integration in particular) run in VPC with subnets that have controlled egress to the EHR's network (often a private peering connection or VPN to the on-premise EHR system). VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, Lex, and Transcribe so the Lambdas do not need NAT for AWS-internal calls. Endpoint policies pin access to the specific resources the pipeline uses. For SMART on FHIR-based integrations against a cloud-hosted EHR, the integration may not require on-premise network connectivity; for on-premise EHRs, the network topology is typically the longest-lead-time portion of the deployment. |
| **CloudTrail** | Enabled with data events on the audit-log S3 bucket, the DynamoDB audit table, the Secrets Manager secrets, and the customer-managed KMS keys. Lambda invocations logged. API Gateway access logs enabled. Lex bot invocations logged. Transcribe streaming session start and stop logged. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days. Audit retention sized to the longer of HIPAA's six-year minimum and the institutional regulatory floor. <!-- TODO (TechWriter): Expert review S4 (MEDIUM). Voice-EHR navigation produces audit records that must be cross-referenced with the EHR's own audit log for forensic reconstruction. Name the audit retention floor as the longest of (HIPAA's six-year minimum, state-specific medical-records-retention rules, the EHR vendor's audit-retention floor so the two records can be cross-referenced for the full lifetime of the EHR's audit, and the institutional regulatory floor). Reference the institutional retention policy as canonical. --> |
| **Sample Data** | Synthetic command audio for development (text-to-speech generation against scripted command transcripts produces audio with known ground truth). Synthea synthetic patient population for the schedule and patient-index tables. Public-domain medical-vocabulary audio corpora for ASR validation. Never use real clinician audio or real patient names in development; the privacy implications of voice samples are non-trivial. |
| **Cost Estimate** | At a mid-sized practice scale (50 clinicians, average 40 voice commands per clinician per day, 22 working days per month, average command audio length 4 seconds): Transcribe streaming at typically $0.024 per minute totals approximately $35-50 per month for ASR. Lex bot invocation at typically $0.004 per request totals approximately $175 per month at this volume. Optional Bedrock fallback adds typically $20-100 per month depending on the fraction of commands that fall through. Lambda, API Gateway, DynamoDB, S3, CloudWatch, KMS, Secrets Manager total typically $50-200 per month combined at this scale. Total AWS infrastructure typically $300-600 per month at this scale, dominated by Lex and Lambda. The infrastructure cost is small compared to the per-clinician licensing of comparable commercial voice-navigation products. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator. Specific costs depend on per-minute Transcribe streaming pricing in the chosen region and the chosen NLU stack -->|

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Transcribe (streaming)** | Low-latency speech-to-text with custom vocabulary biasing and per-word confidence; Transcribe Medical variant when command vocabulary is heavily clinical |
| **Amazon Lex** | Managed intent classification and slot filling for the navigation command set |
| **Amazon Bedrock** | Optional fallback for unusual phrasings and complex slot extraction |
| **AWS Lambda** | Per-stage processing: command-executor, EHR-integration adapter, audit writer, telemetry emitter |
| **Amazon API Gateway** | Client-facing endpoints for streaming audio (WebSocket) and command execution (REST) with Cognito authorization |
| **Amazon Cognito** | Clinician authentication federated to the institutional identity provider |
| **Amazon DynamoDB** | session-state (current patient, current section, last command, staleness timestamp); command-audit (every command with intent, slots, confidences, outcome); configuration (intent taxonomy, read-write rules) |
| **Amazon S3** | Audio recording storage (when retained, with brief lifecycle); audit-log archive with Object Lock |
| **AWS KMS** | Customer-managed encryption keys for all PHI-bearing data stores |
| **AWS Secrets Manager** | EHR API credentials, SMART on FHIR backend-services signing keys |
| **Amazon CloudWatch** | Operational metrics (per-stage latency, command success rate, ASR and intent confidence distributions, disambiguation rates); alarms (command failure spike, EHR API unavailable, audit-log delivery failures) |
| **AWS CloudTrail** | API-level audit logging for PHI-bearing resources and AI/ML service invocations |
| **Amazon EventBridge** | command-events bus for cross-system event flow |
| **Amazon Kinesis Data Firehose** | Streaming audit-log delivery into S3 for long-term retention and analytics |
| **AWS Glue Data Catalog + Amazon Athena** | SQL access to audit logs for operational analytics |
| **Amazon QuickSight (optional)** | Dashboards for clinical operations and IT operations |
| **AWS Step Functions (optional)** | Orchestration for multi-step commands |

---

### Code

#### Walkthrough

**Step 1: Activate the session and capture audio.** The clinician presses the push-to-talk button on the rolling cart (or the foot pedal, or the headset button). The client app opens a streaming audio session through API Gateway's WebSocket endpoint. The session carries the clinician's authenticated identity, the device identity, and the SMART on FHIR launch context (the patient currently open in the EHR, if any). Audio frames stream as the clinician speaks. Skip the activation acknowledgment (the LED, the tone) and the clinician will not know whether the system heard them; this is the most common MVP regression.

```pseudocode
ON activation_signal(device_id, clinician_session, smart_on_fhir_context):
    // Step 1A: validate the clinician session is current
    // and the SMART on FHIR launch context is fresh.
    // Stale tokens are a security failure mode; reject
    // with a re-launch prompt.
    // TODO (TechWriter): Expert review A7 (MEDIUM).
    // SMART on FHIR access tokens typically last
    // 5-60 minutes; voice-navigation sessions can run
    // for hours of patient encounters. Specify the
    // refresh-token flow, pre-emptive refresh window,
    // refresh-failure handling, and token-storage
    // discipline (Secrets Manager or in-memory only).
    IF NOT clinician_session.is_valid():
        RETURN error("re-authenticate")
    IF smart_on_fhir_context.is_stale(MAX_AGE_MINUTES):
        RETURN error("re-launch_app")

    // Step 1B: open the audio streaming session.
    session_id = generate_uuid()
    audio_session = api_gateway.open_websocket(
        clinician_id: clinician_session.clinician_id,
        device_id: device_id,
        session_id: session_id,
        smart_on_fhir_context: smart_on_fhir_context)

    // Step 1C: emit immediate user-visible activation.
    // Without this, the user is talking to a system that
    // gives no feedback. The visible activation can be a
    // device LED, a tone, a screen indicator, or all of
    // the above; pick at least one.
    client.emit_activation_feedback(visible: true,
                                    audible: true)

    // Step 1D: load the per-session vocabulary biasing.
    // The biasing list includes today's schedule, the
    // patient currently in EHR context (and their
    // medications and recent encounters), the providers
    // in the practice. This is what makes patient-name
    // recognition work in noisy clinical environments.
    biasing_list = build_session_biasing(
        clinician_id: clinician_session.clinician_id,
        current_patient: smart_on_fhir_context.patient,
        todays_schedule: load_schedule(
            clinician_session.clinician_id,
            today()))

    audio_session.set_biasing(biasing_list)

    RETURN audio_session
```

**Step 2: Stream audio to ASR and finalize the transcript.** Audio frames stream from the client to API Gateway to the Transcribe streaming endpoint. Partial transcripts emit as audio is processed; the final transcript emits when end-of-utterance is detected (button release, in push-to-talk mode). The pipeline computes aggregate confidence and gates further processing on it. Skip the per-word confidence aggregation and the downstream layers cannot make confidence-aware decisions; the read-write boundary breaks down.

```pseudocode
FUNCTION stream_audio_to_asr(audio_session, biasing_list):
    // Step 2A: open the Transcribe streaming session
    // with the appropriate language model variant. For
    // pure navigation, the general-purpose Transcribe
    // with custom vocabulary is usually sufficient.
    // For navigation + clinical-entity slot extraction,
    // Transcribe Medical may be preferable.
    transcribe_session = transcribe.start_streaming(
        language_code: "en-US",
        media_sample_rate_hertz: 16000,
        custom_vocabulary_name: PER_SESSION_BIASING_VOCAB,
        enable_partial_results_stabilization: true,
        partial_results_stability: "high",
        // Per-word confidence is essential.
        show_speaker_labels: false)

    // Step 2B: pump audio frames from the client
    // session into the Transcribe stream. Emit partial
    // transcripts back to the client for visual feedback
    // ("listening: open patient...").
    WHILE audio_session.is_active():
        audio_frame = audio_session.read_frame()
        IF audio_frame.is_end_of_utterance:
            transcribe_session.end_stream()
            BREAK
        transcribe_session.send_audio_frame(audio_frame)

        partial = transcribe_session.next_partial_result()
        IF partial:
            audio_session.emit_partial_to_client(
                text: partial.transcript)

    // Step 2C: collect the final transcript and per-word
    // confidence.
    final_result = transcribe_session.get_final_result()
    transcript = final_result.transcript
    word_confidences = [
        word.confidence for word in final_result.words
    ]
    avg_confidence = mean(word_confidences) if word_confidences else 0.0
    min_confidence = min(word_confidences) if word_confidences else 0.0

    // Step 2D: gate on overall ASR confidence. If the
    // transcription is too uncertain, prompt the user
    // to repeat rather than guessing.
    IF avg_confidence < ASR_MIN_AVG_CONFIDENCE:
        audio_session.emit_to_client(
            type: "ASR_LOW_CONFIDENCE",
            message: "I didn't catch that. Try again?")
        RETURN { proceed: false,
                 disposition: "asr_low_confidence" }

    RETURN { proceed: true,
             transcript: transcript,
             avg_confidence: avg_confidence,
             min_confidence: min_confidence,
             word_confidences: word_confidences }
```

**Step 3: Parse the command into intent and slots.** The transcript goes to Lex (or the LLM fallback) for intent classification and slot extraction. The output is a structured command object with intent, slots, and per-component confidence. Strict validation against the configured taxonomy: out-of-vocabulary intents are coerced to "unknown" rather than passed through. Skip the strict validation and a hallucinated intent could trigger an unintended EHR action.

```pseudocode
FUNCTION parse_command(transcript, session_context):
    // Step 3A: invoke the Lex bot. Lex returns the
    // intent name, slot values, per-intent confidence,
    // and a dialog state.
    lex_response = lex.recognize_text(
        bot_id: NAVIGATION_BOT_ID,
        bot_alias_id: NAVIGATION_BOT_ALIAS,
        locale_id: "en_US",
        session_id: session_context.session_id,
        text: transcript)

    intent = lex_response.intent.name
    intent_confidence = lex_response.intent.confidence_score
    slots = lex_response.intent.slots

    // Step 3B: validate the intent against the
    // configured taxonomy. Lex generally returns
    // configured intents only, but defensive validation
    // is appropriate for any classifier.
    IF intent NOT IN INTENT_TAXONOMY:
        intent = "unknown"
        intent_confidence = 0.0

    // Step 3C: if Lex confidence is below threshold,
    // optionally fall back to Bedrock for a second
    // opinion. The fallback is configurable per
    // institution.
    // TODO (TechWriter): Expert review S2 (MEDIUM).
    // Add prompt-injection mitigation: wrap the
    // transcript in explicit delimiters
    // (e.g., <transcript>...</transcript>) and
    // instruct the model to treat the transcript as
    // untrusted user data, not as instructions.
    // Validate JSON output strictly against the
    // configured taxonomies. The patient-slot
    // resolution gate (Step 4B) remains the primary
    // safety layer; prompt-injection mitigation
    // bounds what reaches the gate.
    IF intent_confidence < INTENT_CONFIDENCE_THRESHOLD AND
       BEDROCK_FALLBACK_ENABLED:
        bedrock_result = invoke_bedrock_classifier(
            transcript: transcript,
            taxonomy: INTENT_TAXONOMY,
            slot_schemas: SLOT_SCHEMAS,
            current_context: session_context)
        IF bedrock_result.intent IN INTENT_TAXONOMY AND
           bedrock_result.confidence >
               BEDROCK_FALLBACK_CONFIDENCE_THRESHOLD:
            intent = bedrock_result.intent
            intent_confidence = bedrock_result.confidence
            slots = bedrock_result.slots

    // Step 3D: classify the command as read or write.
    // The classification is configuration, not code,
    // so clinical operations can adjust without a
    // deployment.
    read_write = INTENT_READ_WRITE_MAP.get(
        intent, default="unknown")

    // Step 3E: canonicalize medical-vocabulary slots.
    // For example, "lisinopril" goes through Comprehend
    // Medical's RxNorm linker so the downstream EHR
    // call can use the canonical code.
    IF "medication" in slots:
        slots["medication"] = canonicalize_medication(
            slots["medication"])
    IF "lab" in slots:
        slots["lab"] = canonicalize_lab(slots["lab"])
    IF "date" in slots:
        slots["date"] = canonicalize_date(
            slots["date"], reference=now())

    RETURN {
        intent: intent,
        intent_confidence: intent_confidence,
        slots: slots,
        read_write: read_write,
        proceed: intent != "unknown"
    }
```

**Step 4: Resolve context and disambiguate.** The parsed command meets the EHR's current context. If the command includes a patient slot, the patient is resolved against the day's schedule, the clinician's panel, or a broader index. Ambiguous matches go to a disambiguation prompt; unique matches proceed; zero matches go to a clarification prompt. The system never silently picks a patient when input is ambiguous. Skip this gate and you are one misrecognition away from opening the wrong patient's chart.

```pseudocode
FUNCTION resolve_context(parsed_command, session_context):
    // Step 4A: re-fetch the EHR's current context. The
    // EHR is the authoritative source of truth; voice-
    // system context is a derived view.
    // TODO (TechWriter): Expert review A2 (MEDIUM).
    // Bound the check-then-act gap between this
    // re-fetch and the Step 6 execute. On rolling
    // carts the EHR's active patient can change
    // between resolution and execution. Specify
    // either snapshot-precondition (If-Match-style)
    // on EHR API calls where supported, or
    // immediate re-fetch before each API call with
    // abort-on-context-change semantics.
    ehr_state = ehr_api.get_current_state(
        clinician_id: session_context.clinician_id,
        device_id: session_context.device_id)

    current_patient_id = ehr_state.patient_id
    current_section = ehr_state.section

    // Step 4B: if the command specifies a patient slot,
    // resolve against the day's schedule and the panel.
    // TODO (TechWriter): Expert review A4 (MEDIUM).
    // resolve_patient_slot must specify production-
    // grade matching: phonetic matching (Soundex,
    // Metaphone, or clinical name-matching libs),
    // nickname/honorific handling, non-Latin
    // character and accent normalization, MRN-based
    // tiebreaker in the disambiguation prompt, and
    // a broader-index fallback for unscheduled walk-
    // ins and consults with explicit confirmation.
    IF "patient" in parsed_command.slots:
        candidate_patients = resolve_patient_slot(
            spoken_name: parsed_command.slots["patient"],
            todays_schedule: session_context.schedule,
            clinician_panel: session_context.panel)

        IF len(candidate_patients) == 0:
            RETURN { proceed: false,
                     disposition: "patient_not_found",
                     prompt: "I don't see a patient by that name on your schedule today. Can you spell it?" }

        IF len(candidate_patients) > 1:
            // Multiple matches. Disambiguation prompt
            // shows the top candidates with enough
            // identifying info for the clinician to
            // pick. Never silently pick.
            RETURN { proceed: false,
                     disposition: "patient_ambiguous",
                     prompt: build_disambiguation_prompt(
                         candidate_patients) }

        resolved_patient_id = candidate_patients[0].patient_id
    ELSE:
        // No explicit patient slot. Default to the
        // EHR's current patient context.
        resolved_patient_id = current_patient_id

    // Step 4C: staleness check. If the device has been
    // idle past the staleness threshold, require
    // explicit patient confirmation before proceeding.
    idle_seconds = now() - session_context.last_command_at
    IF idle_seconds > SESSION_STALENESS_THRESHOLD_SECONDS:
        IF "patient" not in parsed_command.slots AND
           parsed_command.read_write != "read_only_self_query":
            RETURN { proceed: false,
                     disposition: "stale_session_confirm_patient",
                     prompt: "It's been a while. You're with " +
                             patient_display_name(
                                 resolved_patient_id) +
                             ", correct?" }

    // Step 4D: enrich the command with the resolved
    // context.
    enriched_command = parsed_command.copy()
    enriched_command.resolved_patient_id = resolved_patient_id
    enriched_command.current_section = current_section
    enriched_command.ehr_state_snapshot_id =
        ehr_state.snapshot_id

    RETURN { proceed: true,
             command: enriched_command }
```

**Step 5: Confirm write-class commands; execute read-class commands directly.** The read-write classification gates the confirmation flow. Read commands execute immediately if the intent and slot confidence are above threshold; otherwise a brief confirmation card displays. Write commands always require explicit, non-voice confirmation: the system displays the proposed action and waits for a button press or typed signature. Skip the asymmetric confirmation rigor and either the system is too cautious to be useful (everything confirms) or too aggressive to be safe (writes execute on voice alone).

```pseudocode
FUNCTION confirm_command(enriched_command, session_context):
    // Step 5A: read-only commands with high confidence
    // execute immediately.
    // TODO (TechWriter): Expert review A5 (MEDIUM).
    // Replace the single READ_AUTO_CONFIDENCE_THRESHOLD
    // with a per-intent threshold matrix: low-stakes
    // intents (navigate_section, scroll_*, go_back)
    // tolerate moderate thresholds; medium-stakes
    // intents (open_patient, show_recent_results)
    // require higher thresholds; write-class always
    // require mandatory non-voice confirmation
    // regardless of confidence. Calibration is
    // subgroup-stratified per A1.
    IF enriched_command.read_write == "read" AND
       enriched_command.intent_confidence >=
           READ_AUTO_CONFIDENCE_THRESHOLD:
        RETURN { confirmed: true,
                 confirmation_required: false }

    // Step 5B: read-only commands with medium
    // confidence get a lightweight confirmation card.
    // The user can confirm with button or voice.
    IF enriched_command.read_write == "read":
        client.show_confirmation_card(
            title: "Did you mean...?",
            description: build_command_description(
                enriched_command),
            actions: ["confirm", "cancel"],
            allow_voice_confirm: true,
            timeout_seconds: 5)
        confirmation = client.wait_for_confirmation()
        RETURN { confirmed:
                     confirmation.action == "confirm",
                 confirmation_required: true,
                 confirmation_method:
                     confirmation.method }

    // Step 5C: write-class commands always require
    // explicit non-voice confirmation. Voice cannot
    // confirm a write.
    IF enriched_command.read_write == "write":
        client.show_write_confirmation(
            title: "Confirm action",
            description: build_command_description(
                enriched_command),
            actions: ["confirm_button", "cancel"],
            allow_voice_confirm: false,
            timeout_seconds: 15,
            signature_required: enriched_command.intent
                IN SIGNATURE_REQUIRED_INTENTS)
        confirmation = client.wait_for_write_confirmation()
        RETURN { confirmed:
                     confirmation.action == "confirm_button",
                 confirmation_required: true,
                 confirmation_method: "button_press" }

    // Step 5D: unknown classification: never auto-execute.
    RETURN { confirmed: false,
             confirmation_required: true,
             disposition: "unclassified_no_execute" }
```

**Step 6: Execute against the EHR and reflect the result.** The execution layer translates the structured command into one or more EHR API calls. SMART on FHIR is the preferred path; vendor-specific platforms are next; UI automation is the fallback. The result either updates the EHR's display directly (when the integration supports it) or returns data that the voice-navigation client renders alongside the EHR. Capture every API call's success or failure for the audit log. Skip detailed audit and you have no way to reconstruct what the system did when something goes wrong later.

```pseudocode
FUNCTION execute_command(enriched_command, session_context):
    intent = enriched_command.intent
    slots = enriched_command.slots
    patient_id = enriched_command.resolved_patient_id

    // TODO (TechWriter): Expert review A3 (MEDIUM).
    // Specify per-command idempotency: key composition
    // (clinician_id, session_id, transcript_hash,
    // time_window) with a sliding 30-second window.
    // Session-state holds the recently-executed-
    // commands list with TTL. On idempotency-match,
    // return the prior execution result and record a
    // duplicate-detection event in the audit log
    // with the prior command_id as the dedup
    // reference. Read commands are HIPAA-grade
    // access events: duplicate executions inflate
    // the EHR's access-record fidelity. For write-
    // class intents (added in later phases), the
    // idempotency check must run BEFORE execute, not
    // after, typically as a conditional DynamoDB
    // PutItem that fails closed.

    execution_log = {
        intent: intent,
        slots: slots,
        patient_id: patient_id,
        started_at: now()
    }

    TRY:
        IF intent == "open_patient":
            result = fhir_client.open_patient_chart(
                patient_id: patient_id,
                clinician_token: session_context.access_token)

        ELIF intent == "show_recent_results":
            result = fhir_client.fetch_observations(
                patient_id: patient_id,
                category: slots.get("result_type", "laboratory"),
                _count: slots.get("count", 10),
                _sort: "-date",
                clinician_token: session_context.access_token)
            client.render_results_panel(result)

        ELIF intent == "open_note":
            note_id = fhir_client.find_note(
                patient_id: patient_id,
                note_type: slots["note_type"],
                date: slots.get("date"),
                author: slots.get("author"),
                clinician_token: session_context.access_token)
            IF note_id:
                result = fhir_client.open_note_in_ehr(
                    note_id: note_id,
                    clinician_token:
                        session_context.access_token)
            ELSE:
                client.emit_user_message(
                    "No matching note found.")
                result = { status: "not_found" }

        ELIF intent == "navigate_section":
            result = fhir_client.set_chart_section(
                patient_id: patient_id,
                section: slots["section"],
                clinician_token: session_context.access_token)

        ELIF intent == "navigate_schedule":
            target = resolve_schedule_target(
                slots, session_context)
            result = fhir_client.set_active_appointment(
                appointment_id: target.appointment_id,
                clinician_token: session_context.access_token)

        // Other intents handled similarly; the pattern
        // is the same: translate to EHR API, execute,
        // capture result.

        ELSE:
            result = { status: "unsupported_intent" }

        execution_log.completed_at = now()
        execution_log.status = "success"
        execution_log.ehr_result = result

    CATCH ehr_api_error AS err:
        execution_log.completed_at = now()
        execution_log.status = "ehr_api_error"
        execution_log.error = sanitize_error(err)
        client.emit_user_message(
            "EHR is not responding. Try again or use the keyboard.")

    CATCH timeout_error AS err:
        execution_log.completed_at = now()
        execution_log.status = "timeout"
        client.emit_user_message(
            "That took too long. Try again?")

    // Step 6B: update the voice-system session context
    // to reflect the EHR state change.
    IF execution_log.status == "success":
        session_state.update(
            session_id: session_context.session_id,
            current_patient_id: patient_id,
            current_section: slots.get("section"),
            last_command_at: now())

    RETURN execution_log
```

**Step 7: Audit and emit telemetry.** Every command is recorded with the full pipeline detail: original transcript, parsed intent, resolved slots, confirmation event (if any), execution result. The audit feeds two consumers: the durable HIPAA-grade audit log (DynamoDB plus S3 archive via Firehose) and the operational telemetry layer (CloudWatch metrics, EventBridge events). Skip the durable audit and you cannot reconstruct what the system did during an investigation or quality review.

```pseudocode
FUNCTION audit_and_telemetry(enriched_command, confirmation_result, execution_log, session_context):
    // Step 7A: write the durable audit record. This is
    // the HIPAA-grade record of who issued what command,
    // against which patient, with what outcome.
    // TODO (TechWriter): Expert review S1 (HIGH).
    // Embedding the raw transcript and raw slot values
    // directly in the DynamoDB command-audit table
    // creates a parallel PHI store outside the
    // governance of the audio bucket and the audit-
    // archive S3 bucket. Restructure this record to
    // carry only references and structural metadata:
    // transcript_archive_ref + transcript_length_chars
    // + transcript_hash, slot_keys_present +
    // slot_values_archive_ref + slot_values_hash, and
    // ehr_api_calls_count + ehr_api_calls_archive_ref.
    // Full transcripts and slot values live in the
    // secure archive (S3 with KMS) under the same
    // governance as the audio recordings. The
    // resolved_patient_id remains because it is the
    // structurally-necessary key for HIPAA-grade
    // access auditing. Add a cross-cutting design-
    // points paragraph elevating the references-not-
    // content audit discipline. Update the Expected
    // Results sample audit record below to match.
    audit_record = {
        command_id: generate_uuid(),
        clinician_id: session_context.clinician_id,
        device_id: session_context.device_id,
        session_id: session_context.session_id,
        smart_on_fhir_launch_id:
            session_context.launch_id,
        timestamp: now(),
        transcript: enriched_command.transcript,
        transcript_avg_confidence:
            enriched_command.avg_confidence,
        transcript_min_confidence:
            enriched_command.min_confidence,
        intent: enriched_command.intent,
        intent_confidence:
            enriched_command.intent_confidence,
        slots: enriched_command.slots,
        read_write_classification:
            enriched_command.read_write,
        resolved_patient_id:
            enriched_command.resolved_patient_id,
        confirmation_required:
            confirmation_result.confirmation_required,
        confirmation_method:
            confirmation_result.confirmation_method,
        confirmation_outcome:
            confirmation_result.confirmed,
        execution_status: execution_log.status,
        execution_started_at: execution_log.started_at,
        execution_completed_at:
            execution_log.completed_at,
        ehr_api_calls: summarize_api_calls(
            execution_log)
    }

    command_audit_table.put(audit_record)

    // Step 7B: emit cross-system event for the
    // analytics layer and the EHR's audit overlay.
    EventBridge.PutEvents([{
        source: "voice.navigation",
        detail_type: "command_executed",
        detail: {
            command_id: audit_record.command_id,
            clinician_id: audit_record.clinician_id,
            patient_id: audit_record.resolved_patient_id,
            intent: audit_record.intent,
            execution_status:
                audit_record.execution_status,
            timestamp: audit_record.timestamp
        }
    }])

    // Step 7C: emit operational metrics. These feed
    // the dashboards that surface latency regressions,
    // accuracy drift, and adoption trends.
    cloudwatch.put_metric(
        namespace: "VoiceNavigation",
        metric_name: "CommandLatency",
        value: (execution_log.completed_at -
                enriched_command.activation_at)
                .total_seconds(),
        dimensions: {
            intent: audit_record.intent,
            outcome: audit_record.execution_status
        })
    cloudwatch.put_metric(
        namespace: "VoiceNavigation",
        metric_name: "ASRConfidence",
        value: audit_record.transcript_avg_confidence,
        dimensions: { intent: audit_record.intent })
    cloudwatch.put_metric(
        namespace: "VoiceNavigation",
        metric_name: "IntentConfidence",
        value: audit_record.intent_confidence,
        dimensions: { intent: audit_record.intent })
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter10.03-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample command audit record (illustrative):**

<!-- TODO (TechWriter): Expert review S1 (HIGH). Update this sample to match the references-not-content audit pattern (see TODO at Step 7A): replace the inline `transcript` and `slots` fields with `transcript_archive_ref` + `transcript_length_chars` + `transcript_hash` and `slot_keys_present` + `slot_values_archive_ref` + `slot_values_hash`. Replace the inline `ehr_api_calls` array with `ehr_api_calls_count` + `ehr_api_calls_archive_ref`. -->

```json
{
  "command_id": "cmd-2c4f8e1a-9d3b-4f8a-a8c2-3b1c5d7e9f0a",
  "clinician_id": "user-jdoe",
  "device_id": "rolling-cart-room4",
  "session_id": "sess-7e8f9a0b-1c2d-3e4f-5a6b-7c8d9e0f1a2b",
  "smart_on_fhir_launch_id": "launch-1a2b3c4d",
  "timestamp": "2026-05-23T14:22:08Z",
  "transcript": "open the operative note from October fourteenth",
  "transcript_avg_confidence": 0.94,
  "transcript_min_confidence": 0.78,
  "intent": "open_note",
  "intent_confidence": 0.91,
  "slots": {
    "note_type": "operative",
    "date": "2026-10-14"
  },
  "read_write_classification": "read",
  "resolved_patient_id": "pt-44219-3c",
  "confirmation_required": false,
  "confirmation_method": null,
  "confirmation_outcome": true,
  "execution_status": "success",
  "execution_started_at": "2026-05-23T14:22:08Z",
  "execution_completed_at": "2026-05-23T14:22:09Z",
  "ehr_api_calls": [
    {
      "endpoint": "/DocumentReference",
      "method": "GET",
      "params": {
        "patient": "pt-44219-3c",
        "type": "operative-note",
        "date": "2026-10-14"
      },
      "status_code": 200,
      "duration_ms": 412
    },
    {
      "endpoint": "/Composition/{id}",
      "method": "GET",
      "status_code": 200,
      "duration_ms": 287
    }
  ]
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Keyboard-and-mouse baseline | Voice-driven navigation |
|--------|------------------------------|--------------------------|
| Median time from intent to chart-section-displayed | 8-25 seconds | 1.5-3 seconds |
| Median number of clicks per chart-navigation task | 4-9 | 0 |
| Eye contact preserved during navigation (subjective) | Low | Moderate to high |
| Median time from utterance to action complete | n/a | 800ms-2s |
| ASR average word confidence in clinical environment | n/a | 0.85-0.95 |
| Intent classifier accuracy on configured intents | n/a | 90-97% (top-1) |
| Patient slot misresolution (wrong patient opened) | n/a | <0.1% with disambiguation gate |
| Per-command AWS infrastructure cost | n/a | $0.001-0.01 |
| Adoption rate among pilot clinicians at month 3 | n/a | 30-60% (highly variable) |

<!-- TODO: replace illustrative figures with measured results from the deployment. The ranges above are typical for voice-navigation deployments in healthcare but vary substantially with clinical environment, EHR vendor, and clinician training -->

**Where it struggles:**

- **Patient name resolution under similar names.** Three patients on today's schedule named some variant of "Smith" makes "open patient Smith" inherently ambiguous. The system must disambiguate; the disambiguation prompt adds friction. Mitigations: dictate full name including first name in commands; use date-of-birth as a secondary slot for high-similarity name matches; institutional convention for default-by-time-of-encounter when ambiguity is unresolvable.
- **Heavy ambient noise in clinical environments.** Code blue alarms, IV pump alerts, conversations spilling in from adjacent rooms, the patient's family member talking. Beamforming microphones reduce but do not eliminate the issue. Mitigations: high-quality directional or close-talking microphones, push-to-talk to keep the audio capture window narrow, ambient-noise classification to flag commands issued in particularly hostile audio environments.
- **Speakers with strong accents or non-standard speech patterns.** ASR accuracy varies by speaker. A clinician whose accent is underrepresented in the ASR's training data sees higher word error rates. Vocabulary biasing helps; speaker-adaptive models help more; the institution's monitoring of subgroup-stratified accuracy (per-clinician, per-language-background) should surface disparities. Mitigations: per-clinician custom vocabulary, optional speaker adaptation, periodic vendor evaluation across the represented clinician demographics.
- **Commands at the boundary between navigation and dictation.** "Note that the patient is reporting new burning" is on the boundary. Strict navigation systems reject it; permissive ones execute against the wrong workflow. Mitigations: clearly delineated intent set, "out-of-scope" intent that politely tells the user to switch to the dictation product, hand-off to the dictation product where one is deployed.
- **EHR API limitations.** Some commands the user wants are not feasible against the available EHR API surface. "Show me only the abnormal labs from the last week" may require client-side filtering of a broader API result rather than a server-side narrowed query, which adds latency and complexity. Mitigations: command set scoped to what the EHR API actually supports, fallback to UI automation only as a last resort, ongoing investment in EHR-vendor relationships to expand the API surface.
- **Context drift across sessions.** The clinician walks between rooms, swaps devices, returns hours later. The voice system's context can drift from the EHR's. Mitigations: re-fetch EHR context before every command, staleness checks that require explicit patient confirmation after idle periods, room-change detection (badge tap, RFID, door sensor).
- **Authentication and timeout interactions.** The EHR session times out, the voice command fires, the EHR returns an authentication error. The clinician now has to log in again before continuing. Mitigations: voice-system session lifetime aligned with the EHR session lifetime, proactive token refresh when the voice session is active, graceful re-auth prompts that the clinician can complete with badge tap rather than full re-login.
- **Adoption variability.** Some clinicians embrace voice navigation immediately; others never adopt it. The pilot population is rarely representative of the full deployed population. Mitigations: opt-in deployment, per-clinician usage metrics to identify champions and resistors, structured training, willingness to accept that some clinicians will simply not use it.
- **False activations and pocket-dial-equivalent triggers.** A push-to-talk button accidentally pressed while picking up the cart, a wake word misfired by background conversation, a foot pedal stepped on by accident. The activation must result in a command (or in a clear "no speech detected" disposition) without leaving the system in an indeterminate state.
- **Mid-command interruptions.** The clinician starts a command, the patient asks a question, the clinician answers the question, then continues the command. The system has to handle this gracefully (typically via push-to-talk, where the button release ends the utterance unambiguously). Always-on listening systems struggle here.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Per-intent confidence threshold calibration.** The thresholds in the pseudocode (ASR_MIN_AVG_CONFIDENCE, INTENT_CONFIDENCE_THRESHOLD, READ_AUTO_CONFIDENCE_THRESHOLD) are placeholders. Calibrating them to balance auto-execution throughput against misexecution cost requires measurement against representative production traffic. The calibration is per-axis (ASR confidence is calibrated independently from classifier confidence), per-intent (read intents tolerate lower confidence than write intents; opening a chart tolerates lower confidence than placing an order), and ongoing (recalibrate as the underlying models update). Build the calibration as a recurring operational process.

**Clinical operations governance of the intent taxonomy and read-write classification.** The intent set, the read-write classification per intent, and the confidence thresholds are clinical safety artifacts. They need version control, change review by clinical operations (not by the engineering team unilaterally), scheduled refresh cadence, and a documented escalation path when a misexecution surfaces. Treat them with the procedural rigor that implies, not as configuration files maintained by whoever last edited them.

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Add a Deployment Pattern subsection in the AWS Implementation section specifying the blue-green pattern for Lex bot version aliases, Bedrock inference profiles, classifier prompt definitions, and the intent taxonomy / read-write classification configuration: versioned definitions in source control with commit-SHA-tied builds; canary alias and canary inference profile carrying 5% traffic against a regression evaluation set with subgroup-stratified production metrics (per A1); rollback-on-regression triggers when any subgroup metric drops; held-out evaluation set including accent samples, multi-intent commands, ambiguous-patient-name commands, urgency-keyword phrases against the navigation taxonomy, low-confidence-transcript samples, mixed-language commands; version stamping on every command's audit record (interaction with S1 audit-pattern) including bot_version, classifier_prompt_version, intent_taxonomy_version, read_write_classification_version. -->

**Subgroup-stratified accuracy monitoring with named ownership.** Voice ASR systematically underperforms for some speaker demographics. Per-clinician accuracy metrics (ASR confidence, command success rate, default-to-disambiguation rate) should be visible to the equity-monitoring committee or the clinical-quality officer. Disparities exceeding configured thresholds should alert. The monitoring is not optional analytics; it is the mechanism by which the institution detects whether the system is silently underserving specific clinicians (and, by extension, their patients).

**Patient slot resolution with edge cases.** The patient lookup logic must handle: patients not on the day's schedule (urgent walk-ins, unscheduled consults); patients whose names are spoken as nicknames or honorifics; patients whose names involve non-Latin character sets, accents, or non-standard romanizations; patients with similar names whose disambiguation requires more than first name (date of birth, MRN, clinic location). Pilot the resolution logic against a representative slice of the institution's patient name distribution before launch.

**Voice-write boundary as a clinical safety document.** Every intent that touches a write API surface needs explicit clinical-operations review. The list of write-class intents, the confirmation requirements per intent, and the audit-trail expectations form a clinical safety policy. The list should be conservative at MVP and expand only with deliberate review. Specifically, in MVP: voice-driven placement of medication orders, signing of clinical notes, completion of medication reconciliation, and any action that has direct billing implications should be out of scope.

**Idempotency and retry semantics.** A command issued twice (because of a network blip, or because the clinician thought the system did not hear them) must not produce two executions. The audit record must capture the duplicate-command detection. Idempotency keys per command (typically transcript hash plus clinician plus session plus a short window) prevent double-execution.

**EHR-side audit-overlay integration.** Voice-driven EHR access produces audit events in the voice system. Many institutions also need those events to land in the EHR's native audit log so that the patient's chart-access record is complete from the EHR's perspective. The integration with the EHR's audit API (where one exists) or via FHIR AuditEvent resources is institution-specific and adds engineering scope.

**Performance under load and burst.** The latency budget for an individual command is tight; the system must hold the budget under load. Lambda concurrency limits, API Gateway throughput, Lex quota, Transcribe streaming session limits, all need provisioning headroom. Load test before launch; reserve concurrency where the latency-sensitive Lambdas would otherwise be starved.

**Disaster recovery and EHR-unavailable handling.** If the EHR API is unreachable (vendor outage, network partition, planned maintenance), voice commands cannot execute. The system must communicate this to the clinician immediately and clearly, and the clinician must be able to fall back to keyboard-and-mouse. Test the failure modes in a staging environment before launch.

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Promote this paragraph into an architectural Disaster Recovery Topology subsection in the AWS Implementation section that specifies per-stage failover policy: EHR-unavailable handling with explicit clinician messaging, Streaming Transcribe regional outage with cross-region failover, Lex regional outage with cross-region failover or Bedrock-fallback (gated by S2 prompt-injection mitigation), Bedrock model deprecation with cross-model failover via inference profile abstraction, DynamoDB partition exhaustion with reserved capacity, and quarterly failover testing cadence with synthetic commands. The voice system always degrades gracefully to the keyboard-and-mouse fallback. -->

**On-device or on-premise ASR for air-gapped deployments.** Some hospital environments do not permit clinical audio to leave the institutional network. For those deployments, the cloud-streaming ASR architecture above does not work; an on-premise ASR alternative (or a private cloud connection that satisfies the institution's network policy) is required. Plan the air-gapped variant as a separate architectural track from the cloud variant.

**Multi-language support architecture.** The architecture as described handles English. Adding languages requires per-language Transcribe configurations, per-language Lex bots (or a multilingual NLU layer), per-language intent example utterances, and per-language slot-extraction logic for date and number recognition. Even practices that do not need multilingual support at launch should design the configuration so adding a language later does not require rearchitecting the intent layer.

<!-- TODO (TechWriter): Expert review A10 (MEDIUM). Specify the per-clinician-language-preference dimension as recipe-distinct (the clinician is the speaker, not the patient). Add: language detection at session-open or per-clinician language declaration at onboarding; per-language Transcribe configurations and custom vocabulary lists; per-language Lex bots with shared intent definitions but locale-specific sample utterances; per-language Bedrock prompt templates; per-language slot-extraction with locale-specific date and number canonicalization; mixed-language and code-switched command handling (the language detector returns the dominant language, but the slot extractor handles slot values in either language); per-language patient-name normalization (interaction with A4 patient-resolution edge cases). -->

**Microphone hardware procurement and deployment.** The architecture assumes adequate microphone hardware in the clinical environment. Procurement, installation, and ongoing maintenance of microphone hardware (rolling-cart mounted, room-mounted, or per-clinician headset) is non-trivial operational scope that the engineering organization typically does not own. Identify the operational owner early.

**Clinician training and change management.** The system requires clinicians to learn the command set, the activation pattern, and the failure-mode handling. Most successful deployments include structured training, on-site pilot support during the first week, and a designated point-person for clinician questions. A voice-navigation deployment without change-management investment routinely shows great pilot metrics and stalls at scale.

**Continuous adaptation workflow.** Production transcripts surface intents the original taxonomy missed, command patterns the classifier handles poorly, and patient-name pronunciations the slot extractor mangles. The improvement workflow (review production transcripts and abandoned commands weekly, propose taxonomy and biasing updates, test against a held-out evaluation set, deploy with versioned configurations) is a sustained engineering practice.

**HIPAA-grade audit retention and legal hold.** The command audit log is the durable record of voice-driven EHR access. Retention must meet HIPAA's six-year minimum and any institutional regulatory floor. Legal hold capabilities (the ability to suspend deletion for specific clinicians or patients during litigation) must be configurable.

**Cost monitoring per clinician and per intent.** Different clinicians use the system at very different rates; different intents have very different per-command costs. Per-clinician and per-intent cost dashboards let operations identify outliers and tune accordingly.

**Operational ownership.** The system sits at the intersection of clinical operations (intent taxonomy, read-write classification, training), IT (Lambda code, infrastructure, EHR integration), clinical informatics (mapping commands to EHR operations), and compliance (audit retention, BAA scope). Establish clear ownership at the start. Without it, the system drifts and the metrics are not reviewed.

---

## Variations and Extensions

**Wake-word activation as a phase-two enhancement.** After the push-to-talk MVP has stabilized, add an optional wake-word path for clinicians who prefer fully hands-free operation. The wake word should be carefully chosen (unlikely to occur in normal clinical speech, easily distinguishable from common medical terminology). The architectural extension is the wake-word detection model (typically on-device for privacy and latency reasons), the activation flow that hands off from wake-word detection to the streaming ASR, and the audit-log handling that captures wake-word events distinct from intentional commands.

**Foot-pedal activation for hands-on clinical work.** Procedural environments (operating rooms, interventional suites) often cannot support either button press or wake word reliably. Foot pedals provide explicit activation that does not require a free hand. The architectural extension is the foot-pedal hardware integration (typically USB or Bluetooth HID) and the activation flow that treats foot-pedal events the same as button events.

**Per-clinician custom vocabulary and speaker adaptation.** Clinicians use the system every day, generating ample data for per-clinician adaptation. The extension adds per-clinician custom vocabulary lists (the names of the patients on their panel, the medications they prescribe most, the providers they refer to most) and optional speaker-adaptive ASR. The trade-off is operational complexity and per-clinician data governance; the upside is meaningful accuracy improvement for the specific clinicians using the system.

**LLM-based command suggestion.** When the clinician opens a chart section, an LLM trained on the institution's command patterns and the patient's current context can suggest likely next commands ("you're looking at recent labs; the next command is usually 'open the most recent imaging,' say it now or ignore"). The architectural extension is the suggestion service, the per-clinician learning loop, and the careful UX that suggests without nagging.

**Voice-driven order entry with multi-step confirmation.** Once read-only navigation is mature, a careful expansion into specific low-risk write commands becomes feasible: marking tasks complete, acknowledging results, and (with extreme rigor) drafting medication orders for clinician review and signature. The architectural extension is the order-draft creation workflow, the explicit-non-voice confirmation flow, and the deeper audit trail. Recipe boundary: voice-driven medication-order signature is out of scope for this recipe; the dictation and CPOE recipes (10.4 and beyond) handle that more carefully.

**Multi-language navigation.** Add Spanish (or other languages relevant to the practice's clinician demographics). Per-language ASR configuration, per-language Lex bots, per-language intent example utterances, per-language slot extraction. The clinician experience should support per-clinician language preference, with the system switching seamlessly between languages based on the active clinician.

**Integration with ambient documentation (recipe 10.7).** When ambient documentation is also deployed, the navigation system can hand off context: "open the operative note from October" issued during an ambient-documentation session pulls the note into the documentation interface as a reference document, rather than navigating away from the documentation. The architectural extension is the inter-product context-sharing API and the careful handling of overlapping audio streams.

**EHR-to-EHR command portability.** A clinician who works at multiple institutions (or a system that operates multiple EHRs) wants the same command set to work across all of them. The extension is an EHR-vendor-agnostic intent layer with vendor-specific execution adapters: the intent "show last labs" maps to a Cerner-specific implementation when the active EHR is Cerner, an Epic-specific implementation when the active EHR is Epic, and so on.

**Voice-driven schedule navigation across days.** Beyond the in-encounter navigation this recipe focuses on, the same activation and parsing infrastructure supports schedule-level navigation: "show me tomorrow's schedule," "open the chart for my next patient," "show me Mrs. Davis's chart from her last visit." The architectural extension is the schedule-API integration and the slot extraction for schedule-relative time references.

**Eye-tracking integration for context-aware commands.** When eye tracking is available (some clinical workstations include it), the system can disambiguate commands based on what the clinician is looking at: "show last labs" issued while looking at the medications panel might mean "show the labs related to medication monitoring." The architectural extension is the eye-tracking integration and the context-aware slot resolution that uses gaze location as a slot.

**Real-time clinical decision support hooks.** When voice commands surface specific data (a lab result, a medication), CDS hooks can fire alongside: an abnormal potassium result triggers a CDS alert about the patient's ACE inhibitor; a medication-related command triggers an interaction check. The architectural extension is the CDS Hooks integration and the careful UX that surfaces alerts without overwhelming the clinician.

**Compliance reporting and proactive disparity detection.** Per-clinician usage telemetry combined with per-patient outcome data lets the institution detect whether voice-navigation adoption correlates with quality metrics. The dashboard surfaces adoption gaps (clinicians who never use the system), clinical-outcome correlations, and disparities (does the system work equally well across the practice's clinician demographics?). The architectural extension is the analytics layer and the privacy-preserving design that surfaces patterns without exposing individual clinician performance to other clinicians inappropriately.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Transcribe Streaming Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/streaming.html)
- [Amazon Transcribe Custom Vocabulary](https://docs.aws.amazon.com/transcribe/latest/dg/custom-vocabulary.html)
- [Amazon Transcribe Medical Developer Guide](https://docs.aws.amazon.com/transcribe/latest/dg/transcribe-medical.html)
- [Amazon Lex V2 Developer Guide](https://docs.aws.amazon.com/lexv2/latest/dg/what-is.html)
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon API Gateway WebSocket APIs](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-websocket-api.html)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-transcribe-streaming-app`](https://github.com/aws-samples/amazon-transcribe-streaming-app): streaming Transcribe integration patterns useful for voice-command capture
- [`aws-samples/aws-lex-web-ui`](https://github.com/aws-samples/aws-lex-web-ui): Lex web client patterns relevant to in-browser voice interfaces
- [`aws-samples/amazon-lex-bi-directional-channel-using-websockets-with-amazon-lex`](https://github.com/aws-samples/amazon-lex-bi-directional-channel-using-websockets-with-amazon-lex): bidirectional voice channel patterns
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including classification and structured output extraction
- [`aws-samples/amazon-comprehend-medical-samples`](https://github.com/aws-samples/amazon-comprehend-medical-samples): medical-entity extraction patterns useful for slot canonicalization
<!-- TODO: confirm the current names and locations of these repos at time of build; the AWS sample repo organization changes over time -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences plus Conversational AI): browse for healthcare-voice and conversational-AI reference architectures
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "voice," "Transcribe Medical," "EHR integration" for relevant deep-dives
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "Lex," "Transcribe," "voice assistant" for relevant case studies
<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs -->

**External References (Standards and Frameworks):**
- [HL7 FHIR Specification](https://www.hl7.org/fhir/): the data model and API substrate for modern EHR integration
- [SMART on FHIR](https://docs.smarthealthit.org/): the launch-context and authorization specification for clinically-aware EHR apps
- [SMART App Launch Framework](https://hl7.org/fhir/smart-app-launch/): the formal specification for SMART app launch with clinician and patient context
- [FHIR R4 Resource Reference](https://www.hl7.org/fhir/R4/resourcelist.html): the resource catalog used by most production EHR FHIR APIs in 2026 <!-- TODO: verify; the dominant FHIR version varies by EHR vendor and continues to advance from R4 toward R5 -->
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in voice command audio, transcripts, and audit logs
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards for ePHI access channels
- [21st Century Cures Act and ONC Information Blocking Rules](https://www.healthit.gov/curesrule/): regulatory context for EHR API access and third-party app integration <!-- TODO: confirm current URL at time of build -->
- [HL7 CDS Hooks](https://cds-hooks.hl7.org/): the standard for EHR-triggered clinical-decision-support hooks, relevant to the CDS extension above

**Industry Resources:**
- [HIMSS resources on EHR usability and clinician burden](https://www.himss.org/): industry-association content on the EHR-as-clinical-burden problem that this recipe addresses <!-- TODO: confirm specific URL at time of build -->
- [JAMIA (Journal of the American Medical Informatics Association) literature on voice in clinical workflows](https://academic.oup.com/jamia): peer-reviewed research on voice technology adoption in clinical environments <!-- TODO: confirm current URL at time of build -->

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single-EHR integration (one vendor's FHIR API, SMART on FHIR launch), single-language (English), 8-12 core navigation intents (open patient, switch chart section, show recent results, open recent note, navigate schedule, go back), push-to-talk activation, basic disambiguation flow, basic audit logging, no write operations, single-device pilot with 3-5 clinicians | 2-4 months |
| Production-ready | Read-only command set covering 20-30 common intents, comprehensive disambiguation flows for patient-name and date slots, per-clinician custom vocabulary, sub-2-second end-to-end latency, full HIPAA-grade audit with EHR-side audit-overlay integration, clinical-operations governance of intent taxonomy and read-write classification, subgroup-stratified accuracy monitoring, structured clinician training and rollout playbook, on-call support for the first weeks of broader deployment | 6-12 months |
| With variations | Wake-word activation, foot-pedal integration, per-clinician speaker adaptation, LLM-based command suggestion, voice-driven low-risk write commands with explicit non-voice confirmation, multi-language support, ambient-documentation integration, multi-EHR-vendor support with SMART-on-FHIR substrate, eye-tracking-aware context resolution, CDS Hooks integration | 6-12 months beyond production-ready |

---


---

*← [Main Recipe 10.3](chapter10.03-voice-to-text-ehr-navigation) · [Python Example](chapter10.03-python-example) · [Chapter Preface](chapter10-preface)*
