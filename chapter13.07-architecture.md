# Recipe 13.7 Architecture and Implementation: Disease-Gene-Drug Relationship Graph

*Companion to [Recipe 13.7: Disease-Gene-Drug Relationship Graph](chapter13.07-disease-gene-drug-relationship-graph). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Neptune for the knowledge graph store.** Neptune speaks two graph languages: property graph (openCypher or Gremlin) and RDF (SPARQL). For pharmacogenomics, property graph wins. Your queries read like the clinical question you're actually asking: "start at this variant, traverse to the gene, find drugs metabolized by that gene, filter by evidence level." openCypher makes that traversal pattern natural. Neptune handles the multi-hop traversals efficiently, runs within your VPC, supports encryption at rest, and is HIPAA eligible. The managed nature means you're not tuning JanusGraph or managing Cassandra backends.

**AWS Glue for ETL and source integration.** The source databases (PharmGKB, ClinVar, DrugBank) publish data in various formats: TSV files, XML dumps, REST APIs. Glue jobs handle the extraction, transformation, and entity resolution needed to produce clean graph-loadable data. Glue's serverless Spark environment handles the large ClinVar dataset (millions of variant records) without provisioning infrastructure.

**Amazon S3 for source data staging and graph snapshots.** Raw source downloads, intermediate transformation outputs, and Neptune bulk load files all stage through S3. S3 versioning provides an audit trail of which source versions produced which graph version. Neptune's bulk loader reads directly from S3, making the load path clean.

**AWS Lambda for query orchestration and API serving.** Individual patient queries (given these variants, what's actionable?) are short-lived, stateless operations. Lambda handles the query construction, Neptune interaction, evidence filtering, and response formatting. For the clinical decision support integration, API Gateway plus Lambda provides a synchronous REST endpoint.

**Amazon EventBridge for update orchestration.** Source databases update on different cadences (ClinVar weekly, DrugBank quarterly, CPIC as-published). EventBridge schedules the appropriate ETL jobs and coordinates the graph update pipeline. When a source updates, the pipeline runs automatically: download, transform, validate, load, verify.

**AWS Step Functions for the graph update pipeline.** The full update workflow (download sources, run ETL, validate entity resolution, bulk load to Neptune, run integration tests, swap to new graph version) has multiple steps with error handling and rollback requirements. Step Functions orchestrates this reliably.

### Architecture Diagram

```mermaid
flowchart TD
    subgraph Sources["Source Databases"]
        PGx[PharmGKB]
        CV[ClinVar]
        DB[DrugBank]
        CPIC[CPIC Guidelines]
        OMIM[OMIM]
        FDA[FDA PGx Table]
    end

    subgraph ETL["Integration Pipeline"]
        S3Raw[S3: Raw Downloads]
        Glue[AWS Glue ETL]
        S3Clean[S3: Graph Load Files]
        SF[Step Functions\nOrchestration]
    end

    subgraph Graph["Knowledge Graph"]
        Neptune[Amazon Neptune\nProperty Graph]
    end

    subgraph Query["Query Layer"]
        APIGW[API Gateway]
        Lambda[Lambda\nQuery Engine]
    end

    subgraph Clinical["Clinical Integration"]
        EHR[EHR / CDS System]
        PharmReview[Pharmacist\nReview Queue]
    end

    Sources -->|Scheduled Downloads| S3Raw
    S3Raw --> Glue
    Glue -->|Entity Resolution\nEvidence Grading| S3Clean
    S3Clean -->|Bulk Load| Neptune
    SF -->|Orchestrates| Glue
    EventBridge[EventBridge\nScheduler] -->|Triggers| SF

    EHR -->|Patient Variants\n+ Medications| APIGW
    APIGW --> Lambda
    Lambda -->|Graph Traversal| Neptune
    Lambda -->|Recommendations| EHR
    Lambda -->|Uncertain Cases| PharmReview
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| AWS Services | Neptune, S3, Glue, Lambda, API Gateway, Step Functions, EventBridge, IAM, KMS, CloudWatch |
| IAM Permissions | **Query path (Lambda):** `neptune-db:ReadDataViaQuery`, `neptune-db:GetQueryStatus` only. No graph write permissions. **ETL pipeline (Glue/Step Functions):** full `neptune-db:*` write access, `s3:GetObject/PutObject`, `glue:StartJobRun`, `states:StartExecution`. Principle of least privilege: the query Lambda must never have write access to the graph. |
| BAA | Required. Patient genomic data is PHI under HIPAA. Genetic information also protected under GINA. Implement role-based access control: pharmacists see full genotype data, ordering physicians see recommendation only (no raw variant detail). Separate audit logs for genetic data access. Note: several U.S. states have genetic privacy laws stricter than GINA (e.g., California GIPA, Illinois GIPA). Consult legal counsel for state-specific requirements in your deployment region. |
| Encryption | Customer-managed KMS key (CMK) with automatic annual rotation. Apply the same CMK to S3 bucket encryption, Neptune cluster (set at cluster creation, cannot be changed later), and CloudWatch Logs log group encryption. TLS 1.2+ for all data in transit. |
| VPC | Neptune must run in VPC. Lambda in same VPC with Neptune access. Required VPC endpoints: S3 (Gateway type), KMS (Interface), CloudWatch Logs (Interface), CloudWatch Monitoring (Interface), Step Functions (Interface), EventBridge (Interface). No NAT Gateway required for the query path since all AWS service calls route through VPC endpoints. |
| Network Security | Neptune security group: allow inbound TCP 8182 only from the Lambda security group. Lambda security group: allow outbound TCP 8182 to Neptune SG and outbound TCP 443 to VPC endpoint security groups. No inbound rules on the Lambda security group. |
| CloudTrail | All API calls logged. Neptune audit logs enabled via cluster parameter group (`neptune_enable_audit_log=1`). Publish Neptune audit logs to CloudWatch Logs. Encrypt the audit log group with the same CMK. Set log retention to match your HIPAA audit policy (typically 6-7 years). |
| Sample Data | PharmGKB open-access datasets. ClinVar public XML dump. Synthetic patient variants for testing. |
| High Availability | Deploy Neptune Multi-AZ with a read replica in a different AZ for automatic failover (under 30 seconds). Query Lambda should use the Neptune reader endpoint for all read operations. This separates query load from write load and provides automatic failover if the primary instance fails. |
| Cost Estimate | Neptune db.r5.large primary + read replica (~$836/month total for the cluster), Glue ETL (~$0.44/DPU-hr weekly), Lambda queries (~$0.0001/query) |

### Ingredients

| AWS Service | Role in This Recipe |
|-------------|-------------------|
| Amazon Neptune | Stores the disease-gene-drug knowledge graph. Handles multi-hop traversals for pharmacogenomic queries. |
| AWS Glue | Runs ETL jobs to transform source database dumps into graph-loadable format. Handles entity resolution. |
| Amazon S3 | Stages raw source data, transformed graph files, and Neptune snapshots. Provides versioning for audit. |
| AWS Lambda | Executes patient-specific graph queries. Constructs traversals, filters by evidence, formats recommendations. |
| API Gateway | Exposes REST endpoint for clinical decision support integration. Handles auth and throttling. |
| Step Functions | Orchestrates the multi-step graph update pipeline with error handling and rollback. |
| EventBridge | Schedules source database checks and triggers update pipelines on appropriate cadences. |
| AWS KMS | Manages encryption keys for data at rest across all services. |
| CloudWatch | Monitors query latency, graph size metrics, ETL job success rates, and alert thresholds. |

### Code (Pseudocode Walkthrough)

The system has two major workflows: (1) building and updating the knowledge graph from source databases, and (2) querying the graph for a specific patient's pharmacogenomic recommendations.

#### Step 1: Source Data Ingestion

Each source database publishes data in its own format. We download, validate, and stage it.

This step matters because stale or corrupted source data propagates errors throughout the graph. A bad ClinVar download could reclassify thousands of variants incorrectly. Validation catches this before it reaches the graph.

```pseudocode
FUNCTION ingest_source(source_name, source_url, expected_format):
    // Download the latest release from the source
    raw_data = download(source_url)
    
    // Validate the download is complete and well-formed
    IF NOT validate_checksum(raw_data, source_name):
        RAISE IngestionError("Checksum mismatch for " + source_name)
    
    IF NOT validate_schema(raw_data, expected_format):
        RAISE IngestionError("Schema validation failed for " + source_name)
    
    // Stage in S3 with version metadata
    s3_path = "s3://knowledge-graph-sources/{source_name}/{date}/{filename}"
    upload_to_s3(raw_data, s3_path, metadata={
        "source": source_name,
        "download_date": today(),
        "source_version": extract_version(raw_data),
        "record_count": count_records(raw_data)
    })
    
    RETURN s3_path
```

#### Step 2: Entity Resolution and Normalization

This is the hardest engineering step. Different sources use different identifiers for the same entity. We need a canonical mapping.

If you skip this step, you end up with duplicate nodes: "CYP2D6" from PharmGKB and "CYP2D6" from DrugBank as separate, unconnected entities. The graph becomes fragmented and queries miss relationships that cross source boundaries.

```pseudocode
FUNCTION resolve_entities(source_records):
    resolved = []
    
    FOR EACH record IN source_records:
        // Map gene identifiers to canonical form
        IF record.has_gene:
            record.gene_id = map_to_canonical_gene(
                symbol=record.gene_symbol,
                entrez_id=record.entrez_id,
                ensembl_id=record.ensembl_id
            )
            // Canonical form: {symbol, entrez_id, ensembl_id, hgnc_id}
        
        // Map drug identifiers to canonical form
        IF record.has_drug:
            record.drug_id = map_to_canonical_drug(
                name=record.drug_name,
                drugbank_id=record.drugbank_id,
                rxnorm_cui=record.rxnorm_cui,
                atc_code=record.atc_code
            )
        
        // Map variant identifiers to canonical form
        IF record.has_variant:
            record.variant_id = map_to_canonical_variant(
                rsid=record.rsid,
                hgvs=record.hgvs_notation,
                star_allele=record.star_allele,
                gene=record.gene_id
            )
        
        // Map disease identifiers to canonical form
        IF record.has_disease:
            record.disease_id = map_to_canonical_disease(
                omim_id=record.omim_id,
                mondo_id=record.mondo_id,
                icd10=record.icd10_code
            )
        
        resolved.append(record)
    
    // Detect and flag ambiguous mappings for manual review.
    // Conservative strategy: exclude ambiguous records from the graph load
    // until resolved. An ambiguous mapping could create incorrect edges
    // (e.g., linking the wrong drug to a gene interaction).
    ambiguous = find_ambiguous_mappings(resolved)
    IF ambiguous.count > 0:
        exclude_from_load(resolved, ambiguous)
        queue_for_review(ambiguous)
        log_warning(f"{ambiguous.count} ambiguous mappings excluded from graph load, queued for review")
        // Alert if ambiguity rate is abnormally high (possible source data issue)
        ambiguity_rate = ambiguous.count / resolved.count
        IF ambiguity_rate > 0.05:
            alert_team(f"Ambiguity rate {ambiguity_rate:.1%} exceeds 5% threshold. Possible source data corruption.")
    
    RETURN resolved
```

#### Step 3: Graph Construction

Transform resolved records into graph nodes and edges with evidence metadata.

This step creates the actual knowledge graph structure. Each relationship carries its evidence level, source, and publication date so that downstream queries can filter by confidence.

```pseudocode
FUNCTION build_graph_load_files(resolved_records):
    nodes = []
    edges = []
    
    FOR EACH record IN resolved_records:
        // Create or update entity nodes
        IF record.type == "gene_drug_association":
            // Ensure gene node exists
            nodes.add(Node(
                id=record.gene_id.canonical,
                label="Gene",
                properties={
                    "symbol": record.gene_id.symbol,
                    "entrez_id": record.gene_id.entrez_id,
                    "chromosome": record.chromosome,
                    "function": record.gene_function
                }
            ))
            
            // Ensure drug node exists
            nodes.add(Node(
                id=record.drug_id.canonical,
                label="Drug",
                properties={
                    "name": record.drug_id.name,
                    "rxnorm_cui": record.drug_id.rxnorm_cui,
                    "therapeutic_class": record.therapeutic_class,
                    "mechanism": record.mechanism_of_action
                }
            ))
            
            // Create the relationship with evidence
            edges.add(Edge(
                from_id=record.gene_id.canonical,
                to_id=record.drug_id.canonical,
                type=record.relationship_type,  // "metabolizes", "targets", "transports"
                properties={
                    "evidence_level": record.evidence_level,  // "1A", "1B", "2A", etc.
                    "source": record.source_database,
                    "pmids": record.supporting_publications,
                    "cpic_level": record.cpic_level,
                    "fda_label": record.has_fda_pgx_label,
                    "last_reviewed": record.review_date,
                    "clinical_annotation": record.clinical_text
                }
            ))
        
        IF record.type == "variant_phenotype":
            // Variant node
            nodes.add(Node(
                id=record.variant_id.canonical,
                label="Variant",
                properties={
                    "rsid": record.rsid,
                    "hgvs": record.hgvs,
                    "star_allele": record.star_allele,
                    "functional_status": record.function,  // "no_function", "decreased", "normal"
                    "allele_freq_eur": record.freq_european,
                    "allele_freq_afr": record.freq_african,
                    "allele_freq_eas": record.freq_east_asian,
                    "clinvar_classification": record.clinvar_class
                }
            ))
            
            // Variant-to-gene edge
            edges.add(Edge(
                from_id=record.variant_id.canonical,
                to_id=record.gene_id.canonical,
                type="is_variant_of",
                properties={"functional_impact": record.function}
            ))
    
    // Deduplicate nodes (same entity from multiple sources)
    nodes = deduplicate_nodes(nodes, merge_strategy="union_properties")
    
    // Write Neptune bulk load format (CSV)
    write_neptune_csv(nodes, "s3://graph-loads/{version}/nodes/")
    write_neptune_csv(edges, "s3://graph-loads/{version}/edges/")
    
    RETURN {"node_count": nodes.count, "edge_count": edges.count}
```

#### Step 4: Diplotype-to-Phenotype Mapping

This step encodes the translation tables that convert raw genotypes into clinical phenotypes.

Without this, you have variant data but no clinical interpretation. A clinician doesn't act on "CYP2D6*4/*4." They act on "poor metabolizer." This mapping is gene-specific and maintained by CPIC.

```pseudocode
FUNCTION load_diplotype_phenotype_mappings():
    // CPIC publishes translation tables per gene
    // Example: CYP2D6 has ~100 star alleles with activity scores
    
    FOR EACH gene IN cpic_genes:
        translation_table = download_cpic_table(gene)
        
        FOR EACH entry IN translation_table:
            // Create phenotype node if not exists
            phenotype_node = Node(
                id=f"{gene}_{entry.phenotype}",
                label="Phenotype",
                properties={
                    "gene": gene,
                    "phenotype": entry.phenotype,  // "Poor Metabolizer"
                    "activity_score_range": entry.activity_range,
                    "ehr_term": entry.ehr_display_term
                }
            )
            
            // Create diplotype-to-phenotype edges
            FOR EACH diplotype IN entry.diplotypes:
                edges.add(Edge(
                    from_id=f"{gene}_{diplotype}",
                    to_id=phenotype_node.id,
                    type="results_in_phenotype",
                    properties={
                        "activity_score": entry.activity_score,
                        "cpic_version": translation_table.version
                    }
                ))
    
    // Also load phenotype-to-recommendation edges
    FOR EACH guideline IN cpic_guidelines:
        FOR EACH recommendation IN guideline.recommendations:
            edges.add(Edge(
                from_id=f"{guideline.gene}_{recommendation.phenotype}",
                to_id=recommendation.drug_id,
                type="recommendation",
                properties={
                    "action": recommendation.action,  // "use_alternative", "dose_adjust", "standard_dose"
                    "strength": recommendation.strength,  // "strong", "moderate"
                    "alternatives": recommendation.alternative_drugs,
                    "guideline_version": guideline.version,
                    "population_notes": recommendation.population_caveats
                }
            ))
```

#### Step 5: Patient Query Execution

Given a patient's genetic test results and current medications, traverse the graph to find actionable pharmacogenomic findings.

This is the clinical payoff. Everything above was infrastructure. This step answers the question: "For this specific patient, which of their medications might be affected by their genetics, and what should we do about it?"

**Error handling on the query path:** Distinguish between a successful query that returns no findings (HTTP 200, empty results array) and a query that failed to execute (HTTP 503, Neptune timeout, or connection error). When the query fails, the CDS system should display a "pharmacogenomic check unavailable" notification to the clinician rather than silently omitting results. Log failed queries to an SQS dead-letter queue for retry. Set a CloudWatch alarm on the query failure rate: if it exceeds 1% of queries over a 5-minute window, page the on-call team.

```pseudocode
FUNCTION query_patient_pharmacogenomics(patient_variants, current_medications, evidence_threshold="2A"):
    findings = []
    
    // Input validation: reject malformed inputs before they reach Neptune.
    // This prevents injection, catches upstream data quality issues, and
    // produces clean audit logs.
    FOR EACH variant IN patient_variants:
        IF NOT matches_pattern(variant.rsid, "rs[0-9]+"):
            log_and_skip(variant, "Invalid rsID format")
            CONTINUE
        IF NOT is_known_pharmacogene(variant.gene):
            log_and_skip(variant, "Gene not in known pharmacogenes list")
            CONTINUE
    
    FOR EACH medication IN current_medications:
        IF NOT matches_pattern(medication.rxnorm_cui, "[0-9]+"):
            log_and_skip(medication, "Invalid RxNorm CUI format")
            CONTINUE
    
    // Step 5a: Determine patient phenotypes from their variants
    patient_phenotypes = {}
    FOR EACH gene IN pharmacogenes:
        // Get patient's diplotype for this gene
        diplotype = call_diplotype(patient_variants, gene)
        IF diplotype IS NOT NULL:
            // Traverse: diplotype -> phenotype
            phenotype = graph_query("""
                MATCH (d:Diplotype {gene: $gene, diplotype: $diplotype})
                      -[:results_in_phenotype]->(p:Phenotype)
                RETURN p.phenotype, p.activity_score_range
            """, gene=gene, diplotype=diplotype)
            
            IF phenotype:
                patient_phenotypes[gene] = phenotype
    
    // Step 5b: Check each current medication against patient phenotypes
    FOR EACH medication IN current_medications:
        // Find gene-drug relationships for this medication
        gene_interactions = graph_query("""
            MATCH (g:Gene)-[r:metabolizes|targets|transports]->(d:Drug {rxnorm_cui: $drug_cui})
            WHERE r.evidence_level IN $acceptable_levels
            RETURN g.symbol, r.type, r.evidence_level, r.clinical_annotation
        """, drug_cui=medication.rxnorm_cui, 
             acceptable_levels=levels_at_or_above(evidence_threshold))
        
        FOR EACH interaction IN gene_interactions:
            // Does the patient have an actionable phenotype for this gene?
            IF interaction.gene IN patient_phenotypes:
                phenotype = patient_phenotypes[interaction.gene]
                
                // Get the specific recommendation
                recommendation = graph_query("""
                    MATCH (p:Phenotype {gene: $gene, phenotype: $phenotype})
                          -[rec:recommendation]->(d:Drug {rxnorm_cui: $drug_cui})
                    RETURN rec.action, rec.strength, rec.alternatives, rec.guideline_version
                """, gene=interaction.gene, phenotype=phenotype, drug_cui=medication.rxnorm_cui)
                
                IF recommendation AND recommendation.action != "standard_dose":
                    findings.append({
                        "medication": medication.name,
                        "gene": interaction.gene,
                        "patient_phenotype": phenotype,
                        "recommendation": recommendation.action,
                        "strength": recommendation.strength,
                        "alternatives": recommendation.alternatives,
                        "evidence_level": interaction.evidence_level,
                        "guideline": recommendation.guideline_version,
                        "clinical_context": interaction.clinical_annotation
                    })
    
    // Step 5c: Check for drug-drug-gene interactions (phenoconversion)
    FOR EACH gene, phenotype IN patient_phenotypes:
        inhibitors = find_concomitant_inhibitors(current_medications, gene)
        IF inhibitors:
            adjusted_phenotype = apply_phenoconversion(phenotype, inhibitors)
            IF adjusted_phenotype != phenotype:
                findings.append({
                    "type": "phenoconversion_warning",
                    "gene": gene,
                    "genetic_phenotype": phenotype,
                    "effective_phenotype": adjusted_phenotype,
                    "inhibiting_drugs": inhibitors,
                    "clinical_note": f"Patient is genetically {phenotype} for {gene} but concomitant {inhibitors} may result in effective {adjusted_phenotype} status"
                })
    
    // Sort by clinical urgency and evidence strength
    findings.sort(key=lambda f: (urgency_score(f), evidence_rank(f)), reverse=True)
    
    RETURN findings
```

#### Step 6: Graph Update Pipeline

Orchestrate the periodic refresh of the knowledge graph as sources publish new data.

This step keeps the graph current. Pharmacogenomic knowledge evolves rapidly. A graph that's six months stale might miss newly actionable gene-drug pairs or updated evidence classifications.

```pseudocode
FUNCTION run_graph_update_pipeline(triggered_sources):
    // Create a new graph version (don't modify the live graph in place)
    new_version = generate_version_id()  // e.g., "v2026-05-31"
    
    // Step 6a: Download updated sources
    FOR EACH source IN triggered_sources:
        raw_path = ingest_source(source.name, source.url, source.format)
        validate_source_delta(raw_path, source.previous_version)
        // Delta validation: flag if >5% of records changed (possible data issue)
    
    // Step 6b: Run ETL with entity resolution
    resolved = run_glue_job("entity-resolution", {
        "sources": triggered_sources,
        "version": new_version,
        "resolution_config": "s3://config/entity-resolution-rules.json"
    })
    
    // Step 6c: Build graph load files
    load_stats = build_graph_load_files(resolved)
    log_info(f"Version {new_version}: {load_stats.node_count} nodes, {load_stats.edge_count} edges")
    
    // Step 6d: Zero-downtime graph update using Neptune cloneCluster.
    // Never bulk-load into the live production cluster. Queries during a load
    // window would see an inconsistent graph state.
    // Strategy: clone production -> bulk load into clone -> integration test -> swap endpoint -> terminate old.
    clone_cluster = neptune_clone_cluster(
        source_cluster=production_cluster_id,
        clone_id=f"pgx-graph-{new_version}"
    )
    
    load_result = neptune_bulk_load(
        cluster=clone_cluster.endpoint,
        source="s3://graph-loads/{new_version}/",
        iam_role=neptune_load_role,
        format="opencypher",
        fail_on_error=True
    )
    
    // Step 6e: Run integration tests against the clone (not production)
    test_results = run_integration_tests(clone_cluster.endpoint, test_suite="pharmacogenomics")
    IF NOT test_results.all_passed:
        alert_team("Graph update failed integration tests", test_results.failures)
        terminate_cluster(clone_cluster)
        RETURN {"status": "failed", "reason": test_results.failures}
    
    // Step 6f: Swap live traffic to the new clone, then terminate the old cluster
    old_cluster = swap_reader_endpoint(production_reader_endpoint, clone_cluster)
    terminate_cluster(old_cluster)
    
    RETURN {"status": "success", "version": new_version, "stats": load_stats}
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter13.07-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

Sample output from a patient pharmacogenomics query:

```json
{
  "patient_id": "P-00847291",
  "query_timestamp": "2026-05-31T14:22:08Z",
  "graph_version": "v2026-05-28",
  "variants_analyzed": 14,
  "genes_with_phenotype": 5,
  "findings": [
    {
      "priority": "HIGH",
      "medication": "Tamoxifen",
      "gene": "CYP2D6",
      "patient_diplotype": "*4/*4",
      "patient_phenotype": "Poor Metabolizer",
      "recommendation": "use_alternative",
      "strength": "strong",
      "alternatives": ["aromatase inhibitor (if post-menopausal)", "alternative SERM"],
      "evidence_level": "1A",
      "guideline": "CPIC CYP2D6 and Tamoxifen 2018",
      "clinical_context": "Poor metabolizers have significantly reduced conversion of tamoxifen to endoxifen. Consider alternative endocrine therapy."
    },
    {
      "priority": "MODERATE",
      "medication": "Omeprazole",
      "gene": "CYP2C19",
      "patient_diplotype": "*1/*17",
      "patient_phenotype": "Rapid Metabolizer",
      "recommendation": "dose_adjust",
      "strength": "moderate",
      "alternatives": ["increase dose", "consider alternative PPI"],
      "evidence_level": "1A",
      "guideline": "CPIC CYP2C19 and PPIs 2020",
      "clinical_context": "Rapid metabolizers may have reduced efficacy at standard doses due to increased drug clearance."
    },
    {
      "priority": "INFO",
      "type": "phenoconversion_warning",
      "gene": "CYP2D6",
      "genetic_phenotype": "Poor Metabolizer",
      "effective_phenotype": "Poor Metabolizer",
      "inhibiting_drugs": [],
      "clinical_note": "No phenoconversion detected. Genetic phenotype reflects clinical phenotype."
    }
  ],
  "medications_without_findings": ["Lisinopril", "Metformin", "Atorvastatin"],
  "confidence_metadata": {
    "evidence_threshold_applied": "2A",
    "sources_consulted": ["PharmGKB", "CPIC", "ClinVar", "FDA PGx Table"],
    "graph_last_updated": "2026-05-28",
    "clinvar_version": "2026-05-25",
    "cpic_version": "2026-Q1"
  }
}
```

**Performance Benchmarks:**

| Metric | Value | Notes |
|--------|-------|-------|
| Query latency (single patient) | 200-500ms | Neptune traversal only. End-to-end (API Gateway + Lambda + Neptune): 500-800ms warm, 2-4s cold start. |
| Graph size (nodes) | ~2.5M | Genes, variants, drugs, diseases, phenotypes, pathways |
| Graph size (edges) | ~15M | All relationship types with evidence metadata |
| Source update frequency | Weekly (ClinVar), Quarterly (DrugBank, CPIC) | EventBridge-scheduled |
| Bulk load time (full rebuild) | 45-90 minutes | Neptune bulk loader from S3 |
| Evidence coverage | ~400 gene-drug pairs at Level 1A/1B | CPIC + PharmGKB high-evidence |

**Where It Struggles:**

- Rare variants not yet in ClinVar (no classification available, must return "uncertain")
- Complex CYP2D6 structural variants (gene deletions, duplications, hybrid alleles) that don't map cleanly to star alleles
- Patients with ancestry not well-represented in frequency databases (allele frequency data may be unreliable)
- Novel drugs without established pharmacogenomic data (graph has no edges to traverse)
- Conflicting evidence between sources (requires human adjudication workflow)

---

## Why This Isn't Production-Ready

The pseudocode and architecture above give you the shape of the system. Here's what separates this from something you'd connect to a clinical decision support system:

**No clinical validation suite.** Before any pharmacogenomic recommendation reaches a clinician, the system must pass validation against a curated set of known-correct cases (patients with established genotypes and guideline-concordant recommendations). You need hundreds of these test cases covering edge cases: compound heterozygotes, multi-gene interactions, and population-specific variants.

**Diplotype calling is hand-waved.** The pseudocode assumes diplotypes arrive as input. In reality, you receive raw VCF data from sequencing and must call star alleles, which is a hard bioinformatics problem (especially for CYP2D6 with its structural variants, gene deletions, and hybrid alleles). Tools like PharmCAT handle this, but integrating them is a significant pipeline addition.

**No pharmacist review workflow.** When the system produces a recommendation with moderate evidence or when multiple conflicting recommendations exist, a pharmacist must review before the alert reaches the ordering physician. This requires a review queue, a UI, and a feedback loop that updates the system based on pharmacist decisions.

**Entity resolution is simplified.** The cross-reference tables shown here have a handful of entries. Production requires mappings for thousands of genes, tens of thousands of drugs, and millions of variants. The Glue ETL job that maintains these mappings is typically the largest engineering effort.

**No phenoconversion completeness.** Only CYP2D6 inhibitors are modeled here. Production systems must cover CYP2C19, CYP3A4, and other enzyme systems. The inhibitor lists must be maintained as new drugs enter the market.

**No regulatory submission trail.** If the system qualifies as a clinical decision support tool under FDA guidance, you may need 510(k) clearance or documentation showing it falls under an exemption. The audit trail for graph updates, evidence versions, and recommendation logic must be airtight.

---

## Variations and Extensions

### Variation 1: Tumor Genomics and Targeted Therapy Matching

Extend the graph to include somatic (tumor-specific) mutations and their relationships to targeted therapies. Add nodes for cancer-specific variants (EGFR L858R, BRAF V600E, ALK fusions) and edges connecting them to approved targeted therapies and clinical trials. This requires integrating OncoKB, CIViC (Clinical Interpretation of Variants in Cancer), and the FDA companion diagnostic table. The query pattern shifts from "what's this patient's metabolizer status" to "does this tumor have a druggable target."

### Variation 2: Population Pharmacogenomics Dashboard

Build an analytics layer on top of the graph that shows pharmacogenomic prevalence across your patient population. Which percentage of your patients on clopidogrel are CYP2C19 poor metabolizers (and thus at risk for treatment failure)? Which drugs in your formulary have the highest pharmacogenomic risk exposure? This supports proactive, pre-emptive testing programs rather than reactive single-gene tests.

### Variation 3: Clinical Trial Eligibility Based on Molecular Profile

Extend the graph with clinical trial nodes connected to their molecular eligibility criteria. When a patient's genomic profile is loaded, traverse not just to drug recommendations but also to open clinical trials that match their molecular profile. This requires integrating ClinicalTrials.gov data and maintaining current enrollment status. Particularly valuable in oncology where molecular profiling increasingly drives trial eligibility.

---

## Additional Resources

### AWS Documentation

- [Amazon Neptune User Guide](https://docs.aws.amazon.com/neptune/latest/userguide/) - Graph database setup, bulk loading, query languages
- [Neptune openCypher Query Language](https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html) - Query syntax for property graph traversals
- [Neptune Bulk Load from S3](https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html) - Loading graph data at scale
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/) - ETL job development and scheduling
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/) - Workflow orchestration patterns
- [AWS HealthOmics](https://docs.aws.amazon.com/omics/latest/dev/) - Genomic data storage and analysis (for variant data management)
- [HIPAA on AWS](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/) - Compliance architecture patterns

### Pharmacogenomics Knowledge Sources

- [PharmGKB](https://www.pharmgkb.org/) - Curated pharmacogenomic knowledge base with clinical annotations and dosing guidelines
- [CPIC Guidelines](https://cpicpgx.org/guidelines/) - Clinical Pharmacogenetics Implementation Consortium evidence-based guidelines
- [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/) - NCBI database of variant clinical significance classifications
- [DrugBank](https://go.drugbank.com/) - Comprehensive drug data including gene targets and metabolic pathways
- [FDA Table of Pharmacogenomic Biomarkers](https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling) - FDA-recognized gene-drug pairs in drug labeling

### AWS Blogs and Solutions

- [Build a knowledge graph in Amazon Neptune](https://aws.amazon.com/blogs/database/build-a-knowledge-graph-in-amazon-neptune/) - Patterns for knowledge graph construction on Neptune
- [AWS Solutions Library - Healthcare](https://aws.amazon.com/solutions/?solutions-all.sort-by=item.additionalFields.sortDate&solutions-all.sort-order=desc&awsf.content-type=*all&awsf.methodology=*all&awsf.tech-category=*all&awsf.industries=industry%23healthcare) - Deployable healthcare reference architectures

---

## Estimated Implementation Time

| Phase | Duration | Notes |
|-------|----------|-------|
| Basic (single source, simple queries) | 6-8 weeks | PharmGKB only, basic gene-drug lookups, no phenoconversion |
| Production-ready (multi-source, evidence-graded) | 14-20 weeks | Full entity resolution, CPIC integration, automated updates, CDS integration |
| With variations (tumor genomics, population analytics) | 24-32 weeks | OncoKB integration, analytics dashboards, clinical trial matching |

---

---

*← [Main Recipe 13.7](chapter13.07-disease-gene-drug-relationship-graph) · [Python Example](chapter13.07-python-example) · [Chapter Preface](chapter13-preface)*
