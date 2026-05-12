# Code Review: Recipe 2.10 - Multi-Modal Clinical Reasoning

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-12
**Files reviewed:**
- `chapter02.10-multi-modal-clinical-reasoning.md` (main recipe, pseudocode)
- `chapter02.10-python-example.md` (Python companion)

**Validation performed:**
- Nine-step pseudocode walked against Python functions, one-to-one
- boto3 Bedrock Runtime `invoke_model` parameters, Anthropic Messages API body, and response traversal verified
- boto3 Bedrock Guardrails `guardrailIdentifier` / `guardrailVersion` parameter names verified; `amazon-bedrock-guardrailAction` intervention field verified (see Finding 3)
- boto3 Comprehend Medical `detect_entities_v2` call shape verified; UTF-8 byte-count truncation used on every call
- boto3 S3 `put_object` with SSE-KMS (`ServerSideEncryption="aws:kms"`, `SSEKMSKeyId`) verified
- boto3 DynamoDB `put_item` / `update_item` calls; reserved-word `status` aliased via `ExpressionAttributeNames` verified
- boto3 CloudWatch `put_metric_data` shape verified
- S3 keys checked for leading slashes (none present)
- Every numeric value that flows into DynamoDB inspected for Python-float writes (all routed through `_to_decimal_safe` or are ints)
- Generation/validation retry loop traced for all exhaustion paths (see Finding 1)
- Module scanned for duplicate function definitions (see Finding 2)
- Citation regex replacement in Step 9 traced for substring-overlap issues (no issue found; `re.sub` with bracketed pattern is safe)
- Healthcare concerns reviewed: PHI logging, BAA, encryption (SSE-KMS), synthetic data labeling, minimum-necessary, retention, provenance/validation, deterministic safety checks (reused from 2.9), FDA CDS exemption posture, licensing registry, missing-modality acknowledgment, graded-term preservation, cross-modality contradiction surfacing

---

## Verdict: PASS

No ERROR findings. Two WARNING findings, both at the boundary of the orchestrator and the validator (the same spots as the Recipe 2.9 review). Several NOTE findings on pedagogical polish, documented stubs, and pseudocode-to-Python consistency gaps.

The code is well-constructed. The nine pseudocode steps map cleanly to nine Python functions (with Step 2 expanded into five parallel ingestion functions per modality). boto3 usage is current and correct. DynamoDB `Decimal` handling is disciplined via `_to_decimal_safe`. S3 keys are clean. SSE-KMS is set on every archive write. The heads-up block at the top is thorough about labeling everything SYNTHETIC and enumerating the production gaps. Each step's docstring references the pseudocode function name, which makes the two-file navigation easy.

What keeps this out of "unqualified pass" territory is two WARNINGs in the safety spine. First, the orchestrator auto-delivers reasoning when validation terminates with `REVIEW_REQUIRED` after exhausted retries (same pattern as Recipe 2.9 Finding 1; even higher stakes here because the reasoning layer touches imaging and cross-modality synthesis). Second, `_collect_all_citations` is defined twice in the file, and the second definition silently shadows the first, disabling the inline-citation text scan that the Step 8 validator depends on.

Both WARNINGs are fixable with small, localized changes.

---

## Summary

The nine-step pseudocode maps one-to-one onto the Python: `start_reasoning_run` → `ingest_imaging` / `ingest_ecg` / `ingest_labs_and_vitals` / `ingest_notes` / `ingest_structured_context` → `normalize_and_inventory` → `scope_gate` → `run_safety_checks` (stub pointing at Recipe 2.9) → `retrieve_supporting_content` → `invoke_reasoning_layer` → `validate_reasoning` → `tier_render_archive`, with `run_multi_modal_reasoning` chaining them and handling the defer-by-scope-gate, grounding-rejected, and validation-retry paths.

The boto3 mechanics are textbook-correct. `invoke_model` uses the Anthropic messages body shape with `anthropic_version`, `max_tokens`, `temperature`, `system`, and `messages`. `guardrailIdentifier` / `guardrailVersion` are the current parameter names and are attached conditionally when both are configured. The contextual-grounding response signal is read from `amazon-bedrock-guardrailAction`, which is correct. `comprehend_medical.detect_entities_v2` is used with UTF-8 byte-count truncation via `_safe_utf8_truncate` on every call (not character-count), which correctly avoids the Comprehend Medical byte limit. S3 `put_object` sets `ServerSideEncryption="aws:kms"` with `SSEKMSKeyId` on both archive writes, and both keys (`reasoning-runs/{run_id}/rendered.json`, `reasoning-runs/{run_id}/trace.json`) have no leading slash.

The DynamoDB discipline is consistent. `_to_decimal_safe` walks dicts and lists recursively and routes floats through `Decimal(str(value))`, which avoids the binary-precision drift that `Decimal(float_value)` introduces. Every `put_item` goes through this helper. Every `update_item` in the code passes strings and ints only via `ExpressionAttributeValues`; no Python float reaches DynamoDB. The reserved word `status` is aliased with `ExpressionAttributeNames={"#s": "status"}` at every `update_item` call.

The citation renumbering in Step 9 (`tier_render_archive`) uses `re.sub(r"\[([^\]]+)\]", _sub, text)` with a substitution function that looks up the bracketed ID in `id_to_source` and returns the original match if the ID is unknown. This avoids the substring-overlap bug that Recipe 2.9 had with `str.replace` on bare tokens (Recipe 2.9 Finding 2). The 2.10 approach is cleaner.

Where the code falls short is the same pair of safety-spine issues that show up in 2.9 plus one that is specific to 2.10. The orchestrator treats `REVIEW_REQUIRED` as equivalent to `VALIDATED` after the retry loop: both `break` out, both fall through to Step 9, both end up with `status = DELIVERED` in DynamoDB. A reasoning output that failed validation for citation-not-in-retrieved-set, quantity-not-verbatim, graded-term-not-in-sources, safety-finding-missing, or directive-language-in-model-voice will ship to the clinician-facing UI marked as a successful delivery. The validator's own terminal log message says "routing to review (%d HIGH, %d MEDIUM)," but the orchestrator does not route it anywhere.

Separately, `_collect_all_citations` is defined twice. The first definition (in Step 8) is the intended validator helper and includes a text scan for inline bracketed citations (`[imaging:1.2.3]`, `[lab:2160-0]`) that the model emits in description fields even when `source_citations` is incomplete. The second definition (in "Putting It All Together") is a shorter version that the docstring claims is "Used in the pipeline's id_to_source fallback; see Step 8 above" but silently overrides the Step 8 version when Python evaluates the file. Python uses the last definition of a name, so the validator ends up using the shorter helper that does not scan text. Inline-only citations to unknown source_ids would not be flagged as missing by the validator. This weakens the citation-discipline guarantee that the prompt, Guardrail, and validator triangulate together.

The NOTE findings cover the same pattern of editorial polish as the Recipe 2.9 review: a dead-code arm in the guardrail-action tuple, a coarse character-slice on the structured context, documented stubs (HealthImaging, HealthLake, Aurora, OpenSearch, ECG foundation model, cleared imaging AI vendor), pseudocode-to-Python coverage gaps (cross-modality consistency scan and scope compliance not implemented in the validator), unused parameters in `_build_sources_block`, and an `_synthetic_ecg_records` helper that returns empty for both branches despite a comment suggesting otherwise.


---

## Findings

### Finding 1: Orchestrator auto-delivers reasoning when validation returns `REVIEW_REQUIRED`

- **Severity:** WARNING
- **Location:** `chapter02.10-python-example.md`, `run_multi_modal_reasoning` orchestrator (the generation/validation retry loop and the subsequent Step 9 fall-through)
- **Description:** The retry loop breaks on both `VALIDATED` and `REVIEW_REQUIRED`:
  ```python
  if validation_result["status"] == "VALIDATED":
      break
  if validation_result["status"] == "REVIEW_REQUIRED":
      break
  regeneration_hint = validation_result.get(
      "suggested_prompt_augmentation", "",
  )
  ```
  After the loop, the only gate on proceeding to Step 9 is:
  ```python
  if not generation_result or generation_result["status"] != "GENERATED":
      # failure path: writes GENERATION_FAILED
  ```
  When validation exits with `REVIEW_REQUIRED`, `generation_result["status"]` is still `"GENERATED"`, so this failure gate does not fire. The code falls through to `tier_render_archive`, which updates the DynamoDB record to `status = "DELIVERED"` and returns the rendered payload to the caller.

  The practical consequence for a clinician-facing multi-modal reasoning surface: a reasoning output that failed validation after `MAX_GENERATION_ATTEMPTS` attempts for reasons including `citation_not_in_retrieved_set`, `quantity_not_verbatim`, `graded_term_not_in_sources`, `safety_finding_missing`, or `directive_language_in_model_voice` will ship marked as a successful delivery. The validator's own terminal log line says "Validation exhausted retries; routing to review," but the orchestrator does not route it anywhere. The trace archive in S3 does retain `validation_result` under `trace.validation_result`, so a post-hoc audit can detect the slip, but the real-time safety posture the validator is designed to provide is bypassed.

  This is the same failure pattern flagged in Recipe 2.9 Finding 1 and Recipe 2.6 Finding 3. The stakes here are higher: a multi-modal reasoning output that upgrades a graded imaging term ("mild" to "moderate" LV dysfunction), fabricates an ejection-fraction value, or silently drops a safety finding can affect decisions that a clinician has limited time to audit. The main recipe's "Failure Modes, Specific to Multi-Modal" section specifically calls out quantitative drift, graded-term fabrication, and missed-safety-finding coverage as the outcomes the architecture is designed to prevent, and the orchestrator is the last line between a flagged reasoning output and the clinician UI.
- **How to fix:** Distinguish `VALIDATED` from `REVIEW_REQUIRED` after the retry loop. Treat `REVIEW_REQUIRED` as its own terminal status that archives the trace for audit but does NOT mark the run as delivered. Roughly:
  ```python
  last_validation_status = (
      validation_result["status"] if validation_result else None
  )

  if (
      not generation_result
      or generation_result["status"] != "GENERATED"
  ):
      runs_table.update_item(
          Key={"run_id": run_id},
          UpdateExpression="SET #s = :s",
          ExpressionAttributeNames={"#s": "status"},
          ExpressionAttributeValues={":s": "GENERATION_FAILED"},
      )
      return {"status": "GENERATION_FAILED", "run_id": run_id,
              "processing_time_ms": int((time.time() - start) * 1000)}

  if last_validation_status != "VALIDATED":
      # Persist the trace for audit but do NOT deliver to the clinician UI.
      # A separate human-review queue consumer picks up ROUTED_TO_REVIEW runs.
      runs_table.update_item(
          Key={"run_id": run_id},
          UpdateExpression="SET #s = :s, validation_issues = :v",
          ExpressionAttributeNames={"#s": "status"},
          ExpressionAttributeValues={
              ":s": "ROUTED_TO_REVIEW",
              ":v": validation_result.get("unverified", []),
          },
      )
      # Optionally archive a redacted trace for the review queue.
      return {"status": "ROUTED_TO_REVIEW", "run_id": run_id,
              "validation_result": validation_result,
              "processing_time_ms": int((time.time() - start) * 1000)}
  ```
  Also add a comment at the validator's `REVIEW_REQUIRED` return site stating that this is a terminal state the orchestrator must NOT pass through to `tier_render_archive` with `status = DELIVERED`.

---

### Finding 2: `_collect_all_citations` is defined twice; the second definition silently shadows the Step 8 validator helper

- **Severity:** WARNING
- **Location:** `chapter02.10-python-example.md`, Step 8 (first definition at approximately line 1731) and the "Putting It All Together" section (second definition at approximately line 2044)
- **Description:** The Step 8 validator uses `_collect_all_citations(item)` to enumerate every citation referenced by a recommendation, then checks each cited ID against `id_to_source`. The intended helper scans both the structured `source_citations` lists AND the bracketed inline citations in the description / evidence / recency-notes text:
  ```python
  def _collect_all_citations(item: dict) -> list:
      """Walk an item's evidence lists and collect every source_citation."""
      cits = []
      for side in ("evidence_for", "evidence_against"):
          for e in item.get(side, []) or []:
              cits.extend(e.get("source_citations", []) or [])
      # The description and reasoning fields may also contain [bracketed] cites.
      text = _collect_item_text(item)
      for m in re.findall(r"\[([^\]]+)\]", text):
          if ":" in m:
              cits.append(m)
      return list(set(cits))
  ```
  The "Putting It All Together" section redefines the function with a shorter body:
  ```python
  def _collect_all_citations(item: dict) -> list:
      """(Used in the pipeline's id_to_source fallback; see Step 8 above.)"""
      cits = []
      for side in ("evidence_for", "evidence_against"):
          for e in item.get(side, []) or []:
              cits.extend(e.get("source_citations", []) or [])
      return list(set(cits))
  ```
  The docstring suggests the second definition is a pointer back to Step 8, but in Python a second `def` at module scope binds the same name and overrides the earlier definition. When a reader copies the full Python example into a single file and imports `_collect_all_citations`, they get the shorter version with no text scan. The Step 8 validator calls this helper on every recommendation to build its citation set for the `citation_not_in_retrieved_set` check.

  The practical consequence: if the reasoning model emits `[imaging:1.2.3.4.5]` or `[lab:2160-0]` inline in a `description` or `evidence_for[i].text` field but fails to include the same source_id in the `source_citations` list (which Claude sometimes does in practice, especially under regeneration with validation hints), the shorter helper does not see the inline token. The validator's check for `citation_not_in_retrieved_set` uses only what the helper returns, so inline citations pointing at fabricated or mis-typed source_ids slip past the citation-resolution pass. The main recipe calls citation discipline "non-optional" and relies on three triangulated layers (prompt, Guardrail, validator); the shadowed helper silently weakens one of them.

  This is a latent bug rather than an active one because the prompt's JSON structure also instructs the model to list source_citations per evidence item, so most of the time the structured list and the inline tokens agree. When they diverge, the divergence is exactly the case the inline scan was written to catch, and the current code cannot catch it.
- **How to fix:** Delete the duplicate definition at the bottom of the file. If the intent was to reference the Step 8 helper, replace it with a one-line comment:
  ```python
  # _collect_all_citations is defined in Step 8 above; re-used here for the
  # trace serialization. No redefinition needed.
  ```
  Verify by loading the module and inspecting `_collect_all_citations.__code__.co_consts` (or just reading the file top-to-bottom) that the text-scanning version is the one bound at the end. An inline test that passes an item with a bracketed source_id in `description` but NOT in `source_citations` should produce the inline ID in the returned set.

---

### Finding 3: Guardrail-intervention tuple match includes a string Anthropic Claude does not emit

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 7 (`invoke_reasoning_layer`), the guardrail-action check
- **Description:** The check reads:
  ```python
  guardrail_action = (
      payload.get("amazon-bedrock-guardrailAction")
      or payload.get("stop_reason")
  )
  if guardrail_action in ("INTERVENED", "guardrail_intervened"):
      ...
  ```
  The primary signal (`amazon-bedrock-guardrailAction`) is correct and is the field Bedrock populates when a Guardrail intervenes on `invoke_model`. The fallback to `stop_reason` is defensive. The cosmetic issue is that `"guardrail_intervened"` is not a documented Anthropic Claude `stop_reason` value. Claude on Bedrock emits `end_turn`, `stop_sequence`, `max_tokens`, `tool_use`, and (on newer versions) `pause_turn` / `refusal`. A Guardrail intervention is signaled via `amazon-bedrock-guardrailAction = "INTERVENED"`, not by a `stop_reason` value. The `"guardrail_intervened"` arm of the tuple is dead code.

  This is the same observation as Recipe 2.9 Finding 4.
- **How to fix:** Drop `"guardrail_intervened"` from the tuple. The primary check and the defensive `stop_reason` fallback can remain:
  ```python
  guardrail_action = payload.get("amazon-bedrock-guardrailAction")
  if guardrail_action == "INTERVENED":
      ...
  ```

---

### Finding 4: Patient structured context passed to the reasoning prompt is character-sliced at 3000 chars

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 7 (`invoke_reasoning_layer`), the `reasoning_user` prompt assembly
- **Description:** The user message renders the structured context with:
  ```python
  PATIENT STRUCTURED CONTEXT:
  {json.dumps(patient_state.get('structured_context', {}), default=str)[:3000]}
  ```
  Character-slicing a JSON serialization is a coarse proxy for token budget and silently drops trailing fields. JSON dict order is insertion order, so the truncation typically lops off `derived` (eGFR, BMI) or the tail of `current_medications`, which is precisely the section the reasoning layer needs for renal-dosing and contraindication context.

  The deterministic safety checks in Step 5 use the full structured context, so the most important flags still reach the prompt via the safety block. But the reasoning-over-context path loses fidelity, and the reasoning layer may produce recommendations that appear to ignore a medication or derived value that was in the input but fell off the end of the slice.

  This is the same pattern noted in Recipe 2.9 Finding 5, at a tighter budget (3000 vs 4000 chars).
- **How to fix:** Either (a) increase the budget with a comment noting it is a coarse proxy for tokens, (b) truncate structurally (drop `procedures`, `documents` before trimming `current_medications` and `derived`), or (c) use a tokenizer-aware counter. For a teaching example, option (a) with a comment suffices:
  ```python
  # Coarse character slice as a proxy for token budget. Production truncates
  # less-critical fields first (procedures, document references) to protect
  # labs, medications, and derived values.
  context_rendered = json.dumps(
      patient_state.get("structured_context", {}), default=str,
  )
  if len(context_rendered) > 30000:
      logger.warning("Structured context exceeded 30k chars; truncating")
      context_rendered = context_rendered[:30000] + "... [truncated]"
  ```

---

### Finding 5: Quantity regex alternation matches `ng/mL` before `ng/mL FEU`, leaving FEU unmatched

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 8 (`validate_reasoning`), the `quantity_regex` pattern
- **Description:** The regex is:
  ```python
  quantity_regex = re.compile(
      r"\b\d+(?:\.\d+)?\s*(?:%|mg|mcg|g|mL|mmHg|bpm|ng/mL|pg/mL|"
      r"U/L|mmol/L|ng/mL FEU|ms)\b",
      flags=re.IGNORECASE,
  )
  ```
  Regex alternation tries alternatives left-to-right. `ng/mL` is listed before `ng/mL FEU`. On the text "D-dimer 1200 ng/mL FEU" (which appears verbatim in the main recipe's vignette and the synthetic lab data at `_synthetic_observations_for_loinc` for LOINC 33762-6), the regex matches `1200 ng/mL` first and leaves `FEU` unmatched. The next scan position starts after `mL`, so no second match captures the full unit.

  The functional impact is subtle. The verbatim check compares the captured string against `source_blob` (a JSON dump of cited sources). If the reasoning output writes "D-dimer 1200 ng/mL" and the source says "D-dimer 1200 ng/mL FEU," the substring search for `1200 ng/mL` succeeds, so the check passes. But the check is weaker than intended: the FEU unit qualifier (fibrinogen equivalent units, which is clinically distinct from DDU units) is never asserted as preserved. A reasoning output that drops FEU when copying the D-dimer value would not be caught.

  For a teaching example this is a minor issue; for a production validator working on coagulation labs, FEU vs DDU unit discipline matters.
- **How to fix:** Reorder the alternation to put longer, more specific units before shorter prefixes:
  ```python
  quantity_regex = re.compile(
      r"\b\d+(?:\.\d+)?\s*(?:%|mcg|mg|g|mL|mmHg|bpm|ng/mL FEU|ng/mL|pg/mL|"
      r"U/L|mmol/L|ms)\b",
      flags=re.IGNORECASE,
  )
  ```
  Also consider adding the common weight-based and rate-based forms (`mg/kg`, `mcg/kg/min`, `ng/mL/hr`) that the Recipe 2.9 review flagged; multi-modal reasoning contexts that cover infusion dosing will need them.

---

### Finding 6: Cross-modality consistency scan and scope-compliance check from the pseudocode are not implemented in the validator

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 8 (`validate_reasoning`); compared against `chapter02.10-multi-modal-clinical-reasoning.md`, Step 8 pseudocode checks 6 and 7
- **Description:** The pseudocode for Step 8 lists eight validator checks:
  1. Citation resolution
  2. Verbatim quantity
  3. Verbatim graded-term
  4. Safety findings represented
  5. Missing-modality acknowledgment
  6. Cross-modality consistency scan (detect claims whose content contradicts another modality's source without acknowledgment)
  7. Scope compliance (flag items outside `scope_decision.scoped_to`)
  8. Directive-language in model voice

  The Python validator implements 1-5 and 8 but omits 6 and 7. The omitted checks are non-trivial to implement well:
  - Cross-modality consistency requires semantic-similarity reasoning to detect that a claim "EF preserved" contradicts a source "EF 40-45%" without the reasoning output acknowledging the contradiction.
  - Scope compliance requires a classifier that decides whether a given recommendation falls within the scenario scope (e.g., a cardiology recommendation within "ed_dyspnea_workup" is in scope, a dermatology recommendation is not).

  The main recipe is honest about the difficulty in the "The Gap Between This and Production" section: "Cross-modality contradiction detection needs more than prompting... this is a hard NLP problem and an active research area." The Python companion silently skips both checks. A reader comparing the pseudocode to the Python will not see the gap unless they read both carefully.
- **How to fix:** No code change required for the teaching example. Add a comment at the end of the validator noting what is deliberately not implemented:
  ```python
  # NOTE: two validator checks from the pseudocode are not implemented here:
  #   - Cross-modality consistency scan (semantic contradiction detection)
  #   - Scope compliance check (classifier over scope_decision.scoped_to)
  # Both require more than regex and are sketched in the main recipe's
  # "Gap to Production" section. Production validators include a semantic-
  # similarity pass and a scope classifier; see Recipe 2.10 prose.
  ```

---

### Finding 7: `_build_sources_block` has two unused parameters

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 7 (`invoke_reasoning_layer`), helper `_build_sources_block`
- **Description:** The helper signature is:
  ```python
  def _build_sources_block(patient_state: dict, inventory: dict,
                           retrieved: dict, safety_findings: dict
                           ) -> tuple[str, dict]:
  ```
  The function body uses `patient_state` and `retrieved`. The `inventory` and `safety_findings` arguments are passed in from `invoke_reasoning_layer` but never referenced in the helper. The prompt assembly handles them separately via `_format_inventory_for_prompt` and `_format_safety_for_prompt`.

  This is a minor code smell rather than a bug. A reader might assume the helper threads inventory and safety findings into the sources block, which it does not.
- **How to fix:** Drop the unused parameters and update the call site:
  ```python
  def _build_sources_block(patient_state: dict, retrieved: dict
                           ) -> tuple[str, dict]:
      ...

  # At the call site:
  sources_block, id_to_source = _build_sources_block(
      patient_state, retrieved,
  )
  ```
  Or, if a future revision will weave safety findings into the sources block, leave the signature and add a TODO comment.

---

### Finding 8: `_synthetic_ecg_records` returns empty for every scenario, but the comment implies otherwise

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 2b helper `_synthetic_ecg_records`
- **Description:** The helper reads:
  ```python
  def _synthetic_ecg_records(patient_id: str, scenario: str) -> list:
      """Synthetic ECGs for illustration. Replace with HealthLake search."""
      # For the ED dyspnea scenario, we deliberately omit the ECG to exercise
      # the missing-modality acknowledgment path. Flip the list to include
      # ECGs for other scenarios.
      if scenario == "ed_dyspnea_workup":
          return []
      return []
  ```
  Both branches return `[]`. The comment says "Flip the list to include ECGs for other scenarios," which suggests the non-dyspnea branch is supposed to return a non-empty synthetic list. It does not. A learner who runs the example with a different scenario expecting to see ECGs ingested will see nothing and wonder whether they wired something wrong.

  The pedagogical intent (exercise the missing-modality path for the ED dyspnea vignette) is correct for the default run, but the second branch is confusing.
- **How to fix:** Either (a) populate the non-dyspnea branch with a small synthetic ECG record so a learner can see the ingestion path fire, or (b) simplify the branching and note that ECG ingestion is a stub across the board:
  ```python
  def _synthetic_ecg_records(patient_id: str, scenario: str) -> list:
      """
      Synthetic ECGs for illustration. Replace with HealthLake search.

      For the default ED dyspnea vignette we return no ECGs to exercise the
      missing-modality acknowledgment path in the reasoning prompt and the
      validator. Production systems replace this with a real HealthLake
      Observation search for LOINC 11524-6 (12-lead ECG report).
      """
      return []
  ```

---

### Finding 9: Module logger has no handler configured

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Configuration block (`logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)`)
- **Description:** Same pattern flagged in Recipe 2.9 Finding 9 and Recipe 2.6 Finding 10. Without `logging.basicConfig(...)` or an explicit handler, the `logger.info` / `logger.warning` calls sprinkled through the pipeline drop silently when the file runs as `__main__`. The orchestrator's `print(...)` statements keep the step-by-step demo visible, but the structured log output the rest of the code produces never reaches the console. A learner who expects to see the modality-inventory log line, the retrieval summary, or the validation verdict will see only the `print` lines.
- **How to fix:** Add one line to the Configuration block:
  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```

---

### Finding 10: `_derive_retrieval_queries` returns empty queries for every scenario except `ed_dyspnea_workup`

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 6 helper `_derive_retrieval_queries`
- **Description:** The helper has a branch for `ed_dyspnea_workup` that returns scenario-aware retrieval queries and a default branch:
  ```python
  return {"guideline_queries": [], "protocol_queries": [],
          "case_analog_queries": []}
  ```
  For any scenario other than ED dyspnea (hf_management, oncology_treatment_planning, comprehensive_reasoning, or a learner-added scenario), `retrieve_supporting_content` calls `_hybrid_search` with an empty query list; `_hybrid_search` returns `[]` immediately and the reasoning prompt gets no guidelines, no protocols, and no case analogs.

  This is a pedagogical simplification: the learner is expected to run the default ED dyspnea example. But a learner who changes the scenario and re-runs will see the reasoning layer operate on patient data alone with no literature grounding, which is not what the architecture is supposed to do, and the failure mode is silent.
- **How to fix:** No code change required. A one-line comment at the default-return would help:
  ```python
  # Only ED dyspnea queries are populated in this teaching example.
  # Replace this function with scenario-aware queries for each scenario
  # you support in production.
  return {"guideline_queries": [], "protocol_queries": [],
          "case_analog_queries": []}
  ```

---

### Finding 11: Documented stubs for HealthImaging, HealthLake, Aurora, OpenSearch, ECG foundation model, and cleared imaging AI vendor

- **Severity:** NOTE
- **Location:** `chapter02.10-python-example.md`, Step 2 ingestion helpers (`_list_relevant_imaging_for_scenario`, `_get_healthimaging_metadata`, `_fetch_radiology_report_from_healthlake`, `_get_cleared_imaging_ai_output`, `_invoke_ecg_foundation_model`, `_synthetic_observations_for_loinc`, `_synthetic_notes`, `_synthetic_ed_vignette_bundle`), Step 5 (`run_safety_checks`), Step 6 (`_hybrid_search`), and the orchestrator's `_query_recent_runs`
- **Description:** These helpers return synthetic or empty data with explicit TODO comments pointing at the real integration (HealthImaging `GetImageSetMetadata`, HealthLake SigV4 HTTPS search, the vendor API, the SageMaker endpoint, the Aurora drug-DB query from Recipe 2.9, the OpenSearch k-NN + BM25 + RRF hybrid from Recipes 2.7 / 2.9). The stubs are appropriate for a teaching example and each carries a TODO or a pointer to the earlier recipe.

  A learner copying the example needs to replace all of them before the pipeline is useful against real data. The heads-up block at the top of the file and the "Gap Between This and Production" section both enumerate the stubs, and each helper's docstring reinforces the placeholder status. This is a documented simplification rather than a bug; flagging for tracking.
- **How to fix:** No code change required. Optional: add a one-line "see Recipe 2.9 Step X" pointer in docstrings where the helper's production version is implemented in the preceding recipe (for `run_safety_checks`, `_hybrid_search`, and `_normalize_patient_context`, Recipe 2.9 has the full expansion).

---

### Finding 12: Pseudocode references Claude family names; Python pins versioned IDs

- **Severity:** NOTE
- **Location:** Pseudocode in `chapter02.10-multi-modal-clinical-reasoning.md` uses `REASONING_MODEL_ID` as an unspecified placeholder (e.g., Claude Sonnet); Python pins `"anthropic.claude-3-5-sonnet-20241022-v2:0"` and `"anthropic.claude-3-5-haiku-20241022-v1:0"`
- **Description:** Same pattern observed in Recipes 2.4, 2.5, 2.6, and 2.9. The pseudocode uses illustrative family names; the Python pins currently-available versioned IDs with an explicit TODO comment ("verify the exact model IDs available in your region and account") and a note about cross-region inference profile prefixes (`us.` or `eu.`). A reader comparing the two files side by side will still notice the gap.
- **How to fix:** Optional. One-line note in the pseudocode saying Bedrock model IDs are versioned and the Python companion pins a specific working example. No code change required.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function(s) | Consistent? |
|-----------------|---------------------|---------------------|-------------|
| Step 1 | `start_reasoning_run(trigger)` | `start_reasoning_run` | Yes (DynamoDB write with `_to_decimal_safe`; run_id generated; status INITIATED) |
| Step 2 | `ingest_imaging`, `ingest_ecg`, `ingest_labs_and_vitals`, `ingest_notes`, `ingest_structured_context` | Same names | Yes (HealthLake / HealthImaging / SageMaker stubs with documented TODOs; see Findings 8, 10, 11; sequential in Python vs parallel Step Functions Map in pseudocode, which the prose explicitly calls out) |
| Step 3 | `normalize_and_inventory(...)` | Same | Yes (patient_state + modality_inventory assembly matches; `_min_age_hours` handles empty lists) |
| Step 4 | `scope_gate(...)` | Same | Yes (suppression check, required-modality check, scoped-down fallback; `_modality_available` is a simpler check than the pseudocode's `modality_available` but is documented as such) |
| Step 5 | `run_safety_checks(...)` | Same | Yes (explicit stub returning a synthetic finding set; docstring points at Recipe 2.9 Step 4) |
| Step 6 | `retrieve_supporting_content(...)` | Same | Yes in shape; `_hybrid_search` and `_derive_retrieval_queries` are stubs (see Finding 10); the RRF fusion and ranking logic is deferred to Recipe 2.7 / 2.9 |
| Step 7 | `invoke_reasoning_layer(...)` | Same | Yes (Anthropic messages body, optional Guardrail kwargs, `amazon-bedrock-guardrailAction` parse; Finding 3 for dead-code guardrail tuple, Finding 4 for context truncation, Finding 7 for unused parameters) |
| Step 8 | `validate_reasoning(...)` | Same | Partial (Findings 2 and 6): citation / verbatim-quantity / graded-term / safety-finding / missing-modality / directive-language checks present; cross-modality consistency scan and scope-compliance check from pseudocode are not implemented; `_collect_all_citations` is shadowed by a duplicate definition |
| Step 9 | `tier_render_archive(...)` | Same | Yes (citation renumbering via `re.sub` with bracketed pattern, which avoids the substring-match bug Recipe 2.9 had with `str.replace`; SSE-KMS on both S3 writes; reserved-word `status` aliased on `update_item`; CloudWatch metrics emitted) |

The `run_multi_modal_reasoning` orchestrator chains all nine steps with explicit handling for the defer-by-scope-gate, grounding-rejected, and validation-retry paths. The retry loop exit on `REVIEW_REQUIRED` is where Finding 1 lives; the rest of the orchestration matches the pseudocode's intent.

---

## AWS SDK Accuracy

### Bedrock Runtime `invoke_model` (Anthropic messages format)

```python
bedrock_runtime.invoke_model(
    modelId=REASONING_MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        6000,
        "temperature":       0.15,
        "system":            reasoning_system,
        "messages":          [{"role": "user", "content": reasoning_user}],
    }),
    guardrailIdentifier=GUARDRAIL_ID,      # when configured
    guardrailVersion=GUARDRAIL_VERSION,    # when configured
)
```

- Parameter names (`modelId`, `contentType`, `accept`, `body`, `guardrailIdentifier`, `guardrailVersion`): correct
- Anthropic body schema: correct for Claude on Bedrock
- Response parsing `json.loads(response["body"].read())` then `payload["content"][0]["text"]`: correct for Anthropic messages responses
- Temperature 0.15 for the reasoning layer: conservative, appropriate for clinician-facing synthesis
- Guardrail kwargs attached conditionally when both IDs are configured: correct posture for the teaching example
- Guardrail intervention signal read from `amazon-bedrock-guardrailAction`: correct (Finding 3 is cosmetic)

### Bedrock Runtime (Titan Text Embeddings v2)

```python
response = bedrock_runtime.invoke_model(
    modelId=EMBEDDING_MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({"inputText": text}),
)
payload = json.loads(response["body"].read())
return payload["embedding"]
```

- Request body shape (`inputText`): correct for `amazon.titan-embed-text-v2:0`
- Response parsing `payload["embedding"]`: correct
- Comment explicitly warns that the embedder must match whatever indexed the corpus, which is the class of bug that silently wrecks retrieval quality

### Comprehend Medical `detect_entities_v2`

```python
entities_resp = comprehend_medical.detect_entities_v2(
    Text=_safe_utf8_truncate(report_text, COMPREHEND_MEDICAL_MAX_BYTES),
)
report_entities = entities_resp.get("Entities", [])
```

- Method name `detect_entities_v2`: correct (the snake_case boto3 form of `DetectEntitiesV2`)
- `Text` parameter name: correct
- Response key `Entities`: correct
- UTF-8 byte-count truncation via `_safe_utf8_truncate` used on every call site (imaging report ingestion, note ingestion): correctly handles multi-byte characters and the Comprehend Medical byte-size limit
- ClientError swallowed to empty list with a warning log per call: acceptable for ingestion-path resilience

### S3 `put_object`

```python
s3_client.put_object(
    Bucket=REASONING_ARCHIVE_BUCKET,
    Key=rendered_key,
    Body=json.dumps(rendered, indent=2, default=str).encode("utf-8"),
    ContentType="application/json",
    ServerSideEncryption="aws:kms",
    SSEKMSKeyId=REASONING_ARCHIVE_CMK_ARN,
)
```

- Parameter names: correct
- `Body` passed as bytes (UTF-8 encoded): correct
- `default=str` in `json.dumps` safely handles any `datetime` or `Decimal` that slips through: correct defensive choice
- `ServerSideEncryption="aws:kms"` with `SSEKMSKeyId`: correct PHI posture
- S3 keys (`reasoning-runs/{run_id}/rendered.json`, `reasoning-runs/{run_id}/trace.json`): no leading slashes, UUID-based uniqueness

### DynamoDB

- `runs_table.put_item(Item=_to_decimal_safe({...}))` in `start_reasoning_run`: every value funneled through `_to_decimal_safe`, which routes floats through `Decimal(str(value))`
- `runs_table.update_item(...)` in `scope_gate` (for DEFERRED), `tier_render_archive` (for DELIVERED), and the orchestrator (for GENERATION_FAILED): `ExpressionAttributeNames={"#s": "status"}` correctly escapes the reserved word; `ExpressionAttributeValues` carries only strings, ints, and lists of strings; no Python floats reach DynamoDB
- `num_recommendations = :nr` in the DELIVERED update is `len(rendered_items)`, an int: correct
- Trace persistence to DynamoDB carries S3 keys only (`rendered_s3_key`, `trace_s3_key`), which is the right pattern for PHI payloads (store only pointers)

### CloudWatch `put_metric_data`

```python
cloudwatch.put_metric_data(
    Namespace="MultiModalClinicalReasoning",
    MetricData=[
        {"MetricName": "ReasoningRunsDelivered",
         "Value": 1.0, "Unit": "Count"},
        {"MetricName": "ModalitiesUsed",
         "Value": float(len(rendered.get("modalities_used", []))),
         "Unit": "Count"},
        {"MetricName": "CrossModalityContradictionsSurfaced",
         "Value": float(len(rendered_contradictions)),
         "Unit": "Count"},
    ],
)
```

- Parameter shape (`Namespace`, `MetricData` with `MetricName`, `Value`, `Unit`): correct
- `Unit="Count"` with float `Value`: correct for the CloudWatch API
- Three metrics that give a useful base for dashboards and alarms (delivered count, modalities-used, cross-modality contradictions)
- ClientError swallowed to a warning log: acceptable for a metric-emission path

### Bedrock Guardrails

- `guardrailIdentifier` / `guardrailVersion` parameter names on `invoke_model`: correct
- Conditional attachment only when both are configured: correct posture (defaults to `None` with an explicit warning that production must configure one at 0.85+ contextual grounding threshold)
- Intervention detection: primary check on `amazon-bedrock-guardrailAction` (correct); see Finding 3 for the cosmetic dead-code concern

---

## DynamoDB Decimal Check

- `_to_decimal_safe` helper present in Shared Helpers, walks dicts and lists recursively, routes floats through `Decimal(str(value))` (the correct pattern that avoids the binary-precision drift `Decimal(float_value)` introduces)
- `start_reasoning_run` wraps its `Item` through `_to_decimal_safe`
- `scope_gate`'s update_item passes a string (`":s"`), a string (`":r"`), and a list of strings (`":m"`) via `ExpressionAttributeValues`: no floats
- `tier_render_archive`'s update_item passes strings and an int (`":nr"`): no floats
- Orchestrator's GENERATION_FAILED update_item passes a string: no floats

Result: no Python float reaches DynamoDB. Pass.

---

## S3 Key Check

All S3 keys inspected: `reasoning-runs/{run_id}/rendered.json`, `reasoning-runs/{run_id}/trace.json`. No leading slashes, no reserved characters, UUID-based uniqueness. The bucket is configured with a KMS CMK and the writes set `ServerSideEncryption="aws:kms"` with `SSEKMSKeyId`.

Pass.

---

## Module-Level Imports and Clients

- Standard library imports (`json`, `logging`, `re`, `time`, `uuid`, `datetime`, `timezone`, `Decimal`, `defaultdict`): all used
- Third-party imports (`boto3`, `botocore.config.Config`, `botocore.exceptions.ClientError`, `opensearchpy.OpenSearch`, `opensearchpy.RequestsHttpConnection`, `requests_aws4auth.AWS4Auth`): all used
- boto3 clients (`bedrock_runtime`, `comprehend_medical`, `s3_client`, `dynamodb`, `cloudwatch`) instantiated at module load with shared adaptive-retry config: correct, re-used across warm Lambda invocations
- HealthLake, HealthImaging, SageMaker-runtime, and Secrets Manager clients are noted as "created in the functions that use them" with the rationale ("so the example runs without them configured") but the example doesn't actually create any of them since all ingestion is stubbed. Fine for the teaching path.

Pass.

---

## Comment Quality

Comments consistently explain the "why," not just the "what." High-value examples:

- "CRITICAL: must match whatever embedder indexed the guideline corpus. Mixing embedders between indexing and query time produces silently bad retrieval." Same class of silent failure that the main recipe warns about.
- "DynamoDB raises TypeError on Python floats; this helper is the muscle memory that prevents that." Short, memorable, and names the exact exception.
- "Going through str avoids binary-precision artifacts that Decimal(float) introduces." The second half of the Decimal gotcha.
- "Never log raw patient context, modality contents, or rendered reasoning in plain text. The audit trail for clinical content lives in S3 and DynamoDB under KMS, with CloudTrail data events enabled." PHI posture at the logger setup.
- "Adaptive retry handles Bedrock throttling. Multi-modal reasoning bursts around admission spikes and shift change; adaptive mode uses exponential backoff with jitter so retries don't pile on." Explains both the choice and the workload shape.
- "This is a reasoning pipeline, not an imaging-AI pipeline. The code below consumes radiology report text and (optionally) structured outputs from cleared imaging AI vendors. It does NOT perform direct pixel-level interpretation of DICOM studies." Sets the regulatory posture explicitly up front.
- "Graded terms from radiology and pathology reports that must be preserved verbatim if they appear in the reasoning output. Upgrading 'mild' to 'moderate' is a specific, common, and dangerous hallucination." Names the specific failure mode.
- Each step header references the pseudocode function: "The pseudocode calls this `scope_gate(...)`." Makes cross-file navigation easy.
- The heads-up block at the top labels every clinical output as SYNTHETIC, lists every production gap (no cleared imaging AI, no ECG foundation model endpoint, no real HealthImaging DICOM workflow, no Step Functions orchestration, no SMART-on-FHIR launch, no PACS deep-linking, no validated regulatory posture, no clinical validation, no post-market surveillance), and frames the example correctly for a learner.
- The final "Gap Between This and Production" section is substantial and honest: regulatory determination before pilot, cleared imaging AI integration, HealthImaging DICOM integration, HealthLake FHIR integration, ECG foundation model integration, guideline corpus ingestion as 50%+ of the work, Aurora drug database, Guardrails contextual grounding as non-optional, missing-modality acknowledgment as the hardest invariant, cross-modality contradiction detection needing more than prompting, verbatim preservation for numerics and graded terms, Step Functions orchestration, prompt versioning, clinical validation per scenario, post-market surveillance, bias monitoring, EHR workflow integration, alert-fatigue tuning, VPC / encryption / audit, PHI minimization in prompts, cost control at scale, the DynamoDB Decimal gotcha, JSON parsing resilience, synthetic-data testing, observability / SLOs, model-ID lifecycle, clinician-as-decision-maker.

---

## Healthcare-Specific Requirements

- **PHI logging:** Logger setup comment says "Never log raw patient context, modality contents, or rendered reasoning in plain text." Log statements use identifiers (run_id, patient_id) and counts only. Pass.
- **Encryption:** SSE-KMS set on both S3 writes with a customer-managed key ARN. The prerequisites call out distinct KMS keys per modality where retention policies differ; the code parameterizes `REASONING_ARCHIVE_CMK_ARN` as a single key for the example and the main recipe flags the distinct-keys recommendation. Pass.
- **BAA / HIPAA context:** Setup section notes Bedrock, HealthLake, HealthImaging, Comprehend Medical, Aurora, OpenSearch, DynamoDB, S3, and SageMaker all HIPAA-eligible under BAA. Every service in the pipeline is covered. Pass.
- **Synthetic data:** The heads-up block and in-line comments label every clinical artifact as SYNTHETIC with an explicit "Do not treat any specific finding, differential, or next-step recommendation in this file as real clinical guidance." The synthetic ED vignette bundle, synthetic CXR and echo reports, synthetic lab observations, synthetic notes, and synthetic vitals all carry the label. Pass.
- **Retention:** Gap section notes per-modality retention policies with distinct CMKs. Pass.
- **Provenance and validation:** `validate_reasoning` does substantive work across citation / verbatim-quantity / graded-term / safety-finding / missing-modality / directive-language (Findings 2 and 6 flag the coverage gap). Trace archive retains `validation_result`, `modality_inventory`, `retrieved_source_counts`, `safety_findings`, `prompt_version`, `reasoning_model`, `small_model`, `embedding_model`, `raw_reasoning_output`, and `attempts`. Pass, modulo Finding 1 undermining the real-time safety posture.
- **Deterministic safety checks:** Step 5 explicitly points at Recipe 2.9's implementation with a synthetic finding set for the ED vignette. The pattern ("safety checks as LLM prompts is not a safety check") is preserved by threading the findings into the prompt as a "must include" block and enforcing coverage in the validator. Pass.
- **FDA CDS exemption posture:** Prompt enforces options-not-directives framing in the model's own voice; validator scans for directive phrases in unquoted text; the final `rendered` payload includes a prominent disclaimer ("This output is decision support synthesizing available multi-modal evidence. Review each cited source before acting. The clinician is the decision-maker."). Pass in architecture; Finding 1 undermines this in practice until fixed.
- **Source licensing posture:** Bibliography carries `modality`, `formatted`, `deep_link`, and `age_hours` per entry. The Gap section calls out vendor contracts, source licensing, and the license registry. Pass.
- **PHI minimization in prompts:** Gap section notes the prompt includes full patient context, that Bedrock under BAA is compliant, and that minimum-necessary argues for stripping direct identifiers before prompt construction and substituting back during rendering. Documented; not implemented. Acceptable for a teaching example.
- **Missing-modality acknowledgment:** The prompt's HARD REQUIREMENTS block explicitly names the `modalities_absent_and_relevant` field; the validator checks that every required-but-missing modality name appears in `modalities_absent_and_relevant`. The Gap section flags this as "the hardest invariant to enforce." Pass in architecture.
- **Graded-term preservation:** `GRADED_TERMS` list covers the common radiology / pathology terms; validator enforces that any graded term in the reasoning output appears verbatim in a cited source. Pass.
- **Cross-modality contradiction surfacing:** Prompt asks the model to surface contradictions in the `cross_modality_contradictions` field. Validator does NOT automate contradiction detection (Finding 6); the Gap section acknowledges this is a hard NLP problem and an active research area. Pass in architecture; validator coverage gap documented.

---

## Logical Flow

The code reads cleanly top-to-bottom:

1. Imports and module-level clients
2. Configuration constants grouped by concern (model IDs, OpenSearch, Aurora, HealthLake, HealthImaging, SageMaker, storage, pipeline tuning, recency windows, suppression window, scenario-modality requirements, graded terms, directive phrases)
3. Shared helpers (timestamp, OpenSearch client, embedder, JSON parser, UTF-8 truncator, Decimal converter, hours-since helper)
4. Step 1: `start_reasoning_run`
5. Step 2a: `ingest_imaging` with documented HealthImaging / HealthLake / cleared-vendor stubs
6. Step 2b: `ingest_ecg`, `ingest_labs_and_vitals`, `ingest_notes`, `ingest_structured_context` with scenario-aware stubs
7. Step 3: `normalize_and_inventory` with the `_min_age_hours` helper
8. Step 4: `scope_gate` with suppression check and required-modality check
9. Step 5: `run_safety_checks` pointing at Recipe 2.9
10. Step 6: `retrieve_supporting_content` with hybrid-search stub and scenario-aware query derivation
11. Step 7: `invoke_reasoning_layer` with optional Guardrail attachment and structured JSON output
12. Step 8: `validate_reasoning` with six check categories and retry/review disposition
13. Step 9: `tier_render_archive` with `re.sub`-based citation renumbering, SSE-KMS S3 writes, and DynamoDB update
14. `run_multi_modal_reasoning` orchestrator chaining all nine steps
15. `_query_recent_runs` stub
16. Synthetic `__main__` example matching the ED dyspnea vignette from the main recipe

The orchestrator's step-by-step `print` statements make the flow visible in a demo run even though the structured logger is not wired to a handler (Finding 9).

---

## What Is Clean

- DynamoDB `_to_decimal_safe` helper applied consistently on `put_item`; no Python float reaches DynamoDB in any path
- S3 `put_object` calls both set `ServerSideEncryption="aws:kms"` with a customer-managed key ARN
- Bedrock `invoke_model` uses the correct Anthropic messages body shape with optional Guardrail kwargs attached only when both IDs are configured
- Titan Text Embeddings request body uses `{"inputText": text}` and the response parses `payload["embedding"]`
- Comprehend Medical `detect_entities_v2` uses UTF-8 byte-count truncation (not character count) via `_safe_utf8_truncate` at every call
- Citation renumbering in Step 9 uses `re.sub(r"\[([^\]]+)\]", _sub, text)` with a substitution function that returns the original match for unknown IDs. This avoids the `str.replace` substring-match bug that Recipe 2.9 had (Recipe 2.9 Finding 2). The 2.10 approach is the cleaner pattern.
- Reserved-word `status` aliased with `ExpressionAttributeNames={"#s": "status"}` at every `update_item` call
- `_safe_utf8_truncate` correctly encodes to UTF-8 before slicing by byte, handles multi-byte characters, and is documented with the rationale
- The JSON parser helper `_parse_json_response` strips both `` ```json `` and `` ``` `` fences defensively
- The heads-up block up top labels every clinical output as SYNTHETIC and enumerates every production gap
- The nine-step header comments explicitly reference the pseudocode function each Python function implements, making cross-file navigation easy
- The orchestrator handles defer-by-scope-gate cleanly (DEFERRED_BY_SCOPE_GATE status in DynamoDB; early return with `scope_decision.reason` and `scope_decision.missing`), grounding-rejected cleanly (loop continues with an augmented hint), and generation-failed cleanly (GENERATION_FAILED status with early return)
- Cost discipline: `MAX_GENERATION_ATTEMPTS = 3` caps retries; retrieval sizes bounded at `TOP_GUIDELINES_TO_PROMPT=10`, `TOP_PROTOCOLS_TO_PROMPT=8`, `TOP_CASE_ANALOGS_TO_PROMPT=3`; two model tiers by role (Haiku for small, Sonnet for reasoning); the Gap section calls out per-user/per-day rate limits as a production requirement
- Scenario-aware design: `SCENARIO_MODALITY_REQUIREMENTS` cleanly defines required and recommended modalities per scenario; the scope gate uses the dict directly; the validator reuses the same dict for the missing-modality check
- Recency windows per modality (`RECENCY_WINDOWS_HOURS`) are scenario-aware and used in the modality inventory

---

## Closing Assessment

This is strong code. The nine pseudocode steps map one-to-one onto nine Python functions (with Step 2 expanded into five parallel ingestion functions per modality, as the pseudocode describes). boto3 usage is current and correct. DynamoDB `Decimal` handling is disciplined. S3 keys are clean. SSE-KMS is set on every archive write. Comprehend Medical byte-limit handling is correct. The deterministic safety layer points at Recipe 2.9's implementation, which is the right inheritance pattern. The validator enforces citation, verbatim-quantity, graded-term, safety-finding, missing-modality, and directive-language checks. The citation renumbering in Step 9 uses a `re.sub` pattern that is immune to the substring-match bug Recipe 2.9 had.

The two WARNINGs sit at the same boundary of the orchestrator and the validator that Recipe 2.9 had. Finding 1 is the auto-deliver bug on `REVIEW_REQUIRED`: a reasoning output that fails validation after exhausting retries still ships with `status = DELIVERED`, which bypasses the validator the architecture is built around. For multi-modal reasoning touching imaging findings, cross-modality consistency, and graded-term preservation, this is a higher-stakes version of the same bug. Finding 2 is the duplicate `_collect_all_citations` definition that silently shadows the text-scanning version from Step 8, which weakens inline-citation validation. Both are fixable with small, localized changes.

The NOTE findings are editorial: a dead-code arm in the guardrail-action tuple (same as 2.9), a 3000-character context slice, quantity-regex alternation order, cross-modality consistency and scope-compliance validator checks from the pseudocode not implemented in Python, unused parameters in `_build_sources_block`, `_synthetic_ecg_records` returning empty in both branches, a missing logger handler, `_derive_retrieval_queries` scenario coverage, the documented stubs for HealthImaging / HealthLake / Aurora / OpenSearch / ECG / vendor AI, and the pseudocode-vs-Python model-ID pinning gap. None block a re-review.

The main recipe's "Gap to Production" section is mirrored thoroughly in the Python file's own gap section, and the architecture decisions (reasoning over cleared modality outputs rather than direct pixel interpretation; grounded generation with triangulated citation discipline across prompt, Guardrail, and validator; deterministic safety as structured queries; modality inventory and scope gate as first-class steps; cross-modality contradictions surfaced in the output; missing-modality acknowledgment as a hard requirement; clinician-as-decision-maker framing throughout) are preserved correctly in the code.

The verdict is PASS with two WARNINGs flagged for follow-up.

---

## Re-review checklist

When this review is addressed, a re-reviewer should verify:

1. The orchestrator distinguishes `REVIEW_REQUIRED` from `VALIDATED` after the retry loop exits, routes the `REVIEW_REQUIRED` path to a distinct terminal status (`ROUTED_TO_REVIEW` or similar), and does NOT call `tier_render_archive` (or archives a redacted version without `status = DELIVERED`) for any run whose validation status is anything other than `VALIDATED`.
2. The second `_collect_all_citations` definition in "Putting It All Together" is removed, or explicitly replaced with a one-line comment that points at the Step 8 definition. An inline test that passes an item with a bracketed source_id in `description` but NOT in `source_citations` should produce the inline ID in the returned set.
3. (Optional) The guardrail tuple is reduced to a single-value check against `"INTERVENED"` and the cosmetic `"guardrail_intervened"` string is dropped.
4. (Optional) The quantity-regex alternation order is fixed so `ng/mL FEU` matches as a unit before `ng/mL` is tried.
5. (Optional) A short comment at the validator's end explains that cross-modality consistency and scope-compliance checks from the pseudocode are intentionally not implemented in this teaching example.
6. (Optional) `_build_sources_block`'s unused parameters are removed or documented.
7. (Optional) `_synthetic_ecg_records` is either simplified to a single return or populated with a synthetic ECG for non-dyspnea scenarios.
8. (Optional) `logging.basicConfig(...)` is added to the Configuration block so structured log messages reach the console in a direct `__main__` run.
9. (Optional) `_derive_retrieval_queries` gets a one-line comment at the default return noting that only ED dyspnea queries are populated in the teaching example.
