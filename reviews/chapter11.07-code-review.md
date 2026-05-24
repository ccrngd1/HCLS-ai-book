# Code Review: Recipe 11.7 — Chronic Disease Management Coach (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter11.07-python-example.md`
- `chapter11.07-chronic-disease-management-coach.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 8 |

The Python companion is a substantial walkthrough of the eight pseudocode steps from the main recipe (enroll the patient and instantiate the longitudinal store; ingest biometric data and evaluate against care-plan thresholds; schedule and deliver proactive engagement; handle a patient-initiated or patient-responding conversation with longitudinal-context loading; generate the response with care-plan-grounded reasoning and behavior-change-stage adaptation; run output safety screening with citation grounding, scope verification, and stage-tone check; persist the durable coaching-decision record and longitudinal updates; generate care-team reports and run outcome correlation). The structural decomposition tracks the pseudocode well; the longitudinal-store-as-architectural-primitive pattern is honored throughout (every conversation loads care plan + recent biometric + recent conversation history + patient preferences + behavior-change-stage estimates + open follow-ups before generating any response); the care-plan-template library is data-driven with version stamping; the biometric-threshold evaluation runs deterministic Python over care-plan-specified thresholds rather than asking the LLM to pick thresholds; the engagement-policy enforcement (quiet hours, daily cap, topic opt-outs, fatigue mitigation) is operational before any proactive message goes out; the continuous emergency-screening runs on every patient utterance with condition-specific gating for HF/diabetes/HTN-specific patterns; the citation-verification stage requires every recommendation to be grounded in a cited care-plan element, clinical guideline, or patient-education content; the coaching-decision-record journal writes to both DynamoDB and an S3 archive with version stamps; the `Decimal`-not-`float` discipline is consistent at every DynamoDB write boundary; `_emit_event`, `_put_metric`, and `_audit_tool_call` follow the established 11.x patterns.

**Validation performed:**
- Walked the eight pseudocode steps against the Python functions: Step 1 → `enroll_patient` + `_initialize_behavior_change_stages` + `_extract_outcome_baseline`; Step 2 → `biometric_data_received` + `_validate_biometric_reading` + `_evaluate_single_reading` + `_evaluate_trend` + `_read_active_care_plan`; Step 3 → `schedule_engagement` + `deliver_scheduled_engagement` + `_enforce_engagement_policy` + `_next_non_quiet_window` + `_summarize_recent_biometric` + `_screen_engagement_output` + `_deliver_via_channel`; Step 4 → `receive_message` + `_get_or_create_session` + `_screen_input` + `_emergency_screen` + `_sensitive_disclosure_screen` + `_handle_emergency_routing` + `_handle_sensitive_disclosure` + `_recent_biometric_for_context` + `_recent_conversation_for_context` + `_open_followups_for_patient`; Step 5 → `handle_conversation` + `compose_coaching_system_prompt` + `_evaluate_behavior_change_signals` + `_update_behavior_change_stage`; Step 6 → `screen_coach_output` + `_detect_coaching_scope_violations` + `_verify_coaching_citations` + `_verify_stage_appropriate_tone` + `_check_care_plan_deviation`; Step 7 → `persist_coaching_artifacts` + `_extract_coaching_decisions` + `_extract_longitudinal_updates` + `propose_escalation`; Step 8 → `deliver_care_team_alerts` + `compose_weekly_digest` + `queue_outcome_correlation` + `run_outcome_correlation_pipeline`.
- Verified service-name strings on the boto3 clients: `bedrock-runtime`, `bedrock-agent-runtime`, `dynamodb` (resource), `events`, `firehose`, `cloudwatch`, `s3`, `secretsmanager`, `pinpoint`, `stepfunctions` are all correct.
- Verified the `Decimal`-not-`float` discipline at every DynamoDB write boundary. `_to_decimal` recursively converts floats to `Decimal` and is invoked at every put_item path: `enroll_patient` (longitudinal-store, care-plan record), `biometric_data_received` (biometric-event-store), `schedule_engagement` (engagement-schedule), `deliver_scheduled_engagement` (engagement-schedule update), `receive_message` (conversation state, conversation-metadata), `_audit_tool_call` (tool-call ledger), `persist_coaching_artifacts` (conversation-metadata, decision-record-table), `propose_escalation` (care-team-alert queue), `_update_behavior_change_stage` (longitudinal-store), `queue_outcome_correlation` (outcome-correlation-pending). The Decimal-typed thresholds and care-plan values (`Decimal("0.70")`, `Decimal("0.30")`, `Decimal("8.2")` for baseline a1c, `Decimal("7.0")` for a1c goal, `Decimal("0.80")` for adherence target) are correct. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` does not wrap value in Decimal.
- Verified the coaching-decision-record-journal S3 path has no leading slash: `f"decisions/{patient_id}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{decision_id}.json"`.
- Verified the deploy-time guardrail asserts every resource-name constant is non-empty (LONGITUDINAL_STORE_TABLE, CONVERSATION_STATE_TABLE, ..., GUARDRAIL_VERSION).
- Verified the EventBridge `put_events(Entries=[{Source, DetailType, Detail, EventBusName}])` shape, the S3 `put_object(Bucket=..., Key=..., Body=..., ServerSideEncryption="aws:kms")` shape, the CloudWatch `put_metric_data(Namespace=..., MetricData=[{MetricName, Value, Unit, Dimensions}])` shape, and the Pinpoint `send_messages(ApplicationId=..., MessageRequest={"Addresses": ..., "MessageConfiguration": ...})` shape are all correct against current SDK conventions.
- Hand-traced each demo scenario through the Python flow:
  - `enroll Maria`: care-plan template `type_2_diabetes_lifestyle_plus_metformin` instantiated; longitudinal-store written with `behavior_change_stage_per_goal` defaulting to `preparation` for all three goals; care plan stored on the (collapsed) CONVERSATION_METADATA_TABLE; onboarding engagement scheduled with `priority="high"` and 24h delay; `patient_enrolled` event emitted; `PatientEnrolled` metric incremented.
  - `glucose readings 138, 145, 162, 168, 165, 175`: each reading validated and stored. None trigger `_evaluate_single_reading` (max 175 < single_reading_high=250). `_evaluate_trend` computes avg = 158.83 over 6 readings; trend_threshold_high=180; 158.83 < 180 → no trend event. So no biometric-triggered engagements scheduled. After ingest, only the original onboarding engagement is in the schedule.
  - `deliver scheduled onboarding engagement`: `priority="high"` bypasses quiet-hours skip; `_enforce_engagement_policy` returns deliver; trigger_kind="onboarding_introduction" falls through to else branch in `MockBedrockRuntime.invoke_engagement_message` and returns the generic check-in body; `_screen_engagement_output` passthrough deliver; `_deliver_via_channel` dispatches via SMS through Pinpoint mock.
  - `mom is visiting`: input passes injection patterns; `_emergency_screen` runs against all categories — `dka_pattern` and `severe_hypoglycemia` and `hypertensive_emergency` are gated by `applies_to_conditions`, none of their keywords match; no emergency. `_sensitive_disclosure_screen` returns no match (no medication-discontinuation keywords). Longitudinal context loaded; `mock_bedrock.invoke_conversation_response` matches "mom is visiting" branch and returns the family-visit response with one `longitudinal_disclosure_record` tool call and a care_plan citation. Output screen passes (no scope violation, has citation, no recommendation patterns, no stage mismatch). `_extract_coaching_decisions` produces 2 decisions: `recommendation_made` (because citations present) + `life_context_recorded`. Decision records written to DynamoDB + S3.
  - `i could do the morning thing`: matches "morning thing" branch; mock returns response containing "Let's try" with 2 citations (education_content + care_plan) and a `follow_up_schedule` tool call. Output screen detects "let's try" matches recommendation patterns; citations present (2); citation_check passes. `_extract_coaching_decisions` produces 1 decision (recommendation_made; follow_up_schedule isn't in the elif chain in `_extract_coaching_decisions`). The follow_up_schedule tool call is processed in Step 7D and schedules a new "morning_breakfast_routine_check" engagement at +4 days. `_evaluate_behavior_change_signals` matches "i could do" against action_signals; updates one of the `preparation` goals to `action`.
  - `weekly digest`: iterates engagement schedule, biometric event store, longitudinal-store disclosures, behavior-change-stage updates within the 7-day window. Computes glucose average of 159 (rounded), median of `sorted_values[3]=165`, with disclosures count=1 and 1 stage update.
- Verified the `MockBedrockRuntime.invoke_conversation_response` for the "stopped my metformin" scenario (not exercised in run_demo but referenced in the recipe): returns a motivational-interviewing-aligned response, `longitudinal_disclosure_record` tool call with category="medication_discontinuation", and `care_team_alert_propose` with urgency="within_shift". This produces 3 decision records (recommendation_made + life_context_recorded + care_team_alert_proposed) when persisted.
- Verified `_apply_special_population_upgrades`-equivalent (n/a — coach doesn't have this concept; the equivalent is care-plan-specified escalation criteria and `propose_escalation`, which is correctly invoked from biometric-threshold evaluation when severity=="escalation").
- Verified the conservative-bias-equivalent in coaching: Step 6E `_check_care_plan_deviation` returns `{"deviation_detected": False}` always; Step 6 falls back to `UNGROUNDED_RESPONSE_FALLBACK` if no citations are present and a recommendation is detected. The architecture is present but the deviation check is a passthrough (NOTE-level finding below).
- Verified the prompt-injection regex list (`INJECTION_PATTERNS`) covers the demo's expected injection patterns.
- Verified the deploy-time guardrail asserting non-empty resource-name constants survives the carry-forward from prior 11.x recipes. As in prior reviews, the placeholder strings (`PINPOINT_APP_PLACEHOLDER`, `STATE_MACHINE_ARN_PLACEHOLDER`, `GUARDRAIL_PLACEHOLDER_ID`, `GUIDELINE_KB_PLACEHOLDER`, `EDUCATION_KB_PLACEHOLDER`, `HISTORY_KB_PLACEHOLDER`) are non-empty and would pass the assert even when the deployer forgot to replace them; a stronger guardrail would require the strings to NOT match a hardcoded placeholder list. (Carry-forward NOTE.)

The walkthrough is structurally faithful to the architecture diagram and the eight pseudocode steps. The longitudinal-store-as-architectural-primitive, the care-plan-as-code with version stamping, the deterministic biometric-threshold evaluation, the engagement-policy enforcement with quiet-hours and daily-cap and topic-opt-out and fatigue-mitigation, the continuous-emergency-screening on every utterance with condition-specific gating, the sensitive-disclosure routing, the behavior-change-stage tracking with conversation-style adaptation, the citation-grounding output screen, the coaching-decision-record journal as a separately-governed log, the per-cohort metric dimensions (Condition, Channel, Type, GoalId, NewStage), and the version stamping (`active_care_plan_id`, `active_care_plan_version`, `active_model_id`, `active_prompt_version`, `active_agent_version`, `active_stage_logic_version`) are all the load-bearing primitives the main recipe sells, and they are structurally present.

Two WARNING-level findings concentrate on (a) `coach_full_pipeline` invoking `handle_conversation` twice per inbound message because `receive_message` already terminates by calling it, producing duplicate LLM invocations and inflating the tool-call ledger by 2x in the demo, and (b) several "production-flow" code paths (`_enforce_engagement_policy`, `_open_followups_for_patient`, `_recent_conversation_for_context`, `deliver_care_team_alerts`, `compose_weekly_digest`, `run_outcome_correlation_pipeline`) directly accessing `MockTable.items` rather than calling `Query`/`Scan`, which works in the demo but fails with `AttributeError` against a real boto3 DynamoDB Table resource. Per the persona's pass/fail rules, two WARNINGs is below the more-than-three threshold; the verdict is PASS.

---

## WARNING Findings

### W1. `coach_full_pipeline` invokes `handle_conversation` twice per inbound message because `receive_message` already terminates by `return handle_conversation(...)`; the demo inflates the tool-call ledger by 2x and pays for double LLM invocations per turn

**File / section:** `chapter11.07-python-example.md`, "Step 4: Handle Patient-Initiated or Patient-Responding Conversation," `receive_message` last block:

```python
return handle_conversation(
    session_id=session_id,
    patient_id=patient_id,
    user_message=user_message,
    longitudinal_context=longitudinal_context)
```

And the "Full Pipeline" section, `coach_full_pipeline`:

```python
intermediate = receive_message(...)

if isinstance(intermediate, dict) and \
        intermediate.get("disposition") in [
            "emergency_routed",
            "blocked",
            "no_care_plan_fallback"]:
    return intermediate

# Step 5: generate the response.
response_intermediate = handle_conversation(
    session_id=intermediate["session_id"],
    patient_id=intermediate["patient_id"],
    user_message=user_message,
    longitudinal_context=intermediate["longitudinal_context"])
```

**What's wrong:**

`receive_message` does Step 4A through 4F (session creation, input screening, emergency screening, sensitive-disclosure screening, longitudinal-context loading) and then returns the result of `handle_conversation(...)` — that is, it already does Step 5. Its return dict has keys `session_id`, `patient_id`, `response_text`, `citations`, `tool_calls`, `longitudinal_context`. There is no `disposition` field.

`coach_full_pipeline` receives that dict as `intermediate`. The disposition gate `intermediate.get("disposition") in ["emergency_routed", "blocked", "no_care_plan_fallback"]` always evaluates False because the field doesn't exist. The pipeline then calls `handle_conversation` AGAIN with the same `user_message`. This produces a SECOND round of:

- A full Bedrock Agent invocation (in production this is the dominant cost).
- A second pass through `_evaluate_behavior_change_signals` and (potentially) `_update_behavior_change_stage`, which is read-modify-write and races against itself.
- A second set of `_audit_tool_call` writes to the tool-call-ledger.

The first response from `receive_message` is silently discarded (only its `session_id`, `patient_id`, and `longitudinal_context` are read).

I traced this against the demo. For "mom is visiting" the mock returns 1 tool call (`longitudinal_disclosure_record`) per `handle_conversation` invocation. With double-invocation, that becomes 2 tool-call-ledger entries. For "morning thing" the mock returns 1 tool call (`follow_up_schedule`). With double-invocation, 2 entries. The demo's printed line:

```python
print(f"Tool-call ledger entries:      "
      f"{sum(len(v) for v in mock_tables[TOOL_CALL_LEDGER_TABLE].items.values())}")
```

shows 4 ledger entries instead of the 2 a learner would expect from the pseudocode's clean Step-4-then-Step-5 separation. Decision-record persistence is run only once (on the second response), so decision-record counts are not duplicated; but the second call's `follow_up_schedule` tool call also re-triggers the `schedule_engagement` path in Step 7D, doubling the scheduled "morning_breakfast_routine_check" engagement count.

The teaching point at stake is significant. The recipe's pseudocode treats Step 4 (receive + load context) and Step 5 (generate response) as separate concerns, with separate Lambdas in production. The whole motivation for that separation is that input-safety screening and emergency screening can short-circuit the pipeline BEFORE the expensive Bedrock invocation runs. Collapsing Step 5 into Step 4's return value defeats that. A learner reading this and copying the pattern into their own Lambda will pay for double LLM invocations on every conversation — a meaningful operational cost given the recipe's "$3-12 per active member per month" budget assumes one orchestration-model invocation per turn.

The bug is observable but doesn't crash the demo because `MockBedrockRuntime.invoke_conversation_response` is deterministic — both invocations return the same response. In production with a real LLM, the two invocations could produce different responses (the LLM's temperature plus the second-invocation tool calls' state changes from the first), which would be silently inconsistent.

**How to fix:**

The smaller change (and the one I'd recommend) is to remove the `return handle_conversation(...)` from the end of `receive_message` and have it return the loaded context only:

```python
def receive_message(*, channel, channel_session_id,
                     user_message, auth_context):
    ...
    # Step 4F: load longitudinal context.
    ...
    longitudinal_context = {...}

    metadata_table.put_item(Item=_to_decimal({...}))

    # Return the loaded context for Step 5 to consume.
    return {
        "session_id":            session_id,
        "patient_id":            patient_id,
        "longitudinal_context":  longitudinal_context,
    }
```

Then `coach_full_pipeline` calls `handle_conversation` exactly once, with the loaded context. The `disposition` gate at the top still works because the emergency-routing and block paths produce dicts with `disposition` keys (`_handle_emergency_routing` returns `{"response": ..., "disposition": "emergency_routed", "citations": []}`; `_handle_block` returns `{"response": ..., "disposition": "blocked", "citations": []}`; the no-care-plan fallback path returns `{"response": ..., "disposition": "no_care_plan_fallback", "citations": []}`).

After the fix, hand-tracing "mom is visiting" gives 1 tool-call-ledger entry (matching the single `longitudinal_disclosure_record` call) and "morning thing" gives 1 entry (the `follow_up_schedule` call). Total ledger entries = 2 in the demo summary, matching what the pseudocode promises.

Severity is WARNING rather than ERROR because the demo runs end-to-end without crashing — the printed output is misleading and the cost is doubled, but no AttributeError, KeyError, or other exception fires.

---

### W2. Six "production-flow" functions iterate `MockTable.items.values()` directly (`_enforce_engagement_policy`, `_open_followups_for_patient`, `_recent_conversation_for_context`, `deliver_care_team_alerts`, `compose_weekly_digest`, `run_outcome_correlation_pipeline`); the `.items` attribute does not exist on a real boto3 DynamoDB Table resource, so a learner promoting these to production gets `AttributeError`

**File / section:** `chapter11.07-python-example.md`, multiple sections. Representative example from "Step 3: Schedule and Deliver Proactive Engagement," `_enforce_engagement_policy`:

```python
today = _now().date().isoformat()
table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
delivered_today = sum(
    1 for record_list in table.items.values()
    for record in record_list
    if record.get("patient_id") ==
        longitudinal["patient_id"]
    and record.get("status") == "delivered"
    and record.get("delivered_at", "").startswith(today))
```

And from "Step 4," `_recent_conversation_for_context`:

```python
metadata_table = dynamodb.Table(CONVERSATION_METADATA_TABLE)
out = []
for record_list in metadata_table.items.values():
    for record in record_list:
        if record.get("kind") != "turn":
            continue
        ...
        out.append(record)
return out[-max_turns:]
```

And from "Step 4," `_open_followups_for_patient`:

```python
table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
out = []
for record_list in table.items.values():
    for record in record_list:
        if record.get("patient_id") != patient_id:
            continue
        if record.get("status") == "scheduled":
            out.append(record)
return out
```

And from "Step 8," `deliver_care_team_alerts`, `compose_weekly_digest`, `run_outcome_correlation_pipeline` — all use the same `for record_list in table.items.values()` pattern.

**What's wrong:**

The `dynamodb.Table()` factory in this demo is monkey-patched to return a `MockTable` instance:

```python
def _mock_dynamodb_table(name):
    return mock_tables[name]

dynamodb.Table = _mock_dynamodb_table
```

`MockTable` exposes `.items` (a `dict[str, list[dict]]`) for the demo's iteration patterns to work. A real `boto3.resource("dynamodb").Table(name)` does NOT expose an `items` attribute — that name is taken by the standard `dict.items()` method on the surrounding dict-like wrappers, but on the boto3 Table resource itself it does not exist. Calling `table.items.values()` against a real boto3 Table raises `AttributeError: 'dynamodb.Table' object has no attribute 'items'` immediately.

The recipe's prose makes this a particularly load-bearing concern:

> The chat-handler Lambda has Bedrock invocation and read-write on the conversation tables, but no direct access to the EHR or the care-team-workflow system.

The implicit message is that production has real DynamoDB calls. A learner who copies the demo's `_enforce_engagement_policy` and points it at a real boto3 Table will see their first proactive engagement attempt crash with `AttributeError`. The prior 11.x recipes (notably 11.05 and 11.06) used a `MockTable.query` method that exposed a `query()` method matching the boto3 surface, with the call sites using `table.query(KeyConditionExpression=Key("session_id").eq(...))`. That pattern is portable; this one is not.

The teaching point at stake: production DynamoDB access for these queries needs either (1) a Global Secondary Index keyed by `patient_id` (or `status` + `patient_id` for the alert-queue) plus a `Query` call against that GSI, or (2) at minimum a `Scan` with a `FilterExpression` and an acknowledgment that scans are expensive. Neither is shown. A learner is taught a pattern that doesn't exist in production.

I traced each affected function:

- `_enforce_engagement_policy`: needs a GSI on `patient_id` (or `patient_id-delivered_at` composite) and a Query that filters by patient_id and the delivered_at date prefix.
- `_open_followups_for_patient`: needs the same GSI plus a filter on status="scheduled".
- `_recent_conversation_for_context`: needs a GSI keyed by `patient_id` with `timestamp` as sort key (and the comment in the function correctly acknowledges this: `"Production keys by patient_id with session_id as a sort attribute."` — but the implementation diverges from the comment).
- `deliver_care_team_alerts`: needs to Query the alert queue filtered by status="pending_review" (probably via a status GSI).
- `compose_weekly_digest`: same as above, multiple GSI Query calls.
- `run_outcome_correlation_pipeline`: needs to Query the outcome-correlation table filtered by status="pending".

Severity is WARNING because the demo runs (the mock provides `.items`), but the pattern is misleading for production and any learner who promotes the function bodies as written will hit an immediate AttributeError. (Compare the prior 11.x reviews where `MockTable.query` matched the boto3 surface; that pattern survived promotion to production with index-name and KeyConditionExpression changes only.)

**How to fix:**

Two natural options, in order of pedagogical value:

1. **Make `MockTable` expose a `query(...)` method** matching the boto3 surface (as the 11.05/11.06 mocks did) and rewrite the six call sites to use Query with KeyConditionExpression. This is the higher-value fix because it teaches the production pattern. Each call site picks up roughly:

   ```python
   from boto3.dynamodb.conditions import Key, Attr
   response = table.query(
       IndexName="patient-id-index",
       KeyConditionExpression=Key("patient_id").eq(patient_id),
       FilterExpression=Attr("status").eq("scheduled"))
   for record in response.get("Items", []):
       ...
   ```

   The mock's `query()` returns `{"Items": [...]}` after applying the KeyConditionExpression to the partition-key dimension; the call sites become directly portable.

2. **At minimum, add a comment block at each affected call site** noting that the iteration pattern is mock-only and the production path uses Query against a named GSI. This is the lower-value fix because it leaves the misleading pattern in the code; but if Option 1 is too much work, Option 2 prevents a learner from silently copying the wrong pattern.

Either fix removes the AttributeError trap. Option 1 also makes the code closer to production-ready and is consistent with the pattern from the prior 11.x recipes.

---

## NOTE Findings

### N1. `_recent_biometric_for_context` reads from `mock_biometric_vendor.feed` directly rather than from the BIOMETRIC_EVENT_STORE_TABLE; `biometric_data_received` writes to the table but the conversation-context loader bypasses it

**File / section:** `chapter11.07-python-example.md`, "Step 4," `_recent_biometric_for_context`:

```python
def _recent_biometric_for_context(patient_id, days=30):
    """Recent biometric data for conversation context."""
    cutoff = _now() - timedelta(days=days)
    out = []
    for r in mock_biometric_vendor.feed.get(patient_id, []):
        ts = datetime.fromisoformat(r["timestamp"])
        if ts >= cutoff:
            out.append(r)
    return out
```

And `_summarize_recent_biometric` in Step 3 (similar pattern):

```python
def _summarize_recent_biometric(patient_id, context):
    device = context.get("device_type", "glucose_meter")
    readings = mock_biometric_vendor.recent(
        patient_id, device, days=7)
    ...
```

`biometric_data_received` writes every reading to the BIOMETRIC_EVENT_STORE_TABLE:

```python
biometric_store = dynamodb.Table(BIOMETRIC_EVENT_STORE_TABLE)
biometric_store.put_item(Item=_to_decimal({...}))
```

But the conversation-context loader and the engagement-context summarizer both read from `mock_biometric_vendor.feed`, not from the table. The two paths are out of sync: in production the biometric event store is the canonical source, with the vendor APIs being the upstream ingestion source feeding the store. A reader is taught that the data is in DynamoDB (because `biometric_data_received` writes there) but the demo never reads it back from there.

Fix: have `_recent_biometric_for_context` and `_summarize_recent_biometric` Query the BIOMETRIC_EVENT_STORE_TABLE filtered by patient_id and reading_timestamp range. This requires the same GSI work as W2's `_recent_conversation_for_context`. The fix unifies the architecture: the vendor APIs feed the store, the store is the canonical retrieval source, the conversation context is loaded from the store. This is also what the recipe's prose says explicitly: "deep biometric integration covering CGM, BP cuff, scale, peak flow meter, pulse oximeter, smartwatch."

### N2. `_screen_engagement_output` is a passthrough no-op; the recipe's pseudocode Step 3D explicitly requires the same output-safety screening for proactive engagement messages as for conversation responses, but the demo skips it

**File / section:** `chapter11.07-python-example.md`, "Step 3," `_screen_engagement_output`:

```python
def _screen_engagement_output(message, care_plan,
                                longitudinal):
    """
    Output screening for proactive engagement messages.
    """
    # Demo: pass-through. Production runs the same screening
    # pipeline as the conversation-handler output screening.
    return {"action": "deliver"}
```

The pseudocode (Step 3D):

```
// Step 3D: output safety screening.
safety_check = screen_output(
    response: composed.message,
    session_context: { patient_id, care_plan_id,
                       engagement_type })

IF safety_check.action != "deliver":
    log_engagement_screening_failure(...)
    return { action: "screening_failed" }
```

The Python's `screen_coach_output` (Step 6) implements scope-violation detection, citation grounding, behavior-change-stage tone check, and care-plan-deviation check for conversation responses. The Step 3D analog should run the same pipeline against composed engagement messages — particularly because proactive engagement messages, unlike user-initiated conversation responses, can include unwarranted health claims if the LLM hallucinates during composition. A coach-initiated message saying "your readings are too high, you need to take more metformin" is a scope violation and an off-care-plan treatment recommendation; without screening, it ships.

The demo's mock LLM is deterministic and returns templated messages, so the demo never produces a screen-triggering message. But a learner running this against a real LLM will discover the screening gap on the first proactive engagement that includes prescriptive language.

Fix: have `_screen_engagement_output` invoke `_detect_coaching_scope_violations` and `_verify_coaching_citations` against the composed message (the citation list comes from `composed["citations"]`), and return a non-deliver action when either trips. The composed message already has citations; the verifier needs the same care_plan reference; the scope detection runs against the message text. This makes Step 3D structurally present rather than acknowledged-and-skipped.

### N3. The continuous emergency-screen `dka_pattern` keyword "really thirsty and confused" matches benign conversational mentions; the architecture is correct but the keyword choice is fragile against false positives in long-running coaching relationships

**File / section:** `chapter11.07-python-example.md`, "Configuration and Constants," `EMERGENCY_VOCABULARY`:

```python
"dka_pattern": {
    "keywords": [
        "can't stop vomiting", "cant stop vomiting",
        "fruity breath",
        "really thirsty and confused",
        "deep heavy breathing",
    ],
    "urgency": "call_911",
    "applies_to_conditions":
        ["type_1_diabetes", "type_2_diabetes"],
},
```

The substring `"really thirsty and confused"` is a low-frequency phrase but coaching conversations span months and accumulate a lot of patient text. Patients with diabetes may say things like "I was really thirsty and confused about whether to take my pill at lunch or dinner" — the substring matches but the acuity is wrong. Similarly `"deep heavy breathing"` could match a yoga or relaxation discussion ("I was practicing deep heavy breathing during the panic attack"), and `"can't stop vomiting"` could match a family-history mention ("my husband can't stop vomiting after the procedure").

This is structurally the same finding as 11.06 W1 (the `cardiac` keyword matching family-history mentions). The Python's `_emergency_screen` is acknowledged to be a simplification:

> Production layers a tuned classifier on top of keyword detection, tests the screening layer against a held-out emergency-presentation corpus curated and reviewed by clinical leadership before launch and on each material update, and treats false-negative rate as a launch-gate metric.

The acknowledgment is fair. NOTE-level rather than WARNING because the demo's headline scenarios for Maria don't trigger this and the recipe's prose is clear that production handles this differently. But a learner copying the keyword list as-is gets false positives at scale.

Fix: tighten each gated keyword to require first-person markers ("I'm really thirsty and confused", "I can't stop vomiting") and exclude family-history-style mentions. Or better, split the screen into a keyword pre-filter plus a small classifier that confirms first-person acuity before routing. The 11.06 review's recommendation applies here.

### N4. The `enrollment` flow stores the care plan record on the CONVERSATION_METADATA_TABLE under a synthetic `session_id` of `f"care_plan_{care_plan_id}"`; there is no separate care-plan store table in the schema

**File / section:** `chapter11.07-python-example.md`, "Step 1," `enroll_patient`:

```python
care_plan_table = dynamodb.Table(
    CONVERSATION_METADATA_TABLE)  # demo: collapsed
care_plan_table.put_item(Item=_to_decimal({
    "session_id":  f"care_plan_{care_plan_id}",
    "kind":        "care_plan",
    "care_plan":   care_plan,
    "stored_at":   _now_iso(),
}))
```

And `_read_active_care_plan`:

```python
care_plan_table = dynamodb.Table(
    CONVERSATION_METADATA_TABLE)
plan_rec = care_plan_table.get_item(
    Key={"session_id": f"care_plan_{care_plan_id}"})
```

The care plan is a clinical record with its own retention floor, signing chain, and access-control story. Putting it on the same DynamoDB table as conversation turns is a demo simplification (acknowledged with a `# demo: collapsed` comment), but the resulting schema mixes record classes the recipe's prose explicitly separates. The recipe lists `patient-longitudinal-store` and `conversation-state` as separate tables; the care plan deserves a dedicated `care-plan-store` table (or, more precisely, the FHIR CarePlan resource in HealthLake/EHR is the canonical store and the demo is approximating it).

The carry-forward concern is that a learner reading the schema list (which includes nine DynamoDB tables but no care-plan store) and then reading `_read_active_care_plan` may be confused about which table holds care plans. The acknowledgment via comment is fair, but a small refactor to define a tenth table — `coach-care-plan-store` — and use it for these reads/writes would clarify the architecture.

Fix: add `CARE_PLAN_STORE_TABLE = "coach-care-plan-store"` to the resource-name constants (and the `mock_tables` registry), and have `enroll_patient` and `_read_active_care_plan` use it. The change is mechanical and untangles the schema.

### N5. The TOOL_CALL_LEDGER_TABLE schema collapses multiple tool calls per session under one partition key with no sort key; in real DynamoDB the second `put_item` overwrites the first

**File / section:** `chapter11.07-python-example.md`, "Mock Infrastructure," `mock_tables`:

```python
TOOL_CALL_LEDGER_TABLE: MockTable(
    TOOL_CALL_LEDGER_TABLE, "session_id"),
```

And `_audit_tool_call`:

```python
table = dynamodb.Table(TOOL_CALL_LEDGER_TABLE)
table.put_item(Item=_to_decimal({
    "session_id":         session_id,
    "invoked_at":         _now_iso(),
    "tool":               tool,
    ...
}))
```

`MockTable.put_item` appends to the per-key list:

```python
self.items.setdefault(key, []).append(_from_decimal(Item))
```

so multiple writes per session_id are preserved. In real DynamoDB, a second `put_item` with the same partition key replaces the first; the table needs a sort key (e.g., `invoked_at` or `tool_call_id`) for multiple records per session to coexist.

The same collapse applies to the BIOMETRIC_EVENT_STORE_TABLE (six glucose readings for one patient go into one partition-key list in the mock; in real DynamoDB the table needs a sort key on `reading_timestamp`), to the CONVERSATION_METADATA_TABLE (multiple turns per session), to the OUTCOME_CORRELATION_TABLE (multiple correlation records per patient), and to the ENGAGEMENT_SCHEDULE_TABLE (multiple status updates per engagement_id).

This is structurally the same NOTE as the prior 11.x reviews. Fix: declare the sort key in the schema description (the "Setup" section of the demo lists nine tables but doesn't specify partition + sort keys). Adding a one-paragraph schema description at the top of the file would resolve the ambiguity. Production would have:

- TOOL_CALL_LEDGER: PK=session_id, SK=invoked_at
- BIOMETRIC_EVENT_STORE: PK=patient_id, SK=reading_timestamp + device_type
- CONVERSATION_METADATA: PK=session_id, SK=timestamp
- OUTCOME_CORRELATION: PK=patient_id, SK=window_start
- ENGAGEMENT_SCHEDULE: PK=engagement_id (unique IDs, no SK needed) — but with a GSI on patient_id for the W2 queries
- DECISION_RECORD: PK=decision_id (unique IDs) — with a GSI on patient_id

### N6. `compose_weekly_digest` counts engagements with `status="responded"` but no code path ever sets engagement status to "responded"; the `responded` field in the digest is always 0

**File / section:** `chapter11.07-python-example.md`, "Step 8," `compose_weekly_digest`:

```python
scheduled, delivered, responded = 0, 0, 0
for record_list in eng_table.items.values():
    for record in record_list:
        ...
        if record.get("status") == "delivered":
            delivered += 1
        if record.get("status") == "responded":
            responded += 1
```

Engagement status transitions in the demo are: `scheduled` (set in `schedule_engagement`) → `delivered` (set in `deliver_scheduled_engagement`). There is no path that sets status to `responded` — the recipe's pseudocode (`engagement_responded`) emits an EventBridge event when the patient responds to a delivered engagement, but the Python doesn't implement the inbound-message-to-engagement linking.

The digest's `responded` count is always 0. This is a demo simplification but it's misleading because the digest's `engagement_summary` block is part of the demo's printed output:

```python
print(f"  -> engagement: "
      f"{digest['engagement_summary']}")
```

A reader sees `{'scheduled': 2, 'delivered': 1, 'responded': 0}` and may be confused about why nothing responded. The relationship-quality engineering the recipe's prose emphasizes ("a patient who responds within 24 hours of a check-in is a positive engagement signal") is invisible in the digest.

Fix: link inbound `receive_message` to the most recent delivered engagement when the inbound timestamp is within the engagement-followup window (e.g., 48 hours). When linked, update the engagement record's status to `responded` and emit the `engagement_responded` event. This is roughly:

```python
def _link_response_to_engagement(patient_id, session_id):
    cutoff = _now() - timedelta(hours=48)
    table = dynamodb.Table(ENGAGEMENT_SCHEDULE_TABLE)
    # production: GSI Query by patient_id and delivered_at
    # demo: scan + filter
    for record_list in table.items.values():
        for record in record_list:
            if record.get("patient_id") != patient_id:
                continue
            if record.get("status") != "delivered":
                continue
            delivered = record.get("delivered_at", "")
            if delivered < cutoff.isoformat():
                continue
            record["status"] = "responded"
            record["responded_at"] = _now_iso()
            _emit_event("engagement_responded", {
                "engagement_id": record["engagement_id"],
                "patient_id": patient_id,
            })
            return
```

Alternatively, just remove the `responded` counter from `compose_weekly_digest` since it's always 0 in the demo.

### N7. Pseudocode Step 6 has six sub-steps (6A standard guardrail layer, 6B scope, 6C citations, 6D stage-tone, 6E care-plan-deviation, 6F persona-and-tone); the Python's `screen_coach_output` collapses to four (scope, citations, stage-tone, deviation), and the deviation check is a passthrough (`return {"deviation_detected": False}`)

**File / section:** `chapter11.07-python-example.md`, "Step 6," `_check_care_plan_deviation`:

```python
def _check_care_plan_deviation(response_text, care_plan):
    """
    Detect recommendations that would deviate from the care
    plan (different medication, different goal, different
    target). Production runs structured-output verification;
    the demo passes through.
    """
    return {"deviation_detected": False}
```

And the persona-and-tone check (pseudocode 6F) is acknowledged in the function's epilogue comment but not implemented:

```python
# Step 6E: persona-and-tone check. Production runs a
# vendor-managed guardrail layer plus a tone evaluator;
# the demo passes through.
return {
    "response":     response_text,
    "disposition":  "delivered",
    "citations":    citations,
    "tool_calls":   tool_calls,
}
```

The 11.05 and 11.06 reviews flagged similar omissions in their output-screening pipelines. The pattern is consistent: handler-level discipline (renderer includes the right phrasings) compensates for the missing screening-stage verifier in the demo, but a future renderer regression silently ships ungrounded or off-tone responses. The persona-and-tone check is particularly load-bearing for a chronic-disease coach because the recipe's prose argues that relationship-quality engineering is most of the engineering and tone calibration is the biggest single lever.

Fix: add minimal per-care-plan-deviation patterns to `_check_care_plan_deviation` (e.g., detect mentions of medications not in the care plan's medication list, detect mentions of goals not in the care plan's goal list) and add a minimal persona-and-tone check that flags prescriptive language for pre-contemplation patients (which `_verify_stage_appropriate_tone` already partially does — that function could be expanded to also flag overly-clinical tone for action patients, etc.). The minimal demo-level checks demonstrate the architectural floor; production runs LLM-as-judge with structured-output validation.

### N8. The Pinpoint `Addresses` keys use synthetic `f"endpoint-{patient_id}"` strings rather than real channel addresses (phone numbers for SMS, push tokens for GCM); a learner copying this hits Pinpoint validation errors against a real campaign

**File / section:** `chapter11.07-python-example.md`, "Step 3," `_deliver_via_channel`:

```python
if channel == "push":
    pinpoint_client.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {
                f"endpoint-{patient_id}": {
                    "ChannelType": "GCM"}},
            "MessageConfiguration": {...}})
elif channel == "sms":
    pinpoint_client.send_messages(
        ApplicationId=PINPOINT_APPLICATION_ID,
        MessageRequest={
            "Addresses": {
                f"endpoint-{patient_id}": {
                    "ChannelType": "SMS"}},
            "MessageConfiguration": {...}})
```

In Pinpoint's `SendMessages` API, the `Addresses` map is keyed by the actual destination address — phone number for SMS (e.g., `"+15551234567"`), push token for GCM/APNS, email address for EMAIL. Synthetic identifiers like `"endpoint-{patient_id}"` are not valid addresses; Pinpoint returns a per-recipient validation error. The correct production flow is either:

1. Use `Endpoints` (not `Addresses`) keyed by Pinpoint endpoint IDs that map to addresses registered ahead of time.
2. Use `Addresses` keyed by the actual destination address resolved from the patient's preferences.

The mock's `MockPinpoint.send_messages` accepts any kwargs and records them, so the demo doesn't surface the bug. But a learner copying the pattern against a real Pinpoint application will get back error responses for every send.

Fix: either resolve the patient's address from the longitudinal store's `patient_preferences` (or a separate registered-endpoint store) before invoking, or switch to the Pinpoint `Endpoints` map and pre-register endpoint IDs at enrollment time. The recipe's prose mentions Pinpoint's "delivery-status tracking" but the demo doesn't show how addresses are sourced.

---

## Validation Notes

- The boto3 API surface used by the companion (`bedrock-runtime.invoke_model`-class via `bedrock_runtime`, `bedrock-agent-runtime` client constructor, `dynamodb.Table().put_item`/`get_item`/`update_item`/`query`, `events.put_events`, `firehose.put_record`, `cloudwatch.put_metric_data`, `s3.put_object`, `secretsmanager` client constructor, `pinpoint.send_messages`, `stepfunctions` client constructor) is correct against current SDK conventions. No method-name typos, no parameter-name drift.
- The `Decimal`-not-`float` discipline is consistent at every DynamoDB write boundary. `_to_decimal` recursively converts at every `put_item` path. The Decimal-typed thresholds (`INTENT_CONFIDENCE_THRESHOLD = Decimal("0.70")`, `ENGAGEMENT_FATIGUE_RESPONSE_RATE_FLOOR = Decimal("0.30")`, the care-plan goal targets `Decimal("0.80")` for adherence and `Decimal("7.0")` for a1c) are correctly typed at definition. The biometric thresholds are int-typed (250, 60, 7, 180) and DynamoDB accepts int natively. The biometric reading values are int (138, 145, etc.) and survive `_to_decimal` unchanged. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` correctly does not wrap value in Decimal.
- S3 keys in `persist_coaching_artifacts` have no leading slashes; the path structure `f"decisions/{patient_id}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{decision_id}.json"` is correctly formed.
- The deploy-time guardrail asserting non-empty resource-name constants survives the carry-forward from 11.1–11.6. The placeholder strings (`PINPOINT_APP_PLACEHOLDER`, `STATE_MACHINE_ARN_PLACEHOLDER`, `GUARDRAIL_PLACEHOLDER_ID`, the three KB placeholders) are non-empty and would pass the assert even when the deployer forgot to replace them; a stronger guardrail would require the strings to NOT match a hardcoded placeholder list. (Carry-forward from prior 11.x reviews.)
- The `EMERGENCY_VOCABULARY` covers the chronic-coach-specific high-acuity categories (cardiac_acute, stroke, hf_decompensation gated by `applies_to_conditions=["heart_failure"]`, dka_pattern gated by both diabetes types, severe_hypoglycemia gated by both diabetes types, hypertensive_emergency gated by hypertension, anaphylaxis ungated, psychiatric_crisis ungated). The condition-gating pattern correctly uses `if applies_to and not any(c in active_conditions for c in applies_to): continue` so general-applicability categories run for everyone and condition-specific categories run only for the relevant cohorts.
- The `SENSITIVE_DISCLOSURE_PATTERNS` covers the categories the recipe's prose names (intimate_partner_violence → ipv_pathway, food_insecurity → care_navigation, housing_insecurity → care_navigation, medication_discontinuation → care_team_followup, severe_side_effects → care_team_followup). The `_handle_sensitive_disclosure` correctly routes per the pathway field.
- The `CARE_PLAN_TEMPLATES` contains two illustrative templates (Type 2 diabetes lifestyle plus metformin, hypertension lifestyle plus lisinopril). Each declares `template_id`, `template_version`, `condition`, `owner` (specialty leadership), `effective_date`, a `goals_template` list, a `biometric_streams` thresholds dict, an `engagement_cadence` config, and an `escalation_criteria` list. The instantiation in `enroll_patient` correctly stamps `care_plan_id`, `care_plan_version`, signing chain, signed_at, effective_date, and next_review_date.
- The `EDUCATION_LIBRARY` contains two illustrative items (`morning_breakfast_glucose_tip`, `metformin_side_effect_tips`) with content_id, content_version, condition, topic, language, reading_level, and text. The "morning thing" demo branch correctly cites `morning_breakfast_glucose_tip` v1.0 alongside the care_plan citation.
- The `BEHAVIOR_CHANGE_STAGES` list is in the canonical order (pre_contemplation → contemplation → preparation → action → maintenance). The `compose_coaching_system_prompt` stage_guidance dictionary keys all match this list. The `_evaluate_behavior_change_signals` heuristic correctly bumps preparation/contemplation goals to action when the patient signals commitment ("i could do", "let's try"), and regresses action to contemplation on disengagement signals.
- The `_emergency_screen` correctly applies condition-gating before keyword matching, and the `_handle_emergency_routing` correctly routes 911 vs 988 by urgency. Both handlers persist context to the triage and mental-health pathways' mock receivers.
- The `_verify_coaching_citations` correctly detects recommendation patterns ("you should", "i'd suggest", "let's try", "what i recommend", "my recommendation"); when a recommendation is detected with no citations the response is replaced with `UNGROUNDED_RESPONSE_FALLBACK`. Care-plan citations are checked against the active plan id; mismatches are caught.
- The `_verify_stage_appropriate_tone` correctly flags prescriptive language ("you need to", "you must", "you should immediately") for pre-contemplation patients. The check is conservative and minimal; production layers a classifier on top.
- The `_extract_coaching_decisions` correctly produces `recommendation_made` when citations are present and one decision per care-team-alert / disclosure-record / escalation tool call. The decisions feed both DynamoDB and the S3 archive with version stamps (active_care_plan_id, active_care_plan_version, active_model_id, active_prompt_version, active_agent_version, active_stage_logic_version).
- The `_emit_event`, `_put_metric`, and `_audit_tool_call` helpers all wrap their AWS calls in try/except and log errors via `logger.error` rather than blocking the chat-handler response on a transient EventBridge / CloudWatch / DynamoDB hiccup.
- The `_redact_pii_for_logging` and `_redact_tool_args` helpers strip likely-PHI substrings before logging or ledger storage. The redaction blocklist correctly includes `patient_id`, `name`, `date_of_birth`, `user_message`, `free_text`, `phone`, `email`, `address`.
- The crisis-detection routing for the 988 path uses `CRISIS_RESPONSE_988` and the 911 path uses `CRISIS_RESPONSE_911`. Both templates include the appropriate stay-on-the-line guidance and the institutional-followup framing.
- The `INJECTION_PATTERNS` regex list (`r"ignore (all |any |the )?(previous|prior|above) (instructions|messages|prompts)"` etc.) covers the common prompt-injection variants.
- The Bedrock model IDs (`anthropic.claude-3-5-haiku-20241022-v1:0`, `anthropic.claude-3-5-sonnet-20241022-v2:0`) follow the published naming convention. The accompanying TODO note correctly cautions that model availability evolves and the deployer should verify against the region.
- The `propose_escalation` writes to the CARE_TEAM_ALERT_QUEUE_TABLE keyed by `alert_id` and emits the `escalation_triggered` event. `deliver_care_team_alerts` (modulo W2's iteration concern) would correctly mark records as delivered.
- The `_extract_longitudinal_updates` correctly extracts `longitudinal_disclosure_record` tool-call categories and appends to the longitudinal-store's `life_context_disclosures` list with a `recorded_at` timestamp.
- The `compose_coaching_system_prompt` correctly stamps the active care-plan id and version, the goals list, the behavior-change-stage guidance, the language preference, and the regulatory-position string. Skip the system-prompt assembly and the LLM has no scope discipline; the function is the architectural floor.

---

## Recommended Changes Before Re-Review

1. **Remove the `return handle_conversation(...)` from the end of `receive_message`** and have it return a `{session_id, patient_id, longitudinal_context}` dict only. The `coach_full_pipeline` then calls `handle_conversation` exactly once, which matches the pseudocode's Step-4-then-Step-5 separation. The tool-call ledger printout in the demo summary will halve, the LLM cost (in production) will halve, and the architectural separation the recipe's prose argues for becomes structurally present. (W1)
2. **Replace the six `for record_list in table.items.values()` iteration patterns** with `MockTable.query()` calls keyed by KeyConditionExpression, matching the pattern from 11.05 and 11.06. The mock's `query()` should accept the boto3 condition shape so the call sites are directly portable to production. The six call sites are `_enforce_engagement_policy`, `_open_followups_for_patient`, `_recent_conversation_for_context`, `deliver_care_team_alerts`, `compose_weekly_digest`, and `run_outcome_correlation_pipeline`. (W2)

The eight NOTE-level items are not blocking; they are quality-of-life improvements for future maintenance. The two WARNING-level fixes are recommended before the next pass but are below the persona's PASS threshold (more than three WARNINGs would FAIL).

The architectural skeleton is sound, the boto3 surface is correct, the Decimal-not-float discipline is consistent, the S3 paths are properly formed, the longitudinal-store-as-architectural-primitive pattern is honored, the care-plan-as-code with version stamping carries through every persisted record, the deterministic biometric-threshold evaluation runs over care-plan-specified thresholds rather than asking the LLM, the engagement-policy enforcement (quiet hours, daily cap, topic opt-outs) is operational before any proactive message ships, the continuous-emergency-screening discipline runs on every utterance with condition-specific gating, the sensitive-disclosure routing is in place for the categories the recipe's prose names, the citation-grounding output screen rejects ungrounded recommendations, the behavior-change-stage tracking with conversation-style adaptation is the one piece that makes the coach a coach rather than a chatbot, the coaching-decision-record journal writes to both DynamoDB and S3 with appropriate redaction, the outcome-correlation queueing is in place, and the version-stamping discipline carries through the conversation-state row, the decision-record journal, and the close-out audit record. The findings concentrate on (a) one pipeline-flow issue that doubles work without crashing, (b) one mocking-pattern that doesn't carry to production, and (c) eight smaller items typical of demo-vs-production simplifications and acknowledged-but-not-implemented pseudocode steps. Re-running the review after the recommended changes should be quick.
