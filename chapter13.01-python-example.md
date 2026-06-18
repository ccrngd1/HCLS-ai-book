# Recipe 13.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.1. It shows one way you could translate those graph concepts into working Python code using boto3 and Neptune's openCypher endpoint. It is not production-ready. There's no error handling, no retry logic, no connection pooling. Think of it as the sketchpad version: useful for understanding how the pieces fit together, not something you'd point at a real formulary on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for Neptune (`neptune-db:*` scoped to your cluster), S3 (`s3:GetObject` on the formulary bucket), and ElastiCache network access from your VPC.

Neptune doesn't use IAM for query authentication by default (it uses VPC-level network isolation), but if you've enabled IAM auth on your cluster, you'll need to sign requests with SigV4. This example assumes VPC network access without IAM auth for simplicity.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the whole pipeline. These constants define how we map formulary file columns to graph entities, what our Neptune endpoint looks like, and how we structure cache keys.

```python
# Neptune cluster endpoint. This is the writer endpoint for loads,
# and the reader endpoint for queries. In production, you'd use
# separate endpoints for read vs. write operations.
#
# Neptune runs inside your VPC. This code must execute from within
# the same VPC (Lambda in VPC, EC2, ECS, etc.) to reach it.
NEPTUNE_ENDPOINT = "your-neptune-cluster.cluster-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_PORT = 8182

# The openCypher HTTP endpoint on Neptune.
# Neptune exposes openCypher queries via HTTPS POST to this path.
NEPTUNE_OPENCYPHER_URL = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/openCypher"

# Redis endpoint for caching query results.
# ElastiCache Redis cluster, also inside your VPC.
REDIS_HOST = "your-redis-cluster.xxxxxxxxxxxx.use1.cache.amazonaws.com"
REDIS_PORT = 6379

# Cache TTL in seconds. 24 hours aligns with formulary update frequency.
# Formularies change quarterly with occasional mid-quarter amendments.
# Flush the cache explicitly when you load new formulary data.
CACHE_TTL_SECONDS = 86400

# S3 bucket where formulary files land.
FORMULARY_BUCKET = "my-formulary-data"

# Column positions in CMS-standard pipe-delimited formulary files.
# CMS Part D formulary files have a defined layout. Commercial plans
# often use similar structures but column positions may vary.
# Adjust these mappings for your specific file format.
FORMULARY_COLUMNS = {
    "rxnorm_cui": 0,
    "ndc": 1,
    "drug_name": 2,
    "dosage_form": 3,
    "strength": 4,
    "tier_level": 5,
    "prior_auth": 6,
    "step_therapy": 7,
    "quantity_limit": 8,
    "therapeutic_class_code": 9,
    "therapeutic_class_name": 10,
    "plan_id": 11,
    "effective_date": 12,
    "termination_date": 13,
    "alternative_drugs": 14,
}
```

---

## Step 1: Parse Formulary File

*The pseudocode calls this `parse_formulary_file(bucket, key)`. It reads a pipe-delimited formulary file from S3 and transforms each row into graph vertices (drugs, therapeutic classes) and edges (tier assignments, class memberships, restrictions, alternatives).*

```python
import boto3
import csv
import io
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")

def parse_formulary_file(bucket: str, key: str) -> tuple[list, list]:
    """
    Read a formulary file from S3 and transform it into graph-ready
    vertices and edges.

    CMS Part D formulary files are pipe-delimited text with a header row.
    Each row represents one drug-plan-tier combination. We parse each row
    into: a Drug vertex, a TherapeuticClass vertex, and edges connecting
    them (class membership, tier assignment, restrictions, alternatives).

    Args:
        bucket: S3 bucket name where formulary files land
        key:    S3 object key (path to the specific formulary file)

    Returns:
        A tuple of (vertices, edges) where:
        - vertices: list of dicts, each with id, label, and properties
        - edges: list of dicts, each with from_id, to_id, type, and properties
    """

    # Fetch the file from S3.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    # Parse as pipe-delimited CSV. CMS files use | as delimiter.
    reader = csv.reader(io.StringIO(content), delimiter="|")

    # Skip the header row.
    next(reader)

    vertices = []
    edges = []

    # Track which vertices we've already created to avoid duplicates.
    # The graph MERGE operation handles deduplication too, but skipping
    # duplicates here reduces the number of Neptune calls.
    seen_vertices = set()

    for row in reader:
        # Extract fields by column position.
        rxnorm_cui = row[FORMULARY_COLUMNS["rxnorm_cui"]].strip()
        drug_name = row[FORMULARY_COLUMNS["drug_name"]].strip()
        strength = row[FORMULARY_COLUMNS["strength"]].strip()
        dosage_form = row[FORMULARY_COLUMNS["dosage_form"]].strip()
        tier_level = row[FORMULARY_COLUMNS["tier_level"]].strip()
        prior_auth = row[FORMULARY_COLUMNS["prior_auth"]].strip()
        step_therapy = row[FORMULARY_COLUMNS["step_therapy"]].strip()
        class_code = row[FORMULARY_COLUMNS["therapeutic_class_code"]].strip()
        class_name = row[FORMULARY_COLUMNS["therapeutic_class_name"]].strip()
        plan_id = row[FORMULARY_COLUMNS["plan_id"]].strip()
        effective_date = row[FORMULARY_COLUMNS["effective_date"]].strip()
        termination_date = row[FORMULARY_COLUMNS["termination_date"]].strip()
        alternatives_raw = row[FORMULARY_COLUMNS["alternative_drugs"]].strip()

        # Use RxNorm CUI as the primary drug identifier.
        # RxNorm is the standard for drug concept normalization in US healthcare.
        drug_id = rxnorm_cui

        # Create Drug vertex (if not already seen in this file).
        if drug_id not in seen_vertices:
            vertices.append({
                "id": drug_id,
                "label": "Drug",
                "properties": {
                    "name": drug_name,
                    "strength": strength,
                    "dosage_form": dosage_form,
                    "rxnorm_cui": rxnorm_cui,
                },
            })
            seen_vertices.add(drug_id)

        # Create TherapeuticClass vertex (if not already seen).
        if class_code and class_code not in seen_vertices:
            vertices.append({
                "id": class_code,
                "label": "TherapeuticClass",
                "properties": {
                    "name": class_name,
                    "classification_system": "AHFS",
                },
            })
            seen_vertices.add(class_code)

        # Edge: Drug belongs to TherapeuticClass.
        if class_code:
            edges.append({
                "from_id": drug_id,
                "to_id": class_code,
                "type": "BELONGS_TO_CLASS",
                "properties": {"effective_date": effective_date},
            })

        # Edge: Drug is covered under this plan at this tier.
        edges.append({
            "from_id": drug_id,
            "to_id": plan_id,
            "type": "COVERED_UNDER",
            "properties": {
                "tier": int(tier_level) if tier_level.isdigit() else tier_level,
                "effective_date": effective_date,
                "termination_date": termination_date,
            },
        })

        # Edge: Prior authorization restriction (if flagged).
        if prior_auth.upper() == "Y":
            edges.append({
                "from_id": drug_id,
                "to_id": f"PA_{plan_id}_{drug_id}",
                "type": "HAS_RESTRICTION",
                "properties": {
                    "restriction_type": "PRIOR_AUTH",
                    "plan_id": plan_id,
                },
            })

        # Edge: Step therapy restriction (if flagged).
        if step_therapy.upper() == "Y":
            edges.append({
                "from_id": drug_id,
                "to_id": f"ST_{plan_id}_{drug_id}",
                "type": "HAS_RESTRICTION",
                "properties": {
                    "restriction_type": "STEP_THERAPY",
                    "plan_id": plan_id,
                },
            })

        # Edges: Therapeutic alternatives (comma-separated list of RxNorm CUIs).
        if alternatives_raw:
            for alt_id in alternatives_raw.split(","):
                alt_id = alt_id.strip()
                if alt_id:
                    edges.append({
                        "from_id": drug_id,
                        "to_id": alt_id,
                        "type": "THERAPEUTIC_ALTERNATIVE",
                        "properties": {
                            "plan_id": plan_id,
                            "source": "formulary_file",
                        },
                    })

    logger.info(
        "Parsed %d vertices and %d edges from s3://%s/%s",
        len(vertices), len(edges), bucket, key,
    )
    return vertices, edges
```

---

## Step 2: Load Graph Data into Neptune

*The pseudocode calls this `load_graph(vertices, edges, neptune_endpoint)`. It takes the parsed vertices and edges and upserts them into Neptune using openCypher MERGE statements. MERGE creates the node or edge if it doesn't exist, or updates its properties if it does.*

```python
import requests

def execute_opencypher(query: str, parameters: dict = None) -> dict:
    """
    Execute an openCypher query against Neptune's HTTP endpoint.

    Neptune exposes openCypher via HTTPS POST. You send the query as
    form data and get JSON results back. This is simpler than the Bolt
    protocol (which requires a driver library) and works fine for
    moderate query volumes.

    Args:
        query:      openCypher query string
        parameters: dict of query parameters (Neptune substitutes these safely)

    Returns:
        The JSON response from Neptune containing query results.
    """
    payload = {"query": query}
    if parameters:
        # Neptune expects parameters as a JSON string in the 'parameters' field.
        import json
        payload["parameters"] = json.dumps(parameters)

    response = requests.post(
        NEPTUNE_OPENCYPHER_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()
    return response.json()

def load_vertices(vertices: list) -> int:
    """
    Upsert vertices into Neptune using openCypher MERGE.

    MERGE is the graph equivalent of "INSERT ... ON CONFLICT UPDATE" in SQL.
    If a node with this id already exists, update its properties.
    If it doesn't exist, create it.

    Args:
        vertices: list of vertex dicts from parse_formulary_file

    Returns:
        Count of vertices processed.
    """
    for vertex in vertices:
        # Build the MERGE query dynamically based on the vertex label.
        # We match on the 'id' property (our business identifier).
        query = f"""
            MERGE (n:{vertex['label']} {{id: $id}})
            SET n.name = $name
        """

        params = {"id": vertex["id"], "name": vertex["properties"].get("name", "")}

        # Add any additional properties.
        for prop_key, prop_value in vertex["properties"].items():
            if prop_key != "name" and prop_value:
                query += f", n.{prop_key} = ${prop_key}"
                params[prop_key] = prop_value

        execute_opencypher(query, params)

    logger.info("Loaded %d vertices into Neptune", len(vertices))
    return len(vertices)

def load_edges(edges: list) -> int:
    """
    Upsert edges into Neptune using openCypher MERGE.

    Each edge connects two nodes (identified by their 'id' property)
    with a typed relationship and optional properties.

    Args:
        edges: list of edge dicts from parse_formulary_file

    Returns:
        Count of edges processed.
    """
    for edge in edges:
        # MATCH both endpoints by id, then MERGE the relationship between them.
        # MERGE on the relationship prevents duplicate edges.
        query = f"""
            MATCH (a {{id: $from_id}})
            MATCH (b {{id: $to_id}})
            MERGE (a)-[r:{edge['type']}]->(b)
            SET r += $props
        """

        params = {
            "from_id": edge["from_id"],
            "to_id": edge["to_id"],
            "props": edge["properties"],
        }

        execute_opencypher(query, params)

    logger.info("Loaded %d edges into Neptune", len(edges))
    return len(edges)

def load_graph(vertices: list, edges: list) -> dict:
    """
    Full graph load: upsert all vertices, then all edges.

    Vertices must be loaded before edges because edges reference
    nodes by id. If a node doesn't exist yet, the MATCH in the
    edge query will fail silently (no edge created).

    Args:
        vertices: list of vertex dicts
        edges:    list of edge dicts

    Returns:
        Summary dict with counts.
    """
    v_count = load_vertices(vertices)
    e_count = load_edges(edges)

    return {"vertices_loaded": v_count, "edges_loaded": e_count}
```

---

## Step 3: Query for Therapeutic Alternatives

*The pseudocode calls this `find_alternatives(drug_id, plan_id, neptune_endpoint)`. This is the core value of the graph: a single traversal that answers "what can my patient take instead, and what will it cost them?"*

```python
def find_alternatives(drug_id: str, plan_id: str) -> list:
    """
    Find therapeutic alternatives for a drug under a specific plan.

    The traversal: start at the prescribed drug, follow BELONGS_TO_CLASS
    to its therapeutic class, follow BELONGS_TO_CLASS back to other drugs
    in that class, filter by COVERED_UNDER edges for the patient's plan,
    and sort by tier (cheapest first).

    Also checks for restrictions (prior auth, step therapy) on each
    alternative so the prescriber knows upfront what's required.

    Args:
        drug_id: RxNorm CUI of the prescribed drug
        plan_id: Patient's benefit plan identifier

    Returns:
        List of alternative drugs with tier and restriction info,
        sorted by tier (lowest/cheapest first).
    """
    query = """
        MATCH (prescribed:Drug {id: $drug_id})
              -[:BELONGS_TO_CLASS]->(class:TherapeuticClass)
              <-[:BELONGS_TO_CLASS]-(alternative:Drug)
              -[coverage:COVERED_UNDER]->(plan {id: $plan_id})
        WHERE alternative.id <> $drug_id
        OPTIONAL MATCH (alternative)-[restriction:HAS_RESTRICTION]->()
        WHERE restriction.plan_id = $plan_id
        RETURN alternative.name AS drug_name,
               alternative.id AS drug_id,
               alternative.strength AS strength,
               coverage.tier AS tier,
               collect(DISTINCT restriction.restriction_type) AS restrictions
        ORDER BY coverage.tier ASC, alternative.name ASC
    """

    result = execute_opencypher(query, {"drug_id": drug_id, "plan_id": plan_id})

    # Neptune returns results in a 'results' array with column-based format.
    # Transform into a cleaner list of dicts.
    alternatives = []
    for record in result.get("results", []):
        alternatives.append({
            "drug_name": record["drug_name"],
            "drug_id": record["drug_id"],
            "strength": record["strength"],
            "tier": record["tier"],
            "restrictions": [r for r in record["restrictions"] if r],
        })

    return alternatives
```

---

## Step 4: Cache Results in Redis

*The pseudocode calls this `get_alternatives_cached(drug_id, plan_id, redis_client, neptune_endpoint)`. The same drug-plan combinations get queried repeatedly. Caching avoids hammering Neptune for every request.*

```python
import json
import redis

# Create a Redis client. This connects to your ElastiCache cluster.
# In production, use connection pooling and handle connection failures.
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

def get_alternatives_cached(drug_id: str, plan_id: str) -> list:
    """
    Get therapeutic alternatives with Redis caching.

    Cache key combines drug_id and plan_id for uniqueness.
    On cache hit, return immediately without touching Neptune.
    On cache miss, query Neptune and populate the cache.

    The 24-hour TTL aligns with formulary update frequency.
    When you load new formulary data, flush the cache explicitly
    (call invalidate_formulary_cache) rather than waiting for TTL.

    Args:
        drug_id: RxNorm CUI of the prescribed drug
        plan_id: Patient's benefit plan identifier

    Returns:
        List of alternative drugs (from cache or fresh query).
    """
    cache_key = f"formulary:alternatives:{drug_id}:{plan_id}"

    # Check cache first.
    cached = redis_client.get(cache_key)
    if cached:
        logger.info("Cache hit for %s", cache_key)
        return json.loads(cached)

    # Cache miss. Query Neptune.
    logger.info("Cache miss for %s, querying Neptune", cache_key)
    alternatives = find_alternatives(drug_id, plan_id)

    # Store in cache with TTL.
    redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(alternatives))

    return alternatives

def invalidate_formulary_cache() -> int:
    """
    Flush all formulary cache entries.

    Call this after loading new formulary data into Neptune.
    Uses Redis SCAN to find and delete all keys matching our prefix.
    SCAN is non-blocking (unlike KEYS which blocks the server).

    Returns:
        Count of cache entries deleted.
    """
    deleted = 0
    cursor = 0

    while True:
        cursor, keys = redis_client.scan(cursor, match="formulary:*", count=100)
        if keys:
            redis_client.delete(*keys)
            deleted += len(keys)
        if cursor == 0:
            break

    logger.info("Invalidated %d cache entries", deleted)
    return deleted
```

---

## Step 5: API Query Handler

*The pseudocode calls this `handle_formulary_query(request)`. It wraps the graph query in domain logic: check if the prescribed drug is already preferred, and format the response for the consuming application.*

```python
def get_drug_tier(drug_id: str, plan_id: str) -> int | None:
    """
    Look up the tier of a specific drug under a specific plan.

    Returns None if the drug is not on the formulary for this plan.
    """
    query = """
        MATCH (d:Drug {id: $drug_id})-[c:COVERED_UNDER]->(p {id: $plan_id})
        RETURN c.tier AS tier
    """

    result = execute_opencypher(query, {"drug_id": drug_id, "plan_id": plan_id})
    results = result.get("results", [])

    if not results:
        return None

    return results[0]["tier"]

def handle_formulary_query(drug_id: str, plan_id: str) -> dict:
    """
    Main API handler for formulary navigation queries.

    Accepts a drug ID and plan ID, returns one of three responses:
    - NOT_COVERED: drug isn't on the formulary, here are alternatives
    - PREFERRED: drug is already the best option in its class
    - ALTERNATIVES_AVAILABLE: cheaper options exist

    This is what your API Gateway Lambda resolver would call.

    Args:
        drug_id: RxNorm CUI of the prescribed drug
        plan_id: Patient's benefit plan identifier

    Returns:
        Structured response dict for the consuming application.
    """
    # First, check if the prescribed drug is even on the formulary.
    prescribed_tier = get_drug_tier(drug_id, plan_id)

    # Get alternatives regardless (useful for NOT_COVERED case too).
    alternatives = get_alternatives_cached(drug_id, plan_id)

    if prescribed_tier is None:
        # Drug not on formulary at all. Show alternatives.
        return {
            "status": "NOT_COVERED",
            "prescribed_drug": drug_id,
            "message": "This drug is not on the formulary for this plan.",
            "alternatives": alternatives,
        }

    # Filter to alternatives with a better (lower) tier.
    better_alternatives = [a for a in alternatives if a["tier"] < prescribed_tier]

    if not better_alternatives:
        # The prescribed drug is already the best option.
        return {
            "status": "PREFERRED",
            "prescribed_drug": drug_id,
            "tier": prescribed_tier,
            "message": "This is the preferred option in its therapeutic class.",
        }

    return {
        "status": "ALTERNATIVES_AVAILABLE",
        "prescribed_drug": drug_id,
        "prescribed_tier": prescribed_tier,
        "alternatives": better_alternatives,
        "message": "Lower-cost alternatives are available.",
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into callable functions. The load pipeline runs when new formulary data arrives. The query pipeline runs on every prescriber request.

```python
def run_formulary_load(bucket: str, key: str) -> dict:
    """
    Full formulary load pipeline: parse file, load into Neptune, flush cache.

    This is what your S3-triggered Lambda would call when a new
    formulary file lands in the inbox bucket.

    Args:
        bucket: S3 bucket name
        key:    S3 object key for the formulary file

    Returns:
        Summary of the load operation.
    """
    print(f"=== Formulary Load Pipeline ===")
    print(f"Source: s3://{bucket}/{key}")

    # Step 1: Parse the formulary file into graph entities.
    print("\nStep 1: Parsing formulary file...")
    vertices, edges = parse_formulary_file(bucket, key)
    print(f"  Parsed {len(vertices)} vertices, {len(edges)} edges")

    # Step 2: Load into Neptune.
    print("\nStep 2: Loading into Neptune...")
    load_result = load_graph(vertices, edges)
    print(f"  Loaded {load_result['vertices_loaded']} vertices, {load_result['edges_loaded']} edges")

    # Flush the cache so queries pick up the new data.
    print("\nFlushing formulary cache...")
    deleted = invalidate_formulary_cache()
    print(f"  Invalidated {deleted} cache entries")

    print("\n=== Load Complete ===")
    return {
        "source": f"s3://{bucket}/{key}",
        "vertices_loaded": load_result["vertices_loaded"],
        "edges_loaded": load_result["edges_loaded"],
        "cache_entries_invalidated": deleted,
    }

def run_formulary_query(drug_id: str, plan_id: str) -> dict:
    """
    Full query pipeline: check cache, query graph, return structured response.

    This is what your API Gateway Lambda resolver would call.

    Args:
        drug_id: RxNorm CUI of the prescribed drug
        plan_id: Patient's benefit plan identifier

    Returns:
        Structured formulary navigation response.
    """
    print(f"=== Formulary Query ===")
    print(f"Drug: {drug_id}, Plan: {plan_id}")

    result = handle_formulary_query(drug_id, plan_id)

    print(f"Status: {result['status']}")
    if result.get("alternatives"):
        print(f"Alternatives found: {len(result['alternatives'])}")
        for alt in result["alternatives"]:
            restrictions = ", ".join(alt["restrictions"]) if alt["restrictions"] else "none"
            print(f"  - {alt['drug_name']} (Tier {alt['tier']}, restrictions: {restrictions})")

    return result

# Example usage:
if __name__ == "__main__":
    # Load a formulary file (run this when new data arrives).
    # load_result = run_formulary_load(
    #     bucket="my-formulary-data",
    #     key="formulary-inbox/2026/Q2/commercial-ppo-formulary.txt",
    # )

    # Query for alternatives (run this on every prescriber request).
    query_result = run_formulary_query(
        drug_id="RX_83367",   # Atorvastatin (example RxNorm CUI)
        plan_id="PLAN_12345", # Commercial PPO plan
    )

    print("\nFull response:")
    print(json.dumps(query_result, indent=2))
```

---

## The Gap Between This and Production

This example demonstrates the shape of the solution. Here's what separates it from something you'd deploy to a health system:

**Error handling.** Every Neptune query and Redis call can fail. Network timeouts, connection resets, Neptune throttling under load. A production system wraps each external call in try/except with specific handling for connection errors, timeout errors, and Neptune-specific error codes. If Neptune is unreachable, you need a graceful degradation path (return a "service unavailable" response, not a stack trace).

**Connection management.** This example creates a new HTTP connection to Neptune for every query. In production, you'd use connection pooling (via `requests.Session()` at minimum, or the `neptune-python-utils` library for Bolt protocol connections). Lambda cold starts with Neptune connections add 1-2 seconds of latency. Use provisioned concurrency for the query Lambda, or keep a warm connection pool in a Fargate task.

**Bulk loading.** The vertex-by-vertex and edge-by-edge loading approach works for small formularies but is painfully slow for large ones (50K+ drugs). Neptune's bulk loader API accepts CSV files from S3 and loads them in parallel, orders of magnitude faster than individual MERGE statements. For quarterly full reloads, stage your parsed data as Neptune-format CSV in S3 and use the bulk loader. Reserve individual MERGE for mid-quarter incremental updates.

**Input validation.** This code trusts that the formulary file is well-formed. Real formulary files have missing fields, malformed dates, duplicate rows, and occasionally corrupted characters. Validate every row before creating graph entities. Log and skip malformed rows rather than crashing the entire load.

**Temporal filtering.** The graph stores effective_date and termination_date on edges, but the queries don't filter by them. A production system adds `WHERE coverage.effective_date <= date() AND (coverage.termination_date IS NULL OR coverage.termination_date >= date())` to every query. Without this, you'll return alternatives that were removed from the formulary last quarter.

**RxNorm normalization.** Formulary files use inconsistent drug identifiers. Some rows have RxNorm CUIs, some have NDCs, some have GPIs. Before loading, you need a normalization step that maps everything to a common identifier (RxNorm CUI is the standard choice). The NLM provides RxNorm REST APIs and downloadable files for this mapping. Without normalization, the same drug appears as multiple disconnected nodes in your graph.

**IAM authentication for Neptune.** This example uses plain HTTPS without request signing. If your Neptune cluster has IAM authentication enabled (recommended for production), you need to sign every request with AWS SigV4. The `boto3` library can generate SigV4 signatures, or use the `amazon-neptune-sigv4-signer` utility.

**VPC and network configuration.** Neptune requires VPC deployment. Your Lambda functions need to be in the same VPC with security groups that allow outbound traffic to Neptune's port (8182) and Redis's port (6379). You also need VPC endpoints for S3 and CloudWatch Logs so Lambda can reach those services without a NAT gateway.

**Redis connection pooling.** The `redis.Redis()` client in this example creates a single connection. Under concurrent Lambda invocations, you'll exhaust Redis connection limits quickly. Use `redis.ConnectionPool` with appropriate max_connections settings, or use ElastiCache Serverless which handles connection management for you.

**Monitoring and alerting.** No metrics here. A production system tracks: query latency (p50, p95, p99), cache hit rate, Neptune query count, graph load duration, and error rates. Set alarms on cache hit rate dropping below 80% (indicates a cache key mismatch or TTL issue) and on query latency exceeding 100ms (indicates Neptune is undersized or queries need optimization).

**Testing.** There are no tests here. A production pipeline has: unit tests for `parse_formulary_file` with sample file fixtures, integration tests that load a small graph and verify query results, and a synthetic formulary file that covers edge cases (drugs with no class, drugs with multiple strengths, drugs with all restriction types). Never use real formulary data with real plan IDs in test fixtures if your test environment isn't HIPAA-compliant.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.1](chapter13.01-drug-formulary-navigation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
