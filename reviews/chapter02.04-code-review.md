# Code Review: Recipe 2.4 - Prior Authorization Letter Generation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-10
**Files reviewed:**
- `chapter02.04-prior-auth-letter-generation.md` (main recipe, pseudocode)
- `chapter02.04-python-example.md` (Python companion)

**Validation performed:**
- Seven-step pseudocode mapped 1:1 against Python functions
- boto3 Bedrock Runtime `invoke_model` parameters and response parsing confirmed against the Anthropic messages API format on Bedrock
- boto3 Bedrock Agent Runtime `retrieve` parameters and response parsing confirmed
- boto3 S3 `put_object` and DynamoDB `put_item` / `update_item` usage verified
- DynamoDB Decimal usage checked for every numeric write (only `validation_rate` reaches DynamoDB as a number)
- S3 keys checked for leading slashes (none present)
- `status` reserved-word handling with `ExpressionAttributeNames` confirmed
- Healthcare-specific concerns (PHI logging, encryption, BAA, synthetic data labeling, retention, provider attestation, hallucination mitigation) reviewed
- Module-level imports and client instantiation verified

---

## Verdict: PASS

No ERROR findings. Zero WARNING findings. Four NOTE findings, all pedagogical polish.

---

## Summary

The Python companion is a faithful, correct translation of the seven-step pseudocode in the main recipe. All boto3 calls use correct method names, parameter structures, and response traversal for the current SDK. The one float that reaches DynamoDB (`validation_rate`) is wrapped as `Decimal(str(round(...)))`, which is the right pattern. S3 keys are clean and use short UUID suffixes. The Anthropic messages body for `invoke_model` is consistently structured with `anthropic_version`, `system`, and `messages` across all four call sites. Both Bedrock endpoints (`bedrock-runtime` for inference, `bedrock-agent-runtime` for KB retrieval) are correctly distinguished, and the setup narrative explicitly calls out the two-endpoint gotcha plus the matching VPC endpoint requirement.

Healthcare-specific concerns are handled well: synthetic data is explicitly labeled, PHI is kept out of logs, encryption and BAA are called out, and the validation step genuinely enforces claim-to-source traceability rather than serving as theater. The fact_id / criterion_id / citation_id provenance scheme turns hallucination detection into a simple set-membership test, which is both pedagogically clear and operationally sound.

---

## Findings

### Finding 1: `_parse_json_response` helper is defined at the end of Step 2

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, end of Step 2 code block
- **Description:** The helper is defined at the bottom of Step 2 and then used in Steps 2, 3, 4, and 6. Step 3 has an inline comment (`# _parse_json_response is the shared helper defined at the end of Step 2.`) that points to its location, which mitigates the confusion. If a learner copies only a later code block in isolation to experiment, they will still hit `NameError`. Running the whole file works fine; this is a layout issue, not a correctness issue.
- **Suggestion:** Acceptable as-is; the inline pointer in Step 3 is helpful. Optionally move the helper into a dedicated "Shared Helpers" section before Step 2 in a future revision.

---

### Finding 2: Model ID string differs between pseudocode and Python

- **Severity:** NOTE
- **Location:** `chapter02.04-prior-auth-letter-generation.md` pseudocode (uses `"anthropic.claude-sonnet-4"` in four places) vs `chapter02.04-python-example.md` Configuration section (uses `MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"`)
- **Description:** The pseudocode uses an illustrative model identifier; the Python uses a concrete, currently-available Bedrock model ID. The Python comment acknowledges the gap with a `TODO: verify the exact model ID available in your region and account` plus a hint about the cross-region inference profile (`us.` prefix). A reader comparing the two files side by side will still notice the mismatch.
- **Suggestion:** Acceptable as-is. Optionally add a one-line note in the pseudocode that Bedrock model IDs are versioned and the Python companion shows a specific working example.

---

### Finding 3: Pseudocode Step 2 mentions an S3 criteria cache that the Python skips

- **Severity:** NOTE
- **Location:** `chapter02.04-prior-auth-letter-generation.md` Step 2 pseudocode says: `write to S3: "policy-criteria-cache/{payer_id}/{service_code}/criteria.json" = criteria`. `chapter02.04-python-example.md` `retrieve_and_extract_criteria` does not perform this write.
- **Description:** The Python implementation omits the policy-criteria cache write. This is a sensible simplification for a teaching example (the cache would need a companion read-before-extract path to be useful, which would add complexity), but it does mean the two files diverge on what Step 2 persists. The docstring for the Python function does not call out this omission.
- **Suggestion:** Either add one line in the Python function docstring or an inline comment noting that production deployments typically cache extracted criteria in S3 keyed by payer+service version so re-extraction only happens when the policy changes. No code change required for correctness.

---

### Finding 4: `process_pa_request` uses `print()` for step progress instead of the module logger

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, `process_pa_request` function body
- **Description:** The orchestrator uses `print(f"Step N: ...")` for step progress while every other function in the file uses `logger.info(...)`. Using `print` is a reasonable pedagogical choice for a top-level demo (it's easier for a reader running the script to see the flow), but it creates an inconsistency that a learner may carry into production code where `print` statements pollute CloudWatch and bypass structured logging.
- **Suggestion:** Optionally add a one-line comment above the first `print` explaining the choice, e.g. `# Using print() here for visibility when running the __main__ demo; production code would use logger.info().` No behavior change required.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function | Consistent? |
|----------------|---------------------|-----------------|-------------|
| Step 1 | `receive_pa_request(request)` | `receive_pa_request(request: dict) -> str` | Yes |
| Step 2 | `retrieve_and_extract_criteria(payer_id, service_code, diagnosis_code)` | Same | Yes (S3 cache write omitted; see Finding 3) |
| Step 3 | `retrieve_patient_facts(patient_id, criteria, diagnosis_code)` | `retrieve_patient_facts(patient_id, criteria, patient_clinical_data)` | Yes (signature accepts pre-fetched data dict in place of in-function HealthLake call; docstring explains) |
| Step 4 | `map_facts_to_criteria(criteria, facts)` | `map_facts_to_criteria(criteria, facts_by_criterion)` | Yes |
| Step 5 | `retrieve_supporting_evidence(diagnosis_code, service_code, key_facts)` | `retrieve_supporting_evidence(diagnosis_code, service_description, mappings)` | Yes (derives distinctive features from mappings; same intent) |
| Step 6 | `generate_letter(case, mappings, citations, ...)` | Same shape | Yes |
| Step 7 | `validate_letter(letter, provenance, inputs)` | `validate_letter(case_id, letter_result, mappings, citations)` | Yes (Python bundles letter+provenance into `letter_result`; same logic) |

The `process_pa_request` orchestrator chains the seven steps and implements the pseudocode's early-exit logic: short-circuit on `NO_POLICY_FOUND` and `BLOCKED_INSUFFICIENT_EVIDENCE` rather than generating letters destined to fail. Both exit paths write meaningful status updates to DynamoDB, not just drop the case. That teaches the right architectural pattern: don't generate letters you know will be denied.

The pseudocode's Step 7 mentions `send notification to provider_review_queue` on success; the Python omits this and leaves it to the orchestration layer. Acceptable simplification for a teaching example.

---

## AWS SDK Accuracy

### Bedrock Runtime `invoke_model` (Anthropic messages format)

```python
bedrock_runtime.invoke_model(
    modelId=MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "temperature": 0.0,
        "system": extraction_system,
        "messages": [{"role": "user", "content": user_message}],
    }),
)
```

- Parameter names (`modelId`, `contentType`, `accept`, `body`): correct
- Anthropic body schema (`anthropic_version`, `max_tokens`, `temperature`, `system`, `messages`): correct for Claude on Bedrock
- Message role `"user"` with string content: correct for single-turn text input
- Response parsing `json.loads(response["body"].read())` then `response_body["content"][0]["text"]`: matches the documented Anthropic response structure on Bedrock

All four `invoke_model` call sites (Steps 2, 3, 4, 6) use the same consistent, correct pattern. Temperatures are well-chosen with clinical reasoning attached in comments: 0.0 for deterministic extraction, 0.1 for assessment that needs mild judgment, 0.2 for prose generation with natural variation.

### Bedrock Agent Runtime `retrieve`

```python
bedrock_agent_runtime.retrieve(
    knowledgeBaseId=PAYER_POLICIES_KB_ID,
    retrievalQuery={"text": query_text},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": MAX_POLICY_CHUNKS,
        }
    },
)
```

- Parameter names: correct (`knowledgeBaseId`, `retrievalQuery`, `retrievalConfiguration`)
- `retrievalQuery.text` structure: correct
- `vectorSearchConfiguration.numberOfResults`: correct
- Response traversal (`response.get("retrievalResults", [])`, per-result `.content.text`, `.metadata`, `.score`): matches documented structure

The comment about `bedrock-runtime` vs `bedrock-agent-runtime` being separate service endpoints (each needing its own VPC endpoint) is a genuinely valuable gotcha for learners doing production network design.

### S3 `put_object`

```python
s3_client.put_object(
    Bucket=PA_BUCKET,
    Key=draft_key,
    Body=json.dumps(draft_payload, indent=2, default=str).encode("utf-8"),
    ContentType="application/json",
)
```

- Parameter names: correct
- `Body` is bytes (UTF-8 encoded): correct
- `default=str` in `json.dumps` safely handles `datetime` objects embedded in nested inputs: correct defensive choice
- Bucket-default SSE-KMS encryption assumption with an inline comment pointing to SSE-KMS CMK overrides for production: acceptable teaching pattern
- S3 key `f"letter-drafts/{case['case_id']}/draft-{uuid.uuid4().hex[:8]}.json"` has no leading slash, no colons, no reserved characters

### DynamoDB

- `cases_table.put_item(Item=case_record)` in Step 1: all string/bool values, no Decimal concerns
- `cases_table.update_item(...)` in Step 7: `validation_rate` wrapped as `Decimal(str(round(validation_rate, 4)))`. All other values are strings or lists of string-typed dicts.
- `cases_table.update_item(...)` in `process_pa_request` BLOCKED branch: writes `blocking_gaps` (list of mapping dicts with string/bool fields only). No floats.
- `ExpressionAttributeNames={"#status": "status"}` correctly escapes the DynamoDB reserved word `status` in all relevant update calls.
- `letter_ready_at` is set unconditionally in Step 7 whether the status lands on `APPROVED_FOR_REVIEW` or `REQUIRES_REGENERATION`. The pseudocode prose says "current UTC timestamp if status == APPROVED_FOR_REVIEW" but the column semantically represents "when letter generation completed", so writing it on both paths is defensible. Not flagging as a finding because the attribute name still reads naturally in either state.

---

## DynamoDB Decimal Check

- `validation_rate` (a float computed from `verified_claims / total_claims`) is the only numeric value written to DynamoDB, and it is wrapped: `Decimal(str(round(validation_rate, 4)))`. This is the correct pattern (string-through-Decimal to preserve precision).
- `Decimal` is imported at module top: `from decimal import Decimal`. Used.
- No raw `float` reaches DynamoDB. No instances of `Decimal(float_value)` (which would be wrong because it captures IEEE 754 imprecision).

Pass.

---

## S3 Key Check

- `f"letter-drafts/{case['case_id']}/draft-{uuid.uuid4().hex[:8]}.json"`: no leading slash, safe character set, collision-resistant short UUID tail.
- Three logical destinations are named in the Configuration narrative (drafts, signed archives, audit). Only the drafts bucket is used in code; the others are described in comments for production extension. Acceptable for a teaching example.

Pass.

---

## Module-Level Imports and Clients

- `import time` is at module top (line 39) alongside the rest of the standard-library imports.
- `Decimal` is imported at module top and actually used.
- All five boto3 clients (`bedrock_runtime`, `bedrock_agent_runtime`, `s3_client`, `dynamodb`, `stepfunctions_client`) are instantiated at module load with shared adaptive-retry config.
- `stepfunctions_client` has an inline comment above its instantiation (`# Reserved for the Step Functions orchestration shown commented-out in Step 1.`) that explains why the client exists even though the only usage in the code is commented out. Good save.

Pass.

---

## Comment Quality

Comments consistently explain the "why," not just the "what." High-value examples:

- Two-endpoint explanation (`bedrock-runtime` vs `bedrock-agent-runtime`) with the VPC endpoint gotcha
- Rationale for adaptive retry mode ("practices tend to process prior auths in waves")
- One-call-per-criterion in Step 3 instead of batching ("gives clean audit trails... prevents the model from getting confused when criteria have overlapping evidence requirements")
- `MIN_VALIDATION_RATE_FOR_REVIEW = 1.0` reasoning ("A letter with fabricated facts is worse than no letter at all")
- Temperature choices with clinical justification (0.0 deterministic extraction, 0.1 assessment with judgment, 0.2 prose with natural variation)
- Minimum-necessary PHI discussion in the "Gap to Production" section
- Cross-region inference profile hint with the `us.` prefix
- Deliberate choice to gate letter generation on `ready_to_draft` so the system doesn't produce letters destined to be denied

The `_parse_json_response` helper has an accurate comment about Claude occasionally wrapping JSON in code fences "even when instructed not to." That is a real behavior a learner will eventually hit; naming it preemptively is useful.

---

## Healthcare-Specific Requirements

- **PHI logging:** Logger setup comment explicitly says "Never log PHI: no patient names, no member IDs, no clinical note text, no generated letter bodies." Log statements in the code use identifiers only (case_id, payer_id, service_code, provider_id) and counts, never patient names or note text. Pass.
- **Encryption:** SSE-KMS with customer-managed keys referenced in both the S3 write comment and the Configuration narrative. CMK is flagged for DynamoDB in the Gap section. Pass.
- **BAA / HIPAA context:** Setup section notes Bedrock under BAA for PHI in letter content. Pass.
- **Synthetic data:** Sample inputs explicitly labeled "All data below is SYNTHETIC. Do not use real patient data in development." Pass.
- **Retention:** Step 6 comment notes "HIPAA retention is typically 6 years minimum, sometimes longer depending on state law and payer contract." Pass.
- **Provider attestation:** "Gap to Production" correctly frames physician sign-off as load-bearing for legal and clinical reasons. Pass.
- **Hallucination mitigation:** Three layers: prompt constraints, provenance tracking (fact_id, criterion_id, citation_id), post-generation validation. The `validate_letter` function is real defense, not cosmetic. Pass.
- **Minimum necessary:** "Gap to Production" explicitly names the minimum-necessary principle and suggests a redaction-then-restore pattern for PHI in prompts. Pass.

---

## Logical Flow

The code reads cleanly top-to-bottom:

1. Imports and module-level clients
2. Configuration constants with explanatory comments (model ID, KB IDs, bucket, table, tuning knobs)
3. Step 1: intake and case initialization
4. Step 2: policy retrieval and criteria extraction (with `_parse_json_response` helper defined at the end of the block)
5. Step 3: patient fact extraction per criterion, with a comment pointing back at the helper's definition
6. Step 4: fact-to-criteria mapping with readiness gating
7. Step 5: supporting evidence retrieval with citation metadata validation
8. Step 6: letter generation with provenance tracking and S3 draft archive
9. Step 7: claims validation against sources and DynamoDB state update
10. Orchestrator chaining all seven with early-exit handling
11. Synthetic `__main__` example with realistic RA biologic scenario

The orchestrator's early-exit paths update DynamoDB with meaningful statuses (`BLOCKED_INSUFFICIENT_EVIDENCE`, `NO_POLICY_FOUND`) rather than discarding the case record. That's the right operational behavior.

---

## What Is Clean

- `invoke_model` body uses the Anthropic messages format consistently across all four call sites
- System prompts are multi-line strings with explicit JSON schemas rather than vague "return JSON" instructions, which is the right way to shape Claude's behavior
- `retrieve` calls correctly separate the query text from the vector search configuration
- The fact_id / criterion_id / citation_id scheme turns hallucination detection into a simple set-membership test
- `_parse_json_response` strips both ` ```json ` and plain ` ``` ` fences from either end (a small, practical touch)
- Step 5 filters retrieval results that lack citation metadata rather than inventing bibliographic info, which matches the architectural rule "every citation comes from retrieval, never from training data"
- Orchestrator early-exit paths update DynamoDB with meaningful statuses
- Synthetic sample data uses realistic clinical values (DAS28 5.8, QuantiFERON negative, methotrexate 25mg weekly) matching the main recipe narrative, so a reader can trace the example end to end
- The "Gap to Production" section is substantial and honest about where the real engineering lives (policy ingestion, EHR integration, physician UI, denial rate measurement)
- The paraphrase-drift check in `validate_letter` uses a simple substring heuristic and is honest about its limits, pointing to semantic similarity as the stronger approach in the Gap section

---

## Closing Assessment

This is publication-ready teaching code. The code will run given the stated prerequisites (IAM, KB IDs, bucket, table, model access). Nothing teaches a habit a reader should avoid. The four NOTE findings are pedagogical polish items an editor can address in a single pass without changing behavior, and none of them rise to the level of blocking publication.

Pseudocode and Python are tightly aligned in structure and intent. Healthcare-specific concerns are handled both in code and in narrative. Comment quality is uniformly high, with clinical and operational reasoning surfaced alongside the technical choices.
