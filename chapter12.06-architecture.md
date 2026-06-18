# Recipe 12.6: Revenue Cycle Cash Flow Forecasting (Architecture and Implementation)

> **This is the architecture companion to [Recipe 12.6: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting).** Start there for the problem statement, underlying technology, and vendor-agnostic architecture pattern.

---

## Why These Services

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Introduce each AWS service and explain why it was chosen for that specific piece of the architecture. The Python companion uses Amazon S3, AWS Glue, Amazon SageMaker, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge, and Amazon CloudWatch. Connect each back to the conceptual stage from the General Architecture Pattern section. -->

---

## Architecture Diagram

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Mermaid flowchart showing the AWS components and data flow. Match the level of detail used in chapter12.05's architecture diagram. Include the weekly Step Functions cycle (harmonize -> fit curves -> simulate -> aggregate -> deliver) and the EventBridge schedule trigger. -->

---

## Prerequisites

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the prerequisites table per the RECIPE-GUIDE format. Per the Security Expert Review:

- Revenue-cycle data is PHI by association (837/835/277/277CA carry patient identifiers, service dates, diagnosis and procedure codes).
- BAA coverage for revenue-cycle vendors is recipe-specific (clearinghouse like Change Healthcare/Availity/Waystar/Optum/Experian Health, payer-portal vendor, denial-management/appeals-automation vendor).
- Customer-managed KMS keys per data class (raw 837/835/277/277CA, harmonized claim-level, denial-and-appeals state, payer-contract terms, forecast outputs, model artifacts, DynamoDB or RDS serving table, CloudWatch logs).
- CloudTrail data events on PHI-bearing buckets and tables.
- Synthetic-data discipline for development.
- Lambda least-privilege per stage (the Python companion explicitly flags the lack of per-Lambda IAM scoping in its limitations).
- Secrets Manager for clearinghouse credentials with rotation, KMS encryption, and per-Lambda scoped `secretsmanager:GetSecretValue`.
- Networking posture: private subnets for compute, VPC endpoints for S3/KMS/DynamoDB/SageMaker/Lambda/Step Functions/EventBridge/CloudWatch Logs/Secrets Manager, restrictive egress, dedicated VPN or SFTP-over-IPSec to the clearinghouse, no public endpoints. -->

---

## Ingredients

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Table of AWS services and their specific roles in this recipe, mirroring the structure used in chapter12.05's Ingredients section. -->

---

## Pseudocode Walkthrough

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the language-agnostic pseudocode walkthrough. The five steps are already enumerated by the Python companion's preamble; the prose must articulate them as architectural decisions and explain what goes wrong if each step is skipped. Steps:

1. Ingest and harmonize the AR ledger, the historical 835 stream, and the contract metadata.
2. Fit per-payer payment-time distributions with a Kaplan-Meier-style survival estimator and right-censoring.
3. For every open AR claim, simulate N payment-date samples conditional on age and adjudication state, and compose into per-week trajectories.
4. Apply seasonality, denial-and-appeal cycle adjustments, and patient-responsibility tail modeling on top of the per-payer simulations.
5. Load forecasts to DynamoDB keyed by `forecast_week`, write trajectories to S3, and emit pipeline-lifecycle events.

Cross-reference Code review W2 (WARNING): the Python companion's Step 4 section header is "Aggregate to Per-Week Cash Flow Forecasts" but applies seasonality and denial-and-appeal adjustments inside Step 3. The main recipe's pseudocode should state the canonical step ordering; whichever resolution the TechWriter chooses for the Python companion (relabel Step 4, or move the seasonality/denial logic into Step 4) must be reflected here so the two artifacts agree. -->

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter12.06-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

## Expected Results

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Sample JSON output, performance benchmarks, and an honest list of failure modes. The Python companion's run produces per-week per-payer percentile records and an all-payer rollup; mine those for the sample shape but author the prose. -->

---

## Why This Isn't Production-Ready

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Per the Voice Reviewer's expectation, include this section calling out specific failure modes: clearinghouse outages, contract-version drift, self-pay tail mis-estimation, denial-reason-code distribution shifts, and the per-Lambda IAM gap the Python companion already flags. -->

---

## Variations and Extensions

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). 2 to 3 practical extensions with enough detail to get started. Candidates: (1) joint multi-entity forecasting for health-system-level cash flow with shared models across hospitals; (2) denial-prevention coupling that uses claim-level features to predict denial probability before submission and feeds back into the cash forecast; (3) payer-contract-renewal scenario modeling (what does cash flow look like if the next renewal shifts the fee schedule by X%?); (4) real-time integration with the daily 835 file so the forecast refreshes intra-week. -->

---

## Additional Resources

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Populate AWS Documentation, AWS Sample Repos, External Resources, and AWS Solutions and Blogs sections per RECIPE-GUIDE rules. Verify every link before publication; never use fake or made-up GitHub URLs. Required candidate sources to evaluate:

- AWS HIPAA Eligible Services list
- Architecting for HIPAA Security and Compliance on AWS whitepaper
- Amazon SageMaker DeepAR Forecasting documentation (hierarchical multi-payer forecasting)
- AWS Step Functions documentation (orchestration with retries and Catch blocks)
- Amazon DynamoDB documentation
- AWS Glue documentation (837/835 ingestion ETL)
- lifelines Python library (Kaplan-Meier and Cox proportional hazards)
- scikit-survival library (gradient-boosted survival models)
- HL7 837/835/277/277CA transaction set specifications
- CMS resources on revenue cycle and denials management
- aws-samples repos to evaluate (search for healthcare revenue cycle, claims processing, survival modeling)

Apply the chapter-12 pattern of leaving an audit-pass TODO note acknowledging that AWS doc and blog links should be re-verified close to publication. -->

<!-- TODO (TechWriter): N4 (chapter pattern). Audit all external links during the final pre-publication pass. AWS doc links and blog links rotate; HL7, lifelines, scikit-survival, and CMS links are stable. -->

---

## Estimated Implementation Time

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Three tiers (Basic, Production-ready, With variations) per RECIPE-GUIDE. Use the chapter-12 pattern from recipes 12.4 and 12.5 as the reference for ranges. -->

---

*← [Main Recipe: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting) · [Python Example](chapter12.06-python-example) · [Chapter 12 Index](chapter12-preface)*
