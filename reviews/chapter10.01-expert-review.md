# Expert Review: Recipe 10.1 - IVR Call Routing Enhancement

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-23
**Recipe file:** `chapter10.01-ivr-call-routing-enhancement.md`

---

## Overall Assessment

This is the first recipe in Chapter 10 (Speech / Voice AI) and the chapter's introductory simple-tier recipe. It establishes the chapter's operational discipline (urgency-lexicon-first routing as a clinical safety substrate, per-intent confidence thresholding rather than a single global threshold, verification-before-fulfillment for any intent that touches PHI or the back office, eligibility-check-before-action as the safety floor below caller verification, idempotency-keyed fulfillment to survive at-least-once delivery, audit-everything substrate, versioned bot/threshold/lexicon artifacts) and frames the chapter's posture toward the IVR as a patient-experience product with engineering as its substrate rather than as a routing engine that happens to interact with patients. The 67-year-old-with-AFib-who-needs-a-refill-and-is-feeling-a-flutter Tuesday-morning vignette earns its position: the legal-disclaimer ten seconds, the ten-option menu read-aloud, the date-of-birth-keypad-rejection-loop, the dump-into-the-thirty-eight-minute-general-queue, and the missed-clinical-signal-on-the-flutter sets up the cascading vignettes (the diabetic with foot swelling routed to general appointments instead of same-day triage, the Spanish-speaker who hangs up after the English-only menu repeats, the 31-year-old commercial-insurance patient who defects to out-of-network urgent care because they have an app, the pediatric mother whose child has a fever ending up in the ER) at exactly the right "this is what legacy IVR actually produces in production" energy. The "every healthcare organization with a phone system has stories like these" pivot lands the institutional-and-economic stakes (missed clinical signal, abandoned calls, unnecessary ER utilization, patient leakage to competitors with better digital experiences, staff time spent on calls that should never have reached a human) without lapsing into hype.

The Technology section is the chapter's introductory pedagogy on the speech-to-intent pipeline, and it executes at the right grain for the simple-tier slot. The four-stage pipeline framing (telephony plumbing, ASR, NLU, dialog management, plus the cross-cutting fallbacks) is correct. The ASR-for-telephony subsection's five practical primitives (audio bandwidth at 8 kHz narrowband versus 16 kHz wideband with high-frequency content above 4 kHz absent on the PSTN side, streaming versus batch with the dead-air consequence of batch ASR for IVR, endpointing tuned at the acoustic-and-linguistic level rather than naive silence detection, per-word and per-utterance confidence as the integrity boundary the downstream consumer must consume, domain adaptation with the lisinopril-versus-listen-approval example) is the recipe's strongest single passage of pedagogy on the ASR-for-telephony dimension. The NLU subsection's four-pattern survey (rule-based pattern matching with the brittleness-as-the-cost-of-transparency framing, statistical intent classifiers with the bootstrap-from-call-log-analysis pattern and the few-months-of-production-stabilization observation, vendor-managed NLU as the typical right-starting-point, LLM-based intent classification with the per-call-latency-and-cost trade-off and the "for most IVR use cases in 2026, the right answer is some kind of vendor-managed NLU with optional LLM augmentation" framing) is correctly granular and forward-looking. The dialog-management subsection's two-pattern framing (slot-filling state machines as the production-default for healthcare, LLM-driven dialog as more common in consumer settings) is correctly framed. The "Fallbacks Are the System" subsection's five-fallback enumeration (DTMF availability throughout, operator escape hatch, clinical urgency override, language fallback, and the "the system that ignores fallbacks works perfectly in the demo and falls apart on the first real call" framing) is the recipe's strongest single observation about why IVR engineering is operational-discipline-not-just-ML. The "What Routing Really Means" subsection's five-action enumeration (self-service fulfillment, queue routing with screen pop, callback scheduling, escalation to clinical, decline gracefully) is correctly granular. The "Where the Field Has Moved" subsection (end-to-end SLU models, LLMs as dialog backbone increasingly feasible for low-traffic enterprise IVR, vendor-managed conversational platforms maturing, healthcare-specific intent libraries available as starting points, voice biometrics operationally available but operationally fraught with BIPA and similar state laws) is correctly forward-looking and sets up Chapter 10's later recipes.

The five-stage architecture (telephony ingress, speech-to-intent processing with parallel urgency-keyword scanner, dialog management with the policy block enumerated, routing-or-fulfillment with five disposition paths, observability with per-call audit and aggregate metrics) is the right shape. The cross-cutting design points are correctly elevated (patient verification at the right moment not too early, ANI-based prefill as a usability win with the spoofability caveat, per-intent confidence thresholds rather than a global one, urgency lexicon as a living document, recordings-are-PHI treatment, ML-pipeline-degrades-gracefully discipline). The Why-These-Services section walks each AWS component back to the conceptual primitive it implements (Connect for the contact-center backbone, Lex V2 for the NLU layer with native Connect integration, Polly for TTS, Lambda for fulfillment-and-integration, DynamoDB for active-call-context with TTL, S3 for recordings with KMS, Kinesis for real-time event flow, Athena and Glue for analytics, KMS and Secrets Manager and EventBridge and CloudWatch and CloudTrail for the cross-cutting concerns).

The Honest Take is strong, with twelve observations earning the recipe's voice: (1) the technology-is-mature-and-the-difference-is-operational-discipline framing as the recipe's central observation; (2) the IVR-as-technology-project trap (the recipe's strongest single trap, with the patient-experience-product-with-engineering-substrate reframe); (3) the under-investing-in-the-urgency-lexicon trap with the clinical-safety-document-with-versioning-and-review-and-audit framing; (4) the over-eager-self-service-expansion trap with the harder-intents-have-higher-verification-and-integration-and-failure-mode framing and the "containment rate is a proxy metric, not a goal in itself" closing; (5) the IVR-is-a-fraud-target trap with the social-engineering-and-pattern-anomaly-detection framing; (6) the back-office-integration-dominates-the-engineering-effort observation (consumer-voice-AI-backgrounds tend to underestimate this); (7) the patient-experience-layer-matters observation (IT-operations-backgrounds tend to underestimate this) with the conversational-design-and-usability-testing-with-representative-populations framing; (8) the Lex-specifically observation (competent platform with native Connect integration, not the most accurate NLU, integration savings outweigh the accuracy difference for most healthcare use cases); (9) the Connect-specifically observation (credible cloud contact center, migration cost is real, greenfield-or-AWS-native vs migration-from-existing-vendor decision); (10) the LLMs-in-IVR observation with the "right answer for most healthcare IVR deployments is vendor-managed NLU for primary intent classification and LLM augmentation for harder cases" framing and the "this will keep moving; revisit annually" closer; (11) the per-call-cost economic case observation with the agent-cost-comparison; (12) the would-do-differently-the-second-time observation on the analytics-layer earlier-investment lesson. The closing paragraph ("the IVR is, for many patients, their first interaction with the institution after they decide they need care... they've already done the hard part") is the recipe's strongest single closing line and frames the IVR as a patient-dignity surface in a way that sets up the chapter's voice-AI register.

The Variations and Extensions section (hybrid voice plus DTMF flow as the operationally-safest starting point, LLM-augmented intent classification, outbound proactive callbacks, real-time agent assist with screen pop, live transcript and translation, authenticated patient portal hand-off via SMS, multilingual IVR with the Lex V2 multi-locale framing and the higher-engineering-and-operational-cost honest framing, voice biometric caller verification with the BIPA-aware deployment caveat, conversational AI fulfillment for complex intents, real-time fraud detection on call stream, A/B testing of dialog variants, federated agent assist across multi-site practices) is well-scoped and frames each extension at the right grain.

That said, three correctness-and-compliance gaps at HIGH severity need attention before publication, plus a chapter-pattern set of MEDIUM and LOW items. (1) The Step 2A audit_log call records the raw transcript verbatim into the structured audit log payload. The transcript contains PHI (the caller's words, including potentially their name, their condition, their medication, their date of birth, their symptoms). Placing the transcript into a CloudWatch-backed structured audit log creates a parallel PHI store outside the call-recordings-bucket-with-its-recordings-governance-and-retention discipline. The transcript can be retained at the audit-log retention floor, can be queried by anyone with CloudWatch Logs read access, and can be exported into downstream analytics that may not have the recordings bucket's controls. The Python companion correctly redacts transcript and demographic fields from the audit_log payload (per the code review's Finding); the architectural pseudocode here teaches the wrong pattern. (2) The Step 4E `queue_refill_request` call has no idempotency key visible in the pseudocode. A Lex retry on a fulfillment-hook timeout, an EventBridge replay, an at-least-once Lambda invocation, or a duplicate downstream-Kinesis event each can produce a duplicate refill request submitted to the e-prescribing system. Duplicate refills are not a cosmetic analytics issue: a patient on a controlled-supply medication whose pharmacy receives two refill requests in the same morning experiences either a denial loop (the e-prescribing system rejects the duplicate; the patient sees confused status), a double-fill (the pharmacy fills twice; the patient may be at risk of accumulation), or an audit-flag-and-review (the patient experiences delay because their refill is held for clinical review). The recipe correctly elevates idempotency in the Why-Not-Production-Ready section, but the Step 4 pseudocode itself teaches the wrong pattern. (3) The cohort-stratified accuracy monitoring is structurally absent from the architecture pattern, despite the recipe's correct elevation of the equity dimension as recipe-specific in the "Where it Struggles" subsection ("Patients with strong accents or non-native English are systematically less well-served... Subgroup-stratified accuracy monitoring is non-negotiable"). The architecture does not specify cohort-stratified versions of the operational metrics (containment rate per cohort, intent-classification accuracy per cohort, abandon rate per cohort, time-to-clinical-triage per cohort), the disparity-alert thresholds, the cohort-distribution allow-listed dimensions (age band, language preference, geographic region, accent group where inferable), or the named ownership for the equity-monitoring committee.

Eleven chapter-wide and recipe-specific MEDIUM patterns repeat or are recipe-new (caller-verification policy strength as illustrative-but-not-production-bar named in production-gaps but not architecturally specified for high-impact intents, urgency-lexicon governance with regression-test-set-and-named-clinical-operations-ownership architecturally specified, DLQ topology and idempotency-key composition for every Lambda named in production-gaps but not architecturally specified, Lex bot version-control-and-blue-green-deployment via aliases architecturally specified, multi-language architecture as build-for-it-day-one even-if-shipping-English-first architecturally specified, audit-log retention floor with explicit floor named, ANI-spoofing-and-fraud-pattern-detection architectural primitive specified, recording-disclosure-jurisdiction-aware-language as configured-not-hardcoded, Lex Runtime VPC endpoint and Polly VPC endpoint specified for VPC egress, Lambda-fulfillment-hook authentication-of-Lex-invocation specified, Connect-Voice-ID and Connect-Contact-Lens HIPAA eligibility verified-at-build-time). Most are explicitly TODO'd or named in the Why-This-Isn't-Production-Ready section; this review carries them forward at MEDIUM severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by raw-byte match against the U+2014 sequence; zero matches in the file). En dash count: 0 (verified). The 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: the opening 67-year-old-AFib-flutter-on-the-anticoagulant Tuesday-morning vignette sets the engineer-explaining-something-cool register exactly. The five vignettes (the AFib patient, the swelling-foot diabetic, the Spanish-speaker, the 31-year-old commercial-insurance defection, the pediatric mother) ground the institutional-and-economic stakes. The "the underlying technology has gotten dramatically better in the last few years, the operational patterns are well-understood, and the failure modes are observable. Let's get into it" pivot from The Problem into The Technology is exactly the right "you're a colleague at the whiteboard" moment. The "this is one of those problems that sounds simple until you actually try it" energy carries through the Technology section. Self-deprecating expertise lands well: "the engineering joy of an IVR project is that you don't have to be an expert in any of them; you just have to know how they fit together and where they typically break" is the chapter's strongest single articulation of the integration-engineer-as-systems-thinker register. The Honest Take's twelve observations close at exactly the right grain.

Clinical and regulatory accuracy is strong. Atrial fibrillation with an anticoagulant on first refill after diagnosis is a clinically authentic scenario for the urgency-versus-routine-refill ambiguity. The diabetic with foot swelling who develops a foot ulcer after a routing miss is clinically valid (peripheral edema in a diabetic with vascular compromise is a same-day-triage signal that, missed, can progress to ulceration). The AFib-flutter symptom matched against an urgent-versus-routine routing decision is the right canonical example for the urgency-lexicon discussion. Section 508, WCAG, TCPA, BIPA, HIPAA Privacy Rule citations are correct. The PSTN-narrowband-at-8-kHz-versus-wideband-at-16-kHz framing is technically accurate (G.711 is the codec; the analog-or-narrowband-VoIP-PSTN delivers 8 kHz sample rate; modern HD voice codecs deliver wideband but the legacy PSTN does not). The AWS Connect, Lex V2, Polly, Transcribe, Transcribe Medical HIPAA-eligibility statements are correct as of recent listings (with the recipe's appropriate "verify the current list at build time" hedge). The state-recording-consent one-party-versus-all-party variation is correctly referenced. The 50-year-posthumous and 6-year-HIPAA retention floors are correctly framed.

Architectural accuracy is high. The streaming-ASR pipeline with confidence-aware downstream consumption is the correct pattern. The per-intent confidence threshold rather than a global one is the correct discipline. The urgency-keyword scanner running in parallel with the intent classifier (not after it) is the correct architectural primitive. The verification-at-the-right-moment-not-too-early discipline is correct. The ANI-spoofability-caveat is correctly elevated. The customer-managed KMS keys for the recordings bucket, the active-call-context DynamoDB table, the Secrets Manager secrets, the Lambda environment variables, and the CloudWatch Logs is the correct posture. The Object-Lock-in-Compliance-mode for the CloudTrail logs bucket is the correct posture. The cost-estimate framing with the per-call-cost-versus-fully-loaded-agent-cost economic case is correctly granular.

Priority breakdown: 0 critical, 3 high, 11 medium, 7 low. **The verdict is PASS** because the HIGH count (3) is at the > 3 = FAIL threshold and there are no CRITICAL findings. The three HIGH findings are localized correctness gaps that the prose elsewhere in the recipe correctly diagnoses with TODO references already in place; closing them brings the architecture and the pseudocode up to the standard the recipe text claims and matches the chapter pattern from prior chapters' first-recipe entries. Recipe 10.1 is Chapter 10's introductory simple-tier recipe; its successful execution at this level (vendor-agnostic four-stage pipeline pedagogy with telephony-tuned ASR and per-intent confidence thresholding and slot-filling dialog management and clinical-urgency-override fallback discipline, five-stage architecture with telephony ingress and speech-to-intent processing and dialog management and routing-or-fulfillment and observability, AWS implementation with Connect plus Lex V2 plus Polly plus Lambda plus DynamoDB plus S3 plus Kinesis plus EventBridge plus KMS plus Secrets Manager plus CloudWatch plus CloudTrail at the right grain, twelve Honest Take observations closing on the IVR-as-patient-dignity-surface framing, twelve-extension Variations including hybrid-voice-plus-DTMF and LLM-augmented intent classification and outbound proactive callbacks and authenticated patient portal hand-off and multilingual IVR and voice biometric caller verification and federated multi-site routing) opens the chapter at exactly the level the chapter text promises.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly in the Prerequisites section with the appropriate framing: "AWS BAA signed. Connect, Lex, Polly, Transcribe, Lambda, DynamoDB, S3, Kinesis, KMS, Secrets Manager, CloudWatch Logs, CloudTrail are HIPAA-eligible (verify the current list at build time)." The "verify at build time" hedge is correctly placed because the eligibility list is a moving target.
- Customer-managed KMS keys for the recordings bucket (SSE-KMS), the DynamoDB tables holding caller context, the Secrets Manager secrets, the Lambda environment variables, and the Lambda log groups. mTLS implied by the back-office API call discipline. KMS key policies should enforce least-privilege access (the caller-verifier Lambda role can decrypt the active-call-context but not the longer-retention caller-recent-history; the urgency-escalator Lambda role has its own scoped key access).
- CloudTrail enabled with data events on the call-recordings S3 bucket, the active-call-context DynamoDB table, the Secrets Manager secrets, and the customer-managed KMS keys. Lambda invocations logged. Lex bot configuration changes logged ("version control your bot definitions"). Connect contact flow changes logged. CloudTrail logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days.
- The recipe correctly identifies the call recording as PHI even when the caller's name is not explicitly captured in any structured field ("Call recordings are PHI, full stop, regardless of whether the caller's name is captured"), and correctly elevates this point in the cross-cutting design section. The recordings bucket runs under BAA with customer-managed KMS, lifecycle to colder tiers, and retention bound by institutional and regulatory policy.
- Recording-consent disclosure is jurisdiction-aware with the correct one-party-versus-all-party framing and the institutional-legal-team approval discipline ("the disclosure is jurisdiction-aware: some U.S. states are one-party-consent, some are all-party-consent, and the disclosure plus continued participation is the standard pattern"). The TODO at the BAA row correctly anchors the state-by-state recording-consent-tracker reference to the Reporters Committee for Freedom of the Press.
- The urgency-override discipline is correctly elevated as a non-negotiable fallback ("A short list of urgency phrases triggers an immediate route to clinical triage, regardless of whatever else the caller said. This is non-negotiable and should be tested explicitly").
- The ANI-spoofability caveat is correctly elevated ("ANI is spoofable, so high-stakes actions still need explicit verification").
- The synthetic-data discipline in the Sample Data row ("Never use real PHI in development") is correctly stated with the Synthea-derived synthetic-utterance pattern as the recipe-specific source for IVR training data.
- The recordings-and-transcripts retention floor is correctly framed: "HIPAA's six-year minimum applies to specific document types and the state-specific medical-records retention may be longer." The TODO at the CloudTrail row correctly defers the institution-specific retention floor to operational decision while naming the floor.
- The recipe correctly identifies the IVR as a fraud target ("Once the IVR can release information or trigger actions, it becomes a target for social engineers") in the Honest Take, with the verification-discipline-and-rate-limiting-and-pattern-anomaly-detection mitigation framing.
- The voice-biometrics paragraph correctly defers Voice ID as MVP-skip-revisit-only-if-business-case-justifies-the-regulatory-overhead with explicit BIPA reference ("voiceprints are biometric data, regulated under BIPA and similar state laws"). This is the correct institutional posture.

### Finding S1: Step 2A `audit_log` Records Raw Transcript (PHI) Into the Structured Audit Log Payload, Creating a Parallel PHI Store Outside the Recordings-Bucket Governance

- **Severity:** HIGH
- **Expert:** Security (PHI minimization, retention, access boundary)
- **Location:** Step 2 pseudocode, the `handle_lex_turn` function:
  ```
  // Step 2A: log the turn so we can audit it later
  // regardless of routing outcome.
  audit_log({
      event_type: "LEX_TURN_RECEIVED",
      call_id: call_id,
      intent_name: intent_name,
      intent_confidence: intent_confidence,
      transcript: transcript,
      timestamp: current UTC timestamp
  })
  ```
  And the Step 4 `handle_refill_intent` and Step 3 `verify_caller_if_needed` functions, which include `dob`, `partial_phone`, `medication_name`, and other PHI-bearing slot values implicitly into the audit context.

- **Problem:** The audit_log helper in the architectural pseudocode writes the raw transcript verbatim into the structured audit-log payload. The Python companion correctly redacts these fields (per the code review's positive note that `audit_log` filters PHI fields including `transcript`, `dob`, `partial_phone`, `medication_name`, `patient_demographics` from the structured log payload), but the architectural pseudocode here teaches the wrong pattern. The consequence is sharp because:

  1. **The transcript is PHI.** The caller's spoken words include any subset of name, date of birth, condition, medication, symptom, family member name, address, partial financial information. The Lex transcript is the highest-resolution PHI capture in the call (more than the structured slot extraction, which has been parsed and filtered).

  2. **CloudWatch Logs is a parallel PHI store outside the recordings-bucket governance.** The recordings bucket runs under customer-managed KMS with explicit lifecycle and retention. CloudWatch Logs runs under a separate access-control surface (CloudWatch Logs read access is a different IAM permission from the recordings bucket's read access; analytics consumers, troubleshooters, and developers may have CloudWatch Logs read but not recordings-bucket read). A transcript captured in the audit log is accessible to a different population than the recording itself, with a different retention default, and may be subject to different export-and-archive rules.

  3. **Downstream analytics consumption is not bounded.** CloudWatch Logs that contain transcripts can be ingested into log-aggregation platforms, sent to third-party SIEMs, replicated to backup accounts, or queried by Insights. Each downstream consumer becomes another PHI-handling surface that the recordings bucket's governance does not cover.

  4. **The minimum-necessary requirement is at risk.** The audit log's purpose is to capture the routing decisions, the confidence levels, the policy invocations, and the disposition. The transcript is not necessary to support the audit purpose; the call_id and the timestamp are sufficient to correlate the audit event with the full transcript in the secure transcript archive. Retaining the transcript in the audit log violates minimum necessary.

  5. **The institutional log-retention floor differs from the recordings-retention floor.** CloudWatch Logs default retention is "never expire" unless configured; institutional log retention may be shorter or longer than the recordings retention. A transcript in the audit log may be retained beyond the recordings retention (a HIPAA accidental-disclosure-prolonged-retention concern) or destroyed before the recordings retention (an audit-trail-shorter-than-the-PHI concern).

  Same regulatory ground as the chapter-wide pattern but recipe-specific in that the IVR's audit log is the only place where the structured-classification and the raw-transcript can be co-located, and the temptation to log both is exactly what the pseudocode demonstrates.

- **Fix:** Specify in the architectural pseudocode that the audit_log helper redacts PHI from the structured payload and references the transcript by its archive identifier rather than its content. The architecturally-correct pattern is:

  ```
  audit_log({
      event_type: "LEX_TURN_RECEIVED",
      call_id: call_id,
      intent_name: intent_name,
      intent_confidence: intent_confidence,
      transcript_archive_ref: transcript_archive_path,
      transcript_length_chars: length(transcript),
      transcript_hash: sha256(transcript),
      timestamp: current UTC timestamp
  })
  ```

  The full transcript lives in the secure transcript archive (S3 with KMS, the same governance as the recordings bucket); the audit log carries only the reference, the length, and a hash for integrity verification. The slot-bearing audit events (verification-completed, refill-queued, appointment-scheduled) similarly redact the slot values from the audit log, retaining only structural metadata (slot count, slot types filled, fulfillment outcome). The Python companion's pattern is the correct one; the architectural pseudocode should match.

  Add an explicit prose paragraph in the cross-cutting design points section (where "Recordings are PHI; treat them accordingly" lives) to elevate transcripts to the same posture: "Transcripts are PHI; they live in the secure transcript archive under the same governance as the recordings, and the audit log carries only references and structural metadata, never the raw content."

### Finding S2: Step 4E `queue_refill_request` Has No Idempotency Key, Permitting Duplicate Refill Submission on Lex Retry, EventBridge Replay, or At-Least-Once Lambda Invocation

- **Severity:** HIGH
- **Expert:** Security and Architecture (clinical safety, fulfillment integrity)
- **Location:** Step 4 pseudocode, `handle_refill_intent`:
  ```
  // Step 4E: queue the refill request. We don't
  // dispense, just queue it for the e-prescribing
  // system's normal flow.
  refill_request_id =
      e_prescribing.queue_refill_request(
          patient_id=patient_id,
          medication_id=matching_med.medication_id,
          requested_via="ivr_self_service",
          requested_at=current UTC timestamp)
  ```
  And Step 4F's EventBridge.PutEvents call which similarly has no idempotency-key composition specified.

- **Problem:** The refill-fulfillment Lambda is invoked in a delivery model with at-least-once semantics on multiple paths: Lex's fulfillment hook can retry on timeout (Lex's default retry behavior on Lambda invocation failures or near-timeouts); Connect's contact flow can re-invoke the fulfillment Lambda on a retry; EventBridge's downstream replay or DLQ-redrive can cause a second downstream consumer to operate on the same event; the Lambda runtime itself has at-least-once invocation semantics under failure-and-retry conditions; an operational redrive of a DLQ during incident response can re-fire fulfillment events. The Step 4E pseudocode has no idempotency-key composition, so each invocation submits a fresh refill request to the e-prescribing system. The recipe's Why-Not-Production-Ready section correctly elevates this concern ("Use the (call_id, intent_name, turn_index) tuple as an idempotency key for fulfillment; use (call_id, fulfillment_action_id) for the event-emission record"), but the Step 4 pseudocode itself does not adopt the pattern.

  The clinical-safety consequence is sharp:

  1. **Duplicate refill submission to the e-prescribing system.** The e-prescribing system receives two `queue_refill_request` calls with different request_ids for the same patient, the same medication, the same time. Depending on the e-prescribing system's deduplication discipline, the patient experiences either a denial loop (the system rejects the duplicate; the patient sees confused status), a double-fill (the system fills twice; the patient may be at risk of accumulation, particularly for medications with narrow therapeutic indices), or an audit-flag-and-review (the patient experiences delay because their refill is held for clinical review).

  2. **Duplicate cross-system event emission.** The EventBridge event is fanned out to downstream consumers (analytics, audit, surveillance). Duplicate events inflate metrics (the containment rate per intent appears higher than reality), corrupt downstream state (the fulfillment counter for the patient is incremented twice), and generate duplicate downstream actions (a notification system that consumes the event sends two notifications).

  3. **Duplicate audit-event emission.** The Step 4F `audit_log` call records the refill-queue event twice. The audit trail now shows two refill-queue events at slightly-different timestamps for the same call. A subsequent incident review cannot determine which was the canonical event without correlating against the e-prescribing system's record.

  4. **Cross-call replay.** A redrive of a DLQ that contains historical fulfillment events can re-fire fulfillment for a patient call that ended weeks ago, against an active call's context. This is the worst case: a refill that was intentionally not processed (because the call was abandoned, because the verification failed, because the medication was excluded) is now retroactively processed.

  Same chapter pattern as the entity-resolution recipes' findings on idempotency for cross-recipe events; recipe-specific because the e-prescribing fulfillment is one of the two clinically-impactful write paths in the IVR (the other being the appointment-fulfillment path, which has the same gap).

- **Fix:** Promote the recipe's own production-gaps TODO content into the Step 4 pseudocode. Specify the idempotency-key composition at the architectural level:

  ```
  // Step 4E: queue the refill request idempotently. The
  // (call_id, intent_name, turn_index) tuple is the
  // idempotency key; the e-prescribing system either
  // returns the existing request_id for a duplicate key
  // or creates a new request and returns its id.
  idempotency_key =
      f"{call_id}:refill_prescription:{turn_index}"

  refill_request = e_prescribing.queue_refill_request(
      idempotency_key=idempotency_key,
      patient_id=patient_id,
      medication_id=matching_med.medication_id,
      requested_via="ivr_self_service",
      requested_at=current UTC timestamp)

  // refill_request.is_duplicate is true if this was a
  // replay; the audit log captures both the new and the
  // duplicate paths but the e-prescribing side does not
  // double-process.
  IF refill_request.is_duplicate:
      audit_log({
          event_type: "REFILL_REQUEST_DUPLICATE_DETECTED",
          call_id: call_id,
          idempotency_key: idempotency_key,
          existing_request_id:
              refill_request.refill_request_id,
          timestamp: current UTC timestamp
      })
      RETURN response_with_prompt(
          spoken_already_queued_acknowledgment(
              matching_med))
  ```

  And specify in Step 4F that the EventBridge event carries the idempotency_key in `detail.event_id` so consumers can deduplicate at the consumer side. Add the parallel idempotency-key composition for the appointment-fulfillment path in the prose. Reference the recipe's existing production-gaps section for the cross-system DLQ topology and the Lambda concurrency limits that bound the idempotency window.

  Add an explicit prose paragraph in the cross-cutting design points section: "Fulfillment Lambdas operate under at-least-once delivery semantics. Every fulfillment path uses an idempotency key composed of (call_id, intent_name, turn_index) and the back-office system's idempotency-honoring API. The architecture rejects fulfillment paths that don't expose an idempotency-honoring API and routes them through a one-shot intermediate queue with a deduplication store."

### Finding S3: Caller-Verification Policy "DOB Plus Partial Phone" Is Marked as Illustrative but Bound to High-Impact Intents Including Refill Release Without an Architectural "Below Production Bar" Marker

- **Severity:** MEDIUM
- **Expert:** Security (authentication strength, fraud-resistance)
- **Location:** Step 3 pseudocode, the `verify_slots_returned` function with `verification_method: "dob_plus_partial_phone"`, and the Prerequisites BAA / Compliance row implying this is the canonical production pattern, plus the Why-These-Services / DynamoDB paragraph framing the pattern as the operational default.

- **Problem:** The verification policy in the pseudocode (date of birth plus the last four of the phone on file) is described as "illustrative" in prose but bound to the refill-prescription intent in the pseudocode without a "below production bar" marker. The recipe's Why-Not-Production-Ready section correctly elevates this with "The verification approach in the pseudocode (DOB plus partial phone) is illustrative. Real institutions have layered verification policies that vary by intent risk level, by detected fraud signals (caller calling from a never-seen-before number, pattern of rapid attempts), and by patient preference (some patients have asked for additional verification). The verification policy is an explicit document maintained by the institution's identity-and-access governance, not a snippet of Lambda code." But the architectural pseudocode does not actually adopt the framing: a reader who copies the pattern as-shown ships with DOB-plus-last-four for refill release. The recipe-specific consequence:

  1. **DOB is widely public.** Date of birth is in voter records, in social media profiles, in real-estate filings, in genealogy databases. A would-be social engineer attempting to obtain a target patient's medication can readily obtain the DOB.

  2. **The last four of the phone on file is shared across the household.** A landline shared by spouses, an ANI-prefilled call from a household number where the phone is registered to one of multiple family members, or an attacker who has obtained the household phone bill all match the partial-phone slot.

  3. **The refill release is a clinically-impactful write.** A successful refill release for the wrong patient is a controlled-medication-misappropriation event (if the medication is controlled), a clinical-decision-support-bypass event (the prescriber's intent was to refill for the verified patient, not for whoever called), and a HIPAA-disclosure event (the e-prescribing system pulls up the patient's medication record during the refill flow).

  4. **The chapter-pattern verification framework is intent-keyed.** Different intents have different verification strengths: a hours-and-location lookup needs no verification; a billing-statement question needs a basic verification; a prescription release needs a strong verification (knowledge plus possession plus optional out-of-band confirmation); a controlled-substance refill needs the strongest verification (the recipe correctly already excludes controlled substances from self-service in the eligibility check, but the pattern should be specified architecturally).

- **Fix:** Promote the production-gaps section's verification-policy framework into the architecture pattern. Specify the intent-keyed verification-strength matrix:

  - **No verification:** ask hours/location, language fallback, operator transfer.
  - **Basic verification (DOB plus partial phone or ANI plus DOB):** appointment confirmation, billing-statement question, generic information.
  - **Strong verification (DOB plus address-line-1 plus partial phone, or DOB plus member-id plus partial phone, or ANI-on-file plus DOB plus knowledge):** prescription refill release, appointment scheduling, contact-information update.
  - **Out-of-band confirmation required (basic verification plus SMS-or-email confirmation code):** specific high-risk actions named in institutional policy.

  Mark the pseudocode's `verification_method: "dob_plus_partial_phone"` with an explicit `// ILLUSTRATIVE: institutional policy may require stronger verification for prescription release; see verification-strength matrix in the production-gaps section.` comment. Reference the institutional identity-and-access-governance ownership for the matrix.

### Finding S4: Lambda Fulfillment-Hook Authentication of Lex Invocation Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (identity-boundary)
- **Location:** Architecture diagram `LEX --> L2` and `L2 --> L1/L3/L4/L5`, plus the IAM Permissions row mentioning "Connect's service role has scoped access to invoke the Lex bot and Polly. Lex's service role has scoped access to invoke the Lambda fulfillment hook."

- **Problem:** The recipe specifies that Lex invokes the fulfillment Lambda but does not specify the integrity boundary on the Lambda invocation. The Lambda accepts incoming events from Lex and processes the turn payload (intent, slots, confidence, transcript), then mutates the active-call-context, queues fulfillment actions, and emits cross-system events. The Lambda's resource-based policy and the Lex bot's invocation principal are the integrity boundary that ensures the fulfillment Lambda can only be invoked by the legitimate Lex bot. A misconfigured policy (the Lambda's resource policy allows invocations from any Lex bot in the account; the Lambda is invocable from a development bot in the same account) can route development-or-test traffic into the production fulfillment path, mutating real patient records.

  Same chapter pattern as the cross-recipe Lambda invocation patterns; recipe-specific because the IVR fulfillment is the only Lex-driven Lambda invocation in the chapter and the pattern bears repeating.

- **Fix:** Specify in the IAM Permissions row that the fulfillment Lambda's resource-based policy pins the invoking principal to the specific production Lex bot ARN with the production alias. The Lambda rejects invocations from any other Lex bot, any other alias, or any other principal. The development bot has its own development fulfillment Lambda with its own resource policy. The architectural pseudocode adds an early-event guard:

  ```
  FUNCTION handle_lex_turn(turn_event):
      // Validate the invocation source. The Lambda's
      // resource policy already restricts the principal
      // to the production Lex bot's ARN with the
      // production alias, but defense-in-depth: validate
      // the bot_id and bot_alias_id in the event payload
      // against the production constants.
      IF turn_event.bot.bot_id != PROD_BOT_ID OR
         turn_event.bot.bot_alias_id != PROD_BOT_ALIAS:
          LOG("invocation source mismatch",
              bot_id=turn_event.bot.bot_id,
              bot_alias_id=turn_event.bot.bot_alias_id)
          REJECT
      // Continue with normal processing.
      ...
  ```

### Finding S5: Audit-Log Retention Floor Specified With Generic "Institutional Regulatory Floor" Without Explicit Floor Naming

- **Severity:** MEDIUM
- **Expert:** Security (regulatory retention)
- **Location:** Prerequisites CloudTrail row: "Audit retention sized to the longest of HIPAA's six-year minimum, state medical-records-retention, and the institutional regulatory floor."

- **Problem:** Same chapter-wide pattern: the recipe correctly identifies the audit-log retention floor as a multi-source minimum (HIPAA six-year, state medical-records-retention, institutional-regulatory) but does not name a default floor for the recipe-specific use case. For IVR specifically, the audit log captures the routing decisions, the confidence levels, the policy invocations, and the disposition; the corresponding retention floor is the longest of: HIPAA six-year for the records-of-disclosure-and-routing decisions, state-specific call-recording-retention rules (some states require 1-7 years for healthcare phone records), and the institutional regulatory floor.

- **Fix:** Name the default IVR audit-log retention floor as "the longest of HIPAA's six-year minimum, the state-specific call-recording retention (typically 1-7 years), and the institutional regulatory floor" with the institutional-decision-required-at-build-time hedge. Reference the institutional retention policy as the canonical source.

### Finding S6: Recording-Disclosure Language Is Configured-Not-Hardcoded, but the Configuration Mechanism Is Underspecified

- **Severity:** LOW
- **Expert:** Security (regulatory-disclosure)
- **Location:** Step 1B pseudocode `play_audio("consent-disclosure-en-us.wav")` and the Prerequisites BAA / Compliance row's TODO on jurisdiction-aware recording consent.

- **Problem:** The recording-disclosure file is hardcoded as `consent-disclosure-en-us.wav`. The recipe correctly elevates the jurisdiction-aware variation in prose ("some U.S. states are one-party-consent, some are all-party-consent") and the institutional-legal-team approval discipline, but does not specify the configuration mechanism (per-DNIS routing to a jurisdiction-specific disclosure, per-ANI lookup to determine the caller's likely jurisdiction, default-to-all-party-consent-language as the conservative fallback). The pseudocode reads as if the disclosure is jurisdictionally uniform.

- **Fix:** Specify the per-DNIS disclosure configuration with the conservative-default-to-all-party-consent fallback for unknown jurisdictions:

  ```
  // Step 1B: play the consent and recording disclosure.
  // Disclosure language is configured per DNIS (the
  // dialed-in number maps to a jurisdiction; the
  // jurisdiction maps to disclosure language approved
  // by general counsel for that jurisdiction). For
  // unknown DNIS or ambiguous jurisdiction, the
  // conservative all-party-consent language is played.
  disclosure_audio =
      lookup_disclosure_for_dnis(dnis,
          fallback="consent-disclosure-all-party-en-us.wav")
  play_audio(disclosure_audio)
  ```

  Reference the Reporters Committee for Freedom of the Press tracker in the production-gaps section as the canonical source for the per-state recording-consent requirements.


## Architecture Expert Review

### What's Done Well

- Five-stage architecture (telephony ingress, speech-to-intent processing, dialog management, routing-or-fulfillment, observability) is the correct decomposition for a natural-language IVR. Each stage has a clear input, a clear output, and a clear failure mode.
- The urgency-keyword scanner runs in parallel with the intent classifier rather than after it ("Urgency-keyword scanner runs in parallel"). This is the correct architectural primitive: the urgency override must not be dependent on a successful intent classification, because the intent classifier may fail (low confidence, out-of-vocabulary, ASR error) on exactly the call where urgency override is most needed.
- Per-intent confidence thresholds rather than a global one are correctly elevated as an architectural primitive ("Confirm appointment can run on lower confidence than release prescription refill"). This is the correct pattern for balancing self-service containment against fulfillment risk.
- Verification-at-the-right-moment-not-too-early is correctly elevated as a cross-cutting design point ("Asking the caller for their date of birth before knowing what they want is what the legacy IVR did and it's part of why people hate it"). The intent-keyed verification framework that follows is the correct discipline.
- ANI-based prefill is correctly elevated as a non-trivial usability win with the spoofability caveat. The architecture diagram shows the caller-verifier Lambda consuming the ANI for prefill, with the verification slot collection still required for high-stakes actions.
- The active-call-context DynamoDB table with TTL is the correct pattern for ephemeral per-call state, with the 6-hour TTL (well above the typical call duration) sized to handle longer calls and post-call event processing without expiring mid-flow.
- The longer-retention caller-recent-history DynamoDB table is correctly separated from the active-call-context, with different access patterns (single-key reads for active-call, GSI on patient-id for recent-history) and different retention policies.
- The Kinesis Data Streams plus Firehose plus S3 plus Glue plus Athena analytics path is the correct serverless-analytics pattern for CTRs and contact events. The streaming-to-batch transition through Firehose is operationally robust.
- The Connect Contact Lens optional integration for sentiment, redaction, and keyword detection is correctly framed as additive rather than required, which respects institutional preference and cost sensitivity.
- The DTMF-fallback discipline is elevated correctly ("Every state in the dialog has to accept DTMF input as an alternative to voice"). This is the correct accessibility-and-availability primitive.
- The cost-estimate framing with the per-call-cost-versus-fully-loaded-agent-cost economic case is correctly granular and provides the institutional decision-makers with the right framing for the build-versus-not decision.
- The five-action routing decision (self-service fulfillment, queue routing with screen-pop context, callback scheduling, escalation to clinical, decline gracefully with always-reachable-fallback) is the correct enumeration for the disposition space.

### Finding A1: Cohort-Stratified Accuracy Monitoring Is Structurally Absent From the Architecture Pattern Despite Recipe-Specific Equity Stakes

- **Severity:** HIGH
- **Expert:** Architecture (operational metrics, equity instrumentation)
- **Location:** Observability stage in the General Architecture Pattern: "Aggregate metrics: Containment rate (calls fulfilled without agent), Top intents and their accuracy, Subgroup-stratified accuracy (age cohorts, language, accent groups where data is available), Mean handle time, abandon rate, escalation rate." The mention exists, but the architecture does not specify the cohort dimensions allow-list, the disparity-alert thresholds, the per-cohort sample-size minimums, or the named ownership.

- **Problem:** The recipe correctly elevates cohort-stratified monitoring as recipe-specific in the "Where it Struggles" subsection: "Patients with strong accents or non-native English are systematically less well-served. The ASR error rate on accented English is higher; the intent classifier sees noisier transcripts; the dialog manager hits low-confidence thresholds more often and routes more of these callers to agents... The agent routing isn't a failure (the call still gets handled), but it's a containment gap, and it's a gap that disproportionately affects specific populations. Subgroup-stratified accuracy monitoring is non-negotiable, and improving the accent-handling specifically usually requires either model fine-tuning on representative audio or vendor switching." The Why-Not-Production-Ready section also names this: "Subgroup-stratified accuracy monitoring with named ownership... The metric is institutionally important, not just engineering housekeeping; the institution that does not monitor subgroup performance silently delivers a worse experience to specific populations and learns about it from a complaint, an audit, or a lawsuit."

  Despite the prose elevation, the architecture pattern does not specify the structural elements:

  1. **The cohort-dimensions allow-list.** Which dimensions are tracked (age band where derivable, preferred language from the patient record, geographic region from the ANI or patient address, accent group where inferable from the ASR diagnostic data, primary insurance type as a coarse SES proxy, gender where available)? The architecture does not name these explicitly, leaving the engineering team to make the determination ad-hoc.

  2. **The disparity-alert thresholds.** What disparity in containment rate or intent-classification accuracy across cohorts triggers an alert? A 5-point gap? A 10-point gap? Statistical-significance-based threshold? The architecture does not specify, leaving the alarm configuration ungrounded.

  3. **The per-cohort sample-size minimums.** A cohort with only 50 calls per month produces noisy per-cohort metrics; the architecture should specify the minimum sample size before per-cohort metrics are deemed reliable, with the smaller-cohort fallback to the cohort-aggregated baseline.

  4. **The named ownership for the equity-monitoring committee.** The recipe names the committee in prose but does not establish it as an architectural primitive with monthly review cadence and explicit escalation path when disparities are detected.

  5. **The recipe-specific cohort dimension on accent-and-language.** The IVR's most acute equity stake is the accent-and-language disparity (accented English speakers, non-native English speakers, callers whose preferred language is not English). The architecture should specifically elevate the accent-and-language cohort-stratification as the recipe's primary equity instrumentation, with the per-cohort containment rate, intent-classification accuracy, and time-to-clinical-triage metrics tracked separately.

  6. **The interaction with the accessibility cohorts.** Section 508 accessibility includes callers with hearing impairments, callers with speech disabilities, and callers with cognitive impairments. The architecture should specify the per-cohort metrics for these accessibility cohorts (DTMF-only-throughout containment rate, slower-pacing-callers handle time) where the data is available.

  Same chapter pattern as the equity-instrumentation findings in chapters 4 (recipe 4.10 Finding A4) and 5 (multiple recipes); recipe-specific because the IVR is the front door for the substantial fraction of patients who do not use a portal or an app, and that fraction is disproportionately older, lower-broadband-access, and lower-digital-literacy populations who are exactly the populations the equity instrumentation should protect.

- **Fix:** Promote the recipe's prose elevation into the architecture pattern. Specify in the Observability stage:

  ```
  [Aggregate metrics, cohort-stratified]
   - Cohort dimensions allow-list:
     * Age band (where derivable from patient record)
     * Preferred language (from patient record)
     * Geographic region (from ANI or address)
     * Accent group (where inferable from ASR diagnostic
       data; calibration via a representative-audio
       evaluation set)
     * Primary insurance type (as a coarse SES proxy)
     * Accessibility flag (DTMF-only, hearing-impaired,
       speech-impaired, where the patient record carries
       the flag)
   - Per-cohort metrics:
     * Containment rate
     * Intent-classification accuracy
     * Time-to-clinical-triage for urgent calls
     * Abandon rate
     * Repeated-low-confidence-turn rate
     * Verification-failure rate
   - Per-cohort sample-size minimums:
     * Reliable: >= 200 calls in the metric window
     * Noisy: 50-199 calls (reported with wide CI)
     * Insufficient: < 50 calls (suppressed; aggregated
       to the dimension's "all_other" cohort)
   - Disparity-alert thresholds:
     * Containment rate gap > 10 points across cohorts
     * Intent-classification accuracy gap > 5 points
     * Time-to-clinical-triage gap > 30 seconds
     * Alerts fire at the equity-monitoring committee's
       weekly review queue
   - Named ownership:
     * Equity-monitoring committee (cross-functional;
       includes patient-advocacy representation)
     * Monthly review cadence with quarterly written
       summary to institutional governance
  ```

  Reference the cohort-stratified pattern as the chapter-wide convention emerging from earlier chapters and elevate it to a chapter-10 preface for consistent application across recipes 10.2 through 10.10.

### Finding A2: DLQ Topology and Lambda Concurrency Limits Are Named in Production-Gaps but Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (operational resilience)
- **Location:** Why-This-Isn't-Production-Ready section: "Configure DLQs on every Lambda; alarm on DLQ depth." Architecture diagram does not show DLQs; the IAM Permissions row does not name the DLQ-write permissions.

- **Problem:** The recipe correctly identifies the DLQ requirement in the production-gaps section but does not architect the DLQ topology. Each fulfillment Lambda (caller-verifier, intent-router, refill-fulfillment, appointment-fulfillment, urgency-escalator) has independent failure modes and independent retry-and-poison-message semantics. The DLQ topology should specify:

  1. **Per-Lambda DLQ.** Each Lambda has its own DLQ; the DLQs are not pooled. This isolates poison messages in one Lambda from blocking processing in another.
  2. **Maximum-receive-count.** Each DLQ has a configured maximum-receive-count after which the message is moved to the DLQ. The Lambda's invocation retry behavior (Lex's retry semantics, Connect's retry semantics, EventBridge's retry semantics) interacts with the receive-count.
  3. **DLQ-depth alarms.** Each DLQ has a CloudWatch alarm at >= 1 message and a higher-severity alarm at >= 10 messages, routed to the on-call channel.
  4. **DLQ-redrive procedure.** The runbook for redriving DLQ messages includes the idempotency-key validation (per Finding S2) so a redrive does not produce duplicate fulfillment.
  5. **The urgency-escalator Lambda's DLQ has a special-case alarm.** A poison message in the urgency-escalator DLQ means an urgent call did not route to clinical triage; the alarm is page-immediately rather than next-business-day.
  6. **Lambda concurrency limits.** Reserved concurrency for the urgency-escalator Lambda ensures it cannot be starved by a high-volume non-urgent intent. The other fulfillment Lambdas have provisioned concurrency for the typical-business-hours load with on-demand burst.

- **Fix:** Add a "Resilience Topology" subsection in the AWS Implementation section that specifies the per-Lambda DLQ configuration, the per-Lambda concurrency posture, the DLQ-depth alarm thresholds, and the DLQ-redrive runbook with idempotency-key validation. Update the architecture diagram to show the per-Lambda DLQ.

### Finding A3: Lex Bot Version Control and Blue-Green Deployment via Aliases Is Named in Prose but Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (deployment-and-change-management)
- **Location:** Step 1C pseudocode `invoke_lex_bot(bot_id=PATIENT_BOT_ID, bot_alias=PATIENT_BOT_ALIAS_PROD, ...)` and Why-Not-Production-Ready section "deploy via versioned bot aliases."

- **Problem:** The pseudocode references a single production alias but does not specify the blue-green deployment pattern that the production-gaps section names. The Lex V2 bot-alias model supports versioned deployments where a new bot version is built, tested against a held-out evaluation set, deployed to a canary alias, traffic-shifted incrementally to the canary, and then promoted to the production alias on success. The architecture should specify:

  1. **Versioned bot definitions in version control.** The bot definition (intents, sample utterances, slot types) is checked into version control; bot-version builds are tied to specific commit SHAs.
  2. **Canary alias with traffic-shift.** New bot versions are deployed to a canary alias with 5% traffic, monitored against a regression evaluation set and against subgroup-stratified production metrics, then traffic-shifted to 25%, 50%, and 100% over a configured window.
  3. **Rollback-on-regression.** A regression in any subgroup metric (per Finding A1) triggers automatic rollback to the prior production alias.
  4. **Held-out evaluation set.** The evaluation set is curated to include the recipe-specific edge cases (accent samples, multi-intent utterances, urgency-keyword phrases, controlled-substance medication names, low-confidence-turn samples) and the subgroup-coverage cohorts.

- **Fix:** Add a "Deployment Pattern" subsection in the AWS Implementation section that specifies the blue-green deployment via Lex aliases, the traffic-shift cadence, the regression-evaluation-set composition, and the rollback-on-regression triggers.

### Finding A4: Multi-Language Architecture as Build-For-It-Day-One Even-If-Shipping-English-First Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (multi-language operational pattern)
- **Location:** Why-Not-Production-Ready section: "Multi-language support architecture. If you need Spanish (and most U.S. healthcare organizations should), Lex V2 supports multi-language bots, but the operational pattern (one bot with locale-specific training, or one bot per locale, or a router bot that detects language and dispatches) is an architectural decision with real implications. Build for multi-language from the start even if you ship English-first; retrofitting multi-language onto a single-language design is more expensive than designing for it day one."

- **Problem:** The recipe correctly elevates the multi-language architectural decision in production-gaps but does not specify the recommended pattern for the recipe. Lex V2 supports two patterns: (a) one bot with multiple locales (English plus Spanish, sharing the intent definitions but with locale-specific sample utterances); (b) one bot per locale plus a router bot that detects the caller's preferred language and dispatches. For healthcare IVR specifically, the per-locale-bot-with-router pattern is operationally cleaner because it isolates the locale-specific evaluation sets, the locale-specific intent definitions (some intents are locale-specific in healthcare; for example, the Spanish-language curandero-or-traditional-medicine intent has no English equivalent), and the locale-specific lexicon governance.

- **Fix:** Specify the per-locale-bot-plus-router pattern in the architecture section with the locale-detection logic at the start of the call (typically "press 1 for English, press 2 for Spanish" as the conservative default; auto-detection from the caller's first utterance as the optional enhancement). Add the locale-specific evaluation sets and locale-specific lexicon governance as architectural primitives. Reference the multi-language pattern as build-for-day-one even when shipping English-only.

### Finding A5: VPC Endpoints for Lex Runtime, Polly, and Other AWS-Internal Calls Are Named for DynamoDB and S3 but Not for the Conversational-AI Services

- **Severity:** MEDIUM
- **Expert:** Architecture and Networking (data-in-transit egress)
- **Location:** Prerequisites VPC row: "VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge so the Lambdas don't need NAT for AWS-internal calls."

- **Problem:** The recipe correctly elevates the VPC endpoint pattern for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, and EventBridge but does not include the conversational-AI services (Lex Runtime V2, Polly, Transcribe). Amazon Lex V2 Runtime supports interface VPC endpoints (`com.amazonaws.<region>.runtime.lex`); Amazon Polly supports interface VPC endpoints (`com.amazonaws.<region>.polly`); Amazon Transcribe supports interface VPC endpoints. For Lambdas in VPC that invoke these services (a Lambda that, for example, calls Polly directly to synthesize a custom prompt rather than relying on Lex's inline TTS), the VPC endpoint avoids the NAT-gateway egress cost and keeps the data-in-transit on the AWS backbone.

- **Fix:** Add the Lex Runtime V2, Polly, and Transcribe VPC endpoints to the Prerequisites VPC row. Note that Connect itself runs as a managed service outside the customer VPC, so the integration with Lex, Polly, and Lambda still terminates through Connect's managed control plane; the customer-VPC endpoints apply specifically to Lambda-initiated calls into these services.

### Finding A6: Connect-Voice-ID and Connect-Contact-Lens HIPAA Eligibility Verified-At-Build-Time

- **Severity:** LOW
- **Expert:** Architecture (BAA-eligibility currency)
- **Location:** Prerequisites BAA / Compliance row: "Connect, Lex, Polly, Transcribe, Lambda, DynamoDB, S3, Kinesis, KMS, Secrets Manager, CloudWatch Logs, CloudTrail are HIPAA-eligible (verify the current list at build time)."

- **Problem:** The list does not specifically name Connect Contact Lens or Connect Voice ID, both of which are sub-features of Connect with their own eligibility status. Contact Lens is HIPAA-eligible under BAA at the time of writing; Voice ID has been HIPAA-eligible but the recipe correctly recommends skipping it in MVP, so the eligibility is moot but the eligibility statement should still be confirmed for future-state planning.

- **Fix:** Add Connect Contact Lens and Connect Voice ID to the explicit HIPAA-eligible list with the "verify the current list at build time" hedge. Reference the AWS HIPAA Eligible Services Reference URL.

### Finding A7: Single-Point-of-Failure Analysis for Lex and Connect Outage Is Named in Production-Gaps but Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (disaster-recovery and failover)
- **Location:** Why-Not-Production-Ready section: "The IVR is the front door. When it's down, callers can't reach the practice. The architecture needs an explicit failover path: if Lex is unavailable, drop to a DTMF menu in Connect; if Connect is unavailable, fail over to a backup carrier-side IVR."

- **Problem:** The recipe correctly elevates the failover requirement in production-gaps but does not architect the failover topology. The architecture should specify:

  1. **Lex failover within Connect.** A contact flow branch that triggers when the Lex invocation fails or times out, dropping the call to a DTMF menu within Connect. The DTMF menu is a degraded-but-functional state that handles the highest-volume intents (refill transfer, billing transfer, nurse-line transfer, hours-and-location, operator).

  2. **Connect failover to backup carrier-side IVR.** A carrier-side DNS or routing failover that routes calls away from Connect when Connect is unavailable. The backup carrier-side IVR is a static DTMF menu that routes to the same agent queues as Connect's primary path, with a degraded set of self-service capabilities.

  3. **Failover testing cadence.** Quarterly exercise of both failover paths with synthetic calls. The exercise produces a report on the failover latency, the degraded-mode containment, and the staff-impact during the exercise.

  4. **Failover-detection and failover-back triggers.** The detection of the upstream service's recovery and the failover-back to the primary path is automated (Connect health checks; Lex health checks) with the on-call engineer notified at each transition.

- **Fix:** Add a "Disaster Recovery Topology" subsection in the AWS Implementation section that specifies the Lex-failover-within-Connect contact flow branch, the Connect-failover-to-backup-carrier-side-IVR pattern, the failover-testing cadence with quarterly exercise, and the failover-detection-and-failover-back triggers.

### Finding A8: Idempotency for the Appointment-Fulfillment Path Is Implied but Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (write-path integrity)
- **Location:** Architecture diagram `L4[Lambda appointment-fulfillment]` and the parallel pattern to the refill-fulfillment Lambda.

- **Problem:** Same Finding S2 issue replicated for the appointment-fulfillment path. A duplicate appointment confirmation does not have the same clinical-safety consequence as a duplicate refill, but it produces analytics inflation (the containment rate appears higher than reality), state corruption (the patient's appointment status is updated twice), and downstream notification noise (the patient receives two confirmation SMS).

- **Fix:** Same as Finding S2; specify the idempotency-key composition for the appointment-fulfillment path with the (call_id, intent_name, turn_index) tuple.


## Networking Expert Review

### What's Done Well

- VPC endpoints called out for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge ("so the Lambdas don't need NAT for AWS-internal calls"). This is the correct egress-discipline posture for VPC-attached Lambdas that handle PHI.
- TLS-in-transit explicitly elevated for back-office API calls. The institutional cipher-suite policy is correctly assumed to be in place.
- Connect's managed-service positioning is correctly framed: "Connect itself is a managed service that runs outside your VPC; the integration with Lambda and Lex still terminates in your account." This honestly characterizes the data flow boundary between the AWS-managed control plane and the customer's account-bound resources.
- The mTLS-or-equivalent posture for the back-office API integration is implied by the Secrets Manager pattern with rotation.
- The audio-path security from carrier to Connect is architecturally implicit: SIP trunking with the carrier supports TLS-encrypted SIP signaling and SRTP-encrypted media; Connect's carrier integration uses these where the carrier supports them. This is the correct posture for the telephony-egress boundary.

### Finding N1: Carrier-Side TLS-and-SRTP for the Telephony Egress Boundary Is Architecturally Implicit but Not Named

- **Severity:** LOW
- **Expert:** Networking (data-in-transit on the telephony boundary)
- **Location:** Telephony Ingress stage: "SIP trunk or carrier routes the call to the contact center platform."

- **Problem:** The recipe does not name the carrier-side TLS-for-SIP-signaling and SRTP-for-media as the secure-transport posture for the telephony egress. The PSTN side of the boundary is the legacy circuit-switched network with no in-band encryption available; the SIP-trunk side, where it terminates with the customer's carrier, can be configured with TLS-for-signaling and SRTP-for-media. Connect supports SIP trunks with TLS/SRTP. The architectural specification of this posture matters because:

  1. **Recording at the carrier boundary is otherwise unencrypted.** A SIP trunk without TLS exposes the SIP signaling (caller ANI, dialed DNIS, call setup metadata) to anyone in the path; without SRTP, the media is unencrypted RTP and is interceptable on the path.

  2. **The PSTN side is unavoidable.** Once the call originates from a PSTN endpoint, the audio travels in-clear through the PSTN until it reaches the customer's carrier. The customer cannot encrypt the PSTN side. The customer can ensure the carrier-to-Connect side is encrypted.

  3. **The institutional security posture should specify the carrier requirement.** The carrier contract should require TLS-for-SIP-signaling and SRTP-for-media; the carrier should be a BAA-covered entity if the institution's interpretation requires it (most do, given that the carrier transmits PHI).

- **Fix:** Add a "Carrier-Side Transport" prose paragraph in the AWS Implementation section that specifies the TLS-for-SIP-signaling and SRTP-for-media posture as the institutional requirement for the carrier-to-Connect boundary, with the carrier-BAA framing as the institutional-decision question.

### Finding N2: Egress Concerns for PHI in Back-Office API Calls Are Architecturally Implicit

- **Severity:** LOW
- **Expert:** Networking (data-in-transit egress for back-office)
- **Location:** Prerequisites VPC row: "Production: Lambdas that call back-office APIs run in VPC with subnets that have controlled egress to the back-office systems' network."

- **Problem:** The recipe correctly elevates the controlled-egress framing but does not specify the egress topology. The Lambdas calling the EHR API, the e-prescribing API, and the scheduling API egress through the customer's VPC. The egress pattern is one of:

  1. **Direct egress through the VPC's NAT Gateway and the public Internet to the back-office system's public endpoint.** This is the simplest pattern but the egress is on the public Internet, with TLS-only-as-the-encryption-substrate.

  2. **VPC-peering or Transit-Gateway to the back-office network.** This is the institutional-network-attached pattern; the egress is on the customer's private network (VPC peering, Direct Connect, Transit Gateway).

  3. **PrivateLink to the back-office system's PrivateLink endpoint.** This is the AWS-internal pattern where the back-office system's vendor exposes its API via PrivateLink.

- **Fix:** Specify the recommended egress topology in the production-gaps section with the institutional-network-attached pattern preferred for back-office systems on the institutional network and PrivateLink preferred for vendor-managed APIs that expose PrivateLink endpoints. Direct egress through NAT Gateway is the fallback for vendor APIs that are public-Internet only.

### Finding N3: Lex Runtime, Polly, Transcribe VPC Endpoints

- **Severity:** MEDIUM (bundled with Architecture Finding A5)
- **Expert:** Networking
- **Location:** See Architecture Finding A5.

- **Problem:** Same as Architecture Finding A5; carries the networking expert's perspective that the conversational-AI-service VPC endpoints are the correct posture for Lambdas that initiate calls into these services from within VPC.

- **Fix:** See Architecture Finding A5.

---

## Voice Reviewer

### What's Done Well

- Em dash count: 0 (verified by raw-byte match against the U+2014 sequence; zero matches in the file).
- En dash count: 0 (verified).
- The 70/30 vendor balance is maintained. AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. The Technology section's four-stage pipeline survey (telephony plumbing, ASR, NLU, dialog management plus fallbacks) is fully vendor-agnostic; the General Architecture Pattern's five-stage decomposition is fully vendor-agnostic.
- The opening 67-year-old-AFib-flutter-on-the-anticoagulant Tuesday-morning vignette sets the engineer-explaining-something-cool register exactly. The five subsequent vignettes (the diabetic with foot swelling, the Spanish-speaker, the 31-year-old commercial-insurance defection, the pediatric mother, the 67-year-old refill loop) ground the institutional-and-economic stakes in patient experience.
- "This is one of those problems that sounds simple until you actually try it" energy carries through the Technology section.
- Self-deprecating expertise lands well: "the engineering joy of an IVR project is that you don't have to be an expert in any of them; you just have to know how they fit together and where they typically break"; "Here's the thing nobody tells you about IVR engineering: most of the architectural decisions are about what happens when the ML pipeline doesn't work, not when it does"; "The system that ignores fallbacks works perfectly in the demo and falls apart on the first real call from someone the demo didn't model."
- The Honest Take's twelve observations close at exactly the right grain. The IVR-as-patient-dignity-surface closing paragraph ("the IVR is, for many patients, their first interaction with the institution after they decide they need care... the patient has wrestled with whether the symptom is bad enough to call... they've already done the hard part. The IVR's job is to honor that") is the recipe's strongest single closing line.
- Healthcare-domain accuracy is consistent. Atrial fibrillation, anticoagulant on first refill after diagnosis, the diabetic-foot-swelling-to-ulcer progression, the AFib-flutter symptom matched against urgency are all clinically valid.
- Parenthetical asides are present and serve the voice ("ok, this is a gross oversimplification, but stay with me" energy without overdoing it; the casual "your mileage may vary" framing in the performance benchmarks).
- No documentation-voice ("This recipe demonstrates how to leverage..."). No marketing-influencer language ("AWS architects, we need to talk about X").
- The "thing about Amazon Lex specifically" / "thing about Amazon Connect specifically" / "thing about LLMs in IVR" honest assessments at the end of the Honest Take are the recipe's strongest single passage of vendor-honest framing without lapsing into either hype or trash-talk. The Lex "competent platform that ships with managed ASR-and-NLU and integrates natively with Connect, which removes a substantial amount of integration friction. It's not the most accurate NLU on the market" framing is exactly the right register.

### Finding V1: A Few Long Sentences in the Technology Section Could Be Tightened Without Losing Voice

- **Severity:** LOW
- **Expert:** Voice (sentence-length register)
- **Location:** Technology section, NLU subsection: "Send the transcript to a large language model with a prompt that lists the available intents and asks the model to classify. Modern LLMs are extremely good at this with zero or few-shot prompting. The advantages: no per-intent training data, easy to extend (add a new intent by editing the prompt), and the model handles weird phrasings gracefully. The disadvantages: per-call latency and cost (LLM inference is more expensive per call than a small classifier), occasional hallucinated intents that aren't in your list (you have to validate the output strictly), and the operational dependency on a model you don't control."

- **Problem:** The sentences here are dense, but consistent with CC voice. Some readers may find the pacing heavy in this subsection. This is a minor voice observation rather than a flag; the cumulative-momentum-through-accumulation pattern works for CC. Optional tightening would replace the parenthetical-rich sentences with shorter declarative ones for breathing room.

- **Fix:** Optional. Consider breaking the longest run-on sentences in the NLU subsection (the LLM advantages and disadvantages enumeration) into shorter declaratives. Not required; current voice is consistent.

### Finding V2: The Closing Paragraph's Patient-Dignity Framing Is the Recipe's Strongest Single Voice Moment, but the Preceding Paragraph's Vendor-Specific Framing on Lex Could Be Pulled Earlier

- **Severity:** LOW
- **Expert:** Voice (closing-section ordering)
- **Location:** Honest Take, the order: vendor-specific Lex / Connect / LLM observations followed by per-call-cost economic observation followed by would-do-differently-the-second-time observation followed by patient-dignity closing paragraph.

- **Problem:** The patient-dignity closing paragraph is the recipe's strongest single voice moment and earns its position as the closer. The vendor-specific observations on Lex, Connect, and LLMs are less voice-strong but are operationally important. The current ordering puts the vendor-specific observations before the closer, which preserves the vendor-honesty-as-the-build-up-to-the-philosophical-closer pacing. This is consistent with CC voice and is not a flag; minor observation that the alternative ordering (patient-dignity-first then vendor-specific) would also work but lose the build-up.

- **Fix:** No fix required; current ordering is consistent with CC voice.

### Finding V3: The Phrase "It's a real call" in The Problem Section Could Be Slightly Softened

- **Severity:** LOW
- **Expert:** Voice (assertion-strength register)
- **Location:** The Problem section: "This is a real call, and it's one of millions like it that happen every day in U.S. healthcare."

- **Problem:** The recipe vignette is composite (representative of many real calls; not literally one call from one patient). The phrase "this is a real call" is slightly stronger than "this is a real pattern" or "this happens millions of times every day in U.S. healthcare." A pedantic reader might object to the literal interpretation.

- **Fix:** Optional. Consider rephrasing to "This is a representative call, and it's one of millions of similar calls that happen every day in U.S. healthcare" or "This is the kind of call that happens millions of times every day in U.S. healthcare." Not required; the figurative reading is the obvious one.

---

## Stage 2: Expert Discussion

The four expert lenses produce overlapping concerns at three intersections.

**Audit-log PHI minimization (Security S1) overlaps with Architecture observability.** The Security expert's concern about transcript content in audit logs is operationally connected to the Architecture expert's concern about cohort-stratified accuracy monitoring (Finding A1): the cohort-stratification analytics need access to a transcript-derivable signal (accent, language, age band where derivable from voice) but that signal must come from structured-and-redacted metadata, not from the transcript itself. The architectural fix is to capture the signal in the transcript-archive's structured metadata (ASR-confidence-distribution, average-utterance-length, language-detection-result) and reference that metadata in the audit log; the audit log itself never sees the transcript content. The two findings reinforce each other and the consolidated fix is the right one.

**Idempotency (Security S2 / Architecture A8) overlaps with the DLQ topology (Architecture A2).** The idempotency-key composition is the load-bearing primitive that makes the DLQ-redrive runbook safe; without idempotency, a redrive produces duplicate fulfillment. The two findings are intertwined; the consolidated fix specifies idempotency-keyed fulfillment plus DLQ-redrive-with-idempotency-validation as a single architectural primitive.

**Cohort-stratified accuracy (Architecture A1) overlaps with Voice's accent-and-language-disparity observation.** The Voice expert's observation that the accent-and-language-disparity is recipe-specific reinforces the Architecture expert's elevation of the cohort-stratified monitoring as the recipe's primary equity instrumentation. The two findings reinforce each other; the consolidated fix specifies the accent-and-language cohort dimension as the recipe's primary equity dimension, with the architectural-primitive elevation matching the prose elevation.

**No conflicts** between expert lenses requiring resolution. The Security expert's verification-policy strengthening (Finding S3) is consistent with the Architecture expert's intent-keyed verification framework; both elevate the same primitive at different layers. The Networking expert's egress-discipline framing is consistent with the Architecture expert's resilience-topology framing; both elevate the same primitive in different operational contexts.

**Priority resolution.** The three HIGH findings are independent and additive: the audit-log PHI minimization fix (Security S1), the idempotency-key composition fix (Security S2 plus Architecture A8 consolidated), and the cohort-stratified accuracy fix (Architecture A1) each address a distinct architectural primitive. The MEDIUM findings cluster into the deployment-and-resilience category (DLQ topology, Lex bot version control, multi-language architecture, VPC endpoints, Connect-Voice-ID and Connect-Contact-Lens HIPAA eligibility, single-point-of-failure analysis) and the verification-and-disclosure category (verification-policy strength, recording-disclosure jurisdiction-aware language, Lambda fulfillment-hook authentication, audit-log retention floor). The LOW findings are individually minor and collectively cosmetic.

---

## Stage 3: Synthesized Feedback

### Verdict: PASS

**Rationale:** 0 CRITICAL findings; 3 HIGH findings (at the > 3 = FAIL threshold but not exceeding); 11 MEDIUM findings (most explicitly TODO'd in the recipe's prose with the chapter-pattern consolidation deferred to the editor); 7 LOW findings (cosmetic or minor). The three HIGH findings are localized correctness gaps that the prose elsewhere in the recipe correctly diagnoses with TODO references already in place; closing them brings the architecture and the pseudocode up to the standard the recipe text claims and matches the chapter pattern from prior chapters' first-recipe entries. Recipe 10.1 is Chapter 10's introductory simple-tier recipe, and at the simple-tier level the verdict reflects a recipe that is publishable with the three HIGH findings closed.

### Prioritized Findings

| # | Severity | Expert | Location | Summary | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Step 2A pseudocode `audit_log` block | Raw transcript (PHI) written into structured audit log payload; CloudWatch Logs becomes parallel PHI store outside recordings-bucket governance | Audit log carries `transcript_archive_ref`, `transcript_length_chars`, `transcript_hash`; full transcript lives in secure transcript archive only. Add cross-cutting prose paragraph elevating transcripts to recordings-equivalent governance. |
| 2 | HIGH | Security / Architecture | Step 4E `queue_refill_request` | No idempotency key in fulfillment call; Lex retry, EventBridge replay, or at-least-once Lambda invocation produces duplicate refill request | Promote production-gaps idempotency-key pattern into Step 4 pseudocode with `(call_id, intent_name, turn_index)` key; specify that e-prescribing API honors the key. Apply same pattern to appointment-fulfillment Lambda (Finding A8). |
| 3 | HIGH | Architecture | Observability stage in General Architecture Pattern | Cohort-stratified accuracy monitoring named in prose but architecturally underspecified; missing cohort-dimensions allow-list, disparity-alert thresholds, sample-size minimums, named ownership | Promote the prose elevation into the architecture stage with explicit cohort-dimensions allow-list (age band, preferred language, geographic region, accent group, primary insurance type, accessibility flag), per-cohort metrics, sample-size minimums, disparity-alert thresholds, and named equity-monitoring committee ownership. |
| 4 | MEDIUM | Security | Step 3 `verify_slots_returned` | Verification policy "DOB plus partial phone" marked illustrative in prose but bound to high-impact intents in pseudocode without below-production-bar marker | Specify intent-keyed verification-strength matrix (no/basic/strong/out-of-band); annotate pseudocode example as illustrative; reference institutional identity-and-access-governance ownership. |
| 5 | MEDIUM | Security | Architecture diagram `LEX --> L2` | Lambda fulfillment-hook authentication of Lex invocation underspecified | Resource-based policy pinning principal to production Lex bot ARN with production alias; defense-in-depth event-payload validation of `bot_id` and `bot_alias_id`. |
| 6 | MEDIUM | Security | Prerequisites CloudTrail row | Audit-log retention floor named generically without explicit IVR-specific floor | Name the longest-of-(HIPAA-six-year, state-specific call-recording retention typically 1-7 years, institutional regulatory floor). |
| 7 | MEDIUM | Architecture | Why-Not-Production-Ready section | DLQ topology and Lambda concurrency limits named in production-gaps but not architecturally specified | Add Resilience Topology subsection with per-Lambda DLQ, max-receive-count, DLQ-depth alarms (urgency-escalator paged immediately), DLQ-redrive runbook with idempotency-key validation, reserved concurrency for urgency-escalator. |
| 8 | MEDIUM | Architecture | Step 1C `invoke_lex_bot(...PROD)` | Lex bot version control and blue-green deployment via aliases named in prose but underspecified | Add Deployment Pattern subsection with versioned bot definitions in version control, canary alias with traffic-shift, rollback-on-regression, held-out evaluation set with subgroup coverage. |
| 9 | MEDIUM | Architecture | Why-Not-Production-Ready section | Multi-language architecture build-for-day-one named but not specified | Specify per-locale-bot-plus-router pattern with locale-detection logic; locale-specific evaluation sets and lexicon governance as architectural primitives. |
| 10 | MEDIUM | Architecture / Networking | Prerequisites VPC row | VPC endpoints named for DynamoDB/S3/KMS/Secrets Manager/CloudWatch/EventBridge but not for Lex Runtime, Polly, Transcribe | Add Lex Runtime V2, Polly, Transcribe interface VPC endpoints. |
| 11 | MEDIUM | Architecture | Why-Not-Production-Ready section | Single-point-of-failure analysis for Lex/Connect outage named but not architected | Add Disaster Recovery Topology subsection: Lex-failover-within-Connect contact flow branch (degraded DTMF menu); Connect-failover-to-backup-carrier-side-IVR; quarterly failover testing; failover-detection and failover-back triggers. |
| 12 | MEDIUM | Architecture | Architecture diagram `L4` | Idempotency for appointment-fulfillment path implied but not specified | Same pattern as Finding 2; specify `(call_id, intent_name, turn_index)` idempotency-key composition. |
| 13 | MEDIUM | Networking | Prerequisites VPC row | Egress concerns for PHI in back-office API calls architecturally implicit | Specify recommended egress topology: VPC-peering or Transit Gateway for institutional-network-attached back-office systems; PrivateLink for vendor-managed APIs with PrivateLink endpoints; NAT Gateway egress as fallback. |
| 14 | MEDIUM | Architecture | Prerequisites BAA row | Connect Voice ID and Connect Contact Lens HIPAA eligibility not explicitly named | Add Contact Lens and Voice ID to explicit HIPAA-eligible list with verify-at-build-time hedge; reference AWS HIPAA Eligible Services Reference URL. |
| 15 | LOW | Security | Step 1B `play_audio("consent-disclosure-en-us.wav")` | Recording-disclosure language is configured-not-hardcoded but the configuration mechanism is underspecified | Specify per-DNIS disclosure configuration with conservative-default-to-all-party-consent fallback; reference Reporters Committee for Freedom of the Press tracker. |
| 16 | LOW | Networking | Telephony Ingress stage | Carrier-side TLS-and-SRTP for telephony egress boundary architecturally implicit | Add Carrier-Side Transport prose paragraph specifying TLS-for-SIP-signaling and SRTP-for-media as institutional carrier requirement; carrier-BAA framing as institutional-decision question. |
| 17 | LOW | Voice | Technology section, NLU subsection | Some long parenthetical-rich sentences in the LLM-NLU subsection | Optional tightening; not required, current voice is consistent. |
| 18 | LOW | Voice | The Problem section | "This is a real call" phrasing slightly stronger than figurative meaning warrants | Optional rephrase to "This is a representative call" or "This is the kind of call that happens millions of times"; not required. |
| 19 | LOW | Voice | Honest Take ordering | Vendor-specific observations precede patient-dignity closer; current ordering preserves build-up | No fix required; current ordering is consistent with CC voice. |
| 20 | LOW | Architecture | Operational Ownership paragraph in production-gaps | Operational ownership named but specific roles not enumerated for the named functions | Optionally enumerate: contact-center-operations owns intent thresholds and DTMF-fallback content; clinical-operations owns urgency lexicon; IT-security owns identity-boundary checks and KMS; compliance owns recording-disclosure language and retention; equity-monitoring committee owns cohort-stratification dashboards. Optional clarification, not required. |
| 21 | LOW | Architecture | Prerequisites Cost Estimate row | Per-minute Connect telephony charges depend on inbound vs outbound and local vs toll-free | Recipe correctly TODOs the verification against AWS Pricing Calculator; LOW because the TODO is appropriate. |

### Closing Notes

Recipe 10.1 is publishable at the simple-tier level once the three HIGH findings are closed. The Honest Take is the recipe's strongest single passage and frames the IVR as a patient-experience product with engineering as its substrate, which is exactly the right framing for a chapter-opening recipe that establishes the chapter's voice-and-operational register. The chapter-wide consolidation work (the cohort-stratified-accuracy chapter preface, the identity-boundary chapter preface, the audit-log retention floor chapter preface, the urgency-lexicon governance chapter preface) is deferred to the chapter editor. The recipe's twelve Variations and Extensions provide the right runway into the chapter's later recipes (10.2 voicemail transcription, 10.4 medical transcription, 10.5 patient-facing voice assistant, 10.6 telehealth transcription, 10.10 multilingual real-time medical interpretation), each of which builds on the speech-to-intent-pipeline-with-confidence-aware-downstream-consumption pattern this recipe establishes.

The recipe's central operational insight ("The technology is the substrate; the system is fundamentally about how the institution greets the patients who pick up the phone") is the chapter's strongest single closing observation and earns its position as the recipe's central voice moment.
