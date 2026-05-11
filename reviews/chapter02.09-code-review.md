# Code Review: Recipe 2.9 - Clinical Decision Support Synthesis

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-11
**Files reviewed:**
- `chapter02.09-clinical-decision-support-synthesis.md` (main recipe, pseudocode)
- `chapter02.09-python-example.md` (Python companion)

**Validation performed:**
- Eleven-step pseudocode walked against Python functions, one-to-one
- boto3 Bedrock Runtime `invoke_model` parameters, Anthropic Messages API body shape, and response traversal verified
- boto3 Bedrock Guardrails `guardrailIdentifier` / `guardrailVersion` parameter names verified; intervention-detection field verified against current Bedrock response shape (see Finding 4)
- boto3 Titan Text Embeddings v2 request body shape (`inputText`) verified
- boto3 RDS Data API `execute_statement` with parameterized `:name` placeholders and typed cell values (`stringValue`, `doubleValue`) verified
- OpenSearch k-NN query body structure (`knn.embedding.vector`, `k`), BM25 `multi_match`, and filter clause shapes verified
- boto3 S3 `put_object` with SSE-KMS (`ServerSideEncryption="aws:kms"`, `SSEKMSKeyId`) verified
- boto3 DynamoDB `put_item` / `update_item` calls, reserved-word `status` aliased via `ExpressionAttributeNames` verified
- S3 keys checked for leading slashes (none present)
- Every numeric value that flows into DynamoDB inspected for Python-float writes (all routed through `_to_decimal_safe` or are ints)
- CKD-EPI 2021 (race-free) formula coefficients verified against the published NEJM 2021 equation
- Generation/validation retry loop traced for all exhaustion paths (see Finding 1)
- Citation replacement helper traced for substring overlap on multi-digit source IDs (see Finding 2)
- Healthcare concerns reviewed: PHI logging, BAA, encryption (SSE-KMS + distinct CMKs), synthetic data labeling, minimum-necessary, retention, provenance/validation, deterministic safety checks, FDA CDS exemption posture, licensing registry, alert-fatigue suppression

---

## Verdict: PASS

No ERROR findings. Two WARNING findings, both at the boundary of the orchestrator and the validation layer. Several NOTE findings on pedagogical polish and documented stubs.

The code is well-constructed overall: eleven pseudocode steps map cleanly to eleven Python functions, boto3 usage is current and correct, DynamoDB `Decimal` handling is disciplined via `_to_decimal_safe`, S3 keys are clean, parameterized SQL is used throughout the Aurora path, SSE-KMS is set on all archive writes, and the pedagogical comments explain "why" rather than "what" in the places where it matters (adaptive retry, Decimal serialization, byte-limit handling on Comprehend Medical, embedding-model/index alignment, grounding-check dependencies). The stubs (`_fetch_fhir_bundle_from_healthlake`, `_query_patient_history`, `_classify_drug`, `_drug_allergy_match`) are all explicitly labeled with TODOs or clarifying docstrings so a learner will not mistake them for production-ready code.

What keeps this out of "unqualified pass" territory is a pair of WARNINGs in the pipeline's safety spine: the orchestrator auto-delivers a synthesis when validation terminates with `REVIEW_REQUIRED` after exhausted retries, and the citation-to-number replacement has a latent substring-match bug that corrupts bibliography numbering if the model ever emits bare `src_N` citations without brackets. Both are fixable with small, localized changes.

---

## Summary

The eleven-step pseudocode maps one-to-one onto eleven Python functions, and `run_cds_synthesis` chains them in order with explicit handling for the suppression, no-evidence, parse-failure, grounding-rejected, and validation-retry paths. The boto3 mechanics are mostly textbook-correct. `invoke_model` uses the right Anthropic messages body shape with `anthropic_version`, `max_tokens`, `temperature`, `system`, and `messages`; `guardrailIdentifier` / `guardrailVersion` are the current parameter names; the contextual-grounding response signal is read from `amazon-bedrock-guardrailAction` (which is correct and fixes the issue flagged in the Recipe 2.6 review). `execute_statement` uses named parameterized placeholders with typed `stringValue` / `doubleValue` cells, which avoids the injection class that shows up when teams try to hand-format SQL with f-strings. S3 `put_object` correctly sets `ServerSideEncryption="aws:kms"` and `SSEKMSKeyId` on every archive write, and both archive keys (`syntheses/{id}/rendered.json`, `syntheses/{id}/trace.json`) have no leading slash.

The DynamoDB discipline is the best part. Every `put_item` goes through `_to_decimal_safe`, which recursively walks dicts and lists and routes floats through `Decimal(str(value))` to avoid the `TypeError: Float types are not supported` that a direct float write produces. The reserved word `status` is correctly aliased with `ExpressionAttributeNames={"#s": "status"}` at every `update_item` call. This is the kind of detail that is easy to get wrong in half of the calls and right in the other half; the Python companion gets it right in all of them.

The deterministic safety-check layer (Step 4) is a genuine safety-check, not a thin wrapper on an LLM. Drug-drug interactions, allergy conflicts, renal-dose flags, contraindications, and duplicate-therapy checks all run as structured SQL against Aurora before the generation model is invoked, and the findings are threaded into the generation prompt as a block the model is instructed to surface verbatim. The validator in Step 9 then enforces that every deterministic finding appears in the synthesis output, so a model that silently drops a safety finding is caught. That's exactly the architecture the main recipe argues for.

The code falls short in two places. First, the orchestrator's retry loop exits on `REVIEW_REQUIRED` and falls through to Step 10 and Step 11, which render and archive with `status = DELIVERED` regardless of whether validation actually passed. This is the same pattern the Recipe 2.6 review flagged as Finding 3, and for a clinician-facing CDS surface it is the exact safety-rail miswire that the architecture is designed to prevent: a synthesis with HIGH-severity validation failures (missed safety finding, drug that contradicts a contraindication without acknowledgment, dose not in a cited structured source) can ship to the clinician UI marked as delivered. Second, the `_replace_citations` helper in Step 10 does a `text.replace(cit_bare, ...)` pass after the bracketed replace. If the model ever emits a bare `src_1` and a bare `src_10` (no brackets), Python's naive `str.replace` would match `src_1` as a prefix of `src_10` and corrupt the rendered output. The prompt does instruct the model to use brackets, so this is a latent rather than active bug, but the defensive fallback is broken in a way that would be hard to debug when it eventually fires.

Beyond those, several NOTEs cover documented stubs, token-aware truncation, weight-based dose matching in the validator regex, and a cosmetic dead-code match in the guardrail tuple.


---

## Findings

### Finding 1: Orchestrator auto-delivers synthesis when validation returns `REVIEW_REQUIRED`

- **Severity:** WARNING
- **Location:** `chapter02.09-python-example.md`, `run_cds_synthesis` orchestrator (the generation/validation retry loop and the subsequent Step 10/Step 11 fall-through)
- **Description:** The retry loop in `run_cds_synthesis` breaks on both `VALIDATED` and `REVIEW_REQUIRED`:
  ```python
  if validation_result["status"] == "VALIDATED":
      break
  if validation_result["status"] == "REVIEW_REQUIRED":
      break
  regeneration_hint = validation_result.get(
      "suggested_prompt_augmentation", "",
  )
  ```
  After the loop, the only gate on proceeding is:
  ```python
  if not generation_result or generation_result["status"] not in (
      "GENERATED", "NO_EVIDENCE",
  ):
      # failure path: writes GENERATION_FAILED
  ```
  When validation exits with `REVIEW_REQUIRED`, `generation_result["status"]` is still `"GENERATED"`, so this failure gate does not fire. The code falls through to Step 10 (`tier_suppress_render`), which does not inspect `validation_result` at all, and then to Step 11 (`archive_and_log`), which updates the DynamoDB record to `status = "DELIVERED"` and returns the rendered payload to the caller.

  The practical consequence: a synthesis that failed validation after `MAX_GENERATION_ATTEMPTS` attempts for reasons including `citation_not_in_retrieved_set`, `dose_not_in_structured_source`, `safety_finding_not_represented`, `contradicts_contraindication`, or `contradicts_allergy` will ship to the clinician UI and be marked as a successful delivery in DynamoDB. The validator's own docstring says `REVIEW_REQUIRED` is what the function returns after exhausting retries ("Retries exhausted; routing to review" in the validator's internal comment and log message), but the orchestrator does not route it anywhere. The trace archive does retain `validation_result`, so post-hoc audit can detect the slip, but the real-time safety posture the validator is designed to provide is bypassed.

  This is the same failure pattern the Recipe 2.6 review flagged as Finding 3. For a CDS surface, the stakes are higher than a summarizer: a drug-contradicting-contraindication recommendation delivered without the flag is the kind of output that can harm a patient. The main recipe's "Failure Modes You Have to Design Around" section specifically calls out "missed contraindication" and "missed interaction" as the outcomes the architecture is designed to prevent, and the orchestrator is the last line between a flagged synthesis and the clinician.
- **How to fix:** Distinguish `VALIDATED` from `REVIEW_REQUIRED` in the post-loop flow. One approach: expand the failure gate to include the non-validated-generated case, and treat `REVIEW_REQUIRED` as its own terminal status (not `DELIVERED`). Roughly:
  ```python
  last_validation_status = (
      validation_result["status"] if validation_result else None
  )

  if (
      not generation_result
      or generation_result["status"] not in ("GENERATED", "NO_EVIDENCE")
  ):
      syntheses_table.update_item(
          Key={"synthesis_id": synthesis_id},
          UpdateExpression="SET #s = :s",
          ExpressionAttributeNames={"#s": "status"},
          ExpressionAttributeValues={":s": "GENERATION_FAILED"},
      )
      return {"status": "GENERATION_FAILED", "synthesis_id": synthesis_id}

  if (
      generation_result["status"] == "GENERATED"
      and last_validation_status not in ("VALIDATED",)
  ):
      # Persist the trace for audit but do NOT deliver to the clinician UI.
      archive_and_log(
          synthesis_id=synthesis_id,
          rendered={"status": "ROUTED_TO_REVIEW", "validation_result": validation_result, ...},
          trace=trace,
          clinician_id=trigger.get("clinician_id", "unknown"),
          patient_id=trigger.get("patient_id", "unknown"),
      )
      syntheses_table.update_item(
          Key={"synthesis_id": synthesis_id},
          UpdateExpression="SET #s = :s",
          ExpressionAttributeNames={"#s": "status"},
          ExpressionAttributeValues={":s": "ROUTED_TO_REVIEW"},
      )
      return {"status": "ROUTED_TO_REVIEW", "synthesis_id": synthesis_id,
              "validation_result": validation_result}
  ```
  Then a human-review queue consumer picks up `ROUTED_TO_REVIEW` items, and the clinician UI never sees an unvalidated synthesis as `DELIVERED`. Also add a comment at the validator's return site that `REVIEW_REQUIRED` is a terminal state that the orchestrator must NOT pass through to delivery.

---

### Finding 2: Citation replacement in `_replace_citations` has a substring-match bug for bare `src_N` citations

- **Severity:** WARNING
- **Location:** `chapter02.09-python-example.md`, Step 10 (`tier_suppress_render`), the nested `_replace_citations` helper
- **Description:** The helper finds citations with `re.findall(r"\[src_\d+\]|src_\d+", text)` (matching both bracketed and bare forms), then for each match does:
  ```python
  text = text.replace(f"[{cit_bare}]", f"[{numbered[cit_bare]}]")
  text = text.replace(cit_bare, f"[{numbered[cit_bare]}]")
  ```
  The second line is the defensive fallback for when the model emits citations without brackets. Python's `str.replace` is a pure substring replacement with no word-boundary awareness. On a text containing the bare tokens `src_1 and src_10`, when the loop processes the `src_1` match first, `text.replace("src_1", "[1]")` replaces `src_1` wherever it appears, including as the prefix of `src_10`. The text becomes `[1] and [1]0`, and the subsequent iteration for `src_10` finds nothing to replace (the token has already been mangled).

  In practice, the generation prompt explicitly instructs the model to use `[src_N]` format with brackets ("Every recommendation or factual claim must cite at least one source by identifier (e.g., [src_5])"). So the bug stays latent as long as the model complies. But CDS prompts evolve over time, corpus sizes grow past ten sources (making two-digit IDs common), and the whole point of the defensive fallback is to handle the case where the model deviates from the format. When it fires, it does so silently: the bibliography numbers are correct (the mapping is built by `findall` order before the replace loop), but the rendered text contains `[1]0` where `[2]` was intended, and a clinician reading the synthesis sees nonsense citation numbers.

  This is not a crash; it is the worse kind of bug, which is a silent corruption that a reader could easily miss in a synthesis they are scanning quickly at 2 AM.
- **How to fix:** Either (a) use a regex-based replace that respects token boundaries, or (b) process citations in order of decreasing length so the longer forms are replaced before their prefixes. Option (a) is more robust:
  ```python
  def _replace_citations(text: str) -> str:
      nonlocal next_num
      # Build a stable citation -> number mapping first.
      for cit in re.findall(r"\[src_\d+\]|(?<![\w_])src_\d+(?![\w_])", text):
          cit_bare = cit.strip("[]")
          if cit_bare not in id_to_source:
              continue
          if cit_bare not in numbered:
              numbered[cit_bare] = next_num
              bibliography.append({
                  "number":           next_num,
                  "formatted":        _format_source_for_bibliography(
                                          id_to_source[cit_bare]),
                  "source_type":      id_to_source[cit_bare].get("_kind"),
                  "source_url":       id_to_source[cit_bare].get("source_url")
                                      or id_to_source[cit_bare].get(
                                          "source_citation"),
                  "evidence_tier":    id_to_source[cit_bare].get("evidence_tier"),
                  "publication_year": id_to_source[cit_bare].get(
                                          "publication_year"),
              })
              next_num += 1

      # Single regex-based substitution pass handles both bracketed and bare
      # forms, using negative lookaround for the bare form to avoid matching
      # prefixes of longer IDs.
      def _replace_match(m):
          cit_bare = m.group(0).strip("[]")
          if cit_bare in numbered:
              return f"[{numbered[cit_bare]}]"
          return m.group(0)

      return re.sub(r"\[src_\d+\]|(?<![\w_])src_\d+(?![\w_])",
                    _replace_match, text)
  ```
  The negative-lookaround assertions `(?<![\w_])` and `(?![\w_])` make sure a bare `src_1` only matches when it is not the prefix of `src_10` or `src_123`. Option (b), sorting citation IDs by descending length before the loop, is a smaller diff but more fragile to future edits. Either way, add a code comment noting the substring-match trap so a future maintainer does not regress the fix.

---

### Finding 3: `_fetch_fhir_bundle_from_healthlake` returns synthetic data, not a real HealthLake call

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 1, `_fetch_fhir_bundle_from_healthlake` and its helper `_synthetic_patient_bundle_entries`
- **Description:** The helper is documented as a stub with an explicit TODO comment: "replace this stub with the real HealthLake SigV4 HTTPS integration. The current code returns a minimal synthetic bundle so the example runs end-to-end without a live datastore." The synthetic bundle returned is pedagogically useful; a reader can run the whole pipeline and see the shape without provisioning HealthLake. The concern is that a learner copying the example into a new project might miss the TODO and assume `boto3.client("healthlake")` exposes a direct `search_fhir_resources` method, which it does not in current SDK versions. HealthLake's FHIR endpoint is an HTTPS API requiring SigV4 signing, typically via `requests` plus `botocore.auth.SigV4Auth` or a FHIR client library.

  The TODO is clear and the synthetic bundle is labeled as illustrative, so this is a documented simplification rather than a bug. Calling it out so a re-review can track that the integration pathway is deliberate.
- **How to fix:** No code change required. The existing TODO is adequate. Optional: add a one-line pointer in the docstring to the SigV4-signed HTTPS pattern or to `botocore.auth.SigV4Auth` so a reader knows where to look when replacing the stub.

---

### Finding 4: Guardrail-intervention tuple match includes a string Anthropic Claude does not emit

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 8 (`generate_synthesis`), the guardrail-action check
- **Description:** The check reads:
  ```python
  guardrail_action = (
      payload.get("amazon-bedrock-guardrailAction")
      or payload.get("stop_reason")
  )
  if guardrail_action in ("INTERVENED", "guardrail_intervened"):
      ...
  ```
  The primary signal (`amazon-bedrock-guardrailAction`) is correct and is the fix for the bug flagged in Recipe 2.6 Finding 2. The fallback to `stop_reason` is defensive, and the comment above it notes "Field shape varies with Guardrail configuration; check both common patterns defensively." That is reasonable.

  The cosmetic issue is that the tuple includes `"guardrail_intervened"`, which is not a documented Anthropic Claude `stop_reason` value. Claude on Bedrock emits `end_turn`, `stop_sequence`, `max_tokens`, `tool_use`, and (on newer versions) `pause_turn` / `refusal`. A Guardrail intervention is signaled via `amazon-bedrock-guardrailAction = "INTERVENED"`, not by setting `stop_reason` to an intervention-specific value. So the `"guardrail_intervened"` arm of the tuple never matches.

  This is not a correctness bug (the primary check catches the real intervention signal), but the dead match is confusing for a learner and suggests that `stop_reason == "guardrail_intervened"` is a valid path. It is not.
- **How to fix:** Drop `"guardrail_intervened"` from the tuple and update the comment to just describe the single canonical check:
  ```python
  # Bedrock Guardrails signals intervention on InvokeModel via the
  # amazon-bedrock-guardrailAction response field. Value "INTERVENED"
  # means the Guardrail rejected the output; "NONE" means it passed.
  guardrail_action = payload.get("amazon-bedrock-guardrailAction")
  if guardrail_action == "INTERVENED":
      ...
  ```
  The `or payload.get("stop_reason")` fallback can stay if you want defense in depth, but the tuple match should be only `"INTERVENED"`.

---

### Finding 5: Patient context passed to the generation prompt is character-sliced at 4000 chars

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 8 (`generate_synthesis`), in `synthesis_user` prompt assembly: `{json.dumps(structured_context, default=str)[:4000]}`
- **Description:** The patient context is rendered to JSON and then truncated by character-slice at 4000 characters. For most patients this fits; for patients with long medication lists, active problem lists, or a dense recent-labs block, this can silently drop trailing fields. The JSON is ordered by dict insertion, so the truncation typically drops the tail of `recent_labs` or `derived` first, which is precisely the section guidelines key on (eGFR, INR, potassium).

  The validator in Step 9 compares the model's output to the retrieved sources and safety findings, so a dropped context field would not cause a citation failure, but it could cause the model to produce recommendations that ignore the dropped field (e.g., failing to note that the patient's INR is outside range). The deterministic safety checks in Step 4 use the full structured context, so the most important safety signals still reach the prompt via the safety block. The degradation is most visible for reasoning that depends on labs the safety check did not flag.

  This is a pedagogical simplification rather than a bug, but it is the kind of silent truncation that a production team should make explicit with a token-aware truncator and an explicit "context truncated" flag.
- **How to fix:** Either (a) increase the character budget with a note that this is a coarse proxy for tokens (Claude's 200K context accommodates far more than 4000 characters), (b) replace the character slice with a structured truncation that drops less-critical sections first (e.g., procedures, documents) before labs, or (c) use a tokenizer-aware counter. For a teaching example, option (a) plus a comment is enough:
  ```python
  # Coarse character slice as a proxy for token budget. Production systems
  # use a tokenizer-aware counter and truncate less-critical fields first
  # (procedures, document references) to protect labs and medications.
  context_rendered = json.dumps(structured_context, default=str)
  if len(context_rendered) > 30000:
      logger.warning("Patient context exceeded 30k chars; truncating")
      context_rendered = context_rendered[:30000] + "... [truncated]"
  ```

---

### Finding 6: Dose-verbatim regex does not cover weight-based dosing

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 9 (`validate_synthesis`), the `dose_regex` pattern
- **Description:** The regex is:
  ```python
  dose_regex = re.compile(
      r"\d+(?:\.\d+)?\s*(?:mg|g|mcg|units|mL|IU)"
      r"(?:\s+(?:IV|PO|IM|SC))?"
      r"(?:\s+(?:q\d+h|daily|BID|TID|QID))?",
      flags=re.IGNORECASE,
  )
  ```
  This captures standard flat doses like `2.25 g IV q6h` or `500 mg PO BID`. It does NOT capture weight-based dosing forms that are common in pediatric, oncology, and critical-care scenarios: `15 mg/kg IV q8h`, `0.1 mcg/kg/min`, `4 mg/kg/hr continuous infusion`. It also does not capture dose ranges (`1-2 g IV q8h`), surface-area dosing (`200 mg/m^2`), or unit prefixes on some biologics (`100,000 units`).

  The consequence: for recommendations containing weight-based or surface-area dosing, the validator's "dose not in cited source" check will not find any doses to check, and the faithfulness check effectively does not fire for those recommendations. The validator is not wrong (no doses extracted means nothing to verify), but a reader might conclude the check fired and passed when actually it had no work to do.
- **How to fix:** Extend the regex to cover weight-based forms and ranges, or make the dose extractor a small set of named regexes rather than one monolithic pattern. Something like:
  ```python
  dose_patterns = [
      re.compile(r"\d+(?:\.\d+)?\s*(?:mg|g|mcg|units|mL|IU)"
                 r"(?:\s*/\s*(?:kg|m\^2|hr|min))?"
                 r"(?:\s+(?:IV|PO|IM|SC|SL))?"
                 r"(?:\s+(?:q\d+h|daily|BID|TID|QID|continuous))?",
                 flags=re.IGNORECASE),
  ]
  def _extract_doses(text):
      doses = []
      for pat in dose_patterns:
          doses.extend(pat.findall(text))
      return doses
  ```
  A short comment noting that the regex is a coverage starter, not exhaustive, would also be useful for a learner who builds on this.

---

### Finding 7: `_query_patient_history` returns an empty list, disabling alert-fatigue suppression in practice

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, stub helper `_query_patient_history` used by both `determine_scope` (duplicate-suppression check) and `tier_suppress_render` (per-recommendation delivery-tier assignment)
- **Description:** The helper is documented as a stub with a TODO: "implement the real GSI query; stub returns empty." The effect is that two distinct suppression behaviors are disabled in the example run: the trigger-signature duplicate check in `determine_scope` never finds a prior synthesis, and the `_determine_delivery_tier` helper in Step 10 always sees an empty `prior` list and therefore cannot mark recommendations as `acknowledged`, `rejected`, or `changed`. Every recommendation is treated as new.

  The main recipe argues strongly that alert-fatigue suppression is a first-class design force for CDS; the Python stub effectively skips exercising it. This is acceptable for the purposes of the example (it keeps the synthetic run self-contained), and the TODO is explicit, but a reader wiring this into production has to implement the GSI query before any suppression behavior will actually fire.
- **How to fix:** No code change required for the teaching example. Add a one-line pointer in the docstring or the surrounding comment explaining the expected GSI structure (`(patient_id_encounter_id, delivered_at)` as a composite key, or a GSI on `(patient_id, encounter_id)` with a sort key on `delivered_at`) so the replacement is obvious. A follow-up variation could show a real implementation against a Local DynamoDB instance for learners who want to exercise the full suppression flow.

---

### Finding 8: `_drug_allergy_match` "class" substring match and "cross" rule are pedagogical shortcuts

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 4 helper `_drug_allergy_match`
- **Description:** The helper does three checks: exact RxNorm match (correct), substring match of allergy name in drug name (class stub), and a single-string rule for penicillin-cephalosporin cross-reactivity. The docstring correctly notes that "Real systems use a cross-reactivity table" and calls out the substring check as a fallback. In practice, the substring rule can produce both false negatives (allergy "amoxicillin" does not substring-match drug "ampicillin", which shares the aminopenicillin class and has real cross-reactivity concerns) and false positives (allergy "sulfonamide antibiotic" might not substring-match "sulfamethoxazole-trimethoprim" depending on how it was recorded). The penicillin-cephalosporin rule matches any drug containing `cef`, which does catch most cephalosporins but misses cefazolin formulations recorded under brand names.

  For a teaching example this is fine because it illustrates the pattern; a production build requires a cross-reactivity database (often tables keyed on drug class and allergen class, with severity gradations). The docstring signals the simplification clearly, so the concern is tracking it rather than fixing it.
- **How to fix:** No change for the teaching example. Optional: add a second sentence to the docstring pointing at cross-reactivity tables from commercial drug databases (First Databank, Lexicomp) or open alternatives as the production replacement.

---

### Finding 9: Module logger has no handler configured

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Configuration section (`logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)`)
- **Description:** Same pattern flagged in Recipe 2.6 (Finding 10). Without `logging.basicConfig(...)` or an explicit handler, the `logger.info` / `logger.warning` calls sprinkled through the eleven steps drop silently when the file runs as `__main__`. The orchestrator's `print(...)` calls keep the step-by-step demo visible, but the structured log output the rest of the code produces never reaches the console. A learner who expects to see the logger messages ("Normalized patient context: 3 conditions, 1 meds, ...", "Safety checks: 0 interactions, ...", "Generated synthesis: 2 recommendations, ...") will see only the `print` lines from the orchestrator.
- **How to fix:** Add one line to the Configuration block:
  ```python
  logging.basicConfig(
      level=logging.INFO,
      format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  ```
  This is a copy of the Recipe 2.6 fix suggestion.

---

### Finding 10: Pseudocode references Claude family names; Python pins versioned IDs

- **Severity:** NOTE
- **Location:** Pseudocode references `"anthropic.claude-haiku-4"` / `"anthropic.claude-sonnet-4"`; Python uses `"anthropic.claude-3-5-haiku-20241022-v1:0"` / `"anthropic.claude-3-5-sonnet-20241022-v2:0"`
- **Description:** Same pattern observed in Recipes 2.4, 2.5, and 2.6. The pseudocode uses illustrative family names; the Python pins currently-available versioned IDs. Python carries an explicit TODO note ("verify the exact model IDs available in your region and account") and a comment about cross-region inference profile prefixes (`us.` or `eu.`). A reader comparing the two files side by side will still notice the gap.
- **How to fix:** Optional. One-line note in the pseudocode saying Bedrock model IDs are versioned and the Python companion shows a specific working example. No code change required.

---

### Finding 11: `tier_suppress_render` rewrites citations via regex scanning of text rather than via `rec.source_citations`

- **Severity:** NOTE
- **Location:** `chapter02.09-python-example.md`, Step 10, the nested `_replace_citations` helper and its interaction with the pseudocode's structured `source_citations` field
- **Description:** The pseudocode in Step 10 iterates over `rec.source_citations` (the declared list of source IDs per recommendation) to build the bibliography and renumber citations. The Python implementation instead scans the recommendation text with a regex to find citations inline. The two approaches end up at the same place most of the time, because the generation prompt forces the model to emit `[src_N]` tokens both in the `source_citations` list and inline in the text. When they diverge, the regex-scan approach is more forgiving: a citation that appears inline but was not declared in `source_citations` still gets numbered and included in the bibliography.

  The functional implication is small, but it is a semantic divergence between pseudocode and Python. A reader comparing the two is left to reconcile whether to trust the declared list or the inline scan. The final `rec_rendered.pop("source_citations", None)` discards the declared list after rendering, so downstream consumers can only use the inline-scanned numbered references. This is workable; it is also worth a one-line comment.
- **How to fix:** Add a comment at the `_replace_citations` definition explaining the choice:
  ```python
  # We rewrite citations by scanning the text rather than iterating
  # rec.source_citations because the regex scan also catches citations
  # the model emits inline but forgets to declare. The numbered
  # bibliography is the source of truth for downstream rendering.
  ```
  No code change required.

---

## Pseudocode-to-Python Consistency

| Pseudocode Step | Pseudocode Function | Python Function | Consistent? |
|-----------------|---------------------|-----------------|-------------|
| Step 1 | `trigger_synthesis(trigger)` | Same | Yes (HealthLake call stubbed with a documented TODO; synthetic bundle stands in for a real datastore call; see Finding 3) |
| Step 2 | `normalize_patient_context(patient_bundle)` | Same | Yes (CKD-EPI 2021 race-free formula implemented with correct coefficients; BMI; derived-value section matches the pseudocode) |
| Step 3 | `determine_scope(trigger, ctx, history)` | Same | Yes (trigger-signature duplicate suppression uses an empty `_query_patient_history` stub by default; see Finding 7) |
| Step 4 | `run_deterministic_safety_checks(ctx, proposed_meds)` | Same | Yes (every pseudocode category is implemented as a structured Aurora query; allergy-match stub is fine with a docstring caveat; see Finding 8) |
| Step 5 | `classify_and_plan(ctx, scope, safety)` | Same | Yes (small model is called with a JSON-constrained system prompt; fallback to starter scenarios if the small-model call fails, which is the right posture) |
| Step 6 | `multi_source_retrieval(retrieval_plans)` | Same | Yes (hybrid retrieval = embedding + BM25, fused with reciprocal rank; structured SQL for drug-DB renal-dosing lookups) |
| Step 7 | `rank_and_filter(results, ctx)` | Same | Yes (authority + recency + population specificity + RRF, with weighted sum; trim to TOP_GUIDELINE_CHUNKS / TOP_PROTOCOL_CHUNKS) |
| Step 8 | `generate_synthesis(...)` | Same | Yes (structured JSON output enforced via prompt, temperature 0.1, optional Guardrail kwargs, primary guardrail signal via `amazon-bedrock-guardrailAction`; see Finding 4 for the dead-code tuple member and Finding 5 for character-slice truncation) |
| Step 9 | `validate_synthesis(...)` | Same | Yes (citation existence, dose verbatim, safety-finding coverage, contraindication/allergy contradiction, directive-language scan, scope compliance; see Finding 6 for dose-regex coverage) |
| Step 10 | `tier_suppress_render(...)` | Same | Yes in structure; citation renumbering uses regex scan rather than `rec.source_citations` iteration (Finding 11); `_replace_citations` has a latent substring bug for bare citations (Finding 2) |
| Step 11 | `archive_and_log(...)` | Same | Yes (S3 writes with SSE-KMS, DynamoDB update with aliased reserved word, CloudWatch metric emission, feedback token generation) |

The `run_cds_synthesis` orchestrator chains all eleven steps with explicit handling for the suppression, no-evidence, parse-failure, grounding-rejected, and validation-retry paths. The retry loop exit on `REVIEW_REQUIRED` is where Finding 1 lives; the rest of the orchestration matches the pseudocode's intent.

---

## AWS SDK Accuracy

### Bedrock Runtime `invoke_model` (Anthropic messages format)

```python
bedrock_runtime.invoke_model(
    modelId=SMALL_MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens":        1500,
        "temperature":       0.0,
        "system":            classification_system,
        "messages":          [{"role": "user", "content": user_prompt}],
    }),
)
```

- Parameter names (`modelId`, `contentType`, `accept`, `body`): correct
- Anthropic body schema (`anthropic_version`, `max_tokens`, `temperature`, `system`, `messages`): correct for Claude on Bedrock
- Message role `"user"` with string content: correct for single-turn text input
- Response parsing `json.loads(response["body"].read())` then `payload["content"][0]["text"]`: correct for Anthropic messages responses on Bedrock
- Temperature choices are disciplined: 0.0 for scenario classification (deterministic), 0.1 for synthesis (low-variance but some flexibility), which is the right posture for CDS
- Guardrail kwargs (`guardrailIdentifier`, `guardrailVersion`) are attached conditionally when the IDs are configured — correct parameter names
- Guardrail intervention signal read from `amazon-bedrock-guardrailAction` — correct (see Finding 4 for the minor dead-code concern)

### Bedrock Runtime (Titan Text Embeddings v2)

```python
response = bedrock_runtime.invoke_model(
    modelId=EMBEDDING_MODEL_ID,
    contentType="application/json",
    accept="application/json",
    body=json.dumps({"inputText": text}),
)
```

- Request body shape (`inputText`): correct for `amazon.titan-embed-text-v2:0`
- Response parsing `payload["embedding"]`: correct
- Default dimension is 1024 (matches the OpenSearch `knn_vector` config documented in the setup notes)
- Comment explicitly warns that the embedder must match whatever indexed the corpus, which is the class of bug that silently wrecks retrieval quality

### RDS Data API `execute_statement`

```python
rds_data.execute_statement(
    resourceArn=AURORA_CLUSTER_ARN,
    secretArn=AURORA_SECRET_ARN,
    database=AURORA_DATABASE,
    sql=sql,
    parameters=parameters,
    includeResultMetadata=True,
)
```

- Parameter names (`resourceArn`, `secretArn`, `database`, `sql`, `parameters`, `includeResultMetadata`): correct
- Parameter list uses dicts shaped `{"name": ..., "value": {"stringValue" | "doubleValue": ...}}`: correct typed-cell format
- Named `:placeholder` style in SQL with parameterized parameters list: correct, and protects against injection
- `_data_api_cell_value` helper correctly unwraps the typed-cell return format into plain Python values
- `includeResultMetadata=True` is necessary for the column-name mapping downstream; correctly set

### OpenSearch (k-NN + BM25 hybrid)

```python
{
    "size": size,
    "query": {
        "bool": {
            "must":   [{"knn": {"embedding": {"vector": query_vector, "k": size}}}],
            "filter": base_filter,
        }
    },
    "_source": {"excludes": ["embedding"]},
}
```

- k-NN body shape (`knn.embedding.vector`, `k`): correct for the OpenSearch k-NN plugin
- `_source.excludes: ["embedding"]` avoids pulling the vector back with every hit: correct optimization
- BM25 uses `multi_match` with `best_fields` and a weighted field list: correct
- IAM auth via `AWS4Auth` with service `"es"` and a note pointing at `"aoss"` for Serverless: correct
- Filter clauses: `term` for single-valued fields, `terms` for multi-valued, `range` for publication year: correct shapes
- Reciprocal Rank Fusion `K=60` is the standard choice

### S3 `put_object`

```python
s3_client.put_object(
    Bucket=SYNTHESIS_ARCHIVE_BUCKET,
    Key=rendered_key,
    Body=json.dumps(rendered, indent=2, default=str).encode("utf-8"),
    ContentType="application/json",
    ServerSideEncryption="aws:kms",
    SSEKMSKeyId=SYNTHESIS_ARCHIVE_CMK_ARN,
)
```

- Parameter names: correct
- `Body` passed as bytes (UTF-8 encoded): correct
- `default=str` in `json.dumps` safely handles any `datetime` slipping through: correct defensive choice
- `ServerSideEncryption="aws:kms"` with `SSEKMSKeyId`: correct PHI-posture for the archive (customer-managed key)
- S3 keys (`syntheses/{synthesis_id}/rendered.json`, `syntheses/{synthesis_id}/trace.json`): no leading slashes, no reserved characters, UUID-based uniqueness

### DynamoDB

- `syntheses_table.put_item(Item=_to_decimal_safe({...}))` in Step 1: every numeric or nested value is funneled through `_to_decimal_safe`, which routes floats through `Decimal(str(value))`
- `syntheses_table.update_item(...)` in Steps 1 and 11: `ExpressionAttributeNames={"#s": "status"}` correctly escapes the reserved word; `ExpressionAttributeValues` carries string values (`":s"`, `":rk"`, `":tk"`, `":d"`, `":u"`) and int counts (`":nr"`, `":n"`); no floats reach the update
- No DynamoDB put/update in the code writes a Python float

### CloudWatch `put_metric_data`

```python
cloudwatch.put_metric_data(
    Namespace="ClinicalDecisionSupport",
    MetricData=[
        {
            "MetricName": "SynthesisDelivered",
            "Dimensions": [
                {"Name": "UncertaintyTier",
                 "Value": rendered.get("overall_uncertainty", "unknown")},
            ],
            "Value": 1.0,
            "Unit":  "Count",
        },
        ...
    ],
)
```

- Parameter shape (`Namespace`, `MetricData` list with `MetricName`, `Dimensions`, `Value`, `Unit`): correct
- `Unit="Count"` with numeric `Value`: correct
- Three distinct metrics emitted per synthesis (delivered, recommendation count, safety-finding count) gives a useful base for CloudWatch dashboards and alarms

### Bedrock Guardrails invocation

- `guardrailIdentifier` / `guardrailVersion` parameter names on `invoke_model`: correct
- Conditional attachment only when both are configured: correct posture for the teaching example (defaults to `None` with an explicit warning that production should configure one)
- Comment at the config block explicitly notes that contextual grounding is the feature that matters most for clinician-facing CDS and that the threshold should be 0.85+: good guidance
- Intervention-detection field: primary check on `amazon-bedrock-guardrailAction` (correct); see Finding 4 for the dead-code concern

---

## DynamoDB Decimal Check

- `_to_decimal_safe` helper present, recursively walks dicts and lists, routes floats through `Decimal(str(value))` (the correct pattern that avoids binary-precision drift from `Decimal(float_value)`)
- Every `put_item` wraps its `Item` through `_to_decimal_safe`: verified at `trigger_synthesis`
- Every `update_item` in the code passes only strings and ints via `ExpressionAttributeValues`: no float writes
- CloudWatch `Value` is a float, which is correct for the CloudWatch API (not a DynamoDB concern)
- Aurora Data API parameters use `{"doubleValue": float(...)}`, which is correct for the Data API (not a DynamoDB concern)

Result: no Python float reaches DynamoDB. Pass.

---

## S3 Key Check

All S3 keys inspected: `syntheses/{synthesis_id}/rendered.json`, `syntheses/{synthesis_id}/trace.json`. No leading slashes, no reserved characters, all use UUIDs for uniqueness. The bucket is configured with a KMS CMK and the writes set `ServerSideEncryption="aws:kms"` and `SSEKMSKeyId`, which is the right posture for PHI archive content.

Pass.

---

## Module-Level Imports and Clients

- Standard library imports (`json`, `logging`, `re`, `time`, `uuid`, `datetime`, `timezone`, `Decimal`, `defaultdict`): all used at least once
- Third-party imports (`boto3`, `botocore.config.Config`, `botocore.exceptions.ClientError`, `opensearchpy.OpenSearch`, `opensearchpy.RequestsHttpConnection`, `requests_aws4auth.AWS4Auth`): all used
- boto3 clients (`bedrock_runtime`, `comprehend_medical`, `s3_client`, `dynamodb`, `cloudwatch`) instantiated at module load with shared adaptive-retry config: correct
- HealthLake, Aurora Data API, and Secrets Manager clients created lazily inside the functions that use them, with a rationale comment ("so the example runs without those services configured"): correct trade-off for a teaching example
- Client re-use across Lambda warm containers is implicit in the module-level instantiation

Pass.

---

## Comment Quality

Comments consistently explain the "why," not just the "what." High-value examples:

- "CRITICAL: this must match whatever embedder indexed the guideline corpus. If the corpus was indexed with Titan v2 and this function uses Titan v1, retrieval quality will be garbage and you won't get an error." This is exactly the class of silent failure the main recipe warns about.
- "DynamoDB raises TypeError on Python floats. This helper is the muscle memory that prevents that." Short, memorable, and names the exact exception.
- "Going through str avoids the binary-precision issues that Decimal(float_value) introduces." The second half of the Decimal gotcha that many teams learn the hard way.
- "Structured logging. In production, ship JSON-formatted records to CloudWatch Logs Insights for query-friendly analysis. The patient context and the synthesized recommendation contain PHI; never log them in plain text." PHI posture called out at the logger setup, not buried in prose.
- "Adaptive retry handles Bedrock throttling. CDS workload is naturally bursty (morning rounds, admission spikes, shift change). Adaptive mode uses exponential backoff with jitter so retry storms don't pile on." Explains both the choice and the workload shape.
- The heads-up block at the top labels every clinical output as SYNTHETIC and lists every production gap (no corpus ingestion, no drug-database licensing integration, no Step Functions wiring, no EHR launch, no post-market surveillance). This frames the entire example correctly for a learner.
- Step-level comments at every function explicitly name the pseudocode function they implement, which makes the eleven-step mapping traceable without jumping between files.
- The Gap-to-Production section is substantial and honest: corpus ingestion as 50-70% of total effort, source licensing, FDA exemption documentation, the PHI-minimization-in-prompts posture, and the clinician-is-the-decision-maker principle are all called out with concrete guidance.

The pseudocode callouts in each section header ("The pseudocode calls this ...") help a reader navigate the two files together.

---

## Healthcare-Specific Requirements

- **PHI logging:** Logger setup comment explicitly says "The patient context and the synthesized recommendation contain PHI; never log them in plain text." Log statements use identifiers only (synthesis_id, patient_id, counts) and structural metadata. Pass.
- **Encryption:** SSE-KMS is set on every S3 write with a customer-managed key ARN. The main-recipe Prerequisites block calls out distinct KMS keys for corpus vs PHI archive, which the code reflects by parameterizing `SYNTHESIS_ARCHIVE_CMK_ARN` (and the comment notes the distinct-keys recommendation). Pass.
- **BAA / HIPAA context:** Setup section notes Bedrock, HealthLake, Comprehend Medical, Aurora, OpenSearch, DynamoDB, and S3 all HIPAA-eligible under BAA; every service in the pipeline is covered. Pass.
- **Synthetic data:** The heads-up and in-line example comments explicitly label every clinical artifact as SYNTHETIC. "Do not treat any specific recommendation, dose, or citation in this file as real clinical guidance." Pass.
- **Retention:** Gap section notes archive retention per institutional medical-record and regulatory policy (typically years); S3 traces at 90 days as a separate, shorter retention. Pass.
- **Provenance and validation:** `validate_synthesis` does substantive work: citation existence, dose verbatim against cited structured records, safety-finding coverage, contraindication/allergy contradiction, directive-language scan, scope compliance. The trace archive retains the full validation result for audit. Pass (modulo Finding 1 on the auto-deliver bug).
- **Deterministic safety checks:** Step 4 runs structured SQL against Aurora for every drug pair, every proposed-drug / allergy combination, every proposed-drug / renal-function combination, and every proposed-drug / active-condition combination. Findings are passed to the generator as a "must include" block that the validator enforces. This is exactly the pattern the main recipe argues for ("safety checks as LLM prompts is not a safety check"). Pass.
- **FDA CDS exemption posture:** Prompt enforces options-not-directives framing in the model's own voice; validator scans for directive phrases; scope-compliance check flags out-of-scope recommendations; citation discipline is enforced at the prompt, the guardrail, and the validator. The final `rendered` payload includes a prominent disclaimer ("This is a decision support synthesis. Review the sources before acting. The clinician is the decision-maker."). Pass in architecture; the auto-deliver bug in Finding 1 undermines this in practice until fixed.
- **Source licensing posture:** Bibliography carries `source_type` and `source_url` for every cited record; a real implementation can use these fields to enforce per-source redistribution constraints. The Gap section calls out licensing as a first-class project. Pass.
- **PHI minimization in prompts:** Gap section explicitly notes that the prompts include the full patient context, that Bedrock under BAA is compliant, and that minimum-necessary argues for redacting direct identifiers (name, MRN) before sending to the model. Documented; not implemented. Pass for a teaching example.
- **Alert fatigue:** Suppression logic present in `determine_scope` (trigger-signature duplicate-suppression with a `SUPPRESSION_WINDOW_MINUTES` configurable) and `tier_suppress_render` (per-recommendation delivery tier against prior engagement). Exercising both requires a real `_query_patient_history` (stub; Finding 7). Documented; the architecture is right. Pass.

---

## Logical Flow

The code reads cleanly top-to-bottom:

1. Imports and module-level clients
2. Configuration constants grouped by concern (model IDs, OpenSearch, Aurora, HealthLake, storage, pipeline tuning, source authority ranking, high-alert drug classes, out-of-scope patterns, directive phrases)
3. Shared helpers (timestamp, OpenSearch client, embedder, JSON parser, UTF-8 truncator, Decimal converter, Aurora Data API wrapper)
4. Step 1: trigger and fetch patient context, with a documented HealthLake stub
5. Step 2: normalize and structure (CKD-EPI 2021 implemented; BMI; active-conditions, medications, allergies, recent labs)
6. Step 3: scope determination with trigger-type-specific rules and duplicate suppression
7. Step 4: deterministic safety checks across interactions, allergies, renal dosing, contraindications, duplicate therapy
8. Step 5: scenario classification via small model with retrieval plan construction
9. Step 6: multi-source retrieval with hybrid OpenSearch search and structured Aurora lookups
10. Step 7: rank and filter with authority + recency + population + RRF weighting
11. Step 8: grounded synthesis with the stronger model, optional Guardrail attachment, and structured JSON output
12. Step 9: post-generation validation with six check categories and retry/review disposition
13. Step 10: tier, suppress, render with per-recommendation delivery-tier assignment and citation renumbering
14. Step 11: archive and log to S3 and DynamoDB with CloudWatch metric emission
15. `run_cds_synthesis` orchestrator chaining all eleven with the generation/validation retry loop (Finding 1 lives here)
16. Synthetic `__main__` example with a 2-AM ICU scenario matching the main recipe's opening vignette

The orchestrator's step-by-step `print` statements make the flow visible in a demo run even though the structured logger is not wired to a handler (Finding 9).

---

## What Is Clean

- DynamoDB `_to_decimal_safe` helper is applied consistently on every `put_item` and handles nested dicts and lists recursively
- S3 `put_object` calls all set `ServerSideEncryption="aws:kms"` with a customer-managed key ARN
- Aurora Data API uses parameterized `:name` placeholders with typed-cell values, avoiding the SQL-injection pitfall that comes with f-string interpolation
- Bedrock `invoke_model` uses the correct Anthropic messages body shape at both call sites (classification and synthesis)
- Titan Text Embeddings request body uses `{"inputText": text}` (correct for v2) and the response parses `payload["embedding"]` (correct)
- The k-NN OpenSearch query correctly uses `knn.embedding.vector` and `_source.excludes: ["embedding"]`
- Deterministic safety checks run as structured SQL before the LLM sees the prompt, and the findings are threaded into the prompt as a "must include" block enforced by the validator
- The validator does substantive work (citations, dose verbatim, safety-finding coverage, contraindication/allergy contradiction, directive language, scope compliance) and distinguishes HIGH from MEDIUM severity for the retry decision
- CKD-EPI 2021 race-free formula is implemented with correct coefficients (κ = 0.7/0.9, α = -0.241/-0.302, male/female multiplier 1.0/1.012, age term 0.9938^age, overall constant 142)
- `_safe_utf8_truncate` correctly encodes to UTF-8 before slicing by byte, handles multi-byte characters, and is documented with the rationale
- The JSON parser helper `_parse_json_response` strips both `` ```json `` and `` ``` `` fences defensively, which matches how Claude sometimes wraps JSON even when instructed not to
- The heads-up block up top labels every clinical output as SYNTHETIC and enumerates every production gap so a learner cannot mistake the example for a deployable artifact
- The eleven-step header comments explicitly reference the pseudocode function each Python function implements, making cross-file navigation easy
- Cost discipline: `MAX_GENERATION_ATTEMPTS` caps retries, the retrieval sizes are bounded, two model tiers are used by role (classification on the small model, synthesis on the capable model), and the Gap section calls out per-user/per-patient-day rate limits as a production requirement

---

## Closing Assessment

This is strong code. The pseudocode-to-Python mapping is one-to-one and clean, boto3 usage is current and correct, DynamoDB `Decimal` handling is disciplined, S3 keys are clean, SQL is parameterized, KMS encryption is set on every PHI write, the deterministic safety layer is a genuine safety check rather than an LLM prompt, and the validator enforces citation and dose fidelity along with safety-finding coverage. The pedagogical comments explain "why" in the places where a learner would otherwise make the wrong call (embedder / index alignment, Decimal serialization, adaptive retry, byte-limit handling, PHI posture in logs).

The two WARNINGs sit at the boundary of the orchestrator and the validator. Finding 1 is the auto-deliver bug on `REVIEW_REQUIRED`: a synthesis that fails validation after exhausting retries still ships with `status = DELIVERED`, which bypasses the validator the architecture is built around. Finding 2 is the citation-replacement substring-match bug that corrupts rendered output if the model ever emits bare `src_N` tokens. Both are fixable with small, localized changes, and both would benefit from a re-review against a small regression test.

The NOTE findings are editorial: a dead match in the guardrail tuple, a character-slice context truncation, a dose-regex that misses weight-based dosing, the documented stubs for HealthLake and patient history, and a missing logger handler. None block re-review.

The main recipe's "Gap to Production" section is mirrored thoroughly in the Python file's own gap section, and the architecture decisions (grounded synthesis with deterministic safety checks as hard inputs, citation discipline enforced at three layers, alert-fatigue suppression as a first-class concern, clinician-as-decision-maker framing) are preserved correctly in the code. The verdict is PASS with the two WARNINGs flagged for follow-up.

---

## Re-review checklist

When this review is addressed, a re-reviewer should verify:

1. The orchestrator distinguishes `REVIEW_REQUIRED` from `VALIDATED` after the retry loop exits, routes the `REVIEW_REQUIRED` path to a human-review queue (or a distinct DynamoDB status like `ROUTED_TO_REVIEW`), and does NOT call `archive_and_log` with `status = DELIVERED` for any synthesis whose validation status is anything other than `VALIDATED` (or, for the no-evidence case, `NO_EVIDENCE`).
2. `_replace_citations` uses a regex-based substitution (or a length-sorted replacement order) that does not match bare `src_1` as a prefix of `src_10`. A synthetic test that feeds the helper a string containing both `src_1` and `src_10` should produce correctly numbered output with neither token corrupted.
3. (Optional) The guardrail tuple is reduced to `("INTERVENED",)` or a single-value check against `"INTERVENED"`, and the cosmetic `"guardrail_intervened"` string is dropped or explicitly documented as a no-op historical alias.
4. (Optional) A short comment is added at the `[:4000]` character-slice noting that the slice is a coarse proxy for token budget and pointing at a tokenizer-aware truncator as the production replacement.
5. (Optional) The dose regex is extended to cover `mg/kg`, `mcg/kg/min`, and weight-based dosing variants, or a short comment notes the current coverage as a starter.
6. (Optional) `logging.basicConfig(level=logging.INFO, format="...")` is added to the Configuration block so the structured log messages reach the console in a direct `__main__` run.
