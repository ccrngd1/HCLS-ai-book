# Recipe 13.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.3. It shows one way you could translate those graph concepts into working Python code using boto3 and Neptune's openCypher endpoint. It is not production-ready. There's no connection pooling, no robust error handling, no input validation. Think of it as the sketchpad version: useful for understanding how ICD/CPT hierarchy data flows into a graph and how traversal queries work, not something you'd deploy to a coding department on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for Neptune (`neptune-db:*` scoped to your cluster), S3 (`s3:GetObject` and `s3:PutObject` on the staging bucket), and network access to Neptune from within your VPC.

Neptune doesn't use IAM for query authentication by default (it uses VPC-level network isolation). If you've enabled IAM auth on your cluster, you'll need to sign requests with SigV4. This example assumes VPC network access without IAM auth for simplicity.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These constants define the Neptune endpoint, the graph schema for medical code hierarchies, and the ICD-10-CM chapter structure we'll use to derive hierarchy from code structure.

```python
import boto3
import csv
import json
import io
import logging
import requests
from datetime import date

# Configure logging. In production, use structured JSON logging
# for CloudWatch Logs Insights queries.
# PHI Safety: Code assignments linked to patients are part of the
# designated record set. Never log patient-code associations.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Neptune cluster endpoint. Use the writer endpoint for loads,
# reader endpoint for queries. In production, separate these.
#
# Neptune runs inside your VPC. This code must execute from within
# the same VPC (Lambda in VPC, EC2, ECS, etc.) to reach it.
NEPTUNE_ENDPOINT = "your-neptune-cluster.cluster-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_PORT = 8182

# Neptune exposes openCypher queries via HTTPS POST to this path.
NEPTUNE_OPENCYPHER_URL = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/openCypher"

# S3 bucket for staging source files and Neptune bulk load CSVs.
STAGING_BUCKET = "my-code-hierarchy-staging"

# Neptune bulk loader IAM role. This role must have S3 read access
# to the staging bucket and a trust policy allowing Neptune to assume it.
NEPTUNE_LOAD_ROLE_ARN = "arn:aws:iam::123456789012:role/NeptuneLoadFromS3"

# AWS region for all service calls.
AWS_REGION = "us-east-1"

# Redis endpoint for caching traversal results.
# Hierarchy queries are deterministic per version, so caching is very effective.
REDIS_HOST = "your-redis-cluster.xxxxxxxxxxxx.use1.cache.amazonaws.com"
REDIS_PORT = 6379

# Cache TTL: 24 hours. ICD-10 updates annually (Oct 1), CPT annually with
# quarterly corrections. Flush cache explicitly on version loads.
CACHE_TTL_SECONDS = 86400

# ICD-10-CM chapter ranges. The first character of the code determines
# the chapter. This is how we derive the top-level hierarchy from code structure.
ICD10_CHAPTERS = {
    "A": ("1", "Certain infectious and parasitic diseases"),
    "B": ("1", "Certain infectious and parasitic diseases"),
    "C": ("2", "Neoplasms"),
    "D": ("2-3", "Neoplasms / Blood diseases"),  # D00-D49 = neoplasms, D50-D89 = blood
    "E": ("4", "Endocrine, nutritional and metabolic diseases"),
    "F": ("5", "Mental, behavioral and neurodevelopmental disorders"),
    "G": ("6", "Diseases of the nervous system"),
    "H": ("7-8", "Eye and adnexa / Ear and mastoid"),  # H00-H59 = eye, H60-H95 = ear
    "I": ("9", "Diseases of the circulatory system"),
    "J": ("10", "Diseases of the respiratory system"),
    "K": ("11", "Diseases of the digestive system"),
    "L": ("12", "Diseases of the skin and subcutaneous tissue"),
    "M": ("13", "Diseases of the musculoskeletal system"),
    "N": ("14", "Diseases of the genitourinary system"),
    "O": ("15", "Pregnancy, childbirth and the puerperium"),
    "P": ("16", "Certain conditions originating in the perinatal period"),
    "Q": ("17", "Congenital malformations"),
    "R": ("18", "Symptoms, signs and abnormal clinical findings"),
    "S": ("19", "Injury, poisoning"),
    "T": ("19", "Injury, poisoning"),
    "V": ("20", "External causes of morbidity"),
    "W": ("20", "External causes of morbidity"),
    "X": ("20", "External causes of morbidity"),
    "Y": ("20", "External causes of morbidity"),
    "Z": ("21", "Factors influencing health status"),
}

# Node labels in our graph schema.
NODE_LABELS = {
    "icd10": "ICD10CM",
    "cpt": "CPT",
    "chapter": "Chapter",
    "block": "Block",
}

# Edge types connecting our nodes.
EDGE_TYPES = {
    "is_child_of": "IS_CHILD_OF",
    "excludes1": "EXCLUDES1",
    "excludes2": "EXCLUDES2",
    "code_first": "CODE_FIRST",
    "use_additional": "USE_ADDITIONAL",
    "cross_walks_to": "CROSS_WALKS_TO",
    "superseded_by": "SUPERSEDED_BY",
}
```

---

## Step 1: Parse ICD-10-CM Source Files

*The pseudocode calls this `parse_icd10_to_graph(source_file_path)`. It reads the CMS order file (a fixed-width text file where each line represents one code) and produces graph nodes and edges. The hierarchy is derived from the code structure itself: E11 is parent of E11.6, which is parent of E11.65.*

```python
s3_client = boto3.client("s3", region_name=AWS_REGION)


def derive_parent_code(code: str) -> str | None:
    """
    Derive the parent code from an ICD-10-CM code by removing the last
    character of specificity.

    ICD-10-CM hierarchy is encoded in the code structure:
      E11.65 -> parent is E11.6
      E11.6  -> parent is E11
      E11    -> parent is the chapter/block level (handled separately)

    The dot is cosmetic (separates category from subcategory) but the
    hierarchy is purely positional.
    """
    # Remove the dot for uniform handling. ICD-10 codes are 3-7 chars
    # without the dot (the dot always appears after position 3).
    clean = code.replace(".", "")

    if len(clean) <= 3:
        # Three-character codes (categories like E11) are children of blocks.
        # We'll handle block-level parenting separately.
        return None

    # Drop the last character to get the parent.
    parent_clean = clean[:-1]

    # Re-insert the dot if the parent is longer than 3 characters.
    if len(parent_clean) > 3:
        return parent_clean[:3] + "." + parent_clean[3:]
    else:
        return parent_clean


def parse_icd10_order_file(bucket: str, key: str, version: str) -> tuple[list, list]:
    """
    Parse the CMS ICD-10-CM order file into graph nodes and edges.

    The order file is a fixed-width text file. Each line contains:
      - Positions 1-5: sequence number
      - Position 6: blank
      - Positions 7-13: ICD-10-CM code (no dot, left-justified)
      - Position 14: blank
      - Position 15: 0 = non-billable header, 1 = billable code
      - Position 16: blank
      - Positions 17-76: short description (60 chars)
      - Positions 77+: long description

    CMS publishes this at:
    https://www.cms.gov/medicare/coding-billing/icd-10-codes

    Args:
        bucket: S3 bucket containing the downloaded CMS file
        key: S3 key to the order file (e.g., "icd10cm/FY2026/icd10cm_order_2026.txt")
        version: Fiscal year version string (e.g., "FY2026")

    Returns:
        Tuple of (nodes_list, edges_list) ready for Neptune bulk load formatting.
    """
    # Download the order file from S3.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    nodes = []
    edges = []

    for line in content.strip().split("\n"):
        if len(line) < 77:
            continue  # skip malformed lines

        # Parse fixed-width fields.
        # The code field is positions 7-13 (0-indexed: 6:13), no dot included.
        raw_code = line[6:13].strip()
        is_billable = line[14] == "1"
        short_desc = line[16:76].strip()
        long_desc = line[77:].strip() if len(line) > 77 else short_desc

        # CMS stores codes without dots. Re-insert the dot after position 3
        # for codes longer than 3 characters (standard display format).
        if len(raw_code) > 3:
            code = raw_code[:3] + "." + raw_code[3:]
        else:
            code = raw_code

        # Determine the chapter from the first character.
        first_char = code[0].upper()
        chapter_info = ICD10_CHAPTERS.get(first_char, ("?", "Unknown"))

        # Create the node for this code.
        node = {
            "id": code,
            "label": NODE_LABELS["icd10"],
            "description": long_desc,
            "short_desc": short_desc,
            "is_billable": is_billable,
            "chapter": chapter_info[0],
            "version": version,
        }
        nodes.append(node)

        # Derive parent-child edge from code structure.
        parent = derive_parent_code(code)
        if parent:
            edge = {
                "id": f"{code}_child_of_{parent}",
                "source": code,
                "target": parent,
                "label": EDGE_TYPES["is_child_of"],
            }
            edges.append(edge)

    logger.info(
        "Parsed %d ICD-10-CM codes, %d parent-child edges from order file",
        len(nodes), len(edges)
    )
    return nodes, edges
```

---

## Step 2: Parse Cross-Walk Mappings

*The pseudocode calls this `parse_cpt_and_crosswalks(cpt_source, crosswalk_source)`. This step handles the ICD-to-CPT medical necessity mappings that tell you which diagnosis codes justify which procedure codes. The cross-walk data comes from CMS for Medicare (the NCCI edits files).*

```python
def parse_crosswalk_file(bucket: str, key: str) -> list:
    """
    Parse an ICD-10 to CPT cross-walk file into graph edges.

    CMS publishes medical necessity mappings as part of the National Correct
    Coding Initiative (NCCI). These files map ICD-10 diagnosis codes to CPT
    procedure codes that are considered medically necessary given that diagnosis.

    The format varies by source. This example assumes a CSV with columns:
    icd_code, cpt_code, effective_date, end_date, payer

    In reality, you'll need separate parsers for:
    - CMS NCCI files (Medicare)
    - LCD/NCD files (local/national coverage determinations)
    - Payer-specific files (commercial plans, each in their own format)

    Args:
        bucket: S3 bucket containing the cross-walk file
        key: S3 key to the cross-walk CSV

    Returns:
        List of edge dictionaries for Neptune bulk load.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    edges = []
    reader = csv.DictReader(io.StringIO(content))

    for row in reader:
        icd_code = row["icd_code"].strip()
        cpt_code = row["cpt_code"].strip()
        payer = row.get("payer", "Medicare").strip()
        effective = row.get("effective_date", "").strip()
        end_date = row.get("end_date", "").strip()

        edge = {
            "id": f"{icd_code}_crosswalk_{cpt_code}_{payer}",
            "source": icd_code,
            "target": f"CPT:{cpt_code}",
            "label": EDGE_TYPES["cross_walks_to"],
            "payer": payer,
            "effective": effective,
            "end_date": end_date if end_date else "",
        }
        edges.append(edge)

    logger.info("Parsed %d cross-walk edges from %s", len(edges), key)
    return edges


def parse_exclusion_annotations(bucket: str, key: str) -> list:
    """
    Parse ICD-10-CM excludes annotations into graph edges.

    ICD-10-CM has two types of exclusion relationships:
    - EXCLUDES1: Mutually exclusive. Never code together. The two conditions
      cannot coexist (e.g., acquired vs. congenital form of same condition).
    - EXCLUDES2: Not included here, but CAN be coded together if both are
      documented. Means "this code doesn't cover that concept, look elsewhere."

    These annotations are published by CMS alongside the code files.
    Format assumed: CSV with columns: source_code, target_code, type, note

    Args:
        bucket: S3 bucket containing the annotation file
        key: S3 key to the exclusions CSV

    Returns:
        List of edge dictionaries for Neptune bulk load.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    edges = []
    reader = csv.DictReader(io.StringIO(content))

    for row in reader:
        source = row["source_code"].strip()
        target = row["target_code"].strip()
        exc_type = row["type"].strip().upper()  # "EXCLUDES1" or "EXCLUDES2"
        note = row.get("note", "").strip()

        # Only create edges for recognized exclusion types.
        if exc_type not in (EDGE_TYPES["excludes1"], EDGE_TYPES["excludes2"]):
            logger.warning("Unknown exclusion type '%s' for %s -> %s", exc_type, source, target)
            continue

        edge = {
            "id": f"{source}_{exc_type.lower()}_{target}",
            "source": source,
            "target": target,
            "label": exc_type,
            "note": note,
        }
        edges.append(edge)

    logger.info("Parsed %d exclusion edges from %s", len(edges), key)
    return edges
```

---

## Step 3: Format and Bulk Load into Neptune

*The pseudocode calls this `load_graph_to_neptune(nodes, edges, neptune_endpoint, s3_staging_bucket)`. Neptune's bulk loader expects CSV files in S3 with specific header conventions. Node files need `~id`, `~label`, and property columns. Edge files need `~id`, `~from`, `~to`, `~label`, and property columns.*

```python
def format_nodes_as_neptune_csv(nodes: list) -> str:
    """
    Transform node dictionaries into Neptune bulk load CSV format.

    Neptune's CSV loader expects specific column headers:
    - ~id: unique node identifier (required)
    - ~label: node type label (required)
    - property_name:datatype: typed property columns

    Data types: String (default), Int, Double, Bool, Date
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row with Neptune's required column naming.
    writer.writerow([
        "~id",
        "~label",
        "description:String",
        "short_desc:String",
        "is_billable:Bool",
        "chapter:String",
        "version:String",
    ])

    for node in nodes:
        writer.writerow([
            node["id"],
            node["label"],
            node.get("description", ""),
            node.get("short_desc", ""),
            str(node.get("is_billable", False)).lower(),  # Neptune expects "true"/"false"
            node.get("chapter", ""),
            node.get("version", ""),
        ])

    return output.getvalue()


def format_edges_as_neptune_csv(edges: list) -> str:
    """
    Transform edge dictionaries into Neptune bulk load CSV format.

    Neptune's edge CSV expects:
    - ~id: unique edge identifier (required)
    - ~from: source node ~id (required)
    - ~to: target node ~id (required)
    - ~label: edge type (required)
    - property_name:datatype: typed property columns
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row.
    writer.writerow([
        "~id",
        "~from",
        "~to",
        "~label",
        "note:String",
        "payer:String",
        "effective:String",
        "end_date:String",
    ])

    for edge in edges:
        writer.writerow([
            edge["id"],
            edge["source"],
            edge["target"],
            edge["label"],
            edge.get("note", ""),
            edge.get("payer", ""),
            edge.get("effective", ""),
            edge.get("end_date", ""),
        ])

    return output.getvalue()


def upload_and_bulk_load(nodes: list, edges: list) -> dict:
    """
    Upload formatted CSVs to S3 and trigger Neptune's bulk loader.

    The bulk loader is dramatically faster than inserting nodes one at a time
    via openCypher (minutes vs. hours for 70,000+ nodes). It's also idempotent
    if you use consistent ~id values: reloading the same file updates existing
    nodes rather than creating duplicates.

    Returns:
        Load status response from Neptune.
    """
    # Format as Neptune CSV.
    node_csv = format_nodes_as_neptune_csv(nodes)
    edge_csv = format_edges_as_neptune_csv(edges)

    # Upload to S3 staging bucket.
    s3_client.put_object(
        Bucket=STAGING_BUCKET,
        Key="neptune-load/nodes/icd10_nodes.csv",
        Body=node_csv.encode("utf-8"),
    )
    s3_client.put_object(
        Bucket=STAGING_BUCKET,
        Key="neptune-load/edges/icd10_edges.csv",
        Body=edge_csv.encode("utf-8"),
    )
    logger.info("Uploaded %d nodes and %d edges to S3 staging", len(nodes), len(edges))

    # Trigger Neptune bulk load via the loader API.
    # This is a POST to the Neptune loader endpoint (separate from the query endpoint).
    loader_url = f"https://{NEPTUNE_ENDPOINT}:{NEPTUNE_PORT}/loader"

    load_request = {
        "source": f"s3://{STAGING_BUCKET}/neptune-load/",
        "format": "csv",
        "iamRoleArn": NEPTUNE_LOAD_ROLE_ARN,
        "region": AWS_REGION,
        "failOnError": "FALSE",  # log errors but continue loading valid records
        "parallelism": "HIGH",   # use all available loader threads
        "updateSingleCardinalityProperties": "TRUE",  # update existing nodes on reload
    }

    response = requests.post(loader_url, json=load_request)
    response.raise_for_status()
    load_result = response.json()

    load_id = load_result["payload"]["loadId"]
    logger.info("Neptune bulk load started: loadId=%s", load_id)

    return {"load_id": load_id, "status": load_result["status"]}
```

---

## Step 4: Query the Hierarchy

*The pseudocode calls this `handle_query(request)`. This is where the graph pays off. Queries that would be recursive CTEs in SQL become simple traversal expressions in openCypher. Each function below implements one query pattern from the main recipe.*

```python
def execute_opencypher(query: str, parameters: dict = None) -> list:
    """
    Execute an openCypher query against Neptune and return the results.

    Neptune's openCypher endpoint accepts POST requests with the query
    as a form parameter. Parameters are passed separately for safe
    parameterization (no injection risk).

    Args:
        query: openCypher query string with $parameter placeholders
        parameters: dict of parameter name -> value

    Returns:
        List of result rows (each row is a dict of column -> value).
    """
    payload = {"query": query}
    if parameters:
        payload["parameters"] = json.dumps(parameters)

    response = requests.post(
        NEPTUNE_OPENCYPHER_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()

    result = response.json()
    return result.get("results", [])


def get_children(code: str, depth: int = 99, version: str = "FY2026") -> list:
    """
    Find all descendant codes under a given code in the hierarchy.

    This is the most common query pattern. A population health analyst asks
    "give me all diabetes codes" and you traverse the subtree under E11.
    A coding tool asks "what are the specific codes under this category?"
    and you walk one level down.

    Args:
        code: Starting code (e.g., "E11" for Type 2 diabetes)
        depth: Maximum traversal depth (1 = direct children only, 99 = all)
        version: Fiscal year version to filter by

    Returns:
        List of descendant codes with descriptions and depth levels.
    """
    # openCypher variable-length path pattern: *1..N means 1 to N hops.
    # We traverse IS_CHILD_OF edges in reverse (descendants point UP to parents,
    # so we follow the edge backwards to find children).
    query = """
        MATCH path = (start {`~id`: $code})<-[:`IS_CHILD_OF`*1..%d]-(descendant)
        WHERE descendant.version = $version
        RETURN descendant.`~id` AS code,
               descendant.description AS description,
               descendant.is_billable AS billable,
               length(path) AS depth_level
        ORDER BY descendant.`~id`
    """ % depth  # openCypher in Neptune doesn't support parameterized path lengths

    results = execute_opencypher(query, {"code": code, "version": version})
    logger.info("get_children(%s, depth=%d): %d results", code, depth, len(results))
    return results


def get_ancestors(code: str) -> list:
    """
    Walk up the hierarchy from a code to the chapter level.

    Useful for reporting rollups: "this patient has E11.65, which rolls up
    to E11.6 (complications), which rolls up to E11 (Type 2 DM), which is
    in Chapter 4 (Endocrine)."

    Args:
        code: Starting code (e.g., "E11.65")

    Returns:
        List of ancestor codes ordered from nearest parent to chapter level.
    """
    query = """
        MATCH path = (start {`~id`: $code})-[:`IS_CHILD_OF`*1..10]->(ancestor)
        RETURN ancestor.`~id` AS code,
               ancestor.description AS description,
               length(path) AS levels_up
        ORDER BY levels_up
    """

    results = execute_opencypher(query, {"code": code})
    logger.info("get_ancestors(%s): %d levels", code, len(results))
    return results


def get_crosswalks(code: str, target_system: str = "CPT") -> list:
    """
    Find all codes in another system linked by cross-walk edges.

    The critical question for coding and billing: "which CPT procedure codes
    are justified by this ICD diagnosis code?" Or in reverse: "which diagnoses
    support medical necessity for this procedure?"

    Args:
        code: Source code (e.g., "E11.65")
        target_system: Target code system label (default "CPT")

    Returns:
        List of cross-walked codes with payer and effective date info.
    """
    query = """
        MATCH (start {`~id`: $code})-[r:`CROSS_WALKS_TO`]->(target)
        WHERE target.`~label` = $target_system
        RETURN target.`~id` AS code,
               target.description AS description,
               r.payer AS payer,
               r.effective AS effective_date
        ORDER BY target.`~id`
    """

    results = execute_opencypher(query, {"code": code, "target_system": target_system})
    logger.info("get_crosswalks(%s -> %s): %d results", code, target_system, len(results))
    return results


def get_exclusions(code: str) -> list:
    """
    Find codes that cannot be reported together with this one (EXCLUDES1).

    EXCLUDES1 means mutually exclusive: these two conditions cannot coexist
    in the same patient at the same time. Coding both on the same claim is
    always an error. This is different from EXCLUDES2, which means "not
    included here, but you CAN code both if both are documented."

    Args:
        code: Code to check exclusions for (e.g., "E11")

    Returns:
        List of excluded codes with the exclusion note explaining why.
    """
    query = """
        MATCH (start {`~id`: $code})-[r:`EXCLUDES1`]-(excluded)
        RETURN excluded.`~id` AS code,
               excluded.description AS description,
               r.note AS exclusion_note
        ORDER BY excluded.`~id`
    """

    results = execute_opencypher(query, {"code": code})
    logger.info("get_exclusions(%s): %d exclusions", code, len(results))
    return results


def get_siblings(code: str) -> list:
    """
    Find codes that share the same parent (sibling codes).

    Useful for coding assistance: "You picked E11.65, but did you consider
    E11.64 or E11.69?" Shows the coder what other options exist at the
    same level of specificity.

    Args:
        code: Code to find siblings for (e.g., "E11.65")

    Returns:
        List of sibling codes (same parent, different code).
    """
    query = """
        MATCH (start {`~id`: $code})-[:`IS_CHILD_OF`]->(parent)<-[:`IS_CHILD_OF`]-(sibling)
        WHERE sibling.`~id` <> $code
        RETURN sibling.`~id` AS code,
               sibling.description AS description,
               sibling.is_billable AS billable
        ORDER BY sibling.`~id`
    """

    results = execute_opencypher(query, {"code": code})
    logger.info("get_siblings(%s): %d siblings", code, len(results))
    return results
```

---

## Step 5: Handle Version Transitions

*The pseudocode calls this `apply_version_update(...)`. When CMS publishes a new ICD-10-CM version each October, the graph needs to incorporate changes without destroying history. New codes get new nodes. Retired codes get SUPERSEDED_BY edges pointing to their replacements.*

```python
def apply_version_update(
    bucket: str,
    new_order_file_key: str,
    gems_file_key: str,
    current_version: str,
    new_version: str,
) -> dict:
    """
    Apply an annual ICD-10-CM version update to the graph.

    This function:
    1. Parses the new version's order file
    2. Compares against current graph contents
    3. Adds new codes, marks retired codes, updates descriptions
    4. Creates SUPERSEDED_BY edges using GEMs (General Equivalence Mappings)

    The GEMs file maps old codes to new codes when codes are retired or split.
    CMS publishes GEMs at:
    https://www.cms.gov/medicare/coding-billing/icd-10-codes/general-equivalence-mappings-gems

    Args:
        bucket: S3 bucket with the new version files
        new_order_file_key: S3 key to the new version's order file
        gems_file_key: S3 key to the GEMs mapping file
        current_version: Current version string (e.g., "FY2025")
        new_version: New version string (e.g., "FY2026")

    Returns:
        Summary of changes applied.
    """
    # Parse the new version's codes.
    new_nodes, new_edges = parse_icd10_order_file(bucket, new_order_file_key, new_version)
    new_code_ids = {node["id"] for node in new_nodes}

    # Get current codes from the graph.
    current_codes_query = """
        MATCH (n:`ICD10CM` {version: $version})
        RETURN n.`~id` AS code
    """
    current_results = execute_opencypher(current_codes_query, {"version": current_version})
    current_code_ids = {r["code"] for r in current_results}

    # Identify changes.
    added_codes = new_code_ids - current_code_ids
    retired_codes = current_code_ids - new_code_ids

    logger.info(
        "Version update %s -> %s: %d added, %d retired",
        current_version, new_version, len(added_codes), len(retired_codes)
    )

    # Parse GEMs file for retired code mappings.
    # GEMs format: source_code, target_code, flags
    gems_response = s3_client.get_object(Bucket=bucket, Key=gems_file_key)
    gems_content = gems_response["Body"].read().decode("utf-8")
    gems_map = {}  # old_code -> [new_code, ...]
    for line in gems_content.strip().split("\n"):
        parts = line.split(",")
        if len(parts) >= 2:
            old_code = parts[0].strip()
            new_code = parts[1].strip()
            if old_code not in gems_map:
                gems_map[old_code] = []
            gems_map[old_code].append(new_code)

    # Create SUPERSEDED_BY edges for retired codes.
    superseded_edges = []
    for code in retired_codes:
        replacements = gems_map.get(code.replace(".", ""), [])
        for replacement in replacements:
            # Re-insert dot for display format.
            if len(replacement) > 3:
                replacement_formatted = replacement[:3] + "." + replacement[3:]
            else:
                replacement_formatted = replacement

            superseded_edges.append({
                "id": f"{code}_superseded_by_{replacement_formatted}_{new_version}",
                "source": code,
                "target": replacement_formatted,
                "label": EDGE_TYPES["superseded_by"],
                "effective": new_version,
            })

        # Mark the retired code as inactive.
        retire_query = """
            MATCH (n {`~id`: $code})
            SET n.status = 'RETIRED', n.retired_in = $version
        """
        execute_opencypher(retire_query, {"code": code, "version": new_version})

    # Bulk load the new nodes and all new edges (hierarchy + superseded).
    all_new_nodes = [n for n in new_nodes if n["id"] in added_codes]
    all_new_edges = new_edges + superseded_edges

    if all_new_nodes or all_new_edges:
        upload_and_bulk_load(all_new_nodes, all_new_edges)

    return {
        "current_version": current_version,
        "new_version": new_version,
        "codes_added": len(added_codes),
        "codes_retired": len(retired_codes),
        "superseded_edges_created": len(superseded_edges),
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into callable functions. The ETL pipeline runs periodically (annually for ICD, quarterly for CPT). The query functions are what your API Gateway + Lambda setup calls in response to REST requests.

```python
def run_initial_load():
    """
    Run the full initial load pipeline: parse ICD-10-CM codes and
    cross-walks, then bulk load into Neptune.

    This is what you run once to bootstrap the graph, and then again
    each year when CMS publishes the new version.
    """
    logger.info("=== Starting ICD/CPT Hierarchy Initial Load ===")

    # Step 1: Parse ICD-10-CM order file.
    logger.info("Step 1: Parsing ICD-10-CM order file...")
    nodes, edges = parse_icd10_order_file(
        bucket=STAGING_BUCKET,
        key="icd10cm/FY2026/icd10cm_order_2026.txt",
        version="FY2026",
    )
    logger.info("  Parsed %d nodes, %d edges", len(nodes), len(edges))

    # Step 2: Parse cross-walks and exclusions.
    logger.info("Step 2: Parsing cross-walks and exclusions...")
    crosswalk_edges = parse_crosswalk_file(
        bucket=STAGING_BUCKET,
        key="crosswalks/medicare_icd_cpt_crosswalk.csv",
    )
    exclusion_edges = parse_exclusion_annotations(
        bucket=STAGING_BUCKET,
        key="icd10cm/FY2026/icd10cm_excludes.csv",
    )
    all_edges = edges + crosswalk_edges + exclusion_edges
    logger.info("  Total edges: %d", len(all_edges))

    # Step 3: Upload and bulk load into Neptune.
    logger.info("Step 3: Uploading to S3 and triggering Neptune bulk load...")
    load_result = upload_and_bulk_load(nodes, all_edges)
    logger.info("  Load started: %s", load_result)

    logger.info("=== Initial Load Complete ===")
    return load_result


def handle_api_request(query_type: str, code: str, **kwargs) -> dict:
    """
    Handle an API request by dispatching to the appropriate query function.

    This is what your Lambda query handler calls after parsing the REST request
    from API Gateway. In production, you'd add Redis caching here (check cache
    first, execute query on miss, store result).

    Args:
        query_type: One of "children", "ancestors", "crosswalks", "exclusions", "siblings"
        code: The ICD-10 or CPT code to query
        **kwargs: Additional parameters (depth, version, target_system)

    Returns:
        Structured JSON response.
    """
    depth = kwargs.get("depth", 99)
    version = kwargs.get("version", "FY2026")
    target_system = kwargs.get("target_system", "CPT")

    if query_type == "children":
        results = get_children(code, depth=depth, version=version)
    elif query_type == "ancestors":
        results = get_ancestors(code)
    elif query_type == "crosswalks":
        results = get_crosswalks(code, target_system=target_system)
    elif query_type == "exclusions":
        results = get_exclusions(code)
    elif query_type == "siblings":
        results = get_siblings(code)
    else:
        return {"error": f"Unknown query type: {query_type}"}

    return {
        "code": code,
        "query_type": query_type,
        "version": version,
        "results": results,
        "total_results": len(results),
    }


# Example usage: run queries against the loaded graph.
if __name__ == "__main__":
    # Example 1: Get all children of E11 (Type 2 diabetes), depth 2.
    print("\n--- Children of E11 (depth 2) ---")
    result = handle_api_request("children", "E11", depth=2)
    print(json.dumps(result, indent=2))

    # Example 2: Walk up from E11.65 to the chapter level.
    print("\n--- Ancestors of E11.65 ---")
    result = handle_api_request("ancestors", "E11.65")
    print(json.dumps(result, indent=2))

    # Example 3: What CPT codes does E11.65 justify?
    print("\n--- Cross-walks from E11.65 to CPT ---")
    result = handle_api_request("crosswalks", "E11.65")
    print(json.dumps(result, indent=2))

    # Example 4: What codes can't be reported with E11?
    print("\n--- Exclusions for E11 ---")
    result = handle_api_request("exclusions", "E11")
    print(json.dumps(result, indent=2))

    # Example 5: What are the sibling codes of E11.65?
    print("\n--- Siblings of E11.65 ---")
    result = handle_api_request("siblings", "E11.65")
    print(json.dumps(result, indent=2))
```

---

## The Gap Between This and Production

This example works. Point it at a Neptune cluster with loaded ICD-10-CM data and it will return structured hierarchy traversals. But there's a meaningful distance between "works in a script" and "runs in a coding department handling real claims." Here's where that gap lives:

**Error handling.** Right now, if Neptune returns an error or the network times out, the whole thing crashes. A production system wraps every Neptune call in try/except blocks with specific handling for connection timeouts (Neptune is in a VPC, network issues happen), query timeouts (broad subtree traversals can be slow), and malformed responses. You want graceful degradation: return a partial result or a clear error message, not a stack trace.

**Retries and backoff.** Neptune can return throttling errors under sustained query load. The `requests` library doesn't retry by default. A production system uses `urllib3.util.retry.Retry` or a similar mechanism with exponential backoff. For the bulk loader specifically, you need polling logic that checks load status every few seconds until completion.

**Input validation.** This code trusts its inputs completely. A production system validates that the code parameter matches ICD-10-CM or CPT format before querying, rejects depth values that would cause unreasonably broad traversals (depth=99 on a chapter code returns thousands of results), and sanitizes any user-provided strings before passing them as openCypher parameters (even though parameterized queries prevent injection, defense in depth matters).

**Caching.** The main recipe describes a Redis caching layer. This example skips it entirely. In production, every query function checks Redis first (using a cache key built from code + query_type + depth + version), returns the cached result on hit, and stores the Neptune result on miss. Cache hit rates of 85-95% are typical because the same popular codes get queried repeatedly. Flush the cache on version updates.

**Connection pooling.** Each `requests.post()` call in this example opens a new HTTPS connection to Neptune. In production, use a `requests.Session()` with connection pooling to reuse TCP connections. Neptune supports persistent connections and the overhead of TLS handshakes on every query adds up at scale.

**IAM least-privilege.** The IAM role for the query Lambda should have exactly `neptune-db:ReadDataViaQuery` (not `neptune-db:*`). The ETL Lambda needs `neptune-db:WriteDataViaQuery` and the loader permissions. The Neptune load role needs only `s3:GetObject` on the specific staging bucket prefix. Separate roles for separate functions.

**VPC configuration.** Neptune requires VPC deployment. Your Lambda functions must be in the same VPC with security groups that allow outbound traffic to Neptune's port (8182). Add VPC endpoints for S3 (gateway endpoint, free) and CloudWatch Logs (interface endpoint) so Lambda can reach those services without a NAT gateway.

**Monitoring.** In production, emit CloudWatch metrics for: query latency (p50, p95, p99), cache hit rate, Neptune connection errors, bulk load duration, and graph size (node/edge counts). Set alarms on query latency spikes (which indicate cache misses after a version update) and on Neptune CPU utilization (which indicates queries that need optimization).

**The annual version transition.** The `apply_version_update` function here is simplified. In production, you'd run it in a staging environment first, validate that the new version's hierarchy is correct (spot-check known codes), then promote to production. The GEMs mappings are approximate, not exact. Some retired codes map to multiple replacements (one-to-many splits). Your analytics team needs to understand that historical queries spanning a version boundary may have slight discontinuities.

**Neptune openCypher limitations.** Neptune's openCypher support is good but not complete. Variable-length path patterns work, but some advanced Cypher features (like APOC procedures from Neo4j) don't exist. The `%d` string formatting for path length in this example is a workaround for Neptune not supporting parameterized path lengths. Test your specific query patterns against Neptune during development, not just against a local Neo4j instance.

**Testing.** There are no tests here. A production pipeline has unit tests for `derive_parent_code` (with known code/parent pairs), integration tests against a Neptune cluster loaded with a known subset of codes, and validation scripts that verify the loaded graph matches expected node/edge counts. Use the CMS-published code counts as your ground truth.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.3](chapter13.03-icd-cpt-hierarchy-navigation.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
