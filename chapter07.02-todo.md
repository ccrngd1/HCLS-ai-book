# Open TODOs — Recipe 7.2: Propensity to Pay Scoring

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter07.02-propensity-to-pay-scoring.md`

- **L41** — TODO (TechWriter): Expert review S3 (MEDIUM). Add a paragraph noting FCRA implications. Since the recipe draws an explicit credit scoring analogy, note that propensity scores used for adverse financial decisions (escalating to collections, denying payment plans) may trigger Fair Credit Reporting Act requirements. Recommend consulting legal counsel and using scores for prioritization rather than exclusion.

## architecture — `chapter07.02-architecture.md`

- **L46** — TODO (TechWriter): Expert review A1 (HIGH). Add a feedback loop to the architecture diagram showing ground truth collection, calibration monitoring (rolling AUC and ECE to CloudWatch), and a retraining trigger when ECE exceeds 0.05 or AUC drops below 0.75. The recipe identifies calibration as the critical requirement but the diagram has no monitoring infrastructure.
- **L236** — TODO (TechWriter): Expert review A2 (MEDIUM). Add a note about interpreting scores relative to balance age. A 90-day model applied to a balance at day 85 has only 5 days of remaining outcome window, making the score more definitive than the same score on a day-5 balance. Consider recommending multiple time-horizon models or age-adjusted thresholds in the strategy engine.
- **L283** — TODO (TechWriter): Expert review S2 (HIGH). Expand DynamoDB retention and access control guidance. The predictions table stores PHI (patient IDs linked to financial behavioral data). Add: (1) TTL policy to expire predictions after balance resolution plus audit window; (2) IAM policy separation between strategy engine (broad read) and other consumers (restricted); (3) note that the score-range GSI should be restricted to authorized revenue cycle roles, not exposed to clinical staff.
- **L287** — TODO (TechWriter): Expert review A3 (MEDIUM). Add a 5-10% randomization holdout to the strategy engine pseudocode. Reserve a fraction of balances in each score band for random assignment to alternative strategies. This creates counterfactual data to validate thresholds and prevents the self-fulfilling prophecy warned about in the Honest Take. Log the randomization flag alongside the routing decision.
- **L383** — TODO (TechWriter): RECIPE-GUIDE compliance. Add a "Why This Isn't Production-Ready" section between Expected Results and Variations. Should cover gaps a production deployment must close (monitoring, fairness audits, feedback loops, integration with billing system workflow).
