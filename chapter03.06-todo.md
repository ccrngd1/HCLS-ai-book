# Open TODOs: Recipe 3.6: Healthcare Fraud, Waste, and Abuse Detection ⭐

> Remaining items require human verification of external sources or product decisions.

## main — `chapter03.06-healthcare-fraud-waste-abuse-detection.md`

- [NEEDS HUMAN] **L166** — Verify current NHCAA and CMS published estimates for FWA losses. Figures shift each year; cannot confirm specific numbers without access to the latest publications.
- [NEEDS HUMAN] **L234** — Expand with concrete references once specific validated patterns for GNN-based FWA detection become published with operational results. No confirmed publications with operational results available to cite.
- [NEEDS HUMAN] **Expert S1** — Graph-construction pseudocode in Step 3 has a `billed` edge comment ("organization -> claim") but the code targets a hashed-patient. Claim vertices are not upserted despite the prose listing claims as a node type. Community detection on the resulting graph finds patient-centered communities rather than provider-and-organization collusive networks. Requires coordinated edit to add Claim vertex upserts and separate edge types (rendered_on_claim, billed_for_claim, for_patient). Editor decision on scope.
- [NEEDS HUMAN] **Expert A1** — Outcome-event idempotency for the EventBridge to evidence-aggregator path. Twelfth consecutive recipe with this finding; recommend a cookbook-wide trigger-idempotency appendix rather than per-recipe pseudocode edits.
- [NEEDS HUMAN] **Expert A2** — No DLQ or poison-message handling for the stream-normalizer, rules-engine, evidence-aggregator, or outcome-capture Lambdas. Recurring chapter-wide pattern; recommend cookbook-level architectural guidance.
- [NEEDS HUMAN] **Expert A3** — Provider appeals and due-process workflow: Step 9 outcome taxonomy has no appeal-stage states, no immutable evidence-as-of-decision snapshot, no appeal-reversal feedback path. Editor decision on whether to add pseudocode or an explicit deferral note.
- [NEEDS HUMAN] **Expert A4** — Reference-data versioning (LEIE-extract date, MUE-table version, coverage-policy version, graph-snapshot ID, model version) not consistently propagated through evidence aggregation. Needs coordinated pseudocode update in Steps 4, 5, 6, 7.

## architecture — `chapter03.06-architecture.md`

- [NEEDS HUMAN] **L27** — Confirm the set of HIPAA-eligible Bedrock foundation models as of the current year. Model availability under the AWS BAA has been expanding; need to verify before recommending a specific model. The pseudocode uses "anthropic.claude-XX" as a placeholder.
- [NEEDS HUMAN] **L143** — Verify current published industry benchmarks for SIU ROI. NHCAA and the Healthcare Fraud Prevention Partnership have published figures; cannot confirm current values without access to the latest publications.
- [NEEDS HUMAN] **L185** — Verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating healthcare fraud detection, graph-based anti-fraud, or payment integrity analytics on AWS. A direct match has not been confirmed.
- [NEEDS HUMAN] **L1154** — Benchmark ranges in the Expected Results table are directional from typical payment integrity project experience. Replace with measured numbers or confirmed published ranges from NHCAA, HFPP, or industry conferences (AHIMA, HFPP, SIU/SIIA).
- [NEEDS HUMAN] **L1265** — Confirm current production adoption of federated learning in healthcare payer contexts. Evidence is limited; cannot verify specific deployments.
- [NEEDS HUMAN] **L1295** — Verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating healthcare fraud detection, insurance fraud detection, or graph-based anomaly detection on AWS. Candidate repos exist in adjacent domains but a direct healthcare match has not been confirmed.
- [NEEDS HUMAN] **L1301** — Verify and add two or three specific AWS blog post URLs on graph-based fraud detection, payer fraud detection, or related topics. Cannot confirm URLs exist without live verification.
- [NEEDS HUMAN] **Expert S4** — Legal-privilege architecture: Prerequisites row names the concern but does not specify infrastructure primitives (separate AWS account, separate VPC, separate KMS keys, distinct CloudTrail trail, SCP-level controls). Unique to this recipe; the fix gives architects primitives to bring to the GC conversation.
- [NEEDS HUMAN] **Expert S2** — Per-investigator-assignment IAM scoping for OpenSearch case index and case-state DynamoDB not specified in Prerequisites or pseudocode. Requires product decision on access-control granularity.
- [NEEDS HUMAN] **Expert S3** — Subgroup data governance for fairness monitoring: architectural artifacts (data store location, access scope, audit trail, query path for demographic data) are unspecified. Fifth recipe in Chapter 3 with this finding; recommend a chapter-level or appendix-level resolution.
