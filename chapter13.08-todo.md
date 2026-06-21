# Open TODOs: Recipe 13.8: Medical Concept Normalization and Mapping

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter13.08-architecture.md`

- **L58** — TODO (TechWriter): Expert review A-4 (MEDIUM). Recommend db.r5.xlarge (32GB) as minimum for full UMLS deployment, plus a read replica for query isolation during bulk loads. Route API queries to the read replica; route ingestion writes to the primary. Update cost estimate to ~$1,400/month for primary + replica.
- **L60** — TODO (TechWriter): Expert review A-5 (MEDIUM). Add a fallback strategy for Neptune unavailability: if Neptune is unreachable, return cached results with a "stale: true" flag and "status: service_degraded" for cache misses. Mention Neptune multi-AZ deployment as the primary availability mechanism.
- **L380** — TODO (TechWriter): Expert review A-1 (HIGH). Add a Step 7 pseudocode block for cache invalidation during terminology updates. After Neptune bulk load completes, compute the set of changed concept codes from the terminology delta and selectively delete corresponding Redis cache keys. For large deltas (annual ICD-10 update), flush the entire cache or implement a cache warming step for top-N queried concepts.
- **L449** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add this section covering gaps a production deployment must close.
