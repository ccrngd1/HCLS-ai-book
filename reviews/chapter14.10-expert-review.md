# Expert Review: Recipe 14.10 -- Health System Network Design

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 14.10 -- Health System Network Design
**Date:** 2026-06-01
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 14.10 is the capstone of Chapter 14 and arguably one of the most intellectually ambitious recipes in the entire book. The treatment of facility location problems, mixed-integer programming, gravity models, and multi-objective optimization is genuinely educational. The vendor-agnostic technology section is excellent: a reader on any cloud would walk away understanding how to approach health system network design. The honest take section correctly identifies the political and data quality challenges that dominate real-world implementations.

The recipe passes review. There are no critical findings. The architecture is sound for the stated use case (strategic planning, not real-time operations). The security posture is appropriate for the data sensitivity level (aggregate/de-identified data in the optimizer, with PHI only in upstream pipelines). The voice is consistent with the cookbook's style.

That said, there are several medium-severity issues that should be addressed before publication, primarily around IAM permission specificity, the gap between the stated BAA requirement and the actual data flow, and a missing discussion of solver licensing implications for HIPAA environments.

---

## Stage 1: Independent Expert Reviews

---

## Security Review

### 🟡 SEC-1: IAM Permissions Are Overly Broad for QuickSight

**Finding:** The prerequisites table lists `quicksight:*` as a required IAM permission. This grants full administrative access to QuickSight including the ability to create/delete data sources, manage users, and access all dashboards across the account. For a network design pipeline that only needs to refresh a specific dataset and publish to a specific dashboard, this is a violation of least-privilege.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Replace `quicksight:*` with the specific actions needed: `quicksight:CreateIngestion` (to trigger SPICE refresh), `quicksight:DescribeIngestion` (to check refresh status), `quicksight:UpdateDataSet` (if schema changes are needed), and `quicksight:DescribeDashboard`. Scope these to the specific QuickSight resources using resource ARNs. Add a note that QuickSight namespace isolation should be used to prevent the pipeline role from accessing unrelated dashboards.

---

### 🟡 SEC-2: BAA Requirement Discussion Is Ambiguous About Data Boundaries

**Finding:** The prerequisites state: "Required if patient-level utilization data is used (it usually is for gravity model estimation). Aggregate/de-identified data for the optimizer itself may not require BAA, but the upstream data pipeline does." This is technically correct but creates a dangerous ambiguity. The gravity model estimation step (Step 2 in the pseudocode) explicitly uses "historical patient flow data: where did patients actually go." This is patient-level data with geographic identifiers (ZIP code of residence + facility visited), which constitutes PHI under HIPAA's geographic subdivision rule (ZIP codes with populations under 20,000 are direct identifiers; all ZIP codes combined with dates of service are indirect identifiers).

The recipe implies the optimizer runs on de-identified data, but the gravity model calibration step requires identified or limited-dataset data. The boundary between "upstream pipeline that needs BAA" and "optimizer that might not" is not clearly drawn.

**Location:** Prerequisites table, "BAA" row; Step 2 pseudocode description.

**Fix:** Clarify the data flow explicitly: (1) Gravity model parameter estimation uses patient-level data and requires BAA coverage on all services involved (Redshift, SageMaker, S3 buckets holding patient origin data). (2) Once parameters are estimated, the optimizer itself operates on aggregate demand matrices (zone-level counts, not patient-level records) and facility-level attributes. (3) Draw the PHI boundary clearly: "Patient-level data stays in Redshift and the SageMaker processing job that estimates gravity model parameters. The optimization model receives only zone-level demand aggregates and estimated choice probabilities. Ensure the SageMaker processing job output contains no patient-level records."

---

### 🟡 SEC-3: Solver Licensing in HIPAA Environments Not Addressed

**Finding:** The recipe recommends commercial solvers (Gurobi, CPLEX) running on SageMaker instances. Commercial solver licensing typically involves either a license server (network-based) or token-based cloud licensing that phones home to the vendor's licensing infrastructure. If the SageMaker instance is in a private subnet with no internet access (as required by the VPC prerequisites), token-based licensing that requires internet connectivity will fail. License server approaches require the license server to be reachable from the SageMaker instance.

More importantly: if the solver sends any telemetry or usage data to the vendor (Gurobi Cloud licensing sends model statistics), and the model contains variable names derived from facility names or service line names that could be considered business-sensitive (not PHI, but potentially confidential strategic information), this creates a data exfiltration concern.

**Location:** Prerequisites table, "Solver Licensing" row; Technology section, "Solver Selection" subsection.

**Fix:** Add guidance: "For HIPAA environments with no-internet VPC configurations, use a self-hosted license server (Gurobi token server or CPLEX ILM server) deployed in the same VPC. Verify that the solver's telemetry/usage reporting is disabled or does not transmit model content. Gurobi's Web License Service (WLS) requires outbound HTTPS to license.gurobi.com; if your VPC prohibits this, use a local license file or token server instead. For open-source solvers (HiGHS), no licensing infrastructure is needed."

---

### 🔵 SEC-4: CloudTrail Logging Scope Could Be More Specific

**Finding:** The prerequisites state "Enabled for all API calls. Optimization runs are auditable (who ran what scenario with what assumptions)." This is good intent but CloudTrail alone does not capture "what assumptions" were used in an optimization run. CloudTrail logs the API call to `CreateTrainingJob` but not the content of the model formulation or scenario parameters.

**Location:** Prerequisites table, "CloudTrail" row.

**Fix:** Add: "CloudTrail captures infrastructure-level audit (who started which SageMaker job). For decision-level audit (what scenarios were run, what parameters were used, what the optimizer recommended), log scenario configurations and solution summaries to a dedicated S3 audit bucket with object lock (WORM) enabled. This supports regulatory inquiries about why specific capital allocation decisions were made."

---

## Architecture Review

### 🟡 ARC-1: Gravity Model Linearization Approximation Error Not Quantified

**Finding:** The technology section mentions that the gravity model introduces "approximation error" when linearized for the MIP formulation, and the "Where it struggles" section notes "Highly non-linear patient choice models (the gravity model linearization introduces approximation error)." However, the recipe never explains how the gravity model is linearized, what the magnitude of the approximation error is, or how to validate that the linearization is acceptable.

The flow consistency constraint in Step 3 (`flow[z][f][s] <= demand[z][s] * choice_probability(z, f, s, parameters)`) uses pre-computed choice probabilities. But choice probabilities in a gravity model depend on which facilities are open (the denominator sums over all open facilities). If the optimizer closes a facility, the choice probabilities for remaining facilities should increase. The constraint as written uses static probabilities that don't update with the optimizer's decisions. This is the linearization, and it can produce solutions where patient flows are inconsistent with the gravity model predictions for the recommended network configuration.

**Location:** Step 3 pseudocode, flow consistency constraint; "Where it struggles" section.

**Fix:** Add a paragraph after the flow consistency constraint explaining: "This constraint uses pre-computed choice probabilities based on the current network configuration. When the optimizer opens or closes facilities, the true choice probabilities change (closing a facility redistributes its patients to remaining facilities). The standard approach is iterative: solve the MIP with current probabilities, recompute probabilities for the recommended network, re-solve, and repeat until convergence (typically 3-5 iterations). This 'iterative balancing' approach is not shown in the pseudocode for clarity but is essential for solution quality. Without it, the optimizer may recommend closing a facility while simultaneously assuming patients continue to flow there."

---

### 🟡 ARC-2: SageMaker Training Job Is a Misfit for Solver Execution

**Finding:** The recipe uses SageMaker Training Jobs to execute the MIP solver. SageMaker Training Jobs are designed for ML model training: they expect training data in specific channels, produce model artifacts, and report training metrics. Using them for optimization solver execution works (you can run arbitrary code in a custom container) but is architecturally awkward. The solver doesn't produce a "model artifact" in the ML sense; it produces a solution file. The training job's built-in checkpointing, early stopping, and hyperparameter tuning features are irrelevant.

SageMaker Processing Jobs are a better fit: they're designed for arbitrary compute tasks (data processing, evaluation, any batch computation) without the ML training semantics. The recipe already uses Processing Jobs for demand forecasting but switches to Training Jobs for solver execution without explaining why.

**Location:** Architecture diagram; "Why These Services" section (SageMaker paragraph); Step 4 pseudocode.

**Fix:** Either (a) switch to SageMaker Processing Jobs for solver execution and explain that Processing Jobs are the right abstraction for non-ML compute tasks, or (b) add a sentence explaining why Training Jobs were chosen over Processing Jobs (e.g., "Training Jobs support Spot instances with automatic checkpointing, which is valuable for long-running solver executions that might be interrupted"). If the reason is Spot instance support, say so explicitly.

---

### 🟡 ARC-3: No Discussion of Model Infeasibility Handling

**Finding:** The optimization model has many constraints (budget, capacity, demand satisfaction, minimum volume, workforce, CON, service dependencies). It is entirely possible that no feasible solution exists: the budget is too small to meet all demand satisfaction and minimum volume constraints simultaneously, or workforce constraints make it impossible to staff the services needed to satisfy demand.

When a MIP solver encounters an infeasible model, it returns an infeasibility status. The recipe's Step 4 pseudocode calls `solve()` and extracts results without checking for infeasibility. In practice, infeasibility is common during model development and scenario analysis (e.g., the "low budget" scenario might be infeasible).

**Location:** Step 4 pseudocode, after `solve()` call.

**Fix:** Add infeasibility handling after the solve call: "If the solver returns INFEASIBLE, compute an Irreducible Infeasible Subsystem (IIS) to identify which constraints conflict. Most commercial solvers (Gurobi: `model.computeIIS()`, CPLEX: `conflict refiner`) provide this automatically. Present the conflicting constraints to decision-makers: 'The budget constraint and the minimum volume constraint for cardiac surgery at Location X cannot both be satisfied. Either increase the budget by $Y or relax the minimum volume threshold.' This is often the most valuable output of the optimization: it makes hidden tradeoffs explicit."

---

### 🟡 ARC-4: Cost Estimate Omits Redshift Serverless as an Alternative

**Finding:** The cost estimate specifies "Redshift ra3.xlplus (2 nodes): ~$1,500/month" as a fixed cost. For a strategic planning workload that runs quarterly (or at most monthly), a provisioned Redshift cluster running 24/7 is wasteful. The analytical queries for demand forecasting and gravity model estimation likely run for a few days per quarter, not continuously.

**Location:** Prerequisites table, "Cost Estimate" row.

**Fix:** Add Redshift Serverless as the recommended option for this workload pattern: "For quarterly optimization runs, Redshift Serverless (pay-per-query) is more cost-effective than a provisioned cluster. Estimated cost: $50-$200 per optimization cycle versus $1,500/month for always-on provisioned. Use provisioned only if the analytics warehouse serves other continuous workloads." This also aligns better with the stated cost range of "$2,000-$15,000 per optimization run" in the recipe header.

---

### 🔵 ARC-5: Step Functions Standard vs Express Not Discussed

**Finding:** The recipe uses Step Functions for pipeline orchestration but doesn't specify Standard or Express Workflows. For a multi-hour optimization pipeline (the recipe states 12-24 hours for the full pipeline), Standard Workflows are required (Express Workflows have a 5-minute maximum duration). This is likely obvious to experienced AWS users but worth stating explicitly given the recipe's educational purpose.

**Location:** "Why These Services" section, Step Functions paragraph.

**Fix:** Add: "Use Step Functions Standard Workflows (not Express) for the optimization pipeline. The full pipeline runs 12-24 hours, well beyond Express Workflows' 5-minute limit. Standard Workflows also provide execution history for debugging failed runs."

---

## Networking Review

### 🟡 NET-1: VPC Endpoint List Is Incomplete for the Stated Architecture

**Finding:** The prerequisites state "SageMaker jobs in private subnets with VPC endpoints for S3 and CloudWatch." The architecture also uses Step Functions, Lambda, Glue, Redshift, and QuickSight. If SageMaker jobs need to invoke or be invoked by Step Functions, the Step Functions VPC endpoint is needed. If Lambda functions in the VPC need to call SageMaker APIs, the SageMaker API endpoint is needed.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Expand the VPC endpoint list: "VPC endpoints required: S3 (Gateway), CloudWatch Logs (Interface), SageMaker API (Interface), SageMaker Runtime (Interface), Step Functions (Interface), Glue (Interface), Redshift (Interface or use Redshift in the same VPC), KMS (Interface). Lambda functions that call AWS services from within the VPC require these endpoints or a NAT Gateway."

---

### 🔵 NET-2: No Egress Discussion for QuickSight

**Finding:** QuickSight is a managed service that runs outside the customer's VPC. When QuickSight connects to Redshift or S3 for data, it uses either a public connection or a VPC connection (QuickSight VPC Connection feature). The recipe doesn't discuss how QuickSight accesses the data sources, which are in private subnets.

**Location:** Architecture diagram; "Why These Services" section.

**Fix:** Add: "Configure a QuickSight VPC Connection to access Redshift in the private subnet. For S3 access, QuickSight uses its service role and does not require VPC connectivity (S3 access is via IAM, not network path). Ensure the QuickSight service role has KMS decrypt permissions for the S3 buckets containing optimization results."

---

## Voice Review

### 🟡 VOI-1: Two Instances of Documentation-Voice Creep

**Finding:** Two sentences slip into documentation register:

1. "The optimization approach doesn't replace human judgment on these decisions. It structures the analysis so that judgment is applied to the right tradeoffs rather than lost in a fog of competing anecdotes." -- The second sentence is fine, but "The optimization approach doesn't replace human judgment on these decisions" reads like a product disclaimer rather than an engineer explaining something.

2. "This is one of the hardest problems in this entire book." -- This is good voice, but it's immediately followed by "The solution space is enormous, the constraints are politically charged, and the objective function is genuinely multi-dimensional." which is slightly formal/academic.

**Location:** The Problem section, paragraph 4; The Problem section, final paragraph.

**Fix:** (1) Rephrase to something like: "None of this replaces the judgment calls. It just makes sure those judgment calls happen on the actual tradeoffs instead of getting lost in a fog of competing anecdotes." (2) The second instance is borderline and could stay as-is; it's a minor style note, not a requirement.

---

### ✅ VOI-2: Vendor Balance Is Excellent

The 70/30 split is well-maintained. The Technology section (approximately 60% of the recipe's prose) is completely vendor-agnostic. AWS services appear only in the implementation section. A reader using Google OR-Tools on GCP or Azure's optimization services would learn the full conceptual framework from the first half.

---

### ✅ VOI-3: No Em Dashes Found

Zero em dashes in the entire recipe. Colons, periods, and parentheses are used correctly throughout.

---

### ✅ VOI-4: The Problem Section Is Engaging

The opening scenario (CEO staring at a map, $400M capital budget, state attorney general) is vivid and specific. It makes the reader feel the stakes. The "spreadsheet and good intentions" line is exactly the right tone.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. The security, architecture, and networking findings are complementary rather than conflicting.

**Priority resolution:** The most impactful finding is ARC-1 (gravity model linearization). A reader who implements the flow consistency constraint as written without the iterative balancing approach will get solutions that are internally inconsistent. This is the kind of subtle error that produces confident-looking but wrong recommendations. However, it's a medium-severity issue because the recipe does mention the approximation in "Where it struggles" and the pseudocode is explicitly simplified for educational purposes.

SEC-2 (BAA boundary ambiguity) and SEC-3 (solver licensing) are both medium because they affect real deployments but don't create immediate HIPAA violations if the reader follows the general guidance to "put everything under BAA."

---

## Stage 3: Synthesized Feedback

**Verdict: PASS**

The recipe is architecturally sound, educationally excellent, and appropriately scoped for a strategic planning use case. No critical findings. The medium-severity findings are refinements that improve production-readiness but don't represent fundamental flaws in the approach.

---

## Prioritized Findings

| ID | Severity | Expert | Location | Title |
|----|----------|--------|----------|-------|
| SEC-1 | 🟡 Medium | Security | Prerequisites, IAM Permissions | QuickSight `*` permission violates least-privilege |
| SEC-2 | 🟡 Medium | Security | Prerequisites, BAA row; Step 2 | BAA boundary between PHI and aggregate data is ambiguous |
| SEC-3 | 🟡 Medium | Security | Prerequisites, Solver Licensing | Solver licensing in no-internet VPC not addressed |
| ARC-1 | 🟡 Medium | Architecture | Step 3, flow constraint | Gravity model linearization not explained; iterative balancing missing |
| ARC-2 | 🟡 Medium | Architecture | Why These Services, SageMaker | Training Job vs Processing Job choice unexplained |
| ARC-3 | 🟡 Medium | Architecture | Step 4, after solve() | No infeasibility handling or IIS discussion |
| ARC-4 | 🟡 Medium | Architecture | Prerequisites, Cost Estimate | Redshift provisioned is wasteful for quarterly workload |
| NET-1 | 🟡 Medium | Networking | Prerequisites, VPC row | VPC endpoint list incomplete for stated architecture |
| VOI-1 | 🟡 Medium | Voice | The Problem, paragraph 4 | Two sentences with documentation-voice register |
| SEC-4 | 🔵 Low | Security | Prerequisites, CloudTrail | Decision-level audit not captured by CloudTrail alone |
| ARC-5 | 🔵 Low | Architecture | Why These Services, Step Functions | Standard vs Express Workflows not specified |
| NET-2 | 🔵 Low | Networking | Architecture diagram | QuickSight VPC Connection not discussed |

---

## Specific Praise

### ✅ Technology Section Is Best-in-Class

The explanation of facility location problems, MIP formulation, gravity models, and multi-objective optimization is genuinely educational. A reader with no OR background would understand the problem class, the solution approach, and the tradeoffs. The solver selection guidance (with honest cost/performance comparisons between commercial and open-source) is practical and actionable. This section alone justifies the recipe's existence.

### ✅ Constraint Modeling Reflects Real Healthcare Operations

The constraints in Step 3 (minimum volume thresholds, service line dependencies, CON requirements, workforce limits) reflect actual operational realities. The minimum volume constraint is particularly well-motivated: the recipe explains why spreading volume too thin creates quality and accreditation problems, not just financial ones. The "Honest Take" section's observation that minimum volume constraints are often the binding ones is a genuine insight that experienced health system planners will recognize.

### ✅ Scenario Analysis Framing Is Executive-Ready

The distinction between "robust decisions" (good in all futures) and "contingent decisions" (scenario-dependent) in the expected results output is exactly how capital allocation decisions should be presented to boards. The sample output JSON demonstrates this clearly. An executive reading this recipe would understand what they'd get from the system.

### ✅ Honest Take Is Genuinely Honest

The four-point honest take (data quality, gravity model calibration, politics, uncertainty) is not hedging or false modesty. These are the actual failure modes of health system network design projects. The advice to "start with a single service line" before tackling full network design is practical wisdom that saves organizations from over-scoping their first attempt.

### ✅ Variations Are Substantive

The three variations (dynamic staging, competitive response, equity constraints) are not throwaway bullet points. Each describes a real extension with enough detail to understand the formulation change required. The equity-constrained optimization variation (Gini coefficient on travel times across income quintiles) is particularly relevant given current regulatory focus on health equity.

---

*Review complete. Recipe 14.10 is the strongest recipe in Chapter 14 from an educational standpoint. The medium-severity findings are refinements for production deployments, not structural problems. Recommended for publication with the noted improvements.*
