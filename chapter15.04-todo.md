# Open TODOs — Recipe 15.4: Sepsis Treatment Optimization

> Auto-extracted 2026-06-18 from inline source comments (9 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter15.04-architecture.md`

- **L15** — TODO (TechWriter): Expert review A4 (MEDIUM). Add model versioning and rollback strategy: use SageMaker Model Registry with approval workflows, run OPE comparison of new vs. deployed policy, implement canary deployment pattern with automatic rollback on degraded safety constraint or clinician override rates.
- **L21** — TODO (TechWriter): Expert review A3 (MEDIUM). Clarify that this recipe's code uses continuous states with a neural Q-network (SageMaker endpoint). DynamoDB is the alternative for discretized state spaces (750 k-means clusters). Recommend choosing one approach and noting the tradeoff.
- **L29** — TODO (TechWriter): Expert review A2 (HIGH). Add concrete distribution shift detection mechanism: compute training-time state mean/covariance, use Mahalanobis distance at inference to flag OOD states, suppress low-confidence recommendations, track OOD percentage in CloudWatch with alarms for rising rates.
- **L61** — TODO (TechWriter): Expert review S1 (HIGH). Replace flat IAM permission list with role-separated guidance: separate roles per pipeline stage (Glue ETL, SageMaker training, inference endpoint, Step Functions orchestration) with resource-scoped ARN constraints.
- **L65** — TODO (TechWriter): Expert review N1 (MEDIUM). Expand VPC endpoint list to include SageMaker API, SageMaker Runtime, and KMS interface endpoints. Without these, private subnet deployment requires NAT Gateway (egress point for PHI) or fails entirely. Note per-AZ-hour cost (~$7.20/month per endpoint per AZ).
- **L89** — TODO (TechWriter): Expert review S3 (MEDIUM). Add note on de-identification: training data should be de-identified per HIPAA Safe Harbor or used under Limited Data Set with DUA. Patient IDs replaced with pseudonymous identifiers. Model artifact trained on de-identified data is not itself PHI, but trajectory dataset is.
- **L303** — TODO (TechWriter): Expert review A1 (HIGH). Add monitoring/alerting for safety constraint trigger rates. If any constraint fires on >20% of recommendations in a 24-hour window, alert clinical informatics. Publish constraint trigger rates to CloudWatch as custom metrics with alarms.
- **L378** — TODO (TechWriter): Expert review S2 (MEDIUM). Specify tamper-evident audit storage: S3 Object Lock (compliance mode) or CloudWatch Logs with resource policy preventing deletion. Consider separate audit account with cross-account write-only access.
- **L453** — TODO (TechWriter): Expert review A5 (MEDIUM). Add a variation on reward function experimentation: parameterize reward, train multiple policies in parallel, use SageMaker Experiments to track reward-to-policy mapping, compare via OPE pipeline.
