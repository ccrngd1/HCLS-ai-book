# Open TODOs — Recipe 8.1: Chief Complaint Classification

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter08.01-chief-complaint-classification.md`

- **L62** — TODO (TechWriter): Expert review A2 (HIGH). The 50,000 examples claim earlier in this section and the 1,000-per-category minimum in Prerequisites are inconsistent for a 150-category system. Reconcile: either note that 50K examples across fewer high-frequency categories achieves 85-92% on those categories while long-tail categories underperform, or adjust the total corpus guidance to 100K-200K for full category coverage.

## architecture — `chapter08.01-architecture.md`

- **L66** — TODO (TechWriter): Expert review S1 (MEDIUM). Add SQS queue access control guidance: queue policy restricting sqs:ReceiveMessage to the review application's IAM role only, message retention period set to match review SLA (e.g., 24 hours not the default 4 days), and a dead-letter queue for messages exceeding max receive count. PHI in an unscoped queue is a compliance gap.
- **L67** — TODO (TechWriter): Expert review S2 (MEDIUM). Specify resource-scoped IAM statements: dynamodb:GetItem on abbreviation-map table ARN only, dynamodb:GetItem+PutItem on classification-results table ARN only. Separate sensitivity levels (config vs. PHI).
- **L305** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section here per RECIPE-GUIDE. Cover gaps like error handling, retry logic, input validation, structured logging, multi-language support, and retraining automation.
- **L309** — TODO (TechWriter): Expert review A3 (MEDIUM). Add a "Retraining Pipeline" variation showing: SQS review queue corrections written back to training S3 bucket, scheduled (weekly/monthly) Step Functions workflow triggering Comprehend training, A/B accuracy comparison of new model vs. current, and endpoint update strategy. This is the recipe's key differentiator (feedback loop) but currently has no architectural detail for closing it.
