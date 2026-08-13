# Recipe 13.8: Medical Concept Normalization and Mapping

**Effort:** 5 of 5

---


<!-- phi-callout -->
> **Before you build this, settle the data-governance questions.** This recipe moves protected health information (PHI) through a hosted model or trains on historical patient data, or both. See "Before You Send Protected Health Information Anywhere" at the front of this book for the vendor and secondary-use questions to put to your own privacy, security, and legal or compliance teams before any of this reaches a patient.
## The Problem

Here's a scenario that plays out every single day in healthcare data integration. A hospital system acquires a physician practice. The practice has been coding diagnoses in ICD-10-CM. The hospital's analytics platform uses SNOMED CT for clinical decision support (CDS). The quality reporting system needs Healthcare Effectiveness Data and Information Set (HEDIS) value sets that reference both. The pharmacy system speaks RxNorm. The lab system uses Logical Observation Identifiers Names and Codes (LOINC). And someone in the C-suite wants a unified patient dashboard that pulls from all of them.

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

**Current Procedural Terminology (CPT)**. Procedure codes for outpatient billing. Maintained by the AMA. Proprietary (you pay for a license).

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

The alternative to a graph is a relational database with a stack of join tables. It works for simple lookups, but the moment you need multi-hop traversals, hierarchy navigation, or transitive reasoning, the SQL gets ugly fast and the performance degrades. Graphs are the natural data structure for this problem.

### The UMLS: Your Starting Point

The Unified Medical Language System (UMLS), maintained by the National Library of Medicine, is the most comprehensive source of terminology mappings in healthcare. It integrates over 200 source vocabularies and provides:

**Concept Unique Identifiers (CUIs).** Each distinct clinical meaning gets a CUI. Multiple terms from multiple vocabularies that mean the same thing share a CUI. This is the normalization layer: map any term to its CUI, and you've normalized it.

**Relationships.** The UMLS Metathesaurus contains millions of relationships between concepts: synonymy, hierarchy, association, and more.

**Semantic types.** Each concept is assigned one or more semantic types (Disease or Syndrome, Pharmacologic Substance, Laboratory Procedure, etc.) that enable category-level reasoning.

The UMLS is not perfect. Its mappings are algorithmically generated and human-reviewed, but coverage is uneven. Some terminology pairs have excellent mappings (SNOMED to ICD-10 via the NLM's map). Others have sparse or outdated links. You'll need to supplement UMLS with custom mappings for your specific use cases.

### The General Architecture Pattern

At a conceptual level, a concept normalization system has these components:

```text
[Terminology Sources] → [Graph Ingestion] → [Knowledge Graph Store] → [Normalization API] → [Consumers]
                                                      ↑
                                            [Curation Interface]
```

**Terminology Sources.** The raw vocabulary files: UMLS releases, SNOMED RF2 files, ICD-10 code tables, LOINC downloads, RxNorm RRF files. Each has its own format and release schedule.

**Graph Ingestion.** Extract, transform, and load (ETL) pipelines that parse terminology files, extract concepts and relationships, and load them into the graph. This runs on each terminology release (monthly for RxNorm, quarterly for SNOMED, annually for ICD-10).

**Knowledge Graph Store.** A graph database holding all concepts as nodes and all relationships (intra-terminology hierarchies, cross-terminology mappings) as edges. Must support efficient traversal, pattern matching, and temporal queries.

**Normalization API.** The interface that consuming systems call. Given a concept (code + terminology + version), return the canonical representation and all known mappings. Must be fast (sub-100ms for point lookups) and support batch operations.

**Curation Interface.** A tool for terminologists to review, approve, and create custom mappings. The UMLS gets you 80% of the way. The last 20% requires human expertise specific to your organization's use cases.

**Consumers.** Analytics pipelines, CDS engines, quality reporting systems, research platforms. Each has different access patterns: some need point lookups, some need batch translations, some need hierarchy traversals.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.08-architecture). The Python example is linked from there.

## Related Recipes

- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Provides the hierarchy traversal foundation that value set expansion in this recipe builds upon
- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Uses RxNorm normalization from this recipe to identify drugs regardless of how they're coded in source systems
- **Recipe 13.6 (Care Gap Reasoning Engine):** Depends on normalized concepts to match patient conditions against guideline criteria
- **Recipe 8.4 (Medication Extraction and Normalization):** natural language processing (NLP) pipeline that feeds extracted concepts into this normalization service
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Uses cross-terminology mappings to join claims data (ICD-10) with clinical data (SNOMED)

---

## Tags

`knowledge-graph` · `structured-extraction` · `icd-10` · `interoperability` · `loinc` · `rxnorm` · `snomed` · `hipaa` · `neptune`
