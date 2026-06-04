# Expert Review: Recipe 14.5 - Operating Room Block Scheduling

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter14.05-operating-room-block-scheduling.md`

---

## Overall Assessment

This is a strong recipe that teaches OR block scheduling optimization from first principles. The problem statement is outstanding: it puts you in the Monday morning war room and makes you feel the political dysfunction of committee-based scheduling. The technology section does an excellent job explaining MIP formulation (decision variables, hard constraints, soft constraints, objective functions) in a way that a non-OR-researcher can follow. The solver selection guidance (MIP vs. CP, commercial vs. open-source) is practical and accurate. The dual-mode architecture (batch solver for quarterly template generation, lightweight Lambda for real-time block release) is the right decomposition.

The "Honest Take" section is one of the best in the chapter. The insight that "the math is the easy part" and that institutional buy-in takes 6-12 months is exactly the kind of wisdom that separates a textbook from a cookbook. The recommendation to start with block release as the non-controversial quick win is sound operational strategy.

Issues found are primarily around incomplete security specifications for the schedule approval workflow, an architectural gap in the solver container's network access, incomplete VPC endpoint guidance, and a few missing items noted in the Additional Resources section (TODO placeholders). No CRITICAL findings.

**Verdict: PASS**

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

BAA requirement is clearly specified with the correct rationale: schedule data may reference surgeon names and service lines, and if linked to patient data for utilization analysis, PHI applies. Encryption at rest (S3 SSE-KMS, DynamoDB encryption) and in transit (TLS) are specified. CloudTrail is explicitly called out for auditing "all schedule modifications for compliance and dispute resolution," which is the right framing for a politically sensitive system. The prerequisites state "Never use real surgeon names in dev environments," which demonstrates awareness that provider identities are sensitive even when not PHI. IAM permissions are listed with specific actions.

#### Issue S1: No Access Control Model for Schedule Approval Workflow (HIGH)

**Location:** Architecture section, "Operations" subgraph; Step 4 pseudocode (evaluate_schedule); The Honest Take, "Change management workflow"

**The problem:** The recipe describes a workflow where the solver produces a proposed schedule, a human reviews it via QuickSight dashboard, and the approved schedule flows into DynamoDB. But there is no discussion of who can approve a schedule change, how that approval is authenticated and recorded, or how the transition from "proposed" to "approved" is secured. In a hospital where block schedule changes cost departments millions in revenue and create political conflict, unauthorized modification of the approved schedule (or bypassing the approval step entirely) is a significant risk.

The Honest Take mentions "a structured approval workflow: notification to the affected department chair, appeal period, executive sign-off" but this is listed as a "what's still missing for production" item rather than being addressed in the architecture. For a recipe at "Production" phase, the approval path should be part of the design.

**Suggested fix:** Add a brief section in the AWS implementation addressing schedule approval: API Gateway endpoint for approval actions authenticated via IAM or Cognito with role-based access (only surgical governance committee members can approve). DynamoDB should store schedule state transitions (proposed, under_review, approved, active) with the approver's identity and timestamp. CloudTrail captures the approval event. This doesn't need to be elaborate, but the approval path should be a first-class architectural element, not a "still missing" footnote.

#### Issue S2: Solver Container Image Security Not Addressed (MEDIUM)

**Location:** Step 3 pseudocode, `container_image: "solver-image:latest"`; Prerequisites

**The problem:** The solver runs as a container on AWS Batch. The recipe specifies `container_image: "solver-image:latest"` but doesn't discuss: Where is this image stored? (ECR, presumably.) Is it scanned for vulnerabilities? Does it pull solver binaries from external sources at runtime? Commercial solvers like Gurobi require license validation that may involve outbound network calls to license servers. The solver container has read access to the model file (which encodes institutional constraints and service names) and write access to S3 for the solution output. A compromised container image could exfiltrate sensitive operational data.

**Suggested fix:** Add a note in prerequisites or the Batch section: "Store the solver container image in Amazon ECR with image scanning enabled. Pin the image to a digest (not `:latest`) for reproducibility. If using a commercial solver requiring license validation, configure the Batch compute environment's security group to allow outbound HTTPS only to the specific license server endpoint. The solver container should have a minimal IAM role: read from the specific S3 model input prefix, write to the specific S3 solution output prefix, nothing else."

#### Issue S3: Block Release Decision Lacks Audit Trail for Fairness Disputes (MEDIUM)

**Location:** Step 5 pseudocode, `handle_block_release`; DynamoDB update

**The problem:** The block release engine automatically assigns released blocks to the highest-scoring candidate service. The DynamoDB update records the assignment but doesn't capture the full decision context: which services were considered, what scores they received, and why the winner beat the alternatives. In the politically charged environment the recipe describes, services that don't receive released blocks will dispute the fairness of the algorithm. Without a complete audit trail of each decision, the institution can't demonstrate that the release engine is unbiased.

The recipe stores `assigned_service`, `assignment_type`, `released_from`, and `assigned_at`. It does not store the candidate list, their scores, or the scoring function version.

**Suggested fix:** Add to the DynamoDB update in Step 5: store the full candidate list with scores, the scoring function version/hash, and a timestamp. Alternatively, write a decision audit record to a separate DynamoDB table or S3 (for cheaper long-term storage). Add a note: "Service chiefs will ask 'Why did orthopedics get that released block and not us?' You need to be able to answer that question with data for every single release decision."

#### Issue S4: No Discussion of Data Retention for Historical Case Data (LOW)

**Location:** Step 1, `extract_demand_data`; Prerequisites, Sample Data

**The problem:** The demand forecasting step pulls 12-24 months of surgical case history. If this data includes patient-level records (case IDs, surgeon names, procedure types linked to dates), it contains information that could be used to re-identify patients. The recipe doesn't discuss data retention policies, de-identification of historical data used for modeling, or whether aggregated service-level metrics (which don't contain PHI) are sufficient for the demand forecast.

**Suggested fix:** Add a note in Step 1: "For the demand forecast, you need per-service aggregate metrics (weekly volume, duration distributions, cancellation rates), not individual case records. If your data lake stores case-level records, aggregate at query time and don't persist patient-level data in the optimization pipeline's S3 bucket. If case-level data is needed for duration distribution analysis, apply de-identification (remove patient identifiers, generalize dates to week-level) before storing in the optimization pipeline."

---

### Architecture Expert Review

#### What's Done Well

The dual-mode architecture (heavyweight batch solver for quarterly generation, lightweight Lambda for block release) is the correct decomposition. The recipe correctly identifies that these are fundamentally different problem sizes requiring different compute models. AWS Batch for the solver is the right choice: spin up compute, run for 5-30 minutes, terminate. No idle cost between quarterly runs.

The model formulation is well-structured: clear decision variables, properly categorized constraints (hard vs. soft), and a weighted objective function with explicitly labeled policy weights. The explanation of why brute force is impossible (15^200 combinations) effectively motivates the need for a solver. The solver selection guidance (MIP for block scheduling because the objective is naturally linear; CP for case sequencing where temporal ordering matters) is accurate and helpful.

The performance benchmarks are realistic. A 20-OR, 15-service problem solving in 5-30 minutes with < 2% optimality gap matches what HiGHS and CBC achieve on problems of this size. The 2-second block release decision time is achievable with a simple scoring function in Lambda.

#### Issue A1: No Solver Timeout Fallback Strategy (HIGH)

**Location:** Step 3 pseudocode, `run_solver`; "Why This Is Hard" section

**The problem:** The recipe correctly notes that "A bad formulation can run for hours without finding a provably optimal solution." Step 3 sets a `time_limit_seconds` for the solver. But if the solver hits the time limit without finding an acceptable solution (e.g., optimality gap > 10%, or worse, no feasible solution found within the time limit), the only handling is `raise error "Solver failed."` There's no fallback strategy.

In practice, solvers can find a feasible but suboptimal solution quickly, then spend hours trying to prove optimality. If the time limit is hit with a 15% gap, that solution may still be far better than the current manual schedule. The recipe should distinguish between: (1) solver found no feasible solution (infeasible model, need to relax constraints), (2) solver found a solution but couldn't prove optimality within the time limit (probably acceptable), and (3) solver crashed or ran out of memory.

**Suggested fix:** Modify Step 3 to handle solver outcomes more granularly:
- If optimality gap <= 5%: proceed normally (near-optimal).
- If gap is 5-15%: proceed but flag for review ("best we could find in the time allowed; consider running longer or relaxing soft constraints").
- If gap > 15% or no feasible solution: check constraint relaxation (which hard constraints are binding?), alert the operations team, and don't auto-replace the current schedule.
- Add a note: "Most hospital-scale problems converge to < 2% gap in 10-30 minutes. If your solver is struggling, the issue is usually the formulation (too many symmetry-equivalent solutions, weak LP relaxation) rather than the compute. Try adding symmetry-breaking constraints or decomposing into stages."

#### Issue A2: No Concurrency Protection for Block Release Decisions (MEDIUM)

**Location:** Step 5 pseudocode, `handle_block_release`; DynamoDB update

**The problem:** The block release engine reads the current state (waitlist, room capabilities), scores candidates, and writes the assignment to DynamoDB. If two blocks are released simultaneously (e.g., two surgeons cancel at the same time near the deadline), two Lambda invocations could independently score the same waitlisted cases and assign the same service to both blocks without considering that the service now has two new blocks (which might exceed its staffing capacity). There's a race condition between read-score-write across concurrent invocations.

**Suggested fix:** Add a note on concurrency handling: "Use DynamoDB conditional writes (PutItem with ConditionExpression ensuring the block is still in 'released' state) to prevent double-assignment. If two release events fire simultaneously, process them sequentially using a DynamoDB Streams trigger with a single-concurrent-execution Lambda, or use Step Functions to serialize release decisions. The scoring function should read the latest assignment state (including any assignments made in the last few seconds) before scoring."

#### Issue A3: SageMaker Endpoint Cost May Be Disproportionate (MEDIUM)

**Location:** Prerequisites, Cost Estimate; "Why These Services" section

**The problem:** The cost estimate lists "SageMaker endpoint: ~$100-400/month depending on forecast complexity." For a system that runs the full optimization quarterly and the demand forecast is consumed only during the model-building phase (Step 1 feeds into Step 2), a persistent SageMaker endpoint is expensive relative to its utilization. The endpoint is idle for ~99% of the time (between quarterly runs and occasional ad-hoc what-if scenarios).

The recipe's total cost estimate is "$200-800/month," and the SageMaker endpoint represents 50-100% of that range. This is a significant portion of the budget for a component used infrequently.

**Suggested fix:** Add a note: "For quarterly-only forecasting, consider SageMaker Serverless Inference (scales to zero between invocations) or batch transform jobs (run the forecast as a batch job during the quarterly cycle, no persistent endpoint). A persistent endpoint only makes sense if you're also using the forecast model for daily block release scoring or real-time utilization dashboards. The cost estimate above assumes a persistent endpoint; serverless or batch alternatives could reduce this to ~$10-30/month."

#### Issue A4: No Monitoring or Alerting for Schedule Drift (LOW)

**Location:** Architecture diagram; "Expected Results" section

**The problem:** The recipe generates a schedule quarterly and handles block releases in real-time, but doesn't discuss how to detect when the actual utilization diverges significantly from the predicted utilization. If orthopedics was predicted to utilize 80% of their blocks but is actually at 55% three weeks into the quarter, the schedule is underperforming. Without monitoring, the institution won't know until the next quarterly review.

**Suggested fix:** Add a brief note in the architecture or Variations section: "Deploy a CloudWatch dashboard (or QuickSight report) that compares predicted vs. actual utilization weekly. Alert if any service's actual utilization falls more than 15 percentage points below prediction for two consecutive weeks. This early-warning system lets you investigate (has the surgeon's clinic schedule changed? Are cases being diverted to another facility?) and consider a mid-quarter adjustment."

---

### Networking Expert Review

#### What's Done Well

The prerequisites specify VPC for production with Lambda and Batch running inside VPC. The architecture keeps the solver compute and operational database within the VPC boundary. TLS is implied for all API calls (standard AWS SDK behavior). The data flow is clean: S3 for staging (within-region, no cross-region transfer needed for single-site), DynamoDB for operational state, API Gateway for external exposure to EHR/scheduling systems.

#### Issue N1: VPC Endpoints Not Specified (MEDIUM)

**Location:** Prerequisites table, VPC row; Architecture diagram

**The problem:** The prerequisites state "Production: Lambda and Batch in VPC with endpoints for S3, DynamoDB" but lists only two endpoints. The architecture uses S3, DynamoDB, SageMaker, EventBridge, CloudWatch Logs, and Batch API. Lambda functions in a VPC cannot reach these services without VPC endpoints or a NAT gateway. The Batch compute environment similarly needs outbound access to pull the container image from ECR and write results to S3.

Listing only "endpoints for S3, DynamoDB" suggests the other services would use a NAT gateway, which creates an egress path for any data in the VPC (potential PHI data exfiltration vector) and adds ~$30-45/month per AZ in NAT gateway costs.

**Suggested fix:** Expand the VPC row to list all required endpoints: "S3 (gateway), DynamoDB (gateway), SageMaker Runtime (interface), EventBridge (interface), CloudWatch Logs (interface), ECR (interface, for Batch image pull), KMS (interface), STS (interface, for Lambda/Batch role assumption). Budget ~$50-70/month for interface endpoints in a 3-AZ deployment. If using a commercial solver with license validation, a restricted NAT gateway or specific endpoint for the license server may be needed."

#### Issue N2: Batch Compute Environment Network Configuration Not Specified (MEDIUM)

**Location:** Step 3 pseudocode, Batch job submission; "Why These Services" section

**The problem:** AWS Batch compute environments can run in VPC with specific subnet and security group configurations. The recipe doesn't specify whether the Batch compute environment should be in a private subnet (no internet access) or a public subnet. If the solver container needs to validate a commercial license (Gurobi, CPLEX), it needs outbound HTTPS to the license server. If it only needs S3 access, it should be in a private subnet with only VPC endpoints.

The recipe also doesn't mention the ECR image pull path. Batch needs to pull the container image from ECR, which requires either a NAT gateway or ECR VPC endpoints (both `ecr.api` and `ecr.dkr` plus S3 gateway for the image layers).

**Suggested fix:** Add a note in the Batch section: "Place the Batch compute environment in private subnets. Configure ECR VPC endpoints (`com.amazonaws.{region}.ecr.api` and `com.amazonaws.{region}.ecr.dkr`) and S3 gateway endpoint for image layer pulls. The solver container's security group should allow outbound to VPC endpoints only (restrict to specific endpoint security groups). If using a commercial solver requiring license validation, add a NAT gateway or specific route for the license server CIDR range only."

#### Issue N3: API Gateway to EHR Integration Path Unclear (LOW)

**Location:** Architecture diagram, "Operations" subgraph; API Gateway role

**The problem:** The architecture shows "API Gateway: Schedule API" connecting to "EHR / Scheduling System." This is the path by which the approved schedule flows into Epic OpTime, Cerner SurgiNet, or whatever scheduling system the hospital uses. The recipe doesn't discuss whether this is a push (the optimization system pushes the schedule to the EHR) or a pull (the EHR polls for updates). It also doesn't specify the network path: is the EHR on-premises (requiring the API Gateway to be private, accessed via Direct Connect/VPN) or cloud-hosted?

**Suggested fix:** Add a brief note: "The EHR integration is typically a pull model: the scheduling system queries the Schedule API for the current block template. For on-premises EHRs, deploy a private API Gateway endpoint accessible via Direct Connect or Site-to-Site VPN. For cloud-hosted EHRs, consider VPC peering with a PrivateLink endpoint. The integration is institution-specific and is often the hardest part of the project (as noted in the Honest Take)."

---

### Voice Reviewer

#### What's Done Well

The voice is excellent throughout. The opening paragraph ("Every Monday morning, the OR scheduling office is a war room") is vivid, specific, and sets the right energy. The escalation through stakeholder perspectives (orthopedics, cardiothoracic, general surgery, chief of surgery, CFO, nurses) paints a complete picture. The payoff line ("This is a mathematical optimization problem pretending to be a political one. Let's make it a mathematical one for real.") is perfect CC energy.

The technology section maintains a teaching cadence without being condescending. The mathematical formulation is introduced accessibly (decision variables as a yes/no matrix, constraints as things that must be true vs. things we want). The explanation of why brute force fails (15^200 combinations, "more than atoms in the universe") is effective science communication.

The "Honest Take" is standout. "The math is the easy part," the advice to start with a what-if tool, and the block release as non-controversial quick win are all genuine operational insights delivered with the right tone. The utilization ceiling observation (75% target is arbitrary; 90% utilized with frequent overtime is worse than 75% that finishes on time) is the kind of nuanced thinking that distinguishes this recipe from an operations research textbook.

The 70/30 vendor balance is well-maintained. The entire Technology section and General Architecture Pattern (easily 65-70% of the recipe) are vendor-agnostic. A reader on GCP (using Cloud Run + custom solver) or Azure (using Azure Batch + custom solver) would learn the full optimization approach without needing to translate.

#### Issue V1: Zero Em Dashes Found

No em dashes anywhere in the recipe. Clean.

#### Issue V2: Two TODO Placeholders in Additional Resources (MEDIUM)

**Location:** Additional Resources section, "AWS Sample Repos" and "Operations Research in Healthcare"

**The problem:** Two TODO items appear in the published recipe:
- `<!-- TODO (TechWriter): Find and verify relevant aws-samples repos for optimization/scheduling patterns (RECIPE-GUIDE requires 3-5 sample repos per recipe) -->`
- `<!-- TODO (TechWriter): Verify and add link for INFORMS Healthcare journal or relevant OR in healthcare publication -->`

The RECIPE-GUIDE requires 3-5 sample repos per recipe. The recipe currently has zero verified sample repos. This is a structural gap against the recipe guide requirements, not just a cosmetic placeholder.

**Suggested fix:** The writer needs to search for and verify relevant aws-samples repos (e.g., `amazon-sagemaker-examples` for forecasting patterns, any OR-Tools or optimization examples in AWS contexts, Batch job submission patterns). The INFORMS Healthcare conference proceedings or the journal "Operations Research for Health Care" are legitimate references that should be verified and linked. This is a blocking item per the RECIPE-GUIDE.

#### Issue V3: "What's Still Missing for Production" Could Be Integrated Better (LOW)

**Location:** The Honest Take, final bullet list

**The problem:** The four "What's still missing" items (surgeon preferences, seasonality, change management workflow, EHR integration) are listed as a bullet-point appendage after the main honest take prose. This reads slightly more like a documentation completeness checklist than CC's voice. The first three paragraphs of the Honest Take are perfectly voiced (passionate, personal, strategic). The final list loses some of that energy.

**Suggested fix:** Minor voice polish. Weave the missing items into the narrative or preface the list with something like: "Things I'd build next if I had another quarter:" rather than "What's still missing for production:" The content is correct; it's just the framing that could be slightly warmer.

---

## Stage 2: Expert Discussion

**S1 and the operational context:** The missing access control model for schedule approval (S1) is particularly important given the recipe's own framing of block scheduling as a politically charged process. The recipe eloquently explains that losing blocks creates losers, department chairs will dispute results, and buy-in takes 6-12 months. In that context, a system that allows unauthenticated schedule modifications or lacks a clear approval audit trail would actively undermine institutional trust. S1 is HIGH because the recipe itself establishes why governance matters here.

**A1 and real-world solver behavior:** The solver timeout fallback (A1) is HIGH because the recipe targets a "Production" phase deployment. In production, a solver that returns nothing after hitting a time limit (because the formulation was perturbed by new data) blocks the entire quarterly process. The recipe should teach readers how to handle solver outcomes gracefully, which is a key operational skill.

**A2 and S3 interaction:** The race condition in block release (A2) and the missing audit trail (S3) are related. If concurrent release decisions produce inconsistent assignments, and there's no audit trail explaining why, the resulting disputes become impossible to adjudicate. Fixing both together (sequential processing with full decision logging) addresses both concerns.

**V2 severity:** The TODO items (V2) are marked MEDIUM rather than LOW because the RECIPE-GUIDE explicitly requires 3-5 sample repos per recipe. Having zero verified repos is a structural compliance gap with the book's own specification, not just a polish item.

**N1 and N2 overlap:** VPC endpoints (N1) and Batch network configuration (N2) are related. If the Batch compute environment needs ECR endpoints for image pulls, those same endpoints need to be in the VPC endpoint list. These should be addressed together in a single "production VPC requirements" note.

---

## Stage 3: Synthesized Feedback

**Verdict: PASS**

No CRITICAL findings. Two HIGH findings (below the 3-HIGH threshold for FAIL). The recipe is architecturally well-designed, the optimization formulation is correctly taught, the voice is strong, and the operational wisdom in the Honest Take is genuinely valuable. The issues below improve production-readiness, security governance, and compliance with the book's own formatting requirements. They don't indicate fundamental design flaws.

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Architecture, Operations subgraph; Honest Take | No access control model for schedule approval workflow; proposed-to-approved transition is unsecured in a politically sensitive system where unauthorized changes undermine trust | Add API Gateway + Cognito/IAM for approval actions; store state transitions with approver identity in DynamoDB; capture approval in CloudTrail |
| 2 | HIGH | Architecture | Step 3 pseudocode, solver timeout | Solver hitting time limit returns only "raise error"; no distinction between infeasible model, suboptimal-but-acceptable solution, and crashed solver; blocks quarterly process | Handle outcomes granularly: <=5% gap proceed; 5-15% flag for review; >15% or infeasible alert ops team and don't auto-replace current schedule |
| 3 | MEDIUM | Voice | Additional Resources | Two TODO placeholders for sample repos and OR publications; RECIPE-GUIDE requires 3-5 verified sample repos (currently zero); structural gap against book specifications | Search and verify aws-samples repos for optimization/scheduling patterns; verify INFORMS or OR in Healthcare journal links |
| 4 | MEDIUM | Security | Step 3, container_image | Solver container image uses `:latest` tag with no guidance on image scanning, pinning, or IAM scoping; container has read access to model file containing institutional constraints | Store in ECR with scanning enabled; pin to digest; scope IAM to specific S3 prefixes; restrict outbound to VPC endpoints + license server only |
| 5 | MEDIUM | Security | Step 5, DynamoDB update | Block release audit trail records only the winner; doesn't capture full candidate list, scores, or scoring function version; service chiefs can't verify fairness of automated decisions | Store full candidate list with scores and scoring function version; note that every release decision must be explainable |
| 6 | MEDIUM | Architecture | Step 5, concurrent Lambda invocations | Race condition: simultaneous block releases can double-assign same service or exceed staffing capacity when two Lambdas independently score the same waitlist | Use DynamoDB conditional writes; serialize release decisions via Step Functions or single-concurrency Lambda |
| 7 | MEDIUM | Architecture | Prerequisites, Cost Estimate | SageMaker persistent endpoint ($100-400/month) represents 50-100% of total cost for a model invoked only quarterly; disproportionate spend for utilization | Recommend Serverless Inference or batch transform for quarterly-only forecasting; reduce cost to ~$10-30/month |
| 8 | MEDIUM | Networking | Prerequisites, VPC row | Only S3 and DynamoDB endpoints listed; architecture also needs SageMaker, EventBridge, CloudWatch, ECR, KMS, STS endpoints; missing endpoints cause failures or require expensive NAT gateway | List all required endpoints with cost estimate (~$50-70/month for full set) |
| 9 | MEDIUM | Networking | Step 3, Batch compute environment | No specification of private subnet, security group, or ECR image pull path for Batch; unclear whether solver can reach license server or is internet-isolated | Specify private subnets, ECR VPC endpoints for image pull, restricted security group; add NAT route for license server only if needed |
| 10 | LOW | Security | Step 1, historical case data | Recipe pulls 12-24 months of surgical case history without discussing de-identification or whether aggregate metrics (which avoid PHI) are sufficient for demand forecasting | Add note: aggregate at query time; don't persist patient-level data in optimization pipeline; de-identify if case-level data needed for duration analysis |
| 11 | LOW | Architecture | Architecture overall | No monitoring for schedule performance drift (predicted vs. actual utilization divergence); institution won't know the schedule is underperforming until next quarterly review | Add CloudWatch/QuickSight weekly utilization comparison dashboard; alert if actual drops >15 points below predicted for 2+ weeks |
| 12 | LOW | Networking | Architecture, API Gateway to EHR | Integration path to EHR is shown but not specified (push vs. pull, network path for on-premises vs. cloud EHR) | Add note on private API Gateway for on-premises EHR via Direct Connect; pull model typical |
| 13 | LOW | Voice | The Honest Take, final list | "What's still missing for production" bullet list loses the personal voice energy of the preceding paragraphs; reads slightly like a documentation checklist | Reframe as "Things I'd build next if I had another quarter:" or weave into narrative |

### Priority Actions Before Publication

1. **Fix S1/A1 (HIGH):** Add schedule approval access control model (authenticated approval path, state transitions, audit trail). Add granular solver outcome handling (distinguish infeasible vs. suboptimal vs. crashed). These are the two findings that would cause real problems: one political/governance, one operational.

2. **Fix V2 (MEDIUM, blocking):** Resolve the TODO items in Additional Resources. The RECIPE-GUIDE requires 3-5 verified sample repos. This is a formatting compliance issue that blocks publication per the book's own standards.

3. **Fix S2/S3 + A2 (MEDIUM):** Address container security (image pinning, ECR scanning, IAM scoping) and block release robustness (full audit trail for fairness disputes, concurrency protection). These are the security and operational items that would surface within the first month of production use.

4. **Fix N1/N2 (MEDIUM):** Consolidate VPC endpoint list and Batch network configuration into a single comprehensive "production VPC requirements" section. Readers deploying this in a VPC without the full endpoint list will hit immediate failures.

5. **Fix A3 (MEDIUM):** Add cost optimization note for SageMaker. The current estimate overstates the monthly cost for readers who only need quarterly forecasting.

---

*Review complete. Recipe 14.5 is a well-crafted entry that successfully teaches constrained optimization for OR block scheduling to a mixed technical audience. The problem framing is visceral and politically aware, the mathematical formulation is accessible without sacrificing rigor, the dual-mode architecture (batch + real-time) is well-motivated, and the Honest Take delivers the kind of strategic operational advice ("start with block release as the quick win") that readers can't get from a textbook. The issues above address production governance, solver resilience, and book formatting compliance, but the recipe's educational core is solid.*
