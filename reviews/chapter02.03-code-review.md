# Code Review: Recipe 2.3 - Clinical Documentation Improvement (CDI) Suggestions

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-11
**Files reviewed:**
- `chapter02.03-clinical-documentation-improvement.md` (main recipe, pseudocode)
- `chapter02.03-python-example.md` (Python companion)

**Validation performed:**
- Python syntax reviewed across all code blocks
- boto3 `bedrock-runtime.invoke_model` signature and Claude 3 Messages API request/response structure verified
- boto3 `bedrock-agent-runtime.retrieve` signature and Knowledge Base response structure verified
- boto3 S3 `put_object` and DynamoDB resource `put_item` parameters verified
- DynamoDB Decimal/float check performed
- S3 key pattern check performed (no leading slashes)
- Pseudocode-to-Python step mapping confirmed

---

## Verdict: PASS

---

## Summary

The Python companion is well-structured, pedagogically sound, and technically correct. All six pseudocode steps map cleanly to Python functions. The Bedrock Messages API request body and response traversal are correct for current Claude 3 models on Bedrock. The Bedrock Agent Runtime `retrieve` call uses correct nested parameter structure. S3 keys avoid leading slashes. All DynamoDB item values are strings, so the float-to-DynamoDB gotcha is not triggered. Comments consistently explain the "why" rather than just the "what", and they carry real clinical-domain context (alert fatigue, physician trust, threshold tuning) that is the whole point of this recipe.

No ERROR findings. Four NOTE-level findings, no WARNINGs.

---

## Findings

### Finding 1: Unused `Decimal` import

- **Severity:** NOTE
- **File:** `chapter02.03-python-example.md`, Configuration and Constants section
- **What's going on:** `from decimal import Decimal` is imported but never referenced. The inline comment on the same line explicitly states it's there for when numeric confidence/impact scores are added to DynamoDB items later. Pedagogically this is actually useful because it plants the flag for where Decimal would go, and a reader learning DynamoDB will see that hint.
- **Recommendation:** Leave as-is. The comment carries the teaching value. A linter will flag it, but this is a cookbook example, not a shippable module. If anything, a follow-up comment noting "your linter will warn on this; the import is intentional" could pre-empt confusion.

---

### Finding 2: `MAX_SUGGESTIONS_PER_NOTE` differs between pseudocode (5) and Python (3)

- **Severity:** NOTE
- **File:** `chapter02.03-clinical-documentation-improvement.md` (pseudocode sets 5) vs `chapter02.03-python-example.md` Configuration section (sets 3)
- **What's going on:** The Python code deliberately diverges from the pseudocode and the divergence is explained in a parenthetical: "The main recipe's pseudocode uses 5 as the eventual target; we deliberately start lower here to model a conservative pilot configuration." This is exactly the kind of tuning knob the main recipe calls out ("Start with a high confidence threshold and low maximum suggestions per note"), so modeling it in the companion is valuable. A reader who skims might still miss the note, but the comment is present and clear.
- **Recommendation:** No change required. The explanation is already inline and matches the operational guidance in the "Honest Take" section of the main recipe.

---

### Finding 3: Colons in ISO timestamps embedded in S3 keys

- **Severity:** NOTE
- **File:** `chapter02.03-python-example.md`, `receive_note` and `store_and_notify` functions
- **What's going on:** Keys like `notes-inbox/{encounter_id}/{timestamp}-{note_type}.txt` and `cdi-audit/{encounter_id}/suppressed-{now.isoformat()}.json` will contain colons because `isoformat()` produces strings like `2026-05-06T09:30:00-04:00`. S3 accepts these fine, but a reader who tries to `aws s3 cp` the object to a Windows filesystem will need to rename (colons are illegal in Windows file paths). This is not a bug, just a footgun for anyone doing local debugging.
- **Recommendation:** Optional one-line comment, for example: `# Note: ISO timestamps contain colons, which are valid in S3 but illegal in Windows paths on download.` Not required.

---

### Finding 4: `import time` is scoped inside `analyze_note_for_cdi` rather than at module level

- **Severity:** NOTE
- **File:** `chapter02.03-python-example.md`, orchestrator section
- **What's going on:** `import time` lives inside the function body. Python allows this and it works correctly, but convention is to hoist imports to the top of the file. For a teaching example, this can subtly suggest that per-function imports are acceptable style, which is not a habit you want beginners forming.
- **Recommendation:** Move `import time` to the top-level imports alongside `datetime`, `uuid`, and the others. Low priority.

---

## Pseudocode-to-Python consistency

All six pseudocode steps are implemented. Function names match or map obviously. The one minor signature change is harmless and actually improves the code.

| Pseudocode step | Python function | Match |
|-----------------|-----------------|-------|
| `receive_note(note_content, metadata)` | `receive_note(note_content, metadata)` | Exact |
| `extract_clinical_elements(note_content)` | `extract_clinical_elements(note_content)` | Exact |
| `retrieve_guidelines(diagnoses)` | `retrieve_guidelines(diagnoses)` | Exact |
| `generate_cdi_suggestions(note, elements, guidelines)` | `generate_cdi_suggestions(note_content, clinical_elements, guidelines)` | Exact |
| `prioritize_suggestions(suggestions)` | `prioritize_suggestions(suggestions)` | Exact |
| `store_and_notify(encounter_id, suggestions, suppressed)` | `store_and_notify(encounter_id, prioritized, note_key)` | Minor: Python takes the combined prioritized dict and a `note_key` for audit linkage. Cleaner than juggling two lists, and pedagogically clearer. |

The `analyze_note_for_cdi` orchestrator correctly chains all six steps, including passing `note_key` through from Step 1 to Step 6 for S3 audit linkage.

---

## AWS SDK accuracy

### Bedrock Runtime `invoke_model` (Steps 2 and 4)

```python
bedrock_runtime.invoke_model(
    modelId=MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=request_body,   # JSON string
)
```

Verified correct: `modelId`, `contentType`, `accept`, and `body` are the correct parameter names. The body structure for Claude 3 models on Bedrock:

```json
{
  "anthropic_version": "bedrock-2023-05-31",
  "max_tokens": 4096,
  "temperature": 0.1,
  "system": "...",
  "messages": [{"role": "user", "content": "..."}]
}
```

This matches the Claude Messages API format that Bedrock accepts. Response traversal `response_body["content"][0]["text"]` is correct for Messages API responses. Temperature values (0.1 for extraction, 0.2 for generation) are reasonable and the comments justify them.

### Bedrock Agent Runtime `retrieve` (Step 3)

```python
bedrock_agent_runtime.retrieve(
    knowledgeBaseId=KNOWLEDGE_BASE_ID,
    retrievalQuery={"text": query_text},
    retrievalConfiguration={
        "vectorSearchConfiguration": {"numberOfResults": 5}
    },
)
```

Verified correct. Parameter names (`knowledgeBaseId`, `retrievalQuery`, `retrievalConfiguration`) are the correct camelCase per the boto3 service model. Nested `vectorSearchConfiguration.numberOfResults` is correct. Response parsing via `response.get("retrievalResults", [])` with each item's `content.text` and `score` matches the documented response structure.

### S3 `put_object`

Parameters used: `Bucket`, `Key`, `Body`, `ContentType`, `Metadata`. All correct. Keys use forward slashes as separators and do not start with `/`. The encoding to `utf-8` before upload is explicit and correct.

### DynamoDB resource `put_item`

Uses the resource-level Table interface with `put_item(Item=item)`. All values in the item dict are strings (UUIDs, string defaults from `.get(..., "")`, and `.isoformat()` timestamps). No floats leak into DynamoDB. The `Decimal` import is in place for when numeric scores are added. Pass.

---

## DynamoDB / Decimal check

- All confidence and impact values stored as strings (`"high"`, `"medium"`, `"low"`).
- All timestamps stored as ISO-format strings.
- `suggestion_id` is a UUID string.
- No `float` values in any DynamoDB write path.
- `Decimal` imported at module level for future use with a comment explaining intent.

Pass.

---

## S3 path check

Both S3 keys:
- `notes-inbox/{encounter_id}/{timestamp}-{note_type}.txt`
- `cdi-audit/{encounter_id}/suppressed-{now.isoformat()}.json`

No leading slashes. No double slashes. Pass. (See Finding 3 for the colon caveat on Windows downloads.)

---

## Misleading patterns check

- No hardcoded credentials. Clients use default credential chain.
- Placeholder constants (`KNOWLEDGE_BASE_ID`, `NOTES_BUCKET`, `SUGGESTIONS_TABLE`) are clearly marked "Replace with your..." comments.
- No silent exception swallowing. The code lets errors propagate, which is correct for a teaching example.
- The commented-out SNS publish example now includes the necessary `sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)` hint above the snippet, so a reader who uncomments the block sees what else they need.
- Adaptive retry config on all clients is the right default for Bedrock token-per-minute limits.
- Logging explicitly warns against logging PHI in the module header comment.
- Synthetic sample note is clearly labeled "NOT a real patient note. Never use real PHI in development."

No misleading patterns detected.

---

## Comment quality

Consistently excellent. Comments explain why, not just what:

- Temperature rationale (0.1 for factual extraction, 0.2 for natural query phrasing)
- Confidence threshold semantics and pilot-vs-steady-state tuning advice
- Why adaptive retry mode is the right choice for Bedrock
- Why JSON fence stripping is needed (LLMs sometimes wrap output in ```json)
- Why suppressed suggestions go to S3 (audit trail + threshold tuning data)
- Clinical-domain context on alert fatigue, physician trust, DRG impact
- Security guardrails (PHI in logs, bucket-level SSE-KMS, VPC endpoints in Gap to Production)

The ICD-10-CM codes used in example output (J18.9, J15.1, J15.6, I50.9, I50.23, J13) are accurate to the current code set. A reader can trust the examples.

---

## Logical flow

Top-to-bottom reads cleanly:

1. Setup and IAM prerequisites
2. Imports and module-level configuration
3. Model and knowledge base configuration
4. Threshold constants with tuning guidance
5. Storage configuration
6. Steps 1 through 6 in order, each with the pseudocode reference inline
7. Orchestrator (`analyze_note_for_cdi`)
8. Runnable `__main__` block with a synthetic note
9. Gap-to-production discussion (which is deliberately after the example to avoid cluttering the learning path)

A reader going through in order builds understanding incrementally. Each function is usable in isolation and the orchestrator shows how they compose.

---

## Healthcare-specific requirements

| Requirement | Addressed? | Where |
|-------------|------------|-------|
| PHI handling awareness | Yes | Module-level logger comment warns against logging PHI |
| Encryption at rest | Yes | Comment explains SSE-KMS at bucket level with fallback instructions |
| HIPAA BAA context | Yes | Main recipe prerequisites table and setup section |
| Synthetic data in examples | Yes | Sample note explicitly labeled as not real PHI |
| CDI compliance framing | Yes | Suggestions phrased as questions to physician, never assertions; compliance review of query templates called out in Gap to Production |
| Suggestion lifecycle tracking | Yes | DynamoDB with GENERATED/PRESENTED/ACCEPTED/REJECTED/EXPIRED states |
| Audit trail | Yes | Source notes stored in S3 before analysis; suppressed suggestions written to S3 for threshold tuning |
| ICD-10-CM accuracy | Yes | Example codes (J18.9, J15.1, I50.9, I50.23, J13) are valid current codes |

All good.

---

## What is clean

- The Claude 3 Messages API request/response pattern is textbook-correct for Bedrock `invoke_model`.
- Knowledge base retrieval uses the correct two-tier query structure (per-diagnosis queries plus a bulk query-template retrieval), which matches how production CDI systems stage their retrieval.
- Prioritization logic uses an impact-then-confidence sort with a cap, and it tracks suppression reasons for audit. This directly supports the threshold-tuning workflow described in the main recipe.
- The `store_and_notify` function writes per-suggestion DynamoDB items rather than a nested list on a single encounter item. This is the right access pattern for individual suggestion lifecycle updates and future GSI support.
- The Gap to Production section in the Python file is genuinely educational: it names specific production concerns (EHR integration complexity, knowledge base maintenance, hallucination detection, concurrent vs retrospective CDI, the two separate Bedrock service endpoints) that would bite a team trying to productize this code. This is exactly the right separation of concerns between teaching code and production-hardening guidance.

---

## Recommendations summary

| # | Severity | Action |
|---|----------|--------|
| 1 | NOTE | Leave unused `Decimal` import as-is; comment already explains intent |
| 2 | NOTE | No change needed; pseudocode-to-Python deviation on `MAX_SUGGESTIONS_PER_NOTE` is explained inline |
| 3 | NOTE | Optional one-line comment about colons in ISO timestamps and Windows paths |
| 4 | NOTE | Move `import time` out of the orchestrator to module-level imports |

No ERROR findings. No WARNING findings. Verdict stands: **PASS.**
