# Expert Review: Recipe 2.7 - Literature Search and Evidence Synthesis

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-10
**Recipe file:** `chapter02.07-literature-search-evidence-synthesis.md`

---

## Overall Assessment

**Verdict: PASS**

This is the strongest Chapter 2 recipe so far on recurring-pattern hygiene. The recurring failure modes that have repeatedly torpedoed earlier Chapter 2 reviews are either addressed or acknowledged here. IAM permissions include "Scope every action to specific resource ARNs." The VPC endpoint list is comprehensive (Bedrock, Bedrock Runtime, Bedrock Agent Runtime, Comprehend Medical, KMS, Secrets Manager, Step Functions, CloudWatch Logs, CloudWatch Monitoring, EventBridge, plus gateway endpoints for S3 and DynamoDB) and includes the per-AZ-per-endpoint cost reminder. The Bedrock model-invocation-logging PHI-store note appears explicitly in the Encryption row and correctly flags that logged chunks may contain patient context from the question. OpenSearch is called out as VPC-only with fine-grained access control. The contextual grounding check discussion in Step 7 (the fix that was missing in Recipe 2.6) names both the explicit grounding-source tagging requirement (`guardContent` in Converse, grounding source in Guardrails config for InvokeModel) and the correct intervention-detection field (`amazon-bedrock-guardrailAction`, not `stop_reason`). No em dashes (direct check: zero). The "Why This Isn't Production-Ready" section is unusually substantive (corpus licensing, evaluation, prompt iteration, embedder lifecycle, temporal drift, bias in literature, regulatory posture, cost control at scale).

The core teaching is excellent. The opening vignettes (internist on methotrexate-anastrozole, pulmonary fellow on biologic continuation, payer medical director, clinical research coordinator) are vivid, specific, and clinically accurate. The "Why General-Purpose LLMs Are the Wrong Tool for This Job" section makes the fabricated-citation problem concrete without hedging. The "RAG Done for Grown-Ups" framing teaches real substance: corpus selection by evidence tier, section-aware medical chunking, hybrid retrieval with entity-driven BM25, query expansion, HyDE, cross-encoder re-ranking, metadata filtering, and evidence grading are each explained at engineer depth rather than buzzword depth. The "Hallucination Failure Modes You Have to Design Around" enumeration (citation fabrication, claim fabrication with real citation, over-generalization, wrong direction, population mismatch, temporal drift, non-answers presented as answers, equipoise collapsed, recommendation when asked to inform) is the best taxonomy of clinical RAG failure modes in this chapter. The "Honest Take" delivers genuine production wisdom: the demo-to-production gap, the corpus-quality blind spot, underestimating validation, specialty-specific failure modes, UX as part of the product, library-integrated design, and safety-interaction questions as a beachhead are all specific and hard-won.

Two HIGH findings cluster: the retrieval source-tier hard filter risks excluding all evidence for questions where only lower-tier studies exist, and corpus-ingestion idempotency is not addressed (same recurring Chapter 2 trigger-idempotency pattern, applied here to the scheduled ingestion workflow rather than an event-driven clinical workflow). Several MEDIUM findings address fake Bedrock model IDs in pseudocode that don't match current naming conventions (and don't match the Python companion's correct IDs), sign/direction validation not being implemented even though the recipe names wrong-direction as a "catastrophic error," PHI minimization for patient context sent to Comprehend Medical and to the generation prompt, and the architecture diagram's missing "validation retries exhausted" exit node (the pseudocode routes correctly, but the diagram shows an infinite retry loop).

Priority breakdown: 0 CRITICAL, 2 HIGH, 5 MEDIUM, 4 LOW.

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

- BAA is explicit in the Prerequisites table and correctly distinguishes corpus (generally not PHI) from query and answer (usually PHI because the question may contain patient context).
- S3 SSE-KMS with customer-managed keys, DynamoDB at-rest with CMK, OpenSearch encryption at rest and in transit with CMK, Bedrock and Comprehend Medical TLS. Parity across PHI stores.
- IAM row explicitly says "Scope every action to specific resource ARNs." First recipe since 2.6 to carry the fix forward.
- Bedrock model-invocation-logging PHI-store note is present in the Encryption row with the correct framing: "the chunks may reference patient context from the question. Log destination must be KMS-encrypted to the same standard as the answer archive." This addresses the finding that recurred across 2.2, 2.3, 2.4, 2.5 reviews.
- CloudTrail data events are called out for Bedrock, S3, DynamoDB, and Secrets Manager. Correlation to requesting clinician identity is mentioned.
- Synthetic-data posture is correct. MedQA and BioASQ are cited for evaluation; PMC Open Access and PubMed abstracts for corpus. "Never use real clinician questions with real patient context in development environments" is explicit.
- Sample output is explicitly labeled illustrative with an HTML comment, and the comment correctly warns that "all citations below are illustrative. Do not treat the specific papers, authors, journals, or findings as real."
- Corpus licensing is called out as a production-readiness concern with named risks (redistribution of UpToDate, Cochrane full text, specialty society content). License registry and quarterly audit are recommended.
- PHI de-identification in the question is flagged in "Why This Isn't Production-Ready."
- Retention posture (audit trail, feedback, trace archives) is called out implicitly via CloudTrail and the DynamoDB audit table design.

#### Finding S1: PHI Minimization in Prompts and in Comprehend Medical Calls

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 2 `expand_query_and_extract_entities` (~lines 420-430, the `text_for_entities = question + " " + serialize(patient_context)` pattern); Step 7 `generate_synthesis` (the generation prompt passes `patient_context` verbatim into the model)
- **Problem:** `patient_context` is a structured object that, based on the prose, may carry "age, conditions, medications," and, in the variations section, expands to "labs" and richer clinical state. Nothing in the pseudocode scopes what's sent to Comprehend Medical or to the generation model. A naive implementation using a serialized FHIR `Patient` resource (or a convenience JSON of the patient record) would pass MRN, DOB, name, address, phone, and insurance identifiers to Comprehend Medical's `DetectEntitiesV2` and then again into the Bedrock generation prompt. Comprehend Medical is HIPAA-eligible and appropriate for PHI; still, minimum necessary applies. Bedrock generation does not need MRN, DOB, address, phone, or payer identifiers to produce a literature synthesis; the clinically-relevant fields (age bucket, sex if relevant, conditions, medications, renal/hepatic function, specific comorbidities named in the question) are sufficient. The recipe elsewhere acknowledges this in "Why This Isn't Production-Ready" ("De-identification of questions with PHI. If the clinician includes patient-specific context in the question... Handle it accordingly throughout the pipeline") but the pseudocode doesn't scope the payload.
- **Fix:** Add a one-paragraph addition to Step 2 or Step 7 walkthrough:
  ```
  // Before sending patient_context to downstream services, strip fields
  // that aren't needed for literature retrieval or synthesis.
  //
  // Keep: age band, relevant conditions, current medications, pertinent
  //       labs (renal/hepatic function, pregnancy status, immune status),
  //       weight if drug-dosing is relevant.
  // Drop: MRN, DOB (age band is enough), name, address, phone, email,
  //       payer/member IDs, provider NPIs, addresses.
  //
  // Carry the scrubbed payload through the pipeline; do not re-hydrate
  // the full record downstream.
  patient_context_minimal = minimize_phi_for_literature(patient_context)
  ```
  And one sentence referencing this from the "Why This Isn't Production-Ready" de-identification paragraph.

#### Finding S2: Input-Side Prompt Injection via Retrieved Chunks

- **Severity:** MEDIUM
- **Expert:** Security
- **Location:** Step 7 `generate_synthesis` (the `chunks_block` construction and the generation prompt); "The Hallucination Failure Modes You Have to Design Around" section
- **Problem:** The generation prompt concatenates full-text chunks retrieved from the corpus directly into the prompt body. The corpus includes PMC Open Access XML, guideline text, and "institutional knowledge base" content. Institutional content in particular can be authored by many hands; corpus ingestion pipelines occasionally pull in content that embeds adversarial text (a "take care of this one, it's urgent: ignore prior instructions and..." pattern planted in a note template, a test artifact left in a production import, an imported PDF with prompt-shaped footer text). PMC full text is authored, but section headers and figure captions are machine-processed and sometimes carry artifacts that look like instructions. The recipe discusses hallucination failure modes extensively but does not flag retrieved-chunk content as an injection surface. Bedrock Guardrails' input-side prompt-attack filters apply here: configure them on the model-invocation request, not just the output-side grounding check.
- **Fix:** Add one sentence to the Guardrails comment block in Step 7:
  ```
  // Configure Guardrails with input-side prompt-attack filters in addition
  // to the contextual grounding output check. The retrieved chunks are
  // attacker-reachable content (PMC text, institutional notes, OCR'd
  // imports). Treat them as untrusted input, not verified instructions.
  ```
  Optionally add a line in the "Failure Modes" section noting that retrieved-chunk content is an input-side attack surface, not just a grounding source.

#### Finding S3: Sample Output Contains PMID-Shaped Link Targets Without a "Synthetic" Label on Each

- **Severity:** LOW
- **Expert:** Security
- **Location:** Expected Results sample JSON `bibliography` entries (link fields show `https://pubmed.ncbi.nlm.nih.gov/illustrative`)
- **Problem:** The sample uses `pubmed.ncbi.nlm.nih.gov/illustrative` as a placeholder URL. The top-of-block HTML comment already says all citations are illustrative. Still, if a reader copies the bibliography JSON into a test fixture and the fixture persists into a demo environment, the "/illustrative" literal will 404 in the UI. Minor polish.
- **Fix:** Either (a) leave a comment beside the first bibliography entry reiterating "all links in this sample are placeholders and resolve to 404 by design," or (b) swap to a clearly non-URL placeholder like `pmid:ILLUSTRATIVE-1` for each entry.

---

### Architecture Expert Review

#### What's Done Well

- The ten-stage pipeline (classify → expand → retrieve hybrid → rerank → tier → fetch context → generate → validate → render → log) is a correctly-factored clinical RAG architecture. Each stage is a single responsibility, the orchestration is appropriate for a Step Functions workflow, and the validation loop is explicit.
- The structured-extraction-first approach (`claims_json` emitted alongside the prose answer, one JSON claim per specific statement) is exactly right for auditable grounded generation. Each claim carries its citations, study population, and whether numerics are preserved. This is the architectural pattern that makes the validation step tractable.
- The model-tier split (Haiku for classification/expansion/rerank, Sonnet for generation) is sound and cost-aware.
- The retrieval architecture is mature. Dense-plus-sparse hybrid with reciprocal rank fusion. Query expansion before retrieval. Entity extraction via Comprehend Medical with RxNorm and ICD-10 mapping. Metadata filtering. Cross-encoder re-ranking. These are the right ingredients.
- The evidence-tier taxonomy is reasonable (simplified Level 1-5 hierarchy plus guidelines and narrative reviews). The recipe correctly notes that automated evidence grading is coarse and leaves fine-grained risk-of-bias assessment to the clinician. This is the right humility posture.
- The contextual grounding check section in Step 7 includes both the grounding-source tagging requirement and the `amazon-bedrock-guardrailAction` intervention field. This closes the gap that was flagged in Recipe 2.6's expert review.
- Post-generation validation is a first-class pipeline stage with three layered checks: citation existence, verbatim numerical preservation, and semantic-similarity threshold. The validator returns `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` on retry exhaustion, which is the correct terminal state.
- Cost estimate is defensible and detailed. Corpus ingestion as an amortized upfront cost, per-query variable cost broken out by stage, OpenSearch fixed cost called out separately, daily burn at 1,000 queries modeled.
- The "Honest Take" is the strongest in Chapter 2 so far. Five specific failure patterns, each named with a concrete fix. The demo-to-production gap, the corpus-quality blind spot, the validation shortcut, specialty-specific failure modes, and UX as product. Five equally specific recommendations follow. This is the section a VP of clinical informatics would read, highlight, and circulate.

#### Finding A1: Retrieval Source-Tier Filter Risks Hard-Excluding All Relevant Evidence

- **Severity:** HIGH
- **Expert:** Architecture / Clinical Accuracy
- **Location:** Step 3 `multi_source_retrieval`, `metadata_filters` dict (line ~485): `source_tier: preferred_tiers_for(question_category)`; passed to OpenSearch as hard filters
- **Problem:** `metadata_filters` are applied as filters on the OpenSearch query, which means any chunk whose `source_tier` is not in `preferred_tiers_for(question_category)` is excluded before similarity scoring. For question categories where the preferred tiers are "Level 1 Systematic Review" and "Level 2 RCT" (therapeutic questions are the obvious case), the filter drops all observational, case-control, case-series, and guideline content at the retrieval layer. For a therapeutic question about a newly-approved drug with no systematic review yet, or about an orphan indication where the entire evidence base is observational, this filter produces zero retrieved chunks, which the pipeline then tries to synthesize and correctly says "insufficient evidence." The problem is that there often is evidence; the filter just excluded it. The recipe's own Evidence Grading section teaches the right pattern: "tag each retrieved source with an evidence tier and should communicate that tier in the answer." Tag and weight, not filter and drop. The recipe elsewhere also correctly says "A well-designed medical RAG system often ranks sources by evidence tier during retrieval (...) and weights them accordingly in the generation prompt" which is a ranking boost, not a filter. The pseudocode implementation contradicts the recipe's own teaching.
- **Fix:** Change `source_tier` from a filter to a scoring boost in Step 3.
  ```
  // Metadata boosts instead of hard filters for source_tier. Use
  // OpenSearch function_score or a rescorer that multiplies the similarity
  // score by a tier-specific weight. Do NOT drop lower-tier content at
  // retrieval time; let re-ranking surface the best available evidence,
  // tier-weighted.
  tier_weights = weights_for(question_category)   // e.g., therapeutic:
                                                   //   SR/MA: 1.5, RCT: 1.3,
                                                   //   Cohort: 1.0, Case-control: 0.8,
                                                   //   Case series: 0.5, Guideline: 1.2
  // population_tags and publication_date can remain hard filters where
  // they're truly disqualifying (pediatric-only corpus for pediatric
  // questions, papers older than the useful window for the topic).
  metadata_filters = {
      publication_date: within_useful_window_for(question_category),
      population_tags:  entities.population  // hard filter OK; pediatric
                                              // studies are rarely valid for
                                              // adult questions
  }
  metadata_boosts = {
      source_tier: tier_weights
  }
  ```
  Update the Step 3 walkthrough to say: "Tier is a ranking boost, not a filter. For a question where only observational evidence exists, the pipeline should still surface the observational evidence and let the generation step's evidence-strength rating reflect the tier mix honestly."

#### Finding A2: Corpus-Ingestion Pipeline Has No Idempotency Pattern

- **Severity:** HIGH
- **Expert:** Architecture
- **Location:** Architecture Diagram, Ingestion subgraph (EventBridge Schedule → Step Functions Ingestion Workflow → Fetch New PubMed Records / Fetch Guideline Updates / Fetch Institutional Content); "Amazon EventBridge for corpus update triggers" paragraph in "Why These Services"
- **Problem:** The corpus-ingestion pipeline is triggered by EventBridge on a schedule plus event-driven updates ("New PubMed releases, new guideline publications, and new institutional content trigger corpus ingestion. EventBridge routes these events to the ingestion pipeline."). EventBridge is at-least-once. Duplicate causes are standard: scheduled-rule drift across time zones, overlapping rules in multi-region deployments, event-bus replays after a failover, manual re-runs during operator response to an earlier failure, NCBI E-utilities partial responses that get retried. Each duplicate triggers a fresh Step Functions execution that re-ingests the same PubMed record set, re-embeds chunks (the most expensive step at $200-$2,000 per full rebuild by the recipe's own estimate), and writes to OpenSearch. The worst case is not cost; it is an OpenSearch index with duplicate chunks for the same paper, which then show up as duplicate citations in answers. The recipe does not discuss idempotency for the ingestion pipeline. Same recurring Chapter 2 pattern as Recipes 2.4, 2.5, 2.6. This is the first time the pattern applies to a batch-ingestion workflow rather than a per-patient clinical trigger, but the same conditional-write discipline applies.
- **Fix:** Add a short subsection to "Why These Services" under EventBridge or add a new step in the ingestion workflow:
  ```
  // Idempotency at the ingestion pipeline:
  //   - Per-document: deterministic chunk_id from (paper_id, section,
  //     paragraph_index, chunk_hash). OpenSearch index operations use the
  //     chunk_id as the document ID, so duplicate ingests become upserts
  //     rather than duplicate chunks.
  //   - Per-run: before starting an ingestion Step Functions execution,
  //     attempt a conditional DynamoDB PutItem keyed on
  //     (source, window_start, window_end, run_token). If the item exists,
  //     the run is a duplicate and should no-op.
  //   - Embedding cost control: track embedded chunk_ids in a bitset or
  //     DynamoDB; re-embedding is only triggered by a chunk_hash change
  //     (the content changed), not by re-ingesting the same content.
  ```
  Call this out on the architecture diagram by tagging the EventBridge → Step Functions edge with "idempotency guard" or by adding a DynamoDB node the ingestion workflow consults before fan-out.

#### Finding A3: Validation Architecture Diagram Shows an Infinite Retry Loop

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Architecture Diagram, Query subgraph: `B11 --> B12{Validation Pass?} --> B12 -->|No| B10` back to generation; `B12 -->|Yes| B13[Render]`
- **Problem:** The pseudocode correctly routes to `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` after retries are exhausted. The Mermaid diagram does not. The diagram shows the validation-failed edge looping back to B10 (generation) unconditionally, with no node for retry exhaustion and no node for routing to clinical review. For a mixed-audience recipe where architects often read the diagram before reading the pseudocode, the diagram teaches the wrong picture (infinite retry loop, eventual stuck execution) and obscures the terminal state the pseudocode actually defines. This is the same class of finding flagged as A2 in the Recipe 2.6 review, though here the pseudocode is correct and only the diagram is incomplete.
- **Fix:** Update the diagram to add a retry counter and an exhaustion exit:
  ```
  B11 --> B12{Validation Pass?}
  B12 -->|Yes| B13[Render]
  B12 -->|No, retries < 3| B10
  B12 -->|No, retries exhausted| B19[Route to Clinician Review]
  B19 --> B14
  ```
  Or a simpler edit: label the `No` edge as "retries remaining" and add a separate labeled edge for "retries exhausted → review queue."

#### Finding A4: Sign/Direction Validation Not Implemented Despite Being Called Out as Catastrophic

- **Severity:** MEDIUM
- **Expert:** Architecture / Clinical Accuracy
- **Location:** "The Hallucination Failure Modes You Have to Design Around" → "Wrong direction" (~line 210): "The model reports a finding with the wrong sign. A paper found a 20% reduction in event rate; the model's summary says a 20% increase. This is a catastrophic error for clinical use."; Step 8 `validate_answer` (the verbatim-numeric and semantic-similarity checks)
- **Problem:** The recipe correctly identifies wrong-direction errors as "catastrophic for clinical use." The mitigation named in prose is "semantic validation has to catch sign flips, which is harder than it sounds; preserving exact numerical quantities from source text (verbatim, not paraphrased) helps." The pseudocode's validator does:
  - `extract_numbers(claim.text)` and `IF num not verbatim in supporting_text: unverified`
  - `semantic_similarity(claim.text, supporting_text) < 0.65: unverified`
  
  Neither catches a sign flip. "20% increase in mortality" and "20% reduction in mortality" both contain the literal token "20" and "20%." The verbatim-numeric check passes for both. Semantic similarity between the two sentences is likely well above 0.65 for most embedding models (they share all content tokens except "increase" vs "reduction"). The recipe names this as the hardest validation problem and then ships a validator that does not address it.
- **Fix:** Add a directional-alignment check to the validator:
  ```
  // For claims that reference direction-bearing outcomes (risk, reduction,
  // increase, improvement, decline, superiority, noninferiority), extract
  // the direction token alongside the numeric value and verify both are
  // present in supporting_text in the same sentence. If the direction
  // word in the claim does not match the supporting text's direction
  // word in the matching sentence, flag as "direction_mismatch."
  //
  // Implementation options in increasing sophistication:
  //   a) token co-occurrence check scoped to a sentence window
  //   b) NLI classifier (entailment/contradiction) between claim and
  //      cited sentence
  //   c) domain-specific relation extractor for (intervention, outcome,
  //      direction, magnitude) tuples with exact-match verification
  ```
  Acknowledge in the walkthrough text that direction validation is the hardest of the three checks and that option (c) is the right production target even if the pseudocode shows option (a).

#### Finding A5: Model IDs in Pseudocode Are Not Valid Bedrock Identifiers

- **Severity:** MEDIUM
- **Expert:** Architecture
- **Location:** Step 1 `receive_question` (line 378): `model_id = "anthropic.claude-haiku-4"`; Step 2 `expand_query_and_extract_entities` (line 419): `model_id = "anthropic.claude-haiku-4"`; Step 3 `multi_source_retrieval` (lines 465, 471): `model_id = "amazon.titan-embed-text-v2"`; Step 7 `generate_synthesis` (line 671): `model_id = "anthropic.claude-sonnet-4"`
- **Problem:** These are not real Bedrock model IDs. Bedrock model IDs include version segments: `anthropic.claude-3-5-haiku-20241022-v1:0`, `anthropic.claude-3-5-sonnet-20241022-v2:0`, `amazon.titan-embed-text-v2:0`, or the cross-region inference-profile IDs with `us.` / `eu.` prefixes. A reader copying the IDs as-written will get `ValidationException: The provided model identifier is invalid` on the first Bedrock call. Worse, the Python companion file (`chapter02.07-python-example.md`) uses correct IDs (`anthropic.claude-3-5-haiku-20241022-v1:0`, `anthropic.claude-3-5-sonnet-20241022-v2:0`, `amazon.titan-embed-text-v2:0`), so the main recipe and its companion disagree. The inconsistency between the two files teaches the wrong thing. Either the pseudocode should use generic placeholders (`CLAUDE_HAIKU_MODEL_ID`, `TITAN_EMBEDDING_MODEL_ID`) with a comment pointing to the Python companion for current IDs, or it should use the same versioned IDs the Python companion uses.
- **Fix:** Replace the four pseudocode IDs with either:
  - **Placeholder style** (preferred for pseudocode):
    ```
    model_id = SMALL_MODEL_ID        // Claude Haiku or Nova Lite; see companion for current ID
    model_id = GENERATION_MODEL_ID   // Claude Sonnet or equivalent; see companion for current ID
    model_id = EMBEDDING_MODEL_ID    // Titan v2 or Cohere Embed; see companion for current ID
    ```
  - **Versioned-ID style** (matches Python companion):
    ```
    model_id = "anthropic.claude-3-5-haiku-20241022-v1:0"
    model_id = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    model_id = "amazon.titan-embed-text-v2:0"
    ```
  Add a sentence near the first occurrence reminding readers that Bedrock model IDs change periodically and that cross-region inference profiles (`us.`/`eu.`) are now the recommended path in many regions.

#### Finding A6: Re-Ranker `endpoint_name = "medical-reranker-v1"` Is Presented Without Context

- **Severity:** LOW
- **Expert:** Architecture
- **Location:** Step 4 `rerank_candidates`, `endpoint_name = "medical-reranker-v1"`
- **Problem:** The pseudocode invokes a SageMaker endpoint named `medical-reranker-v1` as if the reader has one. The recipe's prose offers three options (managed re-ranker in OpenSearch/Bedrock, SageMaker-hosted cross-encoder, small-LLM re-ranker), but the pseudocode commits to the SageMaker path without noting that the endpoint has to be built and deployed separately (which is a substantial project: pick a base model like a MS MARCO cross-encoder or a biomedical cross-encoder, fine-tune or not, package, deploy to an endpoint, manage inference scaling). A reader looking at Step 4 alone might think the endpoint is a managed AWS service. "Why This Isn't Production-Ready" mentions fine-tuning a medical re-ranker as a separate effort, which is correct but buried.
- **Fix:** Add a one-line note at the top of Step 4's pseudocode: "`medical-reranker-v1` is a SageMaker endpoint the team deploys separately. See the 're-ranker quality' concern in 'Why This Isn't Production-Ready' for the model-selection and fine-tuning lifecycle." Or switch the pseudocode default to the small-LLM re-ranker option (which is what the Python companion uses) and mention the SageMaker cross-encoder as the preferred production upgrade.

---

### Networking Expert Review

#### What's Done Well

- The VPC row is the most complete in Chapter 2 so far: interface endpoints listed for `bedrock`, `bedrock-runtime`, `bedrock-agent-runtime` (conditional on Knowledge Bases), `comprehendmedical`, `kms`, `secretsmanager`, `states`, `logs`, `monitoring`, `events`; gateway endpoints for `s3` and `dynamodb`. The per-AZ-per-endpoint cost ($7-10/month) is called out explicitly and folded into the cost estimate.
- OpenSearch domain is specified as VPC-only mode with security-group rules for Lambda access, fine-grained access control, encryption at rest and in transit with a CMK, no public endpoint. This is the first Chapter 2 recipe to use OpenSearch as a primary store and the posture is correct.
- TLS in transit is explicitly called out.
- CloudTrail data-events requirement is specific to Bedrock invocations, S3 object access, DynamoDB access, and Secrets Manager retrievals.

#### Finding N1: `execute-api` and `aoss` Endpoints Not Conditionally Called Out

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites "VPC" row
- **Problem:** Two conditional endpoints are worth mentioning:
  - `com.amazonaws.{region}.execute-api` if the clinician-facing API is a private API Gateway (EHR callers inside the same VPC over PrivateLink). The recipe mentions "API Gateway + Cognito" for the clinician interface without specifying public vs private.
  - `com.amazonaws.{region}.aoss` if the reader chooses OpenSearch Serverless rather than the provisioned OpenSearch Service domain. The recipe offers OpenSearch Serverless as an option in "Why These Services" and in the Prerequisites, but the VPC row only covers the provisioned-domain case.
- **Fix:** Add one sentence: "If the clinician-facing API is a private API (EHR callers inside the same VPC), add `execute-api`. If OpenSearch Serverless is used instead of the provisioned domain, substitute `aoss` for the OpenSearch VPC posture."

#### Finding N2: NCBI / External-API Egress Path Not Discussed

- **Severity:** LOW
- **Expert:** Networking
- **Location:** Prerequisites "VPC" row; "AWS Secrets Manager for third-party API keys" paragraph
- **Problem:** The corpus-ingestion pipeline pulls from NCBI E-utilities, ClinicalTrials.gov API, and potentially licensed content providers. These are external egress flows from Lambda (or AWS Batch / SageMaker Processing for full rebuilds). The recipe does not specify how egress is handled: NAT Gateway (expensive for bulk-ingestion traffic), Internet Gateway from a public subnet (not an option if workloads must stay private), or a forward proxy with allow-listing. For a health system where the security team requires egress logging and destination controls, this is a real design question. The "Why This Isn't Production-Ready" section doesn't mention it either.
- **Fix:** Add a sentence to either the VPC row or a new "Egress for external literature APIs" paragraph: "Ingestion workloads egress to NCBI E-utilities, ClinicalTrials.gov, and licensed-content endpoints. For private-subnet deployments, route egress through a NAT Gateway (higher cost at full-rebuild volumes) or through a forward proxy in a DMZ subnet with destination allow-listing. Log egress in VPC Flow Logs; publish destination allow-lists as code."

---

### Voice Reviewer

#### What's Done Well

- Opening vignette (Wednesday afternoon, internist with eight minutes, methotrexate plus anastrozole patient) is concrete, clinically specific, and voice-authentic. The follow-through (the internist abandons the search, gives a gestalt answer, 412 irrelevant results) lands the pain.
- The five scenarios (clinic internist, primary-care physician, pulmonary fellow, payer medical director, research coordinator) are distinct enough to widen the problem frame without diluting it. The framing across all five lands the same underlying point: the gap between clinician and literature is a workflow problem, not an evidence problem.
- "RAG Done for Grown-Ups" is exactly the tone CC would use. Acknowledges the diluted industry term, teaches the pattern, teaches the limitations, earns attention.
- "The Corpus Problem: What You're Indexing Matters More Than How" is substantive. The PMC / PubMed / guidelines / UpToDate / Cochrane / ClinicalTrials.gov / specialty society / institutional-content list is the right taxonomy, with honest license callouts.
- "Chunking Medical Literature Is Not Chunking News Articles" is concrete. Title-Abstract-Intro-Methods-Results-Discussion-Conclusion structure, why a sentence from Results is different from a sentence from Discussion, why a chunk needs the paper title and section header in metadata. Teaches the principle.
- "Evidence Grading Is What Makes It a Clinical Tool" correctly frames why this is the differentiating feature and is honest about the limits of automated grading.
- "The Citation Discipline" names the right discipline and names the right validation target.
- "The Hallucination Failure Modes You Have to Design Around" is the best failure-mode enumeration in Chapter 2 so far. Nine specific failure modes, each with a specific mitigation. "Equipoise collapsed" and "Recommendation when asked to inform" are particularly well-named.
- 70/30 vendor balance is clean. The entire conceptual portion (Problem, Technology, General Architecture Pattern) is vendor-neutral; AWS services enter cleanly in the Implementation section and do not leak back into the conceptual sections.
- "The Honest Take" is unusually strong. The five failure patterns (demo-to-production gap, corpus-quality blind spot, underestimating validation, specialty-specific failure modes, UX) are each specific and each matched to a specific "what has worked" recommendation. The "medical librarians are still better at complex searches than any RAG system" framing is honest and correct.
- No em dashes in the file (direct character check: zero matches for U+2014 and U+2013).
- No marketing language. No "leverage," "seamless," "unlock," "transform," "empower," "revolutionize."
- Variations section is substantive and substantially different from each other (patient-specific Q&A, systematic-review drafting, prior-auth evidence generation, guideline-change monitoring, journal club support, multi-agent decomposition, audio delivery, order-entry integration). Each has enough detail to act on.
- Related Recipes section correctly notes that 2.7 sits on a continuum with 2.9 (decision support) and that the regulatory posture differs as you move toward prescriptive output.

#### Finding V1: Two Unresolved TODO Markers in Published Prose

- **Severity:** LOW
- **Expert:** Voice
- **Location:** "Related Recipes" section: `<!-- TODO (TechWriter): update to specific recipe number once Chapter 13 is drafted (candidate: clinical ontology / disease-drug graph recipe). -->` and `<!-- TODO (TechWriter): update to specific recipe number once Chapter 8 is drafted. -->`
- **Problem:** Two HTML-comment TODOs remain. These are lower-stakes than the TODOs flagged in earlier Chapter 2 reviews (they are placeholders for future recipe numbers rather than unresolved factual claims), but HTML comments survive most Markdown-to-HTML rendering paths and leak to view-source. Same hygiene point as Recipe 2.5 (V1) and Recipe 2.6 (V1).
- **Fix:** Either (a) drop the `Recipe 13.x` and `Recipe 8.x` bullets entirely, with a note to add them back when Chapters 8 and 13 are drafted, or (b) keep the bullets but use placeholder text that reads cleanly if the TODO is never resolved: "**Recipe 13 (Knowledge Graphs):** Knowledge-graph representations of medical entities can augment RAG retrieval. When Chapter 13 is drafted, the specific ontology-and-drug-graph recipe there pairs with this one."

#### Finding V2: "Level 4: Pharmacovigilance" Appears in Sample Output but Not in Evidence-Tier Pseudocode

- **Severity:** LOW
- **Expert:** Voice / Clinical Accuracy
- **Location:** Expected Results sample JSON `bibliography`, entry 4: `"evidence_tier": "Level 4: Pharmacovigilance"`; Step 5 `tag_evidence_tiers` pseudocode (the IF/ELSE ladder has no "Pharmacovigilance" branch)
- **Problem:** The sample output shows one bibliography entry tagged `Level 4: Pharmacovigilance` (a FAERS disproportionality analysis). The Step 5 pseudocode's tier ladder has "Meta-Analysis / Systematic Review," "RCT," "Clinical Trial (non-randomized)," "Cohort / Observational," "Case-Control," "Case Series / Case Reports," "Guideline," "Narrative Review," and "Unclassified." No "Pharmacovigilance" branch. A reader who cross-checks the pseudocode against the sample output will notice the mismatch. Additionally, "Pharmacovigilance" isn't a standard Oxford CEBM level; it usually falls under post-marketing surveillance in separate grading frameworks (the FDA adverse-event reporting methodology). Minor polish issue, but the recipe teaches evidence grading explicitly and should model precise grading in its own sample.
- **Fix:** Either (a) add a pharmacovigilance branch to Step 5 pseudocode (`ELSE IF source_paper.publication_types includes "Adverse Event Report" OR source_paper.source_type == "pharmacovigilance": chunk.evidence_tier = "Post-Marketing Surveillance"`), or (b) change the sample output's entry 4 to a more conventional tier (Level 4 Case-Control or Level 3 Pharmacoepidemiology Cohort).

#### Finding V3: Sample Output's `evidence_strength_justification` References Five Citations but Claims "No Randomized Trials"

- **Severity:** LOW
- **Expert:** Voice / Clinical Accuracy
- **Location:** Expected Results sample JSON: `"evidence_strength_justification": "Based on one systematic review [1], three retrospective cohort studies [2][3][4], and one society consensus statement [5]. No randomized trials directly address this question."`
- **Problem:** The justification says "three retrospective cohort studies [2][3][4]" but [4] is labeled in the bibliography as "FAERS disproportionality analysis... Pharmacoepidemiol Drug Saf" with `evidence_tier: "Level 4: Pharmacovigilance"`. A FAERS disproportionality analysis is a pharmacovigilance signal-detection study, not a retrospective cohort study. A careful clinical reader will notice that the count of studies by type doesn't match the bibliography entries. Minor but the recipe's central teaching is "describe the evidence accurately"; the sample should model that.
- **Fix:** Change the justification to "two retrospective cohort studies [2][3], one FDA FAERS pharmacovigilance analysis [4], and one society consensus statement [5]." Match the labels in the bibliography entries.

#### Finding V4: Opening Vignette Uses "143 results" and "412 results" Specifically but the Rest of the Recipe Doesn't Close the Loop

- **Severity:** LOW
- **Expert:** Voice
- **Location:** Problem section (~line 9): "she types 'methotrexate anastrozole interaction.' She gets 143 results... now she's got 412 results"; Expected Results sample output
- **Problem:** The opening scene is specific and concrete ("143 results," "412 results," "the patient is sitting in front of her"). The Expected Results sample is the resolution of that scene: the literature-RAG system answers the same question with a 5-citation synthesis. The voice-craft question: does the sample output close the loop with the opening? The answer is mostly yes (the question format matches, the answer addresses the same clinical question, the citations are tier-labeled). The small miss is that the opening specifically names "three 2022 observational studies and one 2024 systematic review directly addressing methotrexate continuation during aromatase inhibitor therapy" as what a thorough clinician would have found, and the sample output shows one systematic review (2024), two retrospective cohorts (2022 and 2023), one pharmacovigilance analysis (2022), and one consensus statement (2023). Close but not exactly the same. The asymmetry is minor, and the note at the top of the sample ("all citations below are illustrative") preempts the strict-reading concern.
- **Fix:** Either (a) accept the asymmetry as intentional, since the sample is labeled illustrative and the opening is teaching the shape of the gap rather than setting up a specific output, or (b) bring the opening paragraph into line with the sample: "three retrospective cohort studies and one 2024 systematic review directly addressing..." The LOW severity reflects that this is polish, not a correctness issue.

---

## Stage 2: Expert Discussion

**Overlap: Architecture (source-tier filter) and Clinical Accuracy.**
Finding A1 (source-tier hard filter excluding all evidence) is an architecture concern that expresses itself as a clinical-accuracy risk. The recipe teaches evidence grading as "tag and weight," and then the pseudocode implements "filter and drop." Fixing the pseudocode to use tier as a boost rather than a filter aligns the architecture with the recipe's own teaching. No conflict with other experts; security is silent, networking is silent, voice is neutral.

**Overlap: Architecture (validation diagram) and Voice (sample output consistency).**
Finding A3 (diagram shows infinite loop, pseudocode routes correctly) and the polish findings V2/V3 (sample output tier labels vs bibliography) both trace to the same pattern: different parts of the recipe telling slightly different stories about the same thing. Fixing the diagram makes the architecture consistent with the pseudocode. Fixing the justification makes the sample consistent with the bibliography. Neither fix interacts with the other, and both are small.

**Overlap: Security (PHI minimization) and Architecture (patient_context lifecycle).**
Finding S1 is a security finding about what data leaves the boundary of the pipeline for downstream inference. The right fix is a scrubbing step in Step 2 that produces a `patient_context_minimal` and carries it through the rest of the pipeline. This is a small, localized change with no architectural rework and no ripple through the rest of the pseudocode. Architecture agrees with security on the scope and the shape of the fix.

**Non-conflict: model-ID correctness, re-ranker endpoint clarity, and re-ranker model path are independent.**
Findings A5 (model IDs), A6 (re-ranker endpoint framing) are independent fixes. Each touches its own step. No resource contention.

**Non-conflict: idempotency is a cross-cutting discipline.**
Finding A2 (corpus-ingestion idempotency) is the same recurring pattern flagged in Recipes 2.4, 2.5, 2.6. At this point the editorial recommendation is a Chapter 2 appendix on trigger idempotency that individual recipes can reference. Not a reviewer's decision, but worth flagging to the editor.

**Pattern observation: this recipe's gaps are specification-level rather than architecture-level.**
Unlike Recipe 2.5 (CRITICAL clinical inconsistency) and Recipe 2.6 (four HIGH pipeline gaps), the issues here are mostly "the pseudocode under-specifies something the prose names correctly" (direction validation in A4) or "the pseudocode implements something that contradicts the prose's teaching" (source-tier filter in A1) or "cosmetic mismatches between sections" (V2, V3). The architecture itself is sound and the teaching is strong. The fixes are well-scoped edits rather than design rework.

---

## Stage 3: Synthesized Feedback

## Verdict: PASS

Two HIGH findings, under the "more than 3 HIGH = FAIL" threshold. No CRITICAL findings. The architecture is sound, the teaching is the strongest in Chapter 2 so far, the recurring Chapter 2 patterns (IAM scoping, VPC endpoints, model-invocation-logging PHI, Guardrails contextual-grounding tagging, Guardrails intervention detection) are addressed, and the no-em-dashes rule is satisfied.

The two HIGH findings are both fixable with localized edits. A1 (source-tier hard filter) is a one-block pseudocode change that aligns the retrieval implementation with the recipe's own evidence-grading teaching. A2 (ingestion idempotency) is a new paragraph in "Why These Services" plus a diagram annotation, following the pattern recommended in Recipes 2.4, 2.5, and 2.6 reviews. Neither requires architectural rework.

The five MEDIUM findings cluster around under-specified validation (A4 direction check, A3 diagram exit), under-specified data handling (S1 PHI minimization, S2 input-side injection), and an inconsistency between the pseudocode and the Python companion (A5 model IDs). All are well-scoped fixes; an editorial pass through Step 2, Step 3, Step 7, Step 8, and the architecture diagram addresses them.

The LOW findings are polish: TODOs in published prose, sample-output tier-label consistency, vignette-to-sample loop closure, conditional VPC endpoints, external-API egress path, re-ranker endpoint context.

This recipe is genuinely close to ship-ready. With the two HIGH fixes and a cleanup pass on the MEDIUM findings, it would set the quality bar for Chapter 2.

---

## Prioritized Findings

| # | Severity | Expert | Location | Summary |
|---|----------|--------|----------|---------|
| A1 | HIGH | Architecture / Clinical Accuracy | Step 3 `multi_source_retrieval`, `metadata_filters.source_tier` | Source tier applied as a hard filter; for questions where only observational evidence exists, pipeline excludes it entirely and produces "insufficient evidence" where evidence is available. Recipe's own teaching says "tag and weight," not "filter and drop" |
| A2 | HIGH | Architecture | Architecture Diagram Ingestion subgraph; "EventBridge for corpus update triggers" paragraph | Corpus-ingestion pipeline has no idempotency guard; duplicate EventBridge deliveries drive duplicate Step Functions runs, duplicate embedding cost ($200-$2,000 per rebuild), and duplicate OpenSearch chunks |
| S1 | MEDIUM | Security | Step 2 `text_for_entities`; Step 7 generation prompt | `patient_context` passed to Comprehend Medical and to Bedrock generation without minimum-necessary scoping; MRN, DOB, address, payer IDs not needed for literature synthesis |
| S2 | MEDIUM | Security | Step 7 `generate_synthesis` chunks_block construction | Retrieved chunks are an input-side prompt-injection surface; Guardrails input-side prompt-attack filters not discussed alongside the output-side grounding check |
| A3 | MEDIUM | Architecture | Architecture Diagram validation-loop edges | Diagram shows infinite retry loop; pseudocode correctly routes to `VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW` but diagram lacks the exit node |
| A4 | MEDIUM | Architecture / Clinical Accuracy | "Failure Modes" → "Wrong direction"; Step 8 `validate_answer` | Sign/direction validation identified as "catastrophic" in prose but not implemented; verbatim-numeric check passes for "20% increase" vs "20% reduction"; semantic-similarity at 0.65 likely also passes |
| A5 | MEDIUM | Architecture | Steps 1, 2, 3, 7 `model_id` values | Fake Bedrock model IDs (`anthropic.claude-haiku-4`, `anthropic.claude-sonnet-4`, `amazon.titan-embed-text-v2`); copy-paste fails Bedrock validation; Python companion uses correct versioned IDs so the two files disagree |
| A6 | LOW | Architecture | Step 4 `rerank_candidates` SageMaker endpoint reference | `medical-reranker-v1` endpoint is presented without noting it's a separate deployment project |
| N1 | LOW | Networking | Prerequisites VPC row | `execute-api` and `aoss` not called out as conditional endpoints |
| N2 | LOW | Networking | Prerequisites VPC row; Secrets Manager paragraph | External-API egress path (NCBI, ClinicalTrials.gov, licensed providers) not discussed |
| V1 | LOW | Voice | Related Recipes section | Two HTML-comment TODO markers for Chapter 8 and Chapter 13 cross-references |
| V2 | LOW | Voice / Clinical Accuracy | Sample output bibliography [4]; Step 5 tier pseudocode | `Level 4: Pharmacovigilance` tag in sample but not in Step 5 ladder |
| V3 | LOW | Voice / Clinical Accuracy | Sample output `evidence_strength_justification` | Count of "three retrospective cohort studies" doesn't match bibliography (two cohorts plus one pharmacovigilance) |
| V4 | LOW | Voice | Problem section vs Expected Results | Opening names "three 2022 observational studies and one 2024 systematic review"; sample output has slightly different composition |

---

## Recommended Actions (Priority Order)

1. **Change source-tier from filter to boost** (Finding A1). Rewrite the Step 3 `metadata_filters` dict to separate hard filters (date, population) from ranking boosts (source_tier). Add a sentence to the Step 3 walkthrough: "Tier is a ranking boost, not a filter. For a question where only observational evidence exists, the pipeline should still surface it and let the generation step's evidence-strength rating reflect the tier mix honestly." This is the single highest-leverage fix; it aligns the retrieval implementation with the recipe's evidence-grading teaching.

2. **Add corpus-ingestion idempotency** (Finding A2). Deterministic `chunk_id` for content-addressed upserts in OpenSearch; conditional DynamoDB write on ingestion-run key; chunk-hash-based re-embedding gate. Annotate the architecture diagram. Consider proposing a Chapter 2 trigger-idempotency appendix so the pattern stops recurring in individual reviews.

3. **Add PHI minimization for patient context** (Finding S1). Introduce `patient_context_minimal` in Step 2 and use it for all downstream inference calls. Scope fields to age band, conditions, medications, relevant labs; drop MRN, DOB, name, address, phone, payer/NPI identifiers.

4. **Add input-side prompt-injection guardrails** (Finding S2). One sentence in the Step 7 Guardrails block noting that retrieved chunks are an input-side attack surface and that Guardrails' prompt-attack filters apply to the input, not just the output grounding check.

5. **Fix the validation-loop architecture diagram** (Finding A3). Add a retry-counter branch and an exit edge to a "Route to Clinician Review" node that terminates in the archive step. Match the pseudocode's behavior.

6. **Specify direction/sign validation** (Finding A4). Add a direction-alignment check to the validator, even if it's a token co-occurrence placeholder; acknowledge in the walkthrough that direction validation is the hardest of the three checks and name NLI or relation-extraction as the production target.

7. **Fix fake Bedrock model IDs** (Finding A5). Use either placeholder constants (`SMALL_MODEL_ID`, `GENERATION_MODEL_ID`, `EMBEDDING_MODEL_ID`) pointing at the Python companion, or versioned IDs that match the companion (`anthropic.claude-3-5-haiku-20241022-v1:0`, etc.). Add a sentence near the first occurrence about cross-region inference profiles and periodic ID changes.

8. **Close the smaller polish items** (A6, N1, N2, V1, V2, V3, V4). Step 4 re-ranker endpoint framing, conditional VPC endpoints (`execute-api`, `aoss`), external-API egress path, two TODO markers in Related Recipes, sample-output tier label consistency (Pharmacovigilance), `evidence_strength_justification` count alignment, and opening-vignette-to-sample-output loop closure.

---

## Notes for Editor

- The recurring Chapter 2 hygiene issues (IAM scoping, VPC endpoints, model-invocation-logging PHI, Guardrails grounding-source tagging, Guardrails intervention-detection field) are all addressed in this recipe. This recipe should be the template for future Chapter 2 recipes rather than a one-off fix.
- The `source_tier` filter-vs-boost issue (A1) is a subtle correctness problem: the retrieval returns zero results silently, the generation says "insufficient evidence" honestly, and the clinician concludes (incorrectly) that the literature has nothing to say. A careful evaluation set would catch this; a casual demo would not. Worth flagging to the evaluation program as a specific test case.
- The fake model ID issue (A5) is the kind of error that appears nowhere in the prose (which is careful and accurate) but lives in the pseudocode because pseudocode often gets less review scrutiny than prose. The disagreement between the main recipe and the Python companion is the smoking gun. A simple editorial pass that greps the pseudocode for string literals that look like model IDs and cross-checks them against the companion catches this class of issue.
- The "catastrophic wrong direction" failure mode (A4) is a reviewer's favorite finding because the prose is beautifully correct and the pseudocode quietly sidesteps the hardest part. Fixing it properly is non-trivial (NLI classifier, relation extractor, or a domain-specific direction-preserving validator). The recipe should either implement a placeholder that acknowledges the gap, or be explicit that the validator as-shown does not catch direction flips and that the production path is a separate model.
- The Problem section and the "Why General-Purpose LLMs Are the Wrong Tool for This Job" section deserve to be quoted in the book's marketing copy. They are the clearest articulation of why clinical RAG is hard and why naive LLM deployments in medicine fail. The Honest Take is the strongest in Chapter 2 so far.
- No em dashes found (direct check: zero matches for U+2014 and U+2013). Voice reviewer confirms the file passes the prose rules.
- The references list is clean: Bedrock docs, Knowledge Bases, Guardrails, contextual grounding check page, Titan embeddings, OpenSearch k-NN and hybrid search, Comprehend Medical (including the RxNorm and ICD-10 ontology-linking pages specifically), Step Functions parallel/map, HIPAA eligibility, NCBI E-utilities, PMC Open Access, ClinicalTrials.gov API, Cochrane, USPSTF, CDC MMWR, GRADE Working Group, Oxford CEBM, MedQA / PubMedQA / BioASQ benchmark links, FDA CDS guidance. All real and correctly cited.
- The Variations and Extensions section is substantive. "Prior authorization evidence generation" is particularly clever because it connects back to Recipe 2.4 and shows how the same retrieval-and-synthesis architecture serves both the requester-side and the payer-side of prior auth. Worth flagging as a potential standalone recipe for Chapter 2 or a cross-chapter reference.
- The corresponding code review has not been filed yet at time of this expert review. If the Python companion uses `anthropic.claude-3-5-haiku-20241022-v1:0` and `anthropic.claude-3-5-sonnet-20241022-v2:0` and `amazon.titan-embed-text-v2:0`, the main-recipe pseudocode fix for A5 should match those IDs so the two files stay consistent.
