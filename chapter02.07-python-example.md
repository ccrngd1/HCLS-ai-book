# Recipe 2.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.7. It shows one way you could translate those literature-search-and-evidence-synthesis concepts into working Python using Amazon Bedrock, Amazon OpenSearch Service, Amazon Comprehend Medical, S3, and DynamoDB. It is not production-ready. There is no corpus ingestion pipeline (that's a significant project on its own), no SMART-on-FHIR or EHR integration, no Step Functions orchestration, no clinician-facing UI, no cross-encoder re-ranker (we use a small-LLM re-ranker stand-in, which is cheaper but less accurate), and no fine-grained evidence-grading beyond publication-type tiers. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire up to a health system on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the ten pseudocode steps from the main recipe: receive and classify the question, expand the query and extract entities, multi-source retrieval with hybrid search, re-rank candidates, tag evidence tiers, fetch full-text context, grounded generation with citation discipline, validate citations and claims, render with bibliography, archive for audit. Unverifiable claims trigger regeneration up to a cap, then escalate for clinician review.

---

## Setup

You'll need the AWS SDK for Python and a few utility libraries:

```bash
pip install boto3 opensearch-py requests-aws4auth
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for classification, expansion, generation, and embeddings)
- `bedrock:ApplyGuardrail` (if you configure a Bedrock Guardrail with contextual grounding, which you should for clinician-facing synthesis)
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` (for query-time entity extraction and ontology mapping)
- `es:ESHttpPost`, `es:ESHttpGet` (for OpenSearch hybrid retrieval; `aoss:*` equivalents if using OpenSearch Serverless)
- `s3:GetObject`, `s3:PutObject` (for answer archive and retrieval traces)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem` (for query state and provenance)
- `states:StartExecution` (if you wire this into Step Functions, which you should for anything real)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (for CloudWatch Logs)

You also need model access enabled in the Bedrock console. This pipeline uses three model roles: a smaller, cheaper model for classification, expansion, and re-ranking; an embedding model for query-side vectorization; and a stronger model for the final synthesis where citation discipline, evidence framing, and preserved uncertainty all matter. Scope `bedrock:InvokeModel` to specific model ARNs in production, not a wildcard. The tutorial-level permissions below are fine for learning and will fail any serious IAM review.

A few things worth knowing upfront:

- **Bedrock model IDs change over time** and the set available in your region depends on your account's model access. Cross-region inference profiles are now the recommended path in many regions (IDs prefixed with `us.` or `eu.`). The IDs in this example are reasonable defaults at the time of writing; verify in the Bedrock console and adjust for your region before running.
- **The OpenSearch index used here is assumed to already exist** and to contain your chunked, embedded medical corpus. Building that corpus is a project in its own right (parsing PMC XML, chunking by section, embedding millions of chunks, loading into OpenSearch with the right field mappings). This example focuses on the query-time pipeline, which is what the recipe teaches.
- **Comprehend Medical's per-call limit for `DetectEntitiesV2` is enforced in bytes**, not characters. Clinician questions are usually short enough to not matter, but the helper below encodes to utf-8 and slices by byte length just in case, since getting this wrong produces confusing 400 errors on some inputs.
- **All literature citations, papers, authors, and findings in the example output are synthetic.** Do not treat any specific paper, DOI, PMID, or numerical finding in this file as real. A production system grounds every claim in actual retrieved chunks from a real corpus.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, retrieval sizing, validation thresholds, evidence-tier mappings, and resource names are the knobs you'll change most often between environments.

```python
import json
import logging
import re
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal
from collections import defaultdict

import boto3
from botocore.config import Config
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights for query-friendly analysis. The clinician's question may
# contain PHI via patient context (age, conditions, meds), so never log the
# question text or the generated answer body in regular logs. The audit trail
# for questions and answers lives in S3 with access-controlled retrieval.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling. Literature-search load is
# naturally bursty (clinic sessions, morning rounds). Adaptive mode uses
# exponential backoff with jitter so retry storms don't pile on during peaks.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Three roles. Classification and expansion are cheap per-question tasks where
# a smaller model earns its keep. Embeddings have to match whatever embedder
# indexed the corpus (critical: do NOT mix embedders between indexing and
# query time). Generation is where citation discipline, evidence framing,
# and preserved uncertainty all matter, so use a capable model.
#
# If your region requires cross-region inference, use the inference profile ID:
#   e.g., "us.anthropic.claude-3-5-haiku-20241022-v1:0"
# TODO: verify the exact model IDs available in your region and account.
SMALL_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Optional Bedrock Guardrail for the generation step. Configure one in the
# Bedrock console with the contextual grounding check enabled; for clinician-
# facing literature synthesis, the grounding check is the feature that matters
# most. Set a high threshold (0.85+) to reject responses that drift from the
# retrieved chunks. Leaving these None means no guardrail is applied. Don't
# ship without this in production.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version

# --- OpenSearch Configuration ---
# The corpus index is assumed to exist with these fields:
#   chunk_id (keyword)              - unique per chunk
#   paper_id (keyword)              - parent paper
#   paper_title (text)              - for citation rendering
#   authors (keyword)               - author list
#   journal_or_body (keyword)       - publication venue or issuing body
#   publication_year (integer)      - for date filters
#   publication_types (keyword[])   - PubMed publication type tags
#   source_type (keyword)           - pmc_open_access | pubmed_abstract | guideline | ...
#   section (keyword)               - Abstract | Introduction | Methods | Results | ...
#   chunk_text (text)               - for BM25 and display
#   embedding (knn_vector, 1024)    - Titan v2 is 1024 dimensions
#   population_tags (keyword[])     - adult | pediatric | pregnancy | geriatric | ...
#   doi_or_pmid (keyword)           - link target
OPENSEARCH_ENDPOINT = "your-opensearch-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_INDEX = "medical-corpus"
OPENSEARCH_REGION = "us-east-1"

# --- Storage Configuration ---
# One bucket for answer archives and retrieval traces. In production these
# are typically separate prefixes with different lifecycle policies:
# traces purged at 90 days, final answers retained for the audit window your
# compliance team requires.
ANSWERS_BUCKET = "your-literature-rag-answers-bucket"

# DynamoDB tables. In production, use separate tables for query state and
# feedback, with GSIs for access patterns (by user, by specialty, by status).
LITERATURE_QUERIES_TABLE = "literature-queries"  # Partition key: query_id

# --- Pipeline Tuning ---
# Initial retrieval size per query variant. Broader initial retrieval gives
# the re-ranker more to work with; too broad and re-ranking gets expensive.
INITIAL_RETRIEVAL_SIZE = 50

# After merging across query variants, trim to this many candidates before
# re-ranking. 100 is a reasonable balance for a small-LLM re-ranker.
RERANK_CANDIDATE_LIMIT = 100

# Chunks kept after re-ranking, fed into generation.
TOP_K_FOR_GENERATION = 15

# Minimum semantic-overlap threshold for validating claims that aren't
# exact numeric matches. The validator falls back to substring and token
# overlap; production systems should add embedding-based similarity.
MIN_CLAIM_OVERLAP = 0.55

# Max attempts at the generation + validation loop. If we can't produce a
# validated answer after this many tries, escalate for clinician review
# rather than loop forever.
MAX_GENERATION_ATTEMPTS = 3

# Comprehend Medical's DetectEntitiesV2 has a per-call limit enforced in
# bytes (~20,000 for synchronous calls). Clinical questions are usually
# much shorter than this, but encode defensively.
COMPREHEND_MEDICAL_MAX_BYTES = 19500

# --- Evidence Tier Mapping ---
# Maps PubMed publication types to simplified evidence tiers. Real systems
# use more granular schemes (GRADE, Oxford CEBM, USPSTF); this is a starter
# that the generation prompt and UI can render cleanly.
EVIDENCE_TIER_BY_PUBTYPE = [
    # (publication_type_pattern, tier_label)
    ("Meta-Analysis", "Level 1: Meta-Analysis"),
    ("Systematic Review", "Level 1: Systematic Review"),
    ("Randomized Controlled Trial", "Level 2: Randomized Controlled Trial"),
    ("Clinical Trial, Phase III", "Level 2: Clinical Trial (Phase III)"),
    ("Clinical Trial", "Level 2: Clinical Trial (non-randomized)"),
    ("Cohort Studies", "Level 3: Cohort Study"),
    ("Observational Study", "Level 3: Observational Study"),
    ("Case-Control Studies", "Level 4: Case-Control Study"),
    ("Case Reports", "Level 5: Case Report"),
    ("Practice Guideline", "Guideline"),
    ("Consensus Development Conference", "Consensus Statement"),
    ("Review", "Narrative Review"),
]

# Preferred evidence tiers per question category. Informs retrieval ranking
# and prompt emphasis. Kept small and editable; clinical leadership should
# own and version this.
PREFERRED_TIERS_BY_CATEGORY = {
    "therapeutic": ["Level 1", "Level 2", "Guideline", "Level 3"],
    "diagnostic": ["Level 1", "Level 2", "Level 3", "Guideline"],
    "prognostic": ["Level 3", "Level 1", "Level 2"],
    "etiology": ["Level 3", "Level 4", "Level 1"],
    "screening": ["Guideline", "Level 1", "Level 2"],
    "safety_interaction": ["Level 1", "Level 3", "Guideline", "Level 2"],
    "guideline": ["Guideline", "Consensus Statement", "Level 1"],
    "mixed": ["Level 1", "Level 2", "Guideline", "Level 3"],
}
```

---

## Shared Helpers

A few utilities used across steps. Keeping them together here so each step's code stays focused on the pattern it's teaching.

```python
def _get_opensearch_client() -> OpenSearch:
    """
    Build an IAM-authenticated OpenSearch client.

    Uses the current boto3 session's credentials. In production, the Lambda
    execution role should have least-privilege OpenSearch access scoped to
    the specific domain and index.
    """
    session = boto3.Session()
    credentials = session.get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        OPENSEARCH_REGION,
        "es",  # use "aoss" if targeting OpenSearch Serverless
        session_token=credentials.token,
    )
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )


def _embed_text(text: str) -> list:
    """
    Embed a single string with the configured embedding model.

    CRITICAL: this must match whatever embedder indexed the corpus. If the
    corpus was indexed with Titan v2 and this function uses Titan v1,
    retrieval quality will be garbage and you won't get an error. Always
    pin the embedding model ID in config and verify it matches the index.
    """
    body = json.dumps({"inputText": text})
    response = bedrock_runtime.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    payload = json.loads(response["body"].read())
    return payload["embedding"]


def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from a model response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when told not to.
    Defensive parsing keeps the pipeline robust to that.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON response; returning empty dict")
        return {}


def _safe_utf8_truncate(text: str, max_bytes: int) -> str:
    """
    Truncate text to at most max_bytes when encoded as utf-8.

    Slicing a string by character count can still blow past the byte limit
    for multi-byte characters. Encoding, slicing, and decoding with
    errors='ignore' is the safe pattern.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")
```

---

## Step 1: Receive and Classify the Question

*The pseudocode calls this `receive_question(request)`. A clinician submits a question. We persist the request immediately for audit, then route it through a small model to classify what kind of question it is and whether it is specific enough to drive retrieval. Vague questions get a clarifying round; crisp questions proceed.*

```python
def receive_question(request: dict) -> dict:
    """
    Initialize the query, persist initial state, and classify the question.

    The request is the trigger for the entire pipeline. We persist state
    immediately so that if any later step fails, we have a record of what
    was asked and by whom. The question may contain PHI via patient context,
    so the audit trail lives in S3/DynamoDB with encryption and access
    controls, not in application logs.

    Args:
        request: Dict with request details. Expected keys:
                 - question:              free-text clinical question
                 - requesting_user:       user identity from Cognito or EHR context
                 - requesting_specialty:  requesting specialty (informs source weighting)
                 - patient_context:       optional dict with age, conditions, meds, etc.
                                          If present, this is PHI. Treat accordingly.

    Returns:
        Dict with query_id, status, and classification result (or a
        clarification request if the question is too vague to retrieve).
    """
    query_id = str(uuid.uuid4())
    now = datetime.datetime.now(timezone.utc)

    # Persist the initial request. In production, add a server-side encryption
    # decision here: if patient_context contains PHI, record that flag on the
    # item so retention policies and access controls apply correctly.
    queries_table = dynamodb.Table(LITERATURE_QUERIES_TABLE)
    queries_table.put_item(Item={
        "query_id": query_id,
        "status": "INITIATED",
        "question": request["question"],
        "patient_context": request.get("patient_context") or {},
        "requesting_user": request["requesting_user"],
        "requesting_specialty": request.get("requesting_specialty", "general"),
        "received_at": now.isoformat(),
    })

    # Classify question type with a cheap model. Why classify? Because the
    # preferred evidence source mix depends on the question type: a
    # therapeutic question weights RCTs and systematic reviews; a prognostic
    # question weights cohort studies; a guideline question weights
    # guideline documents. Classification is cheap; running retrieval with
    # the wrong source mix is expensive and produces worse answers.
    classification_system = """You classify clinical questions to route them through a literature-search pipeline.

Return ONLY valid JSON in this exact shape:
{
  "category": "therapeutic | diagnostic | prognostic | etiology | screening | safety_interaction | guideline | mixed",
  "specificity": "high | medium | low",
  "needs_clarification": true | false,
  "suggested_clarification_question": "a targeted follow-up question, or empty string"
}

RULES:
- "high" specificity: the question names a specific intervention, condition, and population.
- "medium": one or two of those are clear; the rest are implied.
- "low": broad or ambiguous; retrieval would likely miss. Set needs_clarification = true.
- When needs_clarification is true, suggest ONE targeted question the clinician could answer
  in a few words to make the search tractable. Do not ask multiple questions at once.
- For safety_interaction, match drug-drug, drug-disease, drug-pregnancy, and contraindication questions.
- "guideline" is specifically "what do the current guidelines say about X"-style questions."""

    patient_snippet = ""
    if request.get("patient_context"):
        patient_snippet = f"\nPATIENT CONTEXT: {json.dumps(request['patient_context'])}"

    classification_user = f"QUESTION: {request['question']}{patient_snippet}"

    classification_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 400,
        "temperature": 0.0,
        "system": classification_system,
        "messages": [{"role": "user", "content": classification_user}],
    })

    try:
        response = bedrock_runtime.invoke_model(
            modelId=SMALL_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=classification_body,
        )
        payload = json.loads(response["body"].read())
        classification = _parse_json_response(payload["content"][0]["text"])
    except Exception as exc:
        # If classification fails, fall back to "mixed/medium" and proceed.
        # Better to retrieve suboptimally than to block the clinician.
        logger.warning("Classification failed for %s: %s", query_id, exc)
        classification = {
            "category": "mixed", "specificity": "medium",
            "needs_clarification": False, "suggested_clarification_question": "",
        }

    # If the question is too vague, return the clarification prompt to the
    # caller rather than running retrieval. Running hybrid retrieval +
    # re-ranking + generation on a vague question wastes dollars and
    # surfaces noisy results that erode clinician trust.
    if classification.get("needs_clarification"):
        queries_table.update_item(
            Key={"query_id": query_id},
            UpdateExpression="SET #s = :s, classification = :c",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "CLARIFICATION_NEEDED",
                ":c": classification,
            },
        )
        logger.info("Query %s needs clarification", query_id)
        return {
            "query_id": query_id,
            "status": "CLARIFICATION_NEEDED",
            "clarification_question": classification.get(
                "suggested_clarification_question", ""),
            "classification": classification,
        }

    queries_table.update_item(
        Key={"query_id": query_id},
        UpdateExpression="SET #s = :s, classification = :c",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "CLASSIFIED",
            ":c": classification,
        },
    )
    logger.info(
        "Classified query %s: category=%s specificity=%s",
        query_id,
        classification.get("category"),
        classification.get("specificity"),
    )
    return {
        "query_id": query_id,
        "status": "CLASSIFIED",
        "classification": classification,
    }
```

---

## Step 2: Expand the Query and Extract Entities

*The pseudocode calls this `expand_query_and_extract_entities(question, patient_context)`. Good retrieval starts with good queries. A small model rewrites the clinician's question into several search variants that cover likely terminology shifts (generic vs brand names, MeSH-style terms, population-focused vs intervention-focused phrasings). In parallel, Comprehend Medical pulls drugs and conditions out of the question and maps them to RxNorm and ICD-10, which drives metadata filtering during retrieval.*

```python
def expand_query_and_extract_entities(
    question: str,
    patient_context: dict | None,
) -> dict:
    """
    Generate query variants and extract medical entities from the question.

    Query expansion catches literature that uses different terminology than
    the clinician's phrasing. If the question says "blood thinner" and the
    literature uses "direct oral anticoagulant," keyword-only retrieval
    misses the right papers. Vector search helps, but paired with expansion
    it's better still.

    Entity extraction gives us the drug and condition mentions that drive
    metadata-filtered retrieval ("chunks that mention both methotrexate AND
    anastrozole"), which is typically higher-precision than a bare semantic
    search.

    Args:
        question:        Free-text clinical question.
        patient_context: Optional structured patient info; used to infer
                         population tags (adult, pediatric, etc.).

    Returns:
        Dict with expanded_queries (list), canonical_query (str), and
        entities (dict of medications, conditions, procedures, population).
    """
    # --- LLM query expansion ---
    expansion_system = """You rewrite clinical questions as search queries for a medical literature index.

Produce 3-5 queries that a skilled medical librarian would use to search PubMed. Each query should:
- Use medical terminology with BOTH generic and brand drug names where applicable
- Include MeSH-style terms where they'd help
- Be phrased as SEARCH QUERIES (terms joined by AND/OR if useful), not full sentences
- Cover different angles: intervention-focused, outcome-focused, population-focused

Also produce one "canonical" rephrasing: the single most precise formulation for semantic
retrieval. The canonical should read as a natural sentence, not as search syntax.

Return ONLY valid JSON:
{
  "queries": ["query 1", "query 2", "query 3"],
  "canonical": "the single canonical rephrasing"
}"""

    patient_snippet = ""
    if patient_context:
        patient_snippet = f"\nPATIENT CONTEXT: {json.dumps(patient_context)}"

    expansion_user = f"QUESTION: {question}{patient_snippet}"

    expansion_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 800,
        "temperature": 0.3,  # Slight variation helps diversify query variants
        "system": expansion_system,
        "messages": [{"role": "user", "content": expansion_user}],
    })

    try:
        response = bedrock_runtime.invoke_model(
            modelId=SMALL_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=expansion_body,
        )
        payload = json.loads(response["body"].read())
        expansion = _parse_json_response(payload["content"][0]["text"])
    except Exception as exc:
        # On failure, fall back to using the original question as the
        # canonical and as the only query variant.
        logger.warning("Query expansion failed: %s", exc)
        expansion = {"queries": [question], "canonical": question}

    # --- Entity extraction via Comprehend Medical ---
    text_for_entities = question
    if patient_context:
        text_for_entities = f"{text_for_entities} {json.dumps(patient_context)}"
    text_for_entities = _safe_utf8_truncate(
        text_for_entities, COMPREHEND_MEDICAL_MAX_BYTES,
    )

    medications = []
    conditions = []
    procedures = []
    anatomy = []

    try:
        cm_response = comprehend_medical.detect_entities_v2(Text=text_for_entities)
        for entity in cm_response.get("Entities", []):
            category = entity.get("Category")
            item = {
                "text": entity.get("Text"),
                "type": entity.get("Type"),
                "score": entity.get("Score"),
                "traits": [t.get("Name") for t in entity.get("Traits", [])],
            }
            if category == "MEDICATION":
                medications.append(item)
            elif category == "MEDICAL_CONDITION":
                # Skip negated conditions; the question is about the present
                # condition, not ones explicitly ruled out.
                if "NEGATION" not in item["traits"]:
                    conditions.append(item)
            elif category == "TEST_TREATMENT_PROCEDURE":
                procedures.append(item)
            elif category == "ANATOMY":
                anatomy.append(item)
    except Exception as exc:
        logger.warning("Comprehend Medical entity extraction failed: %s", exc)

    # Ontology mapping for drugs and conditions. These give us normalized
    # codes the corpus index may be tagged with, which boosts retrieval
    # precision when the text forms don't match exactly.
    rxnorm_codes = []
    icd10_codes = []
    try:
        rx_response = comprehend_medical.infer_rx_norm(Text=text_for_entities)
        for entity in rx_response.get("Entities", []):
            for concept in entity.get("RxNormConcepts", []):
                rxnorm_codes.append({
                    "text": entity.get("Text"),
                    "code": concept.get("Code"),
                    "description": concept.get("Description"),
                    "score": concept.get("Score"),
                })
    except Exception as exc:
        logger.warning("RxNorm mapping failed: %s", exc)

    try:
        icd_response = comprehend_medical.infer_icd10_cm(Text=text_for_entities)
        for entity in icd_response.get("Entities", []):
            for concept in entity.get("ICD10CMConcepts", []):
                icd10_codes.append({
                    "text": entity.get("Text"),
                    "code": concept.get("Code"),
                    "description": concept.get("Description"),
                    "score": concept.get("Score"),
                })
    except Exception as exc:
        logger.warning("ICD-10 mapping failed: %s", exc)

    # Infer population from patient context. This becomes a metadata filter
    # during retrieval so we prefer adult studies for adult patients and
    # pediatric studies for pediatric patients, when the question is
    # population-sensitive.
    population_tags = []
    if patient_context:
        age = patient_context.get("age")
        if isinstance(age, (int, float)):
            if age < 18:
                population_tags.append("pediatric")
            elif age >= 65:
                population_tags.append("geriatric")
                population_tags.append("adult")
            else:
                population_tags.append("adult")
        if patient_context.get("pregnant"):
            population_tags.append("pregnancy")

    result = {
        "expanded_queries": expansion.get("queries", [question]),
        "canonical_query": expansion.get("canonical", question),
        "entities": {
            "medications": medications,
            "conditions": conditions,
            "procedures": procedures,
            "anatomy": anatomy,
            "rxnorm_codes": rxnorm_codes,
            "icd10_codes": icd10_codes,
            "population": population_tags,
        },
    }
    logger.info(
        "Expanded query into %d variants; extracted %d meds, %d conditions",
        len(result["expanded_queries"]),
        len(medications),
        len(conditions),
    )
    return result
```

---

## Step 3: Multi-Source Retrieval with Hybrid Search

*The pseudocode calls this `multi_source_retrieval(expanded_queries, canonical_query, entities, question_category)`. Run dense-vector similarity for each expanded query in parallel against the OpenSearch index, also run a BM25 keyword search driven by extracted drug and condition terms, then fuse the result sets with reciprocal rank fusion. Metadata filters (date range, population, source type) run alongside both searches to drop irrelevant content before similarity computation.*

```python
def multi_source_retrieval(
    expanded_queries: list,
    canonical_query: str,
    entities: dict,
    question_category: str,
) -> list:
    """
    Run hybrid retrieval and return a fused, deduplicated candidate list.

    The pattern: cast a wide net (high-recall retrieval), then pass the
    candidates to a re-ranker for precision. Each retrieval mode catches
    different kinds of relevance:
      - Dense-vector catches semantic similarity across terminology shifts.
      - BM25 catches exact-match entity terms (specific drug names, trial
        acronyms, condition names) that vector search sometimes misses.
      - Metadata filters drop papers outside the population or date window
        before similarity computation, which improves precision and saves
        cost on the re-ranker.

    Args:
        expanded_queries:  Query variants from Step 2.
        canonical_query:   Canonical rephrasing, used for the primary
                           vector query.
        entities:          Extracted entities (medications, conditions, etc.).
        question_category: Question type from Step 1, drives source preferences.

    Returns:
        List of chunk candidate dicts (deduped by chunk_id), each with
        retrieval scores and source metadata.
    """
    client = _get_opensearch_client()

    # Build metadata filters. Start simple: restrict to the last 15 years by
    # default (tune per category), and if a population was inferred, prefer
    # chunks tagged with that population.
    now_year = datetime.datetime.now(timezone.utc).year
    base_filters = [
        {"range": {"publication_year": {"gte": now_year - 15}}},
    ]
    if entities.get("population"):
        base_filters.append({
            "terms": {"population_tags": entities["population"]}
        })

    # Embed each query variant with the same embedder that indexed the corpus
    # (see the warning in _embed_text). The canonical query goes first; the
    # expansion variants follow for diversity.
    query_embeddings = []
    for q in [canonical_query] + expanded_queries:
        try:
            query_embeddings.append((q, _embed_text(q)))
        except Exception as exc:
            logger.warning("Embedding failed for query '%s': %s", q, exc)

    # --- Dense-vector search per query variant ---
    # We collect lists of results so we can fuse them. Real deployments may
    # run these in parallel via asyncio or a ThreadPoolExecutor; keeping
    # them serial here for readability.
    ranked_lists = []
    for query_text, query_vector in query_embeddings:
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
            "_source": {"excludes": ["embedding"]},  # don't ship vectors back
        }
        try:
            resp = client.search(index=OPENSEARCH_INDEX, body=knn_query)
            hits = resp.get("hits", {}).get("hits", [])
            ranked_lists.append([h["_source"] | {"_score": h["_score"],
                                                 "_retrieval_mode": f"vector:{query_text[:40]}"}
                                 for h in hits])
        except Exception as exc:
            logger.warning("kNN search failed for query '%s': %s", query_text, exc)

    # --- BM25 keyword search driven by entity terms ---
    # Entities are high-signal keywords. We build a BM25 query combining
    # drug names, condition names, and procedure names.
    entity_terms = []
    for m in entities.get("medications", []):
        if m.get("text"):
            entity_terms.append(m["text"])
    for c in entities.get("conditions", []):
        if c.get("text"):
            entity_terms.append(c["text"])
    for p in entities.get("procedures", []):
        if p.get("text"):
            entity_terms.append(p["text"])

    if entity_terms:
        bm25_query = {
            "size": INITIAL_RETRIEVAL_SIZE,
            "query": {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query": " ".join(entity_terms),
                            "fields": ["chunk_text^2", "paper_title^3"],
                            "type": "best_fields",
                        }
                    }],
                    "filter": base_filters,
                }
            },
            "_source": {"excludes": ["embedding"]},
        }
        try:
            resp = client.search(index=OPENSEARCH_INDEX, body=bm25_query)
            hits = resp.get("hits", {}).get("hits", [])
            ranked_lists.append([h["_source"] | {"_score": h["_score"],
                                                 "_retrieval_mode": "bm25:entities"}
                                 for h in hits])
        except Exception as exc:
            logger.warning("BM25 entity search failed: %s", exc)

    # --- Reciprocal rank fusion across all ranked lists ---
    # RRF: score(doc) = sum over lists of (1 / (k + rank_in_list))
    # k=60 is a common default; dampens the influence of high-ranked-once
    # outliers vs. documents that appear across multiple lists.
    fused_scores = defaultdict(float)
    seen = {}  # chunk_id -> merged source dict
    K = 60
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            chunk_id = hit.get("chunk_id")
            if not chunk_id:
                continue
            fused_scores[chunk_id] += 1.0 / (K + rank)
            if chunk_id not in seen:
                seen[chunk_id] = hit

    # Sort by fused score descending, keep top RERANK_CANDIDATE_LIMIT
    sorted_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
    candidates = []
    for cid in sorted_ids[:RERANK_CANDIDATE_LIMIT]:
        doc = dict(seen[cid])
        doc["_rrf_score"] = fused_scores[cid]
        candidates.append(doc)

    logger.info(
        "Retrieval returned %d candidates from %d ranked lists",
        len(candidates), len(ranked_lists),
    )
    return candidates
```

---

## Step 4: Re-Rank Candidates

*The pseudocode calls this `rerank_candidates(canonical_query, candidates, top_k)`. Initial retrieval is optimized for recall; re-ranking is optimized for precision at the top. A proper cross-encoder re-ranker (hosted on SageMaker) is the production choice. For illustration here, we use a small-LLM re-ranker: score each (query, chunk) pair with Claude Haiku and sort. This is cheaper to demo but less accurate than a real cross-encoder; flag it as a known trade-off in production planning.*

```python
def rerank_candidates(
    canonical_query: str,
    candidates: list,
    top_k: int = TOP_K_FOR_GENERATION,
) -> list:
    """
    Re-rank candidate chunks using a small LLM as a stand-in re-ranker.

    In production, use a fine-tuned cross-encoder hosted on SageMaker
    (MS-MARCO re-rankers adapt reasonably to medical retrieval; a medically
    fine-tuned re-ranker is better). A small-LLM re-ranker is cheaper and
    easier to wire up, which is why it shows up here, but accuracy at the
    top of the ranking meaningfully improves with a real cross-encoder.

    Args:
        canonical_query: The canonical rephrasing of the question.
        candidates:      Retrieval candidates from Step 3.
        top_k:           Keep this many after re-ranking.

    Returns:
        Top-k candidates sorted by re-ranker relevance score (descending).
    """
    if not candidates:
        return []

    # Batch scoring: pass N (query, chunk) pairs per model call. Higher N
    # reduces per-chunk cost but raises prompt-length sensitivity. For a
    # real deployment, tune or skip this approach in favor of a cross-encoder.
    BATCH_SIZE = 10
    scored = []

    reranker_system = """You score passages for relevance to a clinical question.

For each passage, assign an integer relevance score from 0 to 10:
- 10: passage directly answers or is central to the question
- 7-9: passage is highly relevant; clearly on-topic
- 4-6: passage is on the broader topic but less direct
- 1-3: passage is tangentially related
- 0: passage is off-topic or irrelevant

Return ONLY valid JSON in this exact shape:
{"scores": [{"id": "passage_id", "score": <0-10>}, ...]}

Score strictly. Do not reward passages for sounding medical; they must be
relevant to the SPECIFIC clinical question being asked."""

    for batch_start in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[batch_start:batch_start + BATCH_SIZE]

        # Build a compact prompt for this batch
        passages_block = ""
        for i, c in enumerate(batch):
            # Truncate chunk_text aggressively for the re-ranker; the goal
            # is a relevance signal, not full comprehension.
            snippet = (c.get("chunk_text") or "")[:600]
            passages_block += (
                f"\n[passage_{batch_start + i}]\n"
                f"Title: {c.get('paper_title', '')}\n"
                f"Section: {c.get('section', '')}\n"
                f"Content: {snippet}\n"
            )

        user_msg = (
            f"CLINICAL QUESTION:\n{canonical_query}\n\n"
            f"PASSAGES TO SCORE:{passages_block}\n\n"
            "Return JSON with a score (0-10) for each passage id."
        )

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1500,
            "temperature": 0.0,
            "system": reranker_system,
            "messages": [{"role": "user", "content": user_msg}],
        })

        try:
            resp = bedrock_runtime.invoke_model(
                modelId=SMALL_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            payload = json.loads(resp["body"].read())
            parsed = _parse_json_response(payload["content"][0]["text"])
            score_map = {s["id"]: s.get("score", 0)
                         for s in parsed.get("scores", [])}
        except Exception as exc:
            logger.warning("Re-ranker batch failed: %s", exc)
            score_map = {}

        for i, c in enumerate(batch):
            passage_id = f"passage_{batch_start + i}"
            score = score_map.get(passage_id, 0)
            c_copy = dict(c)
            c_copy["_rerank_score"] = score
            # Fallback: if the re-ranker returned no score, use the RRF score
            # as a tiebreaker so we don't collapse the ordering to zero.
            if score == 0:
                c_copy["_rerank_score"] = c_copy.get("_rrf_score", 0)
            scored.append(c_copy)

    # Sort by re-ranker score descending; ties broken by RRF score.
    scored.sort(
        key=lambda c: (c["_rerank_score"], c.get("_rrf_score", 0)),
        reverse=True,
    )
    top = scored[:top_k]
    logger.info(
        "Re-ranked to top %d (from %d candidates)",
        len(top), len(candidates),
    )
    return top
```

---

## Step 5: Tag Evidence Tiers

*The pseudocode calls this `tag_evidence_tiers(top_chunks)`. For each selected chunk, annotate the source's evidence tier using publication-type metadata. PubMed's publication-type tags are the practical input; GRADE-style bias assessment requires reading the methods carefully and is left to the clinician. The tier flows into the generation prompt so the model can weight evidence appropriately, and into the rendered bibliography so the clinician sees it at a glance.*

```python
def tag_evidence_tiers(top_chunks: list) -> list:
    """
    Tag each chunk with a simplified evidence tier label.

    This is coarse by design. PubMed publication types are fairly reliable
    for study type (RCT, systematic review, case report) but don't capture
    risk of bias or directness, which are what GRADE adds. A clinician
    reading the final answer still has to judge quality; we're just
    surfacing the structural evidence tier so they can.

    Args:
        top_chunks: The top-k chunks after re-ranking.

    Returns:
        Same list with 'evidence_tier' and 'is_recent' fields added.
    """
    now_year = datetime.datetime.now(timezone.utc).year
    for chunk in top_chunks:
        pub_types = chunk.get("publication_types") or []
        source_type = chunk.get("source_type") or ""

        # Walk the mapping in priority order; first match wins. That gives
        # us "Meta-Analysis" ahead of "Systematic Review" when both are
        # tagged, which matches evidence-hierarchy conventions.
        tier = None
        for pattern, label in EVIDENCE_TIER_BY_PUBTYPE:
            if any(pattern.lower() in pt.lower() for pt in pub_types):
                tier = label
                break

        if tier is None:
            # Fall back to source_type for content that doesn't have
            # publication_types (guidelines, institutional content).
            if source_type == "guideline":
                issuing = chunk.get("journal_or_body") or "Guideline"
                tier = f"Guideline: {issuing}"
            elif source_type == "narrative_review":
                tier = "Narrative Review (non-systematic)"
            elif source_type == "institutional":
                tier = "Institutional Content"
            else:
                tier = "Unclassified"

        chunk["evidence_tier"] = tier
        pub_year = chunk.get("publication_year") or 0
        chunk["is_recent"] = pub_year >= (now_year - 5)

    logger.info("Tagged %d chunks with evidence tiers", len(top_chunks))
    return top_chunks
```

---

## Step 6: Fetch Full-Text Context for Top Chunks

*The pseudocode calls this `fetch_full_context(top_chunks)`. Individual chunks can lose critical surrounding context: a finding lives in a paragraph, its caveats live in adjacent paragraphs, and the population description lives in a different section entirely. Before generation, fetch a window of context around each chunk from the source paper if available. For abstract-only sources, the chunk IS the full available context; that's fine, just mark it so the prompt knows what it's working with.*

```python
def fetch_full_context(top_chunks: list) -> list:
    """
    Fetch surrounding context for each top chunk, if available.

    For PMC Open Access full-text sources, we fetch the paragraph before
    and after the chunk within the same section. For PubMed abstract-only
    sources, the chunk text IS the full available context; we just label
    it accordingly.

    In a real deployment, the "fetch surrounding paragraphs" step is an
    OpenSearch query against a secondary full-text index, keyed by
    paper_id and paragraph_index. Stubbed here with a placeholder so the
    pattern is visible.

    Args:
        top_chunks: Chunks after re-ranking and tier tagging.

    Returns:
        Same list with 'full_context' field added per chunk.
    """
    client = _get_opensearch_client()

    for chunk in top_chunks:
        source_type = chunk.get("source_type") or ""
        chunk_text = chunk.get("chunk_text", "")

        if source_type == "pmc_open_access":
            # Attempt to fetch neighboring paragraphs in the same section.
            # The secondary index would have paragraph_index for ordering.
            paper_id = chunk.get("paper_id")
            section = chunk.get("section")
            para_index = chunk.get("paragraph_index")
            try:
                neighbor_query = {
                    "size": 3,  # -1, 0, +1 relative to the hit
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"paper_id": paper_id}},
                                {"term": {"section": section}},
                            ],
                            "filter": [
                                {"range": {
                                    "paragraph_index": {
                                        "gte": (para_index or 0) - 1,
                                        "lte": (para_index or 0) + 1,
                                    }
                                }},
                            ],
                        }
                    },
                    "sort": [{"paragraph_index": {"order": "asc"}}],
                    "_source": {"includes": ["chunk_text", "paragraph_index"]},
                }
                resp = client.search(index=OPENSEARCH_INDEX, body=neighbor_query)
                neighbors = resp.get("hits", {}).get("hits", [])
                if neighbors:
                    combined = "\n\n".join(
                        h["_source"].get("chunk_text", "") for h in neighbors
                    )
                    chunk["full_context"] = combined
                else:
                    chunk["full_context"] = chunk_text
            except Exception as exc:
                logger.warning(
                    "Neighbor fetch failed for paper %s: %s", paper_id, exc,
                )
                chunk["full_context"] = chunk_text
        else:
            # Abstract-only or other source type: the chunk text is all we have.
            chunk["full_context"] = chunk_text

        # Belt-and-suspenders: ensure full_context is non-empty so the prompt
        # builder doesn't emit blank passages.
        if not chunk["full_context"]:
            chunk["full_context"] = chunk_text or "(no content available)"

    logger.info("Fetched full context for %d chunks", len(top_chunks))
    return top_chunks
```

---

## Step 7: Grounded Generation with Citation Discipline

*The pseudocode calls this `generate_synthesis(question, patient_context, top_chunks, question_category)`. Build a prompt that includes the question, the retrieved chunks with stable identifiers, their evidence tiers, and full context. Tell the model to cite every claim by chunk identifier, describe evidence rather than recommend, surface uncertainty honestly, and quote numerical findings verbatim. Apply a Bedrock Guardrail with contextual grounding as the outer guardrail; the validator in Step 8 is the inner check.*

````python
def generate_synthesis(
    question: str,
    patient_context: dict | None,
    top_chunks: list,
    question_category: str,
    regeneration_hint: str = "",
) -> dict:
    """
    Generate the synthesized answer with citation tracking.

    The aggregated retrieved chunks are the only source of facts. The prompt
    enforces grounded generation, preserved negations, preserved uncertainty,
    preserved numerical values, explicit study-population naming, and
    description (not recommendation) language. The output carries both
    readable prose and a structured claims list for downstream validation.

    Args:
        question:          The clinician's original question.
        patient_context:   Optional structured patient info.
        top_chunks:        Top chunks after re-ranking, tagged with tiers
                           and full context.
        question_category: Question category from Step 1.
        regeneration_hint: Extra instruction for retries. Populated by the
                           validator on failed runs.

    Returns:
        Dict with status, answer_text, claims (list), and the chunk set used.
    """
    if not top_chunks:
        return {
            "status": "NO_EVIDENCE",
            "answer_text": (
                "No relevant literature was retrieved for this question. "
                "The corpus may not cover this topic adequately, or the "
                "question may need rephrasing."
            ),
            "claims": [],
        }

    # Build the chunks block with stable identifiers the model will cite.
    # chunk_N identifiers here are local to this generation; they get mapped
    # to numbered citations ([1], [2], ...) during rendering.
    chunks_block_parts = []
    for i, c in enumerate(top_chunks, start=1):
        chunks_block_parts.append(
            f"[chunk_{i}] (Evidence tier: {c.get('evidence_tier', 'Unclassified')}, "
            f"Year: {c.get('publication_year', 'unknown')}, "
            f"Source: {c.get('journal_or_body', 'unknown')})\n"
            f"Title: {c.get('paper_title', '(no title)')}\n"
            f"Section: {c.get('section', 'unknown')}\n"
            f"Content: {c.get('full_context', '')}\n"
        )
    chunks_block = "\n".join(chunks_block_parts)

    preferred_tiers = PREFERRED_TIERS_BY_CATEGORY.get(question_category, [])
    preferred_hint = (
        f"For this question category ({question_category}), "
        f"prefer evidence from these tiers when present: "
        f"{', '.join(preferred_tiers)}."
        if preferred_tiers else ""
    )

    generation_system = f"""You are synthesizing medical literature for a practicing clinician.
Your answer will appear alongside citations to the retrieved sources.
Your ONLY knowledge sources are the retrieved chunks provided below.
Do NOT use any knowledge from your training data beyond what is in the chunks.

HARD REQUIREMENTS:
1. Every specific claim MUST cite at least one chunk by its identifier (e.g., [chunk_3]).
2. Do NOT cite chunks that are not in the retrieved set. Do NOT invent citations.
3. Quote numerical findings verbatim from the chunk text. Immediately follow numerics
   with their chunk citation. Do not paraphrase numbers.
4. Preserve negation language exactly. "No evidence of X" must NOT become "X is unlikely."
5. Preserve uncertainty language. "Possible," "may," "suggests," "associated with" stay
   as written. Do not escalate observational associations to causal claims.
6. Name the study population for each cited finding (adult/pediatric, specific condition,
   sample size if in the chunk). Population mismatches are a common source of error.
7. Rate overall evidence strength: Strong, Moderate, Weak, or Insufficient.
   Justify the rating based on the tier mix and directness of the retrieved chunks.
8. If the retrieved chunks do not directly address the question, say so:
   "The retrieved literature does not directly address this question. The closest
   relevant evidence is..." Do NOT confabulate an answer.
9. DESCRIBE the evidence. Do NOT recommend actions. Recommendations are the clinician's
   prerogative, not yours. "The evidence supports X as an option" rather than "You should do X."
10. Surface equipoise. If evidence is mixed, show the mix. Do not collapse to a false consensus.

{preferred_hint}

OUTPUT STRUCTURE (markdown):
## Summary
(2-4 sentence overall summary with citations)

## Key Findings by Evidence Tier
(systematic reviews first, RCTs next, observational, case-level, then guidelines/consensus;
 each finding cited and population-labeled)

## Limitations and Gaps
(honest list of what the retrieved evidence doesn't cover)

## Overall Evidence Strength: {{Strong|Moderate|Weak|Insufficient}}
(one-paragraph justification of the rating)

AT THE END, append a JSON code block with tracked claims:
```json
{{
  "evidence_strength": "Strong|Moderate|Weak|Insufficient",
  "factual_claims": [
    {{
      "claim": "the specific factual assertion (verbatim from your answer)",
      "chunk_citations": ["chunk_N", ...],
      "population": "study population the claim applies to",
      "preserves_numerics": true|false
    }}
  ]
}}
```"""

    patient_block = ""
    if patient_context:
        patient_block = f"\nPATIENT CONTEXT:\n{json.dumps(patient_context)}\n"

    hint_block = ""
    if regeneration_hint:
        hint_block = f"\nREGENERATION HINT:\n{regeneration_hint}\n"

    generation_user = (
        f"QUESTION:\n{question}\n"
        f"{patient_block}"
        f"QUESTION CATEGORY: {question_category}\n"
        f"{hint_block}\n"
        f"RETRIEVED EVIDENCE:\n\n{chunks_block}"
    )

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        # Low but not zero: we want natural prose with slight variation, not
        # robotic output. Higher than this and the model drifts from grounding.
        "temperature": 0.2,
        "system": generation_system,
        "messages": [{"role": "user", "content": generation_user}],
    }

    invoke_kwargs = {
        "modelId": GENERATION_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(request_body),
    }

    # Apply the Bedrock Guardrail with contextual grounding if configured.
    # For literature synthesis, the grounding check is the outer guardrail:
    # it compares model output against a reference context. The validator
    # in Step 8 is the inner check. Running both is the right posture.
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"] = GUARDRAIL_VERSION

    try:
        response = bedrock_runtime.invoke_model(**invoke_kwargs)
        response_payload = json.loads(response["body"].read())
    except Exception as exc:
        logger.error("Generation failed: %s", exc)
        return {"status": "GENERATION_FAILED", "error": str(exc),
                "answer_text": "", "claims": []}

    # Detect Guardrail intervention. Field shape varies by Guardrail
    # configuration; verify against your setup and branch accordingly.
    stop_reason = response_payload.get("stop_reason")
    if stop_reason == "guardrail_intervened":
        logger.warning("Guardrail intervened on synthesis; returning rejection")
        return {
            "status": "GROUNDING_REJECTED",
            "answer_text": "",
            "claims": [],
        }

    raw_text = response_payload["content"][0]["text"]

    # Extract the JSON block from the response. The model is instructed to
    # put it at the end in a code fence; defensive parsing keeps us robust
    # to small formatting drift.
    claims_json = _extract_trailing_json_block(raw_text)
    # Remove the JSON block from the visible answer so the clinician only
    # sees the prose. The claims list is metadata.
    answer_text = _strip_trailing_json_block(raw_text)

    evidence_strength = claims_json.get("evidence_strength", "Insufficient")
    claims = claims_json.get("factual_claims", [])

    logger.info(
        "Generated synthesis: %d chars, %d claims, strength=%s",
        len(answer_text), len(claims), evidence_strength,
    )
    return {
        "status": "GENERATED",
        "answer_text": answer_text,
        "evidence_strength": evidence_strength,
        "claims": claims,
        "chunks_used": top_chunks,
    }


def _extract_trailing_json_block(text: str) -> dict:
    """
    Pull the last ```json ... ``` block out of the model's response.

    Returns an empty dict if no block is found or parsing fails.
    """
    # Find the last fenced json block; model may emit multiple during
    # regeneration if it gets confused, so we take the last one.
    matches = re.findall(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL)
    if not matches:
        # Last-ditch: look for a bare JSON object at the end.
        last_brace = text.rfind("{")
        if last_brace >= 0:
            candidate = text[last_brace:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                return {}
        return {}
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        logger.warning("Trailing JSON block failed to parse")
        return {}


def _strip_trailing_json_block(text: str) -> str:
    """Remove the last ```json ... ``` block and any trailing whitespace."""
    cleaned = re.sub(
        r"```json\s*.*?\s*```\s*$", "", text.strip(), flags=re.DOTALL,
    )
    return cleaned.strip()
````

---

## Step 8: Validate Citations and Claims

*The pseudocode calls this `validate_answer(answer_text, claims, chunks_used, retry_count)`. Belt-and-suspenders alongside the Guardrail grounding check. For every citation, verify the chunk is in the retrieved set. For every claim with numerical values, verify the numbers appear verbatim in the cited chunks. For other claims, verify substantive overlap with the cited content. Flag unverified claims and route to regeneration or human review based on the failure rate.*

```python
def validate_answer(
    answer_text: str,
    claims: list,
    chunks_used: list,
    retry_count: int = 0,
) -> dict:
    """
    Verify each tracked claim against the retrieved chunks.

    Validation is a layered check:
      1. Every claim cites at least one chunk that was actually retrieved.
      2. Numeric values in claims appear verbatim in the cited chunks'
         content (after normalization). A sign flip or digit flip on a
         dose, p-value, or hazard ratio is a catastrophic error.
      3. Non-numeric claims have substantive token overlap with cited content.
      4. Population labels on claims match the cited chunks' populations
         when population data is present in the chunk metadata.

    The severity model:
      - HIGH severity: citation not in retrieved set, numeric mismatch,
        population mismatch. These should block delivery.
      - MEDIUM severity: low semantic overlap. Warning, not blocker.

    Args:
        answer_text:  The generated prose (used for inline-citation scan).
        claims:       The claims list from the generator.
        chunks_used:  The top chunks that were passed to generation.
        retry_count:  Current attempt count for the generation-validation loop.

    Returns:
        Dict with status (VALIDATED | RETRY_NEEDED | REVIEW_REQUIRED),
        unverified claims list, and guidance for the next retry if needed.
    """
    if not claims:
        return {
            "status": "RETRY_NEEDED",
            "unverified_claims": [],
            "suggested_prompt_augmentation": (
                "The previous draft did not include the structured claims "
                "JSON block. Every claim in your answer must be tracked "
                "with a citation, population, and preserves_numerics flag."
            ),
        }

    chunk_by_id = {f"chunk_{i + 1}": c for i, c in enumerate(chunks_used)}

    # Also scan the answer text for any [chunk_N] markers that aren't backed
    # by a tracked claim. Inline citations without tracking are not auditable.
    inline_refs = set(re.findall(r"\[chunk_(\d+)\]", answer_text))
    tracked_refs = set()
    for claim in claims:
        for cid in claim.get("chunk_citations", []) or []:
            m = re.match(r"chunk_(\d+)$", cid)
            if m:
                tracked_refs.add(m.group(1))

    unverified = []

    # Inline citations not in the tracked claims list. These are claims the
    # model inlined without adding to the tracking structure. Small bug in
    # the generator prompt adherence; flag as medium severity.
    orphan_refs = inline_refs - tracked_refs
    for ref in orphan_refs:
        unverified.append({
            "claim": f"[chunk_{ref}] cited inline but not in claims list",
            "issue": "inline_citation_not_tracked",
            "severity": "MEDIUM",
        })

    # Per-claim validation.
    for claim in claims:
        claim_text = (claim.get("claim") or "").strip()
        cited_ids = claim.get("chunk_citations") or []
        population = claim.get("population", "")
        preserves_numerics = claim.get("preserves_numerics", False)

        # 1. Citation existence.
        valid_chunk_ids = [cid for cid in cited_ids if cid in chunk_by_id]
        invalid_chunk_ids = [cid for cid in cited_ids if cid not in chunk_by_id]
        for bad in invalid_chunk_ids:
            unverified.append({
                "claim": claim_text,
                "issue": "citation_not_in_retrieved_set",
                "cited_id": bad,
                "severity": "HIGH",
            })
        if not valid_chunk_ids:
            unverified.append({
                "claim": claim_text,
                "issue": "no_valid_citation",
                "severity": "HIGH",
            })
            continue

        # Concatenate cited chunks' content for text-level checks.
        supporting_text = " ".join(
            chunk_by_id[cid].get("full_context", "") for cid in valid_chunk_ids
        )
        supporting_norm = _normalize_for_match(supporting_text)
        claim_norm = _normalize_for_match(claim_text)

        # 2. Numeric verification.
        if preserves_numerics:
            numeric_tokens = _extract_numeric_tokens(claim_text)
            for num in numeric_tokens:
                if num not in supporting_text:
                    # Also try a normalized form (strip whitespace around units).
                    num_alt = re.sub(r"\s+", "", num)
                    if num_alt not in re.sub(r"\s+", "", supporting_text):
                        unverified.append({
                            "claim": claim_text,
                            "issue": "numeric_not_in_source",
                            "missing_numeric": num,
                            "severity": "HIGH",
                        })

        # 3. Semantic overlap (token-based fallback).
        overlap = _token_overlap_ratio(claim_norm, supporting_norm)
        if overlap < MIN_CLAIM_OVERLAP and not preserves_numerics:
            # Only flag MEDIUM for non-numeric claims; numeric claims already
            # got a HIGH flag above if the numbers didn't match.
            unverified.append({
                "claim": claim_text,
                "issue": "low_semantic_overlap",
                "overlap": round(overlap, 2),
                "severity": "MEDIUM",
            })

        # 4. Population match (if claim specifies a population and chunks have tags).
        if population:
            claim_pop_norm = _normalize_for_match(population)
            citing_pop_tags = []
            for cid in valid_chunk_ids:
                citing_pop_tags.extend(chunk_by_id[cid].get("population_tags") or [])
            if citing_pop_tags:
                tags_norm = [_normalize_for_match(t) for t in citing_pop_tags]
                if not any(t in claim_pop_norm or claim_pop_norm in t
                           for t in tags_norm):
                    unverified.append({
                        "claim": claim_text,
                        "issue": "population_mismatch",
                        "claim_population": population,
                        "chunk_populations": citing_pop_tags,
                        "severity": "HIGH",
                    })

    high_count = sum(1 for u in unverified if u["severity"] == "HIGH")
    medium_count = sum(1 for u in unverified if u["severity"] == "MEDIUM")

    # Decision logic:
    # - Zero HIGH issues and MEDIUM count below 20% of claims: VALIDATED
    # - HIGH issues with retries remaining: RETRY_NEEDED
    # - HIGH issues with retries exhausted: REVIEW_REQUIRED
    if high_count == 0 and medium_count <= max(1, len(claims) // 5):
        return {"status": "VALIDATED", "unverified_claims": unverified}

    if retry_count < MAX_GENERATION_ATTEMPTS - 1:
        hint = _build_regeneration_hint(unverified)
        logger.info(
            "Validation flagged %d HIGH / %d MEDIUM issues; retrying",
            high_count, medium_count,
        )
        return {
            "status": "RETRY_NEEDED",
            "unverified_claims": unverified,
            "suggested_prompt_augmentation": hint,
        }

    logger.warning(
        "Validation exhausted retries; routing to review (%d HIGH, %d MEDIUM)",
        high_count, medium_count,
    )
    return {
        "status": "REVIEW_REQUIRED",
        "unverified_claims": unverified,
    }


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip punctuation edges, collapse whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip().lower())


def _token_overlap_ratio(a: str, b: str) -> float:
    """
    Jaccard-like token overlap as a fallback similarity signal.

    Production systems layer on embedding-based similarity here; this is
    a simple alternative that catches paraphrases with reasonable lexical
    overlap.
    """
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


def _extract_numeric_tokens(text: str) -> list:
    """
    Pull numeric tokens out of a claim for verbatim matching.

    Captures integers, decimals, percentages, ratios ("2:1"), CI-style
    formats ("1.1-1.8"), and units attached to numbers ("80 mg", "4.2%").
    Production systems should also normalize unit variations ("mg" vs
    "milligram") before comparison.
    """
    # Broad pattern: numbers with optional decimal, optional trailing
    # percent/unit, optional range/CI forms.
    pattern = re.compile(
        r"\d+(?:\.\d+)?"
        r"(?:\s*[-–]\s*\d+(?:\.\d+)?)?"
        r"(?:\s*(?:%|mg|mcg|g|kg|mL|IU|mmHg))?"
    )
    return pattern.findall(text)


def _build_regeneration_hint(unverified: list) -> str:
    """Summarize validator issues into a concise instruction for the next try."""
    if not unverified:
        return ""
    # Take up to 3 distinct issue types to keep the hint focused.
    issues_seen = set()
    hint_lines = [
        "The previous draft had validation failures. Fix these specifically:"
    ]
    for u in unverified:
        key = u.get("issue", "")
        if key in issues_seen or len(issues_seen) >= 3:
            continue
        issues_seen.add(key)
        if key == "citation_not_in_retrieved_set":
            hint_lines.append(
                "- You cited chunk IDs that were not in the retrieved set. "
                "Only cite chunk_1 through chunk_N where N is the number "
                "of chunks provided."
            )
        elif key == "no_valid_citation":
            hint_lines.append(
                "- Some claims had no valid chunk citation. Every claim "
                "must cite at least one chunk from the retrieved set."
            )
        elif key == "numeric_not_in_source":
            hint_lines.append(
                "- Numeric values in your claims did not match the source "
                "text verbatim. Quote numbers (doses, p-values, CIs, "
                "percentages) exactly as they appear in the chunks."
            )
        elif key == "population_mismatch":
            hint_lines.append(
                "- Claim populations did not match the cited chunks' "
                "study populations. State the population as it is "
                "described in the chunk."
            )
        elif key == "low_semantic_overlap":
            hint_lines.append(
                "- Some claims drifted from the cited chunks. Stay closer "
                "to the source wording; paraphrase tightly."
            )
        elif key == "inline_citation_not_tracked":
            hint_lines.append(
                "- Every [chunk_N] citation in your prose must also appear "
                "in the tracked factual_claims JSON at the end."
            )
    return "\n".join(hint_lines)
```

---

## Step 9: Render with Citations and Evidence Grades

*The pseudocode calls this `render_answer(answer_text, claims, chunks_used, evidence_strength)`. Replace the `[chunk_N]` identifiers in the prose with numbered citations (`[1]`, `[2]`, etc.), build the bibliography from the chunks that were actually cited, attach source links so clinicians can click through to the original paper, and surface the evidence grade prominently so it frames how the reader weights the answer.*

```python
def render_answer(
    question: str,
    answer_text: str,
    claims: list,
    chunks_used: list,
    evidence_strength: str,
    validation_status: str,
    unverified_claims: list | None = None,
) -> dict:
    """
    Produce the final clinician-facing rendering.

    The prose is the same content the generator produced; the rendering
    layer handles citation numbering, bibliography assembly, and
    presentation of the evidence-strength rating and any review flags.

    Args:
        question:           Original clinician question, for header display.
        answer_text:        Generated answer with [chunk_N] inline refs.
        claims:             Tracked claims from the generator.
        chunks_used:        The chunks passed to generation (for the bib).
        evidence_strength:  Strong | Moderate | Weak | Insufficient.
        validation_status:  Status from the validator.
        unverified_claims:  Any claims the validator flagged, for review display.

    Returns:
        Dict with rendered payload ready for the clinician UI.
    """
    chunk_by_id = {f"chunk_{i + 1}": c for i, c in enumerate(chunks_used)}

    # Identify chunks actually cited in the answer (either inline in the
    # prose or tracked in the claims list). Only these go in the bibliography.
    cited_ids = set()
    for match in re.finditer(r"\[chunk_(\d+)\]", answer_text):
        cid = f"chunk_{match.group(1)}"
        if cid in chunk_by_id:
            cited_ids.add(cid)
    for claim in claims or []:
        for cid in claim.get("chunk_citations") or []:
            if cid in chunk_by_id:
                cited_ids.add(cid)

    # Order bibliography by first appearance in the answer, fall back to
    # chunk order for citations that only appear in the claims list.
    first_appearance = {}
    for cid in cited_ids:
        match = re.search(rf"\[{re.escape(cid)}\]", answer_text)
        first_appearance[cid] = match.start() if match else 10**9

    # Tiebreaker: use the numerical portion of the chunk id for a stable sort.
    def sort_key(cid: str) -> tuple:
        return (first_appearance[cid], int(cid.split("_")[1]))

    ordered_cited = sorted(cited_ids, key=sort_key)

    # Build bibliography with display numbers [1], [2], ...
    citation_map = {}
    bibliography = []
    for display_num, cid in enumerate(ordered_cited, start=1):
        chunk = chunk_by_id[cid]
        formatted = _format_citation(chunk)
        citation_map[cid] = display_num
        source_link = _build_source_link(chunk)
        bibliography.append({
            "display_number": display_num,
            "formatted": formatted,
            "evidence_tier": chunk.get("evidence_tier", "Unclassified"),
            "year": chunk.get("publication_year"),
            "source_link": source_link,
            "original_chunk_id": cid,
        })

    # Replace [chunk_N] markers in the prose with numeric citations.
    rendered_answer = answer_text
    for cid, display_num in citation_map.items():
        rendered_answer = rendered_answer.replace(cid, f"{display_num}")
    # Normalize any [chunk_N] markers we missed (e.g., the model cited a
    # chunk id that wasn't in our mapping). Strip those to avoid dangling
    # references in the final output.
    rendered_answer = re.sub(r"\[chunk_\d+\]", "", rendered_answer)

    # Evidence strength badge framing so the UI can color-code it.
    strength_badge = {
        "Strong": {"label": "Strong", "severity": "high_confidence"},
        "Moderate": {"label": "Moderate", "severity": "moderate_confidence"},
        "Weak": {"label": "Weak", "severity": "low_confidence"},
        "Insufficient": {"label": "Insufficient", "severity": "insufficient"},
    }.get(evidence_strength, {"label": evidence_strength, "severity": "unknown"})

    requires_review = validation_status == "REVIEW_REQUIRED"

    return {
        "question": question,
        "evidence_strength": strength_badge,
        "answer_markdown": rendered_answer,
        "bibliography": bibliography,
        "retrieval_stats": {
            "chunks_available": len(chunks_used),
            "chunks_cited": len(bibliography),
            "claims_tracked": len(claims or []),
        },
        "requires_clinician_review": requires_review,
        "unverified_claims": unverified_claims or [],
        "corpus_date_coverage": _get_corpus_date_range_stub(),
        "disclaimer": (
            "This synthesis is based on retrieved literature and is not a "
            "substitute for clinical judgment. Verify specific claims "
            "against the cited sources before making clinical decisions."
        ),
    }


def _format_citation(chunk: dict) -> str:
    """
    Build a human-readable citation string from chunk metadata.

    Production systems use a style guide (AMA, NLM, Vancouver). This
    starter keeps it short and structured; swap in your preferred formatter.
    """
    authors = chunk.get("authors") or []
    if isinstance(authors, list) and authors:
        if len(authors) > 3:
            author_str = f"{authors[0]}, et al."
        else:
            author_str = ", ".join(authors)
    else:
        author_str = "Unknown authors"

    title = chunk.get("paper_title") or "(title unavailable)"
    journal = chunk.get("journal_or_body") or ""
    year = chunk.get("publication_year") or ""

    parts = [author_str + ".", title + "."]
    if journal:
        parts.append(f"{journal}.")
    if year:
        parts.append(f"{year}.")
    return " ".join(parts)


def _build_source_link(chunk: dict) -> str:
    """
    Build a clickable source link from chunk metadata.

    Prefers PubMed if a PMID is available; falls back to a DOI URL; else
    returns an empty string. The UI should hide the link control when
    empty rather than render a broken one.
    """
    doi_or_pmid = chunk.get("doi_or_pmid") or ""
    if not doi_or_pmid:
        return ""
    # Heuristic: PMIDs are all digits; DOIs contain a slash.
    if doi_or_pmid.isdigit():
        return f"https://pubmed.ncbi.nlm.nih.gov/{doi_or_pmid}/"
    if "/" in doi_or_pmid:
        return f"https://doi.org/{doi_or_pmid}"
    return ""


def _get_corpus_date_range_stub() -> str:
    """
    Return a human-readable corpus coverage string.

    In production, query the index's metadata record for the ingestion
    window and last-ingestion timestamp. Stubbed here with a placeholder.
    """
    return "Corpus coverage: stubbed for this example. In production, query the index metadata."
```

---

## Step 10: Archive, Log, and Emit Feedback Hooks

*The pseudocode calls this `archive_and_log(query_id, rendered, chunks_used, generation_trace)`. Persist the full trace (question, expanded queries, entities, retrieved chunk IDs, prompt version, model ID, validation result, final answer) so the answer can be re-rendered, audited, and linked to clinician feedback. Emit CloudWatch metrics. Issue a feedback token so the clinician can signal whether the answer was helpful.*

```python
def archive_and_log(
    query_id: str,
    rendered: dict,
    chunks_used: list,
    generation_trace: dict,
) -> dict:
    """
    Persist the complete trace and update the query record to DELIVERED.

    The archive is the authoritative record for compliance and iteration.
    Clinicians may audit answers days or weeks after delivery; the trace
    has to let us reconstruct what the model saw, what the retrieval
    returned, which prompt version produced the answer, and whether
    validation passed. Skip this and you are flying blind.

    Args:
        query_id:         The query UUID.
        rendered:         Rendered payload from Step 9.
        chunks_used:      The top chunks used in generation.
        generation_trace: Dict with expanded_queries, entities, prompt info,
                          model ID, and validation results.

    Returns:
        Dict with final status, S3 keys, and a feedback token for the UI.
    """
    now = datetime.datetime.now(timezone.utc).isoformat()

    # Persist the rendered payload and the retrieval trace separately.
    # The rendered payload is what the clinician saw; the trace is the
    # full provenance. Both are PHI-sensitive because the question may
    # include patient context. Bucket defaults should enforce SSE-KMS.
    rendered_key = f"answers/{query_id}/rendered.json"
    s3_client.put_object(
        Bucket=ANSWERS_BUCKET,
        Key=rendered_key,
        Body=json.dumps(rendered, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    trace_key = f"answers/{query_id}/trace.json"
    trace_payload = {
        "query_id": query_id,
        "expanded_queries": generation_trace.get("expanded_queries", []),
        "canonical_query": generation_trace.get("canonical_query", ""),
        "entities": generation_trace.get("entities", {}),
        "question_category": generation_trace.get("question_category", ""),
        "retrieved_chunk_ids": [c.get("chunk_id") for c in chunks_used],
        "prompt_version": generation_trace.get("prompt_version", "v1"),
        "generation_model": GENERATION_MODEL_ID,
        "small_model": SMALL_MODEL_ID,
        "embedding_model": EMBEDDING_MODEL_ID,
        "validation_status": generation_trace.get("validation_status", ""),
        "validation_details": generation_trace.get("validation_details", {}),
        "attempts": generation_trace.get("attempts", 1),
        "generated_at": now,
    }
    s3_client.put_object(
        Bucket=ANSWERS_BUCKET,
        Key=trace_key,
        Body=json.dumps(trace_payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )

    # Update the DynamoDB record with the final outcome.
    final_status = (
        "PENDING_CLINICIAN_REVIEW"
        if rendered.get("requires_clinician_review")
        else "DELIVERED"
    )
    queries_table = dynamodb.Table(LITERATURE_QUERIES_TABLE)
    queries_table.update_item(
        Key={"query_id": query_id},
        UpdateExpression=(
            "SET #s = :s, rendered_key = :rk, trace_key = :tk, "
            "evidence_strength = :es, delivered_at = :da, "
            "cited_chunk_ids = :cc"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": final_status,
            ":rk": rendered_key,
            ":tk": trace_key,
            ":es": rendered.get("evidence_strength", {}).get("label", ""),
            ":da": now,
            ":cc": [b["original_chunk_id"] for b in rendered.get("bibliography", [])],
        },
    )

    # Emit CloudWatch metrics. Uncomment in a real deployment.
    # cloudwatch = boto3.client("cloudwatch")
    # cloudwatch.put_metric_data(
    #     Namespace="LiteratureRAG",
    #     MetricData=[{
    #         "MetricName": "AnswersDelivered",
    #         "Dimensions": [
    #             {"Name": "EvidenceStrength",
    #              "Value": rendered.get("evidence_strength", {}).get("label", "unknown")},
    #             {"Name": "Status", "Value": final_status},
    #         ],
    #         "Value": 1.0,
    #         "Unit": "Count",
    #     }],
    # )

    feedback_token = str(uuid.uuid4())
    logger.info(
        "Query %s archived (status=%s, cited=%d)",
        query_id, final_status,
        len(rendered.get("bibliography", [])),
    )
    return {
        "status": final_status,
        "rendered_key": rendered_key,
        "trace_key": trace_key,
        "feedback_token": feedback_token,
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. Runs all ten steps sequentially for one clinical question. In production, each step becomes a Step Functions state with its own retry policy, Step 3's multi-source retrieval fans out via a parallel Map state, and the validation-failure regeneration loop is a proper state-machine loop. The sequential version below is fine for understanding the flow.

```python
def answer_clinical_question(request: dict) -> dict:
    """
    Run the full literature-search-and-synthesis pipeline for one question.

    Steps (matching the Recipe 2.7 pseudocode):
      1. Receive and classify the question (route to clarification if vague)
      2. Expand the query and extract entities
      3. Multi-source retrieval with hybrid search
      4. Re-rank candidates
      5. Tag evidence tiers
      6. Fetch full-text context for top chunks
      7-8. Generate and validate (loop up to MAX_GENERATION_ATTEMPTS)
      9. Render with citations
      10. Archive, log, and return

    Args:
        request: Dict with question, requesting_user, requesting_specialty,
                 optional patient_context.

    Returns:
        Dict with the rendered answer, status, query_id, and S3 archive keys.
    """
    start = time.time()

    # Step 1
    print("Step 1: Receiving and classifying question...")
    step1 = receive_question(request)
    query_id = step1["query_id"]
    print(f"  query_id: {query_id}")

    if step1["status"] == "CLARIFICATION_NEEDED":
        print(f"  Question needs clarification: {step1['clarification_question']}")
        return {
            "query_id": query_id,
            "status": "CLARIFICATION_NEEDED",
            "clarification_question": step1["clarification_question"],
        }

    classification = step1["classification"]
    question_category = classification.get("category", "mixed")
    print(f"  category={question_category} specificity={classification.get('specificity')}")

    # Step 2
    print("Step 2: Expanding query and extracting entities...")
    step2 = expand_query_and_extract_entities(
        question=request["question"],
        patient_context=request.get("patient_context"),
    )
    print(
        f"  {len(step2['expanded_queries'])} query variants; "
        f"{len(step2['entities']['medications'])} meds, "
        f"{len(step2['entities']['conditions'])} conditions"
    )

    # Step 3
    print("Step 3: Running hybrid retrieval...")
    candidates = multi_source_retrieval(
        expanded_queries=step2["expanded_queries"],
        canonical_query=step2["canonical_query"],
        entities=step2["entities"],
        question_category=question_category,
    )
    print(f"  {len(candidates)} candidates retrieved")

    if not candidates:
        # No retrieval hits: still archive the attempt so operations can
        # investigate gaps in coverage.
        rendered = render_answer(
            question=request["question"],
            answer_text=(
                "The retrieved literature corpus did not surface any "
                "relevant content for this question. The corpus may not "
                "cover this topic, or the question may need rephrasing. "
                "Consider escalating to a medical librarian for a manual search."
            ),
            claims=[],
            chunks_used=[],
            evidence_strength="Insufficient",
            validation_status="VALIDATED",
        )
        archive_and_log(
            query_id=query_id,
            rendered=rendered,
            chunks_used=[],
            generation_trace={
                "expanded_queries": step2["expanded_queries"],
                "canonical_query": step2["canonical_query"],
                "entities": step2["entities"],
                "question_category": question_category,
                "validation_status": "NO_RETRIEVAL",
                "attempts": 0,
            },
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "query_id": query_id,
            "status": "NO_RETRIEVAL",
            "rendered": rendered,
            "processing_time_ms": elapsed_ms,
        }

    # Step 4
    print("Step 4: Re-ranking candidates...")
    top_chunks = rerank_candidates(
        canonical_query=step2["canonical_query"],
        candidates=candidates,
        top_k=TOP_K_FOR_GENERATION,
    )
    print(f"  Top {len(top_chunks)} chunks selected")

    # Step 5
    print("Step 5: Tagging evidence tiers...")
    top_chunks = tag_evidence_tiers(top_chunks)

    # Step 6
    print("Step 6: Fetching full-text context...")
    top_chunks = fetch_full_context(top_chunks)

    # Steps 7-8: generation + validation loop
    generation_result = None
    validation_result = None
    regeneration_hint = ""
    attempts = 0

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempts = attempt
        print(f"Step 7 (attempt {attempt}): Generating synthesis...")
        generation_result = generate_synthesis(
            question=request["question"],
            patient_context=request.get("patient_context"),
            top_chunks=top_chunks,
            question_category=question_category,
            regeneration_hint=regeneration_hint,
        )

        if generation_result["status"] == "GROUNDING_REJECTED":
            regeneration_hint = (
                "The previous draft was rejected by the grounding check. "
                "Stick strictly to values explicitly present in the "
                "retrieved chunks. Do not add facts or citations beyond "
                "what the chunks provide."
            )
            continue

        if generation_result["status"] != "GENERATED":
            # Non-recoverable generation error (e.g., API failure).
            break

        print(
            f"  Generated {len(generation_result['answer_text'])} chars, "
            f"{len(generation_result['claims'])} claims, "
            f"strength={generation_result.get('evidence_strength')}"
        )

        print("Step 8: Validating claims...")
        validation_result = validate_answer(
            answer_text=generation_result["answer_text"],
            claims=generation_result["claims"],
            chunks_used=top_chunks,
            retry_count=attempt - 1,
        )
        print(f"  validation_status={validation_result['status']}")

        if validation_result["status"] == "VALIDATED":
            break
        if validation_result["status"] == "REVIEW_REQUIRED":
            break
        # RETRY_NEEDED: feed the hint into the next generation attempt.
        regeneration_hint = validation_result.get(
            "suggested_prompt_augmentation", "",
        )

    if not generation_result or generation_result["status"] != "GENERATED":
        # Escalate the failure.
        print("  Generation failed after retries; escalating to review")
        queries_table = dynamodb.Table(LITERATURE_QUERIES_TABLE)
        queries_table.update_item(
            Key={"query_id": query_id},
            UpdateExpression="SET #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "GENERATION_FAILED"},
        )
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "query_id": query_id,
            "status": "GENERATION_FAILED",
            "processing_time_ms": elapsed_ms,
        }

    # Default validation result if the loop never populated one (shouldn't happen
    # with the control flow above, but be defensive).
    if validation_result is None:
        validation_result = {"status": "REVIEW_REQUIRED", "unverified_claims": []}

    # Step 9
    print("Step 9: Rendering final answer...")
    rendered = render_answer(
        question=request["question"],
        answer_text=generation_result["answer_text"],
        claims=generation_result["claims"],
        chunks_used=top_chunks,
        evidence_strength=generation_result.get("evidence_strength", "Insufficient"),
        validation_status=validation_result["status"],
        unverified_claims=validation_result.get("unverified_claims"),
    )

    # Step 10
    print("Step 10: Archiving and logging...")
    archive_result = archive_and_log(
        query_id=query_id,
        rendered=rendered,
        chunks_used=top_chunks,
        generation_trace={
            "expanded_queries": step2["expanded_queries"],
            "canonical_query": step2["canonical_query"],
            "entities": step2["entities"],
            "question_category": question_category,
            "validation_status": validation_result["status"],
            "validation_details": {
                "unverified_count": len(validation_result.get("unverified_claims", [])),
            },
            "attempts": attempts,
            "prompt_version": "v1",
        },
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms}ms")

    return {
        "query_id": query_id,
        "status": archive_result["status"],
        "rendered": rendered,
        "rendered_key": archive_result["rendered_key"],
        "trace_key": archive_result["trace_key"],
        "feedback_token": archive_result["feedback_token"],
        "attempts": attempts,
        "processing_time_ms": elapsed_ms,
    }


# --- Example usage ---
if __name__ == "__main__":
    # All clinical content below is SYNTHETIC. Do not use real patient data
    # in development or testing. The corpus is assumed to exist in OpenSearch
    # at OPENSEARCH_ENDPOINT / OPENSEARCH_INDEX with the field schema noted
    # at the top of this file. Running this script without an indexed
    # corpus will produce NO_RETRIEVAL.

    sample_request = {
        "question": (
            "Is it safe to continue methotrexate in a patient with "
            "rheumatoid arthritis who is starting anastrozole for "
            "early-stage breast cancer?"
        ),
        "requesting_user": "USR-INTERNIST-042",
        "requesting_specialty": "internal_medicine",
        "patient_context": {
            "age": 68,
            "sex": "female",
            "active_conditions": ["rheumatoid arthritis", "breast cancer, stage I"],
            "current_medications": ["methotrexate 15 mg weekly", "folate 1 mg daily"],
        },
    }

    result = answer_clinical_question(sample_request)

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps({
        "query_id": result.get("query_id"),
        "status": result.get("status"),
        "attempts": result.get("attempts"),
        "processing_time_ms": result.get("processing_time_ms"),
    }, indent=2, default=str))

    if result.get("rendered"):
        print("\n" + "-" * 60)
        print("ANSWER (first 1500 chars):")
        print("-" * 60)
        print(result["rendered"].get("answer_markdown", "")[:1500])
        print("\n" + "-" * 60)
        print("BIBLIOGRAPHY:")
        print("-" * 60)
        for entry in result["rendered"].get("bibliography", []):
            print(f"  [{entry['display_number']}] "
                  f"({entry['evidence_tier']}) "
                  f"{entry['formatted']}")
            if entry.get("source_link"):
                print(f"      {entry['source_link']}")
```

---

## The Gap Between This and Production

Run this end-to-end against a populated OpenSearch index and you'll see the pattern: question classified, query expanded, candidates retrieved and re-ranked, tiers tagged, generation grounded, claims validated, answer archived with provenance. The distance between this and a real health-system deployment is substantial. Here's where the gap lives.

**Corpus ingestion is where the real work starts.** This example assumes the OpenSearch index already contains a chunked, embedded medical corpus. Building that corpus is often 50-70% of the total effort: fetching from NCBI E-utilities with rate limiting, parsing PMC XML (which is not clean), chunking by section with appropriate window sizes, embedding millions of chunks without blowing your Bedrock quota or budget, loading into OpenSearch with the right field mappings and refresh policies, and keeping all of it current as new papers publish. Build the ingestion pipeline as a separate Step Functions workflow with EventBridge-scheduled full and incremental rebuilds, and budget generously.

**Corpus licensing compliance.** The fastest way to build a corpus is to dump whatever you can scrape. The fastest way to get sued is to redistribute licensed content. Maintain a license registry for every source, enforce redistribution rules at retrieval time (a "view-only within the institution" source must not leak its chunk content to external endpoints), and audit quarterly. UpToDate, DynaMed, Cochrane full text, and many specialty society journals have internal-use clauses that affect API design.

**The re-ranker in this example is a stand-in.** A small-LLM re-ranker is cheap and simple, but a fine-tuned cross-encoder (MS-MARCO base, ideally fine-tuned on medical relevance pairs) is meaningfully more accurate at the top of the ranking. Host the cross-encoder on a SageMaker real-time endpoint for low latency and switch this step over before going to production. Budget ongoing work to improve the re-ranker: even a few thousand labeled relevance pairs, gathered via clinician feedback on delivered answers, can substantially improve performance on your actual query distribution.

**Step Functions orchestration and parallel retrieval.** The sequential Python loop in Step 3 is a learning artifact. Real pipelines use a Step Functions Map state to fan out per-query-variant retrievals with a tunable concurrency cap. Map state also gives you per-query retries, error isolation, and observability into which retrievals failed. Retrieval latency for a single query variant is typically 50-300 ms; sequential execution of 5 variants is 250 ms to 1.5 seconds, parallel is bounded by the slowest single query. Users notice that difference when it compounds across the pipeline.

**Embedding model lifecycle.** Your corpus is embedded with a specific embedder. If you change embedders, you have to re-embed the whole corpus. For a multi-million-chunk corpus that's a meaningful cost event and a potential outage risk. Maintain parallel indexes during embedder migrations, validate retrieval quality doesn't regress, and have a rollback plan. Pin the embedding model ID in config and verify at runtime that query-time and index-time embedders match.

**Bedrock Guardrails contextual grounding is non-optional for clinician-facing output.** The example sets `GUARDRAIL_ID = None`, which disables it. For production, configure a Guardrail with contextual grounding enabled at a strict threshold (0.85+). The grounding check compares generated output against a reference context; the retrieved chunks block is exactly that reference. Pair this with the validator in Step 8 as defense in depth: the Guardrail catches obvious hallucination and sign flips, the validator catches precise citation and numeric mismatches that the Guardrail's soft scoring sometimes misses.

**Clinician review UI is make-or-break.** The pipeline emits a markdown answer and a structured bibliography. A clinician has to see both in context, click through citations to source papers, audit claims, and form a conclusion. If review happens outside the EHR, context-switching eats the time savings that made the tool worth building. The review UI has to render inline citations as clickable links, highlight claim-to-source mappings on hover, and show the evidence-strength badge prominently. This is at least as much engineering as the AI pipeline, and it's where adoption lives or dies.

**Provenance rendering is a first-class concern.** The claims list in Step 7 and the bibliography in Step 9 are the data; the UI is the rendering. Each inline citation should link to the cited chunk's source paper and, ideally, anchor to the specific section (Methods, Results, Discussion). For claims backed by multiple chunks, the UI should let the user see all supporting sources. Where the validator flagged a MEDIUM-severity issue (e.g., low semantic overlap), the UI should communicate the lower confidence visually rather than silently hiding it. Auditability is the product, not a feature.

**Evaluation methodology is its own project.** Retrieval accuracy on benchmark sets (MedQA, PubMedQA, BioASQ) is useful for algorithm development but doesn't match the distribution of questions your clinicians actually ask. Build a continuous evaluation program: curate a gold-standard question-answer set with clinical reviewer involvement, re-run it weekly against your production pipeline, alert on regressions before they surface as clinician complaints. Budget clinical-reviewer time as an ongoing cost, not a one-time project.

**Prompt versioning from day one.** The generation prompt in Step 7 is version 1. It will go through dozens of revisions as you encounter failure modes in production. Store the prompt text in an SSM Parameter Store or AppConfig configuration with versioning, and stamp every answer in DynamoDB with the prompt version that produced it. When a regression shows up, you can replay the failing questions through the new prompt, verify the fix, and estimate the impact on the back-catalog.

**PHI minimization in prompts.** The prompts here include the clinician's patient context verbatim. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for sending less. Consider redacting patient names, MRNs, and other direct identifiers before sending to the model, then substituting back during rendering if needed. The model doesn't need the patient's actual name to synthesize evidence. This narrows the blast radius if Bedrock model-invocation logging is enabled for quality monitoring.

**Feedback loops that actually close.** Capturing a thumbs-down on an answer is easy. Using that feedback to improve the system is hard. Build a feedback triage workflow: flagged answers route to a clinical reviewer, the reviewer root-causes to a pipeline stage (retrieval miss, re-ranker mis-ordering, validator false-negative, prompt issue), and the root cause feeds into an improvement backlog. Without this, feedback collects dust and the system plateaus. The `feedback_token` emitted by Step 10 is the seed for this workflow; the rest is UI and ops work.

**Cost monitoring and runaway loops.** `MAX_GENERATION_ATTEMPTS` caps the validation retry loop at the code level, but account-level Bedrock quotas are a belt-and-suspenders. Set per-user rate limits on the API Gateway side to prevent a single misconfigured client from burning through budget in an hour. Track cost per question category and specialty in CloudWatch; the outliers will surprise you. A steady-state cost of $0.08-$0.60 per question is fine; a query accidentally looping through 10 regenerations costs $0.80-$6.00 and destroys your cost model.

**Semantic validation beats token overlap.** The validator uses substring checks and token Jaccard as fallbacks. Those catch gross mismatches but miss subtle drift (a claim that says "significant reduction" when the source says "non-significant trend"). Upgrade the validator to use embedding-based semantic similarity (cosine similarity between the claim embedding and the supporting text embedding, at a threshold tuned against labeled examples). Bedrock Titan Embeddings handle this well on clinical text. This adds latency and cost but catches a class of errors token overlap cannot.

**DynamoDB Decimal gotcha.** DynamoDB does not accept Python floats. The common trap on first deployments is passing a float directly and getting `TypeError: Float types are not supported`. Always route floats through `Decimal(str(value))`; going through `str` avoids the binary-precision issues that `Decimal(float_value)` introduces. The sample inputs in this example are integers and strings so the code runs as-is, but add Decimal conversion at every `put_item` and `update_item` call before shipping anything that persists model confidences, scores, or other floating-point fields.

**JSON parsing resilience.** The `_parse_json_response` and `_extract_trailing_json_block` helpers handle common model formatting quirks. In production, when parsing fails entirely, the correct fallback is to send the raw output back to the model with a "fix the JSON structure; preserve content" instruction. Models are usually good at self-correcting structural errors, and this saves a full regeneration cycle for recoverable formatting issues. Don't just log the parse failure and return empty.

**VPC, encryption, and audit.** This example calls APIs without explicit VPC configuration. A production Lambda runs in private subnets with interface endpoints for Bedrock Runtime, Comprehend Medical, Step Functions, KMS, Secrets Manager, CloudWatch Logs, and EventBridge; gateway endpoints for S3 and DynamoDB; and a VPC-only OpenSearch domain with fine-grained access control. All S3 buckets use SSE-KMS with customer-managed keys. DynamoDB encryption at rest uses a CMK. CloudTrail data events are enabled for every Bedrock invocation and every S3 object access. A clinical audit will eventually ask "what did the system see when it answered question X on date Y?" and you need to answer definitively.

**Testing with synthetic data.** There are no tests in this example. A production pipeline has unit tests for the JSON-path parsing, normalization, numeric extraction, and RRF fusion; integration tests against a test OpenSearch index with a small synthetic corpus for each question category; regression tests that hold known-good answers steady through prompt changes; and load tests validating throughput against realistic burst patterns (morning rounds, clinic sessions). Never use real clinician questions with real patient context in test environments. MedQA, PubMedQA, and BioASQ provide synthetic or de-identified question sets that cover most needs.

**Observability and SLOs.** Reasonable targets for a production literature-search system: 95th-percentile end-to-end latency under 30 seconds, retrieval recall at 100 above 0.80 on benchmark questions, validation pass rate above 0.90 on first generation, fraction of answers routed to review below 10%, and citation fidelity (every rendered citation actually present in the retrieved set) at 1.0. Publish these as CloudWatch SLOs. Alert on drift. Without these, problems surface as clinician complaints rather than dashboard anomalies, and by then the trust is already damaged.

**Model-ID lifecycle.** The Bedrock model IDs in this example will be replaced over time as newer versions launch. Store model IDs in configuration (SSM Parameter Store or AppConfig), not in code. When you upgrade, run your regression suite before flipping production. Skipping this is how teams discover at 2 AM that the new model version interprets a critical prompt instruction differently. Cross-region inference profile IDs (prefixed `us.` or `eu.`) are increasingly required in many regions, not optional; plan for that.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.7: Literature Search and Evidence Synthesis](chapter02.07-literature-search-evidence-synthesis) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
