# Open TODOs — Recipe 7.6: Rising Risk Identification

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.06-rising-risk-identification.md`

- **L63** — TODO (TechWriter): Expert review A1 (HIGH). Add subsection "Equity and Bias Considerations" after this paragraph. Cover: differential data density (sparse-visit patients fall into INSUFFICIENT_HISTORY), inherited model bias (Obermeyer et al. 2019), threshold equity across demographic groups, and intervention allocation fairness. Include mitigation strategies: audit flag rates by demographic group, group-specific threshold calibration, proactive outreach for sparse-data patients, equity reporting for the insufficient-history population.

## architecture — `chapter07.06-architecture.md`

- **L19** — TODO (TechWriter): Expert review S1 (HIGH). Add paragraph on access control: API layer with panel-level authorization mediating DynamoDB access, Lambda authorizer validating panel assignment, restricting direct DynamoDB access to pipeline IAM roles only. HIPAA minimum-necessary standard requires care managers access only attributed patients.
- **L23** — TODO (TechWriter): Expert review A3 (MEDIUM). Add note about pipeline failure monitoring: recommend Step Functions or equivalent orchestrator with error handling. Each step should emit success/failure metrics to CloudWatch. Configure alarms for: pipeline not completing within expected window, any step failure, anomalous output (flagged count deviating >50% from prior cycle). Alert ops team if pipeline fails, since a missed cycle means rising-risk patients go unidentified for an additional month.
- **L25** — TODO (TechWriter): Expert review S2 (MEDIUM). Add note: SNS notifications with patient IDs and trajectory data are PHI. Restrict subscriptions to HIPAA-compliant endpoints (SQS, Lambda, HTTPS). Avoid email/SMS with clinical details. Send minimal alerts with dashboard links instead of embedding trajectory data in notification body.
- **L59** — TODO (TechWriter): Expert review S3 (MEDIUM). Add note: each pipeline phase should use a dedicated IAM role scoped to specific resource ARNs. Glue feature assembly role gets S3 read on source + write on feature store only. SageMaker role gets S3 read on features + write on score history only. Lambda detection role gets DynamoDB write on risk state table + events:PutEvents on specific event bus. Never use a single role with all permissions.
- **L396** — TODO (TechWriter): Expert review A2 (MEDIUM). Add note: for populations exceeding 500K, consider splitting the detection step. Use a Glue job for threshold application and signal collection (bulk data transformation), and Lambda only for routing and notification (handles only the flagged subset, typically <1% of population). This avoids Lambda memory and timeout constraints for the bulk filtering operation.
