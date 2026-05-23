# Code Review: Recipe 10.7 — Ambient Clinical Documentation (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.07-python-example.md`
- `chapter10.07-ambient-clinical-documentation.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end across both demo scenarios (Carl's three-speaker primary-care visit with full draft-and-sign through chart updates, and Marcus's lower-audio-quality Spanish-language follow-up with a flagged speaker-uncertainty segment), correctly enforces the `Decimal`-not-`float` discipline for DynamoDB-bound numeric values via the `_to_decimal` helper, avoids hardcoded credentials, uses no leading slashes in S3 keys (`{session_id}/canonical_transcript.json`, `{session_id}/healthscribe_note_draft.json`, `{session_id}/rendered_note.json`, `audit/YYYY/MM/DD/{session_id}.json`, `audio/{session_id}/encounter.pcm` are all properly relative), and treats the recording-consent regime selection (with the behavioral-health-explicit disclosure path), the in-room audio path with per-room device-type and audio-quality monitoring, the streaming-and-batch parallel pipeline, the LLM-faithfulness gate (with a block-vs-flag-vs-pass severity classifier driven by both score threshold and per-check-type severity), the structured-extraction-with-explicit-confirmation gate (with speaker-role-aware filtering and supporting transcript context), the side-by-side-review payload (with confidence highlights, speaker-uncertainty flags, and bystander segment surfacing), and the cohort-stratified audit pipeline (with `audio_quality_band`, `device_type`, `room_id`, and self-disclosed `age_band` on every cohort dimension) with the rigor the recipe demands. The seven pseudocode steps map cleanly to seven Python entry points (`encounter_start`, `stream_audio_to_healthscribe`, `run_batch_healthscribe`, `render_institutional_note`, `extract_structured_fields`, `clinician_review_request` + `clinician_save_review` + `clinician_sign`, `audit_archive_and_telemetry`) plus `run_encounter_pipeline` and `run_demo` as orchestration. The IAM action names listed in Setup (`transcribe:StartMedicalScribeJob`, `transcribe:GetMedicalScribeJob`, `transcribe:StartStreamTranscription`, `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `chime:CreateMediaCapturePipeline`, `kinesisvideo:GetMedia`, `kms:Decrypt`, `kms:GenerateDataKey`, `states:StartExecution`) are correct.

There are two notable WARNINGs (one is a confirmed-against-AWS-docs `NoteTemplate` enum mismatch where the demo passes custom institutional template IDs to a parameter that only accepts a fixed list of HealthScribe-defined values; one is a confirmed-against-AWS-docs `max_speaker_labels` parameter that does not exist on `start_stream_transcription` and would fail the streaming call) plus a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (2) is under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 8 |

---

## WARNING Findings

### W1. `NoteTemplate` accepts a fixed enum of HealthScribe-defined values, not arbitrary institutional template IDs; the production-code comment in `run_batch_healthscribe` would fail with `BadRequestException` if copied verbatim

**Files / sections:**
- "Step 3" section, `run_batch_healthscribe` production-pattern comment block:
  ```python
  # In production:
  #   transcribe_batch.start_medical_scribe_job(
  #       MedicalScribeJobName=f"{session_id}-batch",
  #       Media={"MediaFileUri": audio_archive_ref},
  #       OutputBucketName=HEALTHSCRIBE_OUTPUT_BUCKET,
  #       OutputEncryptionKMSKeyId=OUTPUT_KMS_KEY_ARN,
  #       DataAccessRoleArn=
  #           HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN,
  #       Settings={
  #           ...
  #           "ClinicalNoteGenerationSettings": {
  #               "NoteTemplate": template["id"],
  #           },
  #       })
  ```
- "Configuration and Constants" section, `DEFAULT_TEMPLATES`:
  ```python
  DEFAULT_TEMPLATES = {
      "primary-care-soap-v3": {
          "id":       "primary-care-soap-v3",
          ...},
      "behavioral-health-progress-v2": {
          "id":       "behavioral-health-progress-v2",
          ...},
      "geriatric-comprehensive-v1": {
          "id":       "geriatric-comprehensive-v1",
          ...},
  }
  ```
- "Step 3" section, `select_template` returns these IDs as-is, and `run_batch_healthscribe` passes `template_id=template["id"]` to the mock.

**What's wrong:**
The `Settings.ClinicalNoteGenerationSettings.NoteTemplate` field on `StartMedicalScribeJob` is an enum that accepts exactly these values (per the [HealthScribe Clinical Documentation](https://docs.aws.amazon.com/transcribe/latest/dg/health-scribe-insights.html) reference): `HISTORY_AND_PHYSICAL` (default), `GIRPP`, `BIRP`, `SIRP`, `DAP`, `BH_SOAP`, `PH_SOAP`. Passing a custom string like `"primary-care-soap-v3"` produces a `BadRequestException` from the service; the call never starts a job.

A learner reading the production-pattern comment, then looking at `select_template` returning a `DEFAULT_TEMPLATES["primary-care-soap-v3"]` whose `id` field flows directly into the `NoteTemplate` parameter, would build a pipeline that fails at the first batch HealthScribe submission. The architectural intent of the recipe is correct: institutions have their own per-specialty templates, and HealthScribe's defaults are not the institutional final form. But that institutional templating happens in the Bedrock-rendering step (Step 4), not by passing a custom string to HealthScribe; HealthScribe should be selected with the closest-fit built-in template from the enum, and the institutional rendering happens downstream.

The recipe text itself has the same issue: in the pseudocode in `chapter10.07-ambient-clinical-documentation.md` Step 3C, `clinical_note_generation_settings: { note_template: select_template(...) }` shows the same pattern with the same custom-ID expectation. The mismatch propagates from the recipe to the Python companion.

**How to fix (suggested wording for the next pass):**
Two reasonable fixes:
- Change `select_template` (and the `DEFAULT_TEMPLATES` registry) to return both an institutional-template descriptor (the per-specialty structure used by the Bedrock-rendering step) and a separately-named `healthscribe_note_template` field that is one of the seven enum values. Pass only the enum value to the `start_medical_scribe_job` call:
  ```python
  DEFAULT_TEMPLATES = {
      "primary-care-soap-v3": {
          "id":          "primary-care-soap-v3",
          "specialty":   "family_medicine",
          "structure":   "SOAP",
          "sections":    ["subjective", "objective",
                          "assessment", "plan"],
          # The closest-fit HealthScribe built-in template;
          # the institutional template is applied downstream
          # via Bedrock in Step 4.
          "healthscribe_note_template": "HISTORY_AND_PHYSICAL",
      },
      "behavioral-health-progress-v2": {
          ...
          "healthscribe_note_template": "BH_SOAP",
      },
      "geriatric-comprehensive-v1": {
          ...
          "healthscribe_note_template": "HISTORY_AND_PHYSICAL",
      },
  }
  ```
  And in the production-pattern comment in `run_batch_healthscribe`:
  ```python
  # ...
  #       Settings={
  #           ...
  #           "ClinicalNoteGenerationSettings": {
  #               "NoteTemplate": template[
  #                   "healthscribe_note_template"],
  #           },
  #       })
  ```
- Or, simpler, keep the existing `template["id"]` for the institutional template and just hardwire `"NoteTemplate": "HISTORY_AND_PHYSICAL"` in the comment, with a sentence noting that HealthScribe's seven built-in templates (`HISTORY_AND_PHYSICAL`, `GIRPP`, `BIRP`, `SIRP`, `DAP`, `BH_SOAP`, `PH_SOAP`) are the only valid values and that institutional formatting happens in the Bedrock-rendering step. Either fix is defensible; the first is more architecturally honest, the second is simpler.

The same correction should be applied to the Step 3C pseudocode in the main recipe (`chapter10.07-ambient-clinical-documentation.md`).

**Severity rationale:** WARNING because the production-pattern comment teaches a parameter shape that fails at runtime against the real API. It is not an ERROR because the demo's Python actually runs (the mock accepts whatever string is passed); the error only surfaces if a learner translates the comment into real boto3.

---

### W2. `max_speaker_labels` is not a valid parameter for `start_stream_transcription`; the streaming-pattern comment in `stream_audio_to_healthscribe` would fail at the boto3 layer

**Files / sections:**
- "Step 2" section, `stream_audio_to_healthscribe` production-pattern comment block:
  ```python
  # In production:
  #   client = TranscribeStreamingClient(region=REGION)
  #   stream = await client.start_stream_transcription(
  #       language_code=language,
  #       media_sample_rate_hz=audio_capture_config["sample_rate"],
  #       media_encoding=audio_capture_config["encoding"],
  #       vocabulary_name=INSTITUTIONAL_VOCABULARY,
  #       language_model_name=INSTITUTIONAL_LANGUAGE_MODEL,
  #       show_speaker_label=True,
  #       max_speaker_labels=audio_capture_config[
  #           "expected_speaker_count"],
  #       enable_partial_results_stabilization=True)
  ```

**What's wrong:**
Per the [`StartStreamTranscription` API reference](https://docs.aws.amazon.com/transcribe/latest/APIReference/API_streaming_StartStreamTranscription.html), the streaming API parameters are: `LanguageCode`, `MediaEncoding`, `MediaSampleRateHertz`, `VocabularyName`, `SessionId`, `VocabularyFilterName`, `VocabularyFilterMethod`, `ShowSpeakerLabel` (boolean), `EnableChannelIdentification`, `NumberOfChannels`, `EnablePartialResultsStabilization`, `PartialResultsStability`, `ContentIdentificationType`, `ContentRedactionType`, `PiiEntityTypes`, `LanguageModelName`, `IdentifyLanguage`, `LanguageOptions`, `PreferredLanguage`, `IdentifyMultipleLanguages`, `VocabularyNames`, `VocabularyFilterNames`, `SessionResumeWindow`. `MaxSpeakerLabels` is not in the streaming API; it lives only on the batch `Settings` structure (with a 2-30 valid range).

In the amazon-transcribe-streaming Python SDK, the `start_stream_transcription` coroutine likewise exposes `show_speaker_label` (boolean) but no `max_speaker_labels` parameter. A learner copy-pasting the comment would get a `TypeError` from the SDK ("unexpected keyword argument 'max_speaker_labels'") or, depending on SDK version, a silent no-op.

The architectural point the comment is reaching for (telling the streaming session how many speakers to expect, based on the bystander-declaration count) is real but is only available on the batch path or via the separate `StartMedicalScribeStream` API for HealthScribe streaming, where the `MedicalScribeConfigurationEvent` includes channel definitions and post-stream analytics settings rather than a max-speakers integer.

**How to fix:**
Drop the `max_speaker_labels=...` line from the streaming-pattern comment, leave `show_speaker_label=True`, and add a brief note that the expected-speaker-count signal flows through the batch HealthScribe job (`Settings.MaxSpeakerLabels`, valid range 2-30) and through HealthScribe streaming via the `MedicalScribeConfigurationEvent`'s channel definitions. The production-pattern comment should match what the SDK actually accepts.

Optionally, if the recipe wants to demonstrate HealthScribe streaming specifically rather than generic Transcribe streaming, a sentence noting that HealthScribe streaming uses a separate API (`StartMedicalScribeStream`) with role-attributed output (CLINICIAN / PATIENT / FAMILY / OTHER) would clarify the relationship between the regular Transcribe streaming SDK example shown and the HealthScribe streaming the rest of the demo simulates.

**Severity rationale:** WARNING for the same reason as W1: the runtime Python passes through the mock without error, but the production-pattern comment teaches an SDK call shape that fails when copied to real boto3 / amazon-transcribe.

---

## NOTE Findings

### N1. The 30-second window in `lookup_speaker_role_for_offset` is generous and can attribute entities to the wrong speaker in fast-paced exchanges

**Files / sections:**
- "Step 5" section, `lookup_speaker_role_for_offset`:
  ```python
  if abs(seg_seconds - offset_seconds) < 30:
      return segment.get("speaker_role")
  ```
- "Step 5" section, `extract_context_snippet`:
  ```python
  if abs(seg_seconds - offset_seconds) < window_seconds:
      return segment.get("text", "")
  ```

**What's wrong:**
A 30-second window is wide enough that a medication mentioned by the clinician at 11:02 might be attributed to a patient utterance at 10:45 or a family-member utterance at 11:25, depending on which segment happens to be iterated first. Comprehend Medical's `OffsetSeconds` is precise (it points to the entity's character offset converted to seconds against the input text), so a window of a few seconds (or zero, with a `min(...)` over distances) would be more accurate. The pseudocode in the main recipe is also vague about the window size; the Python's choice of 30 seconds is a reasonable simplification but worth acknowledging.

**How to fix:**
Change to a small window with explicit nearest-neighbor selection:
```python
def lookup_speaker_role_for_offset(transcript, offset_seconds):
    best_role = "unknown"
    best_distance = float("inf")
    for segment in transcript.get("segments", []):
        ts = segment.get("timestamp", "00:00:00")
        try:
            parts = [int(p) for p in ts.split(":")]
            seg_seconds = (parts[0] * 3600
                            + parts[1] * 60 + parts[2])
        except (ValueError, IndexError):
            continue
        distance = abs(seg_seconds - offset_seconds)
        if distance < best_distance and distance < 5:
            best_distance = distance
            best_role = segment.get("speaker_role", "unknown")
    return best_role
```
And note in the docstring that production diarization output includes per-word speaker labels, so this offset-lookup is a simplification to bridge the Comprehend Medical entity offsets with HealthScribe's per-word speaker attribution.

---

### N2. `compute_edit_distance` runs O(n²) Levenshtein on JSON-serialized note dicts; the resulting number is not a meaningful edit metric

**Files / sections:**
- "Step 7" section, `compute_edit_distance`:
  ```python
  def compute_edit_distance(draft_text, final_text):
      ...
      a = json.dumps(draft_text, default=str, sort_keys=True)
      b = json.dumps(final_text, default=str, sort_keys=True)
      ...
      distances = list(range(len(b) + 1))
      for i, ca in enumerate(a, 1):
          new_row = [i]
          for j, cb in enumerate(b, 1):
              cost = 0 if ca == cb else 1
              new_row.append(...)
  ```

**What's wrong:**
Two issues. First, character-level Levenshtein on a JSON serialization counts changes to JSON punctuation (quotes, braces, commas) the same as changes to clinical content; a clinician adding a sentence to the assessment shows up identically to a key being renamed. Second, the implementation is O(len(a) * len(b)) and the JSON of a SOAP-structured note runs into thousands of characters; this is a teaching example, but a reader who copies it into a per-encounter post-sign Lambda will pay seconds of CPU per encounter. The comment acknowledges it as "a proxy"; a stronger note plus a tokenization-first transform would help.

**How to fix:**
Either:
- Tokenize the note into words first (`a_tokens = a_text.split()`), run Levenshtein on the token lists, and report the result as a fraction of total tokens (matching the recipe's "median word fraction" benchmark in the Expected Results table), or
- Use Python's `difflib.SequenceMatcher.ratio()` which gives a similarity score in O(n*m) but with the standard library's optimizations and meaningful semantics for text, and report `1 - ratio` as the edit-magnitude proxy.

A short comment that the production metric is per-section word-level edit distance with section-level breakdown would also help.

---

### N3. The mock `MockHealthScribeStreaming` is synchronous (a generator) but the production-pattern comment shows `await client.start_stream_transcription(...)`; the async/sync gap is not flagged

**Files / sections:**
- "Mock Resources for the Demo" section, `MockHealthScribeStreaming.stream_session`:
  ```python
  def stream_session(self, session_id, encounter_id,
                       expected_speaker_count, language):
      segments = self._fixtures.get(encounter_id, [])
      for segment in segments:
          ...
          yield event
  ```
- "Step 2" section, production-pattern comment:
  ```python
  #   stream = await client.start_stream_transcription(...)
  ```

**What's wrong:**
The amazon-transcribe-streaming-sdk-for-python SDK is async: `start_stream_transcription` is a coroutine, the audio-frame writer is async, and event-stream consumption uses `async for`. The mock collapses this into a synchronous generator, which is fine for the teaching example, but a learner moving from the demo to production has to refactor the entire `stream_audio_to_healthscribe` function (and any callers) to be async. The mock's sync style is a defensible simplification, but the comment in the function should explicitly call out "you will need to convert this to async" rather than just showing the `await` keyword in passing.

**How to fix:**
Add a sentence in `stream_audio_to_healthscribe`:
```python
# In production:
#   client = TranscribeStreamingClient(region=REGION)
#   stream = await client.start_stream_transcription(...)
# Note: the amazon-transcribe-streaming SDK is async; the
# real implementation of this function is `async def
# stream_audio_to_healthscribe(...)`, the audio-frame
# writer uses `await stream.input_stream.send_audio_event(...)`,
# and the result handler iterates `async for event in
# stream.output_stream`. The synchronous mock here is a
# teaching simplification.
```

---

### N4. `MockBedrock.render_institutional_note` returns `{"body": json.dumps(response)}`; the real Bedrock `invoke_model` returns a `StreamingBody` and accepts `body` as `bytes` or a JSON string

**Files / sections:**
- "Mock Resources for the Demo" section, `MockBedrock.render_institutional_note`:
  ```python
  return {"body": json.dumps(response, default=str)}
  ```
- "Step 4" section, `render_institutional_note`:
  ```python
  note_response = bedrock_mock.render_institutional_note(...)
  note_body = json.loads(note_response["body"])
  ```

**What's wrong:**
The pattern of `body = response["body"]` followed by `json.loads(body)` is pedagogically correct for the boto3 `bedrock-runtime.invoke_model` shape, but the real call is more like:
```python
response = bedrock_runtime.invoke_model(
    modelId=BEDROCK_NOTE_RENDERING_PROFILE_ARN,
    body=json.dumps(request_body).encode("utf-8"),
    contentType="application/json",
    accept="application/json",
    guardrailIdentifier=AMBIENT_DOC_GUARDRAIL_ID,
    guardrailVersion=AMBIENT_DOC_GUARDRAIL_VERSION)
body_text = response["body"].read().decode("utf-8")
parsed = json.loads(body_text)
```
The mock skips the `.read()` step (because the mock returns a string, not a `StreamingBody`), which is correct for what the mock does but slightly hides the real shape. The "Real Bedrock invocation" gap-to-production section calls this out, but it would be useful to have a one-line comment in `render_institutional_note` reminding the reader that the real call requires `.read().decode("utf-8")` before `json.loads`.

**How to fix:**
Add a short comment in `render_institutional_note` immediately before `note_body = json.loads(note_response["body"])`:
```python
# In production: the real bedrock_runtime.invoke_model
# returns a StreamingBody under the "body" key, so the
# parse is `json.loads(response["body"].read().decode("utf-8"))`.
# The mock returns a JSON string directly to keep the
# example short.
note_body = json.loads(note_response["body"])
```

---

### N5. `MockComprehendMedical` method names use lowercase `text` parameter; the real boto3 client uses capitalized `Text`

**Files / sections:**
- "Mock Resources for the Demo" section, `MockComprehendMedical`:
  ```python
  def detect_entities(self, text):
      ...
  def infer_rx_norm(self, text):
      ...
  def infer_icd10cm(self, text):
      ...
  ```
- "Step 5" section, calls:
  ```python
  rx_response = comprehend_mock.infer_rx_norm(text=full_text)
  icd_response = comprehend_mock.infer_icd10cm(text=full_text)
  ```

**What's wrong:**
The real boto3 calls are `comprehend_medical.infer_rx_norm(Text=full_text)` (capitalized `Text`), `comprehend_medical.infer_icd10cm(Text=full_text)`, and `comprehend_medical.detect_entities_v2(Text=full_text)`. The mock's lowercase Python-conventional `text` is fine for a Pythonic teaching mock, but a reader copying the call sites verbatim would get a parameter-name error. The "Real Comprehend Medical wiring" gap-to-production section uses the correct capitalization in its comment, but the demo's call sites do not.

Also, the mock has a method `detect_entities` (without the `_v2` suffix) which never gets called in the actual code path, and the IAM permissions list specifies `comprehendmedical:DetectEntitiesV2`. `DetectEntities` has been deprecated in favor of `DetectEntitiesV2`. The mock's naming should probably be `detect_entities_v2` for consistency, or `detect_entities` should be removed since it is not used.

**How to fix:**
- Rename the unused mock method `detect_entities` to `detect_entities_v2` (or remove it; it is not called in the actual code path).
- Add a short comment at the call sites that the real boto3 parameter is `Text` (capitalized):
  ```python
  rx_response = comprehend_mock.infer_rx_norm(text=full_text)
  # Real boto3: comprehend_medical.infer_rx_norm(Text=full_text)
  ```

---

### N6. `MockHealthScribeBatch.start_medical_scribe_job` uses kwargs that do not match the real `boto3.client("transcribe").start_medical_scribe_job` signature; the production-pattern comment is correct but the mock's parameter names are not flagged as illustrative

**Files / sections:**
- "Mock Resources for the Demo" section, `MockHealthScribeBatch.start_medical_scribe_job`:
  ```python
  def start_medical_scribe_job(self, job_name, encounter_id,
                                  audio_uri, language,
                                  max_speaker_labels,
                                  template_id):
      ...
  ```
- "Step 3" section, the call:
  ```python
  job = healthscribe_batch_mock.start_medical_scribe_job(
      job_name=job_name,
      encounter_id=encounter_id,
      audio_uri=audio_archive_ref,
      language=session_context["language"],
      max_speaker_labels=state.get(
          "expected_speaker_count", 2),
      template_id=template["id"])
  ```

**What's wrong:**
The real boto3 call uses `MedicalScribeJobName`, `Media={"MediaFileUri": ...}`, `OutputBucketName`, `OutputEncryptionKMSKeyId`, `DataAccessRoleArn`, and `Settings={...}` (PascalCase, with media as a structure not a string); the mock collapses these into snake_case scalars (`job_name`, `audio_uri`, `template_id`). The production-pattern comment block above the mock call shows the correct shape, so the divergence is acknowledged, but the mock's call signature is far enough from the real API that a learner using the mock as a pattern guide could be misled about the shape of `Media` (it is `{"MediaFileUri": "s3://..."}`, not a bare string) and the location of `MaxSpeakerLabels` (it is inside `Settings`, not a top-level kwarg).

The mock also does not accept or simulate `OutputEncryptionKMSKeyId` or `DataAccessRoleArn`, both of which are required for the real call and important for the teaching point about KMS-encrypted output.

**How to fix:**
Either align the mock's signature closer to the real shape:
```python
def start_medical_scribe_job(self, MedicalScribeJobName,
                                 Media, OutputBucketName,
                                 OutputEncryptionKMSKeyId,
                                 DataAccessRoleArn,
                                 Settings):
    ...
```
Or, more pragmatically, leave the mock's snake_case scalars but extend the production-pattern comment with one more line emphasizing that `Media` is a structure: "Note that `Media` is `{'MediaFileUri': audio_archive_ref}`, not a bare string, and that `OutputEncryptionKMSKeyId` and `DataAccessRoleArn` are required for the real call."

---

### N7. `MockCloudWatch.put_metric` accepts `dimensions` as a dict, but real `cloudwatch.put_metric_data` requires a list of `{"Name": ..., "Value": ...}` dicts; the mock's shape diverges from the boto3 shape

**Files / sections:**
- "Mock Resources for the Demo" section, `MockCloudWatch.put_metric`:
  ```python
  def put_metric(self, namespace, metric_name, value,
                  unit="Count", dimensions=None):
      self.metrics.append({
          ...
          "dimensions": dimensions or {},
          ...
      })
  ```
- All call sites pass `dimensions={"specialty": ..., "language": ...}` as a dict.

**What's wrong:**
Real `cloudwatch.put_metric_data` takes `Namespace=...` and `MetricData=[{...}]` where each metric data item has `MetricName`, `Value`, `Unit`, `Timestamp`, and `Dimensions=[{"Name": "specialty", "Value": "family_medicine"}, {"Name": "language", "Value": "en-US"}, ...]`. The mock's dict-shaped dimensions are simpler to read but diverge from the real shape; a learner who replaces the mock with `cloudwatch_client.put_metric_data(...)` will need to transform the dict to a list of name-value dicts. This is a small detail but worth flagging because every cohort metric in the audit and the per-stage telemetry use this pattern, so the divergence is repeated dozens of times across the demo.

**How to fix:**
Either change the mock to expect a list of `{"Name": ..., "Value": ...}` dicts (and update every call site to use that shape, which is verbose but matches the boto3 API), or add a brief note in the `MockCloudWatch` docstring:
```python
class MockCloudWatch:
    """
    Stands in for CloudWatch metric emission. The mock uses
    a dict for dimensions for readability; real
    cloudwatch.put_metric_data expects a list of
    {"Name": ..., "Value": ...} entries inside MetricData[i]
    .Dimensions. A small adapter at the call sites converts
    between the two when wiring to the real client.
    """
```

---

### N8. The `transcribe_batch_mock` orchestration in `run_batch_healthscribe` calls a single immediate-completion mock; the real workflow polls `get_medical_scribe_job` and the comment block does not show the polling loop

**Files / sections:**
- "Step 3" section, `run_batch_healthscribe`:
  ```python
  # In production:
  #   transcribe_batch.start_medical_scribe_job(
  #       MedicalScribeJobName=f"{session_id}-batch",
  #       ...)
  # Then poll get_medical_scribe_job until COMPLETED. The
  # mock collapses this to a single call that returns
  # immediately.
  ```

**What's wrong:**
The production HealthScribe batch job is asynchronous: `start_medical_scribe_job` returns immediately with `MedicalScribeJobStatus = IN_PROGRESS`, and the orchestrator must poll `get_medical_scribe_job(MedicalScribeJobName=...)` until status is `COMPLETED` or `FAILED` before retrieving the output URIs. The comment acknowledges this in one sentence, but does not show the polling pattern. Step Functions handles this in production via a `WaitForCompletion` state with retry-and-poll semantics; in a Lambda-only orchestration the polling loop with a sleep-and-retry pattern is necessary, and the typical completion time (a few minutes for a 15-30-minute encounter) means a long-running Lambda invocation is not appropriate.

**How to fix:**
Expand the comment with a brief polling-pattern sketch:
```python
# In production:
#   response = transcribe_batch.start_medical_scribe_job(...)
#   job_name = response["MedicalScribeJobName"]
#   while True:
#       status_response = (
#           transcribe_batch.get_medical_scribe_job(
#               MedicalScribeJobName=job_name))
#       status = status_response[
#           "MedicalScribeJob"]["MedicalScribeJobStatus"]
#       if status in ("COMPLETED", "FAILED"):
#           break
#       time.sleep(15)  # back off appropriately
# Step Functions handles this with a Wait + GetJob loop;
# Lambda-only orchestration uses an EventBridge timer or
# SQS-backed retry rather than a long-blocking poll.
```
This makes the asynchrony of the batch path explicit, which matters for learners wiring this into Step Functions or Lambda.

---

## Summary of Fixes (priority order)

1. **W1:** Add a `healthscribe_note_template` enum field to `DEFAULT_TEMPLATES` and update the production-pattern comment in `run_batch_healthscribe` to use it; align the recipe's Step 3C pseudocode with the same enum-based approach. (Highest priority because it would cause a real-world `BadRequestException`.)
2. **W2:** Drop `max_speaker_labels=...` from the `start_stream_transcription` production-pattern comment in `stream_audio_to_healthscribe`; clarify that the expected-speaker-count signal flows through the batch HealthScribe job's `Settings.MaxSpeakerLabels` and through `MedicalScribeConfigurationEvent` for HealthScribe streaming.
3. **N1:** Tighten the `lookup_speaker_role_for_offset` window to a smaller value with explicit nearest-neighbor selection.
4. **N2:** Replace the JSON-Levenshtein in `compute_edit_distance` with token-level word distance (or `difflib.SequenceMatcher.ratio()`).
5. **N3:** Note explicitly that the streaming SDK is async and `stream_audio_to_healthscribe` becomes `async def` in production.
6. **N4:** Add a one-line comment about `StreamingBody.read().decode("utf-8")` in `render_institutional_note`.
7. **N5:** Rename `MockComprehendMedical.detect_entities` to `detect_entities_v2` (or remove it); note that real boto3 uses capitalized `Text` parameter name.
8. **N6:** Either align `MockHealthScribeBatch.start_medical_scribe_job` to the real PascalCase signature or extend the production-pattern comment to emphasize the `Media={"MediaFileUri": ...}` structure shape.
9. **N7:** Add a docstring note to `MockCloudWatch` explaining the dict-vs-list-of-dicts dimensions divergence.
10. **N8:** Show the polling loop or the Step Functions polling pattern in the `run_batch_healthscribe` comment block.

---

## Persona-Specific Checklist

- ERROR findings automatically mean FAIL: **0 ERRORs**, no automatic FAIL.
- More than 3 WARNING findings means FAIL: **2 WARNINGs**, under threshold.
- boto3 API calls are current (method names, parameters, responses): verified `start_medical_scribe_job` parameter shape, `NoteTemplate` enum values, `start_stream_transcription` parameter list, Comprehend Medical method names, EventBridge `put_events` shape, CloudWatch `put_metric_data` shape, Bedrock `invoke_model` `StreamingBody` response. W1 and W2 are the divergences.
- DynamoDB code uses `Decimal`, not `float`: verified. The `_to_decimal` helper is consistently used at every state-table write. Mock fixture floats (e.g., `0.97`, `0.94`) are converted via `Decimal(str(...))` at the boundary in `extract_structured_fields` (`Decimal(str(entity.get("Score", 0.85)))`), `run_faithfulness_check` (`Decimal(str(body.get("score", 0.0)))`), and `handle_streaming_segment` (`Decimal(str(...))`). No raw `float` reaches a state-table write path.
- S3 paths don't have leading slashes: verified. Every `s3_store.put_object(bucket=..., key=...)` call uses keys like `f"{session_id}/canonical_transcript.json"`, `f"{session_id}/healthscribe_note_draft.json"`, `f"{session_id}/rendered_note.json"`, `f"audit/{datetime.now(...).strftime('%Y/%m/%d')}/{session_id}.json"`, and `f"audio/{session_id}/encounter.pcm"`. None have leading slashes.

**Final verdict: PASS.**
