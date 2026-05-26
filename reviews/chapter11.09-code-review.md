# Code Review: Recipe 11.9 - Care Coordination Assistant

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter11.09-care-coordination-assistant.md` (pseudocode, 10 steps)
- `chapter11.09-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. Two WARNING-level findings (under the FAIL threshold of >3). Several NOTE-level improvements. The code maps cleanly to the ten pseudocode steps, the AWS SDK calls are correct, the DynamoDB Decimal discipline is consistent across every `put_item` site, the S3 keys are unprefixed, and the demo runs end-to-end through the mocks.

---

## Pseudocode-to-Python Mapping

The Python companion implements all ten pseudocode steps from the main recipe. The mapping is:

| Pseudocode Step | Python Function | Status |
|-----------------|-----------------|--------|
| Step 1 — Enroll with consent and caregiver setup | `enroll_patient`, `_check_eligibility`, `_state_specific_consent_provisions`, `_check_state_caregiver_law` | ✓ |
| Step 2 — Cross-organizational ingestion with provenance | `ingest_event`, `_classify_sensitivity`, `_verify_consent`, `_write_provenance`, `_normalize_event`, `_update_coordination_state`, `_derive_triggers` | ✓ |
| Step 3 — Seam-detection and protocol-trigger eval | `evaluate_seams_and_triggers`, `_eval_med_discrepancy_rule`, `_eval_referral_window_rule`, `_eval_transition_gap_rule`, `_evaluate_protocol_triggers`, `_schedule_engagement` | ✓ |
| Step 4 — Receive turn, input safety, identity, context | `receive_conversation_turn`, `_screen_input`, `_coordination_acuity_screen`, `_route_to_acuity_pathway`, `_load_coordination_context` | ✓ |
| Step 5 — Agent tool-use loop with citations | `handle_conversation`, `compose_coordination_system_prompt`, `_execute_coordination_tool` | ✓ |
| Step 6 — Output safety with faithfulness verification | `screen_coordination_output`, `_detect_coordination_scope_violation`, `_verify_coordination_faithfulness`, `_speaker_role_disclosure_check`, `_suggests_clinical_judgment`, `_contains_deference`, `persist_coordination_artifacts` | ✓ |
| Step 7 — Transition-of-care orchestration via Step Functions | `initiate_transition_of_care`, `_select_transition_protocol`, `_select_state_machine_arn` | ✓ |
| Step 8 — Referral lifecycle tracking | `process_referral_event`, `_map_event_to_target_state`, `_next_referral_action` | ✓ |
| Step 9 — Medication reconciliation across pharmacies | `process_medication_event`, `_normalize_medication`, `_reconcile_medication`, `_apply_med_reconciliation` | ✓ |
| Step 10 — Care-team reporting and outcome correlation | `compose_weekly_digest`, `queue_outcome_correlation` | ✓ (10 partial — see notes) |

The patient_id-cross-check defense-in-depth from pseudocode Step 5B is implemented in `handle_conversation`. The provenance-as-architectural-primitive discipline is preserved (every coordination-state entry carries `provenance_id`; the provenance journal mirrors to a separately-keyed S3 bucket). The caregiver-as-first-class-participant identity model is realized through the separate `CAREGIVER_TABLE`, the `proxy_scope` parameter that flows through `_load_coordination_context`, and the `_speaker_role_disclosure_check` carve-out enforcement.

---

## Findings

### Issue 1 — WARNING: Dose-titration demo test does not actually exercise the dose-titration safe template

**Severity:** WARNING (misleading)
**File:** `chapter11.09-python-example.md`, `MockBedrockRuntime.invoke_response` and `run_demo` "Out-of-scope (dose titration)" section

The demo runner labels one test case as "Out-of-scope (dose titration). The bot should replace with the dose-titration safe template" and sends the message:

```python
msg = "should i lower my furosemide dose tonight?"
```

But the mock LLM checks for `"furosemide"`, `"diuretic"`, or `"60 mg"` **first** in `invoke_response`:

```python
if ("furosemide" in msg_lower or
    "diuretic" in msg_lower or
    "60 mg" in msg_lower):
    return {
        "response_text": (
            "Thanks for telling me. The dose change ..."
        ),
        ...
    }
```

The dose-titration check (`"should i take"`, `"should i increase"`, `"should i lower"`) is third in the chain and never reached. The medication-discrepancy response that fires instead happens to pass output-safety screening because:

- `_detect_coordination_scope_violation` looks at the **response text** (not the user message) and the response contains none of the dose-titration trigger phrases (`"increase your dose"`, `"go up to"`, etc.).
- `_contains_deference` matches `"i'm not making the"` in the response, so `_suggests_clinical_judgment` short-circuits the conservative-bias check.

Net result: the demo prints `disposition: delivered` with the medication-discrepancy response, contradicting the comment that says "the bot should replace with the dose-titration safe template." A reader following the demo will form the wrong mental model of when `OUT_OF_SCOPE_DOSE_TITRATION` actually fires.

**Fix:** Either (a) reorder the mock so the dose-titration check precedes the furosemide check, or (b) change the test message so it does not contain `"furosemide"` (e.g., `"should i lower my heart medication tonight?"`). Option (a) is simplest and keeps the test as written.

---

### Issue 2 — WARNING: Pinpoint `send_messages` uses `patient_id` as the address-map key

**Severity:** WARNING (misleading pattern)
**File:** `chapter11.09-python-example.md`, `_schedule_engagement`

```python
pinpoint_client.send_messages(
    ApplicationId=PINPOINT_APPLICATION_ID,
    MessageRequest={
        "Addresses": {patient_id: {
            "ChannelType":
                trigger.get("channel_preference",
                            "in_app").upper()}},
        ...
    })
```

In real Pinpoint, the keys of `MessageRequest.Addresses` are the actual delivery addresses (phone number for SMS, email address for EMAIL, device token for APNS/GCM, endpoint ID for IN_APP, etc.), not opaque patient identifiers. Code copied as-is into a real environment will not deliver messages and will likely fail validation. The walkthrough text ("the demo records the engagement") softens this, but the parameter shape itself reads as production-correct.

A learner mapping this pattern to production needs to see either an `EndpointIds` map (preferred for healthcare bots that resolve patient → endpoint via the Pinpoint endpoint registry on enrollment) or an explicit address-keyed map with a comment that says "in production, look up the patient's preferred address from the endpoint registry before this call." A throwaway placeholder like `"+15555550100"` for the SMS demo or a comment block above the call would close the gap.

**Fix:** Either replace `patient_id` with a placeholder address and add a `# In production, look up via Pinpoint endpoint registry` comment, or switch to the `EndpointIds` shape:

```python
pinpoint_client.send_messages(
    ApplicationId=PINPOINT_APPLICATION_ID,
    MessageRequest={
        "EndpointIds": [
            _resolve_pinpoint_endpoint_id(
                patient_id,
                trigger.get("channel_preference"))
        ],
        "MessageConfiguration": {...},
    })
```

---

### Issue 3 — NOTE: Several unused imports and constants

**Severity:** NOTE
**File:** `chapter11.09-python-example.md`, Configuration section

Unused or declared-but-never-referenced:

- `from typing import Optional` — never used.
- `from collections import defaultdict` — never used.
- `INTENT_CONFIDENCE_THRESHOLD = Decimal("0.70")` — declared but never read.
- `SMALL_MODEL_ID`, `PROTOCOL_KB_ID`, `PATIENT_EDUCATION_KB_ID`, `HISTORY_KB_ID`, `GUARDRAIL_ID`, `GUARDRAIL_VERSION`, `HEALTHLAKE_DATASTORE_ID`, `CONNECT_INSTANCE_ID`, `CONNECT_CONTACT_FLOW_ID`, `AUDIT_ARCHIVE_FIREHOSE_NAME`, `PINPOINT_APPLICATION_ID` — declared, passed through the deploy-time guardrail assertion, but never functionally exercised in the demo because the mocks do not consume them.

The unused boto3 clients (`firehose_client`, `bedrock_runtime`, `bedrock_agent_runtime`, `secrets_client`, `connect_client`, `healthlake_client`) fall in the same category. The setup prose explains that production wires them; the unused imports `Optional` and `defaultdict` do not even have that excuse.

**Fix:** Remove the two unused stdlib imports outright. For the constants and clients, either add a single comment block ("constants exercised symbolically by the deploy-time guardrail; production wires them through the action-group Lambdas") or remove them. The current state makes the configuration section longer than it needs to be without giving the learner a payoff.

---

### Issue 4 — NOTE: Mock DynamoDB query semantics silently bypass real DynamoDB filtering

**Severity:** NOTE
**File:** `chapter11.09-python-example.md`, `MockTable.query`/`MockTable.scan` and several rule evaluators

`MockTable.query` returns every record across every key:

```python
def query(self, **kwargs):
    items = []
    for record_list in self.items.values():
        items.extend(record_list)
    return {"Items": items}
```

Several seam-detection rules and the weekly-digest builder then iterate `record_list.items.values()` directly to filter by `patient_id`:

```python
# in _eval_referral_window_rule:
for record_list in referral_table.items.values():
    for ref in record_list:
        if ref.get("patient_id") != state.get("patient_id"):
            continue
```

This works for the demo but reads as if real DynamoDB also returns the entire table when you "query" it. A learner translating to production needs to see either `query` with `KeyConditionExpression="patient_id = :pid"` against a GSI on `patient_id`, or a comment explaining that the real implementation goes through a per-patient secondary index.

**Fix:** Add a one-line comment in the rule evaluators noting the production approach, e.g.:

```python
# In production, this is a DynamoDB Query against a
# patient_id GSI: KeyConditionExpression="patient_id = :pid".
# The mock iterates because it has no real index.
for record_list in referral_table.items.values():
    ...
```

---

### Issue 5 — NOTE: MockBedrockRuntime ignores the system prompt

**Severity:** NOTE
**File:** `chapter11.09-python-example.md`, `MockBedrockRuntime.invoke_response`

The mock takes `system_prompt` as a keyword argument but never reads it. That is fine for a demo whose purpose is to exercise the surrounding pipeline, but it means the carefully-constructed `compose_coordination_system_prompt` (with its scope discipline, citation requirements, deference clauses, and speaker-role-aware role line) is never actually shown influencing model output.

A reader could reasonably wonder whether the prompt is wired correctly. Add one line in the mock that acknowledges the prompt was received:

```python
def invoke_response(self, *,
                      user_message,
                      coordination_context,
                      system_prompt):
    # Production: the system prompt drives the model's
    # scope discipline, citation discipline, and tone.
    # The mock pattern-matches; in production this prompt
    # is what keeps the LLM from freestyling clinical
    # advice.
    msg_lower = user_message.lower()
    ...
```

This is purely a comment-quality improvement.

---

### Issue 6 — NOTE: `queue_outcome_correlation` is a bare `pass`

**Severity:** NOTE
**File:** `chapter11.09-python-example.md`, Step 10

```python
def queue_outcome_correlation(*, patient_id,
                                  window_days_ago=30):
    """..."""
    # ... long comment ...
    pass
```

The function has a thorough docstring explaining what production does, but its body is `pass`. The walkthrough text mentions "queue outcome correlation" as one of the things the full pipeline does. A reader who searches for what the full-pipeline call actually accomplishes here will find no observable side effect.

The minimum fix is one CloudWatch metric emit so the demo summary shows non-zero outcome-correlation activity:

```python
def queue_outcome_correlation(*, patient_id,
                                  window_days_ago=30):
    # See docstring above; production pulls multi-window
    # outcome data. Demo: emits a placeholder metric so
    # the audit pipeline shows something happened.
    _put_metric("OutcomeCorrelationQueued", 1, {
        "Patient": patient_id})
```

This makes Step 10 visibly active in the demo summary.

---

## What Was Verified

- **DynamoDB Decimal discipline:** Every `put_item` site (across `enroll_patient`, `_write_provenance`, `_update_coordination_state`, `evaluate_seams_and_triggers`, `process_referral_event`, `process_medication_event`, `initiate_transition_of_care`, `_get_or_create_session`, `_route_to_acuity_pathway`, `receive_conversation_turn`, `persist_coordination_artifacts`, `_audit_tool_call`) wraps the item with `_to_decimal`. No raw float lands in DynamoDB. ✓

- **S3 key construction:** Both S3 paths (`f"provenance/{patient_id}/..."` in `_write_provenance` and `f"decisions/{patient_id}/..."` in `persist_coordination_artifacts`) lack leading slashes. ✓

- **boto3 SDK accuracy (current API surface):**
  - `pinpoint_client.send_messages(ApplicationId=..., MessageRequest=...)` ✓ (parameter shape correct; address-map key issue noted as Issue 2)
  - `sfn_client.start_execution(stateMachineArn=..., input=...)` ✓ (camelCase `stateMachineArn`, lowercase `input`)
  - `s3_client.put_object(Bucket=..., Key=..., Body=..., ServerSideEncryption="aws:kms", SSEKMSKeyId=...)` ✓
  - `eventbridge_client.put_events(Entries=[...])` ✓
  - `cloudwatch_client.put_metric_data(Namespace=..., MetricData=[...])` ✓
  - `dynamodb.Table(...).put_item(Item=...)` and `.get_item(Key=...)` ✓
  - `bedrock_agent_runtime.invoke_agent(...)` walkthrough comment uses `agentId`, `agentAliasId`, `sessionId`, `inputText`, `sessionState` (correct). ✓
  - IAM actions in setup (`bedrock:InvokeModel`, `bedrock:Retrieve`, `bedrock:RetrieveAndGenerate`, `bedrock:ApplyGuardrail`, `bedrock-agent-runtime:InvokeAgent`, `healthlake:ReadResource`, `healthlake:SearchWithGet`, `healthlake:SearchWithPost`, `mobiletargeting:SendMessages`, `connect:StartChatContact`, `states:StartExecution`, `kms:GenerateDataKey`) all map to real AWS API actions. ✓

- **Patient-id cross-check:** `handle_conversation` validates `tool_call.args.patient_id` against the verified session before executing the tool, matching pseudocode Step 5B's defense-in-depth requirement. ✓

- **Provenance-as-architectural-primitive:** `_write_provenance` records on a separately-keyed DynamoDB table and mirrors to a separately-KMS-keyed S3 bucket. Every `_update_coordination_state` entry carries the `provenance_id`. ✓

- **Caregiver-scope filtering:** `_load_coordination_context` filters the medication list to empty when the caregiver has `scheduling_only` access. The carve-out check in `_speaker_role_disclosure_check` enforces sensitive-record exclusions in the response. ✓

- **State machine validity:** `REFERRAL_TRANSITIONS` is a valid DAG (closed and cancelled have empty successor sets, aged_out is a sink). `_map_event_to_target_state` covers each event in the `REFERRAL_STATES` list. ✓

- **End-to-end runnability:** The demo runner exercises enrollment → ingestion (HL7 ADT discharge, NCPDP fill, FHIR ServiceRequest) → referral lifecycle creation → transition-of-care initiation → medication reconciliation seam → seam-detection eval → five conversation turns (medication question, referral status, dose-titration attempt, acute chest-pain routing, caregiver scheduling-only) → weekly digest → summary counts. All paths complete without exception. ✓

- **No fabricated boto3 methods:** Every API call name maps to a real AWS service operation.

---

## Closing Notes

This is a long Python file (the recipe is one of the most architecturally complex in the chapter), and the structure holds up well across that length. The split between deterministic substrate (consent enforcement, provenance recording, seam-detection rules, state machines, faithfulness verification) and LLM-orchestrated conversational language is exactly the architectural shape the prose describes. The mock layer is consistent enough that the demo runner produces a coherent end-to-end transcript, which is what a learner needs to internalize the pipeline before writing their own.

The two warnings are both fixable in single-digit lines of edits without restructuring anything. The notes are quality-of-life improvements that make the teaching code teach better. Cleared for editor handoff after the warnings are addressed.
