# Code Review: Recipe 10.2 - Voicemail Transcription and Classification

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-23
**Files reviewed:**
- `chapter10.02-voicemail-transcription-classification.md` (main recipe pseudocode)
- `chapter10.02-python-example.md` (Python companion)

**Validation performed:**
- Walked the seven pseudocode steps against the Python functions one-to-one (Step 1 `ON voicemail_arrival` -> `ingest_voicemail`; Step 2 `preprocess_audio` -> `preprocess_audio`; Step 3 `start_asr_job`/`handle_asr_completion` -> same names; Step 4 `classify_voicemail` -> `classify_voicemail`; Step 5 `enrich_voicemail` -> `enrich_voicemail`; Step 6 `route_voicemail` -> `route_voicemail`; Step 7 `ON staff_action` -> `record_staff_action`)
- Verified service-name strings on the boto3 clients: `s3`, `dynamodb` (resource), `transcribe`, `comprehendmedical`, `bedrock-runtime`, `sns`, `events` (EventBridge), `cloudwatch` are all correct identifiers
- Hand-traced each demo scenario through the pipeline (see Finding 1 below for the discovered ERROR)
- Verified `Decimal(str(...))` conversion is used at every point a float crosses into a DynamoDB-bound dict (`_to_decimal` helper is invoked on every `voicemail_records.put`, `voicemail_records.update`, and `triage_queue.put` payload that contains scores, confidences, or thresholds)
- Verified Decimal-at-the-DynamoDB-boundary discipline: the urgency lexicon uses `Decimal("0.20")`, the confidence thresholds (`ASR_MIN_AVG_CONFIDENCE`, `INTENT_CONFIDENCE_THRESHOLD`, `URGENCY_CONFIDENCE_THRESHOLD`) are Decimal at definition, the `MIN_SPEECH_RATIO` is Decimal, and the simulated speech-ratio float is wrapped in `Decimal(str(...))` before comparison
- Confirmed no S3 keys have leading slashes (`f"voicemails/{datetime...:%Y/%m/%d}/{voicemail_id}.{audio_format}"` and `f"transcripts/{voicemail_id}/transcript.json"` both start with the prefix directly)
- Verified the deploy-time guardrail asserts every resource-name and configuration constant is non-empty (the `for _name, _value in [...]: assert _value` block at module load includes both Bedrock identifiers, both bucket names, the topic ARN, the event bus name, and the CloudWatch namespace)
- Verified the urgency-rule-layer-first discipline: `scan_for_urgency_phrases` is called before `bedrock_mock.invoke_model`, the matched phrase is captured separately for audit, and `_max_urgency` enforces that the rule layer can escalate but never de-escalate
- Verified the ASR-confidence-gate-on-classification discipline: `handle_asr_completion` returns `continue_to_classification: False` and short-circuits to `human_review_low_asr_confidence` when `avg_confidence < ASR_MIN_AVG_CONFIDENCE` or `low_conf_count > ASR_MAX_LOW_CONF_WORDS`
- Verified the structured-triage-record discipline: every stage writes its outputs back to the voicemail record with a versioned classifier-prompt-version, intent-taxonomy-version, and urgency-lexicon-version stamp on the classification block
- Verified the emergent-notification path: the SNS publish only fires when `urgency == "emergent"`, the payload is intentionally minimal (no transcript, no medication names, no patient demographics), and the `EMERGENT_NOTIFICATION_SENT` audit event records the urgency_source so the rule-layer-vs-classifier provenance is preserved
- Verified the emergent-fan-out: when urgency is emergent, `clinical_escalation` is added to `queue_targets` regardless of intent, matching the recipe's "emergent urgency always also fans out to the clinical-escalation queue" guarantee
- Verified the priority-key construction puts higher urgency rank first when sorted descending; observed (see Finding 4 below) that within-tier ordering does not match the recipe text

---

## Summary

The Python companion is structurally faithful to the main recipe's seven pseudocode steps and to the architectural picture (asynchronous ingestion with audio persistence to encrypted S3, pre-processing with length-and-VAD filtering and short-circuit dispositions, async ASR submission with confidence gating before classification, urgency-rule-layer-first classification combined with foundation-model intent and urgency classification and Comprehend Medical entity extraction, patient-context enrichment with ANI lookup and repeat-caller detection, priority-aware queue routing with emergent SNS notifications, and staff-action capture with classifier-disagreement logging). The urgency lexicon is illustrative-but-versioned, the per-axis confidence thresholds (ASR, intent, urgency) are calibrated independently with explicit Decimal types, the rule layer-can-only-escalate discipline is enforced through `_max_urgency`, the audit-log helper actively strips `transcript`, `dob`, and `patient_demographics` from the structured log payload, and the emergent SNS payload deliberately excludes PHI in favor of an authenticated click-through.

That said, this companion ships with one ERROR. The ERROR concerns the demo's fixture-keying mechanism: `MockTranscribeMedical` (and by extension the downstream `MockBedrock` and `MockComprehendMedical` matchers) is keyed by `voicemail_id`, but `voicemail_id` is generated dynamically inside `ingest_voicemail` as `"vm-" + uuid.uuid4().hex[:12]`. The fixtures in `run_demo` use the literal keys `"vm-fixture-refill"`, `"vm-fixture-chest-pain"`, and `"vm-fixture-low-confidence"`, and the `if scenario["fixture_id"]: pass` block in the per-scenario loop is a literal no-op (the comment claims "Re-key the fixtures under the actual voicemail_id generated in this scenario," but no re-keying is performed). The result is that for every scenario except the pocket-dial one (which short-circuits before ASR), the transcribe mock returns its default "no fixture available for this voicemail" transcript with empty `items`, `handle_asr_completion` falls through to its no-word-confidences branch (`avg_confidence = 0.50`), the ASR gate fires (`0.50 < ASR_MIN_AVG_CONFIDENCE = 0.65`), and the voicemail is short-circuited to `human_review_low_asr_confidence` without ever invoking the urgency rule layer, the classifier, the entity extractor, the enricher, the router, or the emergent-notification path. The chest-pain scenario does not escalate. The pharmacy queue is never populated. The emergent SNS publish is never called. The reclassification at the end records `machine_intent=None, machine_urgency=None` because the first voicemail's `classification` block is empty.

Beyond the ERROR, the companion ships with one WARNING and several NOTEs. The WARNING is that the demo and its fixture data imply that `ComprehendMedical.detect_entities_v2` returns RxNorm-linked and ICD-10-linked concepts directly on each entity (the fixture data has `"RxNormConcepts": [{"Code": "29046", "Description": "lisinopril"}]` and the code reads `e.get("RxNormConcepts", [])` and `e.get("ICD10CMConcepts", [])` per entity); in production, `detect_entities_v2` does not return ontology-linked concepts on the entity, and a learner copying this pattern against the real API would find that `e.get("RxNormConcepts", [])` always returns `[]`. RxNorm linking comes from a separate `infer_rx_norm` call (likewise `infer_icd10_cm` and `infer_snomed_ct`).

The NOTEs cover smaller items: `BEDROCK_INFERENCE_PROFILE_ARN` is defined, asserted to be set, and described in the prose as the production wiring's pinning mechanism, but is not referenced anywhere in code (not even in the production-comment skeletons); the `_build_priority_key` produces a sort key that, when sorted descending, puts the newest voicemail first within an urgency tier, contradicting the recipe text's "Within an urgency level, older messages come first" guarantee (the in-code comment acknowledges this, but the demo's `items_for_queue` inherits the wrong ordering and a learner copying it inherits the bug); the `MockBedrock.invoke_model` parameter is `model_id` (snake_case) while real `bedrock_runtime.invoke_model` uses `modelId` (camelCase) per boto3, which can mislead a learner; the LLM classifier and Comprehend Medical entity extraction calls are described as parallel in the pseudocode (`invoke_model_async` plus `await`) but run sequentially in the Python with no comment marking the simplification; and the global `transcribe_mock`, `bedrock_mock`, and `comprehend_mock` are initialized only inside `run_demo`, so importing the module and calling `process_voicemail` directly without first running the demo will fail with `AttributeError: 'NoneType' object has no attribute 'start_medical_transcription_job'`.

---

## Verdict: FAIL

One ERROR (the fixture-keying mechanism is broken; the demo does not produce the documented expected output for three of its four primary scenarios). One WARNING (the entity-extraction pattern teaches an incorrect Comprehend Medical API integration). Five NOTEs.

Per the persona-instruction rule (ERROR findings automatically mean FAIL), this companion fails review and should be re-worked before it ships. The ERROR is the load-bearing one: the rule-layer-fires-on-chest-pain scenario, which is the chapter's marquee illustration of the urgency-rule-layer-first discipline, never actually fires because the chest-pain transcript never makes it past the ASR gate. The fix is small (re-key the fixtures by the generated `voicemail_id` after `ingest_voicemail`, or have the scenarios pass a deterministic `voicemail_id` through the source event for the demo, or restructure the mocks to key by `source_message_id` which the scenarios already supply). The fix is small enough that the recipe's pedagogical structure is sound; the bug is in the orchestration glue.

Recipe 10.2 inherits the chapter's operational discipline (urgency-rule-layer-first, per-axis confidence thresholding, audit-everything, versioned-prompts-and-lexicons) and adds the voicemail-specific behaviors (asynchronous ingestion with audio persistence, length and VAD short-circuits before ASR, ASR-confidence-gate-on-classification, repeat-caller detection within a 48-hour window, emergent-fan-out to clinical_escalation regardless of intent, separate medication-alignment cross-reference against the patient's active medication list). All of those are structurally present in the code; the demo just doesn't get to exercise the most-load-bearing ones because of Finding 1.

---

## Findings

### Finding 1: The Demo's Fixture-Keying Mechanism Is Broken; Three of the Four Scenarios Will Not Produce Their Documented Output Because the Transcribe Mock Always Returns the Default "No Fixture Available" Transcript

- **Severity:** ERROR
- **File:** `chapter10.02-python-example.md`
- **Location:** `MockTranscribeMedical.start_medical_transcription_job` (the `fixture = self._fixtures.get(voicemail_id, {...})` lookup line); `run_demo` (the per-scenario loop with `if scenario["fixture_id"]: pass`); the fixture dictionaries `transcript_fixtures`, `classification_fixtures`, `entity_fixtures` (all keyed on literal demo names rather than on the dynamically-generated voicemail_id)
- **Description:**

  `MockTranscribeMedical` is constructed with a `transcript_fixtures` dict keyed by `voicemail_id`:

  ```python
  transcript_fixtures = {
      "vm-fixture-refill":         {"transcript_text": "...", "items": [...]},
      "vm-fixture-chest-pain":     {"transcript_text": "...", "items": [...]},
      "vm-fixture-low-confidence": {"transcript_text": "...", "items": [...]},
  }
  ```

  And `start_medical_transcription_job` uses the `voicemail_id` argument to look up the fixture:

  ```python
  def start_medical_transcription_job(self, job_name, voicemail_id,
                                       media_uri, ...):
      fixture = self._fixtures.get(voicemail_id, {
          "transcript_text": "no fixture available for this voicemail",
          "items": [],
      })
      ...
  ```

  But `voicemail_id` is generated dynamically inside `ingest_voicemail`:

  ```python
  voicemail_id = "vm-" + uuid.uuid4().hex[:12]
  ```

  So the `voicemail_id` passed into `start_medical_transcription_job` is always something like `"vm-9f3a2c1d4e5b"` (12 hex chars), never `"vm-fixture-refill"` or `"vm-fixture-chest-pain"` or `"vm-fixture-low-confidence"`.

  The `run_demo` loop appears to acknowledge the mismatch but does nothing about it:

  ```python
  for scenario in scenarios:
      print("\n" + "#" * 60)
      print(f"# SCENARIO: {scenario['name']}")
      print("#" * 60)
      vm_id = process_voicemail(scenario["source_event"])
      if scenario["fixture_id"]:
          # Re-key the fixtures under the actual voicemail_id
          # generated in this scenario so subsequent stages
          # (classifier, entities) can find them. In a real
          # pipeline, the transcript IS the input to those
          # stages; the demo keys the mocks for clarity.
          pass    # <-- LITERAL NO-OP
      processed_voicemail_ids.append(vm_id)
  ```

  The comment describes what should happen ("Re-key the fixtures under the actual voicemail_id generated in this scenario") but the body is `pass`. No re-keying occurs.

  Hand-traced consequences for each scenario:

  - **`routine_refill_success`** (ANI `5715551234`, duration 32s, simulated_speech_ratio 0.88):
    - Ingest: voicemail_id = `"vm-XXXXXXXXXXXX"` (random).
    - Preprocess: passes (speech_ratio 0.88 >= 0.20, duration 32 in [3, 300]).
    - ASR submit: `transcribe_mock.start_medical_transcription_job(..., voicemail_id="vm-XXXXXXXXXXXX", ...)`. Lookup `self._fixtures.get("vm-XXXXXXXXXXXX", default)` returns the default fixture (empty items, "no fixture available" transcript).
    - ASR complete: `items` is empty -> `word_confidences` is empty -> `avg_confidence = Decimal("0.50")`. Then `0.50 < ASR_MIN_AVG_CONFIDENCE = 0.65` -> ASR gate fires -> `terminal_disposition: human_review_low_asr_confidence`. `continue_to_classification: False`.
    - **Pharmacy queue is never populated. Margaret Chen's active-medications enrichment never runs. The `medication_alignment` cross-reference never runs.**

  - **`emergent_chest_pain_rule_layer`** (ANI `8045555678`, duration 48s, simulated_speech_ratio 0.91):
    - Same flow as above. ASR gate fires for the same reason.
    - **The urgency rule layer never scans the transcript. "chest pain" is never matched. `_max_urgency("emergent", classifier_urgency)` is never called. The emergent SNS publish never fires. The `clinical_escalation` queue never receives the record. The `EmergentNotificationsSent` CloudWatch metric is never incremented.**

  - **`pocket_dial_short_circuit`** (ANI `5559998888`, duration 8s, simulated_speech_ratio 0.05):
    - Preprocess: speech_ratio 0.05 < 0.20 -> short-circuits at `_short_circuit_preprocessing` with `disposition: no_speech_detected`. Works correctly.
    - This is the only scenario that produces its documented output, because it never reaches the ASR stage.

  - **`low_asr_confidence_to_human_review`** (ANI `9145557777`, duration 22s, simulated_speech_ratio 0.65):
    - Preprocess: passes (0.65 >= 0.20).
    - ASR: same default-fixture path. ASR gate fires.
    - This scenario produces its documented output (`human_review_low_asr_confidence`) but for the wrong reason: it's not the documented "transcript with low per-word confidence scores" path; it's the "no items at all in the transcript JSON" no-word-confidences fallback path with the default-stuck `Decimal("0.50")` average.

  - **Reclassification (`record_staff_action`)** depends on `processed_voicemail_ids[0]` (the routine-refill scenario) having a populated `classification` block. Because `classify_voicemail` never ran, the record's `classification` is `{}`, so:

    ```python
    classification = record.get("classification", {})
    ...
    "machine_intent":  classification.get("intent"),    # None
    "machine_urgency": classification.get("urgency"),   # None
    ```

    The `CLASSIFIER_DISAGREEMENT_CAPTURED` audit event is recorded with `machine_intent=None, machine_urgency=None`. This does not exercise the disagreement-capture pattern the recipe is teaching.

  The demo summary at the bottom of `run_demo` (which prints the queue contents, the SNS publishes, and the metric counts) will show:

  - `Triage queue records placed`: 0 (no scenario reaches `route_voicemail`)
  - `Emergent SNS publishes`: 0 (the chest-pain scenario never escalates)
  - `Cross-system events emitted`: 0 (no scenario reaches the EventBridge fan-out in `route_voicemail`; only `record_staff_action` emits one event for the reclassification)
  - `Triage queue contents (highest priority first):` empty for every queue

  This is the opposite of what the demo's documentation claims. The documented expected behavior of the chest-pain scenario ("rule layer fires, escalates to emergent urgency regardless of classifier output, SNS notification sent") is the chapter's marquee illustration of the urgency-rule-layer-first discipline, and the demo as shipped does not exercise it.

- **Recommended fix:** Several reasonable options, in increasing order of invasiveness:

  - **Option A (smallest patch):** Replace the `pass` block with actual re-keying. After `process_voicemail` runs for a scenario with a `fixture_id`, copy the fixture dicts under the dynamically-generated `vm_id`:

    ```python
    if scenario["fixture_id"]:
        fid = scenario["fixture_id"]
        if fid in transcript_fixtures:
            transcribe_mock._fixtures[vm_id] = transcript_fixtures[fid]
    ```

    But this fix has a chicken-and-egg problem: by the time the loop knows `vm_id`, `process_voicemail` has already run (including ASR submission), so the re-keying happens too late.

  - **Option B (preferred):** Have `ingest_voicemail` accept an optional `voicemail_id_override` parameter (or read one from `source_event["voicemail_id_override"]`) so the demo can pass deterministic IDs through the pipeline:

    ```python
    voicemail_id = (source_event.get("voicemail_id_override")
                    or "vm-" + uuid.uuid4().hex[:12])
    ```

    Then each scenario passes `"voicemail_id_override": "vm-fixture-refill"` (or similar) in its `source_event`, and the fixtures match deterministically. The override is documented as "for deterministic demo replay only; production never sets this."

  - **Option C:** Re-key the mocks to look up by `source_message_id` (which each scenario already supplies as `vendor-msg-100001` etc.) rather than by `voicemail_id`. The mocks need to thread `source_message_id` through `start_medical_transcription_job`'s arguments.

  - **Option D:** Restructure `MockBedrock` to do its substring matching directly on the transcript text (which it already does) and have `MockTranscribeMedical` accept a fixture argument at job-submit time rather than looking it up by voicemail_id. Then the per-scenario loop passes the fixture explicitly.

  Option B is the cleanest because it preserves the existing fixture-by-id structure and only adds a single optional override path. Whichever fix is chosen, after the fix the four scenarios should hand-trace to:

  - `routine_refill_success`: pharmacy queue populated, urgency `routine`, intent `medication_refill`, no SNS publish, enrichment populates Margaret Chen's active medications, medication_alignment shows `lisinopril` matches.
  - `emergent_chest_pain_rule_layer`: nurse_triage and clinical_escalation queues populated, urgency `emergent` via `urgency_source: rule_layer_chest_pain`, one SNS publish to `EMERGENT_VOICEMAIL_TOPIC_ARN`, `EmergentNotificationsSent` metric incremented.
  - `pocket_dial_short_circuit`: terminal disposition `no_speech_detected`, no triage queue record.
  - `low_asr_confidence_to_human_review`: terminal disposition `human_review_low_asr_confidence`, no triage queue record, ASR gate fires on the actual low-per-word-confidence content rather than the no-items fallback.

---

### Finding 2: The Demo's Entity Extraction Pattern Implies that `Comprehend Medical.detect_entities_v2` Returns RxNorm-Linked and ICD-10-Linked Concepts Directly on Each Entity, but the Real API Does Not; Ontology Linking Requires Separate `infer_rx_norm`, `infer_icd10_cm`, and `infer_snomed_ct` Calls

- **Severity:** WARNING
- **File:** `chapter10.02-python-example.md`
- **Location:** `classify_voicemail` (the `medications = [... "rxnorm_codes": e.get("RxNormConcepts", []) ...]` and `conditions = [... "icd10_codes": e.get("ICD10CMConcepts", []) ...]` list comprehensions); `entity_fixtures` in `run_demo` (which puts `RxNormConcepts` and `ICD10CMConcepts` directly on the entity dicts)
- **Description:**

  The Python companion's classify_voicemail extracts ontology-linked concept lists per entity:

  ```python
  medications = [
      {"text": e.get("Text"),
       "score": Decimal(str(e.get("Score", 0))),
       "rxnorm_codes": e.get("RxNormConcepts", [])}
      for e in raw_entities if e.get("Category") == "MEDICATION"
  ]
  conditions = [
      {"text": e.get("Text"),
       "score": Decimal(str(e.get("Score", 0))),
       "icd10_codes": e.get("ICD10CMConcepts", [])}
      for e in raw_entities if e.get("Category") == "MEDICAL_CONDITION"
  ]
  ```

  And the fixture data in `run_demo` puts these concepts directly on each entity:

  ```python
  entity_fixtures = {
      "lisinopril": [{
          "Text":     "lisinopril",
          "Score":    0.97,
          "Category": "MEDICATION",
          "RxNormConcepts": [{"Code": "29046",
                               "Description": "lisinopril"}],
      }],
      ...
  }
  ```

  In the real Comprehend Medical API, `DetectEntitiesV2` does not return RxNorm-linked or ICD-10-linked concepts on each entity. The response shape from `detect_entities_v2` is:

  ```json
  {
    "Entities": [{
      "Id": 0,
      "BeginOffset": ...,
      "EndOffset": ...,
      "Score": 0.97,
      "Text": "lisinopril",
      "Category": "MEDICATION",
      "Type": "GENERIC_NAME",
      "Traits": [...],
      "Attributes": [...]
    }]
  }
  ```

  RxNorm linking is a separate API call (`infer_rx_norm`) that returns a different response shape with `RxNormConcepts` per entity. ICD-10 linking is `infer_icd10_cm`. SNOMED CT is `infer_snomed_ct`. None of these are returned by `detect_entities_v2`.

  The recipe's prose is technically accurate ("often with mappings to standard ontologies (RxNorm for medications, ICD-10 for conditions, SNOMED for clinical concepts)"), but the demo's wiring suggests those mappings come back from a single `detect_entities_v2` call. A learner pointing this code at the real Comprehend Medical service would find that `e.get("RxNormConcepts", [])` returns `[]` for every entity, the medication-alignment cross-reference in Step 5C silently has no codes to compare against, and the structured triage record's `entities.medications[*].rxnorm_codes` is always empty.

- **Recommended fix:** Two reasonable options:

  - **Option A:** Show the production-correct integration by adding a second pseudocode-aligned call. After `detect_entities_v2`, call `infer_rx_norm` for the medication-bearing transcript (and optionally `infer_icd10_cm` for the conditions). The demo can mock both. The fixtures then split: `entity_fixtures["lisinopril"]` returns just the entity, and a new `rxnorm_fixtures["lisinopril"]` returns the RxNorm-linked concepts. This doubles the mock surface but accurately teaches the API.

  - **Option B:** Drop the RxNorm and ICD-10 fields from the per-entity dicts and add an inline comment that ontology linking is a separate API call (`infer_rx_norm`, `infer_icd10_cm`, `infer_snomed_ct`) that the recipe defers as a production-readiness concern. The demo's medication_alignment cross-reference falls back to text-based matching rather than RxNorm-code matching (which it already does in `enrich_voicemail` via `name in vm_med_text or vm_med_text in name`).

  Option A is more comprehensive but adds a moving part. Option B is smaller and preserves the demo's clarity at the cost of leaving the ontology-linking pattern as a "see the production-readiness section" reference. Either fix should also update the prose summary at the top to clarify which APIs the demo is actually exercising.

---

### Finding 3: `BEDROCK_INFERENCE_PROFILE_ARN` Is Defined, Asserted to Be Set, and Described in the Prose as the Production Wiring's Pinning Mechanism, but Is Not Referenced Anywhere in Code (Including the Production-Comment Skeletons)

- **Severity:** NOTE
- **File:** `chapter10.02-python-example.md`
- **Location:** `BEDROCK_INFERENCE_PROFILE_ARN` definition (in the constants block); the deploy-time guardrail `assert _value` block; the IAM-permissions narrative ("`bedrock:InvokeModel` for the classifier, scoped to the specific foundation-model ARN and inference profile in use"); `classify_voicemail` Step 4B (the `bedrock_mock.invoke_model(model_id=BEDROCK_CLASSIFIER_MODEL_ID, body=classifier_prompt)` call); `_build_classifier_prompt` (no inference profile reference)
- **Description:**

  The constants block defines and asserts the inference profile ARN:

  ```python
  BEDROCK_INFERENCE_PROFILE_ARN  = (
      "arn:aws:bedrock:us-east-1:000000000000:inference-profile/"
      "voicemail-classifier-v1")
  ...
  for _name, _value in [
      ...
      ("BEDROCK_INFERENCE_PROFILE_ARN", BEDROCK_INFERENCE_PROFILE_ARN),
  ]:
      assert _value, f"{_name} must be set before deploying."
  ```

  And the prose explains its purpose ("In production, pin to a specific model version and inference profile so a model upgrade doesn't silently change classifier behavior"). But the actual `bedrock_mock.invoke_model` call only uses `BEDROCK_CLASSIFIER_MODEL_ID`, never `BEDROCK_INFERENCE_PROFILE_ARN`:

  ```python
  classifier_response = bedrock_mock.invoke_model(
      model_id=BEDROCK_CLASSIFIER_MODEL_ID,
      body=classifier_prompt)
  ```

  And there is no production-comment skeleton above the call showing the real `bedrock_runtime.invoke_model(modelId=BEDROCK_INFERENCE_PROFILE_ARN, body=..., contentType="application/json", accept="application/json")` (or the appropriate `inferenceProfileArn=` parameter, depending on the API mode). The constant is defined and asserted but never referenced in any code path.

  A learner trying to understand how to wire production Bedrock calls against a pinned inference profile will see the constant, search for its usage, find none, and have to consult the AWS docs to figure out how it's actually consumed.

- **Recommended fix:** Either (a) add a production-comment skeleton above the `bedrock_mock.invoke_model` call showing the real `bedrock_runtime.invoke_model` invocation with the inference profile ARN passed as `modelId` (when invoking via inference profile, the boto3 `modelId` parameter accepts the inference-profile ARN directly), or (b) remove the unused constant and the deploy-time assertion and adjust the prose to describe the pinning concept without claiming the demo wires it. Option (a) is more useful because the inference-profile-ARN-as-modelId pattern is a common gotcha.

---

### Finding 4: `_build_priority_key` Produces a Sort Key That, When Sorted Descending, Puts Newer Voicemails First Within an Urgency Tier; the Recipe Text Says Older Voicemails Should Come First Within a Tier so Routine Messages Don't Sit Forever

- **Severity:** NOTE
- **File:** `chapter10.02-python-example.md`
- **Location:** `_build_priority_key` (the `f"U#{urgency_rank:03d}#{recorded_at_iso}"` format string); `MockTriageQueue.items_for_queue` (the `sorted(items, key=lambda r: r.get("priority_key", ""), reverse=True)` call)
- **Description:**

  The recipe text in the routing section says:

  > **Priority-aware ordering.** Emergent urgency comes first. Within an urgency level, older messages come first (so a routine message does not sit in the queue forever just because new routine messages keep arriving).

  The Python's priority key is `f"U#{urgency_rank:03d}#{recorded_at_iso}"`. With urgency ranks 1-4 zero-padded to three digits, the format produces strings like:

  - `U#004#2026-05-23T03:14:22Z` (emergent, recent)
  - `U#004#2026-05-22T18:00:00Z` (emergent, older)
  - `U#002#2026-05-23T03:14:22Z` (routine, recent)
  - `U#002#2026-05-22T18:00:00Z` (routine, older)

  When sorted descending with `reverse=True`, the order is:

  1. `U#004#2026-05-23T03:14:22Z` (emergent, recent)
  2. `U#004#2026-05-22T18:00:00Z` (emergent, older)
  3. `U#002#2026-05-23T03:14:22Z` (routine, recent)
  4. `U#002#2026-05-22T18:00:00Z` (routine, older)

  Within an urgency tier, the recent voicemail comes first. The recipe says it should be the older one.

  The in-code comment on `_build_priority_key` acknowledges this:

  > Sorting descending on this string puts the highest urgency first; within an urgency rank, sorting descending on the timestamp string is wrong (it would put newest first), so the queue UI flips the order within tier. A real implementation usually uses two sort attributes via a DynamoDB GSI; the demo collapses them into one for simplicity.

  But the demo's `items_for_queue` is the only "queue UI" the demo has, and it does not flip the order within tier. So the demo's queue ordering is wrong by the recipe's own criterion. A learner copying `_build_priority_key` and `items_for_queue` into their own demo inherits the bug and will not realize it until they observe in production that older routine voicemails are sitting at the bottom of the queue while newer routine voicemails get attended to first.

- **Recommended fix:** Either (a) construct the timestamp portion of the key as a "ticks-until-far-future" value (e.g., `(datetime(2099, 1, 1) - recorded_at).total_seconds()` formatted with leading zeros), so descending sort within tier puts the older message first, or (b) change `items_for_queue` to do a two-key sort (descending on urgency rank, ascending on `recorded_at`), or (c) split the priority key into separate fields and document the production approach as a DynamoDB GSI with two sort attributes. Option (a) keeps the single-string key shape but corrects the within-tier order; option (b) is the simplest demo fix; option (c) most accurately describes a production approach. Whichever fix is chosen, the in-code comment should match what the code actually does.

---

### Finding 5: `MockBedrock.invoke_model` Uses `model_id` (Snake_case) While the Real `bedrock_runtime.invoke_model` Uses `modelId` (camelCase) per Boto3; the Demo's Parameter Convention Doesn't Match the Production API

- **Severity:** NOTE
- **File:** `chapter10.02-python-example.md`
- **Location:** `MockBedrock.invoke_model` (the `def invoke_model(self, model_id, body)` signature); `classify_voicemail` Step 4B (the `bedrock_mock.invoke_model(model_id=BEDROCK_CLASSIFIER_MODEL_ID, body=classifier_prompt)` call); `MockTranscribeMedical` (similarly uses snake_case `language_code`, `transcription_type`, `output_bucket`, `output_key`)
- **Description:**

  Boto3's `bedrock_runtime.invoke_model` takes `modelId` (camelCase per the AWS API) along with `body`, `contentType`, and `accept`. The demo's mock uses `model_id` (snake_case). The production-comment skeletons elsewhere in the file follow the AWS-API camelCase convention (`MedicalTranscriptionJobName`, `LanguageCode`, `Specialty`, `Type`, `OutputBucketName`, `OutputKey`, `OutputEncryptionKMSKeyId`, `Settings`, `ServerSideEncryption`, `SSEKMSKeyId`, `ContentType`, `Metadata`), so the demo is internally inconsistent: the production-comment skeletons use the real API's casing, but the mock-call sites use Python-snake_case.

  Same pattern applies to `MockTranscribeMedical.start_medical_transcription_job(self, job_name, voicemail_id, media_uri, language_code, specialty, transcription_type, output_bucket, output_key)` versus the real `transcribe_client.start_medical_transcription_job(MedicalTranscriptionJobName=..., Media={...}, LanguageCode=..., Specialty=..., Type=..., OutputBucketName=..., OutputKey=..., OutputEncryptionKMSKeyId=...)`. The mock uses snake_case; the production-comment uses camelCase.

  A learner translating the demo to a production Lambda by deleting the mocks and uncommenting the production-comment skeletons will get a mismatch between the mock-call-site keyword arguments and the real API's keyword arguments. The fix is mechanical (search-and-replace) but worth flagging because it's the kind of small inconsistency that produces an "easy-to-miss" boto3 `ParamValidationError` at first run against the real service.

- **Recommended fix:** Either (a) restructure each mock to accept the same keyword arguments the real boto3 client accepts (e.g., `MockBedrock.invoke_model(self, modelId, body, contentType=None, accept=None)`), so the call sites match production exactly, or (b) keep the snake_case mock signatures but add a comment at each call site noting the keyword-argument translation for production. Option (a) is more rigorous; option (b) preserves the Python-idiomatic look of the demo at the cost of carrying a translation layer.

---

### Finding 6: The LLM Classifier and Comprehend Medical Entity Extractor Are Described as Running in Parallel in the Pseudocode and the Companion's Prose Overview, but the Python Runs Them Sequentially Without a Comment Marking the Simplification

- **Severity:** NOTE
- **File:** `chapter10.02-python-example.md`
- **Location:** `classify_voicemail` (the sequential `classifier_response = bedrock_mock.invoke_model(...)` followed by `entity_response = comprehend_mock.detect_entities_v2(...)`); the companion's prose overview ("classify with the urgency-rule-layer-first pattern and run the LLM classifier and entity extractor in parallel (Step 4)"); the main recipe's pseudocode (Step 4B's `classifier_call = bedrock.invoke_model_async(...)` and `entity_call = comprehend_medical.detect_entities_v2_async(...)` followed by `await(classifier_call)` and `await(entity_call)`)
- **Description:**

  The pseudocode in the main recipe is explicit about parallel execution:

  ```
  // Step 4B: run the LLM classifier and the entity
  // extractor in parallel. Both calls are async and
  // independent.
  classifier_call = bedrock.invoke_model_async(...)
  entity_call = comprehend_medical.detect_entities_v2_async(...)
  classifier_result = await(classifier_call)
  entity_result = await(entity_call)
  ```

  And the Python companion's prose overview at the top of the file says the pipeline runs them in parallel ("run the LLM classifier and entity extractor in parallel").

  But the Python code runs them sequentially:

  ```python
  # Step 4B: LLM-based classifier...
  classifier_response = bedrock_mock.invoke_model(
      model_id=BEDROCK_CLASSIFIER_MODEL_ID,
      body=classifier_prompt)
  ...
  # Step 4E: medical entity extraction.
  entity_response = comprehend_mock.detect_entities_v2(
      text=transcript_text)
  ```

  No comment marks the simplification. A learner who reads "in parallel" in the prose, sees the sequential calls in the code, and wonders if they're missing something will have to figure out for themselves that the demo collapses the parallel calls for readability.

  In a real Lambda, the parallel pattern is commonly implemented with `concurrent.futures.ThreadPoolExecutor` or with `asyncio` plus `aioboto3`; in a Step Functions deployment, the parallel pattern is two parallel branches in the state machine. None of those are in the demo (correctly so for a teaching artifact), but the gap should be marked.

- **Recommended fix:** Add a brief inline comment between the rule layer step and the classifier call along the lines of "In production, the LLM classifier call and the Comprehend Medical detect_entities_v2 call run in parallel (via a ThreadPoolExecutor or via two parallel branches in the Step Functions state machine). The demo runs them sequentially for readability; the latency cost in the demo is irrelevant because the mocks return synchronously." Optionally, also rephrase the prose overview at the top of the file to say "classify with the urgency-rule-layer-first pattern, the LLM classifier, and the entity extractor (the latter two run in parallel in production)."

---

### Finding 7: `transcribe_mock`, `bedrock_mock`, and `comprehend_mock` Are Module-Level Globals Initialized Only Inside `run_demo`; Importing the Module and Calling `process_voicemail` Without First Running the Demo Will Fail With `AttributeError: 'NoneType' Object Has No Attribute ...`

- **Severity:** NOTE
- **File:** `chapter10.02-python-example.md`
- **Location:** Module-level declarations (`transcribe_mock = None`, `bedrock_mock = None`, `comprehend_mock = None`); `run_demo` (the `global transcribe_mock, bedrock_mock, comprehend_mock` block); pipeline-stage references (`transcribe_mock.start_medical_transcription_job(...)` in `start_asr_job`, `bedrock_mock.invoke_model(...)` in `classify_voicemail`, `comprehend_mock.detect_entities_v2(...)` in `classify_voicemail`)
- **Description:**

  The mocks for the AWS services are declared at module level with `None` placeholders:

  ```python
  # transcribe, bedrock, and comprehend_medical mocks are wired
  # up in run_demo() with fixture data tailored to each scenario.
  transcribe_mock      = None
  bedrock_mock         = None
  comprehend_mock      = None
  ```

  And initialized inside `run_demo`:

  ```python
  def run_demo():
      ...
      global transcribe_mock, bedrock_mock, comprehend_mock
      ...
      transcribe_mock  = MockTranscribeMedical(transcript_fixtures)
      bedrock_mock     = MockBedrock(classification_fixtures)
      comprehend_mock  = MockComprehendMedical(entity_fixtures)
      ...
  ```

  The pipeline functions (`start_asr_job`, `classify_voicemail`) call `transcribe_mock.start_medical_transcription_job(...)`, `bedrock_mock.invoke_model(...)`, and `comprehend_mock.detect_entities_v2(...)` directly, expecting these globals to be live.

  A learner who imports this module and tries to write their own driver (for example, `from chapter10_02 import process_voicemail; process_voicemail(my_event)`) will hit `AttributeError: 'NoneType' object has no attribute 'start_medical_transcription_job'`. The other mocks (`s3`, `voicemail_records`, `triage_queue`, `ehr`, `sns`, `event_bus`, `cloudwatch`) are initialized at module level and work fine.

  This is a NOTE rather than a higher severity because the file is structured as a self-contained `__main__` demo, and the typical learner runs `python chapter10_02_python_example.py` rather than importing it. But the inconsistency between "always-initialized mocks" and "deferred-initialized mocks" is awkward.

- **Recommended fix:** Either (a) initialize the deferred mocks at module level with empty fixture dicts, then have `run_demo` reassign them with populated fixtures (so a bare import has a usable but empty mock), or (b) refactor the pipeline-stage functions to receive the mock instances as arguments rather than reading them from module-level globals (this is more invasive but produces a cleaner demo). Option (a) is the smallest patch.

---

## Reviewer Notes (Out-of-Scope, Not Counted Toward the Verdict)

The following items came up during the review and are explicitly listed in the "What NOT to review" section of the persona instructions. They are recorded here for the TechExpertReviewer pass, not as code-review findings:

- **Per-Lambda IAM role definitions.** The Setup section enumerates the permissions per logical Lambda but the demo uses a single set of mocked credentials. The companion's "Gap Between This and Production" section calls this out comprehensively.
- **Real Step Functions state machine plus per-stage Lambda packaging.** The companion runs the seven stages inline; production lives in a Step Functions state machine with one Lambda per stage. Acknowledged in the gap section.
- **Real Transcribe Medical async-job-completion via EventBridge plus the Step Functions wait-for-callback pattern.** The companion's `handle_asr_completion` is invoked inline; production wires the EventBridge job-completion event into a Step Functions task token. Acknowledged in the gap section.
- **Per-jurisdiction recording-disclosure language.** Architecturally described in the recipe and acknowledged as out of scope for the Python; appropriate for the production-readiness section.
- **Real urgency-lexicon governance (versioned reviewable artifact in Parameter Store / AppConfig / S3 with versioning, quarterly clinical-operations review).** The lexicon in the demo is a hard-coded Python list, which the companion calls out explicitly ("Do not ship the demo lexicon to production"). Appropriate for the production-readiness section.
- **Per-axis confidence-threshold calibration against representative production traffic.** Acknowledged in the gap section.
- **Subgroup-stratified accuracy monitoring.** The CloudWatch metric emission has the dimension hooks (`intent`, `urgency`, `final_urgency`) but the cohort-stratification dimensions (preferred language, age cohort, geographic region, accent group) are not exercised in the demo. The recipe's prose calls this out.
- **Sampled human review with stratified sampling and disagreement capture.** The demo has a single staff-action capture path; production has a sampled-review service that selects a stratified random sample. Acknowledged in the gap section.
- **Real fuzzy medication matching against RxNorm with brand-vs-generic equivalence and ASR mis-recognition handling.** The demo's `medication_alignment` cross-reference uses naive substring matching, which is acknowledged in the gap section.
- **VPC and VPC endpoint configuration.** Architecturally described; not in the demo.
- **Connect Voice ID enrollment, BIPA-compliant biometric consent capture, voiceprint-based fraud detection.** Architecturally described as a variation; not in the demo.
- **Multi-language scaffolding (Spanish-language Transcribe Medical jobs, Spanish-language classifier prompts, Spanish-language urgency lexicons that are not literal translations).** Architecturally described as a variation; not in the demo.
- **Idempotency at every stage via conditional writes (`attribute_not_exists`) and (`voicemail_id`, `stage_name`) tuples as deduplication keys.** Acknowledged in the gap section; the demo's writes are not idempotent. The pseudocode's comment about idempotency is preserved in the prose.
- **DLQ configuration on every Lambda and DLQ-depth alarms (especially the emergent-voicemail Lambda's DLQ paged immediately).** Acknowledged in the gap section.
- **On-call rotation integration (PagerDuty / Opsgenie / EHR-vendor on-call).** Acknowledged in the gap section.
- **Staff triage UI design (audio playback synchronized to transcript timing, entities highlighted in transcript, reclassification capture).** Acknowledged in the gap section as a substantial UI effort.
- **Disaster recovery and pipeline-unavailable handling (fall back to raw-audio-to-staff-queue with a "automated triage unavailable" flag).** Acknowledged in the gap section.
- **Audit retention sized to the longest of HIPAA's six-year minimum, state medical-records-retention, and the institutional regulatory floor.** Acknowledged in the gap section.
- **Cost-attribution analytics per intent and per urgency.** Acknowledged in the gap section.
- **Tests (unit tests for the urgency rule layer with edge cases, the confidence-gate logic, the priority-key construction; integration tests against test buckets and tables; end-to-end tests for the emergent-notification path).** Acknowledged in the gap section.
- **Observability beyond metrics (X-Ray traces, CloudWatch Logs Insights queries that join Step Functions, Lambda, and audit records by voicemail_id).** Acknowledged in the gap section.
