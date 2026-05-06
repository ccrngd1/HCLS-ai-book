# Code Review: Recipe 2.1

## Summary

The Python companion is well-structured, pedagogically sound, and technically accurate. The Bedrock Converse API call uses correct parameter names, correct request structure, and correct response parsing. DynamoDB handling properly uses `Decimal` for numeric values and the modern `datetime.now(timezone.utc)` form. The code flows logically from classification through generation to storage, building understanding at each step. Comments explain the "why" effectively. No runtime-breaking bugs found.

---

## Verdict: PASS

---

## Issues

### Issue 1: Broad `except Exception` in `load_system_prompt` Could Mask Configuration Errors

- **File:** Python companion (`chapter02.01-python-example.md`)
- **Location:** `load_system_prompt` function (Step 3)
- **Severity:** NOTE
- **Description:** The `except Exception` block catches everything including `NoSuchBucket`, `NoSuchKey`, and credential errors. For a teaching example this is fine (the comment acknowledges it), but a reader might not realize that silently falling back to a default prompt when the S3 bucket name is misconfigured could produce confusing behavior: the pipeline "works" but uses a stale prompt. A brief inline comment noting that production code should distinguish between "bucket doesn't exist" (configuration error, should crash) and "transient network issue" (should fall back) would help learners understand the tradeoff.
- **Suggested fix:** Add a comment like: `# In production, catch botocore.exceptions.ClientError and check error code. A missing bucket is a config bug (raise), a timeout is transient (fall back).`

---

### Issue 2: Pseudocode Includes `provider_preferences` Parameter; Python Omits It

- **File:** Python companion (`chapter02.01-python-example.md`)
- **Location:** `build_prompt` function (Step 3)
- **Severity:** NOTE
- **Description:** The main recipe's pseudocode defines `build_prompt(message_text, intent, context, provider_preferences)` with a section that appends provider-specific tone guidance. The Python version takes only 3 parameters and omits provider preferences entirely. The "Gap to Production" section does call this out explicitly ("Provider-specific tone tuning is worth the effort"), so this is an intentional simplification. However, a one-line comment in the Python function noting the omission would help readers connect the dots between the pseudocode and the simplified implementation.
- **Suggested fix:** Add a comment in `build_prompt`: `# The pseudocode also accepts provider_preferences for tone tuning. Omitted here for simplicity; see "Gap to Production" section.`

---

### Issue 3: Model ID May Require Inference Profile in Some Regions

- **File:** Python companion (`chapter02.01-python-example.md`)
- **Location:** Config section, `MODEL_ID` constant
- **Severity:** NOTE
- **Description:** The model ID `anthropic.claude-3-haiku-20240307-v1:0` is the correct format for Bedrock model IDs. However, as of early 2025, some regions require using cross-region inference profiles (e.g., `us.anthropic.claude-3-haiku-20240307-v1:0`) rather than direct model IDs for on-demand throughput. A reader following this example in a region where the direct model ID is no longer supported will get a `ValidationException`. Since this is a teaching example and the model ID format is correct, this is informational only.
- **Suggested fix:** Add a comment near `MODEL_ID`: `# If you get a ValidationException, your region may require an inference profile ID instead (e.g., "us.anthropic.claude-3-haiku-20240307-v1:0").`

---

## Pseudocode vs. Python Consistency

The Python implementation faithfully follows the pseudocode's 5-step pipeline with no structural mismatches:

**Step 1 (classify_message):** Both use keyword matching with first-match-wins semantics. The Python adds a few more keywords per intent category (e.g., "running low", "pills", "pharmacy" for refill). This is appropriate enrichment for the developer-facing reference.

**Step 2 (gather_context):** Both pull intent-specific context. The Python uses mock data (clearly documented) while the pseudocode references EHR/FHIR calls. The data shapes match: medications as lists of dicts, appointments with date/time/type, etc.

**Step 3 (build_prompt):** The pseudocode includes `provider_preferences`; the Python omits it (noted above as Issue 2). Otherwise the prompt assembly logic matches: system prompt loaded from S3 with fallback, context formatted as readable text, user prompt assembled with intent + context + message.

**Step 4 (generate_draft):** Both call the model with the same parameters (temperature 0.3, max_tokens 300, top_p 0.9, guardrail applied). The Python correctly uses the Converse API's `stopReason` field to detect guardrail intervention, which is the proper implementation of the pseudocode's abstract `guardrail_action == "BLOCKED"` check.

**Step 5 (store_draft):** The Python improves on the pseudocode by handling the blocked case explicitly (setting `draft_text = None` and `draft_status = "needs_manual_draft"`). The pseudocode's `store_draft` doesn't show this branch, which would actually fail if `draft_result.draft_text` were accessed on a blocked result. The Python's handling is correct and pedagogically clearer. The pseudocode also includes `emit metric "DraftGenerated"` which the Python omits; this is acceptable since CloudWatch metrics emission is a production concern.

---

## AWS SDK Accuracy

- **`bedrock_client.converse()`**: Correct method name for the Converse API. ✓
- **`modelId` parameter**: Correct parameter name (camelCase in boto3). ✓
- **`messages` structure**: Correct format with `role` and `content` array containing `{"text": ...}`. ✓
- **`system` parameter**: Correct format as array of `[{"text": ...}]`. ✓
- **`inferenceConfig`**: Correct parameter names (`maxTokens`, `temperature`, `topP`). ✓
- **`guardrailConfig`**: Correct with `guardrailIdentifier`, `guardrailVersion`, `trace`. ✓
- **Response parsing**: `response["stopReason"]` and `response["output"]["message"]["content"][0]["text"]` match the documented response structure. ✓
- **`stopReason` value**: `"guardrail_intervened"` is a valid enum value per the API docs. ✓
- **S3 `get_object`**: Correct method, correct parameter names (`Bucket`, `Key`), correct response parsing (`response["Body"].read()`). ✓
- **DynamoDB `put_item`**: Correct via resource layer `table.put_item(Item=record)`. ✓
- **DynamoDB Decimal handling**: `Decimal(str(TEMPERATURE))` is the correct pattern. ✓
- **S3 key**: `"prompts/system-prompt-v2.txt"` has no leading slash. ✓

---

## Comment Quality

Comments are excellent throughout. They explain:
- Why keyword matching is sufficient (and when to upgrade)
- Why targeted context retrieval matters (tokens, cost, security)
- Why temperature is set low for healthcare
- Why the system prompt constraints exist
- Why context_used is stored (transparency + debugging)
- Why Converse API is preferred over InvokeModel

The tone matches the cookbook's voice: practical, opinionated, engineer-to-engineer.

---

## Healthcare-Specific Requirements

- **Human-in-the-loop**: Enforced by design. Drafts go to `pending_review` status, never sent directly. ✓
- **PHI logging**: Logger comments explicitly warn against logging PHI. ✓
- **Guardrail integration**: Applied inline with the generation call. ✓
- **Blocked message handling**: Gracefully routes to manual drafting. ✓
- **Audit trail**: Records model_id, prompt_version, guardrail_id, timestamp per draft. ✓
- **No clinical recommendations in system prompt**: Explicitly constrained. ✓
