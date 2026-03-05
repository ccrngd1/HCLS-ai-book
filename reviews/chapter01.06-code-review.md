# Code Review: Recipe 1.6 - Handwritten Clinical Note Digitization

**Reviewer:** Tech Code Reviewer
**Date:** 2026-03-05
**Files reviewed:**
- `chapter01.06-handwritten-clinical-note-digitization.md` (pseudocode, 8 steps)
- `chapter01.06-python-example.md` (Python implementation)

**Syntax check:** All 9 Python code blocks pass `ast.parse()` with no syntax errors.

---

## Summary

The recipe is well-structured and the pseudocode-to-Python mapping is faithful across all 8 steps. Two bugs will cause runtime failures in a real deployment. One is a missing import that is trivially fixed. The other is a float-in-DynamoDB issue that the code's own "Gap to Production" section discusses as a general principle (always use Decimal) but then violates in the final assembly step. Both are fixable with small, targeted changes. Additionally, there is a bounding box propagation gap that spans both pseudocode and Python consistently -- it is a teaching gap rather than a code bug, but it is worth flagging because the pseudocode implies the field is available when it never is.

---

## Critical Bugs (Will Fail at Runtime)

### BUG-1: `boto3.dynamodb.conditions.Key` is not accessible via `boto3.dynamodb`

**Location:** `assemble_final_record()`, Step 8 Python

**Code:**
```python
response = entities_table.query(
    KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(document_key)
)
```

**Problem:** `boto3` module has no `dynamodb` attribute. Accessing `boto3.dynamodb` raises `AttributeError: module 'boto3' has no attribute 'dynamodb'` at runtime. This has been verified:

```
>>> import boto3
>>> boto3.dynamodb.conditions.Key("pk").eq("test")
AttributeError: module 'boto3' has no attribute 'dynamodb'
```

**Fix:** Add `from boto3.dynamodb.conditions import Key` to the module-level imports (alongside the existing `import boto3`) and use `Key("pk").eq(document_key)` directly. The `from boto3.dynamodb.conditions import Key` pattern is the standard boto3 idiom.

**Pseudocode alignment:** The pseudocode uses `query DynamoDB table "clinical-note-entities" where pk == document_key`, which does not reveal this implementation detail. The Python needs to handle it correctly regardless.

---

### BUG-2: Float values in DynamoDB `put_item` will raise `TypeError`

**Location:** `assemble_final_record()`, Step 8 Python

**Code:**
```python
final_entities.append({
    ...
    "confidence": float(record.get("confidence", Decimal("0"))),  # <-- problem
    ...
})
# ...
completed_table.put_item(Item=final_record)  # final_record contains the float
```

**Problem:** The `confidence` field is converted from `Decimal` to `float` before being placed into `final_entities`. When `final_record` (which contains `final_entities`) is written to DynamoDB via `put_item`, the boto3 DynamoDB serializer raises:

```
TypeError: Float types are not supported. Use Decimal types instead.
```

This is verified against the boto3 DynamoDB `TypeSerializer`:

```
>>> TypeSerializer().serialize(89.1)
TypeError: Float types are not supported. Use Decimal types instead.

>>> TypeSerializer().serialize(Decimal("89.1"))
{'N': '89.1'}
```

The irony is that the "Gap to Production" section in the same file correctly states: "Every numeric value written to DynamoDB uses `Decimal` wrapping. Python floats in a `put_item` call raise a `TypeError` at runtime." The code then violates this in Step 8.

**Fix:** Remove the `float()` conversion. Keep the value as `Decimal`:
```python
"confidence": record.get("confidence", Decimal("0")),
```

If a float is needed for downstream consumers of this function's return value (not DynamoDB), convert only in the return value or in the `DecimalEncoder` that already exists in the `__main__` block.

**Pseudocode alignment:** The pseudocode does not specify numeric types, so this is a Python-only issue.

---

## Bugs (Incorrect Behavior, Non-Fatal)

### BUG-3: `bounding_box` is never populated on entities -- `entity.get("bounding_box", {})` always returns `{}`

**Location:** `extract_clinical_entities()` (Step 3) and `route_entities()` (Step 5), both pseudocode and Python

**Problem:** The pseudocode Step 5 references `entity.bounding_box` when building the A2I review task:

```
bounding_box: entity.bounding_box
FOR each entity in tiered_entities.low
```

But the pseudocode Step 3 never adds `bounding_box` to the entity dict. The entity fields populated in Step 3 are: `text`, `category`, `entity_type`, `traits`, `nlp_confidence`, `ocr_confidence`, `composite_confidence`, `is_handwritten`. No bounding box.

In Python, `find_ocr_confidence_for_entity()` locates the matching Textract WORD blocks (which do have `bounding_box` from Step 2) and returns `(ocr_confidence, is_handwritten)` -- but not the bounding box. So `extract_clinical_entities()` never sets `bounding_box` on any entity, and `route_entities()` falls back to `entity.get("bounding_box", {})` which is always `{}`.

The reviewer interface receives an empty bounding box for every entity sent to A2I. The template comment says "can be used to draw a highlight box over the relevant word" -- but the highlight will never render because the data is missing.

**Severity:** Non-fatal (the review task still works, reviewers just cannot see word highlights), but the pseudocode is misleading because it implies the field flows through naturally.

**Fix suggestion:** `find_ocr_confidence_for_entity()` should return the bounding box alongside the confidence:
```python
def find_ocr_confidence_for_entity(...) -> tuple[float, bool, dict]:
    ...
    bounding_box = matching_words[0].get("bounding_box", {}) if matching_words else {}
    return ocr_confidence, is_handwritten, bounding_box
```

Then `extract_clinical_entities()` should include `"bounding_box": bounding_box` in the entity dict. The pseudocode Step 3 should be updated to show this field in the entity structure. This is a teaching snippet, so at minimum a comment explaining the gap would serve readers well.

---

## Style Issues (Valid Python, Against Convention)

### STYLE-1: Local imports inside function bodies

**Location:** `route_entities()` and `digitize_handwritten_note()`, Step 5 and full pipeline

```python
def route_entities(...):
    ...
    import hashlib   # <-- local import
    loop_name = "note-review-" + hashlib.md5(document_key.encode()).hexdigest()[:16]

def digitize_handwritten_note(...):
    import time      # <-- local import
    ...
```

Both `hashlib` and `time` are standard library modules. Move them to the module-level import block with the other imports. Local imports at function scope are valid Python but violate PEP 8 and can confuse readers into thinking they are conditional or deferred for a specific reason.

**Suggested fix:** Add `import hashlib` and `import time` to the imports at the top of the module alongside `import uuid`, `import json`, etc.

---

## Pseudocode-to-Python Consistency

All 8 steps map correctly from pseudocode to Python. The following minor inconsistencies are noted but are not bugs.

### MINOR-1: Output key naming inconsistency: `corrections_made` vs `corrections`

**Location:** Step 7 (pseudocode) vs Step 7 (Python)

Pseudocode `route_entities` sends task success with:
```
output: json_encode({
    document_key:     document_key,
    reviewed_count:   length(reviewed_entities),
    corrections_made: corrections_made   # <-- "corrections_made"
})
```

Python `process_review_completion` sends:
```python
summary = {
    "document_key":   document_key,
    "reviewed_count": reviewed_count,
    "corrections":    corrections_made,  # <-- "corrections"
}
```

This is a naming inconsistency between pseudocode and Python. Not a functional bug (nothing reads this output key in the demonstrated code), but worth aligning for clarity. Pick one name and use it consistently.

### MINOR-2: `processing_summary` fields do not match Expected Results JSON

**Location:** Step 8 (pseudocode and Python) vs Expected Results section

The Expected Results JSON shows:
```json
"processing_summary": {
    "avg_handwriting_confidence": 71.4,
    "avg_printed_confidence": 96.8,
    "total_entities": 14,
    "auto_accepted": 9,
    "accepted_flagged": 2,
    "human_reviewed": 3,
    "corrections_made": 1,
    ...
}
```

Both pseudocode and Python Step 8 produce:
```python
"processing_summary": {
    "total_entities": len(all_records),
    "auto_accepted":  auto_accepted,   # includes accepted_flagged count
    "human_reviewed": human_reviewed,
    "corrections":    corrections,     # not corrections_made
}
```

Two gaps:
1. `avg_handwriting_confidence` and `avg_printed_confidence` are computed in Step 2 but never threaded through to Step 8. They do not appear in the DynamoDB intermediate records and the Step 8 function has no access to them.
2. `accepted_flagged` is a separate counter in the Expected Results JSON but both pseudocode and Python fold it into `auto_accepted`. The Expected Results is not consistent with the code it is illustrating.

These are documentation/consistency issues, not code correctness issues. The Expected Results JSON should either match what Step 8 actually produces, or the recipe should explain that the OCR averages are stored separately and merged at display time.

---

## AWS SDK and API Verification

All verified against boto3 service models.

| Call | Status | Notes |
|------|--------|-------|
| `textract_client.analyze_document(Document=..., FeatureTypes=["FORMS"])` | Correct | `FeatureTypes` is required; `"FORMS"` is a valid value; handwriting is native, no extra flag needed |
| `block["TextType"]` on WORD blocks | Correct | `TextType` is a valid field on Block shapes; values are `"PRINTED"` and `"HANDWRITING"` |
| `comprehend_client.detect_entities_v2(Text=...)` | Correct | Method exists; `Text` is the only required parameter |
| `entity["Score"]` from Comprehend Medical | Correct | `Score` is a float 0.0-1.0; scaling by 100 to match Textract range is correct |
| `entity["Category"]`, `entity["Type"]`, `entity["Traits"]` | Correct | All are valid fields in `DetectEntitiesV2` response entities |
| `a2i_client = boto3.client("sagemaker-a2i-runtime")` | Correct | The A2I runtime client uses service ID `"sagemaker-a2i-runtime"`, distinct from `"sagemaker"` |
| `a2i_client.start_human_loop(HumanLoopName=..., FlowDefinitionArn=..., HumanLoopInput={"InputContent": ...})` | Correct | All three fields verified; `InputContent` is required inside `HumanLoopInput` and must be a JSON string |
| `a2i_client.describe_human_loop(HumanLoopName=...)` | Correct | `HumanLoopName` is the only required parameter; `HumanLoopStatus` is a valid response field |
| `sfn_client.send_task_success(taskToken=..., output=...)` | Correct | Both `taskToken` and `output` are required; `output` must be a JSON string |
| `Decimal(str(entity["composite_confidence"]))` pattern | Correct | The `str()` intermediary avoids floating-point representation drift in Decimal |
| `datetime.datetime.now(timezone.utc).isoformat()` | Correct | Produces a UTC ISO 8601 timestamp with timezone offset |
| IAM action `sagemaker:StartHumanLoop` / `sagemaker:DescribeHumanLoop` | Correct | A2I actions use the `sagemaker:` namespace even though the boto3 client is `sagemaker-a2i-runtime` |
| `entities_table.update_item(Key={"pk": ..., "sk": ...}, UpdateExpression=..., ExpressionAttributeValues=...)` | Correct | Valid DynamoDB update_item syntax |
| `completed_table.put_item(Item=..., ConditionExpression="attribute_not_exists(document_key)")` | Correct | Valid conditional write to prevent duplicate final records |

---

## Step Coverage Check

| Step | Pseudocode | Python | Match |
|------|-----------|--------|-------|
| Step 1: Image pre-processing | `preprocess_image()` | `preprocess_image()` | Yes -- Pillow limitation documented; deskew noted as stub |
| Step 2: Textract OCR | `extract_text_with_confidence()` | `extract_text_with_confidence()` | Yes |
| Step 3: Clinical entity extraction | `extract_clinical_entities()` | `extract_clinical_entities()` + `find_ocr_confidence_for_entity()` | Yes, with bounding_box gap noted above |
| Step 4: Confidence tiering | `tier_entities()` | `tier_entities()` | Yes |
| Step 5: Store and start human loop | `route_entities()` | `route_entities()` | Yes -- presigned URL, A2I input structure, DynamoDB writes all correct |
| Step 6: Reviewer interface | HTML template | HTML template | Yes -- both files include identical template |
| Step 7: Process review results | `process_review_completion()` | `process_review_completion()` | Yes -- `corrections_made` vs `corrections` naming inconsistency noted |
| Step 8: Assemble final record | `assemble_final_record()` | `assemble_final_record()` | Yes -- BUG-1 and BUG-2 are in this step |

---

## Priority List

1. **Fix BUG-1** (missing Key import): Add `from boto3.dynamodb.conditions import Key` to module imports. Replace `boto3.dynamodb.conditions.Key(...)` with `Key(...)` in `assemble_final_record`. One-line import fix.

2. **Fix BUG-2** (float in DynamoDB): Remove `float()` wrapper on `confidence` in `assemble_final_record`. Keep as `Decimal`.

3. **Address BUG-3** (bounding box propagation): Either propagate the bounding box from `find_ocr_confidence_for_entity` through `extract_clinical_entities` to the entity dict, or add a comment in both Step 3 (pseudocode and Python) noting that bounding box propagation is omitted for brevity and what the production fix looks like.

4. **Fix STYLE-1** (local imports): Move `import hashlib` and `import time` to module-level imports.

5. **Align MINOR-1** (`corrections` naming): Pick `corrections` or `corrections_made` and use it in both pseudocode and Python.

6. **Align MINOR-2** (Expected Results): Update the Expected Results JSON to match the actual `processing_summary` structure produced by Step 8, or add a note explaining the gap between the sample output and the reference implementation.
