# Code Review: Recipe 2.7 Literature Search and Evidence Synthesis (Python Companion)

**Reviewer:** TechCodeReviewer
**Files reviewed:**
- `chapter02.07-literature-search-evidence-synthesis.md` (main recipe, pseudocode in the Code/Walkthrough section)
- `chapter02.07-python-example.md` (Python companion)

**Verdict:** **FAIL**

Two ERROR findings (automatic FAIL), plus a handful of WARNING and NOTE-level items. The most damaging issue is a citation-rendering bug in Step 9 that will reliably corrupt bibliography numbering when any chunk_1X identifier appears in the cited set, which is very likely under the recipe's own `TOP_K_FOR_GENERATION = 15`. The second ERROR is a regression on a bug that the Recipe 2.6 code review already flagged: the Guardrail intervention check compares Anthropic Claude's `stop_reason` against `"guardrail_intervened"`, a value Claude does not emit. The recipe's own pseudocode in Step 7 explicitly instructs the reader to use `amazon-bedrock-guardrailAction`, so the Python companion contradicts the main recipe on a safety-critical check.

The broader pipeline is well structured, the step-to-step mapping from pseudocode to Python is clean, the comments do a good job explaining the *why* (not just the *what*), and the Gap-to-Production section correctly identifies most of the real pitfalls (corpus ingestion, re-ranker choice, embedder lifecycle, VPC/encryption posture, Decimal handling, prompt versioning). Fix the two ERRORs and address the WARNINGs and this recipe reaches the bar that Chapter 2.08 and Chapter 2.09 cleared.

---

## Findings

### Finding 1: Citation rendering corrupts any double-digit chunk identifier (ERROR)

- **Severity:** ERROR
- **Location:** `chapter02.07-python-example.md`, Step 9 `render_answer`, the `for cid, display_num in citation_map.items()` loop
- **What's wrong:**

  The rendering loop uses unanchored string replacement on bare identifiers:

  ```python
  rendered_answer = answer_text
  for cid, display_num in citation_map.items():
      rendered_answer = rendered_answer.replace(cid, f"{display_num}")
  ```

  `cid` is a bare identifier like `"chunk_1"` (no brackets). `str.replace` matches every substring occurrence, and `"chunk_1"` appears as a prefix of `"chunk_10"`, `"chunk_11"`, ..., `"chunk_15"`. Because `citation_map` is iterated in insertion order (which is first-appearance-in-answer order), a single-digit chunk almost always gets replaced before the double-digit chunks that contain it as a prefix. The result is that a double-digit chunk reference gets partially overwritten, producing a malformed citation that the later cleanup regex (`re.sub(r"\[chunk_\d+\]", "", rendered_answer)`) does not catch.

  Concrete trace with `citation_map = {"chunk_1": 1, "chunk_12": 2}` and answer text `"Findings [chunk_1] and [chunk_12]"`:

  1. Iteration 1 replaces `"chunk_1"` with `"1"`. The `"chunk_1"` inside `"[chunk_12]"` is also matched. Result: `"Findings [1] and [12]"`.
  2. Iteration 2 tries to replace `"chunk_12"`, but the substring no longer exists (it was corrupted to `"12"`). No change.
  3. The final `re.sub(r"\[chunk_\d+\]", ...)` cleanup does not fire on `"[12]"` because the pattern requires the literal `chunk_` prefix.

  Final rendered output: `"Findings [1] and [12]"`. The reader sees a citation `[12]` that does not exist in the bibliography, and the correct citation `[2]` is missing. With `TOP_K_FOR_GENERATION = 15`, any cited chunk whose identifier is 10 through 15 is subject to this bug whenever `chunk_1` is also cited and appears earlier in the prose.

  This is a correctness bug that will surface on real output, not a corner case. It also teaches a misleading pattern: identifier replacement without bracket anchoring is a common pitfall, and the code silently propagates it.

- **How to fix:**

  Use a single regex substitution with a callback so every `[chunk_N]` marker is replaced in one pass and no partial matches happen. Preserve the bracket anchoring:

  ```python
  def _citation_replacer(match):
      cid = f"chunk_{match.group(1)}"
      display_num = citation_map.get(cid)
      if display_num is None:
          return ""  # unresolved marker, strip it
      return f"[{display_num}]"

  rendered_answer = re.sub(r"\[chunk_(\d+)\]", _citation_replacer, answer_text)
  ```

  This collapses the current two-step process (replace + cleanup) into one pass, eliminates the prefix-collision bug, and handles unresolved markers in the same step. Worth a comment that explains why bare-substring replace is unsafe when identifiers can be prefixes of each other.

---

### Finding 2: Guardrail intervention check uses a `stop_reason` value Anthropic Claude does not emit (ERROR)

- **Severity:** ERROR
- **Location:** `chapter02.07-python-example.md`, Step 7 `generate_synthesis`, the block that reads `stop_reason = response_payload.get("stop_reason")` and compares to `"guardrail_intervened"`
- **What's wrong:**

  The Python code detects Guardrail interventions like this:

  ```python
  stop_reason = response_payload.get("stop_reason")
  if stop_reason == "guardrail_intervened":
      logger.warning("Guardrail intervened on synthesis; returning rejection")
      return {"status": "GROUNDING_REJECTED", ...}
  ```

  Anthropic Claude's documented `stop_reason` values on Bedrock `InvokeModel` are `"end_turn"`, `"stop_sequence"`, `"max_tokens"`, `"tool_use"`, and (on newer model versions) `"pause_turn"` / `"refusal"`. `"guardrail_intervened"` is not in that set. When a Bedrock Guardrail intervenes on an `InvokeModel` call, the intervention is signaled by the top-level `amazon-bedrock-guardrailAction` field in the response body (values `"INTERVENED"` or `"NONE"`), typically paired with `amazon-bedrock-trace` metadata when trace is enabled. The raw Anthropic `stop_reason` is unaffected.

  This means the check never matches. Guardrail interventions are silently ignored, the GROUNDING_REJECTED path is dead code, and the retry loop in the orchestrator never triggers when the Guardrail fires. The outer `invoke_model` call will still return the guardrail's configured blocked response (often a generic "Sorry, I can't help with that" payload), so the pipeline will happily run that sanitized string through the validator and downstream renderer as if it were a real synthesis.

  This bug is particularly notable because:

  - The recipe's own pseudocode in Step 7 explicitly calls this out in an inline comment: *"Check for Guardrail intervention on the response (via amazon-bedrock-guardrailAction field, not stop_reason)"*. The Python companion contradicts the main recipe.
  - The same bug was flagged in the Chapter 2.06 code review (Finding 2). Chapter 2.09's Python companion adopted the correct pattern (checking both fields defensively). Recipe 2.7 regressed to the earlier broken pattern.
  - The comment above the check in the Python code claims *"Field shape varies by Guardrail configuration; verify against your setup and branch accordingly"*, which softens nothing, because no documented Guardrail configuration causes `stop_reason` to equal `"guardrail_intervened"` for `InvokeModel`.

- **How to fix:**

  Check the top-level `amazon-bedrock-guardrailAction` field in the response body. For defensive coding, check `stop_reason` as a secondary signal, but the primary must be `amazon-bedrock-guardrailAction`:

  ```python
  guardrail_action = response_payload.get("amazon-bedrock-guardrailAction")
  if guardrail_action == "INTERVENED":
      logger.warning("Guardrail intervened on synthesis; returning rejection")
      return {"status": "GROUNDING_REJECTED", "answer_text": "", "claims": []}
  ```

  Update the surrounding comment to match: the contextual grounding check requires explicit grounding-source tagging (via `guardContent` blocks in Converse, or the equivalent grounding-source mechanism in the Guardrails policy), and intervention is detected via `amazon-bedrock-guardrailAction`. This aligns the Python with the recipe's own pseudocode.

---

### Finding 3: `_embed_text` is silently hard-coded to Titan's request and response schema (WARNING)

- **Severity:** WARNING
- **Location:** `chapter02.07-python-example.md`, Shared Helpers section, `_embed_text`
- **What's wrong:**

  The embedder helper uses Titan's schema for both request and response:

  ```python
  body = json.dumps({"inputText": text})
  ...
  return payload["embedding"]
  ```

  The Configuration section acknowledges that `EMBEDDING_MODEL_ID` is a config knob and says *"this must match whatever embedder indexed the corpus."* It does not warn that different embedder families use different body schemas. Cohere Embed expects `{"texts": [text], "input_type": "search_query"}` and returns `{"embeddings": [[...]]}` (plural, nested list). A reader who swaps `EMBEDDING_MODEL_ID` to `cohere.embed-english-v3` will get a silent failure: `json.dumps({"inputText": text})` will produce a 400 from Bedrock, or worse, if the body happens to parse, `payload["embedding"]` will KeyError.

  Recipes 2.8 and 2.9 (Ambient Clinical Documentation, Clinical Decision Support) both warn readers about request-body differences between embedder families. Chapter 1.x Python companions did the same for Textract vs Comprehend Medical. This recipe does not.

- **How to fix:**

  Add a comment inside `_embed_text` that explicitly notes the Titan-specific shape and points to where to branch for other embedder families:

  ```python
  # This helper is hard-coded to Amazon Titan Text Embeddings request/response shape.
  # Other embedders on Bedrock use different schemas:
  #   - Cohere Embed: body = {"texts": [text], "input_type": "search_query"};
  #     response payload has "embeddings" (plural, list of lists).
  #   - Self-hosted biomedical embedders on SageMaker: use sagemaker-runtime client
  #     and whatever input/output format the endpoint's inference.py expects.
  # If you change EMBEDDING_MODEL_ID to a non-Titan model, update the body shape
  # and response parsing here accordingly.
  ```

  Pedagogically, the learner needs to understand that the embedder swap is not just a model-ID change; it's a format change that ripples through this helper.

---

### Finding 4: OpenSearch k-NN with boolean filter uses post-filtering without flagging the precision/recall trade-off (WARNING)

- **Severity:** WARNING
- **Location:** `chapter02.07-python-example.md`, Step 3 `multi_source_retrieval`, the `knn_query` body
- **What's wrong:**

  The k-NN query places the k-NN clause inside `bool.must` and the metadata filter inside `bool.filter`:

  ```python
  knn_query = {
      "size": INITIAL_RETRIEVAL_SIZE,
      "query": {
          "bool": {
              "must": [{
                  "knn": {
                      "embedding": {
                          "vector": query_vector,
                          "k": INITIAL_RETRIEVAL_SIZE,
                      }
                  }
              }],
              "filter": base_filters,
          }
      },
      ...
  }
  ```

  With the Approximate k-NN engine (Lucene, nmslib, or faiss), this structure applies the filter *after* the initial k-NN candidate set is returned, not during graph traversal. In practice this means: if the graph returns 50 nearest neighbors and most are outside the 15-year window, you can end up with far fewer than 50 post-filter results, or in extreme cases zero. This is a well-known OpenSearch pitfall.

  OpenSearch supports "efficient filtering" for k-NN where the filter is specified *inside* the `knn` clause and the engine's filtering integrates with ANN traversal. For the `lucene` engine, this is supported and typically preferred for population-aware retrieval. The syntax is:

  ```python
  {
      "query": {
          "knn": {
              "embedding": {
                  "vector": query_vector,
                  "k": INITIAL_RETRIEVAL_SIZE,
                  "filter": {"bool": {"must": base_filters}}
              }
          }
      }
  }
  ```

  The current code will work (the retrieval is post-filtered), but it will underperform on recall for the exact population-aware filters the recipe leans on (adult vs pediatric, recent date ranges). A reader studying this for production RAG will build on it and be surprised later.

- **How to fix:**

  Either switch the snippet to use the efficient-filter syntax with a comment explaining why, or add a comment to the current structure that acknowledges the post-filter behavior and points to OpenSearch's documentation on k-NN filtering. Example comment:

  ```python
  # Note: this structure applies metadata filters AFTER the initial k-NN
  # candidate set is returned (post-filtering). If your filters are restrictive
  # (e.g., a narrow date range or a rare population tag), consider OpenSearch's
  # efficient-filter syntax instead, which integrates filtering with ANN
  # traversal and preserves recall. See the OpenSearch k-NN filtering docs.
  ```

  This teaches the reader the right mental model without requiring the code example to pick a side.

---

### Finding 5: `authors` list is joined without type guarding (WARNING)

- **Severity:** WARNING
- **Location:** `chapter02.07-python-example.md`, Step 9 `_format_citation`
- **What's wrong:**

  ```python
  if isinstance(authors, list) and authors:
      if len(authors) > 3:
          author_str = f"{authors[0]}, et al."
      else:
          author_str = ", ".join(authors)
  ```

  The OpenSearch field schema at the top of the file declares `authors (keyword)`, which in the comment is implied to be a list of strings. In practice, medical corpora often store authors as structured objects (`{"last": "Smith", "first": "J", "affiliation": "..."}`) because PubMed XML carries that structure, and a team building the index might store the list of dicts rather than flatten to strings. If `authors` is a list of dicts, `", ".join(authors)` raises `TypeError: sequence item 0: expected str instance, dict found` and the whole rendering step fails.

  This is a teaching risk. A reader who stores PubMed author objects (the natural thing to do) hits a runtime failure that has nothing to do with the RAG pipeline they are trying to learn.

- **How to fix:**

  Either (a) explicitly document in the schema comment that `authors` must be a list of already-formatted strings (e.g., `"Smith J"`), or (b) defensively coerce to strings at render time:

  ```python
  author_strs = [
      a if isinstance(a, str) else f"{a.get('last', '')} {a.get('first', '')}".strip()
      for a in authors
  ]
  if len(author_strs) > 3:
      author_str = f"{author_strs[0]}, et al."
  else:
      author_str = ", ".join(author_strs)
  ```

  Option (a) is fine for a teaching example; just make the schema comment explicit. Option (b) is more forgiving but heavier. Either is better than the current silent fragility.

---

### Finding 6: Re-ranker batch size and prompt length interact badly without a safeguard (NOTE)

- **Severity:** NOTE
- **Location:** `chapter02.07-python-example.md`, Step 4 `rerank_candidates`
- **What's wrong:**

  `BATCH_SIZE = 10` with chunk snippets truncated to 600 characters each produces prompts in the 6-10 KB range, which is fine. But the function does not cap the total number of passages forwarded. If `len(candidates) == RERANK_CANDIDATE_LIMIT == 100`, the code issues 10 batched model calls. That is acceptable. However, there is no guardrail against accidental misconfiguration: a reader who changes `RERANK_CANDIDATE_LIMIT` to 500 and leaves `BATCH_SIZE = 10` will issue 50 Bedrock calls per question, and the cost shock is on them.

  This is a small pedagogical miss. The stand-in re-ranker pattern is already flagged as "not production quality" in the prose, which is good. A one-line comment noting that re-ranker cost scales linearly with candidate count, and that large candidate sets should use a cross-encoder on SageMaker rather than more small-LLM batches, would close the loop.

- **How to fix:**

  Add a comment near `BATCH_SIZE`:

  ```python
  # Re-ranker cost scales linearly with candidate count. For RERANK_CANDIDATE_LIMIT
  # above ~150, switch to a cross-encoder on SageMaker rather than scaling up the
  # number of small-LLM batches; the cost curve crosses over quickly.
  ```

  Low-impact, keeps readers out of a common mistake.

---

### Finding 7: `_get_corpus_date_range_stub` is called in the rendered output but is a static placeholder (NOTE)

- **Severity:** NOTE
- **Location:** `chapter02.07-python-example.md`, Step 9 `render_answer` → helper `_get_corpus_date_range_stub`
- **What's wrong:**

  The rendered answer surfaces `"corpus_date_coverage": _get_corpus_date_range_stub()`, which returns the literal string `"Corpus coverage: stubbed for this example. In production, query the index metadata."` The main recipe's `Expected Results` section correctly emphasizes that corpus date coverage is a trust signal ("A banner that says 'The corpus contains evidence through April 2026. Recent developments may not be reflected.' is not a weakness; it's a trust signal."). Stubbing this field in the Python example is fine for teaching, but the UI contract it teaches (the rendered output literally says "stubbed for this example") is worth a stronger comment. If a reader copies this code into a production UI without noticing the stub, the clinician sees that string.

- **How to fix:**

  Either have the stub return an empty string (and add a `TODO` comment explaining what to populate), or make the stub function name and docstring impossible to miss:

  ```python
  def _get_corpus_date_range_stub() -> str:
      """
      PLACEHOLDER. In production, query the index's metadata record for the
      ingestion window and last-ingestion timestamp, e.g.:
          GET /medical-corpus/_doc/__meta__
      Return something like "Papers indexed 1990 through April 2026. Last
      ingestion: 2026-05-09." This string is rendered in the clinician UI
      and is a trust signal; do NOT ship the stubbed value.
      """
      return ""  # Prefer empty over a literal "stubbed" string ending up in the UI.
  ```

  Small change, avoids a surprising failure mode.

---

### Finding 8: `_extract_numeric_tokens` regex will not catch negative numbers, scientific notation, or non-ASCII characters common in medical literature (NOTE)

- **Severity:** NOTE
- **Location:** `chapter02.07-python-example.md`, Step 8 `_extract_numeric_tokens`
- **What's wrong:**

  The pattern captures positive decimals with optional ranges and a short unit allowlist:

  ```python
  pattern = re.compile(
      r"\d+(?:\.\d+)?"
      r"(?:\s*[-–]\s*\d+(?:\.\d+)?)?"
      r"(?:\s*(?:%|mg|mcg|g|kg|mL|IU|mmHg))?"
  )
  ```

  Medical literature commonly uses scientific notation (`p = 1.2e-4`), negative numbers for effect-size differences (`-0.15`), non-ASCII comparison operators (`≤`, `≥`), and a much broader unit vocabulary (`U/L`, `ng/mL`, `μg/mL`, `bpm`, `beats/min`, `×10^9/L`, `HR`, `OR`, `RR` with bracketed CIs). The current regex misses scientific notation and negatives entirely, which means any claim citing a p-value or a log-scale effect size is implicitly exempt from the verbatim-numeric check. The recipe's prose warns about "wrong direction" errors (a reduction vs an increase), so missing negatives is worth calling out.

  This is a reasonable simplification for a teaching example, but a one-line note in the docstring would help learners understand what the check actually covers.

- **How to fix:**

  Update the docstring to make the scope explicit, and/or broaden the regex. A small improvement:

  ```python
  pattern = re.compile(
      r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"  # optional sign, decimal, exponent
      r"(?:\s*[-–]\s*-?\d+(?:\.\d+)?)?"
      r"(?:\s*(?:%|mg|mcg|g|kg|mL|IU|mmHg|U/L|ng/mL|bpm))?"
  )
  ```

  And in the docstring, explicitly note that units not in the allowlist fall through to the token-overlap similarity check rather than the verbatim check.

---

### Finding 9: Feedback token issuance is unwired (NOTE)

- **Severity:** NOTE
- **Location:** `chapter02.07-python-example.md`, Step 10 `archive_and_log`
- **What's wrong:**

  ```python
  feedback_token = str(uuid.uuid4())
  ```

  The token is generated but never persisted. The DynamoDB update in the same function does not store it, and no comment points to where it should be recorded to be useful. In a real feedback flow, the token is what correlates a clinician's thumbs-up/thumbs-down event back to the query_id without requiring the client to hold the query_id itself (useful for privacy-scoped UI contexts). A reader following this example could believe that emitting a token is sufficient.

  The Gap-to-Production section mentions feedback-loop design, which is good. A one-line comment here, tying the token to the persistence story ("In production, either persist this token alongside query_id in DynamoDB with a TTL, or sign it as a short-lived JWT so the UI can echo it back on feedback submission") would connect the code to the architecture.

- **How to fix:**

  ```python
  # Issue a feedback correlation token. In production, persist this token in
  # DynamoDB alongside query_id with a short TTL (e.g., 48 hours), OR sign it
  # as a JWT with the query_id as a claim so the UI can echo it back on a
  # thumbs-up/thumbs-down event without exposing query_id to a less-trusted
  # client context. As written, the token is cosmetic.
  feedback_token = str(uuid.uuid4())
  ```

  Keeps the teaching honest without adding complexity.

---

## Positive Observations

A few things this example does well and that later recipes should preserve:

- **Step-by-step narrative matches the pseudocode.** Each Python function is labeled with the corresponding pseudocode function name in the header. The `answer_clinical_question` orchestrator prints step numbers as it runs. A reader can trace the recipe's numbered pseudocode to the exact Python block with no searching. This is the right pattern.
- **Comments explain *why* not just *what*.** The `_embed_text` comment about matching the embedder, the fused-score scoring formula in `multi_source_retrieval`, the retry logic comments in `validate_answer`, and the adaptive-retry rationale in the `BOTO3_RETRY_CONFIG` all teach the reasoning rather than narrating the code. This is the hardest thing to get right in teaching code.
- **Boundaries between pedagogy and production are honest.** The small-LLM re-ranker is explicitly called a stand-in, the Guardrail is set to `None` with a clear note that this is a demo, and the Gap-to-Production section covers cost control, embedder lifecycle, corpus licensing, PHI minimization, prompt versioning, and operational resilience. Readers walk away knowing what they would need to harden.
- **S3 keys are correctly formatted without leading slashes** (`answers/{query_id}/rendered.json`, `answers/{query_id}/trace.json`). No `s3://`-scheme leakage into Key parameters, which is the classic boto3 S3 mistake.
- **DynamoDB Decimal gotcha is addressed in prose.** The Gap-to-Production section explicitly calls out the float → Decimal conversion issue, and the sample inputs avoid floats in persisted fields. A reader who adds a float score to a `put_item` call will be warned by the prose. Better than many earlier recipes.
- **JSON parsing is defensive.** `_parse_json_response` and `_extract_trailing_json_block` handle markdown code-fence wrapping, which the model emits despite instructions not to. A reader who uses these patterns downstream will avoid a common class of runtime parse errors.
- **`_safe_utf8_truncate` for Comprehend Medical byte-limit enforcement** is a thoughtful touch. The byte vs character distinction is a real production bug for clinical text with multi-byte characters, and the helper does it correctly (encode, slice, decode with `errors='ignore'`).

---

## Summary

| Severity | Count |
|----------|-------|
| ERROR    | 2     |
| WARNING  | 3     |
| NOTE     | 4     |

Two ERRORs trigger automatic FAIL. Both are recoverable with small, targeted edits (a regex-based citation replacement in Step 9, and replacing the `stop_reason` check with an `amazon-bedrock-guardrailAction` check in Step 7). The WARNINGs are polish that a diligent reader will need, especially the embedder-schema note and the OpenSearch k-NN filter-behavior note. The NOTEs are teaching improvements that would move this recipe from "very good" to "set the template for the rest of Chapter 2."

Recommend returning to the TechWriter for the fixes to Findings 1 and 2 as blockers, and rolling the WARNING- and NOTE-level items into the same revision pass to avoid a second review cycle.
