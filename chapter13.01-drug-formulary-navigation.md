# Recipe 13.1: Drug Formulary Navigation ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.01 per query

---

## The Problem

A physician is writing a prescription for atorvastatin. The patient's insurance plan covers it, but only at Tier 3. There's a therapeutically equivalent statin on Tier 1 that would save the patient $40 a month. The physician doesn't know this. The patient fills the prescription, sees the copay, calls the office, the office calls the pharmacy, the pharmacy calls the PBM, and eventually someone figures out that rosuvastatin was the preferred alternative all along.

This happens millions of times a day across the US healthcare system.

Drug formularies are the lists that health plans maintain to define which medications they cover, at what cost tier, with what restrictions (prior authorization, step therapy, quantity limits). They're the rulebook for prescription drug benefits. And they're surprisingly hard to navigate, even for the people who are supposed to use them.

The core problem is structural. A formulary isn't a simple lookup table. It's a web of relationships: drugs belong to therapeutic classes, classes have preferred and non-preferred members, drugs have generic equivalents, generics have authorized generics, brand names have multiple strengths, strengths have different tier placements, and all of this changes quarterly when the Pharmacy and Therapeutics (P&T) committee meets. A flat file or relational database can store this data, but querying it for the question a prescriber actually asks ("what's the cheapest equivalent my patient can take?") requires traversing multiple relationship types simultaneously.

That's a graph problem. And knowledge graphs are built for exactly this kind of multi-hop, relationship-rich navigation.

The business impact is real. Pharmacy benefit managers (PBMs) estimate that formulary-aligned prescribing reduces per-member-per-month drug spend by 15-25%. Plans that make formulary navigation easy for prescribers see higher generic utilization rates, fewer prior authorization denials, and better patient adherence (because patients can actually afford their medications). The ROI on making this data navigable is measured in millions annually for a mid-size health plan.

---

## The Technology: Knowledge Graphs for Drug Data

### What Is a Knowledge Graph?

A knowledge graph is a data structure that represents information as entities (nodes) connected by typed relationships (edges). Unlike a relational database where relationships are implicit in foreign keys and JOIN operations, a knowledge graph makes relationships first-class citizens. You can ask "what is connected to what, and how?" without knowing the schema in advance.

The fundamental unit is a triple: subject, predicate, object. "Atorvastatin" (subject) "belongs_to" (predicate) "HMG-CoA Reductase Inhibitors" (object). "Rosuvastatin" "is_therapeutic_alternative_to" "Atorvastatin". "Atorvastatin 40mg" "has_tier" "Tier 3". Chain these triples together and you get a navigable web of pharmaceutical knowledge.

This matters for formulary navigation because the questions prescribers ask are inherently graph traversals:

- "What's the preferred alternative in this therapeutic class?" (traverse: drug -> class -> preferred members)
- "Is there a generic available?" (traverse: brand -> generic equivalents)
- "What tier is the 20mg strength vs. the 40mg?" (traverse: drug -> strengths -> tier assignments)
- "Does this require prior auth?" (traverse: drug -> plan restrictions -> PA requirements)
- "What step therapy is required before this drug?" (traverse: drug -> step therapy chain -> required first-line agents)

In a relational model, each of these queries is a different JOIN pattern. In a graph, they're all the same operation: start at a node, follow edges of specified types, collect what you find.

### Why Graphs Beat Tables Here

Let me be concrete about why a relational approach struggles with formulary data.

A typical formulary has these entity types: drugs (by NDC, GPI, or RxNorm code), therapeutic classes (often using AHFS or USP classification), plan benefit structures, tier assignments, restriction types, and clinical criteria. The relationships between them are many-to-many, hierarchical, and time-varying.

In a relational model, you'd need:
- A drugs table
- A therapeutic_classes table (hierarchical, so you need a self-referencing parent_id or a closure table)
- A drug_class_membership table (many-to-many)
- A tier_assignments table (per plan, per drug, per strength, per time period)
- A restrictions table (per plan, per drug, with different restriction types)
- A therapeutic_alternatives table (per class, per plan)
- A generic_equivalents table
- A step_therapy_chains table (ordered sequences)

To answer "what's the cheapest alternative for this patient's plan?", you're joining 5-6 tables, filtering by plan ID, checking restriction status, and sorting by tier. It works, but it's brittle. Add a new relationship type (say, biosimilar equivalence) and you need a new table and new query logic.

In a graph model, you add a new edge type. The query pattern doesn't change. "Start at drug X, traverse edges of type [therapeutic_alternative, generic_equivalent, biosimilar], filter by plan coverage, sort by tier." Same traversal, new edge type. The schema evolves without breaking existing queries.

The other advantage is path queries. "Why is this drug non-preferred?" might require traversing: drug -> class -> P&T committee decision -> clinical criteria -> evidence citation. That's a path through the graph that tells a story. In a relational model, reconstructing that path requires knowing which tables to join in which order. In a graph, you just say "find all paths from drug X to any node of type 'coverage_rationale' within 4 hops."

### Graph Database Fundamentals

Graph databases come in two flavors: property graphs and RDF (Resource Description Framework) triple stores.

**Property graphs** (Neo4j, Amazon Neptune in property graph mode, TigerGraph) store nodes and edges with arbitrary key-value properties attached. Nodes have labels (Drug, TherapeuticClass, Plan). Edges have types (BELONGS_TO, IS_ALTERNATIVE_TO, HAS_TIER). Both can carry properties (effective_date, confidence_score, source). You query them with languages like Gremlin (Apache TinkerPop) or openCypher.

**RDF triple stores** (Amazon Neptune in RDF mode, Blazegraph, Stardog) store everything as subject-predicate-object triples. They're more standardized (W3C specs), support formal ontologies (OWL, RDFS), and enable logical inference. You query them with SPARQL. They're particularly good when you need to merge data from multiple sources with different schemas, because RDF's use of URIs as identifiers makes cross-source linking natural.

For formulary navigation, property graphs are usually the better fit. The data is well-structured (you know your entity types), the queries are traversal-heavy (find alternatives, navigate hierarchies), and the performance characteristics of property graph engines are optimized for exactly this pattern. RDF shines when you need to integrate with external ontologies (like linking your formulary to RxNorm or SNOMED), but you can do that integration at load time and still query as a property graph.

### The Formulary Data Model

Here's what the graph looks like for a typical formulary:

**Node types:**
- Drug (identified by RxNorm CUI or NDC): the medication itself
- DrugStrength: a specific strength/form (atorvastatin 20mg tablet vs. 40mg tablet)
- TherapeuticClass: AHFS or USP classification hierarchy
- Plan: a specific benefit plan
- TierAssignment: the cost tier for a drug under a plan
- Restriction: PA, step therapy, quantity limit, age limit
- StepTherapyChain: ordered sequence of required prior medications

**Edge types:**
- HAS_STRENGTH (Drug -> DrugStrength)
- BELONGS_TO_CLASS (Drug -> TherapeuticClass)
- PARENT_CLASS (TherapeuticClass -> TherapeuticClass): hierarchy
- GENERIC_OF (Drug -> Drug): generic equivalence
- THERAPEUTIC_ALTERNATIVE (Drug -> Drug): same class, interchangeable
- COVERED_UNDER (DrugStrength -> Plan): with tier property
- HAS_RESTRICTION (DrugStrength + Plan -> Restriction)
- STEP_BEFORE (Drug -> Drug): step therapy ordering

**Key properties on edges:**
- effective_date, termination_date: temporal validity
- plan_id: which plan this applies to
- tier: 1, 2, 3, 4, or specialty
- source: which formulary file or P&T decision created this

This model lets you answer the prescriber's question in a single traversal: start at the prescribed drug, follow BELONGS_TO_CLASS to its therapeutic class, follow THERAPEUTIC_ALTERNATIVE edges back to other drugs in that class, filter by COVERED_UNDER edges for the patient's plan, sort by tier. Three hops, one query, sub-second response.

### Where the Field Is Today

Graph databases have matured significantly in the last five years. Managed services handle the operational complexity (backups, scaling, high availability). Query languages have stabilized (openCypher is becoming a standard via GQL/ISO). And the tooling for loading, visualizing, and monitoring graphs has caught up with what relational databases have had for decades.

In healthcare specifically, knowledge graphs are seeing adoption for drug interaction checking (Recipe 13.4), clinical pathway modeling (Recipe 13.5), and terminology mapping (Recipe 13.8). Formulary navigation is one of the simpler applications because the source data is already well-structured (formulary files follow CMS-mandated formats) and the query patterns are predictable.

The main challenge isn't the technology. It's keeping the graph honest. The formulary file says one thing, but the PBM's adjudication system sometimes does another. You'll build a beautiful graph and then discover that half your tier assignments don't match what actually happens at the pharmacy counter. More on that gap in the honest take.

---

## General Architecture Pattern

At a conceptual level, the pipeline has four stages:

```
[Ingest Formulary Data] → [Build/Update Graph] → [Query API] → [Prescriber Interface]
```

**Stage 1: Ingest.** Formulary data arrives in structured formats. CMS requires health plans to publish formulary files in a standardized format (the CMS formulary file layout for Part D plans). Commercial plans often use similar structures. These files contain drug lists, tier assignments, restriction codes, and therapeutic class mappings. You parse these files and transform them into graph-ready triples or property graph statements.

**Stage 2: Build/Update Graph.** Load the parsed data into a graph database. This isn't a one-time operation. Formularies change quarterly (January, April, July, October for most plans), with mid-quarter amendments for new drug approvals, safety withdrawals, or P&T committee decisions. Your pipeline needs to handle incremental updates: add new drugs, change tier assignments, add or remove restrictions, without rebuilding the entire graph.

**Stage 3: Query API.** Expose the graph through a purpose-built API that translates prescriber questions into graph traversals. The API shouldn't expose raw graph query syntax to consumers. Instead, it offers domain-specific endpoints: "find alternatives for drug X under plan Y," "check restrictions for drug X at strength Z under plan Y," "navigate therapeutic class hierarchy from class C." The API handles the traversal logic, applies temporal filters (only return currently effective data), and formats results for the consuming application.

**Stage 4: Prescriber Interface.** The end consumer is typically an EHR integration, a pharmacy system, or a prescriber-facing tool. It calls the API at the point of prescribing, receives structured alternatives and restriction information, and presents it in the clinical workflow. The interface needs to be fast (sub-second response) and contextual (filtered to the patient's specific plan).

The key architectural decision is where intelligence lives. The graph itself is "dumb" storage of relationships. The query API encodes the business logic: what counts as a valid alternative, how to rank alternatives (by tier, then by formulary preference, then by clinical equivalence), when to surface restrictions vs. suppress them. Keep this logic in the API layer, not embedded in the graph structure, so you can evolve it without reloading data.

---

## The AWS Implementation

### Why These Services

**Amazon Neptune for the graph database.** Neptune is AWS's managed graph database service, supporting both property graph (Gremlin/openCypher) and RDF (SPARQL) query models. For formulary navigation, we'll use the property graph model with openCypher queries. Neptune handles the operational burden: automated backups, Multi-AZ replication, encryption at rest, and it's on the HIPAA eligible services list. The alternative would be self-managing Neo4j on EC2, which gives you more query language features but adds significant operational overhead.

**Amazon S3 for formulary file storage.** Formulary files land in S3 as the ingestion point. S3 event notifications trigger the parsing pipeline when new files arrive. Historical files are retained for audit and rollback purposes.

**AWS Lambda for the parsing and loading pipeline.** Formulary file parsing is a batch operation that runs quarterly (with occasional mid-quarter updates). Lambda handles the parse-and-load workflow: read the file from S3, transform rows into graph vertices and edges, and bulk-load into Neptune. For the quarterly full reload, you might hit Lambda's 15-minute timeout on very large formularies; Step Functions can orchestrate chunked processing if needed.

**AWS AppSync or API Gateway for the query API.** The prescriber-facing API needs low latency and high availability. API Gateway with Lambda resolvers works for simple query patterns. AppSync (GraphQL) is a natural fit if your consumers want flexible query shapes (some want just alternatives, others want alternatives plus restrictions plus step therapy in one call).

**Amazon ElastiCache (Redis) for query caching.** Formulary data changes quarterly, but the same queries repeat constantly. "What tier is atorvastatin 20mg under Plan XYZ?" gets asked every time someone prescribes it. A Redis cache in front of Neptune dramatically reduces graph query load and improves p99 latency. Cache invalidation aligns with formulary update cycles: flush the cache when you load new formulary data.

### Architecture Diagram

```mermaid
flowchart LR
    A[📄 Formulary Files\nCMS format] -->|Upload| B[S3 Bucket\nformulary-inbox/]
    B -->|S3 Event| C[Lambda\nformulary-parser]
    C -->|Bulk Load| D[Amazon Neptune\nProperty Graph]
    
    E[🏥 EHR / Prescriber Tool] -->|REST/GraphQL| F[API Gateway\nor AppSync]
    F -->|Check Cache| G[ElastiCache\nRedis]
    G -->|Cache Miss| H[Lambda\ngraph-query-resolver]
    H -->|openCypher| D
    H -->|Populate Cache| G

    style D fill:#9f9,stroke:#333
    style G fill:#ff9,stroke:#333
```

### Prerequisites

<!-- TODO (TechWriter): Expert review S1 (HIGH). Split IAM permissions into read-only (query Lambda: neptune-db:ReadDataViaQuery, neptune-db:connect) and read-write (loader Lambda: neptune-db:ReadDataViaQuery, neptune-db:WriteDataViaQuery, neptune-db:connect). Add note about enabling Neptune IAM authentication on the cluster. -->

<!-- TODO (TechWriter): Expert review N1 (HIGH). Expand VPC section to specify: Lambda in private subnets, required VPC endpoints (S3 gateway, CloudWatch Logs interface, STS interface for IAM auth), security group rules (Lambda SG -> Neptune SG on port 8182, Lambda SG -> Redis SG on port 6379), and NAT gateway requirement if Lambda needs internet access for RxNorm API calls. -->

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Neptune, Amazon S3, AWS Lambda, API Gateway or AppSync, Amazon ElastiCache (Redis), AWS Step Functions (optional, for large loads) |
| **IAM Permissions** | `neptune-db:*` (scoped to cluster), `s3:GetObject`, `s3:PutObject`, `elasticache:*` (scoped to cluster), `lambda:InvokeFunction` |
| **BAA** | AWS BAA signed. Formulary data itself may not be PHI, but when combined with patient plan membership at query time, the system handles PHI context. |
| **Encryption** | Neptune: encryption at rest enabled at cluster creation (cannot be added later). S3: SSE-KMS. ElastiCache: encryption at rest and in-transit. All API calls over TLS. |
| **VPC** | Neptune requires VPC deployment. Lambda resolvers must be in the same VPC with appropriate security groups. VPC endpoints for S3 and CloudWatch Logs. |
| **CloudTrail** | Enabled: log all Neptune, S3, and API Gateway calls for audit trail. The query Lambda should also log each request (timestamp, requesting system, drug_id, plan_id) to CloudWatch Logs for application-level audit. These logs may contain PHI-adjacent data and should be encrypted and retained per HIPAA retention policies. |
| **Sample Data** | CMS publishes [Part D formulary file layouts](https://www.cms.gov/medicare/prescription-drug-coverage/prescriptiondrugcovcontra) with sample data. Use synthetic plan data for development. |
| **Cost Estimate** | Neptune db.r5.large: ~$0.348/hr (~$254/month). ElastiCache cache.r6g.large (Multi-AZ with automatic failover): ~$0.332/hr (~$242/month). Lambda and API Gateway costs negligible at typical query volumes. Total: ~$500/month for a single-plan deployment. For multi-plan deployments (10+ plans), expect Neptune db.r5.xlarge or larger (~$500-700/month) and proportionally larger Redis instances. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Neptune** | Stores the formulary knowledge graph; executes openCypher traversals. Use the reader endpoint for query Lambdas, writer endpoint for the loader Lambda. |
| **Amazon S3** | Receives and archives formulary files |
| **AWS Lambda** | Parses formulary files into graph format; resolves API queries against Neptune |
| **API Gateway / AppSync** | Exposes formulary navigation as REST or GraphQL API |
| **Amazon ElastiCache (Redis)** | Caches frequent query results; reduces Neptune load. Deploy as a Multi-AZ replication group with automatic failover. Enable Redis AUTH and TLS in-transit. |
| **AWS KMS** | Manages encryption keys for Neptune, S3, and ElastiCache |
| **Amazon CloudWatch** | Metrics, logs, and alarms for query latency and graph load operations |
| **Amazon SQS** | Dead letter queue for failed formulary parse/load events; triggers CloudWatch alarm on DLQ messages |

### Code

#### Walkthrough

**Step 1: Parse formulary file into graph statements.** When a new formulary file lands in S3, the parser reads it and transforms each row into graph vertices (drugs, classes, plans) and edges (tier assignments, class memberships, restrictions). CMS formulary files have a defined column layout: NDC or RxNorm code, drug name, dosage form, tier level, restriction codes, therapeutic class, and alternatives. The parser maps these columns to graph entities and relationships. This step is where you handle data quality issues: missing codes, deprecated NDCs, and inconsistent class assignments. Skip this step and you have a flat file that can only answer "what tier is drug X?" but not "what are the alternatives?"

```
FUNCTION parse_formulary_file(bucket, key):
    // Read the raw formulary file from storage.
    // CMS Part D files are pipe-delimited text with a header row.
    raw_data = read file from S3 at bucket/key
    
    // Parse into rows. Each row represents one drug-plan-tier combination.
    rows = parse_delimited(raw_data, delimiter="|", has_header=true)
    
    // Accumulators for graph entities
    vertices = empty list   // nodes to create or update
    edges = empty list      // relationships to create or update
    
    FOR each row in rows:
        // Create or update the Drug vertex
        drug_id = row["RXNORM_CUI"] or row["NDC"]
        append to vertices: {
            id: drug_id,
            label: "Drug",
            properties: {
                name: row["DRUG_NAME"],
                dosage_form: row["DOSAGE_FORM"],
                strength: row["STRENGTH"],
                rxnorm_cui: row["RXNORM_CUI"]
            }
        }
        
        // Create the TherapeuticClass vertex (if not already seen)
        class_id = row["THERAPEUTIC_CLASS_CODE"]
        append to vertices: {
            id: class_id,
            label: "TherapeuticClass",
            properties: {
                name: row["THERAPEUTIC_CLASS_NAME"],
                classification_system: "AHFS"  // or USP, depending on plan
            }
        }
        
        // Edge: Drug belongs to TherapeuticClass
        append to edges: {
            from: drug_id,
            to: class_id,
            type: "BELONGS_TO_CLASS",
            properties: { effective_date: row["EFFECTIVE_DATE"] }
        }
        
        // Edge: Drug has tier assignment under this plan
        append to edges: {
            from: drug_id,
            to: row["PLAN_ID"],
            type: "COVERED_UNDER",
            properties: {
                tier: row["TIER_LEVEL"],
                effective_date: row["EFFECTIVE_DATE"],
                termination_date: row["TERMINATION_DATE"]
            }
        }
        
        // If restriction codes present, create restriction edges
        IF row["PRIOR_AUTH_FLAG"] == "Y":
            append to edges: {
                from: drug_id,
                to: "PA_" + row["PLAN_ID"] + "_" + drug_id,
                type: "HAS_RESTRICTION",
                properties: { restriction_type: "PRIOR_AUTH", plan_id: row["PLAN_ID"] }
            }
        
        IF row["STEP_THERAPY_FLAG"] == "Y":
            append to edges: {
                from: drug_id,
                to: "ST_" + row["PLAN_ID"] + "_" + drug_id,
                type: "HAS_RESTRICTION",
                properties: { restriction_type: "STEP_THERAPY", plan_id: row["PLAN_ID"] }
            }
        
        // If alternatives are listed, create therapeutic alternative edges
        IF row["ALTERNATIVE_DRUGS"] is not empty:
            FOR each alt_drug_id in split(row["ALTERNATIVE_DRUGS"], ","):
                append to edges: {
                    from: drug_id,
                    to: trim(alt_drug_id),
                    type: "THERAPEUTIC_ALTERNATIVE",
                    properties: { plan_id: row["PLAN_ID"], source: "formulary_file" }
                }
    
    RETURN vertices, edges
```

<!-- TODO (TechWriter): Expert review A1 (HIGH). Add error handling guidance for the ingest pipeline: SQS dead letter queue on the S3 event notification or Lambda async invocation config, CloudWatch alarm on DLQ messages, and note that for production the Step Functions orchestration (already mentioned as optional) should be considered mandatory for retry logic and execution history. Mention idempotency: MERGE operations prevent duplicates, but partial loads could leave the graph inconsistent without transaction boundaries. -->

**Step 2: Load graph data into Neptune.** Take the parsed vertices and edges and load them into the graph database. Neptune supports bulk loading via its loader API (for initial loads) and individual upserts via openCypher MERGE statements (for incremental updates). The key decision: on a quarterly full formulary refresh, do you drop and rebuild, or do you merge? Merging preserves any enrichment you've added (like manually curated alternative relationships), but it's slower and risks stale data if a drug is removed from the formulary. The pragmatic approach: use a versioned subgraph per formulary effective date, and point queries at the current version. Skip this step and your parsed data sits in Lambda's memory doing nothing.

```
FUNCTION load_graph(vertices, edges, neptune_endpoint):
    // For bulk initial load, use Neptune's bulk loader with a CSV staging file.
    // For incremental updates, use openCypher MERGE to upsert.
    
    // Connect to Neptune's openCypher endpoint
    connection = connect_to(neptune_endpoint, port=8182, protocol="bolt")
    
    // Upsert vertices: create if new, update properties if existing
    FOR each vertex in vertices:
        execute openCypher on connection:
            MERGE (n:{vertex.label} {id: vertex.id})
            SET n += vertex.properties
            // MERGE ensures we don't create duplicates.
            // SET += updates properties without removing existing ones.
    
    // Upsert edges: create if the relationship doesn't exist yet
    FOR each edge in edges:
        execute openCypher on connection:
            MATCH (a {id: edge.from})
            MATCH (b {id: edge.to})
            MERGE (a)-[r:{edge.type}]->(b)
            SET r += edge.properties
            // MERGE on the relationship prevents duplicate edges.
            // Properties like effective_date get updated if the edge already exists.
    
    // Log load statistics for monitoring
    log("Loaded {count(vertices)} vertices, {count(edges)} edges")
    
    RETURN { vertices_loaded: count(vertices), edges_loaded: count(edges) }
```

**Step 3: Query for therapeutic alternatives.** This is the core value of the graph: answering "what can my patient take instead?" in a single traversal. The query starts at the prescribed drug, finds its therapeutic class, then finds all other drugs in that class that are covered under the patient's plan, sorted by tier (cheapest first). It also checks for restrictions so the prescriber knows upfront if an alternative requires prior auth or step therapy. Without the graph, this query would be a multi-table JOIN with subqueries. With the graph, it's a pattern match.

```
FUNCTION find_alternatives(drug_id, plan_id, neptune_endpoint):
    // The prescriber's question: "What's cheaper and covered for this patient?"
    // We traverse: prescribed drug -> therapeutic class -> other drugs in class -> 
    //             filter by plan coverage -> sort by tier
    
    connection = connect_to(neptune_endpoint, port=8182, protocol="bolt")
    
    // Note: parameterized queries ($drug_id, $plan_id) prevent graph query injection.
    // Never build openCypher queries via string concatenation with user input.
    query = """
        // Start at the prescribed drug
        MATCH (prescribed:Drug {id: $drug_id})
        
        // Find its therapeutic class
        -[:BELONGS_TO_CLASS]->(class:TherapeuticClass)
        
        // Find other drugs in the same class
        <-[:BELONGS_TO_CLASS]-(alternative:Drug)
        
        // That are covered under the patient's plan
        -[coverage:COVERED_UNDER]->(plan:Plan {id: $plan_id})
        
        // Don't return the drug they already prescribed
        WHERE alternative.id <> $drug_id
        
        // Check for restrictions on each alternative
        OPTIONAL MATCH (alternative)-[restriction:HAS_RESTRICTION]->()
        WHERE restriction.plan_id = $plan_id
        
        // Return alternatives sorted by tier (cheapest first)
        RETURN alternative.name AS drug_name,
               alternative.id AS drug_id,
               alternative.strength AS strength,
               coverage.tier AS tier,
               collect(DISTINCT restriction.restriction_type) AS restrictions
        ORDER BY coverage.tier ASC, alternative.name ASC
    """
    
    results = execute(connection, query, parameters={drug_id: drug_id, plan_id: plan_id})
    
    RETURN results
```

**Step 4: Cache results for repeated queries.** The same drug-plan combinations get queried repeatedly. Atorvastatin under Blue Cross PPO Plan 1234 might get looked up hundreds of times a day across a health system. Caching these results in Redis avoids hitting Neptune for every request. The cache key combines drug ID and plan ID. Cache TTL aligns with formulary update frequency: set it to 24 hours during normal periods, and flush explicitly when you load new formulary data. Skip caching and your Neptune cluster will be oversized (and over-budget) to handle the query volume.

<!-- TODO (TechWriter): Expert review S2 (HIGH). Add guidance on Redis security posture: (1) Enable ElastiCache AUTH (Redis AUTH token or IAM-based access control via ElastiCache for Redis 7.0+). (2) Note that cache keys containing plan_id create an access pattern log of medication inquiries per member; recommend using plan-type identifiers rather than member-specific plan IDs where possible, or document PHI implications if member-specific caching is required. (3) Confirm TLS in-transit is required for Lambda-to-Redis connections. -->

```
FUNCTION get_alternatives_cached(drug_id, plan_id, redis_client, neptune_endpoint):
    // Build a deterministic cache key from the query parameters
    cache_key = "alternatives:" + drug_id + ":" + plan_id
    
    // Check Redis first
    cached_result = redis_client.get(cache_key)
    
    IF cached_result is not null:
        // Cache hit. Return immediately without touching Neptune.
        RETURN deserialize(cached_result)
    
    // Cache miss. Query the graph.
    result = find_alternatives(drug_id, plan_id, neptune_endpoint)
    
    // Store in cache with 24-hour TTL.
    // Formulary data changes at most daily (quarterly full refresh, occasional mid-quarter amendments).
    redis_client.set(cache_key, serialize(result), ttl=86400)
    
    RETURN result
```

**Step 5: Expose via API with plan context.** The final step wraps the graph query in a clean API that accepts what the prescriber's system knows (drug name or code, patient's plan ID) and returns what they need (ranked alternatives with tier and restriction information). The API also handles the common case where the prescribed drug IS the preferred option: it returns a confirmation rather than alternatives. This matters for UX. A prescriber doesn't want to see "no alternatives found" when they've already picked the best option; they want "this is the preferred drug in its class."

```
FUNCTION handle_formulary_query(request):
    // Extract and validate parameters from the API request.
    // Validate format before querying: drug_id should match RxNorm CUI or NDC pattern,
    // plan_id should match expected plan identifier format.
    drug_id = request.params["drug_id"]       // RxNorm CUI or NDC
    plan_id = request.params["plan_id"]       // patient's benefit plan identifier
    
    IF NOT valid_drug_id_format(drug_id) OR NOT valid_plan_id_format(plan_id):
        RETURN { status: "INVALID_INPUT", message: "Malformed drug_id or plan_id." }
    
    // First, check the tier of the prescribed drug itself
    prescribed_tier = get_drug_tier(drug_id, plan_id)
    
    IF prescribed_tier is null:
        // Drug not on formulary at all
        RETURN {
            status: "NOT_COVERED",
            prescribed_drug: drug_id,
            message: "This drug is not on the formulary for this plan.",
            alternatives: get_alternatives_cached(drug_id, plan_id, redis, neptune)
        }
    
    // Get alternatives
    alternatives = get_alternatives_cached(drug_id, plan_id, redis, neptune)
    
    // Check if any alternative has a better (lower) tier
    better_alternatives = filter(alternatives, WHERE tier < prescribed_tier)
    
    IF better_alternatives is empty:
        // The prescribed drug is already the best option
        RETURN {
            status: "PREFERRED",
            prescribed_drug: drug_id,
            tier: prescribed_tier,
            message: "This is the preferred option in its therapeutic class."
        }
    ELSE:
        RETURN {
            status: "ALTERNATIVES_AVAILABLE",
            prescribed_drug: drug_id,
            prescribed_tier: prescribed_tier,
            alternatives: better_alternatives,
            message: "Lower-cost alternatives are available."
        }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3 and the Neptune openCypher endpoint, check out the [Python Example](chapter13.01-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for atorvastatin 40mg under a commercial PPO plan:**

```json
{
  "status": "ALTERNATIVES_AVAILABLE",
  "prescribed_drug": "RX_83367",
  "prescribed_tier": 3,
  "alternatives": [
    {
      "drug_name": "Rosuvastatin 20mg",
      "drug_id": "RX_301542",
      "strength": "20mg",
      "tier": 1,
      "restrictions": []
    },
    {
      "drug_name": "Simvastatin 40mg",
      "drug_id": "RX_36567",
      "strength": "40mg",
      "tier": 1,
      "restrictions": []
    },
    {
      "drug_name": "Pravastatin 40mg",
      "drug_id": "RX_42463",
      "strength": "40mg",
      "tier": 2,
      "restrictions": []
    }
  ],
  "message": "Lower-cost alternatives are available."
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Query latency (cache hit) | 2-5 ms |
| Query latency (cache miss, graph traversal) | 15-50 ms |
| Graph load time (full formulary, ~50K drugs) | 3-8 minutes |
| Graph size (single plan formulary) | ~50K vertices, ~200K edges |
| Cache hit rate (steady state) | 85-95% |
| Cost per query | ~$0.001 (amortized Neptune + cache) |

**Where it struggles:** Drugs with complex step therapy chains (3+ required prior medications). Plans with highly customized formularies that don't follow standard therapeutic class groupings. Combination drugs that span multiple classes. And the perennial problem: the formulary file says one thing, but the PBM's adjudication system behaves differently due to overrides, grandfather clauses, or processing errors.

---

## Why This Isn't Production-Ready

**Formulary file format variations.** The pseudocode assumes a clean, CMS-standard pipe-delimited file. In practice, commercial plans publish formulary data in dozens of formats: Excel spreadsheets, PDFs (yes, really), proprietary XML schemas, and NCPDP-standard files that each PBM interprets slightly differently. Your parser needs to handle multiple input formats, and you'll spend more time on parsing edge cases than on graph queries.

**Temporal validity.** The graph needs to answer "what was the formulary on March 15?" for claims adjudication disputes, not just "what is the formulary today?" This requires versioning every edge with effective and termination dates, and filtering all queries by a point-in-time parameter. The pseudocode shows effective_date properties but doesn't demonstrate temporal query filtering.

**RxNorm normalization.** Formulary files use inconsistent drug identifiers. Some use NDC (National Drug Code), some use GPI (Generic Product Identifier), some use RxNorm CUIs. Before you can build therapeutic alternative relationships, you need to normalize everything to a common identifier. RxNorm is the standard choice, but the mapping isn't always clean (especially for combination drugs and new approvals).

**Neptune connection management.** Lambda functions in a VPC connecting to Neptune need connection pooling. Cold starts with Neptune connections add 1-2 seconds of latency. Use provisioned concurrency for the query Lambda, or consider an always-on Fargate task for the query layer if cold start latency is unacceptable.

---

## The Honest Take

This recipe is one of the cleaner knowledge graph applications because the source data is already structured. You're not doing NLP extraction or entity resolution. The formulary file tells you exactly which drugs are on which tier. The graph just makes it navigable in ways a flat file can't support.

The part that will surprise you: building the graph is maybe 20% of the work. Keeping it current is 80%. Formularies change quarterly, but the real headache is mid-quarter amendments. A new drug gets FDA approval and the P&T committee adds it in week 6 of the quarter. A safety signal causes a drug to be removed. A manufacturer rebate deal changes tier placement for a single drug. Each of these is a targeted graph update that needs to happen within days, not wait for the next quarterly reload.

The therapeutic alternative relationships are where the real value lives, and they're also the hardest to get right. The formulary file might list alternatives, but those lists are often incomplete or based on class membership rather than true clinical equivalence. A statin is not always interchangeable with another statin for a specific patient (dose equivalence tables matter, contraindications matter, prior adverse reactions matter). The graph can tell you what's formulary-preferred, but clinical judgment still determines what's appropriate. Make sure your UI communicates "formulary alternatives" not "recommended substitutions."

The cache hit rate makes or breaks your cost model. Neptune isn't cheap (~$250/month minimum for a production instance). If 90% of queries hit Redis, your effective cost per query is trivial. If your cache hit rate drops (because you have many plans with different formularies, or because you're not normalizing drug identifiers consistently in cache keys), Neptune query volume spikes and you need a larger instance.

One more thing: the gap between "what the formulary file says" and "what the PBM actually adjudicates" is real and frustrating. I've seen cases where a drug is listed as Tier 2 in the formulary file but consistently adjudicates at Tier 3 due to a system override that nobody documented. Your graph reflects the published formulary, not necessarily the operational reality. Build feedback loops from claims adjudication data to validate your graph against actual tier assignments.

---

## Variations and Extensions

**Multi-plan comparison.** Extend the query to compare formulary coverage across multiple plans for a patient who's choosing between insurance options during open enrollment. The graph traversal is the same, just fanned out across plan nodes. Useful for benefits advisors and health insurance marketplaces.

**Step therapy path visualization.** For drugs with step therapy requirements, traverse the STEP_BEFORE edges to build a visual path: "Before you can get Drug C, the plan requires you to try Drug A, then Drug B, each for 30 days." Present this as a timeline to the prescriber so they understand the full journey, not just the current restriction.

**Generic substitution with pricing.** Enrich the graph with average wholesale price (AWP) or WAC data on drug nodes. When presenting alternatives, show estimated patient cost (tier copay) alongside the drug name. This turns a clinical tool into a shared decision-making tool that patients and prescribers can use together.

---

## Related Recipes

- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Uses a similar graph structure but models interaction relationships between drugs rather than formulary relationships. The two graphs can share a common drug node layer.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Demonstrates the same hierarchical traversal pattern applied to diagnosis and procedure codes rather than drug classifications.
- **Recipe 13.6 (Care Gap Reasoning Engine):** Consumes formulary data as part of medication adherence gap detection. If a patient isn't filling a prescribed medication, the care gap engine checks whether a formulary barrier (high tier, PA requirement) might be the cause.
- **Recipe 11.5 (Insurance Benefits Navigator):** A conversational interface that could use this recipe's API as its backend for answering patient questions about drug coverage.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Neptune User Guide](https://docs.aws.amazon.com/neptune/latest/userguide/intro.html)
- [Amazon Neptune openCypher Query Language](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html)
- [Neptune Bulk Loader](https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html)
- [Amazon Neptune Pricing](https://aws.amazon.com/neptune/pricing/)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Amazon ElastiCache for Redis User Guide](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html)

**AWS Sample Repos:**
- [`amazon-neptune-samples`](https://github.com/aws-samples/amazon-neptune-samples): General Neptune examples including graph data modeling, bulk loading, and query patterns
- [`amazon-neptune-ontology-example-blog`](https://github.com/aws-samples/amazon-neptune-ontology-example-blog): Demonstrates building and querying ontology-based knowledge graphs in Neptune

**AWS Solutions and Blogs:**
- [Building a Knowledge Graph with Amazon Neptune](https://aws.amazon.com/blogs/database/building-a-knowledge-graph-with-amazon-neptune/): End-to-end walkthrough of graph modeling and querying in Neptune
- [Let Me Graph That For You (Neptune Blog Series)](https://aws.amazon.com/blogs/database/let-me-graph-that-for-you-part-1-air-routes/): Multi-part series on graph data modeling patterns applicable to healthcare use cases

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 2-3 weeks | Single-plan formulary loaded, alternative lookup API working, no caching |
| **Production-ready** | 6-8 weeks | Multi-plan support, Redis caching, temporal versioning, monitoring, CI/CD for formulary updates |
| **With variations** | 10-12 weeks | Multi-plan comparison, step therapy visualization, pricing enrichment, EHR integration |

---

## Tags

`knowledge-graph` · `neptune` · `formulary` · `pharmacy` · `drug-alternatives` · `opencypher` · `graph-database` · `elasticache` · `simple` · `mvp` · `hipaa`

---

*← [Chapter 13 Index](chapter13-index) · [Next: Recipe 13.2 - Provider Directory as Knowledge Graph →](chapter13.02-provider-directory-knowledge-graph)*
