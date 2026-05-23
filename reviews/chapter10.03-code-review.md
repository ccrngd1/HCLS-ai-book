# Code Review: Recipe 10.3 — Voice-to-Text for EHR Navigation (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.03-python-example.md`
- `chapter10.03-voice-to-text-ehr-navigation.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end against its mocks, faithfully implements the seven pseudocode steps, uses `Decimal` correctly for DynamoDB-bound numeric values, avoids hardcoded credentials, and treats the read-write boundary with the asymmetric rigor the prose demands. The boto3 API surface used for Lex V2, Bedrock, EventBridge, CloudWatch, and DynamoDB resource access is correctly named. The patient-slot disambiguation gate, idempotency check, and audit field set match the recipe's stated discipline. There is one notable WARNING about the streaming Transcribe API surface and a handful of NOTE-level improvements; none rise to ERROR severity, and the WARNING count is at the threshold (1) rather than over it.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 1 |
| NOTE     | 9 |

---

## WARNING Findings

### W1. Misleading boto3 streaming-Transcribe pattern in Step 2A and the `transcribe_client` declaration

**Files / sections:**
- "Configuration and Constants" section: `transcribe_client = boto3.client("transcribe", region_name=REGION, config=BOTO3_RETRY_CONFIG)`
- "Step 2: Stream Audio to ASR..." Step 2A comment: `# Production calls transcribe_client.start_stream_transcription with MediaSampleRateHertz=16000, LanguageCode="en-US"...`
- "Setup" prose: `transcribe:StartStreamTranscription for the streaming ASR session`

**What's wrong:**
`boto3.client("transcribe")` is the batch Transcribe client. It exposes `start_transcription_job`, `start_medical_transcription_job`, etc. It does **not** have a `start_stream_transcription` method. Streaming Transcribe is HTTP/2 / WebSocket-based and is wrapped by the standalone `amazon-transcribe` Python SDK (the `amazon-transcribe-streaming-sdk` package on PyPI), which is not a boto3 client. A learner who copies the comment's pattern into production will hit `AttributeError: 'Transcribe' object has no attribute 'start_stream_transcription'`.

The IAM permission name `transcribe:StartStreamTranscription` is correct (the underlying API operation has that IAM action), so that line is fine. The misleading bit is the implication that the boto3 transcribe client invokes it.

**How to fix (suggested wording for the next pass):**
- Replace the Step 2A comment with something like: `# Production uses the amazon-transcribe-streaming-sdk Python package (separate from boto3) to open an HTTP/2 stream against StartStreamTranscription. The SDK's TranscribeStreamingClient.start_stream_transcription returns an awaitable stream you push audio frames into.`
- Either remove the `transcribe_client = boto3.client("transcribe", ...)` line (since it's never used and the streaming SDK is what production needs) or rename it to clarify it's only for batch operations the demo does not use.
- Add a one-line "Setup" note: `# Streaming Transcribe requires `pip install amazon-transcribe`, which is a separate package from boto3.`

This is the single most likely place a reader gets stuck when they try to translate the demo into a real deployment, so it's worth tightening.

---

## NOTE Findings (improvements; not blocking)

### N1. Five intents in `INTENT_TAXONOMY` have no execution branch

`execute_command` handles `open_patient`, `show_recent_results`, `open_note`, and `navigate_section`. The other five configured intents (`navigate_schedule`, `go_back`, `scroll_down`, `scroll_up`, `log_out`) silently fall through to `execution_log["ehr_result"] = {"status": "unsupported_intent"}`. The demo doesn't exercise them, but a learner expanding the taxonomy will not see a clear "this is where to add a new branch" signpost. Suggest either: (a) add a stub branch for each remaining intent that emits an explicit `not_implemented_in_demo` status, or (b) add a comment above the `else` arm: `# Other intents (navigate_schedule, go_back, scroll_*, log_out) are configured in the taxonomy but their execution paths are out of scope for this demo. Add a branch here when extending.`

### N2. Module-level boto3 clients are constructed but never invoked in the demo

`transcribe_client`, `lex_client`, `bedrock_runtime`, `eventbridge_client`, `cloudwatch_client`, `secrets_client`, and the `dynamodb` resource are all created at import time. The demo uses only the mocks. The block's comment says they're declared "for warm-container reuse," which is true in production but means a learner is staring at a wall of unused setup code on first read. Consider adding a comment line at the top of the block: `# These boto3 clients are declared at module level so a real Lambda deployment reuses them across warm invocations. The demo below uses Mock* classes instead of these clients; the real clients are never invoked here.`

### N3. `from typing import Optional` is unused

`Optional` is imported but never referenced. Drop it or use it where it would help (e.g., the `_normalize_slot_date` return type).

### N4. The `0.6` per-word low-confidence threshold is a magic number

In `stream_audio_to_asr`:
```python
low_conf_count = sum(1 for c in word_confidences if c < 0.6)
```
There's already an `ASR_MAX_LOW_CONF_WORDS = 2` constant for the count. Add a sibling `ASR_PER_WORD_LOW_CONF_THRESHOLD = Decimal("0.6")` so the per-word threshold is named and tunable alongside the others.

### N5. `_resolve_patient_slot` declares but does not use `schedule`

```python
def _resolve_patient_slot(spoken_name, schedule):
    if not spoken_name:
        return []
    return ehr.search_schedule(clinician_id=None, name_query=spoken_name)
```
The `schedule` parameter is passed by the caller (`session_context["schedule"]`) but never read. Either pass it into `ehr.search_schedule` (so the resolution actually uses the per-session schedule the caller built) or drop the parameter. As-is, a reader is left wondering why the caller went to the trouble of preparing the schedule list.

### N6. Real Lex V2 slot shape differs from the mock's flat dict

`MockLex.recognize_text` returns slots as `{"patient": "Margaret Chen"}`. Real Lex V2 returns slots as nested objects:
```python
{"patient": {"value": {"originalValue": "...", "interpretedValue": "...", "resolvedValues": [...]}}}
```
The mock's docstring notes this in passing ("the demo flattens to the bits the pipeline uses"). For a learner, a stronger callout near the slot-handling code in `parse_command` would help. Suggest adding a comment after the `slots = dict(intent_obj.get("slots", {}) or {})` line: `# Real Lex V2 returns slots as nested {value: {interpretedValue: ...}} dicts. Production code reads slot["value"]["interpretedValue"] instead of slot["..."] directly.`

### N7. Bare `except Exception` in `execute_command` collapses two distinct failure modes

The pseudocode shows separate `CATCH ehr_api_error` and `CATCH timeout_error` branches. The Python collapses them into one `except Exception as err`, sets `status = "ehr_api_error"`, and emits a single user message. For teaching code this is acceptable, but: (a) timeouts and API errors warrant different recovery (retry vs. escalate), and (b) catching bare `Exception` masks programming errors in development. Consider catching specific exceptions (e.g., `botocore.exceptions.ClientError`, `botocore.exceptions.ReadTimeoutError`, `requests.Timeout`) and adding a comment that production distinguishes the two paths.

### N8. Idempotency check happens after execution, not before

In `audit_and_telemetry`, `find_recent_for_idempotency` is called *after* `execute_command` has run. For the read-only intents in the MVP demo this is fine (a duplicate read just hits the EHR twice). For write intents (none configured today, but the SIGNATURE_REQUIRED_INTENTS hook is there), this would let a duplicate command write twice before the duplicate is detected. The pseudocode's "production uses a conditional DynamoDB write" implies the check should gate execution. Add a comment in `audit_and_telemetry` clarifying: `# In production, the idempotency check moves UP the pipeline (before execute_command) for write-class intents, typically as a conditional PutItem on (clinician_id, session_id, transcript_hash) that fails closed.`

### N9. Low-ASR-confidence path produces no audit record

`stream_audio_to_asr` returns `{"proceed": False, "disposition": "asr_low_confidence"}` and `process_voice_command` returns immediately without invoking `audit_and_telemetry`. Scenario 4 in the demo therefore won't appear in `command_audit._records`. The Python is consistent with the pseudocode's Step 2 (which also returns early), but the recipe's Step 7 prose says "Every command is recorded with the full pipeline detail." This is a prose-vs-implementation gap, not a code defect: either the code should emit a minimal audit record on ASR-gate rejection (recommended for HIPAA-grade access trails), or the prose should clarify that ASR-rejected utterances aren't classified as commands and therefore aren't audited as such. Worth a follow-up between TechWriter and TechExpertReviewer.

---

## What I checked and confirmed is correct

- **boto3 API names are current and accurate** for Lex V2 (`lexv2-runtime`), Bedrock (`bedrock-runtime`), EventBridge (`events`), CloudWatch (`cloudwatch`), Secrets Manager (`secretsmanager`), and DynamoDB resource (`boto3.resource("dynamodb")`). The Bedrock production-call comment showing `modelId=BEDROCK_INFERENCE_PROFILE_ARN, body=..., contentType="application/json", accept="application/json"` matches the current `bedrock-runtime.invoke_model` signature.
- **Decimal usage for DynamoDB-bound values is correct.** `_to_decimal` recursively converts `float` through `Decimal(str(value))` (avoiding the float-to-Decimal precision pitfall), passes `Decimal` through unchanged, and walks dicts and lists. Confidence values are computed as Decimal before being placed in any DynamoDB-bound dict.
- **No S3 paths with leading slashes** (no S3 PutObject calls in the demo at all; only mentioned in comments).
- **No hardcoded credentials.** Module-level boto3 clients use the default credential resolution chain.
- **`audit_log` strips PHI fields** (`transcript`, `patient_demographics`, `slot_values_raw`) before structured logging. Operational fields (`command_id`, `clinician_id`, `intent`, `outcome`) are retained, which is appropriate.
- **Adaptive retry config** (`Config(retries={"max_attempts": 3, "mode": "adaptive"})`) is reasonable for the latency budget the recipe describes; the comment correctly explains why retry storms are operationally worse than fast failure here.
- **Transcript hashing** (`hashlib.sha256` on lowercased, stripped UTF-8) is a sensible idempotency key derivation that's case-insensitive, consistent across runs, and not reversible.
- **Session staleness check** (`SESSION_STALENESS_THRESHOLD_SECONDS`) and the EHR re-fetch on every command implement the "EHR is source of truth" discipline the prose calls out.
- **Patient slot disambiguation never silently picks** — zero candidates → `patient_not_found`, multi-candidate → `patient_ambiguous` with a prompt, single candidate → proceed. This matches the recipe's hard rule.
- **Asymmetric read-write confirmation rigor** is enforced: read auto-executes above `READ_AUTO_CONFIDENCE_THRESHOLD`, read-medium-confidence triggers a confirmation card with voice-confirm allowed, write triggers a confirmation card with voice-confirm explicitly disabled and a `signature_required` flag plumbed through. The "unknown classification → never auto-execute" default-deny is in place.
- **Versioning fields** (`bot_version`, `intent_taxonomy_version`, `threshold_config_version`, `read_write_rules_version`) are stamped on every audit record so historical commands can be reconstructed against the calibration that was active at the time.
- **The seven pseudocode steps map cleanly to seven Python functions** with the same step boundaries, the same decision points, and the same disposition strings (`asr_low_confidence`, `patient_not_found`, `patient_ambiguous`, `stale_session_confirm_patient`, `unclassified_no_execute`, `user_cancelled`, `unknown_intent`).
- **End-to-end demo runs deterministically.** Tracing through each of the five scenarios manually:
  1. `high_confidence_open_patient` → ASR avg 0.935, intent confidence 0.93 (≥ 0.85 read auto-threshold) → auto-executes `open_patient_chart` for Margaret Chen → audit record written.
  2. `open_operative_note_with_date` → date "october fourteenth" normalizes via `_normalize_slot_date` to `2026-10-14`, matches the seeded operative note → audit record written.
  3. `ambiguous_smith_disambiguation` → `search_schedule` returns two Robert Smiths → disambiguation prompt fires → audit record written with `patient_ambiguous` disposition.
  4. `low_asr_confidence_repeat` → all per-word confidences < 0.45, fails both gates → returns early with `asr_low_confidence` (see N9).
  5. `show_last_labs_for_current_patient` → no patient slot, uses EHR-current-patient context → fetches observations for Margaret Chen → audit record written.
- **The "Why This Isn't Production-Ready" section in the main recipe and the "Gap Between This and Production" appendix in the Python file** correctly flag the production-hardening concerns (per-Lambda IAM, KMS-CMK, VPC endpoints, SMART on FHIR launch, EHR audit-overlay integration, idempotency-before-execution, subgroup-stratified accuracy monitoring) so they're not expected to live in the example code itself.

---

## Verdict

**PASS** with one WARNING and nine NOTEs. The single WARNING (W1, the boto3 streaming-Transcribe pattern) is the most likely thing to trip up a reader translating to production and is worth fixing before publication; the NOTEs are pedagogical polish and can be addressed by the editor in the final pass.
