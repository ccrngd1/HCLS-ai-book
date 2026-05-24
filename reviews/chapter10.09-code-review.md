# Code Review: Recipe 10.9 — Speech Therapy Assessment and Monitoring (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.09-python-example.md`
- `chapter10.09-speech-therapy-assessment-monitoring.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion is a long but well-structured walkthrough of an eight-stage speech-therapy assessment pipeline (session setup, audio capture, feature extraction, per-instrument scoring, longitudinal comparison, SLP review, documentation generation, audit and surveillance) for one demo scenario (Maya, a 6-year-old female with a moderate phonological disorder presenting for a 12-week reassessment with three administered instruments and three prior sessions in the longitudinal store). It correctly enforces the `Decimal`-not-`float` discipline through the `_to_decimal` helper at every state-table write boundary, uses no leading slashes in S3 keys (`{session_id}/{task_id}.wav`, `{session_id}/features.json`, `{session_id}/slp_report.json`, `audit/YYYY/MM/DD/{session_id}.json` are all properly relative), avoids hardcoded credentials, and respects the per-population validation discipline, the disordered-speech-explicit-target discipline, the per-instrument-aligned scoring discipline, the per-item confidence-based SLP-review-flagging discipline, the longitudinal-trajectory discipline, the pediatric consent infrastructure (HIPAA + biometric-data-law + FERPA + COPPA framework selection), the per-deployment-context configuration discipline, and the post-deployment surveillance discipline the recipe demands. The eight pseudocode steps map cleanly to the corresponding Python entry points (`session_initiated`, `capture_session_audio`, `extract_features`, `score_instruments`, `compute_longitudinal`, `slp_review_initiated` + `slp_submits_review`, `generate_documentation`, `audit_and_surveillance`) plus `run_assessment_pipeline` and `run_demo` as orchestration. The IAM action names listed in Setup (`sagemaker:InvokeEndpoint`, `sagemaker:InvokeEndpointAsync`, `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `transcribe:StartMedicalTranscriptionJob`, `transcribe:GetMedicalTranscriptionJob`, `healthlake:CreateResource`, `healthlake:UpdateResource`, `kms:Decrypt`, `kms:GenerateDataKey`, `states:StartExecution`) are correct.

There is one notable WARNING (a confirmed pseudocode-to-Python inconsistency where `compute_instrument_summary` is called with `scoring_method` rather than `summary_method`, causing the `connected_speech_summary` aggregation branch to be unreachable and connected-speech instruments to silently produce `summary_value: Decimal("0")` instead of an aggregated linguistic-feature summary) plus a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (1) is well under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 1 |
| NOTE     | 8 |

---

## WARNING Findings

### W1. `compute_instrument_summary` is called with `scoring_method` instead of `summary_method`; the `connected_speech_summary` branch is unreachable and connected-speech instruments silently produce `summary_value: Decimal("0")`

**Files / sections:**
- "Configuration and Constants" section, `INSTRUMENT_DEFINITIONS["connected_speech_picture_description"]`:
  ```python
  "scoring_method":    "linguistic_feature_summary",
  ...
  "summary_method":  "connected_speech_summary",
  ```
- "Step 4" section, `score_instruments`:
  ```python
  scoring_method = instrument_def.get("scoring_method")
  ...
  auto_summary = compute_instrument_summary(
      scoring_method=scoring_method,
      items=auto_scored)
  ```
- "Step 6" section, `slp_submits_review`:
  ```python
  final_summary = compute_instrument_summary(
      scoring_method=instrument_def.get(
          "scoring_method"),
      items=all_items)
  ```
- "Step 4" section, `compute_instrument_summary`:
  ```python
  def compute_instrument_summary(scoring_method, items):
      ...
      if scoring_method == "percent_consonants_correct":
          ...
      if scoring_method == "connected_speech_summary":
          # Aggregate the linguistic features across items.
          merged = {}
          for it in items:
              for k, v in it.get(
                      "supporting_evidence", {}).items():
                  merged[k] = v
          return {
              "items_scored":      len(items),
              "linguistic_summary": merged,
          }
      return {
          "items_scored":   len(items),
          "summary_value":  Decimal("0"),
      }
  ```

**What's wrong:**
The instrument definition for `connected_speech_picture_description` declares `scoring_method: "linguistic_feature_summary"` (used in `score_item` to score each item) and `summary_method: "connected_speech_summary"` (intended to aggregate items). But both call sites of `compute_instrument_summary` pass `instrument_def.scoring_method` instead of `instrument_def.summary_method`, so the dispatcher receives `"linguistic_feature_summary"` and matches none of the two conditional branches. It falls through to the default:
```python
return {
    "items_scored":   len(items),
    "summary_value":  Decimal("0"),
}
```

The result is that the connected-speech instrument's auto-summary is always `summary_value: Decimal("0")` regardless of the linguistic features extracted upstream, the `connected_speech_summary` branch in `compute_instrument_summary` is dead code that never executes, and the `summary_method` field on the instrument definition is never read.

This matches the recipe's pseudocode in main-recipe Step 4B, which explicitly uses `summary_method`:
```
auto_summary = compute_instrument_summary(
    scoring_method:
        instrument_def.summary_method,
    items: auto_scored_items)
```
The pseudocode is internally inconsistent (the parameter is named `scoring_method` but the value passed is `summary_method`); the Python copies the parameter name and ends up passing the wrong value.

The demo for Maya runs to completion because the articulation instrument (`articulation_inventory_gfta_aligned`) has `scoring_method == summary_method == "percent_consonants_correct"` and the `phonological_pattern_analysis` instrument has empty `scoring_items` so `compute_instrument_summary` is called with no items and short-circuits to `items_scored: 0`. But the connected-speech instrument silently produces a wrong summary that downstream goal-progress evaluation, norm comparison, and severity classification all then operate on. A learner extending the demo (adding a different connected-speech task, a fluency probe with `scoring_method != summary_method`, or any new instrument with a separate aggregation method) hits the same silent failure.

**How to fix:**
Either (a) change the two call sites to pass `instrument_def.summary_method` while keeping the parameter name, with a clarifying comment that the parameter value is the aggregation method:
```python
auto_summary = compute_instrument_summary(
    # The parameter is named scoring_method for symmetry
    # with score_item, but the value passed is the
    # instrument's summary aggregation method.
    scoring_method=instrument_def.get("summary_method"),
    items=auto_scored)
```
Or, more architecturally honest, (b) rename the parameter to `summary_method` and update the dispatch:
```python
def compute_instrument_summary(summary_method, items):
    ...
    if summary_method == "percent_consonants_correct":
        ...
    if summary_method == "connected_speech_summary":
        ...
```
The recipe pseudocode in Step 4B should be updated to match (the pseudocode currently muddles the two by naming the parameter `scoring_method` and passing `summary_method`).

**Severity rationale:** WARNING because the demo runs to completion and produces output, but the connected-speech instrument is silently broken: a reader inspecting the final `auto_summary` for the connected-speech instrument finds `summary_value: 0` and might reasonably attribute it to a feature-extraction problem rather than a summary-dispatch bug. The bug propagates through `apply_norms`, `classify_severity`, and the longitudinal comparison without surfacing a clear error.

---

## NOTE Findings

### N1. Mock SageMaker invocations use snake_case kwargs; real boto3 `invoke_endpoint` is PascalCase

**Files / sections:**
- "Mock Resources for the Demo" section, `MockSageMakerRuntime.invoke_endpoint`:
  ```python
  def invoke_endpoint(self, endpoint_name, body,
                        content_type="application/json"):
      ...
  ```
- "Step 3" section, the call sites:
  ```python
  alignment_response = sagemaker_mock.invoke_endpoint(
      endpoint_name=alignment_endpoint,
      content_type="application/json",
      body=json.dumps({...}, default=str))
  ```

**What's wrong:**
The real boto3 `sagemaker_runtime.invoke_endpoint` parameters are `EndpointName`, `Body`, `ContentType`, `Accept`, `CustomAttributes`, `TargetModel`, `TargetVariant`, `InferenceId` (all PascalCase). The Setup section's IAM list correctly names the action (`sagemaker:InvokeEndpoint`), and the production-pattern comment in the mock docstring shows the right PascalCase form, but a learner copy-pasting the call site needs to translate the kwargs from snake_case to PascalCase. The same divergence appeared in recipes 10.7 and 10.8.

**How to fix:**
Add a one-line comment at the first `invoke_endpoint` call site reminding the reader that real boto3 uses `EndpointName=..., Body=..., ContentType=...`. Alternatively rename the mock signature to PascalCase to mirror the boto3 client. The latter is more architecturally honest; the former is less disruptive.

---

### N2. Mock `MockBedrock` returns `{"body": json.dumps(...)}`; real Bedrock `invoke_model` returns a `StreamingBody` requiring `.read().decode("utf-8")`

**Files / sections:**
- "Mock Resources for the Demo" section, `MockBedrock.render_slp_report` and `render_family_summary`:
  ```python
  return {"body": json.dumps(response, default=str)}
  ```
- "Step 7" section, the call sites:
  ```python
  slp_report_response = bedrock_mock.render_slp_report(...)
  slp_report = json.loads(
      slp_report_response["body"]).get("content", "")
  ```

**What's wrong:**
The real `bedrock_runtime.invoke_model` returns `{"body": StreamingBody, "contentType": "application/json", ...}` where `StreamingBody` requires `.read()` to access the bytes and `.decode("utf-8")` before `json.loads`. The mock skips the `.read()` step (it returns a JSON string directly), which is correct for what the mock does but slightly hides the real shape. Additionally, the request body for Anthropic Claude on Bedrock is the Anthropic Messages API shape (`messages`, `system`, `max_tokens`, `tools`, `tool_choice`, `anthropic_version`); the mock's `render_slp_report(session_id, report_input, guardrail_id)` signature collapses the request shape into a tuple of high-level fields. The "Gap to Production" section calls out the Anthropic Messages API shape in prose but the call site doesn't show the parsing pattern. Same divergence as recipes 10.7 and 10.8.

**How to fix:**
Add a short comment in `generate_documentation` immediately before parsing the Bedrock response:
```python
# In production: real bedrock_runtime.invoke_model returns
# a StreamingBody under the "body" key, so the parse is:
#     body_text = response["body"].read().decode("utf-8")
#     parsed = json.loads(body_text)
# The request body for Anthropic Claude on Bedrock is the
# Anthropic Messages API shape (messages, system, max_tokens,
# anthropic_version, optionally tools + tool_choice for
# structured output via tool-use). The mock returns a JSON
# string directly to keep the example short.
```

---

### N3. `MockHealthLake.create_resource` accepts `resource` as a dict; real `healthlake_client.create_resource` requires `Resource` as a JSON-encoded string

**Files / sections:**
- "Mock Resources for the Demo" section, `MockHealthLake.create_resource`:
  ```python
  def create_resource(self, datastore_id, resource_type,
                        resource):
      ...
      "resource":       dict(resource),
  ```
- "Step 7" section, the call:
  ```python
  healthlake.create_resource(
      datastore_id=HEALTHLAKE_DATASTORE_ID,
      resource_type=resource["resource_type"],
      resource=resource["body"])
  ```

**What's wrong:**
The real `healthlake_client.create_resource` parameters are `DatastoreId` (string) and `Resource` (string — the JSON-encoded FHIR resource). The mock takes the dict directly, which is friendlier for the demo but diverges from the boto3 shape: a learner would need to `json.dumps(resource_body)` and pass the result as the `Resource` kwarg. The Setup section's IAM list correctly names `healthlake:CreateResource`, but the call site doesn't show the JSON-encoding step. Same divergence appeared in recipe 10.8.

**How to fix:**
Add a one-line comment at the call site:
```python
for resource in fhir_resources:
    # Real boto3:
    #   healthlake_client.create_resource(
    #       DatastoreId=HEALTHLAKE_DATASTORE_ID,
    #       ResourceType=resource["resource_type"],
    #       Resource=json.dumps(resource["body"]))
    # The Resource parameter is a JSON-encoded string, not
    # a dict; the mock takes the dict for readability.
    healthlake.create_resource(
        datastore_id=HEALTHLAKE_DATASTORE_ID,
        resource_type=resource["resource_type"],
        resource=resource["body"])
```

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
- All call sites pass `dimensions={"deployment_context": ..., "population_profile": ..., "instrument_id": ...}` as dicts.

**What's wrong:**
Real `cloudwatch.put_metric_data` takes `Namespace=...` and `MetricData=[{...}]` where each metric data item has `MetricName`, `Value`, `Unit`, `Timestamp`, and `Dimensions=[{"Name": "instrument_id", "Value": "articulation_inventory_gfta_aligned"}, ...]`. The mock's dict-shaped dimensions are simpler to read but diverge from the real shape; a learner who replaces the mock with `cloudwatch_client.put_metric_data(...)` will need to transform the dict into a list of name-value dicts. This pattern is repeated half a dozen times across the demo (in `session_initiated`, `capture_session_audio`, `score_instruments`, `slp_submits_review`, `audit_and_surveillance`), so the divergence propagates. Same issue as recipes 10.7 and 10.8.

**How to fix:**
Add a brief note in the `MockCloudWatch` docstring:
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

### N5. `slp_submits_review` json round-trip plus `_to_decimal` does not actually re-Decimal serialized values; the comment is misleading

**Files / sections:**
- "Step 6" section, `slp_submits_review`:
  ```python
  edited_scores = json.loads(
      json.dumps(state.get("instrument_scores", {}),
                   default=str))

  # Re-decimal the freshly deserialized scores so
  # downstream arithmetic stays in Decimal.
  edited_scores = _to_decimal(edited_scores)
  ```
- "Configuration and Constants" section, `_to_decimal`:
  ```python
  def _to_decimal(value):
      if isinstance(value, float):
          return Decimal(str(value))
      if isinstance(value, dict):
          return {k: _to_decimal(v) for k, v in value.items()}
      if isinstance(value, list):
          return [_to_decimal(v) for v in value]
      return value
  ```

**What's wrong:**
The deep-copy via `json.dumps(... default=str)` plus `json.loads` converts every Decimal in the original `instrument_scores` to a string (because `default=str` is what Decimal serializes to when it's not natively JSON-encodable). Then `_to_decimal` is called on the deserialized result, but `_to_decimal` only converts `float` to `Decimal` (and recurses into dicts and lists). It does not convert strings to Decimal. The comment "Re-decimal the freshly deserialized scores so downstream arithmetic stays in Decimal" describes an intent that the code does not actually achieve.

The reason the demo still runs without error is that every downstream arithmetic operation that reads these values wraps them in `Decimal(str(...))` defensively (in `apply_item_edit`, `apply_norms`, `classify_severity`, etc.), so the string values get re-converted on use. But the comment misleads about what `_to_decimal` does, and a learner who relies on the post-`_to_decimal` shape having Decimal values for direct arithmetic will hit `TypeError` or silent string-comparison bugs.

**How to fix:**
Either (a) replace the json-round-trip deep-copy with `copy.deepcopy(state.get("instrument_scores", {}))`, which preserves Decimal types and makes the subsequent `_to_decimal` call unnecessary; or (b) acknowledge the round-trip behavior in the comment:
```python
# Deep-copy via json round-trip; default=str converts
# Decimals to strings. The downstream arithmetic uses
# Decimal(str(...)) defensively, so strings work even
# though _to_decimal does not convert them back.
edited_scores = json.loads(
    json.dumps(state.get("instrument_scores", {}),
                 default=str))
```
The first fix is cleaner; the second preserves the existing behavior with honest documentation.

---

### N6. `score_item` for `linguistic_feature_summary` returns a hardcoded `Decimal("0.78")` confidence with no explanation

**Files / sections:**
- "Step 4" section, `score_item`:
  ```python
  if scoring_method == "linguistic_feature_summary":
      ling = features.get("linguistic_features", {})
      if not ling:
          return {
              "observed":      "unknown",
              "score_value":   Decimal("0"),
              "confidence":    Decimal("0"),
              "evidence": {
                  "reason": "no_linguistic_features"},
          }
      return {
          "observed":      "scored",
          "score_value":   Decimal("1"),
          "confidence":    Decimal("0.78"),
          "evidence":      ling,
      }
  ```

**What's wrong:**
The `Decimal("0.78")` confidence is a magic number that is not derived from any underlying signal (it isn't a function of the linguistic features, the transcript quality, or the alignment confidence). A learner reading this might think the value means something operationally; in production the linguistic-feature-summary confidence would come from the linguistic-feature extractor's per-feature confidence (NLP-pipeline confidence on syntactic-complexity, lexical-diversity, narrative-structure, etc.) rolled up. The hardcoded value also happens to be above the connected-speech instrument's `confidence_threshold` of `Decimal("0.60")`, so it never triggers the SLP-review-flag branch in the demo, which conveniently sidesteps the W1 dead-code branch but obscures the per-item-confidence-flagging mechanism for connected speech.

**How to fix:**
Either compute a per-feature aggregate confidence from the linguistic-feature extractor's outputs, or document the placeholder explicitly:
```python
return {
    "observed":      "scored",
    "score_value":   Decimal("1"),
    # Placeholder confidence. Production rolls up the per-
    # linguistic-feature confidence from the NLP pipeline
    # (syntactic-complexity confidence, narrative-structure
    # confidence, lexical-diversity confidence). The demo
    # uses 0.78 to keep the connected-speech item above
    # the 0.60 review threshold without modeling the
    # underlying confidence sources.
    "confidence":    Decimal("0.78"),
    "evidence":      ling,
}
```

---

### N7. `lookup_population_profile` silently maps unhandled age bands ("under_4", "13_17") to "adult_typical"

**Files / sections:**
- "Mock Resources for the Demo" section, `lookup_population_profile`:
  ```python
  def lookup_population_profile(patient_context):
      ...
      age_band = _bucket_age(age_years)
      ...
      if age_band == "4_8":
          return ("pediatric_disordered_age_4_8"
                  if has_disorder
                  else "pediatric_typical_age_4_8")
      if age_band == "9_12":
          return ("pediatric_disordered_age_9_12"
                  if has_disorder
                  else "pediatric_typical_age_9_12")
      if age_band == "adult":
          return ("adult_dysarthric"
                  if patient_context.get(
                      "has_dysarthria", False)
                  else "adult_typical")
      return "adult_typical"
  ```

**What's wrong:**
`_bucket_age` produces five age bands: `under_4`, `4_8`, `9_12`, `13_17`, and `adult`. `lookup_population_profile` only handles `4_8`, `9_12`, and `adult`; `under_4`, `13_17`, and `not_disclosed` (returned when `age_years` is `None`) all silently fall through to the final `return "adult_typical"`. The downstream pipeline then routes a 3-year-old patient through the adult-typical SageMaker endpoints (`speech-therapy-alignment-adult-typical`, `speech-therapy-phoneme-adult-typical`), which is the opposite of the per-population-validation discipline the recipe is teaching. A learner extending the demo to a younger pediatric patient would not see an error, but the system would invoke models outside their validation envelopes for that patient.

The `POPULATION_PROFILES` dict also defines `adult_voice_disorder` and `adult_aphasic`, neither of which is reachable through `lookup_population_profile`. They appear only in the endpoint-routing maps, never in the routing function.

**How to fix:**
Either route the unhandled age bands to a "needs SLP review for population assignment" sentinel that short-circuits downstream scoring with an indeterminate result, or extend the function with explicit branches plus a final-default raise:
```python
if age_band == "under_4":
    # Production: pediatric_typical_age_under_4 endpoint
    # exists separately; the demo does not host it.
    return "pediatric_typical_age_4_8"  # closest available
if age_band == "13_17":
    return "adult_typical"  # closest available
if age_band == "not_disclosed":
    raise ValueError(
        "Patient age must be disclosed for "
        "population-profile selection.")
```
The exact mapping is a clinical choice; what matters is that the function does not silently misroute.

---

### N8. `audit_and_surveillance` step numbering jumps from 8B to 8D; Step 8C is referenced in the recipe but not implemented in the Python

**Files / sections:**
- "Step 8" section, `audit_and_surveillance`:
  ```python
  # Step 8A: schedule audio deletion per consent terms.
  ...
  # Step 8B: per-population surveillance metrics.
  ...
  # Step 8D: longitudinal-store update with this session.
  ```
- Main recipe pseudocode for Step 8 includes Step 8C:
  ```
  // Step 8C: SageMaker Model Monitor and Clarify
  // jobs run on a scheduled cadence against the
  // inference traffic.
  ```

**What's wrong:**
The recipe pseudocode has four sub-steps (8A audit-record-and-archive, 8B per-population CloudWatch metrics, 8C SageMaker Model Monitor / Clarify scheduled jobs, 8D longitudinal-store update). The Python implements 8A, 8B, and 8D but skips 8C. That is reasonable (Model Monitor and Clarify run as out-of-band scheduled jobs and are not part of the per-session pipeline), but the comment numbering jumps from 8B to 8D without acknowledging 8C, leaving a reader to wonder whether something is missing.

**How to fix:**
Add a single-line comment between 8B and 8D:
```python
# Step 8C is intentionally skipped here: SageMaker Model
# Monitor and Clarify jobs run as scheduled out-of-band
# surveillance over the inference-traffic baseline rather
# than on the per-session pipeline path. See the "Real
# SageMaker endpoint hosting per population" section of
# the gap-to-production for the production wiring.
```

---

### N9. `start_medical_transcription` mock hardcodes `Type="DICTATION"`; for connected-speech tasks `Type="CONVERSATION"` is more appropriate

**Files / sections:**
- "Mock Resources for the Demo" section, `MockTranscribeMedical.start_medical_transcription`:
  ```python
  def start_medical_transcription(self, job_name,
                                     audio_uri, language,
                                     specialty="PRIMARYCARE"):
      # Real boto3:
      #   transcribe_client.start_medical_transcription_job(
      #     ...
      #     Type="DICTATION",
      #     ...
      ...
  ```
- "Step 3" section calls this for connected-speech tasks:
  ```python
  if task_type == "connected_speech_picture_description" \
          or task_type in (
              "connected_speech_story_retell",
              "connected_speech_conversation"):
      transcribe_mock.start_medical_transcription(
          job_name=...,
          audio_uri=captured_task["audio_ref"],
          language=...)
  ```

**What's wrong:**
Transcribe Medical's `Type` parameter accepts `CONVERSATION` or `DICTATION`. `DICTATION` is intended for single-speaker provider-dictating-into-a-microphone audio (like recipe 10.4). Connected-speech tasks in speech-therapy assessment (picture description, story retell, conversation) are closer to `CONVERSATION`-typed audio because they involve the patient speaking spontaneously, often with the SLP providing prompts. The hardcoded `DICTATION` in the production-pattern comment teaches the wrong type for the downstream task. Additionally, the mock's `start_medical_transcription` immediately returns `TranscriptionJobStatus: "COMPLETED"`, collapsing the polling loop that real production requires.

**How to fix:**
Either parameterize the `Type` value per task (`CONVERSATION` for connected-speech, `DICTATION` for any single-speaker task), or change the production-pattern comment to show task-type-aware selection:
```python
# Real boto3:
#   transcribe_client.start_medical_transcription_job(
#     MedicalTranscriptionJobName=job_name,
#     Media={"MediaFileUri": audio_uri},
#     LanguageCode=language,
#     Specialty=specialty,
#     Type="CONVERSATION",  # or "DICTATION" for single-
#                           # speaker tasks
#     OutputBucketName=...,
#     OutputKey=...)
# Then poll get_medical_transcription_job until the status
# is COMPLETED. The mock collapses this to an immediate
# return for readability.
```

---

## Summary of Fixes (priority order)

1. **W1:** Either change both `compute_instrument_summary` call sites to pass `instrument_def.summary_method` (with a clarifying comment), or rename the parameter to `summary_method` and update the dispatch. The recipe pseudocode in Step 4B should be updated to match. Highest priority because the connected-speech instrument silently produces a wrong summary that propagates through norm comparison, severity classification, and longitudinal analysis.
2. **N1:** Add a one-line comment at the SageMaker `invoke_endpoint` call sites mapping snake_case mock kwargs to PascalCase boto3 kwargs (`EndpointName`, `Body`, `ContentType`).
3. **N2:** Add a comment in `generate_documentation` showing `response["body"].read().decode("utf-8")` and noting the Anthropic Messages API request shape.
4. **N3:** Add a comment at the HealthLake call site showing `Resource=json.dumps(...)` JSON-string-encoded.
5. **N4:** Add a docstring note to `MockCloudWatch` explaining the dict-vs-list-of-dicts dimensions divergence.
6. **N5:** Either replace the json-round-trip deep-copy in `slp_submits_review` with `copy.deepcopy`, or update the comment to acknowledge that `_to_decimal` does not convert the post-deserialization strings back to Decimal.
7. **N6:** Document the `Decimal("0.78")` placeholder confidence in `score_item` or compute it from the linguistic-feature extractor's per-feature confidence.
8. **N7:** Handle the `under_4`, `13_17`, and `not_disclosed` age bands explicitly in `lookup_population_profile` rather than silently routing them to `adult_typical`.
9. **N8:** Add a one-line note in `audit_and_surveillance` between Step 8B and Step 8D explaining that Step 8C is intentionally skipped because Model Monitor and Clarify run as scheduled out-of-band jobs.
10. **N9:** Either parameterize the `Type` value per task in `MockTranscribeMedical.start_medical_transcription` or change the production-pattern comment to show `CONVERSATION` for connected-speech tasks, and add a polling-loop pattern for the async transcription job.

---

## Persona-Specific Checklist

- ERROR findings automatically mean FAIL: **0 ERRORs**, no automatic FAIL.
- More than 3 WARNING findings means FAIL: **1 WARNING**, well under threshold.
- boto3 API calls are current (method names, parameters, responses): verified `sagemaker_runtime.invoke_endpoint` parameter shape (PascalCase), `bedrock_runtime.invoke_model` `StreamingBody` response, `transcribe_client.start_medical_transcription_job` parameter shape including `Type` enum, `healthlake_client.create_resource` `Resource` JSON-string parameter, EventBridge `put_events` `Entries=[{Source, DetailType, EventBusName, Detail}]` shape, CloudWatch `put_metric_data` shape with `Dimensions=[{Name, Value}, ...]`, IAM action names. The divergences are all NOTE-level (mock simplifications acknowledged in the gap-to-production section but not always at the call sites).
- DynamoDB code uses `Decimal`, not `float`: verified. The `_to_decimal` helper is consistently used at every state-table write boundary (`session_initiated`, `capture_session_audio`, `extract_features`, `score_instruments`, `compute_longitudinal`, `slp_submits_review`, `generate_documentation`, `audit_and_surveillance`, plus the longitudinal-store puts in `audit_and_surveillance` and the demo bootstrap loop). Mock fixture floats are constructed as `Decimal(...)` directly in `INSTRUMENT_DEFINITIONS`, `NORM_REFERENCE_LOOKUP`, `PATIENT_DEMOGRAPHICS`, `ACTIVE_GOALS`, `LINGUISTIC_FEATURE_FIXTURES`, `PROSODIC_FEATURE_FIXTURES`, `PHONOLOGICAL_PATTERN_FIXTURES`, the SageMaker fixture confidences, and the capture-fixture quality scores. The `_to_decimal` helper recursively handles dicts and lists. No raw `float` reaches a state-table write path. The N5 finding about the json-round-trip-plus-`_to_decimal` pattern in `slp_submits_review` is a comment-quality issue, not a Decimal-vs-float correctness issue: the downstream arithmetic re-wraps the strings in `Decimal(str(...))` defensively.
- S3 paths don't have leading slashes: verified. Every `s3_store.put_object(bucket=..., key=...)` and `s3_store.get_object(bucket=..., key=...)` call uses keys like `f"{session_id}/{task['task_id']}.wav"`, `f"{session_id}/features.json"`, `f"{session_id}/slp_report.json"`, and `f"audit/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{session_id}.json"`. None have leading slashes. The `s3://{bucket}/{key}` URIs constructed for `audio_ref` and the feature-archive references are also properly formed.

**Final verdict: PASS.**
