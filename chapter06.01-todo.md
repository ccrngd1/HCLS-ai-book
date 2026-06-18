# Open TODOs — Recipe 6.1: Geographic Patient Clustering ⭐

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter06.01-geographic-patient-clustering.md`

- **L109** — TODO (TechWriter): Expert review ARCH-2 (MEDIUM). Consider expanding the incremental processing paragraph above into a more detailed architectural pattern showing how to identify new/changed addresses and merge incremental geocoding results with existing data.
- **L120** — TODO (TechWriter): Main recipe is missing Tags and Navigation footer sections per RECIPE-GUIDE. Tags are currently only on the architecture companion. Add them here.

## architecture — `chapter06.01-architecture.md`

- **L17** — TODO (TechWriter): Expert review ARCH-1 (MEDIUM). Add note recommending Step Functions Map state for orchestrating geocoding batches over 50K addresses to avoid Lambda timeout risk.
- **L267** — TODO (TechWriter): Expert review SEC-3 (MEDIUM). Add S3 lifecycle policy recommendation: retain current and previous snapshot, expire older snapshots after 6-12 months. Each snapshot contains PHI; minimizing retained copies reduces exposure surface.
- **L343** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add one covering gaps like lack of automated parameter tuning, missing drive-time validation, no CI/CD pipeline, and absence of data drift monitoring.
