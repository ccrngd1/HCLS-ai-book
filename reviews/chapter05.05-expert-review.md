# Expert Review: Recipe 5.5 - Cross-Facility Patient Matching (HIE)

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-22
**Recipe file:** `chapter05.05-cross-facility-patient-matching.md`

---

## Overall Assessment

This is the fifth recipe in Chapter 5 and the second Medium-tier recipe in the chapter. It introduces the recipe-specific concepts that justify a separate recipe from internal patient matching (5.1), provider NPI matching (5.2), address standardization (5.3), and insurance eligibility matching (5.4): cross-organizational entity resolution against records the institution did not control the creation of and probably never will, the privacy-and-consent-as-architecture posture (the consent layer is in the request path, not a downstream checkbox), the multilateral trust model among peer organizations (each must trust that the others are matching responsibly under the participation agreement), the clinical-safety failure-mode escalation (a wrong match is a wrong-patient overlay in the consuming organization's chart, not a billing error), the discoverability semantics ("patient is in our system" is itself sensitive information the consent registry controls), the standards foundation (IHE PIX/PDQ, the FHIR Patient `$match` operation, TEFCA QHIN exchange), the query-time-vs-linkage-time match dichotomy (synchronous-stateless vs. asynchronous-state-building), and the four-component match output (identity match, consent envelope, sensitivity filter, provenance and authority). The opening trauma-team vignette earns its position: the unconscious patient with no ID, brought to the nearest ED, with records at four different organizations none of which connect directly, sets up the cascade of follow-on operational vignettes (HIE operator with forty hospitals plus two hundred ambulatory practices, the wrong-patient overlay from the urgent care chain that was filed automatically, oncology care coordination across academic medical center and community PCP, state Medicaid quality measurement across claims and EHR and reference lab, public-health immunization information system with pop-up clinic submissions, TEFCA national network operator wiring up QHIN-to-QHIN exchange) at exactly the right level of "this is what cross-facility patient matching actually looks like in production" energy.

The Technology section is the chapter's clearest articulation of "why cross-facility matching is structurally harder than internal patient matching." The four differences subsection (you cannot clean the other side's data, the consent layer is in the request path, the trust model is multilateral, the failure modes have a clinical-safety dimension) is the recipe's strongest single architectural framing. The query-time-vs-linkage-time decomposition is correct and at the right grain. The standards-foundation subsection (IHE PIX/PDQ as the v2-based original, PIXm/PDQm as the FHIR-based mobile-friendly variants, FHIR Patient `$match` as the modern REST-friendly version) is correctly granular: the distinction between query-and-respond protocols (the standard says how to query, not how to match) and the matcher implementation behind `$match` is the right framing for why the aggregating side has to apply its own threshold to the responder's confidence. The "What Makes the Cross-Facility Match Hard" six-bullet enumeration (no shared identifier, asymmetric demographic capture in different ways than eligibility matching, lower probability-base-rate, names not stable across organizations and time, privacy and consent as first-class inputs, bounded trust in the responder's match quality) is correct and at the right grain. The "Where the Field Has Moved" subsection is the recipe's strongest single forward-looking framing (TEFCA operational rollout, FHIR-native query as the dominant new pattern, patient-mediated identity, cohort-stratified accuracy required by regulation in some contexts, privacy-preserving record linkage moving from research to production, match-quality benchmarking standards emerging).

The six-stage architecture (ingest the cross-facility query or linkage submission, normalize the demographic search criteria, evaluate against the local MPI or fan out and aggregate, apply consent and sensitivity filters, persist the match decision with provenance, and react to events that invalidate prior matches) is the right shape for the problem. The trigger-source heterogeneity (inbound query, inbound linkage submission, outbound query from local clinician, periodic MPI reconciliation) is correctly handled by a single downstream pipeline with priority metadata. The blocking-as-first-order-architectural-choice framing is correct and the multi-block union pattern (last-name-phonetic-plus-year-of-birth, last-name-phonetic-plus-first-name-initial, ZIP3-plus-DOB-month-day, SSN-last-four-plus-year-of-birth, prior-cross-org-id) is the right standard production set. The matcher-returns-more-than-a-match-decision framing (the score breakdown, the categorical reason, the data-release decision separated from the match decision) is the recipe's strongest single audit-trail primitive. The consent-consulted-at-release-time-not-at-query-time framing is the chapter's clearest articulation of why the matcher's accuracy must not be polluted by consent-driven bias. The audit-log-as-system-of-record framing in the General Architecture Pattern is the right elevation of the discipline. The cohort-stratified-accuracy-monitoring-with-cross-organizational-variance framing is the right operational hook into the chapter-wide equity discipline.

The Honest Take is the chapter's most operationally pointed section so far. Eight observations earn the recipe's voice: the gap-between-technology-and-operational-capacity framing (the bottleneck is the surrounding infrastructure of trust, consent, governance, and operational discipline rather than the technology), the matcher-as-program-not-as-system trap, the consent-layer-as-first-class-input vs. compliance-overhead trap, the equity-dimension-with-compounding-asymmetries observation, the audit-log-as-the-system observation specific to cross-facility (in 5.1 the audit trail is secondary; here it is the system), the discoverability-semantics-more-nuanced-than-most-teams-design-for observation (a query for "Maria Garcia, DOB 1972-03-14" that returns "no match" tells the requester something different than a query that returns "matched but consent does not permit release"), the trust-but-verify-toward-partner-matchers observation framed as quality-assurance-not-distrust, and the patient-facing-access-reports-as-feature-not-compliance-burden recommendation. The closing observations on IHE PIX/PDQ aging well, the FHIR-native-as-future-but-v2-as-load-bearing-for-several-years, and the 21st Century Cures Act information-blocking rules making the architecture a compliance asset are the right closing lines.

That said, four correctness-and-compliance gaps at HIGH severity need attention before publication, plus the chapter-pattern set of MEDIUM and LOW items. (1) The architecture invokes an inbound query API (PIX/PDQ and FHIR `$match`), an outbound query submitter to partner organizations or HIE intermediaries, a partner-response aggregator, a `release_and_audit` writer that mutates the audit log and emits the cross-facility event, and an invalidation pipeline consumed by 5.1, 5.7, the longitudinal-record-assembler, the patient-portal access-report generator, and the consent-management workflow; the identity-boundary checks on these paths are not specified at the architectural level. The recipe's own TODO at the General Architecture Pattern (referenced as Finding S1) names the gap and prescribes the fix at chapter-pattern grain, but the architecture text does not actually specify the boundary. The consequence is sharp here because the cross-facility match is the substrate the entire HIE participation depends on; a misrouted persist call corrupts the canonical audit log that the patient's right-to-know reads, that the partner's audit request reads, and that the wrong-patient-incident forensic reconstruction reads. (2) The `release_and_audit` operation performs five sequential writes (audit-log PutItem with conditional check, S3 raw archive write for the inbound payload, S3 raw archive write for the outbound payload, S3 curated write, EventBridge PutEvents emit) plus the synchronous response transmission, without `TransactWriteItems` wrapping or an outbox pattern; failures between the writes leave the audit log out of sync with the response that was sent and the event that downstream consumers receive. The recipe acknowledges this in an inline TODO at Step 5B that references the chapter pattern from 5.1 / 5.2 / 5.3 / 5.4 and correctly notes that "the audit log is the legal record of what was exchanged; any divergence between what was sent and what the audit log claims was sent is a compliance incident." The TODO names the gap; the architecture should architect the fix. The regulatory consequence is sharper here than in 5.1/5.2/5.3/5.4 because the recipe text itself elevates the audit log to "the system" in the Honest Take. (3) The cohort-stratified accuracy monitoring is invoked as required-here-too with explicit cohort enumeration in the prose (patients with non-dominant-culture naming conventions, patients with name changes that did not propagate to all organizations, patients whose households cross multiple participating-organization service areas) but the operational threshold values, per-axis aggregation, and disparity-metric definitions are not specified in the architecture text (an inline TODO at the General Architecture Pattern names the suggested values but they are not promoted). Same chapter pattern as 5.1/5.2/5.3/5.4 Finding A2; the cohort-distribution stakes are higher here because cross-facility match disparities can be larger than intra-organizational disparities (the demographic asymmetries compound), and the downstream consequences (missed records at the point of care, delayed care, charity-care eligibility errors propagating from 5.4 into 5.5, public-health reporting gaps) are concrete equity issues. (4) The discoverability semantics that the recipe text correctly elevates to "more nuanced than most teams initially design for ... most implementations get this wrong on the first pass and discover the issue when the first patient files a complaint" are not consistently honored in the pseudocode. Step 4B sets `discoverability_permitted` on the release decision only in the `consent_does_not_permit` branch; the `consent_expired` and `consent_registry_unavailable` branches do not set the field. Step 5A in `release_and_audit` checks `decision.discoverability_permitted == FALSE` to mask the response as `NO_MATCH`, falling through to `MATCHED_NOT_RELEASABLE` (which reveals that the patient is in the responder's system) when the field is missing. A patient whose consent has expired but whose discoverability permission was set to FALSE leaks the fact-of-being-seen-at-this-organization to the requester; a registry-unavailable case where we cannot confirm discoverability permission also leaks. The recipe text correctly diagnoses this as the canonical first-pass failure mode for HIE matchers; the pseudocode reproduces the failure mode the prose warns against.

Eleven chapter-wide patterns repeat (audit-log retention floor with Object Lock specifics, partner data-handling expectations and minimum-acceptable-matcher-quality contractual clauses, IAM ARN scoping, identity-boundary checks, governance SLA on threshold re-calibration, idempotency keys and DLQ topology, cross-recipe orchestration with 5.1 / 5.4 / 5.6 / 5.7 / 5.8 / 1.1 / 1.9 / 2.4 / 7.x, cohort PHI in CloudWatch dimensions, Lake Formation column-level access controls on the audit-archive analytics path, API Gateway resource policy and WAF posture with the additional enumeration-attack consideration specific to cross-facility queries, HIE/partner egress posture). Most are explicitly TODO'd in the recipe text; this review carries them forward at MEDIUM or LOW severity reflecting the chapter editor's eventual consolidation responsibility.

Voice is excellent. Em dash count: 0 (verified by counting U+2014 codepoints in the UTF-8 file). En dash count: 0 (verified by counting U+2013 codepoints in the UTF-8 file). The 70/30 vendor balance is maintained: AWS service names appear first in the AWS Implementation section after The Problem, The Technology, and General Architecture Pattern have been specified vendor-agnostically. CC voice is consistent throughout: the opening trauma-team vignette with the unconscious patient and the four organizations' partial records, the Maria Garcia / Maria Garcia-Lopez / M Garcia / Maria Elena Garcia running example carried into the wrong-patient-overlay vignette with the urgent care positive-pregnancy-test note that ends up in the wrong patient's chart, the seven you-are-running-X scenarios that establish the operational landscape (HIE operator, hospital clinical IT, oncology care coordination, state Medicaid quality measurement, public health immunization, TEFCA national network), the Sequoia Project / Carequality / TEFCA references at the right level of "this is what the field actually looks like" energy, and the closing IHE PIX/PDQ-as-aged-well plus 21st-Century-Cures-Act-as-load-bearing observations. Parenthetical asides land well. The Variations and Extensions section (FHIR-native query, TEFCA QHIN exchange, patient-mediated identity, privacy-preserving cross-facility matching, care-transition-aware match prioritization, multi-organization longitudinal-record assembly with provenance, patient-controlled query authorization, public-health reporting variant, insurance-coverage-aware matching, active-learning threshold tuning, partner-organization quality scorecard) is well-scoped and frames each extension at the right grain.

Priority breakdown: 0 critical, 4 high, 9 medium, 9 low. **The verdict is FAIL** because 4 HIGH findings exceed the > 3 = FAIL threshold. Three HIGH findings are localized correctness-and-compliance gaps that surface in well-specified prose and TODO comments elsewhere in the recipe and require the pseudocode and the architecture to be brought into alignment with the prose; the fourth (the discoverability-permitted field handling in the consent-expired and registry-unavailable branches) is a recipe-specific bug in the pseudocode where the prose correctly diagnoses the failure mode and the code reproduces it. None require structural rework of the recipe; the underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent.

---

## Stage 1: Independent Expert Reviews

## Security Expert Review

### What's Done Well

- BAA called out explicitly with the appropriate framing across multiple partner types: AWS BAA, the HIE's BAA with Data Use and Reciprocal Support Agreement (DURSA-style) or equivalent Common Agreement, each direct-partner-organization connection requiring its own trading partner agreement and BAA, and TEFCA participation governed by the Common Agreement and the QHIN-specific subordinate agreements.
- Customer-managed KMS keys called out for the S3 buckets, the DynamoDB tables, the ElastiCache cluster, the Lambda log groups, and Secrets Manager. Encryption-in-transit named explicitly: *"TLS 1.2 or higher for all in-transit traffic, including HIE and partner connections. Mutual TLS where the partner or HIE requires it."*
- AWS Secrets Manager called out with the right framing for HIE and partner credentials, including mutual-TLS certificates, signing keys, and rotation support where the partner supports it.
- CloudTrail data events on the cross-org MPI table, the audit-log table, and on the audit S3 buckets. API Gateway and Lambda invocations logged.
- The audit-log archive bucket has Object Lock in Compliance mode for immutability. This is the right elevation for a recipe whose Honest Take elevates the audit log to "the system."
- AWS WAF and Shield called out specifically for the enumeration-attack surface: *"Cross-facility query endpoints are public-internet-reachable (or HIE-network-reachable) by definition, and they are attractive targets for enumeration attacks (an attacker submitting demographic guesses to discover whether a known person has records at the institution)."* This is the recipe's strongest single observation about the cross-facility query attack surface that distinguishes it from the earlier recipes' threat models.
- The fail-closed posture on consent-registry availability is correctly framed at the architectural level: *"the architecture treats consent-registry unavailability as a fail-closed condition (withhold release rather than release with stale consent state)."* The recipe correctly elevates this to a CloudWatch alarm and a documented dependency.
- The "Per-Lambda least-privilege" framing in the Prerequisites IAM Permissions row, with the explicit append-only-permissions-on-the-audit-log-table specification: *"The audit-log writer Lambda has append-only permissions on the audit-log table (no delete, no update on existing items) enforced through IAM condition keys plus DynamoDB resource-based policy."* The append-only-via-IAM-condition-keys plus resource-based-policy pattern is the recipe's strongest single audit-trail integrity primitive.
- Synthetic data labeling enforced in the Sample Data row: *"Never use real PHI in development environments."* Synthea correctly named with multi-organization encounter histories, plus the Sequoia Project and ONC patient-matching test datasets.
- The 42 CFR Part 2 sensitivity filter is correctly elevated to a first-class concern, with the architecture filtering data by sensitivity category and the audit trail recording what was filtered and why. The Dobbs-related reproductive-health-information sharing constraints are correctly flagged as part of the moving regulatory landscape.

### Finding S1: Inbound Query Endpoint, Outbound Submitter, Consent-and-Sensitivity Filter, Audit-Log Writer, and Cross-Recipe Invalidation Consumers Lack Identity-Boundary Specification

- **Severity:** HIGH
- **Expert:** Security (PHI integrity boundary, authorization, regulatory)
- **Location:** Architecture diagram shows the inbound path `I1/I2/I3 (HIE / FHIR $match / PIX/PDQ) -> AG1 (API Gateway) -> Q1 (SQS realtime) -> L1 (normalize-query) -> L2 (evaluate-match) -> L3 (apply-consent-and-sensitivity) -> L4 (release-and-audit)`; the outbound path `L4 -> L5 (outbound-query-submitter) -> NAT1 -> EXT1 (Partner Org / HIE Intermediary) -> L6 (aggregate-partner-responses) -> L4`; the invalidation path `EB1 -> L7 (invalidate-on-event)`. Step 1 pseudocode `ingest_query(inbound)` calls `verify_requester_identity(inbound)` and `is_purpose_of_use_permitted(principal, query.purpose_of_use)` but the architecture text does not specify what those functions enforce. Step 5 pseudocode `release_and_audit(query)` writes the audit log and the EventBridge event without a specified caller-context check. The recipe's own TODO at the General Architecture Pattern (referenced as "Expert review S1 (HIGH)") names the gap and prescribes the chapter-pattern fix but the architecture text does not actually specify the boundary.
- **Problem:** The recipe specifies the cross-facility pipeline at flow-and-service granularity but is silent on the identity-boundary policy that controls who can invoke each path and what proves the caller is authorized to act on a particular patient record. The chapter-wide pattern from 4.4 through 5.4 has converged on a structured identity-boundary specification; Recipe 5.5 inherits the concern with five concrete attack surfaces:

  1. **The inbound API Gateway endpoint accepts queries from HIE intermediaries and partner organizations.** The recipe correctly notes that "API Gateway provides authentication via mutual TLS (the HIE participation agreement specifies certificate-based identity for queriers), request logging, request signing verification, and rate limiting per requester." But the architecture text does not specify what mTLS verifies (the certificate must be on the HIE participation roster, with revocation-list checking on every connection), what signed-JWT alternative is acceptable (signing keys from a known partner-issued key store, with key rotation aligned to the partner's rotation schedule), how the asserted purpose-of-use is bound to the authenticated principal (the principal's HIE participation roster entry specifies which purposes-of-use the principal may assert; mismatches reject), or how rate limits are scoped (per-principal, per-source-IP, per-data-category). A forged JWT or a valid-but-rotated certificate accepted past its rotation window silently authorizes a query that was not actually issued by the asserted principal.

  2. **The outbound query submitter signs queries with the institutional credential and verifies response signatures from participating organizations.** Step 5F pseudocode `transmit_response(query, response_payload)` is the corresponding outbound path for inbound queries; the architecture diagram also shows `L5 (outbound-query-submitter)` for queries originated by the local clinician. The architecture text does not specify the signing-key management (where the institutional signing key lives, how it rotates, who has access), the response-signature-verification policy (do we accept responses from partners we have not issued a query to, do we reject responses with control-number mismatches against our outstanding queries), or the replay-rejection on outbound-query-response correlation. The recipe's TODO names "sign queries with the institutional credential, verify response signatures from participating organizations" but the architecture text does not include the specification.

  3. **The consent-and-sensitivity filter is the most security-sensitive component in the recipe.** The recipe text correctly elevates this to fail-closed-on-registry-unavailability and to read consent state from the system-of-record on every release decision. But the architecture text does not specify whether the filter Lambda is invoked only from the `evaluate_match` Lambda's success path (preventing a misrouted invocation that could bypass the consent check), whether the filter's read-from-system-of-record is bounded by a timeout that fails closed on slow reads (vs. only on hard failures), or whether the cache-of-consent-state in ElastiCache is invalidated synchronously on a consent-revocation event (the recipe correctly notes in the ElastiCache paragraph that "consent reads must fall through to the system-of-record on miss" but does not specify the invalidation timing on consent revocation). The recipe's TODO names the filter as "the most security-sensitive component" but the architectural specification of how the filter is protected against misrouted invocation and stale-cache-data is not present.

  4. **The audit-log writer is the system of record for cross-organizational data flow.** The recipe correctly elevates this to "non-negotiable" and to append-only-via-IAM-condition-keys-plus-resource-based-policy. But the architecture text does not specify the producer-signed-envelope pattern that the writer requires from upstream Lambdas (a forged event from a compromised `release_and_audit` Lambda, an attacker-controlled `requesting_principal.org_id` that masquerades as a different partner organization, an attacker-controlled `match_outcome` that claims a match that did not happen) silently links a forged audit record to a real query_id and corrupts the legal record the patient's right-to-know reads. The chapter-wide pattern from 4.4-5.4 has converged on the producer-signed envelope and the consumer-side signature validation; Recipe 5.5 should adopt the same pattern with the additional consideration that the audit log is more load-bearing here than in any earlier recipe.

  5. **The cross-recipe invalidation consumers in 5.1, 5.7, the longitudinal-record-assembler, the patient-portal access-report generator, and the consent-management workflow each receive cross-facility events through EventBridge.** The recipe correctly notes the fan-out but does not specify the producer-signed envelope on the event payload or the acceptance criteria each consumer enforces. A forged `cross_facility_match_invalidated` event from a compromised source could mass-invalidate cross-facility match decisions, force a flood of re-queries that exceed partner-organization rate limits, and produce a self-inflicted denial-of-service on the HIE infrastructure. A forged `cross_facility_query_resolved` event could feed false data into the longitudinal-record-assembler or the patient-portal access-report generator, producing wrong information shown to the patient.

  The HIPAA Privacy Rule's minimum-necessary requirement and the 21st Century Cures Act information-blocking rules both depend on the identity boundary. A read of the cross-org MPI or the audit log that exposes a patient's data flow to a caller without a need-to-know is a minimum-necessary violation; a query that succeeds without proving the calling principal is who they claim to be does not have the audit-trail attribution that compliance requires.

  Same regulatory ground as Recipe 5.1 / 5.2 / 5.3 / 5.4 Finding S1; the chapter editor should consolidate identity-check guidance into a chapter preface in the next pass since the same finding now applies across 4.4-5.5. For 5.5 specifically, the audit-log-as-system consequence (the recipe text itself elevates the audit log to "the system" in the Honest Take) earns the HIGH severity.

- **Fix:** Promote the recipe's own TODO content into the architecture text. Specify the identity-boundary policy and the rejection semantics at the architectural level the chapter has converged on. For the inbound endpoint, specify mTLS with revocation-list checking on every connection, signed-JWT acceptance from partner-issued key stores with rotation alignment, the participation-roster check binding the authenticated principal to permitted purposes-of-use, and per-principal-and-per-data-category rate limits. For the outbound submitter, specify the institutional signing-key management (rotation cadence, who has access, where it lives), the response-signature-verification policy (rejection of responses from partners we did not query, replay-rejection on `(outbound_query_id, partner_response_correlation_id)`), and the timeout that produces a fail-soft response when a partner does not respond within the latency budget.

  For the consent-and-sensitivity filter Lambda, specify the IAM execution-role binding (the filter Lambda's execution role is invoked only from `evaluate_match`'s success path; resource-based policy on the filter Lambda rejects invocations from any other principal), the system-of-record-read timeout (e.g., 500ms with fail-closed on slow reads, not only on hard failures), and the synchronous invalidation contract with the consent registry (when consent is revoked, the registry posts to an EventBridge event that the invalidation Lambda consumes synchronously to clear ElastiCache and to flag in-flight queries for re-evaluation; the cache TTL is a backstop, not a primary defense).

  For the audit-log writer, specify the producer-signed-envelope contract (every upstream Lambda that calls the writer signs the audit record with its execution-role credential; the writer validates the signature against the expected upstream principal and rejects mismatches with a logged metric and DLQ routing). The append-only IAM condition is correct as stated; the producer-signed envelope is the additional defense.

  For the cross-recipe invalidation events, specify the producer-signed envelope and the acceptance criteria each consumer enforces (consumer rejects events from sources not on its allow-list with a logged metric; rate-limiting on invalidation events to prevent mass-invalidation attacks).

  Reference Recipe 5.1 / 5.2 / 5.3 / 5.4 Finding S1 as the chapter pattern.

### Finding S2: Audit-Log Retention Specified as "Per the Regulatory Retention Floor" Without Explicit Floor (Chapter-Wide Pattern, Already Partially TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (regulatory, audit, forensic)
- **Location:** Prerequisites CloudTrail row: *"CloudTrail logs encrypted with KMS and retained per the regulatory floor."* The Why These Services audit-log paragraph: *"retain per the regulatory retention floor."* The recipe's own inline TODO at the CloudTrail row (referenced as "Expert review S2 (MEDIUM)") names the gap and prescribes the chapter-pattern fix but the architecture text does not include the specification.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding S2. The TODO correctly identifies that the floor should be the longest of (HIPAA 7-year minimum, HIE contractual retention, state's medical-records-retention requirement, 42 CFR Part 2 retention requirement where Part 2 data is in scope, and any sensitive-category-specific retention), with Object Lock in Compliance mode on a dedicated audit bucket and CloudTrail data events forwarded to a dedicated audit AWS account. Three concrete consequences are recipe-specific:

  1. **42 CFR Part 2 retention is recipe-specific.** Part 2 has its own retention requirements separate from HIPAA. Cross-facility queries that touch Part 2 data (substance use disorder records) are governed by the Part 2 retention floor, which can extend the audit-retention window beyond the HIPAA minimum. The architecture should reflect this explicitly given the recipe's elevation of 42 CFR Part 2 to a first-class sensitivity-filter category.

  2. **HIE contractual retention can extend beyond statutory minimums.** HIE participation agreements often include audit-retention obligations (commonly 7-10 years, sometimes longer for specific data categories) that the institution cannot unilaterally shorten. The architecture should treat the participation agreement as architecture-level input, not as paperwork (the recipe text says exactly this in the Why-Not-Production-Ready section).

  3. **Object Lock in Compliance mode is correctly specified for the audit-archive bucket.** This is the recipe's strongest single retention-integrity primitive and is correctly elevated. The TODO names a dedicated audit AWS account with isolation from the production data plane; this is the chapter pattern.

- **Fix:** Replace the "per the regulatory retention floor" framing with an explicit floor in the CloudTrail and Audit-Trail-Retention paragraphs, mirroring the chapter pattern from 5.1 / 5.2 / 5.3 / 5.4:

  *"Audit-log retention is the longest of: 7 years (HIPAA records-retention minimum), the HIE's contractual retention (typically 7-10 years, specified in the participation agreement), the state's medical-records-retention requirement, the 42 CFR Part 2 retention requirement where Part 2 data is in scope, and any sensitive-category-specific retention. Audit logs (the raw query and response payloads, the parsed match decisions, the consent-check results, the release-and-withhold records, the deferred-review-queue decisions) are stored in a dedicated S3 bucket with Object Lock in Compliance mode for immutability and a lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days for cost optimization. CloudTrail data events are forwarded to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. The retention floor is enforced at the bucket-policy and Object-Lock-configuration level, not at application logic."*

### Finding S3: HIE and Direct-Partner Data-Handling Expectations Named in TODO but Not Architecturally Specified

- **Severity:** MEDIUM
- **Expert:** Security (third-party-risk, PHI flow, minimum-acceptable-matcher-quality)
- **Location:** Prerequisites BAA row and the recipe's inline TODO (referenced as "Expert review S3 (MEDIUM)"). The TODO names the contractual expectations including (a) retention windows with no-match audit-only obligation, (b) sub-processor disclosure, (c) incident notification, (d) audit rights, (e) minimum acceptable matcher quality (cohort-stratified accuracy thresholds). The architecture text does not include the specification.
- **Problem:** The recipe correctly identifies that the HIE and each direct-partner connection see PHI (the query payload contains the patient's demographics; for inbound queries, the responder learns the requester is asking about a specific demographic profile, which itself is sensitive) and must sign BAAs with trading partner agreements. The TODO names the data-handling expectations but the architecture text does not specify what the institution should require contractually or verify operationally. Five concrete consequences:

  1. **Queries that return no match should produce no persistent record on the partner side beyond the audit log.** A query for "Maria Garcia, DOB 1972-03-14" that returns "no match" still tells the responder the institution was asking; the responder should not be free to retain that demographic profile for any other purpose. The trading partner agreement should specify this contractually.

  2. **Sub-processor disclosure for HIE intermediaries is layered.** An HIE that uses cloud-infrastructure providers, sub-vendors for connectivity to specific partners, sub-vendors for analytics, sub-vendors for sensitivity-filter rule maintenance is a chain of PHI-exposure surfaces. The BAA should require sub-processor disclosure and the institution's right to object.

  3. **Incident notification windows are recipe-specific.** A wrong-patient release at the HIE layer is a more consequential incident than at the eligibility-matching layer (recipe 5.4) because the wrong-patient release produces clinical-safety incidents (a wrong-patient overlay in the consuming organization's chart, missed allergies, wrong allergies, medication-list confusion). The notification window should be tighter than the standard HIPAA 60-day breach notification (typically 24-72 hours for incidents of this severity).

  4. **Audit rights matter more here than in earlier recipes.** The HIE participation agreement should specify the institution's right to audit the HIE's matcher (typically annually) including cohort-stratified accuracy benchmarking against shared gold sets. This converts a hand-wave ("we trust the HIE") into a measurable obligation.

  5. **Minimum acceptable matcher quality is an emerging contractual requirement.** The recipe text correctly notes that "the aggregating side typically applies its own confidence threshold to the responder's score, treating the responder's match decision as one signal among several. This is increasingly being formalized in HIE policy as 'minimum acceptable matcher quality' requirements rather than left to ad-hoc per-querier reinterpretation." The participation agreement should specify the floor (cohort-stratified accuracy thresholds, partner-side review-queue depth and aging, downstream wrong-patient-retrieval rates) below which the institution may suspend the partner connection or escalate to the HIE governance committee.

- **Fix:** Promote the TODO content into the BAA row:

  *"HIE and direct-partner BAA terms should specify: (a) the partner will not retain queried demographics beyond a documented operational window (queries that returned no match should produce no persistent record on the partner side beyond an audit-log entry; queries that returned a match should not retain the requesting institution's demographic profile beyond what is needed for response correlation and the audit window); (b) the partner will disclose all sub-processors that may handle PHI (including cloud-infrastructure providers, sub-vendors for specific partner connectivity, sub-vendors for analytics, sub-vendors for sensitivity-filter policy maintenance); (c) the partner will notify the institution within a tight window (typically 24-72 hours for cross-facility incidents given the clinical-safety dimension) of any data incident affecting institutional data; (d) the partner agreement specifies the institution's right to audit the partner's controls (typically annually, including cohort-stratified matcher-quality benchmarking against shared gold sets); (e) the partner commits to a minimum acceptable matcher quality (cohort-stratified accuracy thresholds, partner-side review-queue depth and aging, downstream wrong-patient-retrieval rates) below which the institution may suspend the partner connection or escalate to the HIE governance committee."*

  Add an inline comment at the outbound-query call site (Step 5F or earlier) explaining the trust boundary (we sign queries with the institutional credential, we verify response signatures, we cap the partner's confidence with our own threshold).

### Finding S4: Deferred-Review-Queue Decision Audit Posture Underspecified (Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Security (privacy, forensic-traceability, equity)
- **Location:** Step 3D pseudocode where deferred-review-band cases get queued via `SQS.SendMessage("deferred-review-queue", ...)`, plus the Why-This-Isn't-Production-Ready Deferred-review tooling paragraph. The recipe's inline TODO at the Why-This-Isn't-Production-Ready section (referenced as "Expert review S4 (MEDIUM)") names the audit fields but the architecture text does not include the specification.
- **Problem:** The matcher's accuracy depends on the deferred-review queue's quality. Reviewers (typically health information management staff with HIE-specific training) make decisions that mutate the cross-org MPI via the same persistence path that auto-accept uses; the audit trail must capture the reviewer's identity, decision, reasoning, and the configuration version at decision time. Three concrete consequences:

  1. **Forensic reconstruction of wrong matches is impossible without reviewer-decision audit.** When a wrong cross-facility match later surfaces (a wrong-patient overlay in the consuming organization's chart, a misfiled CCD, a missed allergy traceable to a mismatched record) and the trail leads back to a reviewer's decision in the deferred-review queue, the audit trail should record who decided what, why, and against which configuration. Without this, the institution cannot defend the decision to a regulator, cannot demonstrate due diligence, and cannot identify systematic reviewer biases.

  2. **The reviewer's stated reasoning supports active learning.** The "active-learning-driven threshold tuning" variation depends on the reviewer's labels feeding back into threshold re-calibration; without a structured reasoning capture, the labels are decisions without context, which is less useful for re-training and produces threshold updates whose rationale cannot be traced.

  3. **Conflict-of-interest cases matter more here than in earlier recipes.** Cross-facility queries can include the reviewer's own family members, the reviewer's neighbors, the reviewer's coworkers (the HIE serves a population that overlaps with the reviewer's social network). The chapter pattern from 5.1 / 5.3 / 5.4 applies here with additional weight: a reviewer adjudicating a cross-facility match for someone they know personally is a conflict-of-interest; the chapter pattern includes a pre-assignment check against an institutional conflict-of-interest registry.

- **Fix:** Promote the TODO content into the architecture text:

  *"Every deferred-review-queue decision records: the reviewer's identity (with appropriate authentication), the decision (confirm-match-and-update-MPI, reject-as-different-person, escalate, request-additional-information-from-the-querying-organization), the reviewer's stated reason, the timestamp, the configuration version active at the time, the threshold values active at decision time, and any reviewer-supplied additional demographic context. The audit trail supports forensic reconstruction when a wrong match is later traced back to a reviewer decision, and it supports the periodic gold-set re-evaluation that catches systematic reviewer biases. Conflict-of-interest cases (a reviewer adjudicating a cross-facility match for someone in their personal network) are surfaced by a pre-assignment check against an institutional conflict-of-interest registry; conflicted cases route to a different reviewer."*

### Finding S5: Cohort PHI in CloudWatch Metric Dimensions (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Step 3E pseudocode `emit_cloudwatch_metric_with_cohort("cross_facility_match_outcome", match_outcome.status, cohort_bucket)`. The General Architecture Pattern paragraph naming per-cohort match success rate. The recipe's inline TODO (referenced as "Expert review S5 (LOW)") names the bucketed-non-reversible-cohort-label pattern.
- **Problem:** Same chapter-wide pattern as 4.4-5.4 Finding S5. The TODO already specifies the right pattern (cohort_bucket = A, B, C, D, E, unknown, with the cohort-label-to-attribute mapping in a separate access-controlled table loaded only at dashboard-render time).
- **Fix:** Promote the TODO content into the CloudWatch paragraph: *"Cohort dimensions on metrics use bucketed, non-reversible cohort labels (cohort_bucket = A, B, C, D, E, unknown) from the institutional cohort registry rather than raw demographic attributes; the cohort-label-to-attribute mapping lives in a separate access-controlled table loaded only at dashboard-render time."*

### Finding S6: IAM "Never `*` Actions or `*` Resources in Production" Stated Without Scoped ARN Examples (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Security
- **Location:** Prerequisites IAM Permissions row. The recipe's inline TODO (referenced as "Expert review S6 (LOW)") names the chapter pattern and specifies the scoped ARN examples but the architecture text does not include the specification.
- **Problem:** Same finding as Recipe 4.1-5.4.
- **Fix:** Inline the scoped ARN examples for the highest-stakes actions: `dynamodb:UpdateItem` on `arn:aws:dynamodb:<region>:<account>:table/cross-org-mpi`; `s3:PutObject` on `arn:aws:s3:::<env>-cross-facility-raw/audit/*`; `events:PutEvents` on `arn:aws:events:<region>:<account>:event-bus/cross-facility-events`; `secretsmanager:GetSecretValue` on `arn:aws:secretsmanager:<region>:<account>:secret:hie-partners/*`. Or consolidate into the chapter preface.

### Finding S7: Patient-Mediated Identity Disclosure Posture for Variations Section Not Addressed

- **Severity:** LOW
- **Expert:** Security (forward-looking, disclosure-policy)
- **Location:** Variations and Extensions, "Patient-mediated identity resolution" subsection: *"For patient-facing apps that authenticate via OAuth/OIDC against a known identity provider (the patient's portal account, a trusted aggregator like Apple Health Records, or a CMS-defined identity layer), use the patient's authenticated identity as a strong signal in the matcher."*
- **Problem:** The variation correctly identifies the operational opportunity but does not name the disclosure-policy gate. A patient-mediated identity that the matcher accepts as authoritative also creates a data-egress channel (the patient's third-party app can pull records under the patient's authority) that is governed by separate frameworks (CMS Patient Access API rules, the 21st Century Cures Act information-blocking provisions, state-specific app-disclosure rules in some jurisdictions). The variation should name the disclosure-policy gate analogous to the chapter pattern from 5.1 / 5.2 / 5.4 Finding S5 / S7.
- **Fix:** Add a sentence to the Patient-Mediated Identity Resolution variation: *"Before accepting a patient-mediated identity as authoritative for matcher input, the institution should review the disclosure policy: the data flowing under the patient's authenticated identity to the third-party app may be governed by separate disclosure-and-consent frameworks (CMS Patient Access API rules, the 21st Century Cures Act information-blocking provisions, state-specific app-disclosure rules in some jurisdictions); the matcher's acceptance of the identity does not automatically authorize the downstream app's data egress."*

## Architecture Expert Review

### What's Done Well

- **Six-stage pipeline shape is correct.** Ingest, normalize, evaluate-or-resolve-identity, consent-and-sensitivity-filter, persist-and-audit, invalidation-and-refresh maps cleanly to the operational reality. The trigger-source heterogeneity (inbound query, inbound linkage submission, outbound query from local clinician, periodic MPI reconciliation) is correctly handled by a single downstream pipeline with priority metadata.
- **Query-time vs. linkage-time match dichotomy is the recipe's strongest single architectural framing.** The decomposition into a real-time, stateless, latency-sensitive query-time matcher and an asynchronous, state-building linkage-time matcher (sharing the underlying scorer but differing in their architecture) is correct. The "Build the matcher as a service and call it from both directions, rather than duplicating logic" framing is the right operational discipline.
- **Multi-block union pattern is correctly elevated to the architectural prose.** Five blocking keys (last-name-phonetic-plus-year-of-birth, last-name-phonetic-plus-first-name-initial, ZIP3-plus-DOB-month-day, SSN-last-four-plus-year-of-birth, prior-cross-org-id) with the matcher unioning the candidate sets and scoring each candidate independently is the right standard production pattern.
- **The matcher returns more than a match decision.** The recipe correctly elevates the score breakdown, the categorical reason, and the data-release decision to first-class outputs separated from the match decision itself. "Cleanly separating 'we matched' from 'we released' matters for the audit trail and for correctly reporting to the patient what data was exchanged about them" is the recipe's strongest single audit-trail framing.
- **Consent is consulted at release time, not at query time.** The recipe correctly elevates this to an architectural pattern with a specific rationale: "this pattern lets the matcher's accuracy not be polluted by consent-driven bias (otherwise, patients who opt out of sharing would systematically not appear in match training data, distorting the matcher's calibration), and it lets the audit log accurately record that a query was made and that consent caused the release to be limited." This is the chapter's clearest articulation of the consent-as-first-class-input principle.
- **The audit log is the system of record.** The Honest Take's elevation of the audit log to "the system" is the right framing for cross-facility. The General Architecture Pattern paragraph correctly names the retention floor and the regulatory-grounding.
- **Cross-organizational match is event-driven on the maintenance side.** The recipe correctly identifies that the cross-org MPI's state must be invalidated on local-MPI events (5.1 merge / unmerge, 5.7 name change, 5.3 address change), on consent-revocation events, and on participating-organization onboarding/offboarding. The event-driven invalidation pattern is the chapter pattern.
- **Cohort-stratified accuracy monitoring with cross-organizational variance.** The recipe correctly identifies that cross-facility match accuracy can be worse than intra-organizational match accuracy for the same cohorts because the demographic asymmetries compound. This is the right framing for the chapter-wide equity-monitoring pattern.
- **API Gateway for the inbound endpoint with WAF and Shield.** The recipe correctly elevates the enumeration-attack surface specific to cross-facility queries. The PIX/PDQ-and-FHIR-`$match` shared-backend-logic pattern is the right operational compromise between regulatory-baseline coverage (v2 connectivity for partners that have not migrated) and forward-looking infrastructure (FHIR-native for new development).
- **Step Functions partitioning by workflow.** Query-time-match (latency-sensitive, with strict timeouts), linkage-submission (asynchronous, batch-friendly), MPI-reconciliation (periodic, operational drift detection) is the right separation of concerns.
- **Three SQS queue priorities.** High-priority for synchronous query-time, standard for asynchronous linkage-submission, deferred-review for the human-review band. Separating the queues prevents linkage-submission load from delaying query-time matching, which is the right priority isolation.
- **The Why-This-Isn't-Production-Ready section names twelve gaps.** HIE participation agreement, consent-registry selection, sensitivity-filter governance, threshold calibration governance, deferred-review tooling, longitudinal-record-assembly, outbound-query orchestration, patient-access-reports, initial-backfill, idempotency-and-retry, audit-retention, and operational ownership. The breadth is appropriate for a Medium-tier recipe with the operational complexity 5.5 carries.

### Finding A1: release_and_audit Is Not Atomic; Sequential DynamoDB / S3 / EventBridge / Response-Transmission Operations Leave the Audit Log Out of Sync with the Released Response

- **Severity:** HIGH
- **Expert:** Architecture (correctness, distributed-systems consistency, regulatory)
- **Location:** Step 5 pseudocode `release_and_audit(query)` performs `DynamoDB.PutItem("audit-log", audit_record, condition_expression="attribute_not_exists(query_id)")`, three S3 `write_to_s3` calls (raw inbound, raw outbound, curated), `EventBridge.PutEvents([...])`, and the synchronous `transmit_response(query, response_payload)` call to send the response back to the requester. The recipe's own inline TODO at Step 5B explicitly names the gap and notes the regulatory consequence: *"Wrap the audit-log write, the response transmission, the cache update, and the EventBridge emit in a TransactWriteItems plus an outbox row drained by a separate Lambda or DynamoDB Streams consumer so partial failures do not leave the audit log out of sync with the released response. Regulatory consequence here is sharp: the audit log is the legal record of what was exchanged; any divergence between what was sent and what the audit log claims was sent is a compliance incident. Same chapter pattern as 5.1, 5.2, 5.3, 5.4."*
- **Problem:** The chapter pattern from 5.1 Finding A1 / 5.2 Finding A1 / 5.3 Finding A1 / 5.4 Finding A1 applies. Sequential operations across DynamoDB, S3, EventBridge, and the synchronous response-transmission each have independent failure modes. The recipe text itself elevates the audit log to "the system" in the Honest Take ("In recipe 5.1, the audit trail is important but secondary. In recipe 5.5, the audit trail is the system"); a divergence between the audit log and the response that was actually sent is the most severe correctness failure the architecture could produce. Concrete failure scenarios:

  1. **Audit-log write succeeds, S3 raw archive fails.** The audit log claims the query was processed and the response was constructed; the immutable raw payload archive has no corresponding inbound or outbound payload. A subsequent compliance reconstruction (a regulator, a partner, or the patient asks "what was sent in response to query Q") can read the audit log's metadata but cannot retrieve the exact payload. The recipe's claim that "the raw payloads are retained for the regulatory retention floor" is silently false for this query.

  2. **Audit-log and S3 writes succeed, EventBridge emit fails.** The audit substrate is durable but downstream consumers (longitudinal-record-assembler, patient-portal access-report generator, consent-management workflow, local patient matcher 5.1, longitudinal name-change matcher 5.7, privacy-preserving linkage 5.8) never receive the change event and continue to operate on prior state. The patient-portal access report fails to surface the query for the patient's right-to-know read; the longitudinal-record-assembler does not refresh; cross-recipe consumers in 5.1 and 5.7 do not see the cross-facility signal that may surface a previously-unknown internal duplicate or a name-change pattern.

  3. **Audit-log, S3, and EventBridge writes succeed, transmit_response fails.** The audit log claims the response was sent; the response was not actually delivered. The requester's clinician does not see the data, retries, and produces a duplicate query. The audit log shows two queries with a single response delivered. The patient's right-to-know report shows two queries that both released data; in fact only one delivered. This is the worst variant of the divergence because the audit-log-to-actual-delivery direction is the one the patient and the regulator both rely on.

  4. **transmit_response succeeds, then audit-log write fails.** The response is delivered to the requester (data has flowed across the cross-organizational boundary, irreversibly) but the audit log has no record. The institution cannot answer "did we release data on date X for query Q" with a yes; the patient's right-to-know report does not show the query. This is a compliance incident the institution cannot defend.

  5. **For linkage submissions: audit-log write succeeds, the cross-org MPI update fails.** The audit log claims the linkage submission was processed; the MPI does not reflect the new identity. Future queries against the MPI miss the just-submitted record; the responder's `$match` query returns "no match" for a patient who is, in fact, in the MPI. The audit log is the only record that the submission was received, but it claims an MPI state that does not exist.

  6. **The invalidation-on-event Lambda has the same problem.** Step 6 `invalidate_on_event(event)` writes to DynamoDB (`UpdateItem` on cross-org-mpi for various event sources), invalidates the consent cache, and emits an aggregated `cross_facility_match_invalidated` EventBridge event. A failure between the cache invalidation and the EventBridge emit leaves the cache in a known-clean state but downstream consumers still hold the stale cross-facility match metadata in their local stores. A failure between the DynamoDB update and the EventBridge emit leaves the MPI updated but the longitudinal-record-assembler not refreshed.

  The regulatory consequence here is sharper than 5.1/5.2/5.3/5.4 because the recipe text itself elevates the audit log to "the system" in the Honest Take. The recipe's own TODO names this as a "compliance incident" if the audit log diverges from what was sent; the architecture should architect the fix.

- **Fix:** Specify the transactional pattern in the General Architecture Pattern paragraph and rewrite Step 5. Per the chapter pattern from 5.3 Finding A1 / 5.4 Finding A1, with the additional consideration that the response transmission is the irreversible side effect:

  ```
  FUNCTION release_and_audit(query):
      decision = query.release_decision
      response_payload = construct_response_payload(query, decision)

      // Compose a TransactWriteItems that writes the audit
      // record AND an outbox row for the side effects.
      DynamoDB.TransactWriteItems([
          {
              Put: {
                  TableName: "audit-log",
                  Item: { ... full audit record ... },
                  ConditionExpression:
                      "attribute_not_exists(query_id)"
              }
          },
          {
              Put: {
                  TableName: "cross-facility-outbox",
                  Item: {
                      outbox_id: uuid(),
                      query_id: query.query_id,
                      event_type: "release_pending",
                      response_payload_ref: <S3 key planned>,
                      eventbridge_payload: <event detail>,
                      transmit_target: query.requester_endpoint,
                      transmit_payload: response_payload,
                      created_at: current UTC timestamp,
                      status: "PENDING"
                  }
              }
          }
      ])

      // A separate outbox-drainer Lambda (triggered by DynamoDB
      // Streams on cross-facility-outbox) handles the S3 writes,
      // the EventBridge emit, and the transmit_response side
      // effect. The drainer is idempotent at outbox_id and
      // marks rows COMPLETED only after all downstream effects
      // succeed; failures route to a DLQ for operator inspection.
      // CloudWatch alarm fires when a pending row's age exceeds
      // an SLA (typically seconds for query-time releases given
      // the latency budget; minutes for linkage-submission
      // releases).

      // CRITICAL: transmit_response is the irreversible side
      // effect. The drainer transmits exactly once after the
      // audit row is durable; on transmit failure, the drainer
      // does NOT retry blindly (a partner-side receiver may have
      // received the response but failed to acknowledge), it
      // routes to the operator-review DLQ where a human
      // operator confirms whether to retry or to mark the
      // outbox row TRANSMITTED with a reconciliation note.
  ```

  For Step 6 (`invalidate_on_event`), wrap the cache invalidation, the DynamoDB updates, and the EventBridge emit in the same outbox pattern. The cache-invalidation-without-event-emit partial-failure mode is consequential because downstream consumers do not see the invalidation signal and continue to hold stale state.

  Reference Recipe 5.1 / 5.2 / 5.3 / 5.4 Finding A1 as the chapter-wide pattern. The chapter editor should consolidate the outbox-pattern guidance into a chapter preface in the next pass.

### Finding A2: Cohort-Stratified Accuracy Thresholds and Metric Definitions Referenced as "Required Here Too" but Undefined (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** HIGH
- **Expert:** Architecture (operational rigor, equity instrumentation)
- **Location:** General Architecture Pattern paragraph: *"Cohort-stratified accuracy monitoring applies here too, with cross-organizational variance. Match accuracy is not uniform across patient cohorts, and cross-facility match accuracy can be worse than intra-organizational match accuracy for the same cohorts because the demographic asymmetries (different organizations capturing different fields differently) compound. Per-cohort match success rate, per-cohort review-queue rate, and per-cohort downstream-error rate (clinician-reported wrong-patient retrieval, mistakenly-filed cross-org documents) all need monitoring with disparity thresholds."* The Honest Take's *"Cross-facility match disparities can be larger than intra-organizational disparities because the demographic asymmetries compound"*. The recipe's inline TODO (referenced as "Expert review A2 (HIGH)") names the suggested values but the architecture pattern does not promote them.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding A2. The recipe explicitly inherits the rigor from 5.1 / 5.2 / 5.3 / 5.4 ("required here too") and the inline TODO names the suggested values (match-success disparity > 0.05 = MEDIUM, review-queue disparity > 0.05 = MEDIUM, downstream wrong-patient disparity > 0.01 = HIGH for clinical safety) but the architecture pattern does not specify them in the prose. Five concrete gaps:

  1. **The cohort axis enumeration that the metric must aggregate over is not specified.** Patients with non-dominant-culture naming conventions, patients with name changes that did not propagate to all organizations, patients whose households cross multiple participating-organization service areas are named in the prose; the architecture should specify the institutional cohort registry as the source of truth and require the metric pipeline to aggregate over the registry's cohort axes rather than over an ad-hoc list (the inline TODO names this but the architecture does not).

  2. **The disparity calculation method is not specified.** "Disparity threshold of 0.05" can mean absolute difference between best and worst cohort, or ratio, or maximum deviation from the population mean. The three calculations produce different alerting behavior.

  3. **The metric pipeline's emission cadence is not specified.** Match-success rate moves slowly; review-queue rate can shift quickly when a partner-side change introduces new asymmetric capture conventions (a partner upgrades their EHR and starts capturing names with different conventions; the cohort-stratified review-queue rate spikes for affected cohorts within a week). The cadence should be specified per-metric.

  4. **The downstream wrong-patient-retrieval metric is recipe-specific and consequential.** Cross-facility match disparities translate to clinical-safety-affecting wrong-patient retrievals (a wrong-patient overlay in the consuming organization's chart, a misfiled CCD, a missed allergy traceable to a mismatched record). The TODO suggests a 0.01 HIGH threshold for downstream wrong-patient disparity (lower than the match-success threshold because clinical safety stakes are higher), which is the right metric but the architecture does not promote it.

  5. **The remediation pathway is not architected.** A threshold crossing should trigger a documented sequence: alert routing (HIE quality committee, clinical safety, equity-monitoring committee), investigation (per-cohort threshold tuning, expanded synonyms and prior-name handling, partner-organization quality scorecard review), and post-mortem retention. The TODO names the SLA and the cohort-disparity ledger but the architecture does not include these.

  The cohort-distribution stakes are higher here than in 5.1/5.2/5.3/5.4 because cross-facility match disparities translate to clinical-safety incidents, missed records at the point of care, delayed care, charity-care eligibility errors propagating from 5.4 into 5.5, and public-health reporting gaps for affected cohorts.

- **Fix:** Specify in the General Architecture Pattern paragraph the operational thresholds, the per-axis aggregation policy, and the remediation pathway, mirroring the chapter pattern from 5.1 / 5.2 / 5.3 / 5.4 Finding A2:

  *"Cohort-stratified accuracy monitoring uses the institutional cohort registry as the source of truth for cohort axes (no ad-hoc enumeration in code). Metrics: (a) per-cohort cross-facility match success rate (percent of inquiries returning AUTO_ACCEPT_HIGH or AUTO_ACCEPT_MED) computed weekly; (b) per-cohort review-queue rate (percent routed to deferred review) computed weekly; (c) per-cohort clinician-reported wrong-patient-retrieval rate (downstream metric tying matcher quality to clinical safety) computed monthly; (d) per-cohort document-misfiling rate computed monthly. Disparity calculation: absolute difference between the cohort with the highest rate and the cohort with the lowest rate, computed per-metric per-cycle. Alarm thresholds: match-success disparity > 0.05 = MEDIUM; review-queue disparity > 0.05 = MEDIUM; downstream wrong-patient disparity > 0.01 = HIGH (clinical safety); document-misfiling disparity > 0.01 = HIGH; any disparity > 2x the threshold = HIGH. Alarms route to the HIE quality committee, the clinical safety team, and the equity-monitoring committee with a 5-business-day SLA for the first investigation report; the post-mortem and any remediation (per-cohort threshold tuning, expanded synonyms and prior-name handling, partner-organization quality scorecard review) is documented in the cohort-disparity ledger and reviewed quarterly by the cross-facility-data-quality steering committee."*

  Reference Recipe 5.1 / 5.2 / 5.3 / 5.4 Finding A2 as the chapter-wide pattern.

### Finding A3: Discoverability-Permitted Field Inconsistently Set in Step 4; Step 5 Falls Through to MATCHED_NOT_RELEASABLE on Consent-Expired and Registry-Unavailable Branches

- **Severity:** HIGH
- **Expert:** Architecture (correctness, recipe-specific privacy semantics)
- **Location:** Step 4B `apply_consent_and_sensitivity` pseudocode sets `discoverability_permitted` only in the `consent_does_not_permit` branch:

  ```
  IF NOT consent_state.is_exchange_permitted:
      query.release_decision = {
          release: FALSE,
          reason: "consent_does_not_permit",
          consent_state_summary: consent_state.summary,
          discoverability_permitted: consent_state.discoverability_permitted
      }
      RETURN query

  IF consent_state.expires_before(query.received_at):
      query.release_decision = {
          release: FALSE,
          reason: "consent_expired",
          consent_state_summary: consent_state.summary
          # Note: discoverability_permitted NOT set here
      }
      RETURN query
  ```

  And the registry-unavailable catch:

  ```
  CATCH consent_registry_unavailable:
      query.release_decision = {
          release: FALSE,
          reason: "consent_registry_unavailable",
          should_retry: TRUE
          # Note: discoverability_permitted NOT set here
      }
      RETURN query
  ```

  Step 5A in `release_and_audit` then applies the discoverability mask:

  ```
  IF decision.release:
      ...
  ELIF decision.discoverability_permitted == FALSE:
      response_payload = {match_status: "NO_MATCH"}
  ELSE:
      response_payload = {
          match_status: "MATCHED_NOT_RELEASABLE",
          withhold_reason: decision.reason
      }
  ```

- **Problem:** When `discoverability_permitted` is missing on the decision (consent_expired or consent_registry_unavailable branches), the comparison `decision.discoverability_permitted == FALSE` evaluates as not-equal-to-FALSE (the field is absent or NULL, not specifically the boolean FALSE), so the ELIF is FALSE and the code falls through to the ELSE branch, returning `MATCHED_NOT_RELEASABLE`. This response reveals that the patient is in the responder's system. The recipe's Honest Take correctly diagnoses this as the canonical first-pass failure mode for HIE matchers:

  > *"The thing about the discoverability semantics: it is more nuanced than most teams initially design for. 'Patient is in our system' is, itself, sensitive information. A query for 'Maria Garcia, DOB 1972-03-14' that returns 'no match' tells the requester something different than a query that returns 'matched but consent does not permit release.' In some frameworks, the difference between those two responses leaks information that the patient did not consent to share (the fact of being seen at this organization, even without the clinical detail). The discoverability flag in the consent registry controls this, and the responder's match-and-release pipeline has to honor it. Most implementations get this wrong on the first pass and discover the issue when the first patient files a complaint about it."*

  The pseudocode reproduces the exact failure mode the prose warns against. Three concrete consequences:

  1. **Consent-expired with discoverability_permitted=False leaks fact-of-care.** A patient whose consent has expired (a common operational state, given that consents are typically time-limited and renewals lag) but whose original consent was set to non-discoverable (a reasonable choice for sensitive-care patients) has the responder reveal "MATCHED_NOT_RELEASABLE" to a requester who should not learn the patient was ever seen at this organization.

  2. **Registry-unavailable leaks fact-of-care.** When the consent registry is unreachable (the recipe correctly elevates this to a fail-closed condition for release), the architecture has no consent state to read; it cannot confirm discoverability_permitted=True or False. The fail-closed posture should extend to discoverability: if we cannot confirm discoverability_permitted=True, we must mask as NO_MATCH. The current pseudocode does the opposite, leaking that the patient is in our system.

  3. **The fail-closed semantics on the discoverability dimension are not stated.** The recipe's prose correctly elevates fail-closed-on-release; it does not extend the same posture to discoverability. The architecture should state explicitly that discoverability defaults to FALSE when not affirmatively known to be TRUE.

  This is a recipe-specific architectural error, not a chapter-wide pattern. The recipe's prose explicitly warns that this is the canonical first-pass failure mode, and the pseudocode reproduces it exactly. The HIGH severity reflects the recipe-internal contradiction and the regulatory risk (some states' consent frameworks specifically require non-disclosure of fact-of-care for non-consenting patients; the leak is a compliance incident).

- **Fix:** Update the Step 4 pseudocode to set `discoverability_permitted` on every non-release branch with a fail-closed default, and update the Step 5 comparison to treat missing/null as FALSE (mask as NO_MATCH):

  ```
  # Step 4: in every non-release branch, set discoverability_permitted
  # with a fail-closed default. If the consent state has it,
  # use that value; if not, default to FALSE.

  IF NOT consent_state.is_exchange_permitted:
      query.release_decision = {
          release: FALSE,
          reason: "consent_does_not_permit",
          consent_state_summary: consent_state.summary,
          discoverability_permitted:
              consent_state.discoverability_permitted IF
                  consent_state HAS discoverability_permitted
              ELSE FALSE  # Fail-closed default
      }
      RETURN query

  IF consent_state.expires_before(query.received_at):
      query.release_decision = {
          release: FALSE,
          reason: "consent_expired",
          consent_state_summary: consent_state.summary,
          discoverability_permitted:
              consent_state.discoverability_permitted IF
                  consent_state HAS discoverability_permitted
              ELSE FALSE  # Fail-closed default
      }
      RETURN query

  CATCH consent_registry_unavailable:
      query.release_decision = {
          release: FALSE,
          reason: "consent_registry_unavailable",
          should_retry: TRUE,
          discoverability_permitted: FALSE  # Fail-closed: we cannot
                                             # confirm discoverability
                                             # without the registry
      }
      RETURN query

  # Step 5: explicitly fail-closed on missing or non-TRUE
  # discoverability_permitted.
  IF decision.release:
      ...
  ELIF NOT (decision.discoverability_permitted == TRUE):
      # Discoverability not affirmatively permitted; mask as NO_MATCH
      # to avoid leaking fact-of-care.
      response_payload = {match_status: "NO_MATCH"}
  ELSE:
      # Discoverability permitted; the requester learns the patient
      # is in our system but data was not released.
      response_payload = {
          match_status: "MATCHED_NOT_RELEASABLE",
          withhold_reason: decision.reason
      }
  ```

  Add a paragraph to The Technology section explaining the fail-closed-on-discoverability posture: *"Discoverability defaults to FALSE when not affirmatively known to be TRUE. The system masks as NO_MATCH (the same shape as a true non-match) for consent-expired, registry-unavailable, and any other case where the consent registry's discoverability flag cannot be affirmatively read as TRUE. Fail-closed on discoverability is the same principle as fail-closed on release; both protect the patient from a leak the consent framework was designed to prevent."*

  Update the Honest Take's discoverability paragraph to reference the architectural specification (so the reader sees that the prose's warning is matched by the pseudocode's behavior).

### Finding A4: Idempotency Keys and DLQ Coverage Named in TODO but Not Architected (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** "Why This Isn't Production-Ready" idempotency paragraph: *"Use the query_id as the primary idempotency key for inbound queries. Use `(query_id, event_seq)` for the audit-log writes (event_seq sequences allow multiple lifecycle events on the same query without overwriting). Configure DLQs on every Lambda path; Step Functions Catch states route terminal failures to the DLQ so stuck workflows are visible."* The recipe's inline TODO at the same location (referenced as "Expert review A4 (MEDIUM)") names the recipe-specific keys but the architecture pattern does not include them.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding A4. The idempotency keys are correctly named in the production-gaps section but not specified in the architecture pattern, the pseudocode, or the Lambda configuration. The DLQ topology is not specified. The TODO names the recipe-specific keys (`normalize-query at query_id`; `evaluate-match at (query_id, matcher_config_version)`; `apply-consent-and-sensitivity at (query_id, consent_state_etag)`; `release-and-audit at (query_id, event_seq)`; `invalidate-on-event at (event_id)`) which is precisely the right granularity. The `(query_id, event_seq)` pattern for the audit-log allows multiple lifecycle events on the same query without overwriting (received, normalized, matched, consent-checked, released-or-withheld, completed) which is the right shape for an append-only audit log.
- **Fix:** Promote the TODO content into the General Architecture Pattern paragraph: *"Every Lambda invocation in the pipeline is idempotent at a recipe-specific key: normalize-query at `query_id`; evaluate-match at `(query_id, matcher_config_version)` (re-evaluation under a new config version is intentional and produces a new audit row, not an overwrite); apply-consent-and-sensitivity at `(query_id, consent_state_etag)` (re-evaluation under updated consent state is intentional); release-and-audit at `(query_id, event_seq)` (event_seq sequences allow multiple lifecycle events on the same query); invalidate-on-event at `event_id`. Each Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows within 15 minutes of accumulation."*

### Finding A5: Outbound Query Orchestration Fail-Soft Pattern Diagnosed in "Where It Struggles" but Not Architected

- **Severity:** MEDIUM
- **Expert:** Architecture (operational SLA, partner-outage handling)
- **Location:** "Where it struggles" subsection: *"Real-time queries during partner outages. When a partner organization or HIE intermediary is down, queries to that partner time out. The aggregating layer cannot block; the response degrades to 'we have data from these N partners, the others did not respond.' The mitigation is the fail-soft pattern: complete the response with whatever was available, log the timeouts, and re-query the unavailable partners asynchronously with the clinician's longitudinal-record-assembler refreshing as responses arrive."* The architecture diagram shows `L5 (outbound-query-submitter) -> NAT1 -> EXT1 (Partner Org) -> L6 (aggregate-partner-responses) -> L4`. The Why-This-Isn't-Production-Ready Outbound-query-orchestration paragraph names the gap but the architecture text does not specify the timeout, retry, or aggregation semantics.
- **Problem:** The recipe correctly diagnoses the fail-soft pattern as the right operational mitigation but the architecture does not specify the timeout values, the retry policy, the aggregation deadline, the response-assembly pattern (does the aggregator return a partial response after the deadline and continue collecting late responses asynchronously, or does it block until the deadline), or the longitudinal-record-assembler's refresh-on-late-response contract. Three concrete consequences:

  1. **The latency budget for the aggregator is not specified.** A query-time match has a strict latency budget (the recipe's stated 50-200ms median, <2s P99 in the Expected Results table); the aggregator's deadline must fit within this budget after subtracting normalization, matching, consent-check, and release-and-audit time. Without explicit specification, the aggregator may set a too-generous timeout (responding only after the slowest partner) or a too-aggressive timeout (cutting off partners that would have responded within the budget).

  2. **The retry policy for transient partner failures is not specified.** A 5xx response from a partner organization is sometimes transient (a momentary load spike, a brief network blip) and sometimes persistent (the partner's matcher is down). The aggregator should distinguish, retry transients within the budget, and not retry persistents. The chapter pattern from 5.4 (clearinghouse-side retry) applies here but is not specified.

  3. **The longitudinal-record-assembler's refresh-on-late-response contract is not specified.** When a partner responds after the aggregator's deadline, the aggregator's response has already been transmitted to the clinician; the late response must flow into the longitudinal-record-assembler so that the clinician's view refreshes. The architecture diagram shows the EventBridge fan-out to the assembler but does not specify the refresh-on-late-response contract.

- **Fix:** Promote the Honest Take and Why-This-Isn't-Production-Ready content into the architecture pattern paragraph: *"Outbound query orchestration uses a fail-soft pattern with the aggregator as the latency-budget-enforcing component. The aggregator fans out to all relevant partners, sets a per-partner timeout calibrated to the query-time latency budget (typically 1.5-2s, leaving room for the local match plus consent-and-release-and-audit), aggregates whatever responses arrived within the deadline, and transmits the aggregated response to the clinician. Late responses are not discarded: they flow into the longitudinal-record-assembler asynchronously via the `cross_facility_query_resolved` event with a `late_response: true` flag, and the assembler refreshes the clinician's view through the patient-portal or EHR widget. Partner-side 5xx errors are retried once within the deadline; persistent failures are logged and the partner's quality scorecard reflects the unavailability. CloudWatch alarms fire on per-partner error rate (a 5xx rate > 5% over 5 minutes is the first signal of a partner-side outage)."*

### Finding A6: Cross-Recipe Orchestration with 5.1 / 5.4 / 5.6 / 5.7 / 5.8 / 1.1 / 1.9 / 2.4 / 7.x Mentioned but Not Architected (Already TODO'd)

- **Severity:** MEDIUM
- **Expert:** Architecture (cross-recipe integration)
- **Location:** Architecture diagram shows `EB1 -->|FanOut| C1[Longitudinal Record Assembler]`, `C2[Patient Portal Access Reports]`, `C3[Consent Management Workflow]`, `C4[Local Patient Matcher 5.1]`, `C5[Longitudinal Name-Change Matcher 5.7]`. The Related Recipes section names 5.1, 5.2, 5.3, 5.4, 5.6, 5.7, 5.8, 5.9, 5.10, 1.1, 1.9, 2.4, 7.x as recipes that consume or produce cross-facility-related events. The recipe's inline TODO (referenced as "Expert review A6 (MEDIUM)") names the chapter-wide event schema with the specific consumer set and the acknowledgment-via-CloudWatch-metric pattern but the architecture text does not include the contract.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding A6. The architecture diagram shows the EventBridge fan-out but the contract between recipes is not specified: what payload each consumer receives, what the consumer's expected response cadence is, how consumers acknowledge processing, what the schema-versioning policy is. The cross-facility events are consumed by more recipes than 5.1/5.2/5.3/5.4 (longitudinal-record-assembler, patient-portal access-report generator, consent-management workflow, plus the cross-recipe consumers in 5.1, 5.7, 5.8, and indirectly 5.4 and 5.6); the integration contract is correspondingly more important.
- **Fix:** Promote the TODO content into the General Architecture Pattern paragraph: *"The cross-facility events conform to a chapter-wide event schema (`source`, `detail_type`, `detail.local_patient_id`, `detail.cross_org_identifier`, `detail.event_id`, `detail.previous_state`, `detail.new_state`, `detail.detected_at`). Downstream consumers in 5.1 (local matcher; cross-facility match may surface a previously-unknown duplicate-patient signal locally), 5.4 (eligibility matcher; cross-facility match data may inform a payer-side identity question), 5.6 (claims-clinical linkage; cross-facility identifier may help bridge claim-vs-clinical join), 5.7 (longitudinal name-change matcher; cross-facility queries are a common surfacing point for prior-name records), 5.8 (privacy-preserving linkage; cross-facility identifier resolution interacts with the privacy-preserving layer), plus the longitudinal-record-assembler, the patient-portal access-report generator, and the consent-management workflow, subscribe to specific `detail_type` values and acknowledge processing via a CloudWatch metric (`{consumer}.events_processed`). The chapter-wide event-bus governance specifies the schema versioning policy and the deprecation cadence for breaking changes."*

### Finding A7: Threshold Calibration Governance Named in TODO but Not Architected (Chapter-Wide Pattern)

- **Severity:** MEDIUM
- **Expert:** Architecture (governance, model lifecycle)
- **Location:** "Why This Isn't Production-Ready" Threshold-calibration paragraph: *"The cross-facility match thresholds are calibrated against an institutional gold set that reflects the cross-organizational query patterns. Re-calibration runs annually or on detection of cohort-stratified disparity above the institutional threshold, whichever first. Re-calibration produces a candidate threshold set; institutional review (HIE-quality committee, compliance, clinical safety, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each match decision records the configuration version active at decision time. Change without governance is the failure mode that produces silent regressions in both accuracy and equity."* The recipe's inline TODO at the same location (referenced as "Expert review A7 (MEDIUM)") names the chapter pattern but the architecture text does not include the specification.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding A7. The threshold calibration is functionally a probabilistic-classifier-tuning workflow whose lifecycle needs governance. The recipe correctly diagnoses the discipline ("change without governance is the failure mode that produces silent regressions in both accuracy and equity") but the architecture does not specify the configuration-as-data pattern, the candidate-promotion gate, or the version-event-on-every-match-outcome contract. The recipe specifies the linkage-time-and-query-time matchers must share configuration ("If the linkage-time matcher and the query-time matcher use different feature weights or thresholds, the query-time matcher can return inconsistent results across queries that should be equivalent. The mitigation is shared configuration"); this is the right framing but the architectural specification is not present.
- **Fix:** Promote the TODO content into the architecture text: *"The thresholds (`AUTO_ACCEPT_HIGH_THRESHOLD`, `AUTO_ACCEPT_MED_THRESHOLD`, `AUTO_REJECT_THRESHOLD`, per-feature weights in the composite score) live in a versioned configuration table. Both the linkage-time matcher and the query-time matcher read from the same versioned configuration store; threshold or weight changes deploy atomically to both. Re-calibration runs annually or on detection of cohort-stratified disparity above 0.05, whichever comes first. Re-calibration produces a candidate threshold set against the institutional gold set; institutional review (HIE-quality committee, compliance, clinical safety, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each match decision records the configuration version and threshold values active at the inference time, supporting forensic reconstruction across re-calibration cycles."*

### Finding A8: API Gateway Resource Policy and WAF Posture for the Inbound Cross-Facility Endpoint Not Fully Specified (Chapter-Wide Pattern + Recipe-Specific)

- **Severity:** MEDIUM
- **Expert:** Architecture (security boundary, defense in depth, recipe-specific enumeration-attack surface)
- **Location:** Architecture diagram shows `AG1[API Gateway cross-facility-endpoint] -> WAF1[AWS WAF] -> SM1[Secrets Manager signing keys]`. The recipe's inline TODO (referenced as "Expert review A8 / Networking review N1 (MEDIUM)") names the chapter pattern with the additional enumeration-attack consideration specific to cross-facility queries.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding A8 / N1, with the additional enumeration-attack consideration specific to cross-facility queries. The "Where it struggles" Enumeration-attack-surface paragraph correctly diagnoses: *"A bad actor with a list of demographic guesses can submit many queries to discover whether specific known persons are in the responder's system. WAF and per-requester rate limits raise the cost; the audit log surfaces suspicious patterns."* The architecture text correctly elevates WAF and Shield but does not specify the resource-policy posture (private API for HIE-network-reachable consumers via VPC endpoint, public API for federated identity-provider-authenticated consumers), the WAF rule groups (rate limiting per source-IP and per Cognito principal, request-size limiting, request-pattern analysis for enumeration-attack signatures), or the geo-restriction posture if the institution's HIE participation agreement constrains query origins.
- **Fix:** Promote the TODO content into the API Gateway paragraph: *"The API Gateway is configured as a private API for HIE-network-reachable consumers via VPC endpoint, with a public API path for federated identity-provider-authenticated consumers (e.g., TEFCA QHIN-to-QHIN traffic that does not flow through the institutional HIE network). AWS WAF is attached with rule groups for SQL injection, command injection, request rate limiting (per-source-IP and per-authenticated-principal), request-size limiting, and request-pattern analysis for enumeration-attack signatures (e.g., a single principal submitting a high volume of distinct demographic combinations). Geo-restriction is configured per the institution's HIE participation agreement (some agreements constrain query origins to specific states or to the United States). Per-requester rate limits in API Gateway are layered on top of the WAF rules."*

### Finding A9: Consent-Cache Invalidation Timing on Consent Revocation Not Specified

- **Severity:** MEDIUM
- **Expert:** Architecture (correctness, fail-closed posture extension)
- **Location:** Why-These-Services / ElastiCache paragraph: *"Consent state is also read on every query, but consent reads must fall through to the system-of-record on miss (caching consent risks releasing data after revocation)."* Step 6 invalidate_on_event handles `consent_revocation` by calling `ConsentCache.invalidate(event.patient_local_id)`. The recipe correctly identifies the risk but does not specify the invalidation timing (synchronous vs. eventually-consistent), the in-flight-query-handling on revocation, or the propagation latency budget.
- **Problem:** The recipe correctly identifies that caching consent state risks releasing data after revocation. The mitigation specified in the architecture is "fall through to the system-of-record on miss" plus event-driven invalidation in Step 6. But three gaps remain:

  1. **The invalidation timing on consent revocation is not specified.** A consent-revocation event from the registry must propagate to the cache deletion before any subsequent query can read the cached state. Without explicit specification, the implementation may treat the invalidation as eventually-consistent (with seconds-to-minutes lag), during which time queries may release data the patient has just revoked consent for.

  2. **The in-flight-query handling on revocation is not specified.** A query that has read the consent cache (the cached state shows consent permitted) and is in the middle of constructing the response may still release data after the registry's consent-revocation event has been emitted but before the in-flight query completes. The mitigation is to either (a) re-check consent at the release-and-audit step (synchronous read from the registry, not the cache), or (b) make the cache-read-and-release path atomic with respect to consent invalidation. The architecture does not specify either.

  3. **The propagation latency budget for consent revocation is not specified.** State and federal regulations may require consent revocations to take effect within a specified window (e.g., 24 hours under some state HIE rules; immediately for some federal categories). The architecture should specify the budget.

- **Fix:** Add to the Why-These-Services / ElastiCache paragraph and to the General Architecture Pattern: *"Consent-cache invalidation on revocation is synchronous: the consent-revocation EventBridge event triggers the invalidate-on-event Lambda which (a) deletes the cached consent state, (b) writes a `consent_revoked_at` flag in the cross-org MPI for the affected patient with the revocation effective time, (c) emits a `cross_facility_match_invalidated` event for downstream consumers. In-flight queries that have already read the cache but have not yet released data must re-check consent at the release-and-audit step against the system-of-record (not the cache); the system-of-record check is synchronous with a tight timeout (500ms) and fail-closed on timeout. The propagation latency budget for consent revocation is 60 seconds from registry emit to release-path effect; CloudWatch alarms on propagation latency exceeding 60 seconds at P99 surface drift in the invalidation pipeline. The fail-closed posture on consent extends through the in-flight-query lifecycle, not just the initial cache-or-system-of-record read."*

### Finding A10: Initial Backfill of Cross-Org Identifiers at HIE Onboarding Not Fully Architected (Chapter-Wide Pattern, Already Partially in Production-Gaps)

- **Severity:** MEDIUM
- **Expert:** Architecture (one-time vs ongoing operations)
- **Location:** "Why This Isn't Production-Ready" Initial-backfill paragraph names the considerations: *"(a) cohort-stratified accuracy monitoring during the backfill (the backfill is a one-time opportunity to surface cohort issues at scale); (b) suppression of routine event emission during the backfill (downstream consumers refresh from a single backfill_complete marker rather than millions of individual events); (c) governance approval at each stage (a backfill that produces a 5% lower match rate than expected may indicate a configuration issue rather than a population-difference issue, and the institutional governance committee has to bless the backfill output before it goes live). Plan onboarding as a project with its own timeline and its own risk register."* The recipe's inline TODO (referenced as "Expert review A11 (LOW)") names the chapter pattern but the production-gaps text already covers most of the substance.
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4. The backfill is a one-time operation with distinct architectural considerations (cohort-stratified monitoring at scale, event-emission suppression, governance approval gates) that the production-gaps text correctly diagnoses. In 5.5 specifically, the cross-organizational dimension makes the backfill more consequential than in earlier recipes: the backfill establishes cross-organizational identifiers that all downstream queries depend on, and a backfill that systematically under- or over-merges patients across organizations produces wrong-patient consequences for years afterward.
- **Fix:** Promote the production-gaps content into the Why-This-Isn't-Production-Ready section more fully, mirroring the chapter pattern from 5.3 / 5.4. Specify the backfill orchestration as a Glue job with controlled concurrency, the event-suppression mechanism (a `backfill_in_progress` flag on the cross-facility-events bus that consumers honor), the cohort-stratified accuracy report attached to the `backfill_complete` event, and the governance-approval-at-each-stage gate (the institutional governance committee blesses the backfill output before downstream consumers start consuming the established cross-org identifiers).

### Finding A11: Lake Formation Column-Level Access Controls Named in TODO but Not Architected (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Architecture (analytics access governance)
- **Location:** Why-These-Services / Athena paragraph and the recipe's inline TODO (referenced as "Expert review A10 (LOW)").
- **Problem:** Same chapter pattern as 5.2 / 5.3 / 5.4. The raw query payloads are sensitive (full demographics on every query, including queries that returned no match; the no-match queries are particularly sensitive because they reveal demographic guesses about people the institution may not have any record for). The parsed match decisions are needed by clinical-IT and longitudinal-record assembly. The cohort-aggregated metrics are needed by leadership and equity-monitoring committees. Different audiences need different views; Lake Formation grants enforce the column-level distinctions.
- **Fix:** Promote the TODO content into the Athena paragraph: *"Lake Formation column-level access controls restrict QuickSight and Athena consumers to the columns they need: dashboards see cohort-aggregated metrics only; clinical-IT and longitudinal-record-assembly teams see the parsed match decisions and audit-trail provenance; the raw query payloads (especially the no-match queries that reveal demographic guesses) are restricted to the HIE operations and audit teams. Direct Athena query path uses the same grants. Access is logged via CloudTrail data events on the catalog and on the underlying S3 buckets."*

### Finding A12: Blocking-Key Naming Inconsistency Between Architecture Diagram and Pseudocode

- **Severity:** LOW
- **Expert:** Architecture (internal consistency)
- **Location:** General Architecture Pattern ASCII diagram (line 170-173): *"Block on (last-name-soundex, year-of-birth) plus secondary blocks for low-recall coverage (last-name-metaphone, ZIP3-and-DOB, first-name-and-DOB-day-month)."* Step 2 pseudocode (line 568-570): the comment says *"a phonetic form (Soundex, Double Metaphone)"* but the actual `blocking_keys` list uses `last_name_phonetic` (which is `double_metaphone(raw.last_name)`). The blocking-key-design prose (line 289) names "last-name-soundex plus year-of-birth, last-name-metaphone, ZIP3-plus-DOB, first-name-plus-DOB-month-day."
- **Problem:** The recipe uses Soundex and Metaphone interchangeably across the diagram, the prose, and the pseudocode. The pseudocode's actual implementation uses Double Metaphone (correct: it is more accurate than Soundex for most US healthcare populations, especially for non-Anglo names). The prose and the diagram should match. This is a minor consistency issue that could confuse a reader following the recipe.
- **Fix:** Update the General Architecture Pattern ASCII diagram and the blocking-key-design prose to consistently say "double-metaphone" or "phonetic-encoded" rather than mixing Soundex and Metaphone. Add a brief explanatory note: *"Production matchers typically use Double Metaphone (more accurate for non-Anglo names) rather than Soundex (the original phonetic encoding); the recipe's pseudocode uses Double Metaphone."*

### Finding A13: ElastiCache Capacity Planning for Cross-Org MPI Blocking Index Not Specified

- **Severity:** LOW
- **Expert:** Architecture (capacity, cost, correctness at scale)
- **Location:** Why-These-Services / ElastiCache paragraph: *"Blocking-key-to-candidate-set map is loaded from DynamoDB at warm-up and refreshed incrementally as the MPI changes; the cache holds the most-frequently-queried blocks."* Cost Estimate row says *"$4,000-12,000/month, dominated by DynamoDB (cross-org MPI plus audit log at this volume) and ElastiCache."*
- **Problem:** The architecture says ElastiCache holds the blocking-index but does not specify the cluster sizing methodology, the eviction policy, or the warm-up strategy at HIE scale. At fifty participating organizations and three million queries per month, the blocking index can be tens to hundreds of GB depending on the population size and the blocking-key cardinality. Without explicit sizing, the implementation may be undersized and produce cache misses that fall through to DynamoDB at higher cost and latency.
- **Fix:** Add to the ElastiCache paragraph: *"At HIE scale (e.g., fifty participating organizations, populations totaling several million patients), the blocking-index cache size is dominated by the candidate-set cardinality per blocking key. The cluster sizing should be calculated against the MPI population, the average blocking-key cardinality, and the read-rate distribution; a typical regional HIE benefits from `cache.r6g.xlarge` or larger with read replicas for availability and a `volatile-lfu` eviction policy. The warm-up strategy at deploy time loads the most-frequently-queried blocks (per the prior period's CloudWatch query-rate metrics); subsequent updates flow through DynamoDB Streams to the cache. CloudWatch alarms fire on cache memory utilization exceeding 80% and on cache-miss rate exceeding the institutional threshold."*

## Networking Expert Review

### What's Done Well

- **VPC posture explicit.** Lambdas in VPC; Glue jobs in VPC connections; ElastiCache in VPC subnet groups; VPC endpoints for S3, DynamoDB, KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, STS. The interface-versus-gateway endpoint distinction is correct.
- **NAT Gateway minimization with allow-listed egress.** "NAT Gateway for HIE and partner-organization egress with an outbound HTTPS proxy and an allow-list of partner endpoints. PrivateLink endpoints for partners that offer them" is the chapter's correct egress-discipline statement.
- **PrivateLink awareness flagged in TODO.** The TODO at the AWS Implementation Lambda paragraph correctly identifies that "HIE intermediaries vary in their connectivity options" and that the institution should evaluate at scale.
- **TLS 1.2-or-higher framing throughout with mTLS for partner connections.** "TLS 1.2 or higher for all in-transit traffic, including HIE and partner connections. Mutual TLS where the partner or HIE requires it" is the right baseline.
- **WAF and Shield specifically named for the inbound-query endpoint.** The recipe correctly identifies the enumeration-attack surface specific to cross-facility queries, which is the recipe's strongest single networking-and-security observation that distinguishes it from the earlier recipes' threat models.
- **HIPAA-eligible service inventory checked.** The Prerequisites AWS Services row enumerates HIPAA-eligible services consistently with the chapter pattern.

### Finding N1: API Gateway Resource Policy and WAF Posture Not Specified (Chapter-Wide Pattern)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Architecture diagram shows the inbound API surface but the resource policy is not specified in prose. (See Architecture Finding A8 for the architecture-side framing of the same concern.)
- **Problem:** Same as Recipe 5.1 / 5.2 / 5.3 / 5.4 Finding N1, with the recipe-specific addition of the enumeration-attack consideration.
- **Fix:** See Finding A8 fix. Specify the private API Gateway with VPC endpoint resource policy for HIE-network-reachable consumers, the public API path for federated identity-provider-authenticated consumers, WAF rules for SQL injection / command injection / rate limiting / enumeration-attack pattern detection, and mTLS for system-to-system clients.

### Finding N2: HIE and Partner-Organization Egress Posture Could Be Sharpened (Chapter-Wide Pattern, Already TODO'd)

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites VPC row: *"NAT Gateway for HIE and partner-organization egress with an outbound HTTPS proxy and an allow-list of partner endpoints. PrivateLink endpoints for partners that offer them."* The recipe's inline TODO (referenced as "Networking review N2 (LOW)") names the chapter pattern but the architecture text does not include the specification.
- **Problem:** The egress posture is correctly outlined but could be sharpened with per-partner allow-list scoping. Each partner's connectivity (HIE intermediary, direct partner organization, TEFCA QHIN) is a distinct concern; a compromise of one Lambda role should not be able to exfiltrate via another partner's endpoint. Same pattern as 5.3 / 5.4 Finding N2.
- **Fix:** Promote the TODO content into the VPC row: *"HIE egress and partner egress are configured as distinct outbound proxy rules with non-overlapping allow-lists scoped to compute roles: each Lambda role allows only the specific partner endpoints it must call; per-role rate limits below the partner's published rate limits; egress connections CloudWatch-logged for forensic auditing."*

### Finding N3: PrivateLink Evaluation Posture Underspecified

- **Severity:** LOW
- **Expert:** Networking (architecture roadmap)
- **Location:** TODO at the AWS Implementation Lambda paragraph: *"confirm partner PrivateLink availability at time of build; HIE intermediaries vary in their connectivity options."*
- **Problem:** The TODO correctly identifies the operational improvement but does not specify the volume threshold or the evaluation criteria for adopting PrivateLink. At HIE-scale query volumes, PrivateLink eliminates NAT Gateway data-transfer cost on the partner-egress path and improves the security posture by keeping traffic on the AWS network.
- **Fix:** Promote the TODO content into the VPC row: *"At HIE-scale query volumes (e.g., several million queries per month), evaluate the partner's or the HIE intermediary's PrivateLink endpoint where available. PrivateLink eliminates NAT Gateway data-transfer cost on the partner-egress path and keeps the traffic on the AWS network without traversing the public internet. The cost trade-off (PrivateLink endpoint hourly fee plus per-GB data-transfer fee vs NAT Gateway data-transfer fee) is institution-specific; institutions with high-volume cross-facility query traffic typically see net savings beyond a couple million queries per month."*

---

## Voice Reviewer

### What's Done Well

- **Em dash count: 0.** Verified by reading the file with grep on U+2014.
- **En dash count: 0.** Verified the same way for U+2013.
- **70/30 vendor balance maintained.** The Problem, The Technology, and General Architecture Pattern sections name no AWS services. AWS service names appear first in the AWS Implementation section. The Honest Take returns to vendor-agnostic territory for the closing observations on the IHE PIX/PDQ aging well, the FHIR-native-as-future-but-v2-as-load-bearing-for-several-years observation, and the 21st Century Cures Act information-blocking rules making the architecture a compliance asset.
- **CC voice consistent throughout.** The opening trauma-team vignette ("A patient gets in a car accident on a Tuesday afternoon. She is unconscious when the ambulance arrives, has no ID on her, and is brought to the nearest emergency department. The trauma team needs to know, very fast, whether she is on blood thinners.") lands in the engineer-explaining-something-cool register exactly. The seven you-are-running-X scenarios that establish the operational landscape (HIE operator, hospital clinical IT, oncology care coordination, state Medicaid quality measurement, public health immunization, TEFCA national network operator) are the recipe's strongest single passage of pacing. The Maria Garcia / Maria Garcia-Lopez / M Garcia / Maria Elena Garcia running example carries through the wrong-patient-overlay vignette to the matcher's pseudocode and the Expected Results sample with the right consistency. Self-deprecating expertise lands well: *"Cross-facility patient matching is the recipe in this chapter where the gap between 'we have the technology' and 'we have the operational capacity to deploy it well' is the widest"* is the right register for opening the Honest Take.
- **The Honest Take is the chapter's most operationally pointed section so far.** Eight observations earn the recipe's voice (the gap-between-technology-and-operational-capacity framing, the matcher-as-program-not-as-system trap, the consent-layer-as-first-class-input vs. compliance-overhead trap, the equity-dimension-with-compounding-asymmetries observation, the audit-log-as-the-system observation, the discoverability-semantics-more-nuanced-than-most-teams-design-for observation, the trust-but-verify-toward-partner-matchers observation, the patient-facing-access-reports-as-feature-not-compliance-burden recommendation). Each is at the right grain.
- **Clinical and regulatory accuracy is high.** The IHE PIX/PDQ framing is correct (HL7 v2-based original plus FHIR-based PIXm/PDQm); the FHIR Patient `$match` framing is correct; the TEFCA QHIN exchange framing is correct (with appropriate TODOs for verification at build time); the 42 CFR Part 2 sensitivity-filter framing is correct; the 21st Century Cures Act information-blocking framing is correct; the Sequoia Project, Carequality, ONC, and AHIMA references are correct; the post-Dobbs reproductive-health-information sharing constraints are correctly flagged as a moving regulatory target.
- **The Variations and Extensions section is well-scoped.** Eleven extensions (FHIR-native query, TEFCA QHIN exchange, patient-mediated identity, privacy-preserving cross-facility matching, care-transition-aware match prioritization, multi-organization longitudinal-record assembly with provenance, patient-controlled query authorization, public-health reporting variant, insurance-coverage-aware matching, active-learning threshold tuning, partner-organization quality scorecard). Each is framed at the right grain with cross-references to the relevant other recipes.

### Finding V1: A Few Headers in the AWS Implementation Section Slip Toward Documentation Voice

- **Severity:** LOW
- **Expert:** Voice (register consistency)
- **Location:** Several entries in "Why These Services" read as service-name-as-bullet-header:
  - *"AWS KMS, CloudTrail, CloudWatch."*
  - *"AWS Secrets Manager for HIE and partner credentials."*
  - *"AWS WAF and Shield for the inbound-query endpoint."*
- **Problem:** Same chapter pattern as 5.1 / 5.2 / 5.3 / 5.4 Finding V1. The headers are functionally correct as scannable structure for a long technical section; the deeper paragraph framing returns to the right register.
- **Fix:** Optional. The chapter editor's call.

### Finding V2: A Few Long Sentences with Multiple Subordinate Clauses

- **Severity:** LOW
- **Expert:** Voice
- **Location:** A handful of sentences in The Technology section's "Why It Is Hard" and "Where the Field Has Moved" subsections, plus the Honest Take's matcher-as-program-not-as-system paragraph stretch past 50 words. Specific examples include the 5-clause sentence on TEFCA QHIN-to-QHIN exchange and the multi-clause sentence on cohort-stratified accuracy monitoring at the cross-organizational layer.
- **Problem:** Most sentences are well-paced; a few in the architectural-and-regulatory paragraphs could be split. Same observation as 5.1 / 5.2 / 5.3 / 5.4 Finding V2.
- **Fix:** Optional.

### Finding V3: The Trauma-Team Opening Vignette and the Seven You-Are-Running-X Scenarios Are the Chapter's Strongest Single Hook on This Domain

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Problem's opening trauma-team vignette and the seven you-are-running-X enumeration that follows.
- **Note:** This framing earns its position. The trauma-team opening is the chapter's strongest single articulation of why cross-facility matching matters in clinical-safety terms (the unconscious patient with records at four different organizations none of which connect directly), and the seven-scenario follow-on enumeration grounds the reader in the operational-not-just-clinical landscape (HIE operator, hospital clinical IT, oncology care coordination, state Medicaid quality measurement, public health immunization, TEFCA national network operator, plus the wrong-patient-overlay scenario where the urgent care positive-pregnancy-test gets filed in the wrong patient's chart). The chapter editor should consider whether a similar "scene-then-scenario-list" pattern applies to the more technically-heavy recipes that need to ground the reader in operational ambiguity.

### Finding V4: The Audit-Log-As-The-System Framing Is the Recipe's Strongest Single Audit-Trail Observation

- **Severity:** None (positive observation)
- **Expert:** Voice
- **Location:** The Honest Take paragraph: *"In recipe 5.1, the audit trail is important but secondary. In recipe 5.5, the audit trail is the system. Every query, every match, every consent check, every release, every withhold, every re-query for the same patient on a different day, all of it lives in the audit log."*
- **Note:** This is the right elevation for cross-facility. The chapter editor should preserve this framing through the editing pass; the architecture-finding A1 ties directly to this prose claim and the fix-recommendation should preserve the audit-log-as-the-system framing.

---

## Stage 2: Expert Discussion

The independent reviews surface several overlapping concerns; the discussion resolves priority across the experts.

**Identity-boundary checks (S1, chapter-pattern):** Security flags the inbound endpoint, the outbound submitter, the consent-and-sensitivity filter, the audit-log writer, and the cross-recipe invalidation consumers at HIGH severity. Architecture concurs because the audit-log-as-the-system consequence (the recipe text itself elevates the audit log to "the system") compounds the security concern with the recipe's own framing. Networking is silent (the network perimeter is sound; the boundary is application-level). Voice is silent. **Resolution: HIGH, attributed to Security with Architecture concurrence. The chapter editor should consolidate to a chapter preface in the next pass since the same finding now applies across 4.4-5.5.**

**release_and_audit atomicity (A1):** Architecture flags the sequential PutItem / S3-writes / PutEvents / transmit_response pattern as needing `TransactWriteItems` plus an outbox pattern at HIGH severity, with the recipe's own inline TODO at Step 5B already naming the gap and noting that the regulatory consequence is sharper than 5.1/5.2/5.3/5.4 because the audit log is "the system" per the Honest Take. Security concurs because the audit-log-to-actual-delivery divergence is precisely the failure mode that breaks the patient's right-to-know, the partner's audit request, and the wrong-patient-incident forensic reconstruction. Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture with Security concurrence.**

**Cohort fairness instrumentation (A2, chapter-pattern):** Architecture flags the equity threshold and metric definitions as needing explicit specification at HIGH severity. Security concurs on the privacy framing of cohort dimensions in CloudWatch (Finding S5). Networking is silent. Voice is silent. **Resolution: HIGH, attributed to Architecture. The cohort-distribution stakes are higher here than in 5.1/5.2/5.3/5.4 because cross-facility match disparities translate to clinical-safety incidents.**

**Discoverability-permitted field handling (A3):** Architecture flags this as a recipe-specific HIGH-severity correctness bug. The pseudocode reproduces the canonical first-pass failure mode the prose explicitly warns against; this is a recipe-internal contradiction. Security concurs because the leak of fact-of-care violates state and federal consent frameworks in some jurisdictions. Networking is silent. Voice is silent (the prose itself is excellent; the issue is the divergence between prose and pseudocode). **Resolution: HIGH, attributed to Architecture with Security concurrence. The fix is localized to Step 4 and Step 5 pseudocode; the Honest Take's discoverability paragraph does not need to change.**

**Audit-log retention floor (S2, chapter-pattern):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Partner data-handling expectations (S3, including minimum-acceptable-matcher-quality):** Security flags as MEDIUM. Architecture concurs because the minimum-acceptable-matcher-quality clauses directly affect the institution's cross-facility match accuracy. **Resolution: MEDIUM, attributed to Security with Architecture concurrence.**

**Deferred-review-queue audit posture (S4):** Security flags as MEDIUM. Architecture concurs. **Resolution: MEDIUM, attributed to Security.**

**Idempotency and DLQ coverage (A4, chapter-pattern):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Outbound query orchestration fail-soft pattern (A5):** Architecture flags as MEDIUM. Recipe-specific finding. **Resolution: MEDIUM, attributed to Architecture.**

**Cross-recipe orchestration (A6):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**Threshold calibration governance (A7, chapter-pattern):** Architecture flags as MEDIUM. **Resolution: MEDIUM, attributed to Architecture.**

**API Gateway resource policy and WAF (A8 / N1, chapter-pattern):** Architecture flags as MEDIUM; Networking flags as LOW. The recipe-specific enumeration-attack consideration is already in the WAF prose; the resource-policy posture is the additional spec. **Resolution: MEDIUM (per A8), attributed to Architecture with Networking concurrence.**

**Consent-cache invalidation timing (A9):** Architecture flags as MEDIUM. Recipe-specific finding. **Resolution: MEDIUM, attributed to Architecture.**

**Backfill at HIE onboarding (A10, chapter-pattern):** Architecture flags as MEDIUM (vs LOW in 5.3) because the cross-organizational dimension makes backfill errors more consequential than in earlier recipes. **Resolution: MEDIUM, attributed to Architecture.**

**Lake Formation column-level access controls (A11, chapter-pattern):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Blocking-key naming inconsistency (A12):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**ElastiCache capacity planning at HIE scale (A13):** Architecture flags as LOW. **Resolution: LOW, attributed to Architecture.**

**Cohort PHI in CloudWatch dimensions (S5, chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**IAM ARN scoping (S6, chapter-pattern):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**Patient-mediated identity disclosure posture (S7):** Security flags as LOW. **Resolution: LOW, attributed to Security.**

**API Gateway resource policy and WAF (N1, paired with A8):** Networking flags as LOW. Already resolved at MEDIUM via A8.

**HIE and partner egress posture (N2, chapter-pattern):** Networking flags as LOW. **Resolution: LOW, attributed to Networking.**

**PrivateLink evaluation posture (N3):** Networking flags as LOW. **Resolution: LOW, attributed to Networking.**

**Voice findings (V1, V2):** Both LOW. V3 and V4 are positive observations. **Resolution: LOW or no-finding, attributed to Voice.**

The resolved priority list is: 0 critical, 4 high, 9 medium, 9 low. The 4 HIGH count exceeds the > 3 = FAIL threshold; the verdict is FAIL.

---

## Stage 3: Synthesized Feedback

**Verdict: FAIL.**

Four HIGH findings (more than 3 = FAIL per the persona rules). Three are correctness-and-compliance gaps with localized fixes that surface in well-specified TODO comments and prose elsewhere in the recipe; one (the discoverability-permitted field handling) is a recipe-specific bug where the pseudocode reproduces the canonical first-pass failure mode the prose explicitly warns against. None require structural rework of the recipe; the underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent.

### Critical Findings

None.

### High Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 1 | HIGH | Security | Inbound query endpoint, outbound submitter, consent-and-sensitivity filter, audit-log writer, and cross-recipe invalidation consumers lack identity-boundary specification |
| 2 | HIGH | Architecture | release_and_audit is not atomic; sequential DynamoDB / S3 / EventBridge / response-transmission operations leave the audit log out of sync with the released response |
| 3 | HIGH | Architecture | Cohort-stratified accuracy thresholds and metric definitions referenced as "required here too" but undefined |
| 4 | HIGH | Architecture | Discoverability-permitted field inconsistently set in Step 4; Step 5 falls through to MATCHED_NOT_RELEASABLE on consent-expired and registry-unavailable branches, leaking fact-of-care |

### Medium Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 5 | MEDIUM | Security | Audit-log retention specified as "per the regulatory retention floor" without explicit floor (chapter pattern) |
| 6 | MEDIUM | Security | HIE and direct-partner data-handling expectations named in TODO but not architecturally specified (including minimum-acceptable-matcher-quality contractual clauses) |
| 7 | MEDIUM | Security | Deferred-review-queue decision audit posture underspecified |
| 8 | MEDIUM | Architecture | Idempotency keys and DLQ coverage named in TODO but not architected (chapter pattern) |
| 9 | MEDIUM | Architecture | Outbound query orchestration fail-soft pattern diagnosed in "Where it struggles" but not architected |
| 10 | MEDIUM | Architecture | Cross-recipe orchestration with 5.1 / 5.4 / 5.6 / 5.7 / 5.8 / 1.1 / 1.9 / 2.4 / 7.x mentioned but not architected |
| 11 | MEDIUM | Architecture | Threshold calibration governance named in TODO but not architected (chapter pattern) |
| 12 | MEDIUM | Architecture | API Gateway resource policy and WAF posture for the inbound cross-facility endpoint not fully specified (chapter pattern + recipe-specific enumeration-attack surface) |
| 13 | MEDIUM | Architecture | Consent-cache invalidation timing on consent revocation not specified |
| 14 | MEDIUM | Architecture | Initial backfill of cross-org identifiers at HIE onboarding not fully architected (chapter pattern) |

### Low Findings

| # | Severity | Source | Title |
|---|----------|--------|-------|
| 15 | LOW | Security | Cohort PHI in CloudWatch metric dimensions (chapter pattern) |
| 16 | LOW | Security | IAM "Never `*` actions or `*` resources in production" stated without scoped ARN examples (chapter pattern) |
| 17 | LOW | Security | Patient-mediated identity disclosure posture for variations section not addressed |
| 18 | LOW | Architecture | Lake Formation column-level access controls named in TODO but not architected (chapter pattern) |
| 19 | LOW | Architecture | Blocking-key naming inconsistency between architecture diagram and pseudocode (Soundex vs Double Metaphone) |
| 20 | LOW | Architecture | ElastiCache capacity planning for cross-org MPI blocking index not specified |
| 21 | LOW | Networking | API Gateway resource policy and WAF posture not specified (chapter pattern, paired with A8) |
| 22 | LOW | Networking | HIE and partner-organization egress posture could be sharpened (chapter pattern) |
| 23 | LOW | Networking | PrivateLink evaluation posture underspecified |
| 24 | LOW | Voice | A few headers in the AWS Implementation section slip toward documentation voice |
| 25 | LOW | Voice | A few long sentences with multiple subordinate clauses |

### Recommended Resolution Path

1. **Address the 4 HIGH findings before publication.** Each has a localized fix:
   - Finding S1 (identity-boundary): pseudocode additions in the inbound API path, the outbound submitter, the consent-and-sensitivity filter Lambda invocation contract, the audit-log writer's producer-signed envelope, and the cross-recipe invalidation consumer-side validation. Reference language is partially present in inline TODOs and the chapter pattern from 4.4-5.4. Estimated effort: half a day.
   - Finding A1 (atomicity): pseudocode rewrite of Step 5 to use `TransactWriteItems` plus an outbox pattern for the S3 writes, the EventBridge emit, and the synchronous response transmission; the architecture prose addition specifies the partial-failure recovery semantics with the irreversible-side-effect caveat for transmit_response. The recipe's own TODO at Step 5B names the gap; the fix is to architect what the TODO references. Estimated effort: half a day.
   - Finding A2 (cohort fairness threshold): threshold-and-metric specification in pseudocode and architecture-prose paragraph. Reference language is present in the cohort-stratified accuracy paragraph and inherited from 5.1/5.2/5.3/5.4. Estimated effort: half a day.
   - Finding A3 (discoverability-permitted): pseudocode update to set discoverability_permitted on every non-release branch with a fail-closed default, plus update Step 5's discoverability check to fail closed (mask as NO_MATCH unless affirmatively TRUE). Add a paragraph to The Technology section explaining the fail-closed-on-discoverability posture. Estimated effort: half a day.

   Total: 2 days of writing time.

2. **Address the recipe-specific MEDIUM findings (S4 deferred-review audit, A5 outbound fail-soft pattern, A9 consent-cache invalidation timing, A10 backfill cross-org identifiers).** Most have language already present elsewhere in the recipe that needs to be promoted into the architecture pattern. Estimated effort: 1-2 days of writing time.

3. **Address the chapter-wide MEDIUM findings (S2 audit retention, S3 partner data-handling with minimum-acceptable-matcher-quality, A4 idempotency, A6 cross-recipe orchestration, A7 threshold governance, A8/N1 API Gateway resource policy).** These are already TODO'd or chapter-pattern; consolidating into a chapter preface in the next pass is acceptable.

4. **Address the LOW findings as time permits.** The voice findings (V1, V2) are stylistic preferences; the networking findings (N2, N3) are explicit-statement additions; the chapter-pattern findings (S5, S6, S7, A11) are consolidation work; A12 (Soundex/Metaphone consistency) and A13 (ElastiCache capacity at HIE scale) are small inline annotations.

5. **After the HIGH and MEDIUM fixes, re-run the expert review cycle** to confirm the fixes are correctly placed and the recipe's overall integrity is preserved. Recipe 5.5 is the second Medium-tier recipe in Chapter 5 and the chapter's first venture into multilateral-trust cross-organizational matching; the quality bar inherits from 5.1/5.2/5.3/5.4 and the recipe's own claim that "the audit trail is the system" earns the architectural specification matching the prose's elevation.

The recipe's underlying methodology, voice, clinical and regulatory accuracy, and architectural shape are excellent. The opening trauma-team vignette, the seven you-are-running-X scenarios, the IHE PIX/PDQ and FHIR Patient `$match` standards-foundation framing, the query-time-vs-linkage-time match dichotomy, the four-component match output (identity match, consent envelope, sensitivity filter, provenance and authority), the consent-consulted-at-release-time-not-at-query-time architectural pattern, the audit-log-as-the-system elevation, the cross-organizational-variance framing on cohort-stratified accuracy monitoring, the discoverability-semantics observation in the Honest Take, the trust-but-verify-toward-partner-matchers framing, the patient-facing-access-reports-as-feature-not-compliance-burden recommendation, and the closing 21st-Century-Cures-Act-as-load-bearing-for-compliance observation are all chapter-strength contributions. The HIGH findings are gaps in the architectural specification that the prose elsewhere in the recipe correctly diagnoses (Findings S1, A1, A2, with TODO references already in place) plus one recipe-specific pseudocode bug where the prose's warning about discoverability semantics is contradicted by the pseudocode's actual behavior (Finding A3). Closing the gaps brings the architecture up to the standard the recipe text claims and makes the cross-facility-match substrate that 5.1, 5.4, 5.6, 5.7, 5.8, plus the longitudinal-record-assembler, the patient-portal access-report generator, and the consent-management workflow depend on as solid as the recipe text promises it is.
