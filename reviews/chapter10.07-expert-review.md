# Expert Review: Recipe 10.7 - Ambient Clinical Documentation

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-23
**Recipe file:** `chapter10.07-ambient-clinical-documentation.md`

---

## Overall Assessment

This is the seventh recipe in Chapter 10 (Speech / Voice AI) and the chapter's first complex-tier recipe. It pivots cleanly from 10.6 (telehealth speech-to-text) and 10.4 (single-speaker dictation) by elevating the in-room audio path, multi-speaker diarization with movement, clinical-versus-social classification, and the device-in-the-room workflow as the recipe-distinct architectural primitives. The opening Dr. Patel pajama-time vignette earns its position as the chapter's strongest single articulation of the in-person documentation burden problem. The "the encounter itself suffers from documentation pressure" framing with the unrecognized-symptom-pattern vignette (the patient's "weird heaviness in her chest when she carries groceries up to her third-floor apartment" that becomes an MI eight months later) is the recipe's strongest single passage of "the technology of typing-while-listening creates the conditions for missed signals" voice and grounds the recipe in the felt-experience of the median primary-care encounter.

The recipe correctly positions itself as the in-person companion to recipe 2.8 (LLM-driven note generation, faithfulness, consent, EHR integration) and as the in-person sibling to recipe 10.6 (telehealth speech-to-text), with explicit deferrals to those recipes for the deeper treatment of overlapping concerns. This composition discipline is a recipe strength and avoids the chapter-pattern repetition problem that earlier complex-tier recipes have struggled with.

The Technology section's twelve-property enumeration (audio path through the room not through a headset, multi-speaker diarization with movement as central problem, clinical-versus-social classification as harder than it looks, encounter is unstructured, note has to read like the clinician wrote it, real-time and near-real-time both matter, bystander capture is meaningful concern, workflow integration is make-or-break, equity as first-class concern, behavioral-health-specific handling) frames the architectural grain correctly and earns its position. The "the audio path runs through the room, not through a headset" framing with the 18-inches-to-8-feet distance variation is the recipe's clearest articulation of the room-acoustics-as-determining-factor primitive.

The In-Room Audio Path subsection's eleven-mechanism enumeration (microphone hardware four patterns, beamforming and source localization, noise suppression and echo cancellation, voice activity detection and audio gating, adjacent-room sound bleed, hallway and door-opening events, physical movement of speakers, patient gowning and exam-mode capture, environmental noise events, consent-aware audio gating, audio retention) is recipe-distinct and the load-bearing audio-path pedagogy of the recipe. The "the institution selects an ASR vendor with great published accuracy numbers, deploys the feature, and then sees real-clinic word error rates that are meaningfully worse than the published numbers. The fix is almost always at the audio path, not at the ASR" framing is the recipe's strongest single articulation of the audio-path-as-deciding-factor primitive in in-person context.

The Multi-Speaker Diarization with Movement subsection's eleven-pattern enumeration (two-speaker case, three-or-more-speaker case, speaker enrollment for the clinician, patient and family-member identification, role assignment from clustering plus context, diarization confidence per segment, overlapping speech, backchannels and short interjections, non-speaker audio events, movement-robust embeddings, joint ASR-and-diarization architectures, in-room versus telehealth diarization comparison) is recipe-distinct. The "the diarization layer that scales best for in-room ambient documentation uses voice-content embeddings (pitch, formants, prosody, spectral features) that are relatively stable to physical movement, rather than spatial-only features that change as speakers walk around the room" framing is the recipe's clearest articulation of the diarization-with-movement-as-recipe-distinct-engineering-problem primitive. The vendor-managed-versus-self-built diarization economics observation correctly elevates the build-versus-buy decision.

The Clinical-Versus-Social Talk Classification subsection's "naive system that captures and structures everything produces a note like this... [example with magazines-in-the-waiting-room and dog-doing-better-since-the-surgery]" framing is the recipe's strongest single passage on the social-content-pollution failure mode and grounds the segment-level classifier as architectural primitive.

The eight-stage architecture (encounter setup and consent capture, in-room audio capture, streaming ASR with diarization, in-encounter live display, batch ASR for finalization, clinical classifier and note generation, clinician review and signature, audit-archive-and-learning) is the right shape for the problem and recipe-distinct from 10.6's eight-stage telehealth decomposition (the in-room audio capture stage and the clinical-classifier stage are the architectural-primitive distinctions). The cross-cutting design points are correctly elevated (audio is PHI throughout and biometric, per-encounter consent and bystander handling first-class, real-time and batch run in parallel, faithfulness checks gate LLM-generated note, clinician review is legal-medical-record boundary, per-cohort accuracy monitoring as launch gate with audio-quality-band particularly important for in-person, behavioral-health-specific handling, bystander handling, failure modes degrade to manual documentation, per-clinician opt-out and per-encounter opt-out).

The Honest Take is the recipe's strongest single passage. The ten traps (underweighting in-room audio path, underweighting diarization, treating faithfulness as scoring metric not safety program, shipping in-room audio quality variation as the patient's problem, over-eagerly auto-applying structured-field extractions, treating bystander consent as a checkbox, treating per-clinician adoption as feature flag, shipping without behavioral-health-specific handling, assuming EHR integration is the easy part, treating room acoustics as an IT problem) are well-chosen and recipe-specific. The tenth trap (room acoustics as IT problem) is the recipe-distinct contribution to the chapter's voice register. The closing "ambient clinical documentation, done well, gives clinicians their evenings back. It improves encounter quality because clinicians can look at patients more and screens less. It produces notes that often read better than the ones clinicians write under time pressure" line is the recipe's strongest single closing primitive and earns its position.

That said, three correctness-and-compliance gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items.

(1) **Biometric clinician voiceprint enrollment under BIPA, Texas, and Washington state law is architecturally implicit despite explicit elevation in prose.** Recipe-acute and recipe-distinct: the in-person ambient documentation is the prime use case for clinician-voiceprint enrollment (high-volume per-clinician encounters justify the enrollment cost), the recipe correctly elevates voiceprint enrollment as a "meaningful improvement in diarization" architectural primitive, and the recipe correctly notes that "biometric handling has its own governance overhead." Despite this, the architecture pattern, the diagram, and the pseudocode treat the voiceprint registry as a passing reference (`CLINICIAN_VOICEPRINT_REGISTRY[state.clinician_id]`) without specifying the BIPA-grade governance scaffolding (biometric-data consent at enrollment, retention policy, deletion-on-departure, disclosure-accounting log, per-state regulatory profile). BIPA carries statutory damages of $1,000 to $5,000 per violation; an architecture that captures and stores voiceprints without the governance scaffolding is a meaningful compliance exposure for institutions deploying in Illinois, Texas, or Washington.

(2) **The faithfulness check at Step 4E is architecturally specified as a single function call returning a `severity` classifier, despite the recipe's prose correctly elevating faithfulness as the highest-stakes safety artifact and naming the multi-layer program (citation grounding, LLM-judge faithfulness scoring, clinical-rule-based contradiction detection, offline sampling review).** Same chapter pattern as Recipe 10.4 Finding A3 and Recipe 10.6 Finding A1. Recipe-acute because the recipe explicitly names this as "the worst class of failure" in The Honest Take's third trap and explicitly defers to recipe 2.8 for the multi-layer program treatment, but the architecture should still specify the layer ordering, per-layer disposition, named ownership, runtime-versus-offline relationship, and per-cohort faithfulness-failure-rate as launch gate at the architecture-pattern level even when the prose deferral to 2.8 is appropriate. The recipe's own self-assessment ("treating faithfulness as a vague concern when it was the safety story") correctly diagnoses the gap.

(3) **Per-cohort accuracy and adoption monitoring with audio-quality-band and per-room stratification is structurally specified in the audit record but the launch-gate discipline is not architecturally elevated.** Same chapter pattern as Recipe 10.6 Finding A2, with recipe-distinct extension: per-room stratification is the recipe's contribution to the equity-monitoring chapter pattern (in-person rooms vary substantially in acoustics, microphone placement, and noise floor, which produces per-room accuracy variability that is independent of patient demographics). The audit record at Step 7 includes `room_id` and `audio_quality_band` in the cohort axes (good), but the architecture pattern, the diagram, and the cross-cutting design points do not specify per-audio-quality-band minimum-recall thresholds as launch gates, per-language-by-audio-quality two-axis stratification, per-room sample-size minimums, per-room remediation playbook (room acoustic treatment, microphone repositioning, dedicated capture hardware), or audio-quality-band as a per-encounter feature driving lower confidence threshold for poor-audio encounters and audio-quality-warning surfaced in the clinician review interface.

Eleven chapter-wide and recipe-specific MEDIUM items (foundation-model prompt-injection on the LLM-driven note generation, per-encounter consent and bystander identification with cross-state recording-consent profile, 42 CFR Part 2 substance-use-treatment behavioral-health profile architecturally specified, idempotency for EHR write-back, foundation-model and prompt and template versioning via Bedrock inference profiles and aliases, audio retention policy with per-visit-type retention windows, audit-log retention floor with explicit pediatric and EHR-vendor and biometric-records floors, Lambda invocation authentication, Step 5C structured-extraction context-snippets persisted in note-state DynamoDB table outside archive-reference discipline, multi-language architecture build-for-day-one, disaster recovery and partial-failure topology, HealthScribe `NoteTemplate` enum constraint flagged in code review carries over to recipe pseudocode at Step 3C). Most are explicitly TODO'd or named in the Why-This-Isn't-Production-Ready section; this review carries them forward at MEDIUM severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. **Em dash count: 0** (verified by raw-byte search against U+2014; zero matches in the file). The 70/30 vendor balance is maintained. CC voice is consistent throughout. Healthcare-domain accuracy is consistent (the family-medicine pajama-time vignette is operationally authentic; the diarization-error-rate ranges (3-8% for two-speaker, 8-18% for three-speaker, 15-30% for four-or-more-speaker) are clinically plausible benchmarks for 2026; the joint-ASR-and-diarization architectures references are accurate; the BIPA, Texas, Washington biometric-data-law references are correct; the 42 CFR Part 2 reference for substance-use treatment records is correct; the FHIR DocumentReference / MedicationRequest / Condition / Observation references are correct; the RxNorm / ICD-10 / LOINC references are accurate; the AWS HealthScribe service framing as HIPAA-eligible-managed-service-with-joint-ASR-diarization-and-clinical-content-classification is operationally accurate; the per-specialty applicability framing (primary care, internal medicine, family medicine, behavioral health show strongest ROI; procedural specialties and primarily-visual-exam specialties show less benefit) is correct).

Architectural accuracy is high. The eight-stage decomposition with streaming-and-batch-running-in-parallel and the in-room-audio-capture as architectural-priority stage is the architecturally-correct shape. The HealthScribe-as-primary-managed-service with Bedrock-for-institutional-template-rendering is the right composition for the recipe-acute requirement (HealthScribe collapses ASR + diarization + role assignment + clinical-content classification + structured note draft; Bedrock renders the institution-specific format on top). The Step-Functions-for-post-encounter-pipeline is the right durable-orchestration choice. The customer-managed-KMS-keys-per-data-class with separate-keys-per-visit-type framing is correct and recipe-distinct (the per-visit-type-key-separation supports the behavioral-health profile's stricter access-control surface). The Object-Lock-in-Compliance-mode for the audit archive is correct. The brief-retention audio policy with the per-room and per-channel quality monitoring is correct. The cost-estimate framing with the HealthScribe-per-minute-charges-dominate honest framing plus the dedicated-capture-hardware-budget-separately note is operationally accurate.

The recipe's working-store discipline is meaningfully better than Recipes 10.1 through 10.6: the streaming transcript writes to `transcript_archive` (S3) rather than to the transcript-state table, and the rendered note writes to `note_draft_archive` (S3) rather than to the note-state table. This is the chapter-pattern discipline that earlier recipes had to be coached toward, and 10.7 has it largely right at the working-store level. The remaining gap is at Step 5C (structured-extraction context-snippets persisted in the note-state table outside the archive-reference discipline); that is a localized MEDIUM rather than the HIGH chapter-pattern repetition.

Priority breakdown: 0 critical, 3 high, 12 medium, 7 low. **The verdict is PASS** because the HIGH count (3) is at the > 3 = FAIL threshold but does not exceed it, and there are no CRITICAL findings. The three HIGH findings are localized correctness gaps that the recipe's own prose correctly diagnoses; closing them brings the architecture and the pseudocode up to the standard the recipe text claims and matches the chapter pattern from Recipes 10.1 through 10.6 with the recipe-distinct biometric-voiceprint contribution.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly: "AWS HealthScribe, Amazon Transcribe (general and Medical), Amazon Bedrock (verify the specific models and regions covered), Amazon Comprehend Medical, Lambda, Step Functions, API Gateway, Cognito, DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, CloudTrail, EventBridge, Kinesis Firehose, Glue, Athena, Chime SDK are HIPAA-eligible." The "verify the current list at build time" hedge is correctly placed.
- Customer-managed KMS keys called out for the audio bucket, transcript bucket, audit-archive bucket (with Object Lock in Compliance mode), DynamoDB tables, Lambda environment variables and log groups, and Secrets Manager. The "Different keys per data class (audio vs. text) and per visit type (general vs. behavioral health) for blast-radius containment and finer retention control" framing is the right elevation and recipe-distinct (per-visit-type key separation supports the behavioral-health profile naturally).
- CloudTrail enabled with data events on the audio S3 bucket, transcript bucket, audit-archive bucket, DynamoDB tables, Secrets Manager secrets, customer-managed KMS keys. HealthScribe (Transcribe) invocations logged. Bedrock invocations logged with metadata only (correctly avoiding PHI persistence in CloudTrail). Comprehend Medical invocations logged. CloudTrail logs in dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days.
- The recipe correctly identifies in-room audio as PHI and biometric throughout: "The microphone in the room captures the patient's voice (a biometric identifier), the clinician's voice, and any bystanders. The audio is PHI by HIPAA definition; in some jurisdictions (Illinois under BIPA, for instance) the voiceprint itself is regulated as biometric data with specific consent and disclosure requirements." This is the recipe's clearest articulation of the biometric-data-as-recipe-acute primitive.
- Recording-consent compliance correctly elevated with the in-person framing: "State-by-state recording-consent compliance: an explicit consent disclosure plays before recording for all-party-consent jurisdictions; consent at intake suffices for one-party-consent jurisdictions but is institution-policy-driven."
- 42 CFR Part 2 substance-use-treatment records correctly elevated as a recipe-specific concern.
- Brief-retention audio policy correctly elevated with the recipe-distinct framing: "Audio recordings: SSE-KMS with customer-managed keys, retention bound to the QA review window (typically hours to a few days post-signing) then automatic deletion via lifecycle policy."
- The audit-record at Step 7 correctly uses archive-references (`audio_archive_ref`, `canonical_transcript_ref`, `rendered_note_archive_ref`, `signed_note_ref`, `ehr_document_id`) rather than embedding raw transcripts. This is the architecturally-correct pattern that Recipes 10.1, 10.2, 10.3 had to be coached toward and that 10.4, 10.5, 10.6 have adopted; Recipe 10.7 has it right at the audit-record level.
- The working-store discipline is meaningfully better than the chapter-pattern baseline: Step 2C uses `transcript_archive.append(...)` to write streaming segments to the archive bucket, with only structural metadata in the transcript-state table; Step 4F uses `note_draft_archive.put(...)` for the rendered note content with only `rendered_note_archive_ref` and metadata in the note-state table. The remaining gap (Step 5C structured-extraction extractions content) is a localized MEDIUM rather than the chapter-pattern HIGH.
- Patient-id correctly stored as a hash (`patient_id_hash: hash(patient_id)`) rather than a raw identifier in the audit record and the upstream state tables.
- Synthetic-data discipline correctly stated: "Never use real patient encounter audio in development without explicit consent and IRB or institutional review; voice samples are biometric and PHI-bearing data with non-trivial governance implications."
- Per-encounter consent capture and bystander handling correctly elevated as architectural primitives with explicit pseudocode at Step 1C and Step 1D. The clinician's confirmation of who is in the room ("Mr. Johnson, your daughter Sarah is with you today; is it okay with both of you that this conversation is being captured for documentation?") is the recipe's strongest single articulation of the workflow-friendly bystander-consent pattern.

### Finding S1: Biometric Clinician Voiceprint Enrollment Under BIPA, Texas, and Washington State Law Architecturally Implicit Despite Explicit Prose Elevation

- **Severity:** HIGH
- **Expert:** Security (biometric-data regulatory compliance, voiceprint lifecycle)
- **Location:**
  - Technology section, "Speaker enrollment for the clinician" paragraph: "A meaningful improvement in diarization comes from enrolling the clinician's voice ahead of time. The system stores a voiceprint for the clinician (typically derived from a brief enrollment recording or accumulated from prior encounters with explicit consent)... This biometric handling has its own governance overhead (the voiceprint is a biometric identifier; institutional policy on biometric data applies; some jurisdictions like Illinois under BIPA have specific consent and disclosure requirements; states with similar statutes include Texas and Washington)."
  - Cross-Cutting Design Points: "Audio is PHI throughout, and biometric. The microphone in the room captures the patient's voice (a biometric identifier), the clinician's voice, and any bystanders... in some jurisdictions (Illinois under BIPA, for instance) the voiceprint itself is regulated as biometric data with specific consent and disclosure requirements."
  - Step 1E pseudocode `encounter_state_table.put({..., clinician_voiceprint_enrolled: check_voiceprint_enrollment(clinician_id)})` and Step 2A pseudocode `clinician_voiceprint_id: (state.clinician_voiceprint_enrolled and CLINICIAN_VOICEPRINT_REGISTRY[state.clinician_id])`.
  - Prerequisites BAA / Compliance row: "Biometric-data law (Illinois BIPA, Texas, Washington) applies if the institution stores clinician voiceprints for diarization-enrollment."

- **Problem:** The recipe correctly identifies clinician voiceprint enrollment as a "meaningful improvement in diarization" architectural primitive in three separate places and correctly identifies BIPA, Texas, and Washington biometric-data law as applicable. Despite this, the architecture pattern, the diagram, and the pseudocode treat the voiceprint registry as a passing reference (`CLINICIAN_VOICEPRINT_REGISTRY[state.clinician_id]`) without specifying the BIPA-grade governance scaffolding. Recipe-acute and recipe-distinct because:

  1. **In-person ambient documentation is the prime use case for clinician-voiceprint enrollment.** The recipe's own prose correctly notes that "for clinicians who do many ambient-documented encounters per day, the enrollment-based diarization is meaningfully more reliable than purely acoustic diarization." The high-volume per-clinician encounter pattern that justifies enrollment is recipe-distinct from telehealth (10.6) and dictation (10.4).

  2. **BIPA carries statutory damages of $1,000 per negligent violation and $5,000 per intentional or reckless violation.** A class-action settlement under BIPA can run into hundreds of millions of dollars (the Facebook BIPA settlement in 2021 was $650 million for the photographic biometric matching feature). An institution that captures and stores clinician voiceprints without the BIPA-grade governance scaffolding is exposed to statutory-damages litigation that an architectural specification could have prevented.

  3. **Texas Capture or Use of Biometric Identifier Act (CUBI) and Washington's biometric-data law have similar but not identical requirements.** The architecture should support a per-state regulatory profile that adapts the consent disclosure, the retention policy, the deletion-on-departure timeline, and the disclosure-accounting log per the clinician's institutional location.

  4. **The architecture does not specify where the voiceprint is stored.** The `CLINICIAN_VOICEPRINT_REGISTRY` is referenced as a constant lookup; whether it is a DynamoDB table, an S3 bucket, a Bedrock-managed feature store, a HealthScribe-managed enrollment, or an external biometric-vendor surface is not specified. Each storage choice has different governance characteristics.

  5. **The architecture does not specify the retention policy for voiceprints.** A voiceprint is biometric data that BIPA generally permits to be retained only as long as needed for the disclosed purpose, with deletion required when the purpose ends (typically when the clinician leaves the institution). The architecture does not specify how the deletion-on-departure flow is triggered, who is responsible, or how the deletion is audited.

  6. **The architecture does not specify the consent flow for voiceprint enrollment.** Recipe 2.8's consent-management treatment, which this recipe defers to, is a per-encounter-patient consent flow, not a per-clinician biometric-data consent flow. The clinician-side consent-and-disclosure for voiceprint enrollment is recipe-distinct and not covered by the patient-side consent flow.

  7. **The architecture does not specify the disclosure-accounting log.** BIPA requires institutions that collect biometric identifiers to disclose the collection, the purpose, and the retention period in writing, and (for some uses) to obtain written consent. A disclosure-accounting log is the operational substrate that demonstrates compliance.

  8. **The recipe correctly notes that "patient-side voice enrollment is rare" and explains why.** The same governance reasoning applies to clinician-side enrollment but with the inverse economic answer: the per-clinician benefit is high enough to justify the governance overhead, but only if the governance is actually built. The architecture should make the governance build explicit.

  9. **Bedrock Knowledge Bases and HealthScribe themselves do not currently expose a managed voiceprint-enrollment feature.** Institutions building enrollment-based diarization typically build their own enrollment workflow (record a brief sample at clinician onboarding; extract a voiceprint embedding; store it for use in subsequent diarization). The architecture should specify this build path or the use of a managed third-party biometric-vendor.

- **Fix:** Promote the clinician voiceprint enrollment from a passing reference to an architectural primitive. Specifically:

  - Add a "Clinician Voiceprint Enrollment and BIPA-Grade Governance" subsection to the architecture pattern's Cross-Cutting Design Points:
    > "Clinicians whose voiceprints are enrolled for diarization purposes are subject to a biometric-data governance profile that complies with Illinois BIPA, Texas CUBI, Washington's biometric-data law, and any other applicable state biometric-data statutes. The profile applies at clinician onboarding (consent capture with written disclosure of purpose, collection method, retention period, and deletion timeline; disclosure-accounting log entry), at voiceprint storage (separate KMS-encrypted store with biometric-data-classification access controls; voiceprints stored as embeddings rather than raw audio where possible; never co-mingled with patient-side audio), at use (every encounter that uses the voiceprint is logged in the disclosure-accounting log), and at clinician departure or consent withdrawal (deletion within the institutional policy timeline, typically immediate; deletion verification logged). The clinician-side consent flow is distinct from the patient-side consent flow and is owned by the institutional human-resources or medical-staff-services team in coordination with the privacy officer."

  - Add a `voiceprint_registry` architectural component to the diagram with explicit KMS key class (separate from patient-side data), retention policy (institutional-policy-bound; deletion-on-departure mandatory), and access-control surface (the streaming and batch HealthScribe data access role, the diarization-quality-evaluation reviewer with explicit biometric-data access, the privacy officer for audit purposes).

  - Update Step 1E pseudocode to capture the voiceprint-enrollment status with explicit BIPA-grade fields:
    ```
    encounter_state_table.put({
        ...,
        clinician_voiceprint_enrolled:
            check_voiceprint_enrollment(clinician_id),
        clinician_voiceprint_consent_version:
            (state.clinician_voiceprint_enrolled and
             CLINICIAN_VOICEPRINT_CONSENT_REGISTRY[
                 state.clinician_id].consent_version),
        clinician_jurisdiction_for_biometric_compliance:
            lookup_clinician_jurisdiction(clinician_id),
        ...
    })
    ```

  - Update Step 7 audit_record to include explicit voiceprint-use disclosure-accounting:
    ```
    voiceprint_used: state.clinician_voiceprint_enrolled,
    voiceprint_consent_version:
        state.clinician_voiceprint_consent_version,
    biometric_jurisdiction:
        state.clinician_jurisdiction_for_biometric_compliance,
    ```

  - Add a Production-Gaps "Clinician Voiceprint Biometric-Data Compliance" subsection naming the privacy officer plus the medical-staff-services or human-resources team as the canonical owners; specify the clinician-onboarding voiceprint-enrollment workflow (consent disclosure language, signature capture, retention period documentation, deletion-on-departure trigger); specify the per-state regulatory profile (BIPA, CUBI, Washington's law, with the verify-current-text-at-build-time hedge); specify the deletion-verification audit cadence; reference the audit log as the disclosure-accounting substrate.

  - Cross-reference Finding A1 (faithfulness check) and Finding A2 (per-cohort monitoring); the voiceprint enrollment improves diarization quality, which improves the per-cohort metrics, which improves the faithfulness check input quality. The three findings reinforce each other.

### Finding S2: 42 CFR Part 2 Behavioral-Health Profile Architecturally Implicit Despite Explicit Elevation in Prose

- **Severity:** MEDIUM
- **Expert:** Security (regulatory-confidentiality, behavioral-health-specific PHI handling)
- **Location:**
  - Cross-Cutting Design Points "Behavioral-health-specific handling" paragraph: "Behavioral-health visits have stricter retention windows, narrower access controls, and per-encounter explicit consent. Some institutions exclude behavioral-health from ambient documentation entirely. The architecture supports a behavioral-health profile that the institution can apply per visit type or per clinician. Recipe 2.8 and recipe 10.6 cover the behavioral-health profile pattern in detail."
  - Prerequisites BAA / Compliance row: "Behavioral-health visits may have additional state-level confidentiality requirements (42 CFR Part 2 for substance-use treatment records); the architecture supports a behavioral-health profile with stricter retention and access controls."
  - Production-Gaps "Behavioral-health-specific privacy controls" paragraph.

- **Problem:** Same chapter pattern as Recipe 10.6 Finding S2. The recipe correctly defers the behavioral-health profile treatment to recipes 2.8 and 10.6 (a defensible composition choice) but does not architect the in-person-specific dimensions of the profile. Recipe-acute because:

  1. **In-room consent for behavioral-health visits has different dynamics than telehealth.** In-person, the patient is physically present and cannot easily exit the room mid-encounter; the consent disclosure has to be more explicit and the in-encounter pause-and-resume affordance is more important. The recipe's "When the patient explicitly invokes a confidentiality moment ('I want to tell you something, but please pause the recording'), the system has to support an in-encounter pause" framing is recipe-distinct but is not specifically tied to the behavioral-health profile.

  2. **In-room bystanders are recipe-acute for behavioral-health.** A behavioral-health visit with a family member present requires both the patient's and the family member's consent; the architecture should specify how the bystander consent flow interacts with the 42-CFR-Part-2 disclosure requirements when applicable.

  3. **The behavioral-health-as-explicit-opt-out pattern is recipe-acute.** The recipe correctly notes that "many institutions choose to exclude behavioral-health visits from ambient documentation entirely." The architecture should specify how the exclusion is enforced (visit-type flag at scheduling time; clinician-side override for inclusion with stricter consent; per-clinician opt-out for behavioral-health-specifically).

- **Fix:** Add a recipe-distinct "Behavioral-Health and 42 CFR Part 2 Profile in In-Person Setting" subsection to the architecture pattern's Cross-Cutting Design Points that defers to recipe 2.8 for the LLM-driven note generation and EHR-write-back specifics but specifies the in-person-distinct dimensions:
  - In-encounter pause-and-resume affordance with hard-pause (audio capture stops at device) versus soft-pause (audio captured but tagged off-the-record) options
  - In-room bystander consent capture for behavioral-health visits with explicit Part-2 disclosure where applicable
  - Visit-type-flag-based exclusion enforcement at scheduling time with clinician-side override requiring stricter consent
  - Per-room device configuration for behavioral-health rooms (typically with stricter retention and audio-deletion-on-encounter-end as the default)
  - Per-state regulatory profile (recipe-acute for the in-person setting because the clinic's location governs unambiguously, unlike telehealth)

  Update Step 1B pseudocode to capture the behavioral-health profile flag explicitly. Cross-reference Finding S1 (voiceprint enrollment); behavioral-health visits with voiceprint-enabled clinicians require dual-compliance handling.

### Finding S3: Foundation-Model Prompt-Injection Risk for the LLM-Driven Note Generation Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (prompt-injection, content-faithfulness boundary)
- **Location:** Step 4D pseudocode `bedrock.invoke_model(model_id: NOTE_RENDERING_MODEL, prompt: rendering_prompt, guardrail_id: AMBIENT_DOC_GUARDRAIL_ID, ...)` and the build_rendering_prompt that templates `transcript_block`, `ehr_context`, and `clinician_style_preferences` directly into the prompt.

- **Problem:** Same chapter pattern as Recipe 10.4 Finding S2, Recipe 10.5 Finding S2, and Recipe 10.6 Finding S3. Recipe-acute because the patient's verbatim speech captured by the in-room microphone, the family-member or bystander speech captured incidentally, and the EHR-context-pulled patient history are all templated into the rendering prompt as the source for the note generation. A patient or bystander who utters instruction-like text during the encounter could trigger prompt-injection that the LLM may follow. The retrieved EHR context is also templated and is an indirect injection vector if any prior content contains instruction-like text.

  Recipe-specific scenarios:

  1. A bystander (a family member with adversarial interests in the patient's medical record) recites instruction-like text during the encounter hoping to manipulate the generated note.
  2. A patient who, in good faith, repeats text they read elsewhere (a self-help guide, a medication-information leaflet) that happens to contain instruction-like patterns.
  3. A retrieved EHR-context entry that contains instruction-like text becomes an indirect injection vector for the next encounter's note generation.
  4. A successful prompt-injection that produces a note with content the patient never said is the worst class of failure the recipe explicitly names; the runtime faithfulness check is supposed to catch this but, per Finding A1, the faithfulness check is itself underspecified.

- **Fix:** Add a prompt-injection-mitigation paragraph to the architecture pattern. Specify the delimited-input framing for the transcript and the EHR context (transcript wrapped in `<transcript>...</transcript>`, EHR context wrapped in `<ehr_context>...</ehr_context>`, clinician style preferences wrapped in `<clinician_style>...</clinician_style>`); the system prompt explicitly instructs the model to treat all delimited content as untrusted patient-or-historical data, not as instructions; the prompt requests strict structured output (JSON with the per-section template plus citations) that the orchestration logic validates before treating the output as the draft. The faithfulness check (Step 4E) is the secondary safety layer that catches prompt-injection-driven content that survives structured-output validation. Bedrock Guardrails (already present in the pseudocode at `guardrail_id: AMBIENT_DOC_GUARDRAIL_ID`) is the tertiary safety layer.

  Add to Production-Gaps a paragraph on "EHR-context retrieved-content supply-chain integrity": treat the retrieved EHR context as an indirect injection surface; periodically scan the retrieved-context content for instruction-like text and flag for review; limit the retrieved-context to the minimum necessary for the per-specialty template.

### Finding S4: Audit-Log Retention Floor Specified Generically Without Explicit Pediatric-Records, EHR-Vendor, and Biometric-Records Floors

- **Severity:** MEDIUM
- **Expert:** Security (regulatory retention)
- **Location:** Prerequisites Encryption row: "Audit archive: SSE-KMS with customer-managed keys, retention sized to the longer of HIPAA's six-year minimum, state medical-records-retention rules, and the institutional regulatory floor."

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. Recipe-acute because:

  1. **Pediatric records.** In-person ambient documentation includes pediatric visits (the recipe-distinct "pediatric visit with the clinician + parent + child" failure-mode framing). State-specific medical-records-retention rules for pediatric patients can extend to age-of-majority-plus-multiple-years.

  2. **The EHR-vendor's audit-retention floor.** EHR vendors (Epic, Oracle Health, athenahealth) have their own audit-retention defaults that may differ from the institutional floor.

  3. **Biometric records retention.** BIPA, CUBI, and Washington's biometric-data law have specific retention rules for biometric identifiers (typically deletion when the purpose ends, not the medical-records-retention floor). The voiceprint-disclosure-accounting log is a biometric-records artifact with its own retention regime.

  4. **42 CFR Part 2 disclosure-accounting log retention.** For Part-2-eligible visits, the disclosure-accounting log has its own retention requirement.

- **Fix:** Name the audit-log retention floor as "the longest of HIPAA's six-year minimum, state-specific medical-records-retention rules (which for certain patient populations such as pediatric records can extend to age-of-majority-plus-multiple-years), the EHR vendor's audit-retention floor, the 42 CFR Part 2 disclosure-accounting log retention for Part-2-eligible visits, and the institutional regulatory floor." Note that biometric-records (voiceprint-disclosure-accounting log) follow a separate retention regime per Finding S1. Reference the institutional retention policy as the canonical source.

### Finding S5: Lambda Invocation Authentication Across API Gateway-to-Lambda and Step-Functions-to-Lambda Integration Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (identity-boundary)
- **Location:** Architecture diagram `APIGW --> WEB`, `APIGW --> COGNITO`, `WEB --> L_EHR`, and the IAM Permissions row.

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. The recipe specifies per-Lambda least-privilege but does not specify the additional integrity boundary on the Lambda invocation (resource-based policy pinning the invoking principal to the production API Gateway stage ARN, the production Step Functions state-machine ARN, or the production EventBridge rule ARN as appropriate).

- **Fix:** Specify in the IAM Permissions row that each Lambda's resource-based policy pins the invoking principal to the production API Gateway stage ARN, the production Step Functions state-machine ARN, or the production EventBridge rule ARN as appropriate. Add a defense-in-depth event-payload validation guard at the start of each Lambda that verifies the invoking context against the production constants.

### Finding S6: Cohort Encoding in CloudWatch Metric Dimensions With Equity-Stake Implications

- **Severity:** LOW
- **Expert:** Security (privacy, recipe-specific equity-monitoring stakes)
- **Location:** Step 7 `cloudwatch.put_metric` calls with `dimensions: { specialty, language, visit_type, audio_quality_band }`.

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. The recipe correctly elevates per-cohort accuracy as architecturally important and uses `cohort_axes` in the audit record (best practice). The CloudWatch dimensions are language, specialty, visit_type, and audio_quality_band; these are not sensitive demographics by themselves, but if the dimensions expand to include age-band, accent-group, region, or per-room demographic-correlated variables, those should be encoded as cohort-axis-hash labels in CloudWatch dimensions.

- **Fix:** Specify that cohort dimensions on CloudWatch metrics use cohort-axis-hash labels for sensitive dimensions; language, specialty, visit_type, and audio_quality_band may use direct identifiers; demographic-stratification analytics happen in the analytics layer (Athena over the audit archive).

### Finding S7: Audio Retention Deletion Verification Specified But Not Architecturally Audited

- **Severity:** LOW
- **Expert:** Security (PHI lifecycle verification)
- **Location:** Prerequisites Encryption row.

- **Problem:** The recipe correctly specifies the brief-retention default with KMS-encrypted storage and lifecycle-policy deletion. The deletion-verification discipline is implicit. Recipe-acute because in-room audio captures bystander content and biometric data that the institution has additional disclosure obligations around.

- **Fix:** Add a paragraph: "Audio retention deletion is verified by a periodic audit job that lists the audio bucket's contents older than the retention window and confirms the lifecycle policy is removing them; deletion-verification events are logged to CloudTrail and surfaced in the audit-archive analytics."


## Architecture Expert Review

### What's Done Well

- **Eight-stage architecture (encounter setup and consent capture, in-room audio capture, streaming ASR with diarization, in-encounter live display, batch ASR for finalization, clinical classifier and note generation, clinician review and signature, audit-archive-and-learning) is the right shape and recipe-distinct from 10.6's eight-stage telehealth decomposition.**
- **In-room audio capture as architectural priority correctly elevated.** "The choice of capture device has more impact on system performance than the choice of ASR vendor, in many deployments. A great ASR with bad audio underperforms a mediocre ASR with good audio, almost without exception."
- **Streaming-and-batch as parallel-not-sequential pipelines correctly architected.**
- **HealthScribe-as-primary-managed-service with Bedrock-for-institutional-template-rendering is the right composition.**
- **The three-DynamoDB-table separation (encounter-state, transcript-state, note-state) is correct.** Working-store discipline largely follows archive-reference pattern (`transcript_archive`, `note_draft_archive`); meaningfully better than 10.1-10.6 baseline.
- **Step-Functions-for-post-encounter-pipeline is the right durable-orchestration choice.**
- **Clinician-side voiceprint enrollment elevated as diarization-quality primitive** (governance gaps per S1).
- **Clinical-content classifier as architectural primitive correctly elevated.** Recipe-distinct: "A naive system that captures and structures everything produces a note like this..." with the magazines-and-dog-surgery vignette grounds the classifier-as-architectural-primitive case.
- **Failure modes degrade to manual documentation correctly elevated.**
- **Cost estimate correctly granular** with HealthScribe-per-minute-charges-dominate framing plus dedicated-capture-hardware-budget-separately note.
- **Honest Take's ten-trap enumeration covers the recipe's central operational risks** including the recipe-distinct tenth trap (room acoustics as IT problem).
- **Why-This-Isn't-Production-Ready section names sixteen production gaps** including the recipe-distinct per-room audio infrastructure, per-specialty note template library, and clinician training and adoption support.

### Finding A1: Faithfulness Check Architecturally Underspecified With No Layer Ordering, No Per-Layer Disposition, No Named Ownership, and No Specified Relationship Between Runtime and Offline Review

- **Severity:** HIGH
- **Expert:** Architecture (LLM-output-integrity, faithfulness-as-clinical-safety)
- **Location:** Step 4E pseudocode `faithfulness_result = run_faithfulness_check(rendered_note, canonical_transcript, ehr_context)` and the architecture diagram's `BEDROCK_FAITH[Bedrock<br/>Faithfulness Check]` as a single component.

- **Problem:** Same chapter pattern as Recipe 10.4 Finding A3 and Recipe 10.6 Finding A1. The recipe correctly elevates faithfulness as the highest-stakes safety artifact in seven separate places (the LLM-Driven Note Generation subsection's "Faithfulness checks" property; the Cross-Cutting Design Points "Faithfulness checks gate the LLM-generated note" paragraph; the Where-it-Struggles "LLM-generated note hallucination on sparse content" item; the Production-Gaps "Layered faithfulness program with named clinical-quality ownership" paragraph which correctly names the four layers; the Production-Gaps "Faithfulness regression testing on prompt and model updates" paragraph; the Honest Take's third trap; and the recipe's defer-to-2.8 framing). Despite the prose elevation, the architecture pattern leaves the faithfulness check as a single function call returning a `severity` classifier.

  Recipe-acute because:
  1. The LLM-rendered note is the highest-stakes-LLM-output in the recipe (a faithfulness failure produces a chart with content the patient never said, the clinician signs it, it becomes the legal record; the recipe explicitly names this as "the worst class of failure").
  2. The in-room audio quality variation interacts with faithfulness: poor-audio-quality encounters produce lower-confidence transcript content; the LLM is more prone to filling in plausible-sounding content from low-confidence segments; the faithfulness check must be tuned to recognize low-confidence-source-segment as an additional risk factor.
  3. The recipe's deferral to 2.8 is appropriate for the LLM-driven generation specifics but does not absolve the architecture-pattern of specifying the layered structure at this recipe's level.
  4. The implicit-exam-finding handling subsection correctly names the placeholder-versus-normal-template tradeoff but does not tie it to the faithfulness check (a system that defaults to a normal-exam template is making a faithfulness claim that the exam was actually normal; this should be a specific faithfulness rule).

- **Fix:** Promote the faithfulness check from a single opaque function call to a layered architecture stage matching the structure recommended in Recipe 10.6 Finding A1 with recipe-distinct in-person dimensions:

  - Layer 1 (cheaper, runs first): citation grounding verification, structured-output schema validation, exam-finding-fabrication detection (when the placeholder pattern would have been correct but the LLM emitted exam findings without transcript support)
  - Layer 2 (parallel): LLM-judge faithfulness scoring; clinical-rule-based contradiction detection
  - Layer 3 (offline, sampled): clinical-quality team sample review with per-specialty samples (recipe-distinct: per-room sample stratification, per-audio-quality-band sample stratification)
  - Per-layer disposition (block vs flag) policy-driven; tighter for behavioral-health profile
  - Per-cohort faithfulness-failure-rate as launch and operational gate
  - Named ownership at clinical-quality officer

  Update Step 4E pseudocode to make per-layer execution explicit. Update the architecture diagram to show three faithfulness components rather than one. Add a Production-Gaps "Faithfulness Asset Maintenance" subsection. Cross-reference Finding S3 (prompt-injection mitigation) and Finding A2 (per-cohort monitoring).

### Finding A2: Per-Cohort Accuracy and Adoption Monitoring With Audio-Quality-Band, Per-Room, and Per-Device Stratification Specified in Audit Record But Launch-Gate Discipline Architecturally Implicit

- **Severity:** HIGH
- **Expert:** Architecture (equity-monitoring-as-architectural-primitive)
- **Location:** Step 7 audit record `cohort_axes: { language, visit_type, specialty, patient_age_band, audio_quality_band }` plus dimensions `room_id, device_type` referenced elsewhere in the audit_record; Cross-Cutting Design Points "Per-cohort accuracy monitoring is a launch gate" paragraph; Production-Gaps "Per-cohort accuracy and adoption monitoring with launch gates" paragraph.

- **Problem:** Same chapter pattern as Recipe 10.6 Finding A2, with recipe-distinct extension for per-room and per-device stratification. The recipe correctly elevates per-cohort monitoring with audio-quality-band as recipe-acute in three separate places, and the audit record correctly includes the architecturally-correct cohort_axes decomposition. Despite the correct elevation, the architecture pattern, the diagram, and the cross-cutting design points do not specify:

  1. Per-audio-quality-band minimum-recall thresholds as launch gates
  2. Per-language-by-audio-quality two-axis stratification
  3. **Per-room and per-device stratification (recipe-distinct).** The recipe correctly notes that "the institution that runs the audio survey, identifies the rooms that need treatment, and budgets the physical-plant work is the team that ships a system that works equally well across the institution. The team that skips this work ships a system that works in some rooms and not others." Per-room metrics are the operational instrumentation that surfaces the room-acoustics-as-deciding-factor primitive at scale; the architecture should elevate per-room and per-device-type cohort monitoring as recipe-distinct launch gates.
  4. Per-cohort sample-size minimums for statistical reliability
  5. Per-specialty stratification with behavioral-health-as-distinct-cohort
  6. Audio-quality-band as per-encounter feature not just metric dimension (driving lower confidence threshold for poor-audio encounters and audio-quality-warning surfaced in the clinician review interface)
  7. Per-cohort sustained-adoption rate (recipe-acute: the 60-85% sustained-adoption benchmark is per-cohort, not institution-wide)

  Recipe-acute because:
  1. The asymmetry the recipe correctly names is the equity-stake (the 35-year-old patient with clear voice in a well-treated room versus the 85-year-old patient with denture-related articulation in an HVAC-noisy room).
  2. Per-room variability is recipe-distinct (in-person rooms vary in acoustics independently of patient demographics).
  3. The behavioral-health profile interacts with cohort monitoring (Finding S2 cross-reference).

- **Fix:** Promote per-cohort monitoring from prose to architectural primitive. Add explicit per-cohort structure to the Audit, Archive, and Learning stage with single-axis cohorts (per-language, per-specialty, per-clinician, per-audio-quality-band, per-patient-age-band, per-visit-type, **per-room, per-device-type**), two-axis cohorts (per-language-by-audio-quality, per-specialty-by-language, per-room-by-time-of-day for HVAC-correlated noise patterns), per-cohort minimum sample size, per-cohort threshold metrics including sustained-adoption rate at 30/90/180 days, per-cohort thresholds defined per-axis with launch gate (every cohort must meet threshold; institution-wide average is informational only), disparity alerts triggering reviews and product-level remediation including potentially disabling the feature for cohorts where it underperforms.

  Add audio-quality-band as a per-encounter feature driving lower confidence threshold for poor-audio encounters, audio-quality-warning surfaced in the clinician review interface, and patient-side network-quality-remediation prompt during the visit (where network is involved). Add per-room remediation playbook (acoustic treatment, microphone repositioning, dedicated-capture-hardware deployment) as part of the per-room cohort response.

  Cross-reference Finding S1 (voiceprint enrollment improves diarization quality, which improves per-cohort metrics), Finding S2 (behavioral-health profile cross-cuts cohort monitoring), and Finding A1 (faithfulness check per-cohort failure-rate is a per-cohort metric).

### Finding A3: Working-Store Structured-Extraction Context-Snippets Persisted in Note-State DynamoDB Table Outside Archive-Reference Discipline at Step 5C

- **Severity:** MEDIUM
- **Expert:** Architecture (PHI minimization in working store, archive-reference discipline consistency)
- **Location:** Step 5C pseudocode `note_state_table.update(action: "store_structured_extractions", extractions: { medications: coded_medications, conditions: coded_conditions, higher_level: higher_level.content, ... })` where each entry in `coded_medications` and `coded_conditions` includes a `context_snippet: extract_context(canonical_transcript, ..., window_seconds: 10)` (a 10-second window of transcript text around each entity).

- **Problem:** Same chapter pattern as Recipe 10.1 Finding S1, Recipes 10.2 through 10.6 Finding S1. Recipe-localized because the recipe got most of the working-store discipline right (Step 2C uses `transcript_archive`, Step 4F uses `note_draft_archive`) but slipped at Step 5C: the structured extractions and their context_snippets are written into the note-state table, which is the chapter-pattern parallel-PHI-store anti-pattern. Recipe-localized severity: lower than the chapter-pattern HIGH because the discipline is largely correct elsewhere, but still a localized PHI-minimization gap.

- **Fix:** Adopt the archive-reference pattern at Step 5C. Write the structured extractions (with their context_snippets) to a draft-extractions archive in S3 with the same KMS key class as the note-draft archive; store only `extractions_archive_ref`, `extraction_count`, `confirmation_status`, and per-category counts in the note-state table. Update the Cross-Cutting Design Points to reflect the working-store-as-archive-reference pattern as a uniform discipline across the recipe (already largely the case; just close the Step 5C gap).

### Finding A4: HealthScribe NoteTemplate Enum Constraint at Step 3C Pseudocode Mirrors Code Review Finding W1

- **Severity:** MEDIUM
- **Expert:** Architecture (vendor-API correctness)
- **Location:** Step 3C pseudocode:
  ```
  clinical_note_generation_settings: {
      note_template: select_template(
          visit_type: state.visit_type,
          specialty: state.clinician_specialty)
  }
  ```

- **Problem:** Per the code review's W1 finding, the HealthScribe `Settings.ClinicalNoteGenerationSettings.NoteTemplate` field accepts a fixed enum (`HISTORY_AND_PHYSICAL`, `GIRPP`, `BIRP`, `SIRP`, `DAP`, `BH_SOAP`, `PH_SOAP`); passing a custom institutional template ID like `"primary-care-soap-v3"` produces a `BadRequestException`. The recipe's pseudocode at Step 3C shows `select_template(...)` flowing into `note_template:` directly, which propagates the error into the recipe text alongside the Python companion. The architectural intent of the recipe is correct (institutional templates apply downstream via Bedrock at Step 4); the implementation surface needs to be aligned with the enum-versus-custom-id distinction.

- **Fix:** Update Step 3C pseudocode to use the closest-fit HealthScribe built-in enum (or to default to `HISTORY_AND_PHYSICAL`) and add a sentence noting that institutional formatting happens at the Bedrock-rendering step (Step 4). The recipe-internal consistency carries through to the Python companion.

### Finding A5: Idempotency for EHR Write-Back Architecturally Specified But Composition Could Be More Concretely Tied to Encounter-Level Idempotency

- **Severity:** MEDIUM
- **Expert:** Architecture (clinical safety, write-path integrity)
- **Location:** Step 6C pseudocode:
  ```
  idempotency_key = build_idempotency_key(
      encounter_id: state.encounter_id,
      clinician_id: clinician_id,
      document_type: "clinical_note",
      signed_at: now())
  ```

- **Problem:** The recipe is closer to architecturally-specified than 10.1-10.6 (the idempotency key is explicit, with encounter_id, clinician_id, document_type, signed_at composition). The remaining gap: the per-confirmed-extraction idempotency key for the structured-chart updates is not specified; the FHIR conditional-create header (`If-None-Exist`) where the EHR vendor supports it is not specified; the duplicate-detection flow on idempotency-match returning the prior submission's document_id is not specified.

- **Fix:** Specify per-confirmed-extraction idempotency key `(encounter_id, extraction_id, extraction_type)`; specify the FHIR conditional-create where the EHR vendor's FHIR implementation supports it; specify the duplicate-detection flow on idempotency-match.

### Finding A6: Foundation-Model and Prompt and Template Versioning via Inference Profiles and Aliases Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (deployment-and-change-management)
- **Location:** Step 4F pseudocode `note_state_table.put({..., model_version: NOTE_RENDERING_MODEL_VERSION, prompt_version: NOTE_RENDERING_PROMPT_VERSION})`.

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. The pseudocode references model and prompt identifiers and version-stamps them in the audit record (good, partial credit) but does not specify the blue-green deployment pattern with canary inference profiles, traffic-shift, rollback-on-regression, or held-out evaluation set with per-cohort coverage.

- **Fix:** Add a "Deployment Pattern" subsection specifying versioned model and prompt and template and rule-catalog and per-language asset definitions in version control; canary inference profile with traffic-shift; rollback-on-regression; held-out evaluation set with per-language, per-specialty, per-audio-quality-band, per-room-acoustics-band, faithfulness-edge-case, structured-extraction-edge-case, and prompt-injection samples; version stamping on every encounter audit record (already partially correct; extend to all artifact versions).

### Finding A7: Multi-Language Architecture Build-For-Day-One Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (multi-language operational pattern)
- **Location:** Cross-Cutting Design Points and the Variations "Multi-language support" item.

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. The recipe acknowledges multi-language support in the Variations section but does not architect the per-language pipeline pattern. Recipe-acute because the in-person encounter often involves a Spanish-speaking patient with an English-speaking clinician (the recipe's own "multilingual visits where the configured language differs from the actual visit language" failure mode confirms this).

- **Fix:** Specify the per-language pipeline pattern: per-language ASR configuration with custom vocabulary; per-language note-generation prompt with native-speaker clinical-informatics input; per-language template definitions; per-language faithfulness rule catalogs; per-language diarization tuning; per-language structured-extraction approach (where Comprehend Medical does not directly support the language). Reference build-for-day-one.

### Finding A8: Audio Retention Policy Configuration Mechanism Could Be More Concretely Specified With Per-Visit-Type and Per-Room Differentiation

- **Severity:** MEDIUM
- **Expert:** Architecture (PHI lifecycle)
- **Location:** Prerequisites Encryption row.

- **Problem:** Same chapter pattern as Recipes 10.3 through 10.6. The recipe is closer to architecturally-specified than earlier recipes but the configuration mechanism with per-visit-type and per-room differentiation is not specified. Recipe-acute because the behavioral-health profile (per Finding S2) requires shorter retention than primary care, and per-room defaults may differ (a behavioral-health-dedicated room has shorter retention by default than a general-medicine room).

- **Fix:** Specify retain-briefly with configurable per-visit-type and per-room retention window (default: brief retention 24-72 hours for primary care; 24-48 hours for behavioral-health; 24 hours for 42-CFR-Part-2-eligible) with KMS-encrypted storage, lifecycle-policy deletion, and access logged through CloudTrail. Per-visit-type and per-room retention enforced through S3 lifecycle policies on per-prefix definitions.

### Finding A9: Disaster Recovery and Partial-Failure Topology Architecturally Implicit

- **Severity:** MEDIUM
- **Expert:** Architecture (disaster-recovery and failover)
- **Location:** Production-Gaps "Disaster recovery and degraded-mode operation" paragraph.

- **Problem:** Same chapter pattern as Recipes 10.1 through 10.6. The recipe correctly elevates the failover requirement in production-gaps but does not architect the failover topology.

- **Fix:** Add a "Disaster Recovery Topology" subsection specifying the per-stage failover policy (HealthScribe outage with cross-region fallback or with degraded-mode-record-only; Bedrock unavailability with HealthScribe-default-template fallback or manual documentation; Comprehend Medical unavailability with LLM-only structured-extraction; EHR API unreachable with durable note storage and retry; in-room device failure with per-room fallback to a backup device or manual documentation). Specify the failover-detection-and-failover-back triggers and quarterly testing cadence.

### Finding A10: Bedrock Model HIPAA Eligibility Per Specific Model Underspecified

- **Severity:** LOW
- **Expert:** Architecture (BAA-eligibility currency)
- **Location:** Prerequisites BAA / Compliance row.

- **Problem:** Same chapter pattern as Recipes 10.2 through 10.6.

- **Fix:** Add a default-model recommendation (Claude family typical for healthcare) with verify-at-build-time hedge; reference AWS HIPAA Eligible Services Reference URL.

### Finding A11: SMART on FHIR Token Lifecycle for Multi-Hour Pipeline Workflows Not Specified

- **Severity:** LOW
- **Expert:** Architecture (authentication-token lifecycle)
- **Location:** Step 6C pseudocode `lookup_clinician_credentials(clinician_id)` for the EHR write-back.

- **Problem:** Same chapter pattern as Recipes 10.3 through 10.6. The post-encounter pipeline can span hours from encounter-end to clinician-sign (clinicians often batch-sign at end-of-day).

- **Fix:** Add a brief "SMART on FHIR Token Lifecycle" paragraph specifying refresh-token flow, pre-emptive refresh window, refresh failure handling, and audit on token-lifecycle events.


## Networking Expert Review

### What's Done Well

- **VPC endpoint coverage is comprehensive.** DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, Comprehend Medical, Transcribe, Lambda all called out.
- **TLS-in-transit explicitly elevated for all calls.**
- **Endpoint policies pinned to specific resources.**
- **PrivateLink and VPN/Direct Connect for back-office systems mentioned explicitly.**
- **Public-versus-private boundary correctly architected.** Clinician review-and-sign API on public side; back-office EHR FHIR write surface and patient-portal release path on private side.

### Finding N1: In-Room Device-to-Cloud Audio Path Authentication and Encryption Underspecified

- **Severity:** MEDIUM
- **Expert:** Networking (data-in-transit, vendor-data-boundary)
- **Location:** Architecture diagram `DEVICE[Capture Device] --> KVS[Audio Stream WebRTC or HTTPS]` and the Why-These-Services Chime SDK paragraph.

- **Problem:** Recipe-acute and recipe-distinct because the in-room capture devices vary (clinician phone or tablet with vendor app, dedicated capture hardware with microphone array, EHR-embedded experience with workstation microphone or Bluetooth-paired array). Each device-to-cloud audio path has different authentication, encryption, and integrity characteristics:

  1. **Phone or tablet vendor apps** typically authenticate via per-encounter session tokens; the audio path runs through the vendor's cloud before reaching the institutional Transcribe/HealthScribe backend.
  2. **Dedicated capture hardware** typically authenticates via device-certificate-based mTLS; the audio path runs directly from the device to the institutional cloud.
  3. **EHR-embedded experiences with workstation microphones** authenticate via the clinician's EHR session; the audio path may or may not transit the EHR vendor's cloud.

  The architecture does not specify the per-device-pattern data-in-transit posture or the per-pattern BAA scope.

- **Fix:** Add an "In-Room Device-to-Cloud Audio Path" paragraph specifying the per-device-pattern data-in-transit posture (TLS-in-transit minimum; mTLS preferred for dedicated-capture-hardware; per-encounter session tokens scoped to the visit); the per-pattern BAA scope (vendor-app pattern requires the vendor's BAA covers the audio data-in-transit and at-rest within the vendor pipeline; dedicated-capture-hardware pattern requires the hardware vendor's BAA covers the device firmware and update channel; EHR-embedded pattern requires the EHR vendor's BAA covers the audio capture and transit). Reference the platform-specific certification (HITRUST, SOC 2 Type II) for each pattern.

### Finding N2: WebSocket-Based Real-Time Live-Display Through API Gateway Authentication and Connection Limits Architecturally Implicit

- **Severity:** LOW
- **Expert:** Networking (data-in-transit and connection-management)
- **Location:** Architecture diagram `LIVE_DISPLAY[Live Transcript Display API]` and the implicit WebSocket integration for the in-encounter live transcript display.

- **Problem:** Same chapter pattern as Recipes 10.3 through 10.6.

- **Fix:** Add a "WebSocket Live-Display Streaming" paragraph specifying connection-time authentication via Lambda authorizer with Cognito token, account-level concurrent-connection limits, idle-timeout interaction with conversation-pause behavior, and message-type frame format.

### Finding N3: PrivateLink Egress Hierarchy Specified But Not Recipe-Specifically Elevated for the EHR FHIR Surface

- **Severity:** LOW
- **Expert:** Networking (data-in-transit egress for back-office EHR APIs)
- **Location:** Prerequisites VPC row.

- **Problem:** Same chapter pattern as Recipes 10.3 through 10.6.

- **Fix:** Specify the egress hierarchy as: PrivateLink (preferred where the EHR vendor exposes it) > Direct Connect / VPN to on-premise > public-Internet-with-TLS.

### Finding N4: Per-Room Network Resilience and Local-Buffer Behavior Architecturally Implicit

- **Severity:** LOW
- **Expert:** Networking (recipe-distinct device-side resilience)
- **Location:** In-Room Audio Path subsection.

- **Problem:** Recipe-distinct. The in-room capture device may experience brief network outages (clinic Wi-Fi blip, switch reboot, network maintenance). The architecture should specify the device-side local-buffer behavior (audio buffered locally for a few seconds; resumed transmission once network is restored; no audio loss for brief outages) and the network-outage threshold beyond which the encounter falls back to manual documentation.

- **Fix:** Add a paragraph specifying the per-device local-buffer behavior, the network-outage threshold for fallback to manual documentation, and the operational metrics that surface network-outage events (per-room network-quality monitoring, per-encounter audio-gap detection).

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by raw-byte search against U+2014; zero matches in the file.
- **70/30 vendor balance maintained.** AWS service names appear first in the AWS Implementation section. The Problem, The Technology, and General Architecture Pattern are fully vendor-agnostic.
- **The opening Dr. Patel pajama-time vignette earns its position.** The "she has fourteen notes still to write" / "She will be in bed at 11:30. She will be back here at 7:30 tomorrow morning" cadence is the recipe's strongest single passage of "you're sitting at a kitchen table watching the documentation tax compound" voice.
- **The unrecognized-symptom-pattern vignette is the recipe's strongest single passage on the encounter-quality-suffers-from-documentation-pressure primitive.** "He does not pull the thread. The patient walks out with her refill and an unrecognized symptom pattern that one of his residents will recognize in the chart eight months later when she presents to the ED with an MI" is the recipe's clearest articulation of the typing-while-listening-creates-conditions-for-missed-signals primitive.
- **The four contextualization vignettes (primary-care, hospitalist, ophthalmology, encounter-quality-suffering) earn their position** as the recipe's articulation of the cross-specialty applicability of ambient documentation.
- **The Technology section's twelve-property enumeration is correct and recipe-distinct.**
- **The In-Room Audio Path subsection is the recipe's strongest single passage on the audio-pipeline-engineering primitive.**
- **The Multi-Speaker Diarization with Movement subsection is the recipe's strongest single passage on the diarization-with-movement-as-recipe-distinct primitive.**
- **The Clinical-Versus-Social Talk Classification subsection's "naive system that captures and structures everything" example is the recipe's clearest articulation of the social-content-pollution failure-mode.**
- **Self-deprecating expertise lands well.** "It is also the recipe where institutions most often ship a mediocre product because they treated the in-room audio path as solved when it was not, treated diarization as easy when it was the central engineering problem, treated faithfulness as a vague concern when it was the safety story" is the recipe's strongest single articulation of the recipe-as-deployment-quality-test primitive.
- **The "let's get into it" pivot from The Problem into The Technology is exactly the right "you're a colleague at the whiteboard" moment.**
- **The Honest Take's ten-trap enumeration is well-chosen.** The recipe-distinct tenth trap (room acoustics as IT problem) is the recipe's contribution to the chapter's voice register.
- **The closing "ambient clinical documentation, done well, gives clinicians their evenings back. It improves encounter quality because clinicians can look at patients more and screens less" line is the recipe's strongest single closing primitive and earns its position.**
- **The "the thing about" vendor-honest assessments are the right register.** HealthScribe-as-right-starting-point with the opinionatedness-tradeoff framing; Bedrock-as-genuinely-useful-for-institutional-template-rendering; Comprehend Medical-as-canonical-clinical-coding-worth-the-extra-service-call; behavioral-health-as-specialty-where-stakes-are-highest.
- **No documentation-voice creep.** The Why-These-Services subsection links each service back to its conceptual role.
- **Healthcare-domain accuracy is consistent.** The pajama-time framing is operationally authentic; the diarization-error-rate ranges are clinically plausible; the BIPA / Texas / Washington biometric-data-law references are accurate; the FHIR / RxNorm / ICD-10 / LOINC references are correct.
- **Parenthetical asides are present and serve the voice without overdoing it.**

### Finding V1: The "Ambient Clinical Documentation, Done Well, Gives Clinicians Their Evenings Back" Closing Earns Its Position

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's closing paragraph.

- **Note:** This is the recipe's central operational observation and earns its position as the recipe's closing voice moment. The "Invest in those, and the AI part takes care of itself" cadence frames the implementation imperative at exactly the right grain. Preserve through editing.

### Finding V2: The "the Thing That Surprises Engineers Coming From Telehealth Backgrounds" and "the Thing That Surprises Engineers Coming From Dictation Backgrounds" Cross-Recipe Comparisons Earn Their Position

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's cross-recipe-comparison paragraphs.

- **Note:** The cross-recipe-comparison framing ("Plan accordingly. The dictation playbook does not transfer.") is the recipe's strongest single articulation of the recipe-distinct-architectural-primitives observation and earns its position. The chapter editor should preserve this framing as it grounds the recipe's relationship to 10.4 and 10.6.

### Finding V3: The Per-Trap Diagnostic Pattern Across the Honest Take Earns Its Position

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's ten-trap enumeration.

- **Note:** Each trap is a real failure mode with a specific cause and a specific institutional remedy. The "first trap is underweighting the in-room audio path" / "second trap is underweighting diarization" / "third trap is treating faithfulness as a scoring metric" sequence frames the recipe's three central architectural primitives in priority order. The tenth trap (room acoustics as IT problem) is the recipe-distinct contribution. Preserve through editing.

### Finding V4: A Few Long Sentences in the Honest Take's Trap Discussions Could Be Tightened

- **Severity:** LOW
- **Expert:** Voice (sentence-length register)
- **Location:** Honest Take's "first trap" through "tenth trap" paragraphs.

- **Problem:** Most sentences are well-paced; a few in the longer trap discussions stretch across multiple subordinate clauses. Same observation as Recipes 10.1 through 10.6.

- **Fix:** Optional. Not required.


---

## Stage 2: Expert Discussion

The four expert lenses produce overlapping concerns at four intersections.

**Biometric voiceprint enrollment (Security S1) overlaps with the faithfulness check (Architecture A1) and per-cohort monitoring (Architecture A2).** The Security expert's concern about voiceprint-enrollment governance is operationally connected to the Architecture expert's elevation of diarization-quality (clinician voiceprint enrollment improves diarization, which improves the per-cohort metrics, which improves the faithfulness check input quality). The three findings reinforce each other: the BIPA-grade governance scaffolding is the substrate; the per-cohort monitoring is the operational instrumentation that surfaces the diarization-quality benefit; the faithfulness check consumes the diarization output.

**Faithfulness check architecture (Architecture A1) overlaps with prompt-injection mitigation (Security S3) and per-cohort monitoring (Architecture A2).** Same chapter pattern as 10.6 Stage 2. The three architectural primitives reinforce each other: prompt-injection mitigation operates at the input-side; the faithfulness check operates at the output-side; per-cohort faithfulness-failure-rate is the operational gate.

**Per-cohort monitoring (Architecture A2) overlaps with behavioral-health profile (Security S2) and audio retention policy (Architecture A8).** The behavioral-health profile is a per-specialty cohort with stricter thresholds; per-visit-type retention is a per-cohort-axis lifecycle policy. The recipe-distinct per-room and per-device cohort axes extend the chapter pattern to the in-person setting.

**In-room device-to-cloud audio path (Networking N1) overlaps with biometric voiceprint enrollment (Security S1) and the in-room audio-quality-band cohort (Architecture A2).** The per-device-pattern data-in-transit posture, the per-device authentication, and the per-device microphone-array beamforming all interact: a phone-or-tablet vendor app pattern has different audio quality and different authentication than a dedicated capture hardware pattern; the per-device cohort monitoring (per Finding A2) surfaces these differences operationally; the voiceprint-enrollment use of the device-captured audio for diarization (per Finding S1) inherits the per-device quality and authentication characteristics.

**No conflicts** between expert lenses requiring resolution. The Security expert's voiceprint-enrollment governance is consistent with the Architecture expert's diarization-quality elevation. The Networking expert's per-device-pattern data-in-transit posture is consistent with the Architecture expert's per-device-cohort monitoring. The Voice expert's positive observations on the recipe's "clinician-experience product" framing reinforce the Architecture expert's elevation of the per-clinician-opt-out and per-encounter-opt-out cross-cutting design point.

**Priority resolution.** The three HIGH findings are independent and additive. The Security S1 (biometric voiceprint enrollment under BIPA) addresses the recipe-distinct biometric-data regulatory gap that the recipe correctly identifies in prose but does not architect; this is the recipe's most distinctive HIGH finding and the strongest case for raising the architectural specification beyond the chapter pattern. The Architecture A1 (faithfulness check layered structure) addresses the chapter-pattern LLM-clinical-safety gap. The Architecture A2 (per-cohort monitoring with per-room and per-device extension) addresses the chapter-pattern equity gap with the recipe-distinct per-room contribution.

The MEDIUM findings cluster into the LLM-safety-substrate category (prompt-injection mitigation, foundation-model versioning, working-store extractions persistence at Step 5C, HealthScribe NoteTemplate enum), the deployment-and-resilience category (idempotency, multi-language architecture, audio retention with per-visit-type, disaster recovery, in-room device-to-cloud authentication), and the API-integration category (Lambda invocation authentication, audit-log retention floor, behavioral-health profile). The LOW findings are individually minor and collectively cosmetic.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

**Rationale:** 0 CRITICAL findings; 3 HIGH findings (at the > 3 = FAIL threshold but not exceeding it); 12 MEDIUM findings (most explicitly TODO'd in the recipe's prose with the chapter-pattern consolidation deferred to the editor); 7 LOW findings (cosmetic or minor). The three HIGH findings are localized correctness gaps that the recipe's own prose correctly diagnoses, with the recipe-distinct biometric-voiceprint-enrollment HIGH being the recipe's strongest contribution to the chapter's discipline.

Recipe 10.7 is Chapter 10's first complex-tier recipe and the chapter's first in-person ambient documentation recipe. Its successful execution at the complex-tier level extends the chapter's voice-AI register at exactly the level the chapter text promises. The recipe's central operational insight ("the difference between 'when it works' and 'when it does not' is mostly not the AI. It is the audio path, the consent design, the workflow integration, the faithfulness program, the per-cohort monitoring, and the clinician support program. Invest in those, and the AI part takes care of itself") is the chapter's strongest single articulation of the workflow-engineering-as-deciding-factor primitive in in-person ambient documentation context.

The recipe's deferral to recipe 2.8 for the LLM-driven note generation, faithfulness program, consent management, and EHR integration specifics is a defensible composition choice that avoids the chapter-pattern repetition problem. The recipe's distinct contributions (in-room audio path, multi-speaker diarization with movement, clinical-versus-social classification, device-in-the-room workflow integration, per-room cohort monitoring, biometric voiceprint enrollment) are recipe-distinct and correctly elevated.

### Prioritized Findings

| # | Severity | Expert | Location | Summary | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Step 1E `clinician_voiceprint_enrolled: check_voiceprint_enrollment(clinician_id)`, Step 2A `CLINICIAN_VOICEPRINT_REGISTRY[state.clinician_id]`, Cross-Cutting Design Points "Audio is PHI throughout, and biometric" | Biometric clinician voiceprint enrollment under BIPA, Texas, and Washington state law architecturally implicit; voiceprint registry is a passing reference without BIPA-grade governance scaffolding (consent capture, retention policy, deletion-on-departure, disclosure-accounting log, per-state regulatory profile); recipe-acute because in-person ambient is the prime use case and BIPA carries statutory damages of $1,000-$5,000 per violation | Promote clinician voiceprint enrollment from passing reference to architectural primitive: add "Clinician Voiceprint Enrollment and BIPA-Grade Governance" subsection specifying biometric-data consent at onboarding with written disclosure of purpose/collection/retention/deletion, voiceprint-storage-as-embedding with separate KMS key class and biometric-data-classification access controls, deletion-on-departure mandatory with deletion-verification logging, disclosure-accounting log per use, per-state regulatory profile (BIPA, CUBI, Washington); update Step 1E to capture consent_version, jurisdiction; update Step 7 audit_record to include voiceprint_used, voiceprint_consent_version, biometric_jurisdiction; add Production-Gaps "Clinician Voiceprint Biometric-Data Compliance" subsection naming privacy officer plus medical-staff-services as canonical owners |
| 2 | HIGH | Architecture | Step 4E `run_faithfulness_check(rendered_note, canonical_transcript, ehr_context)` opaque function call and architecture diagram's monolithic `BEDROCK_FAITH` component | Faithfulness check architecturally underspecified with no layer ordering, no per-layer disposition, no named ownership, and no specified relationship between runtime checks and offline sampling review; recipe explicitly elevates faithfulness as highest-stakes safety artifact in seven separate places | Promote faithfulness check from single function call to layered architecture stage with Layer 1 (citation grounding verification, structured-output schema validation, exam-finding-fabrication detection), Layer 2 (LLM-judge faithfulness scoring, clinical-rule-based contradiction detection), Layer 3 (offline sampling review with per-specialty / per-room / per-audio-quality-band sample stratification); per-layer disposition policy-driven with tighter thresholds for behavioral-health profile; per-cohort faithfulness-failure-rate as launch and operational gate; named ownership at clinical-quality officer |
| 3 | HIGH | Architecture | Step 7 audit record `cohort_axes: { language, visit_type, specialty, patient_age_band, audio_quality_band }` plus `room_id, device_type` dimensions and Cross-Cutting Design Points equity-monitoring paragraph | Per-cohort accuracy and adoption monitoring with audio-quality-band, per-room, and per-device stratification specified in audit record but launch-gate discipline architecturally implicit; per-room and per-device cohort axes are recipe-distinct contribution to chapter pattern | Promote per-cohort monitoring from prose to architectural primitive; specify single-axis cohorts (language, specialty, clinician, audio-quality-band, age-band, visit-type, room, device-type) and two-axis cohorts (language-by-audio-quality, room-by-time-of-day, device-by-specialty); specify per-cohort sample-size minimums, per-cohort threshold metrics including sustained-adoption rate, per-cohort thresholds defined per-axis, launch gate (every cohort must meet threshold), per-cohort drift detection; add audio-quality-band as per-encounter feature driving lower confidence threshold and audio-quality-warning surfaced in clinician review; add per-room remediation playbook (acoustic treatment, microphone repositioning, dedicated-capture-hardware deployment) |
| 4 | MEDIUM | Security | Cross-Cutting Design Points "Behavioral-health-specific handling" paragraph | 42 CFR Part 2 behavioral-health profile architecturally implicit despite explicit prose elevation and deferral to 2.8 / 10.6 | Add recipe-distinct "Behavioral-Health and 42 CFR Part 2 Profile in In-Person Setting" subsection specifying in-encounter pause-and-resume affordance with hard-pause vs soft-pause options, in-room bystander consent capture with explicit Part-2 disclosure where applicable, visit-type-flag-based exclusion enforcement at scheduling time with clinician-side override, per-room device configuration for behavioral-health rooms, per-state regulatory profile |
| 5 | MEDIUM | Security | Step 4D `bedrock.invoke_model(model_id: NOTE_RENDERING_MODEL, prompt: rendering_prompt, ...)` | Foundation-model prompt-injection risk for the LLM-driven note generation underspecified; patient/bystander verbatim speech and EHR-context templated directly into prompt | Add prompt-injection-mitigation paragraph with delimited-input framing for transcript and EHR context (`<transcript>...</transcript>`, `<ehr_context>...</ehr_context>`), strict structured-output validation, faithfulness check and Bedrock Guardrails as secondary and tertiary safety layers; add Production-Gaps paragraph on EHR-context retrieved-content supply-chain integrity |
| 6 | MEDIUM | Security | Prerequisites Encryption row | Audit-log retention floor specified generically without explicit pediatric, EHR-vendor, biometric-records, and 42-CFR-Part-2 floors | Name longest-of-(HIPAA-six-year, state-specific medical-records-retention including pediatric extending to age-of-majority-plus-X, EHR-vendor floor, 42 CFR Part 2 disclosure-accounting log retention for Part-2-eligible visits, institutional regulatory floor); note biometric-records (voiceprint disclosure-accounting log) follow separate retention regime per Finding S1 |
| 7 | MEDIUM | Security | Architecture diagram and IAM Permissions row | Lambda invocation authentication across API Gateway-to-Lambda and Step-Functions-to-Lambda integration underspecified | Resource-based policy on each Lambda pinning invoking principal to production API Gateway stage ARN, Step Functions state-machine ARN, or EventBridge rule ARN as appropriate; defense-in-depth event-payload validation against production constants |
| 8 | MEDIUM | Architecture | Step 5C `note_state_table.update(action: "store_structured_extractions", extractions: { ..., context_snippet: ... })` | Working-store structured-extraction context-snippets persisted in note-state DynamoDB table outside archive-reference discipline; recipe-localized chapter-pattern PHI-minimization gap (rest of working-store discipline largely correct) | Adopt archive-reference pattern at Step 5C: write structured extractions with context_snippets to draft-extractions archive in S3 with same KMS key class as note-draft archive; store only `extractions_archive_ref`, `extraction_count`, `confirmation_status`, per-category counts in note-state table |
| 9 | MEDIUM | Architecture | Step 3C pseudocode `clinical_note_generation_settings: { note_template: select_template(...) }` | HealthScribe `NoteTemplate` accepts fixed enum (HISTORY_AND_PHYSICAL, GIRPP, BIRP, SIRP, DAP, BH_SOAP, PH_SOAP) not custom institutional template IDs; pseudocode would fail with BadRequestException; mirrors code review W1 finding | Update Step 3C pseudocode to use closest-fit HealthScribe built-in enum (default HISTORY_AND_PHYSICAL); add sentence noting institutional formatting happens at Bedrock-rendering step (Step 4) |
| 10 | MEDIUM | Architecture | Step 6C `idempotency_key = build_idempotency_key(...)` | Idempotency for EHR write-back partially specified for note-write; per-confirmed-extraction idempotency key and FHIR conditional-create not specified | Specify per-confirmed-extraction idempotency key `(encounter_id, extraction_id, extraction_type)`; specify FHIR conditional-create where EHR vendor supports; specify duplicate-detection flow on idempotency-match returning prior document_id |
| 11 | MEDIUM | Architecture | Step 4F `note_state_table.put({..., model_version: ..., prompt_version: ...})` | Foundation-model and prompt and template versioning via inference profiles and aliases not architecturally specified despite version-stamping in audit record | Add Deployment Pattern subsection with versioned model/prompt/template/rule-catalog in version control, canary inference profile with traffic-shift, rollback-on-regression, held-out evaluation set with per-language/per-specialty/per-audio-quality-band/per-room-acoustics-band/faithfulness-edge-case/structured-extraction-edge-case/prompt-injection coverage |
| 12 | MEDIUM | Architecture | Variations "Multi-language support" item | Multi-language architecture build-for-day-one underspecified | Specify per-language pipeline pattern with per-language ASR configuration, note-generation prompt with native-speaker clinical-informatics input, template definitions, faithfulness rule catalogs, diarization tuning, structured-extraction approach where Comprehend Medical does not support the language |
| 13 | MEDIUM | Architecture | Prerequisites Encryption row | Audio retention policy configuration mechanism could be more concretely specified with per-visit-type and per-room differentiation | Specify retain-briefly with configurable per-visit-type and per-room retention window (default: 24-72 hours primary care, 24-48 hours behavioral-health, 24 hours 42-CFR-Part-2-eligible); per-visit-type and per-room retention enforced through S3 lifecycle policies on per-prefix definitions |
| 14 | MEDIUM | Architecture | Production-Gaps "Disaster recovery and degraded-mode operation" | Disaster recovery and partial-failure topology architecturally implicit | Add Disaster Recovery Topology subsection with per-stage failover policy (HealthScribe outage with cross-region fallback or degraded-mode-record-only; Bedrock unavailability with HealthScribe-default-template fallback or manual; Comprehend Medical unavailability with LLM-only structured-extraction; EHR API unreachable with durable note storage and retry; in-room device failure with per-room backup or manual); failover-detection-and-failover-back triggers; quarterly testing cadence |
| 15 | MEDIUM | Networking | Architecture diagram `DEVICE --> KVS` and Why-These-Services Chime SDK paragraph | In-room device-to-cloud audio path authentication and encryption underspecified across the three deployment patterns (phone/tablet vendor app, dedicated capture hardware, EHR-embedded with workstation microphone) | Add "In-Room Device-to-Cloud Audio Path" paragraph specifying per-device-pattern data-in-transit posture (TLS minimum, mTLS preferred for dedicated hardware, per-encounter session tokens scoped to visit); per-pattern BAA scope; platform-specific certification (HITRUST, SOC 2 Type II) for each pattern |
| 16 | LOW | Architecture | Step 6C `lookup_clinician_credentials(clinician_id)` | SMART on FHIR token lifecycle for multi-hour pipeline workflows not specified | Add SMART on FHIR Token Lifecycle paragraph with refresh-token flow, pre-emptive refresh window, refresh failure handling, audit on token-lifecycle events |
| 17 | LOW | Architecture | Prerequisites BAA row | Bedrock model HIPAA eligibility per specific model underspecified | Add default-model recommendation (Claude family typical for healthcare) with verify-at-build-time hedge; reference AWS HIPAA Eligible Services Reference URL |
| 18 | LOW | Security | Step 7 `cloudwatch.put_metric` calls | Cohort encoding in CloudWatch metric dimensions discipline not specified for sensitive demographic dimensions | Specify cohort-axis-hash labels for sensitive dimensions if added; current dimensions (language, specialty, visit_type, audio_quality_band) acceptable as direct identifiers |
| 19 | LOW | Security | Prerequisites Encryption row | Audio retention deletion verification specified but not architecturally audited | Add paragraph specifying audio retention deletion verified by periodic audit job that lists audio bucket contents older than retention window; deletion-verification events logged to CloudTrail and surfaced in audit-archive analytics |
| 20 | LOW | Networking | Architecture diagram `LIVE_DISPLAY` | WebSocket-based real-time live-display authentication, connection limits, idle timeouts, frame format architecturally implicit | Add WebSocket Live-Display Streaming paragraph specifying Lambda authorizer with Cognito token, connection-limit considerations, extended idle-timeout for in-encounter pauses, message-type frame format |
| 21 | LOW | Networking | Prerequisites VPC row | PrivateLink egress hierarchy specified but not recipe-specifically elevated for EHR FHIR surface | Specify egress hierarchy: PrivateLink (preferred) > Direct Connect / VPN to on-premise > public-Internet-with-TLS |
| 22 | LOW | Networking | In-Room Audio Path subsection | Per-room network resilience and local-buffer behavior architecturally implicit | Add paragraph specifying per-device local-buffer behavior, network-outage threshold for fallback to manual documentation, per-room network-quality monitoring and per-encounter audio-gap detection |
| 23 | LOW | Voice | Honest Take long-trap paragraphs | A few long sentences in the Honest Take's longer trap discussions could be tightened | Optional; current voice consistent with CC's accumulation pattern |

### Closing Notes

Recipe 10.7 is publishable at the complex-tier level once the three HIGH findings are closed. The Honest Take is the recipe's strongest single passage and frames in-person ambient documentation as a clinical-experience product where the difference between "when it works" and "when it does not" is mostly not the AI but the audio path, the consent design, the workflow integration, the faithfulness program, the per-cohort monitoring, and the clinician support program. This framing matches the chapter pattern from 10.4, 10.5, and 10.6 while elevating the recipe-distinct in-room-audio-path and per-room-cohort-monitoring contributions.

The recipe's deferral to recipe 2.8 for the LLM-driven note generation and EHR integration specifics is a defensible composition choice. The recipe's distinct contributions (in-room audio path, multi-speaker diarization with movement, clinical-versus-social classification, device-in-the-room workflow integration, per-room cohort monitoring, biometric voiceprint enrollment) are recipe-distinct and correctly elevated. The HealthScribe-as-primary-managed-service framing is operationally accurate; the institution-builds-on-Transcribe-Medical alternative for institutions wanting more control is the right alternative.

The chapter-wide consolidation work (working-store-PHI-minimization chapter preface, LLM-clinical-safety-substrate chapter preface, foundation-model-versioning chapter preface, multi-language chapter preface, disaster-recovery chapter preface, SMART on FHIR token lifecycle chapter preface, audit-log retention floor chapter preface, cohort-stratified accuracy monitoring chapter preface) is deferred to the chapter editor for the next pass.

The recipe-specific contributions that should be elevated to the chapter preface as load-bearing primitives are: (a) the **biometric-voiceprint-enrollment-under-BIPA-grade-governance primitive** (recipe-distinct, load-bearing for any in-person ambient or any recipe that captures biometric identifiers); (b) the **per-room and per-device cohort monitoring primitive** (recipe-distinct, load-bearing for any in-person voice recipe where room acoustics and device hardware vary); (c) the **clinical-versus-social-talk classification primitive** (recipe-distinct, load-bearing for any conversational ASR recipe where the conversation contains note-irrelevant content); (d) the **in-room audio path engineering primitive** (recipe-distinct, load-bearing for any recipe with in-room capture); (e) the **device-in-the-room workflow integration primitive** (recipe-distinct, load-bearing for any recipe deploying dedicated hardware in clinical spaces).
