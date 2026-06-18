# Recipe 13.2: Provider Directory as Knowledge Graph

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.10 per 1,000 queries

---

## The Problem

Every health plan, hospital system, and clinic network maintains a provider directory. On the surface, it sounds simple: a list of doctors, their specialties, their locations, whether they're accepting new patients. In practice, it's one of the most frustrating data problems in healthcare.

A patient calls their insurance company and asks: "I need a cardiologist near downtown who accepts my plan, is in-network, and ideally has privileges at the hospital where my PCP practices." The customer service rep types "cardiologist" into a flat search tool, gets 200 results sorted alphabetically, and starts reading them off. The patient sighs. The rep sighs. Nobody is having a good time.

The underlying problem is that provider directories are stored as flat tables. Rows of providers with columns for specialty, address, phone, network status. But the relationships between providers, facilities, specialties, insurance products, and geographic areas are inherently a graph. A provider practices at multiple locations. Each location belongs to a facility. That facility is in-network for certain products but not others. The provider has admitting privileges at a hospital across town. They share a practice group with three other physicians who cover for each other. They speak Spanish and Mandarin. They completed a fellowship in interventional cardiology, which is a subspecialty of cardiology, which is a specialty within internal medicine.

None of that relational richness survives in a flat table. You can't ask "find me a provider who shares a practice group with my current PCP and also has privileges at Memorial Hospital" against a relational database without writing a horrifying multi-join query that the DBA will reject on sight. And even if you write it, the query planner will weep.

This is exactly the kind of problem knowledge graphs were built to solve. When your data is fundamentally about entities and the relationships between them, and your queries are about traversing those relationships, a graph database turns a nightmare into a straightforward traversal.

---

## The Technology: Knowledge Graphs for Connected Data

### What Is a Knowledge Graph?

A knowledge graph is a data structure that represents information as entities (nodes) connected by typed relationships (edges). Each node has properties (attributes), and each edge has a type that describes the nature of the connection. The combination of two nodes and the edge between them is called a triple: subject, predicate, object. "Dr. Smith" (subject) "practices at" (predicate) "Downtown Clinic" (object).

The power of a knowledge graph comes from traversal. Instead of joining tables, you walk along edges. "Find all providers who practice at facilities that are in-network for Plan X and are within 10 miles of this ZIP code" becomes a path traversal: start at the plan node, follow the in-network edges to facilities, filter by geography, then follow the practices-at edges to providers. Each hop is cheap. The query reads like the question you're actually asking.

### Why Graphs Beat Tables for Provider Data

Relational databases handle provider directories adequately when queries are simple: "give me all cardiologists in ZIP 40202." But the moment you need multi-hop reasoning, relational models struggle.

Consider this query: "Find a female endocrinologist within 15 miles who accepts BlueCross PPO, has privileges at University Hospital, speaks Spanish, and is accepting new patients." In a relational model, that's a five-table join (providers, locations, networks, privileges, languages) with geographic filtering. Performance degrades as the dataset grows, and adding new relationship types means schema migrations.

In a graph, each of those constraints is a traversal filter. You start at the plan node, walk to in-network providers, filter by specialty, filter by gender, check the accepting-patients flag, verify hospital privileges via a single edge hop, and confirm language. No joins. No schema changes when you add a new relationship type (say, "trained by" or "covers for"). You just add edges.

The other advantage is schema flexibility. Provider directories change constantly. A new data source adds "telehealth availability" as a relationship. In a relational model, that's an ALTER TABLE or a new junction table. In a graph, it's a new edge type. No migration, no downtime, no breaking existing queries.

### Graph Data Models for Provider Directories

The core entity types in a provider directory graph are straightforward:

- **Provider**: An individual clinician (physician, NP, PA, therapist)
- **Facility/Location**: A physical place where care is delivered
- **Organization**: A practice group, health system, or clinic network
- **Specialty**: A medical specialty or subspecialty (hierarchical)
- **Insurance Product**: A specific plan offered by a payer
- **Network**: A grouping of providers contracted with a payer
- **Geographic Area**: ZIP codes, counties, service areas

The relationships between them carry the real value:

- Provider PRACTICES_AT Location
- Provider HAS_SPECIALTY Specialty
- Provider HAS_PRIVILEGES_AT Facility
- Provider MEMBER_OF Organization
- Provider SPEAKS Language
- Provider ACCEPTS_PRODUCT InsuranceProduct
- Location BELONGS_TO Organization
- Location IN_NETWORK_FOR Network
- Specialty IS_SUBSPECIALTY_OF Specialty
- Network OFFERED_BY Payer

Properties on nodes carry the attributes: accepting-new-patients status, gender, years of experience, board certifications, appointment availability windows. Properties on edges can carry temporal information: "in-network effective 2025-01-01 through 2025-12-31."

### Ontology and Taxonomy

The specialty hierarchy deserves special attention. Medical specialties form a tree (actually a directed acyclic graph, since some subspecialties relate to multiple parent specialties). "Interventional Cardiology" is a subspecialty of "Cardiology," which is a specialty within "Internal Medicine." When a patient searches for "heart doctor," you need to resolve that to the appropriate level of the specialty hierarchy and include all subspecialties beneath it.

This is where ontology comes in. An ontology defines the formal relationships between concepts in a domain. For provider directories, the relevant ontologies include:

- **NUCC taxonomy**: The National Uniform Claim Committee maintains the standard taxonomy of healthcare provider types and specialties. It's hierarchical and widely used in claims processing.
- **NPI taxonomy codes**: Each NPI registration includes taxonomy codes from the NUCC set.
- **Custom organizational hierarchies**: Health systems often have their own groupings that don't map cleanly to NUCC.

Encoding these taxonomies as part of your graph (specialty nodes connected by IS_SUBSPECIALTY_OF edges) enables hierarchical queries naturally. "Find all providers in any cardiology subspecialty" becomes "start at the Cardiology node, traverse all IS_SUBSPECIALTY_OF edges downward, collect all providers connected to any node in that subtree."

### Query Patterns

The most common query patterns for a provider directory graph:

1. **Filtered search**: Start with constraints (specialty, geography, network), traverse to matching providers
2. **Referral pathways**: Given a PCP, find specialists who share a facility or organization
3. **Coverage verification**: Given a provider and a patient's plan, verify in-network status by traversing the network edges
4. **Availability matching**: Combine graph traversal with real-time availability data
5. **Similar provider discovery**: Given a provider a patient likes, find others with similar attributes and relationships

Each of these is a natural graph traversal. The query language (Gremlin, Cypher, SPARQL, or a managed query API) expresses these as path patterns rather than set operations.

### What Makes This Hard

**Data freshness.** Provider directories are notoriously inaccurate. The CMS No Surprises Act requires directories to be updated within 2 business days of a change, but reality lags. Providers change locations, drop out of networks, stop accepting patients, retire. Your graph is only as good as your update pipeline. Stale data in a graph is worse than stale data in a table, because traversals that hit stale edges produce confidently wrong answers.

**Source reconciliation.** Provider data comes from multiple sources: credentialing systems, payer rosters, NPI registry, state licensing boards, facility privilege lists, the providers themselves. These sources disagree. Dr. Smith's credentialing record says she's at Location A. The payer roster says Location B. The NPI registry hasn't been updated in two years. You need a reconciliation strategy, and it's not trivial.

**Geographic reasoning.** "Within 10 miles" requires geospatial computation. Most graph databases support geospatial indexes, but the integration isn't always seamless. You may need to pre-compute geographic relationships (ZIP-to-service-area mappings) and encode them as edges rather than computing distances at query time.

**Scale.** A large health plan's provider directory might have 500,000 providers, 200,000 locations, 50 networks, and millions of edges connecting them. Graph databases handle this scale well, but you need to think about index strategies, query optimization, and caching for hot paths.

---

## General Architecture Pattern

```text
[Source Systems] → [Ingest & Reconcile] → [Graph Database] → [Query API] → [Applications]
```

**Source Systems.** Credentialing databases, payer roster files (often 834/835 EDI or CSV), NPI registry downloads, facility privilege lists, provider self-service portals. Each source provides a partial view of the truth.

**Ingest and Reconcile.** An ETL pipeline that reads from each source, resolves conflicts (which address is current? which network status is authoritative?), and produces a unified set of nodes and edges. This pipeline runs on a schedule (daily for most sources, near-real-time for critical updates like network terminations).

**Graph Database.** The persistent store for nodes, edges, and properties. Must support efficient traversal queries, property filtering, and ideally geospatial indexes. Should handle concurrent reads at high throughput for patient-facing search applications.

**Query API.** A service layer that translates application-level questions ("find me a cardiologist near ZIP 40202 accepting BlueCross PPO") into graph traversal queries. This layer handles query construction, result ranking, pagination, and caching.

**Applications.** Patient-facing search portals, member services tools, referral management systems, care coordination platforms. Each consumes the query API with different access patterns and latency requirements.

The key architectural decision is whether to use the graph as the primary store or as a query-optimized projection of data that lives authoritatively elsewhere. For most healthcare organizations, the graph is a projection: the credentialing system remains the system of record, and the graph is rebuilt or incrementally updated from it. This avoids the "two sources of truth" problem.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.02-architecture). The Python example is linked from there.

## The Honest Take

The graph model is genuinely the right abstraction for provider directories. The moment you try to answer "find me a provider who..." questions with more than two constraints, the graph approach wins decisively over relational joins. The query code reads like the question you're asking, which makes it maintainable and extensible.

The part that will surprise you: the graph database is the easy part. Neptune, Neo4j, or any mature graph DB handles the storage and traversal beautifully. The hard part is the data pipeline. Getting clean, reconciled, current provider data into the graph is 80% of the engineering effort. Provider data is messy, contradictory, and constantly changing. You'll spend more time on the ETL jobs than on the graph queries.

The other surprise: you'll want a full-text search engine alongside your graph database, not instead of it. Patients don't search by NPI or NUCC code. They search by name fragments, partial addresses, and colloquial specialty names ("heart doctor" not "207RC0000X"). A text search engine handles the fuzzy text matching and geospatial filtering; the graph database handles the relationship traversal. The two together are more powerful than either alone.

One more thing: don't underestimate the specialty hierarchy. "Cardiology" means different things to different people. A patient searching for a "heart doctor" might need a general cardiologist, an interventional cardiologist, a cardiac electrophysiologist, or a cardiothoracic surgeon. Getting the taxonomy traversal right (and making it configurable per search context) is worth investing in early.

---

## Related Recipes

- **Recipe 5.2 (Provider NPI Matching):** Covers the entity resolution techniques needed to match providers across source systems during the ingest phase
- **Recipe 13.1 (Drug Formulary Navigation):** Uses similar graph modeling patterns for navigating hierarchical drug data
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Uses taxonomy traversal patterns applicable to the specialty hierarchy
- **Recipe 4.3 (Provider Directory Search Optimization):** Covers the search ranking and personalization layer that sits on top of this graph
- **Recipe 14.3 (Network Adequacy Optimization):** Uses the provider graph as input for network adequacy compliance calculations

---

**Tags:** `knowledge-graph`, `provider-directory`, `graph-database`, `provider-search`, `network-adequacy`, `healthcare-directory`, `ontology`, `taxonomy`
