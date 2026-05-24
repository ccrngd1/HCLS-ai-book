# Code Review: Recipe 11.2 — Appointment Scheduling Bot (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter11.02-python-example.md`
- `chapter11.02-appointment-scheduling-bot.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** FAIL

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 1 |
| WARNING  | 4 |
| NOTE     | 6 |

The Python companion is a substantial walkthrough of the ten pseudocode steps from the main recipe (session bootstrap with greeting and disclosure plus input safety screening, intent classification with out-of-scope routing, identity verification at graduated assurance levels, slot search with visit-type mapping and clinical-content detection, slot refinement and hold placement, booking confirmation with booking-event-journal write, reschedule and cancel branches with policy step-up checks, booking-failure dispositions, output safety screening with booking-claim verification against the tool-call ledger, and conversation-close audit archival). The structural decomposition tracks the pseudocode well; the tool surface (`patient_lookup_tool`, `slot_search_tool`, `slot_hold_tool`, `slot_book_tool`, `slot_cancel_tool`, `appointment_lookup_tool`) is cleanly separated from the orchestration logic; the `MockSchedulingSystem` exposes the search-then-hold-then-book transactional contract correctly (the hold registers in `self.holds`, the book consumes the hold and removes the slot from inventory, the cancel removes the appointment from the patient's list); the booking-event journal is written to S3 via a key that has no leading slash (`f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['confirmation_id']}.json"`); and the output-screening function actually walks the `tool_call_ledger` for the session and verifies that every confirmation-ID claim in the response text is backed by a successful `slot_book` ledger entry, which is the load-bearing guarantee the main recipe sells.

**Validation performed:**
- Walked the ten pseudocode steps against the Python functions: Step 1 `receive_message` → `receive_message` + `_get_or_create_session` + `_screen_input` + `_handle_screening_action`; Step 2 `classify_scheduling_intent` → `_classify_scheduling_intent` (called from `_handle_in_scope_message`); Step 3 `verify_identity` → inlined into `_route_to_scheduling_flow` plus `_collect_identifiers_from_message` and `_required_assurance_for`; Step 4 `search_for_slots` → `_search_for_slots` plus `_map_reason_to_visit_type`; Step 5 `refine_or_select_slot` → `handle_slot_response` plus `_classify_slot_response` plus `_apply_refinement` plus `_place_hold_and_confirm`; Step 6 `confirm_booking` → `handle_confirmation_response` plus `_classify_confirmation_response` plus `_write_booking_journal`; Step 7 `handle_reschedule_or_cancel` → `_handle_reschedule_or_cancel` plus `_execute_cancel` plus `_execute_reschedule` plus `_check_appointment`; Step 8 `handle_booking_failure` → `_handle_booking_failure`; Step 9 `screen_output` → `screen_output` plus `_extract_booking_claims` plus `_find_supporting_book_call`; Step 10 `close_conversation_and_archive` → `close_conversation_and_archive` plus `_redact_turn_for_audit`.
- Verified service-name strings on the boto3 clients: `bedrock-runtime`, `bedrock-agent-runtime`, `dynamodb` (resource), `events`, `firehose`, `cloudwatch`, `s3`, `secretsmanager` are all correct.
- Verified the `Decimal`-not-`float` discipline at every DynamoDB write boundary. `_to_decimal` recursively converts floats to `Decimal` and is called at every put_item/update_item path: `_get_or_create_session`, `_append_turn`, `_update_session_flag`, `_audit_tool_call`. The Decimal-typed thresholds (`INTENT_CONFIDENCE_THRESHOLD`, `VISIT_TYPE_CONFIDENCE_THRESHOLD`, `ASSURANCE_MATCH_THRESHOLDS`) are constructed via `Decimal("...")` at definition. `_from_decimal` is invoked when reading state. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` correctly does not wrap `value` in Decimal.
- Verified S3 paths have no leading slashes. The booking-event-journal key construction (`f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['confirmation_id']}.json"`) is properly formed.
- Verified the deploy-time guardrail asserts every resource-name constant is non-empty (the `for _name, _value in [...]: assert _value` block at module load). Same pattern as 11.1: the assertion catches "blank string" but not "wasn't replaced," and that is documented as intentional via the placeholder values.
- Verified the screening-before-classification discipline: `_screen_input` runs crisis detection first (and preempts everything else when triggered), then injection detection, then PHI detection. `_handle_in_scope_message` is only entered if the screening action is `"proceed"`.
- Verified the Bedrock invoke_model body shape: the Anthropic Messages API request (`anthropic_version: "bedrock-2023-05-31"`, `max_tokens`, `temperature`, `system`, `messages: [{role, content}]`) is correct. The response parse `payload = json.loads(response["body"].read())` followed by `payload["content"][0]["text"]` matches the real StreamingBody shape.
- Verified the EventBridge `put_events(Entries=[{Source, DetailType, Detail, EventBusName}])` shape is correct.
- Verified the Firehose `put_record(DeliveryStreamName=..., Record={"Data": <bytes>})` shape is correct.
- Verified the S3 `put_object(Bucket=..., Key=..., Body=..., ContentType=..., ServerSideEncryption="aws:kms")` shape is correct.
- Verified the model IDs (`anthropic.claude-3-5-haiku-20241022-v1:0`, `anthropic.claude-3-5-sonnet-20241022-v2:0`) are real Bedrock model IDs in the Anthropic family.
- Verified the booking-claim verification logic: `_extract_booking_claims` extracts confirmation-ID claims via `[A-Z]{2}-\d{4}-\d{3,}` regex (which matches the mock's `f"RC-2026-{...:07d}"` format) plus generic booking claims via keyword search; `_find_supporting_book_call` walks the tool-call ledger looking for `tool == "slot_book"` entries with `outcome == "booked"` whose `result_summary.confirmation_id` matches the claim. This is the correct architectural primitive for the "did the bot hallucinate a booking" check the main recipe demands.
- Hand-traced each demo scenario through the Python flow. Two scenarios surface defects covered in the findings below: the `happy_path_booking` scenario fails at identity verification because the confirmation-factor regex matches the year in the date of birth before the actual phone-last-four (E1 below); the `cancel_appointment` scenario short-circuits assurance to "authenticated" for a same-day cancel because the policy table's first rule wins for any authenticated user (W3 below).
- The other three scenarios (`high_acuity_routed`, `out_of_scope_refill`, `prompt_injection_attempt`) each trace cleanly to their expected disposition: `high_acuity_routed` matches `chest pain` in `HIGH_ACUITY_CUES` during input screening and emits `CRISIS_ROUTE_TEMPLATE`; `out_of_scope_refill` classifies as `refill_request` and emits `OUT_OF_SCOPE_HANDOFFS["refill_request"]` with target=refill_bot; `prompt_injection_attempt` matches the `r"ignore (all |any |the )?(previous|prior|above) (instructions|messages|prompts)"` regex and returns `INJECTION_REFUSAL_TEMPLATE` before classification.

The walkthrough is structurally faithful to the architecture diagram and the ten pseudocode steps. The tool surface, the slot-hold transactional contract, the booking-event journal, the booking-claim verification check, and the per-cohort metric emissions all match the recipe's stated discipline.

That said, the companion has one ERROR-level finding that breaks the headline scenario the recipe sells (Marcus's ninety-second booking conversation), four WARNING-level findings (each one of which is on its own a misleading pattern that a learner would copy into production), and six NOTE-level findings. Per the persona's pass/fail rules, an ERROR is automatic FAIL, and four WARNINGs is over the three-WARNING ceiling, so the verdict is FAIL. The good news is that all the WARNINGs are localized to specific functions and the ERROR is a single regex change; the architectural skeleton is sound and re-running the review after the fixes should be quick.

---

## ERROR Findings

### E1. `_collect_identifiers_from_message` extracts the year of the date of birth as the confirmation factor; identity verification deterministically fails for the recipe's headline conversation

**File / section:** `chapter11.02-python-example.md`, "Step 3: Verify Identity at the Required Assurance Level," function `_collect_identifiers_from_message`:

```python
# Confirmation factor: a 4-digit number not part of a longer
# number sequence (heuristic for last-four-of-phone).
conf_match = re.search(
    r"(?<!\d)(\d{4})(?!\d)", combined)
confirmation = conf_match.group(1) if conf_match else None
```

**What's wrong:**

The regex `(?<!\d)(\d{4})(?!\d)` matches the *first* 4-digit standalone sequence in the combined identifier string. For the canonical happy-path input `"Marcus Chen, 1979-03-14, 7842"` (which the demo's `happy_path_booking` scenario uses verbatim and which the main recipe's "Sample conversation" walkthrough also presents), the engine evaluates positions left-to-right:

- Position 13: `'1'` (start of `"1979"`). Lookbehind `(?<!\d)` passes (preceded by `' '`). The engine consumes `"1979"`. Lookahead `(?!\d)` passes (followed by `'-'`, which is not a digit). **First match: `"1979"`.**
- The match `"7842"` at the end of the string is never reached because `re.search` returns on the first match.

I verified the bug empirically in the actual Python regex engine:

```
>>> import re
>>> re.search(r'(?<!\d)(\d{4})(?!\d)', 'Marcus Chen, 1979-03-14, 7842').group(1)
'1979'
```

The downstream consequence walks all the way through the demo:

1. `_collect_identifiers_from_message` returns `name="Marcus Chen"`, `date_of_birth="1979-03-14"`, `confirmation_factor="1979"`, `complete=True`.
2. `patient_lookup_tool(name="Marcus Chen", date_of_birth="1979-03-14", confirmation_factor="1979")` is called.
3. `MockSchedulingSystem.patient_lookup` keys into `self.patients` with the tuple `("Marcus Chen", "1979-03-14", "1979")`. The fixture key is `("Marcus Chen", "1979-03-14", "7842")`.
4. The lookup misses, returns `{"match_count": 0, "confidence": 0.0}`.
5. `_route_to_scheduling_flow` enters the `match_count == 0` branch and emits the `no_match_text` "I'm not finding a record matching that information…" with disposition `identity_no_match`.
6. The bot offers a handoff to the front desk and the conversation closes with `bookings_completed == 0`.

In other words: the Python companion's headline scenario (the one the main recipe centers an entire narrative arc around) does not actually book Marcus's appointment when the demo runs. A reader running the file as-is sees `disposition: identity_no_match` instead of the expected `disposition: booked` and the bot tells Marcus it cannot find his record. This is the kind of bug that destroys trust in the rest of the companion: the reader assumes the rest of the flow is suspect because the headline path does not work.

**How to fix:**

Use the *last* standalone 4-digit sequence in the combined string, not the first. That naturally skips the year inside the DOB and picks the last-four-of-phone, which is what the bot's prompt actually asked for:

```python
conf_matches = re.findall(r"(?<!\d)(\d{4})(?!\d)", combined)
confirmation = conf_matches[-1] if conf_matches else None
```

A more defensive approach excludes substrings that overlap the already-extracted DOB before searching for the confirmation factor; that handles the "user types 1979 as their actual confirmation factor" edge case correctly. Either fix is fine for the teaching example; the one-line `findall(...)[-1]` is the smaller change and matches the conversational ordering ("name, then DOB, then last-four").

After the fix, hand-tracing the happy_path scenario produces:

- `confirmation_factor = "7842"`
- `MockSchedulingSystem.patient_lookup` keys into `("Marcus Chen", "1979-03-14", "7842")` → fixture match
- `match_count = 1`, `confidence = 0.97`, `patient_id = "patient-internal-1234"`, `first_name = "Marcus"`
- `0.97 >= ASSURANCE_MATCH_THRESHOLDS["basic"] = Decimal("0.85")` → verified
- Continues into `_continue_after_identity` → `_search_for_slots` → returns the two `cardiology_established_followup_30min` slots
- "tuesday" → `handle_slot_response` selects choice index 0 (`slot-2026-05-28-07-30-patel`) → places hold
- "yes" → `handle_confirmation_response` invokes `slot_book_tool` → outcome `"booked"` → confirmation ID `"RC-2026-XXXXXXX"` → `bookings_completed = 1`

Until the regex is fixed, the demo as published does not produce the booked outcome the recipe shows.

---

## WARNING Findings

### W1. The `SLOT_RACE_TEMPLATE` and similar follow-up apologies are appended to the conversation metadata but are never delivered to the user; the user sees only the next response from the re-search

**File / section:** `chapter11.02-python-example.md`, "Step 5: Refine or Select a Slot, Place a Hold," function `_place_hold_and_confirm` (and the same shape in `_handle_booking_failure` for the `slot_no_longer_available` branch):

```python
if hold_result.get("outcome") == "no_longer_available":
    # Slot was taken between search and hold attempt.
    _put_metric("SlotHoldRaceLost", 1, {...})
    _append_turn(session_id, {
        "speaker":   "assistant",
        "text":      SLOT_RACE_TEMPLATE,
        ...
    })
    # Re-search transparently after the apology.
    session = _session_state(session_id)
    return _search_for_slots(
        session_id=session_id,
        ...)
```

**What's wrong:**

The pattern is "append SLOT_RACE_TEMPLATE as an assistant turn in the metadata table, then return the result of `_search_for_slots(...)`." But the chat reply that actually goes back to the user is the return value of `_search_for_slots`, which renders fresh candidates with no mention of the race. The SLOT_RACE_TEMPLATE goes into the audit trail as if it were spoken, but the user never sees the text "Looks like that slot was taken by someone else just now. Let me grab fresh options for you."

Concretely, the user-facing UX in the slot-race case is:

- Patient: *picks slot from the offered list*
- Bot (actually delivered): "I see one opening: …" or "I see a few openings. Which works best?" with the new candidates (rendered by `_search_for_slots`)
- Audit metadata: shows two assistant turns (SLOT_RACE_TEMPLATE, then candidate render), but only the second was delivered to the chat surface

This is misleading on two axes. First, it teaches a learner the wrong pattern: a returned chat reply payload is what the user sees, and any earlier `_append_turn` of an assistant string that was never put into the returned payload is a phantom turn. Second, it desyncs the audit trail from reality: a future operations team reviewing the conversation log will see a "Looks like that slot was taken…" message that the patient never received, and will conclude the bot apologized when it did not. The recipe's prose specifically calls out "graceful 'that slot is no longer available, here are the next options' recovery" as the safety net, but the demo logs the apology and skips it.

The same shape appears in `_handle_booking_failure` for the `slot_no_longer_available` outcome (the SLOT_RACE_TEMPLATE turn is appended; the actual returned payload is from `_search_for_slots`).

**How to fix:**

Combine the apology with the new offer in the user-facing reply text:

```python
if hold_result.get("outcome") == "no_longer_available":
    _put_metric("SlotHoldRaceLost", 1, {...})
    next_step = _search_for_slots(
        session_id=session_id,
        ...)
    combined_text = (
        f"{SLOT_RACE_TEMPLATE}\n\n{next_step['response']}"
    )
    # Replace the standalone SLOT_RACE_TEMPLATE turn with the
    # combined turn (or skip the standalone append and only
    # append the combined turn).
    _append_turn(session_id, {
        "speaker":   "assistant",
        "text":      combined_text,
        ...
    })
    return {
        "session_id":  next_step["session_id"],
        "response":    combined_text,
        "disposition": next_step["disposition"],
    }
```

The cheaper fix: stop appending the SLOT_RACE_TEMPLATE turn, and prepend it to the response text inside `_search_for_slots`'s return when called from this branch. Either way, the user should see the apology and the audit trail should match what was actually delivered.

### W2. The `account_long` PHI pattern (9-16 digit sequences) collides with the bot's own request for full-phone-number identifiers, producing a contradictory loop where the bot asks for a phone number and then refuses to accept it

**File / section:** `chapter11.02-python-example.md`, "Configuration and Constants," `PHI_PATTERNS`:

```python
PHI_PATTERNS = {
    "ssn_like":     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "account_long": re.compile(r"\b\d{9,16}\b"),
    "mrn_prefix":   re.compile(r"\bMRN\s*[:#]?\s*\d{4,}\b",
                                re.IGNORECASE),
}
```

And `_screen_input`:

```python
matched = []
for category, pattern in PHI_PATTERNS.items():
    if pattern.search(user_message):
        matched.append(category)
if matched:
    return {
        "action":         "phi_redirect",
        "phi_categories": matched,
    }
```

**What's wrong:**

The bot's identity-verification flow specifically asks for a phone number via the `_collect_identifiers_from_message` path. The configured prompt is "the last four digits of the phone number we have on file," which is fine. But the `account_long` PHI pattern matches *any* 9-16 digit standalone sequence anywhere in the user's message. I verified this:

```
>>> re.search(r'\b\d{9,16}\b', 'my phone is 5555551234 thanks')
<re.Match object; span=(12, 22), match='5555551234'>
```

A patient who reads the prompt as "give me your phone number" (a reasonable misread of "the last four digits of the phone number") and types `"my phone is 5555551234"`, or `"5555551234"`, or `"555 555 1234"` collapsed, hits the `account_long` PHI pattern. `_screen_input` returns `action: "phi_redirect"`, `_handle_screening_action` emits `PHI_REDIRECT_TEMPLATE`: "For your privacy, please don't share specific health details, account numbers, or other personal information in this chat. I just need your name, date of birth, and a confirmation factor to find your record."

That message is, almost word for word, an apology for the user having tried to do exactly what the bot asked them to do. The PHI redirect is conceptually right (a 10-digit standalone number is a probable SSN-or-phone-or-MRN signal that a generic chat surface should not happily accept), but in the scheduling-bot context the bot has *just asked* for that input. The result is a contradictory loop. A reader copying this pattern into production gets the same loop in their pilot.

This is also a misleading pattern because it teaches the wrong layering. PHI minimization in the scheduling bot has to be context-aware: before identity verification, sensitive identifiers are unwanted and the screen should redirect; *during* identity verification, the bot is asking for them and the screen should pass them through to the identity-verification handler. The demo's screen runs unconditionally and conflates the two.

**How to fix:**

Either (a) gate the `account_long` PHI check on the conversation phase (skip it when the active session state is `awaiting_identity` or `identity_step_up`), or (b) tighten the `account_long` pattern so it doesn't fire on a bare 10-digit phone-shaped sequence (e.g., require a label like `"account"` or `"member"` nearby), or (c) move PHI minimization to the response side only (block the bot from echoing PHI back to the user) and rely on the identity-verification policy to constrain what identifiers get persisted.

For a teaching example I'd lean to (a): a 10-line `if session.get("disposition") in ("awaiting_identity", "identity_step_up"): pass else: ...` guard around the `account_long` check. It demonstrates the layering the recipe is trying to teach without making the demo loop on itself.

### W3. The `IDENTITY_POLICY` table has the authenticated rule first for every intent, so a same-day cancellation by an authenticated patient never triggers step-up; this is the opposite of the pseudocode's stated behavior

**File / section:** `chapter11.02-python-example.md`, "Configuration and Constants," `IDENTITY_POLICY` (and the `_required_assurance_for` evaluator):

```python
IDENTITY_POLICY = {
    ...
    "cancel_appointment": [
        (lambda ctx: ctx.get("authenticated"), "authenticated"),
        (lambda ctx:
            ctx.get("hours_to_appointment", 999) < 24,
         "step_up"),
        (lambda ctx: True, "basic"),
    ],
    ...
}
```

```python
def _required_assurance_for(intent: str, ctx: dict) -> str:
    rules = IDENTITY_POLICY.get(intent, [(lambda c: True, "basic")])
    for predicate, level in rules:
        if predicate(ctx):
            return level
    return "basic"
```

**What's wrong:**

The pseudocode in the main recipe (Step 7 and the "Identity verification is graduated by intent and channel" architectural note) is explicit that same-day cancellations should require step-up auth even for authenticated portal users:

> Cancellation of certain visit types may require additional verification. Same-day cancellation has different policy than cancellation a week out.

The intent of the policy table, judging from the demo's own `_handle_reschedule_or_cancel` code that checks `if (required == "step_up" and current_assurance not in ("authenticated", "step_up"))` and prompts for a one-time code, is that the `step_up` rule should fire for same-day actions regardless of how the patient arrived.

But the rule-evaluator returns the *first matching rule*, and the `authenticated` rule matches before the `hours_to_appointment < 24` rule does. So an authenticated patient asking to cancel a same-day appointment gets `required_assurance = "authenticated"`, the same-day step-up never triggers, and the demo's `cancel_appointment` scenario short-circuits the policy check entirely.

The recipe specifically describes this as the kind of risk the architecture exists to manage:

> The patient experience for high-assurance flows is intentionally a little more friction than for low-assurance flows, because the cost of a wrong action is higher.

The published policy table demonstrates the opposite: the highest-friction action (same-day cancel) gets the lowest-friction assurance path when the patient is authenticated, which is exactly the escalation pattern a malicious actor with a hijacked session would exploit. A learner copying this table into production has a same-day-cancel exploit on launch day.

**How to fix:**

Reorder the rules so the higher-risk predicate is checked before the authenticated short-circuit:

```python
"cancel_appointment": [
    (lambda ctx:
        ctx.get("hours_to_appointment", 999) < 24,
     "step_up"),
    (lambda ctx: ctx.get("authenticated"), "authenticated"),
    (lambda ctx: True, "basic"),
],
```

Same fix for `reschedule_appointment`. The `new_appointment` and `check_appointment` entries are fine because there is no high-risk same-day predicate to interleave; the authenticated short-circuit there is correct.

Alternatively, change `_required_assurance_for` to compute the *maximum* assurance level across all matching rules instead of returning the first match. That generalizes better but is a larger change for a teaching example.

### W4. Most assistant turns are `_append_turn`-ed directly with hard-coded template strings, bypassing `screen_output`; the demo's `run_demo` only screens the final returned reply text

**File / section:** `chapter11.02-python-example.md`, "Step 9: Output Safety Screening with Booking-Claim Verification," function `screen_output`, plus the dozens of call sites in Steps 1-8 that call `_append_turn(speaker="assistant", text=<TEMPLATE>)` without going through `screen_output` first.

The companion documents this with a comment in `screen_output`'s docstring:

> The chat handler calls this on every assistant turn before appending it to the metadata table. The Python helper functions above each call `_append_turn` directly with pre-built strings; in production all generated assistant text goes through this screen first.

**What's wrong:**

The booking-claim verification is the most important new safety primitive in this recipe. The main recipe's prose calls it out as the critical scheduling-specific check that the FAQ bot did not need:

> The new check verifies that any "your appointment is confirmed" claim in the response is supported by an actual successful booking-tool result. Skip this check and a hallucinated confirmation that no booking actually backs results in a patient showing up for an appointment that does not exist.

In the published demo, the only response that goes through `screen_output` is the final reply text returned by the public entry-point functions (and that is only because `run_demo` calls `screen_output` explicitly after dispatching). Every assistant turn appended via `_append_turn` inside the helper functions skips `screen_output` entirely. Most of those turns are template strings (`SYSTEM_ERROR_TEMPLATE`, `SLOT_RACE_TEMPLATE`, `INJECTION_REFUSAL_TEMPLATE`, etc.), which is fine for those specific cases because they have no booking claims. But the `confirmation_text` in `handle_confirmation_response` ("Booked. Your confirmation is RC-2026-…") is a candidate for the booking-claim check, and it is appended via `_append_turn` and returned via `_build_chat_reply` *without* going through `screen_output` from inside `handle_confirmation_response`. The call site in `run_demo` then runs `screen_output` on the reply text, but by then the audit metadata already has the unscreened version persisted. If the screen replaces the response with `BOOKING_CLAIM_FAILED_TEMPLATE`, the *delivered* text is the safe replacement but the *audit record* still shows the unverified original.

This is also misleading because the comment says "in production all generated assistant text goes through this screen first," and the demo's own production-shaped path (the helper functions building chat replies) does the opposite. A learner who reads the comment and the code together gets two contradictory messages and is likely to copy the helper-function pattern as the "real" pattern.

This finding only borders on ERROR territory because the demo is structured so the booking-claim check still runs on the way out (via `run_demo`'s explicit screen call), so the user-facing safety guarantee holds for the demo's actual scenarios. The audit-record divergence and the pattern-of-confusion are why it lands at WARNING.

**How to fix:**

Centralize the assistant-turn write through a single helper that runs `screen_output` first, then appends the (possibly replaced) turn, and returns the chat-reply payload. Replace the direct `_append_turn(...)` plus `_build_chat_reply(...)` pairs in the helper functions with calls to this new helper. Something like:

```python
def _append_assistant_turn_and_reply(
        session_id, channel, response_text,
        attach_greeting, disposition, **turn_extras):
    screened = screen_output(
        session_id=session_id,
        response_text=response_text)
    final_text = screened["response_text"]
    if screened["action"] == "replace_with_safe_response":
        disposition = "output_replaced"
    _append_turn(session_id, {
        "speaker":   "assistant",
        "text":      final_text,
        "timestamp": _now_iso(),
        **turn_extras,
    })
    return _build_chat_reply(
        session_id=session_id,
        response_text=final_text,
        attach_greeting=attach_greeting,
        disposition=disposition)
```

Then the demo's `run_demo` does not need its own screen pass, and every assistant turn — booking confirmation included — goes through the screen exactly once.

---

## NOTE Findings

### N1. The audit record schema diverges from the pseudocode in two minor ways

The pseudocode for Step 10 lists `identity_verification_outcome` and the active-version stamps as flat top-level keys (`active_model_id_at_session`, `active_prompt_version_at_session`, etc.). The Python's `close_conversation_and_archive` consolidates the version stamps under `active_versions: {...}` and replaces `identity_verification_outcome` with `assurance_level` only. The `state` row carries `identity_verification_outcome` but never sets it (it is initialized to `None` implicitly and never updated; the closest signal is whether `assurance_level` is non-null). The audit-record consumer can reconstruct the outcome from `assurance_level` plus the `tool_calls` slice for `patient_lookup`, but the outcome field was a more direct read.

Either explicitly set `state["identity_verification_outcome"]` to one of `verified_first_attempt`, `verified_after_step_up`, `no_match`, `ambiguous_match`, `step_up_pending` at each branch in the identity flow, or lift the active-version stamps back to the top level to match the sample audit record in the main recipe (which uses the flat structure).

### N2. `slot_reschedule` is documented in the prose and the configuration but is not implemented; `_execute_reschedule` calls `_search_for_slots` directly without coordinating the cancel of the existing appointment

The recipe describes `slot_reschedule` as "a coordinated cancel-and-book operation, but the institution often wants it logged as a reschedule rather than as separate cancel and book events." The Python's `_execute_reschedule` body says "Reschedule is a search-then-hold-then-book against a new slot coordinated with cancellation of the existing one. When the institution's API supports a single-call reschedule, use that; otherwise wrap the cancel-and-book pair as a coordinated transaction" — and then implements neither. It just calls `_search_for_slots` with the existing visit type and existing-appointment-id stuffed into `parameters`; the existing appointment is never canceled and the booking journal never gets a "rescheduled" event.

The demo never exercises a reschedule path so the gap does not surface in `run_demo`, but a reader who copies `_execute_reschedule` into production has a function that books a new appointment and orphans the old one. Either implement the cancel-then-book pair (with a journal entry of `event_type: "rescheduled"` referencing both confirmation IDs) or short-circuit the function to a `live_scheduler` handoff with a TODO comment that says "wrap when the EHR's reschedule API is wired in."

### N3. `scope_violation_count` and `handoffs_offered` / `handoffs_accepted` are initialized in the new-session row but never incremented anywhere in the helper functions

The audit record at close time pulls these counters from the session-state row:

```python
"scope_violation_count":
    int(state.get("scope_violation_count", 0)),
"handoffs_offered":
    int(state.get("handoffs_offered", 0)),
"handoffs_accepted":
    int(state.get("handoffs_accepted", 0)),
```

But none of the helper functions ever calls `_update_session_flag(session_id, "scope_violation_count", ...)` or the handoff counters. `_handle_in_scope_message` emits a `HandoffOffered` CloudWatch metric and an EventBridge event when it routes to an out-of-scope target, but it does not bump the per-session counter. The `screen_output` replacement path returns a violation but does not propagate the count back to the session. The persisted audit record always shows `0` for these fields.

Same shape as 11.1's W2; carries forward as a NOTE here because the surrounding metric and event emissions still happen and the per-cohort dashboards can be reconstructed from the EventBridge stream. Fix is the same: bump the session counter at each emission site.

### N4. `_put_metric("TimeToBooking", duration_seconds, ...)` measures the full conversation duration, not the time-to-first-booking the pseudocode names

The pseudocode's Step 10C emits:

```
cloudwatch.put_metric(
    namespace: "SchedulingBot",
    metric_name: "TimeToBooking",
    value: state.time_to_first_booking_seconds,
    ...)
```

The Python's `close_conversation_and_archive` emits:

```python
if audit_record["bookings_completed"] > 0:
    _put_metric("TimeToBooking",
                duration_seconds, ...)
```

where `duration_seconds = (ended_at - started_at)` covers the full conversation including any post-booking turns, the final goodbye, and any session-cleanup latency. For a "Marcus books and chats for two extra turns" scenario the metric reports a duration meaningfully longer than the actual time-to-booking. The dashboards that key off this metric report a slower bot than the bot actually is.

Track the time-to-first-booking explicitly: stamp `state["time_to_first_booking_seconds"]` inside `handle_confirmation_response` at the moment the booking is confirmed, computed as `(now() - state["started_at"]).total_seconds()`, and emit that value at close time.

### N5. `update_item` on `MockTable` only handles a single-attribute `SET <name> = <val>` update; the surrounding code happens to use only single-attribute updates but the limitation is invisible to a reader

`MockTable.update_item`:

```python
match = re.match(r"\s*SET\s+(\S+)\s*=\s*(\S+)\s*$",
                 UpdateExpression)
if match:
    name_token, val_token = match.groups()
    ...
```

If a reader extends the demo to do a multi-attribute `SET #a = :a, #b = :b` (which is normal DynamoDB syntax), the regex silently does not match and the update is a no-op. The mock should at minimum log a warning when the regex does not match, or split the expression on commas and apply each set in turn. Same shape as 11.1's MockTable; carrying forward as a NOTE.

### N6. The `account_long` PHI redaction in `_redact_pii_for_logging` and `_redact_turn_for_audit` strips digits but leaves the surrounding identifier visible in the audit archive

After redaction, `"my phone is 5555551234"` becomes `"my phone is [REDACTED]"`. The DOB `"1979-03-14"` is not redacted by any of the three patterns (it doesn't match `\d{3}-\d{2}-\d{4}` because the segments are 4-2-2, not 3-2-4; it doesn't match `\d{9,16}` because the dashes break the digit run; it doesn't match the MRN prefix). So the conversation archive still has the patient's date of birth in plain text after redaction, which is the actual identifier the recipe's audit-pipeline section flags as needing protection. The recipe's prose says:

> Production has a more thorough redaction step using Comprehend Medical or a tuned classifier.

That is true, but the demo's redaction-for-logging contract is a misleading floor: a reader who reads `_redact_turn_for_audit` and assumes "my conversation log is safe to view" will be wrong because the most common patient identifier (DOB) is not redacted. Either add a DOB pattern (`\b\d{4}-\d{2}-\d{2}\b` and the slash variant) to `PHI_PATTERNS`, or rename `_redact_pii_for_logging` to make clear it is a partial backstop and the real redaction lives elsewhere.

---

## Validation Notes

- The boto3 API surface used by the companion (`bedrock-runtime.invoke_model`, `bedrock-agent-runtime.invoke_agent`, `dynamodb.Table().put_item`/`get_item`/`update_item`/`query`, `events.put_events`, `firehose.put_record`, `cloudwatch.put_metric_data`, `s3.put_object`, `secretsmanager.get_secret_value`) is correct against current SDK conventions. No method-name typos, no parameter-name drift.
- The `Decimal`-not-`float` discipline is consistent at every DynamoDB write boundary and the Decimal-typed thresholds (`INTENT_CONFIDENCE_THRESHOLD`, `VISIT_TYPE_CONFIDENCE_THRESHOLD`, `ASSURANCE_MATCH_THRESHOLDS`) compare correctly against incoming Decimal values from the classifier mock.
- S3 keys in `_write_booking_journal` have no leading slashes.
- The booking-claim verification is structurally correct (and is the architectural primitive most worth preserving in the rewrite). The regex `[A-Z]{2}-\d{4}-\d{3,}` is loose enough that a future change to the confirmation-ID format (longer prefix, longer year, longer trailing digits) keeps matching, and tight enough that it does not match arbitrary uppercase tokens. The `_find_supporting_book_call` walk over the tool-call ledger is the correct shape: it requires a `slot_book` entry with `outcome == "booked"` whose `result_summary.confirmation_id` matches the claim's confirmation_id.
- The mock scheduling-system fixture exercises the `slot_no_longer_available` path (the `slot_hold` mock checks `if slot_id in self.holds:` and refuses to issue a second hold), which is what makes the slot-hold-and-confirm transactional contract testable. None of the demo scenarios actually drive a race, but the path is exercisable from a test that pre-populates `self.holds[slot_id]`.
- The deploy-time guardrail asserting non-empty resource-name constants is a useful production hygiene pattern that survives the carry-forward from 11.1.

---

## Recommended Changes Before Re-Review

1. Fix `_collect_identifiers_from_message` so `confirmation_factor` does not extract the year of the DOB. Verify by running `run_demo()`'s `happy_path_booking` scenario and confirming the disposition is `booked` with a non-zero `bookings_completed`. (E1)
2. Combine SLOT_RACE_TEMPLATE with the re-search candidates in the user-facing reply rather than appending it as a phantom turn. (W1)
3. Phase-gate the `account_long` PHI check so it does not fire during identity-verification turns where the bot has explicitly asked for a phone-shaped identifier. (W2)
4. Reorder the `IDENTITY_POLICY` rules for `cancel_appointment` and `reschedule_appointment` so the same-day step-up predicate is evaluated before the authenticated short-circuit. (W3)
5. Centralize assistant-turn writes through a helper that runs `screen_output` first, then appends, so the booking-claim check covers every booking-confirmation message before it reaches the audit metadata. (W4)

The NOTE-level items are not blocking; they are quality-of-life improvements for future maintenance. The five WARNING/ERROR fixes above are the ones to land before the next review pass.
