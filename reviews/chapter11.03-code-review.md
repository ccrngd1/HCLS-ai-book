# Code Review: Recipe 11.3 — Prescription Refill Request Bot (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter11.03-python-example.md`
- `chapter11.03-prescription-refill-request-bot.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** FAIL

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 1 |
| WARNING  | 4 |
| NOTE     | 4 |

The Python companion is a substantial walkthrough of the ten pseudocode steps from the main recipe (session bootstrap with greeting and disclosure plus input safety screening including refill-context misuse signals, intent classification with explicit medication_change/clinical_question handoffs, identity verification at the higher-floor refill assurance level with REQUIRE_AUTHENTICATED_FOR_REFILL gating, medication resolution against the patient's structured list with discontinued and specialist branches, refill-protocol evaluation with lab reconciliation and interaction screening and a controlled-substance triple-defense, transactional fulfillment via e_prescribe with prescriber co-signature enqueue, status-check / cancel / medication-question paths, e-prescribe failure handling, output safety screening with refill-claim verification against the tool-call ledger and medication-list integrity check and controlled-substance language detection, and conversation-close audit archival with the separately-governed refill-event journal). The structural decomposition tracks the pseudocode well; the tool surface (`patient_lookup_tool`, `medication_list_lookup_tool`, `medication_resolution_tool`, `lab_reconciliation_tool`, `interaction_screening_tool`, `protocol_evaluate_tool`, `e_prescribe_tool`, `clinical_routing_tool`, `refill_status_check_tool`, `cancel_refill_request_tool`) is cleanly separated from orchestration logic; the controlled-substance triple defense is correctly layered (the protocol forces `controlled_substance_always_route` on any Schedule II-V medication regardless of upstream state, the e_prescribe tool refuses to transmit any controlled substance through the auto-approval path, and the output screen detects controlled-substance auto-approval language); the refill-event journal writes to S3 via a key with no leading slash; and the tool-call ledger is correctly walked at output-screen time to verify each prescription-ID claim against an `e_prescribe` ledger entry with `outcome == "transmitted"`.

**Validation performed:**
- Walked the ten pseudocode steps against the Python functions: Step 1 `receive_message` → `receive_message` + `_get_or_create_session` + `_screen_input` + `_handle_screening_action`; Step 2 `classify_refill_intent` → `_classify_refill_intent` (called from `_handle_in_scope_message`); Step 3 `verify_identity` → inlined into `_route_to_refill_flow` plus `_collect_identifiers_from_message` and `_required_assurance_for`; Step 4 `resolve_medication` → `_resolve_medication`; Step 5 `evaluate_protocol` → `_evaluate_protocol` plus `protocol_evaluate_tool`; Step 6 `execute_disposition` → `_execute_disposition` + `_execute_auto_approve` + `_execute_clinical_routing` + `_execute_denial`; Step 7 (status/cancel/question) → `_handle_status_check` + `_handle_cancel_request` + `_handle_medication_question`; Step 8 `handle_eprescribe_failure` → `_handle_eprescribe_failure`; Step 9 `screen_output` → `screen_output` + `_extract_refill_claims` + `_find_supporting_eprescribe_call` + `_extract_medication_mentions` + `_detect_controlled_substance_auto_approval_language`; Step 10 `close_conversation_and_archive` → `close_conversation_and_archive` + `_redact_turn_for_audit`.
- Verified service-name strings on the boto3 clients: `bedrock-runtime`, `bedrock-agent-runtime`, `comprehendmedical`, `dynamodb` (resource), `events`, `firehose`, `cloudwatch`, `s3`, `secretsmanager` are all correct.
- Verified the `Decimal`-not-`float` discipline at every DynamoDB write boundary. `_to_decimal` recursively converts floats to `Decimal` and is invoked at every put_item/update_item path: `_get_or_create_session`, `_append_turn`, `_update_session_flag`, `_audit_tool_call`, the cosignature_queue.put_item in `_execute_auto_approve`. The Decimal-typed thresholds (`INTENT_CONFIDENCE_THRESHOLD`, `MED_RESOLUTION_CONFIDENCE_THRESHOLD`, `ASSURANCE_MATCH_THRESHOLDS`) are constructed via `Decimal("...")` at definition. `_from_decimal` is invoked when reading state. CloudWatch's `put_metric_data` accepts native floats so `_put_metric` correctly does not wrap `value` in Decimal.
- Verified the refill-event-journal S3 path has no leading slash: `f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['event_id']}.json"`.
- Verified the deploy-time guardrail asserts every resource-name constant is non-empty (the `for _name, _value in [...]: assert _value` block at module load).
- Verified the screening-before-classification discipline: `_screen_input` runs crisis detection first (with refill-specific overdose and misuse cues like "took double" and "took an extra" prepended to the cue list), then injection detection, then PHI detection. `_handle_in_scope_message` is only entered if the screening action is `"proceed"`.
- Verified the Bedrock invoke_model body shape: the Anthropic Messages API request (`anthropic_version: "bedrock-2023-05-31"`, `max_tokens`, `temperature`, `system`, `messages: [{role, content}]`) is correct. The response parse `payload = json.loads(response["body"].read())` followed by `payload["content"][0]["text"]` matches the real StreamingBody shape.
- Verified the EventBridge `put_events(Entries=[{Source, DetailType, Detail, EventBusName}])` shape, the Firehose `put_record(DeliveryStreamName=..., Record={"Data": <bytes>})` shape, and the S3 `put_object(Bucket=..., Key=..., Body=..., ContentType=..., ServerSideEncryption="aws:kms")` shape are all correct.
- Verified the `_resolve_session_key` GSI-then-fallback pattern carries forward correctly from 11.02's W1 fix: in production the lookup uses `IndexName="session_id-index"`, in the demo the mock exposes `_find_session_key_by_session_id` for a scan. So `_update_session_flag` and `close_conversation_and_archive` both target the actual session row, not an orphaned key namespace.
- Verified the controlled-substance triple defense:
  1. `protocol_evaluate_tool` returns `"controlled_substance_always_route"` for any Schedule II-V medication.
  2. `_evaluate_protocol` re-checks the disposition after protocol_evaluate returns, alarms on misclassification, and forces the safe disposition.
  3. `e_prescribe_tool` refuses to transmit any controlled substance regardless of the disposition that arrived.
  4. `screen_output` calls `_detect_controlled_substance_auto_approval_language` which scans for "I've sent" plus a controlled-substance medication name and replaces with `CONTROLLED_SUBSTANCE_ROUTING_TEMPLATE`.
- Verified the refill-claim verification logic: `_extract_refill_claims` matches the prescription-ID format `[A-Z]{2}-\d{4}-\d{3,}` (which matches the mock's `f"RX-2026-{...:07d}"` format) and falls back to a generic-claim regex for "I've sent" / "the pharmacy will text you" / etc.; `_find_supporting_eprescribe_call` walks the tool-call ledger looking for `tool == "e_prescribe"` entries with `outcome == "transmitted"` whose `result_summary.prescription_id` matches the claim's `prescription_id`. This is the load-bearing safety primitive the recipe's "did the bot hallucinate a refill confirmation" check depends on.
- Verified the medication-list integrity check: `_extract_medication_mentions` walks the patient's active medication list and looks for matching name/display-name strings in the response; `_medication_in_list` confirms the membership; the screen replaces the response with `NO_MATCH_MEDICATION_TEMPLATE` if the response mentions a medication not on the patient's list.
- Hand-traced each demo scenario through the Python flow. The headline `happy_path_auto_approve` scenario does not actually auto-approve; it emits the routed disposition because the demo's fixture trips the early-refill check (E1 below). The other five scenarios trace cleanly to their expected dispositions: `specialist_medication_routed` matches `specialist_only` in the protocol entry for amiodarone and emits `SPECIALIST_MEDICATION_TEMPLATE` at medication-resolution time before protocol evaluation runs; `controlled_substance_routed` hits the controlled-substance triple defense and emits `CONTROLLED_SUBSTANCE_ROUTING_TEMPLATE`; `discontinuation_handoff` classifies as `medication_change` via the "want to stop" rule in the classifier prompt and routes to nurse_triage; `prompt_injection_attempt` matches the `r"ignore (all |any |the )?(previous|prior|above) (instructions|messages|prompts)"` regex during input screening; `misuse_signal_crisis_routed` matches `"took double"` in `HIGH_ACUITY_CUES` and emits `CRISIS_ROUTE_TEMPLATE` before classification.

The walkthrough is structurally faithful to the architecture diagram and the ten pseudocode steps. The triple-defense for controlled substances, the refill-claim verification, the medication-list integrity check, the refill-event journal as a separately-governed clinical-record-event log, and the prescriber co-signature queue are all the load-bearing primitives the main recipe sells, and they are all structurally present and functionally exercised by the demo's controlled-substance scenario.

That said, the companion has one ERROR-level finding that breaks the headline scenario the recipe sells (Eleanor's ninety-second metformin auto-approval), four WARNING-level findings (each one of which is a misleading pattern that a learner would copy into production), and four NOTE-level findings. Per the persona's pass/fail rules, an ERROR is automatic FAIL. The good news is that the ERROR is a single fixture-data change and three of the four WARNINGs are already documented in the 11.02 review and inherit the same fixes; the architectural skeleton is sound and re-running the review after the fixes should be quick.

---

## ERROR Findings

### E1. Eleanor's metformin fixture (`days_since_last_fill: 31`) trips the early-refill check, so the headline `happy_path_auto_approve` scenario routes to clinical instead of auto-approving and contradicts the recipe's narrative

**File / section:** `chapter11.03-python-example.md`, "Putting It All Together," `MockEHR.__init__`:

```python
"patient-internal-eleanor": [
    {
        "id": "med-met-500",
        "name": "metformin",
        ...
        "days_since_last_fill": 31,
        "refills_remaining": 0,
        "standard_quantity": 180,
        "standard_days_supply": 90,
        ...
    },
    ...
]
```

And `protocol_evaluate_tool`:

```python
# Early-refill check.
days_since = (
    request_context.get("days_since_last_fill")
    or 999)
early_threshold = entry.get(
    "early_refill_threshold_days", 7)
standard_days = medication.get(
    "standard_days_supply", 30)
if days_since < (standard_days - early_threshold):
    return {
        "disposition":      "early_refill_route",
        "rules_fired":      ["early_refill_detected"],
        ...
    }
```

**What's wrong:**

The protocol's early-refill semantic is "if the patient is asking for a refill more than `early_refill_threshold_days` before their current supply is expected to run out, route to clinical." For metformin the protocol entry sets `early_refill_threshold_days = 7` and the medication record sets `standard_days_supply = 90`, so the threshold for "too early" is `90 - 7 = 83` days. The check `days_since < 83` fires the routing path.

For Eleanor's metformin the fixture has `days_since_last_fill = 31`, which is 31 days into a 90-day supply. The check evaluates `31 < 83 = True`, so `protocol_evaluate_tool` returns `disposition="early_refill_route"` before ever reaching the monitoring check, the interaction check, or the auto_approvable branch. `_execute_disposition` matches `"early_refill_route"` against the route-* set and dispatches to `_execute_clinical_routing`, which emits `EARLY_REFILL_ROUTING_TEMPLATE`:

> It looks like you're asking for a refill on metformin 500 mg earlier than expected. I'm sending this to our clinical team to take a look. They'll reach out to you.

I traced this end-to-end against the demo's `happy_path_auto_approve` scenario:

1. Eleanor authenticated (auth_context bypasses identity verification).
2. `_classify_refill_intent` returns `intent="request_refill"`, descriptor=`"metformin"`.
3. `_resolve_medication` matches `med-met-500`; `specialist_only=False`, not discontinued, not controlled.
4. `_evaluate_protocol`:
   - lab_reconciliation finds the 24-day-old A1c.
   - interaction_screening finds none.
   - `protocol_evaluate_tool`: `days_since=31`, `early_threshold=7`, `standard_days=90`, `31 < 83 = True` → returns `disposition="early_refill_route"`.
5. `_execute_disposition` → `_execute_clinical_routing` → `routing_target="prescriber_inbox"` → `EARLY_REFILL_ROUTING_TEMPLATE`.

The actual demo output for the `happy_path_auto_approve` scenario:

```
-> disposition: routed
-> bot says: It looks like you're asking for a refill on metformin 500 mg earlier than expected. I'm sending this to our clinical team to take a look. They'll reach out to you.
-> conversation closed: user_session_end
-> refills_auto_approved: 0
-> refills_routed: 1
```

The recipe's "Sample conversation" walkthrough explicitly shows the auto-approval response:

> Bot: I see your metformin 500 mg twice daily, last filled at Walgreens on Main Street on March 12th. Let me check the protocol for this one... Your most recent A1c was 7.1 from April 28th, which is in range for maintenance. I'm sending the refill to Walgreens on Main Street: 90-day supply with three refills authorized.

And the corresponding sample audit record shows:

```json
{
  "tool_calls": [...{"tool": "e_prescribe", "result_summary": {"outcome": "transmitted", "prescription_id": "RX-2026-7798231"}}],
  "refills_auto_approved": 1,
  "final_disposition": "auto_approved"
}
```

But the demo's first scenario, named `happy_path_auto_approve`, never invokes `e_prescribe` because the protocol short-circuits at the early-refill check. `refills_auto_approved` ends at 0 and `final_disposition` lands at "routed". A reader running the file as published sees the routing message, not the auto-approval the recipe centers on.

This breaks the load-bearing demo scenario. The recipe spends multiple pages on the auto-approval path (the sample conversation, the sample audit record, the controlled-substance triple defense's "the bot does not auto-approve unless the protocol says yes"), and the published demo never exercises that path.

**How to fix:**

The simplest fix is to change Eleanor's metformin fixture to a value past the early-refill threshold. The recipe's narrative says "she has been off her metformin since Sunday" (i.e., the prior fill ran out a few days ago), so a value like `days_since_last_fill: 92` or `95` matches the narrative and exercises the auto-approval path:

```python
"days_since_last_fill": 92,
```

After the fix, hand-tracing the happy_path scenario produces:

- `days_since=92`, `92 < 83 = False` → early-refill check passes
- monitoring check: A1c from 24 days ago, within the 365-day window → passes
- interactions: empty → passes
- `entry["auto_approvable"] = True` → returns `disposition="auto_approve"`
- `_execute_auto_approve` selects Walgreens (the medication's `last_fill_pharmacy_id`), calls `e_prescribe_tool`, gets `outcome="transmitted"` and a `prescription_id` like `RX-2026-XXXXXXX`
- `refills_auto_approved=1`, response includes "I've sent your metformin 500 mg to Walgreens on Main Street. Confirmation number is RX-2026-XXXXXXX..."

A secondary issue worth fixing in the same pass: the same fixture mismatch affects Eleanor's lisinopril (`days_since_last_fill=20`, `standard_days_supply=90` → 20<83 → early_refill_route) and Marcus's amiodarone (`days_since_last_fill=25`, but amiodarone short-circuits at the specialist_only check before reaching the early-refill rule, so this one happens to land on the right path by accident). Bumping Eleanor's lisinopril to `days_since_last_fill=85` aligns the data with the recipe's narrative and gives the reader a second auto-approvable medication to refer to from the secondary turn in the recipe's sample conversation ("also can you check on the atorvastatin?" — if the demo were extended to support a multi-medication conversation).

Until the fixture is fixed, the demo as published does not produce the auto-approved outcome the recipe shows.

---

## WARNING Findings

### W1. `_collect_identifiers_from_message` extracts the year of the date of birth as the confirmation factor; the bug carries forward unchanged from 11.02 E1

**File / section:** `chapter11.03-python-example.md`, "Step 3: Verify Identity at the Refill-Floor Assurance Level," function `_collect_identifiers_from_message`:

```python
conf_match = re.search(
    r"(?<!\d)(\d{4})(?!\d)", combined)
confirmation = conf_match.group(1) if conf_match else None
```

**What's wrong:**

The regex `(?<!\d)(\d{4})(?!\d)` matches the *first* standalone 4-digit sequence in the combined identifier string. For the canonical input `"Marcus Chen, 1979-03-14, 7842"` the engine returns `"1979"` (the year of the DOB) instead of `"7842"` (the last-four-of-phone the bot's prompt actually asked for). I verified empirically:

```
>>> re.search(r'(?<!\d)(\d{4})(?!\d)', 'Marcus Chen, 1979-03-14, 7842').group(1)
'1979'
```

Same bug as 11.02 E1, copied verbatim into 11.03. The 11.02 review classified it as ERROR because 11.02's headline scenario (Marcus booking an appointment) traveled through the unauthenticated identity-verification path. In 11.03 the bug lands at WARNING rather than ERROR for two reasons:

1. `REQUIRE_AUTHENTICATED_FOR_REFILL = True` short-circuits unauthenticated `request_refill` and `cancel_refill_request` intents to `REQUIRE_PORTAL_LOGIN_TEMPLATE` before identity verification runs at all. The only intents that still travel through the conversational identifier-collection path are `check_refill_status` and `medication_question`, neither of which is exercised by the demo scenarios.
2. The demo's six scenarios all use `auth_context = {"authenticated": True}` (or hit input screening before identity verification, in the prompt-injection case), so the regex bug is invisible at runtime.

That said, the bug is a misleading pattern that a learner would copy into production, especially since this is the third recipe in a row that ships the same buggy regex. A reader deploying the refill bot with `REQUIRE_AUTHENTICATED_FOR_REFILL = False` (which the comment in the config block mentions some institutions choose) hits the bug immediately on any unauthenticated refill action, with the same identity_no_match outcome the 11.02 review described.

**How to fix:**

Same fix as 11.02 E1. Use the *last* standalone 4-digit sequence rather than the first:

```python
conf_matches = re.findall(r"(?<!\d)(\d{4})(?!\d)", combined)
confirmation = conf_matches[-1] if conf_matches else None
```

This naturally skips the year inside the DOB and picks the last-four-of-phone the bot's prompt asked for. Better still, since both 11.01, 11.02, and 11.03 carry the same identifier-extraction logic, factor it out into a shared helper and fix it once. The recipe-to-recipe duplication of this code is itself a smell; centralizing it removes the failure mode of "fix it in 11.02, miss the carry-forward into 11.03 and 11.04."

### W2. The `account_long` PHI pattern (9-16 digit sequences) collides with the bot's own request for full-phone-number identifiers and produces a contradictory loop on any unauthenticated refill flow that still allows free-text identifier collection

**File / section:** `chapter11.03-python-example.md`, "Configuration and Constants," `PHI_PATTERNS`, and `_screen_input`:

```python
PHI_PATTERNS = {
    "ssn_like":     re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "account_long": re.compile(r"\b\d{9,16}\b"),
    "mrn_prefix":   re.compile(r"\bMRN\s*[:#]?\s*\d{4,}\b",
                                re.IGNORECASE),
}
```

**What's wrong:**

Same bug as 11.02 W2, copied unchanged into 11.03. The `account_long` pattern matches any 9-16 digit standalone sequence anywhere in the user's message:

```
>>> re.search(r'\b\d{9,16}\b', 'my phone is 5555551234 thanks')
<re.Match object; span=(12, 22), match='5555551234'>
```

A patient who reads the bot's identity-verification prompt as "give me your phone number" (a reasonable misread of "the last four digits of the phone number") and types `"my phone is 5555551234"` hits the `account_long` PHI pattern, which routes to `PHI_REDIRECT_TEMPLATE`:

> For your privacy, please don't share specific health details, account numbers, or other personal information in this chat. I just need your name, date of birth, and a confirmation factor to find your record.

That message is, almost word for word, an apology for the user having tried to do exactly what the bot asked them to do. The recipe's higher identity-verification floor for refills (most refill actions require an authenticated portal session) makes this less common than in 11.02 because the contradictory-loop scenarios are confined to status-check and medication-question intents over an unauthenticated channel. But the misleading pattern is still present and a reader will copy it into their own implementation.

The PHI-context-awareness gap also surfaces in another place: PHI redaction inside the audit pipeline. `_redact_pii_for_logging` strips matches against the same patterns from log lines, but the patterns don't cover the patient's date of birth (formatted `1954-09-12`, which doesn't match `\d{3}-\d{2}-\d{4}` because the date segments are 4-2-2 not 3-2-4, doesn't match `\d{9,16}` because the dashes break the run, and doesn't match the MRN pattern). So the audit archive carries the full DOB in plain text after redaction. Same shape as 11.01 N6 and 11.02 N6. The recipe acknowledges that real redaction lives in Comprehend Medical, but a learner reading `_redact_turn_for_audit` and assuming "my conversation log is safe to view" is wrong.

**How to fix:**

Three options, in order of intrusiveness:

1. Phase-gate the `account_long` check on the conversation phase. Skip it when the active session state's last assistant turn was an `identity_action: "ask_for_identifiers"` / `"ask_for_phone"` / `"step_up_requested"` so the bot does not refuse what it just asked for.
2. Tighten the `account_long` pattern to require an account-context cue (`(?:account|member|insurance)` within a small window) so a bare 10-digit phone-shaped sequence does not fire.
3. Move PHI minimization to the response side only and rely on the identity-verification policy to constrain what identifiers get persisted.

For a teaching example I'd recommend (1): a small `if session.get("last_identity_action") in ("ask_for_identifiers", "ask_for_phone", "step_up_requested"): pass else: ...` guard around the `account_long` check. It demonstrates the layering the recipe is trying to teach without making the demo loop on itself. Same fix recommendation applies to 11.02.

For the audit-redaction gap, add a DOB pattern to `PHI_PATTERNS`:

```python
"dob_iso":   re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b"),
"dob_slash": re.compile(r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](19|20)\d{2}\b"),
```

or rename `_redact_pii_for_logging` to `_redact_pii_partial_backstop` and add a docstring noting that real PHI redaction lives in Comprehend Medical.

### W3. Most assistant turns are `_append_turn`-ed directly with hard-coded template strings, bypassing `screen_output`; the audit metadata captures the unscreened version while only the `run_demo`-level wrapper sees the screened one

**File / section:** `chapter11.03-python-example.md`, "Step 9: Output Safety Screening," function `screen_output`, plus the dozens of call sites in Steps 1-8 that call `_append_turn(speaker="assistant", text=<TEMPLATE>)` without going through `screen_output` first.

The companion documents this with a comment in `screen_output`'s docstring:

> The chat handler calls this on every assistant turn before delivery; the helper functions above each call _append_turn directly with pre-built strings, so the demo applies this at the boundary in run_demo.

**What's wrong:**

Same bug as 11.02 W4, carried forward into 11.03 with the same architectural shape. Every assistant turn appended via `_append_turn` inside the helper functions skips `screen_output` entirely. The most consequential offender is `_execute_auto_approve`, which builds the response via `_build_approval_response`:

```python
response_text = _build_approval_response(
    medication=medication,
    pharmacy=pharmacy,
    prescription_id=eprescribe_result["prescription_id"],
    ...)

_append_turn(session_id, {
    "speaker":   "assistant",
    "text":      response_text,
    "timestamp": _now_iso(),
    ...
    "prescription_id":
        eprescribe_result["prescription_id"],
})

return _build_chat_reply(...)
```

The response text contains the prescription ID — this is exactly the kind of refill-confirmation claim that `screen_output`'s `_extract_refill_claims` plus `_find_supporting_eprescribe_call` is designed to verify. The audit metadata gets the unscreened version. The call site in `run_demo` then runs `screen_output` on the reply text, but by then the audit metadata already has the unscreened version persisted. If the screen replaces the response with `REFILL_CONFIRM_FAILED_TEMPLATE`, the *delivered* text is the safe replacement but the *audit record* still shows the unverified original.

This is more critical in 11.03 than in 11.02 because the refill-claim verification is the *specific* safety primitive the main recipe sells:

> Did the bot say a refill was sent when no e_prescribe call returned success? Did the bot mention a medication that is not on the patient's list? Did the bot indicate it processed a controlled-substance auto-approval? Skip these checks and a hallucinated success-confirmation results in a patient assuming their medication is on the way when it is not.

The published demo's safety primitive is correct in the user-facing path but only by accident: the path runs through `run_demo`'s explicit screen call. A learner who copies the helper-function pattern and skips the `run_demo` wrapper-level screen has none of the safety the main recipe describes, despite the function being defined.

The same shape affects controlled-substance handling. `_detect_controlled_substance_auto_approval_language` is part of `screen_output`; if the helper functions had bypassed the screen, a controlled-substance auto-approval response (which the protocol's triple-defense should prevent but the screen is the third defense) would land in the audit log unmodified.

**How to fix:**

Centralize the assistant-turn write through a single helper that runs `screen_output` first, then appends the (possibly replaced) turn, and returns the chat-reply payload. Replace the direct `_append_turn(...)` plus `_build_chat_reply(...)` pairs in the helper functions with calls to this new helper. Same pattern as 11.02:

```python
def _append_assistant_turn_and_reply(
        session_id, channel, response_text,
        attach_greeting, disposition, language,
        **turn_extras):
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
        "language":  language,
        **turn_extras,
    })
    return _build_chat_reply(
        session_id=session_id,
        response_text=final_text,
        attach_greeting=attach_greeting,
        disposition=disposition)
```

Then `run_demo` does not need its own screen pass, and every assistant turn — including the auto-approval confirmation with its prescription ID — goes through the screen exactly once.

### W4. Session counters `handoffs_offered`, `handoffs_accepted`, and `scope_violation_count` are initialized in the new-session row but never incremented anywhere in the helper functions; the persisted audit record always shows 0 for the metrics the recipe's per-cohort monitoring depends on

**File / section:** `chapter11.03-python-example.md`, "Putting It All Together," and several call sites that emit CloudWatch metrics without bumping the corresponding session counter:

- `_get_or_create_session` initializes `handoffs_offered`, `handoffs_accepted`, `scope_violation_count`, `feedback_history` to zero/empty.
- `_handle_in_scope_message` for the `OUT_OF_SCOPE_INTENTS` branch emits `_put_metric("HandoffOffered", 1, ...)` and `_emit_event("handoff_offered", ...)` but does not call `_update_session_flag(session_id, "handoffs_offered", ...)`.
- `screen_output` returns violations with metric emissions (`_put_metric("OutputScopeViolation", 1, ...)`, `_put_metric("UnsupportedRefillClaim", 1, ...)`, `_put_metric("MedicationNotOnPatientList", 1, ...)`, `_put_metric("ControlledSubstanceAutoApprovalAttempted", 1, ...)`) but does not bump `scope_violation_count`.
- No code path bumps `handoffs_accepted` (the demo does not simulate the user accepting the handoff).
- `close_conversation_and_archive` reads the counters and includes them in the audit record:

```python
"scope_violation_count":
    int(state.get("scope_violation_count", 0)),
"handoffs_offered":
    int(state.get("handoffs_offered", 0)),
"handoffs_accepted":
    int(state.get("handoffs_accepted", 0)),
```

**What's wrong:**

Same shape as 11.01 W2 and 11.02 N3. The session-level counters are read by the audit-archive step but never written by any code path between session creation and conversation close. The CloudWatch metrics are emitted independently and never join up with the session-level state, which means per-conversation analysis (e.g., "show me conversations where the output screen replaced the response") works against the metric pipeline but not against the audit archive.

11.03 does correctly increment the refill-specific counters (`refills_auto_approved`, `refills_routed`, `refills_denied`, `refills_failed`) via `_update_session_flag`, so the recipe's `final_disposition` logic in `close_conversation_and_archive`:

```python
final_disposition = (
    "auto_approved"
        if audit_record["refills_auto_approved"] > 0
    else "routed"
        if audit_record["refills_routed"] > 0
    else "denied"
        if audit_record["refills_denied"] > 0
    else "crisis_routed"
        if audit_record["crisis_detected"]
    else "escalated"
        if audit_record["handoffs_accepted"] > 0
    ...
)
```

works correctly for the refill-specific outcomes. But the `escalated` branch (which covers the `discontinuation_handoff` scenario where the patient's "I want to stop taking my sertraline" routes to nurse_triage) never fires because `handoffs_accepted` is never incremented. The discontinuation-handoff scenario lands at `final_disposition: "other"` instead of `"escalated"`, contradicting the recipe's per-cohort monitoring discipline:

> Refill auto-approval rate per medication class. Routing rate per disposition. Median time-to-completion. Co-signature backlog. Identity-verification failure rate. Tool-call failure rate per tool. Per-cohort metric slices (language, channel, authentication path, age cohort).

The "routing rate per disposition" dashboard reads from the EventBridge stream (where `refill_routed` events do get emitted with the right disposition), so it works at the operational level. But a learner reading the audit JSON expecting `final_disposition: "escalated"` for the discontinuation scenario will see `"other"` and have to debug.

**How to fix:**

Add an `_increment_session_counter` helper (same as the 11.01 review recommended) and wire it into each emission site:

```python
def _increment_session_counter(session_id: str,
                                counter_name: str) -> None:
    session_key = _resolve_session_key(session_id)
    if not session_key:
        return
    table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    table.update_item(
        Key={"session_key": session_key},
        UpdateExpression="ADD #c :one",
        ExpressionAttributeNames={"#c": counter_name},
        ExpressionAttributeValues={":one": Decimal("1")})
```

Then call it at each emission:

- In `_handle_in_scope_message` after `_put_metric("HandoffOffered", ...)` and `_emit_event("handoff_offered", ...)`:
  ```python
  _increment_session_counter(session_id, "handoffs_offered")
  ```
- In `screen_output` when violations are detected:
  ```python
  _increment_session_counter(session_id, "scope_violation_count")
  ```
- For `handoffs_accepted` and `feedback_history`: add a `record_user_feedback(session_id, payload)` entry point that the demo's `run_demo` calls after the handoff response, simulating the user's reply, or extend the demo scenario script to model the "user accepts handoff" turn.

Also note that the mock `MockTable.update_item` only handles single-attribute `SET <name> = <val>` expressions and would silently no-op the `ADD #c :one` syntax. Fix the mock first or use an explicit increment-via-read-modify-write pattern in the demo (with a comment that production uses `ADD`):

```python
def _increment_session_counter(session_id, counter_name):
    session_key = _resolve_session_key(session_id)
    if not session_key:
        return
    table = dynamodb.Table(CONVERSATION_STATE_TABLE)
    response = table.get_item(Key={"session_key": session_key})
    item = response.get("Item")
    if not item:
        return
    current = int(item.get(counter_name, 0))
    item[counter_name] = current + 1
    table.put_item(Item=_to_decimal(item))
```

with a comment that production should use a single `ADD` UpdateExpression to avoid the read-modify-write race.

---

## NOTE Findings

### N1. `protocol_evaluate_tool` accepts `request_context.refills_remaining` but never consults it; a patient with `refills_remaining = 0` is treated identically to a patient with refills authorized as long as the early-refill, monitoring, and interaction checks pass

The `_evaluate_protocol` function packages `refills_remaining` into `request_context`:

```python
request_context={
    "days_since_last_fill":
        medication.get("days_since_last_fill"),
    "refills_remaining":
        medication.get("refills_remaining"),
    "patient_stated_context":
        session.get("patient_stated_context", {}),
},
```

But `protocol_evaluate_tool` never reads it. The decision logic depends on the controlled-substance schedule, the specialist-only flag, the early-refill threshold, the monitoring requirement, the drug-interaction severity, and the `auto_approvable` flag. `refills_remaining` is passed along and discarded.

The recipe's narrative implies the bot handles the `refills_remaining = 0` case by deferring to the prescriber:

> She tried to refill it through her pharmacy's app last week and the app said "no refills authorized, contact prescriber." She called the pharmacy. The pharmacy said the same thing and recommended she call the doctor's office.

The bot's value in this case is to apply the protocol against the patient's history and either renew (when the protocol auto-approves a renewal under the standing order) or route to the prescriber. The Python's protocol-evaluate logic conflates the two: a patient with refills authorized and a patient with `refills_remaining = 0` both run through the same auto-approval check. In practice the e-prescribing platform may distinguish these (`refills_remaining = 0` plus an authorized standing-order renewal is different from `refills_remaining > 0` plus a routine auto-approve), but the demo's logic does not.

Fix: either consume `refills_remaining` in the protocol evaluation (e.g., a separate `route_for_renewal` disposition when `refills_remaining = 0` and the protocol's standing-order rules require it), or stop packaging it into `request_context` and add a comment that the standing-order-renewal path is out of scope for the demo.

### N2. `_get_or_create_session` does a read-modify-write to bump `message_count`, which is a tutorial-grade race condition

`_get_or_create_session`:

```python
item = response.get("Item")
if item:
    item["message_count"] = (
        int(item.get("message_count", 0)) + 1)
    table.put_item(Item=_to_decimal(item))
    return _from_decimal(item)
```

The pattern works for a single-threaded demo. In production, two messages from the same channel arriving close together race on the read-modify-write: both read message_count=N, both increment to N+1, the last one to write wins, message_count ends at N+1 instead of N+2. The same loss happens when the chat handler retries on a transient error.

The DynamoDB-native pattern is `update_item` with `ADD #c :one`:

```python
table.update_item(
    Key={"session_key": session_key},
    UpdateExpression="SET #la = :ts ADD #mc :one",
    ExpressionAttributeNames={"#la": "last_active_at", "#mc": "message_count"},
    ExpressionAttributeValues={":ts": _now_iso(), ":one": Decimal("1")})
```

Concurrent message arrivals in chat are uncommon enough that this rarely surfaces in production, but the recipe is teaching DynamoDB patterns and the read-modify-write is the wrong one. Fix is a single function-body change (with a corresponding fix to the mock to support multi-attribute UpdateExpression).

### N3. The `MockTable.update_item` regex only handles a single-attribute `SET <name> = <val>` expression; multi-attribute updates and `ADD`/`REMOVE` syntax silently no-op

`MockTable.update_item`:

```python
match = re.match(r"\s*SET\s+(\S+)\s*=\s*(\S+)\s*$",
                 UpdateExpression)
if match:
    name_token, val_token = match.groups()
    ...
```

Same shape as 11.01 N5 and 11.02 N5. The mock silently ignores any UpdateExpression that doesn't match the single-SET regex. A reader extending the demo to do `ADD #c :one` (the natural fix for W4) or a multi-attribute `SET #a = :a, #b = :b` expression sees no error and no state change. The demo's session-flag updates happen to all be single-attribute SETs so the limitation is invisible until extended.

Fix: at minimum, log a warning when the regex does not match. Better: split the expression on commas and `SET`/`ADD`/`REMOVE` action tokens and apply each piece in turn. The mock's purpose is to demonstrate the demo flow, but it's silently filtering production-grade DynamoDB syntax that a learner would write.

### N4. `_handle_medication_question` retrieves from a curated knowledge base but the demo wires it to `MockKnowledgeBase`; the recipe's prose claims Bedrock Knowledge Bases retrieve-and-generate but the Python doesn't show the actual API call

`_handle_medication_question` calls `knowledge_base_retrieve_and_answer`, which delegates to `knowledge_base.retrieve_and_answer(question=..., medication=..., language=...)`. In the demo, `knowledge_base = MockKnowledgeBase()`, which returns canned strings.

The main recipe and the Python's own setup section claim the medication-information corpus comes from a Bedrock Knowledge Base:

> Amazon Bedrock Knowledge Bases for the institutional content. The refill bot needs the same kind of curated content the FAQ and scheduling bots needed, plus a medication-information corpus...

The Python's `bedrock_agent_runtime` client is created at module load but never invoked. The reader does not see the `bedrock_agent_runtime.retrieve_and_generate(...)` API surface they would need in production:

```python
response = bedrock_agent_runtime.retrieve_and_generate(
    input={"text": question},
    retrieveAndGenerateConfiguration={
        "type": "KNOWLEDGE_BASE",
        "knowledgeBaseConfiguration": {
            "knowledgeBaseId": KNOWLEDGE_BASE_ID,
            "modelArn": f"arn:aws:bedrock:{REGION}::foundation-model/{ORCHESTRATION_MODEL_ID}",
            "retrievalConfiguration": {
                "vectorSearchConfiguration": {
                    "numberOfResults": 4,
                    "filter": {"equals": {"key": "medication_class", "value": medication["class"]}}
                }
            }
        }
    }
)
```

Recipe 11.1's Python companion does show the corresponding `bedrock_agent_runtime.retrieve(...)` call shape; carrying it forward into 11.03 would be useful for a reader implementing the medication-question path. Either include the real call in `knowledge_base_retrieve_and_answer` (with the mock taking over via the same boto3-client substitution pattern used elsewhere), or add an explicit "this is what the production call looks like" code comment block referencing recipe 11.1's pattern.

---

## Validation Notes

- The boto3 API surface used by the companion (`bedrock-runtime.invoke_model`, `bedrock-agent-runtime` client constructor, `dynamodb.Table().put_item`/`get_item`/`update_item`/`query`, `events.put_events`, `firehose.put_record`, `cloudwatch.put_metric_data`, `s3.put_object`, `secretsmanager.get_secret_value`, `comprehendmedical` client constructor) is correct against current SDK conventions. No method-name typos, no parameter-name drift.
- The `Decimal`-not-`float` discipline is consistent at every DynamoDB write boundary. Decimal-typed thresholds (`INTENT_CONFIDENCE_THRESHOLD`, `MED_RESOLUTION_CONFIDENCE_THRESHOLD`, `ASSURANCE_MATCH_THRESHOLDS`) compare correctly against incoming Decimal values from the classifier mock.
- S3 keys in `_write_refill_journal` have no leading slashes; the path structure `f"{INSTITUTION_ID}/{datetime.now(timezone.utc):%Y/%m/%d}/{record['event_id']}.json"` is correctly formed.
- The refill-claim verification regex `[A-Z]{2}-\d{4}-\d{3,}` matches the mock's `f"RX-2026-{...:07d}"` confirmation-ID format and is loose enough to survive a future format change. The `_find_supporting_eprescribe_call` walk over the tool-call ledger is the correct shape: it requires an `e_prescribe` entry with `outcome == "transmitted"` whose `result_summary.prescription_id` matches the claim's prescription_id.
- The controlled-substance triple defense is structurally correct and exercised by the `controlled_substance_routed` scenario: the protocol forces `controlled_substance_always_route`, the `_evaluate_protocol` re-check enforces it, the `e_prescribe_tool` refuses transmission, and the output-screen detection catches auto-approval language. All four layers fire on the demo's oxycodone scenario.
- The `_resolve_session_key` GSI-then-fallback pattern correctly addresses 11.01 W1 / 11.02 W1: in production the lookup uses `IndexName="session_id-index"`, in the demo the mock exposes `_find_session_key_by_session_id`. So `_update_session_flag` and `close_conversation_and_archive` both target the actual session row.
- The deploy-time guardrail asserting non-empty resource-name constants survives the carry-forward from 11.1 and 11.2.

---

## Recommended Changes Before Re-Review

1. Fix Eleanor's metformin fixture (`days_since_last_fill: 31` → something past the early-refill threshold like `92`) so the `happy_path_auto_approve` scenario actually exercises the auto-approval path the recipe sells. Verify by running `run_demo()`'s first scenario and confirming the disposition is `auto_approved` with a non-zero `refills_auto_approved`. (E1)
2. Fix the `_collect_identifiers_from_message` confirmation-factor regex to use the *last* standalone 4-digit sequence rather than the first, ideally as a shared helper across 11.01/11.02/11.03. (W1)
3. Phase-gate the `account_long` PHI check on the conversation phase so it does not fire during identity-verification turns where the bot has explicitly asked for a phone-shaped identifier. (W2)
4. Centralize assistant-turn writes through a helper that runs `screen_output` first, then appends, so the refill-claim verification covers every auto-approval confirmation message before it reaches the audit metadata. (W3)
5. Wire the session counters (`handoffs_offered`, `scope_violation_count`, `handoffs_accepted` via a new `record_user_feedback` hook) so the audit record's `final_disposition` logic and the per-cohort monitoring discipline both work end-to-end. (W4)

The four NOTE-level items are not blocking; they are quality-of-life improvements for future maintenance. The four WARNING/ERROR fixes above are the ones to land before the next review pass.

The architectural skeleton is sound, the boto3 surface is correct, the Decimal-not-float discipline is consistent, the S3 paths are properly formed, the refill-claim verification primitive is structurally correct, and the controlled-substance triple defense fires through every layer. The findings concentrate on (a) one fixture-data bug that breaks the headline auto-approval scenario, and (b) four misleading patterns that have been documented in prior 11.x reviews and continue to copy-forward into 11.03 without fixes. Re-running the review after the recommended changes should be quick.
