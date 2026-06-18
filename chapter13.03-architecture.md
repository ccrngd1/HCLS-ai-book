# Recipe 13.3 Architecture and Implementation: ICD/CPT Hierarchy Navigation

*Companion to [Recipe 13.3: ICD/CPT Hierarchy Navigation](chapter13.03-icd-cpt-hierarchy-navigation). This page covers the AWS architecture, services, prerequisites, and pseudocode walkthrough. For the problem framing, conceptual approach, and honest assessment, start with the main recipe.*

---

## Why These Services

**Amazon Neptune for graph storage and traversal.** Neptune is AWS's managed graph database, supporting both property graph (Gremlin/openCypher) and RDF (SPARQL) query models. For ICD/CPT hierarchy navigation, the property graph model with openCypher is the natural fit: codes are nodes with properties, relationships are typed edges with metadata. Neptune handles the index management, replication, and backup that you'd otherwise manage yourself. It's also on the HIPAA eligible services list, which matters because code assignments linked to patients are PHI-adjacent (they're part of the designated record set). Use Neptune's reader endpoint for query traffic and the cluster (writer) endpoint for bulk loads so read and write workloads don't compete.

**Amazon S3 for source file staging.** CMS and AMA publish code files as downloadable archives. These land in S3 as the first step of the ingestion pipeline. S3 also serves as the staging area for Neptune bulk load operations, which expect source data in S3.

**AWS Lambda for ETL orchestration.** The parsing and loading pipeline runs periodically (annually for ICD, quarterly for CPT) and is a short-lived batch job. Lambda functions parse the source files, transform them into Neptune bulk load format (CSV with node/edge headers), and trigger the load. For the annual ICD update, this is a few minutes of compute.

**Amazon API Gateway + Lambda for the query API.** Downstream consumers need a REST interface, not direct graph database access. API Gateway provides the HTTP layer; Lambda functions translate REST requests into openCypher queries, execute them against Neptune, and return structured JSON. This also gives you throttling, authentication, and usage tracking for free.

**Amazon ElastiCache (Redis) for query caching.** Hierarchy traversals are deterministic for a given code version. The children of E11 don't change between October updates. Caching traversal results in Redis eliminates repeated graph queries for popular codes and keeps response times under 50ms for cached paths.

## Architecture Diagram

```mermaid
flowchart TD
    A[CMS/AMA Code Files] -->|Download| B[S3 Bucket\ncode-sources/]
    B -->|Parse & Transform| C[Lambda\ncode-etl]
    C -->|Bulk Load CSV| D[S3 Bucket\nneptune-staging/]
    D -->|Neptune Bulk Loader| E[Amazon Neptune\nCode Graph]
    
    F[API Gateway\n/codes/*] -->|REST| G[Lambda\nquery-handler]
    G -->|Check Cache| H[ElastiCache Redis]
    H -->|Cache Miss| G
    G -->|openCypher| E
    G -->|JSON Response| F
    
    F --> I[Coding Tools]
    F --> J[Analytics Platform]
    F --> K[Rules Engine]

    style E fill:#9ff,stroke:#333
    style H fill:#ff9,stroke:#333
```

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Neptune, Amazon S3, AWS Lambda, Amazon API Gateway, Amazon ElastiCache (Redis), AWS KMS |
| **IAM Permissions** | Query handler Lambda: `neptune-db:ReadDataViaQuery`, `neptune-db:GetQueryStatus` (scoped to cluster ARN). ETL Lambda: `neptune-db:WriteDataViaQuery`, `neptune-db:ReadDataViaQuery`, `neptune-db:GetLoaderStatus` (scoped to cluster ARN). Both: `s3:GetObject`, `s3:PutObject` (scoped to relevant buckets), `kms:Decrypt`, `kms:GenerateDataKey` (scoped to S3 encryption key). |
| **BAA** | BAA must be signed. Code assignments linked to patients are PHI (part of the designated record set). |
| **Encryption** | Neptune: encryption at rest (enabled at cluster creation, cannot be added later). S3: SSE-KMS. ElastiCache: in-transit and at-rest encryption. All API calls over TLS. |
| **VPC** | Neptune requires VPC deployment. Lambda functions in same VPC with security groups: Lambda SG allows outbound to Neptune (port 8182), ElastiCache (port 6379), and VPC endpoints (port 443). Neptune SG allows inbound from Lambda SG on 8182. ElastiCache SG allows inbound from Lambda SG on 6379. VPC endpoints required: S3 (gateway), CloudWatch Logs (interface), KMS (interface). If Lambdas have no NAT/internet egress, also add Neptune management endpoint. |
| **CloudTrail** | Enabled for Neptune API calls and S3 access logging. Enable Neptune audit logging via cluster parameter group (`neptune_enable_audit_log = 1`) for query-level audit trail. |
| **Sample Data** | CMS publishes ICD-10-CM files at [cms.gov/medicare/coding-billing/icd-10-codes](https://www.cms.gov/medicare/coding-billing/icd-10-codes). CPT requires AMA license. Use ICD-10-CM (free) for development; add CPT when licensed. |
| **Cost Estimate** | Neptune db.r5.large: ~$0.348/hr (~$254/month). Neptune I/O: ~$0.20 per million requests (at 1M queries/month with 85% cache hit rate, expect ~150K Neptune I/Os, negligible; spikes during cache-cold periods post-update). ElastiCache cache.t3.medium: ~$0.068/hr (~$50/month). Lambda and API Gateway negligible at query volumes under 1M/month. |

## Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Neptune** | Stores code hierarchy as property graph; executes traversal queries (reader endpoint for queries, cluster endpoint for loads) |
| **Amazon S3** | Stages source code files and Neptune bulk load CSVs |
| **AWS Lambda** | ETL pipeline (parse/transform/load) and query handler |
| **Amazon API Gateway** | REST interface for downstream consumers |
| **Amazon ElastiCache** | Caches traversal results for sub-50ms response on popular codes |
| **AWS KMS** | Encryption keys for Neptune, S3, and ElastiCache |
| **Amazon CloudWatch** | Query latency metrics, cache hit rates, ETL job monitoring |

## Pseudocode Walkthrough

**Step 1: Parse ICD-10-CM source files into graph nodes and edges.** CMS distributes ICD-10-CM as a set of flat files: a tabular code list with descriptions, and an "order file" that encodes the hierarchy through indentation levels and parent references. This step reads those files and produces two outputs: a node list (one row per code with its properties) and an edge list (one row per relationship). The hierarchy is encoded in the code structure itself (E11 is parent of E11.6, which is parent of E11.65), but the source files also contain explicit "includes," "excludes1," and "excludes2" annotations that become additional edge types. Skip this step and you have no graph to query. Get the parsing wrong and your hierarchy traversals return incorrect results, which means wrong cohort counts and invalid coding suggestions.

```text
FUNCTION parse_icd10_to_graph(source_file_path):
    // Read the CMS order file. Each line contains:
    //   - Code (positional, chars 1-7)
    //   - Whether it's a "header" (non-billable parent) or "billable" leaf
    //   - Short description and long description
    raw_codes = read and parse CMS order file from source_file_path

    nodes = empty list   // will hold one entry per code
    edges = empty list   // will hold one entry per relationship

    FOR each code_entry in raw_codes:
        // Create a node for this code
        node = {
            id: code_entry.code,                    // e.g., "E11.65"
            label: "ICD10CM",                          // node type label
            description: code_entry.long_description,        // human-readable name
            short_desc: code_entry.short_description,       // abbreviated name
            is_billable: code_entry.is_billable,             // true = leaf code, false = category header
            chapter: derive_chapter(code_entry.code),    // e.g., "4" for E codes (Endocrine)
            version: "FY2026"                            // fiscal year this code is valid in
        }
        append node to nodes

        // Derive parent from code structure:
        //   E11.65 → parent is E11.6
        //   E11.6  → parent is E11
        //   E11    → parent is E08-E13 block (or chapter node)
        parent_code = derive_parent(code_entry.code)
        IF parent_code is not null:
            edge = {
                source: code_entry.code,
                target: parent_code,
                type: "IS_CHILD_OF"
            }
            append edge to edges

    // Parse the excludes/includes annotations (separate CMS file)
    annotations = parse_annotation_file(source_file_path + "/annotations")
    FOR each annotation in annotations:
        edge = {
            source: annotation.code,
            target: annotation.referenced_code,
            type: annotation.relationship_type,   // "EXCLUDES1", "EXCLUDES2", "CODE_FIRST", etc.
            note: annotation.description          // human-readable explanation
        }
        append edge to edges

    RETURN nodes, edges
```

**Step 2: Parse CPT codes and cross-walk mappings.** CPT has its own hierarchy (sections, subsections, code ranges) and the critical cross-walk file maps ICD-10 diagnosis codes to CPT procedure codes for medical necessity validation. The cross-walk data comes from CMS for Medicare (the "Medically Unlikely Edits" and "Correct Coding Initiative" files) and from individual payers for commercial plans. This step produces additional nodes (CPT codes) and cross-walk edges connecting the two systems. Without this step, your graph answers hierarchy questions but can't answer the cross-system questions that coding and billing teams actually need.

```text
FUNCTION parse_cpt_and_crosswalks(cpt_source, crosswalk_source):
    nodes = empty list
    edges = empty list

    // Parse CPT hierarchy (requires AMA license)
    cpt_codes = parse_cpt_file(cpt_source)
    FOR each cpt_entry in cpt_codes:
        node = {
            id: "CPT:" + cpt_entry.code,        // prefix to distinguish from ICD
            label: "CPT",
            description: cpt_entry.description,
            section: cpt_entry.section,              // e.g., "Surgery", "Medicine"
            subsection: cpt_entry.subsection,
            is_addon: cpt_entry.is_addon_code,        // add-on codes can't be billed alone
            version: "2026"
        }
        append node to nodes

        // CPT parent-child from section hierarchy
        IF cpt_entry.parent_range is not null:
            edge = {
                source: "CPT:" + cpt_entry.code,
                target: "CPT:" + cpt_entry.parent_range,
                type: "IS_CHILD_OF"
            }
            append edge to edges

    // Parse ICD-to-CPT cross-walk (medical necessity mappings)
    crosswalks = parse_crosswalk_file(crosswalk_source)
    FOR each mapping in crosswalks:
        edge = {
            source: mapping.icd_code,                 // ICD-10-CM code
            target: "CPT:" + mapping.cpt_code,        // CPT code
            type: "CROSS_WALKS_TO",
            payer: mapping.payer,                     // "Medicare" or specific payer
            effective: mapping.effective_date,
            end_date: mapping.end_date                   // null if currently active
        }
        append edge to edges

    RETURN nodes, edges
```

**Step 3: Bulk load into Neptune.** Neptune's bulk loader expects CSV files in S3 with specific header conventions. Node files need `~id`, `~label`, and property columns. Edge files need `~id`, `~from`, `~to`, `~label`, and property columns. This step transforms the parsed data into that format and triggers the load. Bulk loading is dramatically faster than inserting nodes one at a time via Gremlin or openCypher (minutes vs. hours for 70,000+ nodes). For true upsert behavior (updating existing nodes with new property values on reload), use `mode=AUTO` with `updateSingleCardinalityProperties=TRUE`. Without these parameters, reloading a file with changed descriptions will skip existing nodes rather than updating them.

```text
FUNCTION load_graph_to_neptune(nodes, edges, neptune_endpoint, s3_staging_bucket):
    // Transform nodes into Neptune CSV format
    node_csv = format_as_neptune_csv(nodes, type="nodes")
    // Columns: ~id, ~label, description:String, is_billable:Bool, chapter:String, version:String

    // Transform edges into Neptune CSV format
    edge_csv = format_as_neptune_csv(edges, type="edges")
    // Columns: ~id, ~from, ~to, ~label, note:String, payer:String, effective:Date

    // Upload to S3 staging bucket
    upload node_csv to s3_staging_bucket + "/nodes/icd10_nodes.csv"
    upload edge_csv to s3_staging_bucket + "/edges/icd10_edges.csv"

    // Trigger Neptune bulk load
    response = call Neptune Loader API:
        source      = s3_staging_bucket
        format      = "csv"
        iamRoleArn  = neptune_load_role_arn    // Neptune needs an IAM role to read from S3
        region      = current_region
        mode        = "AUTO"                   // upsert: update existing, insert new
        failOnError = "FALSE"                  // log errors but continue loading valid records
        parallelism = "HIGH"                   // use all available loader threads
        updateSingleCardinalityProperties = "TRUE"  // update properties on existing nodes

    // Monitor load status
    WHILE load is not complete:
        status = check Neptune Loader status(response.loadId)
        IF status == "LOAD_FAILED":
            log error details
            RAISE exception
        wait 5 seconds

    RETURN load statistics (nodes loaded, edges loaded, errors)
```

**Step 4: Query the hierarchy.** This is where the graph pays off. Queries that would be recursive CTEs in SQL become simple traversal expressions in openCypher. The query handler Lambda receives REST requests, translates them into openCypher, executes against Neptune, and returns structured JSON. Common query patterns: get all descendants (for cohort building), get ancestors (for rollup reporting), find cross-walks (for coding validation), check exclusions (for claim editing). Each query type is a different traversal pattern but they all follow the same execute-and-format flow.

```text
FUNCTION handle_query(request):
    code       = request.path_params.code          // e.g., "E11"
    query_type = request.path_params.query_type    // "children", "ancestors", "crosswalks", "exclusions"
    depth      = request.query_params.depth OR 10  // how many levels to traverse (default: 10)
    version    = request.query_params.version OR current_fiscal_year()
    page_size  = request.query_params.limit OR 100
    offset     = request.query_params.offset OR 0

    // Validate input: reject malformed codes at the API layer.
    // ICD-10 pattern: letter + digits + optional dot + digits
    // CPT pattern: "CPT:" prefix + 4-5 digits
    IF code does not match "^[A-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$"
       AND code does not match "^(CPT:)?[0-9]{4,5}$":
        RETURN 400 Bad Request ("Invalid code format")

    // Clamp depth to prevent unreasonably broad traversals
    depth = max(1, min(depth, 20))

    // Check cache first.
    // Key includes resolved version (not "current") to avoid ambiguity across updates.
    cache_key = build_cache_key(code, query_type, depth, version, page_size, offset)
    cached = lookup cache_key in Redis
    IF cached is not null:
        RETURN cached

    // Build the appropriate openCypher query.
    // Note: Neptune openCypher does not support parameterized variable-length
    // path bounds. The depth value must be interpolated as a literal integer
    // (safe here because we validated it as an integer above).
    IF query_type == "children":
        // Find all descendants up to specified depth
        cypher = "
            MATCH path = (start {id: $code})<-[:IS_CHILD_OF*1..{depth}]-(descendant)
            WHERE descendant.version = $version
            RETURN descendant.id AS code,
                   descendant.description AS description,
                   descendant.is_billable AS billable,
                   length(path) AS depth_level
            ORDER BY descendant.id
            SKIP $offset LIMIT $page_size
        "
        // {depth} is interpolated as a literal integer, not a parameter

    ELSE IF query_type == "ancestors":
        // Walk up the hierarchy to the chapter level
        cypher = "
            MATCH path = (start {id: $code})-[:IS_CHILD_OF*1..10]->(ancestor)
            RETURN ancestor.id AS code,
                   ancestor.description AS description,
                   length(path) AS levels_up
            ORDER BY levels_up
        "

    ELSE IF query_type == "crosswalks":
        // Find all codes in the other system linked by cross-walk edges
        target_system = request.query_params.target OR "CPT"
        cypher = "
            MATCH (start {id: $code})-[r:CROSS_WALKS_TO]->(target)
            WHERE target.`~label` = $target_system
            RETURN target.id AS code,
                   target.description AS description,
                   r.payer AS payer,
                   r.effective AS effective_date
            SKIP $offset LIMIT $page_size
        "

    ELSE IF query_type == "exclusions":
        // Find codes that cannot be reported together with this one
        cypher = "
            MATCH (start {id: $code})-[r:EXCLUDES1]-(excluded)
            RETURN excluded.id AS code,
                   excluded.description AS description,
                   'EXCLUDES1' AS exclusion_type
        "

    // Execute against Neptune (use reader endpoint for queries)
    result = execute_cypher(neptune_reader_endpoint, cypher, params={code, version, offset, page_size})

    // Cache the result.
    // TTL = 24 hours. After a version update, flush the cache (see Step 5).
    store cache_key -> result in Redis with TTL 86400

    RETURN format_as_json(result)
```

**Step 5: Handle version transitions.** When CMS publishes a new ICD-10-CM version each October, the graph needs to incorporate the changes without destroying history. New codes get new nodes. Retired codes get a `SUPERSEDED_BY` edge pointing to their replacement. Modified codes get updated properties with the new version tag. This step runs as part of the annual ETL and ensures that queries scoped to any historical version still return correct results. Skip this and you lose the ability to analyze claims across fiscal year boundaries, which breaks any longitudinal analytics.

```text
FUNCTION apply_version_update(new_version_nodes, new_version_edges, current_version, new_version):
    // Identify changes: new codes, retired codes, modified descriptions
    current_codes = query Neptune for all nodes where version = current_version
    new_codes     = set of new_version_nodes not in current_codes
    retired_codes = set of current_codes not in new_version_nodes
    modified      = set of codes in both but with changed descriptions

    // Add new codes as new nodes
    FOR each code in new_codes:
        create node in Neptune with version = new_version

    // Mark retired codes with SUPERSEDED_BY edges
    FOR each code in retired_codes:
        // CMS publishes a "GEMs" (General Equivalence Mappings) file
        // that maps old codes to their replacements
        replacement = lookup_gem_mapping(code, new_version)
        IF replacement exists:
            create edge: code -[:SUPERSEDED_BY {effective: new_version}]-> replacement
        // Mark the old node as inactive but don't delete it
        update node property: code.status = "RETIRED"
        update node property: code.retired_in = new_version

    // Update modified descriptions
    FOR each code in modified:
        // Don't overwrite: create a versioned property
        update node: code.description = new_description
        update node: code.version = new_version
        // Preserve old description as historical property
        add property: code.description_prior = old_description

    // Add new version's edges (new cross-walks, updated exclusions)
    FOR each edge in new_version_edges:
        IF edge does not exist in current graph:
            create edge with effective_date = new_version

    // Flush the Redis cache after a successful version update.
    // All cached traversal results may now be stale.
    flush Redis cache (or at minimum, flush keys matching the updated version)

    log "Version update complete: {new_codes.count} added, {retired_codes.count} retired, {modified.count} modified"
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3 and the Neptune openCypher endpoint, check out the [Python Example](chapter13.03-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

## Expected Results

**Sample output for a "children" query on E11 (Type 2 diabetes):**

```json
{
  "code": "E11",
  "description": "Type 2 diabetes mellitus",
  "query_type": "children",
  "depth_requested": 2,
  "version": "FY2026",
  "results": [
    {"code": "E11.0", "description": "Type 2 diabetes mellitus with hyperosmolarity", "billable": false, "depth_level": 1},
    {"code": "E11.00", "description": "Type 2 DM with hyperosmolarity without nonketotic hyperglycemic-hyperosmolar coma", "billable": true, "depth_level": 2},
    {"code": "E11.01", "description": "Type 2 DM with hyperosmolarity with coma", "billable": true, "depth_level": 2},
    {"code": "E11.1", "description": "Type 2 diabetes mellitus with ketoacidosis", "billable": false, "depth_level": 1},
    {"code": "E11.10", "description": "Type 2 DM with ketoacidosis without coma", "billable": true, "depth_level": 2},
    {"code": "E11.11", "description": "Type 2 DM with ketoacidosis with coma", "billable": true, "depth_level": 2},
    {"code": "E11.2", "description": "Type 2 diabetes mellitus with kidney complications", "billable": false, "depth_level": 1},
    {"code": "E11.21", "description": "Type 2 DM with diabetic nephropathy", "billable": true, "depth_level": 2},
    {"code": "E11.22", "description": "Type 2 DM with diabetic chronic kidney disease", "billable": true, "depth_level": 2}
  ],
  "total_results": 147,
  "truncated": true,
  "next_offset": 9,
  "query_time_ms": 23
}
```

**Sample output for a "crosswalks" query:**

```json
{
  "code": "E11.65",
  "description": "Type 2 diabetes mellitus with hyperglycemia",
  "query_type": "crosswalks",
  "target_system": "CPT",
  "results": [
    {"code": "CPT:82947", "description": "Glucose; quantitative, blood", "payer": "Medicare", "effective_date": "2024-01-01"},
    {"code": "CPT:83036", "description": "Hemoglobin; glycosylated (A1C)", "payer": "Medicare", "effective_date": "2024-01-01"},
    {"code": "CPT:80053", "description": "Comprehensive metabolic panel", "payer": "Medicare", "effective_date": "2024-01-01"}
  ],
  "total_results": 3,
  "query_time_ms": 8
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Single-code lookup | 5-15ms (cached: <2ms) |
| Subtree traversal (depth 3) | 20-50ms |
| Full subtree (all descendants) | 50-200ms depending on subtree size |
| Cross-walk query | 8-30ms |
| Exclusion check | 5-10ms |
| Bulk load (full ICD-10-CM) | 3-5 minutes |
| Cache hit rate (production) | 85-95% for popular codes |
| Graph size | ~80,000 nodes, ~500,000 edges (ICD + CPT + cross-walks) |

**Where it struggles:** Very broad subtree queries (like "all children of Chapter 4" which returns thousands of codes) can be slow without pagination. Cross-walk queries for codes with hundreds of valid pairings need result limits. And the annual version transition creates a brief period where the cache is cold and query latency spikes (and Neptune I/O costs spike correspondingly).

---

<!-- TODO (TechWriter): Add "Why This Isn't Production-Ready" section per RECIPE-GUIDE.md. Should appear between Expected Results and Variations. -->

## Variations and Extensions

**Coding assistance with similarity search.** Combine the hierarchy graph with a text embedding model. When a coder types a free-text description ("chest wall pain after coughing"), embed it, find the nearest code descriptions in vector space, then use the graph to show the full context: parent codes, sibling codes, and exclusions. The graph turns a flat similarity search into a navigable decision tree.

**Payer-specific rule overlays.** Different payers have different medical necessity rules (which ICD codes justify which CPT codes). Model each payer's rules as a separate edge set in the same graph, tagged by payer ID. A single query can then answer "is this ICD/CPT combination valid for Blue Cross?" by filtering cross-walk edges to that payer. This eliminates maintaining separate lookup tables per payer. Important: if you implement payer-specific cross-walks, include the payer ID in the cache key to prevent cross-tenant data leakage. The base hierarchy cache (public ICD/CPT structure) is safe to share, but payer-specific results must be isolated.

**Real-time claim editing integration.** Connect the graph API to your claims adjudication pipeline. Before a claim is submitted, query the graph for exclusion violations (codes that can't be billed together), bundling opportunities (multiple codes that should be a single code), and medical necessity validation (does the diagnosis justify the procedure?). This catches errors before they become denials.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Neptune User Guide](https://docs.aws.amazon.com/neptune/latest/userguide/intro.html)
- [Neptune openCypher Query Language](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html)
- [Neptune Bulk Loader](https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html)
- [Neptune CSV Format for Bulk Loading](https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load-tutorial-format-gremlin.html)
- [Amazon Neptune Pricing](https://aws.amazon.com/neptune/pricing/)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**CMS Code Resources:**
- [ICD-10-CM Official Code Files (CMS)](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- [CMS General Equivalence Mappings (GEMs)](https://www.cms.gov/medicare/coding-billing/icd-10-codes/general-equivalence-mappings-gems)
- [National Correct Coding Initiative (NCCI) Edits](https://www.cms.gov/medicare/coding-billing/national-correct-coding-initiative-edits)

**AWS Solutions and Blogs:**
- [Building a Knowledge Graph on AWS](https://aws.amazon.com/blogs/database/building-a-knowledge-graph-application-with-amazon-neptune/)
- [Analyze Amazon Neptune Graphs using openCypher](https://aws.amazon.com/blogs/database/analyze-amazon-neptune-graphs-using-amazon-neptune-analytics/)

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| **Basic** (ICD-10-CM hierarchy only, single version) | 2-3 weeks |
| **Production-ready** (ICD + CPT + cross-walks, versioning, caching, monitoring) | 6-8 weeks |
| **With variations** (payer-specific rules, coding assistance, claim editing integration) | 10-14 weeks |

---

*← [Main Recipe 13.3](chapter13.03-icd-cpt-hierarchy-navigation) · [Python Example](chapter13.03-python-example) · [Chapter Preface](chapter13-preface)*
