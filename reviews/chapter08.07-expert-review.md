# Expert Review: Recipe 8.7 - Adverse Event Detection in Clinical Text

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.07-adverse-event-detection-clinical-text.md`

---

## Overall Assessment

This is one of the most clinically significant recipes in the cookbook. The problem framing is excellent: the voluntary-reporting-captures-1-to-13-percent statistic, the amlodipine opening scenario, and the honest breakdown of why "just search for side effects" fails all land well. The five-stage NLP pipeline (entity extraction, assertion filtering, relation extraction, severity classification, aggregation) is architecturally sound and properly sequenced. The layered evidence scoring approach for relation extraction is a mature design that acknowledges the precision/recall tradeoffs honestly.

The recipe delivers on its promise: a reader finishes knowing how adverse event detection works conceptually, why it's hard, and how to build it on AWS. The honest take about the first week drowning in noise and the months-to-signal-detection reality is exactly what a deployer needs to hear.

However: there are security gaps around PHI data flows through Neptune, a missing DLQ on the SQS queue that processes clinical notes, an incomplete cost estimate that understates real-world expenses by 3-5x, and a severity classification default that could cause alert fatigue. None are deployment blockers for a skilled team, but several would trip up a builder following the recipe literally.

Priority breakdown: 0 must-fix, 5 high-severity, 6 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

The PHI baseline is strong: BAA requirement stated explicitly, SSE-KMS on S3 and SQS, DynamoDB encryption at rest, Neptune encryption at rest, TLS for all transit, CloudTrail enabled, VPC with VPC endpoints for all services including Comprehend Medical. The "Never use real patient notes in non-production environments" callout with MIMIC-III as the dev alternative is correct. The `status: "pending_review"` default on all detections (human-in-the-loop before action) is appropriate for a safety-critical system.

#### Issue S1: Neptune PHI Access Controls Not Specified (HIGH)

**Location:** Architecture Diagram and "Why These Services" section (Neptune paragraph)

**The problem:** The recipe routes detected adverse events into Amazon Neptune for signal aggregation. The graph contains patient_id nodes, drug nodes, and event nodes with relationship edges. This is a PHI data store: patient identifiers linked to medical conditions and medications. The recipe mentions Neptune "requires VPC deployment" and "encryption at rest" but provides no guidance on:
- Neptune IAM authentication (required for fine-grained access control)
- Security group rules limiting which Lambda functions can reach Neptune's port 8182
- Whether the signal-aggregator Lambda is the only function with Neptune access, or whether the safety dashboard also connects directly
- Audit logging for Neptune queries (who queried which patient's adverse event graph)

A builder following this recipe will deploy Neptune with default network access from within the VPC, meaning any Lambda or EC2 instance in the same VPC can query the full adverse event graph.

**Suggested fix:** Add to Prerequisites: "Neptune: IAM database authentication enabled, security group restricted to signal-aggregator Lambda and dashboard read-replica. Enable Neptune audit logs to CloudWatch Logs for PHI access tracking." Add a note in the Neptune ingredient row: "Restrict Gremlin/SPARQL query access to the aggregation Lambda and read-only dashboard service via security groups and IAM DB auth."

#### Issue S2: SNS Alert Message Contains Full AE Record Including Patient ID (HIGH)

**Location:** Step 6 pseudocode, `store_and_alert` function

**The problem:** The pseudocode publishes the full `ae_record` to SNS for high-severity alerts:

```text
PUBLISH to SNS topic "ae-critical-alerts":
    subject: "High-severity adverse event detected"
    message: ae_record (formatted for human readability)
```

The `ae_record` contains `patient_id` and `note_id`. SNS messages are delivered to subscribers (email, SMS, HTTPS endpoints, SQS queues). If any subscriber endpoint is outside the HIPAA-compliant boundary (e.g., an email distribution list that includes non-covered recipients, or a webhook to an external incident management system without a BAA), this constitutes PHI disclosure.

**Suggested fix:** Change the SNS message to include only: `ae_id`, `severity`, `medication` (generic name only), `event_description` (clinical finding without patient identifiers), and a link to the internal safety dashboard where authorized users can view full details after authentication. Add a note: "Never include patient_id, note_id, or other direct identifiers in SNS messages. SNS delivery endpoints may not all be within your HIPAA boundary."

#### Issue S3: IAM Permissions Use Wildcard on Neptune (MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions specify `neptune-db:*` with the note "(scoped to cluster)." While scoping to the cluster ARN is better than account-wide access, `neptune-db:*` grants both read and write access to the graph database. The signal-aggregator Lambda needs read+write. A safety dashboard service only needs read. A single wildcard permission applied to all components violates least-privilege.

**Suggested fix:** Specify separate permissions: `neptune-db:ReadDataViaQuery` for read-only consumers (dashboard), `neptune-db:WriteDataViaQuery` and `neptune-db:ReadDataViaQuery` for the signal-aggregator Lambda. Note that Neptune IAM actions are granular and should be scoped per role.

#### Issue S4: No Retention Policy on DynamoDB Adverse Event Records (MEDIUM)

**Location:** Step 6 pseudocode, DynamoDB storage

**The problem:** The recipe mentions DynamoDB's "TTL feature can manage retention policies for different severity levels" in the "Why These Services" section but never actually specifies a retention policy or configures TTL in the pseudocode. Adverse event records containing patient_id and clinical findings accumulate indefinitely. Healthcare data retention policies vary by jurisdiction and purpose (pharmacovigilance records may require longer retention than operational records), but the recipe provides no guidance.

**Suggested fix:** Add a note in Step 6 or in a configuration section: "Configure DynamoDB TTL on a `ttl_epoch` attribute. Suggested retention: Grade 1-2 events retain for 2 years (or per institutional policy), Grade 3-4 events retain for 7 years (aligned with medical records retention requirements in most US states). Aggregated signals in Neptune retain independently of individual event records."

#### Issue S5: Archive Bucket Has No Object Lock or Versioning Mentioned (LOW)

**Location:** Step 1 pseudocode, S3 archive

**The problem:** The raw note archive in S3 serves as the audit trail ("every piece of PHI we process must be traceable"). For audit compliance, this archive should be immutable: a processed note should not be deletable or overwritable after archival. The recipe does not mention S3 Object Lock (compliance mode) or even versioning on the archive bucket.

**Suggested fix:** Add to Prerequisites or Step 1: "Enable S3 versioning on the notes-archive bucket. For regulatory compliance, consider S3 Object Lock in compliance mode with a retention period aligned to your records retention policy. This ensures the audit trail is tamper-proof."

---

### Architecture Expert Review

#### What's Done Well

The five-stage pipeline decomposition is well-reasoned and properly ordered. The layered evidence scoring (causal language 0.6, temporal 0.3, proximity 0.1, knowledge base 0.2) with a 0.4 threshold is a pragmatic design that allows multiple weak signals to compound. The honest acknowledgment that recall for relation extraction is 55-70% (meaning 30-45% of real adverse events are missed) sets correct expectations. The aggregation step using disproportionality analysis is the right approach for pharmacovigilance signal detection. The "Honest Take" section about iterative tuning of expected-effects filters is genuinely useful production guidance.

#### Issue A1: No Dead Letter Queue on the SQS Notes Queue (HIGH)

**Location:** Architecture Diagram, "Why These Services" SQS paragraph

**The problem:** The recipe describes SQS as providing "durable queue that decouples note ingestion from processing, handles retries on transient failures." But the architecture diagram and pseudocode show no DLQ configuration. If a clinical note consistently fails processing (malformed text, Comprehend Medical service error, Lambda timeout), SQS will retry delivery based on the visibility timeout and maxReceiveCount. Without a DLQ, the poisonous message remains in the queue indefinitely, consuming Lambda invocations on every retry cycle.

For a system processing 10,000 notes/day, even a 0.1% failure rate means 10 notes per day cycling endlessly. After a week, that's 70 notes burning Lambda invocations on every visibility timeout expiry.

**Suggested fix:** Add a DLQ to the architecture: "Configure a dead-letter queue (`notes-dlq`) with maxReceiveCount of 3. Notes that fail processing 3 times move to the DLQ for manual investigation. Set a CloudWatch alarm on DLQ depth > 0 to alert the operations team. The DLQ must have the same encryption (SSE-KMS) as the primary queue since messages contain note references."

#### Issue A2: Cost Estimate Is Significantly Understated (HIGH)

**Location:** Prerequisites table, Cost Estimate row; recipe header "~$0.03-0.10 per note"

**The problem:** The recipe header claims "$0.03-0.10 per note." The Prerequisites section states "Comprehend Medical: ~$0.01 per 100 characters (a typical note is 2000-5000 chars = $0.20-0.50 per note at full entity detection)."

These numbers are internally contradictory. The header says $0.03-0.10; the body says $0.20-0.50. Furthermore, the recipe calls both `DetectEntitiesV2` AND `InferRxNorm` on every note. InferRxNorm is a separate API call with its own pricing. At $0.01 per 100 characters for each API, processing a 3000-character note through both APIs costs approximately $0.60, not $0.03-0.10.

A health system processing 10,000 notes/day at $0.60/note is spending $6,000/day ($180,000/month) on Comprehend Medical alone. This needs to be stated clearly so decision-makers can evaluate ROI.

**Suggested fix:** Correct the header cost to "$0.40-1.00 per note" (accounting for both API calls and typical note lengths). Update the Prerequisites to show the calculation explicitly: "DetectEntitiesV2: ~$0.20-0.50 per note + InferRxNorm: ~$0.20-0.50 per note = $0.40-1.00 per note total. At 10,000 notes/day, expect $4,000-10,000/day in Comprehend Medical charges. Batch processing and selective note filtering (processing only notes from relevant departments) can reduce this significantly." Add a note that not every note needs RxNorm normalization; only notes where medications are detected in the first pass.

#### Issue A3: Severity Classification Default of Grade 2 Is Problematic (HIGH)

**Location:** Step 5 pseudocode, `classify_severity` function, default return

**The problem:** The function defaults to Grade 2 (moderate) when no severity indicators are found, with the rationale: "if the clinician documented it at all, it likely required some attention." This default means every detected adverse event that lacks explicit severity language (which is the majority of events in routine documentation) gets classified as "moderate." A system where 70-80% of detections are Grade 2 by default provides no meaningful severity stratification for the safety team.

The practical consequence: Grade 2 events presumably don't trigger real-time alerts (only Grade 3+ does), but they crowd the aggregation database with a uniform "moderate" label that conveys no information. The safety dashboard shows everything as moderate. The prioritization value of severity classification is lost.

**Suggested fix:** Change the default to Grade 1 (mild) with the rationale: "Without explicit severity indicators, assume the mildest category. This creates a more useful severity distribution where events explicitly described as requiring intervention (Grade 2+) stand out from baseline mentions. Clinicians who document severity-relevant context ('required dose change,' 'hospitalized') will naturally elevate the grade. The absence of severity language is more consistent with mild, self-limited events that were mentioned but not emphasized." Alternatively, add a "Grade unknown" category that gets flagged for manual severity assignment during review.

#### Issue A4: Cross-Note Reasoning Dismissed Without Architectural Guidance (MEDIUM)

**Location:** "The Honest Take" section, paragraph on implicit mentions

**The problem:** The recipe acknowledges that cross-note reasoning (connecting "feels worse" at visit 2 to a new medication started at visit 1) is where many false negatives originate, and advises "plan for it in your roadmap but don't try to build it first." This is sound prioritization advice, but the recipe provides no architectural sketch of how cross-note reasoning would integrate. A reader planning their roadmap has no starting point.

**Suggested fix:** Add 2-3 sentences in the Variations section: "Cross-note temporal reasoning requires maintaining a per-patient medication timeline (start dates, stop dates, dose changes) and comparing each new note's clinical findings against recently started medications. The medication timeline can be maintained in DynamoDB with patient_id as partition key and medication-start-date as sort key, updated from pharmacy feeds or medication reconciliation data. When processing a new note, query the patient's recently-started medications (last 30 days) and evaluate any new clinical findings against that list, even if the medication isn't mentioned in the current note."

#### Issue A5: Aggregation Step Assumes Expected Rate Lookup Exists but Doesn't Explain It (MEDIUM)

**Location:** Step 7 pseudocode, `lookup_expected_rate` function call

**The problem:** The aggregation logic calls `lookup_expected_rate(pair_key.rxnorm_code, pair_key.event)` as if this is a simple function, but building and maintaining an expected-rate baseline is itself a significant engineering challenge. The recipe doesn't explain where expected rates come from, how they're calculated, or how they're maintained. This is not a utility function; it's a core dependency that determines whether signals are valid.

**Suggested fix:** Add a paragraph after the aggregation pseudocode: "Expected rates can be derived from: (1) FAERS public data, which provides reporting rates for drug-event pairs nationally; (2) your own historical baseline calculated from the first 3-6 months of pipeline operation; or (3) published incidence rates from drug labels and clinical trials. Option (2) is most practical: calculate your institution's historical rate per drug-event pair, then flag pairs exceeding 2x that baseline. Store expected rates in a DynamoDB lookup table keyed by rxnorm_code and normalized event term, updated monthly."

#### Issue A6: No Deduplication Logic for Repeated Note Processing (MEDIUM)

**Location:** Steps 1-6, entire pipeline

**The problem:** The recipe processes notes "as they're signed in the EHR." In many EHR systems, notes can be amended, addended, or cosigned, each of which may trigger the integration feed again. If the same note (or a slightly modified version) arrives in the queue multiple times, the pipeline will generate duplicate adverse event records. The DynamoDB storage uses a generated `ae_id`, not a composite key that would prevent duplicates.

**Suggested fix:** Add an idempotency check in Step 1 or Step 6: "Before processing, check if this note_id has already been processed (query the archive bucket or maintain a processed-notes set in DynamoDB). If the note has been processed before, check if the text has changed (amendment). For amendments, delete prior AE records for this note_id and reprocess. For exact duplicates, skip. This prevents duplicate AE records from feed retries or EHR integration quirks."

---

### Networking Expert Review

#### What's Done Well

The VPC requirements are well-specified: "Lambda in VPC with VPC endpoints for S3, DynamoDB, SQS, Comprehend Medical, and CloudWatch Logs. Neptune requires VPC deployment." This covers the primary data path correctly. The explicit mention that Neptune requires VPC deployment (it cannot exist outside a VPC) prevents a common confusion point.

#### Issue N1: No VPC Endpoint for SNS (MEDIUM)

**Location:** Prerequisites table, VPC row

**The problem:** The recipe lists VPC endpoints for S3, DynamoDB, SQS, Comprehend Medical, and CloudWatch Logs. The `store_and_alert` function publishes to SNS for high-severity alerts. If the Lambda functions are deployed in a VPC (as the prerequisites require), the SNS publish call must either route through a VPC endpoint or through a NAT gateway to reach the public SNS endpoint.

The recipe does not list an SNS VPC endpoint. Without it, the high-severity alert path requires NAT gateway egress, which means: (a) a NAT gateway must exist in the VPC, (b) PHI-adjacent traffic (the alert message) traverses the NAT gateway and public internet to reach SNS, and (c) NAT gateway costs add up at volume.

**Suggested fix:** Add `sns` to the VPC endpoint list in Prerequisites: "VPC endpoints for S3 (gateway), DynamoDB (gateway), SQS, Comprehend Medical, CloudWatch Logs, and SNS (interface). Neptune is accessed directly within the VPC via security group rules."

#### Issue N2: Neptune Security Group Configuration Not Specified (MEDIUM)

**Location:** Prerequisites table, VPC row; "Why These Services" Neptune paragraph

**The problem:** Neptune is deployed in the VPC and accessed by the signal-aggregator Lambda function. The recipe doesn't specify the security group configuration for Neptune's port 8182. Without explicit guidance, a builder may use a permissive security group (allowing all inbound from the VPC CIDR on 8182), which grants any resource in the VPC access to the adverse event graph.

**Suggested fix:** Add a note: "Neptune security group: allow inbound TCP 8182 only from the security group attached to the signal-aggregator Lambda function and the safety dashboard service. Deny all other inbound. This limits graph database access to only the components that need it."

#### Issue N3: No Mention of KMS VPC Endpoint (LOW)

**Location:** Prerequisites table, VPC row

**The problem:** The recipe uses KMS encryption (SSE-KMS) on S3, SQS, and DynamoDB. Lambda functions in a VPC making calls to these services will implicitly call KMS for envelope encryption/decryption. Without a KMS VPC endpoint, these calls route through a NAT gateway. The recipe lists a KMS key in the Ingredients table but doesn't include a KMS VPC endpoint in the VPC configuration.

**Suggested fix:** Add `kms` to the VPC endpoint list: "Add a VPC endpoint for KMS (`com.amazonaws.{region}.kms`) to ensure encryption operations for S3, SQS, and DynamoDB don't require NAT gateway egress."

---

### Voice Reviewer

#### What's Done Well

The opening scenario (amlodipine/orthostatic dizziness) is vivid and specific. The progressive reveal of complexity ("Here's why") is classic CC voice. The parenthetical honesty ("the ground truth of 'all actual adverse events' is unknowable from documentation alone") is well-placed. The "Honest Take" section about the first week drowning in noise is exactly the right register. The progression from "it sounds simple" to "it isn't" is the signature pattern used effectively. No marketing language, no documentation-voice creep detected.

#### Issue V1: No Em Dashes Found (PASS)

Zero em dashes in the entire recipe. Clean.

#### Issue V2: Vendor Balance Is Appropriate (PASS)

The Technology section (approximately 60% of the recipe's word count) is entirely vendor-agnostic. AWS appears only in the AWS Implementation section. A reader on GCP or Azure would learn the full NLP pipeline architecture, the five-stage approach, and the challenges of relation extraction without encountering a single AWS service name. Slightly better than the 70/30 target (closer to 65/35 given the detailed pseudocode in the AWS section), but within acceptable range.

#### Issue V3: One Instance of Slightly Academic Tone (LOW)

**Location:** "The State of the Art" subsection

**The problem:** The phrase "Key benchmarks:" followed by bullet points with F1 scores and shared task names reads slightly more like a survey paper than an engineer at a whiteboard. The n2c2/i2b2 and TAC ADR references are valuable but the framing is academic rather than practical.

**Suggested fix:** Reframe as: "How well does this actually work? The best systems in research competitions (n2c2, TAC ADR) hit 80-90% F1 on finding medications and 60-75% on connecting them to adverse events. In production, most health systems report 70-85% precision on the adverse event detection itself. Translation: you'll catch most of the explicit stuff, miss a chunk of the implicit stuff, and your safety team will still need to validate what you flag."

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

1. **Security (S2) vs Architecture (A3) on alert content:** The security concern about PHI in SNS messages and the architecture concern about severity defaults interact. If severity defaults are fixed (A3) to produce more Grade 1 events, fewer alerts fire to SNS, reducing the PHI exposure risk (S2). Both should still be fixed independently, but A3 partially mitigates S2's operational exposure.

2. **Architecture (A2) vs Voice (cost framing):** The cost understatement in A2 is not just a technical error; it's a trust issue. If the recipe says $0.03-0.10 and reality is $0.40-1.00, the reader's confidence in other claims drops. This should be the highest priority fix from a credibility standpoint.

3. **Networking (N1, N2, N3) clustering:** The three networking issues are all "missing from the VPC endpoint/security group list" problems. They can be addressed with a single pass through the Prerequisites table and a more detailed VPC configuration note.

### Priority Resolution

The cost estimate error (A2) is the most impactful finding because it affects business decisions (ROI, budgeting, go/no-go). The DLQ absence (A1) is the most likely to cause operational pain in production. The SNS PHI leak (S2) is the most serious compliance risk. These three should be fixed first.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is architecturally sound, clinically accurate in its framing of the adverse event detection challenge, and provides actionable implementation guidance. The five-stage NLP pipeline is correctly structured, the layered evidence scoring is a pragmatic production pattern, and the honest acknowledgment of limitations (55-70% recall, months to signal detection, expected-effects tuning) sets appropriate expectations. No critical findings. The five HIGH findings are individually addressable without restructuring the recipe.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Header + Prerequisites cost row | Cost estimate internally contradictory and understated by 4-10x. Header says $0.03-0.10; body says $0.20-0.50; reality with both API calls is $0.40-1.00/note. | Correct header to $0.40-1.00. Show full calculation including both DetectEntitiesV2 and InferRxNorm. Add monthly estimate at volume. |
| 2 | HIGH | Architecture | Architecture Diagram, SQS section | No dead letter queue configured. Poison messages (malformed notes, persistent API errors) cycle indefinitely consuming Lambda invocations. | Add DLQ with maxReceiveCount=3, CloudWatch alarm on DLQ depth, same KMS encryption as primary queue. |
| 3 | HIGH | Security | Step 6 pseudocode, SNS publish | Full ae_record including patient_id published to SNS. If any subscriber is outside HIPAA boundary, this is PHI disclosure. | Publish only ae_id, severity, medication (generic), event description. Include dashboard link for full details. |
| 4 | HIGH | Security | Architecture Diagram, Neptune section | Neptune PHI access controls unspecified. No IAM DB auth, no security group scoping, no audit logging for graph queries containing patient data. | Add IAM DB auth requirement, security group restricted to aggregator Lambda, Neptune audit logs to CloudWatch. |
| 5 | HIGH | Architecture | Step 5, classify_severity default | Default Grade 2 (moderate) for events lacking severity language. 70-80% of detections will be "moderate" by default, eliminating meaningful severity stratification. | Default to Grade 1 (mild) or add "Grade unknown" category for manual triage. |
| 6 | MEDIUM | Architecture | Step 7, lookup_expected_rate call | Expected rate baseline assumed to exist but never explained. This is a critical dependency, not a utility function. | Add paragraph explaining sources: FAERS data, institutional historical baseline (first 3-6 months), published incidence rates. |
| 7 | MEDIUM | Architecture | Steps 1-6, full pipeline | No deduplication for amended/addended notes re-arriving in the queue. Same note processed multiple times creates duplicate AE records. | Add idempotency check on note_id. For amendments, delete prior AEs and reprocess. For exact duplicates, skip. |
| 8 | MEDIUM | Architecture | Honest Take section | Cross-note reasoning dismissed without architectural guidance. Reader planning roadmap has no starting point. | Add 2-3 sentences in Variations: medication timeline in DynamoDB, query recent starts when processing new notes. |
| 9 | MEDIUM | Networking | Prerequisites, VPC row | No SNS VPC endpoint listed. Lambda in VPC cannot reach SNS without it or a NAT gateway. High-severity alerts may fail silently. | Add SNS interface endpoint to VPC endpoint list. |
| 10 | MEDIUM | Networking | Prerequisites, VPC row | Neptune security group not specified. Default allows any VPC resource to query adverse event graph on port 8182. | Specify: allow inbound 8182 only from signal-aggregator Lambda SG and dashboard service SG. |
| 11 | MEDIUM | Security | Prerequisites, IAM row | `neptune-db:*` violates least-privilege. Dashboard needs read-only; aggregator needs read+write. | Split into ReadDataViaQuery for dashboard, Read+Write for aggregator. |
| 12 | MEDIUM | Security | DynamoDB storage, Step 6 | No retention policy on adverse event records. PHI accumulates indefinitely without TTL despite recipe mentioning TTL as a DynamoDB feature. | Add TTL configuration: Grade 1-2 retain 2 years, Grade 3-4 retain 7 years. Document rationale. |
| 13 | LOW | Networking | Prerequisites, VPC row | No KMS VPC endpoint. Envelope encryption calls for S3/SQS/DynamoDB route through NAT gateway. | Add KMS VPC endpoint to the list. |
| 14 | LOW | Security | Step 1, S3 archive | Audit trail archive has no Object Lock or versioning. Notes could be deleted or overwritten post-processing. | Add S3 versioning requirement. Note Object Lock in compliance mode for regulatory environments. |
| 15 | LOW | Voice | "The State of the Art" subsection | Tone shifts slightly academic with "Key benchmarks:" framing. Reads like a survey paper rather than engineer-at-whiteboard. | Reframe as conversational: "How well does this actually work?" followed by practical translation of the numbers. |

---

### Priority Actions Before Publication

1. **Fix cost estimate (Finding #1).** This is a credibility issue. The 4-10x discrepancy between header and reality will erode reader trust in the entire recipe. Straightforward arithmetic correction.

2. **Add DLQ to SQS queue (Finding #2).** Operational necessity for any production queue processing PHI. Standard pattern, easy to add to both the architecture diagram and prerequisites.

3. **Remove patient_id from SNS alert messages (Finding #3).** Compliance risk with a simple fix. Publish a reference (ae_id + dashboard link) instead of the full record.

4. **Add Neptune access controls (Finding #4).** IAM DB auth + security group scoping + audit logs. Standard Neptune security hardening that should be in any recipe using Neptune for PHI-adjacent data.

5. **Fix severity default (Finding #5).** Change default from Grade 2 to Grade 1. One-line change in pseudocode with updated rationale comment.

The remaining findings (6-15) are improvements that raise production-readiness but don't represent misinformation or compliance gaps.

---

*Review complete. Recipe 8.7 is a strong recipe that teaches the adverse event detection domain thoroughly and provides a sound architectural foundation. The findings above are refinements for production deployment, not structural problems with the approach.*
