# Open TODOs — Recipe 6.5: Provider Practice Pattern Analysis

> Auto-extracted 2026-06-18 from inline source comments (4 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter06.05-architecture.md`

- **L13** — TODO (TechWriter): Expert review SEC-3 (MEDIUM). Add note that patient-level PHI is loaded into SageMaker Processing ephemeral storage during case-mix model training. Apply minimum panel size filter (30-50 patients) before model training, not just before clustering, to prevent small-panel features from encoding individual patient characteristics.
- **L29** — TODO (TechWriter): Expert review SEC-1 (HIGH). Add tiered access control section: (1) Individual providers see only their own report. (2) Medical directors see specialty-level dashboards with individual provider identifiers (requires peer review privilege coverage in most states). (3) Analytics team sees de-identified data for model development. (4) For specialties with fewer than 5 providers in a cluster, suppress individual-level comparisons to prevent re-identification. Implement QuickSight row-level security with a permissions dataset mapping user identity to allowed provider_ids. Consult legal counsel on peer review privilege before exposing individually identified provider performance data.
- **L71** — TODO (TechWriter): Expert review SEC-2 (HIGH). Expand IAM permissions with explicit resource ARN examples showing least-privilege scoping. Show sagemaker:CreateTrainingJob with condition key sagemaker:VpcSecurityGroupIds restricting to PHI security group. Show redshift:GetClusterCredentials restricted to specific database user with schema-level grants only on provider profiling tables.
- **L432** — TODO (TechWriter): Verify all URLs above are current and accessible
