# Expert Review: Recipe 5.2 - Provider NPI Matching

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-22
**Recipe file:** `chapter05.02-provider-npi-matching.md`

---

## Overall Assessment

This is the second Simple-tier recipe in Chapter 5 and the recipe that explicitly leans on Recipe 5.1's framework with the registry-anchored deviations called out where they matter. The opening provider-directory vignette earns its position: "Open the provider directory of any health plan in the country and look up a primary care doctor in your area. Click the first three results. There is a meaningful chance that one of them retired two years ago, one of them moved offices six months back to a new building, and one of them never practiced at the listed address in the first place." The pivot to the member-impact framing (forty minutes calling listed providers, half wrong, ED visit that should have been primary care) and then to the regulatory consequence (the No Surprises Act, ninety-day verification cadence) is the recipe's strongest single setup move. It positions the matcher correctly: not as a credentialing-quality-control project but as compliance infrastructure that the directory and the claims pipeline depend on.

The Technology section is the chapter's clearest articulation of "why provider matching is structurally easier than patient matching": there is an authoritative public registry (NPPES), the NPI is a stable identifier (Type 1 NPI is for life), the data is generally clean (providers are professionally registered with credentials they care about), and the cardinality is two-to-three orders of magnitude smaller than patient matching. The "What the NPI Actually Is" subsection is correctly granular: Type 1 vs Type 2, the field set on each (legal name, credential string, license number plus state, taxonomy codes from NUCC, primary practice address vs mailing address, deactivation status), and the critical observation that NPPES is self-attested and the address fields are widely known to be stale. The "Two Sources of NPPES Data" subsection (downloadable bulk file vs registry API) and the "use both" recommendation is the right operational pattern. The "Where Provider Matching Differs From Patient Matching" subsection is correctly five-bulleted: better data quality, taxonomy-as-powerful-field, one-and-only-one Type 1 NPI as a hard constraint, Type 2 NPIs as many-to-many with people, deactivation status as a drift event, re-verification on a regulatory cadence, and lower volume.

The six-stage architecture (ingest and normalize, blocking and candidate generation, score, route by threshold, persist with audit, schedule re-verification) is the right shape for the problem. The four-bucket framing of "the work is in handling the dozen reliable edge cases" is correct: the matcher is not the hard part; the operational rhythm of keeping matches fresh on a regulated cadence is. The drift-snapshot pattern (capture the registry fields most likely to change at attachment time, compare on each re-verification, surface differences as drift events) is the recipe's most important architectural primitive and is correctly framed as load-bearing. The five blocking passes (license-number-plus-state, last-name metaphone plus first-initial plus state, last-name metaphone plus taxonomy plus state, ZIP plus last-name initial, phone-last-4 plus last-name initial) with their stated information-value ordering is well-chosen. The hard-filter-before-scoring pattern (deactivation, type mismatch, license-state mismatch) is correct.

The Honest Take is the recipe's most operationally pointed section. Five observations stand out: (1) "treating it as a credentialing-team problem rather than as a directory-and-claims problem" with the canonical organizational-duplication failure mode diagnosed precisely (the matcher gets duplicated three or four times, matches drift relative to each other, the directory says one thing and the claims-validation system says another); (2) "under-investing in the drift-detection pipeline" framed as the matcher-versus-static-snapshot distinction, with the closing "build the drift pipeline at the same time as the initial matcher; do not defer it"; (3) the per-segment re-verification cadence trap (Medicare Advantage has stricter requirements than commercial; Medicaid varies state by state) with the architect-for-it-from-the-start instruction; (4) the centrality of the deactivation flag with the "do not bury it. Surface it. Alarm on it. Make it the highest-priority drift event" framing; (5) the equity dimension correctly framed as smaller in scale than patient matching but real and consequential ("equity in matching is equity in access"). The closing "build it as compliance infrastructure, with the audit trail, retention discipline, and access control that comes with that designation" is the recipe's strongest closing line.

That said, four correctness gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items. (1) The architecture invokes a real-time onboarding API path, a daily re-verification path, and an `attach_npi` operation that mutates the assignment table consumed by claims, credentialing, the directory, and the network-adequacy reporting pipeline; the identity-boundary checks on these paths are not specified at the architectural level. The recipe inherits the chapter-wide identity-boundary pattern from 4.4-4.10 and 5.1; the consequence here is concrete: a misrouted `attach_npi` call (an authorization-bypass attempt, a forged event from a compromised credentialing source, an attacker-controlled `decision_metadata` field claiming a high score that was not actually computed) silently links an internal provider record to the wrong NPI, with downstream impact on every consumer of the assignment table. (2) The `attach_npi` operation performs four sequential DynamoDB calls plus an EventBridge emit without `TransactWriteItems` wrapping; failures between the assignment write, the schedule write, the audit-archive write, and the event emit leave the assignment in a half-applied state. Same chapter pattern as 5.1 Finding A1; the regulatory consequence here is sharper because the assignment table feeds the network-adequacy report. (3) The cohort-stratified accuracy monitoring is invoked as "required here too" with the explicit "the monitoring patterns from recipe 5.1 carry over directly" framing, but the operational threshold values, per-axis aggregation, and disparity-metric definitions are not specified. Same chapter pattern as 5.1 Finding A2 / 4.10 Finding A1 / 4.9 Finding A2 / 4.8 Finding A4; carries forward at HIGH severity because the recipe explicitly inherits the rigor and naming the threshold values is the difference between "we measure parity" and "we alert on disparity." (4) The `re_verify_npi` function's interaction with the `verification-schedule` table produces stale schedule entries: each re-verification writes a new `(verification_due_date, internal_provider_id)` item but does not delete or supersede the prior item, so over time the table accumulates expired schedule entries that the daily verification job will repeatedly pull as "overdue." At a 50K-provider network with a 90-day cadence, after a year the daily job would be processing each provider four to five times rather than once. This is a correctness gap with concrete cost-and-data-freshness consequences.

Eleven chapter-wide patterns repeat (audit-log retention floor, IAM ARN scoping, identity-boundary checks, governance SLA on M/U re-estimation, idempotency and DLQ coverage, OpenSearch availability fallback, real-time latency budget, cross-recipe orchestration with later Chapter 5 recipes, cohort PHI in CloudWatch dimensions, USPS / address-standardization vendor egress posture, API Gateway resource policy and WAF posture). Several are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by counting U+2014 byte sequences in the UTF-8 file). En dash count: 0 (verified by counting U+2013 byte sequences). 70/30 vendor balance is maintained; AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: the "open the provider directory of any health plan" hook, the "Sarah J Patel, MD, Family Medicine" running example carried into the Expected Results JSON, the "this is what duplicate patient records do" register from 5.1 carried into the "build it as compliance infrastructure" closing. Parenthetical asides land well. The 50K-active-providers / 200-new-onboardings-per-month deployment scenario is operationally specific. The Variations and Extensions section (LEIE, state medical board, Death Master File, FHIR Practitioner / PractitionerRole, multi-source taxonomy reconciliation, active-learning gold set, per-cohort m/u models, credentialing-system bidirectional sync, provider self-service portal, network-adequacy reporting) is well-scoped and frames each extension at the right grain.

Priority breakdown: 0 critical, 4 high, 9 medium, 7 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are localized correctness-and-compliance gaps; three surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose, and one (the schedule-table stale-entries issue) is a pseudocode-level correctness bug that the architecture should specify the upsert pattern for.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with the appropriate framing that "the provider data itself is generally lower-sensitivity than patient data but the matching pipeline can carry license numbers and personal addresses, so all services in the architecture run under the BAA on the same posture as patient-matching infrastructure." The "lower-sensitivity" framing is technically correct (provider names and practice addresses are typically public information) but the "matching artifacts can carry license numbers and personal addresses" qualification is the right one to make: the mailing address in NPPES is often the provider's home address, license numbers are not generally public to the same extent as practice addresses, and the cohort-stratified analytics dashboards include demographic data the institution should not lose track of.
- Customer-managed KMS keys for the S3 buckets, the DynamoDB tables, the OpenSearch domain, and the Lambda log groups. Encryption-in-transit posture is uniform: TLS for OpenSearch, KMS-encrypted indices, TLS for the API surface, server-side encryption for EventBridge.
- CloudTrail data events on the assignment and review-queue tables and on the audit-archive S3 buckets, with API Gateway and Lambda layer logging for the review-queue API. The CloudTrail retention "per the institution's records-retention policy (typically several years for credentialing records, longer for compliance attestations)" is correctly framed but should specify a floor.
- The "Per-Lambda least-privilege" framing in the Prerequisites IAM Permissions row, with the explicit "Never use `*` actions or `*` resources in production" admonition. The chapter pattern of pairing this with one or two scoped Resource ARN examples should apply here too.
- Synthetic data labeling is enforced in the Sample Data row: "never use real provider data in development environments." The "synthetic data based on representative naming-convention distributions and known-NPI seedings" is the right pattern.
- The deactivation flag is correctly elevated to "the most important field in the drift-detection pipeline, full stop" in the Honest Take, with the "do not bury it. Surface it. Alarm on it" instruction. This is the security-relevant counterpart to the chapter-wide pattern that surfaces wrongness rather than tolerating it.

### Finding S1: Real-Time Onboarding API, Daily Re-Verification Path, Attach-NPI, and Review-Queue API Lack Identity-Boundary Specification

- **Severity:** HIGH
- **Expert:** Security (PHI-adjacent integrity boundary, authorization, regulatory)
- **Location:** Architecture diagram shows `Real-Time Onboarding` flow `OS1 (OpenSearch) -> L2 (candidate-generator) -> L3 (pair-scorer) -> L4 (threshold-router) -> L7 (attach-npi)`; review-queue surface as `D2 (provider-review-queue) -> AG1 (API Gateway) -> CG1 (Cognito / IdP) -> UI1 (Credentialing Review UI) -> AG1 -> L8 (review-decision) -> L7 (attach-npi)`. Step 6 pseudocode `attach_npi(internal_record, matched_candidate, decision_metadata)` and `re_verify_npi(internal_provider_id, matched_npi)`.
- **Problem:** The recipe specifies the matching pipeline at flow-and-service granularity but is silent on the identity-boundary policy that controls who can invoke each path and what proves the caller is authorized to act on a particular provider record. The chapter pattern from Recipe 4.4 through 5.1 has converged on a structured identity-boundary specification including the rejection semantics, the metric emission, and the log-on-violation pattern. Recipe 5.2 inherits the concern with three concrete attack surfaces:

  1. **The real-time onboarding path's authentication context is unspecified.** A new internal provider record triggers candidate generation against OpenSearch, scoring, threshold routing, and (for auto-attach scores) NPI attachment. The credentialing system's role identity (the producer of the new internal record), the per-event integrity-check (a forged onboarding event with a real internal_provider_id but attacker-controlled demographics could trigger a wrong NPI attachment), and the consumer-side validation (the candidate-generator Lambda's input validation against a JSON schema, the credentialing-system signature verification on the inbound payload) are not specified. A misrouted or injected onboarding event would silently produce a candidate-set against OpenSearch, score against another provider's record, and (above the threshold) auto-attach the wrong NPI. The auto-attach path runs without any human in the loop above the threshold; the integrity of the inbound onboarding event is the only safeguard against a wrong-NPI attachment.

  2. **`attach_npi` is the recipe's most security-sensitive write path.** It mutates the `provider-npi-assignment` table, which is the anchor for downstream consumers: the credentialing system for cred-file updates, the network management system for directory updates, the claims-processing system for claim-time NPI validation, and the network-adequacy reporting pipeline for compliance reports. A misrouted `attach_npi` call (an authorization-bypass attempt, a system-emitted event for the wrong provider, an attacker-controlled `decision_metadata` field claiming a high score that was not actually computed) silently links an internal provider record to the wrong NPI, with downstream blast radius across every system that consumes the assignment event. The recipe's "even auto-attach should produce an audit trail" framing is correct in spirit; the architecture should specify the authentication and authorization context of every `attach_npi` invocation, including which Lambda execution role can call it, which event sources are accepted, and which payload fields are signed by the originating system.

  3. **The review-queue API's authentication context is named but the authorization context is not.** Cognito authenticates the credentialing or provider-data-management team (or the institution's IdP via SAML/OIDC); Cognito is identity, not authorization. The architecture should specify what the API Gateway / Lambda / DynamoDB layer enforces on top of the authenticated session: which credentialing specialist can review which queue, whether reviewers can see queues for clinical areas they do not own, whether reviewers can review pairs containing providers who are themselves on the reviewer's clinical team or in the reviewer's family (the chapter-pattern conflict-of-interest case from 5.1 applies equally here, in slightly different form: a credentialing reviewer should not adjudicate the NPI assignment for a provider who is themselves the reviewer or a relative of the reviewer).

  4. **`re_verify_npi` mutates the assignment table on a daily cadence and emits drift events.** A misrouted `re_verify_npi` call could overwrite a recent correction made via the review queue, emit a spurious drift event, or replay a deactivation flag that has since been reversed in NPPES. The function's authentication context (which Lambda role can call it, which event sources it accepts, what the idempotency key is across same-day retries) is not specified.

  5. **The HIPAA Privacy Rule's minimum-necessary requirement and the No Surprises Act's directory-accuracy attestation regime both depend on the identity boundary.** A reviewer who can access any provider's pair without an assigned-queue check exceeds minimum-necessary; an `attach_npi` call that succeeds without proving the calling event came from an authenticated credentialing source does not have the audit-trail attribution that compliance requires. Same regulatory ground as Recipe 5.1 Finding S1; the chapter editor should consolidate identity-check guidance into a chapter preface.

- **Fix:** Specify the identity-boundary policy and the rejection semantics at the architectural level the chapter has converged on. For the real-time-onboarding path, specify in the Lambda candidate-generator paragraph that the inbound event carries a producer-signed envelope (`source_system`, `source_record_id`, `event_id`, `signed_payload`); the candidate-generator Lambda validates the signature against the producer's known signing key (rotated per the institutional secret-rotation policy), validates the source_system is in the allowed-list, validates the event_id is unique within a sliding window (idempotency), and rejects events that fail any of these checks with a logged metric and a routing to the rejected-events DLQ.

  For `attach_npi`, specify the authorization context:

  ```
  FUNCTION attach_npi(internal_record, matched_candidate, decision_metadata):
      // decision_metadata.invocation_source is one of:
      //   "auto_attach_pipeline": invoked by the threshold-router
      //                           Lambda for an auto-attach score
      //   "review_queue_decision": invoked by the review-decision
      //                            Lambda for a human-reviewed match
      //   "batch_match_pipeline":  invoked by the monthly Glue job
      //                            during batch refresh
      //
      // Validate the caller's role matches the invocation_source:
      caller_role = current_lambda_execution_role()
      IF NOT caller_role_matches_invocation_source(caller_role,
                                                     decision_metadata.invocation_source):
          LOG("attach_npi invocation_source mismatch", ...)
          emit_metric("attach_npi_authorization_violation", value = 1)
          REJECT
      // For review_queue_decision, validate that the named reviewer
      // had an assigned queue containing the pair, and that the
      // reviewer is not in the conflict-of-interest list.
      IF decision_metadata.invocation_source == "review_queue_decision":
          IF NOT reviewer_authorized_for_pair(decision_metadata.reviewer_id,
                                                internal_record.internal_provider_id,
                                                matched_candidate.npi):
              LOG("reviewer not authorized for pair", ...)
              emit_metric("review_decision_authorization_violation", ...)
              REJECT
  ```

  For `re_verify_npi`, specify the idempotency and authentication context: the function is invoked by the daily Step Functions workflow with `(internal_provider_id, verification_due_date)` as the idempotency key; the Lambda validates that the calling Step Functions execution role matches the expected re-verification role; same-day retries are idempotent at the (provider, due_date) tuple.

  Reference Recipe 4.4-4.10 and 5.1 Finding S1 as the chapter-wide pattern. For 5.2 specifically, the assignment-as-anchor consequence (downstream consumers in claims, credentialing, directory, and network-adequacy reporting all consume the assignment) earns the HIGH severity.

### Finding S2: Audit-Log Retention Specified as "Per Institution's Records-Retention Policy" Without Architectural Floor (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, audit, forensic)
- **Location:** Prerequisites CloudTrail row: *"CloudTrail logs encrypted with KMS and retained per the institution's records-retention policy (typically several years for credentialing records, longer for compliance attestations)."*
- **Problem:** Specifying audit retention as "per the institution's records-retention policy" is correct in spirit but defers the architectural floor to whoever ships the system. Three concrete consequences:

  1. **The credentialing-record-equivalent posture is named in prose but not enforced architecturally.** The recipe correctly frames the matching audit log as "a regulatory artifact, particularly for the network-adequacy compliance reports" with "tighter access control than for general analytics." Credentialing records typically have a 7-to-10-year retention floor under state Medical Practice Act regulations and NCQA accreditation standards; under HIPAA, the Privacy Rule's 6-year minimum applies to certain documents but does not set the credentialing-record floor. The architecture should specify the minimum floor as the longer of (HIPAA 6-year floor, the institution's documented credentialing-record retention policy, the state-specific credentialing retention statute, and the network-adequacy attestation retention requirement).

  2. **The S3 Object Lock / Glacier-tier transition policy is not specified.** The audit substrate is supposed to be the substrate that proves network adequacy at the regulator's request; immutability requires S3 Object Lock with Compliance mode (or Governance mode with stricter controls). Without architectural specification, the implementation may use Standard storage with versioning, which is mutable by privileged users.

  3. **CloudTrail data event volume is bounded but not zero.** Every read of `provider-npi-assignment`, `verification-schedule`, and `provider-review-queue` produces a data event; for a 50K-provider system with daily re-verification of due records, this is potentially millions of CloudTrail events per month. The retention policy interacts with the CloudTrail-S3 cost model; the cost estimate may be undercounted at the audit volume.

- **Fix:** Replace the "per the institution's records-retention policy" framing with an explicit floor in the CloudTrail and Audit paragraphs:

  *"Audit-log retention is the longer of: 7 years (credentialing-record minimum floor), the institution's documented credentialing-record retention policy, the state-specific credentialing retention statute, and the network-adequacy attestation retention requirement. Audit logs are stored in a dedicated S3 bucket with Object Lock in Compliance mode for immutability and a lifecycle policy that transitions to S3 Glacier Deep Archive after 90 days for cost optimization. CloudTrail data events are forwarded to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. The retention floor is enforced at the bucket-policy and Object-Lock-configuration level, not at application logic."*

### Finding S3: LEIE / Sanction-List Cross-Check Treated as a Variation Rather Than a Required Production Control

- **Severity:** MEDIUM
- **Expert:** Security (federal compliance, payer integrity)
- **Location:** "Why This Isn't Production-Ready" entry on sanction-list integration: *"The OIG List of Excluded Individuals/Entities (LEIE) is a separate authoritative source of providers excluded from federal healthcare programs ... Cross-checking the matched NPI against the LEIE catches sanctioned providers before they end up in the directory."* And in Variations and Extensions: *"Sanction-list integration (LEIE) as a parallel verification pipeline."*
- **Problem:** The recipe places LEIE cross-checking in the production-gaps and variations sections, framing it as a "you'll want to add this" feature. In the federal-payer compliance regime, LEIE checks are not optional: 42 USC § 1320a-7 prohibits federal healthcare programs from paying for items or services furnished by an excluded individual or entity, and OIG sub-regulatory guidance recommends that providers be screened against the LEIE prior to hire and on a monthly basis thereafter. <!-- The OIG Special Advisory Bulletin on the Effect of Exclusion from Participation in Federal Health Care Programs is the primary guidance; the chapter editor should verify the current citation. --> For organizations participating in Medicare Advantage, Medicaid Managed Care, or any federally-funded program, the LEIE check is table stakes. Three concrete consequences:

  1. **A matched NPI without a LEIE cross-check exposes the institution to recoupment risk.** A claim paid to an excluded provider is recoupable; CMP penalties under § 1320a-7a may apply. The matcher's output is the substrate the credentialing system, claims pipeline, and directory build on; if the matcher does not surface the exclusion status, downstream systems inherit the gap.

  2. **The federal-payer compliance program is the same population the No Surprises Act regulates.** The recipe correctly elevates the No Surprises Act to compliance infrastructure framing in the Honest Take; the LEIE check belongs in the same architectural tier, not in variations.

  3. **The architectural integration is structurally identical to the NPPES drift-detection pattern the recipe already specifies.** Monthly LEIE file ingest to S3, normalize, index, cross-check at attach time and on a monthly batch refresh, emit `provider_sanctioned` events on EventBridge with immediate consumer fan-out (claims hold, directory removal, credentialing review). The recipe's drift-detection-and-event-emit primitives transfer directly.

- **Fix:** Promote LEIE integration from variations to the main architecture. Add to the architecture diagram a parallel `LEIE Verification` flow consuming the monthly OIG LEIE file, with a `leie-sanction-status` table or column on `provider-npi-assignment` carrying the most recent check timestamp and result. Add to the Step Functions monthly batch-refresh workflow a step that cross-checks every active assignment against the latest LEIE file. Add to the EventBridge fan-out a `provider_sanctioned` detail-type that downstream consumers (claims, credentialing, directory) subscribe to. Update the Honest Take to name LEIE alongside the deactivation flag as the highest-priority drift events. Reference 42 USC § 1320a-7 and the OIG Special Advisory Bulletin as the regulatory anchor.

### Finding S4: Provider Data "Lower-Sensitivity" Framing Risks Under-Investing in Controls Around the Mailing Address and License Number

- **Severity:** LOW
- **Expert:** Security (PHI-adjacent, state-law variations)
- **Location:** Prerequisites BAA row: *"The provider data itself is generally lower-sensitivity than patient data but the matching pipeline can carry license numbers and personal addresses, so all services in the architecture run under the BAA on the same posture as patient-matching infrastructure."* And the S3 paragraph: *"The provider data is generally lower-sensitivity than patient data (provider names and practice addresses are typically public information, since they appear in directories), but the matching artifacts can carry license numbers and personal addresses, so the same encryption and access discipline applies."*
- **Problem:** The "lower-sensitivity than patient data" framing is technically defensible (practice addresses are public) but understates two specific concerns:

  1. **The NPPES mailing address is often the provider's home address.** The recipe correctly notes that "the mailing address (often a billing or back-office address, not the practice address)" but in solo-practice and small-group cases the mailing address is the provider's residential address. Several states (California, Massachusetts, New York, others) have Address Confidentiality Programs that protect residential addresses for domestic-violence survivors, witnesses, and other safety-sensitive populations; some healthcare providers participate in these programs. The matcher should treat the mailing address with the same care it would treat patient PHI when the address is residential or when the provider is in a state ACP.

  2. **License numbers are not uniformly public.** Some state medical boards publish license numbers; others publish only verification status given the provider's name. License numbers in combination with name and date of birth can enable identity theft for credentialing fraud schemes that target provider identity rather than patient identity. The matcher's audit archive should treat the license-number-plus-name combination with PHI-adjacent care.

  3. **The cohort-stratified accuracy dashboard surfaces demographic data.** Cohort labels (naming-convention-based, rural-vs-urban, recently-enumerated-vs-tenured) are derived from provider attributes; the dashboard's row-level access controls are inherited from the QuickSight specification but the underlying Athena access path is the broader exposure surface. Same gap as Recipe 5.1 Finding A10.

- **Fix:** Soften the "lower-sensitivity" framing in the BAA and S3 paragraphs to: *"Provider data is mixed-sensitivity. Practice addresses, primary taxonomy, and active license numbers are typically public; the mailing address (often residential), state-board license records, and the demographic data underlying cohort-stratified analytics are not. The matching pipeline runs under BAA on the same encryption-and-access posture as patient-matching infrastructure, with additional care for the mailing-address field when the provider is enrolled in a state Address Confidentiality Program (a `mailing_address_protected` flag should suppress the address from operational displays, the directory, and any non-essential audit surfaces)."* Reference state-specific Address Confidentiality Program statutes as relevant.

### Finding S5: Cohort PHI in CloudWatch Metric Dimensions (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Cohort-stratified accuracy monitoring paragraph: *"per-cohort match rate, per-cohort review-queue depth, per-cohort post-match drift rate, with alert thresholds and a documented remediation pathway when disparities cross threshold."*
- **Problem:** Same chapter-wide pattern as Recipe 4.4-4.10 / 5.1 Finding S3. CloudWatch metric dimensions cannot exceed 30 characters per dimension name and cannot be removed once published; emitting raw cohort attributes (naming-convention category, geographic-region category) as metric dimensions is both a cost concern (metric cardinality explosion) and a privacy concern (the metric stream is queryable by any role with `cloudwatch:GetMetricData`).
- **Fix:** Specify in the CloudWatch paragraph that cohort dimensions on metrics use bucketed, non-reversible cohort labels from the institutional cohort registry rather than raw provider attributes. The cohort-label-to-attribute mapping is stored in a separate, access-controlled table and is loaded at dashboard-render time only by roles authorized for cohort interpretation.

### Finding S6: IAM "Never `*` Actions or `*` Resources in Production" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as Recipe 4.1-5.1.
- **Fix:** Inline scoped ARN examples for the highest-stakes actions: `dynamodb:UpdateItem` on `arn:aws:dynamodb:<region>:<account>:table/provider-npi-assignment`; `s3:PutObject` on `arn:aws:s3:::<env>-provider-matching-audit-archive/audit/*`; `es:ESHttpPost` on the OpenSearch domain ARN with index-level path scoping; `events:PutEvents` on `arn:aws:events:<region>:<account>:event-bus/provider-assignment-and-drift-events`. Or consolidate into the chapter preface.

### Finding S7: Provider Self-Service Portal Disclosure Policy (Forward-Looking)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Variations and Extensions: *"Provider-self-service portal. A portal feature that lets providers see (and request corrections to) the demographic data the institution has on file for them."*
- **Problem:** Sibling to Recipe 5.1 Finding S5. Surfacing institution-held demographic data to the authenticated provider is itself a disclosure event under some state laws when the data was sourced from third parties (claims feeds, network-agreement counterparties). The variation should name the disclosure-policy gate as a prerequisite.
- **Fix:** Add a sentence to the Provider Self-Service variation: *"Before surfacing stored demographic data to the provider, the institution should review the data-disclosure policy: data sourced from the provider's own NPPES self-attestation or credentialing application is appropriate to display; data sourced from third-party feeds (claims, partner-organization shares) may have separate disclosure-and-consent requirements that the policy framework needs to address before the self-service feature surfaces it."*

---

## Architecture Expert Review

### What's Done Well

- The six-stage architecture (ingest and normalize, blocking and candidate generation, score, route by threshold, persist, schedule re-verification) is the right shape for a matching-against-authoritative-registry workload. The dual-pipeline pattern (Glue + Splink for monthly batch refresh; Lambda + OpenSearch for real-time onboarding) is the correct workload split, mirroring the 5.1 pattern with the registry-anchored deviation that the Lambda path now does one-sided lookup against an external authoritative source rather than pairwise comparison across the institution's own database.
- The five-blocking-pass starting set is well-chosen and correctly ordered by information value. Pass 1 (`license_number + license_state`) is the highest-information lookup and "often returns a single candidate" with the candidate "almost always the right answer." Pass 2 (`last_name_metaphone + first_initial + state`) catches records without a license-number field. Pass 3 (`last_name_metaphone + primary_taxonomy + state`) is useful for spelling variations. Passes 4-5 (`zip + last_name_initial`, `phone_last_4 + last_name_initial`) round out the recall-vs-cost trade with the explicit framing that the phone pass is "low yield" and "useful as a tiebreaker."
- The hard-filter-before-scoring pattern (deactivation, type mismatch, license-state mismatch) is the correct order. The "deactivated NPIs only match if the internal record is also marked inactive" framing handles the edge case explicitly. The "Type 1 vs Type 2 type-mismatch fail" filter prevents the chapter-canonical "individual provider matched to billing entity" confusion.
- The drift-snapshot pattern is the recipe's single most important architectural primitive and is correctly architected. Capture the registry fields most likely to change (practice address, primary taxonomy, all taxonomies, deactivation status, last update date) at attachment time; compare current registry values to the snapshot at each re-verification; emit drift events for differences. The "drift detection is the difference between a matcher that keeps the directory accurate and a matcher that produces a static snapshot that decays" framing in the Honest Take is the recipe's strongest single architectural claim.
- The margin requirement on routing (top-score minus runner-up-score must exceed `MIN_MARGIN`) catches the "multiple Sarah Patels in the state" confounder that pure absolute thresholds miss. The "9.5 with a runner-up of 9.3 is suspicious" example is operationally precise.
- The DynamoDB schema is well-designed for the access patterns: `provider-npi-assignment` keyed on `internal_provider_id` for resolved-identity lookups; `verification-schedule` keyed on `(verification_due_date, internal_provider_id)` for the daily verification job's date-range query; `provider-review-queue` keyed on `(queue_id, candidate_pair_id)` for queue-by-area assignment. On-demand capacity choice handles the bursty batch-refresh-day-vs-quiet-day pattern.
- The "centralize the matcher as a shared service with a single source of truth" framing in the Honest Take is the recipe's most operationally pointed framing and the correct architectural posture. The "credentialing care for compliance, network management for directory, claims for validation, network adequacy for reports - each builds their own version - matches drift" failure mode is precisely diagnosed.
- The Step Functions orchestration partitioning (monthly batch-refresh workflow, daily re-verification workflow, real-time onboarding workflow) is the right separation of concerns. Each workflow runs at its appropriate cadence with its appropriate substrate (Glue for monthly batch volumes, Lambda for daily and real-time workloads).
- The "Why This Isn't Production-Ready" section names twelve gaps (threshold tuning, taxonomy mapping, per-segment cadence, drift-event downstream, backfill, identity-fraud detection, LEIE, state board, real-time latency, audit retention, equity, idempotency, cross-recipe orchestration). The breadth is appropriate for a Simple-tier recipe and honestly tells the reader how much sits between the recipe and a production deployment.

### Finding A1: Attach-NPI Operation Is Not Atomic; Sequential PutItem Calls Leave Half-Updated State on Partial Failure

- **Severity:** HIGH
- **Expert:** Architecture (correctness, data-integrity, audit-trail consistency, network-adequacy reporting integrity)
- **Location:** Step 6 pseudocode `attach_npi`, the sequential call block:

  ```
  // Step 6B: persist the assignment.
  DynamoDB.PutItem("provider-npi-assignment", { ... })

  // Step 6C: schedule the next re-verification.
  DynamoDB.PutItem("verification-schedule", { ... })

  // Step 6D: write the audit record.
  write_to_audit_archive({ ... }, "npi_attached")

  // Step 6E: emit the assignment event for downstream consumers.
  EventBridge.PutEvents([{ ... }])
  ```

- **Problem:** The pseudocode performs four sequential write calls without a `TransactWriteItems` wrapper or an outbox pattern. A failure between any two steps leaves the system in an inconsistent state. Concrete failure modes:

  1. **Failure after the assignment write but before the schedule write:** the assignment exists, the daily re-verification job has no scheduled work for this provider, so the next regulatory cycle (90 days, depending on segment) misses this provider entirely. The "verified within last 90 days" SLA reporting metric the recipe lists in Performance Benchmarks is silently false for this provider; the network-adequacy report claims compliance the system cannot prove.

  2. **Failure after the schedule write but before the audit-archive write:** the assignment is durable, the schedule is in place, but no audit trail of the decision was created. The recipe's "build it as compliance infrastructure, with the audit trail, retention discipline, and access control that comes with that designation" claim breaks: a compliance-questioned attachment cannot be defended because the audit record is missing.

  3. **Failure after the audit-archive write but before the EventBridge emit:** the attachment is durable, the audit trail is recorded, but downstream consumers (credentialing, network management, claims, network-adequacy reporting) never learn about it. The directory remains stale; the claims-validation system continues to reject claims using the now-attached NPI; the credentialing system's cred-file is not updated.

  4. **The `re_verify_npi` function has the same problem.** Step 6 / re_verify_npi performs `UpdateItem` on the assignment, `PutItem` on the schedule, and conditionally `PutEvents` for each drift type. A failure mid-sequence leaves the assignment updated with the new drift snapshot but no scheduled next verification, or the next-verification scheduled but the drift events not emitted, with the operations team never learning that a provider's NPI was deactivated.

  The Python code review's analogous Finding 5 (for Recipe 5.1) documents the same pattern in implementation; the architectural pseudocode here has the same collapse. The recipe's "Why This Isn't Production-Ready" section names "Idempotency and retry semantics" as a gap but does not specify the atomic-write pattern. The "build it as compliance infrastructure" framing depends on the attach-NPI state being either fully present or fully absent, not partially-applied.

- **Fix:** Specify `TransactWriteItems` for the synchronous DynamoDB writes and an outbox pattern for the EventBridge emit and the audit-archive write. The transaction wraps the assignment Put and the schedule Put atomically; the audit-archive write and the EventBridge emit are decoupled via an outbox pattern (write the outbox row inside the transaction, a downstream Lambda or DynamoDB Stream consumer drains the outbox and emits the events idempotently):

  ```
  // Step 6B/6C atomic write of assignment + schedule + outbox row.
  DynamoDB.TransactWriteItems(
      TransactItems = [
          { Put: { TableName: "provider-npi-assignment",
                    Item: { internal_provider_id, matched_npi,
                              match_score, drift_snapshot, ...,
                              outbox_pending: true,
                              outbox_event_id: new UUID } } },
          { Put: { TableName: "verification-schedule",
                    Item: { verification_due_date,
                              internal_provider_id, matched_npi, ... },
                    ConditionExpression:
                        "attribute_not_exists(verification_due_date) OR matched_npi = :npi",
                    ExpressionAttributeValues: { ":npi": matched_npi } } },
          { Put: { TableName: "outbox",
                    Item: { outbox_event_id,
                              event_payload: { internal_provider_id,
                                                 matched_npi, ... },
                              status: "pending" } } },
      ]
  )

  // Step 6D/6E: outbox drainer Lambda consumes pending rows,
  // writes to the audit-archive S3 bucket, emits to EventBridge,
  // and marks the outbox row drained. Idempotent at the
  // outbox_event_id key.
  ```

  Add a paragraph to the architecture pattern naming the atomic-write pattern, the outbox pattern for the audit-and-event side effects, and the partial-failure-recovery semantics. The outbox drainer's CloudWatch alarm fires when the pending row age exceeds an SLA (typically minutes for assignment events). The same TransactWriteItems pattern applies to `re_verify_npi`, with the additional consideration of the schedule-table stale-entry bug specified separately under Finding A3.

  Reference Recipe 5.1 Finding A1 / 4.6 Finding 2 / 4.7 Finding 5 / 4.10 Finding A4 as the chapter pattern. For Recipe 5.2 specifically, the network-adequacy reporting consequence is the sharpest distinguisher: a half-applied attachment that lacks a scheduled re-verification silently breaks the "verified within 90 days" compliance metric.

### Finding A2: Cohort-Stratified Accuracy Thresholds and Metric Definitions Referenced as "Required Here Too" but Undefined (Chapter-Wide Pattern)

- **Severity:** HIGH
- **Expert:** Architecture (fairness, civil-rights implications, the recipe's explicit inheritance from 5.1)
- **Location:** General Architecture Pattern paragraph: *"Cohort-stratified accuracy monitoring is required here too. Provider-matching errors are not uniformly distributed across cohorts. Providers with names from naming conventions outside the dominant culture, providers with newly-issued NPIs (less drift history, less data to cross-reference), and providers in certain rural states (where multiple providers share addresses or where address standardization is harder) all match at different rates than the dominant cohort. The monitoring patterns from recipe 5.1 carry over directly: per-cohort match rate, per-cohort review-queue depth, per-cohort post-match drift rate, with alert thresholds and a documented remediation pathway when disparities cross threshold."* And the Honest Take's equity paragraph: *"Equity in matching is equity in access."*
- **Problem:** The recipe explicitly inherits the cohort-stratified accuracy framework from 5.1 ("the monitoring patterns from recipe 5.1 carry over directly") but does not specify the operational thresholds, metric definitions, per-axis aggregation policy, chronic-suppression handling, or gold-set cohort-coverage discipline. The architecture is silent on:

  1. **What the alert threshold value should be.** Same gap as 5.1 Finding A2; the Performance Benchmarks table has no cohort-parity row at all (5.1's table cited "0.85-0.95 after cohort-specific tuning"). The threshold-at-which-the-alert-fires is implementation-defined.

  2. **How each metric is computed.** Match-rate parity could be operationalized as the ratio of cohort-specific recall (true matches found / true matches in the cohort), cohort-specific auto-attach precision, cohort-specific review-queue depth-per-FTE, or cohort-specific post-match drift rate. The recipe lists three metrics ("per-cohort match rate, per-cohort review-queue depth, per-cohort post-match drift rate") but does not specify their operationalization or the disparity-ratio formula.

  3. **Per-axis aggregation policy.** Cohort axes named in the recipe include naming-convention-defined cohorts, recently-enumerated-vs-tenured cohorts, and rural-vs-urban cohorts. Setting a single chapter-wide threshold may miss axis-specific patterns; the architecture should specify per-axis thresholds at minimum.

  4. **Chronic-suppression-as-fairness-signal pattern.** Cohorts with structurally low volume (rare naming-convention categories in the deployed region, very-recently-enumerated NPIs in the early launch period) silence the disparity calculation; the system reports "no signal" when the signal is "this cohort is structurally under-represented and we cannot tell whether the matcher works for them." Same gap as 5.1 Finding A2.

  5. **The labeled gold set's cohort coverage is itself an equity concern.** The "Why This Isn't Production-Ready" threshold-tuning paragraph mentions building a labeled gold set ("a few hundred to a few thousand internal records with manually-verified NPIs") but does not specify cohort-stratified gold-set construction. A gold set that is 90 percent dominant-culture-cohort produces threshold tuning that overfits the dominant cohort.

  The recipe's repeated framing of "the monitoring patterns from recipe 5.1 carry over directly" earns the inheritance of the same operational specification 5.1 owes; carrying forward 5.1's gap into 5.2 propagates the same disparity-blind monitoring posture to the foundational provider matcher every downstream credentialing, claims, and directory consumer builds on.

- **Fix:** Specify the thresholds and the metric definitions in the General Architecture Pattern subsection on cohort-stratified accuracy monitoring. Use the same chapter-pattern threshold structure 5.1 should adopt (per Finding A2):

  ```
  // Cohort-disparity thresholds (per chapter-wide policy; per-axis-per-
  // metric overrides set by the equity-review committee):
  //   MATCH_RATE_DISPARITY_THRESHOLD               = 0.10
  //   AUTO_ATTACH_PRECISION_DISPARITY_THRESHOLD    = 0.05
  //   REVIEW_QUEUE_DEPTH_PER_FTE_DISPARITY         = 0.20
  //   POST_MATCH_DRIFT_RATE_DISPARITY              = 0.05
  //   MIN_COHORT_SAMPLE_SIZE = 100 candidate pairs per cohort per
  //     measurement window (lower than 5.1's 200 because provider
  //     volumes are smaller; document the rationale). Below this,
  //     disparity calculation is suppressed and the cohort is
  //     escalated to the equity committee as an under-representation
  //     signal.
  ```

  Add a paragraph naming the per-axis-per-metric override mechanism, the chronic-suppression-as-fairness-signal pattern, the cohort-stratified gold-set construction discipline, and the diagnose-and-address workflow that fires when an alert crosses threshold.

  Reference Recipe 5.1 Finding A2, 4.10 Finding A1, 4.9 Finding A2, 4.8 Finding A4 as the chapter-wide pattern. The chapter editor should consider whether the equity-instrumentation framework belongs in chapter preface; for 5.2 specifically, the inheritance from 5.1 is explicit and the threshold specification belongs in main text.

### Finding A3: Re-Verification Path Writes New Schedule Entries Without Removing Stale Ones; Daily Job Will Repeatedly Process Same Provider

- **Severity:** HIGH
- **Expert:** Architecture (correctness, operational, cost)
- **Location:** Step 6 pseudocode `attach_npi` Step 6C and `re_verify_npi`:

  ```
  // Step 6C: schedule the next re-verification.
  DynamoDB.PutItem("verification-schedule", {
      verification_due_date: today() + VERIFICATION_CADENCE_DAYS,
      internal_provider_id: internal_record.internal_provider_id,
      ...
  })
  ```

  And in `re_verify_npi`:
  ```
  // Re-schedule the next verification.
  DynamoDB.PutItem("verification-schedule", {
      verification_due_date: today() + VERIFICATION_CADENCE_DAYS,
      internal_provider_id: internal_provider_id,
      matched_npi: matched_npi
  })
  ```

  And the DynamoDB schema description: *"`verification-schedule` keyed on `(verification_due_date, internal_provider_id)` holds the scheduled re-verification work, sortable by due date so the daily verification job can pull due-or-overdue records efficiently."*

- **Problem:** The schedule table is keyed on the composite `(verification_due_date, internal_provider_id)`. Each re-verification writes a new row with a new due_date but does not delete or supersede the prior row. Two concrete consequences:

  1. **Stale entries accumulate.** After the first re-verification, the table holds two rows for the same provider: one with the original due_date (now in the past) and one with the new due_date (90 days in the future). After the second re-verification, three rows. After a year of 90-day cadences, four to five rows per provider. At 50K active providers, the table grows from 50K rows at launch to 200-250K rows after a year, with most of the growth being stale entries.

  2. **The daily verification job re-processes providers at the rate of stale-entry accumulation.** The recipe's framing ("pull due-or-overdue records efficiently") describes a query like `verification_due_date <= today()`. With stale entries that match this query forever (they have due_dates in the past), the daily job pulls every prior schedule entry for every previously-verified provider on every run. After a year, the daily job is re-processing each provider four to five times per day rather than once per cycle. The cost implications are concrete: more Lambda invocations, more NPI Registry API calls (which is rate-limited), more DynamoDB writes, more EventBridge events. The data-freshness implications are also concrete: each re-fetch may produce a different drift event if the registry data changed between calls, leading to spurious drift events for the same drift.

  This is also flagged in the code review (Note 2) as an implementation-level observation. The architectural pseudocode has the same gap. The "Why This Isn't Production-Ready" section names "Idempotency and retry semantics" but the schedule-table stale-entry pattern is a different bug: it is not a duplicate-event-delivery bug, it is a single-call-leaves-the-prior-call's-state-in-place bug.

- **Fix:** Either (a) change the schedule schema to be keyed on `internal_provider_id` alone, with `verification_due_date` as a sortable attribute and a GSI that indexes by due_date for the daily-job's range query; or (b) keep the composite key but specify the upsert pattern: when writing a new schedule entry, also delete the prior entry for the same `internal_provider_id`. Option (a) is simpler and more correct because it mirrors the assignment table's "one row per provider" model; option (b) is a smaller architectural change but adds a delete to every write.

  Specify in the pseudocode:

  ```
  FUNCTION schedule_next_verification(internal_provider_id, matched_npi,
                                        prior_due_date_to_supersede):
      // Use TransactWriteItems to atomically remove the prior
      // schedule entry and write the new one.
      DynamoDB.TransactWriteItems(
          TransactItems = [
              { Delete: { TableName: "verification-schedule",
                            Key: { verification_due_date: prior_due_date_to_supersede,
                                    internal_provider_id: internal_provider_id } } },
              { Put:    { TableName: "verification-schedule",
                            Item: { verification_due_date: today() + VERIFICATION_CADENCE_DAYS,
                                    internal_provider_id: internal_provider_id,
                                    matched_npi: matched_npi,
                                    scheduled_at: current_utc_timestamp() } } },
          ]
      )
  ```

  Or, preferred, change the schedule-table schema so each provider has at most one row:

  *"`verification-schedule` keyed on `internal_provider_id` holds the next re-verification timestamp for each provider. A GSI on `(verification_due_date)` (or `(year-month-day, due_count)` to bound the GSI partition size) supports the daily verification job's date-range query: pull all providers with `verification_due_date <= today()`. Writing a new schedule entry uses an UpdateItem that overwrites the prior `verification_due_date` atomically."*

  Add the corresponding update to `attach_npi` and `re_verify_npi` pseudocode. Reference the assignment-table single-row-per-provider model as the pattern to mirror.

### Finding A4: Per-Segment Re-Verification Cadence Configuration Is Named in the Honest Take but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (regulatory, multi-line-of-business)
- **Location:** Honest Take's third trap: *"The third trap, specific to organizations with multiple lines of business: configuring the re-verification cadence as a global constant rather than per-segment. Medicare Advantage has stricter requirements than commercial. Medicaid has state-by-state variation ... Architect for per-segment cadences from the start."* And the pseudocode using a single `VERIFICATION_CADENCE_DAYS` constant.
- **Problem:** The recipe correctly diagnoses the per-segment cadence trap and prescribes "architect for per-segment cadences from the start" but the actual architecture does not include the per-segment configuration mechanism. The pseudocode's single `VERIFICATION_CADENCE_DAYS` constant produces a global ninety-day cadence; switching to a per-segment cadence after a Medicare Advantage audit (which the Honest Take warns against) is a database-schema change, a Lambda-logic change, and a backfill of every existing schedule entry. The architecture should specify the per-segment configuration model, the segment-resolution logic at scheduling time, and the handling of providers in multiple segments (a provider serving both Medicare Advantage and commercial members has two effective cadences; the matcher takes the shorter one).
- **Fix:** Add to the architecture a `verification-cadence-config` table or DynamoDB attribute on `provider-npi-assignment` carrying the segment-specific cadence:

  ```
  // verification-cadence-config keyed on segment_id:
  //   segment_id: "medicare_advantage" | "medicaid_<state>" |
  //                "commercial" | "behavioral_health" | ...
  //   cadence_days: integer (typically 30, 60, 90, or 120)
  //   regulatory_basis: text (CMS MA Provider Directory rule,
  //                            NCQA standard, state Medicaid rule, ...)
  //   last_reviewed_at: timestamp (the segment cadence is itself
  //                                  a periodic-review artifact)
  //
  // The provider-npi-assignment table carries provider_segments
  // as a list. attach_npi computes the effective cadence as the
  // minimum across the segments and writes that into next_verification_due_at.
  // A change in a segment's cadence triggers a re-schedule for
  // every provider in that segment.
  ```

  Add a paragraph to the architecture pattern naming the per-segment model and the segment-overlap policy. Reference Recipe 5.1 Finding A4 (M/U re-estimation governance) for the analogous configuration-as-data pattern.

### Finding A5: Type 2 NPI Affiliations Are Diagnosed in The Technology Section but the Persistence Model Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (data model, downstream-consumer integration)
- **Location:** The Technology section: *"The same individual provider can be associated with several Type 2 NPIs at the same time: their solo practice's Type 2, the hospital they are credentialed at, the academic medical center group they bill under for some of their work, and so on."* And: *"Some operational workflows (credentialing) care about Type 1. Some (claims, network adequacy) care about both. The matching system needs to know which it is asking about."*

  The pseudocode and `provider-npi-assignment` schema:

  ```
  DynamoDB.PutItem("provider-npi-assignment", {
      internal_provider_id: ...,
      matched_npi: matched_candidate.npi,
      ...
  })
  ```

- **Problem:** The recipe correctly diagnoses the Type 2 multi-affiliation pattern but the persistence model stores a single `matched_npi`. The Ingredients table mentions `provider-npi-assignment` "stores the provider-NPI assignments" without specifying that an assignment can hold a Type 1 NPI plus a list of Type 2 affiliations. The drift snapshot only carries the matched NPI's fields; if the provider gains a new Type 2 affiliation (joins a new hospital, becomes credentialed at a new group), the matcher does not capture it.

  Three concrete consequences:

  1. **Claims and network-adequacy reporting consumers receive an under-specified assignment.** Claims billed under the hospital's Type 2 NPI cannot be validated against the matched record because the record only has the Type 1.
  2. **The drift-detection pipeline misses Type 2 affiliation changes.** A provider who joins a new hospital adds a Type 2 association in NPPES; the matcher's drift detection should surface this as a `type2_affiliation_added` event but cannot because the Type 2 list is not persisted.
  3. **The "the matching system needs to know which it is asking about" framing in The Technology section is correct but the architecture conflates the two.** Either two assignment tables (one for Type 1, one for Type 1-to-Type 2 affiliations) or one table with explicit Type 1 and Type 2 fields would address this.

- **Fix:** Update the `provider-npi-assignment` schema to include `matched_type1_npi` (the Type 1 individual NPI) and `matched_type2_npi_list` (the list of Type 2 affiliations the provider currently holds, with each entry carrying the Type 2 NPI, the affiliated organization name, the effective date range, and a `is_primary_billing` flag). Update the drift snapshot to include the Type 2 list. Add to the drift-event taxonomy a `type2_affiliation_added` and `type2_affiliation_removed` event with a documented downstream consumer (claims-validation system, network-adequacy reporting).

  Add to the architecture pattern: *"The assignment record carries the provider's Type 1 NPI and a list of Type 2 affiliations the provider currently holds. The match operation produces both: the Type 1 match is the canonical individual identity; the Type 2 list is constructed from the NPPES record's `Other Provider Identifier` cross-references and the provider's organizational credentials in the institutional credentialing system. Drift detection surfaces Type 2 affiliation changes as separate events from Type 1 drift, with downstream consumers (claims validation, network-adequacy reporting) subscribing to the events relevant to their workflow."*

### Finding A6: Internal Record's Pre-Existing NPI Conflict Resolution Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, edge-case handling)
- **Location:** Step 3 pseudocode Pass 0:
  ```
  // Pass 0: existing NPI confirmation. If the internal record
  // already claims an NPI, look it up directly; this is the
  // confirmation path rather than the search path.
  IF internal_record.has_existing_npi:
      candidate = nppes_index.get_by_npi(internal_record.existing_npi)
      IF candidate IS NOT NULL:
          candidates.add(candidate)
      // do not return here; we still want to check other passes
      // in case the existing NPI is wrong.
  ```
  And the comment "do not return here; we still want to check other passes in case the existing NPI is wrong."
- **Problem:** The pseudocode correctly notes that the existing NPI may be wrong and continues to other passes, but the routing logic does not specify what happens when the existing NPI does not match the highest-scoring candidate from search. The recipe explicitly calls out this scenario in the Problem section: *"A provider whose specialty taxonomy in your system is 'Family Medicine' and in the registry is 'Family Medicine, Adolescent Medicine, Sports Medicine' because the registry stores all taxonomies the provider self-attests, not just the primary one ... A provider whose office address changed six months ago and your system has the new address but the registry has the old one because the provider has not updated their NPPES entry."*

  Concrete edge cases the architecture should specify:

  1. **The existing NPI is wrong (the credentialing system has an incorrect NPI from a typo or a prior bad match).** The matcher's search returns a higher-scoring candidate; the existing NPI is the lower-scoring candidate. The architecture should surface this as a "potential existing-NPI correction" event, route to review (with the existing NPI flagged for the reviewer's attention), and not auto-attach the new NPI without explicit reviewer authorization.

  2. **The existing NPI is right but matches less well than another candidate.** A common-name provider whose existing NPI is correct but whose internal-record taxonomy does not match the registry primary taxonomy may produce a higher-scoring candidate that is actually wrong. The architecture should weight the existing-NPI signal heavily as a tiebreaker.

  3. **The existing NPI is for a deactivated registry entry.** The hard-filter logic correctly drops deactivated NPIs from the candidate set, but if the existing NPI itself is deactivated, the architecture should surface this immediately (the internal record is referencing a deactivated NPI, which is a directory-accuracy event independent of any new match).

- **Fix:** Add to the routing pseudocode (Step 5) explicit handling of the existing-NPI conflict case:

  ```
  IF internal_record.has_existing_npi:
      existing_npi_candidate = find_candidate_by_npi(scored_candidates,
                                                       internal_record.existing_npi)
      IF existing_npi_candidate is None:
          // existing NPI not found in search; surface as an
          // "existing NPI not in registry" event (deactivated,
          // typo, or invalid).
          emit_event("existing_npi_not_resolved", internal_record)
          queue_for_review(internal_record, scored_candidates,
                            "existing_npi_not_resolved")
          RETURN "review"

      IF existing_npi_candidate is the top-scoring candidate:
          // existing NPI confirmed; auto-attach is appropriate
          // if scores meet thresholds.
          ...
      ELSE:
          // existing NPI is a candidate but not the top one.
          IF top_candidate.score - existing_npi_candidate.score >= MIN_MARGIN:
              // search disagrees materially with the existing NPI.
              emit_event("existing_npi_disputed", internal_record,
                          existing = existing_npi_candidate,
                          top = top_candidate)
              queue_for_review(internal_record, scored_candidates,
                                "existing_npi_disputed")
              RETURN "review"
          ELSE:
              // search produces a slightly higher candidate but
              // not by a meaningful margin; preserve the existing
              // NPI to avoid churn.
              auto_attach(existing_npi_candidate)
              RETURN "auto_attach"
  ```

  Add to the architecture pattern a paragraph specifying the existing-NPI-conflict surface and the disputed-existing-NPI review track.

### Finding A7: Idempotency and DLQ Coverage on Lambda Paths (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, resilience)
- **Location:** "Why This Isn't Production-Ready" idempotency paragraph: *"the matching pipeline must handle duplicate-event delivery without producing duplicate attachments or scheduling duplicate verifications. Use the `internal_provider_id` as the idempotency key for normalize-and-route; use the `attachment_id` as the idempotency key for attach-NPI; use `(internal_provider_id, verification_due_date)` as the idempotency key for schedule-re-verification."*
- **Problem:** Same chapter-wide pattern as Recipe 4.4-5.1. The recipe acknowledges the gap and names the keys but does not architect the DLQ coverage on the Lambda paths or the Step Functions Catch-with-route-to-DLQ pattern. For Recipe 5.2 specifically, the `attach_npi` idempotency on `attachment_id` is the most consequential because a duplicate `attach_npi` invocation would re-emit the assignment event, potentially producing duplicate downstream actions in the credentialing system, the directory, and the claims-validation pipeline.
- **Fix:** Same as 5.1 Finding A9. Inline DLQ coverage on all Lambda paths in the architecture diagram, idempotency keys on all writes (with a `attachment_id` ConditionExpression on the attach-NPI Put preventing duplicate writes), and a Step Functions Catch that distinguishes retryable infrastructure failures from terminal logic failures.

### Finding A8: Real-Time Onboarding Latency Budget and OpenSearch Failover (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (availability, real-time-workflow integration)
- **Location:** "Why This Isn't Production-Ready" entry on real-time matching latency: *"Credentialing-team onboarding workflows expect a sub-second response to 'what's the NPI for this provider' ... Architect for sub-second response with fallback paths: candidate-set capping, asynchronous follow-up scoring for borderline cases, and an 'in progress' status the credentialing UI can display while the matching completes."*
- **Problem:** Same chapter-wide pattern as Recipe 5.1 Finding A5. The recipe diagnoses the latency budget but does not architect the response. OpenSearch availability is a single point of failure for real-time onboarding; the candidate-generator Lambda has no specified fallback when OpenSearch is unavailable.
- **Fix:** Same as 5.1 Finding A5. Specify the candidate-set capping, the asynchronous-follow-up scoring path via SQS for borderline cases, and the OpenSearch failover (fall back to the bulk parquet file via Athena query, or fall back to "queued for matching" with a CloudWatch alarm on chronic OpenSearch availability issues). For Recipe 5.2 specifically, the NPI Registry API is the natural fallback substrate (the recipe correctly identifies the API as the path for real-time individual lookups), so the architecture should specify the OpenSearch-then-API failover order.

### Finding A9: Cross-Recipe Orchestration with Patient Matching (5.1) Is Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (cross-recipe integration)
- **Location:** "Why This Isn't Production-Ready" cross-recipe paragraph: *"The same DynamoDB instance and the same Glue catalog can host both the patient-matching and provider-matching artifacts. Where it makes sense, share the matching-primitives library (blocking passes, comparators, Fellegi-Sunter combiner) as a versioned Lambda layer or Glue Python library so improvements to the comparators benefit both recipes."*
- **Problem:** The recipe correctly names the shared-primitives opportunity but does not architect the library boundary, the version-coupling contract, or the cross-recipe operational pattern (review-queue-team-allocation across patient and provider matching, audit-archive shared-substrate consumption). Same chapter pattern as 5.1 Finding A8.
- **Fix:** Add a brief subsection naming the matching-primitives library boundary (versioned Lambda layer or Glue Python library), the version-coupling contract (each recipe pins a specific library version), and the audit-archive shared-substrate cross-recipe consumption pattern.

### Finding A10: Athena Access Control on Audit Archive Underspecified (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (privacy, access control)
- **Location:** AWS Implementation paragraphs naming Athena over the Glue-cataloged data and QuickSight on Athena.
- **Problem:** Same chapter-wide pattern as Recipe 5.1 Finding A10. QuickSight has named row-level security; Athena does not. A direct Athena query against the audit archive can read every PHI-adjacent row regardless of cohort or access role.
- **Fix:** Add Lake Formation to the architecture diagram and specify the column-level and row-level access controls for the audit archive's Glue-cataloged tables.

### Finding A11: M/U Probability Re-Estimation Cadence and Validation Gating Are Underspecified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (model lifecycle)
- **Location:** "Why This Isn't Production-Ready" threshold-tuning paragraph naming "Re-tune at least annually and after any major data-quality change."
- **Problem:** Same chapter pattern as 5.1 Finding A4. The recipe names the discipline but does not architect the re-estimation pipeline, validation gating, or version-event emission. Severity is LOW here rather than MEDIUM (as in 5.1) because the provider-matching workload's lower volume and higher data-quality reduce the M/U drift cadence; quarterly is a reasonable default with annual being acceptable for many deployments. The recipe text correctly identifies this.
- **Fix:** Same as 5.1 Finding A4. Add the M/U re-estimation pipeline to the architecture diagram and the version-event semantics to the validation-gating workflow.

### Finding A12: Drift-Event Downstream Consumption Workflows Are Named in Production-Gaps but Not Architected

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" drift-event-downstream-consumption paragraph: *"Emitting a `practice_address_changed` event is the easy part. The hard part is what happens next: who consumes the event, who updates the directory, who notifies members of an in-network provider whose location has moved, who reconciles the cred-file address with the registry address, who decides whether the address change constitutes a re-credentialing event versus a routine update."*
- **Problem:** The recipe correctly names the downstream-workflow gap. The architecture diagram shows the EventBridge fan-out to credentialing, network management, claims, and network-adequacy reporting, but does not specify what each consumer does with each drift event type. This is largely organization-specific (the recipe acknowledges this) but the architecture should specify the consumer-side contract: each consumer subscribes to a specific event detail-type, processes the event idempotently, and acknowledges or rejects with a documented response semantics.
- **Fix:** Add a brief paragraph to the architecture pattern naming the consumer-side contract: each EventBridge event has a `detail_type` (`npi_attached`, `npi_deactivated`, `practice_address_changed`, `taxonomy_changed`, `type2_affiliation_added`, `type2_affiliation_removed`, `provider_sanctioned`); each consumer subscribes to the relevant detail-types via an EventBridge rule with a target Lambda or SQS queue; consumer-side processing is idempotent at the event_id; consumer-side errors route to a per-consumer DLQ.

### Finding A13: Backfill of Existing Provider Directory Is Mentioned but Not Architected (Chapter Pattern)

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" backfill paragraph: *"When the matcher launches, the existing directory has thousands of provider records, some with NPIs already attached, some without, some with NPIs that are wrong."*
- **Problem:** Same chapter pattern as 5.1 Finding A6. The provider-matching backfill is structurally smaller than the patient-matching backfill (thousands of records, not millions) and the recipe correctly notes "the cleanup will take weeks to months." The throttling and review-capacity coordination still apply.
- **Fix:** Same pattern as 5.1 Finding A6. Add throttling and review-queue-saturation handling to the backfill specification.

---

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** The Prerequisites VPC row names production discipline: Lambdas in VPC; Glue jobs in VPC connections; OpenSearch in VPC; VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, STS. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization with outbound proxy.** The "NAT Gateway only for external services without VPC endpoints" framing with "restrict egress with an outbound HTTPS proxy and an allow-list of destination domains" is the chapter's correct egress-discipline statement, and the recipe correctly includes the NPPES download endpoint and the NPI Registry API as the named external dependencies.
- **NPPES public-data classification correctly handled.** The "CMS does not require BAA for this data because the NPI registry is public information, but route the egress through your standard outbound proxy so the connection is logged and auditable" framing is the right balance: the data is public, but the request itself is institution-attributable and should be auditable.
- **TLS framing throughout.** Encryption-in-transit named for OpenSearch, the API surface, EventBridge.
- **OpenSearch in VPC with fine-grained access control.** The HIPAA-eligible posture for OpenSearch is correctly framed.

### Finding N1: API Gateway Resource Policy and WAF Posture for the Review-Queue API Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram includes `AG1[API Gateway, review API] -> CG1[Cognito / IdP] -> UI1[Credentialing Review UI, S3-hosted SPA] -> AG1 -> L8[Lambda, review-decision]`.
- **Problem:** Same as Recipe 5.1 Finding N1. The review-queue API's resource-policy posture (private API only, IP allowlist, mTLS, integration with AWS WAF) is not specified.
- **Fix:** Same as 5.1. Specify private API Gateway with VPC endpoint resource policy restricting access to the institutional VPC, WAF rules for SQL injection / command injection / rate limiting, optional mTLS where SSO supports it, and CloudFront-with-WAF for the S3-hosted SPA if it is publicly addressable.

### Finding N2: NPI Registry API Egress Posture Could Be Sharpened

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row naming "the NPI Registry API, the NPPES download endpoint" with "route the egress through your standard outbound proxy so the connection is logged and auditable."
- **Problem:** The egress posture is correctly outlined but could be sharpened with specifics: the NPI Registry API endpoint (`npiregistry.cms.hhs.gov`) is the only domain that should be in the allow-list for the real-time-onboarding Lambda; the NPPES download endpoint (`download.cms.gov` per the recipe's TODO) is the only domain that should be in the allow-list for the monthly-batch-refresh Glue job. The two egress paths should be distinct security groups with non-overlapping allow-lists, so a compromise of the real-time Lambda cannot exfiltrate via the bulk-download path. The NPI Registry API has documented rate limits (the recipe TODO notes this); the egress proxy should enforce a per-Lambda-role rate limit so a runaway Lambda does not get the institution's egress IP rate-limited at the CMS edge.
- **Fix:** Add to the VPC row: *"The NPI Registry API egress (`npiregistry.cms.hhs.gov`) and the NPPES bulk-download egress (`download.cms.gov`) are configured as distinct outbound proxy rules with non-overlapping allow-lists scoped to the relevant compute roles: the real-time-onboarding Lambda's role allows only `npiregistry.cms.hhs.gov`; the monthly-batch-refresh Glue job's role allows only `download.cms.gov`. The proxy enforces a per-role rate limit on the NPI Registry API requests below the CMS edge's rate limit. Egress connections are CloudWatch-logged for chargeback and auditability."*

### Finding N3: USPS / Address-Standardization Vendor Egress Posture Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** The normalization step references USPS-standardize but the egress posture for the underlying CASS-certified address-standardization service is not specified.
- **Problem:** Same as Recipe 5.1 Finding N2. USPS Address Validation API, SmartyStreets, Melissa, and similar vendors are the canonical CASS-certified services; each requires outbound HTTPS to a vendor-specific domain. The vendor's BAA coverage and PHI-handling posture is not addressed; provider mailing addresses (often residential) are PHI-adjacent and should not flow to a vendor without a BAA in place.
- **Fix:** Same as 5.1. Specify the outbound-proxy with allow-listed destination domains, BAA coverage for each vendor (annually reviewed), and CloudWatch Logs capture of every outbound connection.

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by counting U+2014 byte sequences (0xE2 0x80 0x94) in the UTF-8 file.
- **En dash count: 0.** Verified by counting U+2013 byte sequences (0xE2 0x80 0x93) in the UTF-8 file.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services; AWS appears first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory for the closing observations.
- **CC voice consistent.** The opening "Open the provider directory of any health plan in the country and look up a primary care doctor in your area" hook lands in the engineer-explaining-something-cool register exactly. The "Forty minutes calling listed providers. Half of them are wrong" pacing is the chapter pattern at its most operationally pointed. Self-deprecating expertise: "the work is not in the matching algorithm; the work is in handling the dozen reliable edge cases that come up at scale and in keeping the matches fresh as both sides change" is the right register for the recipe's Simple-tier framing.
- **The Sarah J Patel running example is consistent.** Carried from the Problem section ("Sarah J Patel, MD, Family Medicine, 1421 Elm Street, Anytown, ST 12345") into the Expected Results sample candidate-pair JSON ("first_name": "sarah", "last_name": "patel") with the right provider-style demographic detail.
- **Clinical accuracy is high.** The Type 1 / Type 2 NPI distinction is correctly stated; the NPPES self-attestation framing is accurate; the No Surprises Act / CMS / NCQA / state-level regulatory framing is correct (with appropriate TODO flags); the LEIE reference in production-gaps is correct in spirit and citation; the NUCC taxonomy reference is correct; the Splink-on-Spark framing is the same library used in 5.1 with appropriate cross-recipe linkage.
- **The Honest Take is the recipe's most operationally pointed section.** The five traps (organizational duplication, drift-detection under-investment, per-segment cadence, deactivation centrality, equity, front-door capture, regulatory framing) are the chapter's strongest individual list of failure modes for this domain. The closing "build it as compliance infrastructure, with the audit trail, retention discipline, and access control that comes with that designation" is the right line.
- **The Variations and Extensions section is well-scoped.** Eleven variations (LEIE, state board, Death Master File, FHIR Practitioner / PractitionerRole, multi-source taxonomy, active-learning gold set, per-cohort m/u models, credentialing-system bidirectional sync, provider self-service portal, network-adequacy reporting). Each is framed at the right grain and points readers to natural follow-on work.

### Finding V1: A Few Headers in the AWS Implementation Section Slip Toward Documentation Voice

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in "Why These Services" read as service-name-as-bullet-header rather than the engineer-explaining register. Examples:
  - *"AWS Step Functions plus a simple web app (API Gateway + Lambda + a static S3-hosted SPA) for the review queue UI."*
  - *"AWS KMS, CloudTrail, CloudWatch."*
- **Problem:** Same as Recipe 5.1 Finding V1. The headers are functionally correct as scannable structure for a long technical section; the deeper paragraph framing returns to the right register.
- **Fix:** Optional. The chapter editor's call.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in The Technology section's Type-1-vs-Type-2 subsection and the Honest Take's regulatory-framing paragraph stretch to 50+ words.
- **Problem:** Most sentences are well-paced; a few in the regulatory-framing paragraph could be split. Same observation as Recipe 5.1 Finding V2.
- **Fix:** Optional.

### Finding V3: The "Build It as Compliance Infrastructure" Closing Is the Chapter's Strongest Single Line on This Domain

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** Honest Take's closing paragraph: *"The matcher is not an optional operational improvement. It is the substrate that makes compliance possible. Build it as compliance infrastructure, with the audit trail, retention discipline, and access control that comes with that designation. The cost of building it well is small relative to the cost of explaining to regulators why the directory was wrong for six months in a row."*
- **Note:** This framing earns its position. The chapter editor should consider whether a similar "build it as X infrastructure" framing applies to the chapter preface for all Chapter 5 recipes; for 5.2 specifically, this is the right closing.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1 and chapter-pattern):** Security flags `attach_npi`, `re_verify_npi`, the real-time-onboarding path, and the review-queue API as needing explicit identity-boundary specification at HIGH severity. Architecture concurs because the assignment-as-anchor consequence (a misrouted attach_npi corrupts the canonical assignment that downstream credentialing, claims, directory, and network-adequacy systems depend on) compounds the security concern with a methodological one. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The chapter editor should consolidate to a chapter preface in the next pass, since the same finding now applies across 4.4-5.2.**

**Attach-NPI atomicity (A1):** Architecture flags the sequential PutItem pattern as needing `TransactWriteItems` plus an outbox pattern for the side effects, at HIGH severity. Security concurs because half-applied attachments produce audit-trail inconsistency (attach happened, no audit record) that breaks the "build it as compliance infrastructure" claim. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence. Sharper for 5.2 than 5.1 because the network-adequacy reporting depends on the verified-within-90-days metric being demonstrable from the assignment table.**

**Cohort fairness instrumentation (A2 and chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security concurs on the privacy framing of cohort dimensions in CloudWatch (Finding S5). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The recipe explicitly inherits the rigor from 5.1 ("the monitoring patterns from recipe 5.1 carry over directly") which earns the recipe's right to specify the threshold operationally.**

**Schedule-table stale-entry bug (A3):** Architecture flags this as a HIGH-severity correctness gap that produces operational and cost consequences at scale. Security is silent (this is a correctness bug, not a security one). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The fix is straightforward (single-row-per-provider schema or upsert pattern with delete) and the consequence is concrete (daily verification job re-processes providers at the rate of stale-entry accumulation).**

**LEIE / sanction-list integration (S3):** Security flags as MEDIUM. Architecture concurs that the federal-payer compliance regime makes this more than a variation. **Resolution: MEDIUM, attributed to Security with Architecture concurrence. Promote LEIE from Variations and Extensions to the main architecture.**

**Audit-log retention floor (S2 and chapter-pattern):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Provider data sensitivity framing (S4):** Security flags as LOW with a specific technical concern about residential mailing addresses and state-board-private license numbers. **Resolution: LOW, attributed to Security.**

**Per-segment cadence configuration (A4):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Type 2 NPI persistence (A5):** Architecture flags as MEDIUM. The recipe correctly diagnoses Type 2 as many-to-many but the persistence model conflates the two. **Resolution: MEDIUM, attributed to Architecture.**

**Existing-NPI conflict resolution (A6):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Idempotency and DLQ coverage (A7 and chapter-pattern):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Real-time onboarding latency budget and OpenSearch failover (A8 and chapter-pattern):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration with patient matching (A9):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Athena access control (A10 and chapter-pattern):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**M/U re-estimation cadence and validation gating (A11 and chapter-pattern):** Architecture flags as LOW. The lower-volume and higher-data-quality of provider matching reduces the urgency relative to 5.1. **Resolution: LOW, attributed to Architecture.**

**Drift-event downstream-consumer contract (A12):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Backfill of existing provider directory (A13 and chapter-pattern):** Architecture flags as LOW. The provider-matching backfill is structurally smaller than the patient-matching backfill. **Resolution: LOW, attributed to Architecture.**

**Cohort PHI in CloudWatch dimensions (S5 and chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S6 and chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Provider self-service portal disclosure policy (S7):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Networking findings (N1, N2, N3):** All LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2):** Both LOW. V3 is a positive observation. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 0 critical, 4 high, 9 medium, 7 low. The 4 HIGH count exceeds the > 3 = FAIL threshold; the verdict is FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Four HIGH findings (more than 3 = FAIL per the persona rules). All four are correctness-and-compliance gaps with localized fixes; three surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose, and one (the schedule-table stale-entries issue) is a pseudocode-level bug that the architecture should specify the upsert pattern for. None require structural rework of the recipe; the underlying methodology, voice, clinical accuracy, and architectural shape are excellent.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | Real-time onboarding API, daily re-verification path, attach-NPI, and review-queue API lack identity-boundary specification |
| 2 | HIGH | Architecture | Attach-NPI operation is not atomic; sequential PutItem calls leave half-updated state on partial failure |
| 3 | HIGH | Architecture | Cohort-stratified accuracy thresholds and metric definitions referenced as "required here too" but undefined |
| 4 | HIGH | Architecture | Re-verification path writes new schedule entries without removing stale ones; daily job will repeatedly process same provider |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 5 | MEDIUM | Security | Audit-log retention specified as "per institution's records-retention policy" without architectural floor (chapter pattern) |
| 6 | MEDIUM | Security | LEIE / sanction-list cross-check treated as a variation rather than a required production control |
| 7 | MEDIUM | Architecture | Per-segment re-verification cadence configuration named in the Honest Take but not architected |
| 8 | MEDIUM | Architecture | Type 2 NPI affiliations diagnosed but persistence model underspecified |
| 9 | MEDIUM | Architecture | Internal record's pre-existing NPI conflict resolution underspecified |
| 10 | MEDIUM | Architecture | Idempotency and DLQ coverage on Lambda paths (chapter-wide pattern, already TODO'd) |
| 11 | MEDIUM | Architecture | Real-time onboarding latency budget and OpenSearch failover (chapter-wide pattern) |
| 12 | MEDIUM | Architecture | Cross-recipe orchestration with patient matching (5.1) mentioned but not architected |
| 13 | MEDIUM | Architecture | Athena access control on audit archive underspecified (chapter-wide pattern) |

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 14 | LOW | Security | Provider data "lower-sensitivity" framing risks under-investing in controls around mailing address and license number |
| 15 | LOW | Security | Cohort PHI in CloudWatch metric dimensions (chapter-wide pattern) |
| 16 | LOW | Security | IAM "Never `*` actions or `*` resources in production" stated without scoped ARN examples (chapter-wide pattern) |
| 17 | LOW | Security | Provider self-service portal disclosure policy not addressed |
| 18 | LOW | Architecture | M/U probability re-estimation cadence and validation gating underspecified (chapter pattern) |
| 19 | LOW | Architecture | Drift-event downstream consumption workflows named in production-gaps but not architected |
| 20 | LOW | Architecture | Backfill of existing provider directory mentioned but not architected (chapter pattern) |
| 21 | LOW | Networking | API Gateway resource policy and WAF posture for the review-queue API not specified (chapter pattern) |
| 22 | LOW | Networking | NPI Registry API egress posture could be sharpened |
| 23 | LOW | Networking | USPS / address-standardization vendor egress posture not specified (chapter pattern) |
| 24 | LOW | Voice | A few headers in the AWS Implementation section slip toward documentation voice |
| 25 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 4 HIGH findings before publication.** Each has a localized fix:
   - Finding S1 (identity-boundary): pseudocode additions in the real-time-onboarding path, `attach_npi`, `re_verify_npi`, and the review-queue authorization context. Reference language is partially present in the chapter pattern from 4.4-5.1. Estimated effort: half a day.
   - Finding A1 (attach-NPI atomicity): pseudocode rewrite of Step 6 to use `TransactWriteItems` for the assignment+schedule writes plus an outbox pattern for the audit and event side effects. The architecture prose addition specifies the partial-failure recovery semantics. Estimated effort: half a day.
   - Finding A2 (cohort fairness threshold): threshold-and-metric specification in pseudocode and architecture-prose paragraph. Reference language is present in the cohort-stratified accuracy paragraph and inherited from 5.1. Estimated effort: half a day.
   - Finding A3 (schedule-table stale entries): pseudocode update to use a single-row-per-provider schedule schema (preferred) or an upsert-with-delete pattern in `attach_npi` and `re_verify_npi`. Estimated effort: half a day.

   Total: 2 days of writing time.

2. **Address the recipe-specific MEDIUM findings (S3 LEIE promotion, A4 per-segment cadence, A5 Type 2 persistence, A6 existing-NPI conflict).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1-2 days of writing time.

3. **Address the chapter-wide MEDIUM findings (S2 audit retention, A7 idempotency, A8 latency, A9 cross-recipe, A10 Athena).** These are already TODO'd or chapter-pattern; consolidating into a chapter preface in the next pass is acceptable.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N1, N2, N3) are explicit-statement additions; the chapter-pattern findings (S5, S6, S7, A11, A12, A13) are consolidation work.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 5.2 is the second Simple-tier recipe in Chapter 5 and the recipe text says it is "the second recipe in Chapter 5 because it shares almost all of its infrastructure with Recipe 5.1." The quality bar inherits from 5.1 and the recipe's own claim that "this is the easiest entity-resolution problem in healthcare" earns the architectural specification needing to be at the level the recipe text claims.

The recipe's underlying methodology, voice, clinical accuracy, and architectural shape are excellent. The opening provider-directory vignette, the Type 1 / Type 2 explanation, the drift-snapshot pattern, the deactivation-flag-as-highest-priority-event framing, the per-segment-cadence trap, and the "build it as compliance infrastructure" closing are all chapter-strength contributions. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses (Findings S1, A1, A2) plus one pseudocode-level correctness bug that needs an architectural fix (Finding A3). Closing the gaps brings the architecture up to the standard the recipe text claims and makes the registry-anchored matcher that the rest of the chapter's downstream consumers depend on as solid as the recipe text promises it is.
