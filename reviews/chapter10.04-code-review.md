# Code Review: Recipe 10.4 — Medical Transcription / Dictation (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.04-python-example.md`
- `chapter10.04-medical-transcription-dictation.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end against its mocks across all three demo scenarios (clean primary-care followup, faithfulness-fail with hedging removed, critical-error laterality flip), correctly enforces the `Decimal`-not-`float` discipline for DynamoDB-bound numeric values, avoids hardcoded credentials, uses no leading slashes in S3 keys, and treats the LLM-faithfulness gate, the structured-field-suggestion-with-explicit-confirmation gate, and the read-edit-sign workflow with the rigor the recipe demands. The boto3 API surface used for Comprehend Medical, Bedrock Runtime, EventBridge, CloudWatch, and Secrets Manager is correctly named. The critical-error detection flags the laterality flip in scenario 3 even though the faithfulness check in that scenario passes — exactly the second-line-of-defense behavior the prose calls out.

There are two notable WARNINGs (one shared with 10.03 around the boto3 streaming-Transcribe pattern, one new pseudocode-to-Python gap where the Step 3 structural events are computed but never applied in Step 4) and a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (2) is under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 11 |

---

## WARNING Findings

### W1. Misleading boto3 streaming-Transcribe-Medical pattern in setup, Step 1E, and Step 2A

**Files / sections:**
- "Configuration and Constants": `transcribe_client = boto3.client("transcribe", region_name=REGION, config=BOTO3_RETRY_CONFIG)`
- "Step 1: Open the Dictation Session" comment in Step 1E:
  ```python
  # In production this is:
  #   transcribe_client.start_medical_stream_transcription(
  #       LanguageCode="en-US",
  #       MediaSampleRateHertz=16000,
  #       Specialty=specialty,
  #       Type="DICTATION",
  #       VocabularyName=vocabulary_name,
  #       ShowSpeakerLabels=False,
  #       EnablePartialResultsStabilization=True,
  #       PartialResultsStability="high",
  #   )
  ```
- "Step 2: Stream Audio to ASR" Step 2A comment:
  ```python
  # Production calls transcribe_client.start_medical_stream_transcription(...)
  ```
- "The Gap Between This and Production" section, "Real Transcribe Medical streaming wiring" paragraph references the same pattern.

**What's wrong:**
`boto3.client("transcribe")` is the batch Transcribe client. It exposes `start_transcription_job`, `start_medical_transcription_job`, `create_medical_vocabulary`, etc., but it does **not** have a `start_medical_stream_transcription` method. Streaming Transcribe Medical is HTTP/2-based and is wrapped by the standalone `amazon-transcribe-streaming-sdk` Python package on PyPI (imported as `from amazon_transcribe.client import TranscribeStreamingClient`), which is separate from boto3. A learner who copies the comments verbatim into production hits `AttributeError: 'Transcribe' object has no attribute 'start_medical_stream_transcription'`.

The IAM permission name `transcribe:StartMedicalStreamTranscription` (in the Setup section) is correct, because the underlying API operation has that IAM action. The misleading bit is the implication that the boto3 transcribe client invokes it directly.

This is the same defect 10.03 W1 flagged for the non-medical streaming variant; the mistake has propagated to 10.04.

**How to fix (suggested wording for the next pass):**
- Replace the Step 2A comment with: `# Production uses the amazon-transcribe-streaming-sdk Python package (separate from boto3) to open an HTTP/2 stream against StartMedicalStreamTranscription. The SDK's TranscribeStreamingClient.start_medical_stream_transcription returns an awaitable stream the audio frames push into.`
- Either remove the `transcribe_client = boto3.client("transcribe", ...)` line (the streaming SDK is what production needs and the demo never calls boto3 transcribe) or rename it (e.g., `transcribe_batch_client`) with a comment that it's only for batch and vocabulary-management operations the demo does not exercise.
- Add a Setup-section line: `# Streaming Transcribe Medical requires `pip install amazon-transcribe`, which is a separate package from boto3.`
- Update the "Real Transcribe Medical streaming wiring" paragraph in the Gap section to clarify the streaming SDK dependency rather than implying the boto3 client.

---

### W2. The pseudocode's `apply_structural_events` is missing from Step 4 in Python; structural events are computed in Step 3 but never used

**Files / sections:**
- Main recipe pseudocode, Step 4 (`format_and_structure`):
  ```
  // Step 4B: apply structural events to direct content
  // into template sections. The cursor moves between
  // sections based on navigation commands; content
  // dictated between commands fills the section the
  // cursor is currently in.
  template_with_content = apply_structural_events(
      template: template,
      content: formatted_content,
      events: structural_events)
  ```
- Python `format_and_structure` (only the content_segments are read):
  ```python
  content_text = " ".join(
      s["text"] for s in disambiguated["content_segments"])
  rule_text = _apply_punctuation_and_capitalization(content_text)
  rule_text = _canonicalize_numbers(rule_text)
  rule_text = _detect_section_headers(rule_text, template)
  ```
- `disambiguated["structural_events"]` from `disambiguate_commands` is computed and metric-emitted but is never read by any downstream stage.

**What's wrong:**
The recipe's Step 3 frames command disambiguation as the mechanism by which navigation commands ("go to assessment," "next field," "new paragraph") direct content into specific template sections. Step 4 in the pseudocode then explicitly applies those structural events to the template via `apply_structural_events(...)`. The Python skips this step entirely: the `structural_events` list is populated, audited, and emitted as a CloudWatch metric, but the formatter never consumes it. Section headers are detected post hoc by regex on the raw text (`_detect_section_headers` looking for "history of present illness colon" patterns), which is the rule-based fallback, not the command-driven path the architecture describes.

The demo gets away with this because the test fixtures embed section markers as literal text ("history of present illness colon...") and because the fixtures use a 0.05-second word-gap that prevents `_segment_by_pauses` from ever isolating a command segment (see N1 below). A learner reading the demo output sees `content segments: 1, structural events: 0` for every scenario, looks at how the formatted output still got section headers, and is left to guess which path produced them.

This is a misleading architectural gap: a reader who carries the demo into production might wire up `disambiguate_commands` and `format_and_structure` per the Python and end up with a system where commands are recognized but never executed against the template.

**How to fix:**
- Add a small `apply_structural_events(template, content, events)` helper that walks the events in time order, applies navigation events to a section cursor, and emits each content segment into the section under the cursor when the event-stream is interleaved correctly. Even a 30-line implementation that handles `new_paragraph`, `go_to_section`, and the navigation events would close the loop.
- Or, if the demo is intentionally keeping the rule-based path only, add an explicit comment at the top of `format_and_structure`:
  ```
  # The pseudocode's Step 4B applies structural_events to
  # navigate between template sections. The demo collapses
  # all structural events into the rule-based section-header
  # detector below for simplicity. In production, the
  # navigation events drive a section cursor that decides
  # which template field the content goes into; see the
  # main recipe's Step 4 pseudocode for the full pattern.
  ```
- Either way, surface the gap so a learner does not silently inherit a partial implementation.

---

## NOTE Findings (improvements; not blocking)

### N1. Demo fixture timings collapse `_segment_by_pauses` into a single segment, so the disambiguation logic is never exercised in the demo output

In `run_demo`, every scenario builds word-level items with this timing pattern:
```python
{"start_time": i * 0.4, "end_time": i * 0.4 + 0.35, ...}
```
Word `i+1` starts at `0.4(i+1) = 0.4i + 0.4`; word `i` ends at `0.4i + 0.35`. The gap is always `0.05` seconds. The `COMMAND_PAUSE_THRESHOLD_SECONDS` is `0.4`. As a result `_segment_by_pauses` never splits, the entire transcript becomes one segment, and `disambiguate_commands` cannot match either the explicit-prefix path (`segment_text.startswith("computer ")`) or the implicit-match path (`segment_text in COMMAND_VOCABULARY`). Every scenario reports `structural events: 0` regardless of whether commands are present.

This is related to W2 but distinct: even after W2 is closed, the demo's fixtures need at least one scenario where the timings produce a valid command segment. Suggest adding a fourth scenario where the verbatim has an explicit-prefix command ("...exam comma <pause> computer new paragraph <pause> assessment colon...") with the corresponding word items showing a `>= 0.4`s gap before and after the command, so the disambiguation actually fires and the audit shows `structural events: 1` (or more). This makes the teaching value of Step 3 visible.

### N2. Idempotency check happens after ASR, so duplicate dictations still incur ASR cost

In `stream_audio_and_transcribe` (Step 2F), the idempotency check via `find_recent_for_idempotency` runs after `transcribe_session` has already executed:
```python
asr_result = transcribe_med.transcribe_session(session_id)
...
duplicate = dictation_meta.find_recent_for_idempotency(
    clinician_id=session_context["clinician_id"],
    transcript_hash=transcript_hash,
    window_seconds=DUPLICATE_DICTATION_WINDOW_SECONDS)
```
Transcribe Medical streaming is the most expensive component in the pipeline. For dictation, the production conditional-write idempotency key is `(clinician_id, session_id, transcript_hash)` — but transcript_hash isn't known until ASR finishes, so there's an inherent ordering dilemma. A useful addition would be a comment near the duplicate check: `# Production also enforces idempotency at session_open via a conditional PutItem on (clinician_id, session_id) so a re-fired dictation_start request from a flaky client does not open two parallel ASR streams. The transcript-hash check below catches the rarer case where two distinct sessions produce the same audio.`

### N3. `_canonicalize_numbers` runs after `_apply_punctuation_and_capitalization`, so any sentence-initial number word is already capitalized and the regex (case-sensitive) silently misses it

The function order in `format_and_structure`:
```python
rule_text = _apply_punctuation_and_capitalization(content_text)
rule_text = _canonicalize_numbers(rule_text)
```
`_apply_punctuation_and_capitalization` capitalizes any letter following a sentence boundary. `_canonicalize_numbers` matches lowercase number words only. A dictation that begins "fifty four year old male presents with..." gets capitalized to "Fifty four year old male presents with..." then the regex misses the age form and the formatted note keeps the spelled-out number. The demo's verbatims happen to have number words mid-sentence ("rated five out of ten") so the issue does not surface, but a primary-care followup that opens with the age commonly does start mid-sentence-initial. Either run number canonicalization before capitalization (the cleanest fix) or make the regex case-insensitive with `re.IGNORECASE`.

### N4. `detect_critical_errors` uses set membership, not span analysis; co-occurrences hide the substitution

In `detect_critical_errors`:
```python
verbatim_set = set(verbatim_words)
formatted_set = set(formatted_words)
...
if (before in verbatim_set
        and after in formatted_set
        and before not in formatted_set):
```
This works for scenario 3 (verbatim has "left" only, formatted has "right" only) but misses the realistic case where the formatted note has both words. Example: verbatim says "pain in the left lower quadrant" and the formatted note says "pain in the right lower quadrant; the left side is unremarkable" — the substitution flipped the clinical claim, but both "left" and "right" are now in `formatted_set`, and the check skips the alert. A span-aware comparison aligned by token position is what production needs. The function is fine for the teaching demo, but worth a comment: `# This set-membership check works for clean substitutions where the original word is fully replaced. Production uses a span-aligned comparison so substitutions in mixed-laterality notes are still flagged.`

### N5. Allergy structured-field decisions are extracted but never written

In `extract_structured_fields` the loop captures `allergies = []` from `entity.Category == "ALLERGY"`. The loop populates it, but `allergies` is never appended to `suggestions` or `cross_check_warnings` and never reaches `handoff_to_ehr`. The demo doesn't include any allergies in the entity fixture, so the gap is silent. A reader extending the system to handle allergies will be confused that the local variable is built but never consumed. Either remove the unused branch with a `# Allergy handling deferred — see N5 follow-up` comment, or finish the wiring (a small addition to `suggestions` and a corresponding `ehr.add_allergy(...)` branch in `handoff_to_ehr`).

### N6. Multiple module-level boto3 clients are constructed but never invoked in the demo

`transcribe_client`, `bedrock_runtime`, `comprehend_medical`, `eventbridge_client`, `cloudwatch_client`, `secrets_client`, `stepfunctions_client`, and the `dynamodb` resource are all constructed at import. The demo uses only the mocks. The block is justified by "Module-level clients. Reused across Lambda invocations in warm containers" but a learner is staring at unused setup code on first read. Same issue as 10.03 N2; consider adding the same one-line clarification: `# These boto3 clients are declared at module level so a real Lambda deployment reuses them across warm invocations. The demo below uses Mock* classes instead; the real clients are never invoked here.`

### N7. `from typing import Optional` is unused

Imported but never referenced. Same as 10.03 N3. Drop the import or use it on a return-type hint where it would help (e.g., `_resolve_*` helpers).

### N8. `process_dictation` is dead code in the demo

`process_dictation` is defined in "Putting It All Together" as the canonical end-to-end flow, but `run_demo` does not call it. Instead, `run_demo` orchestrates all 8 stages manually so the per-scenario transcript fixture can be primed under the just-generated `session_id`. A reader seeing the function presented as the canonical pipeline and then never invoked is left wondering. Either:
- Add a comment above `run_demo`: `# run_demo re-orchestrates the stages manually (rather than calling process_dictation) because the per-scenario transcript fixtures need to be injected under the session_id that open_dictation_session generates. process_dictation above is the canonical wiring; the demo's manual orchestration is purely for fixture-injection convenience.`
- Or refactor so `process_dictation` accepts a transcript-fixture dict and the demo calls it with per-scenario fixtures.

### N9. Faithfulness-fail does not log the original LLM response or the warnings, only their count

In the dictation-metadata update from `format_and_structure`:
```python
"faithfulness_score":          faithfulness_score,
"faithfulness_warning_count":  len(faithfulness_warnings),
```
The actual warning records (with `type`, `before`, `after`, `severity`) are returned in the function's response dict but never persisted to the audit archive. Scenario 2 produces two warnings (`hedging_removed`, `claim_strengthened`); after the run, the audit record stores only `faithfulness_warning_count: 2` and the warnings themselves are gone. For a clinical-quality officer reconstructing why a particular dictation flipped to the rule-based fallback, the warning details are exactly what they need. Suggest persisting the warnings into the formatted-note S3 archive (alongside the rule-based draft and the LLM alternative) so they're retrievable for forensic review.

### N10. `unresolved_critical_count` is logged but signature is never actually blocked

In `render_review_and_capture_decisions`, Step 6C:
```python
if unresolved_critical:
    audit_log({
        "event_type":              "SIGNATURE_BLOCKED_CRITICAL_ALERT",
        ...
    })
    # Production blocks signature; the demo logs and
    # continues so the audit record reflects the gap.
```
The comment acknowledges the gap, but the audit-event name is `SIGNATURE_BLOCKED_CRITICAL_ALERT` even though signature is not actually blocked — it proceeds through `client.get_signature()` regardless. Scenario 3's run will emit this event, then hand off to the EHR with a critical-error alert flagged but unresolved, which is exactly the failure mode the prose says is unacceptable. For the demo's truthfulness, suggest renaming the event to `SIGNATURE_PROCEED_DESPITE_CRITICAL_ALERT` (or similar) and adjusting the comment so a reader does not infer the demo blocks signature when it doesn't.

### N11. Comprehend Medical mock conflates `detect_entities_v2`, `infer_rx_norm`, and `infer_icd10_cm` into one fixture; production needs three calls and a merge

The mock returns Entities with `RxNormCode`, `ICD10Code`, and full attribute lists in a single response. In production:
- `comprehend_medical.detect_entities_v2(Text=...)` returns entities and attributes but no RxNorm/ICD-10 codes.
- `comprehend_medical.infer_rx_norm(Text=...)` returns medication entities with `RxNormConcepts`.
- `comprehend_medical.infer_icd10_cm(Text=...)` returns condition entities with `ICD10CMConcepts`.

The three responses must be merged on `BeginOffset`/`EndOffset`. The Step 5A comment acknowledges this:
```python
# Production calls
#   comprehend_medical.detect_entities_v2(Text=verbatim)
# plus comprehend_medical.infer_rx_norm(Text=verbatim) and
# comprehend_medical.infer_icd10_cm(Text=verbatim) for
# coded linking. The mock returns the union as a single
# entity list.
```
This is a fair acknowledgment, but a stronger callout for learners would help. Suggest adding a one-line note to the response-shape comment: `# Real responses also use different top-level keys: detect_entities_v2 returns "Entities", infer_rx_norm returns "Entities" with "RxNormConcepts", and infer_icd10_cm returns "Entities" with "ICD10CMConcepts". The merge is by character-offset overlap.`

---

## What I checked and confirmed is correct

- **boto3 API names are accurate** for Bedrock Runtime (`bedrock-runtime` with `invoke_model`), Comprehend Medical (`comprehendmedical` with `detect_entities_v2`, `infer_rx_norm`, `infer_icd10_cm`), EventBridge (`events` with `put_events`), CloudWatch (`cloudwatch` with `put_metric_data`), Secrets Manager (`secretsmanager` with `get_secret_value`), Step Functions (`stepfunctions` with `start_execution`), and the DynamoDB resource (`boto3.resource("dynamodb")`). The single API-surface defect is the streaming-Transcribe-Medical pattern flagged in W1.
- **Decimal usage for DynamoDB-bound values is correct.** `_to_decimal` recursively converts `float` through `Decimal(str(value))` (avoiding the float-to-Decimal precision pitfall), passes `Decimal` through unchanged, and walks dicts and lists. Confidence values are computed as Decimal before any DynamoDB-bound dict construction. The `audit_record` is wrapped in `_to_decimal` before persistence. No bare `float` slips through to a `dictation_meta.put`, `dictation_meta.update`, or `session_state.put`.
- **No S3 paths with leading slashes.** All `s3_store.put_object` calls use keys like `2026/05/23/dict-xxxxxxxx.flac`, `transcripts/2026/05/23/...`, `notes/2026/05/23/...`, `audit/2026/05/23/...`. Each starts with the prefix segment, never a `/`.
- **No hardcoded credentials.** The module-level boto3 clients use the default credential resolution chain. The single placeholder string `"<placeholder access token>"` in the SMART on FHIR launch context fixture is clearly a placeholder.
- **`audit_log` strips PHI fields** (`verbatim_transcript`, `formatted_text`, `patient_demographics`, `structured_decisions_raw`) before structured logging and substitutes lengths for the dropped string fields. Operational fields (session_id, clinician_id, specialty, formatter_path, faithfulness_score) are retained appropriately.
- **Adaptive retry config** (`Config(retries={"max_attempts": 4, "mode": "adaptive"})`) is reasonable for the dictation latency budget and the prose's "few seconds of additional formatting time is acceptable" framing.
- **Transcript hashing** (`hashlib.sha256` on lowercased, stripped UTF-8) is a sensible idempotency key derivation: case-insensitive, consistent across runs, irreversible.
- **SMART on FHIR launch staleness check** (`age > timedelta(hours=8)`) is in place at session open, with an explicit re-launch error path.
- **Critical-error detection fires on scenario 3** even though that scenario's faithfulness check returns 0.95 (above the 0.92 threshold). This is the exact second-line-of-defense behavior the prose calls out: faithfulness models can miss laterality flips, so the explicit critical-error pair list is the safety net. The demo correctly demonstrates this layered detection.
- **Faithfulness threshold gating works asymmetrically.** Scenario 1 (faith 0.98 ≥ 0.92) takes the LLM-formatted output. Scenario 2 (faith 0.62 < 0.92) falls back to the rule-based draft and attaches the LLM version as `llm_alternative`. Scenario 3 (faith 0.95 ≥ 0.92) takes the LLM output, and the critical-error detector catches what the faithfulness check missed.
- **Structured-field accept/reject discipline** is enforced in `handoff_to_ehr`: rejected suggestions never produce EHR writes; the structured_results record reflects `rejected_no_write` as a distinct state from `applied`. Scenario 1 accepts the atorvastatin (not in chart) and rejects the chest-pain ICD-10 suggestion (already documented in HPI); both decisions flow through correctly to the audit record.
- **Versioning fields** (`asr_model_version`, `rule_formatter_version`, `llm_formatter_prompt_version`, `faithfulness_prompt_version`, `critical_error_rules_version`, `structured_extraction_version`) are stamped on the dictation-metadata record at session open and carried through to the final audit record, so a future review can reconstruct which calibration produced a given dictation.
- **The eight pseudocode steps map to eight Python functions** with the same step boundaries and the same named status transitions in the dictation-metadata record (`session_open` → `transcribed` → `formatted` → `structured_extracted` → `signed_and_handed_off`). The Step 4 gap (W2) is the only meaningful divergence.
- **End-to-end demo runs deterministically across all three scenarios.** Tracing through:
  1. `standard_primary_care_dictation` → ASR avg 0.94, all words pass low-confidence gate, LLM formatter returns the formatted note, faithfulness 0.98 ≥ 0.92 so LLM output used, Comprehend Medical extracts 3 entities (lisinopril already in chart, atorvastatin new, condition new), clinician accepts the two medications and rejects the condition, EHR creates note `doc-000001` and applies one structured write (atorvastatin). Audit record written.
  2. `faithfulness_fail_hedging_removed` → faithfulness score 0.62, two warnings (`hedging_removed` high-severity, `claim_strengthened` medium-severity), formatter falls back to the rule-based draft and attaches the LLM version as alternative, no Comprehend Medical fixture matches so 0 suggestions, signature captured, EHR creates note `doc-000002` with no structured writes. Audit record reflects `formatter_path: rule_based_fallback_after_faithfulness_fail`.
  3. `critical_error_laterality_flip` → faithfulness score 0.95 (passes), but `detect_critical_errors` finds the `(left, right)` pair flipped between verbatim and formatted, so 1 critical-error alert raised. The demo logs `SIGNATURE_BLOCKED_CRITICAL_ALERT` (despite N10) and proceeds, EHR creates note `doc-000003`. Audit record reflects 1 unresolved critical alert — the forensic trace is intact even though the signature flow is not.
- **The "Why This Isn't Production-Ready" section in the main recipe and the "The Gap Between This and Production" appendix in the Python file** correctly flag the production-hardening concerns (per-Lambda IAM, KMS-CMK, VPC endpoints, real SMART on FHIR launch, real Step Functions orchestration, real per-clinician adaptation pipeline, critical-error rules ownership, faithfulness offline evaluation program, subgroup-stratified accuracy monitoring, audio retention policy with privacy-officer review) so they are not expected to live in the example code itself.

---

## Verdict

**PASS** with two WARNINGs and eleven NOTEs. The two WARNINGs are both worth fixing before publication: W1 (the boto3 streaming-Transcribe pattern) is the most likely thing to trip up a reader translating to production, and W2 (the missing `apply_structural_events` step) leaves a meaningful pseudocode-to-Python gap that obscures how the architecture's command-driven section navigation actually works. The NOTEs are pedagogical polish and can be addressed by the editor in the final pass. The 8-step structure, the Decimal discipline, the no-leading-slash S3 keys, the explicit-confirmation rigor for structured-field updates, the faithfulness-with-rule-based-fallback gate, and the critical-error second-line-of-defense detection are all in place and correctly demonstrated by the three scenarios.
