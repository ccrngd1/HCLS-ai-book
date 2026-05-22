# Expert Review: Recipe 5.1 - Internal Duplicate Patient Detection

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-22
**Recipe file:** `chapter05.01-internal-duplicate-patient-detection.md`

---

## Overall Assessment

This is the foundation recipe for Chapter 5 and the recipe that the chapter explicitly tells the reader to read first. The Maria Garcia opening is the chapter's strongest hook by a clear margin: three registrations across 2018, 2021, and last month, slight name variations (no middle initial, then a married hyphenated form), DOB format drift (03/14/1972 then 3-14-72 then March 14 1972), a phone-number change, an SSN that was sometimes captured and sometimes not. The clinician pulls up the 2021 chart at this week's acute visit, misses the medication started by primary care last month, prescribes something that interacts, and Maria has a moderate adverse reaction. The framing earns the reader's attention because it is neither hypothetical nor exotic; this is the canonical wrong-patient scenario that every HIM team has stories about. The "this is what duplicate patient records do. They are not, as the IT department sometimes tries to frame it, a data quality nuisance. They are a patient safety hazard with documented clinical consequences" pivot is the right framing, with appropriately-flagged Joint Commission and ECRI references that the chapter editor will need to verify against the most current reports.

The Technology section is the chapter's clearest articulation of the entity-resolution-fundamentals canon: stating the problem plainly (it looks like a join, it is not a join, and here is why), the scaling-wall argument that motivates blocking, the multiple-blocking-passes pattern that is the central engineering decision, the string-similarity zoo (Jaro-Winkler, Damerau-Levenshtein, edit distance, soundex, double metaphone, n-gram overlap) with explicit framing of which one is appropriate for which field, and the Fellegi-Sunter probabilistic-linkage framework with the m and u probabilities, the EM-based estimation, and the interpretability argument that has kept it in production for fifty years. The three-bucket output (auto-match, auto-non-match, human review) with the explicit framing that "the review queue is the product, often more than the score is" is the chapter's most operationally honest single sentence about the discipline. The survivorship-rules subsection ("the unglamorous half of duplicate detection that most write-ups skip") is the right place to put the clinical-history-merging discussion: which name wins, which address wins, which medication list wins, when to combine rather than overwrite, when to surface to manual review. The reversibility framing ("you cannot bolt this on later") is the chapter's most pointed articulation of why the audit substrate has to be designed in from day one. The "Where the Field Has Moved" subsection (open-source tooling maturity, commercial EMPI vendor patterns, embeddings as an enhancement layer, bias monitoring as standard practice) honestly characterizes where the field is and is not.

The five-stage architecture (ingest and normalize, blocking and candidate generation, score, route by threshold, persist with audit) is the right shape for the problem, with the right operational discipline framed in prose: "ingest and normalize is where most of the recall comes from"; "blocking is the recall-vs-cost knob"; "scoring is the core that everything else hangs from"; "the review queue is the operational core"; "audit and reversibility are baked in, not added later"; "cohort-stratified accuracy monitoring is part of the system, not an afterthought." The AWS Implementation section's service selection (S3, DynamoDB, OpenSearch, Glue, Athena, Step Functions, Lambda, Kinesis, EventBridge, API Gateway, Cognito, QuickSight) maps cleanly to the architecture stages with the right rationale on each. The split between the batch-matching pipeline (Glue with Splink on Spark, nightly) and the real-time matching pipeline (Lambda + OpenSearch + Step Functions, on every new registration) is the correct operational pattern; each workload runs on the right substrate.

The Honest Take is the chapter's most operationally pointed. Five observations stand out: (1) "the trap most specific to this domain is treating it as a one-time cleanup project rather than as ongoing operational work" with the canonical contractor-summer-cleanup failure mode diagnosed precisely; (2) "under-investing in the review queue UX and the HIM team that staffs it" framed as the chapter-specific engineering anti-pattern, with the "the review queue is not a sidebar; it is the product" closing; (3) the conservative-thresholds discipline tied directly to the patient-safety asymmetry, with the explicit instruction that "the right answer is almost always to staff the review queue at the level the threshold demands rather than to lower the threshold to fit available staffing"; (4) survivorship rules elevated above the ML and the LLM as the harder cross-functional work; (5) the equity dimension framed as non-optional ("this is not optional in 2026; it is the standard") with the canonical Hispanic-surnames / Asian-name-order / Arabic-transliteration patterns that off-the-shelf systems handle worse. The closing "duplicate patient records are a problem that has been 'solved' in the academic literature for thirty years and is still unsolved in production at most healthcare organizations. The gap is not a methods gap. It is an alignment-and-operations gap" is the chapter's strongest single line.

That said, four correctness gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items. (1) The architecture invokes a real-time matching API path (the registration event flows through Kinesis to a normalize Lambda to candidate-generation against OpenSearch to scoring to routing) and a review-queue API path (API Gateway + Cognito + Lambda for the HIM review UI), but the identity-boundary checks on these paths and on the merge / unmerge operations are not specified at the architectural level. Who can call apply_merge? Who can call unmerge? What proves the calling identity is allowed to act on this patient's records? The recipe's own framing that "the audit log is highly sensitive: it contains every patient-identification decision the system has made" and the production-gaps "audit-log access control" paragraph imply tighter-than-default controls but the architecture does not specify them. (2) The merge pseudocode performs sequential `DynamoDB.PutItem` and `DynamoDB.UpdateItem` calls without `TransactWriteItems`. A failure between steps 5E (write merged master) and step 5G (emit merge event) leaves the MPI in an inconsistent state: deprecated cluster still active, no merged master, cross-references still pointing at the deprecated mpi_id, no audit trail of the attempt. The Python code review (Finding 5) documents the implementation collapse; the architecture should specify the atomic-write pattern, not defer it to production-gaps. The recipe's own "Why This Isn't Production-Ready" section names this gap; it should be in the architecture. (3) The cohort-stratified accuracy monitoring is repeatedly invoked as "non-negotiable" and "first-class concern, not a bolt-on," but the operational threshold values, the per-axis aggregation, the chronic-suppression-as-fairness-signal pattern, and the disparity-metric definitions are not specified. The Hispanic-surname cohort the recipe explicitly cites as match-rate-disparate depends on these thresholds being calibrated; leaving them implementation-defined silences the alert that catches the disparate-impact case. Same gap as Recipe 4.8 Finding A4 and Recipe 4.9 Finding A2; sharper here because patient matching is the substrate every other Chapter 5 recipe builds on, so a fairness gap in 5.1 propagates to every downstream recipe. (4) The "do not merge" flag for safety-sensitive patient populations is not addressed. Domestic violence survivors with name-change orders, witness-protection enrollees, adopted children with sealed biological-parent records, and gender-transition patients with separated pre-and-post-transition identities all have explicit, legally-enforced requirements that records remain unlinked or selectively-linked. Without an architectural primitive for "this pair must never auto-merge, must never be surfaced to the standard review queue, and must be routed to the privacy office's restricted-review track," the matcher will eventually re-link records that the institution explicitly intended to keep separate. This is a clinical-safety and legal-compliance gap, not an edge case. The recipe text mentions "intentional name changes" once in the reviewer-training paragraph; the architecture is silent.

Eleven chapter-wide patterns repeat (tracking-ID privacy, IAM ARN scoping, `0.0.0.0/0` egress, audit-log retention specification, SDOH cohort PHI promotion, identity-boundary checks, governance SLA on M/U re-estimation, cross-recipe orchestration with later Chapter 5 recipes, DLQ coverage on real-time pipeline, OpenSearch availability fallback, real-time latency budget). Several are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by grep on U+2014). En dash count: 0 (verified by grep on U+2013). 70/30 vendor balance is maintained; AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: "this is what duplicate patient records do. They are not, as the IT department sometimes tries to frame it, a data quality nuisance" lands the engineer-explaining-something-cool register exactly. Parenthetical asides ("which, for 'John Smith,' should not surprise anyone") are placed well. The Maria Garcia named-patient example is preserved across the Problem, the Expected Results sample candidate-pair JSON, and the Variations section. The "John Smith with no DOB and no SSN" failure-mode example, the twin-and-family-confounding paragraph, the pediatric-and-frequent-mover paragraph, and the recently-merged-system paragraph are the chapter's most operationally specific failure-mode catalog. The Variations and Extensions section (active-learning gold-set construction, per-cohort m/u models, embedding-augmented similarity, graph-based clustering, streaming continuous matching, privacy-preserving extension to 5.8, risk-tier-aware thresholding, continuous comparator updating from review feedback, patient-facing self-service) is well-scoped and frames each extension as "what you'd build at higher sophistication levels."

Priority breakdown: 0 critical, 4 high, 11 medium, 6 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. The four HIGH findings are correctness gaps with localized fixes; most surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with HIPAA-eligibility framing for every named service (S3, DynamoDB, OpenSearch, Glue, Athena, Step Functions, Lambda, Kinesis, EventBridge, API Gateway, Cognito, QuickSight, KMS). Continues the chapter pattern of treating HIPAA eligibility as a per-service question rather than a blanket statement.
- Customer-managed KMS keys for every PHI store with the explicit framing of `mpi-master` and `mpi-xref` as "highly sensitive" and the audit-archive S3 buckets as forensic-grade. The "every read of MPI data is a PHI access and needs to be audited" framing under CloudTrail is the recipe-specific sharpening that distinguishes 5.1 from earlier recipes: the MPI is not just clinical-record-adjacent; the MPI assignment is itself the identifying decision that downstream clinical records anchor to, so a wrong read or write has clinical-record-equivalent blast radius.
- CloudTrail data events on the `mpi-master`, `mpi-xref`, and `review-queue` tables, on the S3 buckets containing patient records / normalized records / candidate pairs / audit archives, and at the API Gateway and Lambda layers for the review-queue API. The "every read of MPI data is a PHI access and needs to be audited" framing is correctly the most aggressive audit posture in any recipe to date.
- Audit-archive partitioning by date and routing decision is the right shape for forensic-grade traceability: a future investigation can trace exactly what the system saw, including the auto-non-match cases that are otherwise invisible. The "every pair the system considered is preserved with its scores, regardless of routing decision" framing under the S3 paragraph is the right discipline.
- The encryption-in-transit posture is uniform: TLS for OpenSearch, KMS-encrypted indices, TLS in transit for the API surface, server-side encryption for Kinesis and EventBridge. Fine-grained access control on OpenSearch indices is named explicitly.
- Synthetic-data labeling is enforced in the Prerequisites Sample Data row: "Never use real PHI in development environments; the synthetic data is the development substrate, the real data only enters production." Synthea-derived patient panels with deduplication labels are correctly framed as the canonical starting point.
- The deploy-time guardrail on validating the SSN pattern (rejecting 000-00-0000, 999-99-9999, sequential digits) is a defensive-coding pattern that prevents the matcher from treating fake-SSN entries as matching evidence. The Python code review's positive note that this is implemented carries forward into the architectural prose.
- Patient identity history is preserved in `previous_mpi_id_history` on `mpi-xref`, which is the substrate that supports unmerge. The recipe text correctly frames this as load-bearing for reversibility.

### Finding S1: Real-Time Matching API and Merge / Unmerge Operations Lack Identity-Boundary Specification

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization, regulatory)
- **Location:** Architecture diagram shows `Real-Time Matching` flow `KS1 (Kinesis) -> L1 (normalize-record) -> L2 (candidate-generator) -> L3 (pair-scorer) -> L4 (threshold-router) -> L5 (apply-merge)`; review-queue surface as `D1 (review-queue) -> AG1 (API Gateway) -> CG1 (Cognito) -> UI1 (HIM Review UI) -> AG1 -> L6 (review-decision) -> L5 (apply-merge)`. Step 5 pseudocode `apply_merge(record_a, record_b, decision_metadata)` and `unmerge(merge_id, reason, operator_id)`.
- **Problem:** The recipe specifies the matching pipeline at flow-and-service granularity but is silent on the identity-boundary policy that controls who can invoke each path and what proves the caller is authorized to act on a particular patient. The chapter pattern from Recipe 4.4 through 4.10 has converged on a structured identity-boundary specification including the rejection semantics, the metric emission, and the log-on-violation pattern. Recipe 5.1 is the chapter pattern's foundational recipe and inherits a sharper version of the concern because the artifact being mutated is the master patient identity itself:

  1. **The real-time matching path's authentication context is unspecified.** A registration event flowing through Kinesis to the normalize Lambda triggers candidate generation, scoring, threshold routing, and (for auto-match scores) merge application. The Kinesis stream's producer authentication (the registration system's role identity), the per-event integrity-check (a forged registration event with a real patient_id but attacker-controlled demographics could trigger a wrong merge), and the consumer-side validation (the normalize Lambda's input validation against a JSON schema, the registration-system signature verification) are not specified. A misrouted or injected registration event would silently produce a candidate-set against the existing index, score against another patient's record, and (above the threshold) auto-merge the records. The auto-match path runs without any human in the loop above the threshold; the integrity of the inbound stream is the only safeguard against a wrong-patient merge from a forged event.

  2. **The review-queue API's authentication context is named but the authorization context is not.** Cognito authenticates HIM team members (or the institution's IdP via SAML/OIDC); Cognito is identity, not authorization. The architecture should specify what the API Gateway / Lambda / DynamoDB layer enforces on top of the authenticated session: which HIM specialist can review which queue, whether reviewers can see queues for clinical areas they do not own, whether reviewers can review pairs they have a personal relationship to (the reviewer is a relative of one of the patients in the pair, the reviewer is themselves the patient in the pair). The "audit posture for review actions" prose is correct in spirit but the policy needs to be architected.

  3. **`apply_merge` is the chapter's most security-sensitive write path.** It mutates the master patient identity table, which is the anchor for all downstream clinical-record linkage. A misrouted apply_merge call (an authorization-bypass attempt, a system-emitted event for the wrong patient, an attacker-controlled `decision_metadata` field claiming a high score that was not actually computed) silently links two patients' clinical histories under a single MPI identity. The downstream blast radius is every system that consumes the merge event: the EHR (chart linkage), the data warehouse (analytics deduplication), the patient communication system (the next outreach goes to the wrong patient), the billing system (account reconciliation across the merged identity). The "even auto-match should produce an audit trail and a reversibility path" framing in the Three-Bucket Output subsection is correct; the architecture should specify the authentication and authorization context of every apply_merge invocation, including which Lambda role can call it, which event sources are accepted, and which payload fields are signed by the originating system.

  4. **`unmerge` has no specified authorization model at all.** The function takes `(merge_id, reason, operator_id)` and restores pre-merge state. Anyone with the function-execution permission can unmerge any merge. In a healthcare context, the unmerge operation is itself a regulated clinical-data action: the records being un-linked may contain laboratory results, medication orders, or notes that were entered while the records were merged, and unmerging must decide which side gets which entries. The recipe's reversibility prose correctly frames the data structures that support unmerge, but the policy framework for who can authorize an unmerge, what evidence is required, and how the unmerge is reviewed is silent. Without specification, the unmerge action becomes either too easy (any HIM specialist with table-write access can unmerge) or de-facto unavailable (the function is gated behind a role nobody has, so wrong merges accumulate). Both failure modes break the recipe's "you need to be able to back out a wrong merge cleanly" claim.

  5. **The Cures Act CDS exemption argument and the HIPAA Privacy Rule's minimum-necessary requirement both depend on the identity boundary.** A reviewer who can access any patient's pair without a treatment-relationship-or-investigation-purpose check exceeds minimum-necessary; an apply_merge call that succeeds without proving the calling event came from an authenticated registration source does not have the audit-trail attribution that compliance requires. Same regulatory ground as Recipe 4.8 Finding S1, 4.9 Finding S1, 4.10 Finding S1; the chapter editor should consolidate identity-check guidance into a chapter preface and reference it from each recipe.

- **Fix:** Specify the identity-boundary policy and the rejection semantics at the architectural level the chapter has converged on. For the real-time-matching path, specify in the Kinesis-and-normalize-Lambda paragraph:

  ```
  // The registration-events Kinesis stream accepts producers with the
  // role arn:aws:iam::<account>:role/registration-source-<env>. Each
  // event carries a producer-signed envelope: {source_system,
  // source_record_id, event_id, signed_payload}. The normalize
  // Lambda validates the signature against the producer's known
  // signing key (rotated per the institutional secret-rotation
  // policy), validates the source_system is in the allowed-list,
  // validates the event_id is unique within a sliding window
  // (idempotency), and rejects events that fail any of these checks
  // with a logged metric and a routing to the rejected-events DLQ.
  ```

  For `apply_merge`, specify the authorization context:

  ```
  FUNCTION apply_merge(record_a, record_b, decision_metadata):
      // decision_metadata.invocation_source is one of:
      //   "auto_match_pipeline": invoked by the threshold-router
      //                          Lambda for an auto-match score
      //   "review_queue_decision": invoked by the review-decision
      //                            Lambda for a human-reviewed match
      //   "backfill_pipeline": invoked by the batch Glue job during
      //                        historical backfill
      //
      // Validate the caller's role matches the invocation_source:
      caller_role = current_lambda_execution_role()
      IF NOT caller_role_matches_invocation_source(caller_role,
                                                     decision_metadata.invocation_source):
          LOG("apply_merge invocation_source mismatch",
              caller = caller_role,
              source = decision_metadata.invocation_source)
          emit_metric("apply_merge_authorization_violation", value = 1)
          REJECT
      // For review_queue_decision, validate that the named reviewer
      // had an assigned queue containing the pair, and that the
      // reviewer is not in the conflict-of-interest list (which
      // includes self-merges and family-member pairs the reviewer
      // is part of).
      IF decision_metadata.invocation_source == "review_queue_decision":
          IF NOT reviewer_authorized_for_pair(decision_metadata.reviewer_id,
                                                record_a.source_record_id,
                                                record_b.source_record_id):
              LOG("reviewer not authorized for pair", ...)
              emit_metric("review_decision_authorization_violation", ...)
              REJECT
  ```

  For `unmerge`, specify the policy framework:

  ```
  FUNCTION unmerge(merge_id, reason, operator_id):
      // Unmerge is a privileged operation. The operator must hold
      // the unmerge-authorized role; the reason must be one of an
      // institution-defined set (wrong_match_clinical_review,
      // patient_self_report, audit_finding, legal_directive); a
      // second-operator approval is required for unmerges affecting
      // records with associated medication orders or recent
      // clinical notes. The unmerge operation routes to the
      // privacy-office review track if the affected records are in
      // the no-link cohort (Finding A4).
      audit_record = lookup_audit_record(merge_id)
      IF audit_record is null:
          REJECT
      IF NOT operator_in_unmerge_role(operator_id):
          LOG("unmerge by unauthorized operator", ...)
          REJECT
      IF NOT reason_in_allowed_set(reason):
          REJECT
      IF requires_second_approval(audit_record):
          IF NOT second_approval_present(merge_id):
              ENQUEUE for second-approval review
              RETURN { status: "pending_second_approval" }
      ...
  ```

  Reference Recipe 4.4 Finding S1, 4.5 Finding S1, 4.6 Finding S1, 4.7 Finding S1, 4.8 Finding S1, 4.9 Finding S1, 4.10 Finding S1 as the chapter-wide pattern. For 5.1 specifically, the unmerge-as-clinical-action posture and the master-patient-identity-as-anchor consequence earn the HIGH severity rather than the MEDIUM of earlier recipes.

### Finding S2: Audit-Log Retention Policy Specified as "Per Institution's Records-Retention Policy" Without Architectural Floor

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, audit, forensic)
- **Location:** Prerequisites CloudTrail row: *"CloudTrail logs themselves are encrypted with KMS and retained per the institution's records-retention policy."* And the Audit and Reversibility paragraph: *"The audit log is queryable, immutable, and retained per the institution's records-retention policy (which for clinical records is typically several years to decades, depending on jurisdiction)."*
- **Problem:** Specifying audit retention as "per the institution's records-retention policy" is correct in spirit but defers the architectural floor to whoever ships the system. Three concrete consequences:

  1. **The clinical-record-equivalent posture is named in prose but not enforced architecturally.** The recipe correctly frames the MPI audit log as forensic-grade and approaching clinical-record audit standards. Clinical-record retention floors are typically 7-10 years for adult records and "until age of majority + 7-10 years" for pediatric records under state-specific medical-records retention statutes; under HIPAA, the Privacy Rule's 6-year minimum applies to certain documents but does not set the medical-record floor. The architecture should specify the minimum floor as the longer of (HIPAA 6-year floor, the institution's medical-record retention policy, the state-specific medical-record retention floor, the state-specific minor-records floor for pediatric patients) and call out that the institution's policy can extend but not shorten this.
  2. **The S3 Object Lock / Glacier-tier transition policy is not specified.** The audit substrate is supposed to be "immutable" per the recipe text; immutability requires S3 Object Lock with Compliance mode (or Governance mode with stricter controls). Without architectural specification, the implementation may use Standard storage with versioning, which is mutable by privileged users.
  3. **The CloudTrail data event volume can be substantial.** Every read of `mpi-master`, `mpi-xref`, and `review-queue` produces a data event; for a 500K-patient system with the recipe's stated cost estimate, this is potentially millions of CloudTrail events per month. The retention policy interacts with the CloudTrail-S3 cost model; the cost estimate ($50-200/month for S3) may be undercounted if the audit volume is large. The architecture should specify whether CloudTrail data events go to a dedicated audit account (the well-architected pattern) or to the same account.

- **Fix:** Replace the "per the institution's records-retention policy" framing with an explicit floor in the CloudTrail and Audit paragraphs:

  *"Audit-log retention is the longer of: 7 years (clinical-record minimum floor), the institution's documented medical-record retention policy, the state-specific medical-record retention statute, and the state-specific minor-records floor for pediatric patient records. Audit logs are stored in a dedicated S3 bucket with Object Lock in Compliance mode for immutability and a lifecycle policy that transitions to S3 Glacier Deep Archive after 90 days for cost optimization. CloudTrail data events are forwarded to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. The retention floor is enforced at the bucket-policy and Object-Lock-configuration level, not at application logic."*

  Reference HIPAA 45 CFR § 164.530(j) for the 6-year administrative-record minimum and the state-specific clinical-record retention statutes for the longer floor.

### Finding S3: SDOH-Cohort and Demographic-Cohort PHI Exposure Through CloudWatch Metric Dimensions (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Cost estimate and architecture paragraphs naming "Compute and report match rate, false-positive rate, and review queue depth by demographic cohort (race, ethnicity, language, age band, geographic region, primary-language)." Implicit in the equity-instrumentation discussion.
- **Problem:** Same chapter-wide pattern as Recipe 4.4 Finding 13 / 4.10 Finding S4. CloudWatch metric dimensions cannot exceed 30 characters per dimension name and cannot be removed once published; emitting raw cohort attributes (race, ethnicity, language) as metric dimensions is both a cost concern (metric cardinality explosion) and a privacy concern (the metric stream is queryable by any role with `cloudwatch:GetMetricData`, which is a wider audience than the audit log).
- **Fix:** Specify in the CloudWatch paragraph: *"Cohort dimensions on CloudWatch metrics use the bucketed, non-reversible cohort labels from the institutional cohort registry (e.g., `cohort_race_eth_bucket = A`, `B`, `C`, `D`, `E`, `unknown`) rather than raw demographic attributes. The cohort-label-to-attribute mapping is stored in a separate, access-controlled table and is loaded at dashboard-render time only by roles authorized for cohort interpretation."*

  Reference Recipe 4.4-4.10 chapter pattern.

### Finding S4: IAM "Never `*` Actions or `*` Resources in Production" Stated Without Scoped ARN Examples (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row, with the TODO comment: *"pair these with one or two scoped Resource ARN examples mirroring the chapter-wide pattern."*
- **Problem:** Same finding as Recipe 4.1-4.10. Already TODO'd.
- **Fix:** Inline scoped ARN examples for the highest-stakes actions: `dynamodb:UpdateItem` on `arn:aws:dynamodb:<region>:<account>:table/mpi-master` and `arn:aws:dynamodb:<region>:<account>:table/mpi-xref`; `s3:PutObject` on `arn:aws:s3:::<env>-mpi-audit-archive/audit/*`; `es:ESHttpPost` on the OpenSearch domain ARN with index-level path scoping; `kinesis:PutRecord` and `kinesis:GetRecords` scoped to the registration-events stream ARN. Or consolidate into the chapter preface.

### Finding S5: Cohort Re-Identification Risk in Similar-Trajectory Retrieval Not Addressed (Forward-Looking Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Variations and Extensions section: *"Patient-facing identity self-service. A portal feature that lets patients see (and request corrections to) the demographic data the institution has on file for them."*
- **Problem:** The patient-facing self-service variation surfaces the institution's stored demographic data to the authenticated patient. The variation is correctly framed as "downstream-of-matching" but inherits the privacy concern that what the institution has on file may include data the patient did not provide and does not know is held (insurance-derived addresses, demographic data from prior employer-sponsored panels, demographic data inferred from claim feeds). Surfacing this data may itself be a disclosure event under state law. The variation should name the disclosure-policy gate as a prerequisite to the self-service feature.
- **Fix:** Add a sentence to the Patient-Facing Self-Service variation: *"Before surfacing stored demographic data to the patient, the institution should review the data-disclosure policy: data sourced from the patient (registration self-attestation, portal submissions) is appropriate to display; data sourced from third-party feeds (insurance, claims, partner-organization shares) may have separate disclosure-and-consent requirements that the policy framework needs to address before the self-service feature surfaces it."*

---

## Architecture Expert Review

### What's Done Well

- The five-stage architecture (ingest and normalize, blocking and candidate generation, score, route by threshold, persist with audit) is the right shape for the problem. The dual-pipeline pattern (Glue + Splink for batch nightly refresh; Lambda + OpenSearch for real-time at registration) is the correct workload-split: each substrate is optimized for its access pattern. The recipe's framing of "blocking is the recall-vs-cost knob" and "scoring is the core that everything else hangs from" earns its position.
- The five-blocking-pass starting set is well-chosen: pass 1 (last_name_metaphone + dob_year), pass 2 (first_name_metaphone + last_initial + dob_year), pass 3 (last_name_initial + dob_full), pass 4 (zip_code + last_name_initial), pass 5 (phone_last_4 + dob_year). Each pass is paired with a stated failure mode it catches (last-name change for marriage / divorce, name spelling variations via metaphone, DOB data-quality issues, name-but-stable-phone). The recipe text correctly notes "add more passes as needed based on recall measurement against the labeled gold set."
- The Splink-on-Glue-with-Spark choice is the right production-scale primitive for the batch matcher. Splink runs natively on Spark, supports the Fellegi-Sunter framework with EM-based parameter estimation, produces interpretable Fellegi-Sunter outputs, and has documented healthcare deployments. The recipe correctly flags "confirm Splink's current Glue/Spark compatibility and the recommended integration pattern at time of build" as a TODO; alternatives (recordlinkage on EMR, dedupe.io) are correctly named.
- The OpenSearch-backed real-time candidate index is the right substrate for sub-second registration-time matching. The recipe text names the production discipline: "in-memory blocking key indices for the most common access patterns, OpenSearch query optimization, candidate-set capping (return at most N candidates per blocking pass), and asynchronous follow-up scoring for borderline cases that did not resolve in time." The asynchronous-follow-up pattern is the right answer for "the registration desk cannot wait fifteen seconds for the result."
- The DynamoDB schema is well-designed for the access patterns: `mpi-master` keyed on `mpi_id` for resolved-identity lookups; `mpi-xref` keyed on `(source_system, source_record_id)` for "which mpi_id does this source record map to right now?" with a GSI on `mpi_id` for cluster-membership queries; `review-queue` keyed on `(queue_id, candidate_pair_id)` for queue-by-area assignment. The on-demand capacity choice handles the bursty review-queue write pattern without capacity-planning headaches.
- The three-bucket routing (auto-match, auto-non-match, review) is faithful to the entity-resolution canon. The conservative-thresholds discipline tied directly to the patient-safety asymmetry ("favor false splits over false merges because the patient safety asymmetry is real") is the chapter's most operationally pointed framing of why thresholds are clinical-leadership decisions, not engineering constants.
- Survivorship rules are explicitly named as cross-functional decisions ("HIM and clinical informatics involvement"), with five canonical rule patterns (most recent, most trusted source, longest non-null, combine rather than overwrite, manual review for sensitive fields). The "wrong survivorship rules can lose clinically significant data even when the match itself was correct" framing is correct and operationally specific.
- Reversibility is architected, not bolted on. Audit records carry `pre_merge_master_a`, `pre_merge_master_b`, `source_records_in_merge` with `previous_mpi_id_history`, the survivorship_decisions, and the decision_metadata. The pseudocode `unmerge` function uses these structures to restore pre-merge state. The "you cannot bolt this on later" framing is correct.
- The cohort-stratified accuracy monitoring is explicitly framed as "first-class concern, not a bolt-on" with the Obermeyer-canonical-pattern reference correctly drawn ("Recipe 5.1, monitor cohort-stratified match rates and false-positive rates as a first-class concern"). The Variations and Extensions section's per-cohort m/u models, the Hispanic-surname / Asian-name-order / Arabic-transliteration patterns, and the equity-instrumentation framing collectively make the recipe's stance on equity unambiguous.
- The "Why This Isn't Production-Ready" section is the chapter's most thorough at this stage of the chapter pattern, with twelve named gaps spanning threshold tuning, M/U re-estimation, survivorship rule design, review-queue UX, real-time latency, cross-system reconciliation, identity-fraud detection, registration-desk feedback, equity tuning, idempotency, audit access control, backfill strategy. The breadth honestly tells the reader how much sits between the recipe and a production deployment.

### Finding A1: Merge Operation Is Not Atomic; Sequential `PutItem` and `UpdateItem` Calls Leave Half-Updated State on Partial Failure

- **Severity:** HIGH
- **Expert:** Architecture (correctness, data-integrity, the recipe's reversibility-and-audit promise)
- **Location:** Step 5 pseudocode `apply_merge`, the master-and-xref-write block:
  ```
  // Step 5E: persist the merged master and update all cross-
  // references in the deprecated cluster to point to the survivor.
  DynamoDB.PutItem("mpi-master", merged_master)
  FOR each member in cluster_a_members + cluster_b_members:
      DynamoDB.UpdateItem("mpi-xref", ...)
  IF surviving_mpi_id == master_a.mpi_id:
      DynamoDB.UpdateItem("mpi-master", ...)
  ELSE:
      DynamoDB.UpdateItem("mpi-master", ...)
  ```
- **Problem:** The pseudocode performs four-to-many sequential DynamoDB calls without a `TransactWriteItems` wrapper. A failure between step 5E (write merged master) and step 5G (emit merge event) leaves the MPI in an inconsistent state. Concrete failure modes:

  1. **Failure after the merged-master write but before the xref updates:** the merged master record exists, but the cross-references still point at the deprecated mpi_ids. A subsequent `(source_system, source_record_id) -> mpi_id` lookup for any of the source records returns the deprecated mpi_id, and downstream consumers (EHR chart linkage, billing) keep treating the records as separate patients despite the merge having "happened" at the master level.

  2. **Failure mid-loop on the xref updates:** some cross-references point at the surviving mpi_id, others still point at the deprecated mpi_ids. The MPI is internally inconsistent: a single patient's clinical-record cross-references span two mpi_ids depending on which source-record was queried. The query path for "all records belonging to this patient" returns a partial cluster.

  3. **Failure after xref updates but before the deprecated-master tombstone:** the deprecated master is still marked `active`, the xrefs point to the survivor, and a future merge operation that consults the deprecated master sees an active-but-empty cluster (no xrefs left). The merge logic's three-case enumeration ("both records already point to the same mpi_id, both records point to different mpi_ids, at least one record has no mpi_id yet") is broken because the case detection relies on consistent xref state.

  4. **Failure after the master-and-xref state is consistent but before the audit-archive write:** the merge happened, the data is internally consistent, but no audit trail of the decision was created. The reversibility promise depends on the audit record being present; a half-written merge with no audit record is a wrong merge that cannot be unmerged.

  5. **Failure after the audit-archive write but before the EventBridge merge event emit:** the merge happened, the audit trail is recorded, but downstream consumers (EHR chart linkage, data warehouse, patient outreach, billing) never learn about it. The recipe's "the merged record is what downstream systems consume" framing breaks: the master is updated, the consumers do not know.

  The Python code review's Finding 5 documents the implementation collapse (the master `PutItem` is unwrapped, a failure aborts before the xref updates). The architectural pseudocode has the same collapse. The recipe's "Why This Isn't Production-Ready" section briefly mentions "Build this from day one" for cross-system reconciliation but does not name `TransactWriteItems` or the atomic-write pattern. The Honest Take frames reversibility as non-negotiable; reversibility requires the merge state to be either fully present or fully absent, not partially-applied.

- **Fix:** Specify `TransactWriteItems` (or an equivalent atomic-write primitive) in the pseudocode and the architecture. DynamoDB `TransactWriteItems` supports up to 100 items per transaction; a typical merge involves 1 master `Put`, 1-2 master `Update`s for the deprecated tombstone, and N xref `Update`s where N is the cluster size. Most clusters are small enough to fit; large clusters need to be split into a "stage the change" + "commit the change" pattern using a separate `merge-staging` table:

  ```
  // Step 5E: atomic write of the merge.
  IF len(cluster_a_members) + len(cluster_b_members) <= 95:
      // single transaction; fits in TransactWriteItems' 100-item cap
      DynamoDB.TransactWriteItems(
          TransactItems = [
              { Put: { TableName: "mpi-master", Item: merged_master,
                        ConditionExpression: "attribute_not_exists(mpi_id) OR mpi_id = :survivor",
                        ExpressionAttributeValues: { ":survivor": surviving_mpi_id } } },
              { Update: { TableName: "mpi-master", Key: deprecated_mpi_id,
                          UpdateExpression: "SET active = :false, merged_into = :survivor, merged_at = :now" } },
              ...for each xref member:
              { Update: { TableName: "mpi-xref", Key: (source_system, source_record_id),
                          UpdateExpression: "SET mpi_id = :survivor, ...",
                          ConditionExpression: "mpi_id = :prev_mpi" } },
          ]
      )
  ELSE:
      // large-cluster path: stage the change, then commit.
      // Step 5E.1: write a staging record with the full intended
      // post-merge state.
      DynamoDB.PutItem("merge-staging", {
          merge_id: new UUID,
          surviving_mpi_id: surviving_mpi_id,
          intended_xref_updates: [...],
          intended_master_writes: [...],
          status: "staged"
      })
      // Step 5E.2: apply the changes in batches of 95, with each
      // batch wrapped in TransactWriteItems and the staging record
      // updated to mark progress.
      FOR each batch in chunked(intended_changes, 95):
          DynamoDB.TransactWriteItems(batch + [
              { Update: { TableName: "merge-staging", Key: merge_id,
                          UpdateExpression: "SET applied_count = applied_count + :n" } }
          ])
      // Step 5E.3: when applied_count == intended_count, mark
      // status = "committed" and continue to audit-archive write.
      // A reconciliation job runs on staged-but-not-committed
      // merges every N minutes to either complete or roll back.

  // Step 5F: audit-archive write happens after the master+xref
  // state is consistent. The audit record references the merge_id
  // from the staging table for traceability.
  ```

  And specify the partial-failure recovery semantics in the architecture prose:

  *"The merge operation is atomic at the master+xref state: either the entire merge is applied or none of it is. For small clusters (≤ 95 cross-references), the merge fits in a single `TransactWriteItems` call. For larger clusters, the merge stages the intended state in a `merge-staging` table, applies the changes in atomic batches with progress tracking, and runs a reconciliation job to complete or roll back staged-but-not-committed merges. The staging-table pattern preserves the all-or-nothing semantics across cluster sizes that exceed transaction limits. The audit-archive write follows the consistent-state confirmation; the EventBridge merge event emit follows the audit-archive write. Each step has DLQ routing for terminal failures so half-applied merges surface for engineering investigation rather than silently producing inconsistent state."*

  Reference Recipe 4.6 Finding 2 / 4.7 Finding 5 / 4.10 Finding A4 as the chapter pattern for atomic-write specification under partial-failure handling. Recipe 5.1's gap is the most consequential because the artifact is the master patient identity itself; downstream Chapter 5 recipes that build on this matcher inherit any state-consistency gap.

### Finding A2: Cohort Disparity Alert Threshold and Equity Metric Definitions Are Referenced as Non-Negotiable but Undefined

- **Severity:** HIGH
- **Expert:** Architecture (fairness, civil-rights implications, the recipe's most-emphasized equity claim)
- **Location:** General Architecture Pattern paragraph: *"Cohort-stratified accuracy monitoring is part of the system, not an afterthought. Compute and report match rate, false-positive rate, and review queue depth by demographic cohort (race, ethnicity, language, age band, geographic region, primary-language). Significant disparities (worse match rate for Hispanic patients than non-Hispanic, for example) are signals that the comparators or the m/u probabilities are not generalizing across populations and need cohort-specific tuning."* And the Honest Take's equity paragraph: *"Hispanic and other naming-convention-diverse patients match worse on average than dominant-culture patients in essentially every off-the-shelf system. The cohort-stratified accuracy monitoring will show this. The fix is per-cohort comparator tuning ... This is not optional in 2026; it is the standard."* And the Performance Benchmarks table referencing *"Cohort match-rate parity (worst cohort vs best cohort): unmonitored | 0.85-0.95 after cohort-specific tuning."*
- **Problem:** The recipe's central fairness instrumentation is repeatedly invoked as non-negotiable, but the operational thresholds, metric definitions, and escalation policy are not specified. The architecture is silent on:

  1. **What the alert threshold value should be.** The Performance Benchmarks table cites "0.85-0.95 after cohort-specific tuning" as the target match-rate parity ratio (worst cohort vs best cohort), but the operational threshold at which the alert fires is implementation-defined. A threshold set too high silences the alert; a threshold set too low produces alarm fatigue. Recipe 4.8 Finding A4, 4.9 Finding A2, and 4.10 Finding A1 all elevated the same gap to HIGH severity on the same Obermeyer-canonical-concern reasoning; 5.1 inherits the concern with the additional weight that this is the foundational matcher every downstream Chapter 5 recipe builds on.

  2. **How each metric is computed.** Match-rate parity could be operationalized as the ratio of cohort-specific recall (true matches found / true matches in the cohort), the ratio of cohort-specific auto-match precision, the ratio of cohort-specific review-queue depth-per-FTE, or the ratio of cohort-specific time-to-resolution. False-positive rate parity could be operationalized as the ratio of post-merge unmerge rates per cohort (the surfaced-wrong-merge rate). Each operationalization has different sensitivity to upstream training-data composition and should be specified rather than implementation-defined.

  3. **Per-axis aggregation policy.** Cohort axes named in the recipe include race, ethnicity, language, age band, geographic region, and primary-language. Setting a single chapter-wide threshold may miss axis-specific patterns (a system can be parity-passing on race while parity-failing on language). The architecture should specify per-axis thresholds at minimum, ideally with the framing that the per-axis threshold is set by the cross-functional equity-review committee.

  4. **Chronic-suppression-as-fairness-signal pattern.** A cohort whose volume is structurally low (rare languages in the deployed region, small geographic-region cohorts) silences the disparity calculation; the system reports "no signal" when in fact the signal is "this cohort is structurally under-represented and we cannot tell whether the matcher works for them." Same gap as Recipe 4.10 Finding A1: the architecture should name chronic insufficient-sample as itself a fairness signal escalated to the equity committee.

  5. **The labeled gold set's cohort coverage is itself an equity concern.** The recipe text correctly mentions "a held-out labeled gold set of pairs that have been reviewed by HIM, with the reviewer's match / not-match decision recorded." A gold set that is 90 percent dominant-culture-cohort produces threshold tuning that overfits the dominant cohort. The architecture should specify cohort-stratified gold-set construction (the gold set must include adequate representation of every operationally-relevant cohort) and the validation discipline (per-cohort precision and recall reported on the gold set, not just overall).

  6. **The relationship between cohort-stratified measurement and per-cohort comparator tuning is unspecified.** The recipe says "the fix is per-cohort comparator tuning, supplementary cohort-specific blocking passes, and (where feasible) a cohort-specific m/u model." When the dashboard surfaces a cohort-specific gap, what is the documented process for diagnosing and addressing it? The Honest Take names the discipline; the architecture should name the operational workflow.

- **Fix:** Specify the thresholds and the metric definitions in the General Architecture Pattern subsection on cohort-stratified accuracy monitoring:

  ```
  // Cohort-disparity thresholds (per chapter-wide policy; per-axis-per-
  // metric overrides set by the equity-review committee):
  //   MATCH_RATE_DISPARITY_THRESHOLD          = 0.10
  //     // Ratio of cohort-specific recall, worst-cohort versus best-
  //     // cohort, on the labeled gold set. Above 0.10 triggers alert.
  //   AUTO_MATCH_PRECISION_DISPARITY_THRESHOLD = 0.05
  //     // Tighter because precision affects safety: a higher false-
  //     // merge rate in some cohorts is a safety asymmetry, not just
  //     // an accuracy issue.
  //   REVIEW_QUEUE_DEPTH_PER_FTE_DISPARITY    = 0.20
  //     // Operational signal: cohorts with structurally larger
  //     // queues per FTE may indicate cohort-specific tuning gaps
  //     // that downstream HIM workload is absorbing.
  //   POST_MERGE_UNMERGE_RATE_DISPARITY       = 0.05
  //     // Surfaced-wrong-merge rate per cohort. Higher rates in
  //     // specific cohorts indicate auto-match precision failures.
  //   MIN_COHORT_SAMPLE_SIZE = 200 candidate pairs per cohort per
  //     measurement window. Below this, disparity calculation is
  //     suppressed and the cohort is escalated to the equity committee
  //     as an "under-representation" signal.
  ```

  Add a paragraph to the architecture pattern naming the per-axis-per-metric override mechanism (the equity-review committee documents the threshold per (axis, metric) at deployment), the chronic-suppression-as-fairness-signal pattern, the cohort-stratified gold-set construction discipline, and the diagnose-and-address workflow that fires when an alert crosses threshold.

  Reference Obermeyer 2019 as the canonical concern (already cited in the recipe), Recipe 4.8 Finding A4, 4.9 Finding A2, 4.10 Finding A1 as the chapter-wide pattern, and the Variations and Extensions section's per-cohort m/u models as the canonical remediation. The chapter editor should consider whether the equity-instrumentation framework belongs in chapter preface; for 5.1 specifically, this is the chapter's foundational recipe and the threshold specification belongs in main text.

### Finding A3: "Do Not Merge" Flag for Safety-Sensitive Patient Populations Is Not Architected

- **Severity:** HIGH
- **Expert:** Architecture (clinical safety, legal compliance, equity, the recipe-specific chapter pattern that is missing)
- **Location:** Reviewer-training paragraph in "Why This Isn't Production-Ready": *"Reviewer training on the decision criteria, on edge cases (twins, family members, intentional name changes, suspected identity fraud), and on documentation standards is a one-to-three-week onboarding investment per reviewer."* And the "Where it struggles" entry on twin and family-member confounding. No architectural primitive in the pseudocode or the architecture diagram for explicit no-merge / no-link flags.
- **Problem:** The recipe is silent on the architectural primitive that handles patients whose records must remain unlinked for safety, legal, or institutionally-defined reasons. Concrete examples that the architecture must accommodate:

  1. **Domestic violence survivors with name-change orders.** Some states' Address Confidentiality Programs (Safe at Home in California, ACP in Massachusetts, comparable programs in 30+ states) provide legally-protected substitute addresses and identity protections. A patient under one of these programs has a legally-enforced separation between their pre-protection and post-protection records; merging them defeats the entire point of the program and may directly endanger the patient. The matcher will have access to demographic data that, naively scored, would auto-merge these records.

  2. **Witness-protection enrollees.** US Marshals Witness Security Program enrollees have federally-mandated identity separation. The institutional system may receive both pre-and-post-enrollment records; merging them is a federal-level violation.

  3. **Adopted children with sealed biological-parent records.** Sealed adoption records are jurisdictionally enforced; the medical record of an adoptee with a known biological-parent medical history may contain demographic data linking to the biological parent. The matcher must not surface that linkage.

  4. **Gender-transition patients with intentionally-separated pre-and-post-transition identities.** Some patients explicitly request that their pre-transition demographic data not be linked to their post-transition record; the linkage is itself a disclosure event. The recipe text mentions "gender transitions, name changes that were specifically requested to be hidden, and patient-stated preferences about historical-name handling" in the production-gaps survivorship discussion, but the matching-side implication (these records must not be merged or surfaced) is not architected.

  5. **Patients in care-team-isolated cohorts.** A patient receiving care for sensitive conditions (substance use treatment under 42 CFR Part 2, behavioral health, infectious disease) may have institutional segmentation policies that restrict cross-program record linkage. The matcher must respect these segmentation boundaries.

  6. **Twins and family members with identical demographics.** The "Where it struggles" entry correctly identifies this as a confounder; the architecture should specify a no-merge flag set when the institutional record explicitly notes a relationship (twin sibling, parent-infant co-registration) that the matcher must respect rather than override.

  Without an architectural primitive for "this pair must never auto-merge, must never be surfaced to the standard review queue, and must be routed to the privacy-office's restricted-review track," the matcher will eventually re-link records that the institution explicitly intended to keep separate. Each re-linkage is a clinical-safety event (in the domestic violence case, potentially a life-safety event) and a legal-compliance violation. The mitigation cannot be "the HIM reviewer will catch it" because (a) auto-match runs without human review by definition, (b) the no-link populations are exactly the populations whose records look most demographically similar across the pre-and-post-protection split, and (c) the reviewer-training paragraph treats this as edge-case onboarding rather than an architectural primitive.

  The chapter pattern is missing entirely. Recipe 4.4-4.10 have analogous chapter-specific patterns (the "do-not-engage" flag in 4.4-4.7, the "treatment-out-of-scope" flag in 4.8, the "regime-not-eligible" flag in 4.10); 5.1 needs an analogous primitive but does not have one.

- **Fix:** Add a `no_link_flags` table and an architectural-primitive specification:

  ```
  // The no_link_flags table is keyed on (mpi_id_or_record_id, flag_type)
  // and persists explicit institutional or patient-requested separation
  // policies. Flag types include:
  //   "address_confidentiality_program": ACP / Safe at Home enrollment
  //   "witness_protection": federal witness-security enrollment
  //   "adoption_sealed": sealed-adoption directive
  //   "patient_requested_separation": patient-elected pre-and-post-
  //     identity separation (gender transition, name change with
  //     intentional historical-record-hiding)
  //   "care_segmentation": institutional cross-program linkage
  //     restriction (Part 2 SUD, behavioral health, infectious disease
  //     under institutional policy)
  //   "family_relationship_explicit": twin sibling, parent-infant
  //     co-registration with explicit relationship flag
  //   "no_link_pairwise": explicit pairwise no-link between two
  //     specific source-record IDs (the mitigation when the matcher
  //     repeatedly suggests a known false-positive pair)
  //
  // The matching pipeline consults no_link_flags at three points:
  //   1. Candidate generation: pairs containing a record with a
  //      blocking-pass-incompatible flag (e.g., address_confidentiality_program
  //      records with the address-based blocking pass) are filtered
  //      from the candidate set.
  //   2. Routing: pairs that scored above the auto-match threshold
  //      but contain a record with a no-link flag are routed to the
  //      privacy-office restricted-review track instead of the
  //      auto-match path. Auto-match never occurs for flagged pairs.
  //   3. Review-queue assignment: pairs with care_segmentation or
  //      family_relationship_explicit flags are routed to a separate
  //      restricted queue with cleared reviewer access controls;
  //      the standard review queue does not see them.
  //
  // The flags are write-protected: only privacy-office and HIM-
  // leadership roles can add or remove flags, with full audit
  // trail. The no_link_flags table is itself encrypted with a
  // separate KMS key from the primary MPI tables, with tighter
  // access controls.
  ```

  Add a paragraph to the architecture pattern:

  *"The matcher must respect explicit no-link policies. Patients in safety-sensitive programs (Address Confidentiality Programs, witness protection, sealed adoptions), patients who have requested intentional pre-and-post-identity separation (gender transition, protected name changes), patients in institutionally-segmented care programs (42 CFR Part 2 SUD, behavioral health under segmentation policy), and family relationships with explicit do-not-merge flags (twins, parent-infant co-registrations) all require architectural support for 'this record must not be auto-merged with that record.' The no-link-flags table is consulted at candidate generation, threshold routing, and review-queue assignment, with auto-match path bypassed for any pair containing a flagged record. The flags are write-protected to privacy-office and HIM-leadership roles, with separate-key encryption and tighter access controls than the primary MPI tables. The implementation gap here is not a feature gap; it is a clinical-safety and legal-compliance baseline."*

  Reference relevant state Address Confidentiality Program statutes, the federal Witness Security Program guidelines, and 42 CFR Part 2 for the Substance Use Disorder confidentiality framework. The chapter editor should consider whether the no-link-flag pattern should propagate to the chapter preface for all Chapter 5 recipes, since cross-organization matching (5.5, 5.7, 5.9) inherits the same concern.

### Finding A4: M/U Probability Re-Estimation Cadence and Validation Gating Are Named in Production-Gaps but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, model lifecycle)
- **Location:** "Why This Isn't Production-Ready": *"M/U probability estimation and re-estimation cadence. The m and u probabilities are the core of the Fellegi-Sunter scoring. EM-based estimation works but produces probabilities that drift as the underlying data drifts ... Build a re-estimation pipeline that runs on a documented cadence (quarterly is typical), validates the new probabilities against the held-out gold set before promotion, and emits a 'model version updated' event that downstream consumers can react to."*
- **Problem:** The recipe correctly diagnoses the M/U drift problem and prescribes the response, but the actual architecture does not include the re-estimation pipeline, the validation-gating workflow, or the version-event emission. Three concrete gaps:

  1. **The re-estimation Glue job is not in the architecture diagram.** The architecture diagram shows the batch-matching Glue job (`block-and-score, Splink on Spark`) and the threshold-router Glue job. It does not show the M/U re-estimation job, the validation-against-gold-set job, or the model-promotion pipeline. The pseudocode mentions `model_version: model.version` and `MODEL_VERSION` constants but does not specify how new versions are produced or promoted.

  2. **The validation-gating semantics are unspecified.** What is the gate that determines whether a new M/U model is promoted? Per-cohort precision and recall stable or improved, no per-cohort regression beyond a documented threshold, overall accuracy maintained. The Honest Take's per-cohort tuning discipline depends on the validation gate being cohort-stratified, not just overall.

  3. **Downstream-consumer reaction to model-version events is unspecified.** The recipe says the system "emits a 'model version updated' event that downstream consumers can react to." Which consumers? With what semantics? A model-version change implies that historical scores in the audit archive were computed against a different model; the analytics queries that span the version transition need to handle the discontinuity. The architecture should specify the model-version-as-an-attribute pattern in the audit archive (already present in the Expected Results JSON: `"model_version": "fs-v2.3.1"`) and the cohort-stratified-by-version dashboard pattern.

- **Fix:** Add an M/U re-estimation pipeline to the architecture diagram and a paragraph specifying the cadence, validation gate, and version-event semantics:

  *"The M/U probability re-estimation pipeline runs on a quarterly cadence (or on-demand after major data-quality events: registration system upgrade, organizational acquisition, change in nickname dictionary). A scheduled Step Functions workflow runs a Glue job to re-estimate M and U probabilities via EM on the current normalized-records dataset, validates the new model against the held-out gold set with per-cohort precision and recall reported, and gates promotion behind a committee review surface. The committee review surface presents the per-cohort accuracy delta from the prior model version, with chronic-suppression-as-fairness-signal handling for under-represented cohorts. Approved models are promoted by writing a new MODEL_VERSION configuration entry; the threshold-router Lambda and the batch Glue job pick up the new version on next invocation. A 'model_version_updated' event is emitted on EventBridge with the prior and new version IDs; downstream consumers (the analytics dashboards over the audit archive, the equity dashboard) handle the version transition by partitioning analyses on `model_version` rather than computing across the boundary."*

  Reference Recipe 4.10 Finding A2 (reward-function governance pattern) for the analogous cross-functional-review-with-parallel-evaluation pattern. The chapter editor should consider whether the model-promotion-with-validation-gate pattern belongs in chapter preface; for 5.1 specifically, the M/U probabilities are the core scoring primitive and the gating discipline belongs in main text.

### Finding A5: Real-Time Matching Latency Budget and Failover Path When OpenSearch Is Unavailable Are Named but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (availability, real-time-workflow integration)
- **Location:** "Why This Isn't Production-Ready" entry on real-time matching latency: *"Real-time matching at registration time has a tight latency budget; the registration clerk cannot wait fifteen seconds for the result. Architect for sub-second response: in-memory blocking key indices for the most common access patterns, OpenSearch query optimization, candidate-set capping (return at most N candidates per blocking pass), and asynchronous follow-up scoring for borderline cases that did not resolve in time. The asynchronous-resolution pattern lets the registration desk proceed while the system continues working in the background."*
- **Problem:** The recipe correctly diagnoses the latency budget and prescribes the response, but the actual architecture does not include the in-memory blocking-key index, the candidate-set capping, the asynchronous-follow-up Lambda, or the OpenSearch availability fallback. Two concrete gaps:

  1. **Sub-second budget requires architectural primitives that are not in the diagram.** The architecture diagram shows `KS1 (Kinesis) -> L1 (normalize) -> L2 (candidate-generator with OpenSearch) -> L3 (pair-scorer) -> L4 (threshold-router)` as a synchronous chain. With OpenSearch query latency (typically 50-200ms for phonetic queries), per-pair scoring (the Lambda invocation overhead plus the comparator computation), and the threshold-routing Lambda, the synchronous chain is realistically 300-800ms on average and can spike to several seconds under load. Without architectural specification of the latency primitives (the in-memory blocking-key cache, candidate-set capping, asynchronous-follow-up for borderline cases), the registration desk does not get the sub-second response the recipe promises.

  2. **OpenSearch availability is a single point of failure for real-time matching.** OpenSearch maintenance, version upgrades, and zone-level outages happen; the architecture does not specify what the registration pipeline does when the candidate-generator Lambda cannot reach OpenSearch. Concrete options: fall back to a "register without matching, queue for later batch matching" path with explicit user-facing acknowledgment that matching will run asynchronously; fall back to a smaller, replicated DynamoDB-backed blocking-key index; reject the registration with a clear error. The choice is policy, but it must be specified architecturally because the registration workflow cannot block on a downstream availability event.

- **Fix:** Add the latency-budget primitives to the architecture and specify the OpenSearch failover policy:

  *"The real-time matching pipeline targets sub-second response. The candidate-generator Lambda consults two indices: an ElastiCache (Redis) in-memory blocking-key index for the most common access patterns (last-name-metaphone + DOB-year, phone-last-4 + DOB-year) seeded from a periodic Glue job, and the OpenSearch index for the broader blocking-pass set. Each blocking pass returns at most N candidates (N = 50 typical, configurable per pass); pairs scoring above HIGH_THRESHOLD or below LOW_THRESHOLD return immediately; pairs in the borderline band are queued via SQS for asynchronous-follow-up scoring with a separate Lambda that does not block the registration response. The registration UI receives the synchronous result (auto-match, auto-non-match, or 'pending review' for borderline pairs) within the latency budget. When OpenSearch is unavailable, the candidate-generator Lambda falls back to the ElastiCache blocking-key index alone, with a logged metric `opensearch_fallback_invoked`. If both are unavailable, the registration pipeline routes the new record to a 'queued for matching' DLQ that the next batch-matching cycle processes, with an explicit user-facing acknowledgment that matching will run asynchronously. The DLQ is monitored with a CloudWatch alarm so chronic OpenSearch availability issues do not silently degrade the matching freshness."*

  Reference Recipe 4.6 / 4.10 patterns for the asynchronous-follow-up SQS pattern.

### Finding A6: Backfill Strategy Is Named in Production-Gaps as a "Separate Engineering and Operational Project" but the Architecture Does Not Specify the Throttling and Review-Capacity Coordination

- **Severity:** MEDIUM
- **Expert:** Architecture (operational, project-execution)
- **Location:** "Why This Isn't Production-Ready" backfill paragraph: *"When the matcher launches, it has to process the existing patient base (potentially millions of records) before steady-state operation begins. The backfill is a separate engineering and operational project: generate the candidate pairs in batch, score them all, route through the review queue, ramp HIM-team capacity for the initial review wave, and accept that the cleanup will take weeks to months."*
- **Problem:** The backfill is named as a project but the architectural primitives that make it manageable are missing. Three concrete gaps:

  1. **Review-queue saturation throttling is not architected.** A backfill that produces tens of thousands of candidate pairs in the borderline band will saturate the review queue beyond the HIM team's daily capacity. Without throttling, the queue grows without bound, reviewers face a perpetually-growing list, decision quality degrades, and the system's promise ("we will find duplicates and route them through review") becomes empirically false. The architecture should specify a queue-depth-aware throttling pattern: backfill candidate-pair routing pauses when the review queue exceeds a configurable depth, resumes when the depth falls below a hysteresis threshold, with a dashboard showing the projected backfill completion timeline given current review-team throughput.

  2. **Backfill-vs-real-time prioritization is unspecified.** When both the backfill candidate pairs and the real-time registration candidate pairs route to the same review queue, the real-time registrations are typically higher-priority (a clinician is currently looking at the chart). The architecture should specify queue partitioning (backfill queue, real-time queue) or priority-based ordering within a single queue.

  3. **The "ramp HIM-team capacity" framing is correct but the ramp-down is unspecified.** Once the backfill completes, the queue depth drops to steady-state. The temporary HIM-team capacity ramp must wind down without leaving the operational team with a permanent over-capacity (a budgeting concern) or under-capacity (the steady-state queue still requires a baseline). The architecture should specify the queue-depth-vs-FTE-ratio target that triggers the ramp transition.

- **Fix:** Add a paragraph to the architecture pattern specifying the backfill primitives:

  *"The backfill operation is throttled and partitioned. Candidate pairs from backfill route to a separate `review-queue-backfill` queue (or with a backfill-specific queue_id assignment), distinct from the real-time `review-queue-realtime` queue. Real-time pairs are reviewed first; backfill pairs are reviewed when real-time queue depth permits. Backfill candidate-pair routing pauses when the combined queue depth exceeds the configured ceiling (typically 2x the team's daily decision throughput) and resumes when depth falls below the hysteresis threshold (typically 1.5x daily throughput). A backfill dashboard tracks projected completion timeline and HIM-team throughput against the backfill volume; ramp-up and ramp-down decisions are made on the dashboard's signal rather than calendar-based. The temporary HIM-team capacity ramp targets steady-state queue depth at the FTE-ratio defined in the recipe's reviewer-staffing prerequisite (0.25-1.0 FTE per 100K active patients); the ramp transitions back to baseline when projected queue depth at baseline staffing falls below the target maintenance threshold."*

### Finding A7: Cross-System Identity Reconciliation When MPI Assignments Diverge Is Named but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, multi-system propagation)
- **Location:** "Why This Isn't Production-Ready" cross-system reconciliation paragraph: *"In a multi-EHR institution, the MPI must be the source of truth and downstream systems must adopt the surviving mpi_id. The reconciliation when source systems disagree (the EHR has linked records as the same patient but the billing system has them separate, or vice versa) requires a cross-system reconciliation process that surfaces the divergence and pushes the resolved identity to all systems. Build this from day one, because cross-system divergence accumulates silently and is much harder to fix later."*
- **Problem:** The recipe correctly names the divergence-detection-and-reconciliation gap but does not architect it. Three concrete gaps:

  1. **The divergence-detection mechanism is unspecified.** How does the matcher learn that a downstream system has linked or unlinked records differently? The institutional EHR's chart-linkage events flow back as evidence, but the architecture diagram does not show this feedback path. The merge-events EventBridge bus flows out to downstream consumers; the inverse path (downstream-system linkage signals flow back to the matcher) is missing.

  2. **The reconciliation policy is unspecified.** When the matcher's `mpi_id` assignment differs from a downstream system's linkage, who wins? The recipe says "the MPI must be the source of truth" but the operational policy needs to handle cases where the downstream system has clinical evidence the matcher does not (a clinician explicitly merged records in the EHR based on knowledge the matcher does not have).

  3. **The divergence-resolution surface is unspecified.** A divergence event needs a review surface analogous to the review queue but for cross-system reconciliation. The architecture should specify a `cross-system-divergence-queue` or equivalent, with HIM-leadership roles authorized to adjudicate.

- **Fix:** Add a cross-system reconciliation pipeline to the architecture, with:

  *"Downstream systems emit linkage-evidence events back to the matcher: the EHR emits `chart_linkage_observed` events when a clinician explicitly merges or unmerges chart records; the billing system emits `account_linkage_observed` events when account reconciliation links or unlinks; the patient communication system emits `outreach_consolidated` events. The reconciliation Lambda consumes these events and compares the downstream linkage state to the MPI's `mpi_id` assignment. Divergence (downstream linked, MPI unlinked, or vice versa) routes to the `cross-system-divergence-queue` with the source-system linkage evidence preserved. HIM-leadership roles adjudicate divergence cases: the resolution either updates the MPI to match the downstream evidence (if the clinical evidence is authoritative) or pushes a corrective linkage event back to the downstream system (if the MPI is correct). The adjudication is logged with full provenance in the audit archive. Cross-system divergence rates per system are dashboarded; chronic divergence indicates either a matcher gap or a downstream-system data quality issue that warrants investigation."*

### Finding A8: Forward-Looking Cross-Recipe Orchestration with Later Chapter 5 Recipes Is Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, integration, the recipe-as-foundation framing)
- **Location:** Related Recipes section names cross-recipe relationships at one-line granularity but does not architect the integration patterns. The Honest Take frames 5.1 as "the cheapest way to make the rest of the chapter cheaper" and "the foundation that every other recipe in this chapter reuses."
- **Problem:** Recipe 5.1 is the foundation matcher; Recipes 5.5 (cross-facility patient matching), 5.6 (claims-to-clinical linkage), 5.7 (longitudinal across name changes), 5.8 (privacy-preserving), 5.9 (national-scale TEFCA), and 5.10 (deceased patient resolution) all extend the framework. The recipe acknowledges this in prose but does not architect:

  1. **The MPI-as-shared-substrate contract.** Downstream recipes consume `mpi_id` as the canonical identity. The version-and-history contract (an `mpi_id` may have been merged into another `mpi_id`; downstream consumers need to handle this) is implicit. The architecture should specify the `mpi_id_resolution_at_query_time` pattern: every consumer that holds an `mpi_id` from a prior write should resolve it through the cross-reference table at read time to handle subsequent merges.

  2. **The blocking-and-comparator-library reuse contract.** The blocking passes, the per-field comparators, and the Fellegi-Sunter combiner are reusable across recipes. The architecture should specify the library boundary (the matching primitives are packaged as a Lambda layer or a Glue Python library) and the version-coupling contract (a downstream recipe pinned to a specific library version).

  3. **The audit-archive shared-substrate contract.** The audit archive is partitioned by date and routing decision; downstream recipes that need entity-resolution forensic data consume from the same archive with the same partition scheme. The architecture should specify the cross-recipe consumption pattern.

- **Fix:** Add a brief subsection to the architecture pattern specifying the MPI-as-shared-substrate contract, the matching-primitives library boundary, and the audit-archive shared-substrate contract. Reference Recipe 4.10 Finding A7 (cross-recipe orchestration pattern) as the chapter sibling.

### Finding A9: Idempotency and DLQ Coverage on All Lambda Paths (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, resilience)
- **Location:** "Why This Isn't Production-Ready" idempotency paragraph: *"Real-time matching is event-driven; the pipeline must handle duplicate-event-delivery without producing duplicate merges. Use the (`source_system`, `source_record_id`) as the idempotency key for normalize-and-route operations; use the `merge_id` as the idempotency key for merge-application operations. Lambda invocations should be idempotent at these keys. Step Functions Catch should distinguish retryable infrastructure failures from terminal logic failures and route terminal failures to a DLQ for human investigation."*
- **Problem:** Same chapter-wide pattern as Recipe 4.4-4.10. The recipe acknowledges the gap.
- **Fix:** Same as 4.4-4.10. Inline DLQ coverage on all Lambda paths in the architecture diagram, idempotency keys on all writes, fall-back-to-no-action pattern when matching fails partway. For Recipe 5.1 specifically, the apply_merge idempotency on `merge_id` is the most consequential because a duplicate-merge invocation would re-apply the merge with potentially different survivorship outcomes if the source records were modified between invocations.

### Finding A10: Audit-Archive Cohort Stratification for Direct Athena Access Is Underspecified

- **Severity:** MEDIUM
- **Expert:** Architecture (privacy, access control)
- **Location:** AWS Implementation Athena and QuickSight paragraphs: *"Athena (over the Glue catalog) provides the ad-hoc SQL access for cohort-stratified accuracy monitoring and HIM-team analytics."* And: *"QuickSight on Athena over the Glue-cataloged audit data, with row-level security for cohort-specific access where institutional policy requires it."*
- **Problem:** QuickSight has named row-level security; Athena does not. A direct Athena query against the audit archive can read every PHI-containing row regardless of cohort. The recipe correctly applies row-level security at the QuickSight layer but the Athena layer is the underlying access surface and is not similarly restricted. Three concrete gaps:

  1. **Athena access control inherits from S3 bucket and Glue catalog permissions.** A role with `athena:StartQueryExecution` on the audit-archive workgroup and `s3:GetObject` on the audit-archive bucket can read every row. Without column-level or row-level restrictions, the access is too coarse for the audit archive's PHI sensitivity.

  2. **Lake Formation provides the column-level and row-level access control that Athena lacks natively.** The architecture should specify Lake Formation as the access-control layer over the Glue catalog, with column-level permissions (the `cohort_features` columns are restricted to the equity-review committee role; the raw demographic columns are restricted to HIM-leadership roles) and row-level permissions (cohort-based filtering at the row level for general analytics use).

  3. **Direct Athena query logging is named in the CloudTrail prerequisite but the per-query review is not architected.** Athena query execution events are CloudTrail-logged; the per-query review surface (a chronic high-volume query against PHI columns, a query from an unexpected role) is the operational signal that catches misuse.

- **Fix:** Add Lake Formation to the architecture diagram and specify the access-control posture:

  *"Lake Formation manages access to the audit archive's Glue-cataloged tables. Column-level permissions restrict the `cohort_features`, `field_comparisons`, and `per_field_log_ratios` columns to roles authorized for entity-resolution analytics; the demographic-snapshot columns are restricted to HIM-leadership roles for forensic investigation. Row-level filtering supports cohort-stratified analytics for the equity-review committee with cohort-bounded scope. QuickSight inherits Lake Formation permissions; direct Athena access uses Lake Formation grants. Athena query execution is CloudTrail-logged with periodic review of high-volume or unusual access patterns."*

### Finding A11: Twin and Family-Member Confounding Is Diagnosed but Not Architected

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** "Where it struggles" entry on twin and family-member confounding: *"The mitigation is family-aware blocking and per-field comparators that down-weight matches on shared-family fields when other fields suggest different individuals."*
- **Problem:** The recipe correctly diagnoses the confounder and prescribes the mitigation but does not architect the family-aware-blocking primitive. A family-aware blocking pass needs explicit relationship metadata (the `family_relationship_explicit` flag from Finding A3 is the canonical primitive); without it, the comparators cannot distinguish "two different family members with shared address and surname" from "one person with two records." Sibling to Finding A3.
- **Fix:** Reference the no-link-flags table from Finding A3 and specify a family-aware blocking pass that consults the flags to skip comparison of explicitly-flagged sibling pairs.

### Finding A12: Data Quality Feedback to the Registration Desk Is Named but the Feedback Loop Is Not Architected

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" data-quality-feedback paragraph: *"The matcher learns where the source data quality is poor. Names that are routinely mistyped, DOBs that are routinely entered as 01/01/1900, addresses that fail USPS standardization, phones that are routinely stored with extension formatting issues. Feed this back to the registration system and the front-desk training program."*
- **Problem:** The recipe correctly diagnoses the feedback opportunity but does not architect the path back to the registration system. A "registration-desk-feedback" event stream that consumes the matcher's quality-flag observations and surfaces them to the registration system's training dashboard or to the front-desk supervisor is a small but operationally meaningful primitive.
- **Fix:** Add a note to the architecture pattern naming the feedback path: *"The matcher emits a `data_quality_observed` event on EventBridge for each normalized record's quality flags (implausible DOB, invalid SSN pattern, USPS-unstandardizable address, phone with extension formatting issues). The registration system consumes these events and surfaces aggregate data-quality patterns to the front-desk training dashboard."*

---

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** The Prerequisites VPC row names production discipline: Lambdas in VPC; Glue jobs in VPC connections; OpenSearch in VPC; VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, STS, Kinesis, OpenSearch. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization.** "NAT Gateway only for external services without VPC endpoints (USPS API, identity-verification services if used); restrict egress with security groups" is the right discipline. The named external dependencies (USPS / SmartyStreets / Melissa for CASS-certified address standardization) are correctly flagged as the cases that require external egress.
- **No `0.0.0.0/0` egress.** The recipe explicitly states "No `0.0.0.0/0` egress; egress destinations are explicit per AWS service prefix list or per VPC endpoint." This is the chapter's most explicit egress-discipline statement to date and should be the chapter pattern that earlier recipes adopt.
- **VPC Flow Logs enabled.** Correct.
- **TLS framing throughout.** Encryption-in-transit named for OpenSearch, the API surface, Kinesis, EventBridge.
- **OpenSearch in VPC with fine-grained access control.** The HIPAA-eligible posture for OpenSearch (BAA-covered, KMS-encrypted indices, fine-grained access control) is correctly framed.

### Finding N1: API Gateway Resource Policy and WAF Posture for the Review-Queue API Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram includes `AG1[API Gateway, review API] -> CG1[Cognito / IdP] -> UI1[HIM Review UI, S3-hosted SPA] -> AG1 -> L6[Lambda, review-decision]`. The Prerequisites VPC row names "EHR integration typically arrives via PrivateLink, Direct Connect, or the institution's existing private network."
- **Problem:** The review-queue API is the operational face of the system; the API Gateway resource-policy posture (private API only, IP allowlist, mTLS, integration with AWS WAF) is not specified. The HIM Review UI is described as an S3-hosted SPA, which implies a publicly-accessible static asset; the API surface that the SPA calls should be private to the institutional network.
- **Fix:** Add to the API Gateway entry: *"Review-queue API deployed as a private API Gateway with VPC endpoint resource policy restricting access to the institutional VPC. WAF enabled with rules for SQL injection, command injection, and rate limiting per authenticated principal. mTLS optionally enabled where the SSO infrastructure supports it. The HIM Review UI is served from S3 with CloudFront and a WAF web ACL; if the UI must be publicly addressable, the API calls are gated through an institutional VPN or PrivateLink-equivalent network rather than direct public-internet access."*

### Finding N2: USPS / Address-Standardization External Egress Posture Is Underspecified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row mentions "external services without VPC endpoints (USPS API, identity-verification services if used)" but the egress controls for these services are not specified.
- **Problem:** USPS Address Validation API, SmartyStreets, and Melissa are the canonical CASS-certified address standardization services. Each requires outbound HTTPS to a vendor-specific domain. Two concrete gaps:

  1. **The egress destination is not pinned.** A `0.0.0.0/0` egress is forbidden per the recipe's own posture, but the alternative (a security group egress rule scoped to the vendor's published CIDR ranges) requires the vendor to publish stable IP ranges. SmartyStreets does not publish a CIDR list; the egress policy needs to either use a NAT Gateway with an outbound proxy that allow-lists the vendor domain, or use the vendor's PrivateLink endpoint where available.

  2. **The vendor's BAA coverage and PHI-handling posture is not addressed.** Each address-standardization vendor must have a BAA in place because the records sent for standardization include patient name and address, which is PHI. The recipe correctly flags BAA coverage for AWS services; the same discipline applies to third-party APIs.

- **Fix:** Add to the VPC row: *"External egress to address-standardization vendors (SmartyStreets, Melissa, USPS) routes through an outbound HTTPS proxy with allow-listed destination domains; the proxy is in VPC with VPC Flow Logs and CloudWatch Logs capture of every outbound connection. Each vendor is BAA-covered before any PHI flows to it; the BAA list is reviewed annually as part of the chapter's BAA-coverage discipline."*

### Finding N3: Kinesis Producer Authentication and Data-in-Transit Encryption Posture Not Specified

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram shows `A1[Patient Registration System / EHR] -> KS1[Kinesis Streams, registration-events]`.
- **Problem:** Kinesis producer authentication for the registration-events stream is not specified. The registration system's role identity (sigv4-signed PutRecord), the cross-account or cross-VPC delivery posture (PrivateLink for the Kinesis endpoint), and the in-transit encryption (TLS 1.2+ enforced) are not explicitly named.
- **Fix:** Add to the Kinesis entry: *"The registration-events Kinesis stream is in the institutional VPC with PrivateLink endpoint access. The registration system uses sigv4-signed PutRecord calls with a dedicated IAM role; cross-account delivery (if the registration system is in a different account) uses VPC PrivateLink with explicit endpoint policies. TLS 1.2+ is enforced; server-side encryption uses customer-managed KMS keys."*

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by counting U+2014 occurrences (PowerShell character iteration over UTF-8 file contents).
- **En dash count: 0.** Verified by counting U+2013 occurrences.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services; AWS appears first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory for the closing observations.
- **CC voice consistent.** The opening Maria Garcia vignette is the chapter's most patient-safety-centered hook and reads as the engineer-explaining-something-cool register. Parenthetical asides land well: "(which, for 'John Smith,' should not surprise anyone)" hits the characteristic register exactly. Self-deprecating expertise: "let's get into how you build it" energy is present in the methodology section. The "this is what duplicate patient records do. They are not, as the IT department sometimes tries to frame it, a data quality nuisance" framing is the chapter's most pointed problem statement.
- **Maria Garcia is consistent throughout.** No name continuity break across the Problem, the Expected Results sample candidate-pair JSON ("first_name": "maria", "last_name": "garcia" / "garcia-lopez"), and the Variations section's references. The clinical scenario is internally consistent: three registrations across years with name-format drift, DOB-format drift, and phone-number change is the canonical entity-resolution case study.
- **Clinical accuracy is high.** The Joint Commission and ECRI Top 10 references are correctly framed as theme-consistent over time with year-specific TODO flags. The 5-15 percent in-system duplicate rate citation is an accurate range from ONC and AHIMA literature, with the appropriate TODO flag for figure verification. The 0.25-1.0 FTE per 100K active patients staffing range is consistent with EMPI vendor and AHIMA practice-guidance figures, with appropriate TODO. The Synthea-derived patient panels framing is the canonical synthetic-data substrate for healthcare entity resolution.
- **The Honest Take is the chapter's most operationally pointed.** Five substantive observations with operational specificity: the one-time-cleanup-vs-permanent-system trap, the review-queue-as-product framing, the conservative-thresholds discipline tied to patient-safety asymmetry, the survivorship-rules-as-clinical-informatics-work framing, and the equity-as-non-optional framing. The closing "duplicate patient records are a problem that has been 'solved' in the academic literature for thirty years and is still unsolved in production at most healthcare organizations. The gap is not a methods gap. It is an alignment-and-operations gap" is the chapter's strongest single line.
- **The Variations and Extensions section is well-scoped.** Eight variations, each framed as "what you'd build at higher sophistication levels": active-learning gold-set construction, per-cohort m/u models, embedding-augmented similarity, graph-based ambiguous-chain clustering, streaming continuous matching, privacy-preserving extension to 5.8, risk-tier-aware thresholding, continuous comparator updating from review-queue feedback, patient-facing self-service. The framing preserves scope discipline and points readers to the natural follow-on chapter recipes.

### Finding V1: A Few Sentences Slip Toward Documentation Voice in the AWS Implementation Section

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in the "Why These Services" and "Ingredients" sections read as service-name-as-bullet-header rather than the engineer-explaining-something-cool register. Examples:

  - *"Amazon DynamoDB for the master patient identity table, the cross-reference table, and the review queue."*
  - *"AWS Glue for the batch matching pipeline."*
  - *"AWS Step Functions for orchestration."*

  These are acceptable as section headers but read as documentation-voice. The deeper-paragraph framing under each header (e.g., "Three tables, each with a clear role. `mpi-master` keyed on `mpi_id`...") returns to the right register.

- **Fix:** Optional. The headers are functionally correct as scannable structure for a long technical section. If the chapter editor wants tighter voice consistency, the headers can be reframed as conversational sentences ("DynamoDB carries the master patient identity, the cross-reference, and the review queue, in three tables with clear roles") but the deeper paragraphs are already in the right register and need no changes.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in The Technology section's probabilistic-record-linkage subsection and the Honest Take's equity paragraph.
- **Problem:** Sentences like *"Two things make Fellegi-Sunter the workhorse it has been for fifty years. First, the m and u probabilities can be estimated directly from the data using **expectation-maximization** (EM). You do not need labeled training data. The algorithm bootstraps from the observed field-comparison patterns under the assumption that the dataset contains a mixture of matches and non-matches. Second, the resulting scores are **interpretable**."* are well-paced but a few sentences in the cohort-fairness paragraph stretch to 40+ words with multiple subordinate clauses. Most sentences in the recipe stay in the right range.
- **Fix:** Optional. The longer sentences are well-formed and read clearly; the trade-off between concision and methodological precision is reasonable for a recipe whose target audience includes statisticians and HIM specialists. If the chapter editor wants tighter sentence rhythm, one or two sentences in the equity paragraph could be split. Most readers will not notice.

### Finding V3: The "Read-Only-One-Recipe" Framing Is the Chapter's Strongest Marketing Line; Use Sparingly

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Problem section's *"This recipe builds the always-on version. ... If you read only one recipe in Chapter 5, read this one. It is the cheapest way to make the rest of the chapter cheaper."* And the Honest Take's *"If you read only one recipe in this chapter, this is the one. If you build only one recipe in this chapter, this is the one."*
- **Note:** Repeating the framing once in The Problem and once in the Honest Take is fine; further repetition would feel like marketing rather than direction. The chapter editor can leave this as is.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1 and chapter-pattern):** Security flags `apply_merge`, `unmerge`, the real-time-matching path, and the review-queue API as needing explicit identity-boundary specification at HIGH severity. Architecture concurs because the master-patient-identity-as-anchor consequence (a misrouted apply_merge corrupts the canonical identity that every downstream clinical record links to) compounds the security concern with a methodological one. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The fix appears once at the recipe level; reference Recipe 4.4-4.10 chapter pattern. The chapter editor should consolidate to a chapter preface in the next pass.**

**Merge atomicity (A1):** Architecture flags the sequential PutItem/UpdateItem pattern as needing `TransactWriteItems` specification at HIGH severity. Security concurs because half-applied merges produce audit-trail inconsistency (merge happened, no audit record) that breaks the reversibility promise the recipe spends substantial space on. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence.**

**Cohort fairness instrumentation (A2 and chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security concurs on the privacy framing of cohort_features in metric dimensions (Finding S3). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The chapter pattern from 4.8 Finding A4, 4.9 Finding A2, 4.10 Finding A1 carries forward; the Obermeyer-pattern citation in the recipe earns the recipe's right to specify the threshold operationally. 5.1 is the foundational matcher and the threshold specification belongs in main text.**

**No-link flag for safety populations (A3):** Architecture flags this as a HIGH-severity gap that is genuinely missing rather than underspecified. The chapter pattern is missing entirely; 4.x recipes have analogous "do-not-engage" or "out-of-scope" primitives but 5.1 has none. Security concurs because the no-link populations include legally-protected categories (Address Confidentiality Programs, Witness Security, sealed adoptions) where re-linkage is a compliance violation and a clinical-safety event. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence. The chapter editor should consider promoting the no-link-flag pattern to chapter preface for all Chapter 5 recipes since cross-organization matching (5.5, 5.7, 5.9) inherits the same concern.**

**Audit-log retention floor (S2):** Security flags as MEDIUM. Architecture concurs that the immutability-via-Object-Lock framing belongs in main text. Networking is silent. **Resolution: MEDIUM, attributed to Security with Architecture concurrence.**

**M/U re-estimation cadence and validation gating (A4):** Architecture flags as MEDIUM. The "Why This Isn't Production-Ready" section names the discipline; the architecture should specify the pipeline. **Resolution: MEDIUM, attributed to Architecture.**

**Real-time matching latency budget and OpenSearch failover (A5):** Architecture flags as MEDIUM. The recipe diagnoses the latency budget but does not architect the response. **Resolution: MEDIUM, attributed to Architecture.**

**Backfill throttling and review-capacity coordination (A6):** Architecture flags as MEDIUM. The recipe names the project; the architecture should specify the throttling primitives. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-system identity reconciliation (A7):** Architecture flags as MEDIUM. Same chapter pattern as 4.10 cross-recipe orchestration, with the inverse direction (downstream-to-matcher rather than recipe-to-recipe). **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration with later Chapter 5 recipes (A8):** Architecture flags as MEDIUM. The recipe acknowledges the dependency in the Honest Take but does not architect the integration. **Resolution: MEDIUM, attributed to Architecture.**

**Idempotency and DLQ coverage (A9 and chapter-pattern):** Architecture flags as MEDIUM. The recipe's existing TODO explicitly names the fix. **Resolution: MEDIUM, attributed to Architecture.**

**Audit-archive cohort stratification for direct Athena access (A10):** Architecture flags as MEDIUM. QuickSight has row-level security; Athena needs Lake Formation. **Resolution: MEDIUM, attributed to Architecture.**

**Twin and family-member confounding (A11):** Architecture flags as LOW (sibling to Finding A3). **Resolution: LOW, attributed to Architecture.**

**Data quality feedback to registration desk (A12):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**SDOH-cohort and demographic-cohort PHI exposure (S3 and chapter-pattern):** Security flags as LOW. Same chapter pattern as 4.4-4.10. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S4 and chapter-pattern):** Security flags as LOW. Existing TODO. **Resolution: LOW, attributed to Security.**

**Patient-facing self-service disclosure policy (S5):** Security flags as LOW. Forward-looking variation concern. **Resolution: LOW, attributed to Security.**

**Networking findings (N1, N2, N3):** All LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2, V3):** V1 and V2 LOW; V3 is a positive observation, not a finding. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 0 critical, 4 high, 11 medium, 6 low. The 4 HIGH count exceeds the > 3 = FAIL threshold; the verdict is FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Four HIGH findings (more than 3 = FAIL per the persona rules). The four HIGH findings are correctness-and-safety gaps with localized fixes; three of them surface in well-specified prose elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose. The fourth (no-link flag) is a genuinely missing chapter-specific primitive that the recipe does not currently address.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | Real-time matching API and merge / unmerge operations lack identity-boundary specification |
| 2 | HIGH | Architecture | Merge operation is not atomic; sequential `PutItem` and `UpdateItem` calls leave half-updated state on partial failure |
| 3 | HIGH | Architecture | Cohort disparity alert threshold and equity metric definitions referenced as non-negotiable but undefined |
| 4 | HIGH | Architecture | "Do not merge" flag for safety-sensitive patient populations is not architected |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 5 | MEDIUM | Security | Audit-log retention policy specified as "per institution's records-retention policy" without architectural floor |
| 6 | MEDIUM | Architecture | M/U probability re-estimation cadence and validation gating named in production-gaps but not architected |
| 7 | MEDIUM | Architecture | Real-time matching latency budget and OpenSearch failover path named but not architected |
| 8 | MEDIUM | Architecture | Backfill strategy named as a "separate engineering and operational project" but throttling and review-capacity coordination not specified |
| 9 | MEDIUM | Architecture | Cross-system identity reconciliation when MPI assignments diverge named but not architected |
| 10 | MEDIUM | Architecture | Forward-looking cross-recipe orchestration with later Chapter 5 recipes not specified |
| 11 | MEDIUM | Architecture | Idempotency and DLQ coverage on all Lambda paths (chapter-wide pattern, already TODO'd) |
| 12 | MEDIUM | Architecture | Audit-archive cohort stratification for direct Athena access underspecified |

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 13 | LOW | Security | SDOH-cohort and demographic-cohort PHI exposure through CloudWatch metric dimensions (chapter-wide pattern) |
| 14 | LOW | Security | IAM "Never `*` actions or `*` resources in production" stated without scoped ARN examples (chapter-wide pattern, already TODO'd) |
| 15 | LOW | Security | Cohort re-identification risk in patient-facing self-service variation not addressed |
| 16 | LOW | Architecture | Twin and family-member confounding diagnosed but not architected |
| 17 | LOW | Architecture | Data quality feedback to registration desk named but feedback loop not architected |
| 18 | LOW | Networking | API Gateway resource policy and WAF posture for the review-queue API not specified |
| 19 | LOW | Networking | USPS / address-standardization external egress posture underspecified |
| 20 | LOW | Networking | Kinesis producer authentication and data-in-transit encryption posture not specified |
| 21 | LOW | Voice | A few sentences slip toward documentation voice in the AWS Implementation section |
| 22 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 4 HIGH findings before publication.** Each has a localized fix:
   - Finding S1 (identity-boundary): pseudocode additions in the real-time-matching path, `apply_merge`, and `unmerge`. Reference language is already present in the production-gaps audit-log access-control paragraph and the reviewer-conflict-of-interest discussion. Estimated effort: half a day.
   - Finding A1 (merge atomicity): pseudocode rewrite of Step 5E to use `TransactWriteItems` for small clusters and the staging-table pattern for large clusters. The architecture prose addition specifies the partial-failure recovery semantics. Estimated effort: half a day.
   - Finding A2 (cohort fairness threshold): threshold-and-metric specification in pseudocode and architecture-prose paragraph. Reference language is present in the equity paragraph and the Variations and Extensions per-cohort m/u models. Estimated effort: half a day.
   - Finding A3 (no-link flag): new `no_link_flags` table specification in the architecture, integration points at candidate generation, threshold routing, and review-queue assignment, and the architecture-prose paragraph naming the safety-sensitive populations. This is the largest fix because it adds a new architectural primitive; estimated effort: one day.

   Total: 2-3 days of writing time.

2. **Address the chapter-wide MEDIUM findings (S2, A9 if not already done).** These are already TODO'd in the recipe and should be consolidated into a chapter preface in the next pass; deferring them to the chapter editor is acceptable.

3. **Address the recipe-specific MEDIUM findings (A4, A5, A6, A7, A8, A10).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1-2 days of writing time.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N1, N2, N3) are explicit-statement additions; the chapter-pattern findings (S3, S4, A11, A12) are consolidation work.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 5.1 is the foundation recipe for Chapter 5; the recipe text says "If you read only one recipe in Chapter 5, read this one. If you build only one recipe in this chapter, this is the one." The quality bar is appropriately the highest in the chapter.

The recipe's underlying methodology, voice, clinical accuracy, and architectural shape are excellent. The Maria Garcia opening, the Fellegi-Sunter exposition, the survivorship-rules subsection, the cohort-fairness framing, and the Honest Take are all chapter-strength contributions. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses (Findings S1, A1, A2) plus one chapter-specific gap that is genuinely missing (Finding A3). Closing the gaps brings the architecture up to the standard the recipe text claims and makes the foundation that the rest of Chapter 5 builds on as solid as the recipe text promises it is.
