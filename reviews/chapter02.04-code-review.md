# Code Review: Recipe 2.4 - Prior Authorization Letter Generation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-07
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

---

## Verdict: PASS

No ERROR findings. Zero WARNING findings. Five NOTE findings, all pedagogical polish.

---

## Summary

The Python companion is a faithful translation of the seven-step pseudocode in the main recipe. All boto3 calls use correct method names, parameter structures, and response traversal for the current SDK. `Decimal(str(round(...)))` is used for the one float that reaches DynamoDB. S3 keys are clean. The Anthropic messages body for `invoke_model` is correctly structured with `anthropic_version`, `system`, and `messages`. Both Bedrock endpoints (`bedrock-runtime` for inference, `bedrock-agent-runtime` for KB retrieval) are correctly distinguished, and the setup narrative explicitly calls out that distinction, which is a real gotcha worth teaching.

Healthcare-specific concerns are handled well: synthetic data is explicitly labeled, PHI is kept out of logs, encryption and BAA are called out, and the validation step genuinely enforces claim-to-source traceability rather than serving as theater.

---

## Findings

### Finding 1: Model ID string differs between pseudocode and Python

- **Severity:** NOTE
- **Location:** `chapter02.04-prior-auth-letter-generation.md` pseudocode (uses `"anthropic.claude-sonnet-4"` in four places) vs `chapter02.04-python-example.md` Configuration section (uses `MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"`)
- **Description:** The pseudocode uses an illustrative model identifier; the Python uses a concrete, currently-available Bedrock model ID. Neither is wrong in isolation, and the Python comment acknowledges the gap with a `TODO: verify the exact model ID available in your region and account` plus a hint about the cross-region inference profile (`us.` prefix). A reader comparing the two files side by side will still notice the mismatch.
- **Suggestion:** Optionally add a one-line note in the pseudocode that Bedrock model IDs are versioned and the Python companion shows a specific working example. No code change required.

---

### Finding 2: `retrieve_patient_facts` signature differs from the pseudocode

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, Step 3 function signature
- **Description:** Pseudocode signature is `retrieve_patient_facts(patient_id, criteria, diagnosis_code)` with an internal `HealthLake.SearchResources` call. The Python signature is `retrieve_patient_facts(patient_id, criteria, patient_clinical_data)`, accepting the clinical data as an already-fetched dict. The docstring explains this is intentional ("so the PHI retrieval step isn't mixed with the AI pipeline demo"). The pseudocode's `diagnosis_code` parameter is not used in the pseudocode body, so no logic is lost.
- **Suggestion:** Acceptable as-is. The docstring already explains why HealthLake is replaced by a dict parameter. Optionally note that `diagnosis_code` was omitted because it was unused downstream.

---

### Finding 3: `_parse_json_response` helper is defined inside Step 2

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, end of Step 2 code block
- **Description:** The helper is defined at the bottom of Step 2 and then used in Steps 2, 3, 4, and 6. If a learner copies only a later code block in isolation to experiment, they will hit `NameError`. Running the whole file works fine. This is a layout issue, not a correctness issue.
- **Suggestion:** Either move the helper into a dedicated "Shared Helpers" section before Step 2, or add an inline comment where it's first used in Steps 3/4/6 (e.g., `# _parse_json_response defined in Step 2`).

---

### Finding 4: `stepfunctions_client` is created but only referenced in commented-out code

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, Configuration section (module-level client) and Step 1 (commented-out `start_execution` block)
- **Description:** `stepfunctions_client = boto3.client("stepfunctions", ...)` is instantiated at module load but the only reference is in a block of commented-out production code showing how Step Functions would be invoked. Linters will flag it as unused, and a learner may wonder why the client exists.
- **Suggestion:** Either move the client instantiation inside the commented-out block, or add a short comment next to the client: `# Reserved for the Step Functions integration shown commented-out in Step 1.`

---

### Finding 5: `import time` appears inside a function body

- **Severity:** NOTE
- **Location:** `chapter02.04-python-example.md`, `process_pa_request` function body (first line)
- **Description:** `import time` is on the first line of `process_pa_request` instead of at the module-top imports block, where the other imports live. This is valid Python but unusual style and may confuse a learner studying idiomatic layout.
- **Suggestion:** Move `import time` to the module imports block. One-line change.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function | Consistent? |
|----------------|---------------------|-----------------|-------------|
| Step 1 | `receive_pa_request(request)` | `receive_pa_request(request: dict) -> str` | Yes |
| Step 2 | `retrieve_and_extract_criteria(payer_id, service_code, diagnosis_code)` | Same | Yes |
| Step 3 | `retrieve_patient_facts(patient_id, criteria, diagnosis_code)` | `retrieve_patient_facts(patient_id, criteria, patient_clinical_data)` | Yes (signature change documented; see Finding 2) |
| Step 4 | `map_facts_to_criteria(criteria, facts)` | `map_facts_to_criteria(criteria, facts_by_criterion)` | Yes |
| Step 5 | `retrieve_supporting_evidence(diagnosis_code, service_code, key_facts)` | `retrieve_supporting_evidence(diagnosis_code, service_description, mappings)` | Yes (derives distinctive features from mappings; same intent) |
| Step 6 | `generate_letter(case, mappings, citations, ...)` | Same shape | Yes |
| Step 7 | `validate_letter(letter, provenance, inputs)` | `validate_letter(case_id, letter_result, mappings, citations)` | Yes (Python bundles letter+provenance into `letter_result`; same logic) |

The `process_pa_request` orchestrator chains the seven steps correctly and implements the pseudocode's early-exit logic: short-circuit on `NO_POLICY_FOUND` and `BLOCKED_INSUFFICIENT_EVIDENCE` rather than generating letters destined to fail. That mirrors the pseudocode's gating behavior and teaches a sound architectural pattern.

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
- Response parsing `json.loads(response["body"].read())` then `response_body["content"][0]["text"]`: matches documented Anthropic response structure on Bedrock

All four `invoke_model` call sites (Steps 2, 3, 4, 6) use the same consistent, correct pattern. Temperatures are well-chosen with clinical reasoning attached in comments: 0.0 for deterministic extraction, 0.1 for assessment, 0.2 for prose generation.

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
- `default=str` in `json.dumps` safely handles `datetime` objects: correct defensive choice
- Bucket-default encryption assumption with a pointer to SSE-KMS CMK for production: acceptable teaching pattern

### DynamoDB

- `cases_table.put_item(Item=case_record)` in Step 1: all string/bool values, no Decimal concerns
- `cases_table.update_item(...)` in Step 7: `validation_rate` wrapped as `Decimal(str(round(validation_rate, 4)))`. All other values are strings or lists of string-typed dicts.
- `cases_table.update_item(...)` in `process_pa_request` BLOCKED branch: writes `blocking_gaps` (list of dicts with string fields). No floats.
- `ExpressionAttributeNames={"#status": "status"}` correctly escapes the DynamoDB reserved word `status`.

### S3 Keys

`f"letter-drafts/{case['case_id']}/draft-{uuid.uuid4().hex[:8]}.json"` has no leading slash, no colons, no reserved characters. Good.

---

## DynamoDB Decimal Check

- `validation_rate` (a float from `verified_claims / total_claims`) is the only numeric value written to DynamoDB, and it is wrapped: `Decimal(str(round(validation_rate, 4)))`. This is the correct pattern (string-through-Decimal to preserve precision).
- `Decimal` is imported at module top: `from decimal import Decimal`. Used.
- No raw `float` reaches DynamoDB. No instances of `Decimal(float_value)` (which would be wrong because it captures IEEE 754 imprecision).

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

The `_parse_json_response` helper has an accurate comment about Claude occasionally wrapping JSON in code fences "even when instructed not to." That is a real behavior a learner will eventually hit; naming it preemptively is useful.

---

## Healthcare-Specific Requirements

- **PHI logging:** Logger comment explicitly says "Never log PHI: no patient names, no member IDs, no clinical note text, no generated letter bodies." Pass.
- **Encryption:** SSE-KMS with customer-managed keys referenced in both the S3 write comment and the Configuration narrative. Pass.
- **BAA / HIPAA context:** Setup section notes Bedrock under BAA for PHI in letter content. Pass.
- **Synthetic data:** Sample inputs explicitly labeled "All data below is SYNTHETIC. Do not use real patient data in development." Pass.
- **Retention:** Step 6 comment notes "HIPAA retention is typically 6 years minimum, sometimes longer depending on state law and payer contract." Pass.
- **Provider attestation:** "Gap to Production" correctly frames physician sign-off as load-bearing for legal and clinical reasons. Pass.
- **Hallucination mitigation:** Three layers: prompt constraints, provenance tracking (fact_id, criterion_id, citation_id), post-generation validation. The `validate_letter` function is real defense, not cosmetic. Pass.

---

## Logical Flow

The code reads cleanly top-to-bottom:

1. Imports and module-level clients
2. Configuration constants with explanatory comments
3. Step 1: intake and case initialization
4. Step 2: policy retrieval and criteria extraction (with `_parse_json_response` helper)
5. Step 3: patient fact extraction per criterion
6. Step 4: fact-to-criteria mapping with readiness gating
7. Step 5: supporting evidence retrieval
8. Step 6: letter generation with provenance tracking
9. Step 7: claims validation against sources
10. Orchestrator chaining all seven
11. Synthetic `__main__` example

The orchestrator short-circuits on "no policy" and "blocking gaps" rather than proceeding to generate letters that will fail. That mirrors the pseudocode's gating and teaches a sound architectural pattern: don't generate letters you know will be denied.

---

## What Is Clean

- `invoke_model` body uses the Anthropic messages format consistently across all four call sites
- System prompts are multi-line strings with explicit JSON schemas rather than vague "return JSON" instructions, which is the right way to shape Claude's behavior
- `retrieve` calls correctly separate the query text from the vector search configuration
- The fact_id / criterion_id / citation_id scheme turns hallucination detection into a simple set-membership test
- `_parse_json_response` strips both ` ```json ` and plain ` ``` ` fences from either end (a small, practical touch)
- Orchestrator early-exit paths update DynamoDB with meaningful statuses (`BLOCKED_INSUFFICIENT_EVIDENCE`, `NO_POLICY_FOUND`) rather than discarding the case record
- Synthetic sample data uses realistic clinical values (DAS28 5.8, QuantiFERON negative, methotrexate 25mg weekly) matching the main recipe narrative, so a reader can trace the example end to end
- The "Gap to Production" section is substantial and honest about where the real engineering lives (policy ingestion, EHR integration, physician UI)

---

## Closing Assessment

This is publication-ready teaching code. The code will run given the stated prerequisites (IAM, KB IDs, bucket, table). Nothing teaches a habit a reader should avoid. The five NOTE findings are pedagogical polish items an editor can address in a single pass without changing behavior.

Pseudocode and Python are tightly aligned in structure and intent. Healthcare-specific concerns are handled in code and in narrative. Comment quality is uniformly high, with clinical and operational reasoning surfaced alongside the technical choices.
