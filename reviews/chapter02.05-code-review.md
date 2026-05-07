# Code Review: Recipe 2.5 - After-Visit Summary Generation

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-07
**Files reviewed:**
- `chapter02.05-after-visit-summary-generation.md` (main recipe, pseudocode)
- `chapter02.05-python-example.md` (Python companion)

**Validation performed:**
- Seven-step pseudocode walked against Python functions, one-to-one
- boto3 Bedrock Runtime `invoke_model` parameters, Anthropic Messages API body shape, and response traversal verified against the current SDK
- boto3 Comprehend Medical `detect_entities_v2` method name, `Text` parameter casing, and response structure verified (method exists; entity `Category`/`Attributes` fields match)
- `client.exceptions.ClientError` is a valid attribute on modern boto3 clients (verified locally against `comprehendmedical`), so that try/except pattern works
- boto3 S3 `put_object` and DynamoDB `put_item` / `update_item` / `get_item` calls verified
- S3 keys checked for leading slashes (none present)
- DynamoDB reserved-word `status` correctly aliased with `ExpressionAttributeNames`
- All DynamoDB writes inspected for Python-float writes (none; see Finding 2)
- Raw bytes inspected for the `language_instruction` dict values to verify encoding
- Healthcare concerns reviewed: PHI logging, BAA, encryption hints, synthetic data labeling, minimum-necessary, retention, provenance/validation, guardrails

---

## Verdict: FAIL

One ERROR (mojibake in non-English instruction strings) and three WARNINGs. The ERROR alone is an automatic FAIL per the review rubric.

---

## Summary

The seven-step pseudocode maps cleanly to seven Python functions, and the orchestrator at the bottom of the file walks them in order. Boto3 API calls are correct: `invoke_model` uses the right parameters and Anthropic Messages API body shape, `detect_entities_v2` is spelled and parameterized correctly, `put_object` uses relative keys, and `update_item` aliases the reserved `status` word. DynamoDB Decimal handling in Step 2 (the read path) is handled correctly, converting `Decimal` to `int` before the value flows into a prompt.

The code falls short in three places that matter for a teaching example. First, the language-specific instruction strings for Spanish, Chinese, and Vietnamese are double-encoded UTF-8 mojibake. A reader who runs the example with a non-English patient will ship garbled bytes to Bedrock. Second, the final step of the orchestrator doesn't catch the case where all generation attempts produced `REQUIRES_REGENERATION`; in that failure mode the summary can be auto-delivered to the patient unless the visit type happens to be on the high-risk list. Third, the "Gap to Production" prose claims the example code writes `validation_rate` to DynamoDB with `Decimal(str(round(...)))`, but the example never writes `validation_rate` to DynamoDB at all.

---

## Findings

### Finding 1: Non-English instruction strings are double-encoded UTF-8 mojibake

- **Severity:** ERROR
- **Location:** `chapter02.05-python-example.md`, Step 4 (`generate_summary`), the `language_instruction` dict, lines covering `"es"`, `"zh"`, and `"vi"` values
- **Description:** The source file stores the Spanish, Chinese, and Vietnamese instruction strings as double-encoded UTF-8. For the Spanish "español" value, the raw bytes on disk include `\xc3\x83\xc2\xb1` where correct UTF-8 for "ñ" is `\xc3\xb1`. The Chinese and Vietnamese values are similarly mangled across every non-ASCII character. When this file is imported and the string is sent to Bedrock, the model receives garbled text. The most likely outcome is that the model ignores the garbled instruction and falls back to writing in English, defeating the language personalization that the recipe's prose treats as a central feature. A secondary risk is that the model attempts to imitate the garbled characters in its output, producing a visibly broken summary.
- **How to fix:** Rewrite the three strings with correct UTF-8 characters, save the file explicitly as UTF-8 (no BOM), and verify with a hex dump that "español" is `\x65\x73\x70\x61\xc3\xb1\x6f\x6c`, not the doubled sequence. For a quick sanity check, a reader should be able to run `python -c "print('español')"` from the Python file and see it render correctly. While fixing, also consider adding a comment noting that these instruction strings must be saved as UTF-8 because mojibake in prompts is a silent failure mode, not an obvious crash.

---

### Finding 2: Prose claims code handles DynamoDB Decimal for `validation_rate`, but code doesn't write `validation_rate` to DynamoDB at all

- **Severity:** WARNING
- **Location:** `chapter02.05-python-example.md`, "Gap to Production" section, `DynamoDB Decimal gotcha` paragraph
- **Description:** The prose says "The validation_rate in Step 5 gets stored as a Decimal when written to DynamoDB, because DynamoDB doesn't accept Python floats. The example code handles this correctly (`Decimal(str(round(validation_rate, 4)))`), but it's a common trap on the first deployment." The claim is false for this example. Searching the file, `validation_rate` appears only in the validator's return value, in a print statement, and in the final result dict returned by `generate_after_visit_summary`. It is never passed to `put_item` or `update_item`. The only DynamoDB writes (Step 1's initial record and Step 7's `update_item`) carry only strings and a string list; no Python float is stored, so no `Decimal` wrapping is necessary or present.
- **How to fix:** Either (a) update the prose to say "DynamoDB requires Decimal for any float you store; the example code above does not persist `validation_rate`, but if you extend it to do so, wrap it with `Decimal(str(round(validation_rate, 4)))` to avoid the binary-precision pitfall of `Decimal(float_value)`," or (b) actually extend Step 7's `update_item` to persist `validation_rate` so the prose is accurate. Option (a) is less work and keeps the teaching point intact.

---

### Finding 3: Orchestrator auto-delivers to patient when all generation attempts fail validation

- **Severity:** WARNING
- **Location:** `chapter02.05-python-example.md`, `generate_after_visit_summary` orchestrator, the `requires_review` expression near the end and the for/else loop
- **Description:** If validation returns `REQUIRES_REGENERATION` on every attempt, the loop does `continue` without running readability, exits via the `else:` branch, and `readability` stays `None`. The final gate is:
  ```python
  requires_review = (
      visit_type in HIGH_RISK_VISIT_TYPES
      or (validation and validation["status"] == "NEEDS_CLINICIAN_REVIEW")
      or (readability and not readability["pass"])
  )
  ```
  This check does not include `validation["status"] == "REQUIRES_REGENERATION"`. So if a non-high-risk visit exhausts all `MAX_GENERATION_ATTEMPTS` with HIGH-severity validation failures on each attempt, `requires_review` is `False`, and `render_and_deliver` is called with `requires_clinician_review=False`, which means `final_status = "DELIVERED"` and the unvalidated summary is routed to the patient portal. For a teaching example whose central safety claim is "every specific claim must trace to a source," this is the exact wrong default. A reader copying this pattern into production would ship a system that quietly delivers hallucinated summaries on the pathological cases the safety rails were designed to catch.
- **How to fix:** Include `REQUIRES_REGENERATION` in the review check, e.g.:
  ```python
  requires_review = (
      visit_type in HIGH_RISK_VISIT_TYPES
      or (validation and validation["status"] in ("NEEDS_CLINICIAN_REVIEW", "REQUIRES_REGENERATION"))
      or (readability and not readability["pass"])
      or readability is None  # loop exhausted before a readability pass
  )
  ```
  Or, cleaner: flip the default so that anything short of a fully-VALIDATED summary with a passing readability check requires review. Either way, add a comment saying that "exhausted attempts" is a reason to route to a human, not a reason to deliver to the patient anyway.

---

### Finding 4: Comprehend Medical truncation uses character count, not byte count

- **Severity:** WARNING
- **Location:** `chapter02.05-python-example.md`, Step 3 (`extract_summary_object`), the `comprehend_medical.detect_entities_v2(Text=note_text[:20000])` call
- **Description:** Comprehend Medical's `DetectEntitiesV2` enforces its size limit in bytes, not characters. The slice `note_text[:20000]` slices by Python characters. For an ASCII English note this is equivalent, so the example runs. For Spanish, Portuguese, French, Mandarin, or any note that contains non-ASCII characters, 20,000 Python characters can be significantly more than 20,000 bytes once encoded as UTF-8. A reader who uses this pattern on a Spanish note and hits a `TextSizeLimitExceededException` will be confused because the number of characters they passed was under the limit they were told to respect. This matters in a recipe whose prose explicitly highlights non-English generation as a first-class use case.
- **How to fix:** Encode once, slice in bytes, decode back (ignoring a potential trailing partial character), or use a lower character ceiling. A concise pattern:
  ```python
  MAX_CM_BYTES = 20000
  encoded = note_text.encode("utf-8")[:MAX_CM_BYTES]
  # Drop partial trailing multi-byte char if any
  safe_text = encoded.decode("utf-8", errors="ignore")
  cm_response = comprehend_medical.detect_entities_v2(Text=safe_text)
  ```
  And add a comment that the limit is byte-based, not character-based. One-line fix; big teaching value given the multilingual framing of the recipe.

---

### Finding 5: Pseudocode status name `VALIDATION_FAILED` versus Python `REQUIRES_REGENERATION`

- **Severity:** NOTE
- **Location:** Pseudocode Step 5 in `chapter02.05-after-visit-summary-generation.md` (`status = "VALIDATION_FAILED"`) vs Python Step 5 in `chapter02.05-python-example.md` (`status = "REQUIRES_REGENERATION"`)
- **Description:** Same state, different string constants. The Python name is arguably more descriptive (it says what to do next), but a learner bouncing between the two files will wonder whether they are the same concept.
- **How to fix:** Align the two, or add a single comment in the Python noting the pseudocode's `VALIDATION_FAILED` is called `REQUIRES_REGENERATION` here because the status drives a retry loop.

---

### Finding 6: Validator uses substring matching where pseudocode specifies semantic similarity

- **Severity:** NOTE
- **Location:** Pseudocode Step 5 (`similarity = semantic_similarity(claim.text, str(source_value))` with MEDIUM severity for paraphrase drift) vs Python Step 5 (bidirectional substring match; all mismatches classified HIGH)
- **Description:** The code comment inside `validate_summary` acknowledges the simplification ("Production systems often layer on semantic similarity (embedding-based)"), so this is a deliberate teaching choice, not a bug. The divergence is still worth naming: the pseudocode draws a HIGH-vs-MEDIUM distinction that the Python collapses. A reader trying to reproduce the pseudocode's three-tier status logic (`VALIDATED` / `NEEDS_CLINICIAN_REVIEW` / `VALIDATION_FAILED`) from the Python alone will miss where MEDIUM-severity claims come from.
- **How to fix:** Either add a brief note to the Python explaining that the MEDIUM-severity branch collapses into the substring path for teaching simplicity, or introduce a trivial "close but not equal" heuristic (e.g., token-set overlap) so the MEDIUM branch exists in code. Not blocking.

---

### Finding 7: `_parse_json_response` helper is defined at the bottom of Step 3

- **Severity:** NOTE
- **Location:** `chapter02.05-python-example.md`, defined at the end of Step 3's code block, used again in Step 4
- **Description:** A learner who copies only the Step 4 block in isolation will hit `NameError` because the helper lives in Step 3. Running the whole file works fine.
- **How to fix:** Move the helper into a "Shared Helpers" block above Step 3, or add a one-line comment at the first Step 4 use site: `# _parse_json_response is defined in Step 3`.

---

### Finding 8: Module logger has no handler configured

- **Severity:** NOTE
- **Location:** `chapter02.05-python-example.md`, top of Configuration section (`logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)`)
- **Description:** Without a handler, `logger.info` and `logger.warning` calls throughout the pipeline silently drop messages when the file is run directly as `__main__`. The orchestrator at the bottom uses `print(...)` for demo output, so the interactive run still shows progress, but the log lines sprinkled through each step never reach the console. A reader trying to understand what the code does by running it will not see the structured log output the author clearly intended to show.
- **How to fix:** Add a single line to the configuration block:
  ```python
  logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
  ```
  Or drop the `logger.setLevel` and let the root logger propagate. Either way, the rest of the logging code becomes visible without pulling in a full observability stack.

---

### Finding 9: Model IDs differ between pseudocode and Python

- **Severity:** NOTE
- **Location:** Pseudocode references `"anthropic.claude-haiku-4"` / `"anthropic.claude-sonnet-4"`; Python uses `"anthropic.claude-3-5-haiku-20241022-v1:0"` / `"anthropic.claude-3-5-sonnet-20241022-v2:0"`
- **Description:** Same pattern observed in Recipe 2.4. The pseudocode uses an illustrative family name while Python pins a currently-available model ID. The Python has a `TODO: verify the exact model IDs available in your region and account` and a comment about the `us.` cross-region inference profile prefix, which is good. A reader comparing the two side by side will still notice the gap.
- **How to fix:** Optionally add a one-line note in the pseudocode that Bedrock model IDs are versioned and the Python companion shows a specific working example. No code change required.

---

## Re-review checklist

When this review is addressed, a re-reviewer should verify:

1. The Spanish, Chinese, and Vietnamese `language_instruction` values render correctly when read by Python (`python -c "print('español')"` equivalent).
2. The orchestrator treats an exhausted regeneration loop as a reason to require clinician review, not as a reason to deliver.
3. The "DynamoDB Decimal gotcha" prose accurately describes what the example code does.
4. (Optional) Comprehend Medical truncation is byte-safe for UTF-8 inputs.
