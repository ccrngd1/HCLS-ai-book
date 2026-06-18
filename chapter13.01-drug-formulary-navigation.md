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

```text
[Ingest Formulary Data] → [Build/Update Graph] → [Query API] → [Prescriber Interface]
```

**Stage 1: Ingest.** Formulary data arrives in structured formats. CMS requires health plans to publish formulary files in a standardized format (the CMS formulary file layout for Part D plans). Commercial plans often use similar structures. These files contain drug lists, tier assignments, restriction codes, and therapeutic class mappings. You parse these files and transform them into graph-ready triples or property graph statements.

**Stage 2: Build/Update Graph.** Load the parsed data into a graph database. This isn't a one-time operation. Formularies change quarterly (January, April, July, October for most plans), with mid-quarter amendments for new drug approvals, safety withdrawals, or P&T committee decisions. Your pipeline needs to handle incremental updates: add new drugs, change tier assignments, add or remove restrictions, without rebuilding the entire graph.

**Stage 3: Query API.** Expose the graph through a purpose-built API that translates prescriber questions into graph traversals. The API shouldn't expose raw graph query syntax to consumers. Instead, it offers domain-specific endpoints: "find alternatives for drug X under plan Y," "check restrictions for drug X at strength Z under plan Y," "navigate therapeutic class hierarchy from class C." The API handles the traversal logic, applies temporal filters (only return currently effective data), and formats results for the consuming application.

**Stage 4: Prescriber Interface.** The end consumer is typically an EHR integration, a pharmacy system, or a prescriber-facing tool. It calls the API at the point of prescribing, receives structured alternatives and restriction information, and presents it in the clinical workflow. The interface needs to be fast (sub-second response) and contextual (filtered to the patient's specific plan).

The key architectural decision is where intelligence lives. The graph itself is "dumb" storage of relationships. The query API encodes the business logic: what counts as a valid alternative, how to rank alternatives (by tier, then by formulary preference, then by clinical equivalence), when to surface restrictions vs. suppress them. Keep this logic in the API layer, not embedded in the graph structure, so you can evolve it without reloading data.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.01-architecture). The Python example is linked from there.

## The Honest Take

This recipe is one of the cleaner knowledge graph applications because the source data is already structured. You're not doing NLP extraction or entity resolution. The formulary file tells you exactly which drugs are on which tier. The graph just makes it navigable in ways a flat file can't support.

The part that will surprise you: building the graph is maybe 20% of the work. Keeping it current is 80%. Formularies change quarterly, but the real headache is mid-quarter amendments. A new drug gets FDA approval and the P&T committee adds it in week 6 of the quarter. A safety signal causes a drug to be removed. A manufacturer rebate deal changes tier placement for a single drug. Each of these is a targeted graph update that needs to happen within days, not wait for the next quarterly reload.

The therapeutic alternative relationships are where the real value lives, and they're also the hardest to get right. The formulary file might list alternatives, but those lists are often incomplete or based on class membership rather than true clinical equivalence. A statin is not always interchangeable with another statin for a specific patient (dose equivalence tables matter, contraindications matter, prior adverse reactions matter). The graph can tell you what's formulary-preferred, but clinical judgment still determines what's appropriate. Make sure your UI communicates "formulary alternatives" not "recommended substitutions."

The cache hit rate makes or breaks your cost model. Managed graph databases are not cheap (see the architecture companion for specific pricing). If 90% of queries hit your cache layer, your effective cost per query is trivial. If your cache hit rate drops (because you have many plans with different formularies, or because you're not normalizing drug identifiers consistently in cache keys), graph query volume spikes and you need a larger instance.

One more thing: the gap between "what the formulary file says" and "what the PBM actually adjudicates" is real and frustrating. I've seen cases where a drug is listed as Tier 2 in the formulary file but consistently adjudicates at Tier 3 due to a system override that nobody documented. Your graph reflects the published formulary, not necessarily the operational reality. Build feedback loops from claims adjudication data to validate your graph against actual tier assignments.

---

## Related Recipes

- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Uses a similar graph structure but models interaction relationships between drugs rather than formulary relationships. The two graphs can share a common drug node layer.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Demonstrates the same hierarchical traversal pattern applied to diagnosis and procedure codes rather than drug classifications.
- **Recipe 13.6 (Care Gap Reasoning Engine):** Consumes formulary data as part of medication adherence gap detection. If a patient isn't filling a prescribed medication, the care gap engine checks whether a formulary barrier (high tier, PA requirement) might be the cause.
- **Recipe 11.5 (Insurance Benefits Navigator):** A conversational interface that could use this recipe's API as its backend for answering patient questions about drug coverage.

---

## Tags

`knowledge-graph` · `neptune` · `formulary` · `pharmacy` · `drug-alternatives` · `opencypher` · `graph-database` · `elasticache` · `simple` · `mvp` · `hipaa`

---

*← [Chapter 13 Index](chapter13-preface) · [Next: Recipe 13.2 - Provider Directory as Knowledge Graph →](chapter13.02-provider-directory-knowledge-graph)*
