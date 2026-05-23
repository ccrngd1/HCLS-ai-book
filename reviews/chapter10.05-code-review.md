# Code Review: Recipe 10.5 — Patient-Facing Voice Assistant (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter10.05-python-example.md`
- `chapter10.05-patient-facing-voice-assistant.md` (cross-referenced for pseudocode-to-Python consistency)

**Verdict:** PASS

The companion runs end-to-end across all five demo scenarios (appointment confirmation with soft-personal step-up, Spanish-speaking patient with OTP step-up for refill, mid-conversation crisis preempt, clinical out-of-scope refusal, RAG-grounded facility info), correctly enforces the `Decimal`-not-`float` discipline for DynamoDB-bound numeric values, avoids hardcoded credentials, uses no leading slashes in S3 keys, and treats the recording-consent gate, the parallel crisis-detection discipline, the layered identity-verification flow, the runtime scope filter as defense-in-depth, the warm-handoff packet, and the cohort-stratified audit pipeline with the rigor the recipe demands. The boto3 client names used for Lex V2 (`lexv2-runtime`), Bedrock Runtime (`bedrock-runtime`), Bedrock Agent Runtime (`bedrock-agent-runtime`), Comprehend Medical (`comprehendmedical`), Polly, Pinpoint, Connect, EventBridge (`events`), CloudWatch, Secrets Manager, and the DynamoDB resource are all current and correctly named. The eight pseudocode steps map to eight Python entry points with the same step boundaries.

There are two notable WARNINGs (one about the mock RAG response shape diverging from the real `bedrock_agent_runtime.retrieve_and_generate` API, one about a misleading `response_format` reference that does not match the real `bedrock_runtime.invoke_model` parameter surface) plus a handful of NOTE-level improvements. None rise to ERROR severity, and the WARNING count (2) is under the FAIL threshold of 3.

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 0 |
| WARNING  | 2 |
| NOTE     | 12 |

---

## WARNING Findings

### W1. `MockBedrock.generate_rag_response` mocks a response shape that does not match `bedrock_agent_runtime.retrieve_and_generate`

**Files / sections:**
- "Mock Resources for the Demo" section, `MockBedrock.generate_rag_response`:
  ```python
  def generate_rag_response(self, query, retrieved_passages,
                              language="en-US"):
      # Production: bedrock_agent_runtime.retrieve_and_generate
      # with the institutional knowledge base ID, with
      # Bedrock Guardrails configured for clinical-advice
      # filtering.
      ...
      return {"body": json.dumps(response)}
  ```
- "Step 5" section, `fulfill_facility_info`:
  ```python
  rag_response = bedrock_mock.generate_rag_response(
      query=utterance,
      retrieved_passages=passages,
      language=session_context["language"])
  try:
      parsed = json.loads(rag_response["body"])
  ```

**What's wrong:**
The mock simulates the response of `bedrock_agent_runtime.retrieve_and_generate` (per the comment) but uses an `{"body": json.dumps(...)}` envelope, which is the response shape of `bedrock_runtime.invoke_model`, not `retrieve_and_generate`. The real `bedrock-agent-runtime` `RetrieveAndGenerate` API returns:

```python
{
    "sessionId": "string",
    "output":   {"text": "string"},
    "citations": [
        {"generatedResponsePart": {...},
         "retrievedReferences":   [...]}
    ],
    "guardrailAction": "INTERVENED" | "NONE",
}
```

There is no top-level `body` field, and the response body is not JSON-encoded — `output.text` is the natural-language reply directly, and citations are a structured list. A learner who copies the demo's `parsed = json.loads(rag_response["body"])` pattern into production hits `KeyError: 'body'` on the first real response, then has to discover the real shape. They will also find that the mock's `in_scope` and `source_passages` keys do not exist in the real response (production reads `output.text` and `citations`, not those fields).

The mock conflates two different APIs (`InvokeModel` and `RetrieveAndGenerate`) into a single shape, which obscures the boundary the recipe is teaching: when you use a Knowledge Base, you call `retrieve_and_generate` and parse the citation-bearing response; when you use a non-KB model directly, you call `invoke_model` and parse the streaming body.

**How to fix (suggested wording for the next pass):**
- Either rename the mock method to make the API surface explicit (e.g., `MockBedrock.invoke_model_for_rag` if it really mimics InvokeModel, or `MockBedrock.retrieve_and_generate` with a response shape that mirrors the real API):
  ```python
  return {
      "sessionId": "demo-session",
      "output":    {"text": response.get("text", "")},
      "citations": [{
          "generatedResponsePart": {"textResponsePart":
              {"text": response.get("text", "")}},
          "retrievedReferences":   retrieved_passages,
      }],
      "guardrailAction": "NONE",
      # Demo-only: an `_in_scope` private flag the demo's
      # response-handler uses to decide whether to refuse.
      # Real callers infer scope through Bedrock Guardrails
      # output and an explicit content-classification step.
      "_in_scope": response.get("in_scope", True),
  }
  ```
- Update the caller in `fulfill_facility_info` to read the real shape:
  ```python
  rag_response = bedrock_mock.retrieve_and_generate(...)
  response_text = rag_response["output"]["text"]
  in_scope_self_reported = rag_response.get("_in_scope", True)
  source_passages = rag_response.get("citations", [])
  ```
- Add a one-line comment near the call: `# Production response shape is {sessionId, output: {text}, citations: [...], guardrailAction}; the demo also adds a private _in_scope flag for the scope-filter teaching point.`

This is the single thing in the file that is most likely to mislead a reader translating the demo into a real Knowledge Base integration.

---

### W2. The "JSON-schema response_format" comment misrepresents `bedrock_runtime.invoke_model`'s parameter surface

**Files / sections:**
- "Mock Resources for the Demo" section, `MockBedrock.classify_intent`:
  ```python
  def classify_intent(self, utterance, available_intents,
                       conversation_history):
      # Production: bedrock_runtime.invoke_model with a strict
      # JSON-schema response_format and the conversation
      # history in the prompt context.
  ```
- "The Gap Between This and Production" section, "Real Bedrock invocation with a versioned prompt and inference profile" paragraph references the same pattern.

**What's wrong:**
`bedrock_runtime.invoke_model` does not have a `response_format` parameter. Its surface is:

```python
bedrock_runtime.invoke_model(
    modelId="anthropic.claude-3-haiku-20240307-v1:0",
    body=json.dumps({...model-specific request body...}),
    contentType="application/json",
    accept="application/json",
    guardrailIdentifier="...",  # optional
    guardrailVersion="...",      # optional
    trace="ENABLED" | "DISABLED" # optional
)
```

The `body` is a model-specific JSON request (Anthropic Claude expects `{"anthropic_version": "...", "messages": [...], "max_tokens": ..., "system": "..."}`); structured output for Anthropic models on Bedrock is enforced through tool-use (the `tools` field inside the body) or through a system prompt that demands JSON, not through a top-level `response_format` parameter. The phrasing "JSON-schema response_format" is OpenAI-flavored terminology that does not apply to Bedrock InvokeModel and is the kind of detail a learner trying to enforce structured intent classification will get stuck on.

The Converse API (`bedrock_runtime.converse`) has more structured affordances (`additionalModelRequestFields`, `toolConfig`), but it still does not surface a `response_format` parameter; OpenAI-style `response_format` on Bedrock would only apply if you were using one of the OpenAI-compatible models proxied through a third-party gateway.

**How to fix:**
- Replace the comment with something like: `# Production: bedrock_runtime.invoke_model with modelId pinned to the inference profile ARN and body containing the Anthropic Claude messages-and-system-prompt request. Structured intent output is enforced through Anthropic's tool-use (the tools field inside the body) or through a system prompt that demands JSON; there is no top-level response_format parameter on InvokeModel.`
- In the "Gap" section's "Real Bedrock invocation" paragraph, replace "with `modelId` pinned to the inference profile ARN" with the same correction so the prose and the comment agree.

---

## NOTE Findings (improvements; not blocking)

### N1. `crisis_flags` field is initialized but never populated

In `open_conversation` (Step 1), the conversation_state is bootstrapped with `"crisis_flags": []`. In `handle_crisis` (Step 2), the code updates `crisis_detected`, `crisis_severity`, `crisis_category`, and `crisis_matched_phrase` directly as scalar fields, but never appends to `crisis_flags`. The `build_warm_handoff_packet` reads `state.get("crisis_flags", [])`, so the field always serializes as an empty list in the screen-pop packet, even when crisis routing fired.

The audit record then gets the actual crisis details from the scalar fields (`crisis_detected`, `crisis_severity`, `crisis_category`), so forensic review still works. But the warm-handoff packet's `crisis_flags: []` for a crisis-routed conversation is misleading: an agent reading the packet sees scalar `crisis_detected: true` plus an empty `crisis_flags` array and may wonder which is authoritative.

Either populate `crisis_flags` in `handle_crisis` (appending each detection event with timestamp, category, and matched phrase, so multi-turn conversations that trigger more than one crisis signal show up correctly), or drop the field entirely from the state schema and the warm-handoff packet, and rely solely on the scalar fields. The append-to-list pattern is a better fit for a multi-turn conversation where a patient might first mention urgent symptoms and later explicit suicidal ideation, where you want both events in the audit, but the demo would need to demonstrate it.

### N2. Identity-verification spoken prompts are hardcoded in English even when `language=es-US`

In `ensure_identity_for_intent`, the prompts returned to the caller are English-only:

```python
return {"satisfied": False,
        "reason":    "soft_personal_dob_required",
        "prompt":    ("To look up your record, can "
                      "you please tell me your "
                      "date of birth?")}
```

```python
"prompt":    (f"Im sending a six-digit code "
              f"to your phone ending in "
              f"{destination[-4:]}. Please "
              f"read it back to me when you "
              f"receive it.")
```

In Scenario 2 (Marisol, `language=es-US`), the demo runs through both the soft-personal DOB prompt and the OTP prompt in English, despite the captured language preference and the registry's `preferred_language: "es-US"`. The recipe stresses multilingual deployment as a launch gate ("Multilingual deployment beyond English plus Spanish... defer launch in languages where the per-language assets are not ready rather than launching with English-quality and shipping a degraded experience"), but the demo does not exercise per-language identity prompts.

Two reasonable fixes:
- Build a small per-language prompt table at module level (next to `GREETING_BY_LANGUAGE`):
  ```python
  IDENTITY_DOB_PROMPT = {
      "en-US": "To look up your record...",
      "es-US": "Para revisar su informacion...",
  }
  ```
  and resolve the prompt by `session_context["language"]`.
- Or add an explicit comment at the top of `ensure_identity_for_intent`: `# All prompts in this function are hardcoded English for demo simplicity. Production resolves prompts from a per-language template table; the multilingual gap is one of the launch-gate items in the production-readiness checklist.`

This is the most visible place where the demo's per-language coverage falls short of what the recipe claims. The Marisol scenario is the right place to demonstrate it.

### N3. Module-level boto3 clients are constructed but never invoked in the demo

`dynamodb`, `s3_client`, `lex_client`, `bedrock_runtime`, `bedrock_agent_runtime`, `comprehend_medical`, `polly_client`, `pinpoint_client`, `connect_client`, `eventbridge_client`, `cloudwatch_client`, and `secrets_client` are all created at import time. The demo uses only the mocks. The block's comment correctly explains the warm-container reuse rationale, but a learner is staring at twelve lines of unused client setup on first read. Same issue noted in 10.03 N2 and 10.04 N6. Suggest adding the same one-line clarification: `# These boto3 clients are declared at module level so a real Lambda deployment reuses them across warm invocations. The demo below uses Mock* classes instead; the real clients are never invoked here.`

(Acceptable as-is for teaching code, but worth noting for consistency with the chapter's style.)

### N4. `from typing import Optional` is imported but never used

Same as 10.03 N3 and 10.04 N7. Drop the import or use it on a return-type hint where it would help (e.g., `_resolve_opt_in_age_band(patient_id) -> Optional[str]`).

### N5. Several Bedrock configuration constants are defined but never referenced

`BEDROCK_INTENT_FALLBACK_MODEL_ID`, `BEDROCK_RESPONSE_GENERATION_MODEL_ID`, and `BEDROCK_RESPONSE_PROFILE_ARN` are all declared in "Configuration and Constants" but never read by any function in the demo (the mocks do not consult them). A learner trying to follow the configuration-to-call-site path is left without an anchor. Suggest either:
- Plumbing them through to `MockBedrock` (e.g., the mock could record which model_id and inference_profile_arn it was "called with" for demo visibility, even though the response is fixture-driven), or
- Adding a one-line comment near the constants: `# These are the model and inference-profile identifiers a real bedrock_runtime.invoke_model call would use. The MockBedrock below does not consult them; production reads them at call time and pins the invocation to the named profile for cross-region inference and per-profile rate limits.`

### N6. `_now_iso()` returns `+00:00` offset, not `Z`, so most `replace("Z", "+00:00")` calls are no-ops

`_now_iso()` calls `datetime.now(timezone.utc).isoformat()`, which produces strings like `"2026-05-23T16:11:12.345678+00:00"` — never with a trailing `Z`. The defensive `.replace("Z", "+00:00")` calls on lines 750 (`MockIdentityVerification.verify_otp`'s `expires_at`), 2257, and 2259 (`close_conversation_and_audit`'s duration computation) operate on values that came from `_now_iso()` and are therefore no-ops.

The `.replace("Z", "+00:00")` on line 1774 in `format_appointment_response`, however, is needed because the `MockEHR` fixture data uses `Z` suffixes for ISO timestamps (`"start": "2026-06-17T18:30:00Z"`). So the pattern is genuinely needed in one place and harmlessly cargo-culted in three others.

For pedagogical clarity, suggest either:
- Change `_now_iso()` to produce `Z`-suffixed strings (`return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`) so the `.replace("Z", "+00:00")` pattern is consistently meaningful everywhere, or
- Add a comment at the no-op sites: `# The replace is defensive: _now_iso() emits +00:00 already, but external timestamp sources (the MockEHR fixture uses Z) need the normalization.`

Tiny, but reading the same-looking line three times where it does different things is the kind of detail that obscures the teaching points.

### N7. Crisis-detection vocabulary is English only; the Marisol (es-US) scenario does not exercise multilingual crisis matching

`CRISIS_KEYWORDS` contains English phrases only. The recipe is explicit that "Multilingual crisis vocabulary requires native-speaker clinical input, not just translation" and lists multilingual coverage as a launch gate. Scenario 3 in the demo (chest pain mid-conversation) uses Walter's English session, so the gap is invisible in the demo output.

The "Gap Between This and Production" section addresses this with the "Real crisis-detection program" paragraph, but the demo does not have a single Spanish utterance that exercises (or fails to exercise) the detector. Suggest adding either:
- A per-language `CRISIS_KEYWORDS_BY_LANGUAGE = {"en-US": {...}, "es-US": {...}}` map (with at least one entry per category in Spanish), and a `detect_crisis(utterance, language)` signature that consults the per-language list, or
- An explicit comment in `detect_crisis`: `# CRISIS_KEYWORDS contains English phrases only. A Spanish-speaking patient saying "dolor en el pecho" (chest pain) would not match. Production maintains a per-language keyword table with native-speaker clinical input on each language; see the production-readiness gap section.`

The Marisol scenario is the obvious place to demonstrate the per-language path, even if the implementation is a small extension.

### N8. Crisis detection runs synchronously before intent classification, not in parallel as the architecture stipulates

The architecture diagram and the "PARALLEL CRISIS DETECTION" stage in the main recipe explicitly call out: "It is not a stage that comes after intent classification; it runs simultaneously and can preempt at any point in the conversation. The architecture wires it as a parallel pass over every utterance with a hard-interrupt callback into the dialog manager." The Python's `on_utterance_received` runs the detector first and returns early on crisis; intent classification only runs if no crisis is detected.

The "Heads up" intro acknowledges this trade-off explicitly: "The demo runs the detector synchronously before intent classification on each utterance; production runs both in parallel and races them with a hard-interrupt callback." Good. But for completeness, add a parallel callout inside `on_utterance_received` itself so a reader who skips the intro doesn't miss it:

```python
# Step 2A: crisis detection runs on every utterance,
# regardless of dialog state. The demo runs the detector
# synchronously here for simplicity; production runs the
# detector and the intent classifier in parallel via
# asyncio (or a Step Functions Parallel branch) and
# races them, with a hard-interrupt callback that
# preempts dialog state when crisis is detected.
crisis_signal = detect_crisis(utterance)
```

This is consistent with how 10.04's review treated the "structural events computed but never applied" gap: the implementation choice is fine for teaching, but the divergence from the architecture deserves a stronger inline callout.

### N9. Caregiver-proxy resolution path is initialized but never implemented; `caregiver_context` is always None

`open_conversation` initializes `"caregiver_context": None`. `build_warm_handoff_packet` reads it. `close_conversation_and_audit` reads it via `(state.get("caregiver_context") or {}).get("relationship_type")`. But no function ever sets it: there is no `resolve_caregiver_context` helper as the pseudocode's Step 4B implies, and `ensure_identity_for_intent` does not consult any caregiver-relationship table.

The "Gap" section addresses this ("The demo handles only the patient-themselves identity case. Production additionally supports caregiver-proxy interactions"), so the gap is documented. But the persistent presence of `caregiver_context` plumbing throughout the code, with no path to populate it, may suggest to a reader that the field will be filled in by some hidden mechanism. Either:
- Wire a minimal caregiver lookup in `soft_personal_check` (e.g., the patient registry's record could include a `caregivers: [...]` list, and the lookup returns the matched caregiver if the caller-ID matches a caregiver entry rather than the patient), even if no scenario exercises it, or
- Add a comment at the field-initialization site: `# caregiver_context stays None throughout the demo. Production populates it via a caregiver-relationship lookup against the EHR's authorized-caregiver table; see the production-readiness checklist.`

The first option is more useful as teaching code because it shows where the lookup belongs. The second is acceptable if the chapter is intentionally deferring the caregiver scenario.

### N10. `MockS3.put_object` and `MockPolly.synthesize_speech` use lowercase parameter names, differing from real boto3's PascalCase

The mocks use Pythonic snake_case for parameters:

```python
s3_store.put_object(bucket=AUDIT_ARCHIVE_BUCKET, key=..., body=..., metadata=...)
polly_mock.synthesize_speech(text=..., voice_id=..., language_code=..., lexicon_names=...)
```

Real boto3 expects PascalCase:

```python
s3_client.put_object(Bucket=..., Key=..., Body=..., Metadata=...)
polly_client.synthesize_speech(Text=..., VoiceId=..., Engine="neural", LanguageCode=..., LexiconNames=...)
```

A reader who replaces the mocks with real clients will hit `TypeError: put_object() got an unexpected keyword argument 'bucket'` and have to retranslate every parameter name. Same pattern shows up in 10.03 and 10.04 reviews. Suggest adding a comment near the mock signatures: `# Real boto3 expects PascalCase parameter names (Bucket, Key, Body, Metadata). The mock uses snake_case so the demo reads naturally; production callers translate at the boundary.`

### N11. `MockPinpoint.send_otp` records the plaintext OTP in `delivered_otps`; production never persists the plaintext anywhere

The mock stores:

```python
self.delivered_otps.append({
    "destination":  destination,
    "code":         code,        # plaintext OTP
    "channel":      channel,
    "delivered_at": _now_iso(),
})
```

This is fine for the demo (it lets `run_demo` show what was sent), and `audit_log` correctly never logs the OTP code. But a reader translating the mock pattern to production needs to know that the real Pinpoint OTP API (`send_otp_message`) returns a delivery receipt that the caller can persist for analytics, but the OTP code itself is never returned by the API and is never stored anywhere by the institution; only the salted hash that `MockIdentityVerification.issue_otp` writes is persisted. Suggest a one-line comment: `# Demo-only: the plaintext OTP is recorded so run_demo can show what would have been sent. Production never stores the plaintext OTP anywhere; only the salted hash in MockIdentityVerification.issue_otp is persistent. The OTP code is also never returned by the real Pinpoint send_otp_message API.`

Related: `issue_otp` returns `{"_demo_code": code}` and that field bubbles up through `ensure_identity_for_intent` and into `handle_turn`'s return value. Similarly demo-only, similarly worth a one-line callout to remind the reader that this is a fixture affordance, not a production pattern.

### N12. Scope-filter matching in `scope_filter_check` is regex-based and case-insensitive only by `text.lower()`, not by `re.IGNORECASE`

`scope_filter_check` does:

```python
text = response_text.lower()
for category, patterns in SCOPE_VIOLATION_PATTERNS.items():
    for pattern in patterns:
        if re.search(pattern, text):
```

Lowercasing the input is fine for the patterns as written, but the regex patterns themselves don't use `\b` word boundaries on every term, and the `.lower()` strips information like "I" vs "i" that some patterns may want preserved (e.g., distinguishing "I recommend" from a misspelled "i recommend"). More importantly, a learner extending `SCOPE_VIOLATION_PATTERNS` with a pattern that includes uppercase letters (e.g., `r"\bMG\b"` for milligram dosing) will silently never match because the input is already lowercased. Suggest either:
- Drop `text = response_text.lower()` and use `re.search(pattern, response_text, re.IGNORECASE)` so case-insensitivity is explicit and the patterns can use whatever case the author intends, or
- Document the lowercase-input convention at the top of `SCOPE_VIOLATION_PATTERNS`: `# Patterns must be authored in lowercase; scope_filter_check lowercases the input before matching.`

The current behavior is correct for the demo's pattern set, but the failure mode for a future contributor extending the list is silent.

---

## What I checked and confirmed is correct

- **boto3 client and API names are accurate** for Lex V2 (`lexv2-runtime` with `recognize_text`), Bedrock Runtime (`bedrock-runtime` with `invoke_model`), Bedrock Agent Runtime (`bedrock-agent-runtime` with `retrieve_and_generate`), Comprehend Medical (`comprehendmedical` with `infer_rx_norm`, `detect_entities_v2`, `infer_icd10_cm`), Polly (`polly` with `synthesize_speech`, `put_lexicon`), Pinpoint (`pinpoint` with `send_otp_message`, `send_messages`), Connect (`connect` with `update_contact_attributes`, `start_outbound_voice_contact`), EventBridge (`events` with `put_events`), CloudWatch (`cloudwatch` with `put_metric_data`), Secrets Manager (`secretsmanager` with `get_secret_value`), and the DynamoDB resource (`boto3.resource("dynamodb")`). The IAM action names listed in Setup (`lex:RecognizeText`, `bedrock:InvokeModel`, `bedrock-agent-runtime:Retrieve`, `bedrock-agent-runtime:RetrieveAndGenerate`, `bedrock:ApplyGuardrail`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM`, `transcribe:StartStreamTranscription`, `polly:SynthesizeSpeech`, `polly:GetLexicon`, `pinpoint:SendMessages`, `pinpoint:SendOTPMessage`, `events:PutEvents`, `cloudwatch:PutMetricData`, `kms:Decrypt`, `kms:GenerateDataKey`, `states:StartExecution`) are correct.
- **Decimal usage for DynamoDB-bound values is correct.** `_to_decimal` recursively converts `float` through `Decimal(str(value))` (avoiding the float-to-Decimal precision pitfall), passes `Decimal` and other types through unchanged, and walks dicts and lists. ASR confidence values are computed as Decimal at entry (`asr_avg_confidence=Decimal("0.92")` defaults). Lex confidence is wrapped at `Decimal(str(interpretation["nluConfidence"]["score"]))`. LLM confidence at `Decimal(str(parsed.get("confidence", 0.0)))`. Comprehend Medical extraction confidence at `Decimal(str(best.get("Score", 0.0)))`. Duration in `close_conversation_and_audit` is wrapped as `Decimal(str(duration))`. The `audit_record` dict is wrapped through `_to_decimal` before persistence. The `conversation_state.put` and `.update` calls that include numeric values are wrapped through `_to_decimal`. No bare `float` slips through to a DynamoDB-bound write.
- **No S3 keys with leading slashes.** All `s3_store.put_object` calls use keys like `audit/2026/05/23/conv-xxxxxxxx.json`. Each starts with the prefix segment, never a `/`.
- **No hardcoded credentials.** Module-level boto3 clients use the default credential resolution chain. The fictitious phone numbers (`+15555550143`, `+15555550199`, `+15555550111`) and patient identifiers (`pt-44219`, `pt-77310`, `pt-99001`) are obviously synthetic; the example callout in the prose calls this out explicitly. The OTP salt (`secrets.token_hex(16)`) is generated per issuance via `secrets`, not hardcoded.
- **`audit_log` strips PHI fields** (`verbatim_transcript`, `patient_demographics`, `otp_code`, `raw_response_text`, `patient_dob`) before structured logging and substitutes lengths for the dropped string fields. Operational fields (`session_id`, `intent`, `severity`, `confidence`, `disposition`, `target_queue`) are retained appropriately. The `_demo_otp_code` field is never directly passed to `audit_log` — it only flows back through return values.
- **OTP storage uses HMAC-SHA256 with a per-issuance salt.** `_hash_otp(code, salt)` does `hmac.new(salt, code, hashlib.sha256).hexdigest()`. The verification side uses `hmac.compare_digest(...)` for constant-time comparison, which is the correct primitive for OTP verification (avoids timing oracles).
- **OTP issuance has a TTL and an attempt counter.** `MockIdentityVerification.issue_otp` writes `expires_at = now + 5 minutes` and `attempts = 0`. `verify_otp` checks expiry first, increments attempts, fails closed when attempts exceed `OTP_MAX_ATTEMPTS`, and marks the issuance `consumed: True` on success so the same code cannot be replayed.
- **Adaptive retry config** (`Config(retries={"max_attempts": 3, "mode": "adaptive"})`) is reasonable for the conversational latency budget.
- **Cohort-stratified CloudWatch metrics** carry the channel, language, region_hint dimensions for every audit-relevant metric (`ConversationDuration`, `ContainmentRate`, `ASRAvgConfidence`, `IntentClassificationConfidence`, `IdentityVerificationOutcome`, `FulfillmentOutcome`, `ScopeViolationsCaught`, `ConversationsStarted`, `CrisisDetected`, `ConversationEscalated`). The `_resolve_opt_in_age_band` helper returns `"not_disclosed"` rather than inferring demographic labels for protected classes, which is the discipline the prose calls out.
- **Versioning fields** (`LEX_BOT_VERSION`, `INTENT_FALLBACK_PROMPT_VERSION`, `RESPONSE_GENERATION_PROMPT_VERSION`, `CRISIS_DETECTION_RULES_VERSION`, `SCOPE_FILTER_RULES_VERSION`, `IDENTITY_POLICY_VERSION`) are stamped on the conversation-metadata record at session open and carried through to the final audit record. A future review can reconstruct which configuration was active for any given conversation.
- **Recording-consent jurisdiction logic is implemented as the stricter-regime-wins rule.** `determine_consent_regime` looks up the caller's likely state by area code and treats either-side-all-party as triggering the all-party disclosure. The logic is acknowledged as a small fixture in the comments ("production looks up the caller's likely jurisdiction by area code, registered address, or a third-party number-lookup service").
- **The eight pseudocode steps map to eight Python entry points** with the same step boundaries: `open_conversation` (Step 1), `on_utterance_received` (Step 2 with `detect_crisis` and `handle_crisis`), `classify_and_extract` (Step 3 with `classify_intent` and `extract_medication_slot`), `ensure_identity_for_intent` (Step 4 with `soft_personal_check` and `issue_otp`), `fulfill_intent` (Step 5 with per-intent fulfillment helpers), `speak_response` (Step 6 with `scope_filter_check` as defense-in-depth), `warm_transfer` (Step 7 with `build_warm_handoff_packet` and `summarize_conversation_for_agent`), and `close_conversation_and_audit` (Step 8 with cohort-stratified metric emission). The pseudocode-to-Python correspondence is faithful, with the deviations called out in N1, N7, N8, and N9.
- **End-to-end demo runs deterministically across all five scenarios.** Tracing through:
  1. Walter / appointment confirmation → Lex matches `confirm_appointment` at 0.94, soft-personal step-up requested, DOB `1943-10-14` matches the registry, EHR returns one Cardiology appointment, formatted response speaks back to Walter, contained.
  2. Marisol / refill with OTP step-up → Lex matches `request_refill` at 0.93, Comprehend Medical extracts `lisinopril` with RxNorm code `29046`, soft-personal then PHI-disclosing step-up requested, DOB matches, OTP issued and verified on the third turn, refill ticket `refill-xxxxxxxx` created and queued for clinical review, contained.
  3. Walter / appointment then crisis → first turn classifies `confirm_appointment` and asks for DOB (awaiting_identity), second turn includes "chest pain" which triggers `acute_medical_emergency` crisis detection, immediate response spoken, warm-transfer to `nurse-triage-emergency` with crisis flags in the packet, audit record reflects `final_disposition: crisis_routed`.
  4. Anonymous / clinical out-of-scope → Lex matches `out_of_scope_clinical` at 0.88, the `handled: true` early-return path fires, refusal-and-transfer phrase spoken, warm-transfer to `nurse-triage-general`, audit record reflects `transfer_after_refusal`.
  5. Anonymous / facility info via RAG → Lex matches `facility_info` at 0.90, RAG retrieval returns one passage about lab hours, the LLM response is in-scope and passes the scope filter, response spoken, contained.
- **The "Why This Isn't Production-Ready" section in the main recipe and the "The Gap Between This and Production" appendix in the Python file** correctly flag the production-hardening concerns (real Connect contact flow with consent-acknowledgment gating of recording, real Lex V2 bot with per-language locales and slot prompts, real Bedrock invocation with versioned prompts and inference-profile pinning, real Bedrock Knowledge Bases with curated content lifecycle, real Bedrock Guardrails with denied-topics and PHI-redaction filters, real Comprehend Medical wiring with the three-API merge, real Polly with custom-pronunciation lexicons, real Pinpoint OTP with per-region SMS infrastructure, real API Gateway WebSocket plus Cognito for the app channel, per-Lambda IAM, customer-managed KMS per data class, S3 lifecycle and Object Lock, VPC and VPC endpoints, real recording-consent jurisdiction logic, real crisis-detection program with named clinical ownership, real scope-containment continuous-review program, per-cohort accuracy launch gates, real warm-handoff screen-pop integration, real caregiver-proxy enrollment and resolution, DTMF fallback, smart-speaker certification, real EHR integration depth, DR and degraded-mode operation, idempotency-before-execution for write paths, performance under load and burst, audio retention with privacy-officer review, audit-log retention and legal hold, cost monitoring per channel and per intent, vendor-evaluation rigor for build-vs-buy, operational ownership across multiple teams, and tests). These are not expected to live in the example code itself.

---

## Verdict

**PASS** with two WARNINGs and twelve NOTEs. The two WARNINGs (W1: the `MockBedrock.generate_rag_response` shape diverges from the real `retrieve_and_generate` API, and W2: the `response_format` reference does not match `bedrock_runtime.invoke_model`'s parameter surface) are both worth fixing before publication: W1 is the most likely thing to trip up a reader translating to production Knowledge Bases, and W2 misleads readers about how to enforce structured LLM output on Bedrock for Anthropic models. The NOTEs are pedagogical polish and can be addressed by the editor in the final pass.

The eight-step pseudocode-to-Python correspondence is faithful and complete (with the identified gaps in caregiver resolution, multilingual prompts, and parallel crisis detection acknowledged in the prose). The Decimal-not-float discipline, the no-leading-slash S3 keys, the runtime scope filter as defense-in-depth, the layered identity verification with TTL-bounded HMAC-stored OTPs, the cohort-stratified audit pipeline that excludes inferred protected-class labels, the warm-handoff packet that includes enough context for the receiving agent, and the recording-consent stricter-regime-wins logic are all in place and correctly demonstrated by the five scenarios.
