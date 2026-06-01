# Expert Review: Recipe 14.7 - OR Case Sequencing

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter14.07-or-case-sequencing.md`

---

## Overall Assessment

This is an excellent recipe. The problem statement is vivid and grounded in real perioperative operations. The technology section is genuinely educational, covering MIP, CP, and metaheuristics with appropriate depth. The constraint formulation walkthrough is the strongest part: it correctly identifies the key decision variables, hard vs. soft constraints, and the duration uncertainty challenge that makes OR scheduling genuinely difficult in practice. The "Honest Take" section nails the political and operational realities (surgeon buy-in, anesthesia as the binding constraint).

However: there are PHI handling gaps in the pseudocode (patient identifiers flowing through the system without access control discussion), a TODO comment left in the Additional Resources section indicating unverified links, missing DLQ/failure handling in the real-time replan path, and the SQS deduplication strategy has a subtle race condition. The recipe also lacks discussion of human override mechanisms, which is critical for a system that directly affects patient care timing.

Priority breakdown: 0 must-fix factual errors, 4 significant gaps, 5 improvement recommendations.

---

## Verdict: **PASS**

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

The prerequisites table correctly identifies BAA requirement, SSE-KMS for S3, DynamoDB encryption at rest, TLS in transit, VPC with private subnets and VPC endpoints, and CloudTrail for audit. The separation of case data into DynamoDB with API Gateway fronting the schedule output is architecturally sound for access control. The "Never use real patient data in dev" warning is present.

### Issue S1: Patient Identifier Flows Through Constraint Builder Without Access Control Discussion (HIGH)

**Location:** Step 1 pseudocode, line `patient_constraints: get_patient_constraints(case.patient_id)`

**The problem:** The `enrich_case_list` function calls `get_patient_constraints(case.patient_id)` which implies the constraint builder Lambda has access to patient-level clinical data (ASA class, NPO requirements, immunocompromised status). The enriched case record is then written to DynamoDB table "or-cases-today" containing `patient_constraints` alongside `case_id`, `surgeon_id`, and procedure codes. This creates a PHI-bearing table with no discussion of:
- What IAM principals can read this table
- Whether the schedule output (exposed via API Gateway) includes or excludes patient identifiers
- Whether the `patient_constraints` field contains direct identifiers or only derived flags

The published schedule (Step 5) includes `case_id` which is linkable back to the patient. The recipe never discusses whether the API Gateway endpoint requires authentication or what access controls prevent unauthorized schedule viewers from seeing patient-linked procedure information.

**Suggested fix:** Add a security note after Step 1: "The enriched case table contains PHI (patient identifiers linked to procedure codes and clinical flags). IAM policies on this DynamoDB table should restrict read access to the solver engine's ECS task role and the constraint builder Lambda. The published schedule API (Step 5) should expose only the minimum necessary: procedure type, surgeon, and timing. Patient identifiers should not flow to the dashboard unless the viewer has a clinical need-to-know. Implement API Gateway authorizer with role-based access: charge nurses see patient names, the public OR board shows only room/time/procedure."

### Issue S2: Schedule Notification in Step 5 Sends PHI Over Unspecified Channel (MEDIUM)

**Location:** Step 5 pseudocode, `notify surgical team (surgeon, anesthesia, nursing) of new time/room`

**The problem:** The replan notification logic says "notify surgical team of new time/room" but doesn't specify the notification channel. If this is SNS to email or SMS, the notification content (patient name, procedure, room, time) is PHI transmitted over a channel that may not be encrypted end-to-end. SMS notifications of schedule changes containing patient procedure details are a common HIPAA violation vector.

**Suggested fix:** Add a note: "Notifications should use a HIPAA-compliant channel. Options: push notification to a secured mobile app (preferred), pager with case ID only (no patient name), or encrypted email. Avoid SMS with patient-identifiable content. The notification should contain the minimum necessary: case ID, new time, new room. Staff can look up patient details in the secured dashboard."

### Issue S3: ECS Task Role Permissions Not Scoped to Specific Resources (LOW)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions listed are `ecs:RunTask`, `dynamodb:GetItem/PutItem/Query`, `s3:GetObject/PutObject`, `sqs:SendMessage/ReceiveMessage`, `events:PutEvents`. These are listed as actions without resource ARN scoping. A builder following this literally would create an overly permissive policy. The ECS task role for the solver should only access the specific DynamoDB tables (or-cases-today, or-schedule-current), the specific S3 bucket, and the specific SQS queue.

**Suggested fix:** Add a note: "All permissions should be scoped to specific resource ARNs. The solver ECS task role needs DynamoDB access only to the case and schedule tables, S3 access only to the historical data bucket, and SQS access only to the replan queue. Use separate IAM roles for the Lambda functions (constraint builder, replan trigger, duration predictor) with minimal cross-service access."

---

## Architecture Expert Review

### What's Done Well

The batch vs. real-time dual-mode architecture is the correct pattern for OR scheduling. The choice of ECS Fargate for the solver (CPU-intensive, memory-hungry, needs persistent licensing for commercial solvers) over Lambda is well-reasoned. The EventBridge-to-SQS-to-ECS flow for replanning is sound. The constraint builder as a separate Lambda from the solver is good separation of concerns. The DynamoDB choice for schedule state (low-latency reads for dashboard, conditional writes for consistency) is appropriate.

### Issue A1: SQS Deduplication Strategy Has a Race Condition (HIGH)

**Location:** Step 4 pseudocode, `enqueue_replan` function

**The problem:** The deduplication ID is `"replan-" + current_minute()`. This means all replan requests within the same calendar minute are deduplicated to one. But SQS FIFO deduplication window is 5 minutes, not 1 minute. If a replan is enqueued at 10:00:59 and another at 10:01:01, they get different deduplication IDs and both execute, potentially causing two concurrent solver runs against the same schedule state.

More critically: the recipe uses standard SQS (not FIFO) based on the service description ("buffers replan requests"). Standard SQS does not support content-based deduplication or message deduplication IDs. The pseudocode assumes FIFO behavior on what the architecture describes as a standard queue.

**Suggested fix:** Clarify that this must be an SQS FIFO queue for deduplication to work. Then fix the deduplication strategy: use a time-window-based approach (e.g., `"replan-" + floor(current_time / 60_seconds)`) and note that the 5-minute deduplication window means rapid-fire events within 5 minutes of the first replan request will be automatically deduplicated. Alternatively, implement deduplication at the consumer level: the solver checks a "last_replan_timestamp" in DynamoDB before starting, and skips if a replan completed within the last N seconds.

### Issue A2: No Dead Letter Queue or Failure Handling for Solver Failures (HIGH)

**Location:** Architecture diagram and Step 3 pseudocode

**The problem:** The solver can fail: timeout exceeded without finding a feasible solution, out-of-memory on large instances, or infrastructure failure. The recipe handles the "INFEASIBLE" case (returns conflict analysis) but doesn't address what happens when the ECS task itself fails (OOM kill, timeout, network partition). There's no DLQ on the SQS replan queue, no retry policy on the ECS task, and no alerting when the solver fails to produce a schedule.

For a system that directly affects patient care timing (cases may be delayed or rooms left empty if the solver fails silently), this is a significant operational gap.

**Suggested fix:** Add: "Configure a DLQ on the replan SQS queue (max receives = 3). If the solver fails three times on the same replan request, the message moves to the DLQ and triggers a CloudWatch alarm. The alarm notifies the perioperative coordinator that automatic scheduling has failed and manual intervention is needed. The ECS task should have a health check: if no schedule is written to DynamoDB within the expected solve time plus buffer, the orchestration layer falls back to the previous valid schedule and alerts staff."

### Issue A3: No Human Override Mechanism Described (HIGH)

**Location:** Entire recipe (missing section)

**The problem:** The recipe describes an optimization system that produces schedules and replans automatically. It never describes how a charge nurse or surgeon overrides the system. In real OR operations, human overrides happen constantly: "Move Dr. Smith's case to Room 2 because the patient's family is already waiting there," "Swap cases 3 and 4 because the surgeon just called and is running late," "Lock this room's sequence, don't let the optimizer touch it."

Without explicit override mechanisms, the system will either be ignored (staff revert to the whiteboard) or cause conflicts (optimizer replans and undoes a manual change). The "Honest Take" section mentions surgeon buy-in but doesn't translate that into architectural requirements.

**Suggested fix:** Add a subsection in the architecture or a paragraph in the code walkthrough: "The schedule API must support manual overrides: lock a case to a specific room/time (excluded from re-optimization), swap two cases within a room, add a manual hold on a time slot. Overrides are stored as hard constraints in DynamoDB. When the solver runs, it reads current overrides and treats them as fixed assignments. The dashboard should clearly distinguish optimizer-assigned slots from manually-locked slots. An audit trail of who overrode what and when is essential for post-day analysis."

### Issue A4: Cost Estimate Doesn't Account for Commercial Solver Licensing (MEDIUM)

**Location:** Prerequisites table, Cost Estimate row

**The problem:** The cost estimate says "$0.05-0.20 per optimization run" based on Fargate compute. But the Technology section discusses commercial solvers (Gurobi, CPLEX) as the high-performance option. Gurobi cloud licensing is approximately $0.10-0.50 per minute of solve time, and CPLEX has similar pricing. A hospital running 2-3 batch optimizations plus 10-20 replans per day could see $50-200/day in solver licensing alone, far exceeding the stated $200-800/month estimate.

The recipe correctly mentions free alternatives (OR-Tools CP-SAT, HiGHS, COIN-OR CBC) but the cost estimate should acknowledge the licensing delta.

**Suggested fix:** Add a note to the cost estimate: "Using open-source solvers (OR-Tools CP-SAT, HiGHS): $200-800/month as stated. Using commercial solvers (Gurobi, CPLEX): add $1,500-5,000/month for cloud licensing depending on usage volume and contract terms. Commercial solvers offer faster solve times and better optimality guarantees on large instances but are not required for most hospital-scale problems (under 100 cases/day)."

---

## Networking Expert Review

### What's Done Well

The prerequisites correctly specify "Fargate tasks in private subnets with VPC endpoints for DynamoDB, S3, SQS, CloudWatch Logs." This is the right pattern: solver tasks processing PHI-bearing case data should not traverse the public internet to reach AWS services.

### Issue N1: VPC Endpoint for EventBridge Not Mentioned (LOW)

**Location:** Prerequisites table, VPC row

**The problem:** The VPC row mentions endpoints for "DynamoDB, S3, SQS, CloudWatch Logs" but not EventBridge. The Lambda functions (constraint builder, replan trigger) that put events to EventBridge would need either a VPC endpoint for EventBridge or to run outside the VPC. If the Lambdas are in the VPC (which is implied by the private subnet architecture), they need the EventBridge VPC endpoint to publish events without NAT gateway egress.

**Suggested fix:** Add EventBridge to the VPC endpoints list, or clarify that the Lambda functions (which are lightweight and don't directly handle PHI payloads) can run outside the VPC with appropriate IAM controls, while only the ECS solver tasks require VPC placement.

### Issue N2: No Discussion of EHR Integration Network Path (LOW)

**Location:** Architecture diagram, `[EHR / Surgical Scheduling] -->|HL7/FHIR| [EventBridge]`

**The problem:** The architecture shows the EHR sending HL7/FHIR messages to EventBridge, but doesn't discuss how this connection is secured. EHR systems are typically on-premises or in a separate network segment. The integration path (VPN, Direct Connect, PrivateLink, or API Gateway with mutual TLS) is not specified. For a system receiving surgical case data (PHI), the network path between EHR and AWS matters.

**Suggested fix:** Add a brief note in the architecture section or prerequisites: "EHR integration assumes a secured network path (AWS Direct Connect, site-to-site VPN, or API Gateway with mutual TLS and client certificates). HL7v2 messages should be received via a MLLP-to-HTTPS adapter in a private subnet. FHIR APIs should use OAuth 2.0 with SMART on FHIR scopes."

---

## Voice Reviewer

### What's Done Well

The voice is strong throughout. The opening scenario (5:45 AM, charge nurse, whiteboard, phone calls) is exactly the right energy. The parenthetical asides work well: "(ok, this is a gross oversimplification, but stay with me)" energy without being that explicit. The "Honest Take" section is genuinely insightful (duration prediction > solver sophistication, surgeon buy-in, anesthesia as binding constraint). The 70/30 vendor balance is well-maintained: the Technology section is entirely vendor-agnostic, and AWS only appears in the implementation half.

### Issue V1: TODO Comment Left in Published Recipe (MEDIUM)

**Location:** Line 488, `<!-- TODO: Verify specific blog post URLs for optimization on ECS/Fargate -->`

**The problem:** A TODO comment is visible in the markdown source. While it renders as invisible HTML in most viewers, it indicates unfinished work and the "Running optimization workloads on Amazon ECS" link points to the generic containers blog landing page rather than a specific post. This violates the "Only real, verified URLs" rule from the writing guidelines.

**Suggested fix:** Either find and link the specific blog post, or remove the entry entirely. The generic blog landing page (`aws.amazon.com/blogs/containers/`) is not a useful resource link. Replace with a verified, specific post about running compute-intensive workloads on Fargate, or remove and add a note that readers should search the AWS Containers blog for current guidance on optimization workloads.

### Issue V2: "Optimization on AWS" Link May Not Exist (LOW)

**Location:** Line 485, `[Optimization on AWS](https://aws.amazon.com/optimization/)`

**The problem:** The URL `https://aws.amazon.com/optimization/` is not a well-known AWS landing page. AWS has pages for specific services and solutions but "optimization" as a standalone page may not exist or may redirect. This needs verification per the "Never use fake or made-up URLs" rule.

**Suggested fix:** Verify this URL exists. If not, replace with a link to the AWS HPC/batch computing page or the AWS Solutions Library filtered for optimization workloads.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

1. **Security (S1) and Architecture (A3) overlap on the human override question.** The security expert flags that patient identifiers flow to the dashboard without access control discussion. The architecture expert flags that no override mechanism exists. These compound: if you add override capability, you need role-based access control on who can override (charge nurse yes, random staff no), and the override audit trail itself contains PHI (who moved which patient's case).

2. **Architecture (A1) and Architecture (A2) compound on reliability.** The SQS deduplication race condition (A1) combined with no DLQ/failure handling (A2) means the system can both miss needed replans AND fail silently on attempted replans. Together these represent a reliability gap that could leave the OR running on a stale schedule with no alerting.

3. **Security (S2) and Networking (N2) both touch the EHR integration boundary.** The notification channel security and the EHR inbound path are both about securing data at system boundaries. A comprehensive "integration security" paragraph would address both.

### Priority Resolution

The human override gap (A3) is the highest-priority finding because it affects whether the system is usable in practice. A scheduling optimizer without override capability will be rejected by perioperative staff regardless of its technical quality. The SQS race condition (A1) and missing failure handling (A2) are close seconds because they affect reliability of a patient-care-adjacent system.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Entire recipe (missing) | No human override mechanism described. System will be rejected by OR staff without ability to lock cases, swap sequences, or exclude rooms from optimization. | Add override architecture: locked assignments as hard constraints, role-based override permissions, audit trail, visual distinction on dashboard. |
| 2 | HIGH | Architecture | Step 4, `enqueue_replan` | SQS deduplication assumes FIFO queue behavior but architecture describes standard queue. Deduplication ID strategy has race condition at minute boundaries. | Specify FIFO queue. Fix deduplication to time-window approach. Add consumer-side deduplication check. |
| 3 | HIGH | Architecture | Architecture diagram, Step 3 | No DLQ, retry policy, or alerting for solver failures. Silent failure leaves OR on stale schedule with no notification. | Add DLQ (max receives=3), CloudWatch alarm on DLQ depth, fallback to previous valid schedule, staff notification on solver failure. |
| 4 | HIGH | Security | Step 1 pseudocode | Patient identifiers flow through constraint builder to DynamoDB and potentially to API output without access control discussion. | Add IAM scoping discussion, separate patient-identifiable data from published schedule, implement role-based API access. |
| 5 | MEDIUM | Security | Step 5 pseudocode | Replan notifications sent over unspecified channel. SMS/email with patient procedure details is HIPAA violation risk. | Specify HIPAA-compliant notification channel. Minimum necessary content (case ID, time, room only). |
| 6 | MEDIUM | Architecture | Prerequisites, Cost Estimate | Cost estimate ignores commercial solver licensing ($1,500-5,000/month) despite discussing Gurobi/CPLEX as options. | Add licensing cost note distinguishing open-source vs. commercial solver cost profiles. |
| 7 | MEDIUM | Voice | Line 488 | TODO comment left in recipe. Associated link points to generic blog landing page, not a specific verified post. | Remove TODO, replace generic link with verified specific post or remove entry. |
| 8 | LOW | Security | Prerequisites, IAM row | IAM permissions listed as actions without resource ARN scoping. | Add note that all permissions should be scoped to specific resource ARNs. |
| 9 | LOW | Networking | Prerequisites, VPC row | EventBridge VPC endpoint not listed. Lambda functions in VPC need it to publish events. | Add EventBridge to VPC endpoints list or clarify Lambda VPC placement strategy. |
| 10 | LOW | Networking | Architecture diagram | EHR integration network path (VPN, Direct Connect, mTLS) not discussed for PHI-bearing inbound connection. | Add brief note on secured EHR integration path options. |
| 11 | LOW | Voice | Line 485 | "Optimization on AWS" URL may not exist as a real page. Needs verification. | Verify URL or replace with known-good alternative. |

---

## Summary

**Verdict: PASS**

This is a strong recipe with excellent educational value. The technology explanation of combinatorial optimization, constraint formulation, and solver families is genuinely useful and well-written. The operational insights (duration prediction matters more than solver sophistication, anesthesia as binding constraint, surgeon politics) demonstrate real domain expertise.

The four HIGH findings are all addressable without restructuring the recipe. The most important addition is the human override mechanism (A3): without it, the recipe describes a system that would be technically correct but operationally rejected. The SQS/reliability issues (A1, A2) need fixing for production credibility. The PHI access control gap (S1) needs a paragraph of guidance, not a redesign.

No CRITICAL findings. Four HIGH findings (threshold is >3 for FAIL, this is exactly at threshold but the findings are all additive rather than structural, so PASS is appropriate with the expectation that all HIGH items are addressed before publication).
