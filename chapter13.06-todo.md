# Open TODOs — Recipe 13.6: Care Gap Reasoning Engine

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter13.06-care-gap-reasoning-engine.md`

- **L114** — TODO (TechWriter): Add Tags section and navigation footer per RECIPE-GUIDE.md.

## architecture — `chapter13.06-architecture.md`

- **L11** — TODO (TechWriter): Expert review A1 (CRITICAL). Neptune does NOT natively support OWL reasoning/inference. The claim below that "the query engine handles the inference automatically" is factually incorrect. Neptune stores RDF/OWL data and queries it with SPARQL, but hierarchy traversal requires explicit SPARQL property paths (e.g., rdfs:subClassOf*) or pre-materialized inferred triples. Rewrite this section to use SPARQL property paths for hierarchy traversal, or integrate a third-party reasoner (e.g., RDFox). Remove all claims of "native" OWL inference. See AWS blog "Use semantic reasoning to infer new facts from your RDF graph by integrating RDFox with Amazon Neptune" (Feb 2023) for the correct pattern.
- **L410** — TODO (TechWriter): Expert review A3 (MEDIUM). The 45-minute batch estimate doesn't match the per-patient latency math (100 Lambdas × 500 patients × 200-500ms = 2-4 minutes, not 45). Either show the math behind the 45-minute estimate (what's the bottleneck: Step Functions orchestration overhead? Neptune connection pooling?) or correct it. Also add Neptune connection management guidance: reuse connections across invocations, set neptune_query_timeout, monitor SparqlRequestsPerSec.
- **L423** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section per RECIPE-GUIDE.md, between Expected Results and Variations.
- **L449** — TODO (TechWriter): Verify this GitHub URL exists before publication.
