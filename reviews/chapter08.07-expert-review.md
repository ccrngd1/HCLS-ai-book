# Expert Review: Recipe 8.7 - Adverse Event Detection in Clinical Text

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.07-adverse-event-detection-clinical-text.md`

---

## Overall Assessment

This recipe tackles one of the most clinically impactful NLP problems in healthcare. The problem statement is excellent: grounding in the 1-13% voluntary reporting capture rate, the amlodipine scenario, and the systematic breakdown of why naive keyword matching fails. The five-stage pipeline (entity extraction, assertion filtering, relation extraction, severity classification, aggregation) is architecturally appropriate and well-sequenced. The layered evidence scoring for relation extraction is a mature, pragmatic design.

The recipe delivers: a reader finishes understanding why adverse event detection is hard, how the NLP pipeline works conceptually, and how to implement it on AWS. The honest take about the first-week noise flood and the months-to-meaningful-signals timeline is exactly what deployers need.

However, there are issues: the cost estimate in the header contradicts the body by 4-10x, there is no DLQ on the primary SQS queue, PHI leaks into SNS alert messages, Neptune access controls are unspecified, and the severity default of Grade 2 defeats the purpose of severity classification. Five HIGH findings, zero CRITICAL.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### Strengths

PHI handling baseline is solid: BAA explicitly required, SSE-KMS on S3/SQS, DynamoDB encryption at rest, Neptune encryption at rest, TLS in transit, CloudTrail enabled, VPC with VPC endpoints for all primary services, and the "never use real patient notes in non-production" callout with MIMIC-III as dev alternative. The `status: "pending_review"` default enforces human-in-the-loop before clinical action. The IAM permissions list is explicit and reasonably scoped (except Neptune, noted below).

#### Issue S1: SNS Alert Publishes Full AE Record With Patient Identifiers (HIGH)

**Location:** Step 6 pseudocode, `store_and_alert` function

**Problem:** The pseudocode publishes the full `ae_record` to SNS:
```text
PUBLISH to SNS topic "ae-critical-alerts":
    subject: "High-severity adverse event detected"
    message: ae_record (formatted for human readability)
```

The `ae_record` includes `patient_id` and `note_id`. SNS delivers to subscribers (email, SMS, HTTPS, SQS). If any subscriber endpoint is outside the HIPAA boundary (email to non-covered recipients, webhook to external system without BAA), this constitutes unauthorized PHI disclosure.

**Fix:** Publish only `ae_id`, `severity`, generic medication name, and event description (no patient identifiers). Include a link to the internal safety dashboard where authenticated, authorized users can view full details. Add note: "Never include patient_id or note_id in SNS messages. Subscriber endpoints may not all be within your HIPAA-covered boundary."

#### Issue S2: Neptune PHI Access Controls Absent (HIGH)

**Location:** Architecture Diagram and "Why These Services" Neptune paragraph

**Problem:** Neptune stores a graph linking patient_id nodes to drug nodes and adverse event nodes. This is PHI. The recipe mentions "requires VPC deployment" and "encryption at rest" but provides no guidance on:
- IAM database authentication (Neptune supports this for fine-grained access)
- Security group rules restricting port 8182 access to only the signal-aggregator Lambda
- Audit logging for graph queries (who queried which patient's AE relationships)
- Whether dashboard reads go through a read replica or the primary instance

A builder following this recipe literally will deploy Neptune accessible to any resource in the VPC.

**Fix:** Add to Prerequisites: "Neptune: IAM database authentication enabled, security group inbound 8182 restricted to signal-aggregator Lambda SG only, audit logs enabled to CloudWatch Logs." In the Ingredients table for Neptune: "Access restricted via IAM DB auth and security groups. Enable audit logs for PHI access tracking."

#### Issue S3: Neptune IAM Permission Is Wildcard (MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**Problem:** `neptune-db:*` (scoped to cluster) grants full read+write to the graph. The signal-aggregator Lambda needs read+write. A safety dashboard service needs read-only. Single wildcard permission for all consumers violates least-privilege.

**Fix:** Split: `neptune-db:ReadDataViaQuery` for read-only consumers, `neptune-db:ReadDataViaQuery` + `neptune-db:WriteDataViaQuery` for the aggregator Lambda. Document per-role.

#### Issue S4: No DynamoDB TTL or Retention Policy for PHI Records (MEDIUM)

**Location:** Step 6, DynamoDB storage; "Why These Services" DynamoDB paragraph

**Problem:** The recipe mentions DynamoDB's "TTL feature can manage retention policies" but never configures TTL or specifies a retention policy. Adverse event records with patient_id and clinical findings accumulate indefinitely. HIPAA requires documented retention and disposal policies for PHI.

**Fix:** Add to Step 6 or a configuration section: "Configure DynamoDB TTL on `ttl_epoch` attribute. Suggested: Grade 1-2 events retain 2 years, Grade 3-4 events retain 7 years (aligned with most US state medical records retention laws). Document retention policy per institutional compliance requirements."

#### Issue S5: S3 Archive Lacks Immutability Controls (LOW)

**Location:** Step 1, S3 archive

**Problem:** The audit trail archive should be tamper-proof. No mention of S3 versioning or Object Lock. A malicious or accidental deletion of processed notes destroys the audit trail.

**Fix:** Add: "Enable S3 versioning on the notes-archive bucket. For regulatory environments, enable S3 Object Lock in compliance mode with retention aligned to records retention policy."

---

### Architecture Expert Review

#### Strengths

The five-stage pipeline is correctly decomposed and ordered. The layered evidence scoring (causal language 0.6, temporal 0.3, proximity 0.1, knowledge base 0.2, threshold 0.4) is pragmatic and allows weak signals to compound. The honest performance benchmarks (55-70% recall, 15-30% false positive rate) set correct expectations. The aggregation step using disproportionality analysis is the correct pharmacovigilance approach. The "Honest Take" on expected-effects tuning and the months-to-signal-detection reality is genuine production wisdom.

#### Issue A1: No Dead Letter Queue on SQS Notes Queue (HIGH)

**Location:** Architecture Diagram; "Why These Services" SQS paragraph

**Problem:** SQS is described as handling "retries on transient failures" but no DLQ is configured. If a note consistently fails processing (malformed text, Comprehend Medical timeout, Lambda error), SQS retries indefinitely based on visibility timeout. Without a DLQ and maxReceiveCount, poison messages cycle forever, burning Lambda invocations.

At 10,000 notes/day with 0.1% persistent failure rate: 10 notes/day cycling indefinitely. After a month, 300 poison messages consuming retries continuously.

**Fix:** Add DLQ: "Configure `notes-processing-dlq` with maxReceiveCount=3. Failed notes move to DLQ after 3 attempts. CloudWatch alarm on DLQ depth > 0. DLQ must have same SSE-KMS encryption as primary queue (messages reference PHI)."

#### Issue A2: Cost Estimate Internally Contradictory and Understated (HIGH)

**Location:** Recipe header ("~$0.03-0.10 per note"); Prerequisites table, Cost Estimate row

**Problem:** The header claims "$0.03-0.10 per note." The Prerequisites section states "$0.01 per 100 characters (a typical note is 2000-5000 chars = $0.20-0.50 per note at full entity detection)." These are contradictory. Furthermore, the recipe calls BOTH `DetectEntitiesV2` AND `InferRxNorm` per note. Each is billed separately. A 3000-character note through both APIs: ~$0.30 + ~$0.30 = ~$0.60.

At 10,000 notes/day and $0.60/note: $6,000/day, $180,000/month. The header's $0.03-0.10 claim is off by an order of magnitude.

**Fix:** Correct header to "$0.40-1.00 per note." Update Prerequisites cost estimate with explicit calculation showing both API calls. Add monthly projection at volume. Note that InferRxNorm only needs to run on notes where medications were detected (not every note), which can reduce costs for non-medication-related notes.

#### Issue A3: Severity Default of Grade 2 Destroys Stratification Value (HIGH)

**Location:** Step 5 pseudocode, `classify_severity` function, default return

**Problem:** When no severity indicators are found (which will be the majority of clinical documentation), the function defaults to Grade 2 (moderate). Rationale given: "if the clinician documented it at all, it likely required some attention."

Result: 70-80% of detections default to Grade 2. The safety dashboard shows a wall of "moderate" events with no meaningful differentiation. The severity classification step adds no information for the majority of detections.

**Fix:** Default to Grade 1 (mild). Rationale: absence of severity indicators is consistent with routine mentions. Events with actual clinical impact will have documentation context ("dose reduced," "admitted," "discontinued") that the indicator matching will catch. Alternative: introduce "ungraded" category flagged for manual severity assignment.

#### Issue A4: `lookup_expected_rate` Is an Unexplained Critical Dependency (MEDIUM)

**Location:** Step 7 pseudocode, aggregation function

**Problem:** The aggregation logic calls `lookup_expected_rate(rxnorm_code, event)` as if it is a trivial utility function. Building and maintaining an expected-rate baseline is a significant engineering effort. The recipe provides no guidance on data sources, calculation methodology, or maintenance cadence.

**Fix:** Add after the aggregation pseudocode: "Expected rates can be sourced from: (1) FAERS public data for national reporting rates; (2) institutional historical baseline from first 3-6 months of operation; (3) drug label incidence rates from clinical trials. Most practical: calculate your institution's rate per drug-event pair over a rolling 6-month window, store in a DynamoDB lookup table, update monthly. Flag pairs exceeding 2x baseline with minimum 3 unique patients."

#### Issue A5: No Idempotency or Deduplication for Re-processed Notes (MEDIUM)

**Location:** Steps 1-6, full pipeline

**Problem:** EHR notes may be amended, addended, or cosigned, each triggering the integration feed again. The pipeline generates a new `ae_id` (unique ID) per detection, so reprocessing the same note creates duplicate adverse event records. No deduplication logic exists.

**Fix:** Add idempotency check: "Before processing, query the archive for this note_id. If previously processed and text is unchanged, skip. If text changed (amendment), delete prior AE records for this note_id and reprocess. Use note_id + text hash as the idempotency key."

#### Issue A6: Cross-Note Reasoning Mentioned but No Architectural Sketch Provided (MEDIUM)

**Location:** "The Honest Take" section

**Problem:** Cross-note reasoning is acknowledged as a key source of false negatives ("'feels worse' at visit 2 connected to medication started at visit 1") but dismissed with "plan for it but don't build it first." A reader planning their roadmap has no architectural starting point.

**Fix:** Add 2-3 sentences in Variations: "Cross-note reasoning requires a per-patient medication timeline (start/stop/dose changes) maintained in DynamoDB or a timeline service, updated from pharmacy feeds. When processing a new note, query medications started in the last 30 days for that patient and evaluate new clinical findings against them, even without explicit medication mention in the current note."

---

### Networking Expert Review

#### Strengths

VPC requirements are explicitly stated: "Lambda in VPC with VPC endpoints for S3, DynamoDB, SQS, Comprehend Medical, and CloudWatch Logs. Neptune requires VPC deployment." This covers the primary data path. Neptune's mandatory VPC deployment is correctly noted.

#### Issue N1: SNS VPC Endpoint Missing (MEDIUM)

**Location:** Prerequisites table, VPC row

**Problem:** The recipe lists VPC endpoints for S3, DynamoDB, SQS, Comprehend Medical, and CloudWatch Logs. The `store_and_alert` function publishes to SNS. Lambda in a VPC cannot reach SNS without either a VPC endpoint or NAT gateway. The SNS VPC endpoint is not listed. Without it, high-severity alerts either fail silently or require NAT gateway egress (PHI-adjacent traffic over NAT, additional cost).

**Fix:** Add `SNS` to VPC endpoint list: "VPC endpoints for S3 (gateway), DynamoDB (gateway), SQS (interface), Comprehend Medical (interface), CloudWatch Logs (interface), and SNS (interface)."

#### Issue N2: Neptune Security Group Not Specified (MEDIUM)

**Location:** Prerequisites table, VPC row

**Problem:** Neptune port 8182 access is not scoped. Without explicit security group guidance, builders may allow all inbound from VPC CIDR, granting any resource in the VPC access to the PHI-containing graph.

**Fix:** Add: "Neptune security group: inbound TCP 8182 allowed only from signal-aggregator Lambda security group and safety dashboard service security group. All other inbound denied."

#### Issue N3: KMS VPC Endpoint Not Mentioned (LOW)

**Location:** Prerequisites table, VPC row

**Problem:** SSE-KMS is used on S3, SQS, DynamoDB. Lambda in VPC implicitly calls KMS for encryption operations. Without a KMS VPC endpoint, these calls route through NAT gateway.

**Fix:** Add KMS to VPC endpoint list: "Add `com.amazonaws.{region}.kms` interface endpoint."

---

### Voice Reviewer

#### Strengths

Opening scenario is vivid, specific, and grounded (amlodipine, orthostatic dizziness, 47 mentions found in retrospective review). The progressive complexity reveal ("Here's why" ... "It isn't") is on-brand. Parenthetical honesty works well ("the ground truth of 'all actual adverse events' is unknowable from documentation alone"). The Honest Take about drowning in noise the first week is exactly the right register. No marketing language. No documentation-voice ("This recipe demonstrates how to leverage..."). The engineering enthusiasm comes through in the detailed explanation of why naive approaches fail.

#### Issue V1: Em Dash Check (PASS)

Zero em dashes found. Clean.

#### Issue V2: Vendor Balance (PASS)

The Technology section is entirely vendor-agnostic (approximately 60% of total word count). AWS appears only in the AWS Implementation section. A GCP/Azure reader learns the full pipeline architecture, relation extraction challenges, and aggregation methodology without encountering AWS. Within acceptable 70/30 range (actual closer to 65/35 given detailed AWS pseudocode, but acceptable).

#### Issue V3: Slightly Academic Tone in "State of the Art" (LOW)

**Location:** "The State of the Art" subsection

**Problem:** "Key benchmarks:" followed by bullet-pointed F1 scores and shared task names (n2c2, TAC ADR) reads like a literature review rather than an engineer explaining at a whiteboard.

**Fix:** Reframe conversationally: "How well does this stuff actually work? Best research systems hit 80-90% F1 on finding medications and 60-75% on connecting them to adverse events. In production at real health systems, you're looking at 70-85% precision. Translation: you'll catch most of the obvious stuff, miss a good chunk of the implicit stuff, and your safety team will still need to review what you flag."

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

1. **Security S1 (SNS PHI) + Architecture A3 (severity default):** If severity defaults are corrected to Grade 1, fewer events trigger Grade 3+ alerts to SNS, reducing the volume of PHI-exposure-risk messages. But the fix for S1 (remove identifiers from messages) is required regardless of volume.

2. **Security S2 (Neptune access) + Networking N2 (Neptune SG):** These are the same underlying problem viewed from different lenses. The fix is unified: IAM DB auth + scoped security groups + audit logs. Address together.

3. **Architecture A2 (cost):** This is a credibility issue that affects the entire recipe. If the reader catches the 10x discrepancy between header and reality, trust in all other claims erodes. Highest priority fix from editorial perspective.

4. **Networking N1/N2/N3 clustering:** All three are "missing from VPC configuration" issues. Single pass through Prerequisites table resolves all.

### Priority Resolution

1. **Cost estimate (A2):** Credibility and business-decision impact. Fix first.
2. **DLQ (A1):** Operational stability. Standard pattern, easy to add.
3. **SNS PHI (S1):** Compliance risk with simple fix.
4. **Neptune access (S2 + N2):** Combined security/networking fix.
5. **Severity default (A3):** One-line pseudocode change with updated rationale.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is architecturally sound, clinically accurate, and provides actionable guidance. The five-stage NLP pipeline is correctly structured. The layered evidence scoring is production-appropriate. The honest limitations (55-70% recall, months to signals, expected-effects tuning needed) set correct expectations. The domain expertise in explaining why adverse event detection is genuinely hard (implicit mentions, temporal reasoning, negation, severity inference) is strong. Zero CRITICAL findings. Five HIGH findings are individually addressable without structural changes.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Header + Prerequisites cost row | Cost estimate contradicts itself (header $0.03-0.10 vs body $0.20-0.50) and understates reality by 4-10x. Both DetectEntitiesV2 and InferRxNorm are called per note. | Correct header to "$0.40-1.00 per note." Show full dual-API calculation. Add monthly projection at 10K notes/day. |
| 2 | HIGH | Architecture | Architecture Diagram, SQS section | No dead letter queue. Poison messages cycle indefinitely burning Lambda invocations. | Add DLQ with maxReceiveCount=3, CloudWatch alarm on depth > 0, same SSE-KMS encryption. |
| 3 | HIGH | Security | Step 6, SNS publish | Full ae_record with patient_id published to SNS. PHI disclosure risk if any subscriber is outside HIPAA boundary. | Publish only ae_id, severity, medication, event description. Link to dashboard for full details. |
| 4 | HIGH | Security | Architecture Diagram, Neptune | Neptune PHI access controls unspecified. No IAM DB auth, no SG scoping, no audit logging for queries on patient data graph. | Add IAM DB auth, SG restricted to aggregator Lambda, Neptune audit logs to CloudWatch. |
| 5 | HIGH | Architecture | Step 5, default severity | Default Grade 2 for events without severity indicators. Majority of detections will be "moderate," eliminating meaningful stratification. | Default to Grade 1 (mild) or add "ungraded" category for manual assignment. |
| 6 | MEDIUM | Architecture | Step 7, `lookup_expected_rate` | Expected rate baseline treated as trivial utility but is a critical dependency with no explanation of data source or methodology. | Add paragraph: FAERS data, institutional 6-month rolling baseline, or drug label rates. Store in DynamoDB lookup, update monthly. |
| 7 | MEDIUM | Architecture | Steps 1-6, full pipeline | No idempotency for amended/addended notes. Duplicate AE records created on reprocessing. | Add note_id + text hash idempotency check. Skip unchanged, reprocess amendments with prior record deletion. |
| 8 | MEDIUM | Architecture | Honest Take section | Cross-note reasoning dismissed without architectural sketch. Readers planning roadmap have no starting point. | Add to Variations: per-patient medication timeline in DynamoDB, query recent starts when processing new notes. |
| 9 | MEDIUM | Networking | Prerequisites, VPC row | SNS VPC endpoint missing. Lambda in VPC cannot publish alerts without it or NAT gateway. | Add SNS interface endpoint to VPC endpoint list. |
| 10 | MEDIUM | Networking | Prerequisites, VPC row | Neptune security group unspecified. Any VPC resource can query port 8182 by default. | Specify inbound 8182 only from aggregator Lambda SG and dashboard SG. |
| 11 | MEDIUM | Security | Prerequisites, IAM row | `neptune-db:*` is wildcard. Dashboard needs read-only; aggregator needs read+write. | Split into ReadDataViaQuery (dashboard) and Read+Write (aggregator). |
| 12 | MEDIUM | Security | Step 6, DynamoDB | No TTL or retention policy despite recipe mentioning TTL as a feature. PHI accumulates indefinitely. | Configure TTL: Grade 1-2 retain 2 years, Grade 3-4 retain 7 years. Document per institutional policy. |
| 13 | LOW | Networking | Prerequisites, VPC row | KMS VPC endpoint missing. Encryption operations for S3/SQS/DynamoDB route through NAT gateway. | Add KMS interface endpoint to VPC endpoint list. |
| 14 | LOW | Security | Step 1, S3 archive | Audit trail archive has no versioning or Object Lock. Notes can be deleted post-processing. | Enable S3 versioning. Note Object Lock in compliance mode for regulated environments. |
| 15 | LOW | Voice | "The State of the Art" subsection | Slightly academic tone ("Key benchmarks:" + F1 scores) reads like literature review rather than engineer-at-whiteboard. | Reframe conversationally: "How well does this actually work?" with practical translation of numbers. |

---

### Summary of Required Actions

1. **Fix cost estimate** (Finding #1): Arithmetic correction + monthly projection. Credibility issue.
2. **Add DLQ** (Finding #2): Standard SQS pattern, add to diagram and prerequisites.
3. **Strip PHI from SNS alerts** (Finding #3): Publish reference only, not full record.
4. **Add Neptune access controls** (Finding #4): IAM DB auth + SG + audit logs.
5. **Fix severity default** (Finding #5): Change to Grade 1, update rationale comment.

Findings 6-15 improve production-readiness but are not misinformation or compliance gaps.

---

*Review complete. Recipe 8.7 is architecturally sound and clinically well-grounded. The adverse event detection domain is taught thoroughly with appropriate honesty about limitations. The five HIGH findings are individually addressable refinements, not structural problems.*
