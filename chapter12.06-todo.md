# Open TODOs: Recipe 12.6: Revenue Cycle Cash Flow Forecasting ⭐⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (27 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter12.06-revenue-cycle-cash-flow-forecasting.md`

- **L5** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the cost estimate (per-unit and monthly ranges) when the recipe body is drafted. Use the chapter-12 pattern from recipes 12.4 and 12.5 ("$400-$1,800 per month per hospital workload" range style) as the reference. Replace the `_TBD by TechWriter_` placeholder on the line above.
- **L7** — TODO (TechWriter): Expert review C1 (CRITICAL). The main recipe `chapter12.06-revenue-cycle-cash-flow-forecasting.md` was missing for two consecutive expert-review passes. This file is a structural scaffold authored by the TechEditor solely to unblock the file_exists validation gate; every section below is a placeholder that the TechWriter must author from scratch. Use chapter12.04 and chapter12.05 as the reference for length, structure, voice, and the chapter-12 review pattern. The Python companion `chapter12.06-python-example.md` is already present and reviewed (see `reviews/chapter12.06-code-review.md`); its preamble enumerates the five pseudocode steps the main recipe must articulate. Open the recipe at the CFO's desk, the AR-aging meeting, or a treasury cash-application meeting, not at the bedside. Build it around the architectural primitives the expert panel called out: payer-mix decomposition, survival-curve framing for time-to-payment, denial-and-appeals timing, contract-version awareness, self-pay tail modeling, and finance-grade prediction intervals (P10, P50, P90).
- **L13** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the verbose, passionate problem statement. Open at the CFO's Monday treasury meeting, the AR-aging review, or a payer-contract-renewal conversation. Make the reader feel the operational weight of cash flow uncertainty: how a denied-claim wave at a major commercial payer cascades into working-capital pressure, what a Change-Healthcare-class clearinghouse outage looks like to the revenue-cycle team, and why the finance team's existing weekly cash forecast is "a spreadsheet with payer assumptions baked in five years ago." Keep it vendor-agnostic and CC-voice. No em dashes.
- **L19** — TODO (TechWriter): Expert review C1 (CRITICAL). Teach the underlying technology from first principles, vendor-agnostic. The core architectural insights the expert panel expects to see articulated:

1. Payer-mix decomposition as the central architectural decision (Medicare, Medicaid, commercial-by-contract, self-pay, workers comp, auto each pay differently and must be forecast independently).
2. Survival framing for time-to-payment (Kaplan-Meier with right-censoring for still-open claims; explain why this is a survival problem, not a regression problem).
3. Denial-and-appeals timing as a parallel sub-forecast (5 to 12% first-pass denial rate, 60 to 80% appeal recoverability, 30 to 90 day appeal timeline). These are institutional benchmarks the panel expects framed as architecture, not implementation detail.
4. Contract-version awareness (curves train only on data after the relevant contract took effect; an alert fires when live data diverges).
5. Self-pay AR as a separate animal (long tails, low recovery, sensitivity to statement cycle).
6. Monte Carlo composition produces prediction intervals (P10, P50, P90 weekly cash inflow), not point forecasts.
7. Backtesting and cohort-stratified accuracy monitoring (per payer class, per service line, per denial cohort).

Mine the Python companion's prose for the accurate benchmarks but rewrite into architecture-level prose. Vendor-agnostic. No AWS service names in this section.
- **L33** — TODO (TechWriter): Expert review C1 (CRITICAL). Develop the survival-framing subsection along the same pattern as recipe 12.5's "Why This Is a Flow Problem, Not a Volume Problem" and recipe 12.4's analogous framing subsection. Right-censoring of open claims is the headline concept.
- **L37** — TODO (TechWriter): Expert review C1 (CRITICAL). Articulate why a single aggregate payment-time curve is the wrong framing and why per-payer curves with hazard smoothing are the right architectural choice. Include the institutional benchmarks (Medicare clean tight schedule, Medicaid slow with state-specific patterns, commercial varies by contract, self-pay long fat tail).
- **L41** — TODO (TechWriter): Expert review C1 (CRITICAL) and Code review W1 (WARNING, see below). Explain the denial cycle as a separate sub-process with its own timing and recovery dynamics. CRITICAL: the prose must be consistent with however the Python companion's denial-and-appeal modeling lands. Code review W1 flagged that the Python implementation currently double-counts the denied-recovered cohort; the TechWriter (or a follow-up code-fix pass) must resolve W1 in the Python companion before this prose section is finalized so the recipe's architectural description matches what the example code actually does. The two acceptable resolutions described in W1 are: (a) drop the explicit denial sub-process and use the per-payer curve directly with prose stating the curve absorbs the recovered-from-appeal cohort by construction, or (b) carve out the denial-recovery cohort from the curve fitting and explicitly compose the two distributions in the simulation. Pick one resolution path and write the prose to match.
- **L45** — TODO (TechWriter): Expert review C1 (CRITICAL). Promote contract-version awareness to a first-class architectural status as the panel requires. Cover: contract-effective-date registry, training-window selection conditional on contract version, and the divergence alert when live data drifts from the trained curve.
- **L49** — TODO (TechWriter): Expert review C1 (CRITICAL). Develop the self-pay subsection. Long tails, low recovery, statement-cycle sensitivity, payment-plan availability, pre-collection workflow effects. The recipe must either model self-pay separately or explicitly accept the self-pay tail as the dominant longer-horizon uncertainty.
- **L53** — TODO (TechWriter): Expert review C1 (CRITICAL). Explain why a finance-grade prediction interval (P10, P50, P90 weekly cash inflow) is what the CFO actually needs and why a single point forecast is operationally inferior. Tie this to the Monte Carlo per-claim sampling discipline the Python companion already implements.
- **L57** — TODO (TechWriter): Expert review C1 (CRITICAL). Cover the backtest harness and the continuously-updated forecast-vs-actual scorecard. Per payer class, per service line, per denial cohort. Note that finance-team trust is built over months of demonstrated accuracy.
- **L63** — TODO (TechWriter): Expert review C1 (CRITICAL). Describe the multi-stage pipeline at a conceptual level. The expert panel's required articulation: ingestion of 837 claims, 835 remittance, 277/277CA claim-status, and contract metadata; per-payer curve fitting with right-censoring; per-claim Monte Carlo simulation conditional on age and adjudication state; per-week aggregation with prediction intervals; delivery to finance with backtesting feedback. Vendor-agnostic. No service names.
- **L71** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the Honest Take section with at least four observations specific to revenue cycle (not generic forecasting commentary). Candidate themes the expert panel would expect to see: (1) clearinghouse outage scenarios as the operative reference event (Change Healthcare February 2024); (2) contract-version drift breaking models overnight; (3) self-pay tail mis-estimation as the dominant longer-horizon uncertainty; (4) denial-reason-code distribution shifts and what they indicate; (5) cohort-stratified accuracy monitoring revealing systematically wrong Medicaid forecasts that aggregate metrics hide. CC-voice, self-deprecating expertise, no marketing-voice creep.
- **L77** — TODO (TechWriter): Expert review C1 (CRITICAL). Cross-reference the adjacent recipes. Required entries based on what already exists in chapter 12 and the planning docs:

- Recipe 12.1 (Appointment Volume Forecasting): operational forecasting analog; calendar-feature engineering and operational dashboard pattern carry over.
- Recipe 12.2 (Supply Inventory Forecasting): different domain (supplies, not cash) but similar Poisson-style sub-forecasting + safety-buffer composition.
- Recipe 12.3 (ED Arrival Forecasting): the canonical inflow-forecast template chapter 12 establishes; this recipe extends the pattern from operational arrivals to financial inflows.
- Recipe 12.4 (Lab Result Trend Analysis): adjacent recipe; shares the survival-style modeling and the FHIR-adjacent ingestion pattern.
- Recipe 12.5 (Hospital Census Forecasting): operational counterpart to this financial recipe; the flow-not-volume framing carries over directly.
- Recipe 13.x (Knowledge Graphs): the contract-metadata layer in this recipe is a small knowledge graph in disguise; payer hierarchies, plan hierarchies, and contract effective dates are exactly the modeling problem chapter 13 covers.
- Recipe 14.x (Optimization / Operations Research): the downstream consumer of cash flow forecasts (working-capital optimization, payer-mix optimization, AR-prioritization optimization).
- **L91** — TODO (TechWriter): Expert review C1 (CRITICAL). Searchable label list per chapter-12 convention. Candidate tags: time-series · revenue-cycle · cash-flow-forecasting · payer-mix · survival-analysis · kaplan-meier · monte-carlo · denial-management · appeals · contract-modeling · self-pay-ar · sagemaker · dynamodb · step-functions · glue · medium · production · hipaa · 837 · 835 · 277.

## architecture — `chapter12.06-architecture.md`

- **L9** — TODO (TechWriter): Expert review C1 (CRITICAL). Introduce each AWS service and explain why it was chosen for that specific piece of the architecture. The Python companion uses Amazon S3, AWS Glue, Amazon SageMaker, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge, and Amazon CloudWatch. Connect each back to the conceptual stage from the General Architecture Pattern section.
- **L15** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the Mermaid flowchart showing the AWS components and data flow. Match the level of detail used in chapter12.05's architecture diagram. Include the weekly Step Functions cycle (harmonize -> fit curves -> simulate -> aggregate -> deliver) and the EventBridge schedule trigger.
- **L21** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the prerequisites table per the RECIPE-GUIDE format. Per the Security Expert Review:

- Revenue-cycle data is PHI by association (837/835/277/277CA carry patient identifiers, service dates, diagnosis and procedure codes).
- BAA coverage for revenue-cycle vendors is recipe-specific (clearinghouse like Change Healthcare/Availity/Waystar/Optum/Experian Health, payer-portal vendor, denial-management/appeals-automation vendor).
- Customer-managed KMS keys per data class (raw 837/835/277/277CA, harmonized claim-level, denial-and-appeals state, payer-contract terms, forecast outputs, model artifacts, DynamoDB or RDS serving table, CloudWatch logs).
- CloudTrail data events on PHI-bearing buckets and tables.
- Synthetic-data discipline for development.
- Lambda least-privilege per stage (the Python companion explicitly flags the lack of per-Lambda IAM scoping in its limitations).
- Secrets Manager for clearinghouse credentials with rotation, KMS encryption, and per-Lambda scoped `secretsmanager:GetSecretValue`.
- Networking posture: private subnets for compute, VPC endpoints for S3/KMS/DynamoDB/SageMaker/Lambda/Step Functions/EventBridge/CloudWatch Logs/Secrets Manager, restrictive egress, dedicated VPN or SFTP-over-IPSec to the clearinghouse, no public endpoints.
- **L36** — TODO (TechWriter): Expert review C1 (CRITICAL). Table of AWS services and their specific roles in this recipe, mirroring the structure used in chapter12.05's Ingredients section.
- **L42** — TODO (TechWriter): Expert review C1 (CRITICAL). Author the language-agnostic pseudocode walkthrough. The five steps are already enumerated by the Python companion's preamble; the prose must articulate them as architectural decisions and explain what goes wrong if each step is skipped. Steps:

1. Ingest and harmonize the AR ledger, the historical 835 stream, and the contract metadata.
2. Fit per-payer payment-time distributions with a Kaplan-Meier-style survival estimator and right-censoring.
3. For every open AR claim, simulate N payment-date samples conditional on age and adjudication state, and compose into per-week trajectories.
4. Apply seasonality, denial-and-appeal cycle adjustments, and patient-responsibility tail modeling on top of the per-payer simulations.
5. Load forecasts to DynamoDB keyed by `forecast_week`, write trajectories to S3, and emit pipeline-lifecycle events.

Cross-reference Code review W2 (WARNING): the Python companion's Step 4 section header is "Aggregate to Per-Week Cash Flow Forecasts" but applies seasonality and denial-and-appeal adjustments inside Step 3. The main recipe's pseudocode should state the canonical step ordering; whichever resolution the TechWriter chooses for the Python companion (relabel Step 4, or move the seasonality/denial logic into Step 4) must be reflected here so the two artifacts agree.
- **L58** — TODO (TechWriter): Expert review C1 (CRITICAL). Sample JSON output, performance benchmarks, and an honest list of failure modes. The Python companion's run produces per-week per-payer percentile records and an all-payer rollup; mine those for the sample shape but author the prose.
- **L64** — TODO (TechWriter): Expert review C1 (CRITICAL). Per the Voice Reviewer's expectation, include this section calling out specific failure modes: clearinghouse outages, contract-version drift, self-pay tail mis-estimation, denial-reason-code distribution shifts, and the per-Lambda IAM gap the Python companion already flags.
- **L70** — TODO (TechWriter): Expert review C1 (CRITICAL). 2 to 3 practical extensions with enough detail to get started. Candidates: (1) joint multi-entity forecasting for health-system-level cash flow with shared models across hospitals; (2) denial-prevention coupling that uses claim-level features to predict denial probability before submission and feeds back into the cash forecast; (3) payer-contract-renewal scenario modeling (what does cash flow look like if the next renewal shifts the fee schedule by X%?); (4) real-time integration with the daily 835 file so the forecast refreshes intra-week.
- **L76** — TODO (TechWriter): Expert review C1 (CRITICAL). Populate AWS Documentation, AWS Sample Repos, External Resources, and AWS Solutions and Blogs sections per RECIPE-GUIDE rules. Verify every link before publication; never use fake or made-up GitHub URLs. Required candidate sources to evaluate:

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

Apply the chapter-12 pattern of leaving an audit-pass TODO note acknowledging that AWS doc and blog links should be re-verified close to publication.
- **L92** — TODO (TechWriter): N4 (chapter pattern). Audit all external links during the final pre-publication pass. AWS doc links and blog links rotate; HL7, lifelines, scikit-survival, and CMS links are stable.
- **L98** — TODO (TechWriter): Expert review C1 (CRITICAL). Three tiers (Basic, Production-ready, With variations) per RECIPE-GUIDE. Use the chapter-12 pattern from recipes 12.4 and 12.5 as the reference for ranges.

## python-example — `chapter12.06-python-example.md`

- **L1075** — TODO (TechWriter): Expert review / Code review W2 (WARNING). The Step 4
section header below ("Aggregate to Per-Week Cash Flow Forecasts") does not
match what the file's preamble promises Step 4 does ("apply seasonality,
denial-and-appeal cycle adjustments, and patient-responsibility tail
modeling"). Seasonality is actually applied in Step 3 (inside
`simulate_cash_flow`), denial-and-appeal is applied in Step 3 (inside
`simulate_claim_payment`), and patient-responsibility tail modeling is not
implemented at all. Fix the preamble paragraph at the top of this file
(near "the code maps to the five pseudocode steps") so Step 3 = "simulate
per-claim payments with seasonality and denial-and-appeal sub-process
applied per sample" and Step 4 = "aggregate sample-wise to per-week,
per-payer percentiles," with patient-responsibility tail modeling moved to
Gap to Production.
