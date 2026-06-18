# Recipe 12.6: Revenue Cycle Cash Flow Forecasting (Architecture and Implementation)

> **This is the architecture companion to [Recipe 12.6: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting).** Start there for the problem statement, underlying technology, and vendor-agnostic architecture pattern.

---

## Why These Services (AWS Implementation)

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

## Code Review Findings (forwarded to TechWriter)

The Python companion `chapter12.06-python-example.md` has been code-reviewed (verdict PASS, see `reviews/chapter12.06-code-review.md`). Findings the TechWriter must address when drafting the architecture companion and reconciling the Python companion:

<!-- TODO (TechWriter): Code review W1 (WARNING). Denial-and-appeal sub-process double-counts the denied-recovered cohort already absorbed into the Kaplan-Meier curve. The fitted curve in `fit_payer_payment_curves` includes denied-recovered claims as paid events at lag = first_lag + appeal_extra; `simulate_claim_payment` then re-rolls a fresh denial-and-appeal sub-process on top of the curve. Resolutions: (a) drop the explicit denial sub-process and use the curve directly, with prose stating the curve absorbs the recovered-from-appeal cohort by construction; or (b) carve out the denial-recovery cohort from the curve fitting (only fit on `denial_flag=False` records) and then explicitly compose the two distributions in the simulation. The per-claim `denial_flag` is also currently ignored; bias the denial branch on `claim.get("denial_flag")` so a claim with `denial_flag=True` always goes down the appeal branch and a claim with `denial_flag=False` samples a fresh denial outcome. The chosen resolution must be reflected in the main recipe's Denial-and-Appeals subsection. -->

<!-- TODO (TechWriter): Code review W2 (WARNING). Step 4 section header in the Python companion is "Aggregate to Per-Week Cash Flow Forecasts" but the file's preamble describes Step 4 as "seasonality, denial-and-appeal cycle adjustments, and patient-responsibility tail modeling." The actual seasonality logic lives inside Step 3 (`simulate_cash_flow`) and the denial-and-appeal logic lives inside Step 3 (`simulate_claim_payment`). Patient-responsibility tail modeling is not implemented as a separate step. Either relabel the Step 4 section header to match the aggregation function it actually heads, or move the seasonality/denial/self-pay logic into a true Step 4 function. The main recipe's pseudocode walkthrough must agree with whichever resolution lands. -->

<!-- TODO (TechWriter): Code review NOTE 1. `harmonize_ar_records` is called twice in `run_cash_flow_pipeline` and re-writes the same S3 keys with the same content. Remove the duplicate invocation. -->

<!-- TODO (TechWriter): Code review NOTE 2. Dict comprehension in the trajectory write is a no-op. Either remove it or replace it with the intended transformation. -->

<!-- TODO (TechWriter): Code review NOTE 3. Magic-number `or 30` fallback when the curve sample returns `None` in the denial-recovery branch. Promote the fallback to a named constant with a comment explaining the rationale, or compute it from the curve's median. -->

<!-- TODO (TechWriter): Code review NOTE 4. `simulate_cash_flow` silently skips claims with no payer curve, with no metric or count. Add a CloudWatch counter for skipped claims and log the payer ids that lack curves. -->

<!-- TODO (TechWriter): Code review NOTE 5. Module-level boto3 clients `sagemaker_runtime` and `lambda_client` are constructed but never exercised, even by the production code paths the comment promises. Either remove them or wire them into the production-path comment block so the example illustrates the intended invocation. -->

<!-- TODO (TechWriter): Code review NOTE 6. Manual outer chunking around `batch_writer` is redundant given the SDK auto-chunks. Remove the manual chunking and let `batch_writer` handle it. -->

<!-- TODO (TechWriter): Code review NOTE 7. Per-record `as_of` timestamp evaluates `datetime.now(timezone.utc)` once per record. Hoist the timestamp computation out of the loop so all records in a single forecast run share the same `as_of` value. -->

<!-- TODO (TechWriter): Code review NOTE 8. Sample Output prose says "Numbers vary because of the synthetic-data noise" but the seed is fixed across all generators. Either remove the variability claim from the prose or unfix the seed (and document the determinism trade-off explicitly). -->

<!-- TODO (TechWriter): Code review NOTE 9. `aggregate_forecasts` percentile selection uses index truncation rather than interpolation. Replace with `statistics.quantiles` or a NumPy `percentile` call so P10/P50/P90 match the standard library and the panel's expected definitions. -->

<!-- TODO (TechWriter): Code review NOTE 10. `_to_decimal` returns `bool` unchanged rather than converting. Add an `isinstance(value, bool)` branch that converts to `Decimal(int(value))` so the boolean flags do not bypass the Decimal discipline at the DynamoDB write site. -->

---

*← [Main Recipe: Revenue Cycle Cash Flow Forecasting](chapter12.06-revenue-cycle-cash-flow-forecasting) · [Python Example](chapter12.06-python-example) · [Chapter 12 Index](chapter12-preface)*
