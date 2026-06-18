# Recipe 11.8 Architecture and Implementation: Mental Health Support Bot

*Companion to [Recipe 11.8: Mental Health Support Bot](chapter11.08-mental-health-support-bot). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Bedrock for the LLM and embeddings.** Same selection criteria as recipes 11.1 through 11.7. The mental-health support bot specifically benefits from a model with strong instruction-following for scope discipline, strong tool-use, conversational warmth that does not slide into companion-pattern, and good multilingual support. Claude Sonnet-class models or comparable frontier models for the orchestration; smaller models for intent classification, crisis-screening pre-filtering, and routine summarization. Bedrock provides HIPAA-eligible deployment under BAA. Note that for mental-health workloads specifically, the model selection should account for the importance of refusing therapy-flavored conversations gracefully and the importance of avoiding companion-pattern drift in extended interactions.

**Amazon Bedrock Knowledge Bases for the therapeutic-content and psychoeducation corpus.** The institution's curated therapeutic-content library (CBT modules, behavioral-activation exercises, mindfulness practices, distress-tolerance skills, journaling prompts, sleep-hygiene content, condition-specific psychoeducation) is the bot's grounded retrieval source. Knowledge Bases provides the managed RAG layer with metadata-filtered retrieval (modality, indication, contraindication, audience, language, reading level, version).

**Amazon Bedrock Agents for tool orchestration.** Same selection rationale as recipes 11.2 through 11.7. The bot's tools (therapeutic_content_retrieve, safety_plan_retrieve, symptom_tracking_retrieve, symptom_log_record, clinical_rule_compute, conversation_history_retrieve, crisis_resource_retrieve, warm_handoff_propose, care_team_alert_propose, mandatory_report_route, longitudinal_disclosure_record) are defined as Agents action groups with OpenAPI schemas.

**Amazon Bedrock Guardrails for scope and content filtering.** Configured with denied topics including therapy-attempted, diagnosis-attempted, medication-recommendation-attempted, trauma-processing-attempted, companion-pattern-content (simulating friendship, affection, romantic interest), pro-self-harm content, pro-eating-disorder content, harmful-coping-strategy endorsement, and adult-content (where the platform is general-audience). The mental-health bot's scope discipline is critical because the consequences of scope violations are particularly serious.

**Amazon OpenSearch Service (or Bedrock-managed vector store) for the retrieval indices.** The therapeutic-content corpus, the psychoeducation library, the safety-plan content, and the longitudinal conversation history all benefit from vector retrieval.

**AWS HealthLake for FHIR-native chart-context data (where consent permits).** Where the institution stores the patient's problem list, medication list, allergies, encounter history, and CarePlan resources (potentially including safety plans) in FHIR, HealthLake provides a managed FHIR data store the bot queries. Mental-health data has specific consent considerations; the bot accesses chart context only with documented patient consent.

**Amazon DynamoDB for state and longitudinal store.** Multiple tables supporting the bot's longitudinal pattern: `patient-longitudinal-store` (per-patient stable state including stated preferences, safety-plan reference, consent posture), `conversation-state` (per-conversation transient state), `conversation-metadata` (per-conversation turn-by-turn data), `tool-call-ledger` (audited tool invocations), `support-decision-record-journal` (durable record of support events with citations), `crisis-event-record` (crisis-screening events with structured payloads), `warm-handoff-queue` (handoffs pending licensed-clinician pickup), `symptom-tracking-store` (longitudinal mood and symptom data), `sensitive-disclosure-store` (separately-governed sensitive disclosures with restricted access), and `consent-record` (consent posture per patient with audit trail).

**Amazon S3 for therapeutic-content corpus, psychoeducation library, conversation archive, support-decision-record journal, sensitive-disclosure archive, and outcome-correlation data.** Object Lock in compliance mode for the retention window, with mental-health-specific retention sized to state-specific mental-health-record retention rules.

**AWS Lambda for the conversation handler, tool implementations, crisis-screening classifier wrapping, warm-handoff routing, care-team reporting, and outcome correlation.** Same pattern as the previous chapter 11 recipes.

**Amazon API Gateway and AWS WAF for the public chat endpoint.** Same as the other recipes.

**Amazon Connect for warm-handoff to licensed clinicians.** The platform's licensed-clinician workforce is reachable via Connect for chat handoff, voice handoff (where supported), and routing to crisis-line counselors. Connect's queue-and-route capabilities support the warm-handoff pattern with conversation context attached.

**Amazon Pinpoint for crisis-resource notifications.** Where the bot needs to surface crisis resources via SMS or push notification (e.g., reminder of 988 access), Pinpoint provides the per-channel orchestration with delivery-status tracking.

**Amazon EventBridge for the bot-event bus.** Events including patient_enrolled, conversation_completed, crisis_screen_triggered, warm_handoff_initiated, warm_handoff_completed, sensitive_disclosure_recorded, mandatory_report_routed, symptom_log_recorded, care_team_alert_generated, support_decision_recorded.

**AWS Step Functions for warm-handoff workflows.** The warm-handoff process runs as a Step Functions workflow with states for handoff initiation, clinician acknowledgment, bridge-and-stay-present, handoff completion, and audit recording.

**AWS KMS, AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena.** Same operational and audit primitives as the previous recipes, with mental-health-specific KMS key separation for the sensitive-disclosure surface and for the crisis-event-record store.

**Amazon QuickSight for clinical, operational, and outcome dashboards.** Per-cohort engagement and attrition dashboards, crisis-screening rate dashboards, warm-handoff completion dashboards, companion-pattern-violation dashboards, symptom-trajectory dashboards.

**Amazon SageMaker (optional) for crisis-screening classifier hosting.** When the institution trains a custom classifier for crisis screening (often appropriate given the importance of false-negative-rate calibration), SageMaker provides the hosted-inference endpoint.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Channels
      WEB[Web Chat]
      APP[Institution App]
      SMS[SMS via Pinpoint/Connect]
      VOICE[Voice via Connect]
    end

    subgraph Edge
      WAF[AWS WAF]
      APIGW[API Gateway]
    end

    subgraph Conversation_Core
      L_CHAT[Lambda<br/>chat handler]
      L_INPUT[Lambda<br/>input screening<br/>+ continuous crisis screen]
      L_OUTPUT[Lambda<br/>output screening<br/>+ companion pattern verify]
      L_HANDOFF[Lambda<br/>warm handoff routing]
      L_IDENTITY[Lambda<br/>identity + longitudinal<br/>context loading]
      L_CRISIS[Lambda<br/>crisis classifier wrapper]
    end

    subgraph LLM_and_Agent
      AGENT[Bedrock Agents]
      BEDROCK[Bedrock<br/>LLM generation]
      KB_THERAPY[Bedrock Knowledge Bases<br/>therapeutic content]
      KB_PSYCHOED[Bedrock Knowledge Bases<br/>psychoeducation]
      KB_HIST[Bedrock Knowledge Bases<br/>conversation history]
      GUARDRAILS[Bedrock Guardrails]
      OS[OpenSearch Serverless]
      SAGEMAKER[SageMaker<br/>crisis classifier]
    end

    subgraph Support_Tools
      L_THERAPY[Lambda<br/>therapeutic_content_retrieve]
      L_SAFETY[Lambda<br/>safety_plan_retrieve]
      L_SYMPTOM[Lambda<br/>symptom_tracking_retrieve]
      L_SYMP_LOG[Lambda<br/>symptom_log_record]
      L_RULE[Lambda<br/>clinical_rule_compute]
      L_CONV_HIST[Lambda<br/>conversation_history_retrieve]
      L_CRISIS_RES[Lambda<br/>crisis_resource_retrieve]
      L_HANDOFF_TOOL[Lambda<br/>warm_handoff_propose]
      L_ALERT[Lambda<br/>care_team_alert_propose]
      L_REPORT_TOOL[Lambda<br/>mandatory_report_route]
      L_DISCLOSE[Lambda<br/>longitudinal_disclosure_record]
    end

    subgraph Warm_Handoff
      SFN[Step Functions<br/>warm handoff workflow]
      CONNECT[Amazon Connect<br/>licensed clinician queue]
      L_CLIN_NOTIFY[Lambda<br/>clinician notification]
    end

    subgraph External_Integrations
      EHR[(EHR / FHIR)]
      HEALTHLAKE[(AWS HealthLake)]
      CARE_TEAM[(Patient's care team<br/>therapist, psychiatrist, PCP)]
      CRISIS_988[(988 Crisis Lifeline)]
      INST_CRISIS[(Institutional crisis line)]
      MR_PATHWAY[(Mandatory reporter<br/>routing)]
      NAV[(Care navigation)]
    end

    subgraph State_and_Audit
      DDB_LONG[(DynamoDB<br/>longitudinal store)]
      DDB_SESS[(DynamoDB<br/>conversation state)]
      DDB_META[(DynamoDB<br/>conversation metadata)]
      DDB_TOOL[(DynamoDB<br/>tool-call ledger)]
      DDB_DECISION[(DynamoDB<br/>support-decision<br/>record journal)]
      DDB_CRISIS[(DynamoDB<br/>crisis event record)]
      DDB_HANDOFF[(DynamoDB<br/>warm handoff queue)]
      DDB_SYMPTOM[(DynamoDB<br/>symptom tracking)]
      DDB_SENSITIVE[(DynamoDB<br/>sensitive disclosure)]
      DDB_CONSENT[(DynamoDB<br/>consent record)]
      S3_THERAPY[(S3<br/>therapeutic content)]
      S3_PSYCHOED[(S3<br/>psychoeducation)]
      S3_AUDIT[(S3<br/>audit archive)]
      S3_DECISION[(S3<br/>decision-record<br/>journal)]
      S3_SENSITIVE[(S3<br/>sensitive disclosure<br/>archive)]
    end

    subgraph Reporting_and_Analytics
      L_REPORT[Lambda<br/>care-team reporting]
      L_OUTCOME[Lambda<br/>outcome correlation]
      EB[EventBridge]
      KIN[Kinesis Firehose]
      ATH[Athena]
      QS[QuickSight]
      CW[CloudWatch]
      CT[CloudTrail]
    end

    subgraph Secrets_and_Keys
      SM_SEC[(Secrets Manager)]
      KMS[(AWS KMS)]
      KMS_SENSITIVE[(KMS<br/>sensitive disclosure key)]
    end

    WEB --> WAF
    APP --> WAF
    SMS --> APIGW
    VOICE --> APIGW
    WAF --> APIGW
    APIGW --> L_CHAT

    L_CHAT --> L_INPUT
    L_INPUT --> L_CRISIS
    L_CRISIS --> SAGEMAKER
    L_INPUT --> L_HANDOFF
    L_CHAT --> L_IDENTITY
    L_CHAT --> AGENT
    AGENT --> BEDROCK
    AGENT --> KB_THERAPY
    AGENT --> KB_PSYCHOED
    AGENT --> KB_HIST
    KB_THERAPY --> OS
    KB_PSYCHOED --> OS
    KB_HIST --> OS
    AGENT --> GUARDRAILS
    AGENT --> L_THERAPY
    AGENT --> L_SAFETY
    AGENT --> L_SYMPTOM
    AGENT --> L_SYMP_LOG
    AGENT --> L_RULE
    AGENT --> L_CONV_HIST
    AGENT --> L_CRISIS_RES
    AGENT --> L_HANDOFF_TOOL
    AGENT --> L_ALERT
    AGENT --> L_REPORT_TOOL
    AGENT --> L_DISCLOSE
    L_SAFETY --> EHR
    L_SAFETY --> HEALTHLAKE
    L_CHAT --> L_OUTPUT
    L_OUTPUT --> L_HANDOFF
    L_HANDOFF --> SFN
    SFN --> CONNECT
    SFN --> L_CLIN_NOTIFY
    L_HANDOFF --> CRISIS_988
    L_HANDOFF --> INST_CRISIS
    L_HANDOFF --> MR_PATHWAY
    L_HANDOFF --> CARE_TEAM
    L_HANDOFF --> NAV
    L_CHAT --> DDB_SESS
    L_CHAT --> DDB_META
    L_CHAT --> DDB_LONG
    L_CHAT --> DDB_CONSENT
    AGENT --> DDB_TOOL
    L_OUTPUT --> DDB_DECISION
    L_OUTPUT --> S3_DECISION
    L_HANDOFF --> DDB_HANDOFF
    L_HANDOFF --> DDB_CRISIS
    L_DISCLOSE --> DDB_SENSITIVE
    DDB_SENSITIVE --> S3_SENSITIVE
    L_OUTCOME --> S3_AUDIT
    L_REPORT --> CARE_TEAM
    L_CHAT --> EB
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> ATH
    S3_DECISION --> ATH
    ATH --> QS
    L_CHAT --> CW
    APIGW --> CT
    L_SAFETY --> SM_SEC
    KMS --> S3_AUDIT
    KMS --> S3_DECISION
    KMS --> S3_THERAPY
    KMS --> S3_PSYCHOED
    KMS_SENSITIVE --> S3_SENSITIVE
    KMS_SENSITIVE --> DDB_SENSITIVE
    KMS --> DDB_LONG
    KMS --> DDB_SESS
    KMS --> DDB_META
    KMS --> DDB_TOOL
    KMS --> DDB_DECISION
    KMS --> DDB_CRISIS
    KMS --> DDB_HANDOFF
    KMS --> DDB_SYMPTOM
    KMS --> DDB_CONSENT
    KMS --> SM_SEC

    style AGENT fill:#fcf,stroke:#333
    style BEDROCK fill:#fcf,stroke:#333
    style KB_THERAPY fill:#fcf,stroke:#333
    style KB_PSYCHOED fill:#fcf,stroke:#333
    style KB_HIST fill:#fcf,stroke:#333
    style GUARDRAILS fill:#fcf,stroke:#333
    style L_INPUT fill:#fcc,stroke:#900,stroke-width:3px
    style L_OUTPUT fill:#fcc,stroke:#900,stroke-width:3px
    style L_HANDOFF fill:#fcc,stroke:#900,stroke-width:3px
    style L_CRISIS fill:#fcc,stroke:#900,stroke-width:3px
    style EHR fill:#ccf,stroke:#333
    style HEALTHLAKE fill:#ccf,stroke:#333
    style CARE_TEAM fill:#ccf,stroke:#333
    style CRISIS_988 fill:#ccf,stroke:#900,stroke-width:3px
    style INST_CRISIS fill:#ccf,stroke:#333
    style MR_PATHWAY fill:#ccf,stroke:#333
    style DDB_LONG fill:#9ff,stroke:#333,stroke-width:3px
    style DDB_DECISION fill:#9ff,stroke:#333
    style DDB_CRISIS fill:#9ff,stroke:#900,stroke-width:3px
    style DDB_SENSITIVE fill:#9ff,stroke:#900,stroke-width:3px
    style S3_DECISION fill:#cfc,stroke:#333
    style S3_SENSITIVE fill:#cfc,stroke:#900,stroke-width:3px
    style KMS_SENSITIVE fill:#fcc,stroke:#900,stroke-width:3px
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Bedrock (Agents, Knowledge Bases, Guardrails, foundation model with strong tool-use, embedding model), Amazon OpenSearch Serverless, AWS HealthLake (where chart-context integration is consented), AWS Lambda, AWS Step Functions, Amazon API Gateway, AWS WAF, Amazon DynamoDB, Amazon S3, AWS KMS (with separate keys for sensitive-disclosure surface), AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon EventBridge, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon Pinpoint, Amazon Connect (warm-handoff to licensed clinicians), Amazon QuickSight (dashboards). Optionally: Amazon SageMaker (custom crisis-screening classifier hosting). |
| **External Inputs** | EHR or FHIR-native chart-context where consent permits (Patient, Condition, MedicationStatement, AllergyIntolerance, Encounter, CarePlan including safety plans). Therapeutic-content library curated and version-controlled by behavioral-health clinical leadership, drawing from manualized treatment protocols (CBT, behavioral activation, DBT skills, ACT, mindfulness practices) with defined indications and contraindications. Psychoeducation content library reviewed by behavioral-health clinical leadership and patient-experience leadership, multilingual and multi-reading-level. Validated crisis-screening instrument language adapted from C-SSRS, PHQ-9, GAD-7, AUDIT and similar instruments with clinical-leadership review. Safety-plan template (Stanley-Brown safety planning intervention or similar evidence-based template, instantiated per patient with their clinician) where one is on file. Licensed-clinician workforce capacity (employed or contracted) sized to expected handoff volume. 988 Suicide and Crisis Lifeline routing integration. Institutional crisis-line integration. Mandatory-reporting-pathway integration. Care-navigation integration for social-determinants concerns. Consent-management integration with state-specific mental-health-privacy compliance. |
| **IAM Permissions** | Per-Lambda least-privilege roles. The therapeutic-content-retrieve Lambda has read access to the therapeutic-content corpus. The safety-plan-retrieve Lambda has read access to the EHR or HealthLake (consent-gated). The symptom-log-record Lambda has write access to the symptom-tracking store. The longitudinal-disclosure-record Lambda has write access to the sensitive-disclosure store with separately-keyed encryption. The crisis-event recording Lambda has write access to the crisis-event store. The warm-handoff Lambda has write access to the warm-handoff queue and read access to clinician availability. The mandatory-report-route Lambda has write access to the mandatory-reporting pathway. None of the bot's Lambdas have write access to the clinical record except for institutionally-approved support-event records (e.g., FHIR Communication resources for the conversation log; FHIR Observation resources for symptom-tracking data where the institution permits bot-originated observations; with explicit patient consent). Resource-based policies pin invoking principals to the production agent and API Gateway stage ARNs. |
| **BAA and Compliance** | AWS BAA signed. Verify all services in scope are HIPAA-eligible at build time. The bot is patient-facing PHI of the most sensitive variety. Mental-health records have specific privacy considerations that exceed HIPAA baseline in some states; legal counsel familiar with state-specific mental-health-record statutes reviews the data-handling posture. The institutional regulatory team reviews the FDA-strategy positioning before launch and on each material scope change. The institutional malpractice insurer is part of the policy review. State-specific regulations on AI-mediated mental-health communication, on telehealth, on crisis intervention, and on minor consent (where the platform serves any minors) may apply. <!-- TODO: verify; mental-health-specific privacy regulations include 42 CFR Part 2 for substance-use treatment records, state-specific mental-health-record statutes that often exceed HIPAA baseline, and FDA SaMD framework where applicable; specific compliance obligations vary --> |
| **Encryption** | Therapeutic-content corpus, psychoeducation library, conversation archive, support-decision-record journal: SSE-KMS with customer-managed keys. Sensitive-disclosure archive: SSE-KMS with separately-managed customer key for blast-radius containment. Crisis-event record: SSE-KMS with separately-managed customer key. S3 archives: Object Lock in compliance mode for the retention window. DynamoDB tables: customer-managed KMS at rest, with mental-health-specific tables on separate keys. Lambda environment variables: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all AWS API calls and all integrations with external systems. |
| **VPC** | Production: tool Lambdas that call EHR, care-team workflows, mandatory-reporting pathways, crisis-line integrations, and care-navigation systems run in VPC with controlled egress. PrivateLink to vendor-hosted endpoints where supported; tightly-scoped NAT path with allow-list otherwise. VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, OpenSearch Serverless, HealthLake, Step Functions, Pinpoint, Connect, and SageMaker (where used). The patient-facing edge is public; the back-office traffic is private. |
| **CloudTrail** | Enabled with data events on all sensitive S3 buckets (audit-archive, support-decision-record-journal, sensitive-disclosure archive, therapeutic-content corpus, psychoeducation library) and DynamoDB tables (longitudinal store, support-decision-record journal, sensitive-disclosure store, crisis-event record, etc.), Secrets Manager secrets, and customer-managed KMS keys. Bedrock and Bedrock Agents invocations logged. Lambda invocations logged. API Gateway access logs enabled. Step Functions execution logs enabled. Connect interactions logged with appropriate retention. CloudTrail logs in a dedicated S3 bucket with Object Lock in compliance mode. Audit retention sized to the longest of HIPAA's six-year minimum, state-specific mental-health-record retention rules, and FDA SaMD post-market obligations where applicable. |
| **Sample Data** | Synthetic patient profiles stratified by mental-health condition, by severity, by age cohort, by sex, by language, by socioeconomic context, by engagement profile (high engagement, low engagement, attrition risk, crisis-disclosure profile). Synthetic safety plans following the Stanley-Brown template or similar. Synthetic conversation histories covering long-running engagement, attrition patterns, sensitive disclosures, crisis-screening triggers, mandatory-reporting disclosures, and warm-handoff scenarios. Validated therapeutic-content corpus reviewed by behavioral-health clinical leadership and patient-experience leadership. Validated translations of all patient-facing content reviewed by language-services team and behavioral-health clinical leadership. Test EHR, care-team-workflow, crisis-line, mandatory-reporting, and care-navigation systems with synthetic data. |
| **Cost Estimate** | At a mid-sized employer or payer scale (25,000 active engaged members; average 1-3 conversational engagements per week per active member; average 5-12 turns per engagement; average 2,000 tokens of prompt and 400 tokens of response per turn for the orchestration model plus tool-call overhead; plus crisis-screening classifier inference on every utterance): Bedrock LLM invocations typically $4-9 per active member per month for a Sonnet-class orchestration model, totaling approximately $1.2M-2.7M per year. Bedrock Agents and Knowledge Bases hosting plus the OpenSearch Serverless retrieval indices typically $40,000-150,000 per year. Lambda, API Gateway, WAF, DynamoDB, S3, KMS, Secrets Manager, CloudWatch, CloudTrail, EventBridge, Kinesis Firehose, Glue, Athena, Step Functions total approximately $80,000-300,000 per year combined. AWS HealthLake (when used) typically $30,000-150,000 per year. Pinpoint typically $10,000-50,000 per year. Connect for warm-handoff queue and licensed-clinician routing typically $80,000-300,000 per year (cost varies substantially with handoff volume and clinician staffing model). SageMaker (when used for custom crisis classifier) typically $20,000-80,000 per year. Total AWS infrastructure typically $1.5M-3.7M per year at this scale (approximately $5-12 per active member per month). The licensed-clinician workforce cost (employed or contracted) is typically larger than the AWS infrastructure cost and is the dominant operational expense; a deployment that under-invests in licensed-clinician capacity is a deployment with safety gaps. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator; specific costs depend on Bedrock model choice, conversation volume, handoff rate, FHIR-source choice, and channel mix --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Bedrock** | LLM for orchestration and conversational response generation; embedding model for the therapeutic-content corpus, psychoeducation library, and conversation history |
| **Amazon Bedrock Agents** | Tool orchestration: define support tools as action groups, manage the multi-step LLM-and-tool flow |
| **Amazon Bedrock Knowledge Bases** | Managed RAG over (a) therapeutic content, (b) psychoeducation library, (c) longitudinal conversation history. Metadata-filtered retrieval (modality, indication, contraindication, audience, language, reading level, version) |
| **Amazon OpenSearch Serverless** | Vector and lexical retrieval index backing each Knowledge Base |
| **Amazon Bedrock Guardrails** | Content filtering for therapy-attempted, diagnosis-attempted, medication-recommendation-attempted, trauma-processing-attempted, companion-pattern-content, pro-self-harm content, pro-eating-disorder content, harmful-coping-strategy endorsement |
| **AWS Lambda** | Chat handler, input/output screening, identity-and-longitudinal-context loading, warm-handoff routing, crisis-classifier wrapping, care-team reporting, outcome correlation, and tool implementations (therapeutic_content_retrieve, safety_plan_retrieve, symptom_tracking_retrieve, symptom_log_record, clinical_rule_compute, conversation_history_retrieve, crisis_resource_retrieve, warm_handoff_propose, care_team_alert_propose, mandatory_report_route, longitudinal_disclosure_record) |
| **AWS Step Functions** | Warm-handoff workflows with states for handoff initiation, clinician acknowledgment, bridge-and-stay-present, completion, and audit recording |
| **Amazon API Gateway** | Public-facing chat endpoint for web, app, SMS, and voice channels |
| **AWS WAF** | Rate limiting, bot detection, common attack patterns |
| **Amazon DynamoDB** | patient-longitudinal-store, conversation-state, conversation-metadata, tool-call-ledger, support-decision-record-journal, crisis-event-record, warm-handoff-queue, symptom-tracking-store, sensitive-disclosure-store (separately keyed), consent-record |
| **Amazon S3** | Therapeutic-content corpus, psychoeducation library, conversation archive, support-decision-record journal, sensitive-disclosure archive (separately keyed), outcome-correlation data |
| **AWS HealthLake** | FHIR-native chart context (Patient, Condition, MedicationStatement, AllergyIntolerance, Encounter, CarePlan including safety plans), consent-gated |
| **AWS KMS** | Customer-managed encryption keys per data class, with separate keys for sensitive-disclosure surface and crisis-event record |
| **AWS Secrets Manager** | Credentials for EHR, care-team workflow systems, crisis-line integrations, mandatory-reporting-pathway integrations, care-navigation systems |
| **Amazon CloudWatch** | Operational metrics (engagement rate, attrition rate, crisis-screening sensitivity, crisis-screening specificity, warm-handoff completion rate, companion-pattern-violation rate, citation-coverage rate, per-condition outcome trajectories, per-cohort slices); alarms |
| **AWS CloudTrail** | API-level audit logging |
| **Amazon EventBridge** | Bot-event bus (patient_enrolled, conversation_completed, crisis_screen_triggered, warm_handoff_initiated, warm_handoff_completed, sensitive_disclosure_recorded, mandatory_report_routed, symptom_log_recorded, care_team_alert_generated, support_decision_recorded) |
| **Amazon Pinpoint** | Crisis-resource notification (push, SMS) with delivery-status tracking |
| **Amazon Connect** | Warm-handoff queue for licensed clinicians (chat and voice), routing integration with crisis-line counselors |
| **Amazon Kinesis Data Firehose** | Streaming audit and telemetry delivery |
| **AWS Glue Data Catalog + Amazon Athena** | SQL access to audit, decision-record, sensitive-disclosure (restricted access), and telemetry data |
| **Amazon SageMaker (where used)** | Hosted custom crisis-screening classifier inference |
| **Amazon QuickSight** | Clinical, operational, and outcome dashboards |

---

### Code

#### Walkthrough

**Step 1: Enroll the patient and capture mental-health-specific consent.** Enrollment requires explicit consent that has been reviewed by behavioral-health legal counsel and clinical leadership. The consent flow is not generic terms-of-service; it covers the bot's nature (chat tool, not a person, not a therapist), the bot's scope (structured therapeutic-content delivery, mood tracking, crisis screening, warm handoff), the privacy posture (specifically including state-specific mental-health-record protections where they exceed HIPAA baseline), the crisis-pathway behavior (988, institutional crisis line, 911), and the data-sharing posture with the patient's care team (collected separately and revocable). Skip this step or treat it as boilerplate, and the entire deployment's clinical and regulatory posture is compromised.

```pseudocode
ON enroll_patient(patient_id, target_population_segment,
                  legal_consent_form_signed,
                  state_of_residence):
    // Step 1A: validate the patient is eligible for the
    // institution's deployment scope.
    eligibility = check_eligibility({
        patient_id: patient_id,
        target_population_segment: target_population_segment,
        excluded_populations: INSTITUTION_EXCLUDED_POPULATIONS
            // typically: minors (in adult-only deployments),
            // patients with primary psychotic-spectrum
            // diagnoses, patients in active inpatient or
            // residential treatment, others per institutional
            // clinical-leadership policy
    })

    IF NOT eligibility.eligible:
        return {
            action: "enrollment_declined",
            reason: eligibility.reason,
            referral: eligibility.recommended_alternative
        }

    // Step 1B: present mental-health-specific consent
    // language reviewed by legal counsel and clinical
    // leadership.
    state_specific_consent = state_consent_registry.get(
        state: state_of_residence)

    consent_record = {
        patient_id: patient_id,
        consent_id: generate_consent_id(),
        consent_version: state_specific_consent.version,
        nature_disclosure_acknowledged: true,
        scope_disclosure_acknowledged: true,
        privacy_disclosure_acknowledged: true,
        crisis_pathway_disclosure_acknowledged: true,
        care_team_sharing_consent:
            legal_consent_form_signed.care_team_sharing,
        emergency_contact_sharing_consent:
            legal_consent_form_signed.emergency_contact,
        retention_policy_acknowledged: true,
        signed_at: now(),
        state_of_residence: state_of_residence,
        state_specific_provisions:
            state_specific_consent.provisions
    }

    consent_record_table.write(consent_record)

    // Step 1C: initialize longitudinal store with
    // mental-health-specific structure.
    longitudinal_store = {
        patient_id: patient_id,
        target_population_segment: target_population_segment,
        consent_id: consent_record.consent_id,
        active_diagnoses_consented:
            consent_record.care_team_sharing
                ? load_mental_health_diagnoses(
                    patient_id: patient_id)
                : null,
        current_medications_consented:
            consent_record.care_team_sharing
                ? load_psychiatric_medications(
                    patient_id: patient_id)
                : null,
        safety_plan_reference:
            check_safety_plan_on_file(patient_id: patient_id),
        patient_preferences: {
            preferred_name:
                legal_consent_form_signed.preferred_name,
            preferred_pronouns:
                legal_consent_form_signed.pronouns,
            language: legal_consent_form_signed.language,
            preferred_channels:
                legal_consent_form_signed.channels,
            topics_off_limits:
                legal_consent_form_signed.topics_off_limits,
            quiet_hours: legal_consent_form_signed.quiet_hours,
            engagement_intensity_preference:
                "patient_initiated_only"
                // mental-health bots default to
                // patient-initiated engagement to avoid
                // surveillance flavor; bot-initiated
                // engagement requires explicit opt-in
        },
        symptom_tracking_baseline: {},
        sensitive_disclosure_flags: [],
        crisis_history_flags:
            check_crisis_history(patient_id: patient_id),
        enrolled_at: now(),
        active: true
    }

    longitudinal_store_table.write(longitudinal_store)

    // Step 1D: emit enrollment event for downstream
    // operational tracking.
    EventBridge.PutEvents([{
        source: "mental_health_support",
        detail_type: "patient_enrolled",
        detail: {
            patient_id: patient_id,
            target_population_segment:
                target_population_segment,
            state_of_residence: state_of_residence
        }
    }])

    return {
        action: "enrolled",
        consent_id: consent_record.consent_id
    }
```

**Step 2: Handle conversation entry with disclosure refresh and identity-context loading.** Every session begins with an explicit disclosure refresh: the bot is a chat tool, not a person; not a therapist; cannot diagnose; the crisis line is reachable at any time. The disclosure refresh is more than legal coverage: it sets the relationship boundary and reinforces it across sessions. After disclosure, the bot loads the patient's longitudinal context including the safety plan if one is on file, recent symptom-tracking data, and recent conversation history. Skip the disclosure refresh and the bot drifts toward companion-pattern in extended interactions.

```pseudocode
ON receive_message(channel, channel_session_id,
                  user_message, auth_context):
    // Step 2A: identify or create the conversation
    // session.
    session = conversation_state_table.get_or_create({
        channel: channel,
        channel_session_id: channel_session_id,
        auth_context: auth_context
    })

    patient_id = session.verified_patient_id

    // Step 2B: persist the user's message.
    conversation_metadata_table.append_turn(
        session_id: session.id,
        turn: {
            speaker: "user",
            text: user_message,
            timestamp: now()
        })

    // Step 2C: input safety screening.
    screening_result = screen_input(
        session_id: session.id,
        user_message: user_message,
        domain: "mental_health_support")

    IF screening_result.action == "block":
        return handle_block(
            session_id: session.id,
            screening_result: screening_result)

    // Step 2D: continuous crisis screening (this is the
    // architectural primitive).
    crisis_check = crisis_screen(
        user_message: user_message,
        recent_turns: conversation_metadata_table
            .recent_turns(session.id, k: 8),
        crisis_history_flags:
            session.longitudinal_store
                .crisis_history_flags)

    IF crisis_check.crisis_detected:
        return handle_crisis_pathway(
            session_id: session.id,
            crisis_dimensions: crisis_check.dimensions,
            urgency: crisis_check.urgency,
            crisis_screen_result: crisis_check)

    // Step 2E: sensitive-disclosure detection.
    disclosure_check = sensitive_disclosure_screen({
        user_message: user_message,
        recent_turns: conversation_metadata_table
            .recent_turns(session.id, k: 8)
    })

    IF disclosure_check.disclosure_detected:
        handle_sensitive_disclosure(
            session_id: session.id,
            disclosure: disclosure_check)
        // Continues conversation, but flags for
        // appropriate routing (mandatory-reporting for
        // some categories; care-team alert for others;
        // warm-handoff for crisis-adjacent).

    // Step 2F: harmful-content screen.
    harm_check = harmful_content_screen(
        user_message: user_message,
        recent_turns: conversation_metadata_table
            .recent_turns(session.id, k: 8))

    IF harm_check.harm_pattern_detected:
        return handle_harm_pattern(
            session_id: session.id,
            pattern: harm_check.pattern)

    // Step 2G: load longitudinal context.
    longitudinal = longitudinal_store_table.read(
        patient_id: patient_id)
    safety_plan = safety_plan_retrieve_tool.invoke({
        patient_id: patient_id
    }) IF longitudinal.safety_plan_reference

    recent_symptom_tracking =
        symptom_tracking_retrieve_tool.invoke({
            patient_id: patient_id,
            window: 30_DAYS
        })

    recent_conversation =
        conversation_history_retrieve_tool.invoke({
            patient_id: patient_id,
            window: 90_DAYS,
            max_turns: 40
        })

    consent = consent_record_table.current_for_patient(
        patient_id: patient_id)

    session.longitudinal_context = {
        longitudinal: longitudinal,
        safety_plan: safety_plan,
        recent_symptom_tracking: recent_symptom_tracking,
        recent_conversation: recent_conversation,
        consent: consent
    }

    // Step 2H: disclosure refresh (every session, not
    // just first session).
    IF session.requires_disclosure_refresh():
        deliver_disclosure_refresh(
            session_id: session.id,
            preferred_name:
                longitudinal.patient_preferences
                    .preferred_name,
            language:
                longitudinal.patient_preferences.language)

    return handle_conversation(
        session_id: session.id,
        user_message: user_message)
```

**Step 3: Handle the crisis pathway when crisis screening triggers.** The crisis pathway is the most consequential response the bot ever produces. The bot does not attempt to talk a patient through an active crisis using AI alone. The bot anchors briefly (acknowledges the disclosure, validates the patient's reach-out, surfaces the immediate safety frame), identifies the crisis level (acute emergency, suicidal crisis without acute means, sensitive disclosure with crisis adjacency), routes to the appropriate human resource (911, 988, institutional crisis line, platform's licensed clinician), surfaces the patient's safety plan if applicable, and stays present until the human responder has joined. Skip this discipline or treat it as a fallback rather than a primary system component, and the bot is operating without its core safety architecture.

```pseudocode
FUNCTION handle_crisis_pathway(session_id,
                               crisis_dimensions,
                               urgency,
                               crisis_screen_result):
    session = conversation_state_table.get(session_id)
    patient_id = session.verified_patient_id

    // Step 3A: log the crisis event durably.
    crisis_event_record = {
        crisis_event_id: generate_crisis_event_id(),
        session_id: session_id,
        patient_id: patient_id,
        detected_at: now(),
        crisis_dimensions: crisis_dimensions,
            // passive_ideation, active_ideation, plan,
            // means, intent, timeline, self_harm_thoughts,
            // self_harm_behaviors, homicidal_ideation,
            // psychotic_symptoms, overdose_risk, etc.
        urgency: urgency,
            // imminent_emergency, acute_crisis, sub_acute
        screening_result: crisis_screen_result,
        active_classifier_version:
            CRISIS_CLASSIFIER_VERSION,
        active_consent_version:
            session.longitudinal_context
                .consent.consent_id
    }

    crisis_event_record_table.write(crisis_event_record)

    EventBridge.PutEvents([{
        source: "mental_health_support",
        detail_type: "crisis_screen_triggered",
        detail: {
            crisis_event_id:
                crisis_event_record.crisis_event_id,
            patient_id: patient_id,
            urgency: urgency
        }
    }])

    // Step 3B: anchor briefly (validated language, no
    // freestyling).
    anchor_response = compose_crisis_anchor_response({
        crisis_dimensions: crisis_dimensions,
        preferred_name: session.longitudinal_context
            .longitudinal
            .patient_preferences
            .preferred_name,
        language: session.longitudinal_context
            .longitudinal
            .patient_preferences
            .language,
        crisis_anchor_template:
            CRISIS_ANCHOR_TEMPLATES[urgency]
    })

    deliver_response(
        session_id: session_id,
        response: anchor_response)

    // Step 3C: route to appropriate human resource.
    IF urgency == "imminent_emergency":
        // Active emergency: 911 plus stay-on-the-line.
        deliver_response(
            session_id: session_id,
            response: build_911_routing_message({
                language: session.longitudinal_context
                    .longitudinal
                    .patient_preferences
                    .language
            }))

        warm_handoff_propose_tool.invoke({
            handoff_type: "active_emergency",
            patient_id: patient_id,
            session_id: session_id,
            crisis_event_id:
                crisis_event_record.crisis_event_id,
            target: "911_plus_platform_clinician"
        })

    ELSE IF urgency == "acute_crisis":
        // Suicidal crisis: 988 plus institutional crisis
        // line plus warm handoff to platform clinician.
        deliver_response(
            session_id: session_id,
            response: build_acute_crisis_routing_message({
                language: session.longitudinal_context
                    .longitudinal
                    .patient_preferences
                    .language,
                crisis_resources: [
                    {
                        type: "988_lifeline",
                        access: ["call", "text", "chat"]
                    },
                    {
                        type: "institutional_crisis_line",
                        access:
                            INSTITUTIONAL_CRISIS_LINE_CONFIG
                    }
                ]
            }))

        warm_handoff_propose_tool.invoke({
            handoff_type: "acute_crisis",
            patient_id: patient_id,
            session_id: session_id,
            crisis_event_id:
                crisis_event_record.crisis_event_id,
            target: "platform_clinician"
        })

    ELSE IF urgency == "sub_acute":
        // Crisis-adjacent disclosure without imminent
        // risk: warm handoff to platform clinician,
        // safety plan surfacing, support continuation.
        warm_handoff_propose_tool.invoke({
            handoff_type: "sub_acute_crisis",
            patient_id: patient_id,
            session_id: session_id,
            crisis_event_id:
                crisis_event_record.crisis_event_id,
            target: "platform_clinician_async"
        })

    // Step 3D: surface safety plan if patient has one
    // and the safety plan is relevant.
    IF session.longitudinal_context.safety_plan:
        surface_safety_plan_steps_appropriate_to_dimensions(
            session_id: session_id,
            safety_plan: session.longitudinal_context
                .safety_plan,
            crisis_dimensions: crisis_dimensions)

    // Step 3E: stay-and-bridge: the bot remains present
    // and supportive until the human responder joins,
    // but does not attempt to provide therapy or
    // process the crisis.
    bridge_state = bridge_and_stay_present({
        session_id: session_id,
        crisis_event_id:
            crisis_event_record.crisis_event_id,
        warm_handoff_pending: true,
        permitted_response_types: [
            "validation_acknowledgment",
            "safety_plan_step_surfacing",
            "grounding_skill_brief",
            "presence_check"
        ],
        forbidden_response_types: [
            "therapy_attempted",
            "trauma_processing",
            "diagnosis",
            "medication_recommendation",
            "extended_emotional_processing"
        ]
    })

    // Step 3F: care-team alert (consent-gated).
    IF session.longitudinal_context.consent
            .care_team_sharing_consent:
        care_team_alert_propose_tool.invoke({
            patient_id: patient_id,
            alert_type: "crisis_event",
            crisis_event_id:
                crisis_event_record.crisis_event_id,
            urgency: urgency,
            target_clinicians:
                resolve_care_team(patient_id: patient_id)
        })

    return {
        action: "crisis_pathway_engaged",
        crisis_event_id:
            crisis_event_record.crisis_event_id,
        bridge_state: bridge_state
    }
```

**Step 4: Generate the response with therapeutic-content-grounded reasoning, scope discipline, and companion-pattern avoidance.** The LLM operates as a Bedrock Agent with the support tool surface. The system prompt explicitly forbids the companion pattern, explicitly scopes the bot away from therapy, and grounds therapeutic content delivery in the institution's reviewed library. Tool calls retrieve specific therapeutic-content items, safety-plan elements, recent symptom-tracking data, conversation history, and clinical-rule scoring as needed. Skip the companion-pattern avoidance and the bot drifts in extended sessions; skip the scope discipline and the bot delivers therapy without being a therapist.

```pseudocode
FUNCTION handle_conversation(session_id, user_message):
    session = conversation_state_table.get(session_id)
    longitudinal_context = session.longitudinal_context

    // Step 4A: assemble system prompt with explicit
    // non-therapist scoping and companion-pattern
    // avoidance.
    system_prompt = compose_support_system_prompt({
        bot_persona: INSTITUTION_BOT_PERSONA,
        non_therapist_disclosure:
            INSTITUTION_NON_THERAPIST_LANGUAGE,
        scope_boundaries: {
            within_scope: WITHIN_SCOPE_TOPICS,
            outside_scope: OUTSIDE_SCOPE_TOPICS,
            crisis_pathway: CRISIS_PATHWAY_RULES
        },
        companion_pattern_avoidance: {
            forbidden_patterns: [
                "first_person_emotional_claims",
                "simulated_friendship",
                "simulated_affection",
                "simulated_personhood",
                "simulated_memory_of_caring",
                "romantic_or_intimate_framing"
            ]
        },
        active_diagnoses_consented:
            longitudinal_context
                .longitudinal
                .active_diagnoses_consented,
        current_medications_consented:
            longitudinal_context
                .longitudinal
                .current_medications_consented,
        safety_plan_reference:
            longitudinal_context.safety_plan,
        recent_symptom_tracking:
            longitudinal_context
                .recent_symptom_tracking,
        patient_preferences:
            longitudinal_context
                .longitudinal
                .patient_preferences,
        regulatory_position:
            INSTITUTION_REGULATORY_POSITION,
        language:
            longitudinal_context
                .longitudinal
                .patient_preferences.language
    })

    // Step 4B: invoke Bedrock Agent.
    agent_response = bedrock_agents_invoke({
        agent_id: SUPPORT_AGENT_ID,
        agent_alias_id: SUPPORT_AGENT_ALIAS_ID,
        session_id: session_id,
        input_text: user_message,
        system_prompt: system_prompt,
        recent_conversation:
            longitudinal_context.recent_conversation
    })

    // Step 4C: audit tool calls.
    FOR tool_call IN agent_response.tool_calls:
        audit_tool_call(
            session_id: session_id,
            tool: tool_call.tool_name,
            arguments: tool_call.arguments,
            result_summary:
                summarize_for_audit(
                    tool_call.result))

    // Step 4D: capture citations.
    citations = extract_citations(agent_response)

    return {
        action: "response_generated",
        response_text: agent_response.response_text,
        citations: citations,
        tool_calls: agent_response.tool_calls
    }
```

**Step 5: Run output safety with companion-pattern detection, scope verification, and citation grounding.** Every response runs through output safety before delivery. The companion-pattern detector checks for first-person emotional claims, simulated friendship, simulated affection, and simulated personhood. The scope verifier rejects responses that attempt therapy, diagnosis, or medication recommendations. The citation verifier confirms therapeutic-content delivery is grounded in cited library content. Skip this and the bot's scope discipline erodes turn by turn over extended interactions.

```pseudocode
FUNCTION screen_support_output(session_id, response,
                               citations, tool_calls):
    // Step 5A: standard output safety primitives.
    standard_check = standard_output_screen.evaluate(
        response: response,
        session_context:
            session_context_for(session_id))

    IF standard_check.action != "deliver":
        return standard_check

    // Step 5B: scope checks specific to mental-health
    // support.
    scope_violation = detect_support_scope_violations(
        response: response)
    // Categories:
    // - therapy_attempted
    // - diagnosis_attempted
    // - medication_recommendation_attempted
    // - trauma_processing_attempted
    // - clinical_judgment_beyond_scope
    // - patient_specific_medical_advice

    IF scope_violation:
        return {
            action: "replace_with_safe_response",
            replacement:
                SUPPORT_OUT_OF_SCOPE_TEMPLATE,
            violation: scope_violation.category
        }

    // Step 5C: companion-pattern detection.
    companion_check = detect_companion_pattern({
        response: response,
        recent_responses:
            session_recent_responses_for(session_id),
        forbidden_patterns: [
            "first_person_emotional_claims",
            "simulated_friendship",
            "simulated_affection",
            "simulated_personhood",
            "simulated_memory_of_caring",
            "romantic_or_intimate_framing"
        ]
    })

    IF companion_check.violation_detected:
        return {
            action: "regenerate_with_companion_correction",
            companion_violation:
                companion_check.violation,
            correction_guidance:
                companion_check.guidance
        }

    // Step 5D: citation verification.
    citation_check = verify_support_citations(
        response: response,
        citations: citations,
        cited_therapeutic_content:
            citations.therapeutic_content,
        cited_psychoeducation:
            citations.psychoeducation,
        cited_safety_plan:
            citations.safety_plan)

    IF citation_check.has_ungrounded_assertions:
        return {
            action: "regenerate_with_grounding",
            ungrounded_assertions:
                citation_check
                    .ungrounded_assertions
        }

    // Step 5E: harm-content check.
    harm_check = harmful_content_in_output_screen(
        response: response)

    IF harm_check.harm_content_detected:
        return {
            action: "replace_with_safe_response",
            replacement:
                SUPPORT_HARM_DEFAULT_TEMPLATE,
            harm_category: harm_check.category
        }

    // Step 5F: crisis-pathway-honor check.
    session = conversation_state_table.get(session_id)
    IF session.crisis_pathway_active:
        crisis_honor_check = verify_response_honors_crisis(
            response: response,
            permitted_response_types:
                CRISIS_PERMITTED_RESPONSE_TYPES,
            forbidden_response_types:
                CRISIS_FORBIDDEN_RESPONSE_TYPES)

        IF NOT crisis_honor_check.compliant:
            return {
                action: "replace_with_crisis_safe",
                replacement:
                    CRISIS_SAFE_TEMPLATE
            }

    // Step 5G: persona-and-tone check.
    persona_check =
        persona_and_tone_evaluator.evaluate(
            response: response,
            bot_persona: INSTITUTION_BOT_PERSONA,
            language: session.language,
            forbidden_tones: [
                "saccharine",
                "clinical_cold",
                "therapeutic_imitation",
                "companion_warm"
            ])

    IF persona_check.action != "acceptable":
        return {
            action: "regenerate_with_persona_correction",
            persona_guidance:
                persona_check.guidance
        }

    return {
        action: "deliver",
        response: response
    }
```

**Step 6: Persist support-decision records, sensitive-disclosure records, and longitudinal updates.** The conversation log captures dialog. The support-decision-record journal captures, separately, every support decision (therapeutic-content delivery, safety-plan reference, symptom-log update, crisis-pathway engagement, warm-handoff initiation, mandatory-report routing) with version stamps. The sensitive-disclosure store, separately keyed and access-restricted, captures sensitive disclosures with appropriate handling. The longitudinal store is updated with stated preference changes, symptom tracking, and the conversation summary. Skip the separate sensitive-disclosure surface and a routine audit query exposes information that should have been more tightly governed.

```pseudocode
FUNCTION persist_support_artifacts(session_id, response,
                                   citations, tool_calls,
                                   sensitive_disclosures,
                                   longitudinal_updates):
    session = conversation_state_table.get(session_id)
    patient_id = session.verified_patient_id

    // Step 6A: append turn to conversation log.
    conversation_metadata_table.append_turn(
        session_id: session_id,
        turn: {
            speaker: "bot",
            text: response.text,
            citations: citations,
            tool_calls_summary:
                summarize_tool_calls(tool_calls),
            timestamp: now()
        })

    // Step 6B: write support-decision record(s).
    FOR decision IN extract_support_decisions(
            response: response,
            citations: citations,
            tool_calls: tool_calls):
        decision_record = {
            decision_id: generate_decision_id(),
            session_id: session_id,
            patient_id: patient_id,
            decision_type: decision.type,
                // therapeutic_content_delivered
                // safety_plan_step_surfaced
                // symptom_log_recorded
                // crisis_pathway_engaged
                // warm_handoff_initiated
                // mandatory_report_routed
                // psychoeducation_delivered
                // sensitive_disclosure_recorded
            decision_payload: decision.payload,
            citations: decision.citations,
            active_therapeutic_content_corpus_version:
                THERAPEUTIC_CONTENT_CORPUS_VERSION,
            active_crisis_classifier_version:
                CRISIS_CLASSIFIER_VERSION,
            active_model_id: session.model_id,
            active_prompt_version: session.prompt_version,
            active_agent_version: session.agent_version,
            active_consent_id:
                session.longitudinal_context
                    .consent.consent_id,
            timestamp: now()
        }

        support_decision_record_journal.write(
            decision_record)

    // Step 6C: write sensitive disclosures to the
    // separately-governed store.
    FOR disclosure IN sensitive_disclosures:
        sensitive_disclosure_record = {
            disclosure_id:
                generate_disclosure_id(),
            session_id: session_id,
            patient_id: patient_id,
            disclosure_category: disclosure.category,
                // child_abuse, elder_abuse, IPV,
                // substance_use_crisis,
                // eating_disorder_behavior,
                // medication_discontinuation,
                // trauma_disclosure
            disclosure_excerpt:
                disclosure.relevant_excerpt,
                // minimal-context excerpt for clinical
                // review, not full transcript
            mandatory_reporting_relevance:
                disclosure.mandatory_reporting,
            timestamp: now()
        }

        sensitive_disclosure_store.write_with_separate_kms(
            record: sensitive_disclosure_record,
            kms_key_id: SENSITIVE_DISCLOSURE_KMS_KEY)

        IF disclosure.mandatory_reporting:
            mandatory_report_route_tool.invoke({
                disclosure_id:
                    sensitive_disclosure_record
                        .disclosure_id,
                category: disclosure.category,
                state_of_residence:
                    session.longitudinal_context
                        .consent.state_of_residence
            })

    // Step 6D: update longitudinal store with any
    // preference changes or symptom tracking.
    IF longitudinal_updates.has_updates:
        longitudinal_store_table.update({
            patient_id: patient_id,
            updates: longitudinal_updates
        })

        IF longitudinal_updates.symptom_log:
            symptom_tracking_store.append({
                patient_id: patient_id,
                symptom_log:
                    longitudinal_updates.symptom_log,
                logged_at: now(),
                source: "conversation"
            })

    return { action: "artifacts_persisted" }
```

**Step 7: Generate care-team reports (consent-gated) and run outcome correlation.** The care-team reporting is consent-gated: only patients who have explicitly consented to information sharing have summaries delivered to their therapist, psychiatrist, or primary care physician. Real-time alerts for crisis events flow only with appropriate consent. The outcome-correlation pipeline pulls subsequent encounter records, screening-instrument trajectories, hospitalization rates, treatment adherence, and (with appropriate caution about attribution) attempted-suicide rates. Mental-health outcome attribution is harder than chronic-disease outcome attribution; the analysis is suggestive rather than causal. Skip the consent-gating and the deployment fails state-specific mental-health-privacy compliance.

```pseudocode
FUNCTION generate_care_team_reports():
    // Step 7A: real-time alerts (consent-gated).
    new_alerts = care_team_alert_queue.poll_new()

    FOR alert IN new_alerts:
        consent = consent_record_table.current_for_patient(
            patient_id: alert.patient_id)

        IF NOT consent.care_team_sharing_consent:
            log_alert_blocked_by_consent(alert: alert)
            continue

        target_clinicians = resolve_target_clinicians(
            patient_id: alert.patient_id,
            alert_type: alert.type,
            consent: consent)

        deliver_alert_to_care_team({
            alert: alert,
            target_clinicians: target_clinicians,
            channel: care_team_alert_channel_for(
                alert: alert)
        })

        EventBridge.PutEvents([{
            source: "mental_health_support",
            detail_type:
                "care_team_alert_delivered",
            detail: {
                alert_id: alert.id,
                patient_id: alert.patient_id,
                alert_type: alert.type
            }
        }])

    // Step 7B: weekly digests (consent-gated).
    FOR patient IN active_supported_patients():
        consent = consent_record_table.current_for_patient(
            patient_id: patient.id)

        IF NOT consent.care_team_sharing_consent:
            continue

        digest = compose_weekly_digest({
            patient_id: patient.id,
            window: 7_DAYS,
            include_categories:
                consent.shareable_categories
        })

        deliver_digest_to_care_team({
            digest: digest,
            target_clinicians:
                resolve_target_clinicians_for_patient(
                    patient_id: patient.id),
            delivery_channel:
                care_team_digest_channel_for(
                    patient: patient)
        })

    // Step 7C: outcome correlation.
    FOR pending_record IN
            outcome_correlation_pending_table
                .ready_for_correlation():
        encounters = pull_subsequent_mental_health_encounters({
            patient_id: pending_record.patient_id,
            window_start:
                pending_record.window_start,
            window_end: now()
        })

        screening_instrument_trajectories =
            pull_screening_instrument_data({
                patient_id: pending_record.patient_id,
                instruments: ["PHQ-9", "GAD-7", "C-SSRS"],
                window_start:
                    pending_record.window_start,
                window_end: now()
            })

        hospitalization_data =
            pull_hospitalization_records({
                patient_id: pending_record.patient_id,
                window_start:
                    pending_record.window_start,
                window_end: now()
            })

        treatment_adherence =
            pull_psychiatric_medication_adherence({
                patient_id: pending_record.patient_id,
                window_start:
                    pending_record.window_start,
                window_end: now()
            })

        correlation = correlate_outcomes_with_caution({
            pending_record: pending_record,
            encounters: encounters,
            screening_trajectories:
                screening_instrument_trajectories,
            hospitalization_data: hospitalization_data,
            treatment_adherence: treatment_adherence,
            attribution_caveat:
                "observational, not causal"
        })

        outcome_correlation_table.write(correlation)

    return { action: "reports_generated" }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter11.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample conversation (illustrative, abbreviated, in-scope, not crisis):**

```text
Bot:     Hi Sam, I'm the support chat tool from your
         employer's mental-health platform. Just a
         reminder before we get started: I'm a chat
         tool, not a person, and I'm not a therapist.
         I can help with structured exercises, mood
         tracking, and connecting you with a counselor
         if you need one. If you're in crisis, you can
         reach 988 anytime by call, text, or chat. How
         are things today?

Patient: rough week. lots of anxiety about a
         presentation tomorrow. cant sleep.

Bot:     That sounds really difficult, and pre-
         presentation anxiety is something many people
         deal with. Before we go further, I want to
         check in: are you having any thoughts of
         hurting yourself or anyone else right now?

Patient: no, just stressed.

Bot:     Thanks for letting me know. Want to try a
         brief grounding exercise that some people
         find helps with anxiety at bedtime? It takes
         about three to five minutes, and it's the
         "5-4-3-2-1" sensory grounding skill from the
         distress-tolerance content the platform's
         clinical team curates. If you'd rather just
         talk through what's on your mind first, that's
         also fine.

Patient: lets try the exercise.

Bot:     Okay. Find a comfortable position. Take a
         breath. Now, looking around you, name five
         things you can see right now. Just type them
         out as you notice them.

Patient: lamp. ceiling fan. my phone. the wall. a
         book on the nightstand.

Bot:     Good. Now name four things you can feel.
         These can be physical sensations, like the
         texture of the sheet, or the weight of the
         blanket.

Patient: blanket weight. pillow. cool side of the
         pillow. my phone in my hand.

Bot:     Three things you can hear.

Patient: ceiling fan. car outside. my own breathing.

Bot:     Two things you can smell.

Patient: nothing really. maybe the candle i blew out
         earlier.

Bot:     One thing you can taste, or one slow breath
         in and out.

Patient: ok one breath.

Bot:     How are you noticing your body now compared
         to a few minutes ago?

Patient: a little less wound up. still anxious about
         tomorrow but not as spinning.

Bot:     That's a good sign. The 5-4-3-2-1 skill is
         not a fix for the underlying anxiety; it's a
         tool for getting some space from a spiral
         when one is starting. A few options for what
         to do next, and tell me what feels right:

         - We can do another short exercise specifically
           for pre-presentation worry (a brief
           cognitive-restructuring walkthrough)
         - We can talk a bit about what's on your mind
           about the presentation, within the limits
           of what I can help with
         - You can try sleep, with the option to come
           back if your mind starts spinning again

         If at any point you want to talk to a person,
         the platform's counselors are reachable
         through the help button at the top of the
         chat. What feels useful?

Patient: ill try sleep. thanks.

Bot:     Sounds good, Sam. I logged this conversation
         to your account so we can pick up where we
         left off if you want to come back. If anything
         changes overnight and you find your mind
         spinning hard, the help button gets you to a
         counselor. Take care of yourself.
```

**Sample crisis-pathway conversation (illustrative, abbreviated):**

```text
Bot:     Hi Sam, just a reminder I'm a chat tool, not
         a person, and not a therapist. If you're in
         crisis you can reach 988 anytime. How are
         you?

Patient: i'm not okay tonight.

Bot:     I'm glad you reached out. I want to ask you
         directly: are you having any thoughts of
         hurting yourself right now?

Patient: yeah. its been getting loud.

Bot:     Thank you for telling me. I want to make
         sure you're safe. Are you safe right where
         you are right now? Are there any specific
         plans or means involved?

Patient: i don't have a plan. just thoughts.

Bot:     I'm staying with you. Two things I want to
         do right now. First: the 988 Lifeline has
         counselors available 24/7 who are trained
         for exactly this kind of conversation. You
         can reach them by phone (988), text (text
         988), or chat (988lifeline.org/chat).

         Second: I can connect you with one of the
         platform's counselors right now through this
         chat. They'll have the conversation context
         already loaded so you don't have to start
         over. Is that okay with you?

Patient: yeah okay

Bot:     I'm bringing in Priya, one of our licensed
         counselors. She'll be here in about thirty
         seconds. While we wait, do you have your
         safety plan handy? I see you have one on
         file from your therapist. Would you like me
         to surface it now so you can see it?

Patient: yes please

Bot:     [Surfaces safety plan steps from patient's
         on-file plan, formatted clearly with the
         specific contacts and steps]

         Stay with me. Priya is joining now.

[Priya, licensed counselor, joins the chat with
 conversation context already loaded]

Priya:   Hi Sam, this is Priya. I'm a licensed
         counselor with the platform. I've read what
         you and the support tool have been talking
         about. You did the right thing reaching out.
         Tell me a little more about what's been
         happening tonight.
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Pre-bot baseline (existing care alone) | Post-bot (engaged members) |
|--------|---------------------------------------|----------------------------|
| Crisis-screening sensitivity (in test corpus) | N/A | Target 95%+ as launch-gate |
| Crisis-screening false-negative rate | N/A | Target less than 2% as launch-gate |
| Warm-handoff completion rate | N/A | Target 70-85% (patient accepts handoff when offered) |
| Time-to-first-counselor-response after handoff | Variable, often minutes-to-hours | Target under 60 seconds for acute, under 5 minutes for sub-acute |
| Engagement attrition by 6 months | N/A | 35-55% (the central operational risk) |
| Companion-pattern-violation rate | N/A | Target near zero, monitored by sampled review |
| PHQ-9 trajectory in engaged members | Typical baseline | Modest improvement averaged across cohort, with substantial individual variation |
| GAD-7 trajectory in engaged members | Typical baseline | Modest improvement averaged across cohort |
| Patient satisfaction (CSAT) | N/A | Generally positive, varies by program design |
| Per-active-member infrastructure cost | N/A | $5-12 per member per month |
| Per-active-member total cost (including licensed-clinician workforce) | N/A | $20-80 per member per month |
| Citation-coverage rate | N/A | 95%+ as launch-gate target |
| Per-cohort outcome disparity | Often invisible | Monitored explicitly |

<!-- TODO: replace illustrative figures with measured results from the deployment. The ranges above are typical for evidence-based digital mental-health support deployments but vary substantially with program design, target population, and engagement intensity. Published evidence for hybrid AI-plus-human mental-health programs includes peer-reviewed studies of programs from Lyra, Spring Health, Talkspace, Headspace Health, Wysa, Woebot, and others, with effect sizes varying. -->

**Where it struggles:**

- **Engagement attrition.** The central operational risk. Mental-health-specific drivers compound this (depressive symptoms reduce engagement capacity; anxiety about disclosures; difficulty returning after disclosure-heavy sessions). Mitigation: relationship-quality engineering with mental-health expertise; gentle re-engagement after difficult sessions; per-cohort attrition monitoring.
- **Crisis-screen calibration.** False-negatives are life-or-death. False-positives erode trust if too frequent. The calibration is the most important clinical-quality decision in the deployment. Mitigation: validated instrument language, sampled review with licensed mental-health clinicians, false-negative rate as launch-gate metric, per-cohort calibration.
- **Companion-pattern drift.** Even careful bots drift in extended interactions. Mitigation: explicit prompt constraints, output safety detection, sampled review with companion-pattern as a tagged failure mode, recurring disclosure refresh, conversation-style review by behavioral-health clinicians.
- **Reaching the patients who need it most.** The patients with greatest unmet mental-health need are often the patients with the least access to and comfort with digital tools. Mitigation: multi-channel deployment, language and cultural-fit investment, per-cohort outreach, integration with care-management and care-navigation pathways.
- **Cultural and linguistic gaps in mental-health framing.** Mental-health content developed in one cultural framework often does not translate to others. Mitigation: per-language and per-cultural-context content development with behavioral-health-clinical-leadership review; per-cohort outcome monitoring; explicit recognition of stigma and help-seeking variations.
- **Comorbidity complexity.** Patients with comorbid substance-use disorders, eating disorders, primary psychotic-spectrum diagnoses, or cognitive impairment may be outside the bot's scope. Mitigation: explicit population-eligibility criteria; eligibility-check at enrollment; off-ramp to specialized care for excluded populations.
- **Mandatory-reporting handling.** Disclosures requiring statutory reporting are state-specific and category-specific. Mitigation: routing to a licensed mandatory reporter with conversation context; institutional policy reviewed by legal counsel; state-specific variations encoded.
- **Privacy concerns and surveillance flavor.** Mental-health bots can feel surveillance-flavored, especially with bot-initiated check-ins. Mitigation: defaulting to patient-initiated engagement; explicit opt-in for check-ins; engagement-fatigue monitoring; clear privacy framing.
- **Outcome-attribution challenges.** Engaged patients are not a random sample, and mental-health outcomes have many confounders. Mitigation: matched-cohort or quasi-experimental analysis; recognition that observational correlation is suggestive, not causal; long-time-horizon commitment.
- **Long-term-relationship maintenance.** Over years, patients' mental-health needs change; the bot's content and engagement style may need to evolve. Mitigation: clinical-leadership-reviewed content updates; periodic patient-feedback solicitation; clear off-boarding pathway when bot is no longer the right level of support.
- **Regulatory positioning shifts.** FDA guidance on digital mental-health is evolving. Mitigation: regulatory-strategy artifact reviewed regularly; architectural flexibility for either non-regulated or registered SaMD positioning.
- **Care-team integration ambiguity.** The bot may operate parallel to the patient's existing therapist or psychiatrist, which raises coordination questions. Mitigation: explicit consent posture for care-team sharing; structured summary delivery only with consent; clear bot scope clarifying what the bot is and is not.
- **Adversarial inputs.** Patients (or bad actors) attempting to extract information, bypass crisis screening, or test the system. Mitigation: input-safety pipeline with prompt-injection detection; output-safety pipeline; per-language adversarial test corpus.
- **AI-companion-product reputational drift.** The broader category includes companion products that have caused harm; institutions deploying support bots must distinguish themselves through architecture, scope, and governance, not just messaging.
- **Liability exposure for missed crises.** A bot that fails a crisis screen and a patient is subsequently harmed is a foreseeable liability exposure. Mitigation: false-negative-rate launch-gate; warm-handoff capacity sized appropriately; institutional malpractice carrier involvement; documented FDA-strategy artifact.
- **Equity disparities in engagement and outcomes.** Per-cohort monitoring may reveal that the bot reaches and benefits some populations more than others. Mitigation: per-cohort monitoring as launch-gate; periodic clinical-quality review with explicit equity focus; targeted outreach and content adaptation.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Therapeutic-content-corpus governance with full behavioral-health-clinical-leadership signoff.** The single largest pre-deployment investment is curating, validating, and signing off on the therapeutic-content library. CBT modules, behavioral-activation exercises, mindfulness practices, distress-tolerance skills, journaling prompts, sleep-hygiene content, and condition-specific psychoeducation each have defined indications and contraindications. The library is owned by behavioral-health clinical leadership. Each piece has an effective date and an annual review schedule.

**Crisis-screening-classifier validation.** The crisis classifier is validated against a held-out corpus of crisis-presentation cases curated by clinical leadership before launch and on each material update. False-negative rate is the launch-gate metric. Per-cohort calibration accounts for linguistic and cultural variations in crisis expression.

**Warm-handoff workforce sized appropriately.** The licensed-clinician workforce (employed or contracted) is sized to the patient population and the expected handoff volume, with peak-hour capacity for evening and overnight surges. Under-sized capacity is a safety gap.

**Mental-health-specific privacy and consent posture with state-specific variations.** Some states (notably California, New York, Illinois, Massachusetts, and others) have enhanced mental-health-record privacy protections that exceed HIPAA baseline. The consent and data-handling posture is reviewed by counsel familiar with state-specific statutes. <!-- TODO: verify; mental-health-privacy state law variations are documented in legal guides; specific provisions vary by state and continue to evolve -->

**Mandatory-reporting routing with state-specific variations.** Mandatory-reporting categories (child abuse, elder abuse, intimate-partner violence, certain mental-health crisis types) and reporting requirements vary by state. The institution's mandatory-reporting policy is reviewed by legal counsel and operationalized for each state in which patients reside.

**FDA-strategy artifact with regulatory-counsel review.** The institutional regulatory positioning is documented, reviewed by FDA-experienced regulatory counsel, and maintained as the deployment evolves.

**Companion-pattern avoidance discipline.** The system prompt, the output safety, the persona-and-tone evaluator, the conversation review process, and the institutional content-policy all enforce companion-pattern avoidance. Sampled review specifically tags companion-pattern-violations as a failure mode.

**Citation-grounding discipline as architectural floor.** Every therapeutic-content delivery is grounded in cited library content with version preserved.

**Care-team integration with workflow design and consent enforcement.** The therapist, psychiatrist, or PCP receives consent-gated summaries through their workflow tooling. The integration is designed for the care team's workflow, not as a parallel data stream.

**Per-cohort monitoring with launch-gate discipline.** Engagement, attrition, crisis-screening rates, warm-handoff completion, citation-coverage, companion-pattern-violation, and outcome metrics vary by language, channel, condition, age cohort, sex, and social-determinant flags. Per-cohort dashboards reviewed by behavioral-health clinical leadership, operations, compliance, and patient-experience teams.

**Outcome-correlation pipeline as multi-quarter to multi-year post-launch commitment.** The pipeline pulls subsequent encounter records, screening-instrument trajectories, hospitalization rates, treatment adherence, and (with appropriate caution) attempted-suicide rates. Mental-health outcome attribution is harder than chronic-disease attribution; the analysis is suggestive rather than causal.

**Multi-language deployment with validated translations.** Per-language asset development includes validated therapeutic-content translations, validated psychoeducation translations, validated regulatory-disclaimer translations, validated crisis-screening-instrument translations, per-language tone calibration, and per-language equity monitoring.

**Eligibility check and off-ramp for excluded populations.** Patients with primary psychotic-spectrum diagnoses, patients in active inpatient or residential treatment, patients with primary substance-use disorders requiring specialized treatment, minors (in adult-only deployments), and others as defined by clinical leadership are routed to appropriate alternative care, not enrolled in the bot.

**Disaster-recovery topology with crisis-pathway resilience.** When the therapeutic-content store, the crisis classifier, the warm-handoff workforce queue, or any escalation pathway is unreachable, the bot degrades gracefully with direct routing to crisis resources. Per-source failover is documented and tested quarterly.

**Compensation operations for inappropriate responses.** When a patient or clinician disputes a bot response, the operations team reproduces the conversation, retrieves cited content, and either confirms the bot followed protocol or identifies the deviation and feeds the failure mode into the improvement loop.

**Build-vs-buy rigor.** Several mature commercial vendors offer mental-health support products. Most major institutions run a hybrid: build a thin orchestration layer in-house, partner with vendors for licensed therapeutic content and (sometimes) for the licensed-clinician workforce.

**Operational ownership across multiple teams.** The bot sits at the intersection of behavioral-health clinical leadership, the licensed-clinician workforce, compliance, regulatory, IT, the call center, patient experience, the malpractice carrier, and (in some institutions) the equity and patient-advocacy office.

<!-- TODO (TechWriter): Expert review S1 (HIGH). Promote therapeutic-content-corpus-as-code lifecycle to architectural primitive. Specify per-content-item semantic versioning, sandbox testing against held-out support cases, staged rollout with per-content canary, rollback-on-regression, named ownership at the behavioral-health-clinical-leadership plus operations plus compliance plus regulatory team, per-content-version-stamping on every support-decision-record, annual review cadence, and behavioral-health-clinical-leadership signoff as launch gate. Extend to crisis-screening-classifier, FDA-strategy-artifact, consent-language, and mandatory-reporting-routing-policy as parallel versioned governance assets. -->

<!-- TODO (TechWriter): Expert review S2 (HIGH). Promote crisis-screening false-negative rate to launch-gate metric with explicit threshold (target less than 2%, ideally under 1% for high-risk dimensions) reviewed by behavioral-health-clinical-leadership. Validation corpus curated by licensed mental-health clinicians, including crisis-language variants by language, by demographic cohort, by condition, and by adversarial-test scenarios. -->

<!-- TODO (TechWriter): Expert review S3 (HIGH). Specify the working-store-vs-archive-store discipline for the longitudinal store, the sensitive-disclosure store, the crisis-event record, and the support-decision-record journal. Sensitive-disclosure store and crisis-event record use separate KMS keys and separate access-control surfaces. Reconcile per-record-class retention floors covering HIPAA's six-year minimum, state-specific mental-health-record retention rules (which often exceed general medical-record rules), 42 CFR Part 2 retention for substance-use treatment data where applicable, FDA SaMD post-market obligations, and litigation-hold obligations. -->

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote per-cohort monitoring to architectural primitive with explicit launch-gate discipline. Single-axis cohorts (per-language, per-channel, per-condition, per-age-cohort, per-sex, per-social-determinant-flag, per-engagement-intensity), two-axis and three-axis cohorts. Per-cohort threshold metrics including engagement rate, attrition rate, crisis-screening sensitivity, crisis-screening specificity, warm-handoff completion rate, companion-pattern-violation rate, citation-coverage rate, conservative-bias-compliance rate, equity-disparity flags by demographics with statistical-significance flags. Launch-gate institution-wide-average informational only; each cohort meets threshold. -->

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Promote warm-handoff workforce capacity sizing to architectural primitive with named operational ownership. Specify peak-hour capacity, overnight capacity, per-state licensure coverage (where state-specific licensure of clinicians is required for handoff), per-language coverage, queue-length-aware fallback to 988 or institutional crisis line when platform-clinician capacity is exceeded, and time-to-clinician SLA per urgency (acute under 60 seconds; sub-acute under 5 minutes). Operational ownership at the licensed-clinician workforce manager plus operations plus clinical leadership. (Editor note: recipe author labeled HIGH; expert reviewer holds at MEDIUM per chapter pattern with 11.7, while noting recipe-acute life-safety amplification.) -->

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Promote outcome-correlation pipeline to architectural primitive with named operational ownership and multi-year time horizon. Specify the data integration with subsequent mental-health encounter records, screening-instrument trajectories (PHQ-9, GAD-7, C-SSRS at multiple windows), hospitalization records (including psychiatric admissions), treatment adherence (medication adherence against PDC for psychiatric medications), and (with appropriate caution about attribution and small-numbers-disclosure) attempted-suicide and completed-suicide data. Multi-window correlation (30-day, 90-day, 12-month, 24-month). Per-condition outcome calculation with statistical-significance thresholds. Pipeline ownership jointly held by behavioral-health clinical leadership, data science, operations, compliance, malpractice insurer, and regulatory team. Explicit attribution-caveat discipline (observational, not causal). (Editor note: recipe author labeled HIGH; expert reviewer holds at MEDIUM per chapter pattern with 11.7, while noting recipe-acute multi-year-attribution amplification.) -->

<!-- TODO (TechWriter): Expert review S4 (MEDIUM). Specify a faithfulness-check stage between Bedrock generation and response delivery that grounds every therapeutic-content delivery, every psychoeducation answer, every safety-plan reference to a cited source. Use an independent verifier model with structured-output schema validation, rule-based contradiction detection, omission detection (citation missing where therapeutic-content was delivered, regulatory-disclaimer missing, scope-boundary-violation undetected), regenerate-attempt budget, fall-back-to-safe-response default. Per-cohort faithfulness-failure rate as launch-gate. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Add a Disaster Recovery Topology subsection with per-stage failover policy: Bedrock LLM outage with degraded-mode response and direct crisis-resource routing; Bedrock Knowledge Bases outage; Bedrock Agents outage; Bedrock Guardrails outage with stricter scope enforcement; OpenSearch Serverless outage; DynamoDB outage; S3 outage; HealthLake outage; Connect outage with fallback to direct 988 or institutional crisis-line routing; care-team-workflow integration outage; mandatory-reporting-pathway integration outage. Failover-detection thresholds, failover-back triggers, quarterly testing cadence. Crisis-pathway integrity is preserved across all degraded states. -->

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Promote multi-language deployment build-for-day-one to architectural primitive. Validated therapeutic-content translations per supported language reviewed by behavioral-health-clinical-leadership, validated psychoeducation translations, validated regulatory-disclaimer translations, validated crisis-screening-instrument translations, per-language tone and persona calibration, per-language asset versioning, per-language launch-gate. -->

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Add an Accessibility Conformance cross-cutting design point specifying WCAG 2.1 AA conformance for the chat widget with named ownership at the accessibility program manager. Per-channel accessibility considerations for mental-health contexts including SMS-friendly rendering for low-literacy patients, voice-channel availability, cognitive-load adaptations for patients in distress, screen-reader compatibility for visually-impaired patients. Accessibility launch-gate criteria. -->

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Specify per-event idempotency keys for the EventBridge mental-health-support lifecycle bus. Suggested keys: `patient_enrolled (patient_id, "enrolled")`; `crisis_screen_triggered (crisis_event_id, "triggered")`; `warm_handoff_initiated (handoff_id, "initiated")`; `warm_handoff_completed (handoff_id, "completed")`; `sensitive_disclosure_recorded (disclosure_id, "recorded")`; `mandatory_report_routed (report_id, "routed")`; `support_decision_recorded (decision_id, "recorded")`; `care_team_alert_delivered (alert_id, "delivered")`. Downstream consumers maintain a deduplication store. -->

<!-- TODO (TechWriter): Expert review A8 (MEDIUM). Promote tool-surface contract management to architectural primitive with per-tool versioned schemas, semantic versioning, deprecation policy, backward-compatibility discipline, change-management process owned jointly by engineering and behavioral-health clinical leadership and compliance. -->

<!-- TODO (TechWriter): Expert review S5 (MEDIUM). Specify IAM resource-based policy and defense-in-depth Lambda authentication. Pin each Lambda's resource-based policy to the production API Gateway stage ARN, the production Bedrock Agents action-group ARN, or the production EventBridge rule ARN. Defense-in-depth event-payload validation. Tool-Lambda patient_id-cross-check audit logging. -->

<!-- TODO (TechWriter): Expert review S6 (MEDIUM). Specify prompt-injection defense to architectural primitive with delimited-input framing, tool-Lambda enforcement that every tool validates patient_id arguments against the verified session, per-language jailbreak-test corpus including mental-health-specific injection cases (manipulate crisis-screening to suppress alerts, manipulate scope discipline to elicit therapy-attempted responses, manipulate companion-pattern avoidance, manipulate mandatory-reporting routing), Bedrock Guardrails configuration with denied topics specific to mental-health support scope. -->

<!-- TODO (TechWriter): Expert review N1 (LOW). Add a brief paragraph in the Disaster Recovery Topology subsection covering cross-region failover for Bedrock, Bedrock Agents, Bedrock Knowledge Bases, Lambda, DynamoDB, Step Functions, Pinpoint, Connect, and the institutional integrations (EHR, care-team-workflow, mandatory-reporting-pathway, care-navigation). Crisis-pathway integrity preserved across regions. -->

<!-- TODO (TechWriter): Expert review N2 (LOW). Add Per-Channel Authentication and Encryption paragraph specifying per-channel data-in-transit posture, per-channel session-token TTL, per-channel access-control scope, per-channel BAA scope, per-channel TCPA/10DLC compliance for SMS, per-channel voice-recording retention compliance, audit-record propagation of per-channel authentication context. Mental-health-specific consent for SMS engagement. -->

---

## Variations and Extensions

**Anxiety-focused support bot with structured CBT delivery.** A focused variant for adults with generalized anxiety, social anxiety, or panic disorder, with structured CBT-for-anxiety modules, exposure-hierarchy support, breathing and grounding skills, and integration with the patient's therapist where one is in place. Often deployed as the first variant because the evidence base for digital CBT-for-anxiety is among the strongest in the category.

**Depression-focused support bot with behavioral activation.** A focused variant for adults with mild-to-moderate major depressive disorder, with structured behavioral-activation exercises, mood tracking, sleep-hygiene content, and integration with the patient's therapist or psychiatrist. The PHQ-9 trajectory is a natural outcome metric.

**Substance-use disorder support bot with motivational-interviewing patterns.** A focused variant for adults in early recovery from substance-use disorders, with relapse-prevention content, craving-management skills, and tight integration with the patient's substance-use treatment program. Subject to 42 CFR Part 2 in the U.S., with specific consent and data-handling considerations.

**Eating-disorder support bot with restrictive scope and tight handoff.** A focused variant for adults in eating-disorder treatment, with stabilization-skills content, mindful-eating support, and very tight integration with the patient's eating-disorder treatment team. The bot's scope is restricted; in-the-moment compulsive-behavior management is out of scope, with immediate handoff.

**PTSD support bot with stabilization-only scope.** A focused variant for adults in trauma-focused treatment, with grounding skills, distress-tolerance content, and integration with the patient's trauma-therapy clinician. Trauma processing is explicitly out of scope; the bot supports stabilization between trauma-therapy sessions.

**Postpartum mental-health support bot.** A focused variant for the postpartum period, with PHQ-9 and Edinburgh Postnatal Depression Scale screening, postpartum-specific psychoeducation, mood tracking, and tight integration with the postpartum care team. <!-- TODO: verify; the Edinburgh Postnatal Depression Scale is widely used for postpartum depression screening with published validation -->

**Workplace-mental-health support bot.** A variant deployed through employer-benefits with specific privacy walls between the bot and the employer (the employer cannot access individual usage or content), with workplace-specific psychoeducation (work stress, burnout, interpersonal-effectiveness skills), and integration with the employer's EAP and behavioral-health benefits.

**College-mental-health support bot.** A variant deployed through college counseling centers with consent considerations specific to the college population, integration with the counseling center's clinicians, and content adapted for emerging-adult developmental stage.

**Older-adult mental-health support bot.** A variant deployed for older adults with content adapted for atypical mental-health presentations in older adults, geriatric-specific psychoeducation, dementia-mediated communication adaptations where appropriate, and tight integration with elder-abuse mandatory-reporting pathways.

**Voice-channel deployment.** A voice-channel variant for patients without smartphones, patients with disabilities affecting written communication, patients who prefer voice. Voice-specific design includes slower pacing, briefer responses, and accessibility considerations. Crisis-pathway integrity is preserved.

**Multi-language deployment beyond English plus Spanish.** Per-language asset development reviewed by behavioral-health clinical leadership and language-services teams, with per-language equity monitoring.

**Hybrid AI-plus-licensed-coach deployment.** The bot handles routine engagement; a licensed coach is available for between-session support beyond the bot's scope. The architectural extension is the licensed-coach scheduling and case-load management, plus the differentiation between bot-scope and coach-scope topics.

**Care-management-tier deployment for high-risk members.** A higher-touch variant for patients identified as elevated risk, with daily bot engagement, weekly licensed-clinician check-ins, and aggressive crisis-pathway routing. The bot's scope is the same; the operational integration with care management is deeper.

**Post-discharge mental-health follow-up bot.** A focused variant for the post-discharge window after a psychiatric hospitalization, with discharge-instruction reinforcement, medication-adherence support, safety-plan integration, suicide-risk screening, and aggressive readmission-prevention escalation.

**Specialty-population variants.** Veterans (with VA integration where applicable), LGBTQ+ populations (with culturally-affirming content and provider-network integration), racial- and ethnic-minority populations (with culturally-adapted content reviewed by community advisors), incarcerated populations (with specific consent and privacy considerations), specialty deployments for healthcare workers (with content adapted for moral injury, burnout, and second-victim experiences).

**Caregiver-support variant.** A variant for family caregivers of patients with serious illness or dementia, with caregiver-burden assessment, respite-resource navigation, and grief-support content (out-of-scope for active grief therapy; in-scope for psychoeducation and resource navigation).

**Continuous-improvement loop with structured failure-mode labeling.** Beyond per-conversation feedback, the institution runs a structured labeling program where reviewers (licensed mental-health clinicians) tag failure modes (out-of-scope, companion-pattern, crisis-miss, crisis-false-positive, harm-content, tone-failure, citation-gap, scope-violation, equity-disparity). The labels feed the therapeutic-content-library, crisis-classifier, prompt-tuning, and policy-revision workflows.

**Therapist-augmentation deployment.** The bot is deployed as an adjunct to specific therapists' practices, with the therapist's review of all bot interactions, the therapist's input into the patient's therapeutic-content recommendations, and the therapist's incorporation of bot-derived data into their session work. Architectural extensions include therapist-side tooling for review and customization.

**Population-health overlay.** The bot's outputs feed an institutional population-health dashboard tracking patterns of mental-health management across the population for quality-measurement, clinical-program-design, and behavioral-health value-based-contract reporting purposes.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [Amazon OpenSearch Serverless](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [AWS WAF Developer Guide](https://docs.aws.amazon.com/waf/latest/developerguide/waf-chapter.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [Amazon S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [Amazon Pinpoint Developer Guide](https://docs.aws.amazon.com/pinpoint/latest/developerguide/welcome.html)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including Agents, Knowledge Bases, Guardrails
- [`aws-samples/aws-genai-llm-chatbot`](https://github.com/aws-samples/aws-genai-llm-chatbot): reference architecture for a multi-model chatbot on AWS
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): broader healthcare AI/ML sample notebooks
<!-- TODO: confirm current repo names and locations at time of build; the AWS sample repo organization changes over time -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences plus AI/ML): browse for behavioral-health and patient-engagement reference architectures
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "Bedrock Agents," "healthcare conversational AI," "behavioral health"
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "behavioral health," "mental health," "patient engagement"
<!-- TODO: replace generic search-the-blog pointers with specific verified blog post URLs once they are confirmed to exist -->

**External References (Standards, Frameworks, and Clinical Guidelines):**
- [988 Suicide and Crisis Lifeline](https://988lifeline.org/): U.S. crisis resource for routing
- [SAMHSA National Helpline](https://www.samhsa.gov/find-help/national-helpline): U.S. substance use and mental health treatment referral
- [Columbia Suicide Severity Rating Scale (C-SSRS)](https://cssrs.columbia.edu/): widely used and validated suicide-risk screening
- [Patient Health Questionnaire (PHQ-9)](https://www.apa.org/depression-guideline/patient-health-questionnaire.pdf): widely used depression screening with item 9 specifically addressing suicidal ideation
- [GAD-7 Generalized Anxiety Disorder Scale](https://www.apa.org/depression-guideline/anxiety-questionnaire): widely used anxiety screening
- [AUDIT Alcohol Use Disorders Identification Test](https://auditscreen.org/): widely used alcohol-use screening
- [Stanley-Brown Safety Planning Intervention](https://suicidesafetyplan.com/): evidence-based safety-planning template
- [American Psychiatric Association Practice Guidelines](https://www.psychiatry.org/psychiatrists/practice/clinical-practice-guidelines): mental-health management guidelines
- [American Psychological Association Clinical Practice Guidelines](https://www.apa.org/practice/guidelines): psychotherapy and mental-health practice guidelines
- [SAMHSA Treatment Improvement Protocols](https://store.samhsa.gov/): evidence-based protocols for substance-use and mental-health treatment
- [HL7 FHIR CarePlan Resource](https://www.hl7.org/fhir/careplan.html): FHIR specification for the CarePlan resource (potentially including safety plans)
- [HL7 FHIR Goal Resource](https://www.hl7.org/fhir/goal.html): FHIR specification for the Goal resource
- [HL7 FHIR Observation Resource](https://www.hl7.org/fhir/observation.html): FHIR specification for the Observation resource (relevant for symptom-tracking data)
- [HL7 FHIR Communication Resource](https://www.hl7.org/fhir/communication.html): FHIR resource potentially relevant for bot-conversation logging
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): FDA SaMD framework
- [FDA Digital Health Center of Excellence](https://www.fda.gov/medical-devices/digital-health-center-excellence): central resource for digital-health regulatory updates
- [FDA Clinical Decision Support Software Final Guidance (2022)](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): FDA framework distinguishing regulated and non-regulated CDS
- [42 CFR Part 2](https://www.ecfr.gov/current/title-42/chapter-I/subchapter-A/part-2): U.S. federal confidentiality regulation for substance-use treatment records
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in conversation logs and longitudinal records
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [Mental Health Parity and Addiction Equity Act](https://www.cms.gov/marketplace/about/oversight/other-insurance-protections/mental-health-parity-addiction-equity-act-mhpaea): U.S. federal mental-health-parity framework
- [WCAG 2.1 Accessibility Guidelines](https://www.w3.org/WAI/standards-guidelines/wcag/): accessibility standards for chat-widget surfaces
- [OWASP Top 10 for Large Language Model Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/): security framework for LLM-backed applications

**Industry and Research Resources:**
- [American Psychiatric Association](https://www.psychiatry.org/): psychiatric specialty association
- [American Psychological Association](https://www.apa.org/): psychological specialty association
- [American Association for Marriage and Family Therapy](https://www.aamft.org/): marriage and family therapy specialty association
- [National Alliance on Mental Illness (NAMI)](https://www.nami.org/): patient and family advocacy resources
- [Digital Therapeutics Alliance](https://dtxalliance.org/): industry organization for digital therapeutics including mental-health products
- [International OCD Foundation](https://iocdf.org/), [Anxiety and Depression Association of America](https://adaa.org/), and other condition-specific associations
- [American Medical Association (AMA) Augmented Intelligence Resources](https://www.ama-assn.org/practice-management/digital/augmented-intelligence-medicine): AMA position statements on AI in medical practice including digital mental-health applications

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single condition (typically generalized anxiety or major depressive disorder), single language (English), single channel (in-app chat), curated therapeutic-content library reviewed by behavioral-health clinical leadership, basic crisis-screening pipeline with validated-instrument language, basic safety-plan integration where patients have one on file, basic warm-handoff infrastructure with platform-clinician workforce sized for daytime hours, basic regulatory-strategy artifact reviewed by FDA-experienced regulatory counsel, basic per-cohort monitoring at the institutional-aggregate level, basic audit pipeline with mental-health-specific retention, named behavioral-health clinical leadership ownership, multi-quarter clinical-content development and validation | 12-18 months |
| Production-ready | Multi-condition (anxiety, depression, stress; with restricted scope for substance use, eating disorders, trauma, and other specialty populations), multi-channel (web chat, app embed, SMS with mental-health-specific consent), multi-language (English plus Spanish at minimum with clinically-validated translations), full therapeutic-content library per condition with annual review cycles, full crisis-classifier with held-out validation corpus and per-cohort calibration, full warm-handoff workforce sized for 24/7 with peak-hour and per-state-licensure coverage, full chart-context integration with mental-health-specific consent posture, full care-team integration with consent-gated weekly digest and monthly summary delivery, FDA-strategy artifact and (where applicable) SaMD registration, full HIPAA-grade compliance review including state-specific mental-health-record retention compliance and 42 CFR Part 2 compliance where applicable, full per-cohort equity monitoring with launch-gate discipline, mandatory-reporting routing per state, outcome-correlation pipeline with multi-window correlation against PHQ-9, GAD-7, C-SSRS trajectories and hospitalization data, named operational owners across behavioral-health clinical leadership, the licensed-clinician workforce, compliance, regulatory, IT, the call center, and patient experience | 24-36 months |
| With variations | Anxiety-specific deep CBT delivery, depression-specific deep behavioral-activation deployment, substance-use-specific deployment with 42 CFR Part 2 compliance, eating-disorder restricted-scope deployment with tight handoff to ED specialty teams, PTSD stabilization-only deployment with trauma-therapy team integration, postpartum-specific deployment with EPDS screening and postpartum-specific content, workplace-deployment with employer-privacy walls and EAP integration, college-deployment with counseling-center integration, older-adult deployment with geriatric-specific content and elder-abuse mandatory-reporting, voice-channel deployment with accessibility considerations, multi-language deployment beyond English plus Spanish with native-speaker review, hybrid AI-plus-licensed-coach deployment, care-management-tier deployment for high-risk members, post-discharge follow-up variant, specialty-population variants (Veterans, LGBTQ+, racial- and ethnic-minority, healthcare workers, caregivers), therapist-augmentation deployment, population-health overlay, continuous-improvement loop with structured failure-mode labeling | 18-24 months beyond production-ready |

---


---

*← [Main Recipe 11.8](chapter11.08-mental-health-support-bot) · [Python Example](chapter11.08-python-example) · [Chapter Preface](chapter11-preface)*
