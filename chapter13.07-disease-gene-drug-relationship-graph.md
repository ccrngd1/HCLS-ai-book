# Recipe 13.7: Disease-Gene-Drug Relationship Graph

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.01 per query traversal

---

## The Problem

A 47-year-old breast cancer patient isn't responding to tamoxifen. Her oncologist suspects she might be a CYP2D6 poor metabolizer, meaning her body can't convert the drug into its active form. If that's the case, she's been taking a medication for months that was never going to work for her. The alternative (an aromatase inhibitor) would have been the right choice from the start, if anyone had connected the dots between her specific genetic variant, the drug's metabolic pathway, and the available alternatives.

This is precision medicine's core promise: match the right drug to the right patient based on their genetic profile. The problem is that the knowledge needed to make these connections is scattered across dozens of databases, thousands of research papers, and multiple clinical annotation systems that don't talk to each other. PharmGKB has pharmacogenomic annotations. ClinVar has variant classifications. DrugBank has drug mechanism data. OMIM has disease-gene associations. The FDA publishes pharmacogenomic biomarker tables. CPIC publishes dosing guidelines based on genotype.

No single clinician can hold all of this in their head. And no single database contains all of it in a queryable, connected form.

The result is that pharmacogenomic knowledge exists but isn't actionable at the point of care. A genetic test comes back showing a CYP2D6 *4/*4 genotype. The lab report says "poor metabolizer." But translating that into "this patient should not be on tamoxifen, consider aromatase inhibitor or alternative SERM" requires traversing a chain of relationships: gene variant to metabolizer phenotype, phenotype to affected drug pathways, affected pathways to specific drugs, drugs to therapeutic alternatives for the patient's specific condition. That's a graph traversal problem.

And it gets harder. The knowledge is evolving rapidly. New gene-drug associations are published weekly. Evidence levels change as studies replicate (or fail to replicate) findings. Different populations have different allele frequencies, meaning the same variant might be common in one ethnic group and rare in another. A static lookup table can't keep up. You need a living, versioned, evidence-graded knowledge structure that clinicians and clinical decision support systems can query in real time.

That's what a disease-gene-drug relationship graph gives you.

---

## The Technology: Biomedical Knowledge Graphs for Precision Medicine

### What Is a Biomedical Knowledge Graph?

A biomedical knowledge graph represents entities from the life sciences (diseases, genes, proteins, drugs, pathways, variants) as nodes, connected by typed, evidence-backed relationships. Unlike a traditional relational database where you'd need complex joins across normalized tables, the graph makes the connections explicit and traversable.

A simple example: the node "CYP2D6" (a gene) connects to "Tamoxifen" (a drug) via the relationship "metabolizes." The node "CYP2D6*4" (a variant) connects to "CYP2D6" via "is_variant_of" and has a property "functional_status: no_function." The node "Tamoxifen" connects to "Breast Cancer" via "indicated_for." These three facts, when connected, tell you something clinically actionable: a patient with CYP2D6*4 homozygosity will poorly metabolize tamoxifen, which is used for breast cancer.

The power isn't in any single fact. It's in the traversal. You can ask: "Given this patient's genetic variants, which of their current medications might be affected, and what alternatives exist for their conditions?" That question requires traversing multiple relationship types across multiple entity types. Graphs handle this naturally. Relational databases handle it painfully.

### The Core Entity Types

A disease-gene-drug graph typically contains these entity types:

**Diseases/Conditions.** Represented with standard ontology identifiers (OMIM, MONDO, ICD-10). These are the clinical endpoints. A disease node might have properties like inheritance pattern, prevalence, and associated phenotypes.

**Genes.** The functional units. Each gene node carries properties like chromosomal location, protein product, and known function. Genes connect to diseases through various relationship types: "causes" (monogenic), "contributes_to" (polygenic risk), "modifies" (disease modifier).

**Variants/Alleles.** Specific genetic changes within genes. These are the actionable units for pharmacogenomics. A variant node carries properties like rsID (from dbSNP), HGVS notation, allele frequency by population, and functional impact classification. Variants connect to genes ("is_variant_of") and to phenotypes ("results_in_phenotype").

**Drugs/Medications.** Represented with RxNorm or ATC codes. Drug nodes carry properties like mechanism of action, therapeutic class, and metabolic pathways. Drugs connect to genes ("metabolized_by," "targets," "transported_by") and to diseases ("indicated_for," "contraindicated_in").

**Pathways.** Metabolic and signaling pathways that connect genes to drug mechanisms. A pathway node represents a biological process (like "CYP2D6-mediated oxidation") that multiple drugs share.

**Phenotypes.** Observable characteristics that result from genetic variation. In pharmacogenomics, these are typically metabolizer statuses: "poor metabolizer," "intermediate metabolizer," "normal metabolizer," "ultra-rapid metabolizer." Phenotypes bridge the gap between raw genotype and clinical action.

### Relationship Types and Evidence Levels

This is where biomedical knowledge graphs get interesting (and hard). Not all relationships are created equal. The connection between CYP2D6 and codeine metabolism is backed by decades of research, FDA labeling, and CPIC Level A guidelines. The connection between some newly discovered variant and a rare drug interaction might be based on a single case report.

Every relationship in the graph needs an evidence level. Common frameworks include:

**CPIC Levels:** A (guideline available, gene-drug pairs with clear prescribing actions), B (moderate evidence), C/D (weaker evidence). Only Level A and B pairs typically drive clinical decision support.

**ClinVar classifications:** Pathogenic, Likely Pathogenic, Uncertain Significance (VUS), Likely Benign, Benign. For pharmacogenomics, you generally only act on Pathogenic and Likely Pathogenic variants.

**PharmGKB evidence levels:** 1A (CPIC/DPWG guideline), 1B (strong evidence), 2A (moderate), 2B (weak), 3 (annotation only), 4 (case report).

Your graph must carry these evidence levels as relationship properties, and your query logic must filter by evidence threshold. A clinical decision support system should never fire an alert based on a Level 4 case report. That's how you get alert fatigue and clinician distrust.

### Source Integration: The Real Challenge

Building this graph means integrating multiple authoritative sources, each with its own schema, identifiers, and update cadence:

**PharmGKB** provides curated gene-drug-disease associations with clinical annotations and evidence levels. It's the gold standard for pharmacogenomic relationships. Updated continuously.

**ClinVar** provides variant classifications (pathogenic, benign, VUS) submitted by clinical labs and research groups. Critical for determining whether a specific variant is actionable. Updated weekly.

**DrugBank** provides comprehensive drug data including targets, enzymes, transporters, and carriers. Gives you the "which genes does this drug interact with" relationships. Updated quarterly.

**CPIC (Clinical Pharmacogenetics Implementation Consortium)** publishes evidence-based guidelines for specific gene-drug pairs. These are the highest-confidence relationships in your graph. Updated as new guidelines are published (roughly quarterly).

**OMIM (Online Mendelian Inheritance in Man)** provides disease-gene associations, particularly for monogenic conditions. Essential for the disease-to-gene edges.

**FDA Pharmacogenomic Biomarker Table** lists drugs with pharmacogenomic information in their labeling. This is the regulatory ground truth for which gene-drug pairs have FDA recognition.

Each source uses different identifiers. PharmGKB uses its own accession numbers. ClinVar uses variation IDs. DrugBank uses its own IDs. You need a robust entity resolution layer that maps across identifier systems: gene symbols to Entrez IDs to Ensembl IDs, drug names to RxNorm CUIs to ATC codes, variants to rsIDs to HGVS notation. This mapping layer is not trivial. It's where most integration projects spend the majority of their engineering time.

### Why This Is Harder Than It Looks

**Rapidly evolving knowledge.** Pharmacogenomics is a young field. New gene-drug associations are discovered regularly. Evidence levels change as studies accumulate. A variant classified as "uncertain significance" today might be reclassified as "pathogenic" next month. Your graph needs to handle versioning and temporal validity. A query should be answerable as "what did we know as of date X?" for audit and reproducibility purposes.

**Population-specific allele frequencies.** The same variant has different clinical relevance in different populations. CYP2D6*4 is common in European populations (allele frequency ~20-25%) but rare in East Asian populations. CYP2C19*2 shows the opposite pattern. Your graph needs population-stratified frequency data to support appropriate clinical interpretation. A "rare variant" alert that fires for a variant present in 25% of the patient's ancestral population is worse than useless.

**Diplotype-to-phenotype translation.** Pharmacogenomic phenotypes (poor/intermediate/normal/ultra-rapid metabolizer) are determined by the combination of two alleles (the diplotype), not individual variants in isolation. CYP2D6*1/*4 is an intermediate metabolizer. CYP2D6*4/*4 is a poor metabolizer. Your graph needs to represent this diplotype-to-phenotype mapping, which is gene-specific and sometimes complex (CYP2D6 alone has over 100 defined star alleles and gene deletions/duplications that affect copy number).

**Drug-drug-gene interactions.** A patient might be a CYP2D6 normal metabolizer genetically, but if they're also taking fluoxetine (a strong CYP2D6 inhibitor), their phenotype is effectively "poor metabolizer" due to drug-induced enzyme inhibition. These phenoconversion scenarios require your graph to model not just genetic relationships but also drug-enzyme inhibition/induction relationships. The clinical phenotype is the combination of genotype and concomitant medications.

**Conflicting evidence.** Different sources sometimes disagree. One study finds a significant gene-drug association; another fails to replicate it. ClinVar submissions from different labs may classify the same variant differently. Your graph needs to represent these conflicts transparently rather than silently picking a winner. Clinicians need to see the evidence landscape, not a false consensus.

### The General Architecture Pattern

```
[Source Databases] → [ETL / Integration] → [Entity Resolution] → [Knowledge Graph]
                                                                        ↓
[Patient Genomic Data] → [Variant Annotation] → [Query Engine] ← [Evidence Filtering]
                                                        ↓
                                              [Clinical Recommendations]
                                                        ↓
                                              [CDS Integration / API]
```

**Source Databases:** PharmGKB, ClinVar, DrugBank, CPIC, OMIM, FDA tables. Each feeds relationships and entities into the graph through source-specific ETL pipelines.

**Entity Resolution:** Maps identifiers across sources. Ensures that "CYP2D6" in PharmGKB, "1565" in Entrez Gene, and "ENSG00000100197" in Ensembl all resolve to the same node.

**Knowledge Graph:** The unified, evidence-graded graph of disease-gene-drug relationships. Versioned, auditable, queryable.

**Patient Genomic Data:** The patient's sequencing or genotyping results. Variants are annotated against the graph to determine which relationships are relevant.

**Query Engine:** Traverses the graph given a patient's variants and medications to identify actionable pharmacogenomic findings. Filters by evidence level, population frequency, and clinical context.

**CDS Integration:** Delivers findings to clinical decision support systems, EHR alerts, or pharmacist review queues.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.07-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you when you build this:

**The entity resolution is 60% of the work.** You'll think the hard part is the graph queries or the clinical logic. It's not. It's getting "tamoxifen" from PharmGKB, "DB00675" from DrugBank, and "RxNorm:10324" from your EHR to all point to the same node. Every source has its own identifier system, its own naming conventions, and its own version of "the same thing." You'll spend more time on mapping tables than on graph algorithms.

**Evidence levels are political, not just scientific.** Different organizations classify the same evidence differently. PharmGKB might rate something as "2A" while CPIC hasn't issued a guideline for it yet. The FDA might have it in labeling while CPIC calls it "optional." Your system needs a clear policy on which authority wins, and that policy will be debated by your clinical governance committee for months.

**CYP2D6 alone will make you question your career choices.** This single gene has over 100 defined star alleles, gene deletions, gene duplications, tandem arrangements, and hybrid alleles. The diplotype-to-phenotype translation is not a simple lookup table. It involves activity scores, copy number considerations, and edge cases that even experts disagree on. If your system handles CYP2D6 correctly, everything else is comparatively straightforward.

**Clinicians don't trust black boxes.** If your system says "use alternative therapy" but can't show the reasoning chain (this variant, in this gene, causes this phenotype, which affects this drug, per this guideline, at this evidence level), clinicians will ignore it. Explainability isn't a nice-to-have. It's a requirement for adoption. Every recommendation needs a traceable path through the graph.

**The "last mile" to the EHR is the hardest mile.** You can build a beautiful knowledge graph with perfect evidence grading. But if the alert fires in the EHR at the wrong time, in the wrong format, or without enough context for the clinician to act, it's useless. Integration with clinical workflow (when to alert, who to alert, what action to suggest, how to document the decision) is where most pharmacogenomics implementations stall.

---

## Related Recipes

- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Shares the drug entity model and can provide the concomitant medication interaction data needed for phenoconversion detection.
- **Recipe 13.8 (Medical Concept Normalization and Mapping):** The entity resolution challenge here is a specific instance of the broader concept normalization problem covered in 13.8.
- **Recipe 13.9 (Literature-Derived Knowledge Graph):** New gene-drug associations often emerge from literature before they appear in curated databases. Recipe 13.9's extraction pipeline can feed emerging evidence into this graph.
- **Recipe 5.5 (Cross-Facility Patient Matching):** Pharmacogenomic results from external labs need to be matched to the correct patient record before they can be used for graph queries.
- **Recipe 4.8 (Treatment Response Prediction):** Pharmacogenomic data is one input to broader treatment response models that also consider clinical and demographic factors.

---

## Tags

`knowledge-graph` `pharmacogenomics` `precision-medicine` `neptune` `gene-drug-interactions` `clinical-decision-support` `cpic` `pharmgkb` `entity-resolution` `evidence-grading`

---

**Navigation:** [← 13.6: Care Gap Reasoning Engine](chapter13.06-care-gap-reasoning-engine) | [Chapter 13 Index](chapter13-preface) | [13.8: Medical Concept Normalization →](chapter13.08-medical-concept-normalization-mapping)
