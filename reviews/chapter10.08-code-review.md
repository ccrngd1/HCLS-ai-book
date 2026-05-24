# Code Review: Recipe 10.8 — Voice Biomarker Detection (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.08-python-example.md`
- `chapter10.08-voice-biomarker-detection.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end across both demo scenarios (Carl, the 68-year-old male English-speaker submitting a Parkinson's-screening sample on a clinic-grade microphone with a four-sample baseline that supports trajectory analysis; Marcus, the 58-year-old male Spanish-speaker submitting a respiratory-monitoring cough sample on a smartphone). It correctly enforces the `Decimal`-not-`float` discipline through the `_to_decimal` helper at every state-table write boundary, uses no leading slashes in S3 keys (`{session_id}/{task_id}.wav`, `{session_id}/features.json`, `async-input/{session_id}/{indication}.json`, `audit/YYYY/MM/DD/{session_id}.json` are all properly relative), avoids hardcoded credentials, and respects the per-indication-validation discipline, the per-cohort-calibration discipline, the eligibility-checking discipline, the indeterminate-result discipline, the recording-chain-awareness discipline, the longitudinal-trajectory discipline, the biometric-data-governance discipline, and the post-market-surveillance discipline the recipe demands. The seven pseudocode steps map cleanly to seven Python entry points (`capture_initiated`, `extract_features`, `check_eligibility`, `score_biomarkers`, `package_interpretation`, `deliver_to_workflow` plus `clinician_acknowledges_result`, `audit_and_surveillance`) plus `run_biomarker_pipeline` and `run_demo` as orchestration. The IAM action names listed in Setup (`sagemaker:InvokeEndpoint`, `sagemaker:InvokeEndpointAsync`, `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `transcribe:StartTranscriptionJob`, `comprehendmedical:DetectEntitiesV2`, `healthlake:CreateResource`, `kms:Decrypt`, `kms:GenerateDataKey`, `states:StartExecution`) are correct.

There is one notable WARNING (a latent crash in `summarize_ineligibility` when a candidate indication has no model card; the no-model-card-available path constructs a simplified eligibility dict that the summarizer then crashes on with `KeyError`) plus a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (1) is well under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 1 |
| NOTE     | 8 |

---

## WARNING Findings

### W1. `summarize_ineligibility` raises `KeyError` when called on the simplified "no model card" eligibility dict

**Files / sections:**
- "Step 3" section, `check_eligibility` constructs a simplified dict for missing model cards:
  ```python
  for indication in candidate_indications:
      model_card = lookup_model_card(indication)
      if not model_card:
          eligibility_results[indication] = {
              "eligible": False,
              "reason":   "no_model_card_available",
          }
          continue
  ```
- "Step 4" section, `score_biomarkers` calls `summarize_ineligibility` on every ineligible entry:
  ```python
  for indication, elig in eligibility.items():
      if not elig.get("eligible"):
          scores[indication] = {
              "status": "NOT_ASSESSABLE",
              "ineligibility_reasons":
                  summarize_ineligibility(elig),
          }
          continue
  ```
- "Step 3" section, `summarize_ineligibility` accesses keys that don't exist on the simplified dict:
  ```python
  def summarize_ineligibility(elig):
      reasons = []
      if not elig["demographic_fit"]["eligible"]:
          ...
  ```

**What's wrong:**
When a candidate indication has no model card, `check_eligibility` writes `{"eligible": False, "reason": "no_model_card_available"}` to `eligibility_results[indication]`. Then `score_biomarkers` calls `summarize_ineligibility(elig)` which immediately accesses `elig["demographic_fit"]["eligible"]`, raising `KeyError: 'demographic_fit'`. The whole scoring run crashes mid-loop before any indication that does have a model card gets scored.

The demo never triggers this path because both `parkinsons_screening` and `respiratory_monitoring` have model cards in `MODEL_CARDS`. But a learner adapting the demo to add a new indication name to `candidate_indications` before adding the corresponding model card would hit this immediately, and the failure would not be obvious from the stack trace (it looks like a missing dict key, not a missing model card).

**How to fix:**
Either widen `summarize_ineligibility` to handle the simplified shape:
```python
def summarize_ineligibility(elig):
    reasons = []
    # Handle the simplified "no model card available" shape.
    if "reason" in elig and "demographic_fit" not in elig:
        return [elig["reason"]]
    if not elig["demographic_fit"]["eligible"]:
        ...
```
Or have `check_eligibility` produce a shape consistent with the full envelope (with empty/sentinel values) when the model card is missing, so downstream code doesn't have to special-case. Either fix is defensible; the first is less intrusive.

**Severity rationale:** WARNING (not ERROR) because the demo runs to completion without triggering the path. It is misleading because the code structure suggests the no-model-card branch is handled, but the next stage in the pipeline crashes when it is hit.

---

## NOTE Findings

### N1. Mock SageMaker invocations use snake_case kwargs; real boto3 `invoke_endpoint` and `invoke_endpoint_async` are PascalCase

**Files / sections:**
- "Mock Resources" section, `MockSageMakerRuntime`:
  ```python
  def invoke_endpoint(self, endpoint_name, body,
                        content_type="application/json"):
      ...
  def invoke_endpoint_async(self, endpoint_name,
                              input_location):
      ...
  ```
- "Step 4" section, the call sites:
  ```python
  raw_response = sagemaker_mock.invoke_endpoint(
      endpoint_name=endpoint_name,
      content_type="application/json",
      body=json.dumps(model_input, default=str))
  ```

**What's wrong:**
The real boto3 `sagemaker_runtime.invoke_endpoint` parameters are `EndpointName`, `Body`, `ContentType`, `Accept`, `CustomAttributes`, `TargetModel`, `TargetVariant`, `InferenceId` (all PascalCase). The async variant uses `EndpointName`, `InputLocation`, `ContentType`, `Accept`, `InvocationTimeoutSeconds`, `InferenceId`. The Setup section's IAM list correctly names the actions (`sagemaker:InvokeEndpoint`, `sagemaker:InvokeEndpointAsync`), and the production-pattern comments above the mock calls show the right intent, but a learner copy-pasting the call site would need to translate the kwargs.

**How to fix:**
Add a one-line comment at the call site reminding the reader that real boto3 uses `EndpointName=..., Body=..., ContentType=...`, or rename the mock signatures to PascalCase. The latter is more architecturally honest; the former is less disruptive.

---

### N2. `MockComprehendMedical.detect_entities` should be `detect_entities_v2`; real boto3 uses capitalized `Text` parameter

**Files / sections:**
- "Mock Resources" section, `MockComprehendMedical`:
  ```python
  def detect_entities(self, text):
      ...
  ```
- "Step 2" section, the call site:
  ```python
  clinical_entities = (
      comprehend_mock.detect_entities(
          text=transcript))
  ```

**What's wrong:**
The boto3 client method is `comprehend_medical.detect_entities_v2(Text=text)` (capitalized `Text`). `DetectEntities` (without `_v2`) has been deprecated in favor of `DetectEntitiesV2`, and the Setup section's IAM list correctly specifies `comprehendmedical:DetectEntitiesV2`. The mock's lowercase Pythonic `text` is fine, but the method name diverges from the boto3 SDK and the deprecated-API ambiguity is worth resolving.

**How to fix:**
Rename `MockComprehendMedical.detect_entities` to `detect_entities_v2`, update the call site, and add a one-line comment that the real boto3 parameter is `Text=...` (capitalized).

---

### N3. `apply_calibration`'s sigmoid is a linear approximation; the dead `hasattr(Decimal, "max")` fallback obscures intent

**Files / sections:**
- "Step 4" section, `apply_calibration`:
  ```python
  return (Decimal("0.5")
          + z * Decimal("0.18")).max(
              Decimal("0.01")).min(
              Decimal("0.99")) \
      if hasattr(Decimal, "max") else \
      min(Decimal("0.99"),
            max(Decimal("0.01"),
                  Decimal("0.5") + z
                  * Decimal("0.18")))
  ```

**What's wrong:**
Two issues. First, `hasattr(Decimal, "max")` is always `True` (Python's `decimal.Decimal` exposes `max(other, context=None)` and `min(other, context=None)` as instance methods), so the second branch of the conditional is dead code. Second, `Decimal.max()` and `.min()` accept exactly one operand and return the larger/smaller of `self` and that operand, so the chained `score.max(0.01).min(0.99)` is a roundabout way of writing `min(max(score, Decimal("0.01")), Decimal("0.99"))` (Python's built-in `min`/`max` work fine on Decimals; no fallback is needed). A learner might come away thinking Python's built-ins don't work on Decimal, or struggle to read what the chain is doing.

**How to fix:**
Replace with the standard idiom and keep the comment about it being a linear approximation:
```python
# Linear approximation of sigmoid; production uses real
# sigmoid (math.exp via float, then convert back to Decimal).
clamped = min(Decimal("0.99"),
                max(Decimal("0.01"),
                      Decimal("0.5") + z * Decimal("0.18")))
return clamped
```
The same dead-`hasattr` pattern appears in `compute_patient_baseline` for `variance.sqrt()` (Decimal does have `.sqrt()`); same fix.

---

### N4. Step 2 pseudocode includes "Voice activity detection and segmentation" but the Python skips it; the simplification is not flagged

**Files / sections:**
- Recipe pseudocode for Step 2:
  ```
  [Voice activity detection and segmentation]
   - Trim silence from sample boundaries
   - Identify task-specific segments
   - Reject segments below quality threshold
  ```
- Python `extract_features` jumps directly to per-task feature extraction without a VAD stage.

**What's wrong:**
The captured-segments fixture is assumed to already be VAD-trimmed and task-segmented. In production, the audio coming off the device often contains leading/trailing silence, room noise, the prompt-read-back, and other content that needs to be removed before the feature pipeline runs. The omission is reasonable for a teaching example but worth a one-line acknowledgment in `extract_features` so a learner knows what they need to add.

**How to fix:**
Add a docstring note in `extract_features`:
```python
def extract_features(session_id):
    """
    ...
    Note: production runs voice-activity detection and
    task-specific segmentation on each captured audio_ref
    before the feature pipeline. The demo assumes the
    captured segments are already trimmed and task-segmented;
    a real implementation calls a VAD service (a custom
    Lambda running webrtcvad, silero-vad, or a SageMaker
    endpoint hosting a VAD model) at this point.
    """
```

---

### N5. SageMaker async pattern collapses the polling loop; the `retrieve_async_output` mock-only abstraction is not flagged

**Files / sections:**
- "Step 4" section, async-mode invocation:
  ```python
  async_response = (
      sagemaker_mock.invoke_endpoint_async(
          endpoint_name=endpoint_name,
          input_location=input_object["uri"]))
  raw_response = sagemaker_mock.retrieve_async_output(
      output_location=async_response[
          "OutputLocation"],
      fixture_key=async_response["_fixture_key"])
  ```

**What's wrong:**
The real `sagemaker_runtime.invoke_endpoint_async` returns immediately with `{"OutputLocation": "s3://...", "InferenceId": "...", "FailureLocation": "s3://..."}`. The actual model output is written to the OutputLocation S3 object asynchronously (typically tens of seconds to minutes for a voice-biomarker workload). Production polls the S3 object (or, more commonly, uses an SNS topic configured on the endpoint to notify when the output is ready) and then `s3.get_object` on the OutputLocation to retrieve the result. The mock's `retrieve_async_output` collapses both the polling and the S3 read into a single helper that takes a `_fixture_key`, which is not part of the real API surface.

**How to fix:**
Add a comment in the async branch:
```python
# In production: invoke_endpoint_async returns immediately;
# the actual output is written to OutputLocation
# asynchronously. Poll S3 for the output object (or use
# the endpoint's SNS notification topic, which is the
# preferred production pattern), then s3.get_object on
# the OutputLocation to retrieve the result. A long-blocking
# Lambda is not appropriate; Step Functions handles this
# with a Wait + GetObject loop, or EventBridge handles the
# SNS-driven completion event.
```

---

### N6. Mock `MockBedrock` returns `{"body": json.dumps(...)}`; real Bedrock `invoke_model` returns a `StreamingBody` requiring `.read().decode()`

**Files / sections:**
- "Mock Resources" section, `MockBedrock.render_clinician_summary` and `render_patient_message`:
  ```python
  return {"body": json.dumps(response, default=str)}
  ```
- "Step 5" and "Step 6" call sites:
  ```python
  summary_response = (
      bedrock_mock.render_clinician_summary(...))
  summary_body = json.loads(summary_response["body"])
  ```

**What's wrong:**
The real `bedrock_runtime.invoke_model` returns `{"body": StreamingBody, "contentType": "application/json", ...}` where `StreamingBody` requires `.read()` to access the bytes and `.decode("utf-8")` before `json.loads`. The mock skips the `.read()` step (it returns a JSON string directly), which is correct for what the mock does but slightly hides the real shape. Additionally, the body of the request to Anthropic Claude on Bedrock is not freeform; it is the Anthropic Messages API shape with `messages`, `system`, `max_tokens`, `tools` (for forcing structured output via tool-use), `tool_choice`, and an `anthropic_version` field. The Setup section mentions the `tools` field for structured output, but the recipe's Step 5 pseudocode shows `response_format: {type: "json_schema", schema: ...}` which is OpenAI-style and does not work directly with Anthropic's Bedrock surface.

**How to fix:**
Add a comment in `package_interpretation` immediately before parsing the response:
```python
# In production: real bedrock_runtime.invoke_model returns
# a StreamingBody under the "body" key, so the parse is:
#     body_text = response["body"].read().decode("utf-8")
#     parsed = json.loads(body_text)
# The request body for Anthropic Claude on Bedrock is the
# Anthropic Messages API shape (messages, system, max_tokens,
# anthropic_version, optionally tools + tool_choice for
# structured output via tool-use). The pseudocode's
# response_format field in the main recipe is OpenAI-style;
# the Anthropic equivalent is forcing a tool call.
```

---

### N7. HealthLake `create_resource` real API takes `Resource` as a JSON-encoded string, not a dict; the mock simulates correctly but the real shape is not documented at the call site

**Files / sections:**
- "Mock Resources" section, `MockHealthLake.create_observation` accepts a dict:
  ```python
  def create_observation(self, datastore_id, observation):
      ...
      "observation":    dict(observation),
  ```
- "Step 6" section, the call:
  ```python
  observation_response = healthlake.create_observation(
      datastore_id=HEALTHLAKE_DATASTORE_ID,
      observation=observation)
  ```

**What's wrong:**
The real `healthlake_client.create_resource` parameters are `DatastoreId` (string) and `Resource` (string - the JSON-encoded FHIR resource). The mock takes the dict directly, which is friendlier for the demo but diverges from the boto3 shape: a learner would need to `json.dumps(observation)` and pass the result as the `Resource` kwarg. The Setup section's IAM list correctly names `healthlake:CreateResource`, but the call site doesn't show the JSON-encoding step.

**How to fix:**
Add a one-line comment at the call site:
```python
# Real boto3:
#   healthlake_client.create_resource(
#       DatastoreId=HEALTHLAKE_DATASTORE_ID,
#       ResourceType="Observation",
#       Resource=json.dumps(observation))
# The Resource parameter is a JSON-encoded string, not a
# dict; the mock takes the dict for readability.
observation_response = healthlake.create_observation(
    datastore_id=HEALTHLAKE_DATASTORE_ID,
    observation=observation)
```

---

### N8. `route_to_clinical_review` is a noop that only logs; the production "create an EHR alert regardless of biomarker outcome" intent is buried in the comment

**Files / sections:**
- "Step 2" section, `route_to_clinical_review`:
  ```python
  def route_to_clinical_review(session_id, clinical_entities):
      """
      Route incidentally-mentioned actionable clinical content
      to the clinical-review workflow regardless of the
      biomarker output. Production creates an EHR alert;
      the demo records an event.
      """
      audit_log({...})
  ```

**What's wrong:**
The function name suggests it routes the content somewhere, but the implementation only writes an audit log entry. The recipe's Step 2 pseudocode says "the orchestration layer routes any clinically actionable content...to the appropriate clinical workflow" — this is a non-trivial production responsibility (incidental chest-pain mention in a spontaneous-speech sample is a high-stakes clinical signal that must reach a clinician). A learner might wire the demo's noop into production thinking the routing already works.

**How to fix:**
Either rename the function to `log_incidental_clinical_content_for_routing` to make the noop nature obvious, or add a stronger comment that ties the production behavior to a specific call (`ehr_cds.create_alert(...)` with a "spontaneous_speech_incidental" priority). Even a `TODO (production): create EHR alert; this currently only logs` would be enough to flag the gap.

---

## Summary of Fixes (priority order)

1. **W1:** Make `summarize_ineligibility` tolerant of the simplified no-model-card eligibility dict (or have `check_eligibility` produce a uniform shape). Highest priority because the path crashes when triggered.
2. **N1:** Add a one-line comment at the SageMaker call sites mapping the snake_case mock kwargs to PascalCase boto3 kwargs (`EndpointName`, `Body`, `ContentType`, `InputLocation`).
3. **N2:** Rename `MockComprehendMedical.detect_entities` to `detect_entities_v2` and note that real boto3 uses capitalized `Text=...`.
4. **N3:** Replace the dead-`hasattr` Decimal clamp pattern with `min(max(score, Decimal("0.01")), Decimal("0.99"))`; same fix in `compute_patient_baseline` for `.sqrt()`.
5. **N4:** Add a docstring note in `extract_features` that VAD/segmentation is assumed already done and that production runs a VAD stage first.
6. **N5:** Expand the async-SageMaker comment to show the polling-or-SNS pattern and note that long-blocking Lambdas are not appropriate.
7. **N6:** Add a comment in `package_interpretation` showing `response["body"].read().decode("utf-8")` and noting the Anthropic Messages API shape (and that `response_format`/`json_schema` is OpenAI-style, not Anthropic-on-Bedrock).
8. **N7:** Add a comment at the HealthLake call site showing the real boto3 `create_resource` shape with `Resource=json.dumps(...)`.
9. **N8:** Either rename `route_to_clinical_review` to reflect its noop nature or add a strong TODO at the call site.

---

## Persona-Specific Checklist

- ERROR findings automatically mean FAIL: **0 ERRORs**, no automatic FAIL.
- More than 3 WARNING findings means FAIL: **1 WARNING**, well under threshold.
- boto3 API calls are current (method names, parameters, responses): verified `sagemaker_runtime.invoke_endpoint`/`invoke_endpoint_async` parameter shapes, `bedrock_runtime.invoke_model` `StreamingBody` response, Comprehend Medical `detect_entities_v2` deprecation, Transcribe Medical job lifecycle, HealthLake `create_resource` `Resource` JSON-string parameter, EventBridge `put_events` shape, CloudWatch `put_metric_data` shape. The divergences are all NOTE-level (mock simplifications acknowledged in surrounding comments).
- DynamoDB code uses `Decimal`, not `float`: verified. The `_to_decimal` helper is consistently used at every state-table write (capture-session table puts and updates, trajectory-table puts, clinician-feedback puts). Mock fixture floats are never written directly; every numeric value in `MODEL_CARDS`, `CALIBRATION_LOOKUP`, `ACOUSTIC_FEATURE_FIXTURES`, `EMBEDDING_FIXTURES` is constructed as `Decimal(...)` directly. The `_to_decimal` helper recursively handles dicts and lists. No raw `float` reaches a state-table write path.
- S3 paths don't have leading slashes: verified. Every `s3_store.put_object(bucket=..., key=...)` call uses keys like `f"{session_id}/{task['task_id']}.wav"`, `f"{session_id}/features.json"`, `f"async-input/{session_id}/{indication}.json"`, `f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{session_id}.json"`. None have leading slashes. The `s3://` URIs constructed for the audio_ref and feature-archive references are also properly formed.

**Final verdict: PASS.**
