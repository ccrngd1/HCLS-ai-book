# Open TODOs: Recipe 11.10: Clinical Trial Recruitment Conversationalist

> Remaining items after findings resolution pass (2026-06-22).

All expert-review and code-review findings have been resolved. No remaining open items.

## Resolved This Pass

- **Code Review Issue 1 (WARNING):** Added `compute_prescreen_disposition` aggregator that derives the disposition from per-criterion evaluation outcomes rather than trusting the raw `prescreen_state` field. The chat handler now calls this aggregator before persisting the recruitment-decision record.
- **Code Review Issue 2 (WARNING):** Added end-of-turn responses for Turns 1 and 2 in `_seed_scripted_model_responses` so every demo turn cleanly brackets its tool call with a corresponding end-of-turn text that references the tool result.
- **Code Review Issue 3 (NOTE):** Wired `record_funnel_stage` into natural transition points: `receive_conversation_turn` (ENTERED), `tool_eligibility_response_capture` (PRESCREEN_STARTED on first criterion), `tool_prescreen_save_progress` (PRESCREEN_COMPLETED on final disposition), and `tool_coordinator_handoff_request` (HANDOFF_SCHEDULED).
- **Code Review Issue 4 (NOTE):** Replaced single-disclosure substring check with illustrative keyword matching across all seven required first-turn disclosures, with comment noting production uses an IRB-approved token taxonomy.
- **Code Review Issue 5 (NOTE):** Added comment block explaining symbolically-exercised clients (secrets_client, pinpoint_client).
- **Code Review Issue 6 (NOTE):** Added inline comment on zip5 pattern noting over-match behavior and production approach (managed PII-detection service).
- **Code Review Issue 7 (NOTE):** Strengthened inline comment on post-hoc metadata filter to clarify it is defense-in-depth, not the primary isolation mechanism.
- **Code Review Issue 8 (NOTE):** Added Guardrail stub call with full boto3 parameter shape (`apply_guardrail` with `guardrailIdentifier`, `guardrailVersion`, `source`, `content`) wrapped in try/except for the mock.
