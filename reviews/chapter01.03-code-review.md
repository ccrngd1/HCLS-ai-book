# Code Review: Recipe 1.3 - Lab Requisition Form Extraction

**Reviewer:** Tech Code Reviewer
**Date:** 2026-03-05
**Files reviewed:**
- `chapter01.03-lab-requisition-extraction.md` (pseudocode)
- `chapter01.03-python-example.md` (Python)

**Validation performed:**
- Python syntax check via `ast.parse()` across all 11 code blocks: PASSED
- boto3 Comprehend Medical API signatures verified against service model
- InferICD10CM and DetectEntitiesV2 response structures confirmed
- Character limits verified from boto3 service model metadata

---

## Summary

Three issues found. One is a runtime bug that will break any form with low-confidence ICD-10 inferences. Two are incorrect comments or documentation that will mislead readers. All eight pseudocode steps are correctly reflected in the Python. boto3 method names and response key names are accurate throughout.

---

## Issues

### Issue 1: Bug - `icd10_flagged` confidence scores are raw floats, not Decimal

**Severity:** High. This breaks at runtime.
**File:** Python example
**Locations:** Step 5 (`infer_icd10_codes`) and Step 8 (`assemble_and_store`)

In `infer_icd10_codes`, flagged items are built with a plain Python float for confidence:

```python
flagged.append({
    "evidence_text": evidence_text,
    "top_candidate": {
        "icd10_code":  top_concept["Code"],
        "description": top_concept["Description"],
        "confidence":  round(score, 3),   # plain float
    },
})
```

In `assemble_and_store`, `icd10_accepted` gets converted through `to_decimal()`, but `icd10_flagged` is stored as-is:

```python
accepted_with_decimal = [
    {**d, "confidence": to_decimal(d["confidence"])}
    for d in icd10_accepted
]
# ...
"diagnoses": {
    "accepted": accepted_with_decimal,
    "flagged": icd10_flagged,   # no Decimal conversion applied
},
```

Any form where at least one ICD-10 inference falls below `ICD10_CONFIDENCE_THRESHOLD` will hit `TypeError: Float types are not supported. Use Decimal types instead` from the DynamoDB client during `put_item`. The record will not be saved.

The accepted list converts its confidence score. The flagged list must do the same for `top_candidate["confidence"]`.

**Fix:** Apply Decimal conversion to the flagged list before storage. Parallel to the accepted conversion:

```python
flagged_with_decimal = [
    {
        **d,
        "top_candidate": {
            **d["top_candidate"],
            "confidence": to_decimal(d["top_candidate"]["confidence"]),
        },
    }
    for d in icd10_flagged
]
```

Then use `flagged_with_decimal` in the record instead of `icd10_flagged`.

---

### Issue 2: Incorrect comment - InferICD10CM character limit stated as 20,000 instead of 10,000

**Severity:** Medium. The code clips at 9,800, which is correct. The comments teach the wrong limit.
**Files:** Python example (two locations), pseudocode (one location)

The boto3 service model for `InferICD10CM` specifies `max: 10000`. The service model for `DetectEntitiesV2` specifies `max: 20000`. They are not the same limit.

**In the Python `extract_clinical_text` comment (Step 4):**
```python
# The character limit for InferICD10CM
# and DetectEntitiesV2 is 20,000 characters per request.
```
This is wrong for `InferICD10CM`. The clip to 9,800 is correct for the 10,000 limit, but a reader who takes the comment at face value and bypasses or raises the clip will hit API errors on longer inputs.

**In the Python "Gap Between This and Production" section:**
> `InferICD10CM` and `DetectEntitiesV2` each accept up to 20,000 UTF-8 characters per request.

Same error. These limits are not identical.

**In the pseudocode "Why This Isn't Production-Ready" section:**
> `InferICD10CM` and `DetectEntitiesV2` each accept up to 20,000 UTF-8 characters per request.

Same error. (Note: the Step 4 pseudocode body correctly says 10,000 for `InferICD10CM`. The inconsistency exists between Step 4 and the "not production-ready" section within the same file.)

**Fix for all three locations:** State the limits separately.

> `InferICD10CM` accepts up to 10,000 UTF-8 characters per request. `DetectEntitiesV2` accepts up to 20,000. The two limits are different; do not treat them as interchangeable when chunking logic.

---

### Issue 3: Incorrect trait name - "FAMILY" should be "PERTAINS_TO_FAMILY"

**Severity:** Low for the recipe as written, but misleading for readers who copy the trait name into filter logic.
**Files:** Pseudocode Step 6 comment, Python Step 6 comment (same text in both)

The Comprehend Medical `DetectEntitiesV2` trait enum (confirmed from service model) is:
`SIGN, SYMPTOM, DIAGNOSIS, NEGATION, PERTAINS_TO_FAMILY, HYPOTHETICAL, LOW_CONFIDENCE, PAST_HISTORY, FUTURE`

For `InferICD10CM` traits:
`NEGATION, DIAGNOSIS, SIGN, SYMPTOM, PERTAINS_TO_FAMILY, HYPOTHETICAL, LOW_CONFIDENCE`

Both pseudocode and Python Step 6 comments list the trait as `FAMILY`:

**Pseudocode:**
```
// Traits: NEGATION, HYPOTHETICAL, PAST_HISTORY, FAMILY, SIGN, SYMPTOM.
// These modify how the entity should be interpreted.
```

**Python:**
```python
# Traits: NEGATION, HYPOTHETICAL, PAST_HISTORY, FAMILY, SIGN, SYMPTOM.
# These modify how the entity should be interpreted.
```

`FAMILY` is not a valid trait name in either API. The correct name is `PERTAINS_TO_FAMILY`. A reader who writes `if "FAMILY" in entity["traits"]` will never match anything and will silently miss family-history entities, which is exactly the class of error the trait section is warning about.

**Fix:** Replace `FAMILY` with `PERTAINS_TO_FAMILY` in both comments. While there, consider noting that `PAST_HISTORY` is valid for `DetectEntitiesV2` but does not appear in the `InferICD10CM` trait enum.

---

## Validation Details

### Syntax check
All 11 Python code blocks passed `ast.parse()` without errors.

### boto3 method names
- `comprehend_medical_client.infer_icd10_cm(Text=...)`: correct
- `comprehend_medical_client.detect_entities_v2(Text=...)`: correct
- `textract_client.start_document_analysis(...)`: correct
- `textract_client.get_document_analysis(...)`: correct

### InferICD10CM response structure
Confirmed field names match the service model:
- `response["Entities"]`: list of entity dicts
- `entity["Text"]`: text span that triggered the entity
- `entity["ICD10CMConcepts"]`: ranked list of concept candidates
- `concept["Code"]`: ICD-10-CM code string
- `concept["Description"]`: human-readable description
- `concept["Score"]`: float confidence score

All keys used in Step 5 match the actual response structure.

### DetectEntitiesV2 response structure
Confirmed field names match the service model:
- `response["Entities"]`: list of entity dicts
- `entity["Category"]`: one of the category enum values
- `entity["Type"]`: subcategory
- `entity["Text"]`: text span
- `entity["Score"]`: float confidence
- `entity["Traits"]`: list of trait dicts with `Name` and `Score` keys

All keys used in Step 6 match.

### Decimal usage
- `normalize_fields`: wraps confidence with `Decimal(str(round(...)))`. Correct.
- `assemble_and_store`: `to_decimal()` applied to `icd10_accepted` confidence and all entity confidence scores. Correct.
- `icd10_flagged`: NOT converted. This is Issue 1.

### datetime usage
Both `submitted_at` and `extracted_at` use `datetime.datetime.now(timezone.utc).isoformat()`. Correct. No `utcnow()` usage found.

---

## What Is Clean

- All 8 pseudocode steps have corresponding Python implementations. The Python pipeline function in "Putting It All Together" follows the steps in the exact order they appear in the pseudocode.
- The `cpt_mapped: False` / `"UNMAPPED"` pattern for unmapped tests is consistent between pseudocode and Python.
- The confidence threshold split between `accepted` and `flagged` lists is implemented identically in both files.
- The `block_map` construction and CHILD relationship traversal in Step 2 and Step 3 is correct for the Textract block model.
- The medical necessity prefix-matching logic (first 3 characters of ICD-10 code) is consistent between pseudocode and Python.
- IAM permission names in the setup section (`comprehend:DetectEntitiesV2`, `comprehend:InferICD10CM`) match the actual IAM action names.
- The Lambda handler correctly reads `sns_message["Status"]` and short-circuits on non-SUCCEEDED status before calling `GetDocumentAnalysis`. This prevents partial-result parsing on failed Textract jobs.
