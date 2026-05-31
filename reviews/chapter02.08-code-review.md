# Code Review: Recipe 2.8 - Ambient Clinical Documentation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-31
**Files reviewed:**
- `chapter02.08-ambient-clinical-documentation.md` (main recipe, pseudocode)
- `chapter02.08-python-example.md` (Python companion)

**Validation performed:**
- Ten-step pseudocode walked against Python functions, one-to-one
- boto3 Transcribe `start_medical_scribe_job` and `get_medical_scribe_job` method names and parameter shapes verified against current SDK
- boto3 Bedrock Runtime `invoke_model` parameters, Anthropic Messages API body shape, and response traversal verified
- boto3 Comprehend Medical `detect_entities_v2`, `infer_rx_norm`, `infer_icd10_cm` method names and response structures verified
- boto3 S3 `put_object`, `get_object`, `generate_presigned_url`, `put_object_tagging` calls verified
- boto3 DynamoDB resource `Table.put_item`, `Table.get_item`, `Table.update_item` calls verified
- S3 keys checked for leading slashes (none present)
- DynamoDB reserved-word `status` correctly aliased with `ExpressionAttributeNames` throughout
- All DynamoDB writes inspected for Python-float writes (properly handled via `_to_decimal_safe`)
- boto3 `healthlake` client `create_resource` method existence verified (does NOT exist; flagged by TechEditor TODO)
- Healthcare concerns reviewed: PHI logging, BAA, encryption, synthetic data labeling, consent enforcement, retention, provenance/validation

---

## Verdict: FAIL

One ERROR (HealthLake `create_resource` call will always raise `AttributeError`) and one WARNING. The ERROR alone is an automatic FAIL per the review rubric.

---

## Summary

The ten-step pseudocode maps cleanly to ten Python functions plus a sequential orchestrator. The code is pedagogically well-structured: each step builds on the previous, comments explain the "why," and the configuration section is cleanly separated from logic. Boto3 API calls for Transcribe (HealthScribe), Bedrock, Comprehend Medical, S3, DynamoDB, and CloudWatch are correct in method names, parameter names, and response parsing. DynamoDB Decimal handling is properly implemented via `_to_decimal_safe`. S3 keys use relative paths without leading slashes. The `ExpressionAttributeNames` pattern for the reserved word `status` is applied consistently. The consent enforcement logic is sound and the sensitive-encounter exclusion is enforced before audio capture.

The code falls short in one critical place: Step 8's `healthlake.create_resource()` call uses a method that does not exist on the boto3 `healthlake` client. The TechEditor already flagged this with a TODO comment in the file header and inline at the call site. The `except (ClientError, AttributeError)` block silently catches the `AttributeError`, which means the code "runs" without crashing but never actually writes to HealthLake. A reader who copies this pattern will have a pipeline that silently drops the EHR write-back, which is the exact failure mode the recipe's prose calls "a priority-1 operational incident." The code needs to either use the correct integration pattern (SigV4-signed HTTPS POST to the HealthLake FHIR endpoint) or be clearly marked as pseudo-code that cannot execute as-is.

---

## Findings

### Finding 1: `healthlake.create_resource()` does not exist on the boto3 healthlake client

- **Severity:** ERROR
- **Location:** `chapter02.08-python-example.md`, Step 8 (`write_to_ehr`), the `healthlake.create_resource(...)` call
- **Description:** The boto3 `healthlake` client does not expose a `create_resource` method. HealthLake FHIR resource creation is performed via SigV4-signed HTTPS POST requests to the HealthLake datastore's FHIR endpoint (e.g., `https://<datastore-endpoint>/r4/DocumentReference`), typically using the `requests` library with `botocore.auth.SigV4Auth` for signing, or via an FHIR client library. The current code always raises `AttributeError` on the `healthlake.create_resource(...)` line. The `except (ClientError, AttributeError)` block catches this silently, logs an error, updates the session to `EHR_WRITE_FAILED`, and returns `{"status": "FAILED"}`. While the pipeline doesn't crash, the code teaches a pattern that can never succeed. A reader who copies this into production will have a system that always fails the EHR write-back step, which the recipe's own prose identifies as "a critical incident." The TechEditor's inline TODO acknowledges this issue but the code remains misleading as published.
- **How to fix:** Replace the `healthlake.create_resource(...)` call with either:
  (a) A clearly-commented pseudo-code block that says "this is not executable; the real pattern uses SigV4-signed HTTPS" with a skeleton showing the `requests` + `SigV4Auth` approach, OR
  (b) A working implementation using `requests` with `botocore.auth.SigV4Auth` to POST the DocumentReference JSON to the HealthLake FHIR endpoint. Option (b) is better pedagogically but adds a `requests` dependency. Either way, remove the `AttributeError` from the except clause (catching `AttributeError` to mask a non-existent method is an anti-pattern that hides real bugs) and make the code's limitations explicit to the reader.

---

### Finding 2: HealthScribe `Settings` parameter structure may not match current API shape

- **Severity:** WARNING
- **Location:** `chapter02.08-python-example.md`, Step 2 (`finalize_audio_and_start_healthscribe`), the `Settings` dict passed to `start_medical_scribe_job`
- **Description:** The `Settings` dict includes `ClinicalNoteGenerationSettings` with a `NoteTemplate` key. The HealthScribe API has evolved since initial launch, and the exact nesting of `ClinicalNoteGenerationSettings` within `Settings` and the parameter name `NoteTemplate` should be verified against the current boto3 service model. The `ShowSpeakerLabels`, `MaxSpeakerLabels`, and `ChannelIdentification` keys are standard Transcribe settings that may or may not apply to the HealthScribe-specific `start_medical_scribe_job` operation (which has its own parameter shape distinct from `start_transcription_job`). If the parameter names have shifted in a recent SDK release, the call will raise `ParamValidationError` at runtime. The code comment says "Verify the current supported list in the boto3 docs," which is appropriate hedging, but a reader running this today may hit a validation error without understanding why.
- **How to fix:** Add a more prominent comment noting that the `Settings` structure shown is illustrative and that readers must verify the exact parameter shape against their installed boto3 version's service model (`python -c "import botocore; print(botocore.__version__)"` and check the HealthScribe operation's input shape). Alternatively, wrap the `start_medical_scribe_job` call's `Settings` construction in a helper that documents which fields are confirmed stable vs which are subject to API evolution.

---

### Finding 3: `_extract_symptom_phrases` is a placeholder that splits on periods

- **Severity:** NOTE
- **Location:** `chapter02.08-python-example.md`, Step 4, `_extract_symptom_phrases` helper
- **Description:** The function splits patient text on `.` and returns phrases longer than 5 characters, capped at 20. This produces sentence fragments, not symptom phrases. For a patient who says "I've been feeling tired. My daughter's birthday was last week. The weather has been nice." the function returns all three sentences as "symptoms." The code comment acknowledges this is a placeholder ("Production systems typically use a clinical NER fine-tune"), which is appropriate for a teaching example. However, the output feeds into the `must_include` checklist, which means the validator in Step 6 will flag "My daughter's birthday was last week" as a missing must-include item if it doesn't appear in the note. This could confuse a reader trying to understand why validation fails on their test data.
- **How to fix:** Add a brief inline comment at the call site in `extract_transcript_entities` noting that the placeholder symptom extractor will produce false positives and that the validator's `missing_must_include` list should be interpreted accordingly. No code change needed; the teaching point is that production systems need a real NER here.

---

### Finding 4: Guardrail intervention detection checks `stop_reason` as a fallback

- **Severity:** NOTE
- **Location:** `chapter02.08-python-example.md`, Step 5 (`render_institutional_note`), the guardrail action check
- **Description:** The code checks:
  ```python
  guardrail_action = (
      response_body.get("amazon-bedrock-guardrailAction")
      or response_body.get("stop_reason")
  )
  if guardrail_action == "INTERVENED" or guardrail_action == "guardrail_intervened":
  ```
  The main recipe's pseudocode correctly notes that Guardrail intervention is signaled via `amazon-bedrock-guardrailAction`, not `stop_reason`. The Python's fallback to `stop_reason` is defensive but slightly misleading: `stop_reason` in the Anthropic Messages API response is typically `"end_turn"` or `"max_tokens"`, never `"INTERVENED"` or `"guardrail_intervened"`. The `or` fallback will never actually trigger a guardrail detection via `stop_reason`; it just means that if `amazon-bedrock-guardrailAction` is absent, the code reads `stop_reason` (which will be `"end_turn"`) and correctly does not match either intervention string. So the code is functionally correct but the comment "others on a top-level field" is misleading about where intervention signals actually appear.
- **How to fix:** Simplify the comment to say that `amazon-bedrock-guardrailAction` is the authoritative field and the `stop_reason` fallback is a no-op safety net. Or remove the `stop_reason` fallback entirely since it can never match the intervention strings.

---

### Finding 5: Pseudocode uses `"anthropic.claude-sonnet-4"` while Python uses `"anthropic.claude-3-5-sonnet-20241022-v2:0"`

- **Severity:** NOTE
- **Location:** Pseudocode Step 5 in main recipe (`model_id = "anthropic.claude-sonnet-4"`) vs Python Step 5 (`GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"`)
- **Description:** Same pattern as Recipes 2.5 and 2.7. The pseudocode uses an illustrative family name; the Python pins a specific versioned model ID. The Python has an appropriate TODO comment about verifying model IDs. A reader comparing the two will notice the gap but the Python's approach (pinned, versioned ID) is the correct production pattern.
- **How to fix:** No code change needed. Optionally add a one-line note in the pseudocode that model IDs are versioned and the Python companion shows a specific working example.

---

### Finding 6: `_normalized_edit_distance` uses token-set symmetric difference, not Levenshtein

- **Severity:** NOTE
- **Location:** `chapter02.08-python-example.md`, Step 7, `_normalized_edit_distance` helper
- **Description:** The function computes `len(symmetric_difference) / (len(draft_tokens) + len(signed_tokens))`, which is a Jaccard-distance-like metric, not a normalized edit distance. The code comment explicitly acknowledges this ("This placeholder uses a token-set overlap as a proxy... Swap in a real edit distance before shipping"). The metric will behave differently from Levenshtein in important ways: reordering sections produces zero distance (same token set), while synonym substitution produces maximum distance (different tokens, same meaning). For a teaching example this is acceptable, but a reader should understand the metric's limitations.
- **How to fix:** The existing comment is sufficient. No change needed.

---

### Finding 7: `run_ambient_documentation_pipeline` orchestrator skips Step 1

- **Severity:** NOTE
- **Location:** `chapter02.08-python-example.md`, `run_ambient_documentation_pipeline` function and the `__main__` block
- **Description:** The orchestrator function starts at Step 2, assuming Step 1 (`start_encounter_session`) was already called. The `__main__` block calls Step 1 separately, then passes the result into the orchestrator. This is documented in the docstring ("In this example we assume the caller: 1. Calls start_encounter_session(request)..."). The split is pedagogically reasonable (consent is a separate workflow concern), but a reader looking only at `run_ambient_documentation_pipeline` might wonder why it starts at Step 2.
- **How to fix:** The existing docstring is sufficient. No change needed.

---

### Finding 8: Presigned URL in Step 1 uses `HEALTHSCRIBE_OUTPUT_CMK_ARN` for audio encryption

- **Severity:** NOTE
- **Location:** `chapter02.08-python-example.md`, Step 1 (`start_encounter_session`), the `generate_presigned_url` call's `SSEKMSKeyId` parameter
- **Description:** The code reuses `HEALTHSCRIBE_OUTPUT_CMK_ARN` for the audio upload presigned URL, with a comment "reuse a CMK or make a separate audio CMK." The configuration section's comments recommend separate CMKs per data class ("Audio and notes should use their own CMKs"). The code contradicts its own recommendation. For a teaching example this is fine (one CMK simplifies the setup), but the inconsistency between the recommendation and the implementation could confuse a reader.
- **How to fix:** Add a brief comment at the presigned URL line: `# Using the output CMK here for simplicity; production should use a dedicated audio CMK per the config comments above.`

---

## Re-review checklist

When this review is addressed, a re-reviewer should verify:

1. Step 8's HealthLake integration either uses a working SigV4+HTTPS pattern or is clearly marked as non-executable pseudo-code with the real approach documented.
2. The `except (ClientError, AttributeError)` anti-pattern is removed or justified with a comment that doesn't mask real bugs.
3. (Optional) The `Settings` structure in Step 2 is verified against the current boto3 HealthScribe service model.
