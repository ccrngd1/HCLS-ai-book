# Recipe 13.3: ICD/CPT Hierarchy Navigation

**Complexity:** Simple-Medium · **Phase:** Foundation · **Estimated Cost:** ~$0.01 per query

---

## The Problem

A coder is staring at a clinical note that says "patient presents with chest pain, ruled out MI, final diagnosis: costochondritis." They need to assign the right ICD-10 code. They know it's somewhere under musculoskeletal, probably in the M94 range, but is it M94.0? M94.1? And wait, is costochondritis actually Tietze syndrome or is that different? They open the ICD-10 lookup tool, type "costochondritis," get three results, and now they need to understand how those codes relate to each other in the hierarchy. Is one more specific than another? Does the parent code capture the same concept at a less granular level?

This is the daily reality of medical coding. ICD-10-CM alone has over 72,000 codes organized in a strict hierarchy: chapters, blocks, categories, subcategories. CPT has over 10,000 procedure codes with their own hierarchical structure. And the two systems cross-reference each other constantly: a diagnosis code justifies a procedure code, and payers maintain complex rules about which combinations are valid.

The problem gets worse when you zoom out from individual coding to analytics. A population health team wants to know "how many patients have any form of diabetes?" That's not one code. That's an entire subtree: E08 through E13, each with dozens of children. Querying a flat code table means knowing every leaf code in advance. Miss one and your cohort is wrong.

Then there's the version problem. ICD-10 updates annually. CMS publishes new codes, retires old ones, and reclassifies existing ones every October 1st. CPT updates quarterly. Your system needs to answer questions like "what was the parent of this code in FY2024?" and "which codes were added under this category in the latest release?" A flat lookup table can't do this without rebuilding the entire thing every cycle.

Knowledge graphs solve this by representing codes as nodes and their relationships (parent-child, cross-walks, supersedes, groups-with) as edges. Instead of searching a flat list, you traverse a hierarchy. Instead of maintaining cross-reference tables, you query relationship paths. Instead of rebuilding for version changes, you add new nodes and edges while preserving history.

---

## The Technology: Hierarchical Code Systems as Graphs

### Why Medical Code Systems Are Naturally Graphs

ICD-10-CM has a tree structure baked into its design. The code itself encodes the hierarchy:

```text
E11       → Type 2 diabetes mellitus (category)
E11.6     → Type 2 diabetes with complications (subcategory)
E11.65    → Type 2 diabetes with hyperglycemia (further specificity)
E11.65x1  → ... with subsequent encounter (extension)
```

Each level adds specificity. The parent-child relationship is implicit in the code structure. But here's what makes it interesting: the relationships between codes go far beyond simple parent-child. ICD-10 codes have "excludes1" relationships (mutually exclusive, never code together), "excludes2" relationships (not included here, but can be coded together if documented), "includes" notes, and "code first" / "use additional code" instructions that create directed edges between codes in completely different chapters.

CPT has its own hierarchy: sections (Surgery, Radiology, Medicine), subsections, headings, and individual codes. But CPT also has modifier relationships, add-on code dependencies (codes that can only be reported with a primary code), and bundling rules (multiple codes that collapse into one for billing purposes).

The cross-walk between ICD and CPT is where it gets genuinely complex. A procedure code is only payable when paired with a diagnosis code that justifies medical necessity. These pairings aren't one-to-one. A single CPT code might be justified by dozens of ICD codes. A single ICD code might justify dozens of procedures. And payers maintain their own proprietary variations on these rules.

This is a graph problem. Nodes are codes. Edges are typed relationships: `IS_CHILD_OF`, `EXCLUDES`, `CROSS_WALKS_TO`, `BUNDLES_WITH`, `REQUIRES_MODIFIER`, `SUPERSEDED_BY`. Once you model it this way, questions that were painful SQL queries become simple graph traversals.

### Graph Databases vs. Relational Approaches

You can model hierarchies in a relational database. People do it all the time with adjacency lists, nested sets, or materialized path columns. For simple parent-child lookups, this works fine. But the moment you need multi-hop traversals ("find all codes within 3 levels of this code that cross-walk to any CPT code in the 99200 range"), relational queries become recursive CTEs that are hard to write, hard to optimize, and hard to maintain.

Graph databases store relationships as first-class citizens. A traversal query like "start at E11, walk all children to depth 4, filter by those with a CROSS_WALKS_TO edge to any node in the CPT Surgery section" is a natural expression in a graph query language. The database engine optimizes for exactly this access pattern.

The main graph database paradigms:

**Property graphs** (Neo4j, Amazon Neptune, TinkerPop-compatible systems): Nodes and edges both carry properties (key-value pairs). Edges are typed and directed. Query languages include Cypher (Neo4j), Gremlin (TinkerPop), and openCypher. This is the most common model for healthcare ontology work because the property bags on edges let you attach metadata like "effective date," "source authority," and "confidence level."

**RDF triple stores** (Amazon Neptune in RDF mode, Blazegraph, Stardog): Everything is a subject-predicate-object triple. Query language is SPARQL. This model aligns naturally with formal ontologies (SNOMED-CT is distributed as RDF). If you're integrating with existing biomedical ontologies, RDF might be the path of least resistance. The tradeoff is that SPARQL is more verbose than Cypher for simple traversals.

**Hybrid approaches**: Some teams use a relational database for the flat code lookups (fast, simple, well-understood) and a graph database for the relationship queries (traversals, path-finding, cross-walks). This avoids forcing simple lookups through a graph engine while still getting graph benefits for complex queries.

### The Version Problem

Medical code systems change. ICD-10-CM updates annually (effective October 1). CPT updates annually with quarterly corrections. When a code is retired, you can't just delete it. Historical claims reference it. Analytics over time periods spanning a version boundary need to understand that code X in 2023 became code Y in 2024.

In a graph model, versioning becomes edge metadata. A `SUPERSEDED_BY` edge connects the old code to the new one, with an effective date. A `VALID_IN` edge connects a code to a fiscal year node. Queries can be scoped to a specific version ("show me the E11 subtree as of FY2024") or span versions ("show me all codes that have ever mapped to this concept").

This is dramatically cleaner than the relational alternative, which typically involves either maintaining separate tables per version (explosion of tables) or adding valid_from/valid_to columns to every row (complex WHERE clauses on every query).

### Traversal Patterns That Matter

The queries you'll actually run against a medical code hierarchy graph fall into a few categories:

**Ancestor/descendant queries.** "Give me all codes under E11" (for cohort building). "What's the chapter-level parent of M94.0?" (for reporting rollups). These are depth-first or breadth-first traversals along `IS_CHILD_OF` edges.

**Sibling queries.** "What other codes share the same parent as this one?" Useful for suggesting alternative codes during coding. "You picked E11.65, but did you consider E11.64 or E11.69?"

**Cross-walk queries.** "Which CPT codes are justified by this ICD code?" or "Which diagnoses support medical necessity for this procedure?" These traverse `CROSS_WALKS_TO` edges, potentially filtered by payer-specific rules.

**Exclusion queries.** "Can I code E11.65 and E13.65 on the same claim?" Check for `EXCLUDES1` edges between the two codes or their ancestors.

**Path queries.** "What's the shortest path between these two codes in the hierarchy?" Useful for measuring semantic distance between diagnoses.

**Temporal queries.** "What changed in the E11 subtree between FY2024 and FY2025?" Compare edges with different version metadata.

### General Architecture Pattern

```text
[Code Source Files] → [Parser/Loader] → [Graph Database] → [Query API] → [Consumers]
     (CMS, AMA)         (ETL)            (Nodes + Edges)    (REST/GraphQL)   (Coding tools,
                                                                               Analytics,
                                                                               Rules engines)
```

**Source ingestion.** CMS publishes ICD-10-CM as downloadable flat files (tabular format with parent-child relationships encoded positionally). AMA publishes CPT in various formats. Cross-walk files come from CMS (Medicare) and individual payers. Your ETL pipeline parses these into nodes and edges.

**Graph storage.** Codes become nodes with properties (description, effective date, status). Relationships become typed edges with properties (relationship type, source authority, version). The graph accumulates over time rather than being rebuilt.

**Query layer.** A service exposes traversal operations as API endpoints. Consumers don't write raw graph queries; they call endpoints like `/codes/{code}/ancestors`, `/codes/{code}/crosswalks?target_system=CPT`, `/codes/{code}/children?depth=3`.

**Consumers.** Coding assistance tools, analytics platforms, rules engines, and reporting systems all query the same graph through the API. Each gets the traversal depth and relationship types relevant to their use case.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.03-architecture). The Python example is linked from there.

## The Honest Take

The graph model is genuinely elegant for this problem. Once you have the hierarchy loaded, questions that used to require a DBA writing recursive SQL become trivial API calls. The first time a population health analyst says "give me all diabetes codes" and gets a complete, correct answer in 20ms instead of maintaining a spreadsheet of codes they hope is complete, you'll feel good about the investment.

But here's what will surprise you: the hard part isn't the graph database. It's the ETL. CMS publishes ICD-10-CM in a format that was designed for humans reading printed books, not for machines building graphs. The "order file" encodes hierarchy through positional formatting. The annotation files (excludes, includes, code-first notes) are in a separate format with their own parsing challenges. You'll spend more time writing robust parsers for these source files than you will on the graph queries.

The CPT side is worse because it requires an AMA license, the data formats are proprietary, and the cross-walk files from different payers arrive in different formats. Budget significant time for the ingestion pipeline.

The version transition is the other gotcha. Your first annual update will reveal edge cases in your SUPERSEDED_BY logic. Codes don't always map one-to-one when they're retired. Sometimes one code splits into three. Sometimes three codes merge into one. The GEMs (General Equivalence Mappings) files handle this, but they're approximate mappings, not exact equivalences. Your analytics team will need to understand that "E11.65 in FY2024" and "E11.65 in FY2025" might not mean exactly the same clinical concept if the code definition was refined.

One more thing: Neptune's openCypher support is good but not complete. If you're coming from Neo4j, some Cypher features you're used to (like APOC procedures) don't exist. Variable-length path bounds must be literal integers, not parameters. Test your query patterns against Neptune specifically during development, not just against a local Neo4j instance.

---

## Related Recipes

- **Recipe 13.1 (Drug Formulary Navigation):** Same graph database pattern applied to drug hierarchies; shares the Neptune infrastructure
- **Recipe 13.2 (Provider Directory as Knowledge Graph):** Demonstrates the property graph model for a different healthcare entity type
- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Extends the graph with clinical evidence edges and severity scoring
- **Recipe 13.8 (Medical Concept Normalization and Mapping):** Builds the cross-terminology mapping layer that this recipe's cross-walks are a subset of
- **Recipe 8.3 (ICD-10 Code Suggestion):** Consumes this recipe's hierarchy for code suggestion context

---

## Tags

`knowledge-graph` · `neptune` · `icd-10` · `cpt` · `medical-coding` · `hierarchy` · `ontology` · `opencypher` · `graph-database` · `cross-walk` · `coding-assistance` · `hipaa`

---

*← [Recipe 13.2: Provider Directory as Knowledge Graph](chapter13.02-provider-directory-knowledge-graph) · [Chapter 13 Index](chapter13-preface) · [Next: Recipe 13.4 - Drug-Drug Interaction Knowledge Base →](chapter13.04-drug-drug-interaction-knowledge-base)*
