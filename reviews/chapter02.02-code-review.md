# Code Review: Recipe 2.2 - Medical Terminology Simplification

**Reviewer:** Tech Code Reviewer
**Date:** 2026-05-06
**Files reviewed:**
- `chapter02.02-medical-terminology-simplification.md` (pseudocode)
- `chapter02.02-python-example.md` (Python)

**Validation performed:**
- Python syntax verified across all 8 code blocks
- boto3 Bedrock Converse API parameters and response structure confirmed against current API reference
- boto3 Comprehend Medical `detect_entities_v2` parameters and response structure confirmed against current service model
- DynamoDB Decimal usage verified throughout
- Pseudocode-to-Python step mapping confirmed

---

## Verdict: PASS

---

## Summary

The Python implementation is well-crafted and pedagogically sound. All seven pseudocode steps are faithfully translated into working Python with correct boto3 API calls, proper Decimal handling for DynamoDB, and modern datetime usage. The Bedrock Converse API call uses the correct method name, parameter structure, and response traversal. The Comprehend Medical `detect_entities_v2` call is correct. One misleading IAM permission name in the setup section will confuse readers who try to build their own IAM policy, but the code itself will run correctly (IAM is configured externally). One minor note on the entity matching logic.

---

## Issues

### Issue 1: Incorrect IAM action name for Comprehend Medical

- **Severity:** WARNING
- **File:** `chapter02.02-python-example.md`
- **Location:** Setup section, line 18
- **What's wrong:** The IAM permission is listed as `comprehend:DetectEntitiesV2`. The correct IAM action for Amazon Comprehend Medical is `comprehendmedical:DetectEntitiesV2`. Comprehend and Comprehend Medical are separate services with separate IAM namespaces. A reader who builds an IAM policy using `comprehend:DetectEntitiesV2` will get an AccessDeniedException at runtime.
- **Fix:** Change:
  ```
  - `comprehend:DetectEntitiesV2` (for Comprehend Medical entity extraction)
  ```
  to:
  ```
  - `comprehendmedical:DetectEntitiesV2` (for Comprehend Medical entity extraction)
  ```

---

### Issue 2: Entity matching may miss medications detected with different entity boundaries

- **Severity:** NOTE
- **File:** `chapter02.02-python-example.md`
- **Location:** Step 4, `validate_accuracy` function, medication dosage comparison logic (around line 355-370)
- **What's wrong:** The medication matching logic finds simplified medications where `orig_med["Text"].lower() in s["Text"].lower() or s["Text"].lower() in orig_med["Text"].lower()`. If the original detects "aspirin" as the entity and the simplified text detects "aspirin 81mg" as a single entity (or vice versa), the substring match works. But if Comprehend Medical detects "aspirin 81mg every day" as a single medication entity in the simplified text, the dosage check looks for `Attributes` with `Type == "DOSAGE"` on that entity. When the dosage is part of the entity text itself rather than a separate attribute, `simplified_dosages` will be empty, triggering a false positive "altered dosage" flag. This is a known limitation of entity-boundary variance in Comprehend Medical and is already acknowledged in the "Gap to Production" section's discussion of entity matching sophistication. No code change needed, but a brief inline comment at the matching logic would help learners understand why this can produce false positives.
- **Suggested improvement:** Add a comment like `# Note: Comprehend Medical may include dosage in the entity text itself rather than as a separate Attribute, which can cause false positives here.`

---

### Issue 3: Main recipe pseudocode uses `find_matching_entity` and `find_associated_dosage` helper functions not shown

- **Severity:** NOTE
- **File:** `chapter02.02-medical-terminology-simplification.md`
- **Location:** Step 4 pseudocode, `validate_accuracy` function
- **What's wrong:** The pseudocode references `find_matching_entity(entity, simplified_entities)` and `find_associated_dosage(entity, original_entities)` without defining them. The Python companion implements this logic inline (substring matching and attribute traversal). This is fine pedagogically since the pseudocode is meant to convey intent, and the Python shows the actual implementation. The inline approach in Python is arguably clearer for learners than abstracting into helper functions. No change needed, just noting the structural difference.

---

## Validation Details

### boto3 Bedrock Converse API

The Python code calls:
```python
bedrock_client.converse(
    modelId=MODEL_ID,
    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
    system=[{"text": system_prompt}],
    inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": TEMPERATURE, "topP": 0.9},
)
```

Verified against the current Converse API reference:
- `modelId`: correct parameter name (URI parameter)
- `messages`: correct structure (list of message objects with `role` and `content`)
- `system`: correct structure (list of SystemContentBlock objects with `text` key)
- `inferenceConfig`: correct structure with `maxTokens`, `temperature`, `topP` as valid fields
- Response traversal `response["output"]["message"]["content"][0]["text"]`: matches the documented response structure

All correct.

### boto3 Comprehend Medical detect_entities_v2

The Python code calls:
```python
comprehend_medical_client.detect_entities_v2(Text=text)
```

Verified against current boto3 service model:
- Method name `detect_entities_v2`: correct
- Parameter `Text` (string, required): correct
- Response key `response["Entities"]`: correct (returns list of entity dicts)
- Entity fields accessed: `"Text"`, `"Category"`, `"Type"`, `"Score"`, `"Attributes"`: all correct
- Attribute fields accessed: `"Type"`, `"Text"`: correct
- Category values used: `"MEDICATION"`, `"MEDICAL_CONDITION"`, `"TEST_TREATMENT_PROCEDURE"`: all valid enum values

All correct.

### DynamoDB Decimal handling

- `store_result` wraps all float values in `Decimal(str(...))`: correct
- `readability["word_count"]` stored as integer (from `textstat.lexicon_count`): correct, integers are natively supported
- `TEMPERATURE` constant (0.2, a Python float) stored as `Decimal(str(TEMPERATURE))`: correct
- The `DecimalEncoder` in the `__main__` block correctly handles display serialization

No float-to-DynamoDB issues found.

### datetime usage

Uses `datetime.datetime.now(timezone.utc).isoformat()` with `from datetime import timezone` imported at module level. This is the modern, non-deprecated approach. No `utcnow()` usage found.

### Pseudocode-to-Python consistency

| Pseudocode Step | Python Function | Match |
|----------------|-----------------|-------|
| `classify_document(clinical_text)` | `classify_document(clinical_text)` | Exact |
| `build_simplification_prompt(clinical_text, doc_type)` | `build_simplification_prompt(clinical_text, doc_type)` | Exact |
| `generate_simplification(system_prompt, user_prompt, model_id)` | `generate_simplification(system_prompt, user_prompt)` | Minor: model_id is module constant instead of parameter. Acceptable. |
| `validate_accuracy(original_text, simplified_text)` | `validate_accuracy(original_text, simplified_text)` | Exact |
| `score_readability(text)` | `score_readability(text)` | Exact |
| `quality_gate(...)` | `quality_gate(...)` | Exact |
| `store_result(...)` | `store_result(...)` | Exact |

The Python `simplify_clinical_text` orchestrator correctly implements the retry loop described in the pseudocode's Step 6 narrative. The retry prompt augmentation on subsequent attempts is a sensible addition not explicitly in the pseudocode but consistent with the described behavior.

---

## What Is Clean

- The Bedrock Converse API usage is textbook-correct and matches the official AWS examples.
- Decimal handling is thorough and consistent. No float values reach DynamoDB.
- The retry logic correctly distinguishes between accuracy failures (no retry, route to human) and readability failures (retry with stronger prompt). The loop termination is sound: `quality_gate` returns `ACCEPTED_WITH_FLAG` on the final attempt, preventing infinite loops.
- Comment quality is excellent throughout. Comments explain "why" decisions were made, not just "what" the code does. The notes about temperature choice, entity matching limitations, and readability formula caveats are genuinely educational.
- The `DOCUMENT_TYPES` configuration structure is identical between pseudocode and Python, making it easy for readers to map concepts across files.
- The "Gap to Production" section correctly identifies the limitations of the teaching code without cluttering the example itself.
- Module-level client instantiation with retry config is appropriate for Lambda reuse patterns.
- The `textstat` library usage is correct: `flesch_kincaid_grade`, `flesch_reading_ease`, `smog_index`, `lexicon_count`, and `sentence_count` are all valid function names in the current textstat API.
