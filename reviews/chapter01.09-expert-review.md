# Expert Review: Recipe 1.9 -- Medical Records Request Extraction

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking)
**Recipe:** Chapter 01.09 -- Medical Records Request Extraction
**Date:** 2026-03-05
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 1.9 tackles a real and legally sensitive problem: automating the triage of medical records requests under HIPAA's authorization rules. The architectural bones are sound -- synchronous Textract with FORMS + SIGNATURES, four-Lambda pipeline, SQS-based routing, and KMS encryption at every layer. The writing is honest about what the pipeline does and does not do, which is more than most recipes offer.

However, three categories of gaps require attention before this recipe can be recommended to production teams. First, the HIPAA authorization validation is incomplete: it checks five elements when 45 CFR 164.508 requires six for the core set, and omits the additional required statements entirely. Second, signature detection is presented with a confidence that slightly exceeds what fax-quality real-world performance justifies, without adequate discussion of the legal consequences of false negatives. Third, PHI flows through several components (SNS notifications, SQS message bodies) where the encryption assurances are inconsistent or understated.

Every finding below includes a concrete fix.

---

## Security Review

### 🔴 SEC-1: HIPAA 45 CFR 164.508 Validation is Missing Two Core Required Elements

**Finding:** The `REQUIRED_AUTH_ELEMENTS` map checks five elements: signature, authorization date, records description, purpose, and expiration. But 45 CFR 164.508(c)(1) specifies six required elements for a valid authorization:

1. (i) Description of information to be used or disclosed -- checked (`records_requested`)
2. **(ii) Name or specific identification of the person(s) authorized to make the requested use or disclosure** -- the disclosing covered entity; NOT checked
3. **(iii) Name or specific identification of the person(s) to whom the covered entity may make the requested use or disclosure** -- the recipient; `requestor_name` is extracted but NOT in `REQUIRED_AUTH_ELEMENTS`
4. (iv) Description of each purpose -- checked (`purpose`)
5. (v) Expiration date or event -- checked (`expiration_date`)
6. (vi) Signature of individual and date -- checked (split into `patient_or_rep_signature` and `authorization_date`)

Elements (ii) and (iii) are not optional. An authorization that identifies the patient, a purpose, and an expiration date but does not name the disclosing entity or the receiving party is legally deficient under the rule.

Additionally, 45 CFR 164.508(c)(2) requires that the authorization include three additional statements:
- A statement that the individual may revoke the authorization at any time (with procedure).
- A statement about whether treatment, payment, enrollment, or benefits eligibility is conditioned on the authorization.
- A statement that information disclosed pursuant to the authorization may be subject to re-disclosure by the recipient.

None of these are checked. These are required elements, not optional boilerplate. A covered entity that relies on this pipeline's "valid: true" output as confirmation of legal sufficiency without also independently checking these statements has a compliance gap.

**Fix:** Add `requestor_identity` (mapping to 164.508(c)(1)(iii)) and `disclosing_entity` (mapping to 164.508(c)(1)(ii)) to `REQUIRED_AUTH_ELEMENTS`. For (c)(1)(ii), the disclosing entity is typically the covered entity itself -- this may be inferable from the form header rather than a filled field, so add logic to treat it as present if the form is addressed to the covered entity, and flag it for review if ambiguous.

For the (c)(2) required statements, the recipe should add a validated field group and be explicit that it does NOT check for them. The current "Why This Isn't Production-Ready" section only covers sufficiency concerns, not the completeness gap. Add a callout box: "This pipeline does not check for the required 45 CFR 164.508(c)(2) statements (right to revoke, conditioning statement, re-disclosure statement). These must be verified through form template standardization or supplemental review."

```
// Add to REQUIRED_AUTH_ELEMENTS:
"requestor_identity": "Name of person(s) authorized to receive disclosure (45 CFR § 164.508(c)(1)(iii))",
"disclosing_entity":  "Name of person(s) authorized to make the use/disclosure (45 CFR § 164.508(c)(1)(ii))"

// Add separate informational check (not blocking, but logged):
C2_STATEMENTS_NOTE = "Authorization does not check for required 164.508(c)(2) statements. " +
                     "Ensure form templates include right-to-revoke, conditioning, " +
                     "and re-disclosure language."
```

---

### 🔴 SEC-2: Authorized Representative Validation Gap

**Finding:** 45 CFR 164.508(c)(1)(vi) requires the "signature of the individual and the date the authorization was signed. If the authorization is signed by a personal representative of the individual, a description of such representative's authority to act for the individual." The pipeline confirms a signature is present and a date is present, but it does not check whether the signer is the patient or a representative. If it is a representative, the authorization must also document that representative's authority. The pipeline has no mechanism to detect or flag this.

In practice, a significant share of authorization forms are signed by legal guardians, healthcare proxies, or power-of-attorney holders. Accepting these without flagging the representative-authority question creates a compliance gap on the forms most likely to be challenged.

**Fix:** Add a field `representative_authority` to the field map with label variants like "legal guardian," "power of attorney," "relationship to patient," and "authority to sign." In the validation function, add a check: if `requestor_name` does not match `patient_name` AND a `representative_authority` field is present, flag `needs_review` with the reason "Authorization signed by apparent representative. Representative's authority documentation should be confirmed." If the names diverge and no representative-authority field is detected, set `valid = false` and add a missing element: "Representative's authority to act for the patient (45 CFR § 164.508(c)(1)(vi))."

---

### 🟠 SEC-3: SNS Deficiency Notifications Carry PHI Without Confirmed KMS Encryption

**Finding:** The `assemble_and_route` function publishes to the SNS deficiency topic with `patient_name`, `requestor`, and `missing` elements. The prerequisites table specifies KMS encryption for S3, DynamoDB, and SQS, but SNS is not listed. The recipe mentions "Amazon SNS for deficiency notification" in ingredients but does not require or configure SNS server-side encryption with KMS. SNS topics can be configured with SSE-KMS, but it is not enabled by default, and the prerequisites do not call it out.

A deficiency notification containing a patient name is PHI. An unencrypted SNS topic delivering PHI to a downstream ticketing system violates the HIPAA Security Rule's encryption-at-rest and encryption-in-transit requirements (45 CFR 164.312(a)(2)(iv) and 164.312(e)(2)(ii)).

**Fix:** Add SNS to the encryption requirements section in the prerequisites table:

```
| SNS topic (rr-deficiency) | SSE-KMS with the same customer-managed key |
```

And add a note: "The SNS topic must have server-side encryption enabled with a KMS CMK before any PHI-containing notifications are published. SNS SSE-KMS is configured at topic creation; it cannot be retroactively applied to in-flight messages."

Consider whether the SNS notification body needs to carry `patient_name` at all. If the downstream letter-generation workflow can look up the patient by `document_key` from DynamoDB, the SNS payload can be limited to `document_key` + `missing` + `expired`, removing PHI from the notification entirely. This is a better design.

---

### 🟠 SEC-4: PHI in SQS Message Bodies Without Minimum-Necessary Scoping

**Finding:** The `assemble_and_route` function sends `patient_name` and `records_requested` to the fulfillment SQS queues. The `records_requested` field can contain highly specific PHI: diagnoses, procedure types, and treatment dates. The recipe notes that "No PHI in Lambda environment variables or CloudWatch logs" applies to logs but does not extend this same discipline to SQS message payloads.

SQS SSE-KMS is called out in prerequisites, which covers encryption at rest. However, minimum-necessary discipline suggests that SQS messages should carry the minimum PHI needed for the fulfillment system to fetch the full record, not the full record itself. A `document_key` reference is sufficient for the fulfillment system to retrieve everything from DynamoDB or S3.

**Fix:** Revise the SQS routing payload to carry only reference data:

```
// Minimal PHI in SQS messages; fulfillment system fetches full record from DynamoDB.
send message to SQS queue at queue_arn:
    document_key:  document_key,         // primary key for DynamoDB lookup
    request_type:  request_type,
    needs_review:  validation.needs_review,
    processed_at:  record.processed_at
    // Remove patient_name and records_requested from SQS payload
```

Add an explanatory note: "Fulfillment consumers retrieve the full structured record from DynamoDB using document_key. SQS messages carry only enough information to identify and prioritize the work item, not to fulfill it."

---

### 🟡 SEC-5: S3 Bucket Access Logging and Object Versioning Not Specified

**Finding:** The prerequisites specify SSE-KMS and TLS-only access for the S3 bucket but do not require S3 access logging or object versioning. HIPAA audit controls (45 CFR 164.312(b)) require activity logs on systems that access or store PHI. S3 access logs capture every GetObject, PutObject, and DeleteObject on the bucket. Without them, you cannot reconstruct who accessed which document if a breach investigation is needed.

Object versioning is relevant when the same document key might be overwritten (for example, if a fax server retransmits the same file). Versioning preserves the original for audit purposes.

**Fix:** Add to the S3 prerequisites:

```
S3 Access Logging: Enable server access logging to a separate audit-log bucket.
                   The audit-log bucket must itself be encrypted and access-restricted.
S3 Versioning:     Enable versioning on the records-requests bucket. Configure a
                   lifecycle policy to transition versions to S3 Glacier after 90 days
                   and expire after 7 years (typical HIPAA retention window).
```

---

### 🟡 SEC-6: CloudTrail Log Integrity Validation Not Mentioned

**Finding:** CloudTrail is called out in prerequisites, which is correct. However, for HIPAA audit admissibility, CloudTrail log file validation should also be enabled. Log file validation creates a digest file for each CloudTrail log that allows you to detect whether a log file was modified or deleted after delivery. Without it, an attacker or malicious insider who gained access to the CloudTrail S3 bucket could alter audit records.

**Fix:** Add one line to the CloudTrail prerequisite: "Enable log file validation in the CloudTrail trail configuration (`EnableLogFileValidation: true`). This creates SHA-256 hash digest files that allow detection of log tampering."

---

### 🔵 SEC-7: Signature Confidence Threshold is Not Audit-Logged as a Policy Decision

**Finding:** The chapter correctly notes that "the right threshold depends on your risk tolerance" and that the threshold "should be configurable per environment, not hardcoded." However, the code does not show any logging of the threshold value used at processing time. If the threshold is changed after a deficiency decision is made, there is no way to reconstruct what threshold was applied to a specific document.

**Fix:** Include the threshold value in the authorization validation result and in the DynamoDB record:

```
authorization: {
    ...
    signature_confidence_threshold_used: SIGNATURE_CONFIDENCE_THRESHOLD,
    ...
}
```

This makes the threshold a durable part of the audit trail, not just a configuration value.

---

### ✅ SEC-PRAISE-1: Honest Framing of "Validated" vs. "Legally Sufficient"

The "Honest Take" section's explicit statement -- "this pipeline does not validate authorizations. It checks that the required elements are present" -- is exactly right and exactly what legal and compliance teams need to see. Most document-processing recipes in this space oversell the compliance story. This one does not.

### ✅ SEC-PRAISE-2: Four-Lambda Separation for Auditability

Separating extraction, validation, classification, and routing into discrete Lambda functions means each compliance concern has a single owner. Changing the validation logic for a new OCR interpretation of 164.508 does not touch extraction or routing. This is the correct design for a system where compliance requirements evolve.

---

## Architecture Review

### 🔴 ARCH-1: No Orchestration Layer Means Pipeline Failures Are Silent

**Finding:** The recipe describes four Lambda functions (rr-extract, rr-validate, rr-classify, rr-route) but does not specify how they are chained together. The architecture diagram shows them as a linear pipeline, but the implementation section treats each function as independent. In practice, the most common pattern would be synchronous invocation from rr-extract to rr-validate to rr-classify to rr-route, but this is not stated.

If rr-validate succeeds but rr-classify fails (throttle, timeout, unhandled exception), the pipeline is in a partially processed state: the document has a Textract result, the authorization has been checked, but no routing decision has been made. The document will not be retried unless the triggering Lambda (rr-extract, via S3 event) itself fails, which it will not because it succeeded. The request is silently lost.

This is a critical failure mode for a healthcare pipeline. Records requests that are lost in a failed classification step miss HIPAA Right of Access response deadlines (30 days under 45 CFR 164.524).

**Fix:** Use AWS Step Functions Express Workflows to orchestrate the pipeline. The state machine defines the four steps with explicit retry policies and a Catch handler that routes failures to an alerting/dead-letter path:

```
State Machine: MedicalRecordsRequestPipeline
  States:
    Extract:         Invoke rr-extract          | Retry: 3x, backoff 2s | Catch -> PipelineFailure
    Validate:        Invoke rr-validate          | Retry: 2x, backoff 1s | Catch -> PipelineFailure
    Classify:        Invoke rr-classify          | Retry: 2x, backoff 1s | Catch -> PipelineFailure
    RouteAndStore:   Invoke rr-route             | Retry: 2x, backoff 1s | Catch -> PipelineFailure
    PipelineFailure: Publish to SNS alert-topic with document_key and failed_step
```

The S3 event triggers the Step Functions execution, not rr-extract directly. Express Workflows are priced at $0.00001 per state transition; at 50,000 requests per year the cost is under $10.

---

### 🟠 ARCH-2: Idempotency Gap for Re-Submissions via Different S3 Keys

**Finding:** The recipe correctly identifies that "same document, different fax" creates two different S3 keys and two different DynamoDB records. The conditional DynamoDB write (`attribute_not_exists(document_key)`) only catches exact key duplicates. The "Why This Isn't Production-Ready" section notes this gap and suggests near-duplicate detection as an extension but does not implement it.

This is more than an operational annoyance. A duplicate records request that routes to the legal fulfillment queue may cause the covered entity to disclose records twice for the same authorization, potentially violating the minimum-necessary principle if the second fulfillment team is not aware of the first.

**Fix:** Add a composite deduplication check before the DynamoDB write. Hash the combination of `patient_id + requestor_fax + authorization_date + records_requested` (normalized) and write this as a `dedup_hash` attribute on the DynamoDB record. Before writing a new record, query for existing records with the same `dedup_hash` using a GSI. If a match exists within a 7-day window, log the duplicate and skip routing. The 7-day window covers the realistic fax retry window without blocking legitimate re-requests.

```
dedup_hash = sha256(normalize(patient_id) + "|" +
                    normalize(requestor_fax) + "|" +
                    normalize(authorization_date) + "|" +
                    normalize(records_requested[:100]))

// Query DynamoDB GSI on dedup_hash before writing
existing = dynamodb.query(
    IndexName: "dedup-hash-index",
    KeyConditionExpression: "dedup_hash = :h AND processed_at > :cutoff",
    ExpressionAttributeValues: {":h": dedup_hash, ":cutoff": 7_days_ago}
)

IF existing.Count > 0:
    log: "Duplicate request detected for " + document_key + ". Original: " + existing.Items[0].document_key
    RETURN early (no write, no routing)
```

---

### 🟠 ARCH-3: No Lambda Dead-Letter Queue for the S3 Trigger

**Finding:** The S3 event triggers the extraction Lambda. Lambda's default behavior on asynchronous invocation failure is to retry twice (with exponential backoff) and then discard the event. If the S3 trigger Lambda fails three times -- Textract throttle, Lambda cold start timeout, IAM permission error -- the document is never processed and no alert is generated. The pipeline has no visibility into dropped events.

**Fix:** Configure a Lambda destination for the S3-triggered Lambda's failure path:

```
Lambda Function: rr-extract (or Step Functions trigger Lambda)
  OnFailure Destination: SQS queue "rr-pipeline-dlq"
  MaximumRetryAttempts: 2
  MaximumEventAgeInSeconds: 3600
```

Add a CloudWatch alarm on `ApproximateNumberOfMessagesVisible` for the DLQ with a threshold of 1. Any unprocessed document triggers an alert within minutes. The DLQ message contains the S3 key of the failed document, enabling manual reprocessing.

---

### 🟠 ARCH-4: Textract Quota Throttling Not Addressed

**Finding:** Amazon Textract AnalyzeDocument has a default service quota of 1 transaction per second (TPS) for synchronous calls in some regions, with a burst limit that varies. The recipe targets a payer processing 200 requests before noon (roughly 16 per hour in a steady distribution). But fax processing is not uniformly distributed. A fax server batch that dumps 50 documents at market open can saturate the synchronous Textract quota and cause Lambda invocations to fail with `ThrottlingException`.

The recipe does not mention Textract quotas, quota increase procedures, or retry logic specific to throttling.

**Fix:** Add a section to prerequisites: "Request a Textract AnalyzeDocument quota increase before go-live. The default synchronous limit in most regions is 1-5 TPS; payers processing fax batches at market open may need 10-20 TPS. Submit the quota increase request at least two weeks before production launch."

In the extraction Lambda, add explicit retry logic for `ThrottlingException` with exponential backoff:

```
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 1.0

FOR attempt in range(MAX_RETRIES):
    TRY:
        response = textract.AnalyzeDocument(...)
        BREAK
    EXCEPT ThrottlingException:
        IF attempt == MAX_RETRIES - 1:
            RAISE  // Let Lambda fail and DLQ catch it
        sleep(BASE_DELAY_SECONDS * (2 ** attempt) + random_jitter())
```

---

### 🟡 ARCH-5: Cost Estimate Has a Potentially Incorrect Textract SIGNATURES Pricing Assumption

**Finding:** The prerequisites table states: "SIGNATURES detection: $0.0015/page (same rate as DetectDocumentText; Signatures uses the base text detection tier)." This is incorrect. When SIGNATURES is included in an AnalyzeDocument call that already uses FORMS, the SIGNATURES feature is processed at the AnalyzeDocument rate ($0.05/page), not the DetectDocumentText rate ($0.0015/page). There is no separate SIGNATURES line item on the Textract pricing page; it is bundled with the AnalyzeDocument analysis.

This means the actual cost for a 2-page form with FORMS + SIGNATURES is 2 x $0.05 = $0.10, not $0.103 as stated. The actual cost is slightly lower than claimed, which understates the value proposition but also creates a false impression of how Textract pricing is structured. If readers use this recipe to build their own cost models and apply $0.0015/page for SIGNATURES in other contexts (for example, TABLES + SIGNATURES), they will significantly underestimate their bills.

**Fix:** Correct the cost table:

```
| Textract FORMS (2 pages)      | 2 x $0.05 = $0.10 per request         |
| Textract SIGNATURES           | Included in AnalyzeDocument pricing;  |
|                               | no separate charge when used with FORMS|
| DynamoDB, SQS, SNS            | <$0.001 per request                   |
| Step Functions Express         | <$0.001 per request                   |
| Total per 2-page form         | ~$0.10 per request                    |
| Annual (50,000 requests)      | ~$5,000                               |
```

Add a note: "Verify current Textract pricing at aws.amazon.com/textract/pricing. Feature pricing tiers can change; the pricing page is authoritative."

---

### 🟡 ARCH-6: Keyword Classifier Tie-Breaking Priority is Undisclosed

**Finding:** The classifier's tie-breaking rule ("prefer in order: care_coordination, legal, underwriting, utilization_review, patient_access") is stated in the pseudocode without explanation. This priority order has real compliance consequences. A request that scores equally for "legal" and "underwriting" will be routed to care_coordination, which is the highest priority in the tie-breaking list. If the request is actually a legal request, routing it to care coordination causes a disclosure outside the appropriate legal context and delays the actual legal team's involvement.

The priority order should reflect the risk profile of misrouting, not be arbitrarily listed. Legal requests have the highest legal exposure if mishandled; they should get priority in ties over care coordination.

**Fix:** Invert the tie-breaking priority for high-risk types:

```
// Tie-breaking order (highest to lowest):
// Legal and underwriting have largest compliance consequences if misrouted.
// Care coordination and patient access have stricter timeline requirements
// but lower legal exposure on misrouting.
TIE_BREAK_ORDER = ["legal", "underwriting", "utilization_review", "patient_access", "care_coordination"]
```

Add commentary: "The tie-breaking order reflects misrouting risk. Legal requests misrouted to care coordination may trigger unauthorized disclosures outside litigation context. Adjust this order after reviewing your organization's risk profile with legal counsel."

---

### 🔵 ARCH-7: Lambda Memory and Timeout Configuration Not Specified

**Finding:** The recipe does not specify Lambda memory allocation or timeout for any of the four functions. For rr-extract, Textract synchronous calls typically take 2-4 seconds, plus parsing the block list for a 2-page form. A default Lambda timeout of 3 seconds would cause intermittent failures. The recipe's stated latency of "2-5 seconds end-to-end" implies the extraction Lambda alone may need up to 4 seconds of execution time.

**Fix:** Add a Lambda configuration table to the implementation section:

```
| Function   | Memory  | Timeout | Reason                                        |
|------------|---------|---------|-----------------------------------------------|
| rr-extract | 512 MB  | 30s     | Textract call + block parsing                 |
| rr-validate| 256 MB  | 10s     | CPU-light validation logic                    |
| rr-classify| 256 MB  | 10s     | String matching on document text              |
| rr-route   | 256 MB  | 15s     | DynamoDB write + SQS send (potential retries) |
```

---

### ✅ ARCH-PRAISE-1: SQS Decoupling Pattern is Exactly Right

Routing to type-specific SQS queues rather than direct Lambda invocations of downstream systems is the correct pattern for a healthcare pipeline. It absorbs fax-batch bursts, allows each fulfillment team to scale consumers independently, and makes the pipeline observable (queue depth is a first-class metric). The dead-letter queue mention, even if not fully specified, indicates the right instinct.

### ✅ ARCH-PRAISE-2: Synchronous Textract for 1-2 Page Forms

Choosing synchronous `AnalyzeDocument` over the async job pattern is the right call for 1-2 page documents. The async pattern from Recipe 1.2 adds 15-30 seconds of polling or SNS callback latency. For sub-5-page documents, synchronous processing is simpler, faster, and equally reliable.

---

## Networking Review

### 🟠 NET-1: VPC Endpoint Policies Are Not Specified

**Finding:** The prerequisites correctly list VPC endpoints for S3 (gateway), Textract, DynamoDB, SQS, SNS, CloudWatch Logs, and KMS. However, without VPC endpoint policies, these endpoints allow access to ALL resources of each service type, not just the resources belonging to this pipeline. A Lambda function in the VPC could call Textract on arbitrary documents, write to any DynamoDB table in the account, or publish to any SNS topic.

VPC endpoint policies are the network-layer enforcement of least privilege. For a PHI pipeline, they are a required control, not a hardening option.

**Fix:** Define restrictive VPC endpoint policies for each endpoint. Example for S3:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::ACCOUNT_ID:role/rr-lambda-role"},
    "Action": ["s3:GetObject"],
    "Resource": "arn:aws:s3:::records-requests-bucket/*"
  }]
}
```

Example for DynamoDB:
```json
{
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::ACCOUNT_ID:role/rr-lambda-role"},
  "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query"],
  "Resource": "arn:aws:dynamodb:REGION:ACCOUNT_ID:table/records-requests*"
}
```

Add a callout: "VPC endpoint policies are the network-layer equivalent of IAM least privilege. Without them, a Lambda breakout or a misconfigured IAM role can call Textract on any document in the account. Define per-endpoint policies that restrict to the specific ARNs used by this pipeline."

---

### 🟠 NET-2: Fax-Server-to-S3 Ingestion Path Not Secured

**Finding:** The architecture diagram shows "Fax Server / Portal" as the source, with the arrow labeled "Request PDF" going directly to S3. The recipe does not specify how the fax server connects to S3. Common fax-to-cloud integrations (Kofax, eFax Corporate, Sfax, OpenText) typically upload to S3 over the public internet using IAM credentials or pre-signed URLs.

For a PHI pipeline, the fax server is the first touch point of the PHI and is outside the VPC. If the fax server is on-premises, the upload path traverses the public internet unless the organization has Direct Connect or a Site-to-Site VPN. The recipe's VPC controls protect Lambda-to-AWS-service traffic but do nothing for the fax-server-to-S3 ingestion.

**Fix:** Add a network security section covering ingestion:

"Fax server connectivity: If the fax server is on-premises, configure ingestion via either:
(a) AWS Site-to-Site VPN with the S3 upload endpoint routed through the VPN, or
(b) AWS Direct Connect with a private virtual interface.
If the fax server is SaaS-based (cloud fax provider), require that the provider uses an IAM role with least-privilege S3 PutObject permissions scoped to the `records-requests/` prefix, with an S3 bucket policy condition requiring `aws:SourceVpc` or `aws:SourceIP` to restrict uploads to the provider's IP ranges. Enable S3 bucket notifications only on the `records-requests/` prefix to prevent triggering the pipeline on uploads to other prefixes."

---

### 🟡 NET-3: No Mention of Security Group Rules for Lambda VPC

**Finding:** Lambda functions in a VPC require security groups. The recipe does not specify what inbound/outbound rules should be applied. A common misconfiguration is an overly permissive security group (0.0.0.0/0 outbound) that, if the endpoint policies are absent or misconfigured, allows Lambda to reach arbitrary internet endpoints.

Since all downstream calls go through VPC endpoints, the Lambda security group outbound rules should be highly restrictive.

**Fix:** Add security group configuration guidance:

```
Lambda Security Group (sg-rr-lambda):
  Inbound:  None (Lambda functions do not accept inbound connections)
  Outbound: HTTPS (TCP 443) to the VPC endpoint security groups only:
            - sg-vpce-s3 (S3 gateway endpoint; attach to route table, not SG)
            - sg-vpce-textract
            - sg-vpce-dynamodb
            - sg-vpce-sqs
            - sg-vpce-sns
            - sg-vpce-kms
            - sg-vpce-cloudwatch-logs
  No outbound to 0.0.0.0/0. No NAT Gateway.
```

Add a note: "Lambda functions in this pipeline do not need internet access. All AWS service calls route through interface VPC endpoints. Denying all non-VPC-endpoint outbound traffic prevents data exfiltration if a Lambda package dependency is compromised."

---

### 🟡 NET-4: Textract Interface Endpoint Regional Availability Not Verified

**Finding:** Amazon Textract interface VPC endpoints are not available in all AWS regions. As of early 2026, Textract VPC endpoints are available in select regions (us-east-1, us-west-2, eu-west-1, ap-southeast-1, and a few others) but not universally. A team deploying this recipe in ap-south-1 or ca-central-1 may find that a Textract VPC endpoint is not available, forcing Textract calls over the NAT gateway to the public Textract endpoint.

This is a compliance gap: PHI would traverse the public internet for the Textract call, albeit encrypted over TLS. The HIPAA Security Rule does not categorically prohibit encrypted PHI transmission over the public internet, but most covered entity policies and BAAs prefer PHI to stay on private networks.

**Fix:** Add a note to prerequisites: "Verify that Amazon Textract interface VPC endpoints are available in your target AWS region before beginning deployment. Check the AWS regional services list at aws.amazon.com/about-aws/global-infrastructure/regional-product-services. If Textract VPC endpoints are not available in your region, either: (a) deploy to a region where they are available, or (b) route Textract calls through a NAT Gateway and document this as an accepted risk with your privacy officer and legal team. Textract API calls are always encrypted over TLS regardless of network path."

---

### 🔵 NET-5: CloudWatch Logs VPC Endpoint Log Group Scoping

**Finding:** The prerequisites list a VPC endpoint for CloudWatch Logs, which is correct. However, Lambda function log groups for PHI-adjacent pipelines should be isolated in a dedicated log group with restricted access. If the Lambda execution role has `logs:CreateLogGroup` and `logs:PutLogEvents` on `*`, it can write to any log group in the account, and the VPC endpoint policy cannot restrict this at the Lambda level.

**Fix:** Pre-create named log groups for each Lambda function and restrict Lambda IAM permissions to those specific groups:

```
IAM Policy for Lambda execution role (logs section):
  Action: ["logs:CreateLogStream", "logs:PutLogEvents"]
  Resource: [
    "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/lambda/rr-extract:*",
    "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/lambda/rr-validate:*",
    "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/lambda/rr-classify:*",
    "arn:aws:logs:REGION:ACCOUNT_ID:log-group:/aws/lambda/rr-route:*"
  ]
  // Note: logs:CreateLogGroup is NOT granted; pre-create groups with retention policy.
```

Enable CloudWatch Log Data Protection on each log group (already mentioned in "Why This Isn't Production-Ready" but not in prerequisites) and configure a 7-year retention policy.

---

### ✅ NET-PRAISE-1: Complete VPC Endpoint List in Prerequisites

Listing all seven required VPC endpoints explicitly (S3 gateway, Textract, DynamoDB, SQS, SNS, CloudWatch Logs, KMS) is thorough and directly actionable. Many recipes stop at "deploy in a VPC" without specifying which endpoints are needed. This list prevents the most common deployment mistake.

---

## Summary Table

| ID | Severity | Category | Issue | Fix Summary |
|----|----------|----------|-------|-------------|
| SEC-1 | 🔴 Critical | Security/HIPAA | 164.508 validation missing elements (ii), (iii), and (c)(2) statements | Add requestor_identity and disclosing_entity to REQUIRED_AUTH_ELEMENTS; document (c)(2) gap |
| SEC-2 | 🔴 Critical | Security/HIPAA | Authorized representative authority not detected or flagged | Add representative_authority field; flag or reject when patient/signer names diverge |
| SEC-3 | 🟠 High | Security/PHI | SNS deficiency topic not required to use KMS encryption | Add SNS SSE-KMS to prerequisites; reduce PHI in notification payload |
| SEC-4 | 🟠 High | Security/PHI | PHI in SQS message bodies exceeds minimum-necessary | Route SQS messages by document_key reference only; consumers fetch from DynamoDB |
| SEC-5 | 🟡 Medium | Security/Audit | S3 access logging and versioning not required | Add access logging and versioning to S3 prerequisites |
| SEC-6 | 🟡 Medium | Security/Audit | CloudTrail log integrity validation not mentioned | Enable EnableLogFileValidation on CloudTrail trail |
| SEC-7 | 🔵 Low | Security/Audit | Signature confidence threshold not durably logged | Include threshold value in DynamoDB record at processing time |
| ARCH-1 | 🔴 Critical | Architecture | No orchestration: partial pipeline failures are silent | Orchestrate with Step Functions Express Workflows |
| ARCH-2 | 🟠 High | Architecture | Deduplication only covers exact S3 key matches | Add dedup_hash composite key with DynamoDB GSI and 7-day window |
| ARCH-3 | 🟠 High | Architecture | No Lambda DLQ for S3 trigger async failures | Add OnFailure destination DLQ + CloudWatch alarm |
| ARCH-4 | 🟠 High | Architecture | Textract throttling not handled | Add ThrottlingException retry logic; document quota increase process |
| ARCH-5 | 🟡 Medium | Architecture | SIGNATURES pricing assumption is incorrect | Correct to $0.10/2-page form; SIGNATURES bundled with FORMS pricing |
| ARCH-6 | 🟡 Medium | Architecture | Classifier tie-breaking prioritizes care_coordination over legal | Invert: legal and underwriting should win ties over care coordination |
| ARCH-7 | 🔵 Low | Architecture | Lambda memory/timeout not specified | Add configuration table: 512 MB/30s for rr-extract, 256 MB/10-15s for others |
| NET-1 | 🟠 High | Networking | VPC endpoint policies not specified | Add per-endpoint IAM-scoped policies for each Lambda role |
| NET-2 | 🟠 High | Networking | Fax-server-to-S3 ingestion path not secured | Require VPN/Direct Connect for on-prem fax; IP-restrict for cloud fax |
| NET-3 | 🟡 Medium | Networking | Lambda security group rules not specified | Restrict outbound to VPC endpoint SGs only; no 0.0.0.0/0 |
| NET-4 | 🟡 Medium | Networking | Textract VPC endpoint regional availability not verified | Add regional availability check to prerequisites |
| NET-5 | 🔵 Low | Networking | Lambda CloudWatch Logs permissions not scoped to specific log groups | Pre-create log groups; restrict IAM to named ARNs |

---

## Top Priorities for the Author

1. **Fix the HIPAA 45 CFR 164.508 completeness gap (SEC-1).** Missing elements (ii) and (iii) means the validation claims compliance with a rule it does not fully implement. This is the highest-risk finding in the recipe and the most likely to generate pushback from a covered entity's compliance team.

2. **Add Step Functions orchestration (ARCH-1).** Four chained Lambdas without an orchestrator is a reliability anti-pattern. A failed classification step that silently drops a patient access request can cause a Right of Access violation. This is a one-to-two hour code change with significant reliability payoff.

3. **Reduce PHI in SQS and SNS payloads (SEC-3, SEC-4).** Both are straightforward: replace PHI with document_key references. The downstream consumers already have DynamoDB access (they need to update status anyway). This is a 30-minute refactor with a meaningful PHI surface area reduction.

4. **Add Lambda DLQ and Textract retry logic (ARCH-3, ARCH-4).** No medical records pipeline should silently drop documents. These two items together take an afternoon and prevent the class of failure that causes HIPAA Right of Access timeline violations.

5. **Correct the Textract SIGNATURES pricing (ARCH-5).** Verify against the current pricing page and correct the calculation. Cost credibility affects trust in the whole recipe series.

---

*Review complete. 19 findings: 3 Critical, 7 High, 6 Medium, 3 Low. 4 praise items.*
