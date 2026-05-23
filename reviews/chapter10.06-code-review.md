# Code Review: Recipe 10.6 — Speech-to-Text for Telehealth Documentation (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.06-python-example.md`
- `chapter10.06-speech-to-text-telehealth-documentation.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end across both demo scenarios (Carl's Chime-SDK per-channel-separated visit with full draft-and-sign through chart updates, and Marisol's Spanish-language third-party-platform mixed-audio visit), correctly enforces the `Decimal`-not-`float` discipline for DynamoDB-bound numeric values, avoids hardcoded credentials, uses no leading slashes in S3 keys, and treats the recording-consent regime selection (with the behavioral-health-specific disclosure path), the streaming-and-batch parallel pipeline, the LLM-faithfulness gate (with a block-vs-flag severity classifier), the structured-extraction-with-explicit-confirmation gate, the side-by-side-review payload, and the cohort-stratified audit pipeline (with `audio_quality_band` and self-disclosed `age_band` on every cohort metric) with the rigor the recipe demands. The boto3 client and SDK-package usage is correctly distinguished: the standalone `amazon-transcribe` package is named for streaming, the boto3 `transcribe` client is used for batch and vocabulary management, and the IAM action names listed in Setup (`transcribe:StartStreamTranscription`, `transcribe:StartTranscriptionJob`, `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `polly:SynthesizeSpeech`, `chime:CreateMediaCapturePipeline`, `kinesisvideo:GetMedia`, `kms:Decrypt`, `kms:GenerateDataKey`, `states:StartExecution`) are correct.

The seven pseudocode steps map to seven Python entry points (`visit_start`, `run_streaming_asr`, `run_batch_transcription` + `reconcile_streaming_and_batch`, `generate_note_draft`, `extract_structured_fields`, `clinician_review_request` + `clinician_save_review` + `clinician_sign`, `audit_archive_and_telemetry`) with the same step boundaries, plus `run_visit_pipeline` and `run_demo` as orchestration.

There are two notable WARNINGs (one is a real demonstration bug where the mixed-audio path silently yields zero streaming events, contradicting the comment; one is shared with 10.05's W2 about the `response_format` parameter not existing on Bedrock InvokeModel) plus a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (2) is under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 11 |

---

## WARNING Findings

### W1. The mixed-audio streaming path silently yields zero events; Marisol's scenario streaming pipeline produces no transcript despite the comment claiming otherwise

**Files / sections:**
- "Mock Resources for the Demo" section, `MockTranscribeStreaming.stream_per_channel`:
  ```python
  def stream_per_channel(self, session_id, visit_id,
                         channel_role, language):
      segments = self._fixtures.get(visit_id, [])
      for segment in segments:
          if segment["speaker_role"] != channel_role:
              continue
          event = {...}
          yield event
  ```
- "Step 2" section, `run_streaming_asr` mixed-audio branch:
  ```python
  else:
      # Step 2C: mixed audio with diarization. A single
      # streaming session emits speaker labels alongside
      # the transcript; the demo's mock simulates the same
      # event flow by yielding both speakers from the mixed
      # channel.
      channels_to_process = [
          ("mixed", audio_capture_config["mixed_channel"]),
      ]
  ```
- Demo fixture for Marisol (visit_id_2) has segments with `"speaker_role"` of `"clinician"` and `"patient"`, never `"mixed"`.

**What's wrong:**
The comment in `run_streaming_asr` claims "the demo's mock simulates the same event flow by yielding both speakers from the mixed channel." It does not. `MockTranscribeStreaming.stream_per_channel` filters segments with `if segment["speaker_role"] != channel_role: continue`. For the mixed-audio path, `channel_role` is `"mixed"`, but no fixture segment has `"speaker_role" == "mixed"` — the Marisol fixture uses `"clinician"` and `"patient"`. The filter excludes every segment, the loop yields nothing, and the streaming pipeline records `streaming_segment_count == 0`, `avg_streaming_asr_confidence == Decimal("0.0")`.

The downstream batch pipeline still produces a transcript (because `transcribe_batch_mock.retrieve_transcript` returns the full fixture regardless of channel), so the demo "succeeds" end-to-end without an error. But the audit record for Marisol then carries `avg_streaming_asr_confidence: 0.0` and a missing live-display story, neither of which a reader can easily distinguish from "the streaming pipeline ran fine but the audio was very poor." `reconcile_streaming_and_batch` also silently produces `disagreement_count: 0` because the alignment loop sees no streaming text to compare against.

This is a misleading demonstration: the recipe's central architectural insight is that per-channel separated audio makes diarization trivial while mixed audio is the harder case. The Marisol scenario is the demo's only mixed-audio example, and it does not actually exercise the streaming path the architecture describes. A learner reading the demo output for Marisol thinks the mixed-audio path works; the audit record says zero streaming segments processed, which they may attribute to fixture choice rather than the silent mock failure.

**How to fix (suggested wording for the next pass):**
Two reasonable fixes:
- Make the mock yield all segments when `channel_role == "mixed"` (or, equivalently, when the fixture has no segments matching the channel role exactly): change the filter to
  ```python
  for segment in segments:
      if channel_role != "mixed" and segment["speaker_role"] != channel_role:
          continue
      event = {
          "session_id":      session_id,
          "speaker_role":    segment["speaker_role"],   # <-- preserve original role
          "transcript":      segment["text"],
          ...
      }
      yield event
  ```
  Note that the existing event also overwrites `speaker_role` with `channel_role`, which would also drop the per-segment role on the mixed path; the fix needs both changes so the diarized speakers are preserved.
- Or add a third Marisol fixture path keyed on `"mixed"` that simulates what acoustic diarization would yield, and update the comment to say "the mock plays back acoustically-diarized segments labeled `mixed_spk_0` and `mixed_spk_1` mapped to roles by `map_speaker_label_to_role`" — closing the loop with the otherwise-unused `map_speaker_label_to_role` helper (see N5).

Either way, the demo should produce non-zero `streaming_segment_count` for Marisol so the audit record reflects an exercised mixed-audio streaming pipeline.

---

### W2. The "JSON-schema response_format" comment misrepresents `bedrock_runtime.invoke_model`'s parameter surface

**Files / sections:**
- "Configuration and Constants" section, just after the extraction model id:
  ```python
  # Structured extraction uses the same Sonnet-class model as
  # note generation, but with a different prompt and a strict
  # JSON-schema response format.
  BEDROCK_EXTRACTION_MODEL_ID = (
      "anthropic.claude-3-5-sonnet-20240620-v1:0")
  ```
- "Mock Resources for the Demo" section, `MockBedrock.generate_note`:
  ```python
  def generate_note(self, visit_id, transcript, template,
                     guardrail_id):
      # Production: bedrock_runtime.invoke_model with a strict
      # JSON-schema response_format and the transcript and
      # template structure in the prompt context. The
      # guardrail is applied at runtime via the guardrail_id
      # parameter.
  ```
- "Gap to Production" section, "Real Bedrock invocation, prompt management, and inference profile" paragraph references a "strict-JSON output schema" via `invoke_model`.

**What's wrong:**
`bedrock_runtime.invoke_model` does not have a `response_format` parameter. Its surface is:

```python
bedrock_runtime.invoke_model(
    modelId="anthropic.claude-3-5-sonnet-20240620-v1:0",
    body=json.dumps({...model-specific request body...}),
    contentType="application/json",
    accept="application/json",
    guardrailIdentifier="...",   # optional
    guardrailVersion="...",      # optional
    trace="ENABLED" | "DISABLED" # optional
)
```

The `body` is a model-specific JSON request (Anthropic Claude expects `{"anthropic_version": "...", "messages": [...], "max_tokens": ..., "system": "..."}`); structured output for Anthropic models on Bedrock is enforced through tool-use (the `tools` field inside the body, with the structured-extraction schema declared as a tool definition) or through a system prompt that demands JSON. There is no top-level `response_format` parameter on `InvokeModel`. The Converse API (`bedrock_runtime.converse`) exposes more structured affordances (`additionalModelRequestFields`, `toolConfig`) but still does not surface a `response_format` parameter; OpenAI-style `response_format` would only apply if calling OpenAI-compatible models proxied through a third-party gateway.

This is the same defect as 10.05 W2; the misleading phrasing has propagated.

**How to fix:**
- Replace the `MockBedrock.generate_note` comment with: `# Production: bedrock_runtime.invoke_model with modelId pinned to the inference profile ARN and body containing the Anthropic Claude messages-and-system-prompt request. Structured output is enforced through Anthropic's tool-use (the tools field inside the body, with the note schema declared as a tool definition) or through a system prompt that demands JSON; there is no top-level response_format parameter on InvokeModel.`
- Apply the same correction to `MockBedrock.check_faithfulness` and `MockBedrock.extract_higher_level_fields`, both of which carry similar phrasings.
- In the "Configuration and Constants" comment near `BEDROCK_EXTRACTION_MODEL_ID`, change "with a different prompt and a strict JSON-schema response format" to "with a different prompt and a strict JSON tool-use response shape."
- In the Gap section's "Real Bedrock invocation" paragraph, replace "a strict-JSON output schema" with "a tool-use definition that enforces the JSON note schema in the response."

---

## NOTE Findings (improvements; not blocking)

### N1. Mock method `infer_icd10cm` and IAM action `comprehendmedical:InferICD10CM` are correct, but the real boto3 method name is `infer_icd10_cm` (with underscore between "icd10" and "cm")

In `MockComprehendMedical`:
```python
def infer_icd10cm(self, text):
    self.invocations.append({"type": "infer_icd10cm",
                             "text_len": len(text)})
    return self._fixtures.get("infer_icd10cm", {"Entities": []})
```

And in `extract_structured_fields`:
```python
icd_response = comprehend_mock.infer_icd10cm(text=full_text)
```

The real boto3 client method on `comprehend_medical = boto3.client("comprehendmedical")` is `comprehend_medical.infer_icd10_cm(Text=...)`, with an underscore between `icd10` and `cm` (matching the IAM action `InferICD10CM` and the API operation name). The mock-method naming differs from the real client's snake_case rendering. A learner replacing the mock with the real client will hit `AttributeError: 'ComprehendMedical' object has no attribute 'infer_icd10cm'` and have to discover the underscored variant.

The other Comprehend Medical mock method (`infer_rx_norm`) matches the real boto3 method name exactly. Suggest renaming the mock method (and the fixture key) to `infer_icd10_cm` for consistency, or adding a comment near the mock signature: `# Real boto3 method is comprehend_medical.infer_icd10_cm (with underscore between icd10 and cm) and expects Text=... in PascalCase. The mock uses snake_case throughout the demo for readability.`

### N2. The mixed-audio path discards the per-segment speaker role and substitutes the channel name

Even if W1 is fixed and the fixture flows through, `MockTranscribeStreaming.stream_per_channel` builds the event with:
```python
event = {
    "session_id":      session_id,
    "speaker_role":    channel_role,
    ...
}
```

For the per-channel-separated path this is correct (channel_role is "clinician" or "patient"). For the mixed-audio path, `channel_role` is "mixed" and the per-segment role from the fixture (`"clinician"`, `"patient"`) is discarded. Combined with W1, this means even after fixing the filter, the live-display segments for Marisol would be labeled `speaker_role: "mixed"` rather than the diarized roles.

The fix is to have the event carry `segment["speaker_role"]` rather than the channel name on the mixed path:
```python
event = {
    ...
    "speaker_role":    segment["speaker_role"],
    ...
}
```

This is consistent with how production diarization works: the streaming Transcribe session with `show_speaker_label=true` emits per-segment speaker labels alongside the transcript, and the application maps them to roles. The `map_speaker_label_to_role` helper (currently dead code; see N5) is the right place to do that mapping.

### N3. Module-level boto3 clients are constructed but never invoked in the demo

`dynamodb`, `s3_client`, `transcribe_batch`, `bedrock_runtime`, `comprehend_medical`, `polly_client`, `eventbridge_client`, `cloudwatch_client`, `secrets_client`, and `stepfunctions_client` are all constructed at import time. The demo uses only the mocks. The block's comment correctly explains the warm-container reuse rationale ("Reused across Lambda invocations in warm containers"), but a learner is staring at ten lines of unused client setup on first read. Same issue as 10.03 N2, 10.04 N6, and 10.05 N3. Suggest the same one-line clarification: `# These boto3 clients are declared at module level so a real Lambda deployment reuses them across warm invocations. The demo below uses Mock* classes instead; the real clients are never invoked here.`

(Acceptable as-is for teaching code, but worth noting for consistency with the chapter's style.)

### N4. Several Bedrock and Polly configuration constants are defined but never referenced

These are all declared in "Configuration and Constants" but never read by any function or mock in the demo:
- `BEDROCK_NOTE_GENERATION_PROFILE_ARN`
- `BEDROCK_FAITHFULNESS_PROFILE_ARN`
- `BEDROCK_EXTRACTION_MODEL_ID` (the *MODEL_ID* variant — the *PROFILE_ARN* sibling above is also unused)
- `POLLY_VOICE_BY_LANGUAGE`
- `POLLY_LEXICON_NAMES`
- `INSTITUTIONAL_LANGUAGE_MODEL` (referenced only in commented-out production-pseudocode comments at lines 1072 and 1180)
- `TELEHEALTH_NOTE_GUARDRAIL_VERSION` (only `TELEHEALTH_NOTE_GUARDRAIL_ID` is passed through to the mock; production needs both)

A learner trying to follow the configuration-to-call-site path is left without an anchor for any of these. Same N-level pattern as 10.05 N5. Suggest either:
- Plumbing them through to the mocks (e.g., `MockBedrock.generate_note` could record which `inference_profile_arn` it was "called with" for demo visibility, even though the response is fixture-driven), or
- Adding a one-line comment near the constants block: `# These are the model, inference-profile, voice, lexicon, language-model, and guardrail-version identifiers a real bedrock_runtime.invoke_model / polly_client.synthesize_speech / transcribe_batch.start_transcription_job call would use. The mocks below do not consult them; production reads them at call time and pins each invocation to the named asset.`

The Polly voice and lexicon constants are particularly misleading: the recipe describes Polly as an optional patient-facing audio summary feature, but the demo never exercises it (no `MockPolly` is even defined), and the only place these constants surface is the constants block.

### N5. `map_speaker_label_to_role` is defined but never invoked

The function is declared at the top of "Step 2" with a thoughtful docstring about timing heuristics, voiceprint enrollment, and visit-context labeling. It is never called by any function in the demo. The mocks always provide `speaker_role` directly (because, per W1, the mixed-audio path is broken), so the role-mapping branch never fires.

This is the helper that would translate acoustic-diarization labels (`spk_0`, `spk_1`, `spk_2`) to clinical roles (`clinician`, `patient`, `family_member`) in the mixed-audio case. Closing the W1/N2 fix with a real call into `map_speaker_label_to_role` (e.g., the mock yields `speaker_label: "spk_0"` on the mixed path and `run_streaming_asr` calls `map_speaker_label_to_role(...)` to get the role) would make this helper part of the visible pipeline. Without that, the demo has dead code with a useful docstring and a learner has to imagine where it would be called.

### N6. The Comprehend Medical mock does not differentiate by visit; both visits get the same RxNorm and ICD-10 fixtures

In `run_demo`:
```python
comprehend_mock = MockComprehendMedical({
    "infer_rx_norm":  rx_norm_fixture,
    "infer_icd10cm":  icd10_fixture,
    "detect_entities": {"Entities": []},
})
```

The fixtures are keyed by API-method name only, not by `visit_id`. When `extract_structured_fields` is called for Marisol (visit_id_2), the mock returns Carl's gabapentin and conditions (`peripheral neuropathy`, `type 2 diabetes`), even though Marisol's transcript never mentions any of them. Marisol's scenario in the demo passes `review_decisions=[]`, so nothing gets confirmed and no chart writes happen, which masks the issue in the run-time output — but the audit record for Marisol will show structured extractions of medications and conditions from a transcript that did not contain them.

This is the same N6 pattern from prior reviews where the mock returns fixture data divorced from the actual input. Two fixes:
- Key the mock fixture by visit_id (similar to how `MockTranscribeStreaming` and `MockTranscribeBatch` already do), so each visit gets its own `infer_rx_norm` and `infer_icd10cm` response.
- Or document the limitation in a comment at the mock's class docstring: `# Demo simplification: fixtures are keyed by API method only, not by visit_id. Both demo scenarios receive the same RxNorm and ICD-10 fixture; production calls go through the real text and produce per-visit-specific extractions.`

The first fix is more useful pedagogically because it parallels the per-visit fixture pattern the other mocks already use.

### N7. `clinician_sign` does not handle `patient_reported_vitals` or `patient_reported_allergies` categories

`clinician_save_review` builds `confirmed_extractions` for eight categories:
```python
for category in ("medications", "conditions",
                 "orders_placed", "labs_requested",
                 "imaging_requested",
                 "follow_up_appointments",
                 "patient_reported_vitals",
                 "patient_reported_allergies"):
```

`clinician_sign` then iterates `confirmed_extractions` and dispatches per-category EHR writes:
```python
for confirmed_item in confirmed:
    category = confirmed_item.get("category")
    if category == "medications":
        ...
    elif category == "conditions":
        ...
    elif category in ("labs_requested", "imaging_requested"):
        ...
    elif category == "follow_up_appointments":
        ...
```

`patient_reported_vitals` and `patient_reported_allergies` (and also `orders_placed`) are silently dropped: a confirmed allergy or vital from the structured-extraction step would be marked `clinician_confirmed: True` in the note state, but no `ehr.apply_structured_update(...)` call would fire for it, and the audit record would show it as confirmed-but-not-applied without flagging the gap.

The demo doesn't exercise this path (Carl's confirmations are all medications, conditions, and labs; Marisol confirms nothing), so the gap is invisible. A reader extending the demo to confirm a patient-reported allergy will silently lose the chart write. Suggest either:
- Adding the missing branches:
  ```python
  elif category == "patient_reported_allergies":
      ehr.apply_structured_update(
          patient_id=patient_id,
          update_kind="allergy",
          payload=confirmed_item)
  elif category == "patient_reported_vitals":
      ehr.apply_structured_update(
          patient_id=patient_id,
          update_kind="vital",
          payload=confirmed_item)
  elif category == "orders_placed":
      ehr.apply_structured_update(
          patient_id=patient_id,
          update_kind="order",
          payload=confirmed_item)
  ```
- Or adding an `else` branch that logs the unhandled category so the gap is loud:
  ```python
  else:
      audit_log({"event_type": "UNHANDLED_CONFIRMED_CATEGORY",
                 "category": category, "session_id": session_id})
  ```

The recipe's Step 5B explicitly enumerates `patient_reported_vitals` and `patient_reported_allergies` as Bedrock-extracted higher-level fields, so dropping them from the chart write contradicts the architecture's own Step 5/Step 6 contract.

### N8. Mock parameter names use snake_case; real boto3 expects PascalCase

The mocks accept Pythonic snake_case parameters:
```python
s3_store.put_object(bucket=AUDIT_ARCHIVE_BUCKET, key=..., body=..., metadata=...)
ehr.write_document_reference(patient_id=..., encounter_id=..., document_content=..., author=..., signed_at=...)
transcribe_batch_mock.start_transcription_job(visit_id=..., audio_uri=..., language=..., per_channel=...)
```

Real boto3 expects PascalCase:
```python
s3_client.put_object(Bucket=..., Key=..., Body=..., Metadata=...)
transcribe_batch.start_transcription_job(
    TranscriptionJobName=..., LanguageCode=..., Media={"MediaFileUri": ...}, Settings={...})
```

Same N10 / N8 pattern from 10.05 / 10.04 reviews. Suggest adding a comment near the mock signatures: `# Real boto3 expects PascalCase parameter names (Bucket, Key, Body, Metadata, TranscriptionJobName, LanguageCode, MediaFileUri). The mock uses snake_case so the demo reads naturally; production callers translate at the boundary.`

### N9. Real Bedrock InvokeModel uses `guardrailIdentifier` and `guardrailVersion`; the mock parameter is named `guardrail_id` (Pythonic) and the Version constant is unreferenced

`MockBedrock.generate_note` accepts `guardrail_id`. The real `bedrock_runtime.invoke_model` takes both `guardrailIdentifier` (camelCase) and `guardrailVersion`. The Python file defines:
```python
TELEHEALTH_NOTE_GUARDRAIL_ID = "guardrail-78901"
TELEHEALTH_NOTE_GUARDRAIL_VERSION = "2"
```

But only `TELEHEALTH_NOTE_GUARDRAIL_ID` is passed to the mock; `TELEHEALTH_NOTE_GUARDRAIL_VERSION` is never read (see N4). A reader who replaces the mock with the real client will hit two issues simultaneously: the parameter name (`guardrail_id` vs `guardrailIdentifier`) and the missing version pin.

Suggest adding the version to the mock call signature and a comment: `# Mock signature uses snake_case for readability. Real bedrock_runtime.invoke_model takes guardrailIdentifier=... and guardrailVersion=...; both are required for a pinned guardrail invocation. Pinning the version (rather than letting the runtime resolve to the latest) is what makes guardrail behavior reproducible across deployments.`

### N10. Bedrock mock returns `{"body": json.dumps(response)}` and the caller does `json.loads(response["body"])`; real `invoke_model` returns a `StreamingBody` requiring `.read()`

Three places use this pattern:
```python
note_response = bedrock_mock.generate_note(...)
note_body = json.loads(note_response["body"])
```
```python
response = bedrock_mock.check_faithfulness(...)
body = json.loads(response["body"])
```
```python
higher_level_response = bedrock_mock.extract_higher_level_fields(...)
higher_level = json.loads(higher_level_response["body"])
```

Real boto3 returns the body as a `botocore.response.StreamingBody`, not a string:
```python
response = bedrock_runtime.invoke_model(modelId=..., body=...)
body_bytes = response["body"].read()      # <-- StreamingBody.read()
parsed = json.loads(body_bytes)
```

A reader who replaces the mock with the real client will hit a `TypeError` because `json.loads` can't decode a `StreamingBody`. This is the same response-shape divergence flagged in 10.05 W1 (for the Knowledge Base API), but for InvokeModel it is a NOTE rather than a WARNING because the structural shape (`response["body"]` containing the model output) is at least consistent. Suggest adding a one-line comment at one of the call sites: `# Real bedrock_runtime.invoke_model returns response["body"] as a botocore StreamingBody; production calls json.loads(response["body"].read()) to consume it. The mock returns it as a JSON string for demo simplicity.`

### N11. `lookup_speaker_role_for_offset` uses a 30-second window; structured-extraction speaker attribution can be wrong near section boundaries

In `extract_structured_fields`, every coded medication and condition gets a `speaker_role` derived from:
```python
def lookup_speaker_role_for_offset(transcript, offset_seconds):
    for segment in transcript.get("segments", []):
        ts = segment.get("timestamp", "00:00:00")
        ...
        if abs(seg_seconds - offset_seconds) < 30:
            return segment.get("speaker_role")
    return "unknown"
```

The 30-second window is wide. In Carl's fixture, the segment at `00:01:42` (patient describing tingling) and the segment at `00:01:58` (wife reporting unsteadiness) are 16 seconds apart, both within the window of any extraction in that span. The function returns the first match in iteration order (which is also fixture-insertion order), so the patient-vs-family-member distinction is fragile. The recipe's Step 5 explicitly calls this out: "speaker-role-aware extraction (the patient's history is processed differently from the clinician's plan)" and "a medication mentioned by the patient describing their history is processed differently from a medication the clinician verbalizes as part of the plan."

Two reasonable fixes:
- Tighten the window (e.g., `< 5` or even `< 1` if fixture timestamps are accurate to the second), and fall back to "unknown" when no segment falls within the tighter window.
- Iterate to find the *closest* segment (the one minimizing `abs(seg_seconds - offset_seconds)`) rather than the *first* segment within 30 seconds.

The function is fine for Carl's specific fixture (the single gabapentin offset at 662 maps cleanly to the single 00:11:02 clinician segment), but a learner extending the fixture density runs into ambiguity quickly. Worth a comment at minimum: `# The 30-second window is loose; production uses a tighter window plus a closest-match tiebreaker because telehealth conversations have multiple speaker turns per minute and a too-wide window misattributes mentions near section boundaries.`

---

## What I checked and confirmed is correct

- **boto3 client and SDK-package usage is correctly distinguished.** The Python file says explicitly in the Setup section that "Streaming Transcribe (and Transcribe Medical) is HTTP/2 and is not exposed through the regular boto3 transcribe client. The streaming API is wrapped by a separate Python package: `pip install amazon-transcribe`," and the Step 2 comments point at `TranscribeStreamingClient` from the standalone SDK. The boto3 `transcribe` client is used (in comments) only for `start_transcription_job`. This closes the W1 from the 10.03 and 10.04 reviews where the streaming-vs-batch-client confusion was the dominant defect; 10.06 has it right.
- **boto3 API names are accurate** for the batch transcribe client (`transcribe`, with `start_transcription_job`, `create_vocabulary`, `create_language_model`), Bedrock Runtime (`bedrock-runtime` with `invoke_model`), Comprehend Medical (`comprehendmedical` with `infer_rx_norm`, modulo the `infer_icd10_cm` underscore noted in N1), Polly (`polly` with `synthesize_speech` and `get_lexicon` per the IAM action list), EventBridge (`events` with `put_events`), CloudWatch (`cloudwatch` with `put_metric_data`), Secrets Manager (`secretsmanager` with `get_secret_value`), Step Functions (`stepfunctions` with `start_execution`), and the DynamoDB resource (`boto3.resource("dynamodb")`). Chime SDK and Kinesis Video Streams are referenced only in comments and the Setup IAM list.
- **Decimal usage for DynamoDB-bound values is correct.** `_to_decimal` recursively converts `float` through `Decimal(str(value))` (avoiding the float-to-Decimal precision pitfall), passes `Decimal` through unchanged, and walks dicts and lists. ASR confidence values are computed as Decimal at entry (the fixture segments use `Decimal("0.96")`, `Decimal("0.94")`, etc.). Faithfulness scores get wrapped as `Decimal(str(body.get("score", 0.0)))`. Comprehend Medical entity scores are wrapped at `Decimal(str(entity.get("Score", 0.85)))`. The streaming-confidence sum, batch-confidence sum, and avg-confidence calculation all use `Decimal` arithmetic. The `extraction_acceptance_rate` is computed as `Decimal(str(...))`. The `audit_record` dict is wrapped through `_to_decimal` before persistence. The `visit_state.put`, `transcript_state.update`, and `note_state.put` calls that include numeric values are wrapped through `_to_decimal`. No bare `float` slips through to a state-table write. (CloudWatch metrics are converted back to `float` via `float(...)` at the boundary, which is correct because CloudWatch's `put_metric_data` expects `Value=<float>`, not Decimal.)
- **No S3 keys with leading slashes.** All `s3_store.put_object` calls use keys like `f"{session_id}/canonical_transcript.json"` and `f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{session_id}.json"`. Each starts with the prefix segment, never a `/`. The audio-archive reference `f"s3://{AUDIO_BUCKET}/{session_context['session_id']}/audio.pcm"` likewise has no leading slash on the key portion.
- **No hardcoded credentials.** Module-level boto3 clients use the default credential resolution chain. The synthetic patient identifiers (`pt-44219`, `pt-77310`), encounter IDs (`encounter-2026-05-23-0411`, `-0412`), clinician IDs (`clinician-okonkwo`, `clinician-vega`), inference profile ARNs (account `000000000000`), guardrail IDs (`guardrail-78901`), and the institutional vocabulary/language-model names are obviously synthetic. The Heads-up callout explicitly flags the names, MRNs, RxNorm codes, and ICD-10 codes as fictional.
- **`audit_log` strips PHI fields** (`verbatim_transcript`, `generated_note_text`, `patient_demographics`, `structured_decisions_raw`) before structured logging and substitutes lengths for the dropped string fields. Operational fields (`session_id`, `visit_id`, `consent_regime`, `language`, `faithfulness_score`, `severity`, `event_type`) are retained appropriately.
- **Adaptive retry config is split between streaming (low max_attempts) and batch (higher max_attempts)** — the Python uses `Config(retries={"max_attempts": 2, "mode": "adaptive"})` for streaming (because the in-visit display latency budget is tight) and `Config(retries={"max_attempts": 5, "mode": "adaptive"})` for batch (because the post-visit budget is looser). The split is well-motivated and the comment explains the reasoning. The streaming-config object is declared but the streaming clients are built externally via the standalone SDK, so it isn't actually applied to anything in the demo; the batch config is applied to all the boto3 clients. Worth a small note inside an N-level finding next time, but acceptable as-is.
- **Recording-consent regime selection works as the recipe describes.** `determine_consent_regime` follows the stricter-regime-wins rule for cross-jurisdiction visits: behavioral-health visits always require explicit acknowledgment, and any all-party-consent state on either side (patient or institution) triggers the all-party disclosure. The `requires_acknowledgment` gate in `visit_start` correctly disables the feature when the patient declines. The TODO comment about verifying the all-party-consent state list against the Reporters Committee for Freedom of the Press source is a fair acknowledgment of the legal-team-reviewed asset that production maintains.
- **The faithfulness severity classifier (`determine_faithfulness_severity`) implements the layered policy correctly.** Score below `FAITHFULNESS_BLOCK_THRESHOLD` (`0.65`) blocks regardless of failure type. Severe failure types (`claim_without_citation`, `contradiction_with_transcript`, `added_clinical_recommendation`) block independent of score. Score below `FAITHFULNESS_PASS_THRESHOLD` (`0.88`) flags. Otherwise pass. This matches the recipe's "the institution decides which behavior is appropriate per check type" and "faithfulness is a structural risk, not a side issue" framing.
- **Faithfulness block correctly routes to manual-documentation fallback.** When `severity == "block"`, `generate_note_draft` writes a note-state record with `draft_available: False`, `block_reason: "faithfulness_block"`, `fallback: "manual_documentation"`, and the failed-check details for clinical-quality review, and returns `{"draft_available": False, "reason": "faithfulness_block", "fallback": "manual_documentation"}`. `run_visit_pipeline` checks the flag and short-circuits to `audit_archive_and_telemetry` rather than continuing into structured extraction or clinician review. The audit record reflects the gap.
- **Structured-extraction confirmation discipline is enforced.** Every extraction produced by `extract_structured_fields` is initialized with `clinician_confirmed: False`. `clinician_save_review` flips it to `True` only when an explicit decision says so; rejections and missing decisions both stay `False`. `clinician_sign` then iterates `confirmed_extractions` (not the raw structured-extractions list) and applies chart updates only for the confirmed items, modulo N7's missing categories.
- **Cohort-stratified CloudWatch metrics carry `specialty`, `language`, `visit_type`, and `audio_quality_band` dimensions on every audit-relevant metric** (`SessionsStarted`, `StreamingASRConfidence`, `FaithfulnessScore`, `FaithfulnessFailures`, `NoteGenerationInvocations`, `StructuredExtractionsGenerated`, `ExtractionsConfirmed`, `ExtractionsRejected`, `NotesSigned`, `EditDistanceDraftToFinal`, `ExtractionAcceptanceRate`, `FinalFaithfulnessScore`). The `_bucket_audio_quality` helper banks SNR into `high`/`medium`/`low`/`unknown` for cohort segmentation. The `audit_record["cohort_axes"]` includes `age_band` only when the patient self-discloses (the demo uses `"65_74"` for Carl and `"55_64"` for Marisol explicitly via the `patient_age_band` parameter), which is the discipline the prose calls out: "self-disclosed during portal enrollment. Inferred demographic labels for protected classes are explicitly not used."
- **Versioning fields** (`STREAMING_ASR_MODEL_VERSION`, `BATCH_ASR_MODEL_VERSION`, `NOTE_GENERATION_PROMPT_VERSION`, `FAITHFULNESS_PROMPT_VERSION`, `STRUCTURED_EXTRACTION_VERSION`, `TEMPLATE_LIBRARY_VERSION`) are stamped on the visit-state record at `visit_start` and carried through to `audit_record` so a future audit can reconstruct which configuration produced any given visit. This matches the prose's "a future audit reconstructs which configuration was active when a particular visit was processed."
- **The seven pseudocode steps map to seven Python entry points** with the same step boundaries: `visit_start` (Step 1, with `determine_consent_regime`, `select_disclosure_text`, and `configure_audio_capture` as helpers), `run_streaming_asr` + `handle_streaming_event` (Step 2), `run_batch_transcription` + `align_by_timestamp` + `reconcile_streaming_and_batch` (Step 3), `generate_note_draft` + `lookup_note_template` + `determine_faithfulness_severity` + `run_faithfulness_check` (Step 4), `extract_structured_fields` + `lookup_speaker_role_for_offset` + `extract_context_snippet` (Step 5), `clinician_review_request` + `extract_low_confidence_segments` + `extract_uncertain_speaker_segments` + `clinician_save_review` + `clinician_sign` (Step 6), and `audit_archive_and_telemetry` + `compute_edit_distance` (Step 7). The pseudocode-to-Python correspondence is faithful with the deviations called out in W1, N5, N6, and N7.
- **End-to-end demo runs deterministically across both scenarios.** Tracing through:
  1. Carl (visit_id_1) — Chime SDK, per-channel separated, English, primary care, age band 65-74. Consent regime `one_party_consent` (VA is one-party, neither the patient nor institution is in an all-party state), feature enabled. Streaming yields 5 segments split across clinician/patient/family_member channels, average confidence around 0.928. Batch transcript reconciled with 0 disagreements (the fixture clones streaming segments). Note draft generated with three sections (subjective, assessment, plan) and three citations. Faithfulness score 0.94 (above pass threshold of 0.88), severity `pass`. Structured extraction yields 1 medication (gabapentin RxNorm 25480), 2 conditions (peripheral neuropathy G62.9, type 2 diabetes E11.9), 2 lab requests (HbA1c, Vitamin B12), 1 follow-up (6 weeks). Clinician confirms 5 of those (the medication, both conditions, both labs); the follow-up is left unconfirmed because no decision is provided for it. Note signed via mock EHR producing a `doc-xxxxxxxxxx` ID. Three structured updates applied to chart: gabapentin medication, peripheral-neuropathy problem, type-2-diabetes problem. (The labs are in the confirmed list but, per the per-category dispatch, fall under `labs_requested`/`imaging_requested`, which is handled correctly.) Audit record written.
  2. Marisol (visit_id_2) — third-party video, mixed audio, Spanish (`es-US`), primary care, age band 55-64, jurisdiction CA (all-party consent). Consent regime `all_party_consent` because CA is in `ALL_PARTY_CONSENT_STATES`, feature enabled (the demo passes `consent_acknowledged=True`). Streaming yields **0 segments** because of W1 (the bug). Batch transcript reconciled with 3 segments and 0 disagreements (because the streaming side is empty). Note draft generated with empty `sections: {}` and `citations: []` from the fixture, faithfulness score 0.91 with one annotation flagging speaker-uncertain segment, severity `pass`. Structured extraction yields the same fixture as Carl (per N6), but Marisol's `review_decisions` are empty so nothing is confirmed. Note signed via mock EHR producing a `doc-xxxxxxxxxx` ID with no chart updates. Audit record written. Despite the W1 bug, the pipeline does not error.
- **The "Why This Isn't Production-Ready" section in the main recipe and the "The Gap Between This and Production" appendix in the Python file** correctly flag the production-hardening concerns (real telehealth-platform integration, real Transcribe streaming wiring through `amazon-transcribe-streaming-sdk`, real custom-vocabulary management, real Bedrock invocation with versioned prompts and inference profile pinning, real Bedrock Guardrails configuration, real Comprehend Medical wiring with the three-API merge, per-Lambda IAM, real DynamoDB and KMS, S3 lifecycle and Object Lock, VPC endpoints, Step Functions orchestration, per-specialty template library with named clinical-informatics owners, layered faithfulness program, faithfulness regression testing on prompt and model updates, per-cohort accuracy and adoption monitoring with launch gates, multi-state recording-consent compliance, behavioral-health-specific privacy controls, audio retention with privacy-officer review, EHR integration depth and write-back validation, disaster recovery and degraded-mode operation, idempotency, performance under burst load, vendor evaluation rigor, audit retention and legal hold, cost monitoring per specialty and cohort, telehealth-platform audio-quality monitoring, clinician training and adoption, testing). These are not expected to live in the example code itself.

---

## Verdict

**PASS** with two WARNINGs and eleven NOTEs. The two WARNINGs (W1: the mixed-audio streaming path silently yields zero events, contradicting the comment; W2: the `response_format` reference does not match `bedrock_runtime.invoke_model`'s parameter surface) are both worth fixing before publication: W1 leaves Marisol's mixed-audio scenario as a silently broken demonstration of the architecturally-harder case the recipe centers on, and W2 misleads readers about how to enforce structured LLM output on Bedrock for Anthropic models. The NOTEs are pedagogical polish and can be addressed by the editor in the final pass.

The seven-step pseudocode-to-Python correspondence is faithful and complete (with the identified gaps in mixed-audio streaming, the unused `map_speaker_label_to_role` helper, the fixture-keyed-by-method-only Comprehend Medical mock, and the missing `clinician_sign` branches for vitals/allergies/orders acknowledged in the prose or worth a one-line comment). The Decimal-not-float discipline, the no-leading-slash S3 keys, the streaming-vs-batch boto3-vs-standalone-SDK distinction (cleanly handled, unlike 10.03 and 10.04), the runtime faithfulness check with block-vs-flag severity classifier, the structured-extraction-with-explicit-confirmation discipline, the cohort-stratified audit pipeline that excludes inferred protected-class labels and includes audio-quality banding, the recording-consent stricter-regime-wins logic with the behavioral-health-specific disclosure path, and the faithfulness-block fallback to manual documentation are all in place and correctly demonstrated by the two scenarios.
