# Recipe 13.8: Medical Concept Normalization and Mapping

**Complexity:** Complex · **Phase:** Foundation · **Estimated Cost:** ~$2,000–8,000/month (graph database + compute)

---

## The Problem

Here's a scenario that plays out every single day in healthcare data integration. A hospital system acquires a physician practice. The practice has been coding diagnoses in ICD-10-CM. The hospital's analytics platform uses SNOMED CT for clinical decision support. The quality reporting system needs HEDIS value sets that reference both. The pharmacy system speaks RxNorm. The lab system uses LOINC. And someone in the C-suite wants a unified patient dashboard that pulls from all of them.

Every one of these systems is describing the same clinical reality (a patient has Type 2 diabetes, takes metformin, had an HbA1c drawn last month) but they're describing it in completely different languages. "Type 2 diabetes mellitus" in ICD-10 is E11. In SNOMED CT it's concept 44054006. In a clinical note it might say "DM2" or "adult-onset diabetes" or "NIDDM" (a term that's been deprecated for decades but still shows up in legacy data).

This isn't a cosmetic problem. When your analytics can't recognize that ICD-10 E11.9, SNOMED 44054006, and the free-text mention "type 2 DM" all refer to the same clinical concept, you get wrong answers. Quality measures undercount. Risk adjustment misses conditions. Clinical decision support fires for the wrong patients. Research cohorts are incomplete.

The scale is staggering. SNOMED CT contains over 350,000 active concepts. ICD-10-CM has roughly 72,000 codes. LOINC has over 90,000 observation identifiers. RxNorm has hundreds of thousands of drug concepts. The mappings between them are not one-to-one. They're many-to-many, version-dependent, context-sensitive, and constantly evolving. A new ICD-10 code gets added in October. SNOMED releases quarterly. RxNorm updates monthly.

This is the concept normalization problem: taking a clinical concept expressed in any terminology, any version, any level of specificity, and mapping it to a canonical representation that your systems can reason about consistently. It's foundational infrastructure. Every analytics pipeline, every CDS rule, every quality measure depends on it. And getting it wrong is silent. You don't get an error message when your diabetes cohort is missing 15% of patients because their conditions were coded in a terminology your system doesn't map.

Let's talk about how to build this properly.

---

## The Technology: Terminology Mapping and Concept Normalization

### The Terminology Landscape

Healthcare has a terminology problem that's unique among industries. Most domains have one or two standard vocabularies. Healthcare has dozens, each serving a different purpose, maintained by a different organization, on a different release schedule.

The major players:

**SNOMED CT** (Systematized Nomenclature of Medicine, Clinical Terms). The most comprehensive clinical terminology. Hierarchical, with formal logic-based definitions. Maintained by SNOMED International. Used primarily for clinical documentation and decision support. Its strength is expressiveness: you can represent very specific clinical concepts. Its weakness is complexity: the formal ontology is genuinely hard to work with.

**ICD-10-CM/PCS** (International Classification of Diseases, 10th Revision, Clinical Modification / Procedure Coding System). The billing and administrative standard in the US. Maintained by WHO (ICD-10) with US modifications by CMS/NCHS. Every diagnosis on a claim uses ICD-10-CM. Every inpatient procedure uses ICD-10-PCS. Updated annually in October.

**LOINC** (Logical Observation Identifiers Names and Codes). The standard for laboratory and clinical observations. When a lab result comes back, the observation type (what was measured) is identified by a LOINC code. Maintained by the Regenstrief Institute.

**RxNorm**. The standard for medications in the US. Provides normalized names for clinical drugs and links to drug vocabularies used in pharmacy and drug interaction systems. Maintained by the National Library of Medicine (NLM). Updated monthly.

**CPT** (Current Procedural Terminology). Procedure codes for outpatient billing. Maintained by the AMA. Proprietary (you pay for a license).

**HCPCS** (Healthcare Common Procedure Coding System). Extends CPT with codes for supplies, equipment, and non-physician services. Maintained by CMS.

Each of these terminologies has its own structure, its own versioning scheme, its own release cadence, and its own licensing terms. The relationships between them are maintained by various organizations (NLM's UMLS being the most comprehensive), but those relationships are imperfect, incomplete, and require ongoing curation.

### Why Mapping Is Hard

If you've never worked with terminology mapping, you might think it's a straightforward lookup table problem. Concept A in system X equals concept B in system Y. Build the table, done.

It's not that simple. Here's why:

**Granularity mismatch.** SNOMED CT is far more granular than ICD-10. A single ICD-10 code might map to dozens of SNOMED concepts. "E11.9 - Type 2 diabetes mellitus without complications" in ICD-10 maps to multiple SNOMED concepts depending on whether you mean the disorder itself, the finding of elevated glucose, or the clinical situation of a patient with the condition. Going the other direction, a specific SNOMED concept might not have a precise ICD-10 equivalent and must be mapped to a broader code with loss of specificity.

**Context dependence.** The correct mapping sometimes depends on context. A LOINC code for "glucose" might map to different SNOMED concepts depending on whether it's a fasting glucose, a random glucose, or a glucose tolerance test result. The LOINC code alone doesn't always carry enough context.

**Temporal drift.** Terminologies evolve. ICD-10 adds and retires codes annually. SNOMED releases quarterly. A mapping that was correct in 2023 might be incorrect in 2025 because one side of the relationship changed. You need version-aware mappings, not just current-state lookups.

**Many-to-many relationships.** The relationship between terminologies is rarely one-to-one. One SNOMED concept might map to multiple ICD-10 codes depending on the clinical context. One ICD-10 code might be the target of multiple SNOMED concepts. These aren't bugs; they reflect genuine differences in how the terminologies carve up clinical reality.

**Semantic types.** Not all mappings are equivalence. Some are "broader than" (the target concept is more general). Some are "narrower than." Some are "related to" without being equivalent. A naive system that treats all mappings as equivalence will produce incorrect results.

**Composite concepts.** Some clinical ideas require multiple codes in one system but a single code in another. "Diabetic retinopathy" might be a single SNOMED concept but require both a diabetes code and a retinopathy code in ICD-10 to fully represent.

### Knowledge Graphs for Terminology

This is where knowledge graphs earn their keep. A terminology mapping system is fundamentally a graph problem. You have nodes (concepts from various terminologies) connected by typed, directed edges (equivalence, broader-than, narrower-than, related-to). The graph structure lets you:

**Traverse hierarchies.** SNOMED CT is a directed acyclic graph (DAG) where concepts have "is-a" relationships to parent concepts. "Type 2 diabetes mellitus" is-a "Diabetes mellitus" is-a "Disorder of glucose metabolism" is-a "Metabolic disease." When a query asks for "all metabolic diseases," you need to traverse that hierarchy to find all descendants.

**Follow cross-terminology links.** From a SNOMED concept, follow an edge to its ICD-10 equivalent, then from that ICD-10 code follow an edge to its HEDIS value set membership. Graph traversal makes multi-hop queries natural.

**Reason about relationships.** If concept A is equivalent to concept B, and concept B is broader than concept C, then concept A is broader than concept C. Graph databases with reasoning capabilities can infer these transitive relationships.

**Version management.** Each edge can carry metadata: which version of the mapping introduced it, whether it's been deprecated, what the provenance is. Temporal queries ("what was the correct mapping as of January 2024?") become graph traversals with date filters.

The alternative to a graph is a relational database with a bunch of join tables. It works for simple lookups, but the moment you need multi-hop traversals, hierarchy navigation, or transitive reasoning, the SQL gets ugly fast and the performance degrades. Graphs are the natural data structure for this problem.

### The UMLS: Your Starting Point

The Unified Medical Language System (UMLS), maintained by the National Library of Medicine, is the most comprehensive source of terminology mappings in healthcare. It integrates over 200 source vocabularies and provides:

**Concept Unique Identifiers (CUIs).** Each distinct clinical meaning gets a CUI. Multiple terms from multiple vocabularies that mean the same thing share a CUI. This is the normalization layer: map any term to its CUI, and you've normalized it.

**Relationships.** The UMLS Metathesaurus contains millions of relationships between concepts: synonymy, hierarchy, association, and more.

**Semantic types.** Each concept is assigned one or more semantic types (Disease or Syndrome, Pharmacologic Substance, Laboratory Procedure, etc.) that enable category-level reasoning.

The UMLS is not perfect. Its mappings are algorithmically generated and human-reviewed, but coverage is uneven. Some terminology pairs have excellent mappings (SNOMED to ICD-10 via the NLM's map). Others have sparse or outdated links. You'll need to supplement UMLS with custom mappings for your specific use cases.

### The General Architecture Pattern

At a conceptual level, a concept normalization system has these components:

```
[Terminology Sources] → [Graph Ingestion] → [Knowledge Graph Store] → [Normalization API] → [Consumers]
                                                      ↑
                                            [Curation Interface]
```

**Terminology Sources.** The raw vocabulary files: UMLS releases, SNOMED RF2 files, ICD-10 code tables, LOINC downloads, RxNorm RRF files. Each has its own format and release schedule.

**Graph Ingestion.** ETL pipelines that parse terminology files, extract concepts and relationships, and load them into the graph. This runs on each terminology release (monthly for RxNorm, quarterly for SNOMED, annually for ICD-10).

**Knowledge Graph Store.** A graph database holding all concepts as nodes and all relationships (intra-terminology hierarchies, cross-terminology mappings) as edges. Must support efficient traversal, pattern matching, and temporal queries.

**Normalization API.** The interface that consuming systems call. Given a concept (code + terminology + version), return the canonical representation and all known mappings. Must be fast (sub-100ms for point lookups) and support batch operations.

**Curation Interface.** A tool for terminologists to review, approve, and create custom mappings. The UMLS gets you 80% of the way. The last 20% requires human expertise specific to your organization's use cases.

**Consumers.** Analytics pipelines, CDS engines, quality reporting systems, research platforms. Each has different access patterns: some need point lookups, some need batch translations, some need hierarchy traversals.

---

## The AWS Implementation

### Why These Services

**Amazon Neptune for the knowledge graph store.** Neptune is AWS's managed graph database service, supporting both the property graph model (via openCypher/Gremlin) and RDF (via SPARQL). For terminology mapping, the property graph model is the better fit: concepts are nodes with properties (code, display name, terminology, version, status), and relationships are edges with properties (mapping type, confidence, provenance, effective date). Neptune handles the traversal-heavy query patterns that terminology navigation demands. It's also on the HIPAA eligible services list, which matters because concept mappings themselves aren't PHI, but the queries against them (which patient has which condition) can be.

**AWS Glue for terminology ingestion.** Terminology files come in various formats (RRF for UMLS/RxNorm, RF2 for SNOMED, CSV for ICD-10, custom formats for LOINC). Glue ETL jobs handle the parsing, transformation, and bulk loading into Neptune. The jobs run on each terminology release, which means monthly at most. Glue's serverless Spark environment handles the large file sizes (UMLS is multiple gigabytes) without requiring persistent infrastructure.

**Amazon ElastiCache (Redis) for normalization caching.** Point lookups against Neptune are fast (single-digit milliseconds for direct node lookups), but multi-hop traversals can take longer. For the most common normalization queries (single concept to canonical form), a Redis cache in front of Neptune reduces latency to sub-millisecond and protects Neptune from query storms during batch processing runs.

**AWS Lambda + API Gateway for the normalization API.** The normalization service is a stateless lookup: receive a concept, query the graph (or cache), return the mappings. Lambda handles this cleanly with automatic scaling. API Gateway provides the REST interface, request validation, and throttling.

**Amazon S3 for terminology file staging.** Raw terminology downloads land in S3 before Glue processes them. S3 also stores the processed graph load files (Neptune bulk loader format) and serves as the audit trail for which terminology versions have been ingested.

**AWS Step Functions for ingestion orchestration.** A terminology update involves multiple steps: download the new release, validate file integrity, run the Glue ETL, bulk-load into Neptune, validate the load, warm the cache, and notify consumers. Step Functions orchestrates this sequence with error handling and retry logic.

### Architecture Diagram

```mermaid
flowchart TD
    A[Terminology Sources\nUMLS / SNOMED / ICD-10\nLOINC / RxNorm] -->|Download| B[S3 Bucket\nterminology-raw/]
    B -->|Trigger| C[Step Functions\nIngestion Orchestrator]
    C -->|Parse & Transform| D[AWS Glue\nETL Jobs]
    D -->|Bulk Load| E[Amazon Neptune\nKnowledge Graph]
    E -->|Query| F[Lambda\nNormalization Service]
    G[ElastiCache Redis\nMapping Cache] <-->|Cache| F
    F -->|REST API| H[API Gateway\n/normalize endpoint]
    H -->|Consume| I[Analytics / CDS\nQuality Reporting]
    J[Curation UI] -->|Custom Mappings| E

    style E fill:#9ff,stroke:#333
    style G fill:#ff9,stroke:#333
    style H fill:#f9f,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Neptune, AWS Glue, Amazon ElastiCache (Redis), AWS Lambda, API Gateway, Amazon S3, AWS Step Functions |
| **IAM Permissions** | `neptune-db:*` (scoped to cluster), `glue:StartJobRun`, `s3:GetObject`, `s3:PutObject`, `elasticache:*` (scoped to cluster), `lambda:InvokeFunction`, `states:StartExecution` |
| **BAA** | AWS BAA signed. Concept mappings themselves aren't PHI, but normalization queries in context (which patient maps to which concept) can constitute PHI. |
| **Encryption** | Neptune: encryption at rest (enabled at cluster creation, cannot be added later). S3: SSE-KMS. ElastiCache: encryption at rest and in-transit. All API calls over TLS. |
| **VPC** | Neptune requires VPC deployment. Lambda in same VPC with VPC endpoints for S3 and CloudWatch Logs. ElastiCache in same VPC. No public internet access to Neptune. |
| **CloudTrail** | Enabled for all API calls. Neptune audit logging enabled for query-level audit trail. |
| **Terminology Licenses** | UMLS license (free, requires registration with NLM). SNOMED CT (free in US via NLM). CPT (paid AMA license). ICD-10 (free from CMS). LOINC (free, requires registration). RxNorm (free via NLM). |
| **Sample Data** | UMLS Metathesaurus subset. NLM provides sample files for development. Never load full UMLS into a dev environment without understanding the size (multiple GB). |
| **Cost Estimate** | Neptune db.r5.large: ~$700/month. ElastiCache cache.r6g.large: ~$300/month. Glue ETL (monthly runs): ~$50/month. Lambda + API Gateway: ~$100/month at moderate query volume. S3 storage: ~$50/month. Total: ~$1,200–2,000/month for a basic deployment. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Neptune** | Stores the terminology knowledge graph: concepts as nodes, mappings as edges |
| **AWS Glue** | Parses and transforms terminology source files into Neptune bulk load format |
| **Amazon ElastiCache (Redis)** | Caches frequent normalization lookups for sub-millisecond response |
| **AWS Lambda** | Serves normalization queries, handles cache logic, orchestrates graph traversals |
| **Amazon API Gateway** | REST interface for the normalization service with throttling and auth |
| **Amazon S3** | Stages raw terminology files and processed load files |
| **AWS Step Functions** | Orchestrates the multi-step terminology ingestion pipeline |
| **AWS KMS** | Manages encryption keys for Neptune, S3, and ElastiCache |
| **Amazon CloudWatch** | Metrics, logs, and alarms for ingestion failures and API latency |

### Code

#### Walkthrough

**Step 1: Terminology file ingestion.** When a new terminology release arrives (downloaded manually or via automated NLM API calls), it lands in S3 and triggers the ingestion orchestrator. The first task is parsing the raw files into a normalized intermediate format. UMLS uses RRF (Rich Release Format), which is pipe-delimited with specific column semantics. SNOMED uses RF2 (Release Format 2), a set of tab-delimited files with concept, description, and relationship tables. Each terminology has its own parser, but they all produce the same output: a set of nodes (concepts) and edges (relationships) ready for graph loading. Skip this step and you have no data. Get the parsing wrong and you have wrong data, which is worse.

```
FUNCTION ingest_terminology(terminology_name, version, s3_path):
    // Download and validate the raw terminology files from S3.
    // Each terminology has a known file structure:
    //   UMLS: MRCONSO.RRF (concepts), MRREL.RRF (relationships)
    //   SNOMED: sct2_Concept_*.txt, sct2_Relationship_*.txt
    //   ICD-10: icd10cm_tabular_*.xml or flat files from CMS
    //   RxNorm: RXNCONSO.RRF, RXNREL.RRF
    raw_files = download_from_s3(s3_path)
    
    // Validate file checksums against the published manifest.
    // Terminology releases include integrity checks. Use them.
    validate_checksums(raw_files, terminology_name)
    
    // Select the appropriate parser based on terminology type.
    // Each parser knows the file format and column semantics.
    parser = get_parser_for(terminology_name)
    
    // Parse concepts: extract code, display name, semantic type, status.
    // Each concept becomes a node in the graph.
    concepts = parser.extract_concepts(raw_files)
    
    // Parse relationships: extract source, target, relationship type, metadata.
    // Each relationship becomes an edge in the graph.
    relationships = parser.extract_relationships(raw_files)
    
    // Tag every concept and relationship with version and load timestamp.
    // This enables temporal queries: "what was the mapping as of date X?"
    tag_with_version(concepts, terminology_name, version)
    tag_with_version(relationships, terminology_name, version)
    
    RETURN concepts, relationships
```

**Step 2: Graph construction and loading.** The parsed concepts and relationships need to be loaded into Neptune. For initial loads and large updates, Neptune's bulk loader is dramatically faster than individual insert queries. The bulk loader reads CSV files from S3 in a specific format: one file for nodes, one for edges, with headers defining the property names and types. For incremental updates (a few hundred new concepts in a monthly RxNorm release), individual Gremlin or openCypher queries work fine. The choice between bulk and incremental depends on the size of the delta. This step also handles the critical task of linking concepts across terminologies: when UMLS tells us that SNOMED concept 44054006 and ICD-10 code E11 share a CUI, we create a cross-terminology edge between them.

```
FUNCTION build_graph_load_files(concepts, relationships):
    // Neptune bulk loader expects CSV files with specific headers.
    // Node file: ~id, ~label, code:String, display:String, terminology:String, 
    //            version:String, status:String, semantic_type:String
    // Edge file: ~id, ~from, ~to, ~label, relationship_type:String, 
    //            confidence:Double, provenance:String, effective_date:Date
    
    node_file = create_csv_with_headers(NEPTUNE_NODE_SCHEMA)
    edge_file = create_csv_with_headers(NEPTUNE_EDGE_SCHEMA)
    
    FOR each concept in concepts:
        // Generate a deterministic node ID from terminology + code + version.
        // This ensures idempotent loads: reloading the same version doesn't create duplicates.
        node_id = generate_node_id(concept.terminology, concept.code, concept.version)
        
        append_row(node_file, {
            id:            node_id,
            label:         "Concept",
            code:          concept.code,
            display:       concept.display_name,
            terminology:   concept.terminology,
            version:       concept.version,
            status:        concept.status,        // "active" or "retired"
            semantic_type: concept.semantic_type   // e.g., "Disease or Syndrome"
        })
    
    FOR each relationship in relationships:
        // Generate edge ID from source + target + type for idempotency.
        source_id = generate_node_id(relationship.source_terminology, 
                                     relationship.source_code, 
                                     relationship.source_version)
        target_id = generate_node_id(relationship.target_terminology, 
                                     relationship.target_code, 
                                     relationship.target_version)
        
        append_row(edge_file, {
            id:                generate_edge_id(source_id, target_id, relationship.type),
            from:              source_id,
            to:                target_id,
            label:             relationship.type,   // "equivalent_to", "broader_than", "maps_to"
            relationship_type: relationship.type,
            confidence:        relationship.confidence,   // 0.0 to 1.0
            provenance:        relationship.provenance,   // "UMLS", "NLM_MAP", "CUSTOM"
            effective_date:    relationship.effective_date
        })
    
    // Upload to S3 for Neptune bulk loader.
    upload_to_s3(node_file, "terminology-processed/nodes/")
    upload_to_s3(edge_file, "terminology-processed/edges/")
    
    RETURN s3_paths_for_load_files
```

**Step 3: Cross-terminology linking via UMLS CUIs.** This is the heart of the normalization system. UMLS assigns a Concept Unique Identifier (CUI) to each distinct clinical meaning. When SNOMED concept 44054006 ("Type 2 diabetes mellitus") and ICD-10 code E11 ("Type 2 diabetes mellitus") share CUI C0011860, that tells us they represent the same clinical idea. This step creates the cross-terminology edges that make normalization possible. Without it, you have isolated terminology islands with no bridges between them.

```
FUNCTION create_cross_terminology_links(umls_concepts):
    // UMLS MRCONSO.RRF contains rows like:
    //   CUI | Language | Source | Code | Display
    //   C0011860 | ENG | SNOMEDCT_US | 44054006 | Type 2 diabetes mellitus
    //   C0011860 | ENG | ICD10CM | E11 | Type 2 diabetes mellitus
    //
    // Same CUI = same meaning across terminologies.
    
    // Group all source concepts by their CUI.
    cui_groups = group_by(umls_concepts, field="CUI")
    
    cross_links = empty list
    
    FOR each cui, concepts_in_group in cui_groups:
        // For each pair of concepts sharing a CUI but from different terminologies,
        // create a cross-terminology equivalence edge.
        FOR each pair (concept_a, concept_b) in concepts_in_group 
            WHERE concept_a.terminology != concept_b.terminology:
            
            // Determine the relationship type.
            // UMLS provides relationship attributes (REL, RELA) that indicate
            // whether the mapping is exact, broader, narrower, or related.
            rel_type = determine_relationship_type(concept_a, concept_b, cui)
            
            append to cross_links: {
                source:     concept_a,
                target:     concept_b,
                type:       rel_type,        // "exact_match", "broader_than", "narrower_than"
                confidence: 1.0,             // UMLS CUI-based links are high confidence
                provenance: "UMLS_CUI_" + cui
            }
    
    RETURN cross_links
```

**Step 4: Normalization query service.** This is the API that consuming systems call. Given a concept (code + terminology), return the canonical form and all known mappings to other terminologies. The service first checks the Redis cache (most common lookups are repeated frequently). On cache miss, it queries Neptune with a graph traversal that follows cross-terminology edges, respecting relationship types and version constraints. The response includes confidence scores and provenance so consumers can make informed decisions about which mappings to trust.

```
FUNCTION normalize_concept(code, terminology, target_terminologies, version=null):
    // Build a cache key from the input parameters.
    cache_key = build_cache_key(code, terminology, target_terminologies, version)
    
    // Check Redis cache first. Most normalization queries are repeated
    // (the same ICD-10 codes appear on thousands of claims).
    cached_result = redis.get(cache_key)
    IF cached_result is not null:
        RETURN cached_result
    
    // Cache miss. Query Neptune.
    // Find the source concept node.
    source_node = neptune.query("""
        MATCH (c:Concept {code: $code, terminology: $terminology})
        WHERE c.status = 'active'
        AND ($version IS NULL OR c.version = $version)
        RETURN c
    """, params={code, terminology, version})
    
    IF source_node is null:
        RETURN {status: "not_found", code: code, terminology: terminology}
    
    // Traverse cross-terminology edges to find mappings.
    // Limit traversal depth to 2 hops (source -> CUI bridge -> target)
    // to avoid runaway queries on densely connected concepts.
    mappings = neptune.query("""
        MATCH (source:Concept {code: $code, terminology: $terminology})
              -[r:equivalent_to|maps_to|broader_than|narrower_than]->
              (target:Concept)
        WHERE target.terminology IN $target_terminologies
        AND target.status = 'active'
        RETURN target.code AS code,
               target.terminology AS terminology,
               target.display AS display,
               type(r) AS relationship_type,
               r.confidence AS confidence,
               r.provenance AS provenance
        ORDER BY r.confidence DESC
    """, params={code, terminology, target_terminologies})
    
    // Build the response with the source concept and all mappings.
    result = {
        source: {
            code:        source_node.code,
            terminology: source_node.terminology,
            display:     source_node.display,
            semantic_type: source_node.semantic_type
        },
        mappings: mappings,
        mapping_count: length(mappings),
        query_timestamp: current_utc_timestamp()
    }
    
    // Cache the result. TTL depends on how frequently terminologies update.
    // 24 hours is reasonable: terminology releases are at most monthly.
    redis.set(cache_key, result, ttl=86400)
    
    RETURN result
```

**Step 5: Hierarchy traversal for value set expansion.** Quality measures and clinical rules often reference value sets: "all codes that represent diabetes." This requires traversing the terminology hierarchy. In SNOMED CT, "Type 2 diabetes mellitus" (44054006) is-a "Diabetes mellitus" (73211009), which is-a "Disorder of glucose metabolism" (126877002). A value set defined at "Diabetes mellitus" needs to include all descendants. This step provides that expansion, which is computationally expensive for broad concepts but essential for correct quality measurement.

```
FUNCTION expand_value_set(root_code, terminology, include_descendants=true, max_depth=5):
    // Start with the root concept.
    // "Value set expansion" means: give me this concept and everything below it
    // in the hierarchy.
    
    IF not include_descendants:
        // Simple case: just return the root concept and its cross-terminology mappings.
        RETURN normalize_concept(root_code, terminology, all_terminologies)
    
    // Traverse the "is-a" hierarchy downward from the root.
    // max_depth prevents runaway traversals on very broad concepts
    // (e.g., "Clinical finding" in SNOMED has hundreds of thousands of descendants).
    descendants = neptune.query("""
        MATCH (root:Concept {code: $root_code, terminology: $terminology})
              <-[:is_a*1..$max_depth]-
              (descendant:Concept {terminology: $terminology})
        WHERE descendant.status = 'active'
        RETURN descendant.code AS code,
               descendant.display AS display,
               length(path) AS depth
        ORDER BY depth ASC
    """, params={root_code, terminology, max_depth})
    
    // For each descendant, also find cross-terminology mappings.
    // This gives you the full value set in all terminologies.
    expanded_set = [{code: root_code, terminology: terminology}]
    
    FOR each descendant in descendants:
        append to expanded_set: {
            code:        descendant.code,
            terminology: terminology,
            display:     descendant.display,
            depth:       descendant.depth
        }
        
        // Optionally expand each descendant to other terminologies.
        // This is expensive for large hierarchies. Consider doing it lazily.
        cross_maps = normalize_concept(descendant.code, terminology, target_terminologies)
        append cross_maps.mappings to expanded_set
    
    RETURN {
        root:       {code: root_code, terminology: terminology},
        total_concepts: length(expanded_set),
        concepts:   expanded_set
    }
```

**Step 6: Version management and temporal queries.** Terminologies change. A code that existed in ICD-10-CM 2023 might be retired in 2024 and replaced by two more specific codes. Your normalization system needs to answer questions like "what was the correct mapping for this code as of the date this claim was filed?" This step handles version-aware queries by maintaining historical edges and filtering by effective date.

```
FUNCTION normalize_as_of_date(code, terminology, target_terminologies, as_of_date):
    // Find the concept version that was active on the given date.
    // Terminology versions have effective dates (e.g., ICD-10-CM FY2024 effective Oct 1, 2023).
    
    active_version = neptune.query("""
        MATCH (c:Concept {code: $code, terminology: $terminology})
        WHERE c.effective_date <= $as_of_date
        AND (c.retirement_date IS NULL OR c.retirement_date > $as_of_date)
        RETURN c
        ORDER BY c.effective_date DESC
        LIMIT 1
    """, params={code, terminology, as_of_date})
    
    IF active_version is null:
        RETURN {status: "not_found_at_date", code: code, as_of: as_of_date}
    
    // Find mappings that were active on that date.
    mappings = neptune.query("""
        MATCH (source:Concept {code: $code, terminology: $terminology})
              -[r]->(target:Concept)
        WHERE target.terminology IN $target_terminologies
        AND r.effective_date <= $as_of_date
        AND (r.retirement_date IS NULL OR r.retirement_date > $as_of_date)
        AND target.effective_date <= $as_of_date
        AND (target.retirement_date IS NULL OR target.retirement_date > $as_of_date)
        RETURN target, r
    """, params={code, terminology, target_terminologies, as_of_date})
    
    RETURN {
        source:    active_version,
        mappings:  mappings,
        as_of:     as_of_date,
        note:      "Mappings reflect terminology state as of the specified date"
    }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3 and the Neptune graph client, check out the [Python Example](chapter13.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample normalization response for "Type 2 diabetes mellitus" (ICD-10 E11):**

```json
{
  "source": {
    "code": "E11",
    "terminology": "ICD10CM",
    "display": "Type 2 diabetes mellitus",
    "semantic_type": "Disease or Syndrome"
  },
  "mappings": [
    {
      "code": "44054006",
      "terminology": "SNOMEDCT",
      "display": "Type 2 diabetes mellitus",
      "relationship_type": "equivalent_to",
      "confidence": 0.95,
      "provenance": "UMLS_CUI_C0011860"
    },
    {
      "code": "73211009",
      "terminology": "SNOMEDCT",
      "display": "Diabetes mellitus",
      "relationship_type": "broader_than",
      "confidence": 1.0,
      "provenance": "SNOMED_HIERARCHY"
    },
    {
      "code": "4855003",
      "terminology": "SNOMEDCT",
      "display": "Diabetic retinopathy",
      "relationship_type": "related_to",
      "confidence": 0.7,
      "provenance": "UMLS_ASSOCIATION"
    }
  ],
  "mapping_count": 3,
  "query_timestamp": "2026-06-01T14:30:22Z"
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Point lookup (cached) | < 1ms |
| Point lookup (cache miss, single hop) | 5-15ms |
| Multi-hop traversal (2 hops) | 20-80ms |
| Value set expansion (100 descendants) | 200-500ms |
| Value set expansion (10,000 descendants) | 2-5 seconds |
| Full terminology load (SNOMED CT) | 30-60 minutes |
| Incremental update (monthly RxNorm) | 5-15 minutes |
| Graph size (full UMLS subset) | ~5M nodes, ~20M edges |

**Where it struggles:**

- Very broad hierarchy expansions (e.g., "all clinical findings" in SNOMED) can return hundreds of thousands of concepts and take minutes. Pagination and depth limits are essential.
- Ambiguous mappings where UMLS provides multiple candidate targets with similar confidence. Consumers need logic to pick the best match for their context.
- Retired codes that appear in historical data but have no active mapping target. You need a "best available" fallback strategy.
- Composite concepts that require multiple codes in the target terminology. The API returns individual mappings; the consumer must assemble them.

---

## The Honest Take

Building a concept normalization system is one of those projects where the first 80% feels deceptively easy. You load UMLS, wire up a query API, and for common concepts (diabetes, hypertension, the top 100 diagnoses), everything works beautifully. Then you hit the long tail.

The long tail is where you discover that "unspecified" codes in ICD-10 map to dozens of SNOMED concepts and your consumers don't know which one to pick. Where a LOINC code for "hemoglobin" maps differently depending on whether it's a point-of-care test or a lab panel component. Where a drug concept in RxNorm has been split into two concepts in the latest release and your historical mappings are now ambiguous.

The curation interface is the thing that will consume the most ongoing effort. UMLS gets you the bulk of the mappings, but every organization has edge cases specific to their data. A local lab uses non-standard LOINC codes. A legacy system has proprietary internal codes that need mapping. A quality measure references a value set that doesn't align cleanly with your SNOMED hierarchy. These all require human terminologists to create and maintain custom mappings.

Version management is the thing that surprised me most. I initially built this as a "current state" system: load the latest version of everything, done. Then someone asked "why did this patient's risk score change between last month and this month when nothing clinical changed?" The answer was that an ICD-10 annual update reclassified a code, which changed its SNOMED mapping, which changed its HCC category. Without temporal queries, you can't explain that. Retroactive terminology changes are a real operational concern.

The cache invalidation problem is also non-trivial. When you load a new terminology version, which cache entries are stale? The naive answer is "flush everything," but that causes a thundering herd on Neptune. The smart answer is to compute the delta (which concepts changed) and selectively invalidate, but that requires tracking which cache entries depend on which graph nodes.

One more thing: licensing. UMLS requires a free license from NLM. SNOMED CT is free in the US (NLM holds the license). But CPT requires a paid AMA license, and some specialty terminologies have their own licensing terms. Budget for this and track your compliance.

---

## Variations and Extensions

**Real-time NLP normalization.** Integrate the normalization API with an NLP pipeline (see Chapter 8) that extracts clinical concepts from free text. The NLP system identifies "type 2 DM" in a clinical note, the normalization service maps it to the canonical SNOMED concept, and downstream systems get structured, coded data from unstructured text. This is the bridge between NLP extraction and computable clinical data.

**FHIR ConceptMap integration.** Expose your normalization mappings as FHIR ConceptMap resources. This makes your terminology service interoperable with any FHIR-compliant system. The ConceptMap resource has native support for equivalence types (equivalent, wider, narrower, inexact), which maps directly to your graph edge types. Useful for health information exchange scenarios.

**Automated mapping suggestion.** For concepts that lack cross-terminology mappings, use embedding-based similarity to suggest candidates. Encode concept display names and definitions as vectors, find nearest neighbors across terminologies, and present suggestions to terminologists for review. This accelerates curation for the long tail of unmapped concepts. Not a replacement for human review, but a significant productivity multiplier.

---

## Related Recipes

- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Provides the hierarchy traversal foundation that value set expansion in this recipe builds upon
- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Uses RxNorm normalization from this recipe to identify drugs regardless of how they're coded in source systems
- **Recipe 13.6 (Care Gap Reasoning Engine):** Depends on normalized concepts to match patient conditions against guideline criteria
- **Recipe 8.4 (Medication Extraction and Normalization):** NLP pipeline that feeds extracted concepts into this normalization service
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Uses cross-terminology mappings to join claims data (ICD-10) with clinical data (SNOMED)

---

## Additional Resources

**AWS Documentation:**
- [Amazon Neptune User Guide](https://docs.aws.amazon.com/neptune/latest/userguide/intro.html)
- [Neptune openCypher Query Language](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html)
- [Neptune Bulk Loader](https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html)
- [Amazon Neptune Pricing](https://aws.amazon.com/neptune/pricing/)
- [AWS Glue ETL Programming Guide](https://docs.aws.amazon.com/glue/latest/dg/aws-glue-programming-etl.html)
- [Amazon ElastiCache for Redis](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**Terminology Sources:**
- [UMLS Metathesaurus (NLM)](https://www.nlm.nih.gov/research/umls/knowledge_sources/metathesaurus/index.html)
- [SNOMED CT Browser](https://browser.ihtsdotools.org/)
- [ICD-10-CM Files (CMS)](https://www.cms.gov/medicare/coding-billing/icd-10-codes)
- [LOINC Downloads (Regenstrief)](https://loinc.org/downloads/)
- [RxNorm (NLM)](https://www.nlm.nih.gov/research/umls/rxnorm/index.html)

**AWS Solutions and Blogs:**
- [Building a Healthcare Knowledge Graph on AWS](https://aws.amazon.com/blogs/database/building-a-healthcare-knowledge-graph-on-amazon-neptune/)
- [Graph Data Modeling with Amazon Neptune](https://aws.amazon.com/blogs/database/graph-data-modelling-with-amazon-neptune/)

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 4-6 weeks | Single terminology pair (ICD-10 to SNOMED), point lookup API, no caching |
| **Production-ready** | 3-5 months | Full UMLS integration, 5+ terminologies, caching layer, version management, curation UI |
| **With variations** | 6-9 months | NLP integration, FHIR ConceptMap exposure, automated mapping suggestions, multi-tenant support |

---

## Tags

`knowledge-graph` · `terminology` · `normalization` · `snomed` · `icd-10` · `loinc` · `rxnorm` · `umls` · `neptune` · `mapping` · `interoperability` · `complex` · `foundation` · `hipaa`

---

*← [Recipe 13.7: Disease-Gene-Drug Relationship Graph](chapter13.07-disease-gene-drug-relationship-graph) · [Chapter 13 Index](chapter13-index) · [Next: Recipe 13.9 - Literature-Derived Knowledge Graph →](chapter13.09-literature-derived-knowledge-graph)*
