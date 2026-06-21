# Open TODOs: Recipe 14.5: Operating Room Block Scheduling

> Auto-extracted 2026-06-18 from inline source comments (5 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter14.05-architecture.md`

- **L200** — TODO (TechWriter): Expert review A1 (HIGH). Add granular solver outcome handling: distinguish infeasible model (relax constraints), suboptimal-but-acceptable solution (gap 5-15%, flag for review but proceed), no feasible solution found (alert ops, don't auto-replace current schedule), and solver crash. Current pseudocode only raises a generic error on failure.
- **L341** — TODO (TechWriter): Expert review S1 (HIGH). Add schedule approval access control model: API Gateway endpoint for approval actions authenticated via Cognito/IAM with role-based access (surgical governance committee only). DynamoDB should store schedule state transitions (proposed, under_review, approved, active) with approver identity and timestamp. CloudTrail captures approval events. The approval path should be a first-class architectural element given the politically sensitive nature of schedule changes.
- **L403** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section per RECIPE-GUIDE. Should appear before Variations and Extensions. Content needed: gaps a production deployment must close (approval workflows, EHR integration, surgeon-level decomposition, seasonal re-training, etc.).
- **L430** — TODO (TechWriter): Expert review V2 (MEDIUM). Find and verify relevant aws-samples repos for optimization/scheduling patterns. RECIPE-GUIDE requires 3-5 sample repos per recipe; currently zero verified. Check amazon-sagemaker-examples for forecasting patterns, OR-Tools or optimization examples in AWS contexts, Batch job submission patterns.
- **L433** — TODO (TechWriter): Expert review V2 (MEDIUM). Verify and add link for INFORMS Healthcare journal or "Operations Research for Health Care" publication.
