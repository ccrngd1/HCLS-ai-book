# Recipe 13.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.2. It shows one way you could translate those graph concepts into working Python code using boto3 and Neptune's openCypher endpoint. It is not production-ready. There's no connection pooling, no retry logic beyond what boto3 provides, no input validation. Think of it as the sketchpad version: useful for understanding how provider directory data flows into a graph and how traversal queries work, not something you'd deploy to a member portal on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for Neptune (`neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery`, `neptune-db:connect`, and `neptune-db:StartLoaderJob` scoped to your cluster), S3 (`s3:GetObject` and `s3:PutObject` on the staging bucket), and network access to Neptune from within your VPC. In production, split read and write permissions into separate roles (see the main recipe's Prerequisites table).

Neptune doesn't use IAM for query authentication by default (it uses VPC-level network isolation). If you've enabled IAM auth on your cluster, you'll need to sign requests with SigV4. This example assumes VPC network access without IAM auth for simplicity.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These constants define the Neptune endpoint, the graph schema (node labels and edge types), and the NUCC specialty taxonomy codes we'll use for hierarchical queries.

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
# PHI Safety: Never log patient identifiers or member-provider assignments.
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
STAGING_BUCKET = "my-provider-directory-staging"

# Neptune bulk loader IAM role. This role must have S3 read access
# to the staging bucket and a trust policy allowing Neptune to assume it.
NEPTUNE_LOAD_ROLE_ARN = "arn:aws:iam::123456789012:role/NeptuneLoadFromS3"

# AWS region for all service calls.
AWS_REGION = "us-east-1"

# Node labels in our graph schema.
# These match the schema defined in the main recipe's Step 1.
NODE_LABELS = {
    "provider": "Provider",
    "location": "Location",
    "specialty": "Specialty",
    "organization": "Organization",
    "network": "Network",
    "facility": "Facility",
}

# Edge types connecting our nodes.
EDGE_TYPES = {
    "practices_at": "PRACTICES_AT",
    "has_specialty": "HAS_SPECIALTY",
    "has_privileges": "HAS_PRIVILEGES",
    "member_of": "MEMBER_OF",
    "in_network": "IN_NETWORK",
    "located_in": "LOCATED_IN",
    "is_subspecialty": "IS_SUBSPECIALTY",
    "covers_for": "COVERS_FOR",
}

# A small subset of NUCC taxonomy codes for cardiology specialties.
# In production, you'd load the full NUCC taxonomy file (~800 codes)
# and build the hierarchy from it. This subset demonstrates the pattern.
SAMPLE_SPECIALTY_HIERARCHY = {
    "207R00000X": {"name": "Internal Medicine", "parent": None},
    "207RC0000X": {"name": "Cardiovascular Disease", "parent": "207R00000X"},
    "207RI0011X": {"name": "Interventional Cardiology", "parent": "207RC0000X"},
    "207RE0101X": {"name": "Cardiac Electrophysiology", "parent": "207RC0000X"},
    "207RH0003X": {"name": "Hematology & Oncology", "parent": "207R00000X"},
    "2086S0120X": {"name": "Pediatric Cardiology", "parent": None},
    "208600000X": {"name": "Surgery", "parent": None},
    "2086S0105X": {"name": "Cardiothoracic Surgery", "parent": "208600000X"},
}
```

---

## Step 1: Parse Source Data (NPI Registry)

*The pseudocode calls this part of `ingest_provider_data(sources)`. Here we parse the NPPES NPI data file from S3. The real NPPES file is a massive CSV (~8GB) with 300+ columns. We extract the columns relevant to our graph: NPI, name, taxonomy codes, and practice addresses.*

```python
s3_client = boto3.client("s3", region_name=AWS_REGION)


def parse_npi_file(bucket: str, key: str) -> list[dict]:
    """
    Parse the NPPES NPI data file from S3 and extract provider records.

    The NPPES file is freely available from CMS. It contains every NPI
    registration in the US. We only care about individual providers
    (Entity Type 1), not organizations (Entity Type 2).

    Args:
        bucket: S3 bucket containing the NPPES file
        key:    S3 object key for the NPPES CSV

    Returns:
        List of provider dicts with normalized fields ready for graph loading.
    """
    logger.info("Downloading NPI file from s3://%s/%s", bucket, key)

    # Stream the file from S3 rather than loading it all into memory.
    # The full NPPES file is ~8GB. In production, use Glue or EMR
    # for this. Here we demonstrate the logic on a smaller extract.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(content))
    providers = []

    for row in reader:
        # Only individual providers (Entity Type Code 1).
        # Type 2 is organizations. We model those separately.
        if row.get("Entity Type Code") != "1":
            continue

        npi = row.get("NPI", "").strip()
        if not npi:
            continue

        # Extract the primary taxonomy code. NPPES allows up to 15
        # taxonomy codes per provider. The one marked as primary
        # (via the "Is Primary" flag) is what we use for specialty assignment.
        primary_taxonomy = None
        for i in range(1, 16):
            code_col = f"Healthcare Provider Taxonomy Code_{i}"
            primary_col = f"Healthcare Provider Primary Taxonomy Switch_{i}"
            if row.get(primary_col) == "Y":
                primary_taxonomy = row.get(code_col, "").strip()
                break

        # If no primary flag is set, fall back to the first taxonomy code.
        if not primary_taxonomy:
            primary_taxonomy = row.get(
                "Healthcare Provider Taxonomy Code_1", ""
            ).strip()

        # Build the provider record for our graph.
        provider = {
            "npi": npi,
            "first_name": row.get("Provider First Name", "").strip(),
            "last_name": row.get("Provider Last Name (Legal Name)", "").strip(),
            "gender": row.get("Provider Gender Code", "").strip(),
            "primary_taxonomy": primary_taxonomy,
            # Practice location address (first practice address in NPPES)
            "address_line1": row.get(
                "Provider First Line Business Practice Location Address", ""
            ).strip(),
            "city": row.get(
                "Provider Business Practice Location Address City Name", ""
            ).strip(),
            "state": row.get(
                "Provider Business Practice Location Address State Name", ""
            ).strip(),
            "zip": row.get(
                "Provider Business Practice Location Address Postal Code", ""
            ).strip()[:5],  # First 5 digits only
        }

        providers.append(provider)

    logger.info("Parsed %d individual providers from NPI file", len(providers))
    return providers
```

---

## Step 2: Build Neptune Bulk Load CSVs

*The pseudocode calls this `write_nodes_csv()` and `write_edges_csv()`. Neptune's bulk loader expects a specific CSV format: node files have `~id`, `~label`, and property columns; edge files have `~id`, `~from`, `~to`, `~label`, and property columns. We transform our parsed provider data into these formats.*

```python
def build_provider_nodes_csv(providers: list[dict]) -> str:
    """
    Transform provider records into Neptune bulk load CSV format for nodes.

    Neptune node CSV format:
    ~id, ~label, property1, property2, ...

    The ~id must be globally unique across all node types.
    We prefix with the node type to avoid collisions
    (e.g., "provider:1234567890" vs "location:loc-001").

    Args:
        providers: List of provider dicts from parse_npi_file()

    Returns:
        CSV string ready to upload to S3 for Neptune bulk loading.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row. Neptune uses ~ prefix for system columns.
    writer.writerow([
        "~id", "~label",
        "npi:String", "first_name:String", "last_name:String",
        "gender:String", "accepting_new:Bool", "telehealth:Bool",
    ])

    for p in providers:
        writer.writerow([
            f"provider:{p['npi']}",       # unique node ID
            NODE_LABELS["provider"],       # node label
            p["npi"],
            p["first_name"],
            p["last_name"],
            p["gender"],
            "true",   # default to accepting; update from credentialing data later
            "false",  # default to no telehealth; update from provider portal
        ])

    return output.getvalue()


def build_location_nodes_csv(providers: list[dict]) -> str:
    """
    Extract unique locations from provider records and format as Neptune node CSV.

    Multiple providers may share a location (same address = same practice).
    We deduplicate by address to avoid creating duplicate location nodes.

    Args:
        providers: List of provider dicts from parse_npi_file()

    Returns:
        CSV string for location nodes.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "~id", "~label",
        "address_line1:String", "city:String", "state:String", "zip:String",
    ])

    # Deduplicate locations by full address string.
    # In production, you'd use geocoding to catch near-duplicates
    # ("123 Main St" vs "123 Main Street").
    seen_locations = set()

    for p in providers:
        # Create a location key from the address components.
        loc_key = f"{p['address_line1']}|{p['city']}|{p['state']}|{p['zip']}"

        if loc_key in seen_locations:
            continue
        seen_locations.add(loc_key)

        # Location ID is a hash of the address for deterministic dedup.
        # In production, use a UUID or SHA-256 prefix to avoid collisions
        # at scale (32-bit hash collides at ~50K entries via birthday paradox).
        loc_id = f"location:{hash(loc_key) & 0xFFFFFFFF:08x}"

        writer.writerow([
            loc_id,
            NODE_LABELS["location"],
            p["address_line1"],
            p["city"],
            p["state"],
            p["zip"],
        ])

    logger.info("Built %d unique location nodes", len(seen_locations))
    return output.getvalue()


def build_specialty_nodes_csv() -> str:
    """
    Build specialty nodes from our taxonomy hierarchy.

    In production, you'd parse the full NUCC taxonomy CSV file.
    Here we use the sample hierarchy defined in our constants.

    Returns:
        CSV string for specialty nodes.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "~id", "~label", "nucc_code:String", "name:String",
    ])

    for code, info in SAMPLE_SPECIALTY_HIERARCHY.items():
        writer.writerow([
            f"specialty:{code}",
            NODE_LABELS["specialty"],
            code,
            info["name"],
        ])

    return output.getvalue()


def build_edges_csv(providers: list[dict]) -> str:
    """
    Build edge CSV connecting providers to locations and specialties.

    Neptune edge CSV format:
    ~id, ~from, ~to, ~label, property1, property2, ...

    Edge IDs must be globally unique. We construct them from the
    relationship type and the connected node IDs.

    Args:
        providers: List of provider dicts from parse_npi_file()

    Returns:
        CSV string for edges.
    """
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "~id", "~from", "~to", "~label", "effective_date:String",
    ])

    today = date.today().isoformat()

    for p in providers:
        provider_id = f"provider:{p['npi']}"

        # Edge: Provider PRACTICES_AT Location
        loc_key = f"{p['address_line1']}|{p['city']}|{p['state']}|{p['zip']}"
        loc_id = f"location:{hash(loc_key) & 0xFFFFFFFF:08x}"

        writer.writerow([
            f"edge:practices:{p['npi']}:{hash(loc_key) & 0xFFFFFFFF:08x}",
            provider_id,
            loc_id,
            EDGE_TYPES["practices_at"],
            today,
        ])

        # Edge: Provider HAS_SPECIALTY Specialty
        if p["primary_taxonomy"] and p["primary_taxonomy"] in SAMPLE_SPECIALTY_HIERARCHY:
            specialty_id = f"specialty:{p['primary_taxonomy']}"
            writer.writerow([
                f"edge:specialty:{p['npi']}:{p['primary_taxonomy']}",
                provider_id,
                specialty_id,
                EDGE_TYPES["has_specialty"],
                today,
            ])

    # Edges: Specialty IS_SUBSPECIALTY_OF parent Specialty
    for code, info in SAMPLE_SPECIALTY_HIERARCHY.items():
        if info["parent"]:
            writer.writerow([
                f"edge:subspec:{code}:{info['parent']}",
                f"specialty:{code}",
                f"specialty:{info['parent']}",
                EDGE_TYPES["is_subspecialty"],
                "",  # no effective_date for taxonomy relationships
            ])

    return output.getvalue()
```

---

## Step 3: Load the Graph via Neptune Bulk Loader

*The pseudocode calls this `load_graph(node_files, edge_files, neptune_endpoint)`. We upload our CSVs to S3, then trigger Neptune's bulk loader API. The loader reads from S3 and populates the graph.*

```python
neptune_client = boto3.client("neptunedata", region_name=AWS_REGION)


def upload_csvs_to_s3(
    provider_csv: str,
    location_csv: str,
    specialty_csv: str,
    edges_csv: str,
) -> str:
    """
    Upload all bulk load CSVs to S3 under a common prefix.

    Neptune's bulk loader can point at an S3 prefix and load all files
    beneath it. We organize by load batch (date-stamped) so we can
    track which load produced which version of the graph.

    Returns:
        The S3 prefix where all files were uploaded.
    """
    prefix = f"bulk-load/{date.today().isoformat()}/"

    files = {
        "providers.csv": provider_csv,
        "locations.csv": location_csv,
        "specialties.csv": specialty_csv,
        "edges.csv": edges_csv,
    }

    for filename, content in files.items():
        s3_client.put_object(
            Bucket=STAGING_BUCKET,
            Key=f"{prefix}{filename}",
            Body=content.encode("utf-8"),
        )
        logger.info("Uploaded %s to s3://%s/%s%s", filename, STAGING_BUCKET, prefix, filename)

    return f"s3://{STAGING_BUCKET}/{prefix}"


def trigger_bulk_load(s3_source: str) -> dict:
    """
    Trigger Neptune's bulk loader to ingest CSVs from S3.

    The bulk loader is the efficient path for initial loads and large
    batch updates. It's significantly faster than individual Gremlin/openCypher
    mutations for anything over a few thousand records.

    Args:
        s3_source: Full S3 URI prefix (e.g., "s3://bucket/bulk-load/2026-05-31/")

    Returns:
        Load status response from Neptune.
    """
    # Neptune's bulk load API is a REST endpoint on the cluster.
    # We use the neptunedata client for this.
    response = neptune_client.start_loader_job(
        source=s3_source,
        format="csv",
        iamRoleArn=NEPTUNE_LOAD_ROLE_ARN,
        s3BucketRegion=AWS_REGION,
        failOnError=False,         # log errors, don't abort entire load
        parallelism="MEDIUM",      # balance speed vs. cluster load
        updateSingleCardinalityProperties=True,  # overwrite existing properties
    )

    load_id = response["payload"]["loadId"]
    logger.info("Bulk load started. Load ID: %s", load_id)

    return {"load_id": load_id, "status": response["status"]}


def check_load_status(load_id: str) -> dict:
    """
    Check the status of a running bulk load job.

    Poll this until status is LOAD_COMPLETED or LOAD_FAILED.
    Typical load times: ~15 minutes for 500K providers.

    Args:
        load_id: The load ID returned by trigger_bulk_load()

    Returns:
        Status dict with overall status and error counts.
    """
    response = neptune_client.get_loader_job_status(loadId=load_id)

    status = response["payload"]["overallStatus"]["status"]
    logger.info("Load %s status: %s", load_id, status)

    return {
        "status": status,
        "total_records": response["payload"]["overallStatus"].get("totalRecords", 0),
        "total_errors": response["payload"]["overallStatus"].get("totalErrors", 0),
    }
```

---

## Step 4: Query the Graph (Provider Search)

*The pseudocode calls this `search_providers(params)`. This is where the graph pays off. We translate a patient's search criteria into an openCypher traversal that reads like the question being asked.*

```python
def execute_opencypher_query(query: str, parameters: dict = None) -> dict:
    """
    Execute an openCypher query against Neptune's HTTP endpoint.

    Neptune supports openCypher via HTTPS POST. The query and parameters
    are sent as form data. Results come back as JSON.

    Args:
        query:      openCypher query string
        parameters: Optional dict of query parameters (for parameterized queries)

    Returns:
        Query results as a dict with "results" key containing matched records.
    """
    payload = {"query": query}
    if parameters:
        payload["parameters"] = json.dumps(parameters)

    # Neptune's openCypher endpoint. Must be reachable from within the VPC.
    response = requests.post(
        NEPTUNE_OPENCYPHER_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response.raise_for_status()

    return response.json()


def search_providers(
    specialty_code: str,
    state: str,
    zip_code: str = None,
    gender: str = None,
    accepting_new: bool = True,
    limit: int = 20,
) -> list[dict]:
    """
    Search for providers matching the given criteria using graph traversal.

    This demonstrates the core value of the graph model: multi-constraint
    provider search expressed as a natural traversal pattern rather than
    a multi-table join.

    In production, you'd combine this with OpenSearch for geospatial
    distance filtering (Neptune doesn't do geo natively). Here we
    filter by state and ZIP as a simplified geographic constraint.

    Args:
        specialty_code: NUCC taxonomy code (e.g., "207RC0000X" for Cardiology)
        state:          Two-letter state code for geographic filtering
        zip_code:       Optional ZIP code for narrower geographic filtering
        gender:         Optional gender filter ("M" or "F")
        accepting_new:  Only return providers accepting new patients
        limit:          Max results to return

    Returns:
        List of provider dicts with location and specialty details.
    """
    # First, get all subspecialty codes beneath the requested specialty.
    # "Cardiology" should match "Interventional Cardiology" too.
    specialty_codes = get_specialty_subtree(specialty_code)

    # Build the openCypher query. We start from providers, then traverse
    # to their specialties and locations to apply filters.
    #
    # The query pattern:
    # 1. Match providers with a specialty in our target set
    # 2. Match their practice locations
    # 3. Filter by geography, gender, accepting status
    # 4. Return provider + location + specialty details
    query = """
    MATCH (p:Provider)-[:HAS_SPECIALTY]->(s:Specialty)
    WHERE s.nucc_code IN $specialty_codes
    MATCH (p)-[:PRACTICES_AT]->(loc:Location)
    WHERE loc.state = $state
    """

    params = {
        "specialty_codes": specialty_codes,
        "state": state,
    }

    # Filter by accepting status. Most patient-facing searches want
    # only providers accepting new patients, but admin views may need all.
    if accepting_new:
        query += "AND p.accepting_new = true\n"

    # Add optional filters. Each one narrows the traversal.
    if zip_code:
        query += "AND loc.zip = $zip_code\n"
        params["zip_code"] = zip_code

    if gender:
        query += "AND p.gender = $gender\n"
        params["gender"] = gender

    # Return the matched providers with their details.
    query += """
    RETURN p.npi AS npi,
           p.first_name AS first_name,
           p.last_name AS last_name,
           p.gender AS gender,
           p.accepting_new AS accepting_new,
           p.telehealth AS telehealth,
           s.name AS specialty_name,
           s.nucc_code AS specialty_code,
           loc.address_line1 AS address,
           loc.city AS city,
           loc.state AS state,
           loc.zip AS zip
    LIMIT $limit
    """
    params["limit"] = limit

    logger.info(
        "Searching providers: specialty=%s, state=%s, zip=%s",
        specialty_code, state, zip_code,
    )

    result = execute_opencypher_query(query, params)

    # Transform Neptune's response format into clean provider dicts.
    providers = []
    for record in result.get("results", []):
        providers.append({
            "npi": record["npi"],
            "name": f"Dr. {record['first_name']} {record['last_name']}",
            "specialty": record["specialty_name"],
            "specialty_code": record["specialty_code"],
            "gender": record["gender"],
            "accepting_new": record["accepting_new"],
            "telehealth": record["telehealth"],
            "location": {
                "address": record["address"],
                "city": record["city"],
                "state": record["state"],
                "zip": record["zip"],
            },
        })

    logger.info("Found %d matching providers", len(providers))
    return providers


def get_specialty_subtree(root_code: str) -> list[str]:
    """
    Traverse the specialty hierarchy to find all subspecialties
    beneath a given specialty code.

    This is the key graph advantage for provider search. When a patient
    searches for "Cardiology," they should also see Interventional
    Cardiologists and Electrophysiologists. The IS_SUBSPECIALTY edges
    make this a simple traversal rather than a hardcoded lookup table.

    Args:
        root_code: NUCC taxonomy code to start from

    Returns:
        List of all codes in the subtree (including the root).
    """
    # openCypher variable-length path pattern.
    # *0.. means "zero or more hops," which includes the starting node itself.
    # Edge direction: child -[:IS_SUBSPECIALTY]-> parent (child points to its parent).
    # So (child)-[:IS_SUBSPECIALTY*0..]->(root) finds all nodes that can
    # reach root by following parent pointers upward, giving us the full
    # subtree beneath root (all descendants + root itself via *0..).
    query = """
    MATCH (root:Specialty {nucc_code: $root_code})
    MATCH (child:Specialty)-[:IS_SUBSPECIALTY*0..]->(root)
    RETURN collect(DISTINCT child.nucc_code) AS codes
    """

    result = execute_opencypher_query(query, {"root_code": root_code})

    codes = []
    for record in result.get("results", []):
        codes = record.get("codes", [])

    # Always include the root code itself.
    if root_code not in codes:
        codes.append(root_code)

    logger.info(
        "Specialty subtree for %s: %d codes (%s)",
        root_code, len(codes), ", ".join(codes),
    )
    return codes
```

---

## Step 5: Incremental Updates

*The pseudocode calls this `apply_incremental_update(change_event)`. Between bulk loads, provider data changes constantly. A provider stops accepting patients, moves locations, or leaves a network. These changes need to propagate to the graph quickly via direct mutations.*

```python
# Whitelist of properties that can be updated via incremental mutations.
# This prevents injection of arbitrary property names into the query.
UPDATABLE_FIELDS = {"accepting_new", "telehealth", "gender"}


def update_provider_property(npi: str, field: str, value) -> dict:
    """
    Update a single property on a provider node.

    This is the incremental update path for simple property changes:
    accepting_new status flips, telehealth flag changes, etc.

    Args:
        npi:   Provider's NPI (unique identifier)
        field: Property name to update (must be in UPDATABLE_FIELDS)
        value: New value for the property

    Returns:
        Query result confirming the update.
    """
    # Validate field name against whitelist. Dynamic property names
    # require string interpolation into the query (openCypher doesn't
    # support parameterized property names). Without this check, a
    # caller could inject arbitrary property mutations.
    if field not in UPDATABLE_FIELDS:
        raise ValueError(
            f"Field '{field}' is not updatable. Allowed: {UPDATABLE_FIELDS}"
        )

    # openCypher doesn't support dynamic property names via parameters
    # in all implementations. Use string formatting for the field name.
    # The whitelist check above ensures only known-safe field names reach here.
    query = f"""
    MATCH (p:Provider {{npi: $npi}})
    SET p.{field} = $value
    RETURN p.npi AS npi
    """

    result = execute_opencypher_query(query, {"npi": npi, "value": value})
    logger.info("Updated provider %s: %s = %s", npi, field, value)
    return result


def add_network_membership(npi: str, network_id: str, effective_date: str) -> dict:
    """
    Add a provider to a network by creating an IN_NETWORK edge.

    This handles the case where a provider joins a new network
    (e.g., signs a new payer contract).

    Args:
        npi:            Provider's NPI
        network_id:     Network identifier
        effective_date: When the network participation begins (ISO date)

    Returns:
        Query result confirming the edge creation.
    """
    query = """
    MATCH (p:Provider {npi: $npi})
    MATCH (n:Network {network_id: $network_id})
    CREATE (p)-[:IN_NETWORK {effective_date: $effective_date}]->(n)
    RETURN p.npi AS npi, n.network_id AS network_id
    """

    result = execute_opencypher_query(query, {
        "npi": npi,
        "network_id": network_id,
        "effective_date": effective_date,
    })
    logger.info("Added provider %s to network %s", npi, network_id)
    return result


def terminate_network_membership(
    npi: str, network_id: str, term_date: str
) -> dict:
    """
    Terminate a provider's network membership by setting the term_date
    on the IN_NETWORK edge.

    We do NOT delete the edge. Historical network participation is needed
    for claims adjudication (was this provider in-network on the date of
    service?). We set a termination date and filter on it in queries.

    Args:
        npi:        Provider's NPI
        network_id: Network identifier
        term_date:  When the network participation ends (ISO date)

    Returns:
        Query result confirming the update.
    """
    query = """
    MATCH (p:Provider {npi: $npi})-[r:IN_NETWORK]->(n:Network {network_id: $network_id})
    WHERE r.term_date IS NULL
    SET r.term_date = $term_date
    RETURN p.npi AS npi, n.network_id AS network_id
    """

    result = execute_opencypher_query(query, {
        "npi": npi,
        "network_id": network_id,
        "term_date": term_date,
    })
    logger.info("Terminated provider %s from network %s effective %s", npi, network_id, term_date)
    return result
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Glue job or orchestration Lambda would call for a full directory refresh.

```python
def run_full_directory_load(npi_file_key: str) -> dict:
    """
    Run the full provider directory graph load pipeline.

    This orchestrates: parse source data, build CSVs, upload to S3,
    trigger Neptune bulk load. In production, this would be a Glue job
    or Step Functions workflow with error handling at each stage.

    Args:
        npi_file_key: S3 key for the NPPES NPI data file in STAGING_BUCKET

    Returns:
        Summary of the load operation.
    """
    # Step 1: Parse the NPI source file.
    logger.info("Step 1: Parsing NPI source data")
    providers = parse_npi_file(STAGING_BUCKET, npi_file_key)
    logger.info("  Parsed %d providers", len(providers))

    # Step 2: Build Neptune bulk load CSVs.
    logger.info("Step 2: Building bulk load CSVs")
    provider_csv = build_provider_nodes_csv(providers)
    location_csv = build_location_nodes_csv(providers)
    specialty_csv = build_specialty_nodes_csv()
    edges_csv = build_edges_csv(providers)
    logger.info("  CSVs built for providers, locations, specialties, and edges")

    # Step 3: Upload CSVs to S3 and trigger Neptune bulk loader.
    logger.info("Step 3: Uploading to S3 and triggering bulk load")
    s3_prefix = upload_csvs_to_s3(provider_csv, location_csv, specialty_csv, edges_csv)
    load_result = trigger_bulk_load(s3_prefix)
    logger.info("  Bulk load triggered: %s", load_result["load_id"])

    return {
        "providers_parsed": len(providers),
        "s3_prefix": s3_prefix,
        "load_id": load_result["load_id"],
        "load_status": load_result["status"],
    }


# Example: run the full pipeline.
if __name__ == "__main__":
    # Load the graph from an NPI extract file.
    result = run_full_directory_load(
        npi_file_key="source-data/npi-extract-2026-05.csv"
    )
    print(json.dumps(result, indent=2))

    # Query the graph: find cardiologists in Kentucky.
    providers = search_providers(
        specialty_code="207RC0000X",  # Cardiovascular Disease
        state="KY",
        zip_code="40202",
        gender="F",
        accepting_new=True,
        limit=10,
    )
    print(f"\nFound {len(providers)} matching providers:")
    for p in providers:
        print(f"  {p['name']} - {p['specialty']} - {p['location']['city']}, {p['location']['state']}")
```

---

## The Gap Between This and Production

This example works against a real Neptune cluster with real NPI data. But there's a meaningful distance between "works in a script" and "powers a member portal handling real provider searches." Here's where that gap lives:

**Error handling.** Every Neptune query and S3 operation can fail. Network timeouts, throttling, malformed data. A production system wraps each external call in try/except with specific handling for connection errors (Neptune is VPC-only, so network issues are common during deployments), throttling (back off and retry), and data validation errors (log and skip malformed records rather than aborting the entire load).

**Connection management.** This example creates a new HTTP connection for every query. Neptune supports WebSocket connections for Gremlin and persistent HTTPS for openCypher. A production query layer maintains a connection pool, handles reconnection on failure, and routes read queries to read replicas while sending writes to the writer endpoint.

**Geospatial filtering.** The search function filters by state and ZIP code, which is crude. A real provider search needs "within 10 miles" distance filtering. Neptune doesn't have native geospatial indexes. The standard pattern is to use OpenSearch for the geo filtering (it has excellent geo_distance support), get back a set of location IDs, then feed those into the Neptune traversal. Recipe 13.2's main text covers this architecture.

**Network membership queries.** The search function doesn't filter by network (insurance plan). In production, you'd add a traversal hop: from the provider, follow IN_NETWORK edges, check that the network matches the patient's plan and that the term_date is null or in the future. This is straightforward to add but requires network nodes to be loaded (which requires payer roster data beyond what NPPES provides).

**Full-text search.** Patients don't search by NUCC code. They type "heart doctor" or "Dr. Patel." You need OpenSearch alongside Neptune for fuzzy name matching and colloquial specialty resolution. The pattern: OpenSearch handles the text query, returns candidate provider IDs, then Neptune handles the relationship traversal (network status, privileges, etc.).

**Data reconciliation.** This example loads from a single source (NPPES). A real directory reconciles multiple sources: credentialing systems (for board certs and accepting status), payer rosters (for network participation), hospital privilege lists, and provider self-service portals. The reconciliation logic (which source wins when they disagree?) is the hardest engineering work in the pipeline. Recipe 5.2 covers entity resolution patterns.

**Bulk load monitoring.** The `trigger_bulk_load` function fires and returns. A production pipeline polls `check_load_status` until completion, handles partial failures (some records rejected), alerts on error rates above threshold, and validates the loaded graph (expected node counts, edge counts, connectivity checks).

**IAM and encryption.** This example assumes VPC network access to Neptune without IAM auth. Production enables IAM authentication on the Neptune cluster (SigV4 request signing), uses KMS customer-managed keys for encryption at rest, and ensures all data in transit uses TLS. The Neptune bulk loader role should have minimal S3 permissions scoped to the specific staging bucket and prefix.

**Testing.** There are no tests here. A production pipeline has unit tests for CSV generation (with known input, verify output format), integration tests against a test Neptune cluster with synthetic data, and validation queries that run after each load to confirm graph integrity (no orphaned edges, expected node counts, specialty hierarchy is connected).

**Query caching.** Popular searches (cardiologists in major metros) hit the same graph paths repeatedly. A production system caches query results in ElastiCache Redis with TTLs aligned to the data refresh frequency. Cache invalidation triggers on incremental updates that affect cached results.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.2](chapter13.02-provider-directory-knowledge-graph.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
