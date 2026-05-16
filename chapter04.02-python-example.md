# Recipe 4.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.2. It shows one way you could translate those patient-education-content-matching concepts into working Python using Amazon Bedrock for embeddings, Amazon OpenSearch Service for vector search, Amazon DynamoDB for catalog and patient metadata, S3 for content bodies, and Amazon Kinesis for engagement events. It is not production-ready. There is no real CMS integration, no SMART-on-FHIR feed for the patient profile, no Step Functions ingestion orchestration, no learned re-ranker (we use a hand-tuned scoring function), no clinician approval workflow, no fairness dashboard. Think of it as the sketchpad version: useful for understanding the shape of a content recommender, not something you'd wire into a portal on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the six pseudocode steps from the main recipe: ingest content and build the searchable index, build the patient query context, apply hard filters and run candidate generation, re-rank with personalization signals, log the recommendation and return, capture engagement and update aggregates. All sample content, patients, and engagement signals are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 opensearch-py requests-aws4auth textstat
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` on the specific embedding model ARN (e.g., `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0`)
- `es:ESHttpPost`, `es:ESHttpGet`, `es:ESHttpPut` on the OpenSearch domain (or `aoss:APIAccessAll` if using OpenSearch Serverless)
- `s3:GetObject`, `s3:PutObject` on the content bucket
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the catalog, patient profile, recommendation log, engagement events, and engagement summary tables
- `kinesis:PutRecord` on the engagement stream
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console. This pipeline uses one model: an embedding model that runs at content-ingestion time and at query time. The embedding model used at query time MUST match the one used at index time, or vector similarity collapses. Pin the model ID in config and verify at runtime if you're paranoid (and you should be).

A few things worth knowing upfront:

- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **The OpenSearch index used here is created on first run if it doesn't exist.** In production, the index is created by infrastructure-as-code (CDK/Terraform/CloudFormation) with proper field mappings, refresh intervals, and a documented schema versioning policy. Don't let application code own index creation in production.
- **All content, patients, and engagement events in the example are synthetic.** Do not treat any specific content_id, title, or patient_id as real. A production system ingests from a real CMS and joins to real patient profiles under BAA.
- **`textstat` is used for the reading-level computation.** It's a small pure-Python library that implements Flesch-Kincaid and friends. In production, the reading-level computation can be a Lambda that runs once per content version; pinning the algorithm and version matters more than which library you pick.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, OpenSearch index settings, scoring weights, and the eligibility-rule constants are the knobs you'll change between environments.

```python
import json
import logging
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Reading-level scoring. textstat ships Flesch-Kincaid, SMOG, Dale-Chall,
# and a few others. We use Flesch-Kincaid Grade Level here because it
# returns an integer-ish grade level that's easy to threshold against
# patient reading-level estimates. SMOG is also reasonable; pick one
# and document the choice.
import textstat

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log the patient's clinical context,
# the recommendation_id joined to a patient_id, or anything that could
# identify a specific patient's content engagement. Recommendation logs
# are PHI by definition (patient_id joined to clinical content like
# "newly diagnosed diabetes" reveals the diagnosis).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Bedrock, OpenSearch, DynamoDB,
# and Kinesis during burst traffic (a content batch import, or a portal
# page that calls the recommender for every logged-in user at 8 AM).
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Titan Text Embeddings v2 returns 1024-dimensional vectors by default.
# CRITICAL: this must match what indexed the corpus. If you switch
# embedders, you must re-index every piece of content.
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024

# --- DynamoDB Table Names ---
# Five tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. content-metadata:   catalog metadata (content_id PK)
#   2. patient-profile:    patient demographics, language, prefs (patient_id PK)
#   3. recommendation-log: one row per recommendation served (recommendation_id PK)
#   4. engagement-events:  raw engagement events (event_id PK)
#   5. engagement-summary: per-patient running aggregates (patient_id PK)
CONTENT_TABLE = "content-metadata"
PATIENT_TABLE = "patient-profile"
RECOMMENDATION_LOG_TABLE = "recommendation-log"
ENGAGEMENT_EVENTS_TABLE = "engagement-events"
ENGAGEMENT_SUMMARY_TABLE = "engagement-summary"

# --- S3 ---
# Content bodies live here. Versioning enabled so updates leave a paper trail.
# Customer-managed KMS key for encryption at rest.
CONTENT_BUCKET = "your-patient-education-content-bucket"

# Customer-managed KMS key ARN for the content bucket. Setting
# ServerSideEncryption="aws:kms" without SSEKMSKeyId falls back to the
# AWS-managed default key (alias/aws/s3), which is fine for non-PHI data
# but does not meet the customer-managed-keys posture this recipe assumes
# for PHI-adjacent stores. Pass the explicit key ARN on every put.
CONTENT_BUCKET_CMK_ARN = "arn:aws:kms:us-east-1:000000000000:key/REPLACE-WITH-YOUR-KEY-ID"

# --- OpenSearch Configuration ---
# The k-NN index holds embeddings + duplicate metadata so a single
# query can filter and search.
OPENSEARCH_ENDPOINT = "your-opensearch-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_INDEX = "patient-education"
OPENSEARCH_REGION = "us-east-1"

# --- Kinesis ---
# Same engagement-event stream pattern as Recipe 4.1, with new event types.
ENGAGEMENT_STREAM_NAME = "engagement-stream"

# --- Pipeline Tuning ---
# Initial vector-search candidate set. Larger = more recall, more re-ranker work.
INITIAL_CANDIDATE_LIMIT = 50

# After re-ranking, how many to surface to the patient. Portal slots
# typically show 3-5 items.
TOP_N_TO_RETURN = 5

# --- Re-ranker Weights ---
# Hand-tuned weights for the v1 re-ranker. Each multiplier adjusts the
# base semantic-similarity score. In production, replace this with a
# learning-to-rank model (XGBoost, LightGBM lambdarank) once you have
# enough labeled engagement data.
WEIGHT_FORMAT_PREFERENCE_BOOST = 1.25  # patient prefers this format
WEIGHT_RECENT_TOPIC_BOOST = 1.15       # related to recently-engaged topic
PENALTY_READING_LEVEL_GAP_2_TO_4 = 0.5 # 2-4 grades above patient level
PENALTY_READING_LEVEL_GAP_OVER_4 = 0.2 # more than 4 grades above

# Default reading-level estimate when the patient has none on file.
# Skews to a sensible "not too hard" default rather than over-shooting.
DEFAULT_PATIENT_READING_LEVEL = 8

# CloudWatch namespace for engagement metrics. Slice by language and
# reading-level cohort in the dashboard to catch subgroup issues early.
METRIC_NAMESPACE = "PatientEducationRecommender"

# Model version stamp. Increment when you change scoring or candidate logic;
# stored on every recommendation log row so back-catalog analysis can
# segment by version.
MODEL_VERSION = "rerank-v0.4"
```

---

## Shared Helpers

A handful of utilities used across steps. Pulled together here so each step's logic stays focused.

```python
def _get_opensearch_client() -> OpenSearch:
    """
    Build (or reuse) an IAM-authenticated OpenSearch client.

    The client is cached at module scope after first construction. In a
    Lambda warm container, the SigV4 credential resolution and TLS
    handshake happen once per process rather than once per invocation,
    which matters when the recipe targets sub-200 ms p95 inference latency.

    The Lambda execution role in production should have least-privilege
    OpenSearch access scoped to the specific domain ARN and index name.
    """
    global _opensearch_client
    if _opensearch_client is not None:
        return _opensearch_client

    session = boto3.Session()
    credentials = session.get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        OPENSEARCH_REGION,
        "es",  # use "aoss" if targeting OpenSearch Serverless
        session_token=credentials.token,
    )
    _opensearch_client = OpenSearch(
        hosts=[{"host": OPENSEARCH_ENDPOINT, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        timeout=30,
    )
    return _opensearch_client


# Lazy module-level cache. Populated on first _get_opensearch_client() call.
_opensearch_client: OpenSearch | None = None


def _embed_text(text: str) -> list:
    """
    Embed a string using the configured embedding model.

    CRITICAL: this MUST match whatever embedder indexed the corpus.
    Mismatched embedders produce vectors that don't live in the same
    space, retrieval quality silently collapses, and you don't get an
    error. Pin the model ID in config and never change it without a
    full re-index.

    This helper is hard-coded to Titan v2's request/response shape.
    Other Bedrock embedders (Cohere Embed, etc.) use a different schema:
    if you swap models, update body construction and parsing here.
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


def _ensure_index_exists(client: OpenSearch) -> None:
    """
    Create the OpenSearch index with k-NN-enabled mappings if missing.

    Production note: index creation belongs in infrastructure-as-code
    (CDK/Terraform), not application code. This helper exists so the
    example runs from a fresh environment without manual setup.
    """
    if client.indices.exists(index=OPENSEARCH_INDEX):
        return

    index_body = {
        "settings": {
            "index": {
                "knn": True,
                # ef_search trades latency for recall. 100 is a fine starting
                # point for a small catalog (under 100k items).
                "knn.algo_param.ef_search": 100,
                "number_of_shards": 1,  # tiny catalog; one shard is plenty
                "number_of_replicas": 1,
            }
        },
        "mappings": {
            "properties": {
                "content_id":    {"type": "keyword"},
                "title":         {"type": "text"},
                "language":      {"type": "keyword"},
                "reading_level": {"type": "integer"},
                "topic_tags":    {"type": "keyword"},
                "content_type":  {"type": "keyword"},
                "audience":      {"type": "keyword"},
                "status":        {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIMENSION,
                    # cosine similarity is the right choice for semantic
                    # text embeddings; L2 is also reasonable but cosine
                    # is more forgiving of magnitude variation.
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
            }
        },
    }
    client.indices.create(index=OPENSEARCH_INDEX, body=index_body)
    logger.info("Created OpenSearch index %s", OPENSEARCH_INDEX)


def _strip_html_basic(html_text: str) -> str:
    """
    Very rough HTML-to-text conversion for the example.

    In production, use beautifulsoup4 or trafilatura. The reading-level
    computation is sensitive to structural noise (nav menus, footers,
    HTML entities), and a real ingestion pipeline cleans aggressively.
    """
    import re
    no_tags = re.sub(r"<[^>]+>", " ", html_text or "")
    no_entities = re.sub(r"&[a-z]+;", " ", no_tags)
    return re.sub(r"\s+", " ", no_entities).strip()
```

---

## Step 1: Ingest Content and Build the Searchable Index

*The pseudocode calls this `on_content_published(content_event)`. When a piece of content lands in the CMS or gets updated, extract the textual portion, compute the reading-grade level, generate an embedding from the title and abstract, persist the body to S3, write metadata to DynamoDB, and index the embedding plus duplicate metadata into OpenSearch. This is the offline preparation step. Everything the inference path does later depends on this step having done its job.*

```python
def on_content_published(content_event: dict) -> dict:
    """
    Process a newly published or updated content item.

    Args:
        content_event: Dict representing the content payload. Expected keys:
            - id:             unique content identifier (e.g., "edu-diabetes-newly-diagnosed-en-v3")
            - version:        version string (so updates are tracked)
            - title:          display title
            - body:           raw body (HTML, plain text, or transcript)
            - language:       BCP-47 language code (e.g., "en", "es", "vi")
            - topic_tags:     list of taxonomy tags (SNOMED-CT, ICD-10, or in-house)
            - content_type:   "article" | "video" | "pdf" | "module" | "audio"
            - audience:       "adult" | "pediatric" | "caregiver"
            - status:         "active" | "draft" | "deprecated" | "retired"
            - format:         file extension for S3 storage ("html", "pdf", "mp4")

    Returns:
        Dict with the computed reading_level and the s3 key, useful for
        downstream notifications.
    """
    content_id = content_event["id"]
    version = content_event["version"]

    # ---- Step 1a: Extract clean text from the body ----
    # The reading-level computation is sensitive to HTML noise. Strip tags,
    # entities, and collapse whitespace. For PDFs and videos in production,
    # you'd run Textract on the PDF or Transcribe on the video first; here
    # we assume the CMS event has already extracted the relevant text.
    cleaned_text = _strip_html_basic(content_event.get("body", ""))
    # The abstract is what feeds the embedding. Title + first ~500 chars
    # is the right size: enough topical signal without diluting the vector
    # with body-text noise.
    abstract = cleaned_text[:500]
    title = content_event["title"]

    # ---- Step 1b: Compute reading level ----
    # textstat returns a float; round to int for clean threshold logic.
    # Some content (videos with no transcript text, very short items) will
    # produce nonsense reading levels; clamp to a sensible range.
    if cleaned_text and len(cleaned_text.split()) >= 30:
        try:
            grade_level = int(round(textstat.flesch_kincaid_grade(cleaned_text)))
            grade_level = max(1, min(grade_level, 18))  # clamp to 1st-grad school year ceiling
        except Exception as exc:
            logger.warning("Reading-level computation failed for %s: %s", content_id, exc)
            grade_level = 8  # safe default
    else:
        # Too little text to score reliably (typical for video items where
        # the transcript wasn't included in the event). Mark as None so
        # the re-ranker doesn't penalize it incorrectly.
        grade_level = None

    # ---- Step 1c: Generate the embedding ----
    # title + "\n\n" + abstract: the title is short but high-signal, the
    # abstract gives semantic depth. Sending the full body would dilute
    # the embedding with section headers, navigation text, and other noise.
    embedding_input = f"{title}\n\n{abstract}".strip()
    if not embedding_input:
        # Edge case: no title and no body. Skip rather than emit a junk vector.
        logger.warning("Content %s has no text to embed; skipping index", content_id)
        return {"content_id": content_id, "indexed": False}

    embedding = _embed_text(embedding_input)

    # ---- Step 1d: Persist body to S3 ----
    # Versioned key path so updates leave a paper trail. The bucket should
    # have versioning enabled and a customer-managed KMS key for encryption.
    s3_key = f"content/{content_id}/{version}/body.{content_event.get('format', 'html')}"
    s3_client.put_object(
        Bucket=CONTENT_BUCKET,
        Key=s3_key,
        Body=content_event.get("body", "").encode("utf-8"),
        ContentType=_mime_for_format(content_event.get("format", "html")),
        # Server-side encryption is enforced via bucket policy in production;
        # passing it explicitly here documents the intent. Pair "aws:kms"
        # with an explicit SSEKMSKeyId so the put uses the customer-managed
        # key, not the AWS-managed default (alias/aws/s3).
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=CONTENT_BUCKET_CMK_ARN,
    )

    # ---- Step 1e: Persist metadata to DynamoDB ----
    # The catalog table is the system of record for content metadata. The
    # OpenSearch index duplicates the filterable fields for filter-and-search
    # in one query, but DynamoDB owns the truth.
    content_table = dynamodb.Table(CONTENT_TABLE)
    item = {
        "content_id":    content_id,
        "version":       version,
        "title":         title,
        "language":      content_event["language"],
        "topic_tags":    content_event.get("topic_tags", []),
        "content_type":  content_event["content_type"],
        "audience":      content_event.get("audience", "adult"),
        "status":        content_event.get("status", "active"),
        "s3_key":        s3_key,
        "indexed_at":    datetime.datetime.now(timezone.utc).isoformat(),
    }
    if grade_level is not None:
        item["reading_level"] = grade_level
    content_table.put_item(Item=item)

    # ---- Step 1f: Index embedding + duplicated metadata into OpenSearch ----
    client = _get_opensearch_client()
    _ensure_index_exists(client)

    os_doc = {
        "content_id":    content_id,
        "title":         title,
        "language":      content_event["language"],
        "topic_tags":    content_event.get("topic_tags", []),
        "content_type":  content_event["content_type"],
        "audience":      content_event.get("audience", "adult"),
        "status":        content_event.get("status", "active"),
        "embedding":     embedding,
    }
    if grade_level is not None:
        os_doc["reading_level"] = grade_level

    client.index(
        index=OPENSEARCH_INDEX,
        id=content_id,           # use content_id as the doc id for idempotent upserts
        body=os_doc,
        refresh=False,           # don't force a refresh; near-real-time is fine for ingestion
    )

    logger.info(
        "Indexed content %s (version=%s, grade=%s, lang=%s)",
        content_id, version, grade_level, content_event["language"],
    )
    return {
        "content_id": content_id,
        "indexed": True,
        "reading_level": grade_level,
        "s3_key": s3_key,
    }


def _mime_for_format(fmt: str) -> str:
    """Map a format hint to a Content-Type header value."""
    return {
        "html": "text/html",
        "pdf":  "application/pdf",
        "mp4":  "video/mp4",
        "txt":  "text/plain",
        "json": "application/json",
    }.get(fmt, "application/octet-stream")
```

---

## Step 2: Build the Patient Query Context

*The pseudocode calls this `build_patient_context(patient_id)`. When a recommendation request fires (portal page load, post-visit summary attachment, reminder email assembly), the recommender first assembles what it knows about the patient. Conditions, language, reading-level estimate, recent engagement aggregates, format preferences. This is mostly DynamoDB joins; it's the unglamorous step that makes the rest of the pipeline patient-aware instead of one-size-fits-all.*

```python
def build_patient_context(patient_id: str) -> dict | None:
    """
    Assemble everything the recommender needs to know about this patient.

    The patient profile is the system of record for language preference,
    consent flags, and recently-active conditions. The engagement summary
    is the rolling aggregate of clicks, completions, and ratings used by
    the re-ranker. They live in separate tables because they have very
    different update patterns: profile changes infrequently, engagement
    summary updates many times per day per active patient.

    Returns None if the patient profile doesn't exist (caller should
    decline to recommend rather than fall back to defaults; an unknown
    patient indicates an upstream join error worth logging).
    """
    patient_table = dynamodb.Table(PATIENT_TABLE)
    response = patient_table.get_item(Key={"patient_id": patient_id})
    profile = response.get("Item")
    if profile is None:
        logger.warning("No patient profile found for %s; declining to recommend", patient_id)
        return None

    # Pull active clinical context. In production, this is sourced from a
    # feature store populated upstream from the EHR (FHIR Condition resources
    # filtered to active status, recent procedures, current medications).
    # The example assumes those have been denormalized into the profile;
    # a real pipeline reads from a feature store or hits the EHR directly.
    active_conditions = profile.get("active_conditions", []) or []
    recent_procedures = profile.get("recent_procedures", []) or []
    active_medications = profile.get("active_medications", []) or []

    # Build the free-text "intent" that drives the semantic search. We
    # concatenate human-readable descriptions of the structured codes
    # because the embedding model was trained on natural-language text,
    # not on raw SNOMED codes. Codes alone embed poorly; descriptive
    # text embeds well.
    intent_parts = []
    if active_conditions:
        intent_parts.append("conditions: " + ", ".join(c.get("description", c.get("code", ""))
                                                       for c in active_conditions))
    if recent_procedures:
        intent_parts.append("recent procedures: " + ", ".join(p.get("description", "")
                                                              for p in recent_procedures))
    if active_medications:
        intent_parts.append("medications: " + ", ".join(m.get("description", "")
                                                        for m in active_medications))
    intent_text = "; ".join(intent_parts) if intent_parts else "general health information"

    # Pull engagement summary. Missing means cold-start patient: the
    # re-ranker will fall back to candidate-generation order.
    engagement_table = dynamodb.Table(ENGAGEMENT_SUMMARY_TABLE)
    eng_response = engagement_table.get_item(Key={"patient_id": patient_id})
    engagement_summary = eng_response.get("Item") or {}

    # Aggregate recent topic tags from the profile: tags from the patient's
    # active conditions, plus any topics the engagement summary tracked.
    # These boost retrieval precision via the OpenSearch should-clause.
    topic_tags_pref = []
    for c in active_conditions:
        topic_tags_pref.extend(c.get("topic_tags", []))
    topic_tags_pref.extend(engagement_summary.get("last_topics_engaged", []) or [])
    # Deduplicate while preserving order (Python 3.7+ dicts are ordered)
    topic_tags_pref = list(dict.fromkeys(topic_tags_pref))

    return {
        "patient_id":         patient_id,
        "language":           profile.get("language", "en"),
        "reading_level_est":  profile.get("reading_level"),  # may be None
        "intent_text":        intent_text,
        "engagement_summary": engagement_summary,
        "topic_tags_pref":    topic_tags_pref,
        "format_preference":  _highest_engagement_format(engagement_summary),
        # Audience constraints: pediatric, adult, etc. Inferred from profile.
        "audience":           _infer_audience(profile),
    }


def _highest_engagement_format(engagement_summary: dict) -> str | None:
    """
    Determine the patient's most-engaged content format.

    Uses completion counts (a stronger signal than clicks) when available;
    falls back to clicks. Returns None for cold-start patients with no data.
    """
    completions = engagement_summary.get("format_completions") or {}
    if completions:
        # max() with key= returns the format with the highest count
        return max(completions, key=lambda k: completions[k])
    clicks = engagement_summary.get("format_clicks") or {}
    if clicks:
        return max(clicks, key=lambda k: clicks[k])
    return None


def _infer_audience(profile: dict) -> str:
    """
    Pick the audience filter for this patient.

    Ultra-simple here. Production would also consider things like a parent
    accessing on behalf of a child (caregiver audience), patients with
    cognitive support needs, etc.
    """
    age = profile.get("age")
    if isinstance(age, (int, float)) and age < 18:
        return "pediatric"
    return "adult"
```

---

## Step 3: Apply Hard Filters and Run Candidate Generation

*The pseudocode calls this `generate_candidates(patient_context, top_k=50)`. This is where Layers 1 and 2 of the architecture meet. Hard filters (language, status, audience) reduce the catalog to the eligible subset; semantic similarity plus tag overlap reduce that subset to a few dozen plausibly relevant candidates. OpenSearch handles both in a single query: filter clauses for the eligibility rules, a k-NN clause for the embedding similarity, and a should-match clause where tag overlap acts as a tiebreaker.*

```python
def generate_candidates(
    patient_context: dict,
    top_k: int = INITIAL_CANDIDATE_LIMIT,
) -> list:
    """
    Combine eligibility filtering and semantic search in one OpenSearch query.

    The filter clauses are correctness rules, not optimization decisions:
      - language: never show English-only content to a Spanish-preference patient
      - status:   never show deprecated/draft content
      - audience: never show pediatric content to adults and vice versa
    These are HARD constraints. The model should never have to reason about
    them; doing so creates ways for the wrong content to slip through.

    The k-NN clause is the candidate generator. Cosine similarity over the
    title+abstract embedding gives us topical relevance even when exact
    tag matches aren't present.

    The should clause boosts candidates that share topic tags with what the
    patient has engaged with recently. This is a soft signal; missing tags
    don't disqualify a candidate, they just don't get the boost.

    Returns a list of dicts (one per candidate) with score, metadata, and
    the explanation features that flow downstream.
    """
    client = _get_opensearch_client()

    # Embed the patient's intent text using the SAME model that indexed
    # the catalog. If you ever swap embedders, both sides flip together
    # or retrieval quality silently collapses.
    query_embedding = _embed_text(patient_context["intent_text"])

    # Build the OpenSearch query.
    # Note: combining a `bool.filter` with a `bool.must` knn clause applies
    # the filter as a post-filter (after kNN candidate generation). For
    # restrictive filters on large indexes this can return fewer than k
    # results; for our small catalog and broad language/status filters
    # it's fine. If you need pre-filtering for very restrictive filter
    # combinations, use OpenSearch's efficient-filter syntax inside the
    # knn clause instead.
    query = {
        "size": top_k,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"language": patient_context["language"]}},
                    {"term": {"status":   "active"}},
                    {"term": {"audience": patient_context["audience"]}},
                ],
                "must": [
                    {
                        "knn": {
                            "embedding": {
                                "vector": query_embedding,
                                "k": top_k,
                            }
                        }
                    }
                ],
                "should": [
                    # Tag overlap as a tiebreaker. Empty list is safe; the
                    # `terms` query just contributes nothing to the score.
                    {"terms": {"topic_tags": patient_context["topic_tags_pref"] or []}}
                ],
            }
        },
        # Don't ship the full embedding back to the caller; it's large and
        # we already used it for the similarity computation.
        "_source": {"excludes": ["embedding"]},
    }

    try:
        response = client.search(index=OPENSEARCH_INDEX, body=query)
    except Exception as exc:
        # Retrieval failure should not crash the pipeline. In production,
        # emit a metric and return an empty candidate set; the caller can
        # decide whether to surface a fallback (e.g., top-popular for the
        # patient's language cohort).
        logger.exception("Candidate generation search failed: %s", exc)
        return []

    hits = response.get("hits", {}).get("hits", [])
    candidates = []
    for h in hits:
        source = h["_source"]
        candidates.append({
            "content_id":    source["content_id"],
            "title":         source.get("title", ""),
            "language":      source.get("language"),
            "reading_level": source.get("reading_level"),  # may be None for video
            "topic_tags":    source.get("topic_tags", []) or [],
            "content_type":  source.get("content_type"),
            "audience":      source.get("audience"),
            "similarity_score": float(h["_score"]),
        })

    logger.info(
        "Generated %d candidates for patient %s (language=%s, audience=%s)",
        len(candidates),
        patient_context["patient_id"],
        patient_context["language"],
        patient_context["audience"],
    )
    return candidates
```

---

## Step 4: Re-Rank with Personalization Signals

*The pseudocode calls this `rerank(candidates, patient_context, top_n=5)`. The candidate set is relevant in aggregate; the order matters. The re-ranker scores each candidate against patient-specific features (does the patient prefer videos? is this content's reading level a good fit? have they engaged with this topic family recently?). For v1, a hand-tuned weighted scoring function is plenty. Move to LambdaMART or XGBoost-Ranker once you have a meaningful labeled dataset.*

```python
def rerank(
    candidates: list,
    patient_context: dict,
    top_n: int = TOP_N_TO_RETURN,
) -> list:
    """
    Re-order candidates using patient-specific signals.

    The scoring function below is intentionally simple. Multiplicative
    weights apply to the base semantic similarity score; reading-level
    fit penalizes content that's too hard for the patient; format
    preference and recent topic engagement give modest boosts. Each
    boost or penalty is annotated in an explanation list so the UI
    and audit log can render natural-language reasons.

    For a learned ranker, the inputs are the same; the difference is
    that XGBoost-Ranker (or LambdaMART) learns the weights from
    historical (patient, candidate, observed-engagement) triples
    rather than having a human pick them.
    """
    if not candidates:
        return []

    # Explicit None check rather than `or DEFAULT_PATIENT_READING_LEVEL` so
    # a legitimate Decimal(0) or 0 from the profile pipeline is preserved
    # instead of silently swapped for the default.
    profile_reading_level = patient_context.get("reading_level_est")
    patient_reading_level = (
        DEFAULT_PATIENT_READING_LEVEL if profile_reading_level is None
        else profile_reading_level
    )
    preferred_format = patient_context.get("format_preference")
    recent_topics = set(
        (patient_context.get("engagement_summary") or {}).get("last_topics_engaged", []) or []
    )

    scored = []
    for c in candidates:
        # Start with the semantic similarity score from candidate generation.
        # OpenSearch's k-NN _score for cosine is already on a similar scale
        # across queries, so this is a sensible base.
        score = c["similarity_score"]
        explanation_parts = [f"matches '{patient_context['intent_text'][:60]}'"]

        # ---- Reading-level fit ----
        # Penalize content significantly above the patient's level. A
        # modest stretch (1 grade) is fine; college-level for a 6th
        # grader is a poor fit.
        candidate_level = c.get("reading_level")
        if candidate_level is not None:
            gap = candidate_level - patient_reading_level
            if gap > 4:
                score *= PENALTY_READING_LEVEL_GAP_OVER_4
                explanation_parts.append(
                    f"reading level much higher than patient ({candidate_level} vs {patient_reading_level})"
                )
            elif gap > 2:
                score *= PENALTY_READING_LEVEL_GAP_2_TO_4
                explanation_parts.append(
                    f"reading level somewhat higher than patient ({candidate_level} vs {patient_reading_level})"
                )
            elif gap <= 0:
                explanation_parts.append(f"fits patient reading level ({candidate_level})")
        # else: no reading level (typical for video). Don't penalize; let
        # the format-preference signal dominate for video items.

        # ---- Format preference ----
        # Bump items in the patient's preferred format. The format
        # preference comes from prior engagement (Step 6 updates it).
        if preferred_format and c.get("content_type") == preferred_format:
            score *= WEIGHT_FORMAT_PREFERENCE_BOOST
            explanation_parts.append(f"matches preferred format ({preferred_format})")

        # ---- Recent topic boost ----
        # If this candidate shares any tag with what the patient has
        # been engaging with lately, modest boost.
        candidate_tags = set(c.get("topic_tags", []))
        topic_overlap = candidate_tags & recent_topics
        if topic_overlap:
            score *= WEIGHT_RECENT_TOPIC_BOOST
            explanation_parts.append(
                f"related to recent activity ({', '.join(sorted(topic_overlap))})"
            )

        # Clamp the cumulative score to a reasonable range so multiplicative
        # factors can't compound into runaway values or vanish entirely.
        # Helps when a clinical reviewer asks "why was this recommended" and
        # you need to explain the math without hand-waving.
        score = max(0.05, min(2.0, score))

        scored.append({
            **c,
            "score": score,
            "explanation": "; ".join(explanation_parts),
        })

    # Sort descending by score. In production, add a Maximal Marginal
    # Relevance pass here to demote near-duplicate candidates so the
    # patient doesn't see three near-identical articles.
    scored.sort(key=lambda x: x["score"], reverse=True)
    top = scored[:top_n]

    logger.info(
        "Re-ranked %d candidates -> top %d for patient %s",
        len(candidates), len(top), patient_context["patient_id"],
    )
    return top
```

---

## Step 5: Log the Recommendation and Return

*The pseudocode calls this `log_and_return(patient_id, recommendations)`. Before returning to the caller, persist a recommendation log entry. This is the join point that makes engagement attribution possible later. Each recommendation gets a unique ID; impressions, clicks, and completions reference that ID. Skip this step and you cannot evaluate the model.*

```python
def log_and_return(
    patient_context: dict,
    recommendations: list,
) -> dict:
    """
    Persist the recommendation, emit impression events, return to caller.

    Three things happen here:
      1. A recommendation_log row is written with the items, scores, model
         version, and a feature snapshot. This is the audit record.
      2. One impression event per item is emitted to Kinesis. Impression
         is a separate event from click; we want both signals so we can
         compute click-through rate later.
      3. The response payload is built for the caller (portal, email
         composer, AVS generator). Includes explanation strings.
    """
    recommendation_id = str(uuid.uuid4())
    now_iso = datetime.datetime.now(timezone.utc).isoformat()
    patient_id = patient_context["patient_id"]

    # Persist the recommendation log row. DynamoDB Decimal is required for
    # numeric fields; route every float through Decimal(str(...)) to avoid
    # the precision issues with Decimal(float).
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    rec_table.put_item(Item={
        "recommendation_id": recommendation_id,
        "patient_id":        patient_id,
        "timestamp":         now_iso,
        "model_version":     MODEL_VERSION,
        "items": [
            {
                "content_id": r["content_id"],
                "score":      Decimal(str(round(r["score"], 4))),
                "rank":       i + 1,
            }
            for i, r in enumerate(recommendations)
        ],
        # Feature snapshot lets future analysis ask "what did the model
        # see when it made this decision?" without re-running the pipeline.
        # This row joined to a patient_id is PHI; store accordingly.
        # Minimization rule: persist only the cohort-level features actually
        # consumed downstream (CloudWatch metric dimensions, ranker training
        # features). Do NOT persist the verbatim intent_text or the
        # structured condition / procedure / medication codes used to build
        # it; that turns this log into a free-text clinical narrative
        # joined to a patient_id and dramatically expands the disclosure
        # surface. If you need reconstructable patient context for incident
        # investigation, log it through a separate, append-only audit
        # channel with stricter access controls and a shorter retention.
        "feature_snapshot": {
            "language":           patient_context["language"],
            "reading_level_est":  patient_context.get("reading_level_est") or "unknown",
            "audience":           patient_context["audience"],
            "format_preference":  patient_context.get("format_preference") or "unknown",
            "topic_tags_pref":    patient_context.get("topic_tags_pref", []),
        },
    })

    # Emit impression events. One per item shown. The recommender does NOT
    # wait for these to commit; if Kinesis is unavailable we'd rather miss
    # an impression event than block the patient-facing response. In a
    # fault-tolerant design, you'd buffer to a local queue and retry async.
    for rank, r in enumerate(recommendations, start=1):
        try:
            kinesis_client.put_record(
                StreamName=ENGAGEMENT_STREAM_NAME,
                # Partition key on patient_id keeps a single patient's events
                # ordered within a shard, which makes downstream attribution
                # logic simpler (no out-of-order impression-after-click).
                PartitionKey=patient_id,
                Data=json.dumps({
                    "event_type":        "content_impression",
                    "recommendation_id": recommendation_id,
                    "content_id":        r["content_id"],
                    "patient_id":        patient_id,
                    "timestamp":         now_iso,
                    "rank":              rank,
                }).encode("utf-8"),
            )
        except Exception as exc:
            # Log and continue; impression-event failures should not block
            # the recommendation. Production: emit a metric so this is
            # visible on a dashboard.
            logger.warning(
                "Impression event publish failed for content_id=%s: %s",
                r["content_id"], exc,
            )

    # Build the caller-facing response. Keep the payload trim; the UI does
    # the rendering, the recommender ships data + explanations.
    return {
        "recommendation_id": recommendation_id,
        "patient_id":        patient_id,
        "timestamp":         now_iso,
        "model_version":     MODEL_VERSION,
        "items": [
            {
                "content_id":    r["content_id"],
                "title":         r["title"],
                "score":         round(r["score"], 4),
                "reading_level": r.get("reading_level"),
                "language":      r["language"],
                "content_type":  r["content_type"],
                "explanation":   r["explanation"],
            }
            for r in recommendations
        ],
    }
```

---

## Step 6: Capture Engagement and Update Aggregates

*The pseudocode calls this `process_engagement_event(event)`. A separate Lambda consumes the engagement stream, joins each event back to the recommendation log, and updates two things: the patient's running engagement summary (used by the re-ranker) and the per-event record (used for offline ranker training). Underinvest here and the model stops learning.*

```python
def process_engagement_event(event: dict) -> None:
    """
    Update the engagement summary and persist the raw event.

    Expected event shape (decoded from Kinesis):
      {
        "event_type":        "content_impression" | "content_click" |
                             "content_completion" | "content_rating",
        "recommendation_id": "f1d8c2e0-...",
        "content_id":        "edu-...",
        "patient_id":        "pat-...",
        "timestamp":         "2026-05-04T10:32:15Z",
        "rank":              1,
        "rating":            optional integer 1-5 for content_rating events
      }

    Notes on what this function does NOT do:
      - It does not retrain the re-ranker. Training is a periodic offline
        job (weekly/monthly) that reads from engagement-events.
      - It does not update the recommendation_log. That's an immutable
        decision record.
      - It does not enforce dedup. Kinesis at-least-once means duplicates
        happen; defend against double-counting via event_id uniqueness.
    """
    rec_id = event.get("recommendation_id")
    event_type = event.get("event_type")
    content_id = event.get("content_id")
    patient_id = event.get("patient_id")

    if not (rec_id and event_type and content_id and patient_id):
        logger.warning("Malformed engagement event; dropping: %s", event)
        return

    # ---- Verify the recommendation exists ----
    # Look up the original recommendation. If we can't find it, log and skip;
    # this protects against malformed client events with bad IDs and against
    # events that arrive before the log row is committed (rare but possible
    # if the client posted an impression event from a cached page).
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    rec_response = rec_table.get_item(Key={"recommendation_id": rec_id})
    rec_record = rec_response.get("Item")
    if rec_record is None:
        logger.warning("Engagement event references unknown recommendation_id=%s", rec_id)
        return

    # Confirm this content was actually in the recommendation. Defends
    # against clients that mis-tag events. Drop mismatches.
    item_ids = {item["content_id"] for item in rec_record.get("items", [])}
    if content_id not in item_ids:
        logger.warning(
            "Event content_id=%s not in recommendation_id=%s items; dropping",
            content_id, rec_id,
        )
        return

    # Validate the patient identity claim against the recommendation log.
    # The Kinesis engagement stream is the integrity boundary for the
    # personalization model: a buggy or malicious producer that submits
    # events with a patient_id different from the one the recommendation
    # was issued for would pollute another patient's engagement summary
    # and skew their re-ranker features.
    if patient_id != rec_record.get("patient_id"):
        logger.warning(
            "Event patient_id=%s does not match recommendation_id=%s "
            "patient_id; dropping",
            patient_id, rec_id,
        )
        return

    # ---- Persist the raw event ----
    # event_id uses content from the event so duplicate Kinesis deliveries
    # converge to the same row. Production systems often add a SHA-256 over
    # (recommendation_id, content_id, event_type, timestamp).
    event_id = f"{rec_id}:{content_id}:{event_type}:{event.get('timestamp', '')}"
    events_table = dynamodb.Table(ENGAGEMENT_EVENTS_TABLE)
    events_table.put_item(Item={
        "event_id":          event_id,
        "recommendation_id": rec_id,
        "content_id":        content_id,
        "patient_id":        patient_id,
        "event_type":        event_type,
        "timestamp":         event.get("timestamp", datetime.datetime.now(timezone.utc).isoformat()),
        "rank":              event.get("rank"),
        # Rating is included for content_rating events; None otherwise.
        "rating":            event.get("rating"),
    })

    # ---- Update the patient engagement summary ----
    # Atomic ADDs so concurrent events don't trample each other. We need
    # the content_type to update format-keyed counters; look it up from
    # the catalog. In production, denormalize content_type onto each
    # recommendation-log item at recommend time so this lookup goes away.
    content_table = dynamodb.Table(CONTENT_TABLE)
    cat_response = content_table.get_item(Key={"content_id": content_id})
    content_meta = cat_response.get("Item") or {}
    content_type = content_meta.get("content_type", "unknown")
    topic_tags = content_meta.get("topic_tags", []) or []

    summary_table = dynamodb.Table(ENGAGEMENT_SUMMARY_TABLE)

    # Different events update different fields. Click and completion are
    # the signals the re-ranker cares about. Ratings are a strong signal
    # but rarely captured. Impressions are tracked for CTR computation
    # but don't update the format-preference signal.
    if event_type == "content_click":
        # SET format_clicks = if_not_exists(...) initializes the parent map
        # to {} on the very first event for a cold-start patient. Without
        # this, the nested `ADD format_clicks.#ct :one` throws
        # ValidationException because DynamoDB cannot update a nested
        # attribute when the parent map does not exist. Update expressions
        # are atomic, so the entire UpdateItem would be rejected.
        summary_table.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression=(
                "SET format_clicks = if_not_exists(format_clicks, :empty), "
                "    last_session_at = :ts "
                "ADD clicks_total :one, format_clicks.#ct :one"
            ),
            ExpressionAttributeNames={"#ct": content_type},
            ExpressionAttributeValues={
                ":one":   Decimal("1"),
                ":ts":    event["timestamp"],
                ":empty": {},
            },
        )
    elif event_type == "content_completion":
        # Completion is a stronger signal than click: the patient actually
        # finished (or got most of the way through) the content.
        # Same parent-map initialization pattern as the click branch above.
        summary_table.update_item(
            Key={"patient_id": patient_id},
            UpdateExpression=(
                "SET format_completions = if_not_exists(format_completions, :empty), "
                "    last_session_at = :ts "
                "ADD completions_total :one, format_completions.#ct :one"
            ),
            ExpressionAttributeNames={"#ct": content_type},
            ExpressionAttributeValues={
                ":one":   Decimal("1"),
                ":ts":    event["timestamp"],
                ":empty": {},
            },
        )
        # Track recently-engaged topics for the re-ranker's recent-topic boost.
        # Limit length to avoid the list growing unbounded; production uses
        # a separate table or rolling window.
        if topic_tags:
            _append_recent_topics(summary_table, patient_id, topic_tags)
    elif event_type == "content_rating":
        rating = event.get("rating")
        if isinstance(rating, (int, float)) and 1 <= rating <= 5:
            summary_table.update_item(
                Key={"patient_id": patient_id},
                UpdateExpression=(
                    "ADD ratings_total :one, ratings_sum :rating"
                ),
                ExpressionAttributeValues={
                    ":one":    Decimal("1"),
                    ":rating": Decimal(str(rating)),
                },
            )

    # ---- Emit a CloudWatch metric ----
    # Sliced by event_type, content_type, language, and reading-level
    # cohort. These dimensions power the cohort-fairness dashboard.
    # Don't add high-cardinality dimensions like patient_id; CloudWatch
    # custom-metric pricing punishes that quickly.
    feature_snapshot = rec_record.get("feature_snapshot", {}) or {}
    language = feature_snapshot.get("language", "unknown")
    reading_level_band = _reading_level_band(feature_snapshot.get("reading_level_est"))

    cloudwatch_client.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": "content_engagement",
            "Dimensions": [
                {"Name": "event_type",         "Value": event_type},
                {"Name": "content_type",       "Value": content_type},
                {"Name": "language",           "Value": language},
                {"Name": "reading_level_band", "Value": reading_level_band},
            ],
            "Value": 1.0,
            "Unit":  "Count",
        }],
    )

    logger.info(
        "Processed %s for patient=%s content=%s rec=%s",
        event_type, patient_id, content_id, rec_id,
    )


def _append_recent_topics(table, patient_id: str, new_tags: list) -> None:
    """
    Maintain a small rolling list of recently-engaged topic tags.

    The re-ranker uses this list to boost candidates that share tags with
    what the patient has been reading. We cap the list at a small size so
    it stays cheap to read on the hot path.

    A production version uses a Lua-equivalent atomic operation or a
    separate sorted-set abstraction. The simple read-modify-write below
    has a race condition under high concurrency for the same patient,
    which is acceptable here because per-patient engagement event rates
    are low.
    """
    MAX_RECENT_TOPICS = 10
    response = table.get_item(Key={"patient_id": patient_id})
    current = (response.get("Item") or {}).get("last_topics_engaged", []) or []
    # Prepend new tags, dedupe, truncate. Order = most recent first.
    combined = list(dict.fromkeys(list(new_tags) + list(current)))[:MAX_RECENT_TOPICS]
    table.update_item(
        Key={"patient_id": patient_id},
        UpdateExpression="SET last_topics_engaged = :tags",
        ExpressionAttributeValues={":tags": combined},
    )


def _reading_level_band(level) -> str:
    """Bucket a reading level into a low-cardinality cohort label."""
    if level is None or level == "unknown":
        return "unknown"
    try:
        n = int(level)
    except (TypeError, ValueError):
        return "unknown"
    if n <= 6:   return "elementary"
    if n <= 9:   return "middle"
    if n <= 12:  return "high_school"
    return "college_plus"
```

---

## Putting It All Together

Here's the full inference pipeline assembled into a single callable function. In production, content ingestion (Step 1) lives in a Step Functions workflow triggered by EventBridge events from the CMS, the inference path (Steps 2-5) is one Lambda behind API Gateway, and engagement processing (Step 6) is a separate Lambda consuming the Kinesis stream. The example chains them together for a single patient so you can trace one recommendation end-to-end.

```python
def recommend_for_patient(patient_id: str) -> dict:
    """
    Run the full inference pipeline for one patient.

    Steps 2 through 5 from the recipe:
      2. build_patient_context
      3. generate_candidates
      4. rerank
      5. log_and_return

    Step 6 (process_engagement_event) is event-driven and runs in a
    separate Lambda; we exercise it manually in the demo below.
    """
    start = time.time()

    # Step 2
    print(f"Step 2: Building patient context for {patient_id}...")
    patient_context = build_patient_context(patient_id)
    if patient_context is None:
        return {"status": "PATIENT_NOT_FOUND", "patient_id": patient_id}
    print(
        f"  language={patient_context['language']} "
        f"audience={patient_context['audience']} "
        f"reading_level={patient_context['reading_level_est']} "
        f"format_pref={patient_context['format_preference']}"
    )

    # Step 3
    print("Step 3: Generating candidates...")
    candidates = generate_candidates(patient_context)
    print(f"  {len(candidates)} candidates")
    if not candidates:
        return {
            "status": "NO_CANDIDATES",
            "patient_id": patient_id,
            "items": [],
        }

    # Step 4
    print("Step 4: Re-ranking with personalization signals...")
    top = rerank(candidates, patient_context)
    print(f"  Top {len(top)}:")
    for i, item in enumerate(top, start=1):
        print(f"    {i}. {item['content_id']} "
              f"(score={item['score']:.3f}, level={item.get('reading_level')})")

    # Step 5
    print("Step 5: Logging recommendation and emitting impressions...")
    response = log_and_return(patient_context, top)

    elapsed_ms = int((time.time() - start) * 1000)
    response["processing_time_ms"] = elapsed_ms
    print(f"  recommendation_id={response['recommendation_id']} "
          f"({elapsed_ms} ms)")
    return response


# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Seeds three pieces of education content (English, mixed formats)
    #   2. Seeds a synthetic patient with diabetes context
    #   3. Runs the inference pipeline once
    #   4. Simulates a click and completion event to exercise Step 6

    print("=" * 60)
    print("Seeding sample content...")
    print("=" * 60)
    sample_content = [
        {
            "id": "edu-diabetes-newly-diagnosed-en-v3",
            "version": "v3",
            "title": "Type 2 Diabetes: What to Expect in Your First 90 Days",
            "body": (
                "<p>If you have just been told you have type 2 diabetes, "
                "you are not alone. This article walks you through what to "
                "expect in the first three months. We cover what an A1c "
                "is, how to check your blood sugar, and small steps you "
                "can take with food and movement. We also explain how "
                "your medicine works and what to ask at your next visit. "
                "Most people find that simple changes, made one at a time, "
                "are easier to keep up with than big sudden changes.</p>"
            ),
            "language": "en",
            "topic_tags": ["diabetes", "newly_diagnosed", "type_2_diabetes"],
            "content_type": "article",
            "audience": "adult",
            "status": "active",
            "format": "html",
        },
        {
            "id": "edu-metformin-getting-started-en-v2",
            "version": "v2",
            "title": "Starting Metformin: Common Questions Answered",
            "body": (
                "<p>Metformin is the most common first medicine for type 2 "
                "diabetes. This page answers the questions people ask when "
                "they start it. How should I take it? What if I miss a "
                "dose? What side effects are normal in the first few "
                "weeks? When should I call my doctor? Take metformin with "
                "food to reduce stomach upset. Most side effects fade in "
                "two to four weeks.</p>"
            ),
            "language": "en",
            "topic_tags": ["diabetes", "metformin", "medications"],
            "content_type": "article",
            "audience": "adult",
            "status": "active",
            "format": "html",
        },
        {
            "id": "edu-glucose-monitoring-video-en-v1",
            "version": "v1",
            "title": "How to Check Your Blood Sugar at Home (Video Walkthrough)",
            "body": "Video transcript: Today we'll show you how to check your blood sugar at home...",
            "language": "en",
            "topic_tags": ["diabetes", "glucose_monitoring", "self_care"],
            "content_type": "video",
            "audience": "adult",
            "status": "active",
            "format": "mp4",
        },
    ]
    for item in sample_content:
        result = on_content_published(item)
        print(f"  Indexed: {result['content_id']} "
              f"(reading_level={result.get('reading_level')})")

    # Wait for OpenSearch to make the new docs searchable. The default
    # refresh interval is 1 second; for a demo we sleep briefly.
    print("\nWaiting for OpenSearch refresh...")
    time.sleep(2)

    print("\n" + "=" * 60)
    print("Seeding synthetic patient...")
    print("=" * 60)
    patient_id = "pat-synthetic-diabetes-001"
    patient_table = dynamodb.Table(PATIENT_TABLE)
    patient_table.put_item(Item={
        "patient_id": patient_id,
        "language": "en",
        "audience": "adult",
        "age": 54,
        "reading_level": 7,
        "active_conditions": [
            {
                "code": "44054006",
                "description": "type 2 diabetes mellitus newly diagnosed",
                "topic_tags": ["diabetes", "type_2_diabetes", "newly_diagnosed"],
            }
        ],
        "active_medications": [
            {"description": "metformin 500mg twice daily"}
        ],
        "recent_procedures": [],
    })
    # Seed a tiny bit of engagement so the re-ranker has something to work with.
    summary_table = dynamodb.Table(ENGAGEMENT_SUMMARY_TABLE)
    summary_table.put_item(Item={
        "patient_id": patient_id,
        "clicks_total":      Decimal("3"),
        "completions_total": Decimal("2"),
        "format_clicks":      {"article": Decimal("2"), "video": Decimal("1")},
        "format_completions": {"article": Decimal("1"), "video": Decimal("1")},
        "last_topics_engaged": ["diabetes", "diet"],
    })
    print(f"  Seeded {patient_id}")

    print("\n" + "=" * 60)
    print("Running recommendation pipeline...")
    print("=" * 60)
    response = recommend_for_patient(patient_id)

    print("\n" + "=" * 60)
    print("Recommendation response:")
    print("=" * 60)
    print(json.dumps(response, indent=2, default=str))

    if response.get("items"):
        print("\n" + "=" * 60)
        print("Simulating engagement events for the top recommended item...")
        print("=" * 60)
        first_item = response["items"][0]
        rec_id = response["recommendation_id"]
        now_iso = datetime.datetime.now(timezone.utc).isoformat()

        # Simulate a click
        process_engagement_event({
            "event_type":        "content_click",
            "recommendation_id": rec_id,
            "content_id":        first_item["content_id"],
            "patient_id":        patient_id,
            "timestamp":         now_iso,
            "rank":              1,
        })
        print("  click event processed")

        # Simulate a completion
        process_engagement_event({
            "event_type":        "content_completion",
            "recommendation_id": rec_id,
            "content_id":        first_item["content_id"],
            "patient_id":        patient_id,
            "timestamp":         now_iso,
            "rank":              1,
        })
        print("  completion event processed")

        # Verify the summary updated
        updated = summary_table.get_item(Key={"patient_id": patient_id}).get("Item", {})
        print(f"\nUpdated engagement summary:")
        print(f"  clicks_total      = {updated.get('clicks_total')}")
        print(f"  completions_total = {updated.get('completions_total')}")
        print(f"  format_completions= {updated.get('format_completions')}")
```

---

## The Gap Between This and Production

Run this end-to-end against a populated OpenSearch index and a seeded DynamoDB pair and you'll see the pattern: content indexed, patient context assembled, candidates retrieved, re-ranked, logged, returned, and engagement events flowing back. The distance between this and a real health-system deployment is significant. Here's where it lives.

**Content team workflow integration.** The example treats the content event as a clean dict with a `status` field. In reality, the CMS workflow has drafts, clinical-review states, deprecated content that needs to disappear from the index immediately, multilingual translations that must be linked to their source language version, and version-supersede semantics. Build the ingestion as a Step Functions workflow with explicit transitions for each lifecycle event (`PUBLISHED`, `UPDATED`, `DEPRECATED`, `RETIRED`), and wire CMS events into EventBridge with retry-on-failure so a transient ingestion error doesn't leave the index out of sync.

**Reading-level computation is more nuanced than Flesch-Kincaid.** This example uses Flesch-Kincaid because it's available off the shelf. Production patient-education programs often use SMOG (more conservative for clinical text) or Dale-Chall (better at flagging unfamiliar medical jargon). They also strip clinical-vocabulary noise (drug names, anatomical terms) before scoring; raw Flesch-Kincaid on a piece about "hyperlipidemia and atherosclerosis" comes back grade 16 because of two long words, even if the sentence structure is otherwise simple. Pick the algorithm with your clinical content team, document the choice, and re-score the catalog when you change it.

**Embedding model versioning.** When you upgrade the embedding model (Titan v2 to v3, or to a different family), every embedding in the index becomes incompatible with new query embeddings. The migration isn't trivial: re-embed the entire catalog under the new model, build a parallel index, run shadow queries to validate retrieval quality doesn't regress, switch traffic, retire the old index. Plan for at least one of these per year. Pin the model ID in config and never silently roll it forward.

**Catalog-level metadata gaps.** The example assumes every content item has language, topic_tags, content_type, audience, and status. Real catalogs have drift: legacy content with no language tag (default to "en", but flag it), content with stale topic tags that don't match the current taxonomy, content tagged for a deprecated audience category. Build a metadata-quality dashboard alongside the recommender; the recommender's quality is bounded by the catalog's quality, not the model's quality.

**Cold-start patient handling.** The example falls through to default reading level (8) and no preferred format for new patients. In production, you want an explicit cold-start path: a brief onboarding survey (preferred language confirmation, format preference, topics of interest), demographic-cohort defaults (age band → typical reading-level estimate, with caveats), and explicit fallbacks for unknown values rather than implicit ones. The cohort defaults raise the same fairness considerations covered in Recipe 4.1's chapter preface; apply the same care.

**Diversity and exposure controls.** Without diversity logic, the re-ranker will return the most similar three items to the query, and those three may all be variations of the same core article (a primary article, its summary, its FAQ). Production systems use Maximal Marginal Relevance (MMR), category diversification ("no more than 2 items from the same topic in top 5"), or a position-based penalty. Add this between Step 4's sort and the final slice; it's a small addition with a meaningful effect on perceived quality.

**Recommendation log retention and minimization.** The recommendation log table joins patient_id to content_id to feature_snapshot. That join is highly sensitive: a content_id like `edu-cancer-stage-iv-end-of-life-care` combined with a patient_id reveals a clinical fact the patient may not have shared widely. Apply the same controls as the patient profile table: customer-managed KMS, CloudTrail data events, narrow IAM read scopes, defined retention (e.g., 18 months for online tables, with cold archival to S3 Glacier for any longer retention compliance requires).

**Position bias correction in ranker training.** When you graduate from the hand-tuned weighted score to a learned ranker, you'll discover position bias: patients click items at the top of the list more than items at the bottom regardless of quality. A naive ranker trained on raw click data learns to predict "things that were already at the top," not "things that should be at the top." Inverse-propensity weighting or a click-model-based correction (e.g., position-based model) is required for honest training. This is an easy thing to get wrong and a hard thing to debug after the fact.

**Re-ranker training pipeline.** The example treats the re-ranker as a hand-tuned scoring function. Moving to a learned ranker requires a labeled training dataset: pairs of (patient context, candidate set, observed engagement) that get joined into a learning-to-rank dataset. Building that join correctly (positives are clicked or completed items; negatives are impressions that didn't get engagement; weights account for position bias) is its own engineering project. Use SageMaker XGBoost with `rank:pairwise` or `rank:ndcg` as the starting point. Train weekly to monthly; daily training is overkill at typical volumes and tends to overfit to noise.

**Engagement event idempotency.** The example uses `event_id = f"{rec_id}:{content_id}:{event_type}:{timestamp}"` for deduplication. Kinesis at-least-once semantics mean duplicates happen; the same event can land twice in close succession. The string-key dedup works for impression-style events but fails when the same patient legitimately triggers two clicks on the same content (e.g., they navigated away and returned). Production systems use a combination of timestamp bucketing and conditional writes (`PutItem` with `attribute_not_exists(event_id)`) to deduplicate without dropping legitimate repeat events.

**True outcome metrics vs. engagement proxies.** Click-through rate is fast and easy to measure. Read-completion is harder but more meaningful. Downstream behavior change (did the patient take their medication? did their A1c improve?) is what the system is actually trying to influence, but it lives months away in the EHR and joining the signal back to the recommendation that "caused" it is complicated. Don't optimize the recommender directly on downstream clinical outcomes (too far away, too noisy, too many confounders); use them for periodic offline evaluation, not for the online learning loop.

**Multilingual catalogs and gap reporting.** The example handles language preference as a hard filter. If you have 800 English items and 60 Spanish items, the Spanish-preference patient gets a much smaller candidate pool, the recommender will be honest about that, and the patient experience suffers. Build a "content gap" report that surfaces topics covered in the dominant language but not in others, sliced by patient population. Feed it back to the content team. The recommender can't fix gaps; it can highlight them.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), Kinesis (interface), CloudWatch Logs (interface), and the OpenSearch domain. All five DynamoDB tables encrypt at rest with a customer-managed KMS key (not the AWS-owned default). All S3 buckets enforce SSE-KMS via bucket policy. CloudTrail data events are enabled for the patient_profile, recommendation_log, and engagement_summary tables. A clinical audit will eventually ask "who saw this content for this patient on this date" and you need to answer definitively.

**API Gateway, throttling, and authentication.** The example calls `recommend_for_patient(patient_id)` directly. Production fronts the recommender with API Gateway, requires authenticated callers (Cognito, Lambda authorizer, or IAM-signed requests for service-to-service traffic), and applies per-caller rate limits. The portal can call freely; a misconfigured client should not be able to burn through a day's Bedrock quota in an hour. WAF in front of API Gateway is a reasonable extra layer for bot protection.

**Bedrock cost and quota management.** The embedding call is cheap per request but adds up at scale. The recommender embeds the patient query once per recommendation request (a portal page load triggers one); for 5,000 monthly active users with 3-5 sessions each, that's 15,000-25,000 embedding calls per month. Trivial. Where costs grow is content-side: re-embedding 5,000 items during a model migration, or daily incremental ingestion of large content volumes. Monitor Bedrock invocation count and spend in CloudWatch and set per-account quota alarms.

**Index maintenance and refresh policies.** OpenSearch index refresh interval defaults to 1 second, which is fine for development but expensive at scale. Production systems often increase it to 5-30 seconds for ingestion-heavy workloads. The k-NN HNSW index has its own optimization curve: more `ef_search` improves recall at the cost of latency. Tune both empirically against your latency SLO. Snapshot the index daily to S3 so a corruption or accidental delete is recoverable.

**Cohort fairness monitoring with humans in the loop.** The architecture emits cohort-sliced metrics. A dashboard nobody looks at is useless. Establish a monthly review cadence with the content team and a quality-of-care committee. Watch for: language cohorts with consistently lower CTR (catalog gap), reading-level cohorts with lower completion rates (content too hard for that cohort), clinical-condition cohorts with low candidate coverage (catalog or matching gap). Each finding produces an action item; the action items close the loop.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the reading-level computation, JSON-path parsing, and re-ranker scoring; integration tests against a test OpenSearch index with a small synthetic catalog and synthetic patients per language and audience cohort; regression tests that confirm hard filters are never bypassed even when scores prefer the disqualified candidate; and load tests at expected burst rates (Monday morning portal traffic, post-clinic-session AVS attachment surges). Never use real PHI in non-production environments. Synthea generates synthetic FHIR patients suitable for development.

**DynamoDB Decimal gotcha.** DynamoDB does not accept Python floats. The common trap is passing a float directly and getting `TypeError: Float types are not supported`. Always route floats through `Decimal(str(value))`; going through `str` avoids the binary-precision issues that `Decimal(float_value)` introduces. This example uses Decimal correctly throughout, but the trap is real and shows up the moment you start persisting model confidences, engagement weights, or anything else floating-point.

**Index creation in code is a smell.** The `_ensure_index_exists` helper is convenient for the demo but should not exist in production code. Index settings (mappings, k-NN parameters, refresh interval, replica count) belong in infrastructure-as-code so they're versioned, reviewable, and reproducible. Application code that owns index creation will eventually create an inconsistent index on a corner-case deployment and the inconsistency will be invisible until retrieval quality degrades.

**Model-ID lifecycle.** The Bedrock model ID in this example will be replaced over time as newer Titan or competing embedders ship. Store the model ID in SSM Parameter Store or AppConfig, not in code. When you upgrade, run a regression suite (a curated set of (patient context, expected top-k content_ids) pairs) against the new index before flipping production. Skipping this is how teams discover at 2 AM that the new model interprets clinical-context queries differently and the recommender quality has regressed.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.2: Patient Education Content Matching](chapter04.02-patient-education-content-matching) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
