# Code Review: Recipe 10.10 — Multilingual Real-Time Medical Interpretation (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.10-python-example.md`
- `chapter10.10-multilingual-realtime-medical-interpretation.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** FAIL

The companion is a long, well-structured walkthrough of a seven-stage real-time medical-interpretation pipeline (encounter setup with consent, per-speaker audio routing, finalized-transcript translation with verification, target-language TTS, turn-taking state machine with barge-in, human-interpreter escalation, encounter close with audit and per-pair quality monitoring) for one demo scenario (Elena, a 64-year-old Mexican Spanish-speaking patient in an outpatient follow-up with `machine_with_human_standby` posture). It enforces the `Decimal`-not-`float` discipline through the `_to_decimal` helper at every state-table write boundary, uses no leading slashes in S3 keys (`transcripts/{text_hash[:16]}.txt`, `audit/YYYY/MM/DD/{encounter_id}.json`, and the demo URIs `{encounter_id}/patient.ogg`, `{encounter_id}/clinician.ogg` are all properly relative), avoids hardcoded credentials, respects the per-pair-validation discipline (the `ksw-MM_to_en-US` pair is correctly marked `not_validated` and short-circuits to human-only routing), respects the deployment-posture-per-topic-category discipline (the `human_only` topics short-circuit to human-only routing, the `machine_with_human_standby` topics pre-stage an interpreter, and the `machine_only` topics skip the standby), enforces number-and-unit verification as a hard gate that routes the dosing-mismatch utterance to escalation, and runs the faithfulness check on Bedrock LLM-translated content with an independent verifier model.

The blocker is one ERROR-level finding: the module-level client creation `boto3.client("transcribe-streaming", region_name=REGION, config=...)` raises `botocore.exceptions.UnknownServiceError` against current boto3 because there is no `transcribe-streaming` boto3 service. The Amazon Transcribe streaming API uses HTTP/2 and is exposed through a separate package (`amazon-transcribe`, the Amazon Transcribe Streaming SDK for Python), not through the standard boto3 client factory. The boto3 `transcribe` service is the batch-jobs API only. This line runs at module import time, before any mocks intercept anything, and aborts the entire demo with `UnknownServiceError: Unknown service: 'transcribe-streaming'`. A reader who follows the setup instructions (`pip install boto3`) and runs `python <file>.py` cannot get past `import` to see anything else the recipe is trying to teach.

Beyond the ERROR there are two WARNING-level findings (a fictitious `applied_settings_confidence` field on the Translate response that teaches readers Translate returns translation confidence when it does not, and an incomplete conversational state machine where the demo's six-utterance conversation triggers spurious BARGE_IN audit events on every speaker change because the state never transitions out of `"translating"` between turns) plus a handful of NOTE-level improvements covering the mock-vs-real boto3 divergences and a few internal inconsistencies between the pseudocode and the Python.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 1 |
| WARNING  | 2 |
| NOTE     | 8 |

---

## ERROR Findings

### E1. `boto3.client("transcribe-streaming", ...)` raises `UnknownServiceError` at module load; the demo cannot import

**Files / sections:**
- "Configuration and Constants" section, module-level client creation:
  ```python
  transcribe_streaming = boto3.client(
      "transcribe-streaming", region_name=REGION,
      config=BOTO3_RETRY_CONFIG_REALTIME)
  ```

**What's wrong:**
There is no `transcribe-streaming` service in current boto3. Verified directly:
```
$ python -c "import boto3; print('transcribe-streaming' in
              boto3.Session().get_available_services())"
False

$ python -c "import boto3;
              boto3.client('transcribe-streaming',
                            region_name='us-east-1')"
botocore.exceptions.UnknownServiceError:
    Unknown service: 'transcribe-streaming'.
    Valid service names are: ... transcribe ...
```

The Amazon Transcribe streaming API uses HTTP/2 streams (and optionally WebSockets) and is exposed through the separate `amazon-transcribe` package (the Amazon Transcribe Streaming SDK for Python), not through the standard `boto3.client(...)` factory. The boto3 `transcribe` service exists, but it is the batch-jobs API only (`start_transcription_job`, `start_medical_transcription_job`, `get_transcription_job`); none of the streaming methods (`StartStreamTranscription`, `StartMedicalStreamTranscription`) are available on it.

The IAM action names listed in the Setup section (`transcribe:StartStreamTranscription`, `transcribe:StartMedicalStreamTranscription`) are correct as IAM action strings for Transcribe Streaming, so the recipe is internally inconsistent: the IAM is right, the client construction is impossible.

The line runs at module-import time, before any of the `Mock*` classes get a chance to substitute. The cascade is:
1. `python chapter10.10-demo.py` invokes the module
2. The `boto3.client("transcribe-streaming", ...)` line at module top level executes
3. botocore tries to load the service model from its data files
4. The service is not in the registry; `UnknownServiceError` is raised
5. The script terminates before `if __name__ == "__main__": run_demo()` is even reached

A reader who follows the Setup instructions (`pip install boto3`) and runs the demo gets a stack trace with no demo output. None of the seven pipeline stages run. None of the audit records are produced. The lesson the recipe is trying to teach is hidden behind an import error.

**How to fix:**

Two reasonable paths.

Option A (preferred for the cookbook's pedagogical posture, which is "show what production looks like, mock for the demo"): replace the boto3 client construction with the Amazon Transcribe Streaming SDK client construction inside an `import` block that is guarded so the demo can still run if the SDK is not installed:
```python
# Amazon Transcribe streaming uses HTTP/2 and a separate
# Python SDK from boto3. Install with:
#   pip install amazon-transcribe
# Production replaces the mock with a real client; the
# demo never actually creates a streaming session, so the
# import is optional here.
try:
    from amazon_transcribe.client import TranscribeStreamingClient
    transcribe_streaming = TranscribeStreamingClient(
        region=REGION)
except ImportError:
    transcribe_streaming = None
```
Update the docstring on `MockTranscribeStreaming` to reference `amazon_transcribe.client.TranscribeStreamingClient` and `start_stream_transcription` (the real async method on that client) rather than `transcribe_streaming.start_stream_transcription` as if it were a boto3 client.

Option B (lower-effort, preserves the "production clients are never invoked here" framing): drop the `transcribe_streaming` module-level client entirely. The mock is the only thing that gets used; the boto3 line is dead code. The Setup section can reference the streaming SDK by name without instantiating it. Add a one-line note at the top of the constants section:
```python
# Amazon Transcribe streaming is not exposed through
# boto3; the production client is
# amazon_transcribe.client.TranscribeStreamingClient
# from the amazon-transcribe package. The demo uses
# MockTranscribeStreaming below.
```

The pseudocode and the rest of the recipe text reference Transcribe streaming in prose but do not call any specific Python construction; once the broken client line is removed (or replaced with the correct SDK), nothing else needs to change.

**Severity rationale:** ERROR because the demo will not run as written. The persona checklist explicitly says "Would it run without errors given the stated prerequisites?" — and the stated prerequisite is `pip install boto3`. With only boto3 installed, the script aborts on import. ERROR findings automatically mean FAIL.

---

## WARNING Findings

### W1. `applied_settings_confidence` is invented; real Amazon Translate `translate_text` does not return a per-translation confidence score

**Files / sections:**
- "Mock Resources for the Demo" section, `MockTranslate.translate_text`:
  ```python
  return {
      "translated_text":
          fixture.get("translated_text",
                        "<no fixture available>"),
      "applied_terminologies":
          fixture.get(
              "applied_terminologies", []),
      "applied_settings_confidence":
          fixture.get("confidence", Decimal("0.85")),
  }
  ```
- "Step 3" section, `asr_finalized_transcript` consuming the mock response:
  ```python
  translation_result = translate_mock.translate_text(
      text=segment.get("transcript_text", ""),
      source_language_code=source_language,
      target_language_code=target_language,
      terminology_names=[...])
  translated_text = translation_result[
      "translated_text"]
  translation_confidence = Decimal(str(
      translation_result.get(
          "applied_settings_confidence", 0.85)))
  ```

**What's wrong:**
Real `translate_client.translate_text` returns a dict with `TranslatedText`, `SourceLanguageCode`, `TargetLanguageCode`, `AppliedTerminologies`, and `AppliedSettings` (the `Formality`/`Profanity`/`Brevity` settings that were applied) plus the standard response metadata. There is no `applied_settings_confidence` field. Translate does not surface per-translation confidence on the synchronous `TranslateText` API; quality estimation is a separate problem the institution solves with a downstream model (a quality-estimation model, COMET-QE-style metrics, or a secondary verifier as the recipe describes elsewhere).

The mock's field name `applied_settings_confidence` looks like it was constructed by appending `_confidence` onto the real `AppliedSettings` field name. The pipeline then reads this fake field and uses it as the gating signal for confidence-based escalation:
```python
confidence_threshold = Decimal(str(
    pair_def.get("confidence_threshold", ...)))
asr_confidence = Decimal(str(
    segment.get("per_word_confidence_min", 1)))
low_confidence = (
    translation_confidence < confidence_threshold
    or asr_confidence <
        DEFAULT_ASR_CONFIDENCE_THRESHOLD)
```

This teaches a misleading pattern: a learner replacing the mock with `translate_client.translate_text(...)` will see no `applied_settings_confidence` key in the response and fall back to the `0.85` default for every utterance, which masks the confidence-based escalation entirely (every utterance becomes "high confidence" by default). The recipe's main text correctly describes per-segment quality estimation as a separate engine ("Translation quality estimation per segment / Aggregate per-utterance confidence" in the Medical-Domain Machine Translation section), but the code conflates that estimation with a non-existent Translate response field.

This is the pattern the recipe specifically warns against in its honest take: deploying a system that "produces dosing errors in production" because confidence gating is not wired up correctly. The current code's confidence gating works only for the demo's hand-tuned fixtures.

The Bedrock branch does the same thing (`Decimal(str(parsed.get("confidence", 0.80)))`), but at least there the response shape is the model's structured-output response and the `confidence` field can be defined by the prompt schema. The Translate branch is worse because it implies a real API field.

**How to fix:**
Either (a) drop the field from the mock and source the per-utterance translation confidence from a separate quality-estimation step (with a stub function in the demo and a comment that production calls a quality-estimation model or runs a secondary verifier), or (b) keep the mock-only field but rename it to make the source explicit and add a comment at the call site:
```python
# Translate's TranslateText response does NOT include a
# per-translation confidence score. Production runs a
# separate quality-estimation step (COMET-QE, a quality-
# estimation model fine-tuned per pair, or a secondary
# verifier model) on each translated segment. The mock
# returns a "demo_confidence" field built into the
# fixture so the confidence-based escalation path can be
# exercised; replace this with a real quality-estimation
# call when wiring to production.
demo_confidence = translation_result.get(
    "demo_confidence", 0.85)
translation_confidence = Decimal(str(demo_confidence))
```
Update the mock's return shape accordingly. The architecturally honest fix is option (a); option (b) is the lower-disruption variant.

**Severity rationale:** WARNING because the misleading pattern propagates from the mock to the production-pattern guidance. A learner who replaces the mock with the real Translate client and does nothing else will silently lose all confidence-based escalation. The hard gates (number-and-unit verification, faithfulness check on LLM output) still fire, but the soft gate that protects against the long tail of low-confidence translations on routine content is broken. In a clinical context where the recipe explicitly warns about the cumulative risk of low-confidence translations on routine clinical content, that is a real teaching failure.

---

### W2. The conversational state machine never transitions out of `"translating"` or into `"playing_translation"`; the six-utterance demo emits five spurious BARGE_IN audit events

**Files / sections:**
- "Step 5" section, `vad_event`:
  ```python
  if event_type == "speech_start":
      if current_state == "idle":
          transition_to_state(
              encounter_id, "speaker_active",
              active_speaker=speaker)
      elif current_state == "translating" and \
              speaker != state.get(
                  "translating_for_speaker"):
          handle_barge_in(...)
          transition_to_state(
              encounter_id, "speaker_active",
              active_speaker=speaker)
      elif current_state == "playing_translation" and \
              speaker == state.get(
                  "target_audience_speaker"):
          handle_barge_in(...)
          transition_to_state(
              encounter_id, "speaker_active",
              active_speaker=speaker)
  elif event_type == "speech_end":
      transition_to_state(
          encounter_id, "translating",
          translating_for_speaker=speaker)
  elif event_type == "silence":
      pass
  ```
- "Step 4" section, `synthesize_translated_audio` does not transition state.
- "Putting It All Together" section, `run_interpretation_encounter`:
  ```python
  for speaker, segment in conversation_segments:
      vad_event(encounter_id, speaker, "speech_start")
      vad_event(encounter_id, speaker, "speech_end")
      translation_result = asr_finalized_transcript(...)
      ...
      synthesize_translated_audio(...)
  ```

**What's wrong:**
The state machine has five states by name (`idle`, `speaker_active`, `translating`, `playing_translation`, plus the implicit "speaker is speaking again"), but only two transitions are wired:
1. `idle` → `speaker_active` on `speech_start` (or, with barge-in, `translating`/`playing_translation` → `speaker_active`).
2. `speaker_active` (any) → `translating` on `speech_end`, with `translating_for_speaker` set to the most recent speaker.

There is no transition from `translating` to `playing_translation` and no transition from either of those states back to `idle`. The translation completes (`asr_finalized_transcript` returns a translated text), the audio is synthesized (`synthesize_translated_audio` records a CloudWatch latency metric), and then control returns to the loop. The state stays at `"translating"` indefinitely.

When the next utterance comes in:
- `vad_event(encounter_id, "<other speaker>", "speech_start")` runs.
- `current_state` is `"translating"`.
- `speaker != state.get("translating_for_speaker")` because the other speaker has just started.
- The barge-in branch fires: `handle_barge_in(encounter_id, interrupting_speaker=<other speaker>, in_flight_translation=state.get("in_flight_translation", {}))`.
- An `event_type: BARGE_IN` audit log event is emitted for what is actually a normal turn-taking event.

The demo's six-utterance conversation alternates patient/clinician/patient/clinician/patient/clinician, so:
- u-001 (patient): no barge-in (state was `idle`).
- u-002 (clinician): spurious BARGE_IN (state stuck at `translating`, translating_for_speaker=patient, new speaker=clinician).
- u-003 (patient): spurious BARGE_IN.
- u-004 (clinician): spurious BARGE_IN. (And the real number-mismatch escalation fires on translation, plus another BARGE_IN gets logged.)
- u-005 (patient): spurious BARGE_IN.
- u-006 (clinician): spurious BARGE_IN.

Total: five spurious BARGE_IN audit events out of five non-initial speaker changes, plus the real escalation events. The audit log makes the encounter look like a chaotic mess where the patient and clinician are constantly interrupting the system, when the actual demo conversation is six clean alternating turns with two real escalations.

`in_flight_translation` is also always an empty dict (`state.get("in_flight_translation", {})`), so `halt_translation(in_flight_translation.get("translation_id"))` is called with `translation_id=None`. The audit event records `translation_id_hash=None` and `in_flight_translation_id=None`. The pseudocode envisions `in_flight_translation` being populated when the system enters `"translating"`, but the Python never populates it.

This breaks both the pedagogical and the operational story: a learner reading the audit log to understand the demo cannot tell which BARGE_IN events represent real interruptions and which are artifacts of the missing state transition, and the post-deployment per-encounter quality dashboards (which the recipe describes as being driven by the audit data) would be polluted by spurious barge-in counts.

**How to fix:**

The minimum fix is to add the missing transitions. After translation finishes in `asr_finalized_transcript`, transition to `"playing_translation"`. After audio is delivered in `synthesize_translated_audio` (or after a short silence in `vad_event`), transition back to `"idle"`. The cleanest place is at the end of `synthesize_translated_audio`:
```python
return_value = {
    "audio_stream":            synthesis,
    "end_to_end_latency_ms":   end_to_end_latency_ms,
}

# Translation playback complete; reset state machine to
# idle so the next speech_start does not trigger a
# spurious barge-in.
transition_to_state(encounter_id, "idle")

return return_value
```

For the escalation path, the equivalent reset belongs at the end of `execute_escalation` once the audio has been routed to the human interpreter. The `in_flight_translation` field should also be populated when the state transitions to `"translating"` so that legitimate barge-ins (when the demo gets extended to test real interruption) record meaningful `translation_id` values rather than `None`.

A more thorough fix populates the full state machine the recipe describes:
- `idle` → `speaker_active(speaker)` on `speech_start` from `idle`.
- `speaker_active(speaker)` → `translating(speaker)` on `speech_end`.
- `translating(speaker)` → `playing_translation(target)` on translation success.
- `playing_translation(target)` → `idle` on TTS completion or after a short silence.

The Python implementation does not have to model every transition explicitly; a `_transition_after_translation_complete` helper that gets called at the right point in `synthesize_translated_audio` is enough.

**Severity rationale:** WARNING because the demo runs to completion and produces output, but the audit log and the BARGE_IN event count are wrong in a way that misleads readers about the state machine's behavior. In a learning context where the recipe specifically calls out "skip the state machine and the conversation feels like a walkie-talkie," the demo's audit log makes the demo look like a walkie-talkie with constant interruptions when in fact the conversation is clean. Two WARNING findings is still under the FAIL threshold of 3, but combined with E1 the recipe FAILs on the ERROR criterion regardless.

---

## NOTE Findings

### N1. `MockBedrock.invoke_translation` and `invoke_faithfulness_check` are fictitious method names; real boto3 is `bedrock_runtime.invoke_model` returning a `StreamingBody`

**Files / sections:**
- "Mock Resources for the Demo" section, `MockBedrock`:
  ```python
  def invoke_translation(self, source_text, source_language,
                            target_language,
                            guardrail_id):
      ...
      return {"body": json.dumps(response, default=str)}

  def invoke_faithfulness_check(self, source_text,
                                       target_text,
                                       source_language,
                                       target_language):
      ...
      return {"body": json.dumps(response, default=str)}
  ```
- "Step 3" section, the call sites:
  ```python
  bedrock_response = bedrock_mock.invoke_translation(
      source_text=segment.get("transcript_text", ""),
      ...)
  parsed = json.loads(bedrock_response["body"])
  ```

**What's wrong:**
Real `bedrock_runtime.invoke_model` takes parameters `modelId`, `body` (a JSON-encoded string), `contentType`, `accept`, optionally `guardrailIdentifier`/`guardrailVersion`/`trace`, and returns a dict whose `body` field is a `botocore.response.StreamingBody`. Reading the response is `response["body"].read().decode("utf-8")`, then `json.loads(...)`. The mock collapses the request shape (modelId, the structured Anthropic Messages API body, the guardrail config) into a tuple of high-level fields and returns a plain string body, which is fine for the demo but hides the real shape. Same pattern flagged in recipes 10.7, 10.8, and 10.9.

The "Gap to Production" section calls out the Anthropic Messages API shape and the Guardrails configuration in prose but the call site does not show the parsing pattern. A learner replacing the mock with `bedrock_runtime.invoke_model(...)` needs to add the `.read().decode("utf-8")` step and translate the high-level kwargs into the full Anthropic Messages API request body (`anthropic_version`, `messages`, `system`, `max_tokens`, optionally `tools`/`tool_choice` for structured-output via tool-use).

**How to fix:**
Add a short comment in `asr_finalized_transcript` immediately before the `json.loads(bedrock_response["body"])`:
```python
# In production: real bedrock_runtime.invoke_model returns
# a StreamingBody under the "body" key, so the parse is:
#     body_text = response["body"].read().decode("utf-8")
#     parsed = json.loads(body_text)
# The request body for Anthropic Claude on Bedrock is the
# Anthropic Messages API shape (anthropic_version, messages,
# system, max_tokens, optionally tools + tool_choice for
# structured output via tool-use), with the source content
# wrapped in a delimited untrusted-input envelope. The
# guardrailIdentifier and guardrailVersion parameters
# attach the runtime Guardrails policy. The mock returns a
# JSON string directly to keep the example short.
parsed = json.loads(bedrock_response["body"])
```

---

### N2. `MockTranslate.translate_text` uses snake_case kwargs; real `translate_client.translate_text` is PascalCase

**Files / sections:**
- "Mock Resources for the Demo" section, `MockTranslate.translate_text`:
  ```python
  def translate_text(self, text, source_language_code,
                        target_language_code,
                        terminology_names=None):
      ...
  ```
- "Step 3" section, the call site:
  ```python
  translation_result = translate_mock.translate_text(
      text=segment.get("transcript_text", ""),
      source_language_code=source_language,
      target_language_code=target_language,
      terminology_names=[
          pair_def.get("mt_custom_terminology")
      ] if pair_def.get("mt_custom_terminology")
        else None)
  ```

**What's wrong:**
The real boto3 `translate_client.translate_text` parameters are `Text`, `TerminologyNames`, `SourceLanguageCode`, `TargetLanguageCode`, and optionally `Settings` (the `Formality`/`Profanity`/`Brevity` block). The mock's snake_case kwargs are friendlier for reading the demo but diverge from boto3's PascalCase parameter style. Same pattern as the SageMaker invocations flagged in recipes 10.7-10.9. A learner replacing the mock with the real client needs to translate the parameter names.

Note that the recipe pseudocode is explicit about the `Settings: { profanity: "MASK" }` configuration ("Per institutional policy; some flows suppress profanity in clinical output"), but the Python mock signature does not surface a `settings` kwarg at all. Production needs the explicit `Settings` parameter.

**How to fix:**
Add a one-line comment at the first call site:
```python
# Real boto3:
#   translate_client.translate_text(
#     Text=segment["transcript_text"],
#     SourceLanguageCode=source_language,
#     TargetLanguageCode=target_language,
#     TerminologyNames=[pair_def["mt_custom_terminology"]],
#     Settings={"Profanity": "MASK"})
# The mock takes snake_case for readability and skips the
# Settings field; production explicitly sets Profanity per
# the institutional policy referenced in the pseudocode.
```

---

### N3. `MockPolly.synthesize_speech_streaming` is a fictitious method name; real boto3 is `polly_client.synthesize_speech` returning an `AudioStream` `StreamingBody`

**Files / sections:**
- "Mock Resources for the Demo" section, `MockPolly`:
  ```python
  def synthesize_speech_streaming(self, text, voice_id,
                                       engine, lexicon_ids,
                                       text_type="ssml",
                                       language_code=None):
      ...
      return {
          "audio_stream_ref": ...,
          "format":          "audio/ogg",
          "sample_rate":     "24000",
          "time_to_first_byte_ms": ...,
      }
  ```
- "Step 4" section, the call site:
  ```python
  synthesis = polly_mock.synthesize_speech_streaming(
      text=ssml_text,
      voice_id=pair_def.get("tts_voice", "Joanna"),
      engine=pair_def.get("tts_engine", "neural"),
      lexicon_ids=pair_def.get("tts_lexicons", []),
      text_type="ssml",
      language_code=target_language)
  ```

**What's wrong:**
Real `polly_client.synthesize_speech` parameters are `Text`, `VoiceId`, `OutputFormat` (not `format`, and the value is `mp3`, `ogg_vorbis`, `pcm`, or `json`), `Engine` (`standard`, `neural`, `long-form`, or `generative`), `LanguageCode`, `LexiconNames`, `SampleRate`, `SpeechMarkTypes`, `TextType` (`text` or `ssml`). The response is `{"AudioStream": StreamingBody, "ContentType": "...", "RequestCharacters": ..., ...}`. Streaming in Polly means the response body is a `StreamingBody` that yields audio bytes as they are produced, not a separate `synthesize_speech_streaming` method. The mock invents a method name that does not exist.

The mock's response also synthesizes a `time_to_first_byte_ms` field that does not come from Polly; in production the time-to-first-byte is measured at the caller (`time.monotonic()` before and after the first chunk read off `AudioStream`), not returned by the API. The pipeline reads this fictitious field for the latency budget check in `deliver_audio_stream`:
```python
"time_to_first_byte_ms":
    audio_stream.get(
        "time_to_first_byte_ms", 0),
```
which falls back to 0 in production, masking the latency-budget tracking.

**How to fix:**
Either rename the mock method to `synthesize_speech` and add a docstring comment about the streaming pattern:
```python
def synthesize_speech(self, text, voice_id, engine,
                          lexicon_names, text_type="ssml",
                          language_code=None):
    # Real boto3:
    #   response = polly_client.synthesize_speech(
    #     Text=text, VoiceId=voice_id, Engine=engine,
    #     LanguageCode=language_code,
    #     LexiconNames=lexicon_names,
    #     OutputFormat="ogg_vorbis", TextType=text_type)
    # The response["AudioStream"] is a StreamingBody;
    # measure time-to-first-byte at the caller by timing
    # the first .read() call against the stream.
    ...
```
or document the divergence at the call site with the same content. The latency-budget tracking should be moved out of the synthesis return value into measurement at the delivery site (`deliver_audio_stream`).

---

### N4. `MockCloudWatch.put_metric` accepts `dimensions` as a dict; real `cloudwatch.put_metric_data` requires a list of `{"Name": ..., "Value": ...}` dicts

**Files / sections:**
- "Mock Resources for the Demo" section, `MockCloudWatch.put_metric`:
  ```python
  def put_metric(self, namespace, metric_name, value,
                  unit="Count", dimensions=None):
      self.metrics.append({
          ...
          "dimensions":  dimensions or {},
          ...
      })
  ```
- All call sites pass `dimensions={"language_pair": ..., "posture": ..., ...}` as dicts.

**What's wrong:**
Real `cloudwatch_client.put_metric_data` takes `Namespace=...` and `MetricData=[{...}]` where each item has `MetricName`, `Value`, `Unit`, `Timestamp`, and `Dimensions=[{"Name": "language_pair", "Value": "es-MX_to_en-US"}, ...]`. The mock's dict-shaped dimensions are simpler to read but diverge from the real shape; a learner who replaces the mock with `cloudwatch_client.put_metric_data(...)` needs to transform the dict into a list of name-value dicts and group all the metric items into a single `MetricData` array. This pattern is repeated half a dozen times across the demo (in `encounter_initiated`, `route_audio_to_asr`, `asr_finalized_transcript`, `synthesize_translated_audio`, `execute_escalation`, `encounter_ended`), so the divergence propagates. Same issue as recipes 10.7-10.9.

Additionally the mock's `put_metric` accepts a `Decimal` value (the `EscalationRate` calculation passes `Decimal(str(escalation_count)) / Decimal(str(...))`), but real `put_metric_data` requires `Value` to be a `float` or `int`; `Decimal` instances raise a serialization error in the real client. Production has to cast via `float(...)` at the call site.

**How to fix:**
Add a docstring note to `MockCloudWatch`:
```python
class MockCloudWatch:
    """
    Stands in for CloudWatch metric emission. The mock uses
    a dict for dimensions for readability; real
    cloudwatch.put_metric_data expects a list of
    {"Name": ..., "Value": ...} entries inside
    MetricData[i].Dimensions, with all metric items grouped
    into a single MetricData array per call. Real
    put_metric_data also requires Value to be a float or
    int; cast Decimal values via float(...) at the call
    site. A small adapter at the call sites converts the
    mock shape to the real shape when wiring to production.
    """
```

---

### N5. `escalate_to_human` is a logging-only placeholder duplicated by `execute_escalation`; the pseudocode shows a single function that does both

**Files / sections:**
- "Step 3" section, the placeholder:
  ```python
  def escalate_to_human(encounter_id, reason, segment,
                            additional_context=None):
      """Triggered from inside the translation pipeline when
      a verification gate fails. Implementation deferred to
      Step 6; here we just capture the trigger event."""
      audit_log({
          "event_type":      "ESCALATION_TRIGGERED",
          "encounter_id":    encounter_id,
          "reason":          reason,
          "segment_id":      segment.get("utterance_id"),
          "timestamp":       _now_iso(),
      })
      return {"escalation_triggered": True, "reason": reason}
  ```
- "Step 6" section, the real implementation `execute_escalation`.
- "Putting It All Together" section, `run_interpretation_encounter` calling both:
  ```python
  if translation_result.get("escalated"):
      execute_escalation(
          encounter_id=encounter_id,
          reason=translation_result.get(
              "escalation_reason"),
          ...)
  ```

**What's wrong:**
The recipe's pseudocode in Step 3 calls `escalate_to_human(...)` directly from the verification-gate failure paths. The Python splits this into a logging-only `escalate_to_human` that runs synchronously inside `asr_finalized_transcript` and a real `execute_escalation` that runs from the orchestrator. The split is reasonable as a demo structure (it keeps Step 3 readable without forward-referencing all of Step 6), but it produces duplicate audit events: each verification-gate failure emits an `ESCALATION_TRIGGERED` audit_log entry from `escalate_to_human`, then a `human_escalation` audit_table entry from `execute_escalation`, then a `HUMAN_ESCALATION_COMPLETE` audit_log entry from `execute_escalation`. Three log lines per escalation where the pseudocode shows one logical event.

The split also creates a subtle race-condition pedagogical issue: in the pseudocode, the escalation happens inline and the function returns without producing a translation. In the Python, `asr_finalized_transcript` returns with `escalated=True` and the orchestrator decides whether to invoke `execute_escalation`. The audit table for the failed segment has `escalation_triggered=True` but the `human_escalation` event entry is in a separate audit-table row. A reader who queries the audit table for the encounter sees both rows for the same segment without an obvious link between them.

**How to fix:**
Either (a) fold `execute_escalation` into the `escalate_to_human` placeholder so the function does the real work and the orchestrator just observes the result, with the comment shifted from "deferred to Step 6" to "this function spans Step 3's escalation trigger and Step 6's pool integration; the orchestrator does not need to call it again," or (b) keep the split but rename the placeholder to `flag_for_escalation` (a verb that more clearly signals it is a marker, not a handoff) and link the audit_table rows by stamping the `human_escalation` row with the failed segment's `utterance_id` plus a back-reference to the per-utterance row's primary key. Option (a) matches the pseudocode more closely.

---

### N6. `count_utterances` includes `human_escalation` event rows in the per-encounter utterance count

**Files / sections:**
- "Step 7" section, `count_utterances`:
  ```python
  def count_utterances(encounter_id):
      return len(audit_table.query_by_encounter(encounter_id))
  ```
- The audit table contains both per-utterance translation entries (with `utterance_id`) and `human_escalation` event entries (with `event_type: "human_escalation"`, no `utterance_id`).

**What's wrong:**
For the demo's six-utterance conversation with two escalations, the audit table holds eight rows: six per-utterance translation rows (some of which have `escalation_triggered=True`) and two `human_escalation` event rows from `execute_escalation`. `count_utterances` returns 8, which then flows into the encounter-audit summary as `utterance_count: 8`. The metric `EscalationRate` (in `encounter_ended`) is computed as `escalation_count / max(utterance_count, 1)` = `2 / 8` = `0.25` rather than the more meaningful `2 / 6` = `0.33`. The persisted audit summary's `utterance_count` is then off by the number of escalations.

**How to fix:**
Filter on the per-utterance shape:
```python
def count_utterances(encounter_id):
    return sum(
        1 for r in audit_table.query_by_encounter(encounter_id)
        if r.get("utterance_id"))
```
Or maintain a per-utterance counter directly in the encounter state.

---

### N7. `compute_latency_distribution` filters CloudWatch metrics across the entire global mock, not per-encounter

**Files / sections:**
- "Step 7" section, `compute_latency_distribution`:
  ```python
  def compute_latency_distribution(encounter_id):
      relevant = [
          m for m in cloudwatch.metrics
          if m.get("metric_name") == "EndToEndLatencyMs"
          and m.get("dimensions", {}).get(
              "language_pair") is not None
      ]
      ...
  ```

**What's wrong:**
The function pulls every `EndToEndLatencyMs` metric across the global `cloudwatch` mock, regardless of which encounter produced it. For the demo's single-encounter run this happens to be correct, but the function takes `encounter_id` as a parameter and ignores it. A test scenario that runs two encounters back-to-back through `run_demo()`-style harness would aggregate latency across both into each encounter's audit summary. The dimension filter on `language_pair is not None` does not narrow down to the encounter; it is a guard against missing-dimension entries.

In production, the CloudWatch `Dimensions` field would include `encounter_id`, and the per-encounter aggregation would be a `cloudwatch_client.get_metric_statistics` query keyed on the encounter dimension. The demo could either drop the function or filter on a per-encounter dimension that the CloudWatch put_metric calls add when emitting.

**How to fix:**
Either (a) extend the CloudWatch `dimensions` dict to include `encounter_id` and filter on it in `compute_latency_distribution`:
```python
cloudwatch.put_metric(
    CLOUDWATCH_NAMESPACE, "EndToEndLatencyMs",
    end_to_end_latency_ms, "Milliseconds",
    dimensions={
        "encounter_id":    encounter_id,
        "language_pair":   pair_def.get("pair_id", "unknown"),
        "posture":         state.get("deployment_posture", "unknown"),
    })
```
and:
```python
def compute_latency_distribution(encounter_id):
    relevant = [
        m for m in cloudwatch.metrics
        if m.get("metric_name") == "EndToEndLatencyMs"
        and m.get("dimensions", {}).get(
            "encounter_id") == encounter_id
    ]
```
or (b) document that the function is illustrative and is global by design; production uses CloudWatch metric queries with explicit dimensions.

---

### N8. `archive_text` writes transcripts into the audio bucket; the recipe's prerequisites describe transcripts and audio as separate buckets with different retention

**Files / sections:**
- "Step 3" section, `archive_text`:
  ```python
  def archive_text(text):
      text_hash = _hash_value(text)
      s3_store.put_object(
          bucket=AUDIO_BUCKET,
          key=f"transcripts/{text_hash[:16]}.txt",
          body=(text or "").encode("utf-8"),
          metadata={"text_hash": text_hash})
      return text_hash
  ```
- "Setup" section in the recipe, on bucket layout:
  > Amazon S3 buckets for audio with consent-bounded retention, transcripts and translations with appropriate retention, and the audit archive (with Object Lock in compliance mode and lifecycle to Glacier Deep Archive) ...

**What's wrong:**
The recipe describes three S3 buckets with different retention profiles: audio (hours to days, consent-bound), transcripts and translations (aligned with medical-record retention), and audit archive (HIPAA six-year minimum or longer with Object Lock). The Python collapses transcripts into the AUDIO_BUCKET, which has the wrong retention story (audio retention for transcript content). The encrypted-storage prose at the call site says "Production writes to an SSE-KMS-encrypted S3 bucket; the demo just hashes for the audit reference" but does not call out the bucket-mixing.

**How to fix:**
Add a `TRANSCRIPT_BUCKET` constant near the other resource names, route `archive_text` to it, and add a comment:
```python
TRANSCRIPT_BUCKET = "medical-interpretation-transcripts"

def archive_text(text):
    """Archive transcript content to encrypted storage with
    retention aligned to medical-record retention (longer
    than audio retention, shorter than the audit archive's
    HIPAA six-year minimum). Production writes to an
    SSE-KMS-encrypted S3 bucket with a separate KMS key from
    the audio bucket for blast-radius containment; the demo
    writes to the mock S3 store and references the content
    by hash."""
    text_hash = _hash_value(text)
    s3_store.put_object(
        bucket=TRANSCRIPT_BUCKET,
        key=f"transcripts/{text_hash[:16]}.txt",
        ...)
    return text_hash
```

---

### N9. `wait_time_ms` is hardcoded to 0 in `execute_escalation`; the pseudocode computes it from the dispatch and connect timestamps

**Files / sections:**
- "Step 6" section, `execute_escalation`:
  ```python
  escalation_event = _to_decimal({
      ...
      "wait_time_ms":   0,
      ...
  })
  ```
- Recipe pseudocode for Step 6E:
  ```
  audit_table.put({
      ...
      wait_time_ms:
          interpreter_session.connect_time -
          interpreter_session.dispatch_time,
      ...
  })
  ```

**What's wrong:**
The pseudocode computes the human-interpreter wait time as the difference between dispatch and connect timestamps. The mock interpreter pool sets both timestamps to ISO strings via `_now_iso()`:
```python
dispatch = {
    ...
    "dispatch_time":   _now_iso(),
    "connect_time":    _now_iso(),
}
```
and the Python in `execute_escalation` hardcodes `wait_time_ms` to 0, sidestepping the string-subtraction issue from the pseudocode (which would raise `TypeError` if implemented literally, since you cannot subtract two ISO strings). A learner reading both side-by-side will not understand why the Python diverges; a learner extending the demo to surface real wait-time analytics has to reason out the time-arithmetic correction themselves.

**How to fix:**
Either (a) change the mock to return millisecond timestamps and compute the wait time:
```python
"dispatch_time_ms":   int(
    datetime.now(timezone.utc).timestamp() * 1000),
"connect_time_ms":    int(
    datetime.now(timezone.utc).timestamp() * 1000) + 1500,
```
and:
```python
"wait_time_ms":
    interpreter_session.get("connect_time_ms", 0)
    - interpreter_session.get("dispatch_time_ms", 0),
```
or (b) document the placeholder explicitly:
```python
# wait_time_ms is hardcoded to 0 here because the mock
# interpreter pool does not differentiate dispatch and
# connect timestamps. Production captures both as
# millisecond timestamps from the human-interpreter pool
# integration and emits the difference here as a key
# operational metric (interpreter response time per
# language).
"wait_time_ms":   0,
```

---

### N10. `MockChimeSDK` and `MockConnect` use snake_case method names and parameters; real boto3 is PascalCase

**Files / sections:**
- "Mock Resources for the Demo" section:
  ```python
  class MockConnect:
      def start_contact(self, contact_id, language):
          ...

      def transfer_audio(self, contact_id, from_mode,
                            to_mode, target_session=None):
          ...

  class MockChimeSDK:
      def create_meeting(self, meeting_id, participants):
          ...
  ```

**What's wrong:**
Neither `start_contact` nor `transfer_audio` are real boto3 methods on `connect_client`. The closest real boto3 methods on `connect_client` are `start_outbound_voice_contact`, `start_chat_contact`, `start_contact_streaming`, `transfer_contact`, with PascalCase parameters (`InstanceId`, `ContactId`, `Endpoint`, etc.). On `chime_sdk_client` (the `chime-sdk-meetings` service), `create_meeting` is a real method but the parameters are PascalCase: `ClientRequestToken`, `MediaRegion`, `MeetingHostId`, `ExternalMeetingId`, `NotificationsConfiguration`, etc., with no direct `participants` parameter (you create a meeting first, then add attendees with `create_attendee` per participant).

The mock collapses the per-service surface into intuitive helper methods, which is fine for the demo but does not reference the real methods at all. A learner cannot copy any of the mock call sites onto the real client.

**How to fix:**
Add a docstring comment in each mock pointing at the real boto3 surface:
```python
class MockConnect:
    """
    Stands in for Amazon Connect's contact-center and SIP
    integration. Real boto3 methods on connect_client
    include start_outbound_voice_contact, start_chat_contact,
    start_contact_streaming (with PascalCase parameters
    InstanceId, ContactId, Endpoint, and so on),
    transfer_contact, update_contact_routing_data, and
    stop_contact_streaming. The mock's start_contact and
    transfer_audio collapse the per-flow specifics into a
    pair of helpers; production wires the appropriate
    methods per encounter mode (telephonic, telehealth) and
    per pipeline stage (initial routing, human-interpreter
    handoff).
    """
    ...
```
And similarly for `MockChimeSDK`, with a reminder that meeting creation plus per-participant attendee creation is two boto3 calls, not one.

---

## Summary of Fixes (priority order)

1. **E1:** Replace `boto3.client("transcribe-streaming", ...)` at module top level with either an `amazon-transcribe`-package import (guarded `try`/`except ImportError`) or a comment-only reference and let the mock be the only path. Highest priority because the demo cannot import as written; a learner running `python <file>.py` after `pip install boto3` gets `UnknownServiceError` and never sees any of the seven pipeline stages execute.
2. **W1:** Either drop the fictitious `applied_settings_confidence` field from `MockTranslate` and source the per-utterance translation confidence from a separate quality-estimation step, or rename it to `demo_confidence` with a comment that real `translate_client.translate_text` does not return per-translation confidence and production runs a separate quality-estimation model.
3. **W2:** Add the missing state-machine transitions out of `"translating"` (to `"playing_translation"` after translation completes, to `"idle"` after TTS playback completes or after a short silence). The minimum fix is a `transition_to_state(encounter_id, "idle")` call at the end of `synthesize_translated_audio`. Populate `in_flight_translation` when the state enters `"translating"` so legitimate barge-in events record meaningful translation IDs. Without this, the demo emits five spurious BARGE_IN audit events per six-utterance run.
4. **N1:** Add a comment in the Bedrock branch of `asr_finalized_transcript` showing `response["body"].read().decode("utf-8")` and noting the Anthropic Messages API request shape.
5. **N2:** Add a one-line comment at the Translate call site mapping snake_case mock kwargs to PascalCase boto3 kwargs (`Text`, `SourceLanguageCode`, `TargetLanguageCode`, `TerminologyNames`, `Settings`).
6. **N3:** Either rename `MockPolly.synthesize_speech_streaming` to `synthesize_speech` to match boto3, or document the divergence and move the time-to-first-byte measurement to the caller.
7. **N4:** Add a docstring note to `MockCloudWatch` explaining the dict-vs-list-of-dicts dimensions divergence and the float-vs-Decimal Value-type divergence.
8. **N5:** Either fold `execute_escalation` into `escalate_to_human` so a single function spans the Step 3 verification trigger and the Step 6 pool integration, or rename the placeholder to `flag_for_escalation` and link the per-utterance and `human_escalation` audit rows.
9. **N6:** Filter `count_utterances` to per-utterance rows only (`r.get("utterance_id")`) so the persisted `utterance_count` and the derived `EscalationRate` reflect actual utterances, not utterances plus human_escalation event rows.
10. **N7:** Either extend the CloudWatch `dimensions` dict to include `encounter_id` and filter on it in `compute_latency_distribution`, or document that the function is illustrative and global by design.
11. **N8:** Route `archive_text` to a separate `TRANSCRIPT_BUCKET` (with a docstring explaining the medical-record retention alignment) rather than the AUDIO_BUCKET so the demo matches the bucket layout the recipe describes.
12. **N9:** Either change the mock interpreter pool to expose millisecond timestamps and compute `wait_time_ms` from them, or document the hardcoded 0 explicitly.
13. **N10:** Add docstring comments to `MockConnect` and `MockChimeSDK` pointing at the real boto3 method surface (`start_outbound_voice_contact`, `start_contact_streaming`, `transfer_contact`, `create_meeting` plus `create_attendee` per participant).

---

## Persona-Specific Checklist

- ERROR findings automatically mean FAIL: **1 ERROR (E1: `boto3.client("transcribe-streaming", ...)` raises `UnknownServiceError`).** Automatic FAIL.
- More than 3 WARNING findings means FAIL: **2 WARNINGs**, under that threshold (the FAIL is driven by E1, not by WARNING count).
- boto3 API calls are current (method names, parameters, responses): verified `transcribe-streaming` is not a boto3 service (only `transcribe` exists, for batch jobs); verified `bedrock-runtime`, `connect`, `chime-sdk-meetings`, `polly`, `translate`, `dynamodb`, `s3`, `events`, `cloudwatch`, `secretsmanager` are valid services. The mock-vs-real divergences (snake_case vs PascalCase parameters, fictitious method names like `synthesize_speech_streaming` and `invoke_translation`, fictitious response fields like `applied_settings_confidence`, dict-vs-list-of-dicts CloudWatch dimensions, dict-vs-JSON-string HealthLake-style payloads) are NOTE-level except where they propagate misleading patterns into the production pipeline (which is what makes W1 a WARNING).
- DynamoDB code uses `Decimal`, not `float`: verified. The `_to_decimal` helper is consistently used at every state-table write boundary (`encounter_initiated`, `route_audio_to_asr`, `asr_finalized_transcript`, `synthesize_translated_audio`, `vad_event` (via `transition_to_state`), `execute_escalation`, `encounter_ended`). Mock fixture floats are constructed as `Decimal(...)` directly in `LANGUAGE_PAIR_CONFIGS`, the demo's `MockTranslate` fixtures, the per-segment `per_word_confidence_min`, `snr_db`, and the threshold constants. The `_to_decimal` helper recursively handles dicts and lists. No raw `float` reaches a state-table write path. The one Decimal-related caveat is N4 (CloudWatch's real `put_metric_data` rejects Decimal `Value` and requires `float`), but that is a different surface from DynamoDB.
- S3 paths don't have leading slashes: verified. Every `s3_store.put_object(bucket=..., key=...)` call uses keys like `f"transcripts/{text_hash[:16]}.txt"` and `f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{encounter_id}.json"`. None have leading slashes. The `s3://{AUDIO_BUCKET}/{encounter_id}/patient.ogg` and `s3://{AUDIO_BUCKET}/{encounter_id}/clinician.ogg` URIs constructed for `audio_ref` are also properly formed. The N8 finding about transcript-bucket-vs-audio-bucket is a logical organization issue, not a leading-slash issue.

**Final verdict: FAIL** (driven by the single ERROR).
