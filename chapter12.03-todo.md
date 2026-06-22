# Open TODOs: Recipe 12.3: ED Arrival Forecasting ⭐⭐

> Remaining items require human verification (live link checks, pricing confirmation, or benchmark sourcing).

## architecture - `chapter12.03-architecture.md`

- [NEEDS HUMAN] **L15** - N1. Verify the Amazon Forecast deprecation status and confirm the migration guidance link is still live as of the publication date. The prose now notes "verify at publication time" but the specific URL needs a human to check.
- [NEEDS HUMAN] **L85** - V1. Verify SageMaker, Kinesis, and DynamoDB pricing assumptions reflect current rates. AWS pricing changes; confirm against the AWS pricing calculator before publication.
- [NEEDS HUMAN] **L110** - N2. Verify all three reference implementation links are still live and up-to-date (amazon-sagemaker-examples GitHub repo, SageMaker DeepAR docs page, HealthLake docs page).
- [NEEDS HUMAN] **L357** - A1. Accuracy benchmarks (10-18% MAPE at 4h, 15-28% at 24h, 20-35% at 7d) are typical industry figures for ED arrival forecasting on EDs with 2+ years of clean ADT history and weather/surveillance feeds. Confirm against your reference data sources before publication.
- [NEEDS HUMAN] **L425** - N4. Audit all external links during final pre-publication pass. The MIMIC-IV-ED, CDC FluView, AHRQ ESI handbook, and Hyndman textbook links are stable. AWS blog and docs links should be re-verified.
