# Expert Review: Recipe 5.3 - Address Standardization and Household Linkage

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-22
**Recipe file:** `chapter05.03-address-standardization-household-linkage.md`

---

## Overall Assessment

This is the third Simple-tier recipe in Chapter 5 and the one that introduces the recipe-specific concepts that justify a separate chapter from the patient (5.1) and provider (5.2) matchers: USPS-conformant address standardization through CASS-certified vendor APIs, the six-status classification of standardization outcomes (`VALIDATED`, `CORRECTED`, `MISSING_SECONDARY`, `AMBIGUOUS`, `NOT_VALIDATED`, `INVALID`), the building-type-aware household-inference layer, the graded household-confidence contract (`HOUSEHOLD_HIGH`, `HOUSEHOLD_MEDIUM`, `CO_LOCATED`, `SUPPRESSED`), and the NCOA-driven mover-detection and drift-event fan-out. The opening "every patient address you have ever pulled up" enumeration earns its position: the seven concrete address-pathology examples ("1421 Elm St Apt 3B," the same address typed differently, the apartment number missing because the patient mumbled it, the property description "the trailer behind the QuickStop on Route 9," the homeless-or-shelter case, the wrong address because the patient moved three years ago) set up the follow-on operational vignettes (the population-health mailing campaign with twenty-percent failure baseline, the SDOH-derived value-based-care metric breaking on un-geocodable addresses, the financial-assistance program needing household linkage, the HIE missing match signal on un-standardized addresses) at exactly the right level of "this is what the patient address field actually looks like in production" energy.

The Technology section is the chapter's clearest articulation of "why addresses are harder than they look": USPS publishes the rules (Publication 28 as the foundational document), maintains the reference data (DPV, ZIP+4), and runs a certification program (CASS) for software that processes addresses. The "Two questions about each address: is this real, and what is the standardized form" framing introduces DPV correctly, the structured-anatomy subsection lays out the post-standardization schema with the right level of granularity (delivery_line_1, delivery_line_2, last_line, components, metadata, provenance), and the "Where Standardization Hits Its Limits" subsection enumerates the failure modes (rural addresses, military APO/FPO/DPO, international, newly built, unstable housing, non-residential mailing, in-care-of, PO Box) with operationally-honest framing.

The household-linkage subsection is the recipe's most operationally pointed teaching content. The four-problem framing ("same address" is necessary but not sufficient; "different addresses" does not always mean different households; household membership is sometimes private and not derivable from data the institution has permission to use; granularity depends on data capture) is correct. The graded-confidence contract (`HOUSEHOLD_HIGH` with corroborating evidence; `HOUSEHOLD_MEDIUM` with some corroborating evidence; `CO_LOCATED` for same-address-no-other-evidence; `SUPPRESSED` for privacy-flagged records; with a fourth "possible household at different addresses" track for outreach-only workflows) is the recipe's strongest single architectural primitive and is correctly framed as the discipline that prevents downstream consumers from treating co-location as household. The privacy-suppression-as-first-class-case framing ("the privacy contract is part of the architecture, not a downstream filter; suppressing late is much harder to get right than suppressing early") is the right closing line for the household subsection.

The six-stage architecture (ingest, standardize, geocode, persist, infer household, refresh and drift) is the right shape for the problem. The "standardization is an external service" framing with the idempotency-on-input-hash discipline is correct. The geocoding-co-located-but-separable framing handles the cost-and-workflow split honestly. The household-inference-downstream-of-standardization sequencing is correct (the matcher cannot run on un-standardized addresses without producing the same-physical-address-different-format failure mode). The privacy-suppression-as-first-class-case framing is repeated correctly in the architecture pattern. The refresh-on-regulatory-cadence framing names the monthly USPS reference data and quarterly NCOA cadences with the right operational specificity.

The Honest Take is the recipe's most operationally pointed section. Five observations stand out and earn the recipe's voice: (1) "treating it as a one-time data-cleanup project rather than as ongoing operational infrastructure" with the canonical decay pattern (six months later, the address quality is back to where it was) and the "treat it as infrastructure from the start, with the operational ownership, monitoring, and budget that implies" prescription; (2) "under-investing in the registration-time correction-confirmation UX" with the silent-correction failure mode and the "build the registration-time UX into the project plan; it is not a frill" prescription; (3) "confusing co-location with relationship" framed as the discipline that prevents the "build a household graph and let downstream consumers figure it out" failure mode, with the "the graded contract is non-negotiable" closing; (4) the equity dimension correctly framed ("address-data-quality disparities are real and consequential"), with the multi-unit / cultural-naming / unstable-housing cohort enumeration and the "equity in address quality is equity in access" closing; (5) the NCOA-as-underused-tool observation with the quarterly-at-minimum baseline. The closing on HIPAA Safe Harbor and the standardized-address-as-sensitive-identifier framing is the right closing line.

That said, four correctness-and-compliance gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items. (1) The architecture invokes a real-time standardization API path (registration-time), a quarterly NCOA submission flow, a monthly USPS refresh, and a household-re-inference flow that mutates the assignment and household tables consumed by outreach, SDOH analytics, the patient portal, the patient matcher, and financial-assistance workflows; the identity-boundary checks on these paths are not specified at the architectural level. The recipe inherits the chapter-wide identity-boundary pattern from 4.4-4.10 / 5.1 / 5.2; the consequence here is concrete: a misrouted standardize-and-persist call (an attacker-controlled `original_input`, a forged ingest event from a compromised registration source, a bypassed privacy-suppression flag) silently links the wrong patient to the wrong address-and-household, with downstream impact on every consumer of the address store. (2) The `persist_standardized_record` and `infer_household_for_address` operations perform multiple sequential DynamoDB writes plus EventBridge emits and S3 archive writes without `TransactWriteItems` wrapping or an outbox pattern; failures between the writes leave the address-and-household state in a half-applied state. The pseudocode includes a "TODO (TechWriter): Wrap the DynamoDB write, the S3 archive write, and the EventBridge emit in a transactional pattern" comment that names the gap but does not architect the fix. Same chapter pattern as 5.1 Finding A1 / 5.2 Finding A1; the regulatory consequence here is sharper because the address store feeds outreach (mailing-list scrubbing breaks if the address persisted but the household-inference event was not emitted) and the financial-assistance workflow (eligibility re-determination reads the household membership). (3) The cohort-stratified accuracy monitoring is invoked as "required here too" with explicit per-cohort enumeration (urban multi-unit, rural, naming-convention-defined, unstable-housing) but the operational threshold values, per-axis aggregation, and disparity-metric definitions are not specified. Same chapter pattern as 5.1 Finding A2 / 5.2 Finding A2; the cohort-distribution stakes are higher here because address-data-quality disparities directly translate to SDOH metric disparities, outreach reach disparities, and financial-assistance access disparities. (4) The `monthly_usps_refresh` pseudocode iterates the entire `patient-address` population with a `DynamoDB.Scan` (the comment "For large populations, this is a Glue/Spark job over S3-archived snapshots rather than a DynamoDB scan" acknowledges the gap), re-standardizes every record on every cycle, and re-runs household inference for every drift detected. At a 500K-patient health system with monthly cadence, this produces ~6M vendor-API calls per year purely for refresh (plus the new-patient and registration-update calls). The recipe's cost estimate ($2,800-11,500/month) does not square with this throughput at the higher per-record vendor pricing tier. The architecture should specify the change-driven-refresh pattern (only re-standardize records where the input changed, the cache TTL expired, or the USPS reference data flagged the canonical-hash-prefix range as updated) rather than the full-population-monthly pattern.

Eleven chapter-wide patterns repeat (audit-log retention floor, IAM ARN scoping, identity-boundary checks, governance SLA on M/U-equivalent re-estimation of household-inference thresholds, idempotency and DLQ coverage, cross-recipe orchestration with 5.1 / 5.2 / 5.4-5.8, cohort PHI in CloudWatch dimensions, vendor BAA execution discipline for the CASS vendor and the NCOA vendor, real-time standardization API latency budget, API Gateway resource policy and WAF posture, Athena access control on the audit archive). Several are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by counting U+2014 codepoints in the UTF-8 file). En dash count: 0 (verified by counting U+2013 codepoints in the UTF-8 file). 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: the opening "you will find one of these" enumeration, the running examples (the Patel family at 1421 Elm Street Apt 3B carried into the Expected Results JSON, the move scenario carried into the drift event), the "this is what duplicate patient records do" register from 5.1 carried into the address pathology enumeration, the "build it as compliance infrastructure" register from 5.2 carried into the "treat it as infrastructure from the start" closing. Parenthetical asides land well. The 500K-patient deployment scenario with the 10K-new-addresses-per-month cadence is operationally specific. The Variations and Extensions section (international, privacy-preserving cross-organization household linkage, SDOH-indicator integration, address-based fraud detection cross-reference, USPS Informed Delivery, address-based household-fairness auditing, active-learning-driven correction tuning, reverse-geocoding for unaddressed locations, address-confidence-aware patient matching, patient-portal address self-service, multi-source address reconciliation) is well-scoped and frames each extension at the right grain.

Priority breakdown: 0 critical, 4 high, 11 medium, 8 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are localized correctness-and-compliance gaps; three surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose, and one (the monthly-refresh-over-full-population pattern) is a cost-and-throughput pattern the architecture should specify at the right granularity. None require structural rework of the recipe; the underlying methodology, voice, clinical accuracy, and architectural shape are excellent.

---

## Stage 1: Independent Expert Reviews


## Security Expert Review

### What's Done Well

- BAA called out explicitly with the appropriate framing that the CASS-certified vendor "must be willing to sign a BAA, since you will be sending PHI (the address combined with patient identifier) to their API." The recipe correctly elevates vendor BAA execution from a feature comparison to a privacy-and-security review: *"the vendor selection is consequential because the vendor sees PHI; treat the procurement as a privacy and security review, not just a feature comparison."*
- The PHI framing on standardized addresses is honest and specific. The Honest Take's closing paragraph names the HIPAA Safe Harbor identifier list explicitly: *"HIPAA's de-identification standards (Safe Harbor and Expert Determination) treat addresses above the state-or-three-digit-ZIP level as identifiers that must be removed for de-identified datasets ... Treat the standardized address store with the same encryption and access-control posture as the rest of the patient demographics. Apply Lake Formation column-level controls or equivalent for analytics consumers who do not need the full address."* This is the right framing.
- Customer-managed KMS keys for the S3 buckets, the DynamoDB tables, and the Lambda log groups. Encryption-in-transit named explicitly: *"TLS 1.2 or higher for all in-transit traffic, including the vendor-API call."*
- AWS Secrets Manager called out explicitly for vendor API key storage, with the right framing: *"Vendor credentials are sensitive and should not appear in code or in environment variables. Secrets Manager stores them with KMS encryption at rest, IAM-controlled access, and rotation support where the vendor supports rotation."*
- CloudTrail data events on the patient-address and household-membership tables and on the audit S3 buckets, with the API Gateway and Lambda invocation logging.
- The "Per-Lambda least-privilege" framing in the Prerequisites IAM Permissions row, with the explicit "Never use `*` actions or `*` resources in production" admonition.
- Synthetic data labeling enforced in the Sample Data row: *"Never use real patient addresses in development environments."*
- Privacy-suppression-as-first-class-case discipline. The recipe correctly elevates the privacy contract to "first-class" in the architecture pattern: *"Some patient records have a 'do not link to household' flag (set explicitly via patient request, set automatically when domain-specific signals indicate domestic violence or other safety concerns, set when the address is a confidential address kept for the patient's safety). The household inference pipeline checks for this flag on every record before grouping."* The two-policy framing (suppress entire group when any record is suppressed, vs exclude suppressed records) is the right pattern for a domain where the right answer is institution-specific.
- Address Confidentiality Program awareness. The recipe correctly names that domestic-violence-survivor patients and other safety-sensitive populations require special handling, with the architectural primitive (the privacy-suppression flag) named at the right place in the pipeline.

### Finding S1: Real-Time Standardization API, Persist-Standardized-Record, Infer-Household, NCOA-Result-Processing, and Drift-Event Paths Lack Identity-Boundary Specification

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization, regulatory)
- **Location:** Architecture diagram shows the real-time standardization flow `Registration -> L1 (standardize-on-update) -> SM1 (Secrets Manager) -> V1 (CASS Vendor API) -> S2 (address-curated) -> D1 (patient-address)`; the household-inference flow `S2 -> GL2 (household-inference) -> S3 -> D2 (household-membership)`; the NCOA-result-processing flow `SF2 (Step Functions quarterly NCOA) -> V2 (NCOA Vendor) -> L4 (drift-detector) -> EB1 (drift event bus)`; the real-time API surface `AG1 (API Gateway) -> CG1 (Cognito) -> L3 (api-handler) -> D1 / D2 / L1`. Step 3 pseudocode `persist_standardized_record(patient_id, raw, standardized)`, Step 4 `infer_household_for_address(canonical_hash)`, and the NCOA `update_address_with_ncoa_match(patient_id, new_address, move_date, ncoa_match_type)` operation.
- **Problem:** The recipe specifies the standardization-and-household pipeline at flow-and-service granularity but is silent on the identity-boundary policy that controls who can invoke each path and what proves the caller is authorized to act on a particular patient record. Same chapter pattern as 5.1 / 5.2; the consequence here is concrete with five attack surfaces:

  1. **The real-time standardization API's authentication context is named (Cognito) but the authorization context is not.** Cognito authenticates the registration system or the patient portal as a service principal; Cognito alone does not enforce that the caller can only invoke standardization for patient records the caller is authorized to act on. A registration clerk at one facility should not be able to standardize-and-persist an address change for a patient at a different facility. A patient-portal session for `patient-internal-00874` should not be able to mutate the address for `patient-internal-00875`. The architecture should specify the authorization layer enforced on top of Cognito: API Gateway authorizer that validates the caller's role and the patient_id-in-scope binding; Lambda-side validation that the authenticated caller is authorized for the patient_id in the request body; rejection with a logged metric on mismatch.

  2. **The ingest event for new patient registration is unauthenticated at the architectural level.** The `ingest_address_record(source_event)` pseudocode reads `source_event.patient_id`, `source_event.address_role`, and the address fields directly. A forged source event (an attacker-controlled `original_input`, a compromised registration source replaying old events, an event with the right `patient_id` but attacker-controlled address fields) silently overwrites the patient's address with the wrong one. The producer-signed envelope pattern (the chapter pattern from 4.4-5.2: `source_system`, `source_record_id`, `event_id`, `signed_payload` with the consumer-side signature validation) is not specified here.

  3. **`persist_standardized_record` is the recipe's most security-sensitive write path.** It mutates `patient-address`, which is the anchor for outreach (mailing-list scrubbing reads from it), SDOH analytics (geocoding pipeline reads from it), the financial-assistance workflow (household-membership lookup reads from it), the patient matcher (5.1 reads address as a comparator signal), and the patient portal (the patient sees their address from it). A misrouted persist call (an attacker-controlled `previous_canonical_hash` value, a forged event from a compromised source, an attacker-controlled `dpv_footnotes` flag claiming the address validated when the vendor never confirmed it) silently links the wrong address to the wrong patient with downstream blast radius across every consumer.

  4. **`infer_household_for_address` is privacy-sensitive in a different way.** A misrouted call (an attacker-controlled `canonical_hash`, a privacy-suppression-flag bypass that omits the `suppressed_patients` check, a building-type override that maps a shelter to "single_family") could produce a `HOUSEHOLD_HIGH` inference for a domestic-violence-survivor patient and her spouse, which is the precise harm the privacy-suppression machinery is supposed to prevent. The recipe's "the privacy contract is part of the architecture, not a downstream filter" framing depends on the inference path's authentication and the privacy-flag-read path's integrity.

  5. **The NCOA-result-processing path mutates the address store without an explicit authentication context.** `update_address_with_ncoa_match(patient_id, new_address, move_date, ncoa_match_type)` is invoked by the quarterly Step Functions workflow with the NCOA vendor's response payload. A forged NCOA result (an attacker-controlled vendor response payload, a Lambda misconfiguration that processes a stale or duplicated submission) silently re-locates the patient to an address the patient never moved to. The vendor-response signature verification, the submission-id-to-result-id idempotency check, and the per-mover authorization-to-update check are not specified.

  6. **The real-time API's household-lookup endpoint is named but not bounded.** The architecture diagram shows `AG1 / L3 / D2 (household-membership)`; the household-lookup pattern returns membership records for a given patient_id. A clinical-context query that returns household membership for a patient may inadvertently expose a privacy-suppressed relationship (the spouse's record is not flagged, so the household membership for the spouse leaks the survivor's location). The privacy-suppression check on the read path is named at the inference layer (the pipeline declines to write the inference) but not at the query layer (a query for the spouse's household membership might still return a record that does not exist for privacy reasons but would have existed otherwise; the absence is itself a signal).

  The HIPAA Privacy Rule's minimum-necessary requirement and the Address Confidentiality Program statutes both depend on the identity boundary. Same regulatory ground as Recipe 5.1 Finding S1 / 5.2 Finding S1; the chapter editor should consolidate identity-check guidance into a chapter preface.

- **Fix:** Specify the identity-boundary policy and the rejection semantics at the architectural level the chapter has converged on. For the real-time-ingest path, specify in the Lambda standardize-on-update paragraph that the inbound event carries a producer-signed envelope (`source_system`, `source_record_id`, `event_id`, `signed_payload`, `signature`); the standardize-on-update Lambda validates the signature against the producer's known signing key (rotated per the institutional secret-rotation policy), validates the source_system is in the allow-list, validates the event_id is unique within a sliding window (idempotency), and rejects events that fail any of these checks with a logged metric and routing to the rejected-events DLQ.

  For `persist_standardized_record`, specify the authorization context:

  ```
  FUNCTION persist_standardized_record(patient_id, raw, standardized,
                                          caller_context):
      // caller_context.invocation_source is one of:
      //   "registration_event":   inbound event from the registration
      //                            system, signed by the producer
      //   "portal_self_update":   patient-portal-initiated update,
      //                            authenticated as the patient
      //   "ncoa_mover_processor": invoked by the NCOA result handler
      //   "monthly_refresh":      invoked by the monthly USPS refresh
      //   "api_handler":          real-time API call; requires
      //                            patient_id-in-scope binding
      //
      // Validate the caller's role matches the invocation_source:
      caller_role = current_lambda_execution_role()
      IF NOT caller_role_matches_invocation_source(caller_role,
                                                     caller_context.invocation_source):
          LOG("persist_standardized_record invocation_source mismatch", ...)
          emit_metric("persist_authorization_violation", value = 1)
          REJECT
      // For api_handler, validate the authenticated principal is
      // authorized for the patient_id in the request:
      IF caller_context.invocation_source == "api_handler":
          IF NOT principal_authorized_for_patient(caller_context.principal_id,
                                                     patient_id):
              LOG("api caller not authorized for patient", ...)
              emit_metric("api_authorization_violation", ...)
              REJECT
      // For portal_self_update, the authenticated principal MUST
      // equal the patient_id (a patient may only update their own
      // address):
      IF caller_context.invocation_source == "portal_self_update":
          IF caller_context.principal_id != patient_id:
              LOG("portal self-update for non-self patient", ...)
              emit_metric("portal_authorization_violation", ...)
              REJECT
  ```

  For `infer_household_for_address`, specify that the function reads the privacy-suppression flag from a separate access-controlled table with read-side audit logging, and that the function rejects calls from invocation sources that do not include the household-inference role (the real-time API's household-lookup endpoint should not be able to invoke the inference path, only the read path).

  For the NCOA-result-processing path, specify the vendor-response signature verification (the NCOA vendor signs the result file with a key the institution holds; the result-handler Lambda validates the signature before processing) and the idempotency-on-submission-id check (a result file is processed exactly once per submission; replays are rejected).

  For the real-time API's household-lookup endpoint, specify the privacy-suppression-on-read pattern: a household-membership query for a patient_id that has the suppression flag returns "no household" (the same response as a patient who is genuinely the only person at their address) so the absence-as-signal channel is closed; an audit event records the query for forensic review.

  Reference Recipe 4.4-5.2 Finding S1 as the chapter-wide pattern. For 5.3 specifically, the address-as-anchor consequence (downstream consumers in outreach, SDOH analytics, financial assistance, the patient matcher, and the portal all consume the address) earns the HIGH severity.

### Finding S2: Audit-Log Retention Specified as "Per Institution's Records-Retention Policy" Without Architectural Floor (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, audit, forensic)
- **Location:** Prerequisites CloudTrail row: *"CloudTrail logs encrypted with KMS and retained per the institution's records-retention policy."* "Why This Isn't Production-Ready" audit-trail-retention paragraph: *"Address records and household memberships are PHI, and they are referenced in care-coordination, financial-assistance, and equity-reporting contexts. Apply the institution's records-retention policy. Keep the original input on every standardization event so the system can be re-run with newer reference data or newer correction logic and the lineage can be reconstructed."*
- **Problem:** Same chapter pattern as 5.1 Finding S2 / 5.2 Finding S2. Specifying audit retention as "per the institution's records-retention policy" is correct in spirit but defers the architectural floor. Three concrete consequences:

  1. **The records-retention floor is named in prose but not enforced architecturally.** Address records and household memberships are referenced in financial-assistance eligibility determinations (which carry their own retention floor under state and federal program rules), equity-reporting and value-based-care contracts (which often specify multi-year retention for the substrate of compliance metrics), and HIE participation agreements (which often specify retention for cross-organization-sharing artifacts). The architecture should specify the minimum floor as the longest of (HIPAA 6-year floor, the institution's documented address-and-household retention policy, the financial-assistance program's retention statute, the value-based-care contract's retention requirement, and the HIE-participation retention specification).

  2. **S3 Object Lock posture for the audit substrate is not specified.** The audit substrate is the substrate that proves which address was on file at which time, with what provenance, for which patient; immutability requires S3 Object Lock with Compliance mode. Without architectural specification, the implementation may use Standard storage with versioning, which is mutable by privileged users.

  3. **CloudTrail data event volume on the address and household tables is bounded but non-trivial.** Every read of `patient-address` and `household-membership` produces a data event; for a 500K-patient system with frequent outreach and clinical-context-query reads, this is potentially tens of millions of CloudTrail events per month.

- **Fix:** Replace the "per the institution's records-retention policy" framing with an explicit floor in the CloudTrail and Audit-Trail-Retention paragraphs:

  *"Audit-log retention is the longest of: 7 years (records-retention minimum floor for healthcare encounter-adjacent records), the institution's documented address-and-household retention policy, the financial-assistance program's retention statute (where applicable), the value-based-care contract's retention requirement (where applicable), and the HIE-participation retention specification. Audit logs are stored in a dedicated S3 bucket with Object Lock in Compliance mode for immutability and a lifecycle policy that transitions to S3 Glacier Deep Archive after 90 days for cost optimization. CloudTrail data events are forwarded to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. The retention floor is enforced at the bucket-policy and Object-Lock-configuration level, not at application logic."*

### Finding S3: Vendor BAA Posture Named but Vendor Data-Handling Expectations Are Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Security (third-party-risk, PHI flow)
- **Location:** Prerequisites BAA row: *"AWS BAA signed. The standardization vendor must also be willing to sign a BAA, since you will be sending PHI (the address combined with patient identifier) to their API. Most major address-quality vendors offer healthcare-tier service plans with BAAs available."* And the Vendor Selection row: *"Vet the standardization vendor for: CASS certification, NCOAlink certification, BAA availability, healthcare-customer references, API rate limits and bulk-processing options, response-time SLAs, geographic coverage (US-only or international), pricing model, uptime SLA, and data-handling commitments (do they retain submissions, for how long, with what controls)."*
- **Problem:** The recipe correctly identifies that the vendor sees PHI and must sign a BAA. The Vendor Selection row names "data-handling commitments" but the architecture does not specify what the institution should require contractually or verify operationally. Three concrete consequences:

  1. **The PHI-in-flight content is precisely the address combined with the patient_id.** The recipe's pseudocode sends `raw.line1`, `raw.line2`, `raw.city`, `raw.state`, `raw.zip` and the patient_id is captured separately in the `_archive_raw_to_s3` step, but the vendor API call includes whatever payload the vendor expects. Some vendors require sending the patient identifier as part of the API call (for batch processing with response correlation); others accept the address alone. The architecture should specify which pattern is in use and what de-identification is feasible at the vendor boundary.

  2. **Vendor data-retention policies vary widely.** Some vendors retain submitted addresses for a documented window (often 30-90 days) for fraud detection, accuracy improvement, or operational debugging; others retain them indefinitely; others retain only the response, not the submission. The architecture should specify the maximum acceptable retention and require the vendor to delete submissions on a documented cadence as a contractual obligation.

  3. **Vendor sub-processor disclosure is not addressed.** The vendor may use sub-processors (cloud-infrastructure providers, sub-vendors for specific country coverage, sub-vendors for the geocoding step). Each sub-processor is a PHI-exposure surface. The BAA should require sub-processor disclosure and the institution's right to object.

- **Fix:** Add to the Vendor Selection row and the BAA row a paragraph specifying the PHI-flow controls:

  *"Vendor BAA terms should specify: (a) the vendor will not retain submitted addresses beyond a documented operational window (typically 30-90 days), with deletion verifiable on request; (b) the vendor will disclose all sub-processors that may handle PHI (including cloud-infrastructure providers, sub-vendors for international coverage, sub-vendors for geocoding) and the institution may object to specific sub-processors; (c) the vendor will notify the institution within a documented window (typically 24-72 hours) of any data incident affecting institutional data; (d) the vendor will sign a HIPAA-compliant BAA and a data-processing addendum specifying the institution's right to audit the vendor's controls (typically annually or upon material change)."*

  Add to the architecture pseudocode a comment at the vendor-API call site explaining the de-identification posture (whether the patient_id flows to the vendor and why, or whether the architecture uses a vendor-side correlation token instead).

### Finding S4: Suppress-Entire-Group vs Exclude-Suppressed Policy Decision Is Surfaced but the Audit Posture for the Decision Path Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Security (privacy, forensic-traceability)
- **Location:** Step 4B pseudocode and the architecture pattern paragraph: *"the household inference pipeline checks for this flag on every record before grouping, and any group that contains a suppressed record either suppresses the household inference for the entire group or excludes the suppressed record from the group, depending on the institution's privacy policy."* And "Why This Isn't Production-Ready" privacy paragraph: *"The recipe presents two policy options ... Either is defensible; the right one depends on the institution's legal and clinical context. The decision has to be made by the privacy office and the clinical leadership, documented in the institution's privacy policy, and surfaced in the household-inference audit trail. Do not leave this as an implementation detail."*
- **Problem:** The recipe correctly elevates the policy decision to "surface in the audit trail" and "do not leave this as an implementation detail." But the architecture does not specify the audit fields, the policy-version tracking, or the per-suppression-event audit record. Concrete consequences:

  1. **The audit trail does not specify which policy was active at the time of an inference.** A household-membership record written under `suppress_entire_group_if_any_suppressed` has different semantics than one written under `exclude_suppressed_from_group`; the policy in effect is not stored on the record. A subsequent forensic review (a domestic-violence-survivor patient learns the household graph leaked her location and asks the institution to investigate) cannot reconstruct the policy state at the time of the inference.

  2. **Policy changes are not architectural events.** The recipe's "the policy decision has to be made by the privacy office" framing implies the policy is decision-level; the architecture should treat the policy-change as an event that triggers re-inference of all affected records (otherwise records inferred under the old policy persist with the old semantics indefinitely).

  3. **Per-suppression-event audit records are not specified.** When the inference path encounters a suppressed record, the audit record should capture: which patient was suppressed, which canonical hash was being inferred, what action the policy took (excluded the record, suppressed the entire group), what the resulting household-membership state was, and which downstream consumers were notified (or not).

- **Fix:** Specify in the architecture pattern and in the household-inference pseudocode:

  *"The household-inference pipeline records, on every household-membership row, the policy version active at the time of inference (`privacy_policy_version`), the policy decision (`privacy_decision`: `none`, `suppressed_record_excluded`, `suppressed_group_entirely`), and the inference timestamp. A separate `privacy_suppression_audit` table records every encounter with a suppression flag during inference, keyed on `(canonical_hash, suppression_event_timestamp)`, with the patient_id of the suppressed record, the action taken, and the resulting household state. A change in the institutional privacy policy emits a `privacy_policy_changed` event on EventBridge that triggers re-inference for every canonical hash with at least one suppressed record."*

  Add to the household-membership schema the `privacy_policy_version` and `privacy_decision` fields. Add to the `privacy_suppression_audit` table the schema for forensic reconstruction.

### Finding S5: Cohort PHI in CloudWatch Metric Dimensions (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** General Architecture Pattern paragraph: *"Per-cohort standardization-success rate, household-inference confidence distribution, and downstream geocoding success rate are all metrics worth tracking, with disparity thresholds that trigger investigation."*
- **Problem:** Same chapter-wide pattern as 4.4-5.2 / Finding S5. Cohort dimensions on metrics use bucketed, non-reversible labels.
- **Fix:** Same as 5.2 Finding S5. Specify in the CloudWatch paragraph that cohort dimensions on metrics use bucketed, non-reversible cohort labels from the institutional cohort registry rather than raw patient attributes.

### Finding S6: IAM "Never `*` Actions or `*` Resources in Production" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row.
- **Problem:** Same finding as Recipe 4.1-5.2.
- **Fix:** Inline scoped ARN examples for the highest-stakes actions: `dynamodb:UpdateItem` on `arn:aws:dynamodb:<region>:<account>:table/patient-address`; `dynamodb:Query` on the canonical-hash-index ARN; `s3:PutObject` on `arn:aws:s3:::<env>-address-curated/audit/*`; `events:PutEvents` on `arn:aws:events:<region>:<account>:event-bus/address-and-household-drift`; `secretsmanager:GetSecretValue` on the vendor-API-key secret ARN. Or consolidate into the chapter preface.

### Finding S7: Patient-Portal Address Self-Service Disclosure Posture Not Addressed

- **Severity:** LOW
- **Expert:** Security (forward-looking, disclosure-policy)
- **Location:** Variations and Extensions: *"Patient-portal address self-service. Build the portal feature that shows the patient their on-file address with a confirm-or-update flow."* And the Honest Take's *"invest more heavily in the patient-portal address-confirmation flow."*
- **Problem:** Sibling to Recipe 5.1 / 5.2 Finding S5. Surfacing the on-file address back to the patient is itself a disclosure event under some state laws, particularly when the on-file address differs from the patient's expectation (the institution has a stale address, the institution has a vendor-corrected address that the patient never confirmed, the institution has multiple address roles and the portal exposes which one it is showing). The variation should name the disclosure-policy gate as a prerequisite.
- **Fix:** Add a sentence to the Patient-Portal Self-Service variation: *"Before surfacing the institution's standardized address back to the patient, the institution should review the disclosure policy: addresses sourced from the patient's own portal updates are appropriate to display verbatim; addresses sourced from registration-clerk entry, insurance subscriber feeds, or HIE referrals carry separate provenance, and the portal display should indicate the source rather than presenting the address as if the patient had entered it. Patients with privacy-suppression flags require special handling: the portal should not surface the household-membership inference, only the address itself."*



## Architecture Expert Review

### What's Done Well

- **Six-stage pipeline shape is correct.** Ingest, standardize, geocode, persist, infer household, refresh-and-drift maps cleanly to the operational reality. The "geocoding is co-located but separable" framing is the right architectural choice.
- **Idempotency-on-input-hash for standardization caching.** The recipe correctly frames the cache key as `sha256(canonical_form(raw))` and notes that "many addresses are repeats across patient records (family members at the same address, address copied from one record to another)." This is the right cache-design discipline for a workload where 30-50% of vendor calls would otherwise be duplicates.
- **Six-status classification of standardization outcomes.** `VALIDATED`, `CORRECTED`, `MISSING_SECONDARY`, `AMBIGUOUS`, `NOT_VALIDATED`, `INVALID` is the right granularity. Each status drives a different downstream behavior; collapsing them into "good vs bad" loses information that downstream consumers need.
- **Graded household-confidence contract.** `HOUSEHOLD_HIGH`, `HOUSEHOLD_MEDIUM`, `CO_LOCATED`, `SUPPRESSED` is the recipe's strongest single architectural primitive. The "co-located but not household" category prevents the "200-unit apartment building collapsed into one household" failure mode that any naive grouper produces.
- **Privacy suppression as a first-class case in the architecture.** The "suppress early, not late" framing and the two-policy options (suppress-entire-group vs exclude-suppressed) are correctly elevated from "implementation detail" to "architectural primitive."
- **Building-type-aware household inference.** Mapping the standardization metadata (`is_residential`, `is_business`, `is_po_box`) plus same-record analysis to a building-type classifier (`single_family`, `multi_unit_with_unit`, `multi_unit_no_unit`, `commercial`, `po_box`, `shelter`, `nursing_home`) and using it to gate household inference is the right pattern. PO Boxes and shelters do not produce household groupings; nursing homes do not either.
- **NCOA-driven mover detection on a quarterly cadence.** The "1-3% mover detection rate per quarter at a 500K-patient system" framing in the Honest Take produces the right intuition for the operational value of NCOA. The architecture-level Step Functions orchestration with the secure file exchange to the vendor and the result-handler Lambda is the right pattern for batch-oriented vendor integration.
- **Drift-event fan-out via EventBridge.** Drift events to outreach pipeline, SDOH analytics, patient portal, and the patient matcher (5.1) is the right pattern for cross-recipe orchestration.
- **Vendor-as-swappable-component framing.** The architecture treats the standardization vendor as "swappable, the standardized-record schema is the contract" which is the right institutional stance for a vendor-dependent pipeline.

### Finding A1: persist_standardized_record and infer_household_for_address Are Not Atomic; Sequential DynamoDB / S3 / EventBridge Operations Leave Half-Updated State on Partial Failure

- **Severity:** HIGH
- **Expert:** Architecture (correctness, distributed-systems consistency)
- **Location:** Step 3 pseudocode `persist_standardized_record(patient_id, raw, standardized)` performs `DynamoDB.GetItem` (read previous), `DynamoDB.PutItem` (write current), `write_to_s3` (archive), `EventBridge.PutEvents` (emit), and two `invoke_household_inference` calls (re-inference for old and new canonical hashes). Step 4 pseudocode `infer_household_for_address(canonical_hash)` performs `DynamoDB.Query` (read group), N `DynamoDB.PutItem` calls (one per member of the household), and `EventBridge.PutEvents` (emit). The recipe's TODO at Step 3B explicitly names the gap: *"TODO (TechWriter): Wrap the DynamoDB write, the S3 archive write, and the EventBridge emit in a transactional pattern (TransactWriteItems plus an outbox row drained by a separate Lambda or DynamoDB Streams consumer) so partial failures do not leave the address table out of sync with downstream consumers. Same chapter pattern as 5.1, 5.2."*
- **Problem:** The chapter pattern from 5.1 Finding A1 / 5.2 Finding A1 applies. Sequential operations across DynamoDB, S3, and EventBridge each have independent failure modes (Lambda timeout between operations, IAM permission expiry mid-call, cross-region replication lag, EventBridge throttling). Concrete failure scenarios:

  1. **DynamoDB write succeeds, S3 archive fails.** `patient-address` has the new standardized record; the audit S3 has no entry for this update. Subsequent compliance reconstructions cannot prove what was on file at what time.

  2. **DynamoDB write succeeds, EventBridge emit fails.** `patient-address` has the new record; downstream consumers (outreach, SDOH analytics, patient matcher) never receive the change event and continue to operate on the previous address. Mailing-list scrubbing breaks: the outreach pipeline mails to the previous address even though the new one is on file.

  3. **DynamoDB write succeeds, household-inference invocation fails.** `patient-address` has the new record at the new canonical hash; `household-membership` still reflects the patient's membership at the old canonical hash. The financial-assistance workflow looks up the household, gets the stale membership, and computes eligibility against the wrong household composition.

  4. **DynamoDB write succeeds, secondary household-inference invocation fails (only one of the two re-inferences ran).** The new-canonical-hash group is updated; the old-canonical-hash group is not. The patient is in two households simultaneously, or the old household has a phantom member who has actually moved.

  5. **For `infer_household_for_address`: partial PutItem batch.** The function writes one PutItem per household member. If the batch partially completes (DynamoDB throttling, Lambda timeout), the household has some members updated and some not. The membership records are inconsistent: some say "HIGH confidence as of t+1," some say "MEDIUM confidence as of t-1."

  The regulatory consequence here is sharper than 5.1/5.2 because the address store feeds outreach (mailing-list scrubbing breaks if the address persisted but the household-inference event was not emitted), the financial-assistance workflow (eligibility re-determination reads household membership), and the equity-reporting pipeline (SDOH metrics depend on the address being current). Half-applied state in any of these paths produces compliance-visible inconsistency.

- **Fix:** Specify the transactional pattern in the architecture pattern paragraph and rewrite the pseudocode for both Step 3 and Step 4. For Step 3:

  ```
  FUNCTION persist_standardized_record(patient_id, raw, standardized):
      previous = DynamoDB.GetItem("patient-address",
          key={patient_id, address_role: raw.address_role})

      // Compose a TransactWriteItems request that updates the
      // patient-address row, writes an outbox row for the side
      // effects, and conditionally writes a single canonical-hash
      // change record. The transaction is all-or-nothing.
      DynamoDB.TransactWriteItems([
          {
              Put: {
                  TableName: "patient-address",
                  Item: {patient_id, address_role, standardized,
                          previous_canonical_hash, last_updated_at,
                          next_revalidation_due_at}
              }
          },
          {
              Put: {
                  TableName: "address-outbox",
                  Item: {
                      outbox_id: uuid(),
                      event_type: "address_standardized",
                      payload: {patient_id, address_role,
                                  previous_canonical_hash,
                                  new_canonical_hash,
                                  standardization_status,
                                  standardized_at},
                      created_at: current UTC timestamp,
                      status: "PENDING"
                  }
              }
          }
      ])
      // A separate outbox-drainer Lambda (triggered by DynamoDB
      // Streams on the address-outbox table) handles the S3 archive
      // write, the EventBridge emit, and the household-inference
      // invocations. The drainer is idempotent at outbox_id and
      // marks rows COMPLETED only after all downstream effects
      // succeed; failures route to a DLQ for operator inspection.
  ```

  For Step 4, group the per-member PutItem calls into a `TransactWriteItems` batch (DynamoDB supports up to 100 items per transaction; for households exceeding this, use a saga pattern with a household-update-id that downstream consumers can correlate on). Reference Recipe 5.1 Finding A1 / 5.2 Finding A1 as the chapter-wide pattern. The chapter editor should consolidate the outbox-pattern guidance into a chapter preface.

### Finding A2: Cohort-Stratified Accuracy Thresholds and Metric Definitions Referenced as "Required Here Too" but Undefined (Chapter-Wide Pattern)

- **Severity:** HIGH
- **Expert:** Architecture (operational rigor, equity instrumentation)
- **Location:** General Architecture Pattern paragraph: *"Cohort-stratified accuracy monitoring is required here too. Address standardization quality varies across cohorts ... Per-cohort standardization-success rate, household-inference confidence distribution, and downstream geocoding success rate are all metrics worth tracking, with disparity thresholds that trigger investigation."* And "Why This Isn't Production-Ready" paragraph: *"Like recipes 5.1 and 5.2, the cohort-stratified monitoring needs operational thresholds (suggested: per-cohort standardization-success-rate disparity threshold of 0.05, household-inference HIGH-confidence-rate disparity threshold of 0.10, geocoding-success-rate disparity of 0.05), per-cohort gold-set construction discipline, and a documented remediation pathway for threshold crossings."*
- **Problem:** Same chapter pattern as 5.1 Finding A2 / 5.2 Finding A2 / 4.10 Finding A1. The recipe explicitly inherits the rigor from 5.1 and 5.2 ("required here too") and the Honest Take names the suggested thresholds (0.05 for standardization-success-rate, 0.10 for HIGH-confidence-rate, 0.05 for geocoding-success-rate). But the architecture pattern does not specify:

  1. **The cohort axis enumeration that the metric must aggregate over.** Urban-multi-unit, rural, naming-convention-defined, unstable-housing are named in the prose; the architecture should specify the institutional cohort registry as the source of truth and require the metric pipeline to aggregate over the registry's cohort axes rather than over an ad-hoc list.

  2. **The disparity calculation method.** "Disparity threshold of 0.05" can mean absolute difference between best and worst cohort, or ratio of best to worst, or maximum deviation from the population mean. The three calculations produce different alerting behavior. The architecture should specify which.

  3. **The metric pipeline's emission cadence.** Daily, weekly, monthly. The standardization-success-rate moves slowly (population-level metric); the household-inference confidence distribution can shift quickly (a single registration event change can cascade). The cadence should be specified per-metric.

  4. **The remediation pathway.** A threshold crossing should trigger a documented sequence: alert routing (which team), investigation (what artifacts to pull), corrective action (per-cohort vendor tuning, supplementary correction logic, registration-staff training, threshold review), and post-mortem retention.

  The cohort-distribution stakes are higher here than in 5.1/5.2 because address-data-quality disparities directly translate to SDOH metric disparities (downstream of standardization plus geocoding), outreach reach disparities (mailing-list scrubbing produces fewer reaches for cohorts with worse standardization), and financial-assistance access disparities (household linkage is a gating factor). The Honest Take's "equity in address quality is equity in access" framing earns the architectural specification.

- **Fix:** Specify in the General Architecture Pattern paragraph:

  *"Cohort-stratified accuracy monitoring uses the institutional cohort registry as the source of truth for cohort axes (no ad-hoc enumeration in code). Metrics: (a) standardization-success rate (percent of records with status `VALIDATED` or `CORRECTED` confidence > 0.90) per cohort, computed weekly; (b) household-inference HIGH-confidence rate (percent of multi-record co-location buckets resolving to `HOUSEHOLD_HIGH`) per cohort, computed weekly; (c) geocoding-success rate (percent of standardized addresses resolving to a census-block geocode) per cohort, computed weekly; (d) NCOA mover-detection rate per cohort, computed quarterly. Disparity calculation: absolute difference between the cohort with the highest rate and the cohort with the lowest rate, computed per-metric per-cycle. Alarm thresholds: standardization-success-rate disparity > 0.05 → MEDIUM; HIGH-confidence-rate disparity > 0.10 → MEDIUM; geocoding-success-rate disparity > 0.05 → MEDIUM; any disparity > 2x the threshold → HIGH. Alarms route to the data-quality team with a 5-business-day SLA for the first investigation report; the post-mortem and any remediation (vendor tuning, supplementary correction logic, registration-staff training) is documented in the cohort-disparity ledger and reviewed quarterly by the address-data-quality steering committee."*

  Reference 5.1 Finding A2 / 5.2 Finding A2 as the chapter-wide pattern. The chapter editor should consolidate cohort-fairness instrumentation into a chapter preface.

### Finding A3: Monthly USPS Refresh Iterates the Entire Population Per Cycle; Cost and Throughput Math Does Not Match the Stated Cost Estimate

- **Severity:** HIGH
- **Expert:** Architecture (cost discipline, throughput modeling)
- **Location:** Step 5A pseudocode: *"all_addresses = DynamoDB.Scan('patient-address')"* with the comment *"For large populations, this is a Glue/Spark job over S3-archived snapshots rather than a DynamoDB scan."* Step 5B: *"new_standardized = standardize_address(address_record.standardized.original_input)"* (re-standardize every record on every cycle). The Cost Estimate row: *"At a medium-sized health system with ~500,000 patients and ~10,000 new addresses per month plus quarterly refresh: vendor standardization costs roughly $0.005-0.02 per address validated ... so monthly throughput at ~520,000 addresses (10K new plus 510K quarterly-refresh share) ≈ $2,500-10,000/month."*
- **Problem:** The architecture specifies a full-population monthly refresh in the pseudocode (Step 5A pulls all addresses, Step 5B re-standardizes each, Step 5C compares, Step 5D persists, Step 5E re-runs household inference). At 500K patients with the implied at-least-one-physical-plus-mailing-address profile, the monthly refresh is at minimum 500K vendor calls per month, plus the 10K new-address calls, plus the quarterly NCOA submission, plus the registration-time real-time calls (which depend on registration volume).

  Concrete throughput math at the higher per-record vendor pricing tier ($0.02):

  - 500K patients × 1.2 addresses/patient (physical plus 20% with separate mailing) × 12 monthly refreshes = 7.2M calls/year
  - 10K new addresses/month × 12 = 120K calls/year
  - Quarterly NCOA: 4 cycles × 500K = 2M calls/year (depending on vendor billing model)
  - Real-time registration: 2-5% of population/month × 12 = 120K-300K calls/year

  Total: ~9.4M-9.6M vendor calls/year × $0.02 = ~$188K-$192K/year, which is ~$15K-$16K/month, exceeding the stated upper bound of $11.5K/month.

  At the lower pricing tier ($0.005), the monthly refresh alone is 500K × 1.2 × $0.005 = $3K/month plus the other paths, which fits the lower bound. The point is not that the cost estimate is wrong (the lower bound fits), but that the architecture's full-population monthly pattern ties throughput to population size in a way that does not scale gracefully (a 1M-patient system pays double for the same operational cadence; a 5M-patient system pays 10x for no additional value over a change-driven pattern).

  Architectural alternatives that the recipe does not specify:

  1. **Change-driven refresh.** Re-standardize only records where (a) the input changed since last cycle, (b) the cache TTL expired, or (c) the USPS reference data flagged the canonical-hash-prefix range as updated (the USPS refresh data identifies which ZIP+4 ranges and which DPV records changed; an architecturally-aware refresh restandardizes only the records whose canonical-hash prefix maps to a changed range).

  2. **Sample-and-extrapolate.** Re-standardize a stratified sample (per cohort, per ZIP-3 prefix, per address vintage) and use the sample to extrapolate the population drift rate; full-refresh only the cohorts with elevated drift.

  3. **Vendor-side change feed.** Some vendors (Smarty, Melissa) offer a change-feed product that emits the addresses in your population that changed since last cycle, eliminating the need for a full re-validation pass.

  The recipe's Honest Take partially acknowledges this gap (*"which subset of addresses to re-standardize each cycle (entire population is expensive; only-changed-in-USPS-reference is hard to identify; sample-and-extrapolate is wrong)"*) but the architecture commits to the entire-population pattern that the Honest Take labels as expensive. The architecture should specify the change-driven pattern as the primary path.

- **Fix:** Replace the Step 5 pseudocode and the architecture-pattern paragraph with the change-driven refresh:

  ```
  FUNCTION monthly_usps_refresh():
      // Step 5A': pull the USPS reference-data change manifest for
      // this cycle. The manifest enumerates: (1) ZIP+4 ranges with
      // changed delivery information, (2) DPV records added/removed,
      // (3) building-type metadata changes. The manifest is published
      // by the vendor as part of the monthly reference-data release.
      change_manifest = vendor_sdk.get_reference_data_change_manifest(
          previous_release: last_processed_release,
          new_release: latest_release)

      // Step 5B': identify the patient-address rows whose canonical
      // hash maps to a changed range. Use a Glue/Spark job over the
      // S3-archived snapshots rather than a DynamoDB scan.
      affected_records = glue_job_filter_by_canonical_hash_range(
          snapshot: latest_patient_address_snapshot,
          changed_ranges: change_manifest.changed_ranges)

      // Step 5C': also include records whose cache TTL expired
      // independent of reference-data changes (catches vendor
      // software updates and correction-logic improvements).
      stale_records = glue_job_filter_by_cache_ttl(
          snapshot: latest_patient_address_snapshot,
          ttl_threshold: today() - CACHE_TTL_DAYS)

      records_to_refresh = union(affected_records, stale_records)

      // Step 5D': re-standardize only the affected records.
      FOR each address_record in records_to_refresh:
          new_standardized = standardize_address(
              address_record.standardized.original_input)
          // ... drift detection and persist as in original Step 5C-E

      emit_cloudwatch_metric("usps_refresh_records_processed",
                                len(records_to_refresh))
      emit_cloudwatch_metric("usps_refresh_population_skipped",
                                population_size - len(records_to_refresh))
  ```

  Update the Cost Estimate row to reflect the change-driven throughput: *"At a 500K-patient health system, the change-driven refresh typically processes 5-15% of the population per cycle (the remainder is skipped because no relevant USPS reference change applies and the cache TTL has not expired). Vendor cost: $300-1,500/month for the refresh path, $150-300/month for new addresses, $1,000-3,000/quarter for NCOA, plus AWS infrastructure $300-1,500/month. Total: $2,000-6,000/month. Full-population monthly refresh is available as an architectural alternative for institutions that prefer simplicity over cost optimization, with the cost roughly 3-5x the change-driven baseline."*

  Reference: this is a recipe-specific finding (5.1 and 5.2 do not have the same full-population periodic-refresh pattern; 5.2's daily re-verification is per-provider and naturally scoped to providers due for verification, not full population).

### Finding A4: Idempotency and DLQ Coverage on Lambda Paths Underspecified (Chapter-Wide Pattern, Already Partially TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" idempotency paragraph: *"Use the `(patient_id, address_role)` as the idempotency key for standardization-and-persist. Use the `canonical_hash` as the idempotency key for household-inference. Use the `(patient_id, ncoa_submission_id)` for NCOA-result processing. Lambda invocations should be idempotent at these keys; DLQs should be configured on every Lambda path; Step Functions Catch states should route to the DLQ so terminal failures are visible."*
- **Problem:** Same chapter pattern as 5.1 / 5.2. The idempotency keys are correctly named in the production-gaps section but not specified in the architecture pattern, the pseudocode, or the Lambda configuration. The DLQ topology (one DLQ per Lambda, or shared DLQ per pipeline phase) is not specified.
- **Fix:** Add to the General Architecture Pattern paragraph: *"Every Lambda invocation in the pipeline is idempotent at a recipe-specific key: standardize-on-update at `(patient_id, address_role, raw_input_hash)`; persist-standardized-record at `(patient_id, address_role, standardized.standardized_at)`; household-inference at `(canonical_hash, inference_version)`; NCOA-result-processing at `(submission_id, mover_record_id)`; drift-event emission at `(patient_id, address_role, drift_type, detected_at_day)`. Each Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows within 15 minutes of accumulation."*

### Finding A5: Real-Time Standardization API Latency Budget and Vendor Failover Pattern Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (operational SLA, availability)
- **Location:** Real-Time API paragraph: *"Latency budget is sub-second for the registration-clerk experience; vendor API calls typically fit in that budget, with caching for repeat addresses helping the common case."*
- **Problem:** Sub-second is a stated budget but the architecture does not specify the breakdown (cache hit vs miss latency, vendor SLA, fail-open vs fail-closed semantics, fallback when the vendor is unavailable). At a registration desk, a 5-second hang on the address-validation API can break the workflow; the architecture should specify what happens on vendor unavailability:

  1. Fail-open: accept the raw address with a `pending_standardization` flag and re-standardize asynchronously when the vendor recovers. Workflow continues without interruption.
  2. Fail-closed: block registration until standardization succeeds. Workflow halts.
  3. Hybrid: fail-open for new patients (registration must complete); fail-closed for portal updates (patient can retry later).

  The recipe mentions "exponential-backoff retry for transient failures, and a degraded path that accepts the raw address with a `pending_standardization` flag" in the "Where it struggles" section but does not specify the latency thresholds or the workflow gating policy.

- **Fix:** Add to the Real-Time API paragraph: *"Latency budget breakdown: P50 cache-hit latency < 50ms, P50 cache-miss-with-vendor-call latency < 400ms, P95 < 800ms, P99 < 2s. Vendor API call timeout 1.5s with one retry (total 3s before fallback). Fallback: accept the raw address with `standardization_status: 'PENDING_STANDARDIZATION'`, write to `patient-address` with the pending flag, emit a `pending_standardization` event that drains via the asynchronous re-standardization Lambda when the vendor recovers (typically within minutes for transient failures, hours for vendor-side incidents). The registration workflow continues without interruption (fail-open); a CloudWatch alarm fires when the pending-standardization queue depth exceeds 100 records or persists for more than 30 minutes. Vendor failover to a secondary CASS-certified vendor is not architected at the Lambda layer (the operational complexity of multi-vendor consistency exceeds the value at most institutions); institutions with stricter availability requirements should evaluate primary-secondary vendor patterns separately."*

### Finding A6: Cross-Recipe Orchestration with 5.1 (Patient Matcher) and Downstream Consumers Mentioned but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture diagram shows `EB1 -->|FanOut| C4[Patient Matcher 5.1<br/>re-evaluate]`. Related Recipes section names 5.1, 5.4, 5.5, 5.7, 5.8 as recipes that consume the address store.
- **Problem:** The architecture diagram shows the drift-event fan-out to the patient matcher, but the contract between recipes is not specified: what payload the matcher receives, what the matcher's expected response cadence is, how the matcher signals back that re-evaluation produced a new candidate pair, what the deduplication semantics are when the matcher and the address store both hold address fields. Same chapter pattern as 5.2 Finding A9.
- **Fix:** Add to the General Architecture Pattern paragraph a cross-recipe contract: *"The address-and-household drift events conform to a chapter-wide event schema (`source`, `detail_type`, `detail.patient_id`, `detail.event_id`, `detail.previous_state`, `detail.new_state`, `detail.detected_at`). Downstream consumers in 5.1, 5.4, 5.5, 5.7, 5.8, and the outreach and SDOH pipelines subscribe to specific `detail_type` values and acknowledge processing via a CloudWatch metric (`{consumer}.events_processed`). The chapter-wide event-bus governance specifies the schema versioning policy and the deprecation cadence for breaking changes."* Reference Recipe 5.1 / 5.2 / 5.4 contracts as the chapter pattern.

### Finding A7: M/U-Equivalent Probability Re-Estimation for Household-Inference Confidence Thresholds Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (governance, model lifecycle)
- **Location:** Step 4D pseudocode: *"confidence = assign_confidence_level(confidence_assessment, building_type)"* and the inference_basis enumeration. The function is treated as a deterministic classifier; the parameters that govern the classifier (last-name overlap threshold, age-pattern consistency criteria, insurance-subscriber match weight) are implicit.
- **Problem:** Same chapter pattern as 5.1 Finding A11 / 5.2 Finding A11. The household-inference confidence assignment is functionally a probabilistic classifier whose thresholds need re-estimation as the patient population evolves and as the vendor's address-quality output changes. The architecture should specify:

  1. The threshold values used by `assign_confidence_level` (what last-name-overlap fraction crosses MEDIUM-to-HIGH, what age-pattern criteria, what insurance-subscriber weight).
  2. The re-estimation cadence (annually, semiannually, on cohort-distribution drift detection).
  3. The validation gating (a held-out gold set with known household memberships across building types and cohorts; an institutional review of the confusion matrix before threshold changes are deployed).
  4. The change-management posture (threshold changes are versioned; downstream consumers see the version on every household-membership row, as called out in Finding S4).

- **Fix:** Add to the General Architecture Pattern paragraph: *"The household-inference confidence assignment uses configurable thresholds (last-name overlap fraction, age-pattern consistency criteria, insurance-subscriber match weight, secondary-unit completeness weight) stored in a versioned configuration table. The thresholds are calibrated against a held-out gold set of labeled households spanning building types and cohorts; re-calibration runs annually or on detection of cohort-stratified disparity above 0.10 (whichever comes first). Re-calibration produces a candidate threshold set; the institutional review (data-quality team, privacy office, clinical leadership) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to the production configuration. Each household-membership row records the configuration version and the threshold values active at inference time, supporting forensic reconstruction across re-calibration cycles."*

### Finding A8: API Gateway Resource Policy and WAF Posture for the Real-Time API Not Specified (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (security boundary, defense in depth)
- **Location:** Architecture diagram shows `AG1[API Gateway<br/>standardize / household-lookup] -> CG1[Cognito] -> L3[Lambda<br/>api-handler]`. Prerequisites IAM Permissions row references the API but does not specify the resource policy or WAF.
- **Problem:** Same chapter pattern as 5.1 Finding N1 / 5.2 Finding N1. The real-time API's resource-policy posture (private API only, IP allowlist, integration with AWS WAF) is not specified. The standardize endpoint accepts patient-level address data; without a resource policy restricting the API to the institutional VPC and without WAF rules on rate limiting and injection-pattern matching, the API surface is exposed to the public internet by default.
- **Fix:** Add to the Real-Time API paragraph: *"The API Gateway is configured as a private API with a VPC endpoint resource policy restricting access to the institutional VPC; the registration system, the patient portal, and the clinical-context-query consumers reach the API through the VPC endpoint. AWS WAF is attached with rule groups for SQL injection, command injection, request rate limiting (per-source-IP and per-Cognito-principal), and request-size limiting. CloudFront-with-WAF is used if the patient portal is publicly addressable; the institutional perimeter terminates TLS at the WAF and re-establishes TLS to the API."*

### Finding A9: Outbound Vendor API Egress Posture Could Be Sharpened (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (egress discipline, audit)
- **Location:** Prerequisites VPC row: *"NAT Gateway for the vendor API call (vendor APIs typically do not have AWS PrivateLink endpoints) with an outbound HTTPS proxy and an allow-list of vendor domains."*
- **Problem:** The egress posture is correctly outlined but could be sharpened with vendor-specific allow-list scoping. The standardization vendor's domain (e.g., `us-rest.api.smartystreets.com` or equivalent) and the NCOA vendor's domain are distinct concerns; a compromise of the standardization Lambda should not be able to exfiltrate via the NCOA path. Same pattern as 5.2 Finding N2.
- **Fix:** Add to the VPC row: *"The standardization-vendor egress and the NCOA-vendor egress are configured as distinct outbound proxy rules with non-overlapping allow-lists scoped to the relevant compute roles: the standardization Lambda's role allows only the CASS-certified-vendor's API domain; the NCOA-result-handler Lambda's role allows only the NCOA-vendor's secure-file-exchange domain. The proxy enforces a per-role rate limit on vendor API calls below the vendor's published rate limits. Egress connections are CloudWatch-logged for chargeback and for forensic auditing."*

### Finding A10: Athena Access Control on Audit and Curated S3 Zones Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (analytics access governance)
- **Location:** Architecture diagram shows `S2[S3<br/>address-curated] -> GC1[Glue Catalog] -> AT1[Athena] -> QS1[QuickSight]`.
- **Problem:** Same chapter pattern as 5.2 Finding A10. The Athena access path to the curated and audit zones lacks explicit access-control specification. Standardized addresses are PHI; QuickSight users do not need access to the full address payload, only the cohort-aggregated metrics. Lake Formation column-level controls or equivalent should restrict access.
- **Fix:** Add to the Why These Services / Athena paragraph: *"Lake Formation column-level access controls restrict QuickSight and Athena consumers to the columns they need: dashboards see cohort-aggregated metrics only; data-quality team users see the full standardized address payload and the audit-trail provenance; the privacy-suppression-audit table is restricted to the privacy office and the institutional auditors. Access is logged via CloudTrail data events on the catalog and on the underlying S3 buckets."*

### Finding A11: Backfill of the Existing Patient Address Population Mentioned but Not Architected (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (one-time vs ongoing operations)
- **Location:** The Honest Take's *"The first time you run standardization across the population, the data team gets a small shock at how many patient addresses needed correction"* implies a backfill operation but the architecture does not specify it.
- **Problem:** Same chapter pattern as 5.1 / 5.2. A one-time backfill of the existing 500K patient address population is a separate operational concern from the steady-state pipeline: it requires Glue capacity planning, vendor rate-limit negotiation, household-inference batch over the entire post-standardization population, and careful sequencing of the downstream-event emission (a 500K-record fan-out at once would flood the consumers).
- **Fix:** Add to the Production-Gaps section a paragraph: *"Initial backfill of the existing patient address population is a one-time operation with distinct architectural considerations: (a) negotiate a one-time bulk pricing tier with the standardization vendor (typical bulk pricing is 5-10x cheaper per record than the real-time tier); (b) run the backfill as a Glue job with controlled concurrency to stay below the vendor's rate limit; (c) suppress the address-standardized event emission during backfill (downstream consumers refresh from a single 'backfill_complete' marker rather than 500K individual events); (d) run household inference as a separate Glue job after backfill completes; (e) emit one 'household_inference_backfill_complete' event when household inference is done, with the cohort-stratified accuracy report attached. Plan the backfill timeline in coordination with downstream consumers (outreach, SDOH analytics, financial assistance) so the change in address quality lands in their workflows on a known date."*

### Finding A12: Cache TTL Policy Not Specified

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 2B pseudocode: *"cached = check_standardization_cache(raw_input_hash); IF cached IS NOT NULL AND cached.cache_age < CACHE_TTL: RETURN cached.standardized"*
- **Problem:** The cache TTL is referenced but not specified. The right TTL is bounded by USPS reference-data update cadence (monthly): a cache entry older than 30 days might be stale because the underlying USPS data has updated. A TTL of 30 days aligns with the monthly USPS refresh; longer TTLs increase the risk of returning stale standardizations; shorter TTLs reduce the cache hit rate and increase vendor cost.
- **Fix:** Add to the Step 2B comment: *"CACHE_TTL is set to 30 days (aligned with the USPS monthly reference-data update cadence). Cache entries are stored in DynamoDB with a TTL attribute so DynamoDB auto-evicts. Cache invalidation on USPS reference-data update is handled separately by the change-driven refresh (Finding A3): if the USPS refresh re-standardizes a record, the cache for the underlying raw_input_hash is updated as a side effect."*

---

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** Lambdas in VPC; Glue jobs in VPC connections; VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, STS. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization with outbound proxy.** "NAT Gateway for the vendor API call ... with an outbound HTTPS proxy and an allow-list of vendor domains" is the chapter's correct egress-discipline statement.
- **TLS framing throughout.** "TLS 1.2 or higher for all in-transit traffic, including the vendor-API call" is the right baseline.
- **PrivateLink awareness flagged as TODO.** The TODO at the VPC row (*"some address-quality vendors offer AWS PrivateLink endpoints for high-volume customers"*) correctly identifies the operational improvement available at high volume.
- **HIPAA-eligible service inventory checked.** The Prerequisites AWS Services row enumerates HIPAA-eligible services consistently with the chapter pattern.

### Finding N1: API Gateway Resource Policy and WAF Posture Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram shows the real-time API surface but the resource policy and WAF posture are not specified.
- **Problem:** Same as Recipe 5.1 Finding N1 / 5.2 Finding N1. (See Finding A8 above for the architecture-side framing of the same concern.)
- **Fix:** See Finding A8 fix. Specify private API Gateway with VPC endpoint resource policy, WAF rules for SQL injection / command injection / rate limiting, optional mTLS where SSO supports it, CloudFront-with-WAF for the patient portal if it is publicly addressable.

### Finding N2: Vendor API Egress Posture Could Be Sharpened (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row: *"NAT Gateway for the vendor API call ... with an outbound HTTPS proxy and an allow-list of vendor domains."*
- **Problem:** See Finding A9. Same chapter pattern.
- **Fix:** See Finding A9 fix. Distinct allow-lists for standardization-vendor and NCOA-vendor scoped to compute roles; per-role rate limits below vendor edge limits; CloudWatch-logged egress.

### Finding N3: Vendor PrivateLink Evaluation Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking (architecture roadmap)
- **Location:** Prerequisites VPC row TODO: *"some address-quality vendors offer AWS PrivateLink endpoints for high-volume customers."*
- **Problem:** The TODO correctly identifies the operational improvement but does not specify the volume threshold or the evaluation criteria for adopting PrivateLink. PrivateLink eliminates the NAT Gateway data-transfer cost on the vendor-egress path and improves the security posture (the egress traffic does not leave the AWS network); at moderate volumes (>1M vendor calls/month), the data-transfer savings often justify the PrivateLink fee.
- **Fix:** Add to the VPC row: *"At volumes exceeding ~1M vendor API calls/month, evaluate the vendor's PrivateLink endpoint (where available). PrivateLink eliminates NAT Gateway data-transfer cost on the vendor-egress path and keeps the traffic on the AWS network without traversing the public internet. The cost trade-off (PrivateLink endpoint hourly fee plus per-GB data-transfer fee vs NAT Gateway data-transfer fee) is institution-specific; institutions with high-volume real-time API traffic typically see net savings at the 1M-calls/month threshold."*

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by reading the file with explicit UTF-8 encoding and counting U+2014 codepoints. (An ASCII-art diagram-character earlier appeared to register as U+2013 under an encoding mismatch; the actual UTF-8 codepoint counts confirm both em-dash and en-dash counts are zero.)
- **En dash count: 0.** Verified the same way for U+2013.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services. AWS service names appear first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory.
- **CC voice consistent throughout.** The opening "you will find one of these" enumeration of address pathologies (1421 Elm St Apt 3B; the same address typed differently; the patient who mumbled the apartment number; the property description "the trailer behind the QuickStop on Route 9"; the homeless / shelter case; the address the patient moved out of three years ago) lands in the engineer-explaining-something-cool register exactly. The follow-on operational vignettes (population-health mailing campaign at 20% baseline failure rate; SDOH-derived value-based-care metric; financial-assistance program needing household linkage; HIE missing match signal on un-standardized addresses) carry the register through to the Honest Take's "treat it as infrastructure from the start" closing. Self-deprecating expertise: "the address standardization piece is largely a solved problem ... but the household-linkage piece introduces real ambiguity" is the right register for the recipe's Simple-Medium tier framing.
- **The Patel-family running example is consistent.** Carried from the Problem section ("1421 Elm St Apt 3B, Anytown, ST 12345") into the Expected Results sample standardized-address JSON (delivery_line_1: "1421 ELM ST APT 3B", last_line: "ANYTOWN ST 12345-1234") with the right address detail. The move scenario carries forward into the drift-event example (previous canonical_hash to new canonical_hash with `ncoa_match_type: "family"`).
- **Clinical / regulatory accuracy is high.** The CASS / DPV / NCOA framing is correct; the USPS Publication 28 reference is accurate (with appropriate TODO for verification at build time); the HIPAA Safe Harbor reference is correct (HIPAA Privacy Rule § 164.514 lists 18 identifiers including geographic subdivisions smaller than a state); the Address Confidentiality Program awareness in the privacy-suppression framing is correct; the No Surprises Act is not relevant to this recipe (provider directories, not address standardization) and is correctly absent.
- **The Honest Take is the recipe's most operationally pointed section.** The five traps (one-time-cleanup vs ongoing-infrastructure; under-investing in the registration-time UX; confusing co-location with relationship; equity dimension; NCOA-as-underused-tool) are the chapter's strongest individual list of failure modes for this domain. The HIPAA-Safe-Harbor closing line is the right closing.
- **The Variations and Extensions section is well-scoped.** Eleven extensions (international, privacy-preserving cross-organization household linkage, SDOH-indicator integration, address-based fraud detection, USPS Informed Delivery, address-based household-fairness auditing, active-learning-driven correction tuning, reverse-geocoding for unaddressed locations, address-confidence-aware patient matching, patient-portal address self-service, multi-source address reconciliation). Each is framed at the right grain.

### Finding V1: A Few Headers in the AWS Implementation Section Slip Toward Documentation Voice

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in "Why These Services" read as service-name-as-bullet-header:
  - *"AWS KMS, CloudTrail, CloudWatch."*
  - *"AWS Secrets Manager for the standardization-vendor API key and the NCOA-vendor credentials."*
- **Problem:** Same chapter pattern as 5.1 Finding V1 / 5.2 Finding V1. The headers are functionally correct as scannable structure for a long technical section; the deeper paragraph framing returns to the right register.
- **Fix:** Optional. The chapter editor's call.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in The Technology section's "Where Standardization Hits Its Limits" subsection and the Honest Take's HIPAA-Safe-Harbor closing paragraph stretch past 50 words.
- **Problem:** Most sentences are well-paced; a few in the privacy / regulatory paragraphs could be split. Same observation as 5.1 / 5.2 Finding V2.
- **Fix:** Optional.

### Finding V3: The Address-Pathology Opening Enumeration Is the Chapter's Strongest Single Hook on This Domain

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Problem's opening seven-example enumeration: *"You will find '1421 Elm St Apt 3B, Anytown, ST 12345.' That is the clean case. You will find '1421 ELM STREET APARTMENT 3B ANYTOWN ST 12345-1234,' which is the same address but typed differently ..."*
- **Note:** This framing earns its position. The chapter editor should consider whether a similar "you will find one of these" enumeration applies to other recipes that need to ground the reader in the messiness of real production data; for 5.3 specifically, the enumeration is the recipe's strongest single hook.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1 and chapter-pattern):** Security flags `persist_standardized_record`, `infer_household_for_address`, the real-time standardization API, the ingest path for new patient registration, the NCOA-result-processing path, and the household-lookup endpoint as needing explicit identity-boundary specification at HIGH severity. Architecture concurs because the address-as-anchor consequence (a misrouted persist call corrupts the canonical address that downstream outreach, SDOH analytics, financial assistance, the patient matcher, and the portal all consume) compounds the security concern with a methodological one. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The chapter editor should consolidate to a chapter preface in the next pass, since the same finding now applies across 4.4-5.3.**

**persist_standardized_record / infer_household atomicity (A1):** Architecture flags the sequential PutItem/PutObject/PutEvents pattern as needing `TransactWriteItems` plus an outbox pattern at HIGH severity, with the recipe's own TODO at Step 3B already naming the gap. Security concurs because half-applied state produces audit-trail inconsistency that breaks the "address store is compliance infrastructure" claim. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence. The regulatory consequence here is sharper than 5.1/5.2 because the address store feeds the financial-assistance workflow (eligibility re-determination reads household membership) and the equity-reporting pipeline (SDOH metrics depend on the address being current).**

**Cohort fairness instrumentation (A2 and chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security concurs on the privacy framing of cohort dimensions in CloudWatch (Finding S5). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The cohort-distribution stakes are higher here than in 5.1/5.2 because address-data-quality disparities directly translate to SDOH metric disparities, outreach reach disparities, and financial-assistance access disparities.**

**Monthly USPS refresh full-population pattern (A3):** Architecture flags the entire-population monthly refresh as a HIGH-severity throughput-and-cost pattern that does not match the stated cost estimate at the higher per-record vendor pricing tier. Security is silent (this is a cost / throughput concern, not a security one). Networking is silent (the egress is correct, the volume is the issue). Voice is silent. **Resolution: HIGH, attributed to Architecture. The fix is the change-driven refresh pattern; the recipe's Honest Take partially acknowledges the gap but the architecture commits to the entire-population pattern that the Honest Take labels as expensive. The architecture should commit to the change-driven pattern.**

**Audit-log retention floor (S2 and chapter-pattern):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Vendor BAA data-handling expectations (S3):** Security flags as MEDIUM. Architecture concurs because the vendor data-handling commitments (retention window, sub-processor disclosure, incident notification, audit rights) directly affect the institution's risk posture. **Resolution: MEDIUM, attributed to Security with Architecture concurrence.**

**Privacy-suppression policy audit posture (S4):** Security flags as MEDIUM with a concrete fix specifying the policy-version field on every household-membership row, the privacy-suppression-audit table, and the policy-change-as-event pattern. Architecture concurs (the policy-change-as-event pattern fits the chapter's event-driven architecture). **Resolution: MEDIUM, attributed to Security with Architecture concurrence.**

**Idempotency and DLQ coverage (A4 and chapter-pattern):** Architecture flags as MEDIUM. The recipe's own production-gaps section names the idempotency keys but the architecture does not specify them. **Resolution: MEDIUM, attributed to Architecture.**

**Real-time API latency budget and vendor failover (A5):** Architecture flags as MEDIUM. The recipe states "sub-second" but does not specify the breakdown, the timeout, the retry policy, or the fail-open vs fail-closed semantics. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration with 5.1 / 5.4 / 5.5 / 5.7 / 5.8 (A6):** Architecture flags as MEDIUM. The drift-event fan-out is shown in the architecture diagram but the contract between recipes is not specified. **Resolution: MEDIUM, attributed to Architecture.**

**Household-inference threshold re-estimation (A7 and chapter-pattern):** Architecture flags as MEDIUM. The household-inference confidence assignment is functionally a probabilistic classifier whose thresholds need re-estimation; the chapter-wide governance pattern applies. **Resolution: MEDIUM, attributed to Architecture.**

**API Gateway resource policy and WAF (A8 / N1, chapter-pattern):** Architecture and Networking flag as MEDIUM and LOW respectively; consolidating into a chapter preface is the right pattern. **Resolution: MEDIUM (per A8), attributed to Architecture with Networking concurrence.**

**Cohort PHI in CloudWatch dimensions (S5 and chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S6 and chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Patient-portal address self-service disclosure posture (S7):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Outbound vendor egress posture (A9 / N2, chapter-pattern):** Architecture and Networking flag as LOW. **Resolution: LOW, attributed to Architecture with Networking concurrence.**

**Athena access control (A10, chapter-pattern):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Backfill of existing patient address population (A11, chapter-pattern):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Cache TTL policy (A12):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Vendor PrivateLink evaluation posture (N3):** Networking flags as LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2):** Both LOW. V3 is a positive observation. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 0 critical, 4 high, 8 medium, 12 low. The 4 HIGH count exceeds the > 3 = FAIL threshold; the verdict is FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Four HIGH findings (more than 3 = FAIL per the persona rules). All four are correctness-and-compliance gaps with localized fixes; three surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose, and one (the monthly-refresh-over-full-population pattern) is a cost-and-throughput pattern the architecture should commit to the change-driven alternative for. None require structural rework of the recipe; the underlying methodology, voice, clinical accuracy, and architectural shape are excellent.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | Real-time standardization API, persist-standardized-record, infer-household, NCOA-result-processing, and drift-event paths lack identity-boundary specification |
| 2 | HIGH | Architecture | persist_standardized_record and infer_household_for_address are not atomic; sequential DynamoDB / S3 / EventBridge operations leave half-updated state on partial failure |
| 3 | HIGH | Architecture | Cohort-stratified accuracy thresholds and metric definitions referenced as "required here too" but undefined |
| 4 | HIGH | Architecture | Monthly USPS refresh iterates the entire population per cycle; cost and throughput math does not match the stated cost estimate |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 5 | MEDIUM | Security | Audit-log retention specified as "per institution's records-retention policy" without architectural floor (chapter pattern) |
| 6 | MEDIUM | Security | Vendor BAA posture named but vendor data-handling expectations are not architecturally specified |
| 7 | MEDIUM | Security | Suppress-entire-group vs exclude-suppressed policy decision is surfaced but the audit posture for the decision path is underspecified |
| 8 | MEDIUM | Architecture | Idempotency and DLQ coverage on Lambda paths underspecified (chapter-wide pattern, already partially TODO'd) |
| 9 | MEDIUM | Architecture | Real-time standardization API latency budget and vendor failover pattern not specified |
| 10 | MEDIUM | Architecture | Cross-recipe orchestration with 5.1 / 5.4 / 5.5 / 5.7 / 5.8 mentioned but not architected |
| 11 | MEDIUM | Architecture | Household-inference confidence threshold re-estimation cadence and validation gating not specified (chapter pattern) |
| 12 | MEDIUM | Architecture | API Gateway resource policy and WAF posture for the real-time API not specified (chapter pattern) |

(The Overall Assessment estimated 11 MEDIUM findings; the discussion-stage resolution settled on 8 MEDIUM and 12 LOW, with three chapter-wide patterns that the Overall Assessment had pre-counted as MEDIUM resolving to LOW after pairing with their architecture-side counterparts: the vendor egress posture (A9 / N2), the cohort PHI in CloudWatch dimensions (S5), and the cache TTL policy (A12). The total finding count is unchanged at 24; the breakdown by severity is 0 CRITICAL, 4 HIGH, 8 MEDIUM, 12 LOW.)

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 14 | LOW | Security | Cohort PHI in CloudWatch metric dimensions (chapter-wide pattern) |
| 15 | LOW | Security | IAM "Never `*` actions or `*` resources in production" stated without scoped ARN examples (chapter-wide pattern) |
| 16 | LOW | Security | Patient-portal address self-service disclosure posture not addressed |
| 17 | LOW | Architecture | Outbound vendor API egress posture could be sharpened (chapter pattern, paired with N2) |
| 18 | LOW | Architecture | Athena access control on audit and curated S3 zones not specified (chapter pattern) |
| 19 | LOW | Architecture | Backfill of the existing patient address population mentioned but not architected (chapter pattern) |
| 20 | LOW | Architecture | Cache TTL policy not specified |
| 21 | LOW | Networking | API Gateway resource policy and WAF posture not specified (chapter-wide pattern, paired with A8) |
| 22 | LOW | Networking | Vendor API egress posture could be sharpened (chapter-wide pattern, paired with A9) |
| 23 | LOW | Networking | Vendor PrivateLink evaluation posture not specified |
| 24 | LOW | Voice | A few headers in the AWS Implementation section slip toward documentation voice |
| 25 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 4 HIGH findings before publication.** Each has a localized fix:
   - Finding S1 (identity-boundary): pseudocode additions in the real-time-standardization API, `persist_standardized_record`, `infer_household_for_address`, the NCOA-result-processing path, and the household-lookup read path. Reference language is partially present in the chapter pattern from 4.4-5.2. Estimated effort: half a day.
   - Finding A1 (atomicity): pseudocode rewrite of Steps 3 and 4 to use `TransactWriteItems` for the DynamoDB writes plus an outbox pattern for the S3 archive, EventBridge emit, and household-inference invocation side effects. The architecture prose addition specifies the partial-failure recovery semantics. The recipe's own TODO at Step 3B names the gap; the fix is to architect what the TODO references. Estimated effort: half a day.
   - Finding A2 (cohort fairness threshold): threshold-and-metric specification in pseudocode and architecture-prose paragraph. Reference language is present in the cohort-stratified accuracy paragraph and inherited from 5.1/5.2. Estimated effort: half a day.
   - Finding A3 (full-population monthly refresh): architecture-prose addition and Step 5 pseudocode rewrite to use the change-driven refresh pattern based on the USPS reference-data change manifest plus cache-TTL expiry. Cost Estimate row updated to reflect the change-driven throughput. Estimated effort: 1 day.

   Total: 2.5 days of writing time.

2. **Address the recipe-specific MEDIUM findings (S4 privacy-suppression audit posture, A5 latency budget, A7 threshold re-estimation, S3 vendor BAA expectations).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1-2 days of writing time.

3. **Address the chapter-wide MEDIUM findings (S2 audit retention, A4 idempotency, A6 cross-recipe orchestration, A8 / N1 API Gateway resource policy).** These are already TODO'd or chapter-pattern; consolidating into a chapter preface in the next pass is acceptable.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N1, N2, N3) are explicit-statement additions; the chapter-pattern findings (S5, S6, S7, A9, A10, A11) are consolidation work; A12 is a small inline annotation.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 5.3 is the third Simple-tier recipe in Chapter 5 and the one that introduces the recipe-specific concepts (CASS-conformant standardization, the six-status outcome classification, the building-type-aware household-inference layer, the graded household-confidence contract, the NCOA-driven mover detection) that justify a separate chapter from 5.1 and 5.2. The quality bar inherits from 5.1 and 5.2 and the recipe's own claim that "you can ship the address-standardization layer in weeks" earns the architectural specification needing to be at the level the recipe text claims.

The recipe's underlying methodology, voice, clinical accuracy, and architectural shape are excellent. The opening address-pathology enumeration, the CASS / DPV / NCOA framing, the six-status outcome classification, the graded household-confidence contract, the privacy-suppression-as-first-class-case framing, the cohort-stratified-accuracy-monitoring rigor, and the HIPAA-Safe-Harbor closing line are all chapter-strength contributions. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses (Findings S1, A1, A2) plus one cost-and-throughput pattern that the Honest Take partially acknowledges but the architecture commits to in the wrong direction (Finding A3). Closing the gaps brings the architecture up to the standard the recipe text claims and makes the address-and-household substrate that 5.1, 5.4, 5.5, 5.7, 5.8, and the outreach / SDOH / financial-assistance pipelines depend on as solid as the recipe text promises it is.
