# Code Review: Recipe 1.7 - Prescription Label OCR

**Reviewer:** Tech Code Reviewer
**Date:** 2026-03-05
**Files reviewed:**
- `chapter01.07-prescription-label-ocr.md` (pseudocode, 7 steps)
- `chapter01.07-python-example.md` (Python implementation)

**Syntax validation:** All code passed `python3` syntax check and unit tests (decode_sig, validate_ndc, compute_refill_metrics, parse_key_value_pairs, normalize_rx_fields). See validation script at `/tmp/validate_recipe_1_7.py`.

---

## Step Coverage

All 7 pseudocode steps are present and named consistently in the Python.

| Step | Pseudocode Function | Python Function | Match |
|------|--------------------|--------------------|-------|
| 1 | `extract_label(bucket, key)` | `extract_label(bucket, key)` | Yes |
| 2 | `parse_key_value_pairs(textract_response)` | `parse_key_value_pairs(textract_response)` | Yes |
| 3 | `normalize_rx_fields(raw_kv)` | `normalize_rx_fields(raw_kv)` | Yes |
| 4 | `decode_sig(raw_sig)` | `decode_sig(raw_sig)` | Yes |
| 5 | `map_to_rxnorm(drug_name, dosage)` | `map_to_rxnorm(drug_name, dosage)` | Yes |
| 6 | `validate_ndc(ndc_raw)` + `compute_refill_metrics(...)` | Both present | Yes |
| 7 | `store_medication_record(...)` | `store_medication_record(...)` | Yes |

The `process_label` integration function correctly wires all 7 steps in order.

---

## Issues

### Issue 1 - BUG: Duplicate key `"inh"` in SIG_CODES (Step 4)

**Severity:** Medium - silent data integrity issue

**Location:** `SIG_CODES` dict in Python (and matching pseudocode SIG_CODES table)

`"inh"` is defined twice in `SIG_CODES`:

```python
# Under "Route codes":
"inh":    "inhaled",

# Under "Dose form codes":
"inh":    "inhaler",
```

Python silently discards the first definition and uses the last. The dict ships with `"inh" -> "inhaler"` as the active mapping. A SIG like `"1 puff inh BID"` decodes `inh` to `"inhaler"` instead of `"inhaled"`. Both are legitimate medical English, but route context ("inhaled") is the more common SIG usage. Neither the pseudocode table nor the Python raises any warning.

**Suggested fix:**
```python
# Route codes:
"inh":     "inhaled",

# Dose form codes (choose a distinct key):
"inhaler": "inhaler",
```
Or drop `"inhaler"` from dose forms entirely; `"inhaled"` covers both meanings in SIG context.

---

### Issue 2 - BUG: Ambiguous variant `"rx"` in RX_FIELD_MAP (Step 3)

**Severity:** Medium - incorrect field classification on some labels

**Location:** `RX_FIELD_MAP` in both pseudocode and Python

The string `"rx"` appears as a variant under two canonical fields:

```python
"drug_name": [..., "rx", ...],       # iteration position 1
"rx_number": [..., "rx", "rx num"],  # iteration position 7
```

`normalize_rx_fields` iterates `RX_FIELD_MAP` in insertion order (Python 3.7+ guaranteed). On a label that prints `"Rx"` to label the prescription number, the match hits `drug_name` first and the prescription number is stored as the drug name. No error is raised. The record silently contains the Rx number in the wrong field.

`"rx"` as a drug name label is unusual enough that it should probably be removed from `drug_name`'s variants. The `"product"` and `"medication"` variants already cover the common drug name labels.

**Suggested fix:**
```python
"drug_name": ["drug name", "medication", "medication name", "drug", "product", "item", "drug/product"],
# Remove "rx" from drug_name variants
```

---

### Issue 3 - Mismatch: Expected output shows duration expansion the code does not perform (Step 4)

**Severity:** Low - documentation inconsistency that will confuse readers

**Location:** Expected output in recipe vs. `decode_sig` function and `SIG_CODES`

The recipe's expected output JSON shows:

```json
"directions_decoded": "Take 1 capsule by mouth three times daily for 7 days"
```

The raw directions field is `"Take 1 CAP PO TID x 7d"`. The `decode_sig` function decodes `CAP`, `PO`, and `TID` correctly. But neither `"x"` nor `"7d"` appear in `SIG_CODES`. Both tokens pass through unchanged.

What the code actually produces:

```
"Take 1 capsule by mouth three times daily x 7d"
```

The "for 7 days" in the expected output is not achievable with the current `decode_sig` implementation. The code would need a duration pattern handler (e.g., a regex pass to expand `"x Nd"` to `"for N days"`) to match that output. The pseudocode Step 4 walkthrough also does not describe duration expansion, so this looks like an oversight in the expected output section.

**Suggested fix:** Either correct the expected output to show `"x 7d"` (honest to the code), or add a note: "Duration tokens like 'x 7d' pass through unchanged; a production SIG parser would handle these separately."

---

### Issue 4 - Mismatch: `directions_raw` field placement in expected output vs. code (Step 7)

**Severity:** Low - documentation inconsistency

**Location:** Expected output JSON vs. `store_medication_record` return value

The expected output JSON shows `directions_raw` as a top-level key alongside `directions_decoded`:

```json
{
  "fields": { "drug_name": "Amoxicillin", ... },
  "directions_raw": "Take 1 CAP PO TID x 7d",
  "directions_decoded": "Take 1 capsule by mouth three times daily for 7 days"
}
```

The Python code stores the raw directions inside `fields["directions"]` (if confidence >= threshold), not as a separate top-level `directions_raw` key. The `store_medication_record` function does not receive or store a `directions_raw` parameter. The `process_label` function does not pass it.

The record the code actually produces has:

```json
{
  "fields": { "drug_name": "Amoxicillin", "directions": "Take 1 CAP PO TID x 7d", ... },
  "directions_decoded": "..."
}
```

This is functionally equivalent but structurally different from the expected output. Readers following the expected output as a contract will be confused.

**Suggested fix:** Either update the expected output to reflect the actual structure, or update `store_medication_record` to explicitly extract and store `directions_raw` at the top level (matching Step 7 pseudocode commentary: "Every field carries both the raw extracted value and the normalized or decoded value").

---

### Issue 5 - Code quality: Mixed client instantiation pattern (Steps 1, 5, 7)

**Severity:** Low - won't break the code, but is inconsistent and suboptimal for Lambda

**Location:** `extract_label`, `map_to_rxnorm`, `store_medication_record`

Step 1 uses module-level clients (correct Lambda pattern for connection reuse across warm invocations):

```python
textract_client = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")
```

Steps 5 and 7 create new clients inside the function on every call:

```python
def map_to_rxnorm(...):
    import boto3                                         # boto3 already imported at top
    comprehend_medical_client = boto3.client("comprehendmedical")  # new client every call

def store_medication_record(...):
    import boto3                                         # boto3 already imported at top
    dynamodb = boto3.resource("dynamodb")                # new resource every call
```

The in-function `import boto3` statements are redundant (boto3 is already imported at module level). Creating new clients on every invocation prevents Lambda connection reuse and adds latency. The pattern is also inconsistent - readers may not notice the difference and copy the in-function pattern for new steps.

**Suggested fix:** Move all client/resource instantiation to module level, alongside the existing `textract_client` and `comprehend_medical_client` declarations:

```python
textract_client = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")
dynamodb = boto3.resource("dynamodb")
```

Remove the `import boto3` statements and local client creation from inside `map_to_rxnorm` and `store_medication_record`.

---

## AWS SDK Accuracy

All AWS SDK usage is correct.

**Textract:**
- `analyze_document` with `FeatureTypes=["FORMS"]`: correct sync call
- `Document={"S3Object": {"Bucket": ..., "Name": ...}}`: correct S3 reference structure
- Block walking logic (KEY_VALUE_SET, EntityTypes, CHILD/VALUE relationship types) matches the Textract FORMS response schema

**Comprehend Medical:**
- `detect_entities_v2(Text=...)`: correct method name and parameter
- `entity.get("Category") != "MEDICATION"`: correct category filter
- `entity.get("RxNormConcepts", [])`: correct attribute name for RxNorm candidates
- `concept.get("Code", "")`, `concept.get("Description", "")`, `concept.get("Score", 0.0)`: all correct field names

**DynamoDB:**
- `Decimal(str(round(value, 2)))` for float fields: correct - boto3 DynamoDB resource requires Decimal, not float; the `str()` intermediate prevents floating-point precision artifacts
- Integer values (refill counts, days supply) stored as Python ints: correct - DynamoDB accepts ints natively
- `None` values in `refill_metrics_for_dynamo`: DynamoDB's boto3 resource layer converts Python `None` to DynamoDB NULL type; this is safe

**NDC regex:**
- `re.sub(r"[-\s]", "", ndc_raw)` then `re.match(r"^\d{10,11}$", ndc_clean)`: correct; accepts the 10-digit and 11-digit representations described in the recipe

**Decimal/datetime usage:**
- `datetime.datetime.now(timezone.utc).isoformat()` for extraction_timestamp: correct - produces ISO 8601 UTC string (e.g., `"2026-03-01T14:22:08.123456+00:00"`)
- `Decimal(str(...))` pattern used consistently for all float values written to DynamoDB: correct

---

## Minor Observations

**NDC format description in prose:** The recipe's "Additional Resources" section describes NDC as "10-digit" with format "5-4-2." But 5+4+2 = 11, not 10. The code comment correctly notes "Standard NDC is 10 digits; some systems pad to 11" and the regex accepts both. The prose is slightly inconsistent (describes a 10-digit code with an 11-digit breakdown). Worth a single-sentence clarification for readers who notice the arithmetic.

**SIG codebook size claim:** The Python file's gap section refers to "60-odd abbreviations in SIG_CODES." The actual dict has 50 entries (counting unique keys after deduplication). After fixing Issue 1, it will have 49 or 50. The claim is approximately right but slightly off; this is minor.

**`"rx_number"` variants overlap with field map iteration:** Beyond the `"rx"` conflict flagged in Issue 2, the variant `"rx num"` (two words) in `rx_number` will never match because `normalize_rx_fields` compares full label strings stripped and lowercased. A label printing `"Rx Num"` would produce a raw_key of `"Rx Num"`, which lowercased is `"rx num"` - this DOES match. But `"rx #"` requires the `#` character, which Textract may or may not include in the extracted key text depending on label rendering. Noting this as an awareness point, not a blocking issue for a teaching example.

---

## Summary

| Category | Count |
|----------|-------|
| Bugs (silent data integrity) | 2 (Issues 1, 2) |
| Documentation mismatches | 2 (Issues 3, 4) |
| Code quality | 1 (Issue 5) |
| AWS SDK accuracy | Pass |
| Syntax validation | Pass |
| Step coverage (all 7) | Pass |

The core logic is sound and the AWS SDK usage is accurate throughout. The two bugs (duplicate `"inh"` key and ambiguous `"rx"` variant) are the priority fixes before publication. The documentation mismatches in the expected output will create reader confusion and should be corrected to match what the code actually produces.
