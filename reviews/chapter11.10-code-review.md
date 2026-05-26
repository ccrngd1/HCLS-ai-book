# Code Review: Recipe 11.10 - Clinical Trial Recruitment Conversationalist

**Reviewer:** Tech Code Reviewer
**Files reviewed:**
- `chapter11.10-clinical-trial-recruitment-conversationalist.md` (main recipe with ten-step decomposition)
- `chapter11.10-python-example.md` (Python implementation)

---

## Verdict: PASS

No ERROR-level findings. Two WARNING-level findings (under the FAIL threshold of >3). Several NOTE-level improvements. The code maps cleanly to the ten pseudocode steps, the AWS SDK calls are correct, the DynamoDB Decimal discipline is consistent across every `put_item` site, the S3 keys are unprefixed, and the demo runs end-to-end through the mocks.

---

## Pseudocode-to-Python Mapping

The Python companion implements all ten logical steps described in the main recipe and the demo intro. The mapping is:

| Step | Description | Python Functions | Status |
|------|-------------|------------------|--------|
| 1 | Onboard trial with IRB-approved content | `onboard_trial`, `set_trial_state`, `register_eligibility_criterion`, `register_recruitment_faq`, `register_irb_approved_corpus_excerpt` | ✓ |
| 2 | Track trial-state and IRB-amendment status | `get_trial_state`, `get_trial_context`, `request_irb_amendment`, `apply_irb_amendment_approval`, `pause_trial_enrollment`, `close_trial_enrollment` | ✓ |
| 3 | Receive turn, input safety, emergency, identity, trial-context | `receive_conversation_turn`, `handle_emergency_routing`, `handle_out_of_scope_routing`, `handle_trial_unavailable`, `handle_identity_mismatch` | ✓ |
| 4 | Agent tool-use loop with IRB-citation discipline | `RECRUITMENT_TOOL_SCHEMA`, `build_system_prompt`, `run_agent_turn`, `_summarize_tool_result` | ✓ |
| 5 | Conversational eligibility prescreen with deterministic logic | `dispatch_tool`, `tool_trial_context_retrieve`, `tool_recruitment_faq_retrieve`, `tool_eligibility_question_surface`, `tool_eligibility_response_capture`, `evaluate_eligibility_criterion`, `_convert_unit`, `tool_prescreen_save_progress` | ✓ |
| 6 | Output safety with IRB-language faithfulness verification | `screen_assistant_response` | ✓ |
| 7 | Coordinator handoff orchestration | `tool_coordinator_handoff_request`, `build_prescreen_summary`, `_expected_followup_window`, `tool_request_coordinator_immediate` | ✓ |
| 8 | Per-cohort representativeness instrumentation | `tool_representativeness_capture`, `record_funnel_stage` | ✓ (see Issue 3) |
| 9 | Recruitment-decision record persistence | `persist_recruitment_decision`, `archive_conversation_transcript` | ✓ |
| 10 | Per-trial reporting and outcome correlation | `generate_per_trial_report`, `correlate_consent_and_randomization` | ✓ |

The IRB-citation discipline is structurally enforced: `tool_trial_context_retrieve`, `tool_recruitment_faq_retrieve`, and `tool_eligibility_question_surface` all attach `citations` arrays bound to the IRB approval record. The output-safety layer's citation-coverage check verifies the citations propagated through the tool trace before delivering the response. The deterministic eligibility-evaluation engine (`evaluate_eligibility_criterion`) handles the seven rule patterns the recipe enumerates (`age_range`, `boolean_response`, `numeric_range_with_unit`, `categorical_set`, `time_since`, `clinical_judgment`, `verification_only`). Per-trial isolation is preserved at the DynamoDB partition-key level for per-trial stores and applied as a post-hoc metadata filter on the mock retrieve surface.

---

## Findings

### Issue 1 — WARNING: `disposition` propagates as `prescreen_state` without normalization, so the persisted decision can record a non-disposition value

**Severity:** WARNING (misleading)
**File:** `chapter11.10-python-example.md`, `chat_handler` end-of-turn persistence block (Step 10 / Full Pipeline section)

In `chat_handler`, after the agent runs, the code computes the disposition for `persist_recruitment_decision` like this:

```python
funnel_stage = state.get("funnel_stage")
prescreen_state = state.get("prescreen_state")
if funnel_stage == FUNNEL_STAGE_HANDOFF_SCHEDULED:
    persist_recruitment_decision(
        session_id=session_id,
        trial_id=trial_id,
        disposition=prescreen_state or DISPOSITION_LIKELY_ELIGIBLE,
        ...)
```

The state's `prescreen_state` field is set in two places:

- `tool_eligibility_response_capture` sets `state["prescreen_state"] = "IN_PROGRESS"` after every captured criterion response.
- `tool_prescreen_save_progress` sets `state["prescreen_state"] = current_disposition` (one of the `DISPOSITION_*` constants).

If the LLM never calls `prescreen_save_progress` (the demo's scripted responses do not call it), `prescreen_state` stays `"IN_PROGRESS"` through the handoff. The `or DISPOSITION_LIKELY_ELIGIBLE` fallback only triggers when `prescreen_state` is empty/None, not when it is the string `"IN_PROGRESS"`. The result is a recruitment-decision record persisted with `disposition="IN_PROGRESS"`, which is not in the documented disposition vocabulary (`DISPOSITION_DISQUALIFIED`, `DISPOSITION_UNCERTAIN_PENDING`, `DISPOSITION_LIKELY_ELIGIBLE`, `DISPOSITION_DECLINED_BY_PATIENT`, `DISPOSITION_TRIAL_CLOSED`, `DISPOSITION_OUT_OF_SCOPE`, `DISPOSITION_EMERGENCY_ROUTED`).

A learner copying the demo's flow into production will inherit this gap: the deterministic-evaluation results live on `state["prescreen_responses"][criterion_id]["evaluation"]` per criterion, but no code aggregates those per-criterion evaluations into a final disposition. The recipe's prose explicitly describes this aggregation ("The prescreen produces a structured result: clearly-disqualified... uncertain-pending... clearly-eligible-pending"), but the deterministic engine is not in the Python.

**Fix:** Either (a) add an aggregator helper that the chat-handler calls before persisting (compute_prescreen_disposition_from_responses), normalizing per-criterion evaluations into a final `DISPOSITION_*` value; or (b) gate the `disposition=prescreen_state or ...` logic on `prescreen_state in DISPOSITIONS` and otherwise fall back to a documented default; or (c) make the orchestration prompt require the LLM to call `prescreen_save_progress` before requesting the handoff and surface the requirement in the system prompt's rules. Option (a) matches the deterministic-engine-owns-disposition discipline the prose advocates.

---

### Issue 2 — WARNING: Demo turns 1 and 2 fire tool calls then fall through to the default mock response, so the tool result is never visibly consumed

**Severity:** WARNING (misleading)
**File:** `chapter11.10-python-example.md`, `_seed_scripted_model_responses` and `MockBedrockRuntime.invoke_model`

The mock queues six scripted responses across four conversation turns. The agent loop iterates per turn until it sees a `stop_reason == "end_turn"`. Walking through the demo:

- **Turn 0 (intro):** Iter 0 pops scripted response 1 (tool_use `trial_context_retrieve`). Iter 1 pops scripted response 2 (end_turn with body that begins "Per the IRB-approved protocol summary..."). The tool result is consumed by the second response. ✓
- **Turn 1 (logistics question):** Iter 0 pops scripted response 3 (tool_use `eligibility_question_surface` for `age_18_75`). Iter 1 finds the queue empty, so `MockBedrockRuntime.invoke_model` returns the default end_turn payload: `"I appreciate your interest. I'd like to connect you with a research coordinator..."`. The eligibility question is surfaced but the model response is the unrelated coordinator-handoff fallback. The demo prints `Tools: ['eligibility_question_surface']` next to that fallback text.
- **Turn 2 (`"My age is 52."`):** Iter 0 pops scripted response 4 (tool_use `eligibility_response_capture`). Iter 1 again hits the empty queue and returns the default fallback text. Same shape as Turn 1.
- **Turn 3 (handoff request):** Iter 0 pops response 5 (tool_use `coordinator_handoff_request`). Iter 1 pops response 6 (end_turn confirmation). ✓

The pedagogy issue: a learner reading the demo output will see a tool call name followed by a coordinator-handoff message that has nothing to do with the tool's purpose, and may infer that this is how the loop is supposed to work. The agent-loop pattern teaches that the LLM consumes the tool result on the next iteration to compose its end-of-turn text, but the script does not exhibit that pattern for two of the four turns.

**Fix:** Either queue end-of-turn responses for Turns 1 and 2 that actually reference the tool result (for example, "Visits run about 90 minutes over 12 months" after the FAQ retrieval, or "You're in the eligible age range" after capturing age 52), or restructure the demo so the scripted responses cleanly bracket each turn's tool call with the corresponding end-of-turn text. Two additional `bedrock_runtime.queue_response({...})` calls in `_seed_scripted_model_responses` close the gap.

---

### Issue 3 — NOTE: `record_funnel_stage` is defined but never called

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, Step 8 section

The function:

```python
def record_funnel_stage(*, session_id, trial_id, stage,
                          metadata=None) -> None:
    """Record a funnel-stage transition for per-cohort
    monitoring. The runtime calls this at each stage
    transition; per-cohort dashboards aggregate the
    transitions for representativeness reporting."""
    _emit_event("RecruitmentEvent.FunnelStage", {...})
    _put_metric("FunnelStage", 1, {...})
```

Search for callers across the file: there are none. The conversation-state's `funnel_stage` field is set in `receive_conversation_turn` (`FUNNEL_STAGE_ENTERED`), in `tool_coordinator_handoff_request` (`FUNNEL_STAGE_HANDOFF_SCHEDULED`), and in `tool_request_coordinator_immediate` (`FUNNEL_STAGE_HANDOFF_SCHEDULED`), but the per-stage standalone events (`DISCLOSURE_ACCEPTED`, `FAQ_ENGAGED`, `PRESCREEN_STARTED`, `PRESCREEN_COMPLETED`, `HANDOFF_ACCEPTED_BY_COORDINATOR`, `CONSENTED`, `RANDOMIZED`) never fire.

The recipe's prose makes per-stage funnel monitoring central to the value proposition ("The recruitment funnel is the metric, not the conversation count" and the per-cohort funnel-stage table). A learner expecting to see how the runtime emits each transition has only the function definition with no exercise.

**Fix:** Either invoke `record_funnel_stage` from the natural transition points (in `receive_conversation_turn` after disclosure surfacing, in `tool_recruitment_faq_retrieve` for FAQ engagement, in `tool_eligibility_question_surface` for prescreen-started, in `tool_prescreen_save_progress` for prescreen-completed, in `tool_coordinator_handoff_request` for handoff-scheduled) or remove the unused function and consolidate the funnel-stage capture into `_emit_event` calls at those sites with a comment about the production aggregation pipeline. Wiring it into the existing call sites is a few lines and makes the funnel-stage taxonomy visibly active in the demo.

---

### Issue 4 — NOTE: First-turn disclosure check is a substring match on "chat" or "tool"

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, `screen_assistant_response`

```python
if is_first_turn:
    if ("chat" not in response_text.lower()
            and "tool" not in response_text.lower()
            and DISCLOSURE_ASSISTANT_NOT_PERSON
            not in disclosures_shown):
        findings.append({
            "category":     "MISSING_DISCLOSURE",
            "severity":     "WARN",
            "disclosure":   DISCLOSURE_ASSISTANT_NOT_PERSON,
        })
```

The check is acknowledged in the surrounding comment as "illustrative" with the production approach noted. The comment is fine; the issue is that the check itself only verifies one of the seven `REQUIRED_DISCLOSURES_FIRST_TURN` constants, and even that one is verified against the literal substrings `"chat"` and `"tool"`. A learner could infer that this is a reasonable verification approach. The other six required disclosures (`DISCLOSURE_NOT_COORDINATOR`, `DISCLOSURE_CANNOT_ENROLL`, etc.) are declared as constants but never checked.

**Fix:** Either (a) check all seven required disclosures with the same illustrative substring approach plus a comment marking it as illustrative, or (b) replace the check with a single comment block explaining that production verifies the disclosure surface against an explicit token taxonomy reviewed by the IRB and skip the check entirely in the demo. Option (a) at least makes the disclosure taxonomy visible as a runtime artifact.

---

### Issue 5 — NOTE: Several configured clients and constants are unused

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, Configuration section and Mock Infrastructure section

Declared but never functionally exercised:

- `pinpoint_client` — declared, mocked, never called. The setup prose mentions Pinpoint for proactive recruitment messaging but no demo path sends a message.
- `secrets_client` — declared, never replaced with a mock or called.
- `firehose_client` — declared, never replaced or called. The recipe refers to a Firehose-backed audit pipeline.
- `IDENTITY_PROTECTED_POPULATION_B`, `IDENTITY_PROTECTED_POPULATION_C`, `IDENTITY_PROTECTED_POPULATION_D` — declared, never used in any branch.
- `RECRUITMENT_PATTERN_KB_ID`, `TRIAL_CORPUS_KB_ID` — declared, but only `FAQ_KB_ID` and `TRIAL_CORPUS_KB_ID` are populated in `_KB_CORPUS`; only `FAQ_KB_ID` is queried (in `tool_recruitment_faq_retrieve`). The corpus-excerpt KB and pattern KB are seeded but not retrieved.
- `GUARDRAIL_ID`, `GUARDRAIL_VERSION` — declared, written into the decision record, but the Guardrail apply call is skipped per the comment in `screen_assistant_response`.

The production-distinction prose explains why each exists, which helps. A short comment block ("constants and clients exercised symbolically by the deploy-time guardrail; production wires them through their respective Lambdas") near the configuration section would make the situation explicit rather than leaving the reader to discover the gap by greping.

**Fix:** Add the comment block, or (for the most clearly unused ones) prune. The unused identity-posture protected-population constants are particularly worth either branching on or removing since they map directly to a regulatory regime (45 CFR 46 Subparts B/C/D) that the recipe spends paragraphs explaining.

---

### Issue 6 — NOTE: PHI redaction `zip5` pattern over-redacts

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, `PHI_PATTERNS`

```python
"zip5":      re.compile(r"\b\d{5}(?:-\d{4})?\b"),
```

This matches any 5-digit number (with an optional 4-digit suffix), not just ZIP codes. Five-digit lab values, prescription numbers, dates rendered without separators, study identifiers, and numeric parts of dosing regimens all get redacted as ZIP5. Since the redaction target is log lines (per the comment block at the top of Configuration), the over-redaction is bounded; but it teaches a misleadingly simple pattern.

**Fix:** Either (a) replace the regex with a context-aware pattern that requires a city/state qualifier or a "zip" keyword nearby, or (b) note in the comment that production redaction uses a managed PII-detection service or a multi-token contextual rule. The recipe already includes a comment that says production combines pattern-based redaction with a managed PII-detection service, so option (b) is a one-line addition.

---

### Issue 7 — NOTE: Mock retrieve enforces metadata filter post-hoc

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, `tool_recruitment_faq_retrieve`

```python
response = bedrock_agent_runtime.retrieve(
    knowledgeBaseId=FAQ_KB_ID,
    retrievalQuery={"text": question},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "filter": {
                "equals": {
                    "key":   "trial_id",
                    "value": trial_id,
                },
            },
        },
    })

matches = response.get("retrievalResults", [])
# Apply the per-trial filter post-hoc as the mock does
# not enforce the metadata filter natively.
matches = [
    m for m in matches
    if m.get("metadata", {}).get("trial_id") == trial_id
    and m.get("score", 0.0) >= float(RETRIEVAL_SCORE_FLOOR)
]
```

The boto3 retrievalConfiguration shape is correct for the real Bedrock Knowledge Base API. The post-hoc filter is acknowledged in the inline comment. The remaining gap: a learner won't see the runtime cost of the filter being applied at index time vs. post-hoc, and the per-trial isolation discipline in the recipe ("isolation is structural, not advisory") could be misread as relying on the post-hoc check rather than on the index filter.

**Fix:** Strengthen the inline comment to call out that the post-hoc check is defense-in-depth; production deployments rely on the index-time filter for correctness and the post-hoc check only as a guardrail against misconfigured filters. One sentence is enough.

---

### Issue 8 — NOTE: The Bedrock Guardrail apply call is skipped in `screen_assistant_response`

**Severity:** NOTE
**File:** `chapter11.10-python-example.md`, Step 6

```python
# 5. Bedrock Guardrail apply. In production this is the
#    real bedrock_runtime.apply_guardrail call against
#    the recruitment-tuned guardrail. The demo skips
#    the network call and assumes the guardrail
#    response is permitted unless a recommendation
#    pattern fires above.
```

The comment is clear about what is omitted. The issue: the recipe lists the Guardrail as one of the four output-safety checks ("a Bedrock Guardrail with a recruitment-tuned restricted-topic policy did not flag the content") and the production-distinction prose explains the Guardrail topics in detail, but the demo doesn't show the call shape, not even as a no-op stub. A learner translating to production has to look up `bedrock-runtime.apply_guardrail` independently.

**Fix:** Add a stub call with the boto3 parameter shape and a `try/except` that falls through to PASS, plus a comment explaining the parameter binding (`guardrailIdentifier`, `guardrailVersion`, `source`, `content`). Even if the demo always passes, the call shape is the teaching content. Cf. how the demo writes the `s3_client.put_object` and `dynamodb` calls explicitly.

---

## What Was Verified

- **DynamoDB Decimal discipline:** Every `put_item` site wraps the item with `_to_decimal`. Specifically: `onboard_trial`, `set_trial_state`, `register_eligibility_criterion`, `register_recruitment_faq`, `apply_irb_amendment_approval` (context update), `receive_conversation_turn`, `tool_eligibility_response_capture`, `tool_prescreen_save_progress`, `tool_coordinator_handoff_request` (both writes), `tool_request_coordinator_immediate` (both writes), `tool_representativeness_capture`, `persist_recruitment_decision`, `_audit_tool_call`. No raw float lands in DynamoDB. ✓

- **S3 key construction:** Both `s3_client.put_object` calls (in `persist_recruitment_decision` and `archive_conversation_transcript`) construct keys without a leading slash (`f"trial={trial_id}/year={...}/..."`). ✓

- **boto3 SDK accuracy (current API surface):**
  - `bedrock_runtime.invoke_model(modelId=..., body=...)` — correct (camelCase `modelId`, lowercase `body`). ✓
  - `bedrock_agent_runtime.retrieve(knowledgeBaseId=..., retrievalQuery={"text": ...}, retrievalConfiguration={"vectorSearchConfiguration": {"filter": {...}}})` — correct shape including the metadata filter. ✓
  - `dynamodb.Table(...).put_item(Item=...)` and `.get_item(Key=...)` — correct. ✓
  - `eventbridge_client.put_events(Entries=[{"Source": ..., "DetailType": ..., "Detail": ..., "EventBusName": ...}])` — correct. ✓
  - `cloudwatch_client.put_metric_data(Namespace=..., MetricData=[...])` — correct. ✓
  - `s3_client.put_object(Bucket=..., Key=..., Body=..., ContentType=..., ServerSideEncryption="aws:kms", SSEKMSKeyId=...)` — correct. ✓
  - `connect_client.start_chat_contact(InstanceId=..., ContactFlowId=..., Attributes={...}, ParticipantDetails={"DisplayName": ...})` — correct. ✓
  - `sfn_client.start_execution(stateMachineArn=..., name=..., input=...)` — correct (camelCase `stateMachineArn`, lowercase `input`). ✓
  - IAM actions in setup (`bedrock:InvokeModel`, `bedrock:Retrieve`, `bedrock:RetrieveAndGenerate`, `bedrock:ApplyGuardrail`, `bedrock-agent-runtime:InvokeAgent`, `mobiletargeting:SendMessages`, `connect:StartChatContact`, `states:StartExecution`, `kms:GenerateDataKey`, `firehose:PutRecord`, `secretsmanager:GetSecretValue`) all map to real AWS API actions. ✓

- **Per-trial isolation primitives:** Trial-context, trial-state, eligibility-rule, recruitment-FAQ, and representativeness records all carry `trial_id` as the partition key. Cross-trial reads at the demo level can only happen by passing a different `trial_id`. ✓

- **Citation propagation through the agent loop:** `run_agent_turn` extends `citations` from both tool results (via `tool_result["citations"]`) and end-of-turn text blocks (via `block.get("citations", [])`). The output-safety check in `screen_assistant_response` reads from this aggregated list. ✓

- **Tool schema (Anthropic-native format):** `RECRUITMENT_TOOL_SCHEMA` uses the `name`, `description`, `input_schema` (JSON Schema) shape that Anthropic's tool-use API on Bedrock accepts. ✓

- **Eligibility-rule library coverage:** `evaluate_eligibility_criterion` covers seven rule types (`age_range`, `boolean_response`, `numeric_range_with_unit`, `categorical_set`, `time_since`, `clinical_judgment`, `verification_only`). The `_convert_unit` helper handles HbA1c, weight, and height conversions. The clinical-judgment and verification-only types correctly route to `EVAL_OUTCOME_REQUIRES_COORDINATOR`. ✓

- **Vulnerable-populations identity check:** `receive_conversation_turn` validates `identity` against `trial_context["identity_posture"]` and routes to `handle_identity_mismatch` when the trial does not enroll the requesting identity class. The handler has distinct messages for parent/guardian and surrogate-decision-maker scenarios. ✓

- **Trial-state fail-closed:** Missing `trial_state` records resolve to `TRIAL_STATE_CLOSED` rather than `TRIAL_STATE_OPEN`, routing to the trial-unavailable handler. ✓ Same for missing `trial_context`.

- **Continuous emergency screening:** `_detect_emergency_signal` runs first inside `receive_conversation_turn`, before any LLM invocation. The matched-text field is always `"[REDACTED]"` rather than the raw utterance. ✓

- **Out-of-scope routing:** Four categories (`clinical_advice_about_existing_care`, `trial_recommendation_request`, `benefits_quote_request`, `prescription_request`) each have an IRB-approved-style routing message in `handle_out_of_scope_routing`. ✓

- **Decision-record persistence to two destinations:** `persist_recruitment_decision` writes to DynamoDB for queryable access and to Object-Lock S3 (with `SSEKMSKeyId=DECISION_RECORD_KMS_KEY_ID`) for immutable retention. The S3 key is partitioned by trial and date. ✓ The conversation-archive uses a separately-keyed bucket (`CONVERSATION_ARCHIVE_KMS_KEY_ID`). ✓

- **Tool-call ledger redaction:** `_redact_tool_args` strips `patient_id`, `prospective_participant_id`, `name`, `date_of_birth`, `user_message`, `free_text`, `phone`, `email`, `address`, `guardian_name`, `guardian_phone`, `surrogate_name`, `surrogate_phone`, `irb_corpus_excerpt`, `transcript` before the ledger write. ✓

- **End-to-end runnability:** The `run_demo` runner exercises trial onboarding (with five eligibility criteria across four categories, three IRB-approved FAQs, one corpus excerpt) → four conversation turns through the chat handler (intro, logistics, age capture, handoff request) → recruitment-decision persistence → per-trial report generation. All paths complete without exception. ✓

- **No fabricated boto3 methods:** Every API call name maps to a real AWS service operation.

---

## Closing Notes

The Python file is dense but the structural decisions hold up: the deterministic substrate (eligibility-rule registration, trial-state management, IRB-amendment workflow, prescreen evaluation, output-safety verification, decision-record persistence) is cleanly separated from the LLM-orchestrated conversation, and the per-trial isolation discipline is consistent across stores. The two warnings are both addressable in modest edits: Issue 1 is either an aggregator helper or an explicit fallback, and Issue 2 is two extra `queue_response` calls in the demo seed function. The notes are quality-of-life improvements that make the teaching code teach better. Cleared for editor handoff after the warnings are addressed.
