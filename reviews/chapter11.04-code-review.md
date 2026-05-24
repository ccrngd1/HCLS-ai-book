# Code Review: Recipe 11.4 — Pre-Visit Intake Bot (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter11.04-python-example.md`
- `chapter11.04-pre-visit-intake-bot.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** FAIL

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 3 |
| WARNING  | 3 |
| NOTE     | 4 |

The Python companion is a substantial walkthrough of the ten pseudocode steps from the main recipe (session bootstrap with greeting/disclosure plus partial-state resume; intake-specific input safety screening including screener-aware crisis detection; encounter-context, chart-context, prior-intake, and demographics loading with protocol selection; question-flow state machine with one-question-per-turn capture; per-category extraction tools; parallel crisis-and-acuity flagging; explicit crisis-response templates; validated screener administration with item-level capture; pre-visit packet assembly and EHR delivery; output safety screening with intake-specific scope checks and chart-fact integrity; durable conversation archival with the per-record-class versioning stamps and per-cohort metric emission). The structural decomposition tracks the pseudocode well; the tool surface (`encounter_context_lookup_tool`, `chart_context_lookup_tool`, `prior_intake_lookup_tool`, `patient_demographics_lookup_tool`, `protocol_selector_tool`, `hpi_extraction_tool`, `ros_extraction_tool`, `medication_reconciliation_capture_tool`, `allergy_reconciliation_capture_tool`, `history_extraction_tool`, `screener_administer_tool_capture_item`, `crisis_routing_tool`, `packet_assemble_tool`, `packet_deliver_tool`, `clinical_staff_routing_tool`) is cleanly separated from orchestration logic; the validated-screener wordings are preserved verbatim from the configured library (PHQ-9 item 9 is correctly tagged `is_crisis_sensitive=True` with `crisis_response_values=[1,2,3]` and `crisis_category="suicidal_ideation"`); the pre-visit-packet journal writes to S3 via a key with no leading slash; `_emit_event`, `_put_metric`, and `_audit_tool_call` follow the established 11.x patterns; `REQUIRE_AUTHENTICATED_FOR_INTAKE = True` short-circuits the unauthenticated path and elides the unauthenticated identifier-collection bug that 11.01-11.03 carried.

**Validation performed:**
- Walked the ten pseudocode steps against the Python functions: Step 1 `receive_message` → `receive_message` + `_get_or_resume_session` + `_screen_input` + `_handle_screening_action`; Step 2 `load_visit_and_chart_context` → `_load_visit_and_chart_context`; Step 3 `conduct_intake_turn` → `_conduct_intake_turn` + `_question_flow_state_machine` + `_resolve_branch_questions` + `_phrase_question_conversationally`; Step 4 `capture_answer_for_question` → `_capture_answer_for_question` (dispatches to per-category extraction tools); Step 5 `crisis_and_acuity_flagging` → `_crisis_and_acuity_flagging` + `_acuity_pattern_detection` + `_pattern_matches` + `_detect_new_information`; Step 6 `route_crisis` → `_route_crisis` + `crisis_routing_tool`; Step 7 `administer_screener_bundle` → `screener_administer_tool_capture_item` + `_match_response_value` + `_compute_screener_score`; Step 8 `assemble_and_deliver_packet` → `_assemble_and_deliver_packet` + `packet_assemble_tool` + `packet_deliver_tool` + `_build_closing_summary` + `_write_packet_journal`; Step 9 `screen_output` → `_screen_output` + `_detect_intake_scope_violation` + `_extract_chart_fact_references` + `_ref_supported_by_chart`; Step 10 `close_conversation_and_archive` → `close_conversation_and_archive` + `_redact_turn_for_audit`.
- Verified service-name strings on the boto3 clients: `bedrock-runtime`, `bedrock-agent-runtime`, `comprehendmedical`, `dynamodb` (resource), `events`, `firehose`, `cloudwatch`, `s3`, `secretsmanager` are all correct.
- Verified the `Decimal`-not-`float` discipline at every DynamoDB write boundary. `_to_decimal` recursively converts floats to `Decimal` and is invoked at every put_item path: `_get_or_resume_session`, `_append_turn`, `_update_session_field`, `_audit_tool_call`, `_persist_partial_state`, `_persist_flag_event`. The Decimal-typed threshold `EXTRACTION_CONFIDENCE_THRESHOLD = Decimal("0.70")` is correct. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` does not wrap value in Decimal. `_from_decimal` is invoked when reading state.
- Verified the pre-visit-packet-journal S3 path has no leading slash: `f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['event_id']}.json"`.
- Verified the deploy-time guardrail asserts every resource-name constant is non-empty.
- Verified the screening-before-flow-handling discipline: `_screen_input` runs crisis detection (with screener-context awareness so PHQ-9 item 9 responses route through the screener path), then injection detection, then PHI detection.
- Verified the EventBridge `put_events(Entries=[{Source, DetailType, Detail, EventBusName}])` shape, the Firehose `put_record(DeliveryStreamName=..., Record={"Data": <bytes>})` shape, the S3 `put_object(Bucket=..., Key=..., Body=..., ContentType=..., ServerSideEncryption="aws:kms")` shape are all correct.
- Verified the `_resolve_session_key` GSI-then-fallback pattern carries forward correctly from 11.02's W1 fix.
- Verified the validated-screener wordings in `SCREENER_LIBRARY` for PHQ-2 and PHQ-9 item 9 match the validated instrument wordings exactly.
- Hand-traced each demo scenario through the Python flow. Findings below.

The walkthrough is structurally faithful to the architecture diagram and the ten pseudocode steps. The crisis-response template selection by category, the parallel crisis-and-acuity pipeline, the per-category extraction dispatch, the packet-journal as a separately-governed clinical-record-event log, the partial-state TTL for resume, the per-cohort metric dimensions, and the version stamping (`active_protocol_version`, `active_screener_bundle_version`, `active_acuity_pattern_version`, `packet_schema_version`) are all the load-bearing primitives the main recipe sells, and they are structurally present.

That said, the headline `happy_path_followup_with_acuity` scenario is broken in three independent ways that each prevent the demo from producing the recipe's advertised behavior. None of the three would be obvious from reading the code top-to-bottom; they require hand-tracing the demo turns against the protocol, the state machine, the acuity-pattern matcher, and the screener tool. Each of the three is an ERROR-level finding because the load-bearing scenario the recipe spends pages on (Marisol's chest tightness with paternal-cardiac history triggering a `same_day_callback` acuity flag and producing a delivered pre-visit packet with PHQ-2 score band) does not produce that behavior in the published demo. Per the persona's pass/fail rules, even one ERROR is automatic FAIL. The good news is that the architectural skeleton is sound, the boto3 surface is correct, the Decimal discipline is consistent, the S3 paths are properly formed, and the validated-screener wordings are preserved verbatim. The fixes are self-contained.

---

## ERROR Findings

### E1. The acuity-pattern matcher reads only string-typed fields from each finding, so `tags=["early", "before_60"]` (the only place those keywords actually appear) is invisible to the matcher; the demo's headline cardiac acuity flag never fires

**File / section:** `chapter11.04-python-example.md`, "Step 5: Crisis-and-Acuity Flagging in Parallel," function `_pattern_matches`:

```python
def _pattern_matches(pattern, findings):
    triggers = pattern.get("triggers", {})
    if not triggers:
        return False
    for finding_id, keywords in triggers.items():
        finding = findings.get(finding_id)
        if not finding:
            return False
        text = (
            finding.get("text", "")
            + " "
            + " ".join(
                str(v) for v in finding.values()
                if isinstance(v, str))
        ).lower()
        if not any(kw in text for kw in keywords):
            return False
    return True
```

And the family-history finding produced by `history_extraction_tool` for the canonical Marisol input "my dad had a heart attack at 51":

```python
finding = {
    "type":         "history_finding",
    "dimension":    history_dimension,
    "text":         text,
    "summary":      summary,
    "tags":         tags,           # <-- list, not str
    "captured_at":  _now_iso(),
}
```

with the tag-extraction logic:

```python
if history_dimension == "family_cardiac":
    for match in re.finditer(r"\b(\d{2})\b", text):
        age = int(match.group(1))
        if age < 60:
            tags.append("early")
            tags.append(f"age_{age}")
            tags.append("before_60")
            break
```

And the cardiac acuity pattern's triggers:

```python
"exertional_chest_pain_with_family_history": {
    ...
    "triggers": {
        "hpi_quality":         ["pressure", "tightness",
                                "squeezing", "heaviness"],
        "hpi_provocation":     ["exertion", "stairs",
                                "rushing", "walking"],
        "history_family_cardiac": ["early", "before_60"],
    },
},
```

**What's wrong:**

The `_pattern_matches` text-construction filter `if isinstance(v, str)` excludes the `tags` field (which is a Python list). The keywords `"early"` and `"before_60"` only appear inside `tags`; they do not appear inside the patient's verbatim `text` ("my dad had a heart attack at 51"). The summary echoes the verbatim text. So the joined text the matcher walks looks roughly like:

```
"my dad had a heart attack at 51 history_finding family_cardiac
my dad had a heart attack at 51 my dad had a heart attack at 51
2026-05-24T...:00:00+00:00"
```

Neither `"early"` nor `"before_60"` is anywhere in that string. The matcher returns False on the `history_family_cardiac` trigger and bails before checking the other two triggers, so the cardiac red-flag pattern never fires.

I traced this end-to-end against the demo's `happy_path_followup_with_acuity` scenario:

1. Turn 5 captures `hpi_quality` with text "more like pressure on my chest, kind of heavy" — would match keyword `"pressure"`.
2. Turn 4 captures `hpi_provocation` with text "mostly when I walk up stairs to my apartment, sometimes when I'm rushing around" — would match keywords `"stairs"`, `"rushing"`, `"walking"`.
3. Turn 10 captures `history_family_cardiac` with text "my dad had a heart attack at 51" and `tags=["early", "age_51", "before_60"]`.
4. After turn 10, `_crisis_and_acuity_flagging` runs `_acuity_pattern_detection` against the accumulated findings. The cardiac pattern's triggers are checked one by one. `history_family_cardiac`'s text is searched for `"early"` and `"before_60"`. Neither appears in the string-only joined text. The check fails. The pattern does not match.
5. `session.acuity_flags` stays empty.
6. The closing summary picks `CLOSING_SUMMARY_TEMPLATE` (the no-acuity branch), not `CLOSING_WITH_ACUITY_TEMPLATE`. The patient does not receive the "Because of what you described, I'm flagging this for the clinical team" language.
7. The packet's `acuity_flags` list is empty. `clinical_staff_routing_tool` is never invoked. No same-day-callback ticket is queued.
8. The audit record's `acuity_flags_raised` is 0 and `acuity_flag_summary` is empty.

The recipe's sample audit record explicitly shows the cardiac flag firing for the canonical Marisol scenario:

```json
"acuity_flag_summary": [
  {
    "category": "cardiac_red_flag",
    "severity": "high",
    "routing_target": "same_day_callback",
    "pattern_id":
      "exertional_chest_pain_with_family_history",
    "raised_at": "2026-05-18T12:39:07Z"
  }
],
```

The demo does not produce this. The headline "this is the bot's value-delivery moment" output the recipe centers on never happens.

This is the load-bearing acuity primitive of the entire chapter: the recipe's prose says "When the bot detects, somewhere in turn nine, a constellation of features that warrant a higher-acuity flag, it does not tell Marisol that she might be having cardiac symptoms... It quietly flags the encounter for a same-day call from a triage nurse." A reader running the published demo gets the opposite outcome: the bot finishes intake, never flags the encounter, and the patient walks away thinking everything is fine until Wednesday.

**How to fix:**

Either include list-typed values in the joined search text, or check tags as a separate axis. The minimal fix is to expand the joined-text construction to flatten list elements:

```python
text_parts = [finding.get("text", "")]
for v in finding.values():
    if isinstance(v, str):
        text_parts.append(v)
    elif isinstance(v, list):
        text_parts.extend(str(x) for x in v if isinstance(x, str))
text = " ".join(text_parts).lower()
if not any(kw in text for kw in keywords):
    return False
```

A more robust fix is to extend the trigger schema so each pattern can declare which finding fields to check (e.g., trigger against `tags` for history findings, against `text` for HPI findings) rather than relying on a flatten-everything string match. The recipe's prose calls out that "production stores this as a versioned artifact with named clinical-leadership ownership" and the schema explicitness is part of that governance.

Either fix produces the expected demo output. After the fix, hand-tracing the headline scenario:

- After turn 10 captures `history_family_cardiac` with `tags=["early", "age_51", "before_60"]`, `_pattern_matches` finds `"early"` in the joined text → all three trigger keys match → the cardiac pattern fires.
- A flag-event is persisted with `pattern_id="exertional_chest_pain_with_family_history"`, `severity="high"`, `routing_target="same_day_callback"`.
- `session.acuity_flags` accumulates the flag.
- The closing template switches to `CLOSING_WITH_ACUITY_TEMPLATE`.
- `clinical_staff_routing_tool` is invoked at packet-deliver time with the same-day-callback target.
- The audit record's `acuity_flags_raised` is 1 and the cardiac category appears in the summary.

Until this is fixed, no demo scenario in the file exercises the acuity-pattern path. The other ERROR findings below mean the demo cannot complete intake to even reach packet assembly, so this finding compounds with E2 and E3.

---

### E2. The protocol's `screener_phq2` entry is a single state-machine question, but PHQ-2 is a two-item screener; `screener_administer_tool_capture_item` defaults to the first item when `item_id` is missing, so only PHQ-2 q1 is ever asked, and the demo's second "not at all" answer is captured as the closing-confirmation answer

**File / section:** `chapter11.04-python-example.md`, "Configuration and Constants," `PROTOCOL_LIBRARY` and `SCREENER_LIBRARY`:

```python
PROTOCOL_LIBRARY = {
    "primary_care_followup": {
        ...
        "question_flow": [
            ...
            {"id": "screener_phq2", "category": "screener",
             "screener_id": "PHQ-2"},
            {"id": "closing_confirmation", "category": "closing"},
        ],
        ...
    },
}

SCREENER_LIBRARY = {
    "PHQ-2": {
        "version":  "v1.0",
        "items": [
            {"id": "phq2_q1", "text": "...little interest...", ...},
            {"id": "phq2_q2", "text": "...feeling down...", ...},
        ],
        ...
    },
}
```

And `screener_administer_tool_capture_item`:

```python
if item_id:
    item = next((i for i in items if i.get("id") == item_id), None)
else:
    # When no item_id is provided, default to the first
    # item. Production tracks per-screener item progress
    # explicitly; the demo administers one item per turn.
    item = items[0]
```

**What's wrong:**

The protocol's question-flow entry for PHQ-2 has no `item_id`. When the state machine reaches it, `_capture_answer_for_question` calls `screener_administer_tool_capture_item(screener_id="PHQ-2", item_id=None, ...)`. The function defaults to `items[0]` (phq2_q1). `_phrase_question_conversationally` does the same defaulting via `_format_screener_item(screener["items"][0])`. So only phq2_q1 is asked, only phq2_q1 is captured, and the state machine advances past the screener entry to the next protocol position (closing_confirmation).

The demo's `happy_path_followup_with_acuity` scenario has TWO consecutive "not at all" user messages after med- and allergy-reconciliation, clearly intended as PHQ-2 q1 and PHQ-2 q2 responses. The actual flow:

- Turn 13 ("not at all") captures phq2_q1 with response_value=0; state advances to position 12 (closing_confirmation).
- Turn 14 ("not at all") is captured as the closing-confirmation answer, with the finding `{free_concern_text: "not at all", captured_at: ...}`. The "free concern" interpretation of "not at all" is nonsense.

Worse, neither item ever becomes part of `session.screener_records` (see W1 below), so the score never gets computed via `_compute_screener_score` (which is defined but never called), and the audit record's `screener_records_summary` is empty:

```python
"screener_records_summary": [
    {"screener_id": r.get("screener_id"),
     "screener_version": r.get("screener_version"),
     "score": r.get("score"),
     "score_band": r.get("band")}
    for r in session.get("screener_records", [])
],
```

The recipe's main-text sample audit record shows:

```json
"screener_records_summary": [
  {
    "screener_id": "PHQ-2",
    "screener_version": "v1.0",
    "score": 0,
    "score_band": "negative"
  }
],
```

The demo never produces this. The "Sample conversation (illustrative)" walkthrough in the recipe also implies the bot administers a brief PHQ-2 (a two-item screener), which the demo cannot do as written.

This breaks the load-bearing screener-administration primitive the recipe sells:

> Validated-screener administration as a discrete tool. PHQ-9, GAD-7, AUDIT-C, PROMIS instruments, fall-risk screeners, social-determinants screeners are each their own validated tool with specific item wordings, response options, and scoring rules. The bot's screener tool encapsulates each one. The bot does not paraphrase the items; it administers the validated wordings and captures the responses. The scoring is deterministic and produces a clinical-record event.

The demo's scoring is never deterministic because it is never computed. The audit record never produces the score.

**How to fix:**

Two options.

Option A (lower-touch, matches the recipe's "one item per turn" framing): expand the protocol's question-flow at design time so each screener item is its own entry. For PHQ-2:

```python
{"id": "phq2_q1", "category": "screener",
 "screener_id": "PHQ-2", "item_id": "phq2_q1"},
{"id": "phq2_q2", "category": "screener",
 "screener_id": "PHQ-2", "item_id": "phq2_q2"},
```

After all items for a screener are captured, an additional state-machine action computes the score and appends a `screener_record` to the session. This is cleaner architecturally because the state machine remains "one question per turn" and the screener registry can declare its items independently.

Option B (higher-touch, but matches the recipe's "screener as a single tool that administers a bundle" framing): treat the screener entry as a sub-flow that the orchestration loop runs as a nested state. The state machine, when it encounters a screener entry, transitions to a `screener_admin` substate that walks the items one per turn before resuming the parent flow. `_compute_screener_score` is called at substate-exit time and the result is appended to `session.screener_records`.

Either fix produces the expected demo output. After the fix, hand-tracing the headline scenario:

- The PHQ-2 questions are administered one at a time across two turns.
- Both response values are captured as `screener_item_response` findings.
- `_compute_screener_score("PHQ-2", [{response_value: 0}, {response_value: 0}])` returns `{score: 0, band: "negative"}`.
- A `screener_record` is appended to `session.screener_records`.
- The packet's `screeners` field has the PHQ-2 record. The closing summary's "PHQ-2 score: 0 (negative)" line appears.
- The audit record's `screener_records_summary` matches the recipe's sample.

The screener-library entry for PHQ-9 has a similar latent issue: it lists only item 9 (the crisis-sensitive one) and not items 1-8. The demo never administers PHQ-9 (the protocol does not include it), so this does not surface, but a future protocol that includes PHQ-9 would have the same single-item pickup problem unless one of the two fix options above is in place. Worth noting in the same fix pass.

---

### E3. Branch questions are appended to the END of the question flow, after `closing_confirmation`, rather than inserted at the right protocol position; the demo's chest-symptoms branch asks `hpi_severity` and `hpi_alleviating_factors` AFTER the bot has already wrapped up the conversation with the closing question

**File / section:** `chapter11.04-python-example.md`, "Step 3: Drive the Conversation Through the Question-Flow State Machine," function `_question_flow_state_machine`:

```python
def _question_flow_state_machine(session):
    protocol = session.get("active_protocol") or {}
    flow = list(protocol.get("question_flow", []))
    captured = session.get("captured_findings", {})
    position = int(session.get("protocol_position", 0))

    branches = protocol.get("branches", {})
    branch_questions = _resolve_branch_questions(
        branches=branches, captured=captured)

    full_flow = flow + branch_questions

    if position >= len(full_flow):
        return {"action": "complete"}

    return {
        "action":            "ask_question",
        "question":          full_flow[position],
        "protocol_position": position + 1,
        "total_questions":   len(full_flow),
    }
```

**What's wrong:**

`full_flow = flow + branch_questions` puts every branch question at the tail of the flow. The base `primary_care_followup` flow has 13 entries with `closing_confirmation` at index 12. The chest-symptoms branch contributes `hpi_severity` and `hpi_alleviating_factors` at indices 13 and 14. So when the chest-symptoms branch fires (which it does for "chest tightness for 3 weeks getting more frequent" because the chief complaint contains both "chest" and "tightness"), the resulting conversational arc is:

- Position 11: PHQ-2 screener
- Position 12: closing_confirmation ("Thanks for going through all that. Does anything I missed feel important to mention before we wrap up?")
- Position 13: hpi_severity ("On a scale from 1 to 10, with 10 being the worst, how bad does it get?")
- Position 14: hpi_alleviating_factors ("Is there anything that helps it stop or feel better?")

The bot wraps up, then asks two more HPI questions about the chest tightness, then wraps up again. This is conversationally incoherent and contradicts the recipe's prose:

> Open: patient mentions chest pain in primary-care annual; cardiac-symptoms branch opens
> Close: patient denies the symptom in question; the negative-finding is captured and the branch closes without follow-ups
> Diverge: patient brings up an unrelated significant concern; the bot acknowledges, captures the concern, and weaves back to the protocol

The recipe's design says the branch opens at the right place in the flow (when the chief complaint is captured) and the branch's HPI questions are interleaved into the HPI section, not appended to the end.

The bug also breaks the demo's message-count expectation. The base flow has 13 questions; if branches are added, the demo provides 15 user messages, expecting one capture per turn after the initial "ready" greeting. Counting:

- 1 message ("ready") asks chief_complaint.
- 14 capture-and-advance turns cover positions 0-13 (capturing chief_complaint through hpi_severity).
- Position 14 (hpi_alleviating_factors) is asked but never answered because the demo runs out of messages.
- The state machine never reaches `action="complete"`, so `_assemble_and_deliver_packet` is never called.
- `session.completion_status` stays at `"in_progress"` and `session.packet_id` is None.

The published demo's `run_demo()` then calls `close_conversation_and_archive` with the scenario's hardcoded `close_reason="intake_completed"`, but the audit record's `intake_completion_status` reads from the session field, which is still `"in_progress"`. The demo's printed output:

```python
print(f"  -> completion_status: {audit['intake_completion_status']}")
print(f"  -> acuity_flags_raised: {audit['acuity_flags_raised']}")
```

prints `completion_status: in_progress` and `acuity_flags_raised: 0` (the latter compounding with E1). No packet is delivered to the EHR. No closing summary is shown. `intake_completed` events are not emitted. The recipe's headline outcome ("Dr. Adekunle has the structured pre-visit packet she needs before Wednesday") never happens in the published demo.

**How to fix:**

Two options.

Option A (matches the recipe's "interleave branch into the HPI section" framing): the protocol's branch definitions declare an `insert_after` field (or an `insert_before` field) referencing a base-flow question id. `_question_flow_state_machine` builds `full_flow` by inserting each triggered branch's questions at the declared position rather than appending them. For example:

```python
"branches": {
    "chest_symptoms": {
        "trigger_keywords":
            ["chest", "tightness", "pressure"],
        "insert_after": "hpi_associated",
        "additional_questions": [
            {"id": "hpi_severity", "category": "hpi",
             "dimension": "severity"},
            {"id": "hpi_alleviating_factors",
             "category": "hpi",
             "dimension": "alleviating"},
        ],
    },
},
```

This is the cleanest fix because branch questions belong in the HPI section, alongside the other HPI questions.

Option B (lower-touch but coarser): pre-resolve the full flow once at protocol-selection time (Step 2) by walking the chief-complaint capture, deciding which branches will fire, and storing the resolved flow on the session. This decouples the runtime state machine from re-resolving branches every turn. The branches still need an `insert_after` declaration to land at the right position; this option just moves the resolution from per-turn to once-at-start.

Either fix produces the expected demo output. After the fix, hand-tracing the headline scenario with Option A's `insert_after: "hpi_associated"`:

- Position 0-5: chief_complaint, hpi_onset, hpi_provocation, hpi_quality, hpi_radiation, hpi_associated (base HPI).
- Position 6-7: hpi_severity, hpi_alleviating_factors (branch HPI inserted after hpi_associated).
- Position 8-14: hpi_timing, ros_cardiopulmonary, history_family_cardiac, med_reconciliation, allergy_reconciliation, screener_phq2 (or two screener entries per E2's fix), closing_confirmation.

That's 15 base-plus-branch positions covered by the demo's 14 capture turns plus 1 greeting turn — the demo completes the flow and assembles the packet.

The branch-position issue and E2 are linked: E2's option-A fix expands the screener entry into two question-flow entries, which adds another position to the flow. Combined with E3's fix, the demo's message count needs to accommodate the actual full flow. Quick reckoning: 13 base + 2 branch + 1 extra screener = 16 positions, requiring 16 capture turns + 1 greeting = 17 user messages. The demo currently has 15. After both fixes, the demo author would need to add two more user messages (one for the second PHQ-2 item and one to close out the longer flow). That is a small adjustment but worth flagging so the author does not inadvertently truncate the scenario again.

---

## WARNING Findings

### W1. `session.screener_records` is initialized to `[]` in `_get_or_resume_session` but never appended to anywhere in the orchestration; `_compute_screener_score` is defined but never called; the packet's `screeners` field is always empty and the closing summary never includes the screener score line

**File / section:** `chapter11.04-python-example.md`, "Step 1," `_get_or_resume_session` (initialization), "Step 7," `screener_administer_tool_capture_item` (capture), `_compute_screener_score` (defined but unused), "Step 8," `_assemble_and_deliver_packet` (reads from session), and `_build_closing_summary` (iterates the empty list).

```python
new_session = {
    ...
    "screener_records": [],
    ...
}
```

```python
def _compute_screener_score(screener_id, item_responses):
    """Compute the score for a completed screener."""
    ...
```

```python
def _assemble_and_deliver_packet(session_id, ...):
    ...
    packet = packet_assemble_tool(
        ...
        screener_records=session.get("screener_records", []),
        ...)
```

```python
def _build_closing_summary(captured_findings,
                              screener_records,
                              acuity_flags):
    ...
    for record in screener_records:
        lines.append(
            f"- {record.get('screener_id')} score: ...")
```

**What's wrong:**

The screener-administration plumbing has three disconnected pieces: the per-item capture (returns a `screener_item_response` finding via `_capture_answer_for_question`), the score computation (`_compute_screener_score`), and the per-screener record accumulation (`session.screener_records`). The demo wires the first; the second and third are not wired. The captured items land in `session.captured_findings` keyed by question id (e.g., `"screener_phq2"` → the item finding) but never get aggregated into a screener_record, never get scored, and never get propagated to the packet or the closing summary.

This is a separate bug from E2 (E2 means only item 1 is ever captured) but they compound. Even after E2 is fixed and both PHQ-2 items get captured, this gap means the resulting `screener_records` is still empty because nothing aggregates the items, calls the scorer, and appends.

The recipe's main-text walks through the expected wiring explicitly:

> Step 7: Administer Screeners with Validated Wordings...
> Step 7D: compute the score per the validated scoring rules.
> ```
> screener_record.score = screener.compute_score(items: screener_record.items)
> screener_record.score_band = screener.classify_band(score: screener_record.score)
> ```
> Step 7E: persist as a clinical-record event.
> ```
> session.screener_records.add(screener_record)
> ```

The Python's `_compute_screener_score` corresponds exactly to the pseudocode's `screener.compute_score`/`classify_band`, but no call site invokes it. The recipe's "Step 7E" is missing entirely from the Python.

The downstream consequences:

- The closing summary's screener-score line ("- PHQ-2 score: 0 (negative)") never appears for any patient.
- The packet's `screeners` field is always empty.
- The audit record's `screener_records_summary` is always empty.
- The recipe's per-cohort monitoring discipline ("screener positivity rates per screener" as a launch-gate metric) cannot be measured because no record carries the score.
- The PHQ-2-positive → PHQ-9-administration follow-up logic (the recipe's "positive_action: administer_phq9" in the screener library) cannot fire because the score that would trigger it is never computed.

**How to fix:**

Wire `_compute_screener_score` and the `screener_records` accumulation. Two natural touch points:

1. After the last item of a screener is captured, the orchestration loop in `_conduct_intake_turn` calls a new helper `_finalize_screener_if_complete(session_id, screener_id)`. The helper gathers all `screener_item_response` findings whose `screener_id` matches, calls `_compute_screener_score`, builds a `screener_record`, and appends it to `session.screener_records`. The trigger for "last item of a screener" naturally falls out of E2's option-A fix (the protocol declares each item as its own state-machine question, and the orchestration knows when it has just left the last item).

2. Add a `screener_finalize` question category that runs after the last item-question for a screener and calls `_compute_screener_score` directly. The state machine knows to inject a finalize step after each screener bundle.

Either way, the resulting `screener_record` looks like:

```python
{
    "screener_id":      screener_id,
    "screener_version": screener["version"],
    "language":         session["language"],
    "items": [
        {"item_id": "phq2_q1", "response_value": 0,
         "response_text": "not at all"},
        {"item_id": "phq2_q2", "response_value": 0,
         "response_text": "not at all"},
    ],
    "score":            0,
    "band":             "negative",
    "administered_at":  _now_iso(),
}
```

Until this is fixed, the validated-screener-administration discipline the recipe sells is structurally absent from the demo: the demo captures items but never scores them.

---

### W2. `_persist_partial_state` is called BEFORE `_update_session_field` updates `protocol_position`, so the persisted partial state has the OLD protocol position; on resume, the bot re-asks the question that was just answered

**File / section:** `chapter11.04-python-example.md`, "Step 3: Drive the Conversation Through the Question-Flow State Machine," function `_conduct_intake_turn`:

```python
# Step 3B: ask the state machine for the next question.
next_step = _question_flow_state_machine(session=session)

# Persist partial state for resume.
_persist_partial_state(_session_state(session_id))

if next_step.get("action") == "complete":
    return _assemble_and_deliver_packet(...)

# Step 3C: phrase the next question conversationally.
next_question = next_step["question"]
_update_session_field(
    session_id, "in_flight_question", next_question)
_update_session_field(
    session_id, "protocol_position",
    next_step["protocol_position"])
```

**What's wrong:**

The order is:

1. Capture the answer (Step 3A) — `session.captured_findings` is updated via `_add_captured_finding`.
2. Compute next_step from the state machine (Step 3B) — does NOT mutate session state.
3. `_persist_partial_state(_session_state(session_id))` — reads the current session and persists. At this point `session.protocol_position` still holds the position of the question that was just answered, NOT the next question.
4. `_update_session_field("protocol_position", next_step["protocol_position"])` — only now does the session row reflect the advance.

The persisted partial state has updated `captured_findings` (good) but stale `protocol_position` (bad). On resume:

- `_load_partial_state` returns `protocol_position` pointing at the question that was just answered.
- `_get_or_resume_session` restores it onto the new session row.
- `session.in_flight_question` is None (not persisted at all in `_persist_partial_state`).
- Patient's first message after resume goes through `_conduct_intake_turn`.
- `in_flight_question` is None → the capture branch is skipped.
- `_question_flow_state_machine` is called with the stale `protocol_position`. It returns `full_flow[stale_position]`, which is the question already answered.
- The bot asks the question again. The patient's previous answer is in `captured_findings` but the bot does not see that and re-asks.

In the canonical "Marisol resumes after lunch" workflow, this means the bot asks her chest-tightness chief-complaint question a second time after she comes back. Mildly annoying for a one-question rewind; substantially worse if she had captured ten HPI turns before the resume — she has to re-answer all ten because the resume only restores the position of the most recently answered question, then advances from there.

Actually, rethinking: only the MOST RECENT question gets re-asked, because `captured_findings` IS persisted. So the patient re-answers one question, the new answer overwrites the old one in `captured_findings`, and the flow advances from there. Not a catastrophic data-loss bug, but a real conversational-coherence bug.

Compare this with the recipe's resume narrative:

> Resume is graceful: the bot greets, summarizes what has been captured, asks if the patient wants to continue or restart, and proceeds.

The "summarizes what has been captured" implies the bot knows where the patient left off. With the stale position, the resumed bot asks the just-answered question rather than the next one, which contradicts "graceful."

**How to fix:**

Reorder: update `protocol_position` (and `in_flight_question`) on the session row BEFORE persisting partial state. The simplest reordering:

```python
# Step 3B: ask the state machine for the next question.
next_step = _question_flow_state_machine(session=session)

if next_step.get("action") == "complete":
    return _assemble_and_deliver_packet(...)

next_question = next_step["question"]
_update_session_field(
    session_id, "in_flight_question", next_question)
_update_session_field(
    session_id, "protocol_position",
    next_step["protocol_position"])

# Persist partial state for resume AFTER advancing.
_persist_partial_state(_session_state(session_id))
```

Also persist `in_flight_question` in the partial-state record so the resume path can short-circuit on the next message (the resumed bot can either re-ask the in-flight question conversationally or simply trust that the state machine will return it again at the same position). Currently `_persist_partial_state` does not include `in_flight_question` at all:

```python
def _persist_partial_state(session):
    ...
    table.put_item(Item=_to_decimal({
        "encounter_id":      encounter_id,
        "patient_id":        patient_id,
        "session_id":        session["session_id"],
        "protocol_position": session.get(
            "protocol_position", 0),
        "captured_findings": session.get(
            "captured_findings", {}),
        "screener_records":  session.get(
            "screener_records", []),
        "active_protocol":   session.get("active_protocol"),
        "encounter_context": session.get(
            "encounter_context"),
        "chart_context":     session.get("chart_context"),
        "context_loaded":    session.get(
            "context_loaded", False),
        ...
    }))
```

Add `"in_flight_question": session.get("in_flight_question")` so resume can pick up exactly where the patient left off.

---

### W3. Several assistant-turn paths bypass `_screen_output` entirely; the conversation log captures the unscreened text and the audit pipeline never sees that the static template was the actual delivered text vs an LLM-replaced one

**File / section:** `chapter11.04-python-example.md`, multiple call sites:

- `_handle_unauthenticated` — `_append_turn(speaker="assistant", text=PORTAL_LOGIN_REQUIRED_TEMPLATE, ...)` then `_build_chat_reply`. No screen.
- `_handle_screening_action` for `injection_refusal` and `phi_redirect` — `_append_turn(...)` with the template. No screen.
- `_route_crisis` — `_append_turn(..., text=template, ...)`. No screen.
- `_handle_intake_message` for the `intake_paused` branch — `_build_chat_reply(response_text=...)` with no `_append_turn` AND no screen.
- `_conduct_intake_turn` for the `ask_clarifying` branch — `_build_chat_reply(response_text=CLARIFY_EXTRACTION_TEMPLATE, ...)` with no `_append_turn` and no screen.

The screened paths are only:
- `_conduct_intake_turn` for the `asked_next_question` branch — `response_text = _phrase_question_conversationally(...)`, then `_screen_output`, then `_append_turn`. Correctly screened.
- `_assemble_and_deliver_packet` — closing summary built via `_build_closing_summary`, then `_screen_output`, then `_append_turn`. Correctly screened.

**What's wrong:**

Same shape as 11.02 W4 / 11.03 W3, but with a different concrete impact. The static-template paths in 11.04 are clinical-leadership-reviewed templates (per the recipe's prose), so they do not need to be screened for clinical-advice or chart-fact violations. That part is fine.

The bug that does manifest is the audit gap on the `ask_clarifying` and `intake_paused` branches: those paths return `_build_chat_reply` without ever calling `_append_turn`, so the assistant's clarification/paused-acknowledgment message is never persisted to `conversation_metadata`. The conversation log becomes asymmetric — user messages are appended but the bot's responses to them are not. The audit record's `turn_count` undercounts the bot's actual messages, the cohort-stratified metrics are computed against an incomplete log, and a reviewer pulling up the conversation in the QA queue sees the user asking something with no response shown, even though one was delivered.

I traced this against an extension of the demo's headline scenario where the patient gives an unparseable HPI answer (e.g., "uhh"). `hpi_extraction_tool` returns `{"action": "ask_clarification", ...}` (it actually doesn't currently — see N1 below — but if it did): `_conduct_intake_turn` returns:

```python
return _build_chat_reply(
    session_id=session_id,
    response_text=CLARIFY_EXTRACTION_TEMPLATE,
    attach_greeting=attach_initial_greeting,
    attach_resume=attach_resume_greeting,
    disposition="clarification_requested")
```

No `_append_turn(speaker="assistant", text=CLARIFY_EXTRACTION_TEMPLATE, ...)`. The user's "uhh" is logged. The bot's "I want to make sure I have that right..." is not. On the next turn, the user's reply is logged. The audit reads as if the bot vanished for one turn.

The recipe's audit-pipeline narrative explicitly says:

> User utterances ... Generated bot responses

The narrative implies symmetric logging. The current implementation breaks symmetry on at least two paths.

**How to fix:**

Two structural fixes:

1. Centralize assistant-turn writes through a single helper that handles append + screen + reply, similar to 11.02/11.03's recommended pattern but adapted to 11.04's mix of static-template and LLM-generated paths:

```python
def _append_assistant_turn_and_reply(
        session_id, channel, response_text,
        attach_greeting, attach_resume, disposition,
        language, screen=True, **turn_extras):
    final_text = response_text
    if screen:
        screened = _screen_output(
            session_id=session_id,
            response_text=response_text)
        if screened["action"] == "replace_with_safe_response":
            final_text = screened["response_text"]
            disposition = "output_replaced"
    _append_turn(session_id, {
        "speaker":   "assistant",
        "text":      final_text,
        "timestamp": _now_iso(),
        "language":  language,
        **turn_extras,
    })
    return _build_chat_reply(
        session_id=session_id,
        response_text=final_text,
        attach_greeting=attach_greeting,
        attach_resume=attach_resume,
        disposition=disposition)
```

Static-template paths set `screen=False`. LLM-generated paths set `screen=True`. Every assistant turn lands in the audit log either way.

2. Replace the `ask_clarifying`, `intake_paused`, and similar early-return `_build_chat_reply` calls with the new helper.

The `_handle_unauthenticated`, `_handle_screening_action` injection/phi paths, and `_route_crisis` already call `_append_turn` correctly, so they only need a minor refactor to use the helper for consistency.

---

## NOTE Findings

### N1. The per-category extraction tools never return `ask_clarification` for ambiguous answers; the only branch that triggers clarification is "empty answer text"

`hpi_extraction_tool`, `ros_extraction_tool`, `medication_reconciliation_capture_tool`, `allergy_reconciliation_capture_tool`, `history_extraction_tool` all share the same shape:

```python
text = (answer_text or "").strip()
if not text:
    return {"action": "ask_clarification", "finding": None}
finding = {...}
return {"action": "captured", "finding": finding}
```

The only condition that returns clarification is an empty string. Every non-empty answer is captured, regardless of how nonsensical or incomplete. A patient who types "uhh" or "I don't know" or "what?" gets captured as a valid HPI/history/medication finding. The downstream packet has the noise as a structured finding.

The recipe's main-text emphasizes that the extraction tool "validates against the schema. If the answer is unparseable, the tool returns 'ask_clarification' and the conversation loop asks a follow-up." The demo's tools never do this. The `EXTRACTION_CONFIDENCE_THRESHOLD = Decimal("0.70")` constant in the configuration is never compared against any confidence score because no extraction tool produces one.

Fix: each extraction tool should produce a confidence score (production via the LLM; demo via simple heuristics) and return `ask_clarification` when the score is below `EXTRACTION_CONFIDENCE_THRESHOLD`. Even a few simple heuristics would make the demo more honest:

```python
# HPI: too short to be informative
if len(text.split()) < 3:
    return {"action": "ask_clarification", "finding": None}
# History family-cardiac: doesn't mention any relevant terms
if history_dimension == "family_cardiac" and \
   not any(t in lowered for t in
       ["heart", "cardiac", "stroke", "blood pressure",
        "diabetes", "no", "none", "don't know"]):
    return {"action": "ask_clarification", "finding": None}
```

The current behavior teaches a misleading pattern. A learner reading the code might assume "captured" means "high-confidence" and propagate that assumption.

### N2. `screener_administer_tool_capture_item` defaults to `items[0]` when `item_id` is None, but the function does not warn or log; the silent default is the mechanism behind E2

```python
if item_id:
    item = next(
        (i for i in items if i.get("id") == item_id),
        None)
else:
    # When no item_id is provided, default to the first
    # item. Production tracks per-screener item progress
    # explicitly; the demo administers one item per turn.
    item = items[0]
```

The comment correctly identifies that production tracks item progress explicitly. The demo's silent fallback to `items[0]` is the mechanism by which E2 manifests: the protocol declares no `item_id`, the function silently picks the first one, and the screener never advances past item 1.

A teaching version of this function should at minimum log a warning when `item_id` is missing, or refuse to default at all and require the caller to supply the item id. The recipe is teaching the validated-screener-as-discrete-tool discipline, and the demo's silent default undermines that teaching.

Fix: add a `logger.warning("screener %s called without item_id; defaulting to %s", screener_id, items[0]["id"])` line, or make the function require `item_id` and surface the missing-id issue at call time. Combined with E2's protocol fix (declaring each item as its own question-flow entry), the silent default would never fire.

### N3. The `MockTable.update_item` regex only handles a single-attribute `SET <name> = <val>` expression; multi-attribute updates and `ADD`/`REMOVE` syntax silently no-op (carry-forward from 11.01 N5 / 11.02 N5 / 11.03 N3)

```python
match = re.match(
    r"\s*SET\s+(\S+)\s*=\s*(\S+)\s*$",
    UpdateExpression)
if match:
    name_token, val_token = match.groups()
    ...
```

Same shape as the prior reviews. The mock silently ignores any UpdateExpression that doesn't match the single-SET regex. A reader extending the demo to do `SET #la = :ts ADD #mc :one` (the natural fix for the read-modify-write race in `_get_or_resume_session`'s message_count bump, which is the same race documented in 11.03 N2 and carries forward into 11.04 unchanged) sees no error and no state change.

The 11.04 demo's session-flag updates happen to all be single-attribute SETs, so the limitation is invisible. But the mock is teaching DynamoDB patterns and the silent no-op is the wrong teaching. Same fix recommendation as the prior reviews: at minimum log a warning when the regex does not match; better, parse the expression's action-token list (SET, ADD, REMOVE) and apply each piece in turn.

### N4. The chart-fact integrity check in `_screen_output` only catches "I see you're (taking|listed as allergic to)" phrasing, not "I see these medications on your record:" or "Your record shows allergies to..." which are the actual phrasings the demo's `_phrase_from_template` produces

`_extract_chart_fact_references` and `_ref_supported_by_chart` are the demo's defense against the bot hallucinating a medication or allergy that is not on the chart. The regex:

```python
pattern = re.compile(
    r"i see you'?re (?:taking|listed as allergic to) "
    r"([a-z][a-z0-9\- ]+)",
    re.IGNORECASE)
```

matches phrasings like "I see you're taking sertraline 50mg" or "I see you're listed as allergic to penicillin." But the demo's medication-reconciliation phrasing in `_phrase_from_template` is:

```python
return (
    f"I see these medications on your record:"
    f"\n{listing}\nIs that still right? "
    ...)
```

and the allergy-reconciliation phrasing is:

```python
return (
    f"Your record shows allergies to "
    f"{listing}. Is that still accurate, ...")
```

Neither matches the regex. So the chart-fact integrity check never fires on the demo's actual output. The check is dead code in this demo.

In production, the LLM-generated phrasings would vary substantially and the regex would catch some cases but miss others. The recipe's main-text says the production check uses "Comprehend Medical's clinical-entity extraction with RxNorm coding for higher precision," which is the right approach. The demo's regex is a backstop that does not cover the demo's own templates.

Fix: either expand the regex to cover the actual demo phrasings ("I see (?:these medications|the following medications|you take|you're on|your record shows)", "Your record shows allergies to"), or note in the docstring that production uses Comprehend Medical and the demo's regex is illustrative only. A learner reading the current code might assume the regex covers all chart-fact references; it covers none of the demo's actual ones.

---

## Validation Notes

- The boto3 API surface used by the companion (`bedrock-runtime.invoke_model`, `bedrock-agent-runtime` client constructor, `dynamodb.Table().put_item`/`get_item`/`update_item`/`query`/`delete_item`, `events.put_events`, `firehose.put_record`, `cloudwatch.put_metric_data`, `s3.put_object`, `secretsmanager` client constructor, `comprehendmedical` client constructor) is correct against current SDK conventions. No method-name typos, no parameter-name drift.
- The `Decimal`-not-`float` discipline is consistent at every DynamoDB write boundary. `EXTRACTION_CONFIDENCE_THRESHOLD = Decimal("0.70")` is correctly typed at definition. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` correctly does not wrap value in Decimal. `_to_decimal` recursively converts at every put_item path.
- S3 keys in `_write_packet_journal` have no leading slashes; the path structure `f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['event_id']}.json"` is correctly formed.
- The validated-screener wordings in `SCREENER_LIBRARY` for PHQ-2 and PHQ-9 item 9 match the validated instrument wordings exactly (this is the recipe-distinct safety-acute correctness property and it is correctly preserved).
- The crisis-response template selection by category is structurally correct: `_route_crisis` picks `CRISIS_SUICIDAL_TEMPLATE` for `suicidal_ideation`, `CRISIS_DV_TEMPLATE` for `intimate_partner_violence_disclosure`, `CRISIS_MEDICAL_EMERGENCY_TEMPLATE` for `acute_medical_emergency_description`, and `CRISIS_RESPONSE_GENERIC_TEMPLATE` as fallback.
- The packet-journal record carries the version stamps the recipe's "audit-record-version-stamping" discipline requires (`schema_version`, `protocol_version`, `screener_bundle_version`, `ehr_delivery_record_id`, `acuity_flag_count`, `crisis_flag_count`).
- The deploy-time guardrail asserting non-empty resource-name constants survives the carry-forward from 11.1-11.3.
- The PARTIAL_STATE_TTL_SECONDS = 60*60*72 (72 hours) is reasonable for the demo; the recipe correctly notes that production tunes per visit type.
- `REQUIRE_AUTHENTICATED_FOR_INTAKE = True` short-circuits unauthenticated patients to `PORTAL_LOGIN_REQUIRED_TEMPLATE` before any tool call runs, eliding the unauthenticated-identifier-collection bug that 11.01-11.03 carried (the year-of-DOB regex is not in this file at all, which is the correct outcome for an authenticated-only intake bot).
- The `_emit_event`, `_put_metric`, and `_audit_tool_call` helpers all wrap their AWS calls in try/except and never block the chat-handler response on a transient EventBridge/CloudWatch/DynamoDB hiccup.

---

## Recommended Changes Before Re-Review

1. **Fix the acuity-pattern matcher to read list-typed fields (`tags`).** Either flatten list elements into the joined search text, or extend the trigger schema so each pattern declares which finding fields to check. After the fix, re-run the `happy_path_followup_with_acuity` scenario and confirm `acuity_flags_raised: 1` with the cardiac category, severity high, routing target `same_day_callback`, and the closing message switching to `CLOSING_WITH_ACUITY_TEMPLATE`. (E1)
2. **Fix the screener-administration to walk all items.** Either expand the protocol's `screener_phq2` entry into per-item entries (`phq2_q1`, `phq2_q2`) plus a finalize step, or implement a substate for the screener bundle. Wire `_compute_screener_score` so `session.screener_records` carries the scored record by the time `_assemble_and_deliver_packet` runs. (E2 + W1)
3. **Fix the branch question insertion to land at the right protocol position.** Add an `insert_after` field to the branch definition and update `_question_flow_state_machine` to insert branch questions at the declared position rather than appending them. After the fix, the demo author needs to verify the `happy_path_followup_with_acuity` scenario has enough user messages to cover the full branch-expanded flow; expect to add one or two more messages depending on E2's fix shape. (E3)
4. **Reorder `_persist_partial_state` to be called AFTER `protocol_position` is updated**, and include `in_flight_question` in the persisted partial state so resume picks up exactly where the patient left off. (W2)
5. **Centralize assistant-turn writes through a single helper** that handles append + (optional) screen + reply, so the `ask_clarifying` and `intake_paused` branches no longer skip the audit log. (W3)

The four NOTE-level items are not blocking; they are quality-of-life improvements for future maintenance. The three ERROR-level fixes plus the three WARNING-level fixes are the ones to land before the next review pass.

The architectural skeleton is sound, the boto3 surface is correct, the Decimal-not-float discipline is consistent, the S3 paths are properly formed, the validated-screener wordings are preserved verbatim, the crisis-response template selection is correct, and the version-stamping discipline is in place. The findings concentrate on (a) three independent bugs that each break the headline `happy_path_followup_with_acuity` scenario the recipe centers on, and (b) three carry-forward shape issues from the prior 11.x reviews. Re-running the review after the recommended changes should be quick.
