# Code Review: Recipe 11.1 — FAQ Chatbot (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter11.01-python-example.md`
- `chapter11.01-faq-chatbot.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 7 |

The Python companion is a long, well-structured walkthrough of the eight pseudocode steps from the main recipe (session bootstrap with greeting and disclosure, parallel input screening with crisis detection / prompt-injection / PHI minimization, scope classification with low-confidence clarification and per-category handoff templates, hybrid retrieval against a Bedrock Knowledge Base with a relevance threshold, grounded generation with citation discipline and explicit no-information handling, output screening with backstop scope filter and token-overlap grounding check, delivery-and-logging with EventBridge events and CloudWatch metrics, and conversation-close audit archival via Firehose). The demo exercises six scenarios (in-scope parking, in-scope Aetna, crisis-detected chest pain, out-of-scope clinical question, out-of-scope refill request, prompt-injection attempt) and runs end-to-end through the mocks without raising exceptions.

**Validation performed:**
- Walked the eight pseudocode steps against the Python functions: Step 1 `receive_message` → `receive_message`; Step 2 `screen_input` → `screen_input` + `_handle_screening_action`; Step 3 `classify_scope` → `classify_scope` (called from `_handle_in_scope_message`); Step 4 `retrieve_chunks` → `retrieve_chunks`; Step 5 `generate_grounded_response` → `generate_grounded_response`; Step 6 `screen_output` → `screen_output`; Step 7 `deliver_and_log` → `_retrieve_generate_screen_deliver`; Step 8 `close_conversation_and_archive` → `close_conversation_and_archive`.
- Verified service-name strings on the boto3 clients: `bedrock-runtime`, `bedrock-agent-runtime`, `dynamodb` (resource), `events`, `firehose`, `cloudwatch`, `secretsmanager` are all correct identifiers.
- Verified the `Decimal`-not-`float` discipline at every DynamoDB write boundary. The `_to_decimal` helper recursively converts floats to `Decimal` and is invoked at every put_item/update_item path: `_get_or_create_session` (the new_session and bumped-message-count writes), `_append_turn`, `_update_session_flag`, and the per-turn audit_stamp wrap in `_retrieve_generate_screen_deliver`. The `_from_decimal` inverse is invoked when reading state. Decimal-typed thresholds (`SCOPE_CONFIDENCE_THRESHOLD`, `RETRIEVAL_RELEVANCE_THRESHOLD`, `MIN_CLAIM_OVERLAP`) are constructed via `Decimal("...")` at definition. No float-vs-Decimal comparison footguns in the comparison paths.
- Verified S3 paths have no leading slashes. The Knowledge Base source-document URIs in the mock fixtures (`s3://kb/parking-2026-03.txt`, `s3://kb/insurance-2026-02.txt`) are properly formed. The chunk_id format `f"{uri}#{chunk_idx}"` uses `#` as a separator, not a leading slash. No S3 keys are constructed with leading slashes.
- Verified the deploy-time guardrail asserts every resource-name constant is non-empty (the `for _name, _value in [...]: assert _value` block at module load). Note that placeholder strings like `"KB_PLACEHOLDER_ID"` are truthy and therefore pass the assertion; the assertion catches "blank string" but not "wasn't replaced." That is documented as intentional.
- Verified the screening-before-classification discipline: `screen_input` runs crisis detection first (and preempts everything else when triggered), then injection detection, then PHI detection. `_handle_in_scope_message` is only entered if the screening action is `"proceed"`, so a crisis utterance never reaches the scope classifier or the Knowledge Base.
- Verified the scope-confidence gate: `confidence < SCOPE_CONFIDENCE_THRESHOLD` routes to `"clarify"` rather than acting on a low-confidence classification. The classifier-failure exception path also routes to `"clarify"`, so a transient Bedrock failure on the classifier short-circuits to a safe clarifying question rather than skipping straight to retrieval.
- Verified the retrieval relevance threshold: `score < RETRIEVAL_RELEVANCE_THRESHOLD` is dropped, and an empty post-filter result list returns `no_relevant_results: True`. The generation step's no-results branch then returns `NO_INFORMATION_TEMPLATE` rather than letting the model attempt to answer from training-data memory.
- Verified the grounding-check fallback: when `cited_chunk_ids` is empty but the model claims to have answered (no_information=False, answered=True), `_check_grounding` returns `has_unsupported_claims=True` (because cited_texts is empty) and the screen replaces the response with `NO_INFORMATION_TEMPLATE`. This is the correct conservative behavior.
- Verified the Bedrock invoke_model body shape: the Anthropic Messages API request (`anthropic_version: "bedrock-2023-05-31"`, `max_tokens`, `temperature`, `system`, `messages: [{role, content}]`) is correct and matches current Bedrock conventions for Claude. The `guardrailIdentifier` and `guardrailVersion` parameters on `invoke_model` are real boto3 parameters. The response parse `payload = json.loads(response["body"].read())` followed by `payload["content"][0]["text"]` matches the real StreamingBody shape; the mock's `_wrap_text` helper returns a stand-in `_Body` class with a `read()` method that emits bytes, so the demo's parse path exercises the same code that production would use.
- Verified `bedrock-agent-runtime.retrieve`: the `knowledgeBaseId`, `retrievalQuery: {text: ...}`, and `retrievalConfiguration: {vectorSearchConfiguration: {numberOfResults, overrideSearchType, filter}}` shape is correct. The filter expression with `andAll: [{equals: {key, value}}, ...]` matches the Bedrock Knowledge Bases retrieve API filter shape. The response parsing (`retrievalResults[i].content.text`, `score`, `location.s3Location.uri`, `metadata`) matches the real response shape.
- Verified the EventBridge `put_events(Entries=[{Source, DetailType, Detail, EventBusName}])` shape is correct.
- Verified the Firehose `put_record(DeliveryStreamName=..., Record={"Data": <bytes>})` shape is correct.
- Hand-traced the six demo scenarios:
  - **in_scope_parking**: classify → `parking_and_transportation` (conf 0.94 ≥ 0.65), retrieve → 1 chunk above 0.45 threshold, generate → cites the parking chunk_id, screen_output passes, deliver "We don't validate parking..." with `(Source: Visitor Parking Guide)`. ✓
  - **in_scope_aetna**: classify → `accepted_insurance_general` (conf 0.91 ≥ 0.65), retrieve → 1 chunk above threshold, generate → cites the insurance chunk_id, deliver. ✓
  - **crisis_detected_chest_pain**: input screening matches `"chest pain"` in CRISIS_LEXICON, preempts classification and retrieval, emits CRISIS_RESPONSES["medical_emergency"], emits `crisis_detected` event and metric. ✓
  - **out_of_scope_clinical**: classify → `clinical_question` (conf 0.95), routes to `OUT_OF_SCOPE_HANDOFFS["clinical_question"]` with target=nurse_triage. ✓
  - **out_of_scope_refill**: classify → `refill_request` (conf 0.92), routes to refill handoff template. ✓
  - **prompt_injection_attempt**: input screening matches the `r"ignore (all |any |the )?(previous|prior|above) (instructions|messages|prompts)"` regex, returns INJECTION_REFUSAL_TEMPLATE before scope classification. ✓
- Verified the citation rendering: `_render_with_citations` adds `(Source: Visitor Parking Guide)` to the response by looking up cited chunk_ids in the retrieved_chunks and pulling their `source_title` metadata. The chunk_id stays in the audit record but the user-facing rendering uses the human-readable title.

The walkthrough is structurally faithful to the architecture diagram and the eight pseudocode steps. The recipe gets the load-bearing pieces right: the screening pipeline preempts classification, the scope filter is layered (system prompt + Bedrock Guardrails attachment + post-generation backstop check), the retrieval relevance threshold gates the generation step's no-information path, the citation discipline maps response claims back to chunk_ids in the audit stamp, and every turn carries the active model/prompt/KB/Guardrail/scope-rules/crisis-lexicon versions in its audit record (assuming the persistence layer worked, which is where W1 below comes in).

That said, the companion ships with two WARNING-level findings: a session-state lookup-key mismatch that produces materially broken audit records on conversation close, and a set of session-level counters (scope_violation_count, hallucination_count, handoffs_offered, handoffs_accepted, feedback_history) that are initialized in the new_session row but never updated by any code path, so the persisted audit record always shows 0 for the metrics that the recipe's "Why This Isn't Production-Ready" section explicitly emphasizes. Two WARNINGs is under the FAIL-on-three-WARNINGs threshold, so the verdict is PASS, but both should be addressed before the recipe ships because they undermine the audit-everything discipline the recipe is teaching.

The seven NOTE-level findings cover smaller items: the user message is duplicated in both the scope-classifier and generation prompts (because `_recent_turns` runs after `_append_turn`); the `MockTable.query` extracts the partition-key value via a private boto3 condition attribute; the `_check_response_scope` keyword backstop is incomplete and easily evadable; the disposition strings emitted from chat replies (`continued`, `no_information_offered`, `clarification_requested`, `handoff_offered`) don't reconcile with the four `final_disposition` branches in the audit record (`contained`, `crisis_routed`, `escalated`, `abandoned`, `other`); the example audit record in the main recipe shows a `cohort_axes.region_hint` field that the Python's `close_conversation_and_archive` doesn't populate; the `_redact_pii_for_logging` regex for DOB matches common appointment-date phrasings ("on 03/15/2026"); and the `_flag_turn_for_redaction` is a no-op stub that logs but doesn't actually flag the turn for downstream redaction.

---

## ERROR Findings

None. The demo runs end-to-end through the mocks without raising exceptions; every documented scenario produces a chat reply, an EventBridge event, a Firehose audit record, and CloudWatch metrics.

---

## WARNING Findings

### W1. `_update_session_flag` and `close_conversation_and_archive` look up the session row at `f"_id#{session_id}"`, but the session was created at `f"{channel}#{channel_session_id}"`; the result is orphaned crisis flags and an audit record missing channel, language, started_at, duration, and all version stamps

**Files / sections:**
- `_get_or_create_session` (the create path, line ~630):
  ```python
  session_key = f"{channel}#{channel_session_id}"
  ...
  new_session = {
      "session_key":    session_key,
      "session_id":     str(uuid.uuid4()),
      ...
  }
  table.put_item(Item=_to_decimal(new_session))
  ```
- `_update_session_flag` (line ~952):
  ```python
  table.update_item(
      Key={"session_key": f"_id#{session_id}"},
      UpdateExpression="SET #f = :v",
      ...)
  ```
- `close_conversation_and_archive` (line ~1922):
  ```python
  state_response = state_table.get_item(
      Key={"session_key": f"_id#{session_id}"})
  state = _from_decimal(state_response.get("Item", {}))
  ```
- The mock `MockTable.update_item` creates a brand-new row from the supplied `Key` when the key is not found:
  ```python
  existing = self.items.get(key, dict(Key))
  ...
  self.items[key] = existing
  ```

**What's wrong:**

The session row is created with `session_key = f"{channel}#{channel_session_id}"` (e.g., `"web_chat#demo-session-0003"`), but every read and update path against the conversation-state table uses `session_key = f"_id#{session_id}"` (where `session_id` is the UUID assigned at session creation). These are two different partition-key values; they never collide.

The consequences fall in two places:

**1. Crisis flags (and any other state mutation via `_update_session_flag`) are written into orphaned rows, not into the actual session.**

For the `crisis_detected_chest_pain` scenario, `_handle_screening_action` calls `_update_session_flag(session_id, "crisis_detected", True)` (and twice more for `crisis_severity` and `crisis_category`). Each call invokes `MockTable.update_item` with `Key={"session_key": f"_id#{session_id}"}`. The mock's update_item logic:

```python
existing = self.items.get(key, dict(Key))   # creates dict from Key if not found
match = re.match(r"\s*SET\s+(\S+)\s*=\s*(\S+)\s*$", UpdateExpression)
if match:
    name_token, val_token = match.groups()
    attr = (ExpressionAttributeNames or {}).get(name_token, name_token)
    value = (ExpressionAttributeValues or {}).get(val_token)
    existing[attr] = value
self.items[key] = existing
```

creates a brand-new row at `_id#<UUID>` containing `{session_key: "_id#<UUID>", crisis_detected: True}`, then overwrites it with each subsequent flag. The original session row at `web_chat#demo-session-0003` is never touched and never sees the crisis flag.

**2. The audit record built at conversation close reads from the orphaned row, not the session row, so most of the audit fields are `None`.**

In `run_demo`:
```python
session = dynamodb.Table(CONVERSATION_STATE_TABLE).get_item(
    Key={"session_key": f"{scenario['channel']}#{scenario['session_id']}"})
if session.get("Item"):
    sid = session["Item"]["session_id"]
    close_conversation_and_archive(session_id=sid, reason=...)
```

The demo correctly looks up the original session row, extracts the UUID, and passes it to `close_conversation_and_archive`. But inside that function, the lookup is against `_id#<UUID>` — which retrieves the orphan row (for crisis scenarios) or nothing at all (for non-crisis scenarios). Hand-traced for each scenario:

| Scenario | What `state_response.get("Item")` returns | What's in the audit_record |
|---|---|---|
| `in_scope_parking` (no crisis, no flags written) | `{}` | channel=None, language=None, started_at=now() fallback, duration_seconds=0, all version stamps None, `crisis_detected=False`, `scope_violation_count=0`, `final_disposition="contained"` (because reason==user_session_end and crisis_detected=False) |
| `in_scope_aetna` | `{}` | Same as above. |
| `crisis_detected_chest_pain` | `{session_key: "_id#<UUID>", crisis_detected: True, crisis_severity: "high", crisis_category: "medical_emergency"}` | channel=None, language=None, started_at=now() fallback, but `crisis_detected=True`, so `final_disposition="crisis_routed"`. |
| `out_of_scope_clinical` (close_reason="user_requested_agent") | `{}` | All fields None or 0, `handoffs_accepted=0` (W2 issue), so `final_disposition="other"` instead of `"escalated"`. |
| `out_of_scope_refill` (close_reason="user_requested_agent") | `{}` | Same as above. |
| `prompt_injection_attempt` (close_reason="user_session_end") | `{}` | `final_disposition="contained"` (because no crisis, no scope_violation_count, reason==user_session_end). |

So every audit record is missing the channel, language, started_at, duration_seconds, and all the version stamps (model_id, prompt_version, kb_id, guardrail_id, guardrail_version, scope_rules_version, crisis_lexicon_version) that the recipe's Step 8 audit-record example explicitly shows. The cohort_axes block reads from `state.get("language")` and `state.get("channel")`, both of which are None. The duration_seconds is 0 because `started_at` falls back to `_now_iso()` and `ended_at` is the same `_now_iso()` call.

The recipe's main text and the example audit JSON in the "Expected Results" section both emphasize that the active model and prompt versions are stamped on every conversation's audit record:

> Stamp the active knowledge-base version on each conversation. When content changes, the older version is preserved for a defined retention window. Patient-reported issues from a prior conversation can be reproduced against the actual corpus state at that time.

The Python companion claims to do this — the `audit_stamp` is constructed and stamped on each turn — but the conversation-level versions never make it into the persisted audit record because the session row is never read. A learner who runs the demo and inspects the Firehose mock's output will see audit records that look nothing like the example in the main recipe.

The author was clearly aware of the schema issue: `_update_session_flag` carries the comment

```python
# In a real schema the partition key is session_key, not
# session_id; this helper assumes a GSI or equivalent
# lookup-by-session-id. The demo keeps it simple.
```

and `close_conversation_and_archive` carries an analogous comment. But the code does not "keep it simple" — it fabricates a separate, orphaned key namespace (`_id#<session_id>`) that no other code path writes to or reads from consistently. The comments imply a GSI is going to make this work; in practice the demo creates a parallel set of rows that share nothing with the session.

**How to fix:**

The cleanest fix is to maintain a session-id-to-session-key index inside the demo (a small dict on the `MockDynamoDBResource`, or a simple two-step lookup in both `_update_session_flag` and `close_conversation_and_archive`). Add a helper:

```python
def _resolve_session_key(session_id: str) -> Optional[str]:
    """
    Look up the session_key for a given session_id. In production
    this is a GSI on session_id; in the demo we scan the in-memory
    state table to keep the surface small.
    """
    table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    # MockDynamoDBResource exposes the underlying dict for the demo;
    # production would issue a Query against a GSI.
    for item in getattr(
            table, "items", {}).values():
        if item.get("session_id") == session_id:
            return item["session_key"]
    return None
```

Then update both `_update_session_flag` and `close_conversation_and_archive` to resolve the key first:

```python
session_key = _resolve_session_key(session_id)
if not session_key:
    logger.warning("No session row for %s", session_id)
    return
table.update_item(
    Key={"session_key": session_key},
    UpdateExpression="SET #f = :v",
    ...)
```

Or, alternatively, rework the demo's Step 1 to thread the `session_key` (not just the `session_id`) through every downstream call so both reads and writes go to the same row. The first option is less invasive and more closely matches the production GSI pattern.

After the fix, hand-trace each scenario and confirm the audit record's `active_versions` block reads:

```json
"active_versions": {
  "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
  "prompt_version": "faq-bot-prompt-v3.2",
  "kb_id": "KB_PLACEHOLDER_ID",
  "guardrail_id": "GUARDRAIL_PLACEHOLDER_ID",
  "guardrail_version": "1",
  "scope_rules_version": "faq-bot-scope-v1.4",
  "crisis_lexicon_version": "faq-bot-crisis-lexicon-v1.5"
}
```

rather than seven None values.

**Severity rationale:** WARNING because the demo runs end-to-end without raising exceptions and produces output, but the audit record — which the recipe emphasizes as the central operational artifact — is materially broken in a way a learner copying this pattern into their own demo won't immediately see. The persona checklist allows up to three WARNINGs before flipping to FAIL; this is one of two.

---

### W2. Session-level counters (`scope_violation_count`, `hallucination_count`, `handoffs_offered`, `handoffs_accepted`, `feedback_history`) are initialized in the new_session row but never updated by any code path; the persisted audit record always shows 0 for the metrics the recipe's Step 8 disposition logic depends on

**Files / sections:**
- `_get_or_create_session` (line ~664):
  ```python
  new_session = {
      ...
      "crisis_detected":     False,
      "crisis_severity":     None,
      "scope_violation_count": 0,
      "hallucination_count": 0,
      "handoffs_offered":    0,
      "handoffs_accepted":   0,
      "feedback_history":    [],
  }
  ```
- `screen_output` emits a `_put_metric("OutputScopeViolation", 1, ...)` when violations are detected but does not call `_update_session_flag` to bump `scope_violation_count`.
- `screen_output` emits `_put_metric("HallucinationCaught", 1, {})` but does not bump `hallucination_count`.
- `_handle_in_scope_message` emits `_put_metric("HandoffOffered", 1, ...)` and `_emit_event("handoff_offered", ...)` but does not bump `handoffs_offered`.
- No code path bumps `handoffs_accepted` (the recipe's pseudocode anticipates the user clicking "yes" on the handoff offer; the demo doesn't simulate that interaction).
- No code path appends to `feedback_history` (the recipe's pseudocode anticipates per-turn thumbs-up/thumbs-down feedback; the demo sends a `FOLLOWUP_AFFORDANCE_TEMPLATE` but doesn't process the reply).
- `close_conversation_and_archive` (line ~1971):
  ```python
  "scope_violation_count": int(state.get("scope_violation_count", 0)),
  "hallucination_count":   int(state.get("hallucination_count", 0)),
  "handoffs_offered":      int(state.get("handoffs_offered", 0)),
  "handoffs_accepted":     int(state.get("handoffs_accepted", 0)),
  "feedback_history":      state.get("feedback_history", []),
  ```
- `final_disposition` logic depends on these counters:
  ```python
  final_disposition = (
      "contained"
          if reason == "user_session_end"
              and audit_record["scope_violation_count"] == 0
              and not audit_record["crisis_detected"]
      else "crisis_routed"
          if audit_record["crisis_detected"]
      else "escalated"
          if audit_record["handoffs_accepted"] > 0
      ...
  )
  ```

**What's wrong:**

The session-level counters are initialized to zero in `_get_or_create_session` and are read by `close_conversation_and_archive` to compute `final_disposition`. But no code path between session creation and conversation close ever increments them. The CloudWatch metrics (`OutputScopeViolation`, `HallucinationCaught`, `HandoffOffered`) are emitted independently and never join up with the session-level state.

The consequences for `final_disposition`:

| Scenario | Expected disposition | Actual disposition |
|---|---|---|
| out_of_scope_clinical (reason="user_requested_agent") | `escalated` (handoff offered) | `other` (handoffs_accepted=0) |
| out_of_scope_refill (reason="user_requested_agent") | `escalated` | `other` |
| Any scenario where output screening replaces the response with a refusal | `escalated` or at least flagged | `contained` (scope_violation_count=0) |

For the recipe's "Per-cohort accuracy and containment monitoring" discipline to be meaningful, the counters have to actually count. The demo's containment-rate dashboards (which the recipe describes as the per-launch-gate quality bar) would show every scenario as "contained" because the disposition logic falls through to the catch-all branch.

This is independent of W1: even if the session lookup is fixed, the counters are still 0 because nothing increments them. Both fixes are needed to produce a meaningful audit pipeline.

**How to fix:**

Add per-counter `_update_session_flag`-equivalent calls at the right hooks (after the lookup-key fix from W1 lands, so the writes target the actual session row):

- In `screen_output`, when scope violation is detected:
  ```python
  if violations:
      _put_metric("OutputScopeViolation", 1, {"first_category": violations[0]})
      _increment_session_counter(session_id, "scope_violation_count")
      ...
  ```
- In `screen_output`, when hallucination is caught:
  ```python
  if grounding["has_unsupported_claims"]:
      _put_metric("HallucinationCaught", 1, {})
      _increment_session_counter(session_id, "hallucination_count")
      ...
  ```
- In `_handle_in_scope_message`, when an out-of-scope handoff template is delivered:
  ```python
  _put_metric("HandoffOffered", 1, {...})
  _emit_event("handoff_offered", {...})
  _increment_session_counter(session_id, "handoffs_offered")
  ```
- For `handoffs_accepted` and `feedback_history`: add a `record_user_feedback(session_id, payload)` entry point that the demo's `run_demo` calls after the handoff response, simulating the user's reply. The `final_disposition` logic depends on this for the `escalated` branch.

A small helper:

```python
def _increment_session_counter(session_id: str, counter_name: str) -> None:
    session_key = _resolve_session_key(session_id)  # from W1's fix
    if not session_key:
        return
    table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    table.update_item(
        Key={"session_key": session_key},
        UpdateExpression="ADD #c :one",
        ExpressionAttributeNames={"#c": counter_name},
        ExpressionAttributeValues={":one": Decimal("1")})
```

After the fixes, the audit record produced for the `out_of_scope_clinical` scenario should show `handoffs_offered: 1`, `handoffs_accepted: 0` or `1` depending on whether the demo simulates the accept, and `final_disposition: "escalated"` rather than `"other"`.

**Severity rationale:** WARNING because the demo runs and produces output, but the audit record's counters and the derived `final_disposition` are materially wrong in a way that undermines the recipe's central operational discipline (per-cohort containment-rate monitoring). Combined with W1 the recipe's audit pipeline is broken end-to-end, but neither rises to ERROR because no exception is thrown.

---

## NOTE Findings

### N1. The user message is duplicated in both the scope classifier prompt and the generation prompt because `_recent_turns` is invoked after `_append_turn`

**Files / sections:**
- `receive_message` (Step 1C):
  ```python
  _append_turn(
      session_id=session_id,
      turn={"speaker": "user", "text": user_message, ...})
  ```
- `classify_scope` (line ~1107):
  ```python
  recent = _recent_turns(session_id, k=4)
  history_text = "\n".join(
      f"{t['speaker']}: {t['text']}" for t in recent)
  ...
  classification_user = (
      f"RECENT CONVERSATION:\n{history_text}\n\n"
      f"NEW USER MESSAGE: {user_message}")
  ```
- `generate_grounded_response` (line ~1444):
  ```python
  recent = _recent_turns(session_id, k=4)
  history_text = "\n".join(
      f"{t['speaker']}: {t['text']}"
      for t in recent
      if t.get("speaker") in ("user", "assistant"))
  ...
  user_prompt = (
      f"RECENT CONVERSATION:\n{history_text}\n\n"
      f"USER'S CURRENT QUESTION:\n{user_message}\n\n"
      ...)
  ```

**What's wrong:**

Step 1C appends the user's current turn to the metadata table before any downstream step runs. Then Step 3 (`classify_scope`) and Step 5 (`generate_grounded_response`) both call `_recent_turns(session_id, k=4)`, which queries the metadata table and retrieves the most recent turns including the just-appended one. The resulting `history_text` already includes the current user message at the bottom; then the prompt template appends `NEW USER MESSAGE: {user_message}` (or `USER'S CURRENT QUESTION:`), so the model sees the same message twice.

Concrete example for the parking scenario (turn 1 of a fresh session):

```
RECENT CONVERSATION:
user: do you validate parking?

NEW USER MESSAGE: do you validate parking?
```

For multi-turn conversations the duplication is less obvious but still present (the most recent user turn appears as the last line of `history_text` and then again as `NEW USER MESSAGE`). This biases the model toward over-weighting the most recent message and inflates token usage by roughly the message length.

**How to fix:**

Either (a) call `_append_turn` after the screening + classification + retrieval + generation pipeline finishes, so the user turn is appended along with the assistant turn at the end of `_retrieve_generate_screen_deliver`; or (b) filter the current message out of `_recent_turns` results, e.g. by passing the current user message as an `exclude_text` parameter; or (c) filter the latest user turn out of `history_text` in both `classify_scope` and `generate_grounded_response`:

```python
recent = _recent_turns(session_id, k=4)
# Drop the current user message; the prompt template adds it back
# explicitly under "NEW USER MESSAGE".
if recent and recent[-1].get("speaker") == "user":
    recent = recent[:-1]
history_text = "\n".join(...)
```

Option (a) is structurally cleaner; option (c) is the smallest change.

---

### N2. `MockTable.query` extracts the partition-key value via `list(KeyConditionExpression._values)[0]`, relying on a private boto3 attribute

**Files / sections:**
- `MockTable.query` (line ~2120ish):
  ```python
  def query(self, KeyConditionExpression, ScanIndexForward=True,
            Limit=None):
      sid = list(KeyConditionExpression._values)[0]
      ...
  ```
- The real call site uses `boto3.dynamodb.conditions.Key("session_id").eq(session_id)` which produces a `boto3.dynamodb.conditions.Equals` instance.

**What's wrong:**

The demo extracts the partition-key value by accessing the private `_values` attribute on the Condition object. This works against current boto3 (the `Condition` base class stores its arguments in `_values`), but the underscore prefix signals that the attribute is implementation-detail and may change without notice.

A learner copying this mock pattern into their own demo may build dependencies on `_values` that break when boto3 changes its internal Condition representation. The mock's purpose is to demonstrate the demo flow, not the boto3 internals.

**How to fix:**

Either (a) document the divergence explicitly:
```python
def query(self, KeyConditionExpression, ScanIndexForward=True, Limit=None):
    # The demo unpacks the boto3 Condition object via its private
    # _values attribute purely so the mock can answer queries
    # without implementing the full condition-expression visitor.
    # Real DynamoDB serializes the condition; production code does
    # not need to crack open _values.
    sid = list(KeyConditionExpression._values)[0]
    ...
```

or (b) replace the mock query interface with a simple `query_by_session_id(session_id, limit=None, reverse=False)` helper that the chat handler uses directly, and call out in the demo wiring section that the production code uses real DynamoDB query expressions while the demo uses the helper for readability. Option (b) is closer to the chapter's "this is a sketchpad" framing.

---

### N3. The disposition strings emitted from chat replies (`continued`, `no_information_offered`, `clarification_requested`, `handoff_offered`) don't reconcile with the four `final_disposition` branches in the audit record (`contained`, `crisis_routed`, `escalated`, `abandoned`, `other`)

**Files / sections:**
- `_build_chat_reply` (called from multiple sites):
  - `disposition: "continued"` (after PHI redirect or injection refusal)
  - `disposition: "crisis_routed"` (after crisis response)
  - `disposition: "clarification_requested"` (low-confidence classifier)
  - `disposition: "handoff_offered"` (out-of-scope category)
  - `disposition: "contained"` (in-scope answered)
  - `disposition: "no_information_offered"` (no relevant chunks)
- `close_conversation_and_archive`:
  ```python
  final_disposition = (
      "contained"   if ...
      else "crisis_routed" if ...
      else "escalated"     if ...
      else "abandoned"     if ...
      else "other"
  )
  ```

**What's wrong:**

The two layers use different string values. The chat-reply layer reports the per-turn disposition in real time (useful for the channel UI to render different colors or icons). The audit-archive layer reports the conversation-level disposition based on close_reason and persistent counters. There is no mapping between them, so:

- A turn that returns `disposition="no_information_offered"` is invisible at the conversation level (gets folded into `contained` if it was the last turn before `user_session_end`).
- A turn that returns `disposition="clarification_requested"` similarly disappears.
- A turn that returns `disposition="handoff_offered"` is supposed to map to `final_disposition="escalated"` if the user accepts, but the counter that drives that branch is never updated (W2).

A learner reading the per-turn disposition strings expects them to flow into the conversation's audit record. They don't. The audit record's `final_disposition` is computed from a different, smaller set.

**How to fix:**

Either (a) align the two vocabularies: rename the chat-reply dispositions to subset the audit dispositions plus a few per-turn-only states (`pending`, `clarifying`); or (b) document the layering explicitly in the demo:

```python
# Chat-reply dispositions describe the per-turn outcome (what the
# UI should render). Conversation-level dispositions
# (final_disposition in the audit record) describe the entire
# session and are computed from persistent counters and
# close_reason. The two vocabularies overlap on "contained" and
# "crisis_routed" but otherwise serve different purposes.
```

Option (a) is more pedagogically clean; option (b) is the smallest change.

---

### N4. The example audit record in the main recipe shows `cohort_axes.region_hint`, but the Python's `close_conversation_and_archive` doesn't populate it

**Files / sections:**
- `chapter11.01-faq-chatbot.md` "Expected Results" sample audit record:
  ```json
  "cohort_axes": {
    "language": "en-US",
    "channel": "web_chat",
    "region_hint": "us-northeast"
  }
  ```
- `close_conversation_and_archive`:
  ```python
  "cohort_axes": {
      "language": state.get("language"),
      "channel":  state.get("channel"),
      # Add region, opt-in language preference, and other
      # cohort axes the institution monitors. Never infer
      # demographic labels for protected classes.
  },
  ```

**What's wrong:**

The recipe's example audit JSON shows three cohort axes; the Python's audit record builds two and leaves a comment about adding the third. A learner who copies the example JSON into a downstream analytics step (Athena schema, QuickSight dashboard) and points it at the demo's Firehose output will see no `region_hint` field and have to debug why.

**How to fix:**

Either (a) drop `region_hint` from the recipe's example audit record, or (b) add it to the session-creation code (with a `region_hint=None` default and a `_get_or_create_session` parameter for optional pass-through) and to the `cohort_axes` block in the audit. Option (b) preserves the recipe's "per-cohort monitoring" discipline as a code pattern.

---

### N5. `_check_response_scope` keyword backstop is incomplete; a model that says "Based on your symptoms, I think you should..." doesn't trigger any of the configured phrases

**Files / sections:**
- `_check_response_scope` (line ~1655):
  ```python
  clinical_phrases = [
      "you should take", "you should not take",
      "you should stop", "stop taking",
      "i recommend you", "in your case",
      "your symptoms suggest", "you probably have",
      "you don't need to come in",
      "you should go to the er",
  ]
  ```

**What's wrong:**

The clinical-phrase list is short and easily evaded. A model output like "Based on your symptoms, I'd recommend you contact your doctor" or "It sounds like you might want to come in" wouldn't match any of the patterns. The financial and legal phrase lists are similarly thin. The function is documented as a "backstop" with the real defenses being the system prompt and Bedrock Guardrails, which is correct, but the demo's keyword list is so short that a learner might mistake the backstop for the primary defense.

**How to fix:**

Add a comment at the function head pointing at the layered defenses:

```python
def _check_response_scope(response_text: str) -> list:
    """
    Backstop keyword scope check on generated output. This function
    catches a small set of obvious phrasings as a final safety net.
    The PRIMARY defenses against scope drift are:
      1. The system prompt's SCOPE RULES (HARD) section.
      2. Bedrock Guardrails restricted-topic filters
         (clinical_advice, financial_advice, legal_advice
          configured at minimum).
      3. The offline scope-drift review program (sampled
         conversation review by clinical operations).
    The keyword list here is intentionally small; production should
    rely on Bedrock Guardrails for runtime enforcement and on the
    review program for ongoing rule updates. This list is what
    catches the model on its way out the door if the prompt and
    the Guardrails both miss.
    """
```

The function's behavior is correct; the documentation gap is what's worth flagging.

---

### N6. The DOB regex in `PHI_PATTERNS` matches common appointment-date phrasings; a patient saying "my appointment is on 03/15/2026" triggers PHI redirect

**Files / sections:**
- `PHI_PATTERNS` (line ~575):
  ```python
  "dob_like": re.compile(
      r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])"
      r"[/-](19|20)\d{2}\b"),
  ```
- `_detect_phi` returns `detected=True` for any pattern match.
- `_handle_screening_action` for `phi_redirect` sends `PHI_REDIRECT_TEMPLATE` and short-circuits the rest of the pipeline.

**What's wrong:**

The regex is labeled `dob_like` but matches any MM/DD/YYYY-shaped date with year 19xx or 20xx. Patients commonly volunteer appointment dates as part of asking about visit prep:

- "I have an appointment on 03/15/2026, what time do you open?" → triggers PHI redirect, never reaches the scope classifier.
- "My visit was on 11/02/2025 and I'm wondering about my parking..." → triggers PHI redirect.

Neither of these is actually PHI in a way that needs redirecting; the dates aren't sensitive on their own. The recipe acknowledges that the heuristic is a starter and that production uses Comprehend Medical, but the demo's scenario set doesn't include a date-bearing utterance, so the false-positive isn't visible without manually crafting one.

**How to fix:**

Either (a) tighten the regex to require a DOB-context cue (`(?:dob|birthday|born|date of birth)` within a small window), or (b) demote `dob_like` from a hard-redirect trigger to a "flag for redaction in audit but don't redirect the conversation" behavior, or (c) add a docstring note that the heuristic over-fires on appointment dates and that production replaces it with Comprehend Medical's `DetectPHI`. Option (c) is the smallest change and matches the recipe's "this is a sketchpad" framing.

---

### N7. `_flag_turn_for_redaction` is a no-op stub; the demo's redaction pipeline silently does not flag the metadata-table turn for downstream redaction

**Files / sections:**
- `_flag_turn_for_redaction` (line ~972):
  ```python
  def _flag_turn_for_redaction(session_id: str, phi_categories: list) -> None:
      logger.info("Turn flagged for redaction; categories=%s", phi_categories)
      # In the real implementation, write a redaction marker into
      # the metadata table for the most recent user turn.
  ```
- `_handle_screening_action` for `phi_redirect` calls `_flag_turn_for_redaction(...)` and then proceeds.
- `_redact_turn_for_audit` (called at conversation close) runs `_redact_pii_for_logging` over every turn's text regardless of whether the turn was flagged.

**What's wrong:**

The runtime flagging is a logger.info; nothing is written to the metadata table. The audit-time redaction (`_redact_turn_for_audit`) runs on every turn's text via `_redact_pii_for_logging`, which strips digit-heavy patterns. So the redaction does happen, but it happens uniformly to every turn, not selectively to the flagged ones.

The behavior is "correct" in the sense that PHI gets redacted, but the discipline the recipe describes (flag at runtime, redact at audit) collapses into "redact everything at audit." A learner expecting per-turn flagging won't find it.

**How to fix:**

Either (a) make `_flag_turn_for_redaction` actually write a marker into the metadata table (a small `requires_redaction: True` flag on the user turn row) and have `_redact_turn_for_audit` honor it; or (b) delete `_flag_turn_for_redaction` entirely and document that the demo redacts uniformly at audit time. Option (a) preserves the per-turn flagging discipline that the recipe describes; option (b) is honest about the simplification.

---

## Persona-Specific Checklist

- **ERROR findings automatically mean FAIL:** 0 ERRORs.
- **More than 3 WARNING findings means FAIL:** 2 WARNINGs (W1 session-key mismatch breaking the audit lookup; W2 session counters never incremented).
- **boto3 API calls are current:** Verified `bedrock-runtime.invoke_model` (with `guardrailIdentifier`/`guardrailVersion`/`trace`), `bedrock-agent-runtime.retrieve` (with `vectorSearchConfiguration` containing `filter`), `dynamodb` resource API (get_item/put_item/update_item/query), `events.put_events`, `firehose.put_record`, `cloudwatch.put_metric_data`, `secretsmanager.get_secret_value` are all valid current SDK surfaces. The Anthropic Messages API request body shape (`anthropic_version: "bedrock-2023-05-31"`, `system`, `messages`, `max_tokens`, `temperature`) and the response parse (`json.loads(response["body"].read())["content"][0]["text"]`) match production conventions for Claude on Bedrock.
- **DynamoDB code uses Decimal, not float:** Verified. The `_to_decimal` helper recursively converts floats to `Decimal` and is invoked at every put_item/update_item path (`_get_or_create_session`, `_append_turn`, `_update_session_flag`, the audit_stamp wrap in `_retrieve_generate_screen_deliver`). The `_from_decimal` inverse is invoked when reading state. Decimal-typed thresholds (`SCOPE_CONFIDENCE_THRESHOLD`, `RETRIEVAL_RELEVANCE_THRESHOLD`, `MIN_CLAIM_OVERLAP`) are constructed via `Decimal("...")`. Confidence values from the model are wrapped via `Decimal(str(parsed.get("confidence", 0)))`. No raw float reaches a state-table write path.
- **S3 paths don't have leading slashes:** Verified. The Knowledge Base source URIs in the mock fixtures (`s3://kb/parking-2026-03.txt`, `s3://kb/insurance-2026-02.txt`) are properly formed. The chunk_id format `f"{uri}#{chunk_idx}"` uses `#` as the separator. No S3 keys are constructed with leading slashes.

**Final verdict: PASS.**

The recipe is structurally faithful to the eight-step pseudocode walkthrough, exercises the screening / classification / retrieval / generation / output-screening / archival pipeline end-to-end, gets the boto3 surface right (especially the Bedrock Knowledge Bases retrieve filter shape and the Anthropic Messages API request body), maintains the Decimal-not-float discipline at every state-table write boundary, and runs the demo to completion across six representative scenarios. The two WARNINGs both concern the conversation-state persistence layer (the orphaned-key bug in W1 and the never-incremented counters in W2), which together break the audit pipeline's data quality even though the demo runs to completion. Both should be addressed before the recipe ships, because the audit-everything discipline is one of the central operational practices the recipe is teaching, and the demo as written produces audit records that don't match the example JSON in the main recipe's "Expected Results" section. None of the seven NOTE-level findings block the demo from running or flip the verdict.

Recipe 11.1 is the first recipe in Chapter 11 and establishes the chapter's operational discipline (RAG over a curated institutional knowledge base, layered scope containment with system-prompt + Guardrails + offline review, crisis-detection-as-a-clinical-safety-document with severity tiers and per-language vocabulary, citation discipline that maps response claims to chunk IDs in the audit stamp, per-cohort-stratified containment metrics, prompt and KB and Guardrail versioning stamped on every audit record). The FAQ-bot-specific behaviors that differentiate it from later chapter-11 recipes (no identity verification because the FAQ bot does not need it, refusal-and-handoff for any patient-specific question rather than identity-elevation, scope filter as a structural property of the system rather than an emergent property of the model, no fulfillment integration so the audit pipeline is purely conversational) are all structurally present.
