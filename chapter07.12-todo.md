# Open TODOs: Recipe 7.12: Cohort Matching and Case-Based Reasoning for Novel Claims

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.12-claim-cohort-matching.md`

- **L148** — TODO (TechWriter): Expert review SEC-3 (MEDIUM). Add access control guidance for the case retrieval API: provider portals should only surface cases from the same provider organization (or de-identified cases); internal billing worklists can see broader comparisons. Implement row-level filtering in the OpenSearch query by provider_org_id for provider-facing use cases, or strip identifiable metadata for cross-organization comparisons.
- **L152** — TODO (TechWriter): Expert review ARCH-3 (MEDIUM). Add operational detail: re-cluster monthly (or when denial volume exceeds threshold since last run). Store cluster labels with a cluster_version field in DynamoDB. Downstream routing queries by current cluster version. Alert when cluster composition shifts significantly between runs.

## architecture — `chapter07.12-architecture.md`

- **L322** — TODO (TechWriter): Expert review ARCH-2 (HIGH). Add error handling pattern for hybrid decision engine: retry with exponential backoff for transient failures from OpenSearch/SageMaker, graceful degradation (fall back to primary-only scoring if similarity layer is unavailable), SQS dead-letter queue for claims that fail all retries, and CloudWatch alarm on DLQ depth.
- **L372** — TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" H2 section between Expected Results and Variations. Add a brief section covering: no automated embedding-drift detection, no circuit-breaker for OpenSearch outages, no A/B framework for kNN-vs-primary model allocation, no automated threshold recalibration.
- **L408** — TODO: Verify AWS sample repos for OpenSearch k-NN healthcare patterns
