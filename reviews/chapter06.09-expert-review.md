# Expert Review: Recipe 6.9 - Social Determinant Phenotyping

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter06.09-social-determinant-phenotyping.md`

---

## Overall Assessment

This is an excellent recipe. The problem framing is deeply empathetic and clinically grounded. The technology section teaches multi-modal clustering on sparse, sensitive data without vendor lock-in. The equity audit discussion is not an afterthought but woven throughout the architecture. The "Honest Take" section is genuinely insightful, particularly the observation that the largest cluster is always "we don't know." The pseudocode is well-commented and the feature engineering section is one of the strongest in the chapter, with explicit handling of missingness semantics (distinguishing "screened negative" from "never screened").

The recipe has no critical findings. There are a few high-severity gaps around patient address geocoding (PHI exposure surface), the lack of consent/governance discussion for NLP extraction from notes, and a missing DLQ/error handling pattern in the Lambda orchestration. The voice is strong and consistent throughout.

**Verdict: PASS**

Priority breakdown: 0 critical, 2 high, 5 medium, 3 low.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

BAA requirement is explicit and correctly scoped to all services handling PHI. Encryption at rest (SSE-KMS for S3, DynamoDB default encryption) and in transit (TLS) are specified. CloudTrail for audit logging is included. VPC placement with VPC endpoints for S3, DynamoDB, Comprehend Medical, and CloudWatch Logs is specified. The "never use real patient notes in development" warning is present. The separation of raw notes from extracted features is architecturally sound for PHI minimization. The staleness threshold pattern prevents stale phenotype data from persisting indefinitely.

#### Issue S1: Patient Address Geocoding Creates PHI Exposure Surface (HIGH)

**Location:** Step 2 pseudocode (`assemble_patient_features`), line: `geocode_result = call LocationService.SearchPlaceIndex(Text = address)`

**The problem:** Patient home addresses are PHI under HIPAA. The recipe sends raw patient addresses to Amazon Location Service for geocoding. While Location Service is a HIPAA-eligible service (covered under BAA), the recipe provides no guidance on: (1) whether the address should be truncated to zip+4 or census tract before geocoding (reducing precision to reduce PHI sensitivity), (2) whether geocoding results should be cached to avoid repeated PHI transmission, (3) whether the geocoding call should be logged as a PHI access event for accounting of disclosures.

Additionally, the architecture diagram shows patient addresses flowing to Location Service without passing through the VPC. If Location Service is called via public endpoint rather than VPC endpoint, the address transits the public internet (albeit over TLS).

**Suggested fix:** Add guidance: (1) recommend geocoding at the zip+4 level rather than full street address when census-tract-level precision is sufficient (it is for ADI/SVI lookup), (2) note that Location Service should be called via VPC endpoint in production, (3) recommend caching geocode results in the feature store to avoid repeated address transmission, (4) note that geocoding calls should be included in application-level audit logging.

#### Issue S2: IAM Permissions Not Resource-Scoped (MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The permissions listed (`comprehend:DetectEntities`, `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `glue:StartJobRun`, `geo:SearchPlaceIndexForText`) are action-level but not resource-scoped. A builder following this literally might grant these on `*` rather than on specific resource ARNs.

**Suggested fix:** Add a note: "Scope all permissions to specific resource ARNs in production. For example, `sagemaker:InvokeEndpoint` should be scoped to `arn:aws:sagemaker:REGION:ACCOUNT:endpoint/sdoh-ner-model`, and `s3:GetObject` to the specific bucket and prefix containing clinical notes." One sentence is sufficient.

#### Issue S3: Feature Snapshot in DynamoDB Contains Derived PHI (MEDIUM)

**Location:** Step 5 pseudocode, `feature_snapshot = feature_snapshot`

**The problem:** The phenotype assignment stored in DynamoDB includes a `feature_snapshot` field containing the full feature vector at time of assignment. This includes NLP-derived features (which SDOH domains were mentioned), screening scores, ADI rank, and SVI score. While individually these may not identify a patient, in combination with the patient_id they constitute derived PHI. The recipe provides no guidance on: (1) whether the feature snapshot should be stored in DynamoDB or referenced from S3, (2) retention policy for feature snapshots, (3) whether the snapshot should be encrypted with a separate KMS key from the phenotype label itself (defense in depth).

**Suggested fix:** Add a note that the feature_snapshot is PHI and should be subject to the same retention and access controls as the source data. Consider storing only a reference (S3 URI) in DynamoDB rather than the full snapshot, to keep the real-time lookup store lean and reduce the PHI surface in DynamoDB.

#### Issue S4: No Application-Level Audit Logging for Phenotype Queries (MEDIUM)

**Location:** Architecture generally; DynamoDB lookup by care management systems

**The problem:** CloudTrail captures DynamoDB API calls but not the business-level event of "Care Manager X queried phenotype for Patient Y." HIPAA's accounting of disclosures requirement means you need to track who accessed which patients' SDOH phenotype data. The recipe mentions CloudTrail but doesn't address application-level audit logging for the downstream care management integration.

**Suggested fix:** Add a requirement for application-level audit logging at the care management integration point. Each phenotype lookup should log: requesting user/system, patient_id, timestamp, and phenotype returned. Reference this as a HIPAA accounting-of-disclosures control.

---

### Architecture Expert Review

#### What's Done Well

The multi-stage pipeline (NLP extraction, feature assembly, clustering, validation, intervention matching) is clean and well-motivated. The two-pass NLP approach (Comprehend Medical for broad detection, SageMaker for SDOH-specific extraction) is pragmatic and avoids over-reliance on a single model. The explicit handling of missingness in feature engineering is excellent and often overlooked. The Gower distance choice for mixed data types is well-justified. The staleness threshold pattern is operationally sound. The equity audit is integrated into the pipeline rather than being an afterthought. The "Low Documentation / Minimal Indicators" cluster in the expected results is honest and realistic.

#### Issue A1: No Error Handling or DLQ Pattern in Lambda Orchestration (HIGH)

**Location:** Architecture diagram and "AWS Lambda for orchestration" in Why These Services

**The problem:** The architecture shows Lambda triggering NLP extraction when new notes arrive in S3. But there's no discussion of: (1) what happens when Comprehend Medical or the SageMaker endpoint returns an error (throttling, model errors, malformed input), (2) whether failed extractions are retried or dead-lettered, (3) how partial failures in batch processing are handled (some notes succeed, some fail). In a healthcare enterprise environment processing thousands of notes daily, failures are not edge cases. Without a DLQ pattern, failed extractions silently disappear, creating gaps in the feature matrix that look identical to "no SDOH mentions found."

This is particularly insidious for SDOH phenotyping because the recipe correctly identifies that absence of signal is ambiguous (never screened vs. screened negative). Adding a third ambiguity (extraction failed silently) makes the clustering results unreliable.

**Suggested fix:** Add a brief discussion of error handling: (1) Lambda should write failed note IDs to an SQS dead-letter queue for retry/investigation, (2) the feature assembly step should distinguish "no extractions found" from "extraction never attempted" (e.g., by checking whether the note was processed at all), (3) a CloudWatch alarm should fire when the DLQ depth exceeds a threshold. This can be 2-3 sentences in the architecture section.

#### Issue A2: Clustering Re-Run Cadence Not Specified (MEDIUM)

**Location:** General architecture, between Stage 3 (Clustering) and Stage 5 (Store)

**The problem:** The recipe discusses staleness thresholds for individual phenotype assignments (180 days) but doesn't specify how often the full clustering is re-run. Is it daily? Weekly? Monthly? On-demand when enough new data accumulates? The "Real-time phenotype assignment" variation mentions assigning new patients to existing centroids, but the base architecture doesn't clarify the batch re-clustering cadence. This matters because: (1) new patients accumulate between runs and have no phenotype, (2) the cluster structure itself may shift as the population changes, (3) the equity audit needs to be re-run with each new clustering.

**Suggested fix:** Add a recommendation for re-clustering cadence. A common pattern: weekly incremental assignment (new patients to existing centroids) with monthly full re-clustering and equity audit. Note that the cadence should be driven by the rate of new SDOH data accumulation, not by calendar alone.

#### Issue A3: No Discussion of Cluster Drift Detection (LOW)

**Location:** Expected Results, "Where it struggles" section

**The problem:** The recipe mentions that "a patient's phenotype can change faster than the re-clustering cadence" but doesn't discuss cluster-level drift: the phenomenon where the cluster structure itself changes over time (e.g., a new social determinant emerges, or a community resource eliminates a previously common barrier). Without drift detection, the system may continue assigning patients to phenotypes that no longer reflect the population's actual social determinant patterns.

**Suggested fix:** Add a brief mention in "Variations and Extensions" or "Where it struggles" that cluster drift should be monitored (e.g., by comparing silhouette scores and cluster size distributions across consecutive runs) and that significant drift should trigger a full re-validation with clinical stakeholders.

---

### Networking Expert Review

#### What's Done Well

VPC placement is specified for SageMaker endpoints and Glue jobs. VPC endpoints are explicitly listed for S3, DynamoDB, Comprehend Medical, and CloudWatch Logs. All transit is over TLS. The architecture keeps PHI within the VPC boundary for compute operations.

#### Issue N1: Location Service VPC Endpoint Not Mentioned (MEDIUM)

**Location:** Prerequisites table, VPC row

**The problem:** The VPC row specifies VPC endpoints for S3, DynamoDB, Comprehend Medical, and CloudWatch Logs. But Amazon Location Service (used for geocoding patient addresses) is not included. Patient addresses are PHI. If Location Service calls go over the public internet (even over TLS), this is a data egress concern that some healthcare compliance teams will flag.

**Suggested fix:** Add `geo` (Amazon Location Service) to the list of VPC endpoints. Amazon Location Service supports VPC endpoints via AWS PrivateLink. This keeps address geocoding traffic within the AWS network.

#### Issue N2: No Mention of Cross-AZ Data Transfer for Batch Processing (LOW)

**Location:** Architecture generally

**The problem:** The architecture uses S3 (regional), Glue (runs across AZs), SageMaker Processing (may run in a different AZ than the endpoint), and DynamoDB (regional). For a batch job processing 100K patients, cross-AZ data transfer costs can accumulate. This is a cost concern rather than a security concern, but worth noting for the cost estimate.

**Suggested fix:** This is minor. A one-sentence note in the cost estimate section that cross-AZ transfer costs apply for batch processing jobs and should be factored into the per-patient cost for large populations would be sufficient.

---

### Voice Reviewer

#### What's Done Well

The voice is strong and consistent throughout. The opening scenario (62-year-old woman with uncontrolled diabetes) is compelling and humanizes the problem without being manipulative. The "zip code predicts life expectancy better than genetic code" line is memorable and well-placed. The technology section teaches without condescending. Parenthetical asides are used effectively ("ok, this is a gross oversimplification" energy without literally using that phrase). The "Honest Take" section is genuinely insightful and self-deprecating in the right way. The progression from problem to technology to implementation maintains momentum.

#### Issue V1: One Em Dash Detected (LOW)

**Location:** The Problem section, paragraph 3: "Here's why. SDOH data lives in three places, and none of them talk to each other well:"

**The problem:** No em dash found here. Let me re-scan... After thorough review, I find zero em dashes in this recipe. The recipe correctly uses colons, semicolons, periods, and parentheses throughout.

**Status:** No issue. Recipe is clean.

#### Issue V2: Vendor Balance (LOW)

**Location:** Overall recipe structure

**The problem:** The vendor-agnostic portion (Problem + Technology + General Architecture) is approximately 55% of the recipe. The AWS-specific portion (Why These Services through Expected Results) is approximately 45%. This is slightly over the 70/30 target. The Technology section is thorough and vendor-agnostic, but the pseudocode in the AWS section is quite detailed and lengthy, pushing the AWS portion above 30%.

**Suggested fix:** This is borderline. The pseudocode is genuinely educational and not just AWS boilerplate. The vendor-agnostic Technology section is strong enough that a reader on another cloud would still learn substantially. Consider this a soft flag rather than a hard requirement. If anything, the General Architecture Pattern section could be slightly expanded to rebalance.

---

## Stage 2: Expert Discussion

**Overlap: Security (S1) and Networking (N1) on Location Service.** Both experts flagged the geocoding of patient addresses. Security flagged the PHI exposure surface; Networking flagged the missing VPC endpoint. These are complementary findings that should be addressed together. Resolution: combine into a single recommendation that addresses both the VPC endpoint and the address truncation strategy.

**Overlap: Security (S4) and Architecture (A1) on observability gaps.** Security flagged missing application-level audit logging; Architecture flagged missing error handling/DLQ. Both point to the same underlying gap: the recipe describes the happy path but not the operational reality of running this in production. Resolution: both are valid and should be addressed independently (audit logging is a compliance control; DLQ is a reliability control).

**Priority resolution:** Architecture's A1 (DLQ/error handling) is HIGH because silent failures in NLP extraction directly corrupt the clustering results in a way that's indistinguishable from legitimate data absence. Security's S1 (address geocoding) is HIGH because patient addresses are among the most sensitive PHI elements and the recipe provides no mitigation guidance.

---

## Stage 3: Synthesized Feedback

**Verdict: PASS**

The recipe is well-written, clinically grounded, architecturally sound, and appropriately honest about limitations. The equity audit integration is a standout feature. No critical findings. Two high-severity findings are addressable with brief additions (2-3 sentences each) without restructuring the recipe.

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Lambda orchestration / Architecture diagram | No error handling or DLQ pattern for failed NLP extractions. Silent failures create ambiguous gaps in feature matrix indistinguishable from legitimate absence of SDOH mentions. | Add 2-3 sentences: Lambda writes failed note IDs to SQS DLQ; feature assembly distinguishes "no extractions" from "extraction not attempted"; CloudWatch alarm on DLQ depth. |
| 2 | HIGH | Security + Networking | Step 2 pseudocode, geocoding call | Patient addresses (PHI) sent to Location Service without guidance on precision reduction, caching, VPC endpoint, or audit logging. | Add guidance: geocode at zip+4 level when census-tract precision suffices; use Location Service VPC endpoint; cache results; include in audit logging. |
| 3 | MEDIUM | Security | Prerequisites table, IAM Permissions | Permissions are action-level but not resource-scoped. Builders may grant overly broad access. | Add one sentence: "Scope all permissions to specific resource ARNs in production" with one example. |
| 4 | MEDIUM | Security | Step 5 pseudocode, feature_snapshot field | Feature snapshot in DynamoDB contains derived PHI with no retention/access guidance. | Note that feature_snapshot is PHI; recommend storing S3 URI reference rather than full snapshot in DynamoDB. |
| 5 | MEDIUM | Security | Architecture generally | No application-level audit logging for phenotype queries by downstream care management systems. | Add requirement for application-level audit logging at the care management integration point. |
| 6 | MEDIUM | Architecture | Between Stage 3 and Stage 5 | Clustering re-run cadence not specified. Unclear how often full re-clustering occurs vs. incremental assignment. | Add recommendation: weekly incremental assignment, monthly full re-clustering with equity audit. |
| 7 | MEDIUM | Networking | Prerequisites table, VPC row | Amazon Location Service VPC endpoint not listed despite handling patient addresses (PHI). | Add `geo` to the VPC endpoints list. |
| 8 | LOW | Architecture | Expected Results / Where it struggles | No cluster drift detection discussed. Cluster structure may shift over time without detection. | Brief mention in Variations or Where it struggles: monitor silhouette scores across runs, trigger re-validation on significant drift. |
| 9 | LOW | Networking | Cost estimate | Cross-AZ data transfer costs not mentioned for batch processing of large populations. | One sentence in cost estimate noting cross-AZ transfer applies for batch jobs. |
| 10 | LOW | Voice | Overall structure | Vendor balance is approximately 55/45 rather than 70/30. AWS pseudocode section is detailed. | Soft flag. Consider slightly expanding General Architecture Pattern section to rebalance. Not blocking. |

---

## Summary

Strong recipe with excellent clinical grounding, honest limitations discussion, and integrated equity considerations. The two HIGH findings (DLQ for silent extraction failures, and geocoding PHI exposure) are both addressable with brief additions. The recipe correctly identifies the hardest parts of SDOH phenotyping (sparsity, missingness semantics, temporal instability, bias risk) and provides actionable architecture for each. Recommended for publication after addressing HIGH findings.
