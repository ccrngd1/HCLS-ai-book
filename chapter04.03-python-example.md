# Recipe 4.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.3. It shows one way you could translate those provider-directory-search concepts into working Python using Amazon OpenSearch Service for hybrid keyword + filter + vector search, Amazon DynamoDB for the provider catalog and patient context, Amazon Bedrock for query understanding and embeddings, Amazon Location Service for geocoding, and Amazon Kinesis for engagement events. It is not production-ready. There is no real credentialing-system integration, no NPPES verification loop, no Step Functions ingestion orchestration, no learned LTR ranker (we use a hand-tuned scoring function with the same shape XGBoost-Ranker would have), no exposure-cap calibration, no audit-log access workflow. Think of it as the sketchpad version: useful for understanding the shape of a directory search pipeline, not something you'd wire into a member portal on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the eight pseudocode steps from the main recipe: ingest a provider record and validate it, parse the patient's search query into structured intent, apply eligibility filters and retrieve candidates, join personalization features, score and rank, re-rank for fairness and diversity, assemble results with explanations and log the search, capture engagement events. All sample providers, patients, and engagement signals are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 opensearch-py requests-aws4auth
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` on the specific embedding model ARN (e.g., `arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0`) and the LLM model ARN used for query parsing (e.g., a Claude Haiku or Nova Lite model)
- `es:ESHttpPost`, `es:ESHttpGet`, `es:ESHttpPut` on the OpenSearch domain (or `aoss:APIAccessAll` if using OpenSearch Serverless)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the provider-catalog, provider-freshness, patient-profile, search-log, engagement-events, and exposure-aggregates tables
- `kinesis:PutRecord` on the engagement stream
- `geo:SearchPlaceIndexForText`, `geo:CalculateRoute` on the Location Service place and route resources
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console. This pipeline uses two models: an embedding model (Titan v2 by default) used at ingestion time and at query time, and a small LLM (Haiku-class) used for query parsing and explanation rendering. The embedding model used at query time MUST match the one used at index time, or vector similarity collapses. Pin the model IDs in config and verify at runtime if you're paranoid (and you should be).

A few things worth knowing upfront:

- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **The OpenSearch index used here is created on first run if it doesn't exist.** In production, the index is created by infrastructure-as-code (CDK/Terraform/CloudFormation) with proper field mappings, refresh intervals, and a documented schema versioning policy. Don't let application code own index creation in production.
- **All providers, patients, and engagement events in the example are synthetic.** Do not treat any specific NPI, provider name, or patient_id as real. A production system ingests from a real credentialing feed and joins to real patient profiles under BAA.
- **Geocoding uses Amazon Location Service.** Production deployments cache geocoded coordinates per provider so you're not paying per-lookup at query time. The example geocodes inline for clarity; the cache pattern is noted in the gap-to-production section.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, OpenSearch index settings, scoring weights, fairness policy thresholds, and the eligibility-rule constants are the knobs you'll change between environments.

```python
import json
import logging
import math
import re
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log the verbatim search query string
# joined to a patient_id; the query may include the patient's name, a
# prior provider's name, or other identifying free text. Search-log
# rows joined to a patient_id are PHI by definition.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from Bedrock, OpenSearch, DynamoDB,
# Kinesis, and Location Service during burst traffic (a "Find a Doctor"
# page on a member-portal landing surge, or a member-services rep doing
# rapid-fire searches on behalf of multiple callers).
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
location_client = boto3.client("location", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Titan Text Embeddings v2 returns 1024-dimensional vectors by default.
# CRITICAL: this must match what indexed the catalog. If you switch
# embedders, you must re-index every provider.
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSION = 1024

# A small, fast LLM for query parsing. Haiku-class models hit the
# latency budget; larger frontier models do not. The same model is
# used for the explanation rendering step.
QUERY_PARSER_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"

# --- DynamoDB Table Names ---
# Six tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. provider-catalog:    canonical provider record (provider_id PK)
#   2. provider-freshness:  per-field verification timestamps (provider_id PK)
#   3. patient-profile:     patient demographics, plan, prefs (patient_id PK)
#   4. search-log:          one row per search served (search_id PK)
#   5. engagement-events:   raw engagement events (event_id PK)
#   6. exposure-aggregates: rolling exposure counts per provider (provider_id PK)
PROVIDER_TABLE = "provider-catalog"
FRESHNESS_TABLE = "provider-freshness"
PATIENT_TABLE = "patient-profile"
SEARCH_LOG_TABLE = "search-log"
ENGAGEMENT_EVENTS_TABLE = "engagement-events"
EXPOSURE_TABLE = "exposure-aggregates"

# --- OpenSearch Configuration ---
# Hybrid index: BM25 text fields + filter fields + k-NN vector field.
# A single query can do all three.
OPENSEARCH_ENDPOINT = "your-opensearch-domain.us-east-1.es.amazonaws.com"
OPENSEARCH_INDEX = "provider-directory"
OPENSEARCH_REGION = "us-east-1"

# --- Location Service ---
# Place index for geocoding. Pre-created in production via IaC; the
# example assumes it exists.
LOCATION_PLACE_INDEX = "provider-directory-places"

# --- Kinesis ---
# Engagement stream pattern reused from Recipes 4.1 and 4.2, with new
# event types: search_impression, search_click, provider_call_initiated,
# appointment_booked, directory_complaint_filed.
ENGAGEMENT_STREAM_NAME = "engagement-stream"

# --- Pipeline Tuning ---
# Initial candidate set size. Larger = more recall, more re-ranker work.
INITIAL_CANDIDATE_LIMIT = 200

# Final result list size. Member portal "Find a Doctor" pages typically
# show 10-20 results per page.
TOP_N_TO_RETURN = 10

# --- Default Search Radius (miles) ---
# Patients can override; this is the fallback. Geography-aware defaults
# are better in production (urban dense vs rural).
DEFAULT_SEARCH_RADIUS_MI = 25

# --- LTR Scoring Weights ---
# Hand-tuned weights for the v1 ranker. These are the same features an
# XGBoost-Ranker would consume; the difference is that a learned ranker
# learns the weights from labeled data instead of having a human pick them.
# Replace this whole function with model.predict() once you have a
# meaningful training dataset.
LTR_WEIGHTS = {
    "vector_similarity":     1.0,
    "bm25_score":            0.4,
    "specialty_fit":         1.5,
    "language_match":        0.8,
    "prior_visits":          1.2,
    "panel_openness":        0.6,
    "freshness_penalty":    -1.0,   # negative: stale records demoted
    "distance_penalty":     -0.05,  # per mile
    "network_tier_bonus":    0.4,   # preferred-tier bonus
    "safety_net_bonus":      0.0,   # default zero; the fairness re-ranker
                                    # handles safety-net visibility separately
}

# --- Fairness Re-Rank Policy ---
# Three knobs the re-ranker exposes. Calibrated by network operations,
# not data science.
POLICY_MAX_TOP3_IMPRESSIONS_24H = 5000
POLICY_EXPOSURE_DAMPENING_FACTOR = 0.7
POLICY_SAFETY_NET_FLOOR_ENABLED = True
POLICY_SAFETY_NET_TOP_N = 5
POLICY_SAFETY_NET_MIN_FIT = 0.7
POLICY_SAFETY_NET_MAX_FRESHNESS_PENALTY = 0.2
POLICY_NEAR_DUPLICATE_DAMPENING_FACTOR = 0.6
POLICY_NEAR_DUPLICATE_OVERLAP_THRESHOLD = 0.8

# --- Freshness Scoring ---
# How quickly we demote records based on staleness. Real plans tune
# these against the regulatory reverification cadence (often 90 days).
FRESHNESS_FRESH_DAYS = 30
FRESHNESS_STALE_DAYS = 90
FRESHNESS_PENALTY_FRESH = 0.0
FRESHNESS_PENALTY_AGING = 0.1
FRESHNESS_PENALTY_STALE = 0.5

# CloudWatch namespace for engagement metrics. Slice by language, plan,
# and position-band in the dashboard to catch subgroup issues.
METRIC_NAMESPACE = "ProviderDirectorySearch"

# Model and policy version stamps. Increment when you change scoring,
# candidate logic, or fairness policy; stored on every search log row
# so back-catalog analysis can segment by version.
LTR_MODEL_VERSION = "rank-v0.7"
POLICY_VERSION = "fair-rerank-v0.3"
```

---

## Reference Data: Specialty Taxonomy

A miniature subset of the [NUCC Healthcare Provider Taxonomy](https://www.nucc.org/index.php/code-sets-mainmenu-41/provider-taxonomy-mainmenu-40), enough to drive the example. Production systems load the full taxonomy (1,300-plus codes) into a lookup table or a config-managed reference dataset. The mapping from free-text patient queries to canonical codes is one of the trickiest parts of this pipeline; the LLM in Step 2 is doing exactly that mapping with the taxonomy in its prompt context.

```python
# A subset of NUCC codes used by the example. Real deployments load the
# full taxonomy. Each entry includes the canonical name and a list of
# free-text aliases the parser knows how to map to this code.
SPECIALTY_TAXONOMY = {
    "207Q00000X": {
        "name": "Family Medicine",
        "aliases": ["family doctor", "family physician", "general practitioner",
                    "primary care", "pcp", "gp"],
    },
    "208000000X": {
        "name": "Pediatrics",
        "aliases": ["pediatrician", "kids doctor", "children's doctor",
                    "child doctor"],
    },
    "207RC0000X": {
        "name": "Cardiovascular Disease",
        "aliases": ["cardiologist", "heart doctor", "cardiac specialist"],
    },
    "207RE0101X": {
        "name": "Endocrinology",
        "aliases": ["endocrinologist", "diabetes doctor", "thyroid doctor",
                    "hormone doctor"],
    },
    "207X00000X": {
        "name": "Orthopaedic Surgery",
        "aliases": ["orthopedic", "orthopaedic", "bone doctor", "joint doctor",
                    "knee doctor", "shoulder doctor", "back doctor"],
    },
    "208600000X": {
        "name": "Surgery",
        "aliases": ["general surgeon", "surgeon"],
    },
    "207V00000X": {
        "name": "Obstetrics & Gynecology",
        "aliases": ["obgyn", "ob/gyn", "ob-gyn", "gynecologist", "obstetrician",
                    "women's health"],
    },
    "208D00000X": {
        "name": "General Practice",
        "aliases": ["general practice"],
    },
}

# Plan-tier eligibility lookup. A "preferred" plan can see preferred
# and standard providers; a "standard" plan sees standard only.
# In production this is plan-design metadata loaded from a contracts
# data store, not a hardcoded dict.
PLAN_TIER_ELIGIBILITY = {
    "preferred": ["preferred", "standard"],
    "standard":  ["standard"],
    "basic":     ["standard"],
}
```

---

## Shared Helpers

A handful of utilities used across steps. Pulled together here so each step's logic stays focused.

```python
# Lazy module-level cache for the OpenSearch client. Populated on first
# _get_opensearch_client() call.
_opensearch_client: OpenSearch | None = None


def _get_opensearch_client() -> OpenSearch:
    """
    Build (or reuse) an IAM-authenticated OpenSearch client.

    Cached at module scope after first construction. In a Lambda warm
    container, the SigV4 credential resolution and TLS handshake happen
    once per process rather than once per invocation, which matters
    when the search path targets sub-500 ms p95 latency.
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


def _embed_text(text: str) -> list:
    """
    Embed a string using the configured embedding model.

    CRITICAL: this MUST match whatever embedder indexed the catalog.
    Mismatched embedders produce vectors that don't live in the same
    space, retrieval quality silently collapses, and you don't get an
    error. Pin the model ID in config and never change it without a
    full re-index of the provider directory.
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
    Create the OpenSearch index with hybrid mappings if missing.

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
                # ef_search trades latency for recall. 100 is a fine
                # starting point for a small catalog (under 50k providers).
                "knn.algo_param.ef_search": 100,
                "number_of_shards": 1,
                "number_of_replicas": 1,
            }
        },
        "mappings": {
            "properties": {
                "provider_id":           {"type": "keyword"},
                "name":                  {"type": "text"},
                "canonical_specialty":   {"type": "keyword"},
                "specialty_label":       {"type": "text"},
                "sub_specialties":       {"type": "keyword"},
                "languages":             {"type": "keyword"},
                "gender":                {"type": "keyword"},
                "accepts_new_patients":  {"type": "boolean"},
                "network_tier":          {"type": "keyword"},
                "is_safety_net_provider": {"type": "boolean"},
                "practice_id":           {"type": "keyword"},
                "services_text":         {"type": "text"},
                "bio_text":              {"type": "text"},
                "location":              {"type": "geo_point"},
                "address":               {"type": "text"},
                "phone":                 {"type": "keyword"},
                "last_verified_at":      {"type": "date"},
                "freshness_score":       {"type": "float"},
                "status":                {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": EMBEDDING_DIMENSION,
                    # Cosine similarity is the right choice for semantic
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


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two (lat, lon) points in miles.

    OpenSearch already filters by radius in the query; this is for the
    feature-joining step where we need a numeric distance per candidate
    to feed into the ranker.
    """
    R_miles = 3958.7613
    lat1r, lon1r, lat2r, lon2r = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2 * R_miles * math.asin(math.sqrt(a))


def _geocode_address(address_text: str) -> dict | None:
    """
    Geocode a free-text address using Amazon Location Service.

    Returns {"lat": float, "lon": float} or None if no match. In
    production, cache results aggressively: provider addresses change
    rarely, patient addresses change rarely, and Location Service
    charges per request.
    """
    if not address_text:
        return None
    try:
        response = location_client.search_place_index_for_text(
            IndexName=LOCATION_PLACE_INDEX,
            Text=address_text,
            MaxResults=1,
        )
    except Exception as exc:
        logger.warning("Geocoding failed for '%s': %s", address_text, exc)
        return None

    results = response.get("Results", [])
    if not results:
        return None
    point = results[0]["Place"]["Geometry"]["Point"]
    # Location Service returns [lon, lat] (GeoJSON convention).
    return {"lon": point[0], "lat": point[1]}


def _compute_freshness_penalty(last_verified_iso: str | None) -> float:
    """
    Map a verification timestamp to a freshness penalty in [0, 1].

    Penalty is 0 for fresh records, ramps up linearly past the freshness
    threshold, hits FRESHNESS_PENALTY_STALE at the stale threshold, and
    stays there. This is what the ranker uses to demote stale records;
    the catalog ingestion separately demotes records to "demoted" status
    when validations fail outright.
    """
    if not last_verified_iso:
        return FRESHNESS_PENALTY_STALE
    try:
        verified_at = datetime.datetime.fromisoformat(last_verified_iso.replace("Z", "+00:00"))
    except ValueError:
        return FRESHNESS_PENALTY_STALE
    age_days = (datetime.datetime.now(timezone.utc) - verified_at).days
    if age_days <= FRESHNESS_FRESH_DAYS:
        return FRESHNESS_PENALTY_FRESH
    if age_days >= FRESHNESS_STALE_DAYS:
        return FRESHNESS_PENALTY_STALE
    # Linear ramp between fresh and stale.
    span = FRESHNESS_STALE_DAYS - FRESHNESS_FRESH_DAYS
    progress = (age_days - FRESHNESS_FRESH_DAYS) / span
    return FRESHNESS_PENALTY_AGING + progress * (FRESHNESS_PENALTY_STALE - FRESHNESS_PENALTY_AGING)


def _build_profile_text(record: dict) -> str:
    """
    Build the searchable profile text that gets embedded.

    The embedding picks up topical signal from the specialty + services +
    bio. We don't include languages or tier here; those go into structured
    filter fields, not the vector. Keeping the text focused on clinical
    content gives the embedding cleaner semantic signal.
    """
    parts = [record.get("specialty_label", "")]
    if record.get("sub_specialties"):
        parts.append("sub-specialties: " + ", ".join(record["sub_specialties"]))
    if record.get("services"):
        parts.append("services: " + record["services"])
    if record.get("bio"):
        parts.append(record["bio"])
    return ". ".join(p for p in parts if p).strip()
```

---

## Step 1: Ingest a Provider Record and Index It

*The pseudocode calls this `on_provider_event(event)`. When a new credentialing record, a claims-derived update, or a self-attestation arrives, the ingestion pipeline matches the record to existing providers, validates it, annotates it with the canonical taxonomy, generates an embedding for the searchable profile text, and only then promotes it into the index. The example collapses match/validate/annotate/embed/index into one function for readability; in production these are separate Step Functions tasks with their own error handling and DLQs.*

```python
def on_provider_event(event: dict) -> dict:
    """
    Process a provider event and (re)index the canonical record.

    Args:
        event: Dict representing the provider payload. Expected keys:
            - npi:                  10-digit National Provider Identifier
            - name:                 display name
            - specialty_source:     source-system free-text specialty
            - sub_specialties:      list of sub-specialty strings
            - languages:            list of language codes (ISO 639-1)
            - gender:               "male" | "female" | "non_binary" | None
            - accepts_new_patients: bool
            - network_tier:         "preferred" | "standard" | "out_of_network"
            - is_safety_net:        bool (FQHC, community health center, etc.)
            - practice_id:          identifier for the practice
            - address:              full address string
            - phone:                phone number (E.164-ish)
            - services:             free-text services description
            - bio:                  free-text provider bio
            - source_system:        which upstream system produced the event

    Returns:
        Dict with provider_id, status, and validation details.
    """
    # ---- Step 1a: Match to existing record ----
    # NPI is the primary key. In production, fall back to (tax_id +
    # address_similarity) and (name + state + specialty) when NPI is
    # missing. The example uses NPI directly.
    npi = event.get("npi")
    if not npi or not re.fullmatch(r"\d{10}", npi):
        logger.warning("Event missing or malformed NPI; routing to manual review")
        return {"status": "MANUAL_REVIEW", "reason": "no_or_invalid_npi"}
    provider_id = f"prv-{npi}"

    # ---- Step 1b: Validate ----
    # Each validation that fails feeds into the freshness table and may
    # demote (not delete) the record in the index. The example checks
    # address geocodability and basic phone format. Production also
    # checks NPI active status against NPPES and phone reachability.
    validation = {
        "address_geocoded": _geocode_address(event.get("address", "")),
        "phone_format_ok":  bool(re.match(r"^\+?[\d\-\s\(\)]{7,}$", event.get("phone", "") or "")),
        "specialty_known":  False,
    }
    canonical_specialty_code = None
    canonical_specialty_label = event.get("specialty_source", "")
    for code, info in SPECIALTY_TAXONOMY.items():
        if (event.get("specialty_source", "").lower() == info["name"].lower()
                or event.get("specialty_source") == code):
            canonical_specialty_code = code
            canonical_specialty_label = info["name"]
            validation["specialty_known"] = True
            break
    if canonical_specialty_code is None:
        # Couldn't map; demote but still index so the data quality team
        # sees it on the dashboard. Production routes these to a queue
        # for taxonomy curation.
        logger.warning(
            "Provider %s has unmapped specialty '%s'; indexing as demoted",
            provider_id, event.get("specialty_source"),
        )

    failed_validations = [k for k, v in validation.items() if not v]
    record_status = "active" if not failed_validations else "demoted"

    # ---- Step 1c: Annotate ----
    # Normalize languages to lowercase ISO codes; canonicalize specialty
    # to the NUCC code; carry through the rest verbatim.
    languages = [lang.lower() for lang in (event.get("languages") or [])]
    location = validation["address_geocoded"] or {"lat": None, "lon": None}
    now_iso = datetime.datetime.now(timezone.utc).isoformat()

    annotated = {
        "provider_id":           provider_id,
        "npi":                   npi,
        "name":                  event["name"],
        "canonical_specialty":   canonical_specialty_code or "UNKNOWN",
        "specialty_label":       canonical_specialty_label,
        "sub_specialties":       event.get("sub_specialties", []) or [],
        "languages":             languages,
        "gender":                event.get("gender"),
        "accepts_new_patients":  bool(event.get("accepts_new_patients", False)),
        "network_tier":          event.get("network_tier", "standard"),
        "is_safety_net_provider": bool(event.get("is_safety_net", False)),
        "practice_id":           event.get("practice_id", ""),
        "address":               event.get("address", ""),
        "phone":                 event.get("phone", ""),
        "services":              event.get("services", ""),
        "bio":                   event.get("bio", ""),
        "location":              location,
        "last_verified_at":      now_iso,
        "source_system":         event.get("source_system", "unknown"),
        "status":                record_status,
    }

    # ---- Step 1d: Embed ----
    profile_text = _build_profile_text({
        "specialty_label":  canonical_specialty_label,
        "sub_specialties":  annotated["sub_specialties"],
        "services":         annotated["services"],
        "bio":              annotated["bio"],
    })
    if not profile_text:
        # Edge case: no clinical text. Skip the embedding rather than
        # produce a junk vector.
        logger.warning("Provider %s has no profile text; skipping embedding", provider_id)
        embedding = None
    else:
        embedding = _embed_text(profile_text)

    # ---- Step 1e: Persist canonical record to DynamoDB ----
    # DynamoDB is the system of record. The OpenSearch index is a
    # denormalized projection of this record for search.
    provider_table = dynamodb.Table(PROVIDER_TABLE)
    # Convert the lat/lon dict (which has floats) through Decimal because
    # DynamoDB does not accept Python floats.
    persisted = dict(annotated)
    if persisted["location"].get("lat") is not None:
        persisted["location"] = {
            "lat": Decimal(str(persisted["location"]["lat"])),
            "lon": Decimal(str(persisted["location"]["lon"])),
        }
    provider_table.put_item(Item=persisted)

    # ---- Step 1f: Update freshness table ----
    freshness_table = dynamodb.Table(FRESHNESS_TABLE)
    freshness_table.put_item(Item={
        "provider_id":             provider_id,
        "address_verified_at":     now_iso if validation["address_geocoded"] else None,
        "phone_verified_at":       now_iso if validation["phone_format_ok"] else None,
        "specialty_verified_at":   now_iso if validation["specialty_known"] else None,
        "last_full_verification":  now_iso,
        "failed_validations":      failed_validations,
    })

    # ---- Step 1g: Index into OpenSearch ----
    client = _get_opensearch_client()
    _ensure_index_exists(client)

    # OpenSearch accepts floats natively; we use the original (non-Decimal)
    # location dict for the geo_point field.
    os_doc = {
        "provider_id":            provider_id,
        "name":                   annotated["name"],
        "canonical_specialty":    annotated["canonical_specialty"],
        "specialty_label":        annotated["specialty_label"],
        "sub_specialties":        annotated["sub_specialties"],
        "languages":              annotated["languages"],
        "gender":                 annotated["gender"],
        "accepts_new_patients":   annotated["accepts_new_patients"],
        "network_tier":           annotated["network_tier"],
        "is_safety_net_provider": annotated["is_safety_net_provider"],
        "practice_id":            annotated["practice_id"],
        "services_text":          annotated["services"],
        "bio_text":               annotated["bio"],
        "address":                annotated["address"],
        "phone":                  annotated["phone"],
        "last_verified_at":       now_iso,
        "freshness_score":        1.0,  # fresh on ingestion
        "status":                 record_status,
    }
    if location.get("lat") is not None:
        # OpenSearch geo_point as {"lat": ..., "lon": ...}
        os_doc["location"] = {"lat": location["lat"], "lon": location["lon"]}
    if embedding is not None:
        os_doc["embedding"] = embedding

    client.index(
        index=OPENSEARCH_INDEX,
        id=provider_id,
        body=os_doc,
        refresh=False,
    )

    # ---- Step 1h: Emit observability metric ----
    cloudwatch_client.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": "provider_ingest",
            "Dimensions": [
                {"Name": "source_system", "Value": annotated["source_system"]},
                {"Name": "outcome",       "Value": record_status},
            ],
            "Value": 1.0,
            "Unit":  "Count",
        }],
    )

    logger.info(
        "Indexed provider %s (specialty=%s, status=%s, failed_validations=%s)",
        provider_id, canonical_specialty_label, record_status, failed_validations,
    )
    return {
        "provider_id": provider_id,
        "status":      record_status,
        "failed_validations": failed_validations,
    }
```

---

## Step 2: Parse the Search Query Into Structured Intent

*The pseudocode calls this `parse_query(query_string, patient_context)`. The patient typed something into a search box. Stage 1's job is to figure out what they meant. We try a fast deterministic path first (empty query, exact NPI lookup, name-shaped string) and only call the LLM for the fuzzy free-text cases. The output is a structured intent object that downstream stages use to build the OpenSearch query.*

```python
def parse_query(query_string: str, patient_locale: str = "en") -> dict:
    """
    Parse a free-text search query into structured intent.

    Returns a dict:
      {
        "intent_type":     "specialty_search" | "name_search" |
                           "service_search" | "unknown",
        "specialty":       NUCC code or None,
        "specialty_label": display label or None,
        "sub_specialty":   string or None,
        "filters": {
            "language":             ISO 639-1 code or None,
            "gender":               "male" | "female" | "non_binary" | None,
            "accepts_new_patients": bool or None,
            "telehealth":           bool or None,
        },
        "free_text_residual": string,
      }
    """
    query_string = (query_string or "").strip()

    # ---- Fast path 1: empty query ----
    if not query_string:
        return _empty_intent()

    # ---- Fast path 2: NPI lookup (10 digits) ----
    if re.fullmatch(r"\d{10}", query_string):
        return {
            "intent_type":      "name_search",
            "specialty":        None,
            "specialty_label":  None,
            "sub_specialty":    None,
            "filters":          _empty_filters(),
            "free_text_residual": query_string,
        }

    # ---- Fast path 3: name-shaped query ("Dr. Smith") ----
    if re.match(r"^(dr\.?\s+)?[A-Z][a-z]+(\s+[A-Z][a-z]+){0,2}$", query_string):
        return {
            "intent_type":      "name_search",
            "specialty":        None,
            "specialty_label":  None,
            "sub_specialty":    None,
            "filters":          _empty_filters(),
            "free_text_residual": query_string,
        }

    # ---- Fast path 4: alias match against the specialty taxonomy ----
    # Cheaper than calling the LLM. Tries to match the whole query, then
    # tries to find any alias as a substring.
    lowered = query_string.lower()
    for code, info in SPECIALTY_TAXONOMY.items():
        for alias in info["aliases"]:
            if alias in lowered:
                # We matched a known alias; the LLM call would likely
                # produce the same result. Skip it and save the latency.
                # The remaining text after stripping the alias is the
                # "residual" (e.g., "spanish" from "pediatrician spanish").
                residual = lowered.replace(alias, "").strip()
                filters = _extract_simple_filters(residual)
                return {
                    "intent_type":      "specialty_search",
                    "specialty":        code,
                    "specialty_label":  info["name"],
                    "sub_specialty":    None,
                    "filters":          filters,
                    "free_text_residual": residual,
                }

    # ---- Slow path: call the LLM with structured-output prompting ----
    # The example uses a simple text prompt and JSON-extracts the result.
    # Production uses Bedrock's tool-use / structured output feature for
    # tighter guarantees; the prompt below illustrates the shape.
    return _llm_parse_query(query_string, patient_locale)


def _empty_intent() -> dict:
    return {
        "intent_type":      "unknown",
        "specialty":        None,
        "specialty_label":  None,
        "sub_specialty":    None,
        "filters":          _empty_filters(),
        "free_text_residual": "",
    }


def _empty_filters() -> dict:
    return {
        "language":             None,
        "gender":               None,
        "accepts_new_patients": None,
        "telehealth":           None,
    }


def _extract_simple_filters(text: str) -> dict:
    """
    Pull common filters out of free text deterministically.

    Cheap heuristics that catch the common cases without an LLM call.
    The LLM path can override these for ambiguous inputs.
    """
    filters = _empty_filters()
    text_lower = text.lower()
    # Language hints
    lang_aliases = {
        "spanish": "es",
        "espanol": "es",
        "english": "en",
        "vietnamese": "vi",
        "mandarin": "zh",
        "chinese":   "zh",
        "korean":    "ko",
    }
    for alias, code in lang_aliases.items():
        if alias in text_lower:
            filters["language"] = code
            break
    # Gender hints
    if "female" in text_lower or "woman" in text_lower:
        filters["gender"] = "female"
    elif "male" in text_lower or "man" in text_lower:
        filters["gender"] = "male"
    # Accepting-new-patients hints
    if "accepting" in text_lower or "new patient" in text_lower:
        filters["accepts_new_patients"] = True
    # Telehealth hints
    if "telehealth" in text_lower or "virtual" in text_lower or "online" in text_lower:
        filters["telehealth"] = True
    return filters


def _llm_parse_query(query_string: str, patient_locale: str) -> dict:
    """
    Slow path: invoke the LLM to parse a query that the fast paths missed.

    Production uses Bedrock's structured-output / tool-use feature so the
    model is forced to return JSON conforming to a strict schema. The
    example uses a plain prompt for clarity; real code should validate
    every field, drop unknown specialty codes, and fall back gracefully
    when the response is malformed.
    """
    # Build a compact taxonomy hint for the prompt.
    taxonomy_hint = "\n".join(
        f"  {code}: {info['name']}" for code, info in SPECIALTY_TAXONOMY.items()
    )

    prompt = f"""You are a search-intent parser for a healthcare provider directory.
Parse the following query into structured JSON. Use ONLY the specialty codes
in the taxonomy below; if no specialty fits, set specialty to null.
Valid filter values: language is ISO 639-1, gender is "male"/"female"/"non_binary"/null,
accepts_new_patients and telehealth are true/false/null.

Taxonomy:
{taxonomy_hint}

Query: {query_string}
Patient locale: {patient_locale}

Return ONLY valid JSON with this shape:
{{
  "intent_type": "specialty_search" | "name_search" | "service_search" | "unknown",
  "specialty": "NUCC code or null",
  "sub_specialty": "string or null",
  "filters": {{
    "language": "ISO 639-1 code or null",
    "gender": "male | female | non_binary | null",
    "accepts_new_patients": "true | false | null",
    "telehealth": "true | false | null"
  }},
  "free_text_residual": "string"
}}"""

    try:
        response = bedrock_runtime.invoke_model(
            modelId=QUERY_PARSER_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 400,
                "temperature": 0.0,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
            }),
        )
        payload = json.loads(response["body"].read())
        completion = payload["content"][0]["text"]
        # Extract the first JSON object from the response (LLMs sometimes
        # wrap JSON in prose despite instructions; defensive parse).
        match = re.search(r"\{.*\}", completion, re.DOTALL)
        if not match:
            logger.warning("LLM returned no JSON: %s", completion)
            return _intent_from_residual(query_string)
        parsed = json.loads(match.group(0))
    except Exception as exc:
        # Any failure: fall back to a residual-only intent so retrieval
        # still happens against BM25. We don't raise; search should
        # gracefully degrade.
        logger.warning("LLM parse failed for '%s': %s", query_string, exc)
        return _intent_from_residual(query_string)

    # ---- Validate and normalize the LLM output ----
    specialty_code = parsed.get("specialty")
    if specialty_code and specialty_code not in SPECIALTY_TAXONOMY:
        # Drop unknown codes; let BM25 take over.
        specialty_code = None
    specialty_label = (
        SPECIALTY_TAXONOMY[specialty_code]["name"] if specialty_code else None
    )

    filters = parsed.get("filters") or {}
    normalized_filters = {
        "language":             filters.get("language") if filters.get("language") else None,
        "gender":               filters.get("gender") if filters.get("gender") in ("male", "female", "non_binary") else None,
        "accepts_new_patients": _to_bool_or_none(filters.get("accepts_new_patients")),
        "telehealth":           _to_bool_or_none(filters.get("telehealth")),
    }

    return {
        "intent_type":         parsed.get("intent_type", "unknown"),
        "specialty":           specialty_code,
        "specialty_label":     specialty_label,
        "sub_specialty":       parsed.get("sub_specialty"),
        "filters":             normalized_filters,
        "free_text_residual":  parsed.get("free_text_residual", query_string) or query_string,
    }


def _to_bool_or_none(v) -> bool | None:
    if v is True or v == "true":
        return True
    if v is False or v == "false":
        return False
    return None


def _intent_from_residual(query_string: str) -> dict:
    """Fallback: treat the whole query as free-text residual."""
    return {
        "intent_type":         "unknown",
        "specialty":           None,
        "specialty_label":     None,
        "sub_specialty":       None,
        "filters":             _extract_simple_filters(query_string),
        "free_text_residual":  query_string,
    }
```

---

## Step 3: Apply Eligibility Filters and Retrieve Candidates

*The pseudocode calls this `retrieve_candidates(intent, patient_context, top_k=200)`. Stages 2 and 3 of the architecture combine into a single OpenSearch query. The filter clause enforces hard "shall not show" rules (network match, specialty match, accepting-new-patients when required, geographic radius). The must clause does keyword and vector match for relevance. The should clause adds soft signals (sub-specialty, freshness boost) that nudge ranking without disqualifying anyone.*

```python
def retrieve_candidates(
    intent: dict,
    patient_context: dict,
    top_k: int = INITIAL_CANDIDATE_LIMIT,
) -> list:
    """
    Combine eligibility filtering and hybrid search in one OpenSearch query.

    Hard filters (correctness): network match, status active, geographic
    radius. Filters from the parsed intent: language, gender,
    accepts_new_patients (only applied when the intent system is confident
    about them).

    Hybrid retrieval: vector k-NN for semantic similarity, BM25 for
    keyword match. Neither alone is enough; vectors handle paraphrases,
    BM25 handles exact-name and exact-specialty matches the embedder
    can blur.

    Returns a list of candidate dicts with the per-document signals
    (vector score, BM25 score) needed by the feature-joining step.
    """
    client = _get_opensearch_client()

    # ---- Build the eligibility filters ----
    allowed_tiers = PLAN_TIER_ELIGIBILITY.get(
        patient_context.get("plan_tier", "standard"),
        ["standard"],
    )

    eligibility_filters = [
        {"term": {"status": "active"}},
        {"terms": {"network_tier": allowed_tiers}},
    ]

    # Filters from the parsed intent. Only apply when present; missing
    # filters mean the parser wasn't confident, and we don't want to
    # spuriously narrow the candidate set.
    if intent["filters"].get("language"):
        eligibility_filters.append(
            {"term": {"languages": intent["filters"]["language"]}}
        )
    if intent["filters"].get("gender"):
        eligibility_filters.append(
            {"term": {"gender": intent["filters"]["gender"]}}
        )
    if intent["filters"].get("accepts_new_patients") is True:
        eligibility_filters.append(
            {"term": {"accepts_new_patients": True}}
        )

    # Geographic radius filter. The patient's search location is set
    # from explicit input or from the address on file.
    search_location = patient_context.get("search_location")
    radius_mi = patient_context.get("search_radius_miles", DEFAULT_SEARCH_RADIUS_MI)
    if search_location and search_location.get("lat") is not None:
        eligibility_filters.append({
            "geo_distance": {
                "distance": f"{radius_mi}mi",
                "location": {
                    "lat": search_location["lat"],
                    "lon": search_location["lon"],
                },
            }
        })

    # ---- Build the embedding for the vector match ----
    # Combine the canonical specialty label with the free-text residual.
    # The structured part anchors the embedding in a known specialty;
    # the free text picks up nuance the parser couldn't capture.
    embedding_input_parts = []
    if intent.get("specialty_label"):
        embedding_input_parts.append(intent["specialty_label"])
    if intent.get("free_text_residual"):
        embedding_input_parts.append(intent["free_text_residual"])
    embedding_input = " ".join(embedding_input_parts).strip() or "general practice"
    query_embedding = _embed_text(embedding_input)

    # ---- Build the hybrid query ----
    bm25_query_text = " ".join(
        p for p in [intent.get("specialty_label"), intent.get("free_text_residual")] if p
    )

    query = {
        "size": top_k,
        "query": {
            "bool": {
                "filter": eligibility_filters,
                "must": [
                    {
                        # Vector similarity: how well the provider's
                        # profile matches the parsed intent semantically.
                        "knn": {
                            "embedding": {
                                "vector": query_embedding,
                                "k": top_k,
                            }
                        }
                    }
                ],
                "should": [
                    # BM25 keyword match on name and specialty as a boost.
                    {
                        "multi_match": {
                            "query": bm25_query_text,
                            "fields": [
                                "name^3",
                                "specialty_label^2",
                                "sub_specialties",
                                "services_text",
                                "bio_text",
                            ],
                            "boost": 1.5,
                        }
                    },
                    # Sub-specialty match if the parser found one.
                    {
                        "terms": {
                            "sub_specialties": (
                                [intent["sub_specialty"]] if intent.get("sub_specialty") else []
                            )
                        }
                    },
                    # Freshness boost: recently-verified records get a small lift.
                    {
                        "range": {
                            "last_verified_at": {
                                "gte": "now-30d",
                                "boost": 1.2,
                            }
                        }
                    },
                ],
            }
        },
        # Don't ship the full embedding back; it's large and we already
        # used it.
        "_source": {"excludes": ["embedding"]},
    }

    try:
        response = client.search(index=OPENSEARCH_INDEX, body=query)
    except Exception as exc:
        logger.exception("Candidate retrieval search failed: %s", exc)
        return []

    hits = response.get("hits", {}).get("hits", [])
    candidates = []
    for h in hits:
        source = h["_source"]
        # OpenSearch returns a single _score that combines must + should.
        # For the LTR, we want the vector and BM25 contributions
        # separately. A production deployment uses OpenSearch's
        # "explain" API, named queries, or a custom script_score to
        # decompose the score; the example approximates by re-running
        # a tiny BM25-only query per candidate, which is not what you'd
        # want at scale.
        candidates.append({
            "provider_id":            source["provider_id"],
            "name":                   source.get("name", ""),
            "canonical_specialty":    source.get("canonical_specialty"),
            "specialty_label":        source.get("specialty_label", ""),
            "sub_specialties":        source.get("sub_specialties", []) or [],
            "languages":              source.get("languages", []) or [],
            "gender":                 source.get("gender"),
            "accepts_new_patients":   source.get("accepts_new_patients"),
            "network_tier":           source.get("network_tier"),
            "is_safety_net_provider": source.get("is_safety_net_provider", False),
            "practice_id":            source.get("practice_id", ""),
            "address":                source.get("address", ""),
            "phone":                  source.get("phone", ""),
            "location":               source.get("location"),
            "last_verified_at":       source.get("last_verified_at"),
            # Combined hybrid score from OpenSearch. We split it
            # heuristically below into vector_score and bm25_score
            # for the feature vector.
            "_combined_score": float(h["_score"]),
        })

    logger.info(
        "Retrieved %d candidates for plan_tier=%s specialty=%s",
        len(candidates),
        patient_context.get("plan_tier"),
        intent.get("specialty_label"),
    )
    return candidates
```

---

## Step 4: Join Personalization Features for the Ranker

*The pseudocode calls this `join_features(candidates, patient_context)`. The candidates from Step 3 are relevant in aggregate. The personalized ranker needs more signal: distance from the patient, prior visits to this provider, panel openness, freshness penalties, language match. This step builds the feature vector each candidate will be scored on.*

```python
def join_features(
    candidates: list,
    patient_context: dict,
    intent: dict,
) -> list:
    """
    Build a per-candidate feature vector for the LTR scorer.

    For each candidate, attach the features the ranker consumes:
      - vector_score, bm25_score:  retrieval signals from Step 3
      - specialty_fit:             how well the candidate matches the parsed intent
      - language_match:            patient's preferred language is supported
      - prior_visits:              has the patient seen this provider before
      - distance_miles:            haversine distance from patient location
      - panel_openness:            accepts new patients (if the patient is new)
      - freshness_penalty:         demote stale records
      - network_tier_rank:         preferred=2, standard=1, lower=0
      - is_safety_net_provider:    flag for the fairness re-ranker
    """
    if not candidates:
        return []

    # Pull the patient's prior-visit map. In production this is a
    # claims-derived feature stored as "visits_by_provider" -> {provider_id: count}.
    # New members may have nothing here; treat missing as zero.
    claims_summary = patient_context.get("claims_summary", {}) or {}
    visits_by_provider = claims_summary.get("visits_by_provider", {}) or {}

    preferred_language = patient_context.get("preferred_language", "en")
    search_location = patient_context.get("search_location") or {}
    search_lat = search_location.get("lat")
    search_lon = search_location.get("lon")

    # Whether the patient is "new to network" vs. an existing member.
    # New members can't book closed panels; existing members may already
    # be paneled and can sometimes book panels marked "closed."
    is_new_patient = patient_context.get("is_new_to_network", False)

    feature_rows = []
    for c in candidates:
        # Distance: haversine from search location to provider location.
        # Fall back to a large number if either is missing so the ranker
        # naturally deprioritizes (rather than crashing).
        provider_loc = c.get("location") or {}
        provider_lat = provider_loc.get("lat")
        provider_lon = provider_loc.get("lon")
        if (search_lat is not None and search_lon is not None
                and provider_lat is not None and provider_lon is not None):
            distance_miles = _haversine_miles(
                float(search_lat), float(search_lon),
                float(provider_lat), float(provider_lon),
            )
        else:
            distance_miles = 999.0

        # Specialty fit: 1.0 if the candidate's canonical specialty
        # matches the parsed intent, 0.5 if a sub-specialty matches,
        # 0.0 otherwise. A learned ranker would learn fancier
        # match-quality features.
        specialty_fit = 0.0
        if intent.get("specialty") and c.get("canonical_specialty") == intent["specialty"]:
            specialty_fit = 1.0
        elif intent.get("sub_specialty") and intent["sub_specialty"] in c.get("sub_specialties", []):
            specialty_fit = 0.5

        # Prior visits: a strong positive feature when the patient has
        # claims history with this provider.
        prior_visits = float(visits_by_provider.get(c["provider_id"], 0))

        # Language match: 1 if the provider speaks the patient's
        # preferred language, 0 otherwise.
        language_match = 1.0 if preferred_language in (c.get("languages") or []) else 0.0

        # Panel openness: 1 if accepting new patients OR the patient
        # already has prior visits with this provider; 0 if a new
        # patient is searching and the panel is closed.
        if c.get("accepts_new_patients"):
            panel_openness = 1.0
        elif prior_visits > 0:
            panel_openness = 1.0
        elif is_new_patient:
            panel_openness = 0.0
        else:
            # Existing member, panel marked closed but not searching as new.
            # Half-credit; the ranker can demote naturally.
            panel_openness = 0.5

        # Freshness penalty from the verification timestamp.
        freshness_penalty = _compute_freshness_penalty(c.get("last_verified_at"))

        # Network-tier rank (higher = preferred-tier).
        tier_to_rank = {"preferred": 2, "standard": 1, "out_of_network": 0}
        network_tier_rank = tier_to_rank.get(c.get("network_tier", "standard"), 1)

        # Decompose the OpenSearch combined score into rough
        # vector vs. BM25 components for the feature vector. This is
        # a simplification; production systems either use named queries
        # to get separate scores, or compute the BM25 component via
        # script_score. The example uses the combined score as
        # vector_score and a small constant as bm25_score so the LTR
        # weights still produce reasonable rankings.
        vector_score = float(c.get("_combined_score", 0.0))
        bm25_score = 0.0  # see comment above

        feature_rows.append({
            # Identifying fields (carried through to result assembly).
            "provider_id":           c["provider_id"],
            "name":                  c["name"],
            "specialty_label":       c["specialty_label"],
            "address":               c["address"],
            "phone":                 c["phone"],
            "languages":             c["languages"],
            "network_tier":          c["network_tier"],
            "accepts_new_patients":  c["accepts_new_patients"],
            "is_safety_net_provider": c["is_safety_net_provider"],
            "practice_id":           c["practice_id"],
            "sub_specialties":       c["sub_specialties"],
            # Features the LTR consumes.
            "features": {
                "vector_similarity":     vector_score,
                "bm25_score":            bm25_score,
                "specialty_fit":         specialty_fit,
                "language_match":        language_match,
                "prior_visits":          prior_visits,
                "panel_openness":        panel_openness,
                "freshness_penalty":     freshness_penalty,
                "distance_penalty":      distance_miles,
                "network_tier_bonus":    1.0 if c.get("network_tier") == "preferred" else 0.0,
                "safety_net_bonus":      1.0 if c.get("is_safety_net_provider") else 0.0,
            },
            "distance_miles": round(distance_miles, 2),
            "applied_factors": [],   # populated by the fairness re-ranker
        })

    return feature_rows
```

---

## Step 5: Score and Rank with the LTR Model

*The pseudocode calls this `rank(feature_rows, model)`. In production, this is `xgboost.Booster.predict()` against a trained `XGBoost-Ranker` (objective `rank:pairwise` or `rank:ndcg`) or a LightGBM `lambdarank` model. The example uses a hand-tuned linear scoring function with the same input feature vector. The shape is identical; the only difference is where the weights come from. Once you have a labeled dataset (patient context, candidate set, observed engagement), swap this for `model.predict()` and the rest of the pipeline doesn't change.*

```python
def rank(feature_rows: list, weights: dict | None = None) -> list:
    """
    Score and sort candidates with a linear LTR.

    Drop-in replacement when you have a trained XGBoost-Ranker:

        booster = xgboost.Booster()
        booster.load_model("ranker.bst")
        X = build_feature_matrix(feature_rows, FEATURE_ORDER)
        scores = booster.predict(X)

    Then attach `scores[i]` back to `feature_rows[i].relevance_score`
    and sort. The feature vector this function consumes is the same
    feature vector you'd train the booster on.

    The hand-tuned linear scorer below is honest about its limits:
    weights were picked by hand from intuition, not learned from data.
    Use it as a placeholder while you build the labeled dataset.
    """
    if not feature_rows:
        return []

    weights = weights or LTR_WEIGHTS
    for row in feature_rows:
        f = row["features"]
        # Linear combination. Each feature contributes weight * value.
        score = (
            weights["vector_similarity"]   * f["vector_similarity"] +
            weights["bm25_score"]          * f["bm25_score"] +
            weights["specialty_fit"]       * f["specialty_fit"] +
            weights["language_match"]      * f["language_match"] +
            weights["prior_visits"]        * min(f["prior_visits"], 5.0) +  # cap to avoid runaway
            weights["panel_openness"]      * f["panel_openness"] +
            weights["freshness_penalty"]   * f["freshness_penalty"] +
            weights["distance_penalty"]    * f["distance_penalty"] +
            weights["network_tier_bonus"]  * f["network_tier_bonus"] +
            weights["safety_net_bonus"]    * f["safety_net_bonus"]
        )
        row["relevance_score"] = score
        # Per-feature contributions for explainability. With XGBoost,
        # this is replaced by SHAP values; with the linear scorer,
        # contribution = weight * value. Either way, the structure is
        # the same: a per-feature account of why this row got this score.
        row["feature_contributions"] = {
            name: round(weights[name] * f[name], 4)
            for name in weights.keys()
        }

    # Sort descending by relevance.
    feature_rows.sort(key=lambda r: r["relevance_score"], reverse=True)
    return feature_rows
```

---

## Step 6: Re-Rank for Fairness and Diversity

*The pseudocode calls this `fairness_rerank(sorted_rows, patient_context, policy)`. The raw LTR output is locally optimal but may produce structurally bad outcomes (a handful of providers dominating impressions, safety-net providers buried, near-duplicates clustering). The fairness re-ranker enforces explicit policy constraints. These are policy decisions calibrated by network operations and compliance, not data science.*

```python
def fairness_rerank(sorted_rows: list) -> list:
    """
    Apply policy constraints to the raw LTR output.

    Three policies, in order:
      1. Exposure caps: dampen providers who have been overexposed in
         the rolling window. Pulls live counts from the exposure
         aggregates table.
      2. Safety-net floor: ensure at least one safety-net-flagged
         provider appears in the top N when a high-fit candidate exists.
      3. Near-duplicate suppression: dampen the second of two providers
         from the same practice with overlapping specialties.
    """
    if not sorted_rows:
        return []

    # ---- 1. Exposure caps ----
    # Pull the rolling impressions for each provider in the candidate
    # set in one batched lookup. Production caches this aggressively
    # (the values change slowly and the read load on the hot path is high).
    provider_ids = [r["provider_id"] for r in sorted_rows]
    exposure_map = _batch_get_exposure(provider_ids)
    for row in sorted_rows:
        exposure = exposure_map.get(row["provider_id"], {})
        impressions_top_3 = float(exposure.get("impressions_at_top_3_24h", 0))
        if impressions_top_3 > POLICY_MAX_TOP3_IMPRESSIONS_24H:
            row["relevance_score"] *= POLICY_EXPOSURE_DAMPENING_FACTOR
            row["applied_factors"].append(
                f"exposure_cap_top3: x{POLICY_EXPOSURE_DAMPENING_FACTOR}"
            )

    # ---- 2. Safety-net floor ----
    # If the top N has no safety-net provider, look for the highest-relevance
    # safety-net candidate that meets fit and freshness thresholds, and
    # promote it into the top N. Strict thresholds prevent surfacing
    # poor-quality safety-net data in the name of fairness.
    if POLICY_SAFETY_NET_FLOOR_ENABLED:
        # Re-sort by current score so the "top N" reflects the post-exposure
        # cap ordering before we look.
        sorted_rows.sort(key=lambda r: r["relevance_score"], reverse=True)
        top_n = sorted_rows[:POLICY_SAFETY_NET_TOP_N]
        if not any(r["is_safety_net_provider"] for r in top_n):
            best_safety_net = None
            for r in sorted_rows:
                if not r["is_safety_net_provider"]:
                    continue
                f = r["features"]
                if (f["specialty_fit"] >= POLICY_SAFETY_NET_MIN_FIT
                        and f["freshness_penalty"] <= POLICY_SAFETY_NET_MAX_FRESHNESS_PENALTY):
                    best_safety_net = r
                    break
            if best_safety_net is not None:
                # Promote into the top N by setting score to top_n[-1].score + epsilon.
                # The reorder is small in practice (one row moves up).
                if top_n:
                    target_score = top_n[-1]["relevance_score"] + 0.0001
                    if best_safety_net["relevance_score"] < target_score:
                        best_safety_net["relevance_score"] = target_score
                        best_safety_net["applied_factors"].append(
                            "safety_net_floor: promoted_to_top_n"
                        )

    # ---- 3. Near-duplicate suppression ----
    # If two providers share a practice_id and have substantial
    # specialty overlap, dampen the second-ranked. Patients want
    # choice, not copies of the same office.
    sorted_rows.sort(key=lambda r: r["relevance_score"], reverse=True)
    seen_practices = {}
    for i, row in enumerate(sorted_rows):
        practice = row.get("practice_id") or ""
        if not practice:
            continue
        if practice in seen_practices:
            prior = seen_practices[practice]
            if _specialty_overlap(row, prior) >= POLICY_NEAR_DUPLICATE_OVERLAP_THRESHOLD:
                row["relevance_score"] *= POLICY_NEAR_DUPLICATE_DAMPENING_FACTOR
                row["applied_factors"].append(
                    f"near_duplicate_dampened: x{POLICY_NEAR_DUPLICATE_DAMPENING_FACTOR}"
                )
        else:
            seen_practices[practice] = row

    # Final resort after all the score adjustments.
    sorted_rows.sort(key=lambda r: r["relevance_score"], reverse=True)
    return sorted_rows


def _batch_get_exposure(provider_ids: list) -> dict:
    """
    Batch lookup of rolling exposure aggregates.

    Returns {provider_id: {"impressions_at_top_3_24h": int, ...}}.
    Missing providers default to empty dict.
    """
    if not provider_ids:
        return {}

    table = dynamodb.Table(EXPOSURE_TABLE)
    # DynamoDB BatchGetItem caps at 100 keys per request; chunk if needed.
    out = {}
    chunk_size = 100
    for i in range(0, len(provider_ids), chunk_size):
        chunk = provider_ids[i:i + chunk_size]
        try:
            response = dynamodb.batch_get_item(RequestItems={
                EXPOSURE_TABLE: {
                    "Keys": [{"provider_id": pid} for pid in chunk]
                }
            })
            for item in response.get("Responses", {}).get(EXPOSURE_TABLE, []):
                out[item["provider_id"]] = item
        except Exception as exc:
            logger.warning("Exposure batch lookup failed: %s", exc)
            # Safe default: no exposure data, no caps fire. The cohort
            # dashboard should alarm if this is happening at meaningful rates.
            continue
    return out


def _specialty_overlap(row_a: dict, row_b: dict) -> float:
    """
    Jaccard overlap of canonical + sub-specialties between two providers.

    Returns 1.0 if both are the same specialty with the same sub-specs,
    0.0 if they share nothing.
    """
    set_a = set([row_a.get("specialty_label", "")] + list(row_a.get("sub_specialties", []) or []))
    set_a.discard("")
    set_b = set([row_b.get("specialty_label", "")] + list(row_b.get("sub_specialties", []) or []))
    set_b.discard("")
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0
```

---

## Step 7: Assemble Results With Explanations and Log the Search

*The pseudocode calls this `assemble_and_log(reranked_rows, patient_context, intent, top_n=10)`. Each result returned to the UI carries a short rationale built from the ranking features. The search log is the join point for engagement attribution and the basis of the ranker's training data. Verbatim query strings get sent to a separate audit channel so the search-log table doesn't accumulate unstructured PHI.*

```python
def assemble_and_log(
    reranked_rows: list,
    patient_context: dict,
    intent: dict,
    query_string: str,
    top_n: int = TOP_N_TO_RETURN,
) -> dict:
    """
    Build the response payload, log the search, emit impression events.

    Three things happen:
      1. Top N results are assembled with structured + natural-language
         explanations.
      2. A search-log row is written. Cohort-level features only;
         the raw query goes to a separate audit channel.
      3. One impression event per result is emitted to Kinesis.
    """
    search_id = str(uuid.uuid4())
    now_iso = datetime.datetime.now(timezone.utc).isoformat()
    patient_id = patient_context["patient_id"]

    top = reranked_rows[:top_n]

    # ---- Build per-result explanations ----
    # Structured explanation first; LLM-rendered natural-language string
    # second. The structured fields are what an audit log or member
    # services rep needs; the natural-language string is for the patient.
    results = []
    for row in top:
        f = row["features"]
        structured_explanation = {
            "specialty_fit":      f["specialty_fit"],
            "language_match":     bool(f["language_match"]),
            "prior_visits":       int(f["prior_visits"]),
            "distance_miles":     row["distance_miles"],
            "network_tier":       row["network_tier"],
            "freshness_penalty":  round(f["freshness_penalty"], 3),
            "applied_factors":    list(row["applied_factors"]),
        }
        nl_explanation = _render_explanation(structured_explanation, row, intent, patient_context)
        results.append({
            "provider_id":            row["provider_id"],
            "name":                   row["name"],
            "specialty":              row["specialty_label"],
            "address":                row["address"],
            "distance_miles":         row["distance_miles"],
            "languages":              row["languages"],
            "accepting_new_patients": row["accepts_new_patients"],
            "network_tier":           row["network_tier"],
            "phone":                  row["phone"],
            "relevance_score":        round(row["relevance_score"], 4),
            "explanation":            nl_explanation,
            "structured_explanation": structured_explanation,
        })

    # ---- Persist the search log ----
    # Only cohort features. The intent specialty + filters are kept
    # because they're the structured representation of the query and
    # the ranker training pipeline needs them. The verbatim query
    # string does NOT go here.
    search_log_table = dynamodb.Table(SEARCH_LOG_TABLE)
    search_log_table.put_item(Item={
        "search_id":  search_id,
        "patient_id": patient_id,
        "timestamp":  now_iso,
        "intent": {
            "intent_type":     intent.get("intent_type"),
            "specialty":       intent.get("specialty"),
            "specialty_label": intent.get("specialty_label"),
            "filters":         intent.get("filters", {}),
        },
        "feature_snapshot": {
            "plan_id":            patient_context.get("plan_id", "unknown"),
            "plan_tier":          patient_context.get("plan_tier", "unknown"),
            "preferred_language": patient_context.get("preferred_language", "unknown"),
            "search_radius":     Decimal(str(patient_context.get("search_radius_miles", DEFAULT_SEARCH_RADIUS_MI))),
            "is_new_to_network": bool(patient_context.get("is_new_to_network", False)),
        },
        "ranked_provider_ids": [r["provider_id"] for r in results],
        "ranked_scores":       [Decimal(str(r["relevance_score"])) for r in results],
        "model_version":       LTR_MODEL_VERSION,
        "policy_version":      POLICY_VERSION,
    })

    # ---- Verbatim query goes to the separate audit channel ----
    # In a real deployment this is a different table (or a CloudWatch
    # Logs group with stricter access) with shorter retention and
    # narrower IAM scope. Joining query <-> patient_id requires
    # going through both stores, which is itself logged. The example
    # writes to a side log group via CloudWatch logger; production
    # should use a purpose-built audit store.
    logger.info(
        "search_query_audit",
        extra={
            "search_id":    search_id,
            "timestamp":    now_iso,
            "query_string": query_string,
            # Note: no patient_id here. Joining requires going through
            # the search-log table by search_id, which is auditable.
        },
    )

    # ---- Emit impression events ----
    for rank_pos, result in enumerate(results, start=1):
        try:
            kinesis_client.put_record(
                StreamName=ENGAGEMENT_STREAM_NAME,
                # Partition by patient_id so a single patient's events
                # stay on the same shard and arrive in order.
                PartitionKey=patient_id,
                Data=json.dumps({
                    "event_type":  "search_impression",
                    "search_id":   search_id,
                    "provider_id": result["provider_id"],
                    "patient_id":  patient_id,
                    "position":    rank_pos,
                    "timestamp":   now_iso,
                }).encode("utf-8"),
            )
        except Exception as exc:
            # Don't block the patient-facing response on impression
            # publish failure. Log + metric, move on.
            logger.warning(
                "Impression event publish failed for provider_id=%s: %s",
                result["provider_id"], exc,
            )

    return {
        "search_id":      search_id,
        "patient_id":     patient_id,
        "timestamp":      now_iso,
        "model_version":  LTR_MODEL_VERSION,
        "policy_version": POLICY_VERSION,
        "intent":         intent,
        "results":        results,
    }


def _render_explanation(
    structured: dict,
    row: dict,
    intent: dict,
    patient_context: dict,
) -> str:
    """
    Build a short natural-language explanation from the structured features.

    The example uses a deterministic template so the demo doesn't burn
    Bedrock calls per result. Production batches one LLM call per page
    of results (or caches by structured-explanation hash) to render
    fluent localized explanations. The deterministic version below is
    actually a fine fallback for when the LLM is degraded.
    """
    parts = []
    if intent.get("specialty_label"):
        parts.append(intent["specialty_label"])
    if structured["language_match"]:
        lang = patient_context.get("preferred_language", "your language")
        parts.append(f"speaks {_language_name(lang)}")
    if structured["prior_visits"] > 0:
        parts.append(
            f"you've seen this provider {structured['prior_visits']} "
            f"time{'s' if structured['prior_visits'] != 1 else ''} before"
        )
    parts.append(f"{structured['distance_miles']:.1f} miles away")
    if structured["network_tier"] == "preferred":
        parts.append("in your plan's preferred network")
    if row.get("accepts_new_patients"):
        parts.append("accepting new patients")
    if row.get("is_safety_net_provider"):
        parts.append("federally qualified health center")
    return ". ".join(p[0].upper() + p[1:] if p else "" for p in parts) + "."


def _language_name(code: str) -> str:
    """Map ISO 639-1 codes to display names for the explanation."""
    return {
        "en": "English",
        "es": "Spanish",
        "vi": "Vietnamese",
        "zh": "Chinese",
        "ko": "Korean",
        "tl": "Tagalog",
        "ar": "Arabic",
    }.get(code, code)
```

---

## Step 8: Capture Engagement and Feed Back Into Training and Data Quality

*The pseudocode calls this `process_engagement_event(event)`. A separate Lambda consumes the engagement stream, joins each event back to the search log, applies position-bias correction, and updates two things: the engagement event store (ranker training data) and the rolling exposure aggregates (fairness re-ranker input). A `directory_complaint_filed` event is high-priority operational signal that demotes the offending provider until a re-verification pass.*

```python
def process_engagement_event(event: dict) -> None:
    """
    Process one engagement event from the Kinesis stream.

    Expected event shape:
      {
        "event_type":  "search_impression" | "search_click" |
                       "provider_call_initiated" | "appointment_booked" |
                       "directory_complaint_filed",
        "search_id":   "<uuid>",
        "provider_id": "prv-<npi>",
        "patient_id":  "pat-<id>",
        "position":    int (1-based),
        "timestamp":   ISO 8601,
        "complaint_reason": optional string for directory_complaint_filed
      }
    """
    search_id = event.get("search_id")
    event_type = event.get("event_type")
    provider_id = event.get("provider_id")
    patient_id = event.get("patient_id")

    if not (search_id and event_type and provider_id and patient_id):
        logger.warning("Malformed engagement event; dropping: %s", event)
        return

    # ---- Look up the originating search ----
    search_log_table = dynamodb.Table(SEARCH_LOG_TABLE)
    search_response = search_log_table.get_item(Key={"search_id": search_id})
    search_record = search_response.get("Item")
    if search_record is None:
        logger.warning("Engagement event for unknown search_id=%s; dropping", search_id)
        return

    # ---- Validate provider was in the ranked list ----
    if provider_id not in (search_record.get("ranked_provider_ids") or []):
        logger.warning(
            "Event provider_id=%s not in search %s ranked list; dropping",
            provider_id, search_id,
        )
        return

    # ---- Validate patient identity ----
    # Same integrity boundary as Recipes 4.1 and 4.2: a buggy or
    # malicious producer that submits events with a different patient_id
    # would pollute another patient's ranker training data and
    # personalization signal.
    if patient_id != search_record.get("patient_id"):
        logger.warning(
            "Event patient_id=%s does not match search %s; dropping",
            patient_id, search_id,
        )
        return

    # Position from the search log; the event-supplied position is for
    # client-side telemetry but we trust the server-side record.
    try:
        position_in_results = (search_record["ranked_provider_ids"]
                               .index(provider_id) + 1)
    except ValueError:
        logger.warning("Provider id not findable in ranked list; dropping")
        return

    # ---- Persist the raw event ----
    # event_id is constructed so duplicate Kinesis deliveries converge
    # to the same row.
    event_id = f"{search_id}:{provider_id}:{event_type}:{event.get('timestamp', '')}"
    events_table = dynamodb.Table(ENGAGEMENT_EVENTS_TABLE)
    events_table.put_item(Item={
        "event_id":     event_id,
        "search_id":    search_id,
        "provider_id":  provider_id,
        "patient_id":   patient_id,
        "event_type":   event_type,
        "position":     position_in_results,
        "timestamp":    event.get("timestamp", datetime.datetime.now(timezone.utc).isoformat()),
        "feature_snapshot": search_record.get("feature_snapshot", {}),
        "complaint_reason": event.get("complaint_reason"),
    })

    # ---- Position-bias correction ----
    # Patients click position 1 more than position 10 regardless of
    # quality. Naive "did they click" labels reward whatever the current
    # ranker is already doing. The position-based propensity model is a
    # simple and well-studied way to debias.
    propensity = _position_propensity(position_in_results)
    base_reward = _event_to_reward(event_type)
    bias_corrected_reward = (base_reward / propensity) if propensity > 0 else 0.0
    # bias_corrected_reward is what the offline training pipeline reads;
    # we attach it to the event row so the trainer doesn't have to
    # recompute on every read. The example just logs it.
    logger.debug(
        "Bias-corrected reward for %s position=%d: %.3f",
        event_type, position_in_results, bias_corrected_reward,
    )

    # ---- Update rolling exposure aggregates ----
    # Increment counters atomically so concurrent events don't trample
    # each other.
    exposure_table = dynamodb.Table(EXPOSURE_TABLE)
    if event_type == "search_impression":
        update_expr = "ADD impressions_total_24h :one"
        expr_values = {":one": Decimal("1")}
        if position_in_results <= 3:
            update_expr += ", impressions_at_top_3_24h :one"
        exposure_table.update_item(
            Key={"provider_id": provider_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
        )
    elif event_type == "search_click":
        exposure_table.update_item(
            Key={"provider_id": provider_id},
            UpdateExpression="ADD clicks_total_24h :one",
            ExpressionAttributeValues={":one": Decimal("1")},
        )
    elif event_type == "provider_call_initiated":
        exposure_table.update_item(
            Key={"provider_id": provider_id},
            UpdateExpression="ADD calls_initiated_24h :one",
            ExpressionAttributeValues={":one": Decimal("1")},
        )
    elif event_type == "appointment_booked":
        exposure_table.update_item(
            Key={"provider_id": provider_id},
            UpdateExpression="ADD appointments_booked_24h :one",
            ExpressionAttributeValues={":one": Decimal("1")},
        )

    # ---- Special handling: directory complaints ----
    # A "directory_complaint_filed" event is gold-standard data quality
    # signal. The patient is telling us the directory sent them somewhere
    # wrong. Demote the provider in OpenSearch immediately and queue a
    # re-verification pass; the catalog ingestion pipeline picks it up.
    if event_type == "directory_complaint_filed":
        logger.warning(
            "Directory complaint for provider_id=%s reason=%s; demoting",
            provider_id, event.get("complaint_reason"),
        )
        try:
            client = _get_opensearch_client()
            client.update(
                index=OPENSEARCH_INDEX,
                id=provider_id,
                body={
                    "doc": {
                        "status": "demoted",
                        "freshness_score": 0.1,
                    }
                },
            )
        except Exception as exc:
            logger.error("Failed to demote provider %s in index: %s", provider_id, exc)
        # Increment complaint counter on exposure aggregates so the
        # ops dashboard sees the spike.
        exposure_table.update_item(
            Key={"provider_id": provider_id},
            UpdateExpression="ADD complaints_filed_24h :one",
            ExpressionAttributeValues={":one": Decimal("1")},
        )
        cloudwatch_client.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{
                "MetricName": "ghost_provider_complaint",
                "Dimensions": [
                    {"Name": "specialty",
                     "Value": _safe_specialty_for_metric(provider_id)},
                ],
                "Value": 1.0,
                "Unit":  "Count",
            }],
        )

    # ---- Cohort-sliced engagement metric ----
    # Slice by event_type, language cohort, and position band. Don't
    # add high-cardinality dimensions like patient_id; CloudWatch
    # custom-metric pricing punishes that.
    feature_snapshot = search_record.get("feature_snapshot") or {}
    language = feature_snapshot.get("preferred_language", "unknown")
    position_band = _position_band(position_in_results)

    cloudwatch_client.put_metric_data(
        Namespace=METRIC_NAMESPACE,
        MetricData=[{
            "MetricName": "search_engagement",
            "Dimensions": [
                {"Name": "event_type",    "Value": event_type},
                {"Name": "language",      "Value": str(language)},
                {"Name": "position_band", "Value": position_band},
            ],
            "Value": 1.0,
            "Unit":  "Count",
        }],
    )

    logger.info(
        "Processed %s for patient=%s provider=%s search=%s position=%d",
        event_type, patient_id, provider_id, search_id, position_in_results,
    )


def _position_propensity(position: int) -> float:
    """
    Position-based propensity model (a click model with a single
    free parameter per position). Larger propensity = patients are
    more likely to look at this position regardless of quality.

    These numbers are from the literature for web search; for
    healthcare provider directory you'd estimate them empirically
    from your own A/B click data using e.g. randomized swap experiments.
    """
    propensities = {
        1: 1.00, 2: 0.70, 3: 0.50, 4: 0.40, 5: 0.32,
        6: 0.27, 7: 0.23, 8: 0.20, 9: 0.18, 10: 0.16,
    }
    return propensities.get(position, 0.10)


def _event_to_reward(event_type: str) -> float:
    """
    Map event types to reward magnitudes for ranker training.

    Booking and call signals are stronger than clicks; complaints are
    negative signals; impressions are zero-reward by themselves
    (impression-only IS the negative-class signal in pairwise LTR
    training data).
    """
    return {
        "search_impression":          0.0,
        "search_click":               1.0,
        "provider_call_initiated":    2.0,
        "appointment_booked":         5.0,
        "directory_complaint_filed": -5.0,
    }.get(event_type, 0.0)


def _position_band(position: int) -> str:
    if position <= 3:  return "top_3"
    if position <= 5:  return "top_5"
    if position <= 10: return "top_10"
    return "below_10"


def _safe_specialty_for_metric(provider_id: str) -> str:
    """
    Look up the provider's specialty for the metric dimension.

    Falls back to "unknown" on any error so the metric still emits.
    Production caches this lookup.
    """
    try:
        provider_table = dynamodb.Table(PROVIDER_TABLE)
        response = provider_table.get_item(Key={"provider_id": provider_id})
        item = response.get("Item") or {}
        return item.get("specialty_label", "unknown")[:50]  # CloudWatch dim limit
    except Exception:
        return "unknown"
```

---

## Building the Patient Context

The pipeline expects a `patient_context` dict with a fixed shape. In production this is assembled by a small helper that reads from the patient profile table and joins in claims-derived features. The example version is below; it lives outside the seven main steps because it's plumbing rather than a recipe stage.

```python
def build_patient_context(
    patient_id: str,
    search_address: str | None = None,
    search_radius_miles: float | None = None,
) -> dict | None:
    """
    Assemble the patient context object that drives personalization.

    Sources:
      - patient-profile table (plan, language, preferences, claims_summary)
      - geocoding for the search location (if address supplied)

    Returns None if the patient profile is missing; caller should
    decline to run a search rather than fall back to defaults.
    """
    patient_table = dynamodb.Table(PATIENT_TABLE)
    response = patient_table.get_item(Key={"patient_id": patient_id})
    profile = response.get("Item")
    if profile is None:
        logger.warning("No patient profile for %s; declining to search", patient_id)
        return None

    # Search location: explicit address overrides the address on file.
    location_text = search_address or profile.get("home_address", "")
    search_location = _geocode_address(location_text) if location_text else None

    # Convert the profile's claims_summary (which may have Decimals)
    # back to floats for use inside the ranker; DynamoDB-side stays
    # Decimal but the ranker is happier with floats.
    claims_summary = profile.get("claims_summary") or {}
    visits_by_provider_raw = claims_summary.get("visits_by_provider") or {}
    visits_by_provider = {k: float(v) for k, v in visits_by_provider_raw.items()}

    return {
        "patient_id":          patient_id,
        "plan_id":             profile.get("plan_id", "unknown"),
        "plan_tier":           profile.get("plan_tier", "standard"),
        "preferred_language":  profile.get("preferred_language", "en"),
        "is_new_to_network":   bool(profile.get("is_new_to_network", False)),
        "search_location":     search_location,
        "search_radius_miles": float(search_radius_miles or DEFAULT_SEARCH_RADIUS_MI),
        "claims_summary": {
            "visits_by_provider": visits_by_provider,
        },
        "locale": profile.get("locale", "en-US"),
    }
```

---

## Putting It All Together

Here's the full inference pipeline assembled into a single callable function. In production, ingestion (Step 1) is a Step Functions workflow triggered by EventBridge, the inference path (Steps 2-7) is one Lambda behind API Gateway, and engagement processing (Step 8) is a separate Lambda consuming the Kinesis stream. The example chains them together so you can trace one search end-to-end.

```python
def search_providers(
    patient_id: str,
    query_string: str,
    search_address: str | None = None,
    search_radius_miles: float | None = None,
) -> dict:
    """
    Run the full search pipeline for one patient query.

    Steps 2-7 from the recipe:
      2. parse_query
      3. retrieve_candidates
      4. join_features
      5. rank
      6. fairness_rerank
      7. assemble_and_log

    Step 1 (on_provider_event) is the offline ingestion path; Step 8
    (process_engagement_event) is the offline feedback path. Both are
    exercised separately in the demo below.
    """
    start = time.time()

    # ---- Build patient context ----
    print(f"Building patient context for {patient_id}...")
    patient_context = build_patient_context(patient_id, search_address, search_radius_miles)
    if patient_context is None:
        return {"status": "PATIENT_NOT_FOUND", "patient_id": patient_id}
    print(
        f"  plan_tier={patient_context['plan_tier']} "
        f"language={patient_context['preferred_language']} "
        f"radius={patient_context['search_radius_miles']}mi "
        f"new_to_network={patient_context['is_new_to_network']}"
    )

    # ---- Step 2: parse query ----
    print(f"Step 2: Parsing query '{query_string}'...")
    intent = parse_query(query_string, patient_context["preferred_language"])
    print(
        f"  intent_type={intent['intent_type']} "
        f"specialty={intent.get('specialty_label')} "
        f"filters={intent['filters']}"
    )

    # ---- Step 3: retrieve candidates ----
    print("Step 3: Retrieving candidates...")
    candidates = retrieve_candidates(intent, patient_context)
    print(f"  {len(candidates)} candidates")
    if not candidates:
        return {
            "status":     "NO_CANDIDATES",
            "patient_id": patient_id,
            "intent":     intent,
            "results":    [],
        }

    # ---- Step 4: join features ----
    print("Step 4: Joining personalization features...")
    feature_rows = join_features(candidates, patient_context, intent)

    # ---- Step 5: rank ----
    print("Step 5: Scoring with LTR (linear placeholder)...")
    ranked = rank(feature_rows)
    print(f"  Top before re-rank:")
    for i, r in enumerate(ranked[:5], 1):
        print(f"    {i}. {r['name']} (score={r['relevance_score']:.3f}, "
              f"specialty={r['specialty_label']}, distance={r['distance_miles']}mi)")

    # ---- Step 6: fairness re-rank ----
    print("Step 6: Applying fairness + diversity re-rank...")
    reranked = fairness_rerank(ranked)
    print(f"  Top after re-rank:")
    for i, r in enumerate(reranked[:5], 1):
        factors = ", ".join(r["applied_factors"]) if r["applied_factors"] else "none"
        print(f"    {i}. {r['name']} (score={r['relevance_score']:.3f}, "
              f"factors={factors})")

    # ---- Step 7: assemble + log ----
    print("Step 7: Assembling results, logging search, emitting impressions...")
    response = assemble_and_log(reranked, patient_context, intent, query_string)

    elapsed_ms = int((time.time() - start) * 1000)
    response["processing_time_ms"] = elapsed_ms
    print(f"  search_id={response['search_id']} ({elapsed_ms} ms)")
    return response


# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Seeds five synthetic providers across two specialties
    #   2. Seeds a synthetic patient with a Spanish preference and a
    #      claims-derived prior visit
    #   3. Runs the full search pipeline once
    #   4. Simulates a click and a directory complaint to exercise Step 8

    print("=" * 70)
    print("Seeding sample providers...")
    print("=" * 70)
    sample_providers = [
        {
            "npi": "1000000001",
            "name": "Dr. Maria Hernandez, MD",
            "specialty_source": "Family Medicine",
            "sub_specialties": ["pediatric primary care"],
            "languages": ["en", "es"],
            "gender": "female",
            "accepts_new_patients": True,
            "network_tier": "preferred",
            "is_safety_net": False,
            "practice_id": "prac-001",
            "address": "1244 Elm St, Springfield, IL",
            "phone": "555-0140",
            "services": "primary care, preventive medicine, well-child visits",
            "bio": "Family physician serving Springfield since 2008.",
            "source_system": "credentialing",
        },
        {
            "npi": "1000000002",
            "name": "Dr. Carlos Reyes, DO",
            "specialty_source": "Family Medicine",
            "sub_specialties": [],
            "languages": ["en", "es"],
            "gender": "male",
            "accepts_new_patients": True,
            "network_tier": "preferred",
            "is_safety_net": False,
            "practice_id": "prac-002",
            "address": "808 Oak Ave, Springfield, IL",
            "phone": "555-0188",
            "services": "primary care, chronic disease management",
            "bio": "Osteopathic family physician.",
            "source_system": "credentialing",
        },
        {
            "npi": "1000000003",
            "name": "Springfield Community Health Center",
            "specialty_source": "Family Medicine",
            "sub_specialties": [],
            "languages": ["en", "es", "vi"],
            "gender": None,
            "accepts_new_patients": True,
            "network_tier": "preferred",
            "is_safety_net": True,
            "practice_id": "prac-003",
            "address": "20 River Rd, Springfield, IL",
            "phone": "555-0099",
            "services": "primary care, sliding-fee scale, multilingual support",
            "bio": "Federally Qualified Health Center serving the community.",
            "source_system": "self_attestation",
        },
        {
            "npi": "1000000004",
            "name": "Dr. James Smith, MD",
            "specialty_source": "Family Medicine",
            "sub_specialties": [],
            "languages": ["en"],
            "gender": "male",
            "accepts_new_patients": False,
            "network_tier": "preferred",
            "is_safety_net": False,
            "practice_id": "prac-004",
            "address": "55 Main St, Springfield, IL",
            "phone": "555-0222",
            "services": "primary care",
            "bio": "Established practice; accepting existing patients only.",
            "source_system": "credentialing",
        },
        {
            "npi": "1000000005",
            "name": "Dr. Emily Chen, MD",
            "specialty_source": "Pediatrics",
            "sub_specialties": ["adolescent medicine"],
            "languages": ["en", "zh"],
            "gender": "female",
            "accepts_new_patients": True,
            "network_tier": "preferred",
            "is_safety_net": False,
            "practice_id": "prac-005",
            "address": "302 Maple Dr, Springfield, IL",
            "phone": "555-0311",
            "services": "pediatric primary care, adolescent medicine",
            "bio": "Pediatrician specializing in adolescent and developmental care.",
            "source_system": "credentialing",
        },
    ]
    for p in sample_providers:
        result = on_provider_event(p)
        print(f"  Indexed: {result['provider_id']} (status={result['status']})")

    # Wait for OpenSearch to make the new docs searchable.
    print("\nWaiting for OpenSearch refresh...")
    time.sleep(2)

    print("\n" + "=" * 70)
    print("Seeding synthetic patient...")
    print("=" * 70)
    patient_id = "pat-synthetic-001"
    patient_table = dynamodb.Table(PATIENT_TABLE)
    patient_table.put_item(Item={
        "patient_id":         patient_id,
        "plan_id":            "plan-bronze-2026",
        "plan_tier":          "preferred",
        "preferred_language": "es",
        "is_new_to_network":  False,
        "home_address":       "100 Center St, Springfield, IL",
        "locale":             "es-US",
        # Claims-derived prior visits to one of the sample providers.
        "claims_summary": {
            "visits_by_provider": {
                "prv-1000000001": Decimal("3"),
            },
        },
    })
    print(f"  Seeded {patient_id}")

    print("\n" + "=" * 70)
    print("Running search pipeline...")
    print("=" * 70)
    response = search_providers(
        patient_id=patient_id,
        query_string="family doctor spanish",
        search_address="100 Center St, Springfield, IL",
        search_radius_miles=15,
    )

    print("\n" + "=" * 70)
    print("Search response:")
    print("=" * 70)
    print(json.dumps(response, indent=2, default=str))

    if response.get("results"):
        print("\n" + "=" * 70)
        print("Simulating engagement events...")
        print("=" * 70)
        first_result = response["results"][0]
        search_id = response["search_id"]
        now_iso = datetime.datetime.now(timezone.utc).isoformat()

        # Simulate a click on the top result.
        process_engagement_event({
            "event_type":  "search_click",
            "search_id":   search_id,
            "provider_id": first_result["provider_id"],
            "patient_id":  patient_id,
            "position":    1,
            "timestamp":   now_iso,
        })
        print(f"  click event processed for {first_result['provider_id']}")

        # Simulate a directory complaint about a different result, if one exists.
        if len(response["results"]) > 1:
            second_result = response["results"][1]
            process_engagement_event({
                "event_type":       "directory_complaint_filed",
                "search_id":        search_id,
                "provider_id":      second_result["provider_id"],
                "patient_id":       patient_id,
                "position":         2,
                "timestamp":        now_iso,
                "complaint_reason": "phone_number_disconnected",
            })
            print(f"  complaint event processed for {second_result['provider_id']}")

        # Verify the exposure aggregates updated.
        exposure_table = dynamodb.Table(EXPOSURE_TABLE)
        exposure = exposure_table.get_item(
            Key={"provider_id": first_result["provider_id"]}
        ).get("Item", {})
        print(f"\nExposure aggregates for {first_result['provider_id']}:")
        print(f"  clicks_total_24h = {exposure.get('clicks_total_24h')}")
```

---

## The Gap Between This and Production

Run this end-to-end against a populated OpenSearch index, a seeded DynamoDB pair, and a Location Service place index and you'll see the pattern: providers indexed, patient context assembled, query parsed, candidates retrieved, features joined, ranked, re-ranked, results returned with explanations, and engagement events flowing back. The distance between this and a real health-plan deployment is significant. Here's where it lives.

**Provider data ingestion is its own engineering project.** The example treats the provider event as a clean dict with an `npi` field. In reality, provider data arrives from credentialing systems on a multi-week cycle (in proprietary formats), claims feeds daily (in 837/835 EDI formats), self-attestation portals on demand, and third-party network rosters periodically. Each source has its own data model, its own update cadence, and its own quality issues. Build the ingestion as a Step Functions workflow with explicit Lambdas for match, validate, annotate, embed, and index, each routing failures to a DLQ keyed on `(provider_id, stage, failure_reason)`. Underinvest here and the catalog accumulates ghost providers faster than the search ranker can compensate.

**NPPES verification is a recurring task, not a one-time check.** The example checks `validation["specialty_known"]` against an in-memory dict. Production verifies NPI status against the [NPPES Public API](https://npiregistry.cms.hhs.gov/), and does so on a schedule (nightly for high-priority providers, weekly for the rest). When NPPES reports a deactivated NPI, the catalog must demote or remove the provider. This is the one external API the ingestion pipeline reliably calls, and it's worth wiring up with proper error handling and rate limiting; NPPES is a public service and not designed to absorb burst traffic from every health plan in the country.

**Phone reachability is a periodic sweep.** The example checks phone format. Production sweeps the catalog quarterly with an automated dialer (or a third-party validation service) and demotes providers whose phone numbers bounce, are disconnected, or route to numbers unrelated to the practice. Ghost-provider complaints are the leading indicator that a phone-number sweep is overdue. Treat phone-reachability rate as a top-line catalog quality metric.

**Embedding model versioning.** When you upgrade Titan v2 to v3 (or to a different family), every embedding in the index becomes incompatible with new query embeddings. The migration: re-embed the entire catalog under the new model, build a parallel index, run shadow queries to validate retrieval quality doesn't regress, switch traffic, retire the old index. Plan for at least one of these per year. Pin the model ID in config (Parameter Store / AppConfig) and never silently roll it forward.

**Geocoding caching.** The example calls Location Service inline at ingestion time. Provider addresses change rarely; cache the geocoded coordinates on the provider record and only re-geocode when the address changes. Patient addresses also change rarely; cache the geocoded coordinates on the patient profile. Without caching, you're paying Location Service per search, which adds up at 500K searches per month.

**Cold-start patient handling.** New members have no claims history; the `prior_visits` feature is zero everywhere. The example doesn't compensate. Production cold-start strategies: a brief onboarding step that captures stated preferences (preferred language confirmation, gender preference if any, geographic radius), demographic-cohort defaults for ranking weights, and explicit fallbacks for unknown values. Apply the same fairness considerations as Recipe 4.1's preface; cohort defaults that systematically misrank certain populations are a fairness problem dressed as a UX problem.

**OpenSearch query decomposition.** The example uses the OpenSearch `_score` as a single combined number and hand-codes vector_score = combined_score, bm25_score = 0. That's a simplification. Production uses OpenSearch [named queries](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/searching.html) or per-clause `script_score` to extract the vector and BM25 contributions separately, so the LTR feature vector has accurate per-component scores. The hand-tuned weights in the example partially compensate; with separated scores, a learned ranker can actually learn the right contribution per component.

**LTR training pipeline.** The example uses a hand-tuned linear scorer. Real LTR uses XGBoost-Ranker (`rank:pairwise` or `rank:ndcg`) or LightGBM `lambdarank` trained on a labeled (patient_context, candidate, judgment) dataset. Building that dataset honestly is the hard part: position-bias-corrected click data, supplemented by a small set of human-graded query-document pairs, supplemented by hard rule-based labels (out-of-network = irrelevant, panel-closed = irrelevant for new-patient queries). SageMaker Training Jobs run the periodic retrain; a SageMaker Endpoint or a Lambda layer hosts the model. Train weekly initially; daily training overfits to noise at typical volumes.

**Position-bias correction at training time.** The example computes a bias-corrected reward at engagement-attribution time and logs it; the ranker training pipeline is not implemented. Production-grade LTR training does the bias correction inside the loss function (counterfactual learning to rank, IPS-weighted ranker). Wiring that into the SageMaker training script is real work and worth scoping early.

**Provider quality scores are sensitive.** The example doesn't include HEDIS or CMS Star ratings. Real plans often have these at the practice level (rarely at the individual-provider level with statistical confidence). Adding them as a ranker feature is tempting and dangerous: small-sample noise gets surfaced as authoritative quality signal, providers contest the methodology, and members make decisions on inputs that shouldn't be trusted. If you do add quality scores, do so with a clinical-quality team, document the data sources and refresh cadence, gate display behind explicit thresholds, and explain what the scores mean in the patient-facing UI. Or skip them entirely and use the surface area for next-available-appointment instead.

**Exposure-cap calibration.** The example has hardcoded thresholds. Real numbers come from network operations: the cap depends on the size of the network, the geographic distribution, the volume of searches, and the tolerance for impression concentration. Start with conservative caps, monitor the distribution of impressions per provider, and tighten as you have data. Re-calibrate quarterly. The cap that's correct on day one will be wrong on day 90 as the catalog and search volume change.

**Safety-net floor governance.** The "promote a safety-net provider into the top N" rule is a written policy, not a hardcoded threshold. The policy needs criteria for which provider categories qualify (FQHC, community health center, Ryan White, Medicaid-managed-care provider), what fit thresholds apply, and how the policy is reviewed annually. Audit logs need to record when the floor fired and which provider was promoted, so a compliance review can confirm the policy is being applied as intended. The example writes `applied_factors` onto each row; production routes those into a dedicated audit channel.

**Verbatim query string handling.** The example logs the raw query string via the standard logger. In production, the audit channel is its own log group (or a purpose-built audit table) with stricter access controls, KMS encryption with a key only the audit team uses, and shorter retention (30-90 days, depending on policy). Joining query string back to patient_id requires going through both the audit log (by search_id) and the search log (by patient_id), which is itself a logged action.

**Index creation in code is a smell.** The `_ensure_index_exists` helper is convenient for the demo but should not exist in production code. Index settings (mappings, k-NN parameters, refresh interval, replica count, fielddata, doc_values) belong in infrastructure-as-code so they're versioned, reviewable, and reproducible. Application code that owns index creation will eventually create an inconsistent index on a corner-case deployment and the inconsistency will be invisible until retrieval quality degrades.

**Fault tolerance and DLQs.** The example logs and continues on Kinesis publish failures, OpenSearch failures, and Location Service failures. Production needs explicit failure handling at each integration point: (a) API Gateway -> search Lambda gets an SQS DLQ on the function, with a CloudWatch alarm on DLQ depth and a documented replay-from-logs runbook; (b) Step Functions -> ingestion Lambdas use `Catch` to route to per-stage failure queues; (c) Kinesis -> attribution Lambda uses an event source mapping `OnFailure` destination pointing to SQS, with a CloudWatch alarm on DLQ depth. The third one is the most insidious: an attribution Lambda silently dropping engagement events leaves the ranker training data incomplete and the exposure aggregates wrong, with no observable symptom until a cohort dashboard regresses.

**API Gateway, throttling, and authentication.** The example calls `search_providers(patient_id, query)` directly. Production fronts the recommender with API Gateway, requires authenticated callers (Cognito, Lambda authorizer, or IAM-signed requests for service-to-service traffic), and applies per-caller rate limits. Patient-portal callers and member-services callers should have separate authorizers and separate quota buckets. WAF in front of API Gateway is a reasonable extra layer for bot protection. The Lambda authorizer must validate that the caller is allowed to act on the requested `patient_id`; do not trust the upstream service to enforce that boundary.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), Kinesis (interface), CloudWatch Logs (interface), Location Service (interface), and the OpenSearch domain. All six DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the patient_profile, search_log, and engagement_events tables. A clinical or compliance audit will eventually ask "who searched for what on this date" and you need to answer definitively.

**Bedrock cost and latency budget.** The example calls Bedrock twice per search: once for query parsing (Step 2), once for the embedding (also Step 2 / Step 3). Query parsing for fast-path queries skips the LLM entirely; only fuzzy free-text queries hit the model. Production deployments often pre-cache embeddings for common search inputs (the top 100 specialty + filter combinations cover most volume) and skip the LLM call when the fast path matches. Monitor Bedrock invocation count and spend in CloudWatch and set per-account quota alarms.

**Multilingual query parsing.** The example's LLM prompt is in English; the LLM's quality on non-English queries varies by model. For each supported language, run a parsing-quality regression suite (a curated set of (query, expected intent) pairs in that language) before launching, and route low-confidence parses to the BM25-only fallback rather than letting a low-quality structured intent drive the rest of the pipeline. Add per-language NDCG dashboards from day one.

**DynamoDB Decimal gotcha.** DynamoDB does not accept Python floats. The example uses `Decimal(str(value))` everywhere it persists numbers; going through `str` avoids the binary-precision issues that `Decimal(float_value)` introduces. The pattern is correct in this example, but the trap is real and shows up the moment you add a feature that persists a model confidence, an embedding magnitude, or any other floating-point value. Wrap floats in Decimal at the boundary and forget about it.

**OpenSearch refresh interval.** The example sets `refresh=False` on the index call and sleeps 2 seconds in the demo to let docs become searchable. Production indexes set the refresh interval explicitly (often 5-30 seconds for ingestion-heavy workloads) to balance ingestion throughput against search-result freshness. The default 1-second refresh is fine for development and expensive at scale.

**Snapshotting and disaster recovery.** OpenSearch domain backups are not free. Snapshot to S3 daily so a corruption, accidental delete, or misconfigured ingestion run is recoverable. Cross-region replication if your RTO/RPO requires it. The provider catalog is a critical asset; rebuilding from source feeds takes days or weeks, so the index backup matters.

**Cohort fairness monitoring with humans in the loop.** The architecture emits cohort-sliced metrics. A dashboard nobody looks at is useless. Establish a quarterly review with a cross-functional committee (data science, network operations, compliance, member services). Watch for: language cohorts with consistently lower NDCG (catalog gap or parsing gap), provider exposure distributions that drift toward concentration (re-rank policy needs tightening), ghost-provider complaint rates that vary by region (catalog quality gap). Each finding produces an action item with an owner; the action items close the loop.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the query parser, freshness-penalty math, fairness re-rank logic, and feature-vector construction; integration tests against a test OpenSearch index with a small synthetic catalog and synthetic patients per language and plan tier; regression tests confirming hard filters are never bypassed even when scores prefer a disqualified candidate; and load tests at expected burst rates. Never use real PHI in non-production environments. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic FHIR patients with realistic claims patterns; the [NPPES public registry](https://npiregistry.cms.hhs.gov/) seeds an NPI/specialty/address index for development.

**Provider-side correctness.** The example has no path for a provider (or a credentialing team) to correct their own directory entry. Production should: surface a "report inaccuracy" link on each search result that emits a `directory_complaint_filed` event with structured reason codes; maintain a provider self-service portal where contracted providers can review and correct their own entries (changes flow back through the validation pipeline); periodically email contracted providers with their current directory record and require a sign-off. Each pathway is its own small feature, but together they materially improve catalog accuracy. Without them, the directory's correctness depends entirely on the upstream credentialing-system data, which is rarely complete.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.3: Provider Directory Search Optimization](chapter04.03-provider-directory-search-optimization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
