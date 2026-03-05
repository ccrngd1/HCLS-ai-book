# Expert Review: Recipe 1.10 -- Historical Chart Migration

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking)
**Recipe:** Chapter 01.10 -- Historical Chart Migration (Capstone)
**Date:** 2026-03-05
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 1.10 is the most ambitious recipe in Chapter 1, and it mostly earns that status. The two-tier orchestration model (AWS Batch outer loop, Step Functions inner loop) is architecturally sound. The FHIR provenance philosophy -- `unconfirmed` verification status, migration quality scores embedded in extensions, DocumentReference as a fallback for every document -- reflects genuine clinical data stewardship. The honest take at the end, where the author owns a 73% end-to-end accuracy ceiling and flags A2I cost dominance, is exactly what readers need.

That said, this recipe has three issues severe enough to create real harm in production:

First, the AWS-managed A2I workforce is used for human review of handwritten clinical pages. This workforce is Amazon Mechanical Turk. MTurk workers are members of the general public and are not covered by a BAA. Sending PHI to MTurk is a HIPAA violation. At scale (82,400 pages sent to review in the sample pilot output), this is not a minor oversight; it is a material breach waiting to happen.

Second, the `Condition.clinicalStatus` is set to the code `"unknown"`, which does not exist in the FHIR R4 `condition-clinical` ValueSet. HealthLake will reject these resources on import. For a pilot that produces 284,100 Condition resources, this is a silent, systematic failure that will not surface until the first import job runs.

Third, the Textract cost estimate for the 10,000-chart pilot is off by a factor of ten. At the recipe's own stated pricing of $0.065 per page, 1,482,000 pages costs approximately $96,300 -- not $9,633. The total cost per chart is therefore closer to $17 (low handwriting) to $25+ (high handwriting) rather than the stated $8.44. For a program budgeted at millions of charts, this miscalculation is material.

Every finding below includes a concrete fix. The recipe needs targeted corrections in these three areas before it should be recommended to implementation teams.

---

## Security Review

### 🔴 SEC-1: AWS-Managed A2I Workforce (Mechanical Turk) Is Not HIPAA Eligible

**Finding:** The cost estimate and architecture reference the AWS-managed A2I workforce at "$0.83/reviewed page (using AWS-managed workforce pricing)." The AWS-managed workforce for A2I is Amazon Mechanical Turk. MTurk workers are unvetted members of the public. MTurk is not a HIPAA-eligible service and is not coverable under a BAA. Sending scanned clinical chart pages -- complete longitudinal PHI including diagnoses, medications, and procedure histories -- to MTurk workers is a HIPAA violation regardless of how the workflow is technically configured.

At the scale of this recipe (82,400 pages sent to A2I review in a 10,000-chart pilot), this is not an edge case. It is the primary human review path.

**Fix:** Replace every reference to the AWS-managed workforce with either a private workforce (your organization's employees or contractors, credentialed and trained) or a vendor-managed workforce operating under a BAA and HIPAA-compliant data handling agreement. The cost implication is significant: private workforce reviewers typically charge $2 to $6 per page depending on complexity, not $0.83. Revise the cost estimate accordingly and add a callout box that states explicitly: "The AWS-managed workforce (Mechanical Turk) must never be used for PHI review. Use a private A2I workforce. See [Amazon A2I: Private Workforce documentation]." The cost per chart with private workforce review at 20% A2I rate rises to approximately $30 to $60, which changes the program economics materially and readers need to know.

---

### 🔴 SEC-2: PHI Transmitted to Third-Party Reviewers Without Adequate Safeguards Discussion

**Finding:** Related to SEC-1 but distinct: the A2I human review task includes `image_s3_key` (the page image) and `ocr_text` (the OCR'd text) for every low-confidence handwritten page. These contain full PHI: patient names, dates of birth, diagnoses, medication lists, and clinical narratives from decades of care. The recipe's only safeguard discussion is in the prerequisites under "Encryption," which states that "Text sent to Comprehend Medical and A2I is not retained by AWS beyond the immediate transaction."

This statement is misleading in context. For Comprehend Medical it is accurate. For A2I, the situation is different: the human reviewer sees the full page image and OCR text in the A2I review UI during the task. That UI is served via the reviewer's browser. The task data persists in the A2I system until the review is completed or the task expires. If the reviewer workforce is private, this data is visible to your workforce. The statement "not retained by AWS beyond the immediate transaction" does not describe what actually happens during an open review task.

**Fix:** Add a dedicated callout section titled "PHI in A2I Human Review." It should explain: (a) reviewers see full page images and OCR text; (b) the workforce must be a private workforce under a BAA; (c) A2I task data persists until the task is completed or expires (configure short expiry, 24 to 48 hours); (d) reviewer access logs must be retained for HIPAA audit trail purposes; (e) review tasks should include only the minimum necessary PHI -- redact patient name and date of birth from the OCR text field before submitting the task if the review objective is only handwriting legibility confirmation. The `ocr_text` field in the A2I input does not need to include the full page text; it can be truncated to the context needed for the review decision.

---

### 🟠 SEC-3: PHI in SNS Notification Payloads and Textract Job Tags

**Finding:** The Textract `StartDocumentAnalysis` call uses `JobTag=chart_id`. The Textract completion SNS notification includes this job tag in the message payload. `chart_id` is a linkable identifier: anyone who can read the DynamoDB tracking table can resolve `chart_id` to `member_id` and therefore to a real patient. The SNS topic policy and encryption are not addressed in the recipe. If the SNS topic does not have server-side encryption enabled, PHI-linkable identifiers are transmitted in plaintext.

**Fix:** Enable SNS server-side encryption (SSE) using KMS on the `textract-chart-jobs` topic. Add this to the prerequisites table: "SNS topic encryption: SSE-KMS with the same CMK used for S3 and DynamoDB." Additionally, consider whether `chart_id` needs to be the raw identifier or whether a non-linkable job correlation ID (a random UUID, stored alongside `chart_id` in DynamoDB) could be used as the `JobTag` instead, reserving the actual `chart_id` for internal use only.

---

### 🟠 SEC-4: S3 Glacier Transition Relies on a Single Lambda Call With No Fallback

**Finding:** The source chart PDF transitions to Glacier only when `mark_chart_archived` is called and sets the `migration-status=completed` S3 object tag. If this Lambda invocation fails silently (Lambda throttle, transient error, timeout), the object tag is never set, the lifecycle rule never fires, and the chart stays in S3 Standard indefinitely. At millions of charts, even a 0.1% silent failure rate leaves thousands of charts in Standard storage: both a cost leak and an expanded PHI attack surface.

S3 object tags are also unencrypted metadata visible to any IAM principal with `s3:GetObjectTagging`. If `migration-status=completed` is the only defense against premature archival, that tag can be set or removed by any Lambda execution role that has S3 tag write permissions, not just the archival Lambda.

**Fix:** Add a scheduled Lambda (every 24 hours) that queries DynamoDB for charts with `status = completed` and verifies that the corresponding S3 object has the `migration-status=completed` tag. If the tag is missing, set it. This creates a convergent reconciliation loop. Separately, scope S3 tag write permissions on the charts-raw bucket to the specific archival IAM role only, not the general Lambda execution role.

---

### 🟡 SEC-5: DynamoDB Tracking Table Contains PHI Linkage Without Access Boundary Discussion

**Finding:** The `migration-tracking` DynamoDB table contains `chart_id`, `member_id`, `s3_key`, `textract_job_id`, `quality_score`, and `fhir_bundle_key` per chart. `member_id` directly identifies a HIPAA-covered individual. The table is described as encrypted at rest with KMS, which is correct. However, the recipe does not discuss IAM access control for this table. Any Lambda in the pipeline -- manifest generation, segmentation, classification, FHIR mapping -- needs read/write access, but the scope of that access is not constrained. A compromised Lambda execution role with broad DynamoDB access could enumerate all member IDs in the migration.

**Fix:** Use DynamoDB fine-grained access control (FGAC) with IAM condition keys to restrict each Lambda to operations on specific attributes. Manifest generation needs write access on `chart_id`, `s3_key`, and `status`. The FHIR mapper needs read access on `blocks_key` but should not need access to `member_id`. Define separate IAM policies per Lambda rather than a single shared role. Add a note: "The migration-tracking table is a PHI index. Access must follow minimum necessary principles. Audit CloudTrail for DynamoDB data-plane events on this table."

---

### 🟡 SEC-6: KMS Key Rotation and Cross-Service Key Sharing Not Addressed

**Finding:** The prerequisites specify "SSE-KMS with customer-managed key on all buckets" but do not address key rotation schedule or whether a single CMK serves all services. Using one CMK for S3, DynamoDB, Step Functions, and HealthLake creates a blast radius: a key compromise or accidental key deletion affects every PHI store simultaneously. Key rotation is mentioned nowhere.

**Fix:** Use separate CMKs per data tier (raw chart storage, processed chart storage, FHIR output, DynamoDB). Enable automatic key rotation (annually, which is the AWS default for CMKs with rotation enabled). Add to prerequisites: "Enable key rotation on all CMKs. Use separate keys for raw chart storage, extraction artifacts, and FHIR output. Document key ARNs and rotation schedules in your HIPAA risk assessment." Also add that key deletion must trigger an incident response process, not just a support ticket.

---

## Architecture Review

### 🔴 ARC-1: Cost Estimate Is Off by 10x for Textract

**Finding:** The pilot cost summary shows Textract FORMS + TABLES at $9,633 for 1,482,000 pages. The recipe's own stated pricing is $0.065 per page ($0.05 FORMS + $0.015 TABLES). The correct calculation is:

```
1,482,000 pages * $0.065/page = $96,330
```

Not $9,633. The displayed figure is exactly one-tenth of the correct number, suggesting a decimal point error. This makes the stated cost-per-chart of $8.44 dramatically wrong. Recalculating with the correct Textract figure:

```
Textract (corrected):         $96,330
Comprehend Medical:            $3,240
A2I (using private workforce, ~$3/page): ~$247,200
HealthLake:                      $187
Compute:                         $820
Step Functions:                  $210
S3:                              $680
Total (corrected):          ~$348,667
Cost per chart (corrected):    ~$35.44
```

Even using the stated $0.83/page A2I pricing (which is the ineligible MTurk rate per SEC-1), the Textract error alone takes cost-per-chart from $8.44 to $17. For an organization planning to migrate 10 million charts, the budget impact of this error is $90+ million.

**Fix:** Correct the arithmetic to $96,330 for Textract in the pilot summary. Revise the cost-per-chart range accordingly. Add a note that Textract also charges for the LAYOUT feature when combined with FORMS/TABLES, check current pricing at time of implementation, and that LAYOUT-only pricing differs from FORMS+TABLES pricing -- confirm the feature combination cost at the AWS pricing calculator before budgeting.

---

### 🔴 ARC-2: Condition.clinicalStatus "unknown" Is Not a Valid FHIR R4 Code

**Finding:** The FHIR mapping pseudocode sets `Condition.clinicalStatus.coding[0].code = "unknown"`. The FHIR R4 `condition-clinical` ValueSet (binding: required) contains exactly six codes: `active`, `recurrence`, `relapse`, `inactive`, `remission`, `resolved`. The code `"unknown"` is not in this ValueSet. HealthLake performs FHIR R4 validation on import; resources with invalid required-binding values are rejected.

The pilot produces 284,100 Condition resources. If every Condition uses `clinicalStatus.code = "unknown"`, all 284,100 will fail HealthLake import validation. The import job will not fail cleanly on these -- HealthLake import jobs write failures to the output S3 location, but the chart's DynamoDB status is updated to `import_submitted` regardless. A reader following this recipe will have a DynamoDB table showing 284,100 successful Condition imports that actually failed.

The comment in the pseudocode explains the intent correctly ("We can't reliably determine active vs. resolved from historical notes") but implements it with an invalid code.

**Fix:** Replace `"unknown"` with `"active"` as a conservative default for forward-facing Condition resources (historical diagnoses that may still be relevant) and add `meta.tag` with a custom code indicating the record was migrated from paper. Alternatively, use the FHIR `data-absent-reason` extension on `clinicalStatus` to indicate the status is not determinable from the source document. The correct approach per the HL7 FHIR R4 spec for "status cannot be determined from source" is to use `inactive` with a note, or to omit `clinicalStatus` and let it default (though HealthLake may require it). Add a callout: "HealthLake requires valid ValueSet codes for required bindings. Validate all generated FHIR resources with a FHIR validator (e.g., the HL7 FHIR validator CLI) before submitting the first import job."

---

### 🟠 ARC-3: AWS Batch Array Job Size Limit Not Addressed

**Finding:** The `submit_batch_migration_job` pseudocode submits a single array job with `size: job_count`. AWS Batch array jobs have a maximum size of 10,000 child jobs per array. For a migration of 2 million charts, the manifest would need to be split into at least 200 separate array job submissions. The recipe presents the array job approach without mentioning this limit, which will cause `InvalidParameterException` errors at any real scale above 10,000 charts per batch.

**Fix:** Add logic to `submit_batch_migration_job` that chunks the manifest into sub-manifests of at most 9,500 charts each (leaving headroom) and submits one array job per chunk. Track all array job IDs in DynamoDB under a migration run record. Alternatively, use an SQS queue as the work queue: each chart becomes one SQS message, and Batch workers poll the queue directly rather than using array indexing. The SQS approach has no job-count ceiling and naturally handles retry semantics through message visibility timeouts.

---

### 🟠 ARC-4: No Recovery Mechanism for Charts Stuck in "extracting" State

**Finding:** The recipe relies on an SNS notification from Textract to trigger the `retrieve_textract_results` Lambda and advance chart state. If that SNS notification is lost (SNS delivery failure, Lambda throttle that exhausts retries, DLQ overflow), the chart remains in `status = "extracting"` in DynamoDB indefinitely. There is no watchdog that detects and recovers these charts.

Textract async jobs complete within 5 to 30 minutes for most charts. A chart that is still in `status = "extracting"` after 2 hours is almost certainly stuck. At scale, even a 0.01% stuck rate across 2 million charts is 200 orphaned charts that silently never complete.

**Fix:** Add a scheduled Lambda that runs every 2 hours and queries DynamoDB for charts with `status = "extracting"` AND `updated_at < now() - 2 hours`. For each: call `GetDocumentAnalysis` directly with the stored `textract_job_id` to check current status. If the Textract job is `SUCCEEDED`, retrieve results and continue the pipeline. If the Textract job is `FAILED`, set DynamoDB status to `failed` with the error reason and emit a CloudWatch metric. This requires a DynamoDB GSI on `(status, updated_at)` to support efficient time-range queries per status.

---

### 🟠 ARC-5: Comprehend Medical Real-Time API Is Inappropriate at Bulk Scale

**Finding:** The recipe calls `comprehend_medical.detect_entities_v2`, `comprehend_medical.infer_icd10_cm`, and `comprehend_medical.infer_rxnorm` as real-time (synchronous) API calls inside Lambda functions. For a single chart with 20 clinical pages, each chunked into 3 Comprehend Medical calls, that is 180+ synchronous API calls per chart. At 1,000 concurrent charts and 180 API calls each, you have 180,000 Comprehend Medical API calls per minute.

The default Comprehend Medical `DetectEntitiesV2` throughput quota is 100 transactions per second (TPS) per region. At that limit, 180,000 calls takes 30 minutes just for entity detection, not counting ICD-10 and RxNorm inference. Throughput increases require explicit quota requests (same as Textract), but the recipe only calls out Textract quota increases as a prerequisite. Comprehend Medical quota saturation causes throttling errors that manifest as Lambda retries, Lambda timeouts, and Step Functions task failures -- all hard to diagnose.

The Comprehend Medical Batch API (`StartEntitiesDetectionV2Job`, `StartICD10CMInferenceJob`, `StartRxNormInferenceJob`) is designed for exactly this workload: submit text files to S3 and receive results asynchronously. It has a separate (higher) throughput ceiling and does not compete with real-time API quotas.

**Fix:** Refactor `process_clinical_document` to: (1) write all text chunks for the chart to an S3 prefix (`cm-input/{chart_id}/`), (2) submit Comprehend Medical batch inference jobs for that prefix, (3) await completion via SNS or polling, (4) aggregate results from S3. Add to prerequisites: "File Comprehend Medical batch API quota increases alongside Textract quota increases. Real-time CM API is not appropriate for bulk migration workloads."

---

### 🟠 ARC-6: DiagnosticReport Resource Missing From FHIR Mapping

**Finding:** The recipe's FHIR resource type inventory lists `DiagnosticReport` as the resource for lab and imaging reports. The FHIR R4 specification requires that `Observation` resources for lab values be referenced from a `DiagnosticReport` that groups them. The FHIR mapping pseudocode creates `Observation` resources for lab values but creates no `DiagnosticReport` parent.

This produces an invalid FHIR structure for lab results: standalone Observations without a DiagnosticReport context. Downstream consumers that query for complete blood count results expect a `DiagnosticReport` with component `Observation` references. The sample pilot output shows 521,800 Observations but no DiagnosticReport count, confirming the omission.

**Fix:** Add a `DiagnosticReport` resource creation step inside the `doc_type == "lab_result"` branch of the FHIR mapper. The DiagnosticReport groups all Observations from the same lab result document and provides the ordering provider context, specimen collection date, and panel name. Reference each Observation from the DiagnosticReport's `result` array. The corrected resource hierarchy is: one DiagnosticReport per lab document, N Observations per DiagnosticReport. Update the sample pilot output's `fhir_output` section to include a `diagnostic_reports` count.

---

### 🟠 ARC-7: `loinc_code_for(doc_type)` Is a Critical Stub With No Implementation Guidance

**Finding:** The DocumentReference mapping calls `loinc_code_for(doc_type)` to populate the `type.coding` field. This function is never defined in the recipe. LOINC document type codes are not guessable -- they are specific registered codes that downstream FHIR consumers, CDS Hooks implementations, and CMS Interoperability API queries use to filter document types. Using wrong LOINC codes causes documents to be invisible to systems querying for specific types (e.g., a care management system looking for discharge summaries using LOINC 18842-5 will miss documents coded as 34117-2).

**Fix:** Provide the LOINC code mapping table inline in the recipe. At minimum:

| doc_type | LOINC Code | Display |
|---|---|---|
| progress_note | 11506-3 | Progress note |
| history_and_physical | 34117-2 | History and physical note |
| discharge_summary | 18842-5 | Discharge summary |
| lab_result | 26436-6 | Laboratory studies |
| radiology_report | 18748-4 | Diagnostic imaging study |
| operative_report | 11504-8 | Surgical operation note |
| consultation_report | 11488-4 | Consultation note |
| medication_list | 56445-0 | Medication summary |
| immunization_record | 41291-6 | Immunization |
| problem_list | 11450-4 | Problem list |

Replace the stub with an explicit lookup table and add a note that LOINC codes should be verified against the LOINC database (loinc.org) at implementation time, as new codes are issued periodically.

---

### 🟡 ARC-8: Quality Score Composite Has Correlated Dimensions

**Finding:** The quality score composite is a weighted average of four dimensions: OCR confidence (0.30), classification confidence (0.25), extraction completeness (0.25), and handwriting review rate (0.20). The OCR confidence and handwriting review rate dimensions are strongly correlated: low-confidence pages are exactly those sent to A2I review. When OCR confidence is low, handwriting review rate is high, and both dimensions are penalized simultaneously. The composite score applies a squared penalty to poor handwriting quality while the other two dimensions (classification confidence and extraction completeness) may score well on the same document.

Additionally, the classification confidence normalization divides the keyword match score by 8.0, treating 8 matches as the theoretical maximum. A document type with 14 keyword matches in the signature map (e.g., `progress_note`) can score at most 1.0 regardless of how many keywords matched. A document with 4 matches scores 0.5. This is not a normalized confidence score; it is a count-dependent threshold that varies by document type richness.

**Fix:** Decorrelate OCR confidence and handwriting review rate. If a page was sent to A2I review and the reviewer confirmed the extraction, the OCR confidence score for that page should not remain the raw Textract word confidence; it should be upgraded to a post-review confidence score (e.g., 0.90 for reviewer-confirmed text). Track `review_confirmed_pages` separately from `review_sent_pages`. For classification confidence normalization: use per-document-type calibration rather than a global divisor of 8.0. Track the empirical distribution of keyword match counts across your actual chart population during the pilot and set per-type normalization constants.

---

### 🟡 ARC-9: HealthLake Import Batch Failure Handling Is Incomplete

**Finding:** The `submit_healthlake_import_batch` function marks charts as `import_submitted` and records the `import_job_id` in DynamoDB. HealthLake import jobs can fail at the job level (the entire batch fails) or at the resource level (individual resources fail validation, others succeed). The recipe does not describe what happens after either failure type.

If a HealthLake import job fails due to one invalid resource (e.g., all 284,100 Conditions with invalid `clinicalStatus` per ARC-2), the entire job may fail. The charts are stuck at `import_submitted` with no transition to `completed` or `failed`. There is no reconciliation loop that checks import job status and updates chart records accordingly.

**Fix:** Add a scheduled Lambda that polls in-progress HealthLake import jobs. For completed jobs: parse the output manifest from S3 (`import-results/`) to identify which resources succeeded and which failed. Update chart DynamoDB records to `completed` for charts whose resources all succeeded. For charts with failed resources, log the specific validation errors and set status to `import_failed` with details. For job-level failures: resubmit the batch, but first validate a sample of FHIR resources through the HL7 FHIR validator before resubmitting to avoid re-importing known-bad resources.

---

### 🟡 ARC-10: Blank Page Detection Threshold Is Hardcoded and Brittle

**Finding:** `is_blank_page` uses a hardcoded `white_threshold=0.98` (98% of pixels must be near-white). This threshold is not tunable per scanning vendor. Different scanning vendors have different noise profiles: a scanner with backlight bleed produces a light-gray noise floor across "blank" pages, reducing the white pixel fraction to 0.92 to 0.95 on truly blank pages. The 0.98 threshold would fail to skip these, sending them through Textract. Conversely, a page with a single-line header and otherwise blank content might have 96% white pixels -- it is not blank, but would pass the threshold and be skipped.

**Fix:** Make `white_threshold` a configurable parameter passed from the job definition or from a SSM Parameter Store value per scanning-vendor profile. Set default to 0.95 (more permissive) and add a second check: if the page passes the white threshold but has more than 5 WORD blocks in the Textract output, un-flag it as blank (this requires a lightweight Textract DETECT_DOCUMENT_TEXT call, or use a local OCR pass before the full Textract job). Document the tuning process in the recipe.

---

### 🔵 ARC-11: DynamoDB Status Queries Require a GSI That Is Not Defined

**Finding:** Multiple functions query DynamoDB by status: `submit_healthlake_import_batch` queries for `status = 'fhir_ready'`; the proposed watchdog (ARC-4) queries for `status = 'extracting'`. DynamoDB does not support efficient `Scan` with filter expressions at scale; without a GSI on `status`, these queries require full table scans of the migration-tracking table. At 2 million charts, a full table scan consumes significant read capacity and is cost-inefficient.

**Fix:** Add a GSI with partition key `status` and sort key `updated_at` to the migration-tracking table. This enables efficient queries like "all charts in status 'fhir_ready' ordered by update time." Add the GSI definition to the prerequisites. Note: because DynamoDB GSIs on high-cardinality attributes like `status` can create hot partitions when most charts are in the same state, consider using a composite status key: `status#{shard_id}` where `shard_id` is a random 0-9 integer. This distributes the read load while still enabling parallel queries across all shards.

---

## Networking Review

### 🟠 NET-1: VPC Endpoints for A2I/SageMaker Not Listed

**Finding:** The prerequisites VPC section lists VPC endpoints for S3, Textract, Comprehend Medical, DynamoDB, SNS, SQS, Step Functions, HealthLake, CloudWatch Logs, and KMS. It does not list VPC endpoints for Amazon A2I. A2I uses the SageMaker service plane for human loop management; the relevant endpoints are `sagemaker.api` and `sagemaker.runtime`. Without these endpoints, A2I calls from Lambda inside the VPC route over the public internet, violating the recipe's stated requirement that "chart data should not traverse the public internet."

The A2I human review portal (used by reviewers to see page images and submit decisions) also retrieves content from S3. If reviewers are accessing the portal from within a private network, ensure the S3 VPC endpoint is accessible from their network path or that the review task uses pre-signed URLs with short expiry.

**Fix:** Add `com.amazonaws.{region}.sagemaker.api` and `com.amazonaws.{region}.sagemaker.runtime` to the VPC endpoints list. Note that the A2I review portal itself is a web application that reviewers access from their browsers -- it is not inside your VPC. The Lambda functions submitting human loops are inside the VPC. The pre-signed URLs generated for reviewer page access should have a short expiry (4 hours maximum, matching a review shift length) and should not grant write permissions on the S3 bucket.

---

### 🟠 NET-2: HealthLake VPC Endpoint Availability Is Region-Dependent

**Finding:** The recipe targets HealthLake as the FHIR store and the VPC prerequisites imply a VPC endpoint for HealthLake. However, HealthLake VPC endpoints (Interface endpoints via PrivateLink) are not available in all AWS regions where HealthLake is offered. At time of writing, HealthLake VPC endpoints are available only in `us-east-1`, `us-west-2`, and `eu-west-1`. Organizations deploying in other HealthLake-supported regions (e.g., `ap-southeast-2` for Australian healthcare deployments) cannot route HealthLake API calls through a VPC endpoint and must use NAT Gateway egress.

**Fix:** Add a callout to the VPC prerequisites section: "Verify that a VPC endpoint for Amazon HealthLake is available in your target region before finalizing your VPC architecture. If no VPC endpoint is available, HealthLake API calls require a NAT Gateway. Ensure the NAT Gateway is in a private subnet with security group rules restricting outbound access to HealthLake endpoints only. See the AWS PrivateLink documentation for current HealthLake endpoint availability." Link to the PrivateLink services list.

---

### 🟠 NET-3: Lambda Concurrency Spike From Textract SNS Completion Burst

**Finding:** With 500+ concurrent Textract jobs (the prerequisite mentions 100 to 500+ concurrent jobs after quota increase), a scenario commonly occurs during large batch windows: many Textract jobs complete within the same few minutes as they were submitted in the same Batch wave. This fires 500+ SNS notifications simultaneously, invoking 500+ copies of the `textract-complete` Lambda concurrently. Each of those Lambdas calls `GetDocumentAnalysis` (paginated) to retrieve block data, writes to S3 (blocks.json), updates DynamoDB, and starts a Step Functions execution.

The default Lambda concurrent execution limit is 1,000 per account per region (shared across all functions). If other Lambdas are running in the account, the `textract-complete` function may be throttled. Throttled SNS invocations are retried by SNS with exponential backoff, but SNS has a maximum retry window of 23 days for Lambda failures. In practice, sustained throttling causes SNS to drop messages after exhausting retries. Dropped messages mean permanently orphaned charts.

**Fix:** Set reserved concurrency for the `textract-complete` Lambda to 300 (sizing appropriately for your quota). Configure an SQS queue as an intermediary between SNS and Lambda (SNS to SQS to Lambda) rather than direct SNS to Lambda invocation. SQS absorbs the burst and delivers messages at the Lambda's maximum concurrency rate. With SQS, throttled messages are retained in the queue and retried automatically without the 23-day SNS retry window constraint. Add this to the architecture diagram and the SNS/SQS ingredients table.

---

### 🟡 NET-4: Comprehend Medical API Latency Amplification Inside Lambda

**Finding:** At the real-time API call pattern described in the recipe, `process_clinical_document` makes multiple sequential Comprehend Medical API calls per text chunk (detect_entities_v2, then infer_icd10_cm, then infer_rxnorm on applicable documents). Each API call to Comprehend Medical from a Lambda inside a VPC (using the VPC Interface endpoint) adds 20 to 50ms of network overhead. For a large clinical document (18,000 characters per chunk, 10 chunks, 3 CM calls each), that is 30 sequential API calls with 30+ seconds of cumulative network latency -- before processing time.

Lambda's maximum execution timeout is 15 minutes. A large clinical document with many chunks can approach this limit when CM calls are sequential.

**Fix:** Parallelize Comprehend Medical calls within each chunk. For a given text chunk, call `detect_entities_v2`, `infer_icd10_cm`, and `infer_rxnorm` concurrently using async I/O (Python asyncio or concurrent.futures). This reduces the per-chunk latency from (3 * CM_latency) to (1 * CM_latency). Also, note the batch API alternative from ARC-5 as the preferred approach at scale.

---

### 🟡 NET-5: AWS Batch Spot Fleet Subnet Distribution Not Discussed

**Finding:** AWS Batch with Spot instances requires subnet configuration in the Compute Environment. Spot capacity is allocated per Availability Zone (AZ). A compute environment with a single subnet in one AZ has no fallback when Spot capacity in that AZ is exhausted or the instance type is interrupted. At the scale of this recipe (hundreds of Batch workers), a Spot interruption event during a large batch window can simultaneously terminate a significant fraction of in-progress chart jobs. While Batch retries failed jobs, the retry queue can spike dramatically and delay migration timelines.

**Fix:** Configure the Batch compute environment with subnets in at least 3 Availability Zones. Use a diverse instance type pool (m5.xlarge, m5.2xlarge, m4.xlarge, r5.xlarge) rather than a single type -- Batch selects the cheapest available instance type at submission time. Consider mixing On-Demand instances (set as a fallback in the compute environment's allocation strategy using `BEST_FIT_PROGRESSIVE`) to ensure a floor of capacity during Spot interruption events. Add these configuration details to the AWS Batch prerequisites section.

---

### 🔵 NET-6: Textract Block Data Size and Lambda Memory Constraints

**Finding:** The recipe notes that "large charts can have 50,000+ blocks." A Textract block JSON for 50,000 blocks is approximately 15 to 25 MB of JSON data. Lambda functions loading this full block set from S3 into memory for document segmentation and classification need adequate memory allocation. The recipe does not specify Lambda memory configuration. A Lambda configured with 512 MB (a common default) may fail on large charts due to out-of-memory errors when loading and processing large block sets.

The `segment_chart` and `classify_and_route_segments` functions both call `load_json_from_s3` and operate on the full block set in memory simultaneously.

**Fix:** Recommend Lambda memory settings based on chart size tier: 1 GB for charts under 100 pages, 2 GB for charts up to 300 pages, 3 GB for charts above 300 pages. Implement streaming JSON parsing (ijson library in Python) for block data rather than loading the full JSON into memory. Alternatively, pre-segment the block data during the `retrieve_textract_results` step: write one JSON file per page (`blocks-page-{N}.json`) rather than a single monolithic `blocks.json`. This reduces per-Lambda memory requirements dramatically and allows parallel page processing.

---

## Specific Praise

### ✅ Two-Tier Orchestration Model (Batch + Step Functions)

The design choice to use AWS Batch for the outer fleet loop and Step Functions Standard Workflows for the per-chart pipeline is exactly right. The argument for Standard over Express Workflows is well-made: per-chart execution history is operationally necessary when debugging extraction failures in a program running for months. The cost trade-off is correctly framed. This pattern should be cited as the reference design for any industrial-scale document processing program on AWS.

### ✅ FHIR Provenance Philosophy

Using `verificationStatus: unconfirmed` and `clinicalStatus: unknown` (intent correct, code incorrect per ARC-2) throughout the Condition mapping reflects genuine clinical data stewardship. The note field provenance trail (source pages, OCR confidence, quality tier) is exactly the right design for migrated records. The explicit warning in "The Honest Take" against promoting migrated records to `confirmed` status deserves to be in a callout box, not just prose.

### ✅ Idempotency Design

The idempotency guard pattern -- check DynamoDB for `status = completed` before starting, use Batch retry semantics, check before re-registering -- is correct and complete. The distinction between at-least-once Batch delivery and the need for skip logic is clearly explained. This is a frequent omission in batch processing recipes and its inclusion here is commendable.

### ✅ A2I Cost Dominance Callout

The explicit statement in "The Honest Take" that A2I review dominates cost at high handwriting rates ($68K of $83K total in the pilot) and the recommendation to tune thresholds with a pilot sample before full-scale migration is practical and accurate. Most recipes bury this kind of financial honesty in the appendix or omit it entirely. Putting it in the primary narrative is the right call.

### ✅ Scanning Standards Prerequisites

The specific guidance on minimum DPI (300 DPI for handwriting), color vs. grayscale, PDF/A format, and the price range for scanning vendor services ($0.08 to $0.25 per page) gives readers concrete numbers to use in vendor negotiations. This is information that implementers need and rarely find in architecture recipes.

---

## Summary of Findings

| ID | Severity | Area | Title |
|----|----------|------|-------|
| SEC-1 | 🔴 Critical | Security | AWS-managed A2I workforce (MTurk) is not HIPAA eligible |
| ARC-1 | 🔴 Critical | Architecture | Cost estimate for Textract is off by 10x |
| ARC-2 | 🔴 Critical | Architecture | Condition.clinicalStatus "unknown" is not a valid FHIR R4 code |
| SEC-2 | 🟠 High | Security | PHI in A2I review tasks lacks adequate safeguard discussion |
| SEC-3 | 🟠 High | Security | PHI-linkable identifiers in unencrypted SNS topic |
| SEC-4 | 🟠 High | Security | Glacier transition has no convergence fallback |
| ARC-3 | 🟠 High | Architecture | Batch array job size limit (10,000) not addressed |
| ARC-4 | 🟠 High | Architecture | No recovery for charts stuck in "extracting" state |
| ARC-5 | 🟠 High | Architecture | Comprehend Medical real-time API not appropriate at bulk scale |
| ARC-6 | 🟠 High | Architecture | DiagnosticReport resource missing from FHIR mapping |
| ARC-7 | 🟠 High | Architecture | loinc_code_for() is an undefined stub for a critical mapping |
| NET-1 | 🟠 High | Networking | VPC endpoints for A2I/SageMaker not listed |
| NET-2 | 🟠 High | Networking | HealthLake VPC endpoint availability is region-dependent |
| NET-3 | 🟠 High | Networking | Lambda concurrency spike from Textract SNS completion burst |
| SEC-5 | 🟡 Medium | Security | DynamoDB PHI linkage table lacks access boundary discussion |
| SEC-6 | 🟡 Medium | Security | KMS key rotation and cross-service key sharing not addressed |
| ARC-8 | 🟡 Medium | Architecture | Quality score composite conflates correlated dimensions |
| ARC-9 | 🟡 Medium | Architecture | HealthLake import batch failure handling is incomplete |
| ARC-10 | 🟡 Medium | Architecture | Blank page detection threshold is hardcoded and brittle |
| NET-4 | 🟡 Medium | Networking | CM API latency amplification from sequential calls in Lambda |
| NET-5 | 🟡 Medium | Networking | Batch Spot fleet subnet distribution not discussed |
| ARC-11 | 🔵 Low | Architecture | DynamoDB status queries require a GSI that is not defined |
| NET-6 | 🔵 Low | Networking | Textract block data size and Lambda memory constraints |

---

## Required Fixes Before Publication

The following three issues must be corrected before this recipe is recommended to implementation teams:

1. **SEC-1:** Replace all AWS-managed A2I workforce references with private workforce. Revise the cost estimate to reflect private workforce pricing ($2 to $6 per page). Add an explicit HIPAA callout prohibiting MTurk for PHI review.

2. **ARC-2:** Replace `clinicalStatus.code = "unknown"` with a valid FHIR R4 code (`active` with a migration provenance tag, or `inactive` with a note). Add a FHIR validation step recommendation before first import job submission.

3. **ARC-1:** Correct the Textract cost arithmetic. 1,482,000 pages at $0.065/page is $96,330, not $9,633. Revise the total cost and cost-per-chart accordingly.

---

*Review complete. Recipe 1.10 is architecturally ambitious and largely well-reasoned. Targeted corrections to the three critical findings and the eight high-severity findings will make it production-safe.*
