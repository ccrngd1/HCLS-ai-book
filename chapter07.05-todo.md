# Open TODOs: Recipe 7.5: 30-Day Readmission Risk

> Auto-extracted 2026-06-18 from inline source comments (3 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.05-30-day-readmission-risk.md`

- **L109** — TODO (TechWriter): Expected Results section lives here but RECIPE-GUIDE places it in the architecture companion. Left in place during split polish; consider relocating in a future pass.

## architecture — `chapter07.05-architecture.md`

- **L17** — TODO (TechWriter): Expert review A3 (MEDIUM). Add dead letter queue guidance: SQS DLQ for failed scoring events, CloudWatch alarm on DLQ depth > 0, daily retry Lambda, and manual review fallback for patients not scored within 24 hours.
- **L101** — TODO (TechWriter): Expert review A2 (MEDIUM). Clarify feature store architecture: for >100 discharges/day, pre-compute historical utilization features nightly via Glue into DynamoDB keyed by patient_id. Scoring workflow queries HealthLake only for current-encounter features + DynamoDB for pre-computed historical features. This hybrid keeps latency under 500ms.
