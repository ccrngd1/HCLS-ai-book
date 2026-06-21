# Open TODOs: Recipe 6.4: Disease Severity Stratification

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter06.04-architecture.md`

- **L402** — TODO (TechWriter): Expert review ARCH-1 (MEDIUM). Add brief note on failure handling: Step Functions orchestration with per-step error handling, DLQ (SQS) for patients that fail any step, and retry logic for transient failures. Silent pipeline failures mean patients miss tier assignments and potentially miss interventions.
- **L404** — TODO (TechWriter): Expert review SEC-4 (MEDIUM). Add recommendation for an append-only audit log of tier assignments (patient_id, previous_tier, new_tier, run_date, model_version, pipeline_execution_id) stored in S3 (immutable, versioned bucket) for clinical governance review when tier changes trigger care plan modifications.
- **L408** — TODO (TechWriter): Expert review ARCH-2 (MEDIUM). Add brief orchestration sketch: EventBridge cron trigger + Step Functions workflow that verifies source data freshness, runs pipeline, compares new vs previous assignments, emits tier-change events to SNS, and updates a CloudWatch metric for stale assignments.
- **L416** — TODO (TechWriter): Expert review ARCH-4 (MEDIUM). Add note on SageMaker Feature Store for versioning and sharing the patient feature matrix across models. Each run should record the feature set version (hash of FEATURE_SET config) alongside tier assignments for reproducibility and audit.
