# Recipe 13.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 13.8. It shows one way you could translate those concepts into working Python using boto3 and the Neptune graph client. It is not production-ready. The real UMLS has millions of concepts and complex relationship semantics that this example only scratches the surface of. Think of it as a sketch that helps you understand the shape of the solution. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and the Neptune graph client:

```bash
pip install boto3 gremlinpython requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `neptune-db:*` scoped to your Neptune cluster
- `s3:GetObject` and `s3:PutObject` on your terminology buckets
- `elasticache:Connect` for the Redis cache cluster

You'll also need network access to your Neptune cluster endpoint (Neptune lives in a VPC, so your code must run inside that VPC or have connectivity via VPN/peering).

For the UMLS data, you need a free license from the National Library of Medicine. Register at https://uts.nlm.nih.gov/uts/ and download the Metathesaurus files.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the whole system. Terminology file formats, Neptune connection details, and the relationship type mappings all live here so they're easy to find and update.

```python
import os
import csv
import json
import hashlib
import logging
from io import StringIO
from datetime import datetime, timezone

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# boto3 retry configuration. Neptune and S3 can throttle under load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

# Neptune connection. Neptune uses a WebSocket-based protocol for Gremlin
# and an HTTP endpoint for openCypher. We'll use the HTTP/openCypher endpoint
# because the query syntax is more readable for this use case.
NEPTUNE_ENDPOINT = os.environ.get(
    "NEPTUNE_ENDPOINT", "your-neptune-cluster.cluster-xxxx.us-east-1.neptune.amazonaws.com"
)
NEPTUNE_PORT = int(os.environ.get("NEPTUNE_PORT", "8182"))

# S3 bucket for terminology files (raw downloads and processed load files).
TERMINOLOGY_BUCKET = os.environ.get("TERMINOLOGY_BUCKET", "my-terminology-data")

# Redis cache configuration. ElastiCache endpoint for caching normalization results.
REDIS_HOST = os.environ.get("REDIS_HOST", "my-cache-cluster.xxxx.use1.cache.amazonaws.com")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

# Cache TTL in seconds. 24 hours is reasonable because terminology releases
# happen at most monthly. After a new load, you'd selectively invalidate.
CACHE_TTL_SECONDS = 86400

# Relationship type mappings. UMLS uses short codes (REL field) to describe
# how two concepts relate. We translate these into human-readable edge labels
# for the graph.
UMLS_REL_TO_EDGE_TYPE = {
    "SY": "synonym_of",         # Synonymy: same meaning
    "RO": "related_to",         # Other related: associated but not equivalent
    "RB": "broader_than",       # Broader: source is more general than target
    "RN": "narrower_than",      # Narrower: source is more specific than target
    "PAR": "parent_of",         # Hierarchical parent
    "CHD": "child_of",          # Hierarchical child
    "AQ": "allowed_qualifier",  # Qualifier relationship
    "QB": "qualified_by",       # Qualified by
}

# Terminologies we care about. UMLS contains 200+ source vocabularies,
# but for healthcare concept normalization, these are the ones that matter.
TARGET_TERMINOLOGIES = {
    "SNOMEDCT_US",  # SNOMED CT (US Edition)
    "ICD10CM",      # ICD-10-CM (diagnosis codes)
    "ICD10PCS",     # ICD-10-PCS (procedure codes)
    "LNC",          # LOINC (lab observations)
    "RXNORM",       # RxNorm (medications)
    "CPT",          # CPT (outpatient procedures)
    "HCPCS",        # HCPCS (supplies, equipment)
}

# Neptune bulk load CSV headers. These define the schema for the graph.
NODE_CSV_HEADERS = [
    "~id", "~label", "code:String", "display:String",
    "terminology:String", "version:String", "status:String",
    "semantic_type:String", "cui:String"
]

EDGE_CSV_HEADERS = [
    "~id", "~from", "~to", "~label", "relationship_type:String",
    "confidence:Double", "provenance:String", "effective_date:Date"
]
```

---

## Step 1: Parse UMLS Terminology Files

*The pseudocode calls this `ingest_terminology()`. UMLS distributes its data in RRF (Rich Release Format), which is pipe-delimited with specific column positions. This step parses MRCONSO.RRF (concepts) and MRREL.RRF (relationships) into structured Python objects.*

```python
def parse_umls_concepts(mrconso_path: str) -> list[dict]:
    """
    Parse UMLS MRCONSO.RRF to extract concepts from our target terminologies.

    MRCONSO.RRF is the core concept file in UMLS. Each row represents one
    "atom" (a specific name for a concept in a specific source vocabulary).
    Multiple atoms can share a CUI (Concept Unique Identifier), meaning
    they represent the same clinical idea in different terminologies.

    The file is pipe-delimited with these columns (among others):
      0: CUI    - Concept Unique Identifier
      1: LAT    - Language
      4: LUI    - Lexical Unique Identifier
      6: ISPREF - Is preferred presentation (Y/N)
      11: SAB   - Source Abbreviation (terminology name)
      12: TTY   - Term Type (e.g., PT=Preferred Term)
      13: CODE  - Code in the source terminology
      14: STR   - String (the display name)
      16: SUPPRESS - Suppression flag (O=obsolete, E=non-human, Y=suppressed)

    We filter to:
      - English language only (LAT = "ENG")
      - Our target terminologies only
      - Non-suppressed atoms only
      - Preferred terms where available (for the display name)

    Args:
        mrconso_path: Local file path to MRCONSO.RRF

    Returns:
        List of concept dictionaries ready for graph loading.
    """
    concepts = []
    seen = set()  # Track (terminology, code) pairs to avoid duplicates

    logger.info("Parsing MRCONSO.RRF from %s", mrconso_path)

    with open(mrconso_path, "r", encoding="utf-8") as f:
        for line in f:
            fields = line.strip().split("|")

            # Filter: English only.
            if fields[1] != "ENG":
                continue

            # Filter: target terminologies only.
            terminology = fields[11]
            if terminology not in TARGET_TERMINOLOGIES:
                continue

            # Filter: skip suppressed/obsolete atoms.
            suppress = fields[16]
            if suppress in ("O", "E", "Y"):
                continue

            cui = fields[0]
            code = fields[13]
            display = fields[14]
            term_type = fields[12]

            # Deduplicate: keep only one entry per (terminology, code).
            # Prefer the Preferred Term (PT) for the display name.
            dedup_key = (terminology, code)
            if dedup_key in seen:
                continue

            # Only take preferred terms or, if none available, any term.
            # PT = Preferred Term in most vocabularies.
            if term_type not in ("PT", "PF", "SY"):
                continue

            seen.add(dedup_key)
            concepts.append({
                "cui": cui,
                "code": code,
                "display": display,
                "terminology": terminology,
                "status": "active",
            })

    logger.info("Parsed %d concepts from %d target terminologies",
                len(concepts), len(TARGET_TERMINOLOGIES))
    return concepts


def parse_umls_relationships(mrrel_path: str, valid_cuis: set) -> list[dict]:
    """
    Parse UMLS MRREL.RRF to extract relationships between concepts.

    MRREL.RRF contains relationships between concepts. Each row describes
    a directed relationship from one concept to another.

    Key columns:
      0: CUI1   - Source concept CUI
      2: REL    - Relationship type (SY, RO, RB, RN, PAR, CHD, etc.)
      3: RELA   - Relationship attribute (more specific type)
      4: CUI2   - Target concept CUI
      7: SAB    - Source of the relationship
      10: SUPPRESS - Suppression flag

    We filter to:
      - Relationships where both CUIs are in our concept set
      - Non-suppressed relationships
      - Relationship types we care about

    Args:
        mrrel_path: Local file path to MRREL.RRF
        valid_cuis: Set of CUIs that exist in our concept set (from parse_umls_concepts)

    Returns:
        List of relationship dictionaries ready for graph loading.
    """
    relationships = []

    logger.info("Parsing MRREL.RRF from %s", mrrel_path)

    with open(mrrel_path, "r", encoding="utf-8") as f:
        for line in f:
            fields = line.strip().split("|")

            cui1 = fields[0]
            rel = fields[2]
            cui2 = fields[4]
            source = fields[7]
            suppress = fields[10] if len(fields) > 10 else ""

            # Skip suppressed relationships.
            if suppress in ("O", "Y"):
                continue

            # Skip if either concept isn't in our set.
            if cui1 not in valid_cuis or cui2 not in valid_cuis:
                continue

            # Skip relationship types we don't map.
            if rel not in UMLS_REL_TO_EDGE_TYPE:
                continue

            # Skip self-referential relationships.
            if cui1 == cui2:
                continue

            relationships.append({
                "source_cui": cui1,
                "target_cui": cui2,
                "relationship_type": UMLS_REL_TO_EDGE_TYPE[rel],
                "provenance": f"UMLS_{source}",
            })

    logger.info("Parsed %d relationships", len(relationships))
    return relationships
```

---

## Step 2: Build Neptune Bulk Load Files

*The pseudocode calls this `build_graph_load_files()`. Neptune's bulk loader reads CSV files from S3 with specific header conventions. The `~id`, `~from`, `~to`, and `~label` columns are reserved by Neptune for node IDs, edge endpoints, and labels.*

```python
def generate_node_id(terminology: str, code: str) -> str:
    """
    Generate a deterministic, unique node ID from terminology and code.

    We use a hash to keep IDs short and consistent. The same terminology + code
    always produces the same ID, which makes loads idempotent: reloading the
    same data doesn't create duplicate nodes.
    """
    raw = f"{terminology}:{code}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def generate_edge_id(from_id: str, to_id: str, rel_type: str) -> str:
    """
    Generate a deterministic edge ID from source, target, and relationship type.
    Same logic as node IDs: idempotent and collision-resistant.
    """
    raw = f"{from_id}->{to_id}:{rel_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_node_csv(concepts: list[dict], version: str) -> str:
    """
    Build the Neptune bulk load CSV for concept nodes.

    Each concept becomes one row. The ~id column is the deterministic hash,
    ~label is always "Concept" (our node type), and the remaining columns
    are properties stored on the node.

    Args:
        concepts: List of concept dicts from parse_umls_concepts()
        version: The UMLS release version (e.g., "2025AB")

    Returns:
        CSV content as a string, ready to upload to S3.
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(NODE_CSV_HEADERS)

    for concept in concepts:
        node_id = generate_node_id(concept["terminology"], concept["code"])
        writer.writerow([
            node_id,                    # ~id
            "Concept",                  # ~label
            concept["code"],            # code:String
            concept["display"],         # display:String
            concept["terminology"],     # terminology:String
            version,                    # version:String
            concept["status"],          # status:String
            "",                         # semantic_type:String (populated separately from MRSTY)
            concept["cui"],             # cui:String
        ])

    return output.getvalue()


def build_edge_csv(concepts: list[dict], relationships: list[dict]) -> str:
    """
    Build the Neptune bulk load CSV for relationship edges.

    This creates two types of edges:
    1. Cross-terminology equivalence edges (concepts sharing a CUI)
    2. Explicit UMLS relationships (from MRREL.RRF)

    The cross-terminology links are the heart of normalization: they connect
    the same clinical idea across different coding systems.

    Args:
        concepts: List of concept dicts (need CUI to group by)
        relationships: List of relationship dicts from parse_umls_relationships()

    Returns:
        CSV content as a string, ready to upload to S3.
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(EDGE_CSV_HEADERS)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # First: create cross-terminology equivalence edges.
    # Group concepts by CUI. Concepts sharing a CUI represent the same
    # clinical meaning in different terminologies.
    cui_groups = {}
    for concept in concepts:
        cui = concept["cui"]
        if cui not in cui_groups:
            cui_groups[cui] = []
        cui_groups[cui].append(concept)

    edge_count = 0
    for cui, group in cui_groups.items():
        # For each pair of concepts in different terminologies sharing this CUI,
        # create a bidirectional equivalence edge.
        for i, concept_a in enumerate(group):
            for concept_b in group[i + 1:]:
                if concept_a["terminology"] == concept_b["terminology"]:
                    continue  # Same terminology, skip (intra-terminology handled separately)

                from_id = generate_node_id(concept_a["terminology"], concept_a["code"])
                to_id = generate_node_id(concept_b["terminology"], concept_b["code"])
                edge_id = generate_edge_id(from_id, to_id, "equivalent_to")

                writer.writerow([
                    edge_id,            # ~id
                    from_id,            # ~from
                    to_id,              # ~to
                    "equivalent_to",    # ~label
                    "equivalent_to",    # relationship_type:String
                    0.95,               # confidence:Double (CUI-based = high confidence)
                    f"UMLS_CUI_{cui}",  # provenance:String
                    today,              # effective_date:Date
                ])
                edge_count += 1

    # Second: create edges from explicit UMLS relationships.
    # These capture hierarchical and associative relationships.
    # We need a CUI-to-node-id lookup for this.
    cui_to_nodes = {}
    for concept in concepts:
        cui = concept["cui"]
        if cui not in cui_to_nodes:
            cui_to_nodes[cui] = []
        cui_to_nodes[cui].append(
            generate_node_id(concept["terminology"], concept["code"])
        )

    for rel in relationships:
        source_nodes = cui_to_nodes.get(rel["source_cui"], [])
        target_nodes = cui_to_nodes.get(rel["target_cui"], [])

        # Create edges between all node pairs for this relationship.
        # In practice you might limit this to same-terminology pairs for
        # hierarchical relationships.
        for from_id in source_nodes[:1]:  # Limit to first node to avoid explosion
            for to_id in target_nodes[:1]:
                edge_id = generate_edge_id(from_id, to_id, rel["relationship_type"])
                writer.writerow([
                    edge_id,
                    from_id,
                    to_id,
                    rel["relationship_type"],
                    rel["relationship_type"],
                    0.85,
                    rel["provenance"],
                    today,
                ])
                edge_count += 1

    logger.info("Built %d edges (cross-terminology + explicit relationships)", edge_count)
    return output.getvalue()


def upload_load_files_to_s3(node_csv: str, edge_csv: str, version: str) -> dict:
    """
    Upload the Neptune bulk load CSV files to S3.

    Neptune's bulk loader reads directly from S3. The files must be in the
    same region as the Neptune cluster.

    Returns:
        Dict with S3 URIs for both files (needed for the bulk load API call).
    """
    node_key = f"terminology-processed/{version}/nodes.csv"
    edge_key = f"terminology-processed/{version}/edges.csv"

    s3_client.put_object(
        Bucket=TERMINOLOGY_BUCKET,
        Key=node_key,
        Body=node_csv.encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    s3_client.put_object(
        Bucket=TERMINOLOGY_BUCKET,
        Key=edge_key,
        Body=edge_csv.encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    logger.info("Uploaded load files to s3://%s/%s and %s",
                TERMINOLOGY_BUCKET, node_key, edge_key)

    return {
        "node_s3_uri": f"s3://{TERMINOLOGY_BUCKET}/{node_key}",
        "edge_s3_uri": f"s3://{TERMINOLOGY_BUCKET}/{edge_key}",
    }
```

---

## Step 3: Trigger Neptune Bulk Load

*The pseudocode describes loading data into Neptune. The Neptune bulk loader is an HTTP API on the Neptune cluster itself. You POST a load request with the S3 URI, IAM role ARN, and format details. It runs asynchronously and you poll for completion.*

```python
import requests
from requests_aws4auth import AWS4Auth

# Neptune's bulk loader uses IAM authentication via SigV4.
# This role must have access to both Neptune and the S3 bucket.
NEPTUNE_LOAD_ROLE_ARN = os.environ.get(
    "NEPTUNE_LOAD_ROLE_ARN",
    "arn:aws:iam::123456789012:role/NeptuneLoadFromS3"
)


def get_neptune_auth():
    """
    Create SigV4 auth for Neptune HTTP requests.
    Neptune uses IAM authentication, not username/password.
    """
    session = boto3.Session()
    credentials = session.get_credentials().get_frozen_credentials()
    region = session.region_name or "us-east-1"

    return AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "neptune-db",
        session_token=credentials.token,
    )


def start_bulk_load(s3_uri: str, load_type: str = "nodes") -> str:
    """
    Trigger Neptune's bulk loader to ingest a CSV file from S3.

    The bulk loader is dramatically faster than individual insert queries
    for large datasets. A full UMLS load (millions of nodes) takes minutes
    via bulk loader vs. hours via individual queries.

    Args:
        s3_uri: S3 URI of the CSV file to load
        load_type: "nodes" or "edges" (affects error handling expectations)

    Returns:
        The load ID for polling status.
    """
    url = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/loader"

    payload = {
        "source": s3_uri,
        "format": "csv",
        "iamRoleArn": NEPTUNE_LOAD_ROLE_ARN,
        "region": boto3.Session().region_name or "us-east-1",
        "failOnError": "FALSE",  # Continue loading even if some rows fail
        "parallelism": "MEDIUM",  # Balance speed vs. cluster load
        "updateSingleCardinalityProperties": "TRUE",  # Upsert behavior for existing nodes
    }

    response = requests.post(url, json=payload, auth=get_neptune_auth())
    response.raise_for_status()

    result = response.json()
    load_id = result["payload"]["loadId"]
    logger.info("Started Neptune bulk load: %s (source: %s)", load_id, s3_uri)
    return load_id


def check_load_status(load_id: str) -> dict:
    """
    Poll the Neptune bulk loader for completion status.

    Returns the full status response including:
    - overallStatus: LOAD_COMPLETED, LOAD_IN_PROGRESS, LOAD_FAILED
    - totalRecords: how many rows were processed
    - totalErrors: how many rows failed
    """
    url = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/loader/{load_id}"

    response = requests.get(url, auth=get_neptune_auth())
    response.raise_for_status()

    return response.json()["payload"]
```

---

## Step 4: Normalization Query Service

*The pseudocode calls this `normalize_concept()`. This is the API that consuming systems call. Given a code and terminology, it returns the canonical representation and all known cross-terminology mappings. Redis caching keeps latency low for repeated lookups.*

```python
import redis

# Redis client for caching normalization results.
# In production, use redis-py-cluster for ElastiCache cluster mode.
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,
    ssl=True,  # ElastiCache encryption in transit
)


def normalize_concept(
    code: str,
    terminology: str,
    target_terminologies: list[str] = None,
) -> dict:
    """
    Normalize a clinical concept: find its canonical form and all cross-terminology mappings.

    This is the primary API that consuming systems call. Given "E11" in ICD10CM,
    it returns the SNOMED equivalent, the UMLS CUI, and mappings to any other
    requested terminologies.

    The function checks Redis first (most common lookups are repeated thousands
    of times across claims and clinical data). On cache miss, it queries Neptune
    directly.

    Args:
        code: The concept code (e.g., "E11", "44054006", "2160-0")
        terminology: The source terminology (e.g., "ICD10CM", "SNOMEDCT_US", "LNC")
        target_terminologies: Which terminologies to map to. None = all available.

    Returns:
        Dict with source concept info and list of mappings with confidence scores.
    """
    if target_terminologies is None:
        target_terminologies = list(TARGET_TERMINOLOGIES)

    # Build cache key. Include target terminologies so different query scopes
    # don't collide in the cache.
    targets_key = ",".join(sorted(target_terminologies))
    cache_key = f"norm:{terminology}:{code}:{targets_key}"

    # Check cache first.
    cached = redis_client.get(cache_key)
    if cached:
        logger.info("Cache hit for %s:%s", terminology, code)
        return json.loads(cached)

    # Cache miss. Query Neptune via openCypher.
    logger.info("Cache miss for %s:%s, querying Neptune", terminology, code)
    result = query_neptune_for_mappings(code, terminology, target_terminologies)

    # Cache the result for future lookups.
    if result["status"] == "found":
        redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(result))

    return result


def query_neptune_for_mappings(
    code: str,
    terminology: str,
    target_terminologies: list[str],
) -> dict:
    """
    Query Neptune to find a concept and its cross-terminology mappings.

    Uses openCypher (Neptune's Cypher-compatible query language) to:
    1. Find the source concept node
    2. Traverse equivalence/mapping edges to other terminologies
    3. Return all mappings with confidence and provenance metadata

    Args:
        code: Source concept code
        terminology: Source terminology name
        target_terminologies: List of target terminology names

    Returns:
        Structured result with source info and mappings list.
    """
    # openCypher query: find the source node and traverse one hop to
    # find all connected concepts in target terminologies.
    query = """
        MATCH (source:Concept {code: $code, terminology: $terminology})
        OPTIONAL MATCH (source)-[r]->(target:Concept)
        WHERE target.terminology IN $targets
        AND target.status = 'active'
        RETURN source.code AS source_code,
               source.display AS source_display,
               source.terminology AS source_terminology,
               source.cui AS source_cui,
               source.semantic_type AS source_semantic_type,
               target.code AS target_code,
               target.display AS target_display,
               target.terminology AS target_terminology,
               type(r) AS rel_type,
               r.confidence AS confidence,
               r.provenance AS provenance
        ORDER BY r.confidence DESC
    """

    params = {
        "code": code,
        "terminology": terminology,
        "targets": target_terminologies,
    }

    # Execute against Neptune's openCypher endpoint.
    url = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/openCypher"
    response = requests.post(
        url,
        json={"query": query, "parameters": json.dumps(params)},
        auth=get_neptune_auth(),
    )
    response.raise_for_status()
    results = response.json().get("results", [])

    if not results:
        return {"status": "not_found", "code": code, "terminology": terminology}

    # Build the response structure.
    first_row = results[0]
    source_info = {
        "code": first_row["source_code"],
        "terminology": first_row["source_terminology"],
        "display": first_row["source_display"],
        "cui": first_row["source_cui"],
        "semantic_type": first_row["source_semantic_type"],
    }

    mappings = []
    for row in results:
        if row.get("target_code") is None:
            continue  # No mapping found (OPTIONAL MATCH returned null)
        mappings.append({
            "code": row["target_code"],
            "terminology": row["target_terminology"],
            "display": row["target_display"],
            "relationship_type": row["rel_type"],
            "confidence": row["confidence"],
            "provenance": row["provenance"],
        })

    return {
        "status": "found",
        "source": source_info,
        "mappings": mappings,
        "mapping_count": len(mappings),
        "query_timestamp": datetime.now(timezone.utc).isoformat(),
    }
```

---

## Step 5: Hierarchy Traversal for Value Set Expansion

*The pseudocode calls this `expand_value_set()`. Quality measures and CDS rules often need "all codes that represent diabetes." This requires walking the SNOMED hierarchy downward from a root concept to find all descendants, then mapping each to other terminologies.*

```python
def expand_value_set(
    root_code: str,
    terminology: str,
    max_depth: int = 5,
    include_cross_maps: bool = False,
) -> dict:
    """
    Expand a value set by traversing the terminology hierarchy downward.

    Starting from a root concept (e.g., "Diabetes mellitus" in SNOMED),
    find all descendant concepts via is-a/child-of relationships. This is
    how quality measures work: they define a root concept and include
    everything beneath it.

    Args:
        root_code: The root concept code to expand from
        terminology: Which terminology the root is in
        max_depth: Maximum hierarchy depth to traverse (prevents runaway on broad concepts)
        include_cross_maps: Whether to also map each descendant to other terminologies

    Returns:
        Dict with the root concept, all descendants, and optionally their cross-maps.
    """
    # Traverse the hierarchy downward using variable-length path matching.
    # The *1..N syntax means "follow 1 to N hops of child_of edges."
    query = f"""
        MATCH (root:Concept {{code: $root_code, terminology: $terminology}})
        OPTIONAL MATCH path = (descendant:Concept)-[:child_of*1..{max_depth}]->(root)
        WHERE descendant.status = 'active'
        AND descendant.terminology = $terminology
        RETURN root.code AS root_code,
               root.display AS root_display,
               descendant.code AS desc_code,
               descendant.display AS desc_display,
               length(path) AS depth
        ORDER BY depth ASC
    """

    params = {"root_code": root_code, "terminology": terminology}

    url = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/openCypher"
    response = requests.post(
        url,
        json={"query": query, "parameters": json.dumps(params)},
        auth=get_neptune_auth(),
    )
    response.raise_for_status()
    results = response.json().get("results", [])

    if not results:
        return {"status": "not_found", "root_code": root_code}

    # Build the expanded value set.
    concepts = [{"code": root_code, "terminology": terminology,
                 "display": results[0]["root_display"], "depth": 0}]

    for row in results:
        if row.get("desc_code") is None:
            continue
        entry = {
            "code": row["desc_code"],
            "terminology": terminology,
            "display": row["desc_display"],
            "depth": row["depth"],
        }

        # Optionally get cross-terminology mappings for each descendant.
        # Warning: this is expensive for large hierarchies. In production,
        # you'd batch these or do them lazily.
        if include_cross_maps:
            cross = normalize_concept(row["desc_code"], terminology)
            entry["cross_maps"] = cross.get("mappings", [])

        concepts.append(entry)

    return {
        "status": "expanded",
        "root": {"code": root_code, "terminology": terminology},
        "total_concepts": len(concepts),
        "max_depth_used": max_depth,
        "concepts": concepts,
    }
```

---

## Step 6: Batch Normalization for Pipeline Integration

*This step isn't in the pseudocode explicitly, but it's essential for real-world use. Analytics pipelines don't normalize one concept at a time. They have thousands of codes to translate in a single batch run. This function handles that efficiently.*

```python
def batch_normalize(
    concepts: list[dict],
    target_terminologies: list[str] = None,
) -> list[dict]:
    """
    Normalize a batch of concepts efficiently.

    Analytics pipelines often need to translate thousands of codes at once
    (e.g., all ICD-10 codes on yesterday's claims into SNOMED for CDS).
    This function handles batching with cache-first lookups to minimize
    Neptune queries.

    Args:
        concepts: List of dicts with "code" and "terminology" keys
        target_terminologies: Which terminologies to map to

    Returns:
        List of normalization results, one per input concept.
    """
    results = []

    # Separate cache hits from misses to batch the Neptune queries.
    cache_hits = []
    cache_misses = []

    for concept in concepts:
        code = concept["code"]
        terminology = concept["terminology"]
        targets = target_terminologies or list(TARGET_TERMINOLOGIES)
        targets_key = ",".join(sorted(targets))
        cache_key = f"norm:{terminology}:{code}:{targets_key}"

        cached = redis_client.get(cache_key)
        if cached:
            cache_hits.append(json.loads(cached))
        else:
            cache_misses.append(concept)

    logger.info("Batch normalize: %d cache hits, %d cache misses",
                len(cache_hits), len(cache_misses))

    # Process cache misses individually.
    # In a production system, you'd batch these into a single Neptune query
    # using UNWIND or multiple MATCH clauses to reduce round trips.
    for concept in cache_misses:
        result = normalize_concept(
            concept["code"],
            concept["terminology"],
            target_terminologies,
        )
        results.append(result)

    # Combine hits and miss results in original order.
    # (This simplified version just appends; production would maintain order.)
    all_results = cache_hits + results

    logger.info("Batch normalization complete: %d results", len(all_results))
    return all_results
```

---

## Putting It All Together

Here's the full pipeline assembled into callable functions. The ingestion pipeline runs when new terminology releases arrive. The normalization service runs continuously, serving queries from consuming systems.

```python
def run_terminology_ingestion(
    mrconso_path: str,
    mrrel_path: str,
    version: str,
) -> dict:
    """
    Full terminology ingestion pipeline: parse UMLS files, build graph load
    files, upload to S3, and trigger Neptune bulk load.

    This runs when a new UMLS release arrives (typically twice per year for
    full releases, with monthly RxNorm updates).

    Args:
        mrconso_path: Local path to MRCONSO.RRF
        mrrel_path: Local path to MRREL.RRF
        version: UMLS release version (e.g., "2025AB")

    Returns:
        Summary of what was loaded.
    """
    print(f"=== Terminology Ingestion Pipeline (version: {version}) ===")

    # Step 1: Parse concepts from MRCONSO.RRF
    print("\nStep 1: Parsing UMLS concepts...")
    concepts = parse_umls_concepts(mrconso_path)
    print(f"  Parsed {len(concepts)} concepts")

    # Collect valid CUIs for relationship filtering.
    valid_cuis = {c["cui"] for c in concepts}
    print(f"  {len(valid_cuis)} unique CUIs")

    # Step 1b: Parse relationships from MRREL.RRF
    print("\nStep 1b: Parsing UMLS relationships...")
    relationships = parse_umls_relationships(mrrel_path, valid_cuis)
    print(f"  Parsed {len(relationships)} relationships")

    # Step 2: Build Neptune bulk load CSV files.
    print("\nStep 2: Building Neptune load files...")
    node_csv = build_node_csv(concepts, version)
    edge_csv = build_edge_csv(concepts, relationships)
    print(f"  Node CSV: {len(node_csv)} bytes")
    print(f"  Edge CSV: {len(edge_csv)} bytes")

    # Step 2b: Upload to S3.
    print("\nStep 2b: Uploading to S3...")
    s3_paths = upload_load_files_to_s3(node_csv, edge_csv, version)
    print(f"  Nodes: {s3_paths['node_s3_uri']}")
    print(f"  Edges: {s3_paths['edge_s3_uri']}")

    # Step 3: Trigger Neptune bulk load.
    print("\nStep 3: Starting Neptune bulk load...")
    node_load_id = start_bulk_load(s3_paths["node_s3_uri"], "nodes")
    print(f"  Node load ID: {node_load_id}")
    print("  (Edge load should wait for node load to complete)")

    return {
        "version": version,
        "concepts_loaded": len(concepts),
        "relationships_loaded": len(relationships),
        "node_load_id": node_load_id,
        "s3_paths": s3_paths,
    }


def demo_normalization():
    """
    Demonstrate the normalization service with common healthcare concepts.
    """
    print("\n=== Concept Normalization Demo ===\n")

    # Example 1: Normalize an ICD-10 diagnosis code to SNOMED.
    print("Example 1: ICD-10 E11 (Type 2 diabetes) -> SNOMED")
    result = normalize_concept("E11", "ICD10CM", ["SNOMEDCT_US"])
    print(json.dumps(result, indent=2))

    # Example 2: Normalize a LOINC lab code.
    print("\nExample 2: LOINC 2160-0 (Creatinine) -> all terminologies")
    result = normalize_concept("2160-0", "LNC")
    print(json.dumps(result, indent=2))

    # Example 3: Expand a SNOMED value set for quality measurement.
    print("\nExample 3: Expand 'Diabetes mellitus' (SNOMED 73211009) hierarchy")
    expansion = expand_value_set("73211009", "SNOMEDCT_US", max_depth=2)
    print(f"  Found {expansion.get('total_concepts', 0)} concepts in hierarchy")

    # Example 4: Batch normalization for a claims pipeline.
    print("\nExample 4: Batch normalize a set of ICD-10 codes")
    claims_codes = [
        {"code": "E11", "terminology": "ICD10CM"},
        {"code": "I10", "terminology": "ICD10CM"},
        {"code": "J06.9", "terminology": "ICD10CM"},
        {"code": "M54.5", "terminology": "ICD10CM"},
    ]
    batch_results = batch_normalize(claims_codes, ["SNOMEDCT_US"])
    print(f"  Normalized {len(batch_results)} concepts")


if __name__ == "__main__":
    # To run the ingestion pipeline (requires UMLS files downloaded locally):
    # run_terminology_ingestion(
    #     mrconso_path="/data/umls/2025AB/META/MRCONSO.RRF",
    #     mrrel_path="/data/umls/2025AB/META/MRREL.RRF",
    #     version="2025AB",
    # )

    # To demo the normalization service (requires Neptune + Redis running):
    demo_normalization()
```

---

## The Gap Between This and Production

This example demonstrates the core patterns. It parses UMLS files, builds graph load files, queries Neptune, and caches results. But there's a significant distance between this sketch and something you'd deploy to support clinical systems. Here's where that gap lives:

**Error handling and resilience.** Every external call (Neptune, Redis, S3) can fail. Production code wraps each in try/except with specific handling for connection timeouts, throttling, and transient errors. Neptune queries can time out on complex traversals. Redis can be temporarily unavailable during failover. Your normalization service needs graceful degradation: if the cache is down, fall through to Neptune directly (slower but functional).

**Retries and backoff.** The boto3 retry config handles S3 and basic AWS calls, but Neptune HTTP queries and Redis operations need their own retry logic. Exponential backoff with jitter prevents thundering herd problems when a service recovers from an outage.

**Input validation.** This code trusts its inputs. Production validates that codes match expected patterns (ICD-10 codes follow a specific regex, SNOMED codes are numeric, LOINC codes have a specific format). Invalid inputs should return clear error responses, not crash the service or produce confusing Neptune query errors.

**Structured logging and observability.** The `print()` statements are placeholders. Production uses structured JSON logging with correlation IDs so you can trace a single normalization request through cache lookup, Neptune query, and response assembly. CloudWatch metrics on cache hit rate, query latency percentiles, and error rates are essential for operations.

**IAM least-privilege.** The Neptune IAM policy should scope to specific query actions, not `neptune-db:*`. The S3 policy should scope to the specific terminology bucket. The Redis connection should use IAM-based authentication (ElastiCache supports this) rather than open access within the VPC.

**VPC and network security.** Neptune requires VPC deployment. Your Lambda functions need VPC configuration with private subnets. Use VPC endpoints for S3 and CloudWatch to keep traffic off the public internet. Security groups should restrict Neptune access to only the Lambda security group and the Glue job security group.

**KMS encryption.** This example uses default S3 encryption. Production uses customer-managed KMS keys with key rotation enabled. Neptune encryption at rest must be enabled at cluster creation (you cannot add it later). ElastiCache encryption at rest and in-transit should both be enabled.

**Version management.** This example loads a single version. Production maintains multiple versions simultaneously (the current ICD-10 release and the previous one, because claims filed before October use the old codes). You need version-aware queries and a strategy for retiring old versions without breaking historical lookups.

**Cache invalidation.** When you load a new terminology version, which cache entries are stale? The naive approach (flush everything) causes a thundering herd on Neptune. The smart approach computes the delta (which concepts changed between versions) and selectively invalidates only affected cache keys. This requires tracking which CUIs were modified in the new release.

**Bulk query optimization.** The `batch_normalize` function processes misses one at a time. Production uses Neptune's ability to handle multiple patterns in a single query (via UNWIND in openCypher) to batch cache misses into fewer round trips. For a batch of 1,000 codes, you want 1-2 Neptune queries, not 1,000.

**UMLS licensing compliance.** UMLS data has specific redistribution restrictions. You cannot expose raw UMLS content through your API without ensuring your consumers also have UMLS licenses. Your normalization API should return your own derived mappings, not raw UMLS relationship data. Consult NLM's licensing terms.

**Testing.** There are no tests here. Production needs unit tests for the parsing logic (with sample RRF snippets), integration tests against a Neptune test cluster with known test data, and end-to-end tests that verify the full normalization path. Use synthetic terminology data for testing, never production UMLS data in CI/CD pipelines (it's too large and has licensing implications).

**Monitoring and alerting.** Set CloudWatch alarms on: Neptune query latency exceeding 100ms (p99), cache hit rate dropping below 80%, bulk load failures, and API error rate exceeding 1%. A terminology load failure means your mappings are stale, which means downstream analytics are using outdated relationships.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.8](chapter13.08-medical-concept-normalization-mapping) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
