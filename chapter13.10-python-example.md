# Recipe 13.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the federated clinical knowledge network concepts from Recipe 13.10. It demonstrates the mechanics of federation (source registration, ontology mapping, query decomposition, result assembly) using boto3 calls against Neptune, DynamoDB, and S3. It is not production-ready. Real federation involves governance frameworks, legal agreements, and multi-account networking that take months to establish. Think of this as the technical skeleton, not the finished building.

---

## Setup

You'll need the AWS SDK for Python and a SPARQL client:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `neptune-db:*` (scoped to your Neptune cluster)
- `s3:GetObject` and `s3:PutObject` on the ontology registry bucket
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Query` on the source catalog table
- `lambda:InvokeFunction` for cross-account query adapters

You'll also need a running Amazon Neptune cluster with a SPARQL endpoint. Neptune must be in a VPC, so your code needs to run from within that VPC (Lambda in VPC, EC2, or Cloud9).

---

## Config and Constants

These configuration values define the federation infrastructure. In production, these would come from environment variables or AWS Systems Manager Parameter Store.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import requests
from botocore.config import Config

# Structured logging. Never log actual clinical knowledge content in production
# since it may be derived from PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Neptune SPARQL endpoint. This is your LOCAL institution's graph.
# In production, each institution has their own endpoint.
NEPTUNE_SPARQL_ENDPOINT = "https://your-neptune-cluster.us-east-1.neptune.amazonaws.com:8182/sparql"

# DynamoDB table that tracks all participating federation sources.
SOURCE_CATALOG_TABLE = "federation-source-catalog"

# S3 bucket holding shared ontology mapping files.
ONTOLOGY_REGISTRY_BUCKET = "federation-ontology-registry"

# Maximum time (seconds) to wait for a remote source to respond.
# Federation queries fan out to multiple sources in parallel.
# If a source doesn't respond in time, we return partial results.
FEDERATION_TIMEOUT_SECONDS = 5

# Maximum number of sources to query in parallel.
MAX_PARALLEL_SOURCES = 10

# boto3 clients
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
lambda_client = boto3.client("lambda", config=BOTO3_RETRY_CONFIG)
```

---

## Step 1: Register a Source in the Federation Catalog

*The pseudocode calls this `register_source(institution_id, capabilities, endpoint_config, sharing_policy)`. Before an institution can participate in federated queries, it declares what knowledge it holds, how to reach it, and what sharing rules apply.*

```python
def register_source(
    institution_id: str,
    capabilities: list,
    endpoint_config: dict,
    sharing_policy: dict,
) -> dict:
    """
    Register an institution as a participant in the federated knowledge network.

    This writes a catalog entry to DynamoDB that the federation layer reads
    at query time to determine which sources to contact. Think of it as the
    institution raising its hand: "I have knowledge about these topics, and
    here's how to ask me."

    Args:
        institution_id: Unique identifier, e.g., "boston-medical-center"
        capabilities:   Knowledge domains this source covers,
                        e.g., ["drug_interactions", "genomic_associations"]
        endpoint_config: How to reach this source's query adapter.
                         Contains the Lambda function ARN for cross-account invocation.
        sharing_policy:  Rules governing what can be shared and with whom.
                         Maps knowledge domains to access levels.

    Returns:
        The catalog entry that was written.
    """
    table = dynamodb.Table(SOURCE_CATALOG_TABLE)

    catalog_entry = {
        "institution_id": institution_id,
        "capabilities": capabilities,
        "ontology_version": "SNOMED-CT-2025-03",
        "endpoint": endpoint_config,
        "sharing_policy": sharing_policy,
        "registered_at": datetime.datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }

    # Write to DynamoDB. If this institution already exists, this overwrites
    # their registration (useful for updating capabilities or endpoints).
    table.put_item(Item=catalog_entry)

    logger.info("Registered source: %s with capabilities: %s", institution_id, capabilities)
    return catalog_entry
```

---

## Step 2: Load Ontology Mappings from S3

*The pseudocode calls this `load_ontology_mapping(source_institution_id, mapping_version)`. Each institution models clinical concepts differently. This mapping file translates between the shared federated vocabulary and each source's local representation.*

```python
# In-memory cache for ontology mappings. In production, use a TTL-based cache
# (like functools.lru_cache or an external cache) so you pick up mapping updates
# without redeploying.
_mapping_cache = {}


def load_ontology_mapping(source_institution_id: str, mapping_version: str) -> dict:
    """
    Fetch the ontology mapping file for a specific institution from S3.

    The mapping file contains bidirectional translations:
    - federated_to_local: how to express a federated concept in this source's schema
    - local_to_federated: how to translate this source's results back to shared vocabulary

    Args:
        source_institution_id: Which institution's mapping to load.
        mapping_version:       Version string, e.g., "SNOMED-CT-2025-03"

    Returns:
        Parsed mapping dictionary with concept translations.
    """
    cache_key = f"{source_institution_id}/{mapping_version}"

    if cache_key in _mapping_cache:
        return _mapping_cache[cache_key]

    mapping_key = f"ontology-mappings/{source_institution_id}/v-{mapping_version}.json"

    response = s3_client.get_object(
        Bucket=ONTOLOGY_REGISTRY_BUCKET,
        Key=mapping_key,
    )

    mapping = json.loads(response["Body"].read().decode("utf-8"))

    # Cache it. In production, add a TTL so stale mappings get refreshed.
    _mapping_cache[cache_key] = mapping

    logger.info(
        "Loaded ontology mapping for %s (version %s): %d concept translations",
        source_institution_id,
        mapping_version,
        len(mapping.get("concepts", [])),
    )
    return mapping
```

---

## Step 3: Translate a Federated Query to a Local Schema

*This is the query rewriting step. A federated query uses the shared vocabulary (e.g., SNOMED codes). Each source's local graph might use different identifiers or property names. The mapping file tells us how to translate.*

```python
def translate_query_to_local(federated_query: dict, mapping: dict) -> str:
    """
    Rewrite a federated query into a source's local SPARQL dialect.

    The federated query uses canonical concept codes (SNOMED, RxNorm).
    The local graph might store concepts under different URIs or properties.
    This function applies the ontology mapping to produce a valid local query.

    Args:
        federated_query: Structured query with concept codes and relationship types.
        mapping:         The ontology mapping for the target source.

    Returns:
        A SPARQL query string ready to execute against the local Neptune endpoint.
    """
    # Extract the concept we're querying about from the federated query.
    concept_code = federated_query.get("concept_code", "")
    relationship = federated_query.get("relationship", "treats")
    context = federated_query.get("context", "")

    # Look up how this concept is represented in the local graph.
    # The mapping's "concepts" list maps federated codes to local URIs.
    local_concept_uri = None
    for concept in mapping.get("concepts", []):
        if concept.get("federated_code") == concept_code:
            local_concept_uri = concept.get("local_uri")
            break

    if local_concept_uri is None:
        # This source doesn't have a mapping for this concept.
        # Return an empty query that will produce no results.
        logger.warning("No local mapping found for concept: %s", concept_code)
        return ""

    # Look up the local property name for the relationship type.
    relationship_map = mapping.get("relationships", {})
    local_relationship = relationship_map.get(relationship, relationship)

    # Build the SPARQL query using local URIs and property names.
    # This is a simplified example. Real federation queries can be much more
    # complex, with optional patterns, filters, and subqueries.
    sparql = f"""
    PREFIX local: <{mapping.get("namespace", "http://example.org/")}>
    PREFIX evidence: <http://example.org/evidence/>

    SELECT ?related_concept ?label ?severity ?evidence_level ?last_validated
    WHERE {{
        <{local_concept_uri}> local:{local_relationship} ?related_concept .
        ?related_concept local:label ?label .
        OPTIONAL {{ ?related_concept local:severity ?severity . }}
        OPTIONAL {{ ?related_concept evidence:level ?evidence_level . }}
        OPTIONAL {{ ?related_concept evidence:lastValidated ?last_validated . }}
    """

    # Add context filter if provided (e.g., "renal_impairment").
    if context:
        local_context_uri = None
        for concept in mapping.get("concepts", []):
            if concept.get("federated_code") == context:
                local_context_uri = concept.get("local_uri")
                break
        if local_context_uri:
            sparql += f"        ?related_concept local:context <{local_context_uri}> .\n"

    sparql += "    }\n    LIMIT 50"

    return sparql
```

---

## Step 4: Query the Source Catalog for Relevant Sources

*The pseudocode calls this part of `decompose_and_route`. We query DynamoDB to find which registered sources have capabilities matching our query's knowledge domain.*

```python
def find_relevant_sources(query_domains: list, requester_context: dict) -> list:
    """
    Look up which federation sources have knowledge relevant to our query.

    Scans the source catalog for active sources whose capabilities overlap
    with the query's knowledge domains, then filters by sharing policy.

    Args:
        query_domains:    Knowledge domains the query touches,
                          e.g., ["drug_interactions"]
        requester_context: Who is asking and why. Contains institution_id,
                           purpose (clinical, research, quality), and user_role.

    Returns:
        List of authorized source catalog entries.
    """
    table = dynamodb.Table(SOURCE_CATALOG_TABLE)

    # Scan for active sources. In production with many sources, you'd use a
    # GSI on capabilities or maintain a separate routing index.
    # For a federation of 5-20 institutions, a scan is fine.
    response = table.scan(
        FilterExpression="attribute_exists(capabilities) AND #s = :active",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":active": "active"},
    )

    candidates = response.get("Items", [])

    # Filter to sources whose capabilities overlap with query domains.
    relevant = []
    for source in candidates:
        source_capabilities = set(source.get("capabilities", []))
        if source_capabilities.intersection(set(query_domains)):
            relevant.append(source)

    # Apply sharing policy check: does this source allow the requester access?
    authorized = []
    for source in relevant:
        if evaluate_sharing_policy(source, requester_context, query_domains):
            authorized.append(source)

    logger.info(
        "Found %d relevant sources (%d authorized) for domains: %s",
        len(relevant),
        len(authorized),
        query_domains,
    )
    return authorized


def evaluate_sharing_policy(source: dict, requester_context: dict, query_domains: list) -> bool:
    """
    Check whether a source's sharing policy allows this requester access.

    Sharing policies map knowledge domains to access levels:
    - "public": any federation member can query
    - "research_only": only approved research collaborators
    - "bilateral": only institutions with a bilateral agreement

    Args:
        source:            The source catalog entry with sharing_policy.
        requester_context: Who is asking (institution, purpose, role).
        query_domains:     What domains the query touches.

    Returns:
        True if the requester is authorized for at least one relevant domain.
    """
    policy = source.get("sharing_policy", {})
    requester_purpose = requester_context.get("purpose", "clinical")

    for domain in query_domains:
        domain_policy = policy.get(domain, "public")

        if domain_policy == "public":
            return True
        elif domain_policy == "research_only" and requester_purpose == "research":
            return True
        elif domain_policy == "bilateral":
            # Check if requester's institution has a bilateral agreement.
            allowed_institutions = policy.get("bilateral_partners", [])
            if requester_context.get("institution_id") in allowed_institutions:
                return True

    return False
```

---

## Step 5: Execute a Federated Query Across Sources

*This is the core federation step. We decompose the query, translate it for each source, dispatch sub-queries in parallel, and collect results. The parallel execution is critical because network latency is the bottleneck.*

```python
def execute_federated_query(federated_query: dict, requester_context: dict) -> dict:
    """
    Execute a query across the federated knowledge network.

    This is the main entry point for federation. It:
    1. Identifies relevant sources from the catalog
    2. Translates the query for each source's local schema
    3. Dispatches sub-queries in parallel
    4. Assembles and deduplicates results

    Args:
        federated_query:   Structured query in the federated vocabulary.
                           Contains concept_code, relationship, and optional context.
        requester_context: Who is asking. Contains institution_id, purpose, user_role.

    Returns:
        Assembled federation response with results, provenance, and metadata.
    """
    start_time = datetime.datetime.now(timezone.utc)

    # Determine which knowledge domains this query touches.
    query_domains = federated_query.get("domains", ["drug_interactions"])

    # Find sources that can answer this query and are willing to.
    authorized_sources = find_relevant_sources(query_domains, requester_context)

    if not authorized_sources:
        return {
            "query": federated_query,
            "federation_metadata": {
                "sources_contacted": 0,
                "sources_responded": 0,
                "error": "no_authorized_sources",
            },
            "results": [],
        }

    # Translate the query for each source and dispatch in parallel.
    sub_queries = []
    for source in authorized_sources:
        mapping = load_ontology_mapping(
            source["institution_id"],
            source.get("ontology_version", "SNOMED-CT-2025-03"),
        )
        local_sparql = translate_query_to_local(federated_query, mapping)

        if local_sparql:  # Skip sources where translation produced nothing
            sub_queries.append({
                "source": source,
                "sparql": local_sparql,
                "mapping": mapping,
            })

    # Execute all sub-queries in parallel using a thread pool.
    # Network I/O is the bottleneck, so threads work well here.
    results_by_source = {}
    timed_out_sources = []

    with ThreadPoolExecutor(max_workers=min(len(sub_queries), MAX_PARALLEL_SOURCES)) as executor:
        future_to_source = {
            executor.submit(
                invoke_remote_source,
                sq["source"],
                sq["sparql"],
                requester_context,
            ): sq["source"]["institution_id"]
            for sq in sub_queries
        }

        for future in as_completed(future_to_source, timeout=FEDERATION_TIMEOUT_SECONDS + 2):
            source_id = future_to_source[future]
            try:
                result = future.result(timeout=FEDERATION_TIMEOUT_SECONDS)
                results_by_source[source_id] = result
            except TimeoutError:
                timed_out_sources.append(source_id)
                logger.warning("Source timed out: %s", source_id)
            except Exception as e:
                logger.error("Source query failed for %s: %s", source_id, str(e))
                timed_out_sources.append(source_id)

    # Assemble results from all responding sources.
    assembled = assemble_results(results_by_source)

    end_time = datetime.datetime.now(timezone.utc)
    latency_ms = int((end_time - start_time).total_seconds() * 1000)

    return {
        "query": federated_query,
        "federation_metadata": {
            "sources_contacted": len(sub_queries),
            "sources_responded": len(results_by_source),
            "sources_timed_out": len(timed_out_sources),
            "timed_out_sources": timed_out_sources,
            "total_latency_ms": latency_ms,
        },
        "results": assembled,
    }
```

---

## Step 6: Invoke a Remote Source's Query Adapter

*Each institution exposes a Lambda function as their query adapter. The federation layer invokes it cross-account via Lambda's invoke API (in production, through PrivateLink). The adapter validates authorization, runs the SPARQL query locally, and returns results with provenance.*

```python
def invoke_remote_source(source: dict, sparql_query: str, requester_context: dict) -> list:
    """
    Invoke a remote institution's query adapter Lambda function.

    In production, this call goes over PrivateLink to a Lambda in another
    AWS account. The remote Lambda validates authorization, executes the
    SPARQL query against its local Neptune cluster, attaches provenance
    metadata, and returns filtered results.

    Args:
        source:            Source catalog entry with endpoint config.
        sparql_query:      SPARQL query translated to this source's local schema.
        requester_context: Passed to the remote adapter for authorization checks.

    Returns:
        List of result objects with provenance metadata attached.
    """
    adapter_function_arn = source["endpoint"].get("lambda_arn", "")

    if not adapter_function_arn:
        logger.warning("No Lambda ARN for source: %s", source["institution_id"])
        return []

    payload = {
        "sparql_query": sparql_query,
        "requester": requester_context,
        "request_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }

    # Invoke the remote adapter. In production, this uses a cross-account
    # IAM role assumed via STS, with the invocation routed over PrivateLink.
    response = lambda_client.invoke(
        FunctionName=adapter_function_arn,
        InvocationType="RequestResponse",  # synchronous; we need the results
        Payload=json.dumps(payload).encode("utf-8"),
    )

    # Parse the response payload.
    response_payload = json.loads(response["Payload"].read().decode("utf-8"))

    if response_payload.get("status") == "denied":
        logger.info(
            "Source %s denied query: %s",
            source["institution_id"],
            response_payload.get("reason", "unknown"),
        )
        return []

    return response_payload.get("results", [])
```

---

## Step 7: Local Query Adapter (What Runs at Each Institution)

*This is the Lambda function that each institution deploys. It receives translated SPARQL queries from the federation layer, validates authorization, executes against the local Neptune cluster, and attaches provenance. This is where institutional governance is enforced.*

```python
def local_query_adapter_handler(event: dict, context) -> dict:
    """
    Lambda handler for the local query adapter.

    This runs in each institution's AWS account. It:
    1. Validates the requester's authorization
    2. Executes the SPARQL query against the local Neptune
    3. Attaches provenance metadata to each result
    4. Applies result-level filtering based on sharing policy

    This is the defense-in-depth layer. Even if the federation layer's
    policy check passed, the local adapter re-validates. Belt and suspenders
    when PHI-derived knowledge is involved.
    """
    sparql_query = event.get("sparql_query", "")
    requester = event.get("requester", {})

    # Authorization check. In production, this validates against a local
    # policy engine, checks data use agreements, and logs the access attempt.
    if not validate_local_authorization(requester):
        return {"status": "denied", "reason": "insufficient_authorization"}

    # Execute the SPARQL query against the local Neptune endpoint.
    raw_results = execute_sparql_locally(sparql_query)

    # Attach provenance to each result so consumers know where it came from.
    enriched = []
    for result in raw_results:
        enriched.append({
            "data": result,
            "provenance": {
                "source_institution": "this-institution-id",  # from environment
                "evidence_level": result.get("evidence_level", "ungraded"),
                "last_validated": result.get("last_validated", "unknown"),
                "derivation_method": result.get("derivation", "curated"),
            },
        })

    return {"status": "success", "results": enriched}


def validate_local_authorization(requester: dict) -> bool:
    """
    Validate that the requester is authorized for this query.

    In production, this checks:
    - Is the requester's institution in our approved federation list?
    - Does their stated purpose match our data use agreement?
    - Is their access token valid and not expired?

    For this example, we do a simple institution allowlist check.
    """
    allowed_institutions = [
        "boston-medical-center",
        "midwest-health-network",
        "research-consortium-west",
    ]
    return requester.get("institution_id") in allowed_institutions


def execute_sparql_locally(sparql_query: str) -> list:
    """
    Execute a SPARQL query against the local Neptune cluster.

    Neptune exposes a SPARQL endpoint over HTTPS. We POST the query
    and parse the JSON results. This must run from within the VPC
    where Neptune lives (no public endpoint).
    """
    if not sparql_query:
        return []

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {"query": sparql_query}

    # Neptune uses IAM auth (SigV4) in production. For this example,
    # we assume VPC-internal access without additional auth.
    # In production, use the requests-aws4auth library for SigV4 signing.
    response = requests.post(
        NEPTUNE_SPARQL_ENDPOINT,
        headers=headers,
        data=data,
        timeout=FEDERATION_TIMEOUT_SECONDS,
    )

    if response.status_code != 200:
        logger.error("Neptune query failed: %s", response.text[:200])
        return []

    # Parse SPARQL JSON results format.
    sparql_results = response.json()
    bindings = sparql_results.get("results", {}).get("bindings", [])

    # Convert SPARQL bindings to simpler dicts.
    results = []
    for binding in bindings:
        result = {}
        for var_name, var_data in binding.items():
            result[var_name] = var_data.get("value", "")
        results.append(result)

    return results
```

---

## Step 8: Assemble and Deduplicate Results

*Results arrive from multiple sources. The assembler merges them, deduplicates (two sources might report the same interaction), and ranks by evidence strength and source agreement.*

```python
def assemble_results(results_by_source: dict) -> list:
    """
    Merge results from multiple sources into a unified, deduplicated response.

    Two sources might report the same drug interaction with different severity
    ratings or evidence levels. This function groups duplicates by concept,
    merges their provenance, and calculates a consensus score.

    Args:
        results_by_source: Dict mapping source_id to list of result objects.

    Returns:
        Merged, deduplicated, ranked list of federated results.
    """
    # Flatten all results into a single list with source tracking.
    all_results = []
    for source_id, results in results_by_source.items():
        for result in results:
            result["_source_id"] = source_id
            all_results.append(result)

    if not all_results:
        return []

    # Group by canonical concept. We use the "related_concept" URI or label
    # as the deduplication key. In production, you'd normalize to a canonical
    # code (SNOMED, RxNorm) before grouping.
    grouped = {}
    for result in all_results:
        # Use the concept label as a grouping key (simplified).
        # Production systems use canonical URIs or code mappings.
        concept_key = (
            result.get("data", {}).get("label", "")
            or result.get("data", {}).get("related_concept", "unknown")
        )

        if concept_key not in grouped:
            grouped[concept_key] = []
        grouped[concept_key].append(result)

    # Merge each group into a single federated result.
    merged_results = []
    for concept_key, group in grouped.items():
        if len(group) == 1:
            # Single source. Use directly.
            item = group[0]
            merged_results.append({
                "data": item.get("data", {}),
                "provenance": [item.get("provenance", {})],
                "consensus_score": None,  # can't calculate with one source
                "source_count": 1,
            })
        else:
            # Multiple sources. Merge provenance and calculate consensus.
            provenances = [item.get("provenance", {}) for item in group]

            # Pick the data from the highest-evidence source.
            best = max(group, key=lambda x: evidence_rank(x.get("provenance", {})))

            # Consensus: do sources agree on severity?
            severities = [
                item.get("data", {}).get("severity", "unknown") for item in group
            ]
            unique_severities = set(s for s in severities if s != "unknown")
            consensus = 1.0 if len(unique_severities) <= 1 else round(1.0 / len(unique_severities), 2)

            merged_results.append({
                "data": best.get("data", {}),
                "provenance": provenances,
                "consensus_score": consensus,
                "source_count": len(group),
            })

    # Rank: more sources and higher evidence = higher rank.
    merged_results.sort(
        key=lambda x: (x["source_count"], max_evidence_rank(x["provenance"])),
        reverse=True,
    )

    return merged_results


def evidence_rank(provenance: dict) -> int:
    """Map evidence level letters to numeric ranks for sorting."""
    ranks = {"A": 4, "B": 3, "C": 2, "D": 1, "ungraded": 0}
    return ranks.get(provenance.get("evidence_level", "ungraded"), 0)


def max_evidence_rank(provenances: list) -> int:
    """Get the highest evidence rank from a list of provenance records."""
    if not provenances:
        return 0
    return max(evidence_rank(p) for p in provenances)
```

---

## Putting It All Together

Here's the full federation pipeline assembled into a single callable flow. This is what a clinical application would invoke when a clinician asks "what do we know about drug interactions for Metformin in patients with renal impairment?"

```python
def federated_drug_interaction_query(
    drug_code: str,
    context_code: str = "",
    requester_institution: str = "requesting-hospital",
    purpose: str = "clinical",
) -> dict:
    """
    Run a federated drug interaction query across the knowledge network.

    This is the high-level entry point that a clinical decision support
    system would call. It constructs the federated query, executes it
    across all authorized sources, and returns assembled results.

    Args:
        drug_code:             RxNorm or SNOMED code for the drug.
        context_code:          Optional clinical context (e.g., renal impairment code).
        requester_institution: Which institution is asking.
        purpose:               Why they're asking (clinical, research, quality).

    Returns:
        Full federation response with results, provenance, and metadata.
    """
    print(f"=== Federated Query: drug interactions for {drug_code} ===")
    print(f"    Context: {context_code or 'none'}")
    print(f"    Requester: {requester_institution} ({purpose})")
    print()

    # Build the federated query structure.
    federated_query = {
        "concept_code": drug_code,
        "relationship": "interacts_with",
        "context": context_code,
        "domains": ["drug_interactions"],
    }

    # Build the requester context for authorization checks.
    requester_context = {
        "institution_id": requester_institution,
        "purpose": purpose,
        "user_role": "clinician",
    }

    # Execute the federated query.
    print("Step 1: Finding relevant sources in federation catalog...")
    print("Step 2: Loading ontology mappings for each source...")
    print("Step 3: Translating query to each source's local schema...")
    print("Step 4: Dispatching sub-queries in parallel...")

    response = execute_federated_query(federated_query, requester_context)

    metadata = response.get("federation_metadata", {})
    print(f"\nFederation complete:")
    print(f"  Sources contacted: {metadata.get('sources_contacted', 0)}")
    print(f"  Sources responded: {metadata.get('sources_responded', 0)}")
    print(f"  Sources timed out: {metadata.get('sources_timed_out', 0)}")
    print(f"  Total latency: {metadata.get('total_latency_ms', 0)}ms")
    print(f"  Results returned: {len(response.get('results', []))}")

    return response


# Example: register some sources, then run a federated query.
if __name__ == "__main__":
    # Register three institutions in the federation.
    print("=== Registering Federation Sources ===\n")

    register_source(
        institution_id="boston-medical-center",
        capabilities=["drug_interactions", "genomic_associations", "treatment_protocols"],
        endpoint_config={
            "lambda_arn": "arn:aws:lambda:us-east-1:111111111111:function:bmc-query-adapter",
        },
        sharing_policy={
            "drug_interactions": "public",
            "genomic_associations": "research_only",
            "treatment_protocols": "bilateral",
            "bilateral_partners": ["midwest-health-network"],
        },
    )

    register_source(
        institution_id="midwest-health-network",
        capabilities=["drug_interactions", "treatment_protocols"],
        endpoint_config={
            "lambda_arn": "arn:aws:lambda:us-east-1:222222222222:function:mhn-query-adapter",
        },
        sharing_policy={
            "drug_interactions": "public",
            "treatment_protocols": "public",
        },
    )

    register_source(
        institution_id="research-consortium-west",
        capabilities=["drug_interactions", "genomic_associations"],
        endpoint_config={
            "lambda_arn": "arn:aws:lambda:us-west-2:333333333333:function:rcw-query-adapter",
        },
        sharing_policy={
            "drug_interactions": "public",
            "genomic_associations": "research_only",
        },
    )

    print("\n=== Running Federated Query ===\n")

    # Query for Metformin drug interactions in the context of renal impairment.
    # RxNorm:6809 = Metformin
    # SNOMED:723188008 = Renal impairment (simplified code for illustration)
    result = federated_drug_interaction_query(
        drug_code="RxNorm:6809",
        context_code="SNOMED:723188008",
        requester_institution="requesting-hospital",
        purpose="clinical",
    )

    print("\n=== Full Response ===\n")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the mechanics of federation: source registration, ontology mapping, query decomposition, parallel dispatch, and result assembly. But there's a substantial distance between this and a deployed federated knowledge network. Here's where that gap lives:

**Cross-account networking (PrivateLink).** This example invokes Lambda functions by ARN, which works within a single account. Real federation crosses AWS account boundaries. You need PrivateLink endpoints connecting VPCs in different accounts, cross-account IAM roles assumed via STS, and careful security group configuration. The networking setup alone is a multi-week effort per participating institution.

**Neptune IAM authentication (SigV4).** The `execute_sparql_locally` function makes a plain HTTP POST to Neptune. Production Neptune clusters require IAM authentication via SigV4 request signing. Use the `requests-aws4auth` library or the `boto3` SigV4 signer to sign requests. Without this, Neptune rejects all queries.

**Ontology mapping maintenance.** The mapping files in S3 are treated as static in this example. In production, ontologies evolve (SNOMED releases quarterly, local schemas change). You need automated drift detection that alerts when a source's local schema diverges from its registered mapping, plus a human review process for mapping updates.

**Error handling and circuit breakers.** If a source consistently times out or returns errors, the federation layer should stop querying it temporarily (circuit breaker pattern). This example retries on failure but doesn't track source health over time. A production system maintains a health score per source and routes around unhealthy nodes.

**Query privacy.** The current implementation sends the full SPARQL query to each source. A sophisticated source could infer information about the requester's patient population from query patterns. Production systems may need query obfuscation (adding noise queries) or differential privacy mechanisms.

**Governance framework.** The `sharing_policy` in this example is a simple dictionary. Real governance involves legal data use agreements, institutional review board (IRB) approvals for research queries, audit requirements, and a process for revoking access. The technology is 20% of the effort; governance is 80%.

**Result caching.** For frequently-asked queries (common drug interactions), you don't want to hit the federation on every request. A production system caches federated results locally with a TTL, serving cached results for real-time clinical decision support while refreshing the cache asynchronously.

**Structured logging and audit trail.** Every federated query must produce an audit record: who asked, what they asked, which sources responded, what was returned. This is a HIPAA requirement when knowledge is derived from PHI. Use CloudTrail for API-level audit and CloudWatch Logs for application-level query logging.

**Testing.** There are no tests here. A production federation needs: unit tests for query translation (with mock mappings), integration tests against a local Neptune with known test data, and end-to-end federation tests with mock remote adapters. Never use real institutional knowledge in test environments.

**DynamoDB data types.** If you store numeric values (confidence scores, timestamps) in DynamoDB, remember to wrap them in `Decimal()`. The boto3 DynamoDB resource layer raises `TypeError` on raw Python floats.

**Conflict resolution governance.** When two sources disagree on a drug interaction severity, this example picks the highest-evidence source. In production, clinical governance requires human review of conflicts, especially for safety-critical knowledge. You need a conflict queue and a review process.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.10](chapter13.10-federated-clinical-knowledge-network) for the full architectural walkthrough, pseudocode, and honest take on where federation gets hard in practice.*
