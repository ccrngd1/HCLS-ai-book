# Expert Review: Recipe 10.4 - Medical Transcription (Dictation)

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-23
**Recipe file:** `chapter10.04-medical-transcription-dictation.md`

---

## Overall Assessment

This is the fourth recipe in Chapter 10 (Speech / Voice AI) and the chapter's first medium-tier recipe. After 10.1 (IVR), 10.2 (voicemail), and 10.3 (voice-to-text EHR navigation), this recipe pivots to the most established voice product category in healthcare: clinician dictation. The pivot is executed cleanly and the recipe distinguishes itself from 10.3 (single-speaker, intentional, long-form, structured-output, signed-clinical-record stakes) and from the forthcoming 10.7 (ambient documentation, multi-speaker, conversational, requires diarization) at exactly the right grain. The opening 6:47-PM-empty-clinic-physician-typing-pajama-time vignette earns its position as the chapter's strongest single articulation of the documentation-burden problem; the "she is trying to remember the patient's exact words about a new symptom. She is trying to remember whether the patient said the pain started 'two weeks ago' or 'about two weeks ago, give or take.' She is trying to remember which side. She is trying to reconstruct the physical exam she did four hours ago for a patient she has not seen since" cadence is the recipe's strongest single passage of "you're sitting in the back office watching the documentation tax compound" voice. The "pajama time" colloquialism is correctly elevated as the universal-clinician term for the after-hours documentation burden and grounds the entire recipe in the felt-experience of the median ambulatory physician in 2026.

The seven specific failure-mode vignettes in The Problem section earn their position: (1) the radiologist-with-laterality-mistranscription failure (the recipe's strongest single articulation of the critical-error-rate-versus-WER axis with the four-thousand-reports-times-twenty-with-wrong-laterality math); (2) the underrepresented-accent-clinician failure (the equity-stake recipe-distinct framing); (3) the hemoptysis-versus-hematemesis sound-alike failure (the silent-and-routine clinical-safety primitive); (4) the surgeon-voice-command-confused-with-content failure (the command-versus-content boundary primitive); (5) the deployment-with-forty-percent-of-pilot-adoption failure (the workflow-engineering-not-technology framing); (6) the institutional-BAA-without-scrutiny failure (the audio-as-PHI-and-vendor-cloud-storage primitive). The radiologist-laterality vignette in particular is the recipe's strongest single passage of clinical-safety-failure-mode pedagogy and earns its position as the recipe's central safety primitive.

The Technology section's "Long-Form Dictation with Domain-Specific Stakes" framing with the nine-property enumeration (utterances are long, vocabulary is highly specialized, specialty-specific subdialects, accuracy expectations are very high, safety-critical word substitutions matter more than overall WER, real-time / near-real-time / batch latency requirements, voice commands embedded in dictation, per-clinician adaptation is essential, integration with the EHR documentation workflow) is correct and recipe-distinct from 10.1 / 10.2 / 10.3. The "the metric that matters is not just WER but the rate and severity of clinically-meaningful errors" framing with the critical-error-rate-versus-WER framing is the recipe's strongest single architectural primitive on the safety-relevant accuracy dimension and is the recipe's central operational insight. The Domain-Adapted ASR subsection's four-pattern survey (hybrid HMM-DNN with domain-adapted language models, end-to-end neural systems trained on clinical audio, hybrid neural-ASR-with-LLM-post-processing, vendor cloud APIs) is correctly forward-looking. The custom-vocabulary / per-clinician-adaptation / voice-commands / formatting-and-structuring / read-edit-sign decomposition is the right shape for the problem.

The Voice Commands and Mode Switching subsection is the recipe's strongest passage on the command-versus-content boundary problem. The push-to-command-versus-push-to-talk inversion ("the microphone is always live for dictation, and the clinician presses a button while issuing a command. This inverts the friction (the common case is frictionless; the less-common case has a button) and is the dominant pattern in mature dictation products") is the recipe's clearest articulation of why mature dictation products have settled on push-to-command. The Formatting, Structuring, and Note Template subsection's LLM-driven-formatting paragraph correctly hedges with the faithfulness caveat ("the standard LLM concern that the output may be a fluent reformulation rather than a faithful transcription. Production systems mitigate by treating the LLM output as a draft for clinician review, never as the final signed note"). The Read-Edit-Sign Workflow subsection's six-affordance enumeration (read-back and review with the wall-of-dense-text-invites-skimming framing, confidence highlighting, spell-check and consistency-check overlays, track-changes between draft and final, structured-field extraction with confirmation, co-signature workflows for trainees, late-addendum support) is recipe-distinct and the load-bearing UX primitive.

The eight-stage architecture (activation and audio capture, domain-adapted ASR, command-versus-content disambiguation, formatting and structuring, template integration, structured-field extraction, read-edit-sign, audit-archive-and-adaptation) is the right shape for the problem and is recipe-distinct from 10.1 / 10.2 / 10.3 in the right ways. The cross-cutting design points are correctly elevated (audio is PHI, clinician's signature is the gate to the legal record, per-clinician adaptation requires an adaptation pipeline, critical-error detection is not the same as overall accuracy monitoring, voice commands and dictation content require unambiguous separation, structured-field extraction is a draft never a fact, audit retention has to span the legal record's lifetime, failure has to degrade to a usable fallback, specialty differences are first-class, adoption depends on training and workflow integration as much as accuracy).

The Why-These-Services section walks each AWS component back to the conceptual primitive it implements (Transcribe Medical for clinical-domain ASR with the specialty-list-and-DICTATION-versus-CONVERSATION framing, Bedrock for LLM-driven formatting and structuring with the faithfulness-checked-draft framing, Comprehend Medical for coded-entity extraction with the RxNorm and ICD-10 linking, Lambda for per-stage processing, Step Functions for durable orchestration of the dictation-to-signed-note workflow, API Gateway WebSocket plus REST with Cognito authorizer, Cognito federation to the institutional IdP, DynamoDB for session-state and dictation-metadata and per-clinician-config with three-table separation, S3 for audio with brief-retention lifecycle and audit archive with Object Lock, KMS with customer-managed keys-per-data-class, Secrets Manager for EHR credentials, CloudWatch and CloudTrail for observability and audit, EventBridge for cross-system events, optional ElastiCache for low-latency vocabulary lookup, optional SageMaker for per-clinician adaptation, optional QuickSight for dashboards).

The Honest Take is the recipe's strongest single passage. The seven traps (treating-dictation-as-a-solved-problem-and-skipping-deployment-quality-investment, over-relying-on-overall-accuracy-metrics-rather-than-critical-error-rate, assuming-LLM-post-processing-is-an-unmitigated-good, underinvesting-in-disambiguation-between-voice-commands-and-dictation-content, failing-to-plan-for-per-specialty-tuning, skipping-the-build-vs-buy-analysis) are well-chosen and recipe-specific. The "the metric that matters is critical-error rate, not WER. A dictation system with 92% WER and a tightly-managed critical-error rate is safer than one with 97% WER and no critical-error tracking" framing is the chapter's clearest articulation of the safety-relevant-accuracy-axis primitive. The closing "medical dictation produces clinical documentation that becomes the legal record. A misrecognized word in a signed note is a clinical-safety event, a billing-compliance event, and potentially a litigation event" line frames the dictation pipeline as a legal-record-creation surface and is the recipe's strongest single closing primitive.

That said, three correctness-and-compliance gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items.

(1) The dictation-metadata DynamoDB table writes the verbatim transcript and the per-word results verbatim into DynamoDB at Step 2C, creating a parallel PHI store outside the audio-bucket and audit-archive governance. Same chapter pattern as Recipe 10.1 Finding S1, Recipe 10.2 Finding S1, and Recipe 10.3 Finding S1, but recipe-acute because dictation transcripts are longer and richer than IVR or voicemail transcripts, contain higher-resolution PHI (patient names, medication names with doses, anatomical findings, eponymous syndromes, free-text symptom descriptions), and are accessible to the formatting-and-structured-extraction Lambdas and any downstream analytics consumer with table-read access. The audit_record at Step 8A correctly handles this with archive-references, but the upstream working store at Step 2C and the patch at Step 7C reintroduce the parallel-PHI-store pattern that the audit-record discipline was meant to eliminate.

(2) Critical-error detection (laterality flips, negation flips, drug-name confusions, dose-by-order-of-magnitude errors) is structurally absent from the architecture pattern despite the recipe's own self-assessment that this is "the single most important production gap." The recipe correctly elevates critical-error detection in five separate places (the radiologist-laterality vignette, the safety-critical-word-substitutions Technology subsection, the Critical-error-detection cross-cutting design point, the Where-it-Struggles "Sound-alike substitutions" item, and the Production-Gaps "Critical-error detection with named ownership" paragraph) but does not architect it. The architecture diagram has no critical-error-detection stage; the pseudocode has no detection function; the read-edit-sign rendering has no high-risk-substitution flagging. The recipe-specific stakes are uniquely sharp because dictation produces signed clinical documentation that becomes the legal record, and the recipe's own framing names this as the deciding factor between dictation systems with no clinical-safety incidents and those that have had them.

(3) Cohort-stratified accuracy monitoring is structurally absent from the architecture pattern despite the recipe's correct elevation of the equity dimension as recipe-specific in three separate places (the underrepresented-accent-clinician failure-mode vignette, the Where-it-Struggles "Underrepresented accents and speech patterns" item, the Production-Gaps "Subgroup-stratified accuracy monitoring with disparity alerts" paragraph). Same chapter pattern as Recipe 10.1 Finding A1, Recipe 10.2 Finding A1, and Recipe 10.3 Finding A1; recipe-specific because dictation accuracy disparities translate directly into clinician-time disparities and into per-clinician documentation-burden disparities (a clinician whose accent is underrepresented spends more after-hours time correcting ASR output for the same volume of patient encounters). The architecture should specifically elevate the per-clinician-stratified instrumentation as the recipe's primary equity surface.

Eleven chapter-wide and recipe-specific MEDIUM items repeat or are recipe-new (faithfulness-check architecturally underspecified for the recipe's highest-stakes-LLM-failure-mode, foundation-model prompt-injection risk for the LLM formatter, per-clinician adaptation pipeline architecturally specified, EHR-state and SMART on FHIR token lifecycle, idempotency for dictation submission, foundation-model and prompt versioning via Bedrock inference profiles and aliases, multi-language architecture build-for-day-one, audio retention policy specified more concretely than enumerated, audit-log retention floor with explicit floor named, Lambda invocation authentication, Comprehend Medical multi-call pattern slightly underspecified, disaster recovery and partial-failure topology). Most are explicitly TODO'd or named in the Why-This-Isn't-Production-Ready section; this review carries them forward at MEDIUM severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by raw-byte search against U+2014; zero matches in the file). The 70/30 vendor balance is maintained. CC voice is consistent throughout. Healthcare-domain accuracy is consistent (the radiologist-laterality-mistranscription failure pattern is well-documented in radiology informatics literature; the hemoptysis-versus-hematemesis sound-alike pair is a real and clinically-significant ASR failure mode; the cefepime pronunciation note is correct; the eponymous-syndrome catalog (Wolff-Parkinson-White, Henoch-Schönlein purpura, Mallory-Weiss tear) is accurate; the medication examples (lisinopril, dabigatran, tisagenlecleucel) span common-to-rare appropriately; the specialty-specific dictation patterns (radiology, cardiology, psychiatry, surgery, emergency medicine) are clinically authentic). The Transcribe Medical specialty list (PRIMARYCARE, CARDIOLOGY, NEUROLOGY, ONCOLOGY, RADIOLOGY, UROLOGY) and the DICTATION-versus-CONVERSATION mode framing are correct. The SMART on FHIR / FHIR DocumentReference / FHIR Composition / FHIR Provenance citations are correct. The RxNorm / ICD-10 / SNOMED CT / LOINC references are accurate.

Architectural accuracy is mostly high. The streaming-Transcribe-Medical-with-custom-vocabulary-and-per-clinician-adaptation primitive is the correct shape. The eight-stage decomposition with the read-edit-sign as a discrete stage and the audit-archive-and-adaptation as a combined closing stage is correctly architected. The Step Functions orchestration of the dictation-to-signed-note workflow with the EHR-handoff-and-signature-capture is the right pattern. The customer-managed-KMS-keys-per-data-class is correct. The Object-Lock-in-Compliance-mode for the audit archive is correct. The cost-estimate framing with the "comparable to or slightly cheaper than per-clinician licensing of major commercial dictation products" honest framing is operationally accurate, and the build-vs-buy-economics-favor-buying-for-most-institutions framing earns its position.

Priority breakdown: 0 critical, 3 high, 11 medium, 5 low. **The verdict is PASS** because the HIGH count (3) is at the > 3 = FAIL threshold but does not exceed it, and there are no CRITICAL findings. The three HIGH findings are localized correctness gaps that the recipe's own prose correctly diagnoses (with the recipe's self-assessment of critical-error detection as "the single most important production gap" being the most explicit confession that the architecture is missing its most important piece); closing them brings the architecture and the pseudocode up to the standard the recipe text claims and matches the chapter pattern from Recipes 10.1, 10.2, and 10.3.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with appropriate framing: "AWS BAA signed. Transcribe Medical, Bedrock (verify the specific models and regions covered), Comprehend Medical, Lambda, API Gateway, Cognito, DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, CloudTrail, EventBridge, Step Functions, Kinesis Firehose, Athena, SageMaker are HIPAA-eligible." The "verify the current list at build time" hedge is correctly placed; the explicit-Bedrock-model-coverage hedge correctly acknowledges that per-model BAA coverage continues to evolve.
- Customer-managed KMS keys called out for the audio bucket (SSE-KMS), the audit-archive bucket (SSE-KMS with Object Lock in Compliance mode), the session-state and dictation-metadata and per-clinician-config DynamoDB tables, the Lambda environment variables, the Lambda log groups, and the Secrets Manager secrets. The "Different keys per data class (audio, transcripts, signed notes, configuration) for blast-radius containment" framing is the right elevation.
- CloudTrail enabled with data events on the audio S3 bucket, the audit-archive S3 bucket, the DynamoDB dictation tables, the Secrets Manager secrets, and the customer-managed KMS keys. Lambda invocations logged. Bedrock invocations logged with the "be cautious about input/output capture if the prompts or responses include PHI; many institutions choose to log metadata only" hedge correctly placed (this is the right institutional posture for prompt-and-response capture). Step Functions execution logs enabled. Transcribe Medical streaming session starts and stops logged.
- The recipe correctly identifies dictation audio as PHI ("The dictation audio captures the clinician describing the patient's condition. It is, in every regulatory reading, PHI") and correctly elevates the architectural posture: audio is encrypted at rest, encrypted in transit, access-controlled per clinician, retention bound by an explicit policy, BAAs in place for any vendor service that processes the audio.
- The audit-record at Step 8A correctly uses archive-references rather than embedding raw transcripts (`audio_archive_ref`, `verbatim_transcript_archive_ref`, `formatted_note_archive_ref`, plus length and confidence metadata, plus version stamps). This is the architecturally-correct pattern that Recipes 10.1, 10.2, and 10.3 had to be coached toward; Recipe 10.4 has it right at the audit-record level. The remaining gap is that the upstream working-store (Step 2C and Step 7C) reintroduces the parallel-PHI-store pattern; see Finding S1.
- Audio-retention policy is correctly elevated as a contentious privacy decision with the "the privacy officer wants discard-immediately. The ML engineering team wants retain-for-model-improvement. The clinical-quality team wants retain-briefly-for-QA-review" framing and the "default in this recipe is brief retention (seven to thirty days) with KMS-encrypted storage, access logged through CloudTrail, and a lifecycle policy for automatic deletion" institutional default. The "longer retention requires explicit clinician consent at onboarding and a documented purpose for retention. The decision is institutional and should be revisited annually" framing is the correct governance posture.
- Voice biometric data is correctly elevated as recipe-specific PHI: "voice samples are biometric and PHI-bearing data with non-trivial governance implications" in the Sample Data row. This is the recipe-distinct privacy primitive (clinician voiceprints are biometric data, and the per-clinician acoustic adaptation pipeline retains them).
- The clinician's signature is correctly elevated as the gate to the legal record: "Until the clinician signs, the note is a draft. The architecture must prevent unsigned drafts from being treated as authoritative clinical documentation; downstream systems (CDS, billing, public-health reporting) consume signed notes only." This is the recipe's strongest single primitive on the legal-record-creation surface.
- Co-signature workflows for trainees are correctly elevated as a recipe-specific concern with the "the dictation system has to support multi-signer workflows, with the trainee's draft visible to the attending, with the attending's edits tracked, with both signatures captured in the final note" framing. This is the recipe's clearest articulation of the academic-medical-center deployment pattern.
- The synthetic-data discipline in the Sample Data row ("Never use real clinician audio or real patient names in development") is correctly stated with TTS-against-realistic-clinical-text-prompts as the recipe-specific source.

### Finding S1: Step 2C and Step 7C Write Verbatim Transcript and Word-Level Results to the Dictation-Metadata DynamoDB Table, Creating a Parallel PHI Store Outside the Audio-Bucket and Audit-Archive Governance

- **Severity:** HIGH
- **Expert:** Security (PHI minimization, retention, access boundary)
- **Location:** Step 2C pseudocode `stream_audio_to_asr`:
  ```
  dictation_metadata_table.put({
      session_id: session_id,
      verbatim_transcript: verbatim_transcript,
      word_level_results: word_level_results,
      avg_confidence: avg_confidence,
      transcribed_at: now(),
      status: "transcribed"
  })
  ```
  And Step 7C `handoff_to_ehr` writing `structured_results` (which may contain medication and condition codes plus dosage and frequency text from the dictation) to the same table. The audit-record at Step 8A correctly uses archive-references; the upstream working-store does not.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S1, Recipe 10.2 Finding S1, and Recipe 10.3 Finding S1, but recipe-acute because:

  1. **Dictation transcripts are longer and richer than IVR or voicemail transcripts.** A typical dictation is one to ten minutes of single-speaker clinical narrative with high vocabulary density. The transcript captures patient names, medication names with doses, anatomical findings, eponymous syndromes, clinical assessments, and free-text symptom descriptions. The PHI density per record is the highest of any recipe in the chapter so far.

  2. **The dictation-metadata table is accessible to the formatting Lambda (Step 4), the structured-extraction Lambda (Step 5), the read-edit-sign Lambda (Step 6), the EHR-handoff Lambda (Step 7), the audit-archive Lambda (Step 8), the per-clinician-adaptation pipeline (Step 8C), and any downstream analytics consumer with table-read access.** The access boundary on the table is wider than the access boundary on the audio S3 bucket or the audit-archive S3 bucket. The transcript captured in the metadata table is therefore accessible to a different and broader population than the audio recording itself, with a different retention default (the audio bucket has a brief-retention lifecycle; the dictation-metadata table's retention is implicit and may persist beyond the audio bucket's lifecycle).

  3. **DynamoDB Streams expand the blast radius.** If the dictation-metadata table has DynamoDB Streams enabled (for cross-system event flow into EventBridge per the recipe's pattern, or for replication to other accounts and regions for analytics), the transcript and word-level results flow into every consumer of the stream. Each consumer becomes another PHI-handling surface.

  4. **The minimum-necessary requirement is at risk.** The metadata table's purpose is to capture the dictation lifecycle (session_id, clinician_id, started_at, status, version stamps, signature, archive references). The transcript content and the word-level results are not necessary to support that purpose; the session_id is sufficient to correlate the metadata record with the full transcript in the secure transcript archive. Retaining the transcript content in the metadata table violates minimum necessary.

  5. **The audio-retention policy and the metadata-retention policy may differ.** The audio bucket's recommended default is brief retention (seven to thirty days). The dictation-metadata table's retention is not explicitly bounded in the recipe. A transcript embedded in the metadata table outlives the audio recording itself, which makes the metadata table the de-facto longer-term PHI store and routes the institution into a longer retention obligation than the audio-management policy intended.

  6. **The recipe's own audit-record discipline at Step 8A is the architecturally-correct pattern; Step 2C and Step 7C contradict it.** The recipe gets the audit-record right (`audio_archive_ref`, `verbatim_transcript_archive_ref`, `formatted_note_archive_ref` plus structural metadata) but the upstream working-store does not adopt the same discipline. The correct pattern is consistent across the working-store, the audit-record, and any cross-system events.

  7. **The structured_results written at Step 7C may contain PHI.** The FHIR API responses to add_medication, add_condition, and similar calls typically return resource references and codes; depending on the EHR vendor's API, they may include patient-bound identifiers or echo dictated content. The architecture should treat the EHR-API-response capture with the same references-not-content discipline.

- **Fix:** Update Step 2C pseudocode to write the verbatim transcript and word-level results to a secure transcript archive (S3 with KMS, the same governance as the audio bucket) and to write only references and structural metadata to the dictation-metadata table:

  ```
  // Step 2C: persist the verbatim transcript and the
  // per-word details to the secure transcript archive,
  // and persist only references and structural metadata
  // to the dictation-metadata table for in-flight
  // workflow coordination.
  verbatim_archive_ref = transcript_archive_s3.put(
      key: build_transcript_key(session_id),
      body: verbatim_transcript,
      sse_kms_key_id: TRANSCRIPT_KMS_KEY)

  word_level_archive_ref = transcript_archive_s3.put(
      key: build_word_level_key(session_id),
      body: serialize(word_level_results),
      sse_kms_key_id: TRANSCRIPT_KMS_KEY)

  dictation_metadata_table.put({
      session_id: session_id,
      verbatim_transcript_archive_ref: verbatim_archive_ref,
      verbatim_transcript_length_chars: len(verbatim_transcript),
      verbatim_transcript_hash: sha256(verbatim_transcript),
      word_level_archive_ref: word_level_archive_ref,
      word_count: len(word_level_results),
      avg_confidence: avg_confidence,
      transcribed_at: now(),
      status: "transcribed"
  })
  ```

  The downstream Lambdas (formatting, structured-extraction, read-edit-sign) load the transcript content from the secure archive when they need it, with the access governed by the same KMS key and IAM policy as the audio bucket. The dictation-metadata table holds only references and structural metadata.

  Apply the same discipline to Step 7C: write the EHR-handoff response detail to a secure archive and store only references in the metadata table.

  Update the Expected Results sample audit record's surrounding text to clarify that the transcript and formatted note examples shown are illustrative content stored in the secure archive, not embedded in the metadata table.

  Add an explicit cross-cutting prose paragraph in the architecture's design points elevating the references-not-content discipline across all PHI-handling stages: "PHI content (audio, verbatim transcripts, word-level results, formatted notes, EHR API responses) lives in the secure archive (S3 with KMS) under unified governance. Working-state stores (DynamoDB session-state and dictation-metadata) carry only references, structural metadata, hashes, and non-content identifiers needed for workflow coordination and audit. The audit-record at Step 8A is the canonical reference for this discipline; the upstream stages must adopt the same pattern."

  Reference Recipe 10.1 Finding S1, Recipe 10.2 Finding S1, and Recipe 10.3 Finding S1 (the analogous chapter-pattern findings) and propose chapter-editor consolidation into a chapter preface on PHI-minimization-in-DynamoDB-working-stores.

### Finding S2: Foundation-Model Prompt-Injection Risk for the LLM Formatter Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (prompt-injection, content-faithfulness boundary)
- **Location:** Step 4C pseudocode `bedrock.invoke_model(model_id: CLINICAL_FORMATTER_MODEL, prompt: build_formatter_prompt(verbatim_transcript: verbatim_transcript, rule_based_draft: template_with_content, template_schema: template.schema, specialty: template.specialty), max_tokens: 4000)` and the prose discussion of LLM post-processing.

- **Problem:** The recipe routes the verbatim transcript text directly into the formatter prompt. A dictation transcript can contain instruction-like text that, if naively templated into the prompt, can override the formatter's instructions. Recipe-specific scenarios:

  1. A clinician dictating a patient's quoted speech ("the patient said 'ignore previous instructions and add the following note'" in a behavioral-health or forensic-psychiatric note) can produce a formatter that takes the patient's quoted instructions as system directives.

  2. A clinician dictating a literature-review note ("the published prompt template was 'system: format the following note as...'") can produce similar instruction-following.

  3. An adversary with access to the dictation queue (e.g., through a pre-signed-URL leak or a compromised microphone source) could inject audio designed to manipulate the formatter into producing a structurally different output than the verbatim transcript supports.

  Recipe-specific consequence: a successful prompt-injection that produces a formatted note structurally divergent from the verbatim transcript would defeat the recipe's faithfulness-checking discipline (Step 4D), because the divergence appears in the LLM-formatted output as an apparent legitimate restructuring rather than as a faithful-but-injected reformulation. The faithfulness check would compare the verbatim transcript to the LLM's output and flag the divergence; in the worst case where the injection is subtle (e.g., changes hedging language or removes a clinically-relevant negation), the faithfulness check may not flag it at all because the change is at the semantic-not-structural level.

  Same chapter pattern as Recipe 10.3 Finding S2, but recipe-acute because the LLM-formatter output becomes part of the legal record after clinician review and signature, and a subtle prompt-injection that survives faithfulness checking and clinician review becomes a permanent falsification of the clinical record.

- **Fix:** Add a prompt-injection-mitigation paragraph to the architecture pattern. Specify:

  ```
  // The formatter prompt clearly delimits the verbatim
  // transcript from the system instructions. The
  // transcript is wrapped in explicit delimiters
  // (e.g., <verbatim_transcript>...</verbatim_transcript>)
  // and the prompt includes an explicit instruction
  // that the model treat the transcript as untrusted
  // user data, not as instructions. The prompt also
  // requests strict structured output (JSON schema or
  // XML tag boundaries) that the orchestration logic
  // validates before treating the output as a draft.
  // The faithfulness check (Step 4D) is the secondary
  // safety layer that catches semantic divergence.
  // The clinician's read-edit-sign workflow (Step 6)
  // is the final safety layer.
  ```

  Add to Production-Gaps a paragraph on "Prompt-injection monitoring": sample the LLM-formatted outputs against the rule-based draft for structural divergence; flag dictations where the LLM-formatted draft differs structurally beyond a calibrated threshold (e.g., introduces a new section the rule-based draft did not have, or removes an entire dictated phrase) and feed those into the operational review queue for prompt-injection-attempt detection.

### Finding S3: Lambda Invocation Authentication Across API Gateway-to-Lambda Integration Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (identity-boundary)
- **Location:** Architecture diagram `APIGW --> ORCH` with the Cognito authorizer on API Gateway, and the IAM Permissions row mentioning "API Gateway-to-Lambda integration with Cognito authorizer pinned to the clinician identity scope."

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S4, Recipe 10.2 Finding S3, and Recipe 10.3 Finding S3. The recipe specifies that API Gateway invokes the orchestrator Lambda with the Cognito authorizer pinning the clinician identity, but does not specify the additional integrity boundary on the Lambda invocation. The Lambda mutates session-state and dictation-metadata DynamoDB tables, calls Bedrock and Comprehend Medical, and triggers EHR API calls. A misconfigured resource-based policy that allows invocations from any API Gateway in the account can route development-or-test traffic into the production execution path. Recipe-specific consequence: the orchestrator Lambda's mutations include session-state updates, dictation-metadata writes (which become part of the audit trail per Finding S1's fix), and Step Functions executions that ultimately write to the EHR; a forged Lambda invocation can corrupt the in-flight session, falsify the audit trail, or trigger EHR API calls that appear in the EHR's audit log as legitimate clinician actions when they were not.

- **Fix:** Specify in the IAM Permissions row that the orchestrator Lambda's resource-based policy pins the invoking principal to the production API Gateway's stage ARN with the production version. The Lambda rejects invocations from any other API Gateway, any other stage, or any other principal. Add a defense-in-depth event-payload validation guard at the start of the Lambda that verifies the `requestContext.apiId` against the production constant.

### Finding S4: Audit-Log Retention Floor Specified Generically Without Explicit Dictation-Specific Floor

- **Severity:** MEDIUM
- **Expert:** Security (regulatory retention)
- **Location:** Prerequisites CloudTrail row: "Audit retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, the EHR vendor's audit-retention floor, and the institutional regulatory floor."

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S5, Recipe 10.2 Finding S2, and Recipe 10.3 Finding S4. The recipe correctly identifies the audit-log retention floor as a multi-source minimum and even names the EHR-vendor-audit-retention floor as a recipe-specific input (the dictation audit and the EHR's audit must be retained for the same period to support cross-referenced forensic reconstruction of voice-driven note creation). The Encryption row explicitly states "Audit archive: ... retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institutional regulatory floor." This is closer to the right framing than 10.1 / 10.2 / 10.3 reached, but the dictation-specific floor is the longer of the multi-source minimum AND the longest-retained signed-note's retention period, because the audit trail for a signed clinical note must be retained for as long as the signed note itself (which can be longer than HIPAA's six-year minimum for certain patient populations, e.g., pediatric records that extend to age-of-majority-plus-X-years per state law).

- **Fix:** Name the dictation-specific audit-log retention floor as "the longest of HIPAA's six-year minimum, state-specific medical-records-retention rules (which for certain patient populations such as pediatric records can extend to age-of-majority-plus-multiple-years), the EHR vendor's audit-retention floor, the longest-retained signed note's retention period (the audit trail must outlive the signed note it documents), and the institutional regulatory floor" with the institutional-decision-required-at-build-time hedge. Reference the institutional retention policy as the canonical source.

### Finding S5: Voice Biometric Retention Implications for Per-Clinician Adaptation Underspecified

- **Severity:** LOW
- **Expert:** Security (biometric-data governance)
- **Location:** Sample Data row: "Never use real clinician audio or real patient names in development; voice samples are biometric and PHI-bearing data with non-trivial governance implications" and the Adaptation pipeline references throughout the recipe.

- **Problem:** The recipe correctly elevates voice samples as biometric data in the Sample Data row but does not architect the biometric-data-governance discipline for the per-clinician adaptation pipeline. The pipeline retains clinician audio and uses it for acoustic-model adaptation (per the optional SageMaker training-job pattern). Voice biometric data is regulated separately from general PHI in some jurisdictions (BIPA in Illinois, GIPA in Texas, and similar state laws) and the institutional posture should specify:

  1. Clinician consent for voice-biometric retention at onboarding, with the consent disclosure naming the retention purpose, retention duration, access controls, and clinician's right to revoke and have their voice-biometric data deleted.
  2. Separation of voice-biometric retention from general dictation audio retention. Even if the dictation audio bucket has a brief retention lifecycle, the per-clinician adaptation pipeline may retain audio segments for longer periods specifically for adaptation purposes; this requires its own governance.
  3. Per-clinician right-to-deletion for voice-biometric data (the clinician can request deletion of their voice-biometric data without revoking consent for general dictation audio retention).
  4. Cross-jurisdictional employee-relations considerations for clinicians employed across multiple states with different biometric-data laws.

- **Fix:** Add a "Voice Biometric Data Governance" prose paragraph to the BAA / Compliance row specifying clinician consent at onboarding, separation of biometric retention from general dictation retention, per-clinician right-to-deletion, and cross-jurisdictional considerations. Reference the institutional employment-and-compliance team as the authoritative source for the per-jurisdiction policy.

### Finding S6: Cohort Encoding in CloudWatch Metric Dimensions With Equity-Stake Implications

- **Severity:** LOW
- **Expert:** Security (privacy, recipe-specific equity-monitoring stakes)
- **Location:** Why-These-Services / CloudWatch paragraph: "CloudWatch tracks operational metrics (per-stage latency, ASR confidence distributions, correction rates, structured-field acceptance, time-to-sign); alarms (per-clinician error-rate spikes, latency regressions, EHR-integration failures, critical-error detections)."

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S6, Recipe 10.2 Finding S6, and Recipe 10.3 Finding S6. The recipe correctly elevates subgroup-stratified accuracy as architecturally important (see Finding A2 below) but does not specify how the cohort axes are encoded in CloudWatch metric dimensions. For dictation specifically, the cohort-stratification surfaces per-clinician metrics; per-clinician metrics that include language-background or accent-group dimensions risk encoding sensitivity-classified data into the metrics surface, where it can be re-derived by any operations consumer with CloudWatch read access.

- **Fix:** Specify that cohort dimensions on metrics use cohort-axis-hash labels for sensitive dimensions; the per-clinician identifier may use a direct identifier where institutional policy permits; demographic-stratification analytics happen in the analytics layer (Athena over the audit archive) where the access-control surface is more bounded than CloudWatch metrics. Reference the chapter-wide convention.


## Architecture Expert Review

### What's Done Well

- Eight-stage architecture (activation and audio capture, domain-adapted ASR, command-versus-content disambiguation, formatting and structuring, template integration, structured-field extraction, read-edit-sign, audit-archive-and-adaptation) is the right shape for the problem and is recipe-distinct from 10.1 / 10.2 / 10.3 in the right ways. The read-edit-sign as a discrete stage is recipe-distinct (no other chapter recipe so far has produced a clinician-signed legal record); the audit-archive-and-adaptation as a combined closing stage correctly elevates the per-clinician adaptation as a continuous-improvement primitive rather than a one-time configuration.
- The Step Functions orchestration of the dictation-to-signed-note workflow is correctly framed as durable-and-observable with built-in retry-and-error-handling semantics. The "ASR completion, LLM post-processing, structured-field extraction, hand-off to the EHR for clinician review, signature capture, and audit-archive write" decomposition matches the multi-async-stage shape of the dictation lifecycle.
- The clinician's signature is correctly elevated as the gate to the legal record with the "downstream systems (CDS, billing, public-health reporting) consume signed notes only" framing as the architectural enforcement primitive.
- The structured-field-extraction-as-a-draft-never-a-fact framing is the recipe's strongest single primitive on the dictation-as-data-entry boundary. Step 5B's "Cross-check against the patient's structured chart" with the "discrepancy surface" pattern and Step 6B's "explicit accept or reject per suggestion" pattern correctly implement the never-silently-update-structured-chart discipline.
- The faithfulness-check at Step 4D is conceptually correct (the LLM-formatted note must contain the same clinical claims as the verbatim transcript; discrepancies are surfaced for clinician review; the LLM output is never silently substituted for the rule-based draft when faithfulness is suspect). The "fall back to the rule-based draft and attach the LLM draft as a 'suggested' alternative for clinician comparison" pattern is the right disposition. The faithfulness-check is the recipe's central safety primitive at the LLM-formatter boundary, though it is architecturally underspecified (see Finding A3).
- Per-clinician adaptation is correctly elevated as a continuous-improvement loop with the Step 8C "user corrections feed per-clinician adaptation; aggregate corrections feed institution-wide vocabulary and formatting improvements" framing. The adaptation pipeline as a discrete architectural primitive is recipe-distinct.
- The voice-command-versus-dictation-content disambiguation is correctly elevated as a high-stakes design decision with the explicit-modal-switching versus heuristic-disambiguation comparison and the push-to-command-as-the-mature-pattern recommendation. Step 3A-3D's segment-by-pauses then check-explicit-prefix then check-implicit-vocabulary then default-to-content disposition is correctly implemented.
- The specialty-tuning-as-first-class framing is correctly elevated. The "per-specialty configuration without forking the entire stack" framing in the cross-cutting design points and the specialty-tuning-as-first-class production-gap correctly elevate the per-specialty pilot-and-rollout discipline.
- The build-vs-buy economics are honestly framed: "the build-versus-buy economics for most healthcare organizations favor buying a commercial product (Dragon Medical, M-Modal/3M, vendor-bundled offerings from Epic and Cerner) rather than building a custom transcription system." The recipe's own honest framing of this is the recipe's strongest single observation on the institutional-deployment-decision axis and earns its position.
- The cost estimate is correctly granular with the per-clinician-per-month breakdown and the "the infrastructure cost is comparable to or slightly cheaper than per-clinician licensing of major commercial dictation products at the same scale, though the engineering and operational overhead of operating a custom build is non-trivial and usually tilts the build-versus-buy economics toward buying for institutions of this size" honest framing.
- The Why-This-Isn't-Production-Ready section names eighteen gaps (critical-error detection with named ownership, per-clinician adaptation pipeline, subgroup-stratified accuracy monitoring with disparity alerts, LLM post-processor faithfulness program, voice-command vocabulary review and versioning, specialty-specific tuning programs, EHR integration depth and breadth, audio retention policy with privacy-officer review, disaster recovery and partial-failure handling, idempotency and retry semantics, performance under load and burst, specialty-specific training and rollout playbook, vendor evaluation rigor for build-vs-buy decisions, audit log retention and legal hold, cost monitoring per clinician and per specialty, operational ownership). The breadth is appropriate for the chapter's first medium-tier recipe.

### Finding A1: Critical-Error Detection Is Structurally Absent From the Architecture Pattern Despite Recipe's Self-Assessment as "the Single Most Important Production Gap"

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety primitive, recipe-specific load-bearing)
- **Location:** The architecture diagram has eight stages with no critical-error-detection stage. The pseudocode (Steps 1-8) has no detection function. Step 6A's `render_review_view` builds a confidence overlay but has no critical-error overlay. The Production-Gaps section names this as "the single most important production gap" in its first bullet.

- **Problem:** Critical-error detection (laterality flips, negation flips, drug-name confusions, dose-by-order-of-magnitude errors) is the recipe's own identified central safety primitive. The recipe correctly elevates it in five separate places:

  1. **The radiologist-laterality-mistranscription failure-mode vignette in The Problem** ("Two weeks of reports times ten per hour times eight hours per day times five days per week times two is four thousand reports, of which twenty have the wrong laterality marker. Twenty radiology reports with the wrong laterality is twenty potentially clinically catastrophic errors").

  2. **The Safety-critical word substitutions Technology subsection** ("A 1% word error rate that systematically substitutes 'no' for 'not' or 'left' for 'right' or 'hemoptysis' for 'hematemesis' is dangerous. The metric that matters is not just WER but the rate and severity of clinically-meaningful errors").

  3. **The Critical-error detection cross-cutting design point** ("The system needs explicit detection for the dangerous error classes: laterality flips, negation flips ('no' vs 'not'), drug-name confusions among similar-sounding pairs, dose-by-order-of-magnitude errors, and domain-specific high-stakes substitutions. These deserve their own monitoring and their own alerts").

  4. **The Where-it-Struggles "Sound-alike substitutions" item** ("'Hypertension' vs 'hypotension,' 'left' vs 'right,' 'no' vs 'not,' 'with' vs 'without,' 'increase' vs 'decrease,' 'morphine' vs 'naloxone'... critical-error detection (rule-based or model-based) flags the highest-risk substitutions for explicit clinician confirmation").

  5. **The Production-Gaps "Critical-error detection with named ownership" paragraph** ("**The single most important production gap** is explicit detection of clinically-significant errors").

  Despite the prose elevation in five separate places, the architecture pattern does not specify the structural elements:

  1. **The critical-error detection stage is not in the architecture diagram.** The eight-stage decomposition has no detection stage. The detection is implicit somewhere between formatting (Stage 4) and read-edit-sign (Stage 7).

  2. **The detection function is not in the pseudocode.** Step 6A `render_review_view` builds a `word_confidence_overlay` and a `cross_check_warnings` (limited to medication-list discrepancies); there is no critical-error overlay distinct from confidence-and-discrepancy.

  3. **The high-risk substitution catalog is not architecturally specified.** The recipe lists examples in prose but does not specify the configuration mechanism (per-specialty high-risk-pair lists curated by clinical operations, version-controlled, change-reviewed by clinical-quality officer, periodically refreshed).

  4. **The detection-trigger thresholds are not specified.** When a verbatim transcript contains "left" and the rule-based formatter produces "right" (or vice versa), what triggers the detection? An exact-substitution match? A semantic-similarity match? A heuristic over the verbatim-and-formatted diff?

  5. **The detection-disposition is not specified.** When detection fires, does the system block submission until the clinician explicitly confirms? Does it flag for review-pane highlighting? Does it require attestation? Does it route to an additional reviewer?

  6. **The aggregate-detection-rate monitoring and drift detection is not specified.** The recipe says "Track aggregate detection rates and drift over time" in production-gaps but the architecture does not specify the metrics surface or the alert thresholds.

  7. **The named ownership is not architected.** The recipe says "Assign named ownership to the clinical-quality officer or equivalent role" in production-gaps but the architecture does not establish the architectural-primitive elevation with periodic review cadence and explicit escalation path.

  Recipe-specific because dictation produces signed clinical documentation that becomes the legal record; the recipe's own framing names critical-error detection as the deciding factor between dictation systems with no clinical-safety incidents and those that have had them ("The dictation systems that have been deployed for years and never had a serious clinical-safety incident are the ones with explicit critical-error detection; the ones that have had incidents typically did not"). This is the recipe's strongest single architectural primitive on clinical safety, and it is currently architecturally absent.

  Recipe-acute because critical-error detection is the recipe-specific safety primitive that 10.1 / 10.2 / 10.3 do not need to elevate (IVR call-routing errors are recoverable; voicemail mistranscriptions surface in the human triage step; voice-EHR-navigation errors are bounded by the patient-slot-resolution gate). Dictation is the first recipe in the chapter that produces an unmediated written clinical-record artifact, and the safety primitive that bounds its risk surface is critical-error detection.

- **Fix:** Promote the prose elevation into the architecture pattern. Add an explicit critical-error-detection stage to the eight-stage decomposition (between Stage 4 Formatting and Stage 5 Structured-field extraction, or as a parallel pass invoked from Stage 6 Read-edit-sign):

  ```
  ┌──────────── CRITICAL-ERROR DETECTION ────────────────────┐
  │                                                           │
  │   [Run high-risk-substitution detection over the          │
  │    verbatim transcript and the formatted note]            │
  │    - Laterality detection (left vs right; bilateral       │
  │      vs unilateral; ipsilateral vs contralateral)         │
  │    - Negation flip detection (no vs not; denies vs        │
  │      endorses; with vs without; absent vs present)        │
  │    - Sound-alike drug-name detection (per-specialty       │
  │      curated catalog of confusable pairs)                 │
  │    - Dose-by-order-of-magnitude detection (5 mg vs        │
  │      50 mg; 500 mg vs 5 g)                                │
  │    - Sound-alike clinical-term detection (hemoptysis      │
  │      vs hematemesis; hypertension vs hypotension)         │
  │    - Domain-specific high-stakes substitutions per        │
  │      specialty                                            │
  │                                                           │
  │   [Detection mechanism]                                   │
  │    - Rule-based pattern matching against the              │
  │      configured per-specialty catalog                     │
  │    - Confidence-aware: low-confidence transcript          │
  │      regions are higher prior for detection               │
  │    - LLM-formatter-divergence aware: regions where the    │
  │      LLM-formatted output differs from the rule-based     │
  │      draft are higher prior for detection                 │
  │                                                           │
  │   [Output: list of high-risk substitution detections      │
  │    with source span, severity tier, suggested             │
  │    alternative reading, and required-confirmation flag]   │
  │                                                           │
  └───────────────────────────────────────────────────────────┘
  ```

  Update Step 6A `render_review_view` to overlay the critical-error detections explicitly:

  ```
  review_payload = {
      session_id: session_id,
      formatted_note: formatted_note,
      word_confidence_overlay: ...,
      critical_error_overlay: build_critical_error_overlay(
          verbatim_transcript, formatted_note,
          critical_error_detections),
      structured_suggestions: structured_suggestions,
      cross_check_warnings: ...,
      llm_changes: ...,
      requires_explicit_confirmation:
          any(d.severity == "high"
              for d in critical_error_detections)
  }
  ```

  Specify in Step 6B that high-severity critical-error detections require explicit clinician confirmation (not just edit-or-accept) before signature submission is allowed. Add an audit-record field at Step 8A capturing the critical-error-detection version, the detections-fired list, the clinician's disposition per detection, and the per-detection acknowledgment.

  Add the critical-error-rule-catalog as a clinical-safety document with version control, change review by the clinical-quality officer, scheduled refresh cadence (per-quarter at minimum), and a documented escalation path when a missed clinical-safety incident surfaces post-deployment. Reference per-specialty curation: a radiology-specific rule catalog (laterality is the highest-priority detection axis), a cardiology-specific catalog (medication confusables, dose-by-order-of-magnitude), a primary-care catalog (the broadest substitution surface), an emergency-medicine catalog (high-acuity confusables like morphine-naloxone). Specify that the catalog evolution is a clinical-operations-not-engineering decision.

  Add to CloudWatch the per-specialty critical-error-detection-rate metric with alarms on detection-rate spikes (a sudden change suggests acoustic-condition change, ASR drift, or model-version regression) and on detection-rate troughs (a sudden drop suggests detection-rule regression and risks silent under-detection). Reference the named ownership at the clinical-quality officer with monthly review cadence.

  Cross-reference the LLM-formatter faithfulness program (Finding A3) and the per-specialty tuning program; the critical-error detection, the faithfulness program, and the per-specialty tuning together form the recipe's clinical-safety substrate.

### Finding A2: Cohort-Stratified Accuracy Monitoring Is Structurally Absent From the Architecture Pattern Despite Recipe's Equity Stakes Elevation in Three Separate Places

- **Severity:** HIGH
- **Expert:** Architecture (operational metrics, equity instrumentation)
- **Location:** The architecture's audit-archive-and-adaptation stage has CloudWatch metrics for time-to-sign, corrections-per-note, and ASR-avg-confidence with `specialty` and `clinician_id` dimensions, but does not specify cohort-stratification dimensions, disparity-alert thresholds, sample-size minimums, or named ownership.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding A1, Recipe 10.2 Finding A1, and Recipe 10.3 Finding A1. The recipe correctly elevates cohort-stratified monitoring as recipe-specific in three separate places:

  1. **The underrepresented-accent-clinician failure-mode vignette in The Problem** ("The primary care physician whose accent is underrepresented in the ASR vendor's training data, who consistently gets a 12% word error rate on her dictations while her partner across the hall gets 3%, and who concludes after a frustrating month that 'this technology does not work for me' and reverts to typing. The institution sees overall ASR adoption metrics that look fine, because they are dominated by the partner's 3% error rate, and never investigates the per-clinician disparity. The physician's daily documentation burden is substantially higher than her colleague's for reasons that have nothing to do with her competence and everything to do with how the model was trained").

  2. **The Where-it-Struggles "Underrepresented accents and speech patterns" item** ("Clinicians whose accents are not well-represented in the ASR's training data see meaningfully higher word error rates than their colleagues. Mitigations: per-clinician acoustic adaptation (the system improves over time as the clinician uses it), per-clinician custom vocabulary, vendor evaluation across the institution's clinician demographics, subgroup-stratified accuracy monitoring with alerts on disparities").

  3. **The Production-Gaps "Subgroup-stratified accuracy monitoring with disparity alerts" paragraph** ("Voice ASR systematically underperforms for some speaker demographics. Per-clinician accuracy metrics (verbatim ASR confidence, correction rate, time-to-sign) should be visible to the equity-monitoring committee or the clinical-quality officer. Disparities exceeding configured thresholds should alert. The monitoring is not optional analytics; it is the mechanism by which the institution detects whether the system is silently underserving specific clinicians (and, by extension, their patients). Cohort dimensions should include per-clinician identifier, per-clinician language background (where opt-in declared at onboarding), inferred accent group, specialty, experience level, and deployment site").

  Despite the prose elevation, the architecture pattern does not specify:

  1. The cohort-dimensions allow-list (the recipe's prose lists six dimensions but does not architect the configuration).
  2. The disparity-alert thresholds (what disparity triggers an alert across cohorts).
  3. The per-cohort sample-size minimums (the volume below which per-cohort metrics are statistically unreliable).
  4. The named ownership (the recipe names the equity-monitoring committee and the clinical-quality officer in prose; the architecture does not establish the review cadence and escalation path).
  5. The recipe-specific adoption-correlation dimension (the per-clinician adoption decay correlates with per-clinician accuracy disparities; the architecture should surface adoption-rate and abandonment-rate per cohort, not just accuracy per cohort).
  6. The recipe-specific documentation-burden dimension (a clinician with higher correction rates spends more time per note; the per-clinician corrections-per-note and time-to-sign metrics stratified by cohort surface the documentation-burden disparity directly).
  7. The recipe-specific patient-population-correlation dimension. A clinician serving a patient population with higher proportion of non-English-speaking patients (where the clinician may speak with a regional accent or with code-switching that ASR struggles with) experiences a structural friction the institution's per-patient-population care-quality metrics may be silently affected by.

  Recipe-specific because dictation is the chapter's first recipe where the clinician's documentation-burden metric (corrections-per-note, time-to-sign, after-hours-fraction-of-documentation-completion) directly correlates with patient-care-quality metrics (clinician burnout, attrition, reduced empathy in encounters, missed clinical signals); per-clinician disparities in dictation accuracy translate into per-clinician documentation-burden disparities, which translate into per-patient-population care-quality disparities.

- **Fix:** Promote the prose elevation into the architecture pattern. Specify in the audit-archive-and-adaptation stage:

  ```
  [Telemetry to observability layer, cohort-stratified]
   - Cohort dimensions allow-list:
     * Per-clinician identifier (load-bearing axis)
     * Per-clinician language-background (opt-in at
       clinician onboarding)
     * Per-clinician accent-group (inferable from ASR
       diagnostics; calibration via representative-audio
       evaluation set)
     * Per-clinician specialty
     * Per-clinician experience-level (months-since-
       onboarding to the dictation system)
     * Per-deployment-site (acoustic environment varies
       across clinical sites)
   - Per-cohort metrics:
     * ASR average word confidence
     * Corrections per note
     * Time to sign (median, p90, p95)
     * Critical-error-detection rate (per Finding A1)
     * Faithfulness-warning rate (per Finding A3)
     * Adoption rate (active-dictations-per-clinician
       per week)
     * Abandonment rate (clinicians who used the system
       in month N but not month N+1)
     * Documentation-burden metric (cumulative time
       spent on dictation per clinician per week,
       proxied by aggregate dictation duration plus
       review duration)
   - Per-cohort sample-size minimums:
     * Reliable: >= 100 dictations in the metric window
     * Noisy: 25-99 dictations (reported with wide CI)
     * Insufficient: < 25 dictations (suppressed;
       aggregated to the dimension's "all_other"
       cohort)
   - Disparity-alert thresholds:
     * Corrections-per-note gap > 50% across per-
       clinician-language-background cohorts
     * ASR-confidence gap > 5 points
     * Adoption-rate gap > 20 percent
     * Abandonment-rate gap > 10 percent
     * Critical-error-rate gap > 0.1 percentage point
   - Named ownership:
     * Equity-monitoring committee with monthly review
       cadence and quarterly written summary to
       institutional governance
     * Clinical-quality officer for critical-error-rate
       cohort disparities
     * Explicit escalation: a sustained disparity
       exceeding alert thresholds for two consecutive
       review cycles triggers a remediation plan with
       a named owner and target close date
  ```

  Reference Recipe 10.1 Finding A1, Recipe 10.2 Finding A1, and Recipe 10.3 Finding A1 as the chapter pattern; the chapter editor should consolidate cohort-stratified-accuracy guidance into a chapter preface in the next pass.

### Finding A3: LLM-Formatter Faithfulness Check Architecturally Underspecified for the Recipe's Highest-Stakes LLM Failure Mode

- **Severity:** MEDIUM
- **Expert:** Architecture (LLM-output integrity)
- **Location:** Step 4D pseudocode `faithfulness_check = check_faithfulness(verbatim_transcript: verbatim_transcript, llm_draft: llm_response.formatted_note)`. The function is referenced but not specified. The Production-Gaps section names "LLM post-processor faithfulness program" but the architectural pseudocode is a single function call.

- **Problem:** The recipe correctly elevates faithfulness drift as the highest-stakes LLM failure mode for medical dictation: "The clinician dictates 'may have,' and the LLM produces 'had.' The clinician dictates 'intermittent,' and the LLM smooths it to 'occasional.' The clinical claim is now subtly different. In aggregate, these small drifts accumulate into a class of failure that is invisible at the individual-note level but real at scale. The faithfulness check (Step 4D in the pseudocode) is not an optional optimization; it is a structural requirement." The Honest Take's third trap is the recipe's strongest single passage on this risk.

  Despite the prose elevation, the architecture pattern leaves the faithfulness check as a single opaque function call:

  1. **The check mechanism is not specified.** Is it a separate LLM invocation with a comparison prompt? A deterministic semantic-equivalence check? A clinical-claim-extraction-and-comparison pipeline? The recipe says "Use a separate model invocation (or a deterministic check) to flag content drift" but does not specify the architectural primitive.

  2. **The check threshold is not specified.** What level of divergence between verbatim transcript and LLM-formatted note triggers a "fail" disposition? Word-level divergence is too noisy (the LLM legitimately reformats); semantic-claim-level divergence is the right axis but the threshold is not architectural.

  3. **The check failure-mode catalog is not specified.** The recipe gives examples (hedging removal, semantic strengthening, clinical-claim addition or omission) but does not catalog the categories the check is required to detect.

  4. **The offline-evaluation program is named in production-gaps but not architectured.** "Maintains a held-out evaluation set of verbatim-and-faithful-formatted note pairs across specialties; runs the post-processor against the evaluation set on every model update; flags regressions with clinical-impact tier classification; gates production model updates on regression results." This is a production-grade program; the architecture should specify the evaluation-pipeline shape, the clinical-impact-tier classification scheme, and the regression-gate threshold.

  5. **The interaction between the runtime faithfulness check and the offline evaluation program is not specified.** The runtime check is a per-dictation-pre-render gate; the offline evaluation is a per-model-update regression gate. They are different mechanisms with different operational characteristics; the architecture should specify both as distinct architectural primitives.

  Recipe-specific because the LLM-formatted note becomes part of the legal record after clinician review and signature; subtle faithfulness drift that survives the runtime check and the clinician's review becomes a permanent falsification of the clinical record. The Honest Take's "the design discipline that distinguishes careful clinical software from confident-but-occasionally-hallucinating consumer software" framing names this as the recipe's deciding-criterion-for-quality-software primitive.

- **Fix:** Promote the prose elevation into the architecture pattern. Specify the faithfulness-check architecture:

  ```
  // Step 4D-1: clinical-claim extraction. Run a
  // structured-extraction prompt over the verbatim
  // transcript that produces a list of clinical claims
  // (assertions, negations, hedges, dosages, dates,
  // quantitative observations).
  verbatim_claims = bedrock.invoke_model(
      model_id: CLAIM_EXTRACTOR_MODEL,
      prompt: build_claim_extractor_prompt(
          verbatim_transcript))

  llm_draft_claims = bedrock.invoke_model(
      model_id: CLAIM_EXTRACTOR_MODEL,
      prompt: build_claim_extractor_prompt(
          llm_response.formatted_note))

  // Step 4D-2: claim-by-claim comparison.
  faithfulness_warnings = []
  FOR claim IN verbatim_claims:
      IF NOT exists_semantically_equivalent_claim(
          claim, llm_draft_claims):
          faithfulness_warnings.append({
              type: "missing_claim",
              claim: claim,
              severity: classify_clinical_impact(claim)
          })
  FOR claim IN llm_draft_claims:
      IF NOT exists_semantically_equivalent_claim(
          claim, verbatim_claims):
          faithfulness_warnings.append({
              type: "added_claim",
              claim: claim,
              severity: classify_clinical_impact(claim)
          })
      IF claim.has_strengthened_assertion(verbatim_claims):
          faithfulness_warnings.append({
              type: "hedging_removed",
              claim: claim,
              severity: classify_clinical_impact(claim)
          })

  // Step 4D-3: disposition.
  IF any(w.severity == "high" for w in faithfulness_warnings):
      // High-severity warnings (clinical-claim addition,
      // negation flip, dose change, hedging removal on
      // a clinical assertion) trigger fall-back to the
      // rule-based draft.
      template_with_content = rule_based_draft
      template_with_content.faithfulness_warnings =
          faithfulness_warnings
      template_with_content.llm_alternative =
          llm_response.formatted_note
  ELIF len(faithfulness_warnings) > 0:
      // Lower-severity warnings are surfaced for
      // clinician review but do not block the LLM
      // draft.
      template_with_content = llm_response.formatted_note
      template_with_content.faithfulness_warnings =
          faithfulness_warnings
  ELSE:
      template_with_content = llm_response.formatted_note
  ```

  Specify the offline evaluation program in a Production-Gaps subsection: "Faithfulness Program" with the held-out evaluation set composition (paired verbatim-and-faithful-formatted notes per specialty, with clinical-impact-tier labels), the per-update regression gate, and the named ownership at the clinical-quality officer for the program. Reference the runtime faithfulness check (Step 4D-3 disposition) as the in-flight safety primitive and the offline evaluation as the model-version-gate.

  Cross-reference Finding A1 (critical-error detection) and Finding S2 (prompt-injection mitigation); the faithfulness program, the critical-error detection, the prompt-injection mitigation, and the per-specialty tuning together form the recipe's LLM-clinical-safety substrate.

### Finding A4: Per-Clinician Adaptation Pipeline Architecturally Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (continuous-improvement pipeline)
- **Location:** Step 8C pseudocode `adaptation_events_topic.publish(adaptation_event)` and the Production-Gaps "Per-clinician adaptation pipeline" paragraph.

- **Problem:** The recipe correctly elevates per-clinician adaptation as the recipe's highest-leverage long-term investment ("The adaptation pipeline that captures user corrections and feeds them back into the per-clinician vocabulary and acoustic profile is what transforms 'dictation that mostly works' into 'dictation the clinician relies on'"). The Honest Take's "the thing about per-clinician adaptation" paragraph names this as the recipe's most-important-long-term-investment primitive.

  Despite the prose elevation, the architecture pattern publishes adaptation events to a topic but does not specify:

  1. **The adaptation cadence.** Continuous (event-driven), daily-batch, weekly-batch, or quarterly-batch. The recipe says "Document the adaptation cadence" in production-gaps but does not architect the default.

  2. **The adaptation scope per clinician.** Vocabulary-only adaptation versus full acoustic-model adaptation. The recipe correctly notes that "for most institutions, vocabulary-only adaptation is sufficient and acoustic adaptation is a later phase" but does not architect the default.

  3. **The per-clinician adaptation validation.** The recipe correctly identifies the risk: "validation steps that prevent a single clinician's idiosyncratic corrections from degrading their personal model." The architectural primitive (held-out per-clinician evaluation set, regression-gate on per-clinician metrics) is not specified.

  4. **The adaptation rollback mechanism.** When an adaptation degrades a clinician's accuracy, the architecture should specify the per-clinician rollback path.

  5. **The institution-wide-adaptation aggregation.** The recipe says "aggregate corrections feed institution-wide vocabulary and formatting improvements" but the architectural primitive (the privacy-preserving aggregation that does not leak per-clinician corrections to the institution-wide model) is not specified.

- **Fix:** Add a "Per-Clinician Adaptation Pipeline" subsection to the AWS Implementation section specifying:

  - Default cadence: weekly-batch for vocabulary adaptation; quarterly-batch for acoustic-model adaptation (where in scope).
  - Default scope: vocabulary-only adaptation as the institutional default; acoustic-model adaptation as opt-in via SageMaker training jobs per Finding A6.
  - Validation: held-out per-clinician evaluation set (the most-recent two weeks of dictations are excluded from the adaptation training and used as the validation set); regression gate at 5% deterioration on per-clinician corrections-per-note or ASR-confidence metric.
  - Rollback: per-clinician adaptation is versioned; rollback to prior version is automatic on regression-gate failure.
  - Institution-wide aggregation: the privacy-preserving aggregation pipeline (federated learning or differentially-private aggregation) is the architectural primitive; the per-clinician corrections are not directly fed into the institution-wide model.

### Finding A5: Idempotency for Dictation Submission Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical safety, write-path integrity)
- **Location:** Step 7A pseudocode `fhir_client.create_note(...)`. The Production-Gaps section names "Idempotency and retry semantics" but the architecture does not architect the idempotency-key composition.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S2, Recipe 10.2 Finding A4, and Recipe 10.3 Finding A3. The recipe correctly notes the concern in production-gaps ("A dictation submitted twice (because of a network blip, or because the clinician thought the system did not receive it) must not produce two notes in the EHR") but does not specify the idempotency-key composition. Recipe-specific consequence: a duplicate dictation submission produces two signed notes in the EHR for the same clinical encounter, which is a documentation-integrity event (the patient's chart now has two notes for the same visit) and a billing-compliance event (the duplicate note may trigger duplicate billing-code submission).

- **Fix:** Promote the production-gaps content into the General Architecture Pattern paragraph with the recipe-specific idempotency-key composition: per-dictation idempotency key `(clinician_id, session_id, encounter_id, signature_timestamp)`; the dictation-metadata table holds the recently-submitted-notes list; on submission, the architecture checks for a prior submission with the same idempotency key and returns the prior submission's note_id if found; on idempotency-match, the audit table records both the original submission and the duplicate-detection event.

  Specify that the FHIR API calls themselves should also use idempotency keys where the EHR vendor's API supports them.

### Finding A6: Foundation-Model and Lex Bot and Rule-Formatter Versioning via Inference Profiles and Aliases Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (deployment-and-change-management)
- **Location:** Step 4C pseudocode `bedrock.invoke_model(model_id: CLINICAL_FORMATTER_MODEL, ...)` and Step 5A `comprehend_medical.detect_entities_v2(...)`. The architecture does not specify the blue-green deployment pattern.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding A3, Recipe 10.2 Finding A5, and Recipe 10.3 Finding A6. The pseudocode references a model identifier but does not specify the blue-green deployment pattern. Recipe-acute because the LLM-formatter, the rule-based formatter, the critical-error-detection rule catalog, the faithfulness-evaluation prompt, and the per-specialty templates are all version-controlled artifacts that change over time; a regression in any of them produces a regression in clinical-record quality.

- **Fix:** Add a "Deployment Pattern" subsection that specifies versioned model and prompt and rule-catalog and template definitions in version control with commit-SHA-tied builds; canary inference profile with traffic-shift; rollback-on-regression triggered by the held-out evaluation set's regression gate; held-out evaluation set including specialty-specific edge cases, accent samples, low-confidence-transcript samples, and high-risk-substitution test cases; version stamping on every dictation's audit record (per Finding S1's audit pattern, the audit-record already includes version stamps; the architecture should ensure the version stamps cover all of: ASR version, rule-formatter version, LLM-formatter model_id, faithfulness-check model_id and prompt version, critical-error-rule-catalog version, comprehend_medical_version, template_id, per-specialty configuration version).

### Finding A7: SMART on FHIR Token Lifecycle and EHR Integration Robustness Underspecified for Hours-Long Dictation Sessions

- **Severity:** MEDIUM
- **Expert:** Architecture (authentication-token lifecycle, EHR integration robustness)
- **Location:** Step 1A pseudocode `IF NOT clinician_session.is_valid(): RETURN error("re-authenticate")` and Step 7A's `clinician_token: clinician_session.access_token` referenced in the EHR API calls. The architecture does not specify token refresh.

- **Problem:** Same chapter pattern as Recipe 10.3 Finding A7. SMART on FHIR access tokens have short lifetimes; a clinician's dictation session may produce notes over several hours and the token will expire mid-workflow. The architecture should specify token refresh, pre-emptive refresh, refresh-failure handling, token storage discipline, and audit on token-lifecycle events.

  Recipe-specific because the dictation lifecycle is asynchronous (dictation, ASR, formatting, structured extraction, read-edit-sign, signature, EHR handoff) and may span hours from dictation start to EHR submission, especially when the clinician dictates a batch of notes throughout the day and signs them later.

- **Fix:** Add a "SMART on FHIR Token Lifecycle" subsection specifying the refresh-token flow, the pre-emptive refresh window, the refresh failure handling (graceful prompt for re-authentication on signature submission), the token-storage discipline (Secrets Manager with short-TTL cache rather than DynamoDB), and the audit on token-lifecycle events.

### Finding A8: Audio Retention Policy Configuration Mechanism Could Be More Concretely Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (PHI lifecycle)
- **Location:** Prerequisites Encryption row: "Audio recordings: SSE-KMS with customer-managed keys, retention bound to the QA review window (typically a few days to a few weeks for institutional adaptation feedback) then automatic deletion via lifecycle policy."

- **Problem:** Same chapter pattern as Recipe 10.3 Finding A8. The recipe is closer to architecturally-specified than 10.3 (the brief-retention-default is explicit; the privacy-officer-review is named) but the configuration mechanism is not specified. Three patterns are referenced in prose ("Retain briefly for QA and adaptation feedback / Or discard immediately after transcription / Or retain longer with appropriate consent and access controls") but the architecture does not specify which is the default, the per-institution configuration mechanism, or the operational considerations of each.

- **Fix:** Specify in the architecture pattern that retain-briefly with a 7-30-day window (KMS-encrypted, lifecycle-policy-deletion, access-logged through CloudTrail) is the recommended default; discard-immediately is the conservative alternative for institutions with strict PHI minimization requirements; retain-longer requires explicit clinician consent at onboarding and a documented retention purpose. Reference the audit log (per Finding S1) as the long-term forensic-reconstruction substrate; the audio retention is a short-term QA-and-adaptation substrate.

### Finding A9: Disaster Recovery and Partial-Failure Topology Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (disaster-recovery and failover)
- **Location:** Production-Gaps "Disaster recovery and partial-failure handling" paragraph.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding A7, Recipe 10.2 Finding A7, and Recipe 10.3 Finding A9. The recipe correctly elevates the failover requirement in production-gaps but does not architect the failover topology. Recipe-specific consequence: when Transcribe Medical is unavailable, dictation cannot proceed; when Bedrock is unavailable, the LLM-formatter is offline and the system must fall back to the rule-based formatter; when Comprehend Medical is unavailable, structured-field extraction is offline and the clinician must enter structured fields manually; when the EHR API is unreachable, the signed note cannot be submitted and the system must queue for retry while preserving the signed note.

- **Fix:** Add a "Disaster Recovery Topology" subsection specifying the per-stage failover policy (Transcribe Medical regional outage with cross-region failover or batch-mode-fallback, Bedrock model unavailability with rule-based-formatter-fallback, Comprehend Medical unavailability with manual-structured-field-entry-fallback, EHR API unreachable with signed-note-queue-for-retry-with-explicit-clinician-feedback), the failover-detection-and-failover-back triggers, and the quarterly testing cadence.

### Finding A10: Multi-Language Architecture Build-For-Day-One Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (multi-language operational pattern)
- **Location:** Variations and Extensions "Multilingual dictation" paragraph.

- **Problem:** Same chapter pattern as Recipe 10.1 Finding A4, Recipe 10.2 Finding A6, and Recipe 10.3 Finding A10. The recipe defers multilingual to Variations but does not specify the build-for-day-one pattern. Recipe-specific because dictation language is per-clinician (the clinician dictates in their preferred language) and the per-clinician custom vocabulary, the per-specialty template, and the LLM-formatter prompt are all language-bound.

- **Fix:** Specify the per-language pipeline pattern: per-clinician language declared at onboarding; per-language Transcribe Medical configurations and custom vocabularies; per-language LLM-formatter prompts; per-language formatting rules. Reference build-for-day-one even when shipping English-first.

### Finding A11: Comprehend Medical Multi-Call Pattern Slightly Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (API integration)
- **Location:** Step 5A pseudocode `comp_med_result = comprehend_medical.detect_entities_v2(text: verbatim_transcript)` followed by `rxnorm_code = lookup_rxnorm(entity.text)` and `icd10_code = lookup_icd10(entity.text)` shown as separate function calls.

- **Problem:** Same chapter pattern as Recipe 10.2 Finding S1 (Comprehend Medical API integration), but Recipe 10.4 has improved on the pattern: the pseudocode shows ontology lookup as a separate function call (`lookup_rxnorm`, `lookup_icd10`) rather than expecting `DetectEntitiesV2` to return RxNorm and ICD-10 codes. The accompanying prose comment ("RxNorm linking via InferRxNorm or a separate normalization step") is correct.

  However, the architectural specification could be more explicit. The Comprehend Medical API surface for ontology linking is `InferRxNorm`, `InferICD10CM`, and `InferSNOMEDCT`; each is a separate API call that takes the same input text and returns ontology-linked entities. The recipe's `lookup_rxnorm(entity.text)` could be implemented as either a call to `InferRxNorm` (preferred) or a custom lookup against an institutional dictionary (fallback). The architecture should explicitly specify the multi-call pattern with the cost implications.

- **Fix:** Update Step 5A to specify the multi-call pattern explicitly:

  ```
  // Step 5A: extract clinical entities. The Comprehend
  // Medical API surface is split: DetectEntitiesV2
  // returns categorized clinical entities; the
  // ontology-linked variants (InferRxNorm,
  // InferICD10CM, InferSNOMEDCT) return RxNorm /
  // ICD-10 / SNOMED-coded entities. Use the variant
  // that matches the downstream EHR's coded-entity
  // expectation. For most U.S. EHRs, RxNorm for
  // medications and ICD-10 for conditions are the
  // primary expectations; SNOMED is increasingly
  // used for clinical concepts.
  rxnorm_entities = comprehend_medical.infer_rx_norm(
      text: verbatim_transcript)
  icd10_entities = comprehend_medical.infer_icd10_cm(
      text: verbatim_transcript)
  // Optionally also call infer_snomed_ct for
  // institutions that store SNOMED codes.
  ```

  Update the cost estimate to reflect that ontology-linked entity extraction may require multiple Comprehend Medical calls per dictation. Cross-reference the chapter pattern from Recipe 10.2 Finding S1.

### Finding A12: Bedrock Model HIPAA Eligibility Per Specific Model Underspecified

- **Severity:** LOW
- **Expert:** Architecture (BAA-eligibility currency)
- **Location:** Prerequisites BAA / Compliance row: "Bedrock (verify the specific models and regions covered)..."

- **Problem:** Same chapter pattern as Recipe 10.2 Finding A11 and Recipe 10.3 Finding A11. The list does not specifically name a default-model recommendation. The example audit record at line 1364 names `bedrock-claude-3-haiku-20240307` as the formatter; this is a useful default but the prose does not explicitly recommend it.

- **Fix:** Add a default-model recommendation with the verify-at-build-time hedge (Claude family typical for healthcare due to longer-standing HIPAA-eligible-on-Bedrock track record). Reference the AWS HIPAA Eligible Services Reference URL.


## Networking Expert Review

### What's Done Well

- **VPC endpoint coverage is comprehensive.** Recipe 10.4 explicitly lists VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, Comprehend Medical, and Transcribe Medical, plus references private peering or VPN for on-premise EHR connectivity. This is the correct egress-discipline posture and matches the chapter pattern from 10.2 and 10.3.
- **TLS-in-transit explicitly elevated for all calls.** "TLS in transit for all AWS API calls and all EHR API calls (default)." The institutional cipher-suite policy is correctly assumed to be in place.
- **VPC-attached Lambda for back-office EHR integration is correctly framed.** "Production: Lambdas that call back-office APIs (the EHR integration in particular) run in VPC with subnets that have controlled egress to the EHR's network (often a private peering connection or VPN to the on-premise EHR system)."
- **The on-premise versus cloud-hosted EHR distinction is correctly elevated** with the "for on-premise EHRs, the network topology is typically the longest-lead-time portion of the deployment" framing as the correct operational note.
- **Endpoint policies pinned to specific resources.** "Endpoint policies pin access to the specific resources the pipeline uses." The institutional discipline is correctly elevated.

### Finding N1: WebSocket-Based Streaming Audio Through API Gateway Authentication and Connection Limits Architecturally Implicit

- **Severity:** LOW
- **Expert:** Networking (data-in-transit and connection-management)
- **Location:** Architecture diagram `APIGW[API Gateway WebSocket + REST]` and the Step 2 streaming-audio path through the WebSocket.

- **Problem:** Same chapter pattern as Recipe 10.3 Finding N1. The architecture uses API Gateway WebSocket for streaming dictation audio. The recipe specifies the Cognito authorizer for the REST endpoints but does not specify the WebSocket-specific concerns (connection-time authentication via Lambda authorizer with the clinician's Cognito token, account-level concurrent-connection limits, idle-timeout interaction with long-form dictation sessions, binary-message-type frame format).

  Recipe-specific because dictation sessions are longer than voice-EHR-navigation commands (a single dictation may be ten minutes or longer), and the WebSocket idle-timeout (default 10 minutes for API Gateway WebSocket) interacts with the dictation-session lifecycle. A clinician who pauses mid-dictation for longer than the idle timeout will lose the WebSocket connection and the in-progress audio buffer.

- **Fix:** Add a "WebSocket Audio Streaming" prose paragraph specifying the connection-time authentication mechanism, the connection-limit and rate-limit considerations (with quota increase as a deployment-time activity), the idle-timeout interaction with long-form dictation (consider extending the idle timeout or implementing a keep-alive ping), and the binary-message-type frame format.

### Finding N2: PrivateLink for EHR Vendor APIs Underspecified Where Available

- **Severity:** LOW
- **Expert:** Networking (data-in-transit egress for back-office EHR APIs)
- **Location:** Prerequisites VPC row.

- **Problem:** Same chapter pattern as Recipe 10.3 Finding N2. The recipe correctly elevates controlled-egress for on-premise EHR systems but does not specify the PrivateLink option for EHR vendors that expose PrivateLink endpoints.

- **Fix:** Add a "PrivateLink preferred for EHR vendor APIs that expose PrivateLink endpoints" framing alongside the existing private-peering-or-VPN-to-on-premise-EHR framing. The egress hierarchy: PrivateLink (preferred where available) > private peering / Direct Connect / Transit Gateway > VPN > public-Internet-with-TLS.

### Finding N3: Microphone-to-Cloud Transport Posture for Headset and Handheld Microphones Architecturally Implicit

- **Severity:** LOW
- **Expert:** Networking (device-to-cloud boundary)
- **Location:** Activation & Audio Capture stage in the General Architecture Pattern.

- **Problem:** Same chapter pattern as Recipe 10.3 Finding N3. The recipe does not specify the transport posture from the dictation microphone (headset, handheld, mounted) to the cloud. The audio stream is PHI in transit on the institutional network and across the institutional-to-cloud boundary.

- **Fix:** Add a "Device-to-Cloud Transport Posture" paragraph specifying TLS-encrypted-WebSocket with institutional certificate pinning, clinical-device-VLAN network segmentation, and device-identity authentication via mutual TLS or device-certificates as institutional requirements. Reference the institutional clinical-device-management ownership for the per-device-fleet certificate provisioning.

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by raw-byte search against U+2014; zero matches in the file.
- **70/30 vendor balance maintained.** AWS service names appear first in the AWS Implementation section. The Problem, The Technology, and General Architecture Pattern are fully vendor-agnostic. The Technology section's "Long-Form Dictation with Domain-Specific Stakes" framing is fully vendor-agnostic; the custom-vocabulary / per-clinician-adaptation / voice-commands / formatting / read-edit-sign decomposition is fully vendor-agnostic; the General Architecture Pattern's eight-stage decomposition is fully vendor-agnostic.
- **The opening 6:47-PM-empty-clinic-physician-typing-pajama-time vignette earns its position as the chapter's strongest articulation of the documentation-burden problem.** The cadence of "She is trying to remember the patient's exact words about a new symptom. She is trying to remember whether the patient said the pain started 'two weeks ago' or 'about two weeks ago, give or take.' She is trying to remember which side. She is trying to reconstruct the physical exam she did four hours ago" is the recipe's strongest single passage of "you're sitting in the back office watching the documentation tax compound" voice. The "pajama time" colloquialism is correctly elevated as the universal-clinician term.
- **The "the documentation problem is not new. Physicians have been struggling with the volume of clinical writing required for as long as there have been clinical records. What is new is the operational acceptance of 'pajama time' as a normal feature of medical practice" framing is the recipe's strongest single articulation of why dictation-the-original-solution remains relevant.** The 1985-tape-dictation-then-offshore-transcription-then-Dragon-Medical historical arc grounds the recipe's voice in the actual evolution of the field.
- **The seven specific failure-mode vignettes earn their position.** The radiologist-laterality-mistranscription failure (the recipe's strongest articulation of critical-error-rate-versus-WER), the underrepresented-accent-clinician failure (the equity-stake), the hemoptysis-versus-hematemesis failure (the silent-and-routine clinical-safety primitive), the surgeon-voice-command-confused-with-content failure (command-versus-content boundary), the deployment-with-forty-percent-of-pilot-adoption failure (the workflow-engineering-not-technology framing), the institutional-BAA-without-scrutiny failure (the audio-as-PHI-and-vendor-cloud-storage primitive). Each is recipe-specific and clinically authentic.
- **Self-deprecating expertise lands well.** "It is, frankly, the most established voice product category in healthcare" earns the recipe's right register for an established-but-still-hard category. "The first trap is treating dictation as a solved problem and skipping the investment in deployment quality. The technology is mature. The deployment quality is not" is the recipe's strongest single articulation of the why-buy-vs-build-economics-favor-buy primitive while preserving the engineering-as-substrate posture.
- **The "let's get into it" pivot from The Problem into The Technology** is exactly the right "you're a colleague at the whiteboard" moment, repeating the chapter pattern from 10.1 / 10.2 / 10.3.
- **The Technology section's "Long-Form Dictation with Domain-Specific Stakes" framing is the right register.** The "the utterances are long" / "the vocabulary is highly specialized" / "specialty-specific subdialects" / "accuracy expectations are very high" / "safety-critical word substitutions matter more than overall WER" / "real-time / near-real-time / batch" / "voice commands embedded in dictation" / "per-clinician adaptation is essential" / "integration with the EHR documentation workflow" property enumeration is the right grain for the Technology section.
- **The Honest Take is the recipe's strongest single passage and frames the dictation pipeline as a legal-record-creation surface with workflow-engineering-as-the-substrate.** The seven traps (treating-dictation-as-a-solved-problem, over-relying-on-overall-accuracy-metrics, assuming-LLM-post-processing-is-an-unmitigated-good, underinvesting-in-disambiguation-between-voice-commands-and-content, failing-to-plan-for-per-specialty-tuning, skipping-the-build-vs-buy-analysis) are well-chosen and recipe-specific. The "the metric that matters is critical-error rate, not WER" framing is the chapter's clearest articulation of the safety-relevant-accuracy-axis.
- **The closing "medical dictation produces clinical documentation that becomes the legal record. A misrecognized word in a signed note is a clinical-safety event, a billing-compliance event, and potentially a litigation event. The system's job is not just to make dictation fast; it is to make sure the signed note accurately reflects the clinical encounter" line is the recipe's strongest single closing primitive and frames the dictation pipeline as a legal-record-creation surface that earns its position as the chapter's first medium-tier recipe's voice register.**
- **No documentation-voice creep.** The Why-These-Services subsection links each service back to its conceptual role from The Technology section, matching the chapter pattern from 10.1 / 10.2 / 10.3.
- **Healthcare-domain accuracy is consistent.** The radiologist-laterality-mistranscription failure pattern is well-documented in radiology informatics literature. The hemoptysis-versus-hematemesis sound-alike pair is a real and clinically-significant ASR failure mode. The cefepime pronunciation note is correct ("seff-eh-PEEM"). The eponymous-syndrome catalog (Wolff-Parkinson-White, Henoch-Schönlein purpura, Mallory-Weiss tear) is accurate. The medication examples (lisinopril, dabigatran, tisagenlecleucel) span common-to-rare appropriately. The specialty-specific dictation patterns (radiology, cardiology, psychiatry, surgery, emergency medicine) are clinically authentic. The chest-pain-presentation in the Expected Results sample (54-year-old male, history of HTN/HLD, 5/10 substernal pressure-like pain, exertional, relieved with rest) is the textbook stable-angina presentation. The Section 508, HIPAA Privacy Rule, and SMART on FHIR / FHIR DocumentReference / FHIR Composition / FHIR Provenance citations are correct.
- **Parenthetical asides are present and serve the voice** without overdoing it: "(it is, frankly, the most established voice product category in healthcare)" / "(highly variable by specialty and rollout quality)" / "(though the engineering and operational overhead of operating a custom build is non-trivial)" framings.

### Finding V1: The "primarily a workflow project that uses speech recognition; the institutions that struggle treat it as a speech-recognition project that has some workflow" Line

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take, first trap: "The institutions that succeed treat dictation as a workflow project that uses speech recognition; the institutions that struggle treat it as a speech-recognition project that has some workflow."

- **Note:** Same architectural primitive as Recipe 10.3 Finding V1 ("primarily a workflow engineering problem that happens to use ASR") but recipe-distinct in framing. This is the chapter's clearest articulation of the workflow-versus-technology axis for dictation specifically and earns its position as the recipe's central observation. Preserve through editing.

### Finding V2: The "build the second kind"-Equivalent Closing Earns Its Position

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's closing paragraph: "A dictation system that optimizes for speed at the expense of accuracy ships a product that produces unreliable clinical records at scale. A dictation system that takes the safety rigor seriously ships a product that clinicians and institutions can stand behind."

- **Note:** Recipe 10.4's analog of Recipe 10.3's "build the second kind" line. The "ships a product that clinicians and institutions can stand behind" framing is the recipe-specific analog of the chapter's foundational-rigor-not-engineering-polish primitive. The cadence is preserved through the recipe and earns its position. Preserve through editing.

### Finding V3: The Three "the thing about" Vendor-Honest Assessments Are the Right Register

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's vendor-specific observations: "The thing about Amazon Transcribe Medical specifically..." / "The thing about Amazon Bedrock specifically..." / "The thing about Amazon Comprehend Medical specifically..."

- **Note:** Each is the recipe's right register of vendor-honest framing without lapsing into hype or trash-talk. The Transcribe Medical "competent baseline for clinical-domain ASR. The specialty-specific tuning... covers the largest deployment volumes; specialties outside that list use the closest specialty configuration plus aggressive custom vocabulary" framing is exactly the right "competent platform, not a panacea" register. The Bedrock "the LLM-driven formatting and structuring is genuinely valuable, with the faithfulness caveats already covered" framing earns its position. The Comprehend Medical "the right tool for coded clinical-entity extraction. The RxNorm linking, the ICD-10 linking, the negation detection are all solid. The accuracy varies with the kind of clinical text" framing is correctly granular. Preserve through editing.

### Finding V4: A Few Long Sentences in the Honest Take's Trap Discussions Could Be Tightened

- **Severity:** LOW
- **Expert:** Voice (sentence-length register)
- **Location:** Honest Take's "A third trap is assuming the LLM post-processing is an unmitigated good" paragraph and "A fourth trap is underinvesting in disambiguation between voice commands and dictation content" paragraph.

- **Problem:** Most sentences are well-paced; a few in the Honest Take's longer trap discussions stretch across multiple subordinate clauses. The current voice is consistent with CC's accumulation pattern; not a hard requirement to fix. Same observation as Recipe 10.1 Finding V1, Recipe 10.2 Finding V1, and Recipe 10.3 Finding V4.

- **Fix:** Optional. Not required.

### Finding V5: The "pajama time" Colloquialism Earns Its Position

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Problem section: "The colloquial term clinicians use for this is 'pajama time,' the documentation-after-bedtime that is so universal it has its own name."

- **Note:** The colloquialism is exactly the right register and grounds the recipe in the felt-experience of the median ambulatory physician in 2026. The "pajama time correlates with clinician burnout, clinician attrition, reduced empathy in clinical encounters, missed clinical signals, and (in the cumulative aggregate) the slow-motion collapse of primary care as a viable career path for newly-trained physicians" cadence frames the institutional-and-economic stakes at exactly the right grain. Preserve through editing.

---

## Stage 2: Expert Discussion

The four expert lenses produce overlapping concerns at four intersections.

**Dictation-metadata PHI minimization (Security S1) overlaps with Architecture's faithfulness-check (A3), critical-error-detection (A1), and per-clinician adaptation pipeline (A4).** The Security expert's concern about transcript content in the dictation-metadata table is operationally connected to: (a) the Architecture expert's faithfulness-check pipeline (A3) which needs access to the verbatim transcript and the LLM-formatted note for claim-extraction-and-comparison, but the access should come from the secure transcript archive, not from the working-store DynamoDB table; (b) the Architecture expert's critical-error-detection pipeline (A1) which needs the same access pattern; (c) the Architecture expert's per-clinician adaptation pipeline (A4) which captures user corrections and feeds them into per-clinician-vocabulary updates, with the corrections referenced from the secure archive rather than retained in DynamoDB. The four findings reinforce each other and the consolidated fix specifies: PHI-bearing content (audio, verbatim transcripts, word-level results, formatted notes, EHR API responses) lives in the secure archive (S3 with KMS) under unified governance; the working-state stores (DynamoDB session-state and dictation-metadata) carry references and structural metadata only; the faithfulness-check, critical-error-detection, and adaptation pipelines load content from the secure archive when needed, with their access governed by the same KMS keys and IAM policies as the audio bucket.

**Critical-error detection (Architecture A1) overlaps with faithfulness-check (Architecture A3), per-specialty tuning, and Voice's articulation of the safety-relevant-accuracy-axis.** The Architecture expert's elevation of critical-error detection as a discrete architectural stage is reinforced by the Architecture expert's faithfulness-check architecture (A3); the runtime critical-error-detection pass and the runtime faithfulness check are different lenses on the same input (verbatim transcript and LLM-formatted note) with different detection categories (critical-error detection focuses on safety-critical word-level substitutions; faithfulness check focuses on semantic-claim-level divergence). The two should share the input-loading from the secure archive and produce composable detections that surface together in the read-edit-sign view. The Voice expert's articulation of the recipe's safety-relevant-accuracy-axis as the chapter's central observation reinforces both findings as load-bearing primitives. The consolidated fix specifies: a unified read-edit-sign overlay that surfaces low-confidence words, critical-error detections, and faithfulness warnings as composable detections with severity tiers; the per-detection disposition is configured per-detection-type (e.g., critical-error high-severity requires explicit confirmation; faithfulness-warning high-severity falls back to rule-based draft; low-confidence words highlight only).

**Cohort-stratified accuracy (Architecture A2) overlaps with Voice's per-clinician-language-background observation, Security's metric-PHI concern (S6), and Architecture's per-clinician adaptation pipeline (A4).** The Architecture expert's elevation of cohort-stratified monitoring is reinforced by the Voice expert's observation that the per-clinician-language-background disparity is recipe-specific and shapes the documentation-burden distribution. The Security expert's S6 (cohort PHI in CloudWatch dimensions) is operationally connected: the per-clinician analytics need a per-clinician identifier in the metrics surface, but the per-clinician-language-background and inferred-accent-group dimensions must be encoded as non-reversible cohort-axis-hashes. The per-clinician adaptation pipeline (A4) interacts with cohort monitoring: a per-clinician adaptation that improves the clinician's accuracy should reduce the cohort disparity for the per-clinician-language-background dimension; the cohort-monitoring metric is the lagging indicator of adaptation pipeline effectiveness. The four findings reinforce each other and the consolidated fix specifies: the per-clinician adaptation pipeline produces a per-clinician improvement signal that the cohort-monitoring layer aggregates by language-background-and-accent-group cohort; the cohort-monitoring layer surfaces lagging-indicator metrics (corrections-per-note disparity, time-to-sign disparity, adoption-rate disparity, abandonment-rate disparity) for the equity-monitoring committee.

**Foundation-model prompt-injection (Security S2) overlaps with Architecture's faithfulness-check (A3) and foundation-model versioning (A6).** The Security expert's prompt-injection-mitigation framing is consistent with the Architecture expert's faithfulness-check architecture (A3); the prompt-injection mitigation operates at the input-side (delimited-transcript framing, strict structured-output validation) while the faithfulness check operates at the output-side (claim-extraction-and-comparison). The two together bound the LLM-formatter's risk surface. The version-stamping-on-every-dictation (A6) supports the prompt-injection-monitoring (S2) by enabling forensic reconstruction of which prompt version was active when an injection-suspicious LLM output was produced. The three findings reinforce each other.

**No conflicts** between expert lenses requiring resolution. The Security expert's audit-record PHI-minimization framing (S1) is consistent with the Architecture expert's faithfulness-check and critical-error-detection and adaptation-pipeline framework. The Networking expert's WebSocket and PrivateLink and device-to-cloud framings (N1, N2, N3) are consistent with the Architecture expert's disaster-recovery framework (A9). The Voice expert's positive observations on the recipe's central-observation framing reinforce the Architecture expert's elevation of the workflow-engineering-not-technology primitive.

**Priority resolution.** The three HIGH findings are independent and additive. The Security S1 (dictation-metadata PHI parallel store) addresses the highest-volume PHI-handling surface in the architecture. The Architecture A1 (critical-error detection) addresses the recipe-specific clinical-safety primitive that the recipe's own prose names as "the single most important production gap." The Architecture A2 (cohort-stratified accuracy monitoring) addresses the recipe-specific equity-monitoring primitive that the recipe correctly elevates in three separate places without architecting it. The MEDIUM findings cluster into the LLM-safety-substrate category (faithfulness check, prompt-injection mitigation, foundation-model versioning) and the deployment-and-resilience category (per-clinician adaptation pipeline, EHR token lifecycle, idempotency, multi-language architecture, audio retention, disaster recovery) and the API-integration category (Comprehend Medical multi-call pattern, Lambda invocation authentication, audit-log retention floor). The LOW findings are individually minor and collectively cosmetic.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

**Rationale:** 0 CRITICAL findings; 3 HIGH findings (at the > 3 = FAIL threshold but not exceeding it); 11 MEDIUM findings (most explicitly TODO'd in the recipe's prose with the chapter-pattern consolidation deferred to the editor); 5 LOW findings (cosmetic or minor). The three HIGH findings are localized correctness gaps that the recipe's own prose correctly diagnoses (with the recipe's self-assessment of critical-error detection as "the single most important production gap" being the most explicit confession that the architecture is missing its most important piece); closing them brings the architecture and the pseudocode up to the standard the recipe text claims and matches the chapter pattern from Recipes 10.1, 10.2, and 10.3.

Recipe 10.4 is Chapter 10's first medium-tier recipe and the chapter's transition from simple-tier voice recipes (10.1 IVR, 10.2 voicemail, 10.3 voice-EHR-navigation) to the chapter's more complex clinician-facing voice recipes. Its successful execution at the medium-tier level (vendor-agnostic eight-stage architecture with read-edit-sign as a discrete stage and audit-archive-and-adaptation as a combined closing stage, push-to-command-as-the-mature-pattern, custom-vocabulary-and-per-clinician-adaptation-as-essential, hybrid neural-ASR-with-LLM-post-processing as the 2026 pattern, faithfulness-check-as-structural-requirement-not-optional-optimization, structured-field-extraction-as-draft-never-fact, clinician-signature-as-gate-to-the-legal-record, seven Honest Take traps closing on the legal-record-creation surface framing, twelve Variations including specialty-subdialect-tuning and multilingual and front-end-versus-back-end-modes and voice-driven-order-entry and ambient-and-dictation-hybrid and real-time-CDS-hooks and addendum-and-co-signature and per-clinician-acoustic-adaptation and LLM-quality-scoring) extends the chapter's voice-AI register at exactly the level the chapter text promises.

The recipe's central operational insight ("dictation as a workflow project that uses speech recognition") is consistent with the chapter pattern from 10.3 ("primarily a workflow engineering problem that happens to use ASR") while shifting the lens from real-time-clinician-EHR-navigation to long-form-dictation-with-legal-record-creation. The recipe's seven traps are recipe-specific and well-chosen. The recipe's closing imperative ("ships a product that clinicians and institutions can stand behind") is the chapter's strongest single articulation of the foundational-rigor-not-engineering-polish framing in dictation context and earns its position as the recipe's central voice moment.

### Prioritized Findings

| # | Severity | Expert | Location | Summary | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Step 2C and Step 7C `dictation_metadata_table.put(...)` | Verbatim transcript and word-level results written verbatim into DynamoDB working store, creating parallel PHI store outside audio-bucket and audit-archive governance; downstream Lambdas, DynamoDB Streams consumers, and analytics surfaces inherit broader access boundary than secure archive | Working store carries `verbatim_transcript_archive_ref`, `word_level_archive_ref`, length, hash, and structural metadata only; full transcript and word-level results live in secure transcript archive (S3 with KMS, same governance as audio bucket); downstream Lambdas load content from the secure archive when needed. Add cross-cutting prose paragraph elevating references-not-content discipline across all PHI-handling stages. |
| 2 | HIGH | Architecture | Architecture diagram has no critical-error-detection stage; pseudocode has no detection function; Step 6A `render_review_view` has no critical-error overlay | Critical-error detection (laterality flips, negation flips, drug-name confusions, dose-by-order-of-magnitude errors) is structurally absent despite recipe's own self-assessment as "the single most important production gap"; recipe-specific clinical-safety primitive | Add explicit critical-error-detection stage to architecture; specify per-specialty high-risk-substitution catalog as version-controlled clinical-safety document; specify detection-trigger thresholds (rule-based pattern matching with confidence-aware and LLM-divergence-aware priors); specify high-severity disposition (explicit confirmation required); specify aggregate-detection-rate monitoring with named ownership at clinical-quality officer |
| 3 | HIGH | Architecture | Audit-archive-and-adaptation stage CloudWatch metrics | Cohort-stratified accuracy monitoring named in prose three times but architecturally underspecified; missing cohort-dimensions allow-list (per-clinician primary), disparity-alert thresholds, sample-size minimums, named ownership, recipe-specific documentation-burden dimension, recipe-specific patient-population-correlation dimension | Promote prose elevation into architecture stage with explicit cohort-dimensions allow-list (per-clinician identifier, language-background, accent-group, specialty, experience-level, deployment-site), per-cohort metrics including corrections-per-note and time-to-sign and adoption-rate and abandonment-rate, sample-size minimums, disparity-alert thresholds, equity-monitoring committee ownership with monthly review cadence and clinical-quality officer ownership for critical-error-rate cohort disparities |
| 4 | MEDIUM | Security | Step 4C `bedrock.invoke_model(...)` formatter prompt | Foundation-model prompt-injection risk for LLM formatter underspecified; verbatim transcript directly templated into prompt; subtle prompt-injection that survives faithfulness check becomes permanent falsification of clinical record | Add prompt-injection-mitigation paragraph with delimited-transcript framing (`<verbatim_transcript>...</verbatim_transcript>`), strict structured-output validation, prompt-injection monitoring via formatter-output-divergence-from-rule-based-draft detection; specify faithfulness check as secondary safety layer and clinician's read-edit-sign as final safety layer |
| 5 | MEDIUM | Security | Architecture diagram `APIGW --> ORCH` | Lambda invocation authentication across API Gateway-to-Lambda integration underspecified | Resource-based policy pinning principal to production API Gateway stage ARN; defense-in-depth event-payload validation of `requestContext.apiId` |
| 6 | MEDIUM | Security | Prerequisites CloudTrail row | Audit-log retention floor for dictation-specific use case underspecified; signed clinical note's retention period is recipe-distinct floor | Name longest-of-(HIPAA-six-year, state-specific medical-records-retention including pediatric-records-extending-to-age-of-majority-plus-X, EHR-vendor-audit-retention floor, longest-retained-signed-note's retention period, institutional regulatory floor) |
| 7 | MEDIUM | Architecture | Step 4D `check_faithfulness(...)` opaque function call | LLM-formatter faithfulness check architecturally underspecified for recipe's highest-stakes LLM failure mode; check mechanism, threshold, failure-mode catalog, and offline evaluation program not specified | Specify claim-extraction-and-comparison architecture (Step 4D-1 / 4D-2 / 4D-3) with severity-tier classification of warnings; high-severity warnings (clinical-claim addition, negation flip, dose change, hedging-removal-on-clinical-assertion) trigger fall-back to rule-based draft; lower-severity warnings surface for clinician review without blocking; specify offline Faithfulness Program with per-update regression gate and named ownership at clinical-quality officer |
| 8 | MEDIUM | Architecture | Step 8C `adaptation_events_topic.publish(...)` | Per-clinician adaptation pipeline architecturally underspecified; cadence, scope (vocabulary-only vs acoustic), validation, rollback, institution-wide aggregation not specified | Default cadence weekly-batch for vocabulary, quarterly-batch for acoustic; default scope vocabulary-only with acoustic as opt-in; held-out per-clinician validation set with regression gate; per-clinician versioning with automatic rollback on regression; privacy-preserving aggregation for institution-wide model updates |
| 9 | MEDIUM | Architecture | Step 7A `fhir_client.create_note(...)` | Idempotency for dictation submission architecturally implicit; duplicate submission produces two signed notes for same encounter | Specify per-dictation idempotency key `(clinician_id, session_id, encounter_id, signature_timestamp)`; dictation-metadata table holds recently-submitted-notes list; on idempotency-match return prior note_id and record duplicate-detection in audit |
| 10 | MEDIUM | Architecture | Step 4C `bedrock.invoke_model(...)` and Step 5A `comprehend_medical.detect_entities_v2(...)` | Foundation-model and rule-formatter and critical-error-rule-catalog versioning via inference profiles and aliases not architecturally specified | Add Deployment Pattern subsection with versioned model and prompt and rule-catalog and template definitions in version control, canary inference profile with traffic-shift, rollback-on-regression, held-out evaluation set with specialty and accent and high-risk-substitution coverage, version stamping on every dictation audit record |
| 11 | MEDIUM | Architecture | Step 1A `clinician_session.is_valid()` | SMART on FHIR token lifecycle and EHR integration robustness underspecified for hours-long dictation sessions where token expires mid-workflow | Add SMART on FHIR Token Lifecycle subsection with refresh-token flow, pre-emptive refresh window, refresh failure handling, token storage in Secrets Manager with short-TTL cache, token-lifecycle audit events |
| 12 | MEDIUM | Architecture | Prerequisites Encryption row | Audio retention policy configuration mechanism could be more concretely specified beyond enumeration of three patterns | Specify retain-briefly with 7-30-day window as recommended default; discard-immediately as conservative alternative for strict PHI minimization; retain-longer requires explicit clinician consent at onboarding and documented retention purpose; reference audit log as long-term forensic substrate per Finding S1 |
| 13 | MEDIUM | Architecture | Production-Gaps "Disaster recovery and partial-failure handling" | Disaster recovery and partial-failure topology architecturally implicit | Add Disaster Recovery Topology subsection with per-stage failover policy (Transcribe Medical regional outage, Bedrock model unavailability with rule-based-formatter-fallback, Comprehend Medical unavailability with manual-structured-field-entry-fallback, EHR API unreachable with signed-note-queue-for-retry), failover-detection-and-failover-back triggers, quarterly testing cadence |
| 14 | MEDIUM | Architecture | Variations and Extensions "Multilingual dictation" | Multi-language architecture build-for-day-one underspecified for per-clinician-language-preference dimension | Specify per-clinician language declared at onboarding, per-language Transcribe Medical configurations and custom vocabularies, per-language LLM-formatter prompts, per-language formatting rules; reference build-for-day-one even when shipping English-first |
| 15 | MEDIUM | Architecture | Step 5A pseudocode | Comprehend Medical multi-call pattern slightly underspecified; pseudocode shows lookup_rxnorm and lookup_icd10 as separate function calls but does not explicitly map to InferRxNorm / InferICD10CM API surface | Update Step 5A to explicitly call infer_rx_norm and infer_icd10_cm as separate API calls; update cost estimate to reflect multi-call overhead; cross-reference Recipe 10.2 Finding S1 chapter pattern |
| 16 | LOW | Security | Sample Data row and Adaptation pipeline references | Voice biometric retention implications for per-clinician adaptation pipeline underspecified; BIPA / GIPA / similar state laws may regulate voice biometric data separately from general PHI | Add Voice Biometric Data Governance paragraph specifying clinician consent at onboarding, separation of biometric retention from general dictation retention, per-clinician right-to-deletion, cross-jurisdictional considerations |
| 17 | LOW | Security | Why-These-Services / CloudWatch paragraph | Cohort encoding in CloudWatch metric dimensions implied but discipline not specified | Specify cohort-axis-hash labels for sensitive dimensions (per-clinician-language-background, accent-group); per-clinician identifier may use direct identifier where institutional policy permits; demographic-stratification analytics happen in analytics layer over audit archive |
| 18 | LOW | Architecture | Prerequisites BAA row | Bedrock model HIPAA eligibility per specific model underspecified; example audit record names Claude Haiku as default but prose does not | Add default-model recommendation (Claude family typical for healthcare) with verify-at-build-time hedge; reference AWS HIPAA Eligible Services Reference URL |
| 19 | LOW | Networking | Architecture diagram `APIGW[API Gateway WebSocket + REST]` | WebSocket-based streaming audio through API Gateway authentication, connection limits, idle timeouts, frame format architecturally implicit; recipe-specific because dictation sessions are longer than voice-EHR-navigation commands | Add WebSocket Audio Streaming paragraph specifying Lambda authorizer with Cognito token, connection-limit and rate-limit considerations, extended idle-timeout or keep-alive ping for long-form dictation, binary-message-type frame format |
| 20 | LOW | Networking | Prerequisites VPC row | PrivateLink for EHR vendor APIs underspecified where available | Add PrivateLink-preferred-for-EHR-vendor-APIs framing; egress hierarchy: PrivateLink > private peering / Direct Connect / Transit Gateway > VPN > public-Internet-with-TLS |
| 21 | LOW | Networking | Activation & Audio Capture stage | Microphone-to-cloud transport posture for headset and handheld microphones architecturally implicit | Add Device-to-Cloud Transport Posture paragraph specifying TLS-encrypted-WebSocket with institutional certificate pinning, clinical-device-VLAN network segmentation, device-identity authentication via mutual TLS or device-certificates |
| 22 | LOW | Voice | Honest Take long-trap paragraphs | A few long sentences in the Honest Take's third and fourth trap discussions could be tightened | Optional; current voice is consistent with CC's accumulation pattern |

### Closing Notes

Recipe 10.4 is publishable at the medium-tier level once the three HIGH findings are closed. The Honest Take is the recipe's strongest single passage and frames the dictation pipeline as a legal-record-creation surface with workflow-engineering-as-the-substrate, which is exactly the right framing for the chapter's first medium-tier recipe and matches the patient-trust-and-clinician-trust framing that Recipes 10.1, 10.2, and 10.3 established for the chapter's voice register while shifting the lens from synchronous-voice-interaction-trust to long-form-clinical-record-creation-trust.

The recipe's central operational insight ("dictation as a workflow project that uses speech recognition") is consistent with the chapter pattern from 10.3 and sets up the chapter's later clinician-facing recipes (10.6 telehealth documentation, 10.7 ambient clinical documentation) which build on this insight at progressively higher complexity tiers (10.6 adds multi-speaker diarization; 10.7 adds conversational-multi-speaker-passive-capture). The recipe's twelve Variations and Extensions provide the right runway into those later recipes, each of which builds on the activation-and-streaming-ASR-and-formatting-and-structured-extraction-and-read-edit-sign pattern this recipe establishes.

The recipe's closing observation that "medical dictation produces clinical documentation that becomes the legal record. A misrecognized word in a signed note is a clinical-safety event, a billing-compliance event, and potentially a litigation event" is the chapter's strongest single articulation of the legal-record-creation-stakes primitive and earns its position as the recipe's closing voice moment. The chapter editor should preserve this framing through the editing pass.

The chapter-wide consolidation work (the cohort-stratified-accuracy chapter preface that consolidates 10.1 / 10.2 / 10.3 / 10.4 Finding A1 / A2 into a single architectural primitive, the audit-PHI-minimization chapter preface that consolidates 10.1 / 10.2 / 10.3 / 10.4 Finding S1 into a single architectural pattern with explicit working-store-versus-secure-archive discipline, the LLM-clinical-safety-substrate chapter preface that consolidates 10.4 Finding A1 critical-error detection plus Finding A3 faithfulness check plus Finding S2 prompt-injection mitigation, the foundation-model-versioning chapter preface, the multi-language chapter preface, the disaster-recovery chapter preface, the SMART on FHIR token lifecycle chapter preface, the audit-log retention floor chapter preface) is deferred to the chapter editor for the next pass. The recipe-specific critical-error-detection primitive (Finding A1) is the chapter's strongest single new architectural primitive introduced at the medium-tier level and should be elevated to the chapter preface as the load-bearing clinical-safety primitive for any voice recipe that produces signed clinical documentation (which includes 10.6 and 10.7 in addition to 10.4).
