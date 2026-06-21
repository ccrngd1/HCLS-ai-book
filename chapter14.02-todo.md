# Open TODOs: Recipe 14.2: Patient-Provider Assignment

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter14.02-patient-provider-assignment.md`

- **L83** — TODO (TechWriter): Expert review A3 (MEDIUM). Add a subsection or paragraph explaining how batch and incremental assignment modes coexist architecturally. The incremental case (single new patient, needs PCP immediately) uses a simplified greedy approach with the same scoring function. Discuss latency requirements (seconds vs. minutes) and how both modes share constraint/scoring logic.
- **L85** — TODO (TechWriter): Expert review A4 (MEDIUM). Add a "Fairness and Bias" subsection (in Honest Take or Variations). At minimum: log all assignments with patient demographics, run periodic statistical tests (chi-square on distributions by race/ethnicity/language), alert if any provider's panel demographics deviate significantly from the practice's overall patient demographics.

## architecture — `chapter14.02-architecture.md`

- **L56** — TODO (TechWriter): Expert review S2 (HIGH). Expand the Prerequisites table or add a paragraph specifying that the DynamoDB assignments table must use KMS CMK encryption because the rationale field and patient_complexity field contain PHI-adjacent data. Also specify that IAM access to the assignments table should be restricted to the panel management team's roles.
- **L58** — TODO (TechWriter): Expert review S3 (MEDIUM). Add a note that the review dashboard requires authentication (Cognito or enterprise SSO) with role-based access scoped to the user's department/practice.
- **L258** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section between Expected Results and Variations. Cover gaps like: no retry logic, no dead-letter handling for failed EHR write-backs, no incremental cache invalidation strategy, no automated weight-tuning feedback loop.
