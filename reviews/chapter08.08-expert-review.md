# Expert Review: Recipe 8.8 - Clinical Assertion Classification

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter08.08-clinical-assertion-classification.md`

---

## Overall Assessment

This is an excellent recipe. The problem statement is one of the best in the book: the opening example with "denies chest pain," "Mother had history of MI," and "consider starting atorvastatin" immediately makes the reader feel why naive entity extraction is dangerous in clinical NLP. The three-approach technology survey (rule-based, ML, deep learning, hybrid) is comprehensive and correctly ordered by maturity and complexity. The hybrid architecture (rules for easy 60%, ML for hard 40%) is the right production pattern. The pseudocode is detailed, well-commented, and each step has clear business justification.

The recipe delivers: a reader finishes understanding assertion classification as a concept, why it matters for downstream clinical systems, and how to build a hybrid pipeline on AWS. The "Honest Take" about Comprehend Medical's built-in negation being "better than most people give it credit for" is exactly the practical wisdom a deployer needs.

However: the Lambda orchestrator has no error handling or DLQ, the confidence threshold of 0.85 creates a human review queue with no guidance on its management, there is no data retention/lifecycle policy for annotated entities containing PHI, and the conflict resolution logic (Step 4) has a clinical correctness issue with its section-priority approach. Three HIGH findings, zero CRITICAL.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### Strengths

Solid HIPAA foundation: BAA explicitly required, SSE-KMS on S3, DynamoDB encryption at rest, SageMaker inter-container encryption enabled, all API calls over TLS, CloudTrail for Comprehend Medical and SageMaker API call auditing, VPC deployment specified for production with VPC endpoints for S3, Comprehend Medical, DynamoDB, and CloudWatch Logs. The "Never use real PHI in dev without appropriate safeguards" callout with i2b2 and MIMIC-III as alternatives is correct. IAM permissions are listed per-action and reasonably scoped.

#### Issue S1: No Data Retention or Lifecycle Policy for PHI in DynamoDB (HIGH)

**Location:** Step 5 pseudocode, `store_annotated_entities` function; Prerequisites table

**Problem:** The recipe stores assertion-annotated entities (which contain patient_id, note_id, entity text with clinical context snippets) in DynamoDB indefinitely. No TTL is configured. No retention policy is specified or even mentioned. HIPAA requires documented retention and disposal policies for PHI. The `note-assertion-summary` table also contains patient_id and note_id.

At scale (1000 patients, 50 notes/patient/year, 10 entities/note), this accumulates 500,000 PHI-containing records per year with no automated cleanup.

**Fix:** Add to Step 5: "Configure DynamoDB TTL on a `ttl_epoch` attribute. Suggested retention: align with institutional medical records retention policy (typically 7-10 years for adult records, longer for minors). Document retention decision per compliance requirements." Add to Prerequisites table: "Data Lifecycle: DynamoDB TTL configured per retention policy. S3 lifecycle policy for archived notes."

#### Issue S2: Context Snippets in DynamoDB Expand PHI Surface Area (MEDIUM)

**Location:** Step 5, `context_snippet` field in DynamoDB record

**Problem:** The stored record includes `context_snippet = result.entity.context_text[relevant portion]`. This stores surrounding clinical narrative (potentially mentioning other conditions, medications, family details) alongside the classified entity. This is legitimate for audit purposes, but expands the PHI surface area beyond what downstream query consumers need.

A downstream system querying "all present conditions for patient X" receives entity text + assertion status (needed) PLUS context snippets containing arbitrary clinical narrative (not needed for that query).

**Fix:** Add guidance: "Store context_snippet for audit trail. For downstream query APIs, return only entity_text, category, assertion_status, confidence, and note_id. Consumers needing full context should retrieve it from the source note (with appropriate access logging). Consider a separate audit table for context snippets with more restricted access."

#### Issue S3: `needs_review` Flag Without Access Control Guidance (MEDIUM)

**Location:** Step 5, `needs_review` field

**Problem:** Entities below the confidence threshold are flagged `needs_review = true`. The recipe provides no guidance on who reviews these, how the review queue is accessed, or how reviewer actions are logged. In a HIPAA environment, the review queue is a PHI access point requiring access controls and audit logging.

**Fix:** Add to "Why This Isn't Production-Ready" or a new section: "The human review queue (`needs_review = true` entities) requires: (1) role-based access control (clinical NLP team, not general staff); (2) audit logging of review actions (who reviewed, when, what assertion they assigned); (3) annotation interface that displays only the minimum context needed for classification."

#### Issue S4: SageMaker Endpoint IAM Does Not Scope to Specific Endpoint (LOW)

**Location:** Prerequisites table, IAM Permissions row

**Problem:** `sagemaker:InvokeEndpoint` without resource scoping allows the Lambda to invoke any SageMaker endpoint in the account. Should be scoped to the specific assertion classifier endpoint ARN.

**Fix:** Add resource constraint: `sagemaker:InvokeEndpoint` scoped to `arn:aws:sagemaker:{region}:{account}:endpoint/assertion-classifier-*`.

---

### Architecture Expert Review

#### Strengths

The hybrid architecture (rules first, ML second) is the correct production pattern. The rule-based layer handling 60% of cases at near-zero latency and cost while the ML model handles the genuinely ambiguous 40% is how mature clinical NLP systems actually work. The context window extraction (Step 2) with section header detection is architecturally appropriate. The conflict resolution step (Step 4) acknowledges a real problem that most tutorials ignore entirely. The performance benchmarks are realistic (88-93% F1 for 7-class, 93-97% for present/absent) and correctly cited as typical rather than guaranteed.

#### Issue A1: Lambda Pipeline Orchestrator Has No Error Handling or DLQ (HIGH)

**Location:** "Why These Services" Lambda paragraph; Architecture Diagram

**Problem:** The architecture shows Lambda as the pipeline orchestrator calling Comprehend Medical, then SageMaker, then DynamoDB. If Comprehend Medical throttles (rate limit), SageMaker times out (cold start or model error), or DynamoDB write fails (throughput exceeded), the entire pipeline fails silently. No retry logic, no DLQ, no partial-completion handling.

In production with event-driven triggers (note finalized in EHR), a failed Lambda invocation drops the note entirely. At 200 notes/hour with 2% transient failure rate: 4 notes/hour silently lost. Over a month, ~2900 notes never processed with no alerting.

**Fix:** Add to architecture: "Lambda invocation triggered via SQS (not direct event). SQS provides built-in retry with visibility timeout. Configure DLQ (`assertion-processing-dlq`) with maxReceiveCount=3. CloudWatch alarm on DLQ depth > 0. DLQ must have same SSE-KMS encryption (messages reference note_id which is PHI-adjacent). For partial failures: if entity extraction succeeds but assertion classification fails, store extracted entities with assertion='unclassified' and route to reprocessing queue."

#### Issue A2: Confidence Threshold Creates Unbounded Human Review Queue (HIGH)

**Location:** Step 3, `CONFIDENCE_THRESHOLD = 0.85`; Step 5, `needs_review` flag

**Problem:** At 0.85 threshold, any entity where the ML model is less than 85% confident gets flagged for human review. The recipe estimates 40% of entities go to the ML model (rules handle 60%). Of that 40%, a reasonable estimate is 20-30% will fall below 0.85 confidence (hedging language, ambiguous scope, complex conditionals). That's 8-12% of all entities.

At 200 notes/hour, ~10 entities/note, 10% below threshold: 200 entities/hour needing human review. That's 4800 entities/day, every day. No guidance on queue management, reviewer staffing, SLAs, or what happens to low-confidence entities while awaiting review (are they excluded from downstream systems? included with a caveat?).

**Fix:** Add guidance to "Why This Isn't Production-Ready": "The review queue at 0.85 threshold will generate hundreds of entities per day at even moderate volumes. Options: (1) Use a two-tier threshold: 0.70 (below = exclude from downstream until reviewed), 0.85 (between 0.70-0.85 = include in downstream with 'low_confidence' flag, queue for review). (2) Start threshold at 0.70 for initial deployment, raise as model improves. (3) Budget clinical annotator time: expect 20-30 seconds per entity review. At 200 entities/day, that's ~1.5 hours of reviewer time."

#### Issue A3: Conflict Resolution Section Priority Oversimplifies Clinical Reality (HIGH)

**Location:** Step 4, `SECTION_PRIORITY` mapping and resolution logic

**Problem:** The conflict resolution assigns static priority: Assessment (5) > HPI (4) > ROS (3) > PMH (2) > Family History (1). The logic says "highest section priority wins." This creates a clinical correctness issue:

A patient has "diabetes" in PMH (assertion: historical from rule). The same clinician writes in Assessment: "no active diabetes" (assertion: absent from rule). The recipe's logic picks Assessment (priority 5, assertion: absent) over PMH (priority 2, assertion: historical).

But the correct clinical interpretation may vary. "No active diabetes" in Assessment after "diabetes" in PMH means: the patient HAD diabetes (historical is correct) and it is currently NOT active (absent is also correct for current status). Both assertions are correct for different questions. The recipe flattens this into a single "winner" and discards the other.

More concerning: what if Assessment says "Type 2 DM" (present, from context) and PMH says "history of diabetes" (historical, from rule)? The recipe correctly picks Assessment's "present." But what if the Assessment mention is in a "Problem List" subsection that's actually a copy-forward artifact from 3 years ago? Section headers don't guarantee temporal relevance.

**Fix:** Revise Step 4 commentary: "Conflict resolution is domain-specific and imperfect. The section-priority approach handles the common case (Assessment reflects current clinical state) but fails on copy-forward notes, multi-day progress notes, and situations where both assertions are valid for different clinical questions. Production systems should: (1) retain all mentions with their individual assertions rather than resolving to a single 'winner'; (2) let downstream consumers specify which assertion is relevant to their use case (quality measures care about 'present,' risk models care about 'present OR historical'); (3) add a `conflict_resolution_strategy` parameter that downstream consumers can set."

Also update the pseudocode comment from "Pick the highest-priority one" to acknowledge this is a default heuristic, not ground truth.

#### Issue A4: SageMaker Cold Start Not Addressed for Real-Time Use Case (MEDIUM)

**Location:** "Why These Services" SageMaker paragraph; "Why This Isn't Production-Ready"

**Problem:** The recipe describes real-time inference ("classify assertions as notes are finalized in the EHR for immediate clinical decision support") using a SageMaker real-time endpoint. SageMaker real-time endpoints on ml.m5.xlarge have 5-15 second cold starts after auto-scaling from zero or initial deployment. The recipe mentions "auto-scaling helps but introduces cold-start latency" in the limitations section but provides no mitigation guidance.

For real-time CDS, a 10-second delay between note finalization and assertion availability may miss clinical decision windows.

**Fix:** Add to the real-time discussion: "To minimize cold starts: configure minimum instance count of 1 (keeps one instance warm 24/7, ~$170/month for ml.m5.xlarge). For cost-sensitive deployments, configure Application Auto Scaling with target tracking on InvocationsPerInstance. Accept that the first invocation after scale-up adds 5-15 seconds latency. For strict real-time requirements, consider SageMaker Serverless Inference (sub-second cold starts but lower throughput ceiling) or deploying the model in Lambda with ONNX runtime for simple transformer models."

#### Issue A5: No Monitoring or Alerting for Model Drift (MEDIUM)

**Location:** "Why This Isn't Production-Ready" mentions model drift; no operational guidance

**Problem:** The recipe correctly identifies model drift as a risk ("clinical documentation patterns change") but provides zero operational guidance. No metrics to monitor, no thresholds to alert on, no retraining trigger mechanism.

**Fix:** Add to architecture or limitations: "Monitor: (1) confidence score distribution over time (a shift toward lower scores indicates drift); (2) rule-vs-model ratio (if rules handle less than 50% of entities, something changed in documentation patterns); (3) human reviewer agreement rate on `needs_review` items (declining agreement suggests model and human are both uncertain). Alert when weekly average confidence drops below 0.80 or rule coverage drops below 50%. Plan retraining quarterly or when alerts fire."

#### Issue A6: Batch Processing Architecture Not Shown (LOW)

**Location:** General Architecture Pattern section mentions batch; no diagram or details

**Problem:** The recipe mentions "batch (process notes in bulk for research or quality measurement)" as a deployment pattern but only shows the real-time Lambda-orchestrated architecture. Research workloads processing 100K+ historical notes need different orchestration (Step Functions, SageMaker Batch Transform, parallel processing).

**Fix:** Add 2-3 sentences to Variations: "For batch research workloads: replace Lambda orchestration with Step Functions. Use SageMaker Batch Transform instead of real-time endpoint. Process notes in parallel batches of 100-500. Expected throughput: ~200 notes/minute per SageMaker instance with batch transform. A 100K note research corpus processes in ~8 hours on a single instance, or ~1 hour with 8-way parallelism."

---

### Networking Expert Review

#### Strengths

VPC requirements are explicit: Lambda and SageMaker in VPC with VPC endpoints for S3, Comprehend Medical, DynamoDB, and CloudWatch Logs. This covers the critical data path. All API calls specified over TLS. The separation of training data (S3) from inference (endpoint) is clean.

#### Issue N1: SageMaker Endpoint VPC Configuration Not Fully Specified (MEDIUM)

**Location:** Prerequisites table, VPC row; Architecture Diagram

**Problem:** The recipe says "Lambda and SageMaker in VPC" but does not specify whether the SageMaker endpoint is deployed in a VPC-configured mode (PrivateLink) or uses the public endpoint. SageMaker real-time endpoints can be deployed with VPC configuration (enabling private connectivity) or without (accessible via public internet with IAM auth). For PHI workloads, the endpoint should be VPC-configured so inference traffic stays within the private network.

**Fix:** Add to Prerequisites VPC row: "SageMaker endpoint: deploy with VPC configuration (creates ENIs in your VPC subnets). Lambda invokes endpoint via PrivateLink, no internet traversal. Required for PHI workloads to avoid sending clinical text over public internet to the inference endpoint."

#### Issue N2: No VPC Endpoint for SageMaker Runtime (MEDIUM)

**Location:** Prerequisites table, VPC row

**Problem:** VPC endpoints listed: S3, Comprehend Medical, DynamoDB, CloudWatch Logs. The Lambda calls `sagemaker:InvokeEndpoint` (SageMaker Runtime API). If the SageMaker endpoint is VPC-configured, invocation goes through the ENI. If it's not VPC-configured (or if you're using the SageMaker API endpoint for management operations), you need a `com.amazonaws.{region}.sagemaker.runtime` VPC endpoint. The recipe doesn't clarify this.

**Fix:** Add: "If SageMaker endpoint is not VPC-configured, add `com.amazonaws.{region}.sagemaker.runtime` interface endpoint. Preferred: deploy endpoint with VPC configuration (eliminates need for separate VPC endpoint for inference calls)."

#### Issue N3: No Subnet or AZ Guidance for Multi-AZ Resilience (LOW)

**Location:** Prerequisites table, VPC row

**Problem:** No mention of deploying Lambda and SageMaker across multiple AZs for resilience. A single-AZ deployment introduces an availability risk for a real-time CDS use case.

**Fix:** Add brief note: "Deploy Lambda and SageMaker endpoint across at least 2 AZs for production resilience. SageMaker real-time endpoints with multiple instances automatically distribute across AZs."

---

### Voice Reviewer

#### Strengths

The opening is outstanding. "Now ask a computer: does this patient have chest pain?" immediately makes the reader feel the gap between extraction and understanding. The progressive reveal of six different assertion contexts for the same word ("no fever" is not "fever resolved" is not "fever if infection present"...) builds genuine appreciation for the problem's complexity. The Technology section teaches without condescending: NegEx and ConText are explained with enough detail to understand why they work and where they break, without requiring prior NLP knowledge.

The Honest Take about rule-based layers being "genuinely underrated" and the taxonomy warning ("don't build a 7-class system if you only need present/absent") is exactly the kind of practical wisdom that separates this from a documentation page.

#### Issue V1: Em Dash Check (PASS)

Zero em dashes found. Clean.

#### Issue V2: Vendor Balance (PASS)

The Technology section and General Architecture Pattern are completely vendor-agnostic. Approximately 65% of total word count is vendor-neutral (NLP methodology, assertion categories, NegEx/ConText, ML approaches, field maturity). AWS enters only in "The AWS Implementation." A reader on GCP or Azure learns the full assertion classification methodology. Within acceptable range.

#### Issue V3: Minor Doc-Voice Creep in Prerequisites Table (LOW)

**Location:** Prerequisites table, various cells

**Problem:** Two phrases read slightly like documentation rather than engineer-at-whiteboard: "inter-container encryption enabled" and "requires DUA" are terse technical shorthand that could be more conversational. Not a violation, just slightly flatter than the recipe's otherwise strong voice.

**Fix:** Minor: "inter-container encryption enabled" could become "turn on inter-container encryption (prevents data leaking between inference containers on shared hardware)." And "requires DUA" could become "requires a Data Use Agreement, which takes 2-4 weeks to get approved."

#### Issue V4: "Where the Field Is Today" Section Slightly Survey-ish (LOW)

**Location:** "Where the Field Is Today" subsection

**Problem:** The four bullet points (pre-trained models, transfer learning, span-level classification, integration with extraction) read like a conference survey paper section. Each point is one paragraph of factual statement without the personality or "here's why you should care" energy present in the rest of the recipe.

**Fix:** Add a brief conversational framing at the top: "Ok, so where does all this actually stand in 2026? Four things have changed since the i2b2 2010 days that make assertion classification meaningfully more practical than it was a decade ago:" Then let the bullets flow as they are.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

1. **Architecture A1 (no DLQ) + Architecture A2 (review queue):** Both point to the same operational gap: the recipe has no operational guidance for handling failures or accumulation. The DLQ handles processing failures; the review queue handles classification uncertainty. Both need queue management patterns.

2. **Security S1 (retention) + Architecture A2 (review queue):** Items flagged for review accumulate in DynamoDB with PHI. If the review queue is never processed (understaffed, nobody assigned), PHI sits in a growing, unmanaged table. Retention policy and queue management need to work together.

3. **Architecture A3 (conflict resolution) + Security S2 (context snippets):** The recipe stores all mentions for audit (Step 4 says `all_mentions: mentions`), which is good for conflict resolution transparency. But those multiple mentions with their context snippets expand PHI surface area (Security concern). The fix is consistent: store full audit trail in a restricted table, expose only resolved assertions to downstream consumers.

4. **Networking N1/N2 (SageMaker VPC):** These overlap. If the endpoint is VPC-configured (N1), the VPC endpoint question (N2) is partially resolved. Address together.

### Priority Resolution

1. **Lambda DLQ (A1):** Operational stability. Silent note loss is unacceptable for clinical systems.
2. **Conflict resolution (A3):** Clinical correctness. Current logic can produce wrong "resolved" assertions.
3. **Review queue guidance (A2):** Operational sustainability. Without it, the system generates an unmanageable workload.
4. **PHI retention (S1):** Compliance requirement. Straightforward to add.
5. **SageMaker VPC (N1):** PHI in transit concern for real-time inference.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is clinically accurate, architecturally sound, and provides genuinely valuable guidance on a mature but underappreciated NLP task. The problem statement is one of the book's best. The hybrid rule+ML architecture is the correct production pattern. The technology survey (NegEx, ML classifiers, transformers) is comprehensive and correctly represents the state of the art. The honest limitations (training data quality, model drift, error propagation, real-time cost) are acknowledged. Three HIGH findings are individually addressable without structural changes. Zero CRITICAL findings.

---

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Architecture Diagram, Lambda section | Lambda orchestrator has no error handling, retry logic, or DLQ. Failed notes are silently lost. At 2% transient failure rate and 200 notes/hour: ~2900 notes/month dropped. | Add SQS queue between EHR event and Lambda. Configure DLQ with maxReceiveCount=3. CloudWatch alarm on DLQ depth > 0. Same SSE-KMS encryption on DLQ. |
| 2 | HIGH | Architecture | Step 4, `SECTION_PRIORITY` and resolution logic | Conflict resolution oversimplifies clinical reality. Static section priority produces incorrect "resolved" assertions for copy-forward notes, multi-day notes, and cases where both assertions are valid for different clinical questions. | Retain all mentions with individual assertions. Let downstream consumers specify resolution strategy. Acknowledge the heuristic is a default, not ground truth. |
| 3 | HIGH | Architecture | Step 3 threshold, Step 5 `needs_review` flag | 0.85 confidence threshold creates unbounded human review queue (~200 entities/day at moderate volume) with no guidance on management, staffing, SLAs, or interim handling. | Add two-tier threshold guidance (0.70 exclude / 0.85 flag). Estimate reviewer time (20-30s per entity). Address whether low-confidence entities are included in downstream with caveats or excluded until reviewed. |
| 4 | HIGH | Security | Step 5, DynamoDB storage | No data retention or lifecycle policy for PHI-containing assertion records. Records accumulate indefinitely. HIPAA requires documented retention and disposal. | Configure DynamoDB TTL. Specify retention aligned with institutional records retention policy (typically 7-10 years). Document policy in Prerequisites. |
| 5 | MEDIUM | Networking | Prerequisites, VPC row | SageMaker endpoint VPC configuration not specified. Clinical text may traverse public internet to reach inference endpoint if endpoint is not VPC-configured. | Deploy SageMaker endpoint with VPC configuration (PrivateLink). Specify in Prerequisites that PHI workloads require VPC-configured endpoints. |
| 6 | MEDIUM | Architecture | "Why This Isn't Production-Ready" | Model drift acknowledged with no operational guidance. No metrics to monitor, no alert thresholds, no retraining triggers. | Add monitoring guidance: track confidence score distribution, rule-vs-model ratio, reviewer agreement rate. Alert on weekly average confidence < 0.80 or rule coverage < 50%. |
| 7 | MEDIUM | Security | Step 5, `context_snippet` field | Context snippets store arbitrary clinical narrative alongside classified entities. Expands PHI surface area beyond what downstream consumers need. | Separate audit storage (full context, restricted access) from query API (entity + assertion only). Consumers needing context retrieve from source note with access logging. |
| 8 | MEDIUM | Security | Step 5, `needs_review` flag | Review queue is a PHI access point with no access control guidance or audit logging for reviewer actions. | Add guidance: role-based access for review queue, audit logging of review actions, minimum-context display for reviewers. |
| 9 | MEDIUM | Networking | Prerequisites, VPC row | SageMaker Runtime VPC endpoint not listed. If endpoint is not VPC-configured, Lambda cannot invoke it without VPC endpoint or NAT gateway. | Clarify: VPC-configured endpoint (preferred) eliminates need for separate VPC endpoint. Otherwise add `sagemaker.runtime` interface endpoint. |
| 10 | MEDIUM | Architecture | "Why This Isn't Production-Ready", SageMaker discussion | SageMaker cold start (5-15s) not mitigated for real-time CDS use case. May miss clinical decision windows. | Add: minimum instance count of 1 for warm endpoint (~$170/month). Mention SageMaker Serverless or Lambda+ONNX for cost-sensitive deployments. |
| 11 | LOW | Security | Prerequisites, IAM row | `sagemaker:InvokeEndpoint` not scoped to specific endpoint ARN. Lambda can invoke any endpoint in account. | Scope to `arn:aws:sagemaker:{region}:{account}:endpoint/assertion-classifier-*`. |
| 12 | LOW | Networking | Prerequisites, VPC row | No multi-AZ guidance for production resilience of real-time CDS pipeline. | Note: deploy Lambda and SageMaker across 2+ AZs for production. |
| 13 | LOW | Voice | Prerequisites table | Minor doc-voice in terse technical shorthand ("inter-container encryption enabled," "requires DUA") slightly flatter than recipe's otherwise strong conversational tone. | Expand briefly: explain what inter-container encryption prevents; note DUA approval takes 2-4 weeks. |
| 14 | LOW | Voice | "Where the Field Is Today" subsection | Four bullet points read like conference survey paper without the personality present elsewhere. | Add conversational framing: "Ok, so where does all this stand in 2026? Four things have changed..." |
| 15 | LOW | Architecture | General Architecture Pattern | Batch processing mentioned as deployment pattern but no architectural details provided. Research workloads need different orchestration. | Add to Variations: Step Functions + Batch Transform for research. ~200 notes/min per instance. 100K notes in ~8 hours single-instance. |

---

### Summary of Required Actions

1. **Add SQS + DLQ to pipeline** (Finding #1): Standard resilience pattern. Add between EHR event and Lambda. Prevents silent note loss.
2. **Revise conflict resolution commentary** (Finding #2): Acknowledge heuristic limitations. Recommend retaining all mentions rather than resolving to single winner. Let downstream consumers choose strategy.
3. **Add review queue operational guidance** (Finding #3): Two-tier threshold, staffing estimate, interim handling policy for unreviewed entities.
4. **Add data retention policy** (Finding #4): DynamoDB TTL, institutional alignment, documented in Prerequisites.
5. **Specify SageMaker VPC configuration** (Finding #5): PHI should not traverse public internet for inference.

Findings 6-15 improve production-readiness and operational clarity but are not misinformation or compliance gaps.

---

*Review complete. Recipe 8.8 is one of the strongest in Chapter 8. The clinical assertion classification domain is taught thoroughly and accurately. The hybrid rule+ML architecture is production-appropriate. The honest limitations are well-calibrated. The four HIGH findings are addressable refinements (operational resilience, clinical correctness nuance, queue management, and retention policy), not structural problems.*
