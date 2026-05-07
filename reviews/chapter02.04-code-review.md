# Code Review: Recipe 2.4 - Prior Authorization Letter Generation

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-07
**Files reviewed:**
- `chapter02.04-prior-auth-letter-generation.md` (pseudocode)
- `chapter02.04-python-example.md` (Python companion)

**Validation performed:**
- Python syntax and logical flow verified across all code blocks
- boto3 Bedrock Runtime `invoke_model` API parameters and response parsing confirmed (Anthropic messages API format)
- boto3 Bedrock Agent Runtime `retrieve` API parameters and response parsing confirmed
- boto3 S3 `put_object` and DynamoDB `put_item` / `update_item` usage verified
- DynamoDB Decimal usage checked for every numeric write
- S3 keys checked for leading slashes (none present)
- Seven-step pseudocode mapped 1:1 against Python functions

---

## Verdict: PASS

---

## Summary

The Python companion is a faithful, working translation of the seven-step pseudocode. All boto3 calls use correct method names, parameter structures, and response traversal. Decimal is used for the one float that reaches DynamoDB (`validation_rate`). S3 keys are clean (no leading slashes). The Anthropic messages body for `invoke_model` is correctly structured with `anthropic_version`, `system`, and `messages`. Both Bedrock endpoints (`bedrock-runtime` and `bedrock-agent-runtime`) are correctly distinguished, and the setup narrative explicitly calls out that distinction, which is genuinely useful for learners.

No ERROR findings. Zero WARNING findings. Five NOTE findings, all pedagogical polish items that don't affect correctness.

---

## Findings

### Finding 1: Model ID inconsistency between pseudocode and Python

- **Severity:** NOTE
- **File:** `chapter02.04-prior-auth-letter-generation.md` (lines 324, 389, 436, 567) vs `chapter02.04-python-example.md` (line ~82)
- **Description:** The main recipe pseudocode uses `model_id = "anthropic.claude-sonnet-4"` in four places, while the Python companion uses `MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"`. The Python comment acknowledges the gap with a `TODO: verify the exact model ID available in your region and account` and notes the cross-region inference profile pattern. Neither string is wrong in isolation (the pseudocode's "claude-sonnet-4" is an abstract identifier; the Python's 3.5 Sonnet v2 ID is a real, currently-available Bedrock model), but a reader comparing the two files side-by-side will notice the mismatch.
- **Suggestion:** Either align both files on the same illustrative ID, or add one sentence to the pseudocode explaining "actual Bedrock model IDs are versioned; see the Python companion for the specific ID used in a working example." No code change needed.

---

### Finding 2: `retrieve_patient_facts` signature differs from pseudocode

- **Severity:** NOTE
- **File:** `chapter02.04-python-example.md`, Step 3 (`retrieve_patient_facts` function signature)
- **Description:** The pseudocode signature is `retrieve_patient_facts(patient_id, criteria, diagnosis_code)` with an internal call to `HealthLake.SearchResources`. The Python signature is `retrieve_patient_facts(patient_id, criteria, patient_clinical_data)`, accepting the clinical data as an already-fetched dict. The Python docstring explains this choice: "This example takes it as a parameter so the PHI retrieval step isn't mixed with the AI pipeline demo." That's a reasonable pedagogical decision, but the `diagnosis_code` parameter from the pseudocode quietly disappears (it's not used in the pseudocode body either, so no information is lost).
- **Suggestion:** Acceptable as-is. The docstring already explains why HealthLake is swapped for a dict parameter. Optionally add one line: "The pseudocode's `diagnosis_code` parameter is omitted here because it wasn't used downstream in the fact extraction step."

---

### Finding 3: `_parse_json_response` helper defined inside Step 2's code block

- **Severity:** NOTE
- **File:** `chapter02.04-python-example.md`, end of Step 2 section
- **Description:** The helper `_parse_json_response(raw_text)` is defined at the bottom of the Step 2 code block and then used in Steps 2, 3, 4, and 6. A reader who copies code blocks in isolation (a common learner pattern when experimenting) will hit a `NameError` in later steps without noticing that the helper lives two sections earlier. This is pure layout, not correctness: if you run the whole file, it works fine.
- **Suggestion:** Either move the helper definition into a dedicated "Shared Helpers" section before Step 2, or add an inline comment at the helper's first use in Steps 3/4/6 like `# _parse_json_response defined in Step 2`.

---

### Finding 4: `stepfunctions_client` instantiated at module level but only referenced in commented-out code

- **Severity:** NOTE
- **File:** `chapter02.04-python-example.md`, Configuration section (line 68) and Step 1 (lines 188-192)
- **Description:** `stepfunctions_client = boto3.client("stepfunctions", config=BOTO3_RETRY_CONFIG)` is created at module load, but the only usage is inside a block of commented-out code illustrating how Step Functions would be invoked in production. A reader running a linter will see an unused-variable warning. More importantly, a learner may wonder "why is this client here if nothing calls it?"
- **Suggestion:** Either move the client instantiation into the commented-out block so it lives alongside its usage, or add a brief comment next to the client: `# Reserved for the Step Functions integration shown commented-out in Step 1.`

---

### Finding 5: `import time` inside function body instead of at module top

- **Severity:** NOTE
- **File:** `chapter02.04-python-example.md`, `process_pa_request` function (line 1034)
- **Description:** `import time` appears on the first line of `process_pa_request`'s body rather than with the other imports at module top. This is valid Python but unusual style and may confuse a reader learning idiomatic layout. The rest of the file groups all imports at the top.
- **Suggestion:** Move `import time` up to the imports block at the top of the file. One-line change.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function | Consistent? |
|----------------|---------------------|-----------------|-------------|
| Step 1 | `receive_pa_request(request)` | `receive_pa_request(request: dict) -> str` | Yes |
| Step 2 | `retrieve_and_extract_criteria(payer_id, service_code, diagnosis_code)` | `retrieve_and_extract_criteria(payer_id, service_code, diagnosis_code)` | Yes |
| Step 3 | `retrieve_patient_facts(patient_id, criteria, diagnosis_code)` | `retrieve_patient_facts(patient_id, criteria, patient_clinical_data)` | Yes (documented signature change; see Finding 2) |
| Step 4 | `map_facts_to_criteria(criteria, facts)` | `map_facts_to_criteria(criteria, facts_by_criterion)` | Yes |
| Step 5 | `retrieve_supporting_evidence(diagnosis_code, service_code, key_facts)` | `retrieve_supporting_evidence(diagnosis_code, service_description, mappings)` | Yes (uses `mappings` to derive distinctive clinical features instead of raw `key_facts`; same intent) |
| Step 6 | `generate_letter(case, mappings, citations, patient_info, provider_info, payer_info)` | `generate_letter(case, mappings, citations, patient_info, provider_info, payer_info)` | Yes |
| Step 7 | `validate_letter(letter, provenance, inputs)` | `validate_letter(case_id, letter_result, mappings, citations)` | Yes (Python bundles letter+provenance into `letter_result` and passes `case_id` directly for the DynamoDB update; same logic) |

The `process_pa_request` orchestrator in the Python companion correctly chains all seven steps with proper data flow. The early-exit branches (no policy found, blocking gaps detected) are implemented in both files.

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

- `modelId`, `contentType`, `accept`, `body` parameter names: correct
- Anthropic body schema (`anthropic_version`, `max_tokens`, `temperature`, `system`, `messages`): correct for Claude on Bedrock
- Message role `"user"` and content as string: correct (single-turn text input)
- Response parsing `json.loads(response["body"].read())` and `response_body["content"][0]["text"]`: matches the documented Anthropic response structure on Bedrock

All four `invoke_model` call sites (Steps 2, 3, 4, 6) use the same correct pattern.

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

- `knowledgeBaseId`, `retrievalQuery`, `retrievalConfiguration`: correct parameter names
- `retrievalQuery.text` structure: correct
- `vectorSearchConfiguration.numberOfResults`: correct
- Response traversal (`response.get("retrievalResults", [])`, each result's `.content.text`, `.metadata`, `.score`): matches documented structure

The comment about `bedrock-runtime` vs `bedrock-agent-runtime` being separate service endpoints that each need their own VPC endpoint is a genuinely useful gotcha for learners.

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
- `Body` is bytes (encoded UTF-8): correct
- `default=str` in `json.dumps` handles `datetime` objects: correct defensive choice
- Encryption is left to the bucket default with a comment pointing to SSE-KMS CMK for production: acceptable teaching pattern

### DynamoDB

- `cases_table.put_item(Item=case_record)` in Step 1: all string/bool values, no Decimal concerns
- `cases_table.update_item(...)` in Step 7: `validation_rate` correctly wrapped as `Decimal(str(round(validation_rate, 4)))`. Other values are strings or lists of string-typed dicts.
- `cases_table.update_item(...)` in `process_pa_request` BLOCKED branch: writes `blocking_gaps` (list of dicts with string-typed fields). No floats.
- `ExpressionAttributeNames={"#status": "status"}` correctly handles the DynamoDB reserved word `status`.

### S3 Keys

- `f"letter-drafts/{case['case_id']}/draft-{uuid.uuid4().hex[:8]}.json"`: no leading slash, no colons, no reserved characters. Good.

---

## DynamoDB Decimal Check

- `validation_rate` (a float computed as `verified_claims / total_claims`) is the only numeric value written to DynamoDB, and it is wrapped: `Decimal(str(round(validation_rate, 4)))`. Correct pattern.
- `Decimal` is imported at module top: `from decimal import Decimal`. Used.
- No raw `float` values reach DynamoDB. No instances of `Decimal(float_value)` (which would be wrong). Pass.

---

## Comment Quality

Comments are consistently strong and explain the "why" rather than just the "what". High-value examples:

- The two-endpoint explanation (`bedrock-runtime` vs `bedrock-agent-runtime`) with the VPC endpoint gotcha
- The rationale for adaptive retry mode ("practices tend to process prior auths in waves")
- Why one-call-per-criterion in Step 3 instead of batching ("gives clean audit trails... prevents the model from getting confused when criteria have overlapping evidence requirements")
- Why `MIN_VALIDATION_RATE_FOR_REVIEW = 1.0` ("A letter with fabricated facts is worse than no letter at all")
- The temperature choices with clinical reasoning (0.0 for deterministic extraction, 0.1 for assessment with clinical judgment, 0.2 for prose generation with natural variation)
- The minimum-necessary PHI note in the "Gap to Production" section
- The cross-region inference profile hint with the `us.` prefix

The `_parse_json_response` helper is accompanied by an accurate comment noting that Claude sometimes wraps JSON in code fences "even when instructed not to" - a real gotcha that a learner will eventually hit.

---

## Healthcare-Specific Requirements

- **PHI logging warning:** Present in the logger comment ("Never log PHI: no patient names, no member IDs, no clinical note text, no generated letter bodies"). Pass.
- **Encryption guidance:** SSE-KMS with customer-managed keys is noted in both the S3 write comment and the configuration block. Pass.
- **BAA/HIPAA context:** Setup section explicitly mentions Bedrock under BAA for PHI in letter content. Pass.
- **Synthetic data:** Sample data at the bottom is explicitly labeled "All data below is SYNTHETIC. Do not use real patient data in development." Pass.
- **Audit retention:** Step 6 comment explicitly notes "HIPAA retention is typically 6 years minimum, sometimes longer depending on state law and payer contract." Pass.
- **Provider attestation:** The "Gap to Production" section correctly frames physician sign-off as load-bearing for legal and clinical reasons. Pass.
- **Hallucination mitigation:** Grounding is enforced at three separate layers (prompt constraints, provenance tracking, post-generation validation). The validate_letter function is a real defense, not theater. Pass.

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
10. Orchestrator (`process_pa_request`) that chains all seven
11. Synthetic example at `__main__`

The orchestrator correctly short-circuits on "no policy found" and "blocking gaps" outcomes rather than proceeding to generate a letter that will fail. That mirrors the pseudocode's gating logic and teaches a sound architectural pattern (don't generate letters you know will be denied).

The ordering reinforces the narrative structure of the main recipe: retrieval first, extraction second, mapping third, generation last, validation as the final safety net. A reader working through the Python alongside the prose will see the concepts line up.

---

## What Is Clean

- `invoke_model` body uses the Anthropic messages format correctly across all four call sites with consistent structure
- System prompts are multi-line strings with explicit JSON schemas (rather than vague "return JSON"), which is the right way to pattern-match Claude's behavior
- `retrieve` calls correctly separate the query text from the vector search configuration
- The fact_id / criterion_id / citation_id scheme gives the validation step something concrete to check against, turning hallucination detection into a simple set-membership test
- The `_parse_json_response` helper strips both ` ```json ` and plain ` ``` ` fences from either end - a small, practical touch
- The orchestrator's early-exit paths update DynamoDB with meaningful statuses (`BLOCKED_INSUFFICIENT_EVIDENCE`, `NO_POLICY_FOUND`) rather than throwing away the case record
- Synthetic sample data uses realistic clinical values (DAS28 5.8, QuantiFERON negative, methotrexate 25mg weekly) that match the main recipe's narrative, so a reader can trace the example end-to-end
- The "Gap to Production" section at the bottom is substantial and honest about where the real engineering lives (policy ingestion, EHR integration, physician UI)

---

## Closing Assessment

This is publication-ready code review material. No ERRORs (the code will run given the stated prerequisites). No WARNINGs (nothing teaches a bad habit a reader might carry into production). Five NOTE findings, all pedagogical polish items that the editor can address in one pass without changing behavior.

The pseudocode and Python are tightly aligned in structure and intent. The healthcare-specific concerns (PHI minimization, hallucination mitigation, audit trails, provider attestation) are handled both in the code comments and in the "Gap to Production" narrative. Comment quality is uniformly high, with clinical and operational reasoning surfaced alongside the technical choices.
