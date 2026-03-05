# Expert Review: Recipe 1.4 - Prior Authorization Document Processing

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking)
**Date:** 2026-03-05
**Recipe file:** `chapter01.04-prior-auth-document-processing.md`

---

## Overall Assessment

This is the most technically ambitious recipe in Chapter 1 and largely delivers on it. The three-stage pipeline is well motivated, the fan-out concept is clearly explained, the "Why This Isn't Production-Ready" section is honest and comprehensive, and the connections to earlier recipes are clean. The cost narrative and regulatory framing are strong.

However: there is one significant factual error about Express Workflows that would mislead a production builder on debugging behavior, a disconnect between the recipe's fan-out promise and what the pseudocode actually implements, and a cluster of PHI surface area issues unique to multi-page pipelines that need explicit treatment. The networking prerequisites are the most complete in the series so far, with one specificity gap on CloudWatch Logs endpoints.

Priority breakdown: 1 must-fix factual error, 5 significant gaps, 6 improvement recommendations.

---

## Security Expert Review

### What's Done Well

The PHI baseline is solid: BAA coverage, SSE-KMS on S3 and DynamoDB, TLS for all API calls, "never use real PHI in development" warning, CloudTrail for all services. The explicit call-out that Step Functions execution history is encrypted at rest is useful. Routing Textract output through S3 keys rather than inline payloads is correctly motivated by the 256 KB Step Functions limit, but it also has a PHI benefit: the raw OCR blocks (which contain all extracted text including PHI) stay in the encrypted S3 bucket rather than flowing through Step Functions state transitions.

### Issue S1: S3 Intermediate Artifacts Have No Retention Policy (Significant)

**The problem:** The `retrieve_and_handoff` pseudocode writes Textract output to `textract-outputs/{job_id}/blocks.json` in S3. These JSON files contain the complete OCR block output for the entire multi-page submission, including all PHI present in the document. The recipe acknowledges cleanup is needed ("adds an S3 read to every step and requires you to clean up intermediate objects after the pipeline completes") but treats it as an operational footnote rather than a PHI control.

A submission that completes successfully cleans up. A submission that fails midway leaves the full Textract block output sitting in S3 indefinitely. At volume, this accumulates.

**Suggested fix:** Add a lifecycle rule on the `textract-outputs/` prefix: expire objects after 1 day (or the maximum expected pipeline duration plus a buffer). Add explicit cleanup in the assembler as the final step: after writing the structured record to DynamoDB, delete the intermediate `blocks.json` from S3. Add a note in "Why This Isn't Production-Ready" that this cleanup must be idempotent and must handle partial pipeline failures via a separate cleanup Lambda triggered by Step Functions on failure paths.

### Issue S2: PHI Extracted by DetectEntitiesV2 Stored Without Policy Decision (Significant)

**The problem:** The `clinical_entities` map assembled from `DetectEntitiesV2` results includes a `PROTECTED_HEALTH_INFORMATION` category containing Safe Harbor identifiers: patient names, dates, phone numbers, geographic indicators, ages, and other re-identifiable fields extracted from clinical narrative text. The pseudocode in `extract_clinical_page` passes the full entity map to the assembler, and the assembler stores it in DynamoDB under `clinical_entities`. No guidance is given on whether to store, drop, or separately log the PHI category entities.

A builder following this recipe will store a second copy of PHI-category entities in DynamoDB alongside clinical entities, with no explicit policy rationale. The original submission PDF is already in S3 under access controls. This derived PHI store needs its own justification.

**Suggested fix:** Add a note in `extract_clinical_page` and in the assembler's merge logic: the `PROTECTED_HEALTH_INFORMATION` category from `DetectEntitiesV2` should be handled by explicit policy. Options: drop entirely (the member identity is already captured from the cover sheet), store in a separate DynamoDB attribute with tighter IAM conditions, or log to a separate audit trail. Show which path is selected and why.

### Issue S3: Step Functions Execution Role for Lambda Invocation Not Addressed (Significant)

**The problem:** The prerequisites cover the Lambda execution role needing `states:StartExecution`. They do not cover the Step Functions state machine execution role. A Step Functions state machine that invokes Lambda functions directly (via the `arn:aws:states:::lambda:invoke` resource in ASL) requires an IAM execution role with `lambda:InvokeFunction` on each Lambda function ARN. The recipe implies Step Functions orchestrates the Lambda fan-out but never mentions the IAM role the state machine itself uses to call Lambda.

A builder following this recipe exactly will create the Lambda execution role correctly, create the state machine, and then get `States.TaskFailed` on the first Lambda invocation state because the state machine has no permissions to call Lambda.

**Suggested fix:** Add a row to the IAM Permissions prerequisites table for the Step Functions execution role: `lambda:InvokeFunction` scoped to the specific Lambda function ARNs (pa-extract-cover, pa-extract-clinical, pa-extract-labs, pa-extract-imaging, pa-assembler). Note that this is a separate role from the Lambda execution role: Step Functions assumes its execution role when calling downstream services, not the Lambda's own role.

### Issue S4: DynamoDB Encryption Not Specified as CMK (Minor)

**The problem:** The prerequisites state "DynamoDB: encryption at rest enabled." AWS default DynamoDB encryption uses AWS-owned keys. For a store holding structured clinical data including ICD-10 codes, diagnoses, medications, and member demographics, many HIPAA compliance programs require customer-managed keys so that key usage appears in CloudTrail and key revocation is available if needed.

**Suggested fix:** Align the DynamoDB encryption description with the S3 approach: "DynamoDB: encryption at rest with customer-managed KMS key (same CMK as S3, or a dedicated CMK for the DynamoDB table)." The `aws/dynamodb` AWS-managed key is acceptable as a minimum; a dedicated CMK is preferable for audit visibility.

### Issue S5: Sample Output NPI Should Be Explicitly Marked Fictional (Minor)

**The problem:** The sample output in "Expected Results" contains NPI "1982374650." NPIs are 10-digit numbers assigned to real providers by CMS. The recipe does not mark this as a fictional value. If this NPI happens to match a real provider in the National Plan and Provider Enumeration System (NPPES), the example could cause confusion or be mistaken for real data in documentation or training materials.

**Suggested fix:** Add "(fictional)" annotations next to the NPI and member ID in the sample output, or add a note above the JSON block that all identifiers are synthetic and do not correspond to real members or providers.

---

## Architecture Expert Review

### What's Done Well

The three-stage pipeline decomposition is clean and well-reasoned. The stage boundaries as natural checkpoints (raw extraction, classified pages, per-page results) are valuable framing. The deduplication logic in the assembler is a genuine architectural contribution: deduplicating ICD-10 codes by code value keeping highest-confidence instance is the right approach. The weighted confidence discussion (cover sheet fields are more consequential than supplementary clinical notes) is honest and practically useful. The DLQ, idempotency, and per-branch error handling gaps in "Why This Isn't Production-Ready" are all correctly identified.

### Issue A1: Express Workflows Debugging Claim Is Factually Wrong (Must Fix)

**The problem:** The recipe states:

> "A single Lambda function can implement all of this, but it gets unwieldy fast. Step Functions is designed exactly for this kind of workflow: parallel branches, error handling per branch, retry logic on transient failures, and a visual execution graph in the console that makes debugging a failed 15-page submission tractable. The Express Workflows mode is appropriate here."

The visual execution graph with per-state input and output visibility in the Step Functions console is a feature of **Standard Workflows**, not Express Workflows. Express Workflows do not store execution history in the Step Functions console by default. To see per-state execution details for Express Workflows, you must explicitly configure a CloudWatch Logs log group and enable logging at the ALL or ERROR level on the state machine. Without that configuration, a failed Express Workflow leaves no trace in the console at all. The recipe's strongest argument for using Step Functions (debuggability) is only true if you add configuration that is not mentioned anywhere in the recipe.

A builder who deploys Express Workflows expecting console-level visibility, hits a failure in the lab results extractor branch, opens the Step Functions console, and finds no execution history will have a deeply frustrating debugging experience.

**Suggested fix:** Change the Step Functions rationale to: "Express Workflows offer lower cost and higher throughput than Standard Workflows at the tradeoff of at-most-5-minute duration and no built-in execution history in the console. To preserve debugging capability, configure a CloudWatch Logs log group on the state machine with logging level set to ALL (or at minimum ERROR). Standard Workflows provide full per-state input/output history in the console but cost more and have a 1-year maximum duration; for teams that prioritize debugging over throughput, Standard Workflows are a reasonable choice for this pipeline." Add a prerequisites row: "Step Functions CloudWatch Logs log group configured for execution logging."

### Issue A2: Fan-Out Pseudocode Is Sequential, Not Parallel (Significant)

**The problem:** The recipe's conceptual framing throughout the "Fan-Out Extraction Pattern" section emphasizes parallelism as a key advantage: "the extractors can run in parallel... a 12-page submission with pages spread across four types can fan out to four parallel processes and complete in roughly the time of the slowest individual extractor." The "General Architecture Pattern" ASCII diagram shows concurrent extractor branches. The "Variations" section notes that a Map state makes extraction parallel.

But the Step 5 pseudocode in `route_and_extract` is a sequential call: a single function that calls the appropriate extractor and returns. The actual fan-out (parallel Lambda invocations) only appears as a variation, not as the main path. A reader who implements Step 5 as written gets sequential page processing, not the parallel fan-out described. The 3-5 second single-extractor latency claim relies on parallelism; sequential processing of a 12-page submission with multiple clinical pages could take 30-60 seconds just for the Comprehend Medical calls.

**Suggested fix:** Either: (a) make the Map state the primary implementation path in Step 5 rather than a variation, with a note that sequential processing is the simpler fallback; or (b) add an explicit warning in the pseudocode that this is a sequential reference implementation and that production performance requires the Step Functions Map state parallel execution shown in the Variations section. Do not present the sequential version alongside latency claims that assume parallelism.

### Issue A3: Classification Confidence Score Missing from Output (Significant)

**The problem:** The `classify_page` function returns a page_type string (e.g., "clinical_note") but no confidence score. The assembled record's `page_classifications` map contains only the type, not the score. A human reviewer looking at a flagged record cannot distinguish between a page classified as "clinical_note" with a score of 12 (8 keyword hits plus structural bonuses) versus a page that barely exceeded "cover_sheet" with a score of 4 (3 keyword hits, minimum threshold). Both appear identically in the output.

This gap has two practical consequences. First, borderline classifications are invisible to the assembler's review routing logic: only extraction confidence gates the `needs_review` flag, not classification uncertainty. A page misclassified with high apparent confidence (many keywords matched the wrong type) produces extraction results at full confidence with no review flag. Second, without classification scores in the output, the feedback loop for improving the classifier has no signal about which pages were ambiguous.

**Suggested fix:** Return a classification score and a top-two candidates list from `classify_page`. Store the score in `page_classifications` alongside the type: `{ "3": { "type": "clinical_note", "score": 11, "runner_up": "imaging_report", "runner_up_score": 4 } }`. Add a classification confidence gate to the assembler: if the winning score is below a threshold, or if the runner-up is within N points of the winner, set `needs_review = true` and add the page to `flagged_pages`.

### Issue A4: Lab Results Extractor Has No Confidence Gating (Significant)

**The problem:** The `extract_lab_page` function contains this comment: "lab tables either parse or they don't; no confidence gating here." This is incorrect as a blanket statement. Textract TABLE cell blocks carry individual text confidence scores. A blurry fax of a lab results page can produce structurally valid table parsing (table found, rows and columns identified) while individual cell text confidence is low. A result value of "28" (correct) and "2B" (OCR error) both parse as valid table cells. The confidence difference is in the text confidence of the CELL block, not the table structure.

A lab result row with `{ "test_name": "ESR", "result": "28", "flag": "H" }` extracted at 97% confidence is different from the same row extracted at 63% confidence. Storing both without differentiation means a downstream system treats a potentially garbled numeric value the same as a clean extract.

**Suggested fix:** Remove the "lab tables either parse or they don't" comment. Add confidence gating on CELL block text confidence: cells below 80% text confidence should be flagged. Return them in the `flagged` list with the cell coordinates and the low-confidence value. This aligns lab result confidence handling with the cover sheet extractor's field-level confidence gating.

### Issue A5: Comprehend Medical Throttling Has No Retry Specification (Minor)

**The problem:** The `extract_clinical_page` extractor calls both `InferICD10CM` and `DetectEntitiesV2`. Comprehend Medical has service quotas on transactions per second (default: 10 TPS per API per region, adjustable). At volume, throttling (HTTP 429 / `ThrottlingException`) is expected. The recipe mentions retry logic as a general Step Functions feature but never specifies retry configuration on the Comprehend Medical call states.

**Suggested fix:** Add a note in the clinical extractor pseudocode or in the Step Functions section: configure retry on the `pa-extract-clinical` Lambda state with exponential backoff for `States.TaskFailed` caused by `ThrottlingException`. Alternatively, implement retry within the Lambda itself using the boto3 client's built-in retry configuration (`config=Config(retries={'max_attempts': 3, 'mode': 'adaptive'})`). Note that the adaptive retry mode responds to actual throttle signals rather than retrying on a fixed schedule.

### Issue A6: Two-Page Cover Sheet Logic Is Incomplete in Pseudocode (Minor)

**The problem:** The assembler pseudocode includes the comment "First cover sheet wins if multiple pages classified as cover sheets" with an `IF record.demographics.member_name is null` guard. The "Why This Isn't Production-Ready" section correctly flags this as a gap. However, the pseudocode for requested_service and requesting_provider has the same `IF ... is null` pattern applied only to the second cover sheet encounter. This means if the first cover sheet extracted with low confidence (leaving fields null) and the second cover sheet would have extracted them cleanly, the second cover sheet's fields do fill in correctly -- which is actually the right behavior.

But the comment "First cover sheet wins" sets the wrong mental model. The actual behavior is "first non-null value wins," which is subtly different and actually better. The prose description and the code are inconsistent.

**Suggested fix:** Change the comment to "first non-null value wins: later cover sheets fill in fields that earlier pages left empty." Remove the "first cover sheet wins" language from the "Why This Isn't Production-Ready" gap description, which currently says the second page's data "is left on the floor" -- this is only true if the first page successfully extracted all fields, which is a specific case, not the general behavior of the pseudocode.

---

## Networking Expert Review

### What's Done Well

The VPC endpoint list in prerequisites is the most complete in the series: S3 (gateway), Textract, DynamoDB, SNS, Comprehend Medical, Step Functions, CloudWatch Logs, and KMS. Explicitly calling out Step Functions VPC endpoint is notable -- many architects forget this and discover the gap only when Lambda functions inside the VPC cannot start state machine executions. The inclusion of CloudWatch Logs VPC endpoint is also correct and often missed.

### Issue N1: CloudWatch Logs Endpoint Name Ambiguity (Significant)

**The problem:** The prerequisite lists "CloudWatch Logs" as a VPC endpoint. There are two distinct VPC interface endpoints for CloudWatch: `com.amazonaws.{region}.logs` (for CloudWatch Logs, i.e., `logs:CreateLogGroup`, `logs:PutLogEvents`) and `com.amazonaws.{region}.monitoring` (for CloudWatch Metrics, i.e., `cloudwatch:PutMetricData`). Lambda functions write logs to CloudWatch Logs. Step Functions Express Workflows write execution history to CloudWatch Logs. Both require the `logs` endpoint.

Without specificity, a builder may create the `monitoring` endpoint (the more commonly discussed one) and find that Lambda execution logs and Step Functions execution history are not reaching CloudWatch Logs from within the VPC. This is a silent failure: the function executes, returns a result, and no logs appear.

**Suggested fix:** Change "CloudWatch Logs" in the VPC endpoint list to specify the endpoint service name: `com.amazonaws.{region}.logs` for CloudWatch Logs (Lambda execution logs, Step Functions execution logging). If CloudWatch Metrics are also needed, add `com.amazonaws.{region}.monitoring` separately. Add a note that Express Workflows require the `logs` endpoint configured before CloudWatch Logs logging is enabled on the state machine.

### Issue N2: SNS VPC Endpoint Needs a Resource Policy (Significant)

**The problem:** The recipe correctly includes an SNS VPC endpoint in the VPC endpoint list. SNS Interface endpoints support VPC endpoint policies. Without a resource policy on the VPC endpoint, Lambda functions inside the VPC can publish to any SNS topic in the account. For a PHI workflow, this is an unnecessary blast radius: the Lambda functions in this pipeline should only be able to publish to the specific SNS topic used for Textract completion notifications.

**Suggested fix:** Add a note in the VPC section: "Apply a VPC endpoint policy to the SNS endpoint that restricts `sns:Publish` to the specific Textract completion SNS topic ARN. This prevents Lambda functions in this VPC from inadvertently publishing to other SNS topics in the account." Provide a minimal policy example scoped to the specific topic ARN.

### Issue N3: Textract Service Principal Requires SNS Topic Policy (Significant)

**The problem:** The async Textract workflow requires that the Textract service publishes job completion notifications to the SNS topic. Textract calls SNS from the AWS service network (not from within the customer's VPC). This means Textract does not use the customer's VPC endpoint to reach SNS. For the Textract-to-SNS notification to work, the SNS topic's resource-based policy must grant `sns:Publish` to the Textract service principal (`textract.amazonaws.com`). This is separate from the VPC endpoint policy.

The recipe carries over the async Textract pattern from Recipe 1.2 without repeating this detail ("See Recipe 1.2 for complete pseudocode"). If a reader starts from Recipe 1.4 without having read Recipe 1.2, this configuration is entirely absent. Given that Recipe 1.4 adds SNS to the explicit VPC endpoint discussion, a reader is likely to tighten the SNS topic policy while adding the VPC endpoint, which could inadvertently block the Textract service principal.

**Suggested fix:** Add a brief note in the prerequisites or in the Step 1 walkthrough: "The SNS topic used for Textract job completion requires a resource-based policy granting `sns:Publish` to the Textract service principal (`textract.amazonaws.com`). This is a service-side callback from AWS infrastructure and does not use the VPC endpoint. Ensure any VPC endpoint policy or topic resource policy does not exclude the Textract service principal."

### Issue N4: Step Functions VPC Endpoint Has Per-AZ Cost (Minor)

**The problem:** Step Functions is a new addition to the VPC endpoint list compared to Recipes 1.1-1.3. Interface endpoints (which Step Functions, Textract, Comprehend Medical, SNS, KMS, and CloudWatch Logs all use) cost approximately $0.01/hour per AZ. A deployment in 3 AZs with 7 interface endpoints costs roughly $21/month in endpoint charges, before any data processing fees. This is not a correctness issue, but it is a non-trivial ongoing cost that scales with the number of interface endpoints and AZs.

**Suggested fix:** Add a brief note in the VPC prerequisites section: "Each interface endpoint costs approximately $0.01/hour per AZ ($7-8/month per endpoint in a 3-AZ deployment). The full endpoint set for this recipe adds approximately $50-60/month in VPC endpoint charges. Share endpoints across recipes where the same VPC is used."

### Issue N5: Comprehend Medical Region Availability Not Mentioned (Minor)

**The problem:** Comprehend Medical is not available in all AWS regions. A builder selecting a region for data residency, HIPAA alignment, or latency may choose a region where Comprehend Medical is unavailable (or available only with reduced functionality). The recipe inherits this gap from Recipe 1.3 and repeats it.

**Suggested fix:** Add one sentence to the prerequisites or the Comprehend Medical ingredient row: "Verify Comprehend Medical availability in your target region before architecture decisions; it is available in a subset of AWS regions. See the [AWS Regional Services List](https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/) for current availability."

---

## Additional Observations

### Textract Pricing Arithmetic Needs Verification

The prerequisites state: "Textract async (FORMS + TABLES + LAYOUT): approximately $4.50 per 1,000 pages." Textract async pricing adds per-feature charges on top of the base async rate. At current pricing, running FORMS + TABLES + LAYOUT together involves the base async charge plus charges for each feature type. The stated $4.50 may be understated if multiple feature type charges stack. This should be verified against current Textract pricing and the total cost per submission recalculated, since the per-submission and annual cost estimates flow from this figure.

### `extract_section_text` Section Termination Logic Is Incomplete

The `extract_section_text` function comment says "a production implementation checks against a full section header list" for the section stop condition, but the pseudocode provides no guidance on what that list should look like. A naive reader might implement `break` on any capitalized line or any line shorter than N characters, both of which would produce incorrect section boundaries on real clinical notes. Consider either providing a minimal reference list of common section headers (PLAN, MEDICATIONS, ALLERGIES, VITALS, etc.) or linking to a clinical NLP resource that covers section segmentation.

### "Curious How This Looks in Python" Link Is a Dead Reference

The inline note at the end of the Code section links to `chapter01.04-python-example` without a full path or URL. If this companion file does not exist yet, the link should be removed or replaced with a placeholder note until the file is ready. Dead cross-references in published cookbook content erode reader trust.

### Performance Table Claim Assumes Parallel Execution

The performance benchmarks show "25-50 seconds" end-to-end for a 10-page submission. This assumes the fan-out extractors run in parallel (as described in the Variations section with the Map state). The sequential pseudocode in Step 5 would produce materially higher latency. The performance table should note the parallelism assumption explicitly, consistent with the recommendation in Issue A2 above.

---

## Summary Table

| ID | Area | Severity | Issue |
|----|------|----------|-------|
| S1 | Security | Significant | S3 intermediate Textract artifacts have no lifecycle rule or PHI cleanup path |
| S2 | Security | Significant | PHI category entities from DetectEntitiesV2 stored in DynamoDB without policy decision |
| S3 | Security | Significant | Step Functions state machine execution role (for Lambda invocation) not covered in prerequisites |
| S4 | Security | Minor | DynamoDB encryption not specified as CMK, inconsistent with S3 approach |
| S5 | Security | Minor | Sample output NPI not marked as fictional |
| A1 | Architecture | Must Fix | Express Workflows do not show visual execution history in console by default; recipe's debugging rationale for Step Functions is factually wrong |
| A2 | Architecture | Significant | Fan-out pseudocode is sequential; parallelism claims depend on Map state that is only in Variations |
| A3 | Architecture | Significant | Classification confidence score absent from output; borderline classifications invisible to review routing |
| A4 | Architecture | Significant | Lab results extractor has no cell-level confidence gating despite OCR quality risk |
| A5 | Architecture | Minor | No retry specification for Comprehend Medical throttling on clinical extractor states |
| A6 | Architecture | Minor | "First cover sheet wins" comment is inconsistent with actual "first non-null wins" pseudocode behavior |
| N1 | Networking | Significant | "CloudWatch Logs" VPC endpoint needs explicit endpoint service name to avoid confusion with CloudWatch Metrics |
| N2 | Networking | Significant | SNS VPC endpoint needs a resource policy scoped to the specific topic ARN |
| N3 | Networking | Significant | Textract service principal SNS topic policy not mentioned; tightening the SNS policy could block Textract callbacks |
| N4 | Networking | Minor | Interface endpoint per-AZ cost not quantified; new endpoint set adds ~$50-60/month |
| N5 | Networking | Minor | Comprehend Medical region availability not mentioned |

---

## Priority Actions Before Publication

1. **Fix A1 (must fix):** Correct the Express Workflows debugging claim. Either add CloudWatch Logs configuration as a required step, or recommend Standard Workflows for teams that need console-level debuggability.

2. **Fix A2 (significant):** Reconcile the sequential pseudocode with the parallel fan-out framing. The current recipe promises parallelism and delivers a for-loop.

3. **Fix S3 (significant):** Add the Step Functions execution role for Lambda invocation to the prerequisites. This is a deployment blocker.

4. **Fix N1 and N3 (significant):** Disambiguate the CloudWatch Logs endpoint name, and add the Textract service principal SNS topic policy note. Both are silent failures that appear only at deployment time.

5. **Fix S1 (significant):** Add S3 lifecycle rules and pipeline cleanup for PHI-containing intermediate artifacts. This is a compliance control, not just an operational detail.

The remaining issues (S2, A3, A4, N2, S4, S5, A5, A6, N4, N5) are improvements that meaningfully raise production quality but do not block a technically capable builder from deploying correctly.

---

*Review complete. Recipe 1.4 is the strongest architectural recipe in the chapter and the one with the highest production stakes. The issues above are proportionate to that complexity: most are things that only surface in a real deployment, not in a demo.*
