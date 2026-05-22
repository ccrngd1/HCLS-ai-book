# Expert Review: Recipe 5.4 - Insurance Eligibility Matching

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-22
**Recipe file:** `chapter05.04-insurance-eligibility-matching.md`

---

## Overall Assessment

This is the fourth recipe in Chapter 5 and the first Medium-tier recipe in the chapter. It introduces the recipe-specific concepts that justify a separate recipe from the patient-matching (5.1), provider-matching (5.2), and address-standardization (5.3) recipes: cross-organizational entity resolution where half the data is the payer's and cannot be cleaned, the X12 270/271 transaction set as the regulatory baseline with CAQH CORE Phase II operating rules layered on top, the primary-key-vs-search-match dichotomy on the inquiry side, the multi-component coverage answer (identity match, coverage status, coverage scope, financial responsibility, COB, network status), the real-time-vs-pre-warm-vs-batch trigger heterogeneity, the cache-and-async pattern that decouples registration latency from the underlying 270/271 round-trip, and the freshness-as-two-regimes (past service dates settled, future service dates volatile) framing. The opening 7:42 AM front-desk vignette earns its position: the patient with the card in her hand getting "member not found," the cascade of "maybe the card has the wrong member ID, maybe the patient is in a coverage lookup with her maiden name, maybe the payer's eligibility file is two days behind because their nightly batch job failed and nobody noticed yet" sets up the follow-on operational vignettes (multi-specialty group with claim denials for "patient ineligible at time of service," charity-care eligibility cycles taking weeks, Medicaid managed-care reconciliation against state MMIS, payer enrollment with self-funded employer census files, clearinghouse augmenting non-actionable 271 responses) at exactly the right level of "this is what eligibility verification actually looks like in production" energy.

The Technology section is the chapter's clearest articulation of "why eligibility matching is structurally harder than internal patient matching": the data is asymmetric (half is the payer's and cannot be cleaned), the match has to be real-time (registration fits in a 2-5 second budget), the data flows are bidirectional and event-driven (enrollments, qualifying events, COBRA starts, age-outs, plan changes), and the failure modes have direct financial consequences (wrong "eligible" produces denial; wrong "not eligible" produces delayed care or self-pay charges that should have been billed to insurance). The "What an Eligibility Match Actually Resolves" subsection correctly decomposes the structured answer into identity match, coverage status, coverage scope, financial responsibility, COB, and network status. The X12 270/271 foundation subsection is correctly granular: the inquiry payload, the response segments (AAA, EB, NM1), the primary-key-vs-search-match modes, the CAQH CORE Phase II response-time SLAs (real-time within 20 seconds, batch within 24 hours), and the explicit observation that the requesting side needs an entity-resolution layer even on primary-key matches because the payer's returned record may not actually be the patient in the requesting record. The "What Makes the Match Hard" six-bullet enumeration (no shared identifier, asymmetric demographic capture, member ID changes over time, subscriber-vs-dependent relationships, eligibility data freshness varies wildly, self-funded plans and TPAs add a layer) is correct and at the right grain.

The six-stage architecture (ingest the trigger, normalize the patient side, route the inquiry, evaluate and resolve identity, persist with provenance, react to drift) is the right shape for the problem. The trigger-source heterogeneity (real-time registration, scheduled pre-warm, monthly batch reconciliation, charity-care screening, refresh-on-coverage-change) is correctly handled by a single downstream pipeline with priority metadata. The payer-specific normalization layer (each payer has different field-format expectations, dependent-handling rules, and service-type-code support) is correctly held in a configuration table rather than in code. The connectivity-as-routing-layer-above-the-pipeline framing (clearinghouse for the long tail, direct connections for the high-volume payers) is the right operational pattern. The identity-resolution-on-the-response-side framing (the payer's match decision is a hint, not a verdict) is the recipe's strongest single architectural primitive and is correctly framed as the part of the architecture that needs the most attention. The persistence-keyed-on-inquiry-not-response framing prevents the conflation of two patient records that happen to match the same payer-side member. The freshness-two-regimes framing (past dates 1-year TTL, future dates 24-hour TTL) is the right policy baseline. The cohort-stratified accuracy monitoring framing is correctly elevated to "required here too."

The Honest Take is the recipe's most operationally pointed section. Six observations stand out and earn the recipe's voice: (1) the "we already have this, the clearinghouse handles it" trap framed as the missing-response-side-entity-resolution diagnosis (the connectivity layer is largely a solved problem; the response-side scoring, threshold, review-queue, and cohort-monitoring discipline is what is usually missing); (2) under-investing in the registration-flow latency budget framed as "build the cache layer first, before optimizing the deeper parts of the matcher"; (3) the equity dimension correctly framed ("equity in eligibility match is equity in access"), with the cohort enumeration (Hispanic surnames, Medicaid populations with frequent coverage churn, patients with name changes that did not propagate from one system to the other) and the "non-negotiable" closing; (4) the parsed-coverage-detail-as-substrate-for-half-a-dozen-downstream-workflows framing (revenue cycle, patient portal, care management, patient financial counseling); (5) the cache-freshness-policy-as-consequential framing with the per-payer-TTL-configuration prescription; (6) the X12-270/271-as-aged-well closing, with the "build the boring core first; layer FHIR-based connectivity as a parallel path rather than a replacement" prescription. The closing on No Surprises Act, price transparency, and the eligibility-match infrastructure being load-bearing for compliance is the right closing line.

That said, four correctness-and-compliance gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items. (1) The architecture invokes a real-time inquiry-submission path, a response-evaluation path, a `persist_and_propagate` operation, and a real-time eligibility-lookup read endpoint that mutate or expose the eligibility-match store consumed by practice management, revenue cycle, charity-care, care management, and patient portal; the identity-boundary checks on these paths are not specified at the architectural level. The recipe's own TODO at the AWS Implementation section names the gap (Finding S1) but the architecture text does not actually specify the boundary; the prose carries forward the chapter-wide pattern from 5.1 / 5.2 / 5.3. The consequence here is concrete: a misrouted persist call (an attacker-controlled `previous_canonical_hash` analog, a forged event from a compromised registration source, a clearinghouse reply replayed under a different patient's inquiry) silently links the wrong member-ID-and-coverage state to the wrong patient with downstream blast radius across every consumer of the eligibility store. (2) The `persist_and_propagate` operation performs five sequential writes (DynamoDB PutItem, Redis Set, S3 archive, EventBridge PutEvents, conditionally SQS SendMessage to the review queue) without `TransactWriteItems` wrapping or an outbox pattern; failures between the writes leave the eligibility store in a half-applied state. The recipe acknowledges this in an inline TODO that references the chapter pattern from 5.1 / 5.2 / 5.3 and correctly notes that "the regulatory consequence here is sharper than 5.1/5.2/5.3 because the eligibility outcome directly drives revenue-cycle (claim submission with wrong coverage = denial), charity-care (false-negative coverage = wrongful denial of eligibility), and patient financial responsibility (point-of-service collection)." The TODO names the gap; the architecture should architect the fix. (3) The cohort-stratified accuracy monitoring is invoked as "required here too" with explicit per-cohort enumeration (Hispanic surname components, Medicaid populations with frequent coverage churn and high address mobility, patients with name changes that did not propagate) but the operational threshold values, per-axis aggregation, and disparity-metric definitions are not specified in the architecture text (an inline TODO names the suggested values but they are not promoted). Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A2; the cohort-distribution stakes are higher here because eligibility-match disparities directly translate to charity-care eligibility errors, claim denials cascading into patient bills, and delayed care for the cohorts that can least afford it. (4) The Step 1 ingest pseudocode specifies `MessageGroupId=inquiry.payer_id` for the SQS FIFO queues, with the rationale "FIFO MessageGroupId per payer ensures inquiries for the same payer process in order, which matters for correctly handling subscriber-then-dependent sequenced inquiries." This is an architectural error with concrete throughput consequences. SQS FIFO queues have a 300 messages/sec per MessageGroupId baseline (3000/sec with batching and high-throughput mode). At a medium-volume institution doing 50K registrations/month plus pre-warm (~150K verifications/month), a single high-volume national payer (Aetna, Cigna, UnitedHealth) commonly produces concentrated load in the morning registration window; serializing all of that payer's inquiries through one MessageGroupId converts a horizontally-scalable workload into a sequential bottleneck, with measurable registration-flow latency consequences. The stated rationale (subscriber-then-dependent ordering) is also not generally required by payer eligibility APIs; subscriber and dependent inquiries are independently resolvable. The right MessageGroupId is finer-grained (per `(payer_id, subscriber_id)` for actual ordering needs, or per `inquiry_hash` for parallelism with idempotency).

Twelve chapter-wide patterns repeat (audit-log retention floor, IAM ARN scoping, identity-boundary checks, governance SLA on threshold re-calibration, idempotency and DLQ coverage, cross-recipe orchestration with 5.1 / 5.5 / 5.6 / 1.1 / 1.8 / 2.4 / 3.1, cohort PHI in CloudWatch dimensions, vendor BAA execution discipline for the clearinghouse and direct-payer connections, real-time API latency budget, API Gateway resource policy and WAF posture, Athena access control on the audit archive, backfill discipline). Most are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by counting U+2014 codepoints in the UTF-8 file). En dash count: 0 (verified by counting U+2013 codepoints in the UTF-8 file). 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: the opening 7:42 AM front-desk vignette, the running maybe-clauses ("maybe the card has the wrong member ID, maybe the patient is in a coverage lookup with her maiden name"), the Cigna "U1234567890-01" running example carried into the Expected Results JSON, the Maria Garcia-Lopez vs Maria Garcia search-match example as the right shape for the review-required outcome, the "build the boring core first" register from 5.2 carried into the X12-as-aged-well closing line. Parenthetical asides land well. The medium-sized health system at ~50K monthly registrations / ~150K total verifications scenario is operationally specific. The Variations and Extensions section (FHIR-based connectivity, charity-care multi-payer fanout, COB resolution, real-time pricing transparency, predictive eligibility refresh, patient-portal coverage self-service, clearinghouse-vs-direct optimization, eligibility-driven appointment scheduling, cross-organization eligibility sharing, active-learning threshold tuning, payer-quality scorecards) is well-scoped and frames each extension at the right grain.

Priority breakdown: 0 critical, 4 high, 9 medium, 11 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are localized correctness-and-compliance gaps; three surface in well-specified prose and TODO comments elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose, and one (the SQS FIFO MessageGroupId pattern) is a recipe-specific architectural error in the pseudocode that needs an explicit fix. None require structural rework of the recipe; the underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with the appropriate framing across multiple partner types: AWS BAA, clearinghouse BAA "and a Trading Partner Agreement specifying connectivity terms, transaction volumes, and SLAs," each direct-payer connection requiring its own trading partner agreement and BAA, and self-funded employer plans connecting through TPAs whose BAA covers the eligibility flow. The recipe correctly elevates partner BAA execution to the same tier as core architectural concerns.
- Customer-managed KMS keys for the S3 buckets, the DynamoDB tables, the ElastiCache cluster, and the Lambda log groups. Encryption-in-transit named explicitly: *"TLS 1.2 or higher for all in-transit traffic, including the clearinghouse and direct-payer connections. Mutual TLS where the partner requires it."*
- AWS Secrets Manager called out with the right framing: *"Many clearinghouses use mutual TLS or signed JWTs that rotate periodically; the secret store handles the rotation lifecycle without requiring redeploys."* The mTLS-and-rotation framing is the right operational discipline for partner credentials.
- CloudTrail data events on the eligibility-match table and on the audit S3 buckets. API Gateway and Lambda invocations logged.
- The "Per-Lambda least-privilege" framing in the Prerequisites IAM Permissions row, with the explicit "Never use `*` actions or `*` resources in production" admonition.
- Synthetic data labeling enforced in the Sample Data row: *"Never use real patient or member data in development environments."* The CAQH CORE certification suite and clearinghouse test endpoints are correctly named as the right test substrates.
- The audit archive's regulatory framing: *"the raw 270/271 payloads are retained for the regulatory audit window"* with the recipe correctly elevating the raw 271 to "the legal record of what the payer told you" in the Step 3D pseudocode.
- The eligibility-store-as-substrate-for-half-a-dozen-downstream-workflows framing in the Honest Take. Revenue cycle, patient portal, care management, patient financial counseling all consume the parsed coverage detail; the access-control posture must reflect this distributed-consumption pattern.
- The architecture correctly notes that "the patient_id is a partner-shared identifier under BAA, not a public identifier" in the inline TODO at the Prerequisites BAA row, prefiguring the right framing for the de-identification posture at the partner boundary.

### Finding S1: Inquiry-Submission, Response-Evaluation, Persist-and-Propagate, and Eligibility-Lookup Read Endpoint Lack Identity-Boundary Specification

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization, regulatory)
- **Location:** Architecture diagram shows the real-time inquiry path `T1 (Real-time Registration) -> Q1 (SQS realtime) -> L1 (normalize-inquiry) -> L2 (submit-inquiry) -> CH1/P1/P2 -> L3 (evaluate-response) -> L4 (persist-match)`; the API surface `AG1 (API Gateway) -> CG1 (Cognito) -> L5 (api-handler) -> RC1 / D1 / Q1`; the cache-invalidation path `EB1 -> L6 (invalidate-cache) -> RC1 / Q2`. Step 1 pseudocode `ingest_eligibility_trigger(trigger_event)` reads `trigger_event.patient_id` and `trigger_event.payer_id` directly. Step 5 pseudocode `persist_and_propagate(inquiry, match_outcome)` writes the eligibility outcome and emits the EventBridge event. The recipe's own TODO at the AWS Implementation section (referenced as "Expert review S1 (HIGH)") names the gap and prescribes the fix at chapter-pattern grain but the architecture text does not actually specify the boundary.
- **Problem:** The recipe specifies the eligibility pipeline at flow-and-service granularity but is silent on the identity-boundary policy that controls who can invoke each path and what proves the caller is authorized to act on a particular patient record. The chapter-wide pattern from 4.4 through 5.3 has converged on a structured identity-boundary specification; Recipe 5.4 inherits the concern with five concrete attack surfaces:

  1. **The trigger-ingest path is unauthenticated at the architectural level.** `ingest_eligibility_trigger(trigger_event)` reads `trigger_event.patient_id`, `trigger_event.payer_id`, and `trigger_event.service_date` directly. A forged trigger event (an attacker-controlled `patient_id`, a compromised registration source replaying old events, an event with a `payer_id` swapped to a different payer the patient does not have coverage with) silently produces a 270 inquiry to the wrong payer, exposes the patient's demographics to a payer the patient has no relationship with under the BAA flow, and (in the failure case) populates the eligibility-match store with a NOT_FOUND outcome that cascades into a denied claim or a charity-care eligibility error. The producer-signed envelope pattern (the chapter pattern from 4.4-5.3: `source_system`, `source_record_id`, `event_id`, `signed_payload`, `signature` with the consumer-side signature validation) is not specified here. Trigger source classification is named (`registration_event`, `scheduled_pre_warm`, `batch_reconciliation`, `charity_care_screening`, `coverage_change_refresh`) but the per-source authentication context and rate limit are not.

  2. **The response-evaluation Lambda accepts inbound clearinghouse and direct-payer responses without specified signature verification or replay-rejection.** The 271 response is the substrate the matcher trusts to determine identity match and coverage state. A replayed 271 (a stored response from a prior inquiry submitted under a different patient's inquiry hash, an attacker-controlled response that matches a recent 270's control number, a forged response that bypasses the clearinghouse's content rules) silently produces a wrong eligibility outcome. The recipe's own TODO acknowledges this gap and prescribes "signature verification on the 271 payload from each clearinghouse / direct-connection partner, with replay-rejection on (control_number, transaction_set_id) to prevent stored-271 replay attacks" but the architecture text does not include the specification.

  3. **`persist_and_propagate` is the recipe's most security-sensitive write path.** It mutates the `eligibility-match` DynamoDB table and the ElastiCache layer that is read by every downstream consumer. A misrouted persist call (an attacker-controlled `matched_member_id`, a forged event from a compromised response-evaluation Lambda, an attacker-controlled `match_confidence` value claiming a high score that was not actually computed) silently links the wrong member ID to the wrong patient with downstream consequences: the practice management system displays the wrong patient's coverage at the front desk; revenue cycle submits claims with the wrong member ID and gets denials; charity-care workflow makes the wrong determination; the patient portal shows the wrong benefits to the patient. The TODO acknowledges this gap and prescribes "validate the matched_member_id against the inquiry payload (the response must be for the same payer the inquiry targeted) and reject mismatches with logged metric and DLQ routing" but the architecture text does not include the specification.

  4. **The eligibility-lookup read endpoint exposes parsed coverage state and (potentially) raw 271 audit payloads.** The architecture says "API Gateway provides authentication via Cognito or via mutual TLS for system-to-system clients" but the read-side authorization (which caller can see which patient's coverage; the privacy-suppression-on-read pattern for patients with privacy flags; the separate access-controlled path for the raw 271 payload) is not specified. A clinical-context-query that returns the parsed coverage view is appropriate for clinical and revenue-cycle staff; a query that returns the raw 271 payload (including the full segment-level detail, the COB indicators, and any informational segments the payer chose to include) should be restricted to payer-relations and audit teams. Without architectural specification, a single API endpoint serves both views to all authenticated callers.

  5. **The cache-invalidation path mutates the cache and re-queues inquiries on patient-merge events with `payer_id: "*"`.** A misrouted invalidation event (a forged patient-merge event from a compromised 5.1 source, an attacker-controlled `merged_into_patient_id` value) could cascade into mass invalidations and re-inquiries that exceed the clearinghouse's rate limit, producing a self-inflicted denial-of-service on the eligibility infrastructure plus per-inquiry charges. The cross-recipe event consumption from 5.1 / 5.3 / 5.5 / 5.6 should specify the producer-signed envelope and the acceptance criteria the invalidation Lambda enforces.

  6. **The HIPAA Privacy Rule's minimum-necessary requirement and the No Surprises Act's good-faith-estimate regime both depend on the identity boundary.** A read of the eligibility-match store that exposes financial-responsibility detail to a caller without a need-to-know is a minimum-necessary violation; a write that succeeds without proving the calling event came from an authenticated source does not have the audit-trail attribution that compliance requires.

  Same regulatory ground as Recipe 5.1 / 5.2 / 5.3 Finding S1; the chapter editor should consolidate identity-check guidance into a chapter preface in the next pass since the same finding now applies across 4.4-5.4. For 5.4 specifically, the eligibility-store-as-anchor consequence (downstream consumers in PMS, revenue cycle, charity-care, care management, patient portal, plus cross-recipe consumers in 5.1 / 5.5 / 5.6, all consume the eligibility outcome) earns the HIGH severity.

- **Fix:** Promote the recipe's own TODO content into the architecture text. Specify the identity-boundary policy and the rejection semantics at the architectural level the chapter has converged on. For the trigger-ingest path, specify that the inbound event carries a producer-signed envelope (`source_system`, `source_record_id`, `event_id`, `signed_payload`, `signature`); the normalize-inquiry Lambda validates the signature against the producer's known signing key (rotated per the institutional secret-rotation policy), validates the source_system is in the allow-list, validates the event_id is unique within a sliding window (idempotency), and rejects events that fail any of these checks with a logged metric and routing to the rejected-events DLQ. Per-source rate limits are specified so a runaway batch-reconciliation job cannot consume the registration-flow capacity.

  For the response-evaluation Lambda, specify the signature verification on the 271 payload from each clearinghouse / direct-connection partner (mTLS at the connection layer plus a payload-level check against the partner's per-transaction control numbers), with replay-rejection on `(interchange_control_number, transaction_set_control_number, sender_id)`. The recipe text correctly identifies that "the raw 271 is the legal record of what the payer told you; preserve it exactly as received"; this needs to be paired with the signature-and-replay-rejection check that establishes the 271's provenance.

  For `persist_and_propagate`, specify the authorization context:

  ```
  FUNCTION persist_and_propagate(inquiry, match_outcome, caller_context):
      // caller_context.invocation_source is one of:
      //   "evaluate_response_real_time": the response-evaluation
      //                                   Lambda invoked from the
      //                                   real-time inquiry pipeline
      //   "evaluate_response_async":      the response-evaluation
      //                                   Lambda invoked from the
      //                                   pre-warm pipeline
      //   "batch_reconciliation":         the monthly Glue/Step
      //                                   Functions reconciliation
      //                                   workflow
      //   "review_decision":              the review-queue Lambda
      //                                   after a human review
      //
      // Validate the caller's role matches the invocation_source:
      caller_role = current_lambda_execution_role()
      IF NOT caller_role_matches_invocation_source(caller_role,
                                                     caller_context.invocation_source):
          REJECT with metric and DLQ routing

      // Validate the matched_member_id is consistent with the
      // inquiry payload (the response must be for the same payer
      // the inquiry targeted):
      IF match_outcome.status == "MATCHED":
          IF inquiry.normalized.payer_id != match_outcome.responding_payer_id:
              LOG("payer mismatch", ...)
              emit_metric("persist_payer_mismatch", value = 1)
              REJECT
  ```

  For the eligibility-lookup read endpoint, specify the privacy-suppression-on-read pattern (a query for a patient_id with the suppression flag returns the same shape as a query for an unmatched patient so the absence-as-signal channel is closed), the audit logging on every read, and the separate access-controlled path for the raw 271 audit payload (clinical and revenue-cycle staff need the parsed coverage view; only the payer-relations and audit teams need the raw 271). Specify the per-caller authorization-to-patient-id binding enforced at the API Gateway authorizer or the Lambda layer.

  Reference Recipe 5.1 / 5.2 / 5.3 Finding S1 as the chapter pattern.

### Finding S2: Audit-Log Retention Specified as "Per Institution's Records-Retention Policy" Without Architectural Floor (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, audit, forensic)
- **Location:** Prerequisites CloudTrail row: *"Enabled with data events on the eligibility-match table and on the audit S3 buckets. API Gateway and Lambda invocations logged. CloudTrail logs encrypted with KMS and retained per the institution's records-retention policy."* The recipe's own inline TODO at the same location (referenced as "Expert review S2 (MEDIUM)") names the gap and prescribes the chapter-pattern fix but the architecture text does not include the specification.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding S2. The TODO correctly identifies that the floor should be the longest of (HIPAA 7-year minimum, 10-year Medicare-claims retention where applicable, the institution's documented eligibility-data retention policy, the value-based-care contract retention requirement, and any state-specific Medicaid retention requirement), with Object Lock in Compliance mode on a dedicated audit bucket and CloudTrail data events forwarded to a dedicated audit AWS account. The architecture should promote the TODO content into the prose. Three concrete consequences:

  1. **The Medicare claims retention floor is recipe-specific.** Eligibility-verification records are referenced in claims-and-appeals processes; for Medicare Advantage and traditional Medicare claims, CMS's retention requirement is 10 years for certain claim-related records. The retention floor for the eligibility audit substrate (the raw 270/271 payloads, the parsed match outcomes, the review-queue decisions) should be at minimum 10 years for institutions participating in Medicare programs, longer where state Medicaid retention rules apply.

  2. **The S3 Object Lock posture for the raw 270/271 archive is not specified.** The raw 271 is "the legal record of what the payer told you" per Step 3D pseudocode; immutability requires Object Lock in Compliance mode. Without architectural specification, the implementation may use Standard storage with versioning, which is mutable by privileged users.

  3. **CloudTrail data event volume is bounded but non-trivial.** Every read of `eligibility-match` produces a data event; for a 500K-patient system with frequent PMS, revenue-cycle, and patient-portal reads, this is potentially tens of millions of CloudTrail events per month.

- **Fix:** Replace the "per the institution's records-retention policy" framing with an explicit floor in the CloudTrail and Audit-Trail-Retention paragraphs, mirroring the chapter pattern from 5.1 / 5.2 / 5.3:

  *"Audit-log retention is the longest of: 7 years (HIPAA records-retention minimum), 10 years (Medicare claims-related retention where applicable), the institution's documented eligibility-data retention policy, the value-based-care contract retention requirement (where applicable), and any state-specific Medicaid retention requirement. Audit logs (the raw 270/271 payloads, the parsed match outcomes, the review-queue decisions) are stored in a dedicated S3 bucket with Object Lock in Compliance mode for immutability and a lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days for cost optimization. CloudTrail data events are forwarded to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. The retention floor is enforced at the bucket-policy and Object-Lock-configuration level, not at application logic."*

### Finding S3: Clearinghouse and Direct-Payer Data-Handling Expectations Named in TODO but Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Security (third-party-risk, PHI flow)
- **Location:** Prerequisites BAA row and the recipe's inline TODO (referenced as "Expert review S3 (MEDIUM)"). The TODO names the contractual expectations but the architecture text does not include the specification.
- **Problem:** The recipe correctly identifies that the clearinghouse and each direct-payer connection see PHI (the 270 inquiry payload contains the patient's demographics and the patient_id) and must sign BAAs with trading partner agreements. The TODO names the data-handling expectations but the architecture text does not specify what the institution should require contractually or verify operationally. Three concrete consequences:

  1. **The PHI-in-flight content is precisely the patient demographics plus the patient_id.** The 270 inquiry includes `first_name`, `last_name`, `dob`, `sex`, `address`, optionally `ssn`, plus the patient's last-known member ID and subscriber relationship. The patient_id is the institution's internal identifier shared with the partner under BAA. The architecture should specify whether the partner retains the patient_id-to-demographics mapping, for how long, and with what controls.

  2. **Clearinghouse retention policies vary by partner and by tier.** Typical clearinghouse retention is 7 years for HIPAA audit purposes (separate from operational caches, which are typically days-to-weeks). Some clearinghouses retain submitted demographics indefinitely for accuracy improvement and fraud detection; others retain only the hashed inquiry; others delete after a documented operational window. The architecture should specify the maximum acceptable retention and require the partner to delete on a documented cadence as a contractual obligation.

  3. **Sub-processor disclosure for self-funded TPAs is layered.** A self-funded employer plan administered by a TPA goes through the TPA's infrastructure, which may itself use cloud providers, sub-vendors for connectivity, and analytic processors. Each sub-processor is a PHI-exposure surface. The BAA should require sub-processor disclosure and the institution's right to object.

- **Fix:** Promote the TODO content into the BAA row:

  *"Clearinghouse and direct-payer BAA terms should specify: (a) the partner will not retain submitted patient data beyond a documented operational window (typical clearinghouse retention is 7 years for HIPAA audit, separate from operational caches that are typically days-to-weeks); (b) the partner will disclose all sub-processors that may handle PHI (including cloud-infrastructure providers, sub-vendors for specific payer connectivity, sub-vendors for analytics); (c) the partner will notify the institution within a documented window (typically 24-72 hours) of any data incident affecting institutional data; (d) the partner agreement specifies the institution's right to audit the partner's controls (typically annually). The patient_id flowing in the 270 inquiry is a partner-shared identifier under BAA, not a public identifier; the architecture treats it with the same care as the demographic fields it accompanies."*

  Add an inline comment at the inquiry-submission call site (Step 3) explaining the de-identification posture (the 270 contains the full demographics and the patient_id; the patient_id is shared with the partner under BAA for response correlation, not used as a public identifier).

### Finding S4: Review-Queue Decision Audit Posture Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (privacy, forensic-traceability)
- **Location:** Step 5F pseudocode in `persist_and_propagate`: *"IF match_outcome.status == 'REVIEW_REQUIRED': SQS.SendMessage('eligibility-review-queue', ...)"*. The recipe's inline TODO (referenced as "Expert review S4 (MEDIUM)") names the gap and specifies the audit fields but the architecture text does not include the specification. The "Why This Isn't Production-Ready" review queue tooling paragraph correctly elevates the queue to "the system that the operational staff will spend hours per day in" but does not specify the audit posture.
- **Problem:** The matcher's value depends on the review queue's quality. Reviewers make decisions that mutate the eligibility-match store via the same `persist_and_propagate` write path that auto-attach uses; the audit trail must capture the reviewer's identity, decision, reasoning, and the configuration version at decision time. Three concrete consequences:

  1. **Forensic reconstruction of wrong matches is impossible without reviewer-decision audit.** When a wrong eligibility match later produces a denied claim or a charity-care eligibility error and the trail leads back to a reviewer's decision, the audit trail should record who decided what, why, and against which configuration. Without this, the institution cannot defend the decision to a regulator and cannot identify systematic reviewer biases.

  2. **The reviewer's stated reasoning supports active learning.** The "active-learning-driven threshold tuning" variation depends on the reviewer's labels feeding back into threshold re-calibration; without a structured reasoning capture, the labels are decisions without context, which is less useful for re-training.

  3. **Conflict-of-interest cases are not addressed.** A reviewer who is themselves the patient (or a relative) should not adjudicate the eligibility match for their own coverage; the chapter pattern from 5.1 / 5.3 applies here.

- **Fix:** Promote the TODO content into the architecture text:

  *"Every review-queue decision records: the reviewer's identity (with appropriate authentication), the decision (accept the match, reject the match, escalate, request additional information from the patient), the reviewer's stated reason, the timestamp, the configuration version active at the time, the threshold values active at decision time, and any reviewer-supplied additional demographic context (e.g., 'patient confirmed maiden name was Garcia, married name is Smith'). The audit trail supports forensic reconstruction when a wrong match is later traced back to a reviewer decision, and it supports the periodic gold-set re-evaluation that catches systematic reviewer biases. Conflict-of-interest cases (a reviewer adjudicating an eligibility match for themselves or a relative) are surfaced by a pre-assignment check against an institutional conflict-of-interest registry; conflicted cases route to a different reviewer."*

### Finding S5: Cohort PHI in CloudWatch Metric Dimensions (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Step 4G pseudocode: *"emit_cloudwatch_metric_with_cohort('eligibility_match_outcome', match_outcome.status, cohort_bucket)"*. The General Architecture Pattern paragraph naming per-cohort match success rate and per-cohort review-queue rate. The recipe's inline TODO (referenced as "Expert review S5 (LOW)") names the bucketed-non-reversible-cohort-label pattern.
- **Problem:** Same chapter-wide pattern as 4.4-5.3 Finding S5. The TODO already specifies the right pattern (cohort_bucket = A, B, C, D, E, unknown).
- **Fix:** Promote the TODO content into the CloudWatch paragraph: *"Cohort dimensions on metrics use bucketed, non-reversible cohort labels (cohort_bucket = A, B, C, D, E, unknown) from the institutional cohort registry rather than raw demographic attributes; the cohort-label-to-attribute mapping lives in a separate access-controlled table loaded only at dashboard-render time."*

### Finding S6: IAM "Never `*` Actions or `*` Resources in Production" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row. The recipe's inline TODO (referenced as "Expert review S6 (LOW)") names the chapter pattern and specifies the scoped ARN examples but the architecture text does not include the specification.
- **Problem:** Same finding as Recipe 4.1-5.3.
- **Fix:** Inline scoped ARN examples for the highest-stakes actions: `dynamodb:UpdateItem` on `arn:aws:dynamodb:<region>:<account>:table/eligibility-match`; `s3:PutObject` on `arn:aws:s3:::<env>-eligibility-raw/audit/*`; `events:PutEvents` on `arn:aws:events:<region>:<account>:event-bus/eligibility-events`; `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:<region>:<account>:secret:clearinghouse/*`. Or consolidate into the chapter preface.

### Finding S7: Patient-Portal Coverage Self-Service Disclosure Posture Not Addressed

- **Severity:** LOW
- **Expert:** Security (forward-looking, disclosure-policy)
- **Location:** Variations and Extensions: *"Patient-portal coverage self-service. Build the portal feature that shows patients their on-file coverage with a confirm-or-update flow."* And the Honest Take's *"invest more heavily in the patient-portal eligibility-self-service flow."*
- **Problem:** Sibling to Recipe 5.1 / 5.2 / 5.3 Finding S5 / S7. Surfacing institution-held coverage data back to the patient is itself a disclosure event under some state laws, particularly when the on-file coverage differs from the patient's expectation (the institution has a stale coverage record, the institution has multiple coverages for the patient and the portal exposes which one is primary, the institution has financial-responsibility detail that includes deductible status). The variation should name the disclosure-policy gate.
- **Fix:** Add a sentence to the Patient-Portal Coverage Self-Service variation: *"Before surfacing institution-held coverage and financial-responsibility detail back to the patient, the institution should review the disclosure policy: data sourced from the patient's own portal updates is appropriate to display verbatim; data sourced from registration-clerk entry, the 271 response, or an HIE referral carries separate provenance; financial-responsibility detail (deductible-remaining, out-of-pocket-max-status, COB indicators) may have separate disclosure-and-consent requirements that the policy framework needs to address before the self-service feature surfaces it."*

## Architecture Expert Review

### What's Done Well

- **Six-stage pipeline shape is correct.** Ingest the trigger, normalize the patient side, route the inquiry, evaluate and resolve identity, persist with provenance, react to drift maps cleanly to the operational reality. The trigger-source heterogeneity (real-time, scheduled pre-warm, batch reconciliation, charity-care screening, refresh-on-coverage-change) is correctly handled by a single downstream pipeline with priority metadata.
- **Identity-resolution-on-the-response-side framing.** The recipe correctly elevates the response-side scoring of search-match candidates to "the part of the architecture that needs the most attention" in the Honest Take. This is the recipe's strongest single architectural primitive: the connectivity layer (X12 270/271 through a clearinghouse) is largely a solved problem; the entity-resolution work happens after the 271 comes back.
- **Cache-and-async pattern decouples registration latency from the underlying 270/271 round-trip.** The Honest Take correctly identifies that "a real-time eligibility lookup that takes 6 seconds at the front desk has cascading consequences" and prescribes "build the cache layer first, before optimizing the deeper parts of the matcher." The architecture's three-tier cache-DynamoDB-async pattern (sub-10ms cache hit, sub-50ms DynamoDB hit, sub-200ms async-trigger fallback) is the right pattern for the registration-flow latency budget.
- **Two SQS queues for priority isolation.** A high-priority queue for real-time registration and a standard queue for pre-warm, batch reconciliation, and refresh prevents a flood of pre-warm inquiries from delaying the real-time path. The architecture correctly recognizes that the real-time path cannot be starved by background workloads.
- **Per-payer normalization in a configuration table, not in code.** The architecture correctly holds payer-specific rules (last name without suffix, DOB in YYYY-MM-DD, member ID without dashes, person-code requirements) in a configuration table so adjustments don't require deploys and can be governed and reviewed.
- **Connectivity as a routing layer above the pipeline.** The hybrid clearinghouse-plus-direct-connection pattern with the routing decision happening above the normalize-and-evaluate layer means adding a new direct connection or switching clearinghouses does not change the rest of the pipeline. The architecture treats connectivity as swappable.
- **Persistence keyed on inquiry, not on response.** The architecture correctly notes that "two patients registered on the same day for the same service date with overlapping demographics could produce the same payer-side member; the system keys on the requesting (patient_id, payer_id, service_date) so the eligibility outcome is associated with the patient who triggered the inquiry, not with the payer-side member ID." This prevents the conflation of two patient records that happen to match the same payer-side member.
- **Freshness has two regimes.** Service-date-past TTL = 1 year (long enough for retroactive corrections to surface); service-date-future TTL = 24 hours (balancing freshness against volume). The two-regime pattern is the right policy baseline.
- **Cache invalidation pipeline is explicit and event-driven.** Six change-event sources (payer-roster-delta, claim-status-277, 834-enrollment-file, patient-merge-event from 5.1, address-change from 5.3, plus the timer-driven cache TTL) are correctly enumerated. The invalidation Lambda fans out to cache deletion, DynamoDB flag setting, EventBridge invalidation events, and re-queue for async re-resolution.
- **Step Functions partitioning by workflow.** Real-time-inquiry workflow (latency budget calibrated to registration), scheduled pre-warm workflow (off-peak processing), batch reconciliation workflow (monthly cadence) is the right separation of concerns.
- **The "build the boring core first" framing in the Honest Take.** The architecture commits to X12 270/271 through a clearinghouse with proper response-side entity resolution as the primary path and treats FHIR-based connectivity as a parallel path. This is the right trade between regulatory baseline coverage and forward-looking infrastructure.
- **The "Why This Isn't Production-Ready" section names twelve gaps.** Clearinghouse selection, per-payer configuration governance, threshold calibration, review queue tooling, COB logic, network status integration, patient-facing portal view, initial backfill, idempotency and retry, audit retention, clearinghouse cost monitoring, and operational ownership. The breadth is appropriate for a Medium-tier recipe.

### Finding A1: persist_and_propagate Is Not Atomic; Sequential DynamoDB / Cache / S3 / EventBridge / SQS Operations Leave Half-Updated State on Partial Failure

- **Severity:** HIGH
- **Expert:** Architecture (correctness, distributed-systems consistency, regulatory)
- **Location:** Step 5 pseudocode `persist_and_propagate(inquiry, match_outcome)` performs `DynamoDB.GetItem` (read previous), `DynamoDB.PutItem` (write current), `Redis.Set` (cache write), `write_to_s3` (archive), `EventBridge.PutEvents` (emit on change), and conditionally `SQS.SendMessage` (review-queue routing). The recipe's own inline TODO at Step 5A explicitly names the gap: *"Wrap the DynamoDB write, the cache write, the S3 archive, and the EventBridge emit in a TransactWriteItems plus an outbox row drained by a separate Lambda or DynamoDB Streams consumer so partial failures do not leave the eligibility store out of sync with downstream consumers. Regulatory consequence here is sharper than 5.1/5.2/5.3 because the eligibility outcome directly drives revenue-cycle (claim submission with wrong coverage = denial), charity-care (false-negative coverage = wrongful denial of eligibility), and patient financial responsibility (point-of-service collection). Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A1."*
- **Problem:** The chapter pattern from 5.1 Finding A1 / 5.2 Finding A1 / 5.3 Finding A1 applies. Sequential operations across DynamoDB, ElastiCache, S3, EventBridge, and SQS each have independent failure modes (Lambda timeout between operations, IAM permission expiry mid-call, cross-region replication lag, EventBridge throttling, ElastiCache connection drop, SQS quota throttling). Concrete failure scenarios:

  1. **DynamoDB write succeeds, cache write fails.** The eligibility-match store has the new outcome; the cache continues to serve the previous outcome (or no entry, falling through to DynamoDB on the next read). For a future-service-date entry, the cache lag is bounded by the 24-hour TTL; for a real-time registration lookup happening seconds after the persist, the cache may still serve stale or absent data, defeating the cache-hit-rate benchmark the architecture claims (70-85%).

  2. **DynamoDB and cache writes succeed, S3 archive fails.** The match is durable in the operational data plane; the audit substrate has no entry. The "raw 270/271 payloads are retained for the regulatory audit window" claim is silently false for this match. A subsequent compliance reconstruction (a regulator asks the institution to prove what eligibility decision was made on date X for patient Y, with what 271 response from which payer) cannot be defended.

  3. **DynamoDB, cache, and S3 writes succeed, EventBridge emit fails.** The match is durable, the audit is recorded, but downstream consumers (PMS front-desk display, revenue cycle claim coverage refresh, charity-care workflow, care management, patient portal, cross-recipe consumers in 5.1 and 5.5) never receive the change event and continue to operate on the previous outcome. The PMS continues to display the stale coverage at the front desk; revenue cycle continues to submit claims with the previous member ID; the patient portal shows the stale benefits view. The downstream blast radius is wider here than in 5.1/5.2/5.3 because the eligibility-match store has more cross-system consumers.

  4. **For `REVIEW_REQUIRED` outcomes: DynamoDB / cache / S3 / EventBridge succeed, SQS SendMessage to the review queue fails.** The match is recorded as REVIEW_REQUIRED but never appears in the reviewer's queue. The case is silently lost: no reviewer ever sees it; the registration completes with the REVIEW_REQUIRED status; the downstream consumers see the REVIEW_REQUIRED via the EventBridge event but have no path to resolution. For a real-time registration, this means the patient leaves the front desk with an unresolved coverage status and the operational tail-handling never closes the loop.

  5. **The `re_inquiry` re-resolution path in `invalidate_on_coverage_change` has the same problem.** Step 6B writes the cache deletion and the DynamoDB requires_reinquiry flag; Step 6C emits the invalidation event; Step 6D enqueues the re-inquiry. A failure mid-sequence leaves the cache evicted but the re-inquiry never enqueued, so the next read for the future-service-date hits DynamoDB, sees `requires_reinquiry: true`, and has no mechanism to actually trigger the re-inquiry until the next coverage-change event happens to fire.

  The regulatory consequence here is sharper than 5.1/5.2/5.3 because the eligibility outcome directly drives three compliance-visible workflows: revenue cycle (claim submission with wrong coverage produces a denial that is auditable), charity-care (false-negative coverage produces a wrongful denial of eligibility under federal-and-state charity-care rules), and patient financial responsibility (point-of-service collection of the wrong amount produces patient billing complaints and possible NSA-related complaints). The recipe's own TODO correctly names this as a sharper consequence than 5.1/5.2/5.3.

- **Fix:** Specify the transactional pattern in the architecture pattern paragraph and rewrite the pseudocode for Step 5. Per the chapter pattern from 5.3 Finding A1:

  ```
  FUNCTION persist_and_propagate(inquiry, match_outcome):
      previous = DynamoDB.GetItem("eligibility-match",
          key={patient_id: inquiry.patient_id,
               payer_payer_service_date_sort:
                   "{payer_id}#{service_date}"})

      // Compose a TransactWriteItems request that updates the
      // eligibility-match row and writes an outbox row for the
      // side effects. The transaction is all-or-nothing.
      DynamoDB.TransactWriteItems([
          {
              Put: {
                  TableName: "eligibility-match",
                  Item: { ... full match outcome ... }
              }
          },
          {
              Put: {
                  TableName: "eligibility-outbox",
                  Item: {
                      outbox_id: uuid(),
                      event_type: "eligibility_resolved",
                      payload: { patient_id, payer_id, service_date,
                                  outcome_status, matched_member_id, ... },
                      requires_review_queue: (match_outcome.status
                                                  == "REVIEW_REQUIRED"),
                      created_at: current UTC timestamp,
                      status: "PENDING"
                  }
              }
          }
      ])
      // A separate outbox-drainer Lambda (triggered by DynamoDB
      // Streams on the eligibility-outbox table) handles the
      // cache write, the S3 archive, the EventBridge emit, and
      // the conditional SQS SendMessage to the review queue.
      // The drainer is idempotent at outbox_id and marks rows
      // COMPLETED only after all downstream effects succeed;
      // failures route to a DLQ for operator inspection.
      // CloudWatch alarm fires when the pending row age exceeds
      // an SLA (typically minutes for eligibility events given
      // the registration-flow latency budget).
  ```

  For Step 6 (`invalidate_on_coverage_change`), wrap the cache deletion, the DynamoDB UpdateItem (requires_reinquiry flag), the EventBridge invalidation emit, and the SQS re-queue in the same outbox pattern. The cache-deletion-without-re-inquiry-enqueue partial-failure mode is the most consequential because it produces a silent cache miss that DynamoDB cannot resolve.

  Reference Recipe 5.1 / 5.2 / 5.3 Finding A1 as the chapter-wide pattern. The chapter editor should consolidate the outbox-pattern guidance into a chapter preface in the next pass.

### Finding A2: Cohort-Stratified Accuracy Thresholds and Metric Definitions Referenced as "Required Here Too" but Undefined (Chapter-Wide Pattern)

- **Severity:** HIGH
- **Expert:** Architecture (operational rigor, equity instrumentation)
- **Location:** General Architecture Pattern paragraph: *"Cohort-stratified accuracy monitoring is required here too. Eligibility-match accuracy is not uniform across patient cohorts. Payers' member rolls have systematic data-quality patterns that disadvantage certain cohorts (Hispanic surname components handled inconsistently, Medicaid populations with higher address change rates, patients with name changes that did not propagate from one system to the other). The downstream consequences (charity-care eligibility errors, claim denials, delayed care) are concrete equity issues. Per-cohort match success rate, per-cohort search-match-vs-primary-key-match distribution, and per-cohort review-queue rate are all metrics worth tracking with disparity thresholds."* The Honest Take's *"equity in eligibility match is equity in access ... non-negotiable"* framing. The recipe's inline TODO at the General Architecture Pattern (referenced as "Expert review A2 (HIGH)") names the suggested thresholds but the architecture text does not promote them.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A2 / 4.10 Finding A1. The recipe explicitly inherits the rigor from 5.1 / 5.2 / 5.3 ("required here too") and the inline TODO names the suggested values (match-success disparity > 0.05 = MEDIUM, review-queue disparity > 0.05 = MEDIUM, downstream denial disparity > 0.03 = HIGH) but the architecture pattern does not specify them in the prose. Five concrete gaps:

  1. **The cohort axis enumeration that the metric must aggregate over is not specified.** Hispanic surnames, Medicaid populations with frequent coverage churn, patients with name changes that did not propagate, are named in the prose; the architecture should specify the institutional cohort registry as the source of truth and require the metric pipeline to aggregate over the registry's cohort axes rather than over an ad-hoc list (the inline TODO names this but the architecture does not).

  2. **The disparity calculation method is not specified.** "Disparity threshold of 0.05" can mean absolute difference between best and worst cohort, or ratio, or maximum deviation from the population mean. The three calculations produce different alerting behavior.

  3. **The metric pipeline's emission cadence is not specified.** Match-success rate moves slowly; review-queue rate can shift quickly when payer-side data quality changes (a payer's overnight update introduces a new format that the matcher's normalization layer does not handle). The cadence should be specified per-metric.

  4. **The downstream denial-disparity metric is recipe-specific and consequential.** Eligibility-match disparities translate to claim-denial disparities, which translate to patient-billing disparities. The TODO suggests a 0.03 HIGH threshold for downstream denial disparity, which is the right metric but the architecture does not promote it.

  5. **The remediation pathway is not architected.** A threshold crossing should trigger a documented sequence: alert routing (revenue-cycle and data-quality teams), investigation (per-cohort threshold tuning, payer-specific normalization rules, registration-staff training on data capture for affected cohorts), and post-mortem retention. The TODO names the SLA (5-business-day) and the cohort-disparity ledger but the architecture does not include these in the prose.

  The cohort-distribution stakes are higher here than in 5.1/5.2 because eligibility-match disparities directly translate to charity-care eligibility errors (the cohorts most likely to qualify for charity care are also the cohorts most likely to match poorly), claim denials cascading into patient bills the patients can least afford, and delayed care.

- **Fix:** Specify in the General Architecture Pattern paragraph the operational thresholds, the per-axis aggregation policy, and the remediation pathway, mirroring the chapter pattern from 5.1 / 5.2 / 5.3 Finding A2:

  *"Cohort-stratified accuracy monitoring uses the institutional cohort registry as the source of truth for cohort axes (no ad-hoc enumeration in code). Metrics: (a) per-cohort eligibility-match success rate (percent of inquiries returning AUTO_ACCEPT) computed weekly; (b) per-cohort review-queue rate (percent routed to human review) computed weekly; (c) per-cohort search-match-vs-primary-key distribution computed weekly; (d) per-cohort claim-denial-for-eligibility rate (downstream metric tying matcher quality to revenue impact) computed monthly. Disparity calculation: absolute difference between the cohort with the highest rate and the cohort with the lowest rate, computed per-metric per-cycle. Alarm thresholds: match-success disparity > 0.05 = MEDIUM; review-queue disparity > 0.05 = MEDIUM; downstream denial disparity > 0.03 = HIGH; any disparity > 2x the threshold = HIGH. Alarms route to the revenue-cycle and data-quality teams with a 5-business-day SLA for the first investigation report; the post-mortem and any remediation (per-cohort threshold tuning, payer-specific normalization rules, registration-staff training on data capture for affected cohorts) is documented in the cohort-disparity ledger and reviewed quarterly by the eligibility-data-quality steering committee."*

  Reference Recipe 5.1 / 5.2 / 5.3 Finding A2 as the chapter-wide pattern.

### Finding A3: SQS FIFO MessageGroupId per Payer Serializes a Horizontally-Scalable Workload Through a Per-Payer Bottleneck

- **Severity:** HIGH
- **Expert:** Architecture (throughput, correctness of stated rationale, registration-flow latency)
- **Location:** Step 1 pseudocode `ingest_eligibility_trigger`:

  ```
  SQS.SendMessage(queue_url, inquiry,
      MessageDeduplicationId=inquiry.inquiry_hash,
      MessageGroupId=inquiry.payer_id)
          // FIFO MessageGroupId per payer ensures inquiries
          // for the same payer process in order, which matters
          // for correctly handling subscriber-then-dependent
          // sequenced inquiries.
  ```

- **Problem:** This is an architectural error in the pseudocode with concrete throughput consequences and an incorrect stated rationale. Three concrete issues:

  1. **SQS FIFO has per-MessageGroupId throughput limits that converge to a sequential bottleneck.** Standard FIFO queues support up to 300 messages/second per MessageGroupId. With high-throughput-mode-for-FIFO and batching, a queue can reach 9,000 messages/second total, but the per-MessageGroupId throughput is still bounded. Setting `MessageGroupId=inquiry.payer_id` collapses all inquiries for a single payer onto one MessageGroupId. At a medium-volume institution doing 50K registrations/month plus pre-warm (~150K total verifications/month), the morning registration peak (8 AM - 11 AM) concentrates a substantial fraction of the day's volume into a 3-hour window. For a national payer like Aetna or Cigna or UnitedHealth that covers a large fraction of the patient population, hundreds or low thousands of inquiries per hour go to that single payer; serializing them through one MessageGroupId converts a horizontally-scalable workload into a per-payer queue depth that grows during the peak, with measurable registration-flow latency consequences. The recipe's own latency budget (P50 cache-miss-DynamoDB-miss-trigger-async < 200ms, P95 < 500ms) cannot be met when the inquiry has to wait behind a per-payer queue.

  2. **The stated rationale (subscriber-then-dependent ordering) is not generally required by payer eligibility APIs.** Subscriber and dependent inquiries are independently resolvable: the 270 includes the subscriber relationship and the relevant person code; the payer's eligibility system looks up the appropriate member record without requiring the subscriber's record to be queried first. The recipe's own pseudocode at Step 2D handles `subscriber_or_dependent` and `subscriber_id` correctly per inquiry; there is no architectural reason for cross-inquiry sequencing.

  3. **The FIFO ordering interacts badly with retry semantics.** SQS FIFO with `MessageDeduplicationId=inquiry.inquiry_hash` plus `MessageGroupId=inquiry.payer_id` means a transient failure on one inquiry blocks all subsequent inquiries to the same payer until the retry succeeds or DLQ-routes. A clearinghouse incident affecting a major payer becomes an institutional outage for that payer's inquiries.

  At chapter-pattern grain, this is a recipe-specific finding: 5.1 / 5.2 / 5.3 use SQS Standard or Step Functions, not FIFO with payer-grouping. The error originates in this recipe and warrants a HIGH-severity correction.

- **Fix:** Reconsider the FIFO-vs-Standard choice and the MessageGroupId design. Three options, in order of preference:

  1. **Use SQS Standard for both queues, with per-inquiry idempotency at the inquiry hash.** Standard SQS provides at-least-once delivery with no per-group throughput cap; the inquiry hash serves as the idempotency key for the submit-inquiry Lambda. This matches the chapter pattern from 5.1 / 5.2 / 5.3 and removes the per-payer bottleneck.

     ```
     SQS.SendMessage(queue_url, inquiry)
         // Standard queue; idempotency enforced at the
         // submit-inquiry Lambda via the inquiry hash.
     ```

  2. **If FIFO is required for a specific use case, use a finer-grained MessageGroupId.** Per `(payer_id, subscriber_id)` for actual sequencing needs (subscriber-then-dependent sequencing only matters for the few payers that genuinely require it); per `inquiry_hash` for idempotent-delivery-without-ordering.

  3. **Use Step Functions Express Workflows for the real-time path** rather than a queue-and-Lambda chain. Express Workflows scale to 100,000 invocations/second and provide explicit ordering only where needed in the state machine.

  Update the Step 1 pseudocode and the Why These Services SQS paragraph. Add a paragraph to the architecture explaining the throughput-vs-ordering trade-off and the per-payer bottleneck pattern that the FIFO-with-payer-grouping choice would have produced.

### Finding A4: Idempotency Keys and DLQ Coverage Named in TODO but Not Architected (Chapter-Wide Pattern, Already Partially TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" idempotency paragraph: *"Use the inquiry hash as the idempotency key for inquiry submission. Use `(patient_id, payer_id, service_date)` as the idempotency key for persistence. Use Lambda invocations idempotent at these keys; configure DLQs on every Lambda path; Step Functions Catch states route terminal failures to the DLQ so stuck workflows are visible."* The recipe's inline TODO at the same location (referenced as "Expert review A4 (MEDIUM)") names the recipe-specific keys but the architecture pattern does not include them.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A4. The idempotency keys are correctly named in the production-gaps section but not specified in the architecture pattern, the pseudocode, or the Lambda configuration. The DLQ topology (one DLQ per Lambda, or shared per pipeline phase) is not specified. The TODO names the recipe-specific keys (`normalize-inquiry at inquiry_hash`; `submit-inquiry at inquiry_hash + clearinghouse_idempotency_key`; `evaluate-response at (inquiry_id, response_payload_hash)`; `persist-and-propagate at (patient_id, payer_id, service_date, resolved_at_minute_bucket)`; `invalidate-on-coverage-change at (change_event_source, change_event_id)`) which is precisely the right granularity.
- **Fix:** Promote the TODO content into the General Architecture Pattern paragraph: *"Every Lambda invocation in the pipeline is idempotent at a recipe-specific key: normalize-inquiry at `inquiry_hash`; submit-inquiry at `(inquiry_hash, clearinghouse_idempotency_key)` (the clearinghouse provides its own idempotency key for the X12 transaction); evaluate-response at `(inquiry_id, response_payload_hash)`; persist-and-propagate at `(patient_id, payer_id, service_date, resolved_at_minute_bucket)`; invalidate-on-coverage-change at `(change_event_source, change_event_id)`. Each Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows within 15 minutes of accumulation."*

### Finding A5: Real-Time Eligibility Lookup API Latency Budget and Async-Resolution Pattern Named in TODO but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (operational SLA, registration-flow latency)
- **Location:** API Gateway plus Lambda paragraph: *"The API checks the cache, falls through to DynamoDB, and (if neither has the entry) triggers an asynchronous inquiry while returning a 'verification in progress' response that the caller can poll on."* The recipe's inline TODO at the same location (referenced as "Expert review A5 (MEDIUM)") names the latency targets but the architecture text does not include them.
- **Problem:** The recipe correctly identifies the cache-DynamoDB-async pattern but does not specify the latency thresholds, the queue-depth alarm, or the relationship between the registration-flow target and the underlying CAQH CORE 20-second SLA. The TODO names the right values: P50 cache-hit < 10ms, P50 cache-miss-DynamoDB-hit < 50ms, P50 cache-miss-DynamoDB-miss-trigger-async < 200ms, P95 < 500ms across all paths, P99 < 2s; CloudWatch alarm on async-resolution queue depth > 500 records or > 10 minutes. The architecture should promote the TODO content into the prose.
- **Fix:** Promote the TODO content into the API Gateway paragraph: *"Latency budget breakdown: P50 cache-hit latency < 10ms, P50 cache-miss-DynamoDB-hit < 50ms, P50 cache-miss-DynamoDB-miss-trigger-async < 200ms, P95 < 500ms across all paths, P99 < 2s. The 'verification in progress' response is the fail-open pattern: registration workflow continues with a degraded-but-useful response while the actual 270/271 round-trip happens asynchronously. CloudWatch alarm fires when async-resolution queue depth exceeds 500 records or persists more than 10 minutes (registration is in steady state, async backlog should drain quickly). The 270/271 round-trip itself can take up to 20 seconds per CAQH CORE Phase II rules; the cache-and-async pattern decouples the registration latency from the underlying 270/271 latency."*

### Finding A6: Cross-Recipe Orchestration with 5.1 / 5.5 / 5.6 / 1.1 / 1.8 / 2.4 / 3.1 Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (cross-recipe integration)
- **Location:** Architecture diagram shows `EB1 -->|FanOut| C6[Patient Matcher 5.1]` and the Related Recipes section names 5.1, 5.2, 5.3, 5.5, 5.6, 5.7, 5.8, 1.1, 1.8, 2.4, 3.1, 7.x as recipes that consume or produce eligibility-related events. The recipe's inline TODO (referenced as "Expert review A6 (MEDIUM)") names the chapter-wide event schema but the architecture text does not include the contract.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A6. The architecture diagram shows the EventBridge fan-out to consumers but the contract between recipes is not specified: what payload each consumer receives, what the consumer's expected response cadence is, how consumers acknowledge processing, what the schema-versioning policy is. The eligibility-match store is consumed by more cross-recipe consumers than 5.1/5.2/5.3 (claims-to-clinical linkage in 5.6, claims-side anomaly detection in 3.1, prior-auth in 2.4); the integration contract is correspondingly more important.
- **Fix:** Promote the TODO content into the General Architecture Pattern paragraph: *"The eligibility events conform to a chapter-wide event schema (`source`, `detail_type`, `detail.patient_id`, `detail.event_id`, `detail.previous_state`, `detail.new_state`, `detail.detected_at`). Downstream consumers in 5.1 (patient matcher, when an eligibility match surfaces a previously unknown duplicate-patient signal), 5.5 (cross-facility HIE, when eligibility data from one facility's payer affects record reconciliation), 5.6 (claims-to-clinical linkage, where eligibility state at time of service constrains claim-to-encounter joining), plus the revenue-cycle, charity-care, care-management, and patient-portal pipelines, subscribe to specific `detail_type` values and acknowledge processing via a CloudWatch metric (`{consumer}.events_processed`). The chapter-wide event-bus governance specifies the schema versioning policy and the deprecation cadence for breaking changes."*

### Finding A7: Threshold Calibration Governance Named in TODO but Not Architected (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (governance, model lifecycle)
- **Location:** "Why This Isn't Production-Ready" threshold-calibration paragraph: *"The auto-accept and auto-reject thresholds are calibrated against the gold set. Re-calibration runs annually or on detection of cohort-stratified disparity above the institutional threshold, whichever first. Re-calibration produces a candidate threshold set; institutional review (revenue-cycle leadership, compliance, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each match outcome records the configuration version and threshold values active at the time of the match."* The recipe's inline TODO at the same location (referenced as "Expert review A7 (MEDIUM)") names the chapter pattern but the architecture text does not include the specification.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A7 / A11. The threshold calibration is functionally a probabilistic-classifier-tuning workflow whose lifecycle needs governance. The recipe correctly diagnoses the discipline ("change without governance is the failure mode that produces silent regressions in both accuracy and equity") but the architecture does not specify the configuration-as-data pattern, the candidate-promotion gate, or the version-event-on-every-match-outcome contract.
- **Fix:** Promote the TODO content into the architecture text: *"The thresholds (`AUTO_ACCEPT_THRESHOLD`, `AUTO_REJECT_THRESHOLD`, per-feature weights in the composite score) live in a versioned configuration table. Re-calibration runs annually or on detection of cohort-stratified disparity above 0.05, whichever comes first. Re-calibration produces a candidate threshold set against the institutional gold set; institutional review (revenue-cycle leadership, compliance, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each match outcome records the configuration version and threshold values active at the inference time, supporting forensic reconstruction across re-calibration cycles."*

### Finding A8: API Gateway Resource Policy and WAF Posture for the Real-Time API Not Specified (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (security boundary, defense in depth)
- **Location:** Architecture diagram shows `AG1[API Gateway eligibility-lookup] -> CG1[Cognito] -> L5[Lambda api-handler]`. The recipe's inline TODO (referenced as "Expert review A8 / Networking review N1 (MEDIUM / LOW)") names the chapter pattern but the architecture text does not include the specification.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A8 / N1. The real-time API's resource-policy posture (private API only, VPC endpoint, integration with AWS WAF) is not specified.
- **Fix:** Promote the TODO content into the API Gateway paragraph: *"The API Gateway is configured as a private API with a VPC endpoint resource policy restricting access to the institutional VPC; the institutional registration system, PMS, and revenue-cycle consumers reach the API through the VPC endpoint. AWS WAF is attached with rule groups for SQL injection, command injection, request rate limiting (per-source-IP and per-Cognito-principal), and request-size limiting. mTLS is required for system-to-system clients (clearinghouse webhook receivers, partner integrations) where the partner supports it."*

### Finding A9: ElastiCache Eligibility Cache Capacity Planning and Eviction Policy Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (capacity, cost, correctness at scale)
- **Location:** Why These Services / ElastiCache paragraph: *"Redis holds parsed eligibility state with TTLs that match the freshness policy (24 hours for future service dates, 1 year for past)."* And Step 5C pseudocode: *"Redis.Set(cache_key, item, ex=item.cache_ttl)"* with `cache_ttl` derived as 1 year for past service dates and 24 hours for future. The Cost Estimate row says ElastiCache "small Redis cluster runs $200-600/month."
- **Problem:** A 1-year TTL on past-service-date entries produces unbounded cache growth. Concrete sizing math:

  - At 50K registrations/month + 100K pre-warm/month = 150K eligibility verifications/month.
  - Past entries accumulate at the ingest rate; over 12 months, 1.8M past entries plus the rolling 30-day window of future entries.
  - Each match-outcome JSON is roughly 1-2KB (the parsed coverage state, financial responsibility, COB indicator, network status, plus inquiry/response audit-key references).
  - Steady-state cache size: 1.8M * 1.5KB ≈ 2.7GB, plus future entries ≈ 3-4GB total in steady state.
  - At a small Redis cluster (cache.t3.medium with ~3GB memory), the cache is over-capacity within 6-8 months and must spill or evict.

  The architecture does not specify:

  1. **The Redis cluster sizing methodology.** The "small Redis cluster" framing in the Cost Estimate is under-specified; at the stated volumes, a small cluster is undersized within months.
  2. **The eviction policy.** Redis defaults to `noeviction` on reaching memory limits, which produces cache writes failing rather than silently evicting. The right policy is `volatile-lru` or `volatile-lfu` (evict TTL-bearing keys by LRU/LFU when memory is tight) but this is not specified.
  3. **The trade-off between past-entry cache value and cache-growth cost.** Past-service-date entries have low read frequency once the encounter is closed; the 1-year TTL is conservative but produces a cache that is mostly cold storage. A shorter past TTL (30-90 days) plus on-demand re-fetch from DynamoDB on the rare past-date read would reduce cache size 4-10x.

- **Fix:** Specify the capacity planning and the eviction policy in the ElastiCache paragraph:

  *"ElastiCache cluster sizing is calculated against the steady-state cache size: at a medium-volume institution doing 150K verifications/month, the rolling 12 months of past entries plus the 30-day forward window total approximately 3-4GB at 1-2KB per match-outcome JSON. A `cache.r6g.large` (~13GB memory) is the recommended starting point with two read replicas for availability and a `volatile-lfu` eviction policy (evict TTL-bearing keys by least-frequent-use when memory is tight). Past-service-date TTL of 1 year is conservative; institutions optimizing for cache cost may shorten to 30-90 days with on-demand re-fetch from DynamoDB on the rare past-date read. CloudWatch alarms fire on cache memory utilization exceeding 80% and on eviction count exceeding a per-day threshold; an alarm on either signals undersizing and triggers a capacity review."*

  Add a sentence to the Cost Estimate row to reflect the corrected cluster sizing (`cache.r6g.large` runs roughly $400-800/month vs the originally-stated $200-600).

### Finding A10: Backfill of Existing Patient Population at Launch Mentioned but Not Architected (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (one-time vs ongoing operations)
- **Location:** "Why This Isn't Production-Ready" Initial backfill paragraph names the considerations: *"(a) negotiate a one-time bulk pricing tier with the clearinghouse (typical batch transaction pricing is 5-10x cheaper than real-time); (b) run the backfill as a Glue job with controlled concurrency to stay below the clearinghouse's rate limit; (c) suppress the eligibility-resolved event emission during backfill; (d) emit one eligibility_backfill_complete event when done with the cohort-stratified accuracy report attached. Plan the backfill timeline in coordination with downstream consumers."* The recipe's inline TODO (referenced as "Expert review A11 (LOW)") names the chapter pattern.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3. The backfill is a one-time operation with distinct architectural considerations (clearinghouse rate-limit negotiation, event-emission suppression, downstream-consumer coordination) that the production-gaps text correctly diagnoses but the architecture does not architect. The chapter editor's note at the bottom of the Honest Take treats this as LOW; in 5.4 specifically, the volume (the entire patient population's upcoming appointments at launch) and the cost dimension (clearinghouse fees per inquiry) make this a MEDIUM concern.
- **Fix:** Promote the TODO content into the Why This Isn't Production-Ready section more fully, mirroring the chapter pattern from 5.3 Finding A11. Specify the backfill orchestration as a Step Functions workflow with controlled concurrency, the event-suppression mechanism (a `backfill_in_progress` flag on the eligibility-events bus that consumers honor), and the downstream-coordination protocol (PMS, revenue cycle, charity care receive a `backfill_complete` event with a cohort-stratified accuracy report attached).

### Finding A11: Lake Formation Column-Level Access Controls Named in TODO but Not Architected (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (analytics access governance)
- **Location:** Why These Services / Athena paragraph and the recipe's inline TODO (referenced as "Expert review A10 (LOW)").
- **Problem:** Same chapter pattern as 5.2 / 5.3 Finding A10. The raw 271 payloads are sensitive (full coverage and financial-responsibility detail; restricted to payer-relations and audit teams). The parsed coverage state is needed by clinical and revenue-cycle staff. The cohort-aggregated metrics are needed by leadership. Different audiences need different views; Lake Formation grants enforce the column-level distinctions.
- **Fix:** Promote the TODO content into the Athena paragraph: *"Lake Formation column-level access controls restrict QuickSight and Athena consumers to the columns they need: dashboards see cohort-aggregated metrics only; revenue-cycle and clinical staff see the parsed coverage view and the audit-trail provenance; the raw 271 payload is restricted to the payer-relations and audit teams. Direct Athena query path uses the same grants. Access is logged via CloudTrail data events on the catalog and on the underlying S3 buckets."*

### Finding A12: CAQH CORE-Noncompliant Payer Handling Diagnosed in Honest Take but Architecturally Underspecified

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Honest Take's "Where it struggles" subsection: *"CAQH CORE-noncompliant payers. Smaller payers and self-funded TPAs sometimes ignore the operating rules: they return responses with missing required fields, they ignore service-type codes, they include extraneous segments. The parser has to handle malformed-but-recoverable responses gracefully and route the unrecoverable ones to the review queue."*
- **Problem:** The recipe correctly diagnoses the malformed-response problem but the architecture does not specify the parser's strictness mode (strict vs lenient vs payer-specific) or the threshold for routing to the review queue. At Step 4B, the pseudocode says `parse_x12_271(response.payload)` but the function's behavior on malformed responses is implicit. A strict parser routes too many cases to review; a lenient parser silently accepts under-specified responses and produces wrong outcomes.
- **Fix:** Add to the Step 4 pseudocode comment and the architecture pattern: *"The parser supports per-payer strictness configuration in the payer-config table: `strict` (every CAQH CORE-required field must be present; missing fields route to PARTIAL with review-required flag), `lenient` (missing optional fields default to documented values; missing required fields downgrade the match confidence), and `payer-specific overrides` for known noncompliant payers. The strictness mode is calibrated per-payer based on observed response quality; new payers default to `strict` until their response patterns are characterized."*

### Finding A13: Member-ID Staleness Threshold for Primary-Key vs Search-Match Decision Not Specified

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 2C pseudocode: *"the most recent member ID with the stamp date so the response evaluator can tell if it's stale; else NULL (search match)."*
- **Problem:** The architecture mentions stamp date as a staleness signal but does not specify the threshold at which the system should skip primary-key lookup and go directly to search match. A stale member ID (more than N days old) has degraded reliability; submitting a primary-key 270 with a stale member ID wastes a clearinghouse transaction and produces a NOT_FOUND response when search would have succeeded.
- **Fix:** Add to the Step 2C comment: *"A staleness threshold (typically 90-180 days, calibrated per payer based on observed member-ID change rates) determines whether to submit the cached member ID for primary-key lookup or to skip directly to search match. The threshold is per-payer because Medicaid and Medicare member IDs change less frequently than commercial member IDs; self-funded plans vary widely. The threshold is stored in the payer-config table alongside the other per-payer rules."*

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** Lambdas in VPC; Glue jobs in VPC connections; ElastiCache in VPC subnet groups; VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, STS. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization with allow-listed egress.** "NAT Gateway for clearinghouse and direct-payer egress with an outbound HTTPS proxy and an allow-list of partner endpoints" is the chapter's correct egress-discipline statement.
- **PrivateLink awareness flagged in TODO.** The TODO at the AWS Implementation Lambda paragraph correctly identifies that "most clearinghouses do not offer AWS PrivateLink, though some larger payers and clearinghouses do at high volume tiers" and that the institution should evaluate at scale.
- **TLS 1.2-or-higher framing throughout.** "TLS 1.2 or higher for all in-transit traffic, including the clearinghouse and direct-payer connections. Mutual TLS where the partner requires it" is the right baseline. The mTLS framing for clearinghouse webhook receivers and direct-payer connections is correct.
- **HIPAA-eligible service inventory checked.** The Prerequisites AWS Services row enumerates HIPAA-eligible services consistently with the chapter pattern.

### Finding N1: API Gateway Resource Policy and WAF Posture Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram shows the real-time API surface but the resource policy and WAF posture are not specified in prose. (See Architecture Finding A8 for the architecture-side framing of the same concern.)
- **Problem:** Same as Recipe 5.1 / 5.2 / 5.3 Finding N1.
- **Fix:** See Finding A8 fix. Specify private API Gateway with VPC endpoint resource policy, WAF rules for SQL injection / command injection / rate limiting, mTLS for system-to-system clients.

### Finding N2: Clearinghouse and Direct-Payer Egress Posture Could Be Sharpened (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row: *"NAT Gateway for clearinghouse and direct-payer egress with an outbound HTTPS proxy and an allow-list of partner endpoints."* The recipe's inline TODO (referenced as "Networking review N2 / Architecture A9 (LOW)") names the chapter pattern but the architecture text does not include the specification.
- **Problem:** The egress posture is correctly outlined but could be sharpened with per-partner allow-list scoping. The clearinghouse domain and each direct-payer domain are distinct concerns; a compromise of one Lambda role should not be able to exfiltrate via another partner's endpoint. Same pattern as 5.3 Finding N2.
- **Fix:** Promote the TODO content into the VPC row: *"Clearinghouse egress and direct-payer egress are configured as distinct outbound proxy rules with non-overlapping allow-lists scoped to compute roles: each Lambda role allows only the specific partner endpoints it must call; per-role rate limits below the partner's published rate limits; egress connections CloudWatch-logged for chargeback and forensic auditing."*

### Finding N3: PrivateLink Evaluation Posture Underspecified

- **Severity:** LOW
- **Expert:** Networking (architecture roadmap)
- **Location:** TODO at the AWS Implementation Lambda paragraph naming PrivateLink availability for some larger payers and clearinghouses.
- **Problem:** The TODO correctly identifies the operational improvement but does not specify the volume threshold or the evaluation criteria for adopting PrivateLink. At eligibility-inquiry volumes (1M+ inquiries/month for medium institutions), PrivateLink eliminates NAT Gateway data-transfer cost on the partner-egress path and improves the security posture.
- **Fix:** Promote the TODO content into the VPC row: *"At volumes exceeding ~1M inquiries/month, evaluate the partner's PrivateLink endpoint where available. PrivateLink eliminates NAT Gateway data-transfer cost on the partner-egress path and keeps the traffic on the AWS network without traversing the public internet. The cost trade-off (PrivateLink endpoint hourly fee plus per-GB data-transfer fee vs NAT Gateway data-transfer fee) is institution-specific; institutions with high-volume real-time API traffic typically see net savings at the 1M-inquiries/month threshold."*

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by reading the file with explicit UTF-8 encoding and counting U+2014 codepoints.
- **En dash count: 0.** Verified the same way for U+2013.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services. AWS service names appear first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory for the closing observations on the X12 270/271 standard's longevity, the FHIR-based eligibility evolution, and the regulatory-context closing on No Surprises Act and price transparency.
- **CC voice consistent throughout.** The opening 7:42 AM front-desk vignette ("It is 7:42 AM. A patient walks into a busy primary care office for a follow-up visit. The front desk staff scans her insurance card, the practice management system fires off an eligibility verification request to her health plan, and the response comes back in about three seconds: *member not found*") lands in the engineer-explaining-something-cool register exactly. The seven running maybe-clauses ("Maybe the front desk staff types her name and DOB into the payer's web portal manually... Maybe the patient is in a coverage lookup with her maiden name... Maybe the patient's DOB was keyed in wrong by the payer when she was first enrolled and has been wrong for years... Maybe the payer's eligibility file is two days behind because their nightly batch job failed and nobody noticed yet") are the recipe's strongest single passage of pacing. Self-deprecating expertise: "this is the recipe in this chapter that has the most direct line to dollars" lands in the right register for the recipe's Medium-tier framing.
- **The Cigna and Maria Garcia-Lopez running examples are consistent.** The Cigna member ID `U1234567890-01` carries from the Problem section through to the Expected Results sample MATCHED outcome with the right financial-responsibility detail (primary care copay $25, deductible $1500 with $875 remaining, COB indicator primary, network status in-network). The Maria Garcia-Lopez vs Maria Garcia search-match example carries the right shape for the REVIEW_REQUIRED outcome, with the partial-name-match plus DOB-off-by-one-day detail that explains why the score is 0.78 and routes to review.
- **Clinical and regulatory accuracy is high.** The X12 270/271 framing is correct (5010 is the current version per the HIPAA Administrative Simplification regulations); the CAQH CORE Phase II Phase III Phase IV layered framing is correct (with appropriate TODO for verification at build time); the AAA / EB / NM1 segment framing is correct; the ACA market-segment reference is correct; the No Surprises Act effective-2022 framing is correct (with appropriate TODO for verification of implementing rules); the FHIR Coverage / CoverageEligibilityRequest / CoverageEligibilityResponse references and the Da Vinci Project Coverage Requirements Discovery (CRD), Documentation Templates and Rules (DTR), and Prior Authorization Support (PAS) implementation guides are correctly named; the CMS Patient Access API and Provider Directory API references are correct.
- **The Honest Take is the recipe's most operationally pointed section.** The six observations (the "we already have this, the clearinghouse handles it" trap, the registration-flow latency budget under-investment, the cohort-stratified accuracy under-investment, the parsed-coverage-detail-as-substrate framing, the cache-freshness policy decision, the X12-as-aged-well closing) are the chapter's strongest individual list of failure modes for this domain.
- **The Variations and Extensions section is well-scoped.** Eleven extensions (FHIR-based connectivity, charity-care multi-payer fanout, COB resolution module, real-time pricing transparency, predictive eligibility refresh, patient-portal coverage self-service, clearinghouse-vs-direct optimization, eligibility-driven appointment scheduling, cross-organization eligibility sharing, active-learning-driven threshold tuning, payer-quality scorecards). Each is framed at the right grain.

### Finding V1: A Few Headers in the AWS Implementation Section Slip Toward Documentation Voice

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in "Why These Services" read as service-name-as-bullet-header:
  - *"AWS KMS, CloudTrail, CloudWatch."*
  - *"AWS Secrets Manager for clearinghouse and direct-payer credentials."*
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 Finding V1. The headers are functionally correct as scannable structure for a long technical section; the deeper paragraph framing returns to the right register.
- **Fix:** Optional. The chapter editor's call.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in The Technology section's "What Makes the Match Hard" subsection and the Honest Take's parsed-coverage-detail paragraph stretch past 50 words.
- **Problem:** Most sentences are well-paced; a few in the architectural-and-regulatory paragraphs could be split. Same observation as 5.1 / 5.2 / 5.3 Finding V2.
- **Fix:** Optional.

### Finding V3: The 7:42 AM Opening Vignette and the Maybe-Clause Pacing Are the Chapter's Strongest Single Hook on This Domain

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Problem's opening vignette and the seven-clause "maybe" enumeration following the *member not found* response.
- **Note:** This framing earns its position. The chapter editor should consider whether a similar "scene-then-maybe-list" pattern applies to other recipes that need to ground the reader in operational ambiguity; for 5.4 specifically, the vignette is the recipe's strongest single hook.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1, chapter-pattern):** Security flags `inquiry_submission`, `evaluate_response`, `persist_and_propagate`, the eligibility-lookup read endpoint, and the cache-invalidation cross-recipe consumer at HIGH severity. Architecture concurs because the eligibility-store-as-anchor consequence (a misrouted persist call corrupts the canonical eligibility outcome that downstream PMS, revenue-cycle, charity-care, care-management, patient-portal, and cross-recipe consumers all consume) compounds the security concern with a methodological one. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The chapter editor should consolidate to a chapter preface in the next pass since the same finding now applies across 4.4-5.4.**

**persist_and_propagate atomicity (A1):** Architecture flags the sequential PutItem / Set / PutObject / PutEvents / SendMessage pattern as needing `TransactWriteItems` plus an outbox pattern at HIGH severity, with the recipe's own inline TODO at Step 5A already naming the gap and noting that the regulatory consequence is sharper than 5.1/5.2/5.3. Security concurs because half-applied state produces audit-trail inconsistency that breaks the "build it as compliance infrastructure" claim and produces compliance-visible inconsistency in claims (denials), charity-care (wrongful eligibility denials), and patient financial responsibility (point-of-service collection of wrong amounts). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence.**

**Cohort fairness instrumentation (A2, chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security concurs on the privacy framing of cohort dimensions in CloudWatch (Finding S5). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The cohort-distribution stakes are higher here than in 5.1/5.2/5.3 because eligibility-match disparities directly translate to charity-care eligibility errors, claim denials cascading into patient bills the patients can least afford, and delayed care.**

**SQS FIFO MessageGroupId per payer (A3):** Architecture flags this as a recipe-specific HIGH-severity throughput error. The MessageGroupId-per-payer pattern serializes a horizontally-scalable workload through a per-payer bottleneck; the stated rationale (subscriber-then-dependent ordering) is also incorrect (these inquiries are independently resolvable). Security is silent (this is a throughput / correctness concern, not a security one). Networking is silent (the network is fine; the messaging layer is the issue). Voice is silent. **Resolution: HIGH, attributed to Architecture. The fix is to switch to SQS Standard or use a finer-grained MessageGroupId; this is a localized pseudocode-and-prose fix.**

**Audit-log retention floor (S2, chapter-pattern):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Clearinghouse and partner data-handling expectations (S3):** Security flags as MEDIUM. Architecture concurs because the partner data-handling commitments (retention window, sub-processor disclosure for self-funded TPAs, incident notification, audit rights) directly affect the institution's risk posture. **Resolution: MEDIUM, attributed to Security with Architecture concurrence.**

**Review-queue audit posture (S4):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Idempotency and DLQ coverage (A4, chapter-pattern):** Architecture flags as MEDIUM. The recipe's own production-gaps section names the recipe-specific keys but the architecture pattern does not include them. **Resolution: MEDIUM, attributed to Architecture.**

**Real-time API latency budget and async-resolution pattern (A5):** Architecture flags as MEDIUM. The recipe states the cache-and-async pattern in the prose but the latency thresholds and the queue-depth alarm are TODO'd, not specified. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration (A6):** Architecture flags as MEDIUM. The fan-out is shown in the architecture diagram but the contract between recipes is not specified. **Resolution: MEDIUM, attributed to Architecture.**

**Threshold calibration governance (A7, chapter-pattern):** Architecture flags as MEDIUM. The threshold calibration is functionally a probabilistic-classifier-tuning workflow whose lifecycle needs governance. **Resolution: MEDIUM, attributed to Architecture.**

**API Gateway resource policy and WAF (A8 / N1, chapter-pattern):** Architecture flags as MEDIUM; Networking flags as LOW. Consolidating into a chapter preface is the right pattern. **Resolution: MEDIUM (per A8), attributed to Architecture with Networking concurrence.**

**ElastiCache cache capacity and eviction (A9):** Architecture flags as MEDIUM. The 1-year past-service-date TTL produces unbounded cache growth at the stated volumes; the cluster-sizing math in the Cost Estimate is undersized; the eviction policy is unspecified. **Resolution: MEDIUM, attributed to Architecture. This is a recipe-specific concern (5.1/5.2/5.3 do not have the ElastiCache substrate at this scale).**

**Backfill of existing patient population (A10, chapter-pattern):** Architecture flags as MEDIUM (vs LOW in 5.3) because the eligibility-specific cost dimension (clearinghouse fees per inquiry) and the volume (the entire population's upcoming appointments at launch) make this more consequential than in earlier recipes. **Resolution: MEDIUM, attributed to Architecture.**

**Lake Formation column-level access controls (A11, chapter-pattern):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**CAQH CORE-noncompliant payer handling (A12):** Architecture flags as LOW. The recipe correctly diagnoses the malformed-response problem but does not specify the parser strictness mode. **Resolution: LOW, attributed to Architecture.**

**Member-ID staleness threshold (A13):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Cohort PHI in CloudWatch dimensions (S5, chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S6, chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Patient-portal coverage self-service disclosure posture (S7):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Clearinghouse and direct-payer egress posture (N2, chapter-pattern):** Networking flags as LOW. **Resolution: LOW, attributed to Networking.**

**PrivateLink evaluation posture (N3):** Networking flags as LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2):** Both LOW. V3 is a positive observation. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 0 critical, 4 high, 9 medium, 11 low. The 4 HIGH count exceeds the > 3 = FAIL threshold; the verdict is FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Four HIGH findings (more than 3 = FAIL per the persona rules). Three are correctness-and-compliance gaps with localized fixes that surface in well-specified TODO comments and prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose; one (the SQS FIFO MessageGroupId pattern) is a recipe-specific architectural error in the pseudocode that needs an explicit fix. None require structural rework of the recipe; the underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | Inquiry-submission, response-evaluation, persist-and-propagate, and eligibility-lookup read endpoint lack identity-boundary specification |
| 2 | HIGH | Architecture | persist_and_propagate is not atomic; sequential DynamoDB / cache / S3 / EventBridge / SQS operations leave half-updated state on partial failure |
| 3 | HIGH | Architecture | Cohort-stratified accuracy thresholds and metric definitions referenced as "required here too" but undefined |
| 4 | HIGH | Architecture | SQS FIFO MessageGroupId per payer serializes a horizontally-scalable workload through a per-payer bottleneck |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 5 | MEDIUM | Security | Audit-log retention specified as "per institution's records-retention policy" without architectural floor (chapter pattern) |
| 6 | MEDIUM | Security | Clearinghouse and direct-payer data-handling expectations named in TODO but not architecturally specified |
| 7 | MEDIUM | Security | Review-queue decision audit posture underspecified |
| 8 | MEDIUM | Architecture | Idempotency keys and DLQ coverage named in TODO but not architected (chapter pattern) |
| 9 | MEDIUM | Architecture | Real-time eligibility lookup API latency budget and async-resolution pattern named in TODO but not architected |
| 10 | MEDIUM | Architecture | Cross-recipe orchestration with 5.1 / 5.5 / 5.6 / 1.1 / 1.8 / 2.4 / 3.1 mentioned but not architected |
| 11 | MEDIUM | Architecture | Threshold calibration governance named in TODO but not architected (chapter pattern) |
| 12 | MEDIUM | Architecture | API Gateway resource policy and WAF posture not specified (chapter pattern) |
| 13 | MEDIUM | Architecture | ElastiCache eligibility cache capacity planning and eviction policy not specified |
| 14 | MEDIUM | Architecture | Backfill of existing patient population at launch mentioned but not architected (chapter pattern) |

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 15 | LOW | Security | Cohort PHI in CloudWatch metric dimensions (chapter pattern) |
| 16 | LOW | Security | IAM "Never `*` actions or `*` resources in production" stated without scoped ARN examples (chapter pattern) |
| 17 | LOW | Security | Patient-portal coverage self-service disclosure posture not addressed |
| 18 | LOW | Architecture | Lake Formation column-level access controls named in TODO but not architected (chapter pattern) |
| 19 | LOW | Architecture | CAQH CORE-noncompliant payer handling diagnosed in Honest Take but architecturally underspecified |
| 20 | LOW | Architecture | Member-ID staleness threshold for primary-key vs search-match decision not specified |
| 21 | LOW | Networking | API Gateway resource policy and WAF posture not specified (chapter pattern, paired with A8) |
| 22 | LOW | Networking | Clearinghouse and direct-payer egress posture could be sharpened (chapter pattern) |
| 23 | LOW | Networking | PrivateLink evaluation posture underspecified |
| 24 | LOW | Voice | A few headers in the AWS Implementation section slip toward documentation voice |
| 25 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 4 HIGH findings before publication.** Each has a localized fix:
   - Finding S1 (identity-boundary): pseudocode additions in the trigger-ingest, response-evaluation, persist-and-propagate, and eligibility-lookup-read paths. Reference language is partially present in inline TODOs and the chapter pattern from 4.4-5.3. Estimated effort: half a day.
   - Finding A1 (atomicity): pseudocode rewrite of Step 5 to use `TransactWriteItems` plus an outbox pattern for the cache write, S3 archive, EventBridge emit, and SQS review-queue routing. The architecture prose addition specifies the partial-failure recovery semantics. The recipe's own TODO at Step 5A names the gap; the fix is to architect what the TODO references. Estimated effort: half a day.
   - Finding A2 (cohort fairness threshold): threshold-and-metric specification in pseudocode and architecture-prose paragraph. Reference language is present in the cohort-stratified accuracy paragraph and inherited from 5.1/5.2/5.3. Estimated effort: half a day.
   - Finding A3 (SQS FIFO MessageGroupId): pseudocode change in Step 1 to switch to SQS Standard (preferred) or to a finer-grained MessageGroupId, plus a paragraph in the AWS Implementation section explaining the throughput-vs-ordering trade-off. Estimated effort: half a day.

   Total: 2 days of writing time.

2. **Address the recipe-specific MEDIUM findings (S4 review-queue audit, A5 latency budget, A9 ElastiCache capacity, A10 backfill, A12 CAQH-noncompliance handling).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1-2 days of writing time.

3. **Address the chapter-wide MEDIUM findings (S2 audit retention, S3 partner data-handling, A4 idempotency, A6 cross-recipe orchestration, A7 threshold governance, A8/N1 API Gateway resource policy).** These are already TODO'd or chapter-pattern; consolidating into a chapter preface in the next pass is acceptable.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N2, N3) are explicit-statement additions; the chapter-pattern findings (S5, S6, S7, A11) are consolidation work; A12, A13 are small inline annotations.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 5.4 is the first Medium-tier recipe in Chapter 5 and the recipe text says it is a recipe that "has the most direct line to dollars." The quality bar inherits from 5.1/5.2/5.3 and the recipe's own claim that "the eligibility-match infrastructure is now load-bearing for compliance" earns the architectural specification needing to be at the level the recipe text claims.

The recipe's underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent. The opening 7:42 AM front-desk vignette, the seven running maybe-clauses, the X12 270/271 / CAQH CORE Phase II framing, the primary-key-vs-search-match dichotomy, the multi-component coverage answer (identity, status, scope, financial responsibility, COB, network), the cache-and-async registration-flow pattern, the freshness-two-regimes framing, the parsed-coverage-detail-as-substrate framing, the X12-as-aged-well closing, and the No-Surprises-Act-as-load-bearing closing line are all chapter-strength contributions. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses (Findings S1, A1, A2, with TODO references already in place) plus one recipe-specific architectural error in the pseudocode (Finding A3, the SQS FIFO MessageGroupId). Closing the gaps brings the architecture up to the standard the recipe text claims and makes the eligibility-match substrate that 5.1, 5.5, 5.6, plus the revenue-cycle, charity-care, care-management, and patient-portal pipelines depend on as solid as the recipe text promises it is.
