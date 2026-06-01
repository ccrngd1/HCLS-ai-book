# Expert Review: Recipe 14.9 - Chemotherapy Scheduling

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter14.09-chemotherapy-scheduling.md`

---

## Overall Assessment

This is an exceptional recipe. The problem statement is one of the best in the book: the 7:15 AM infusion center scenario immediately communicates the multi-dimensional complexity of the problem. The financial framing ($6 million annually in wasted capacity for a 30-chair center) gives executives a reason to care. The technology section is genuinely educational, covering RCPSP formulation, solver selection, pharmacy coupling, and workload leveling with enough depth that an operations research student would learn something.

The architecture is well-designed with appropriate separation of batch optimization (overnight), tactical scheduling (weekly), and real-time adjustment (day-of). The pharmacy coordination discussion is a standout section that most scheduling literature ignores. The "Honest Take" is authentic and operationally wise, particularly the insight that "the hardest part isn't the math, it's the data" and the political nature of objective function weights.

However: there are gaps in human override mechanisms (the recipe discusses staff trust but doesn't architecturally implement override workflows), the IAM permissions list is incomplete for the services described, there's no discussion of what happens when the optimizer is unavailable (schedulers must still schedule), the drug stability constraint in the pseudocode has a logic gap, and there are two TODO items in Additional Resources indicating unverified links. The recipe also lacks explicit discussion of consent/notification when patient schedules are algorithmically determined.

Priority breakdown: 0 CRITICAL findings, 3 HIGH findings, 5 MEDIUM findings, 4 LOW findings.

---

## Verdict: **PASS**

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

The prerequisites table correctly identifies BAA requirement with clear reasoning ("Patient treatment schedules are PHI"). Encryption at rest (S3 SSE-KMS, DynamoDB encryption) and in transit (TLS for all API calls) are specified. VPC deployment with VPC endpoints is recommended. CloudTrail is enabled for "all schedule modifications (who changed what, when)." The "Never use real patient data in dev" warning is present with reference to synthetic treatment orders. The sample output uses anonymized patient IDs (PT-9928).

### Issue S1: IAM Permissions List Is Incomplete for Described Architecture (HIGH)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions listed are: `sagemaker:InvokeEndpoint`, `dynamodb:PutItem/GetItem/Query`, `s3:GetObject/PutObject`, `states:StartExecution`, `events:PutEvents`. But the architecture uses API Gateway, CloudWatch, EventBridge (for receiving events, not just putting them), and Lambda invocations from Step Functions. Missing permissions include:

- `execute-api:Invoke` (if internal services call the Schedule API)
- `logs:CreateLogGroup/CreateLogStream/PutLogEvents` (Lambda execution)
- `events:PutRule/DescribeRule` (EventBridge rule management for disruption routing)
- `lambda:InvokeFunction` (Step Functions invoking Lambda steps)
- `sagemaker:DescribeEndpoint` (health checks on the duration prediction endpoint)
- `kms:Decrypt/kms:GenerateDataKey` (for SSE-KMS encrypted S3 and DynamoDB)

More importantly, the permissions aren't scoped to specific resources. `dynamodb:PutItem` on which tables? `s3:GetObject` on which buckets? For a system handling PHI (treatment schedules), resource-level scoping is essential to prevent a compromised Lambda from accessing unrelated patient data in other DynamoDB tables.

**Suggested fix:** Expand the IAM permissions to include all services in the architecture, and add resource-level scoping examples: "dynamodb:PutItem/GetItem/Query (scoped to schedule-* and queue-* tables), s3:GetObject/PutObject (scoped to the schedule-history and solver-logs buckets), sagemaker:InvokeEndpoint (scoped to the duration-prediction endpoint ARN), states:StartExecution (scoped to the batch-scheduler state machine), events:PutEvents (scoped to the scheduling event bus), kms:Decrypt/GenerateDataKey (scoped to the scheduling CMK)."

### Issue S2: No Discussion of Schedule Modification Authorization (MEDIUM)

**Location:** Step 6 (Handle Real-Time Adjustments), entire section

**The problem:** The real-time adjustment function modifies patient schedules based on disruption events. But there's no discussion of who is authorized to trigger these modifications. Can any system component fire a "patient_late" event and shift the schedule? Is there authentication on the EventBridge events? Can a nurse override the optimizer's rescheduling decision?

In a clinical environment, schedule modifications affect patient care (a patient might miss their treatment window if rescheduled too late). There should be role-based authorization: certain disruption types (patient late, patient cancelled) might be triggered by front-desk staff, while others (extended duration, resource unavailable) might require clinical staff authorization.

**Suggested fix:** Add a paragraph before or after Step 6: "Schedule modification events should be authenticated and authorized. Define roles: front-desk staff can trigger arrival/delay/cancellation events; clinical staff can trigger duration extensions and treatment holds; system administrators can trigger resource unavailability. All modification events must include the authenticated user ID. The real-time adjuster should validate that the event source has appropriate authorization before executing schedule changes. Log all modifications with the authorizing user for audit purposes."

### Issue S3: Patient Notification Contains PHI Without Consent Discussion (MEDIUM)

**Location:** Step 5 pseudocode, `send_patient_notification()`

**The problem:** The pseudocode sends patient notifications with confirmed arrival time and estimated duration. This is PHI being transmitted to patients (or their devices). The recipe doesn't discuss:
- What channel is used for notification (SMS, email, patient portal)?
- Is the patient's communication preference respected?
- Is the notification content minimized (does it need to include the treatment type)?
- For SMS/email, is the content encrypted or is it sent in cleartext?
- Has the patient consented to electronic notifications about their treatment schedule?

Under HIPAA, sending treatment schedule information via unencrypted SMS could be a violation if the patient hasn't consented to that communication method.

**Suggested fix:** Add a note after the `send_patient_notification` call: "Patient notifications must respect the patient's documented communication preferences (patient portal, encrypted email, SMS with consent). Minimize PHI in notifications: 'Your appointment is confirmed for 10:30 AM' rather than 'Your FOLFOX chemotherapy infusion is confirmed for 10:30 AM.' For SMS, obtain explicit patient consent for text-based scheduling communications. Route notifications through the patient portal as the default secure channel."

### Issue S4: Solver Logs in S3 May Contain PHI (LOW)

**Location:** "Why These Services" section, S3 paragraph; Prerequisites table

**The problem:** The recipe stores "solver logs, schedule history, model training data, and audit trails" in S3. Solver logs from the optimizer will contain patient IDs, treatment regimens, and scheduling decisions. This is PHI. While S3 SSE-KMS is specified, there's no discussion of:
- Lifecycle policies (how long are solver logs retained?)
- Access controls (who can read historical solver logs?)
- Whether solver logs should be in a separate bucket from training data (different retention/access requirements)

**Suggested fix:** Add: "Solver logs contain PHI (patient IDs, regimens, scheduling decisions). Store in a dedicated bucket with: S3 Object Lock for compliance retention (minimum 6 years per HIPAA), bucket policy restricting access to the scheduling service role and authorized administrators, lifecycle policy transitioning to Glacier after 90 days. Separate from model training data which may have different retention requirements."

---

## Architecture Expert Review

### What's Done Well

The multi-timescale architecture (strategic/tactical/operational/reactive) is the correct decomposition for this problem. The solver selection guidance (CP for heterogeneous constraints, MIP for linear objectives, heuristics for real-time) is accurate and well-explained. The pharmacy coordination section is outstanding and correctly identifies it as the most commonly overlooked constraint. The workload leveling formulation (minimax or variance minimization over time periods) is mathematically sound. The feedback loop for duration prediction improvement is a critical production concern that's often missed.

The choice of DynamoDB for schedule state (low-latency reads for the staff dashboard) and EventBridge for event routing (loose coupling between scheduling engine and consumers) is architecturally sound. Step Functions for the batch workflow provides the visibility and error handling needed for a clinical system.

### Issue A1: No Failover Strategy When Optimizer Is Unavailable (HIGH)

**Location:** Entire recipe (missing section)

**The problem:** The recipe describes a sophisticated optimization system but never addresses what happens when it fails. The batch optimizer might fail to find a feasible solution (infeasible day due to understaffing). The real-time adjuster might timeout. The SageMaker endpoint might be unavailable. The Step Functions workflow might fail mid-execution.

During any of these failures, patients still need to be scheduled. Infusion centers operated for decades without optimization software. The recipe needs to explicitly state that the existing scheduling workflow (manual or template-based) remains as the fallback, and define the conditions under which the system degrades gracefully.

This is particularly important because the recipe's own "Honest Take" section says "Start with the batch problem, not real-time," implying a phased rollout where the manual process coexists with the optimizer. But the architecture doesn't show this coexistence.

**Suggested fix:** Add a subsection after the architecture diagram or in the "Honest Take": "The optimization layer enhances existing scheduling workflows; it does not replace them. If the batch optimizer fails to produce a feasible schedule by 6:00 AM, the system falls back to the previous day's template-based schedule with manual adjustments. If the real-time adjuster times out (>5 seconds), the disruption is routed to the human scheduler's queue for manual resolution. The staff dashboard must always show the current schedule state regardless of optimizer availability. Monitor optimizer availability as a key metric; alert if the batch job fails or if real-time adjustment latency exceeds 5 seconds for more than 3 consecutive events."

### Issue A2: No Explicit Human Override Mechanism in Architecture (HIGH)

**Location:** Architecture diagram and Step 6 pseudocode

**The problem:** The recipe's "Honest Take" section eloquently describes the need for staff trust: "If the system overrides their judgment without explanation, they'll route around it. Build in transparency: show why the optimizer made each decision. Allow overrides." This is excellent advice. But the architecture doesn't implement it.

The architecture diagram shows: `[Optimized Schedule] → [Staff Dashboard]` and `[Real-Time Adjuster] → [Published Schedule]`. There's no feedback path from the staff dashboard back to the scheduling engine. There's no mechanism for a scheduler to:
- Override a specific patient's assignment (move them to a different time/chair)
- Lock a patient's assignment so the optimizer doesn't move them during reoptimization
- Flag a constraint the optimizer doesn't know about ("Mrs. Johnson can't be next to Mr. Smith")
- Reject the optimizer's entire daily schedule and request a re-solve with different parameters

The pseudocode in Step 6 handles system-generated disruptions but not human-initiated schedule modifications.

**Suggested fix:** Add to the architecture diagram a bidirectional arrow between Staff Dashboard and the scheduling engine. Add a paragraph: "The staff dashboard must support manual overrides: drag-and-drop patient reassignment, time slot locking (prevent optimizer from moving a specific patient), ad-hoc constraint addition ('keep these two patients apart'), and full re-solve requests with adjusted weights. Every override is logged with the staff member's ID and optional reason. The optimizer treats locked assignments as fixed constraints in subsequent reoptimization runs. Track override frequency by type; high override rates on specific constraint types indicate the model is missing a real-world rule that should be encoded."

### Issue A3: Drug Stability Constraint Has Logic Gap in Pseudocode (MEDIUM)

**Location:** Step 4 pseudocode, pharmacy prep capacity and drug stability constraints

**The problem:** The drug stability constraint is:
```
request.start_var - prep_completion_time(request) <= request.drug_stability_hours * 60
```

But `prep_completion_time(request)` is not defined anywhere in the model. The pharmacy prep start time is computed as `request.start_var - request.pharmacy_prep_minutes`, which gives the prep START time, not the prep COMPLETION time. The stability window should be measured from when the drug is FINISHED being prepared (ready to administer) to when it's actually administered (patient start time).

If prep takes 45 minutes and the drug has a 4-hour BUD, the constraint should be:
```
request.start_var - (prep_start + request.pharmacy_prep_minutes) <= drug_stability_hours * 60
```

Which simplifies to: the gap between prep completion and patient start must be less than the BUD. But since prep_start = start_var - pharmacy_prep_minutes, the gap is always 0 in this formulation (prep finishes exactly when the patient starts). The real constraint is that if the patient is DELAYED after prep is complete, the drug might expire. This is a reactive constraint, not a planning constraint, and should be handled in Step 6 (disruptions), not Step 4.

The planning constraint should be: pharmacy prep must not start so early that the drug expires before the patient's scheduled start. This means: `request.start_var - prep_start <= drug_stability_hours * 60`, which is: `pharmacy_prep_minutes <= drug_stability_hours * 60`. This is always true for reasonable values (45 min prep < 240 min BUD), making the constraint trivially satisfied in the batch schedule.

**Suggested fix:** Clarify the drug stability constraint's purpose. The real value of this constraint is in the reactive layer: when a patient is delayed, check whether their already-prepared drug will expire before the new start time. In the batch optimizer, the constraint should ensure that the pharmacy prep slot is scheduled close enough to the patient's start time that the drug won't expire even with expected variance. Reformulate as: `request.start_var - pharmacy_prep_start <= drug_stability_hours * 60 - buffer_minutes` where buffer_minutes accounts for typical delays (e.g., 30 minutes). Add a comment explaining that the tighter constraint in real-time (Step 6) checks actual prep completion against actual expected administration time.

### Issue A4: No Discussion of Multi-Day Regimen Handling in Core Architecture (LOW)

**Location:** "Where It Struggles" section mentions multi-day regimens but architecture doesn't address them

**The problem:** The recipe correctly identifies multi-day regimens as a limitation ("Protocols that span 2-3 consecutive days create complex inter-day dependencies that single-day optimizers handle poorly"). But the architecture is entirely single-day focused. The batch optimizer (Step Functions workflow) runs nightly for the next day. There's no mechanism to:
- Reserve a chair for a patient who needs the same chair for 3 consecutive days
- Coordinate pharmacy prep across days (some multi-day protocols have day-specific drugs)
- Ensure the same nursing team is assigned across days for continuity

For a production system, multi-day regimens are not edge cases. FOLFOX (mentioned in the sample output) is a 2-day protocol. 5-FU continuous infusions can span 46-48 hours.

**Suggested fix:** Add a paragraph in the architecture section or as a variation: "For multi-day regimens, the batch optimizer must consider a rolling window. When scheduling Day N, lock in the chair and approximate time slot for Day N+1 and N+2 if the patient's protocol spans multiple days. Implement this as a pre-processing step: before running the single-day optimizer, identify multi-day patients and fix their chair assignments as hard constraints carried forward from the previous day's solve. The Step Functions workflow should include a 'multi-day reservation' step before the main optimization."

---

## Networking Expert Review

### What's Done Well

The prerequisites table specifies VPC deployment with VPC endpoints for AWS services. TLS in transit for all API calls is stated. The architecture uses EventBridge for internal event routing (stays within AWS network). The API Gateway endpoint for the Schedule API provides a controlled access point for external consumers (staff dashboard, patient portal, pharmacy system).

### Issue N1: No VPC Endpoint Specification for SageMaker Runtime (MEDIUM)

**Location:** Prerequisites table, VPC row; Architecture diagram

**The problem:** The recipe specifies "Production deployment in VPC with VPC endpoints for AWS services" but doesn't enumerate which VPC endpoints are needed. The architecture calls SageMaker for duration prediction (Lambda invoking SageMaker endpoint). Without a VPC endpoint for SageMaker Runtime (`com.amazonaws.{region}.sagemaker.runtime`), the Lambda function would need a NAT Gateway to reach the SageMaker endpoint, routing PHI-adjacent data (patient features for duration prediction) through the public internet.

The recipe should explicitly list the required VPC endpoints given the number of services involved: DynamoDB, S3, SageMaker Runtime, Step Functions, EventBridge, CloudWatch Logs, and potentially Secrets Manager (for any credentials).

**Suggested fix:** Expand the VPC row: "VPC endpoints required: DynamoDB (gateway), S3 (gateway), SageMaker Runtime (interface), Step Functions (interface), EventBridge (interface), CloudWatch Logs (interface). All Lambda functions execute within the VPC. No NAT Gateway required for AWS service access when all endpoints are configured. Security groups on interface endpoints restrict access to the scheduling Lambda security group only."

### Issue N2: Patient Portal and Staff Dashboard Access Path Not Defined (LOW)

**Location:** Architecture diagram, `[API Gateway] → [Staff Dashboard]` and `[API Gateway] → [Patient Portal]`

**The problem:** The architecture shows API Gateway serving both the staff dashboard and patient portal, but doesn't discuss the network path for these consumers. The staff dashboard is likely an internal application (hospital network), while the patient portal is internet-facing. These have very different security postures:
- Staff dashboard: should be accessible only from the hospital network (VPN or private API endpoint)
- Patient portal: internet-facing but should go through a WAF

The recipe doesn't distinguish between these access patterns.

**Suggested fix:** Add a note: "Deploy two API Gateway stages or separate APIs: an internal API (private, accessible only from the hospital VPC or via VPN) for the staff dashboard and pharmacy system, and a public API (with WAF, rate limiting, and OAuth/OIDC authentication) for the patient portal. The internal API can use IAM authentication; the patient portal API uses Cognito or the hospital's identity provider."

---

## Voice Reviewer

### What's Done Well

The voice is outstanding. The opening scenario ("It's 7:15 AM at a 30-chair infusion center...") is vivid and immediately relatable to anyone who's worked in healthcare operations. The Tetris metaphor for scheduling is perfect. The financial framing is compelling without being salesy. The technology section maintains teaching energy throughout, with excellent explanations of why the problem is hard (coupled resources, temporal dependencies, stochastic disruptions). The "Honest Take" section is one of the best in the book: "The hardest part isn't the math. It's the data." and "The objective function is political" are genuinely insightful observations that demonstrate real operational experience.

The 70/30 vendor balance is well-maintained. The entire first half (Problem, Technology, General Architecture) is completely vendor-agnostic. AWS services don't appear until "The AWS Implementation" section. A reader using GCP or Azure would learn substantial value from the first half alone.

Parenthetical asides are natural and well-placed: "(or more likely, an Excel spreadsheet that someone printed out)", "(ok, this is a gross oversimplification, but stay with me)" energy throughout.

### Issue V1: Two TODO Items in Additional Resources (MEDIUM)

**Location:** Additional Resources section, "Optimization Libraries and Solvers" and "Healthcare Scheduling Research"

**The problem:** Three TODO items are visible:
- "TODO: Verify current availability of OR-Tools Lambda layer or container packaging guidance"
- "TODO: Verify specific published references on chemotherapy scheduling optimization"
- "TODO: Verify ASCO or ONS guidelines on infusion center operational standards"

These indicate unfinished work and violate the "Only real, verified URLs" rule from the writing guide. For a recipe that discusses operations research extensively and references specific clinical workflows, academic and clinical guideline references would significantly strengthen credibility.

**Suggested fix:** Remove TODOs and either add verified references or remove the placeholder entries. For OR-Tools on Lambda: OR-Tools can be packaged as a Lambda layer or in a container image (the library is ~50MB, fits in a layer). For chemotherapy scheduling research: Hahn-Goldberg et al. (2014) "Dynamic optimization of chemotherapy outpatient scheduling with uncertainty" (Health Care Management Science); Turkcan et al. (2012) "Chemotherapy operations planning and scheduling" (IIE Transactions on Healthcare Systems Engineering). For clinical guidelines: ONS (Oncology Nursing Society) publishes infusion center staffing guidelines; ASCO has quality standards for oncology practices.

### Issue V2: Minor Documentation-Voice in "Why These Services" Opening (LOW)

**Location:** "Why These Services" section, first paragraph for DynamoDB

**The problem:** "The current schedule is a rapidly-read, occasionally-updated data structure. DynamoDB's single-digit-millisecond reads support the real-time display needs..." The second sentence leads with the service capability rather than the architectural need. Compare with the Lambda paragraph which leads with "The batch scheduling job runs once nightly" (the need) before introducing the service.

**Suggested fix:** Rewrite: "Nurses check the schedule board constantly. The patient portal refreshes every 30 seconds. Pharmacy needs instant visibility into timing changes. You need single-digit-millisecond reads on a data structure that updates maybe 50 times per day but gets read thousands of times. DynamoDB's read performance and conditional writes (preventing race conditions when multiple adjustments happen simultaneously) fit this access pattern exactly."

### Issue V3: One Em Dash Present (LOW)

**Location:** Technology section, "Stochastic disruptions" paragraph

**The problem:** Scanning the full recipe text, I do not find any em dashes (the long dash character). The recipe uses periods, commas, colons, and parentheses consistently. No violation found.

**Status:** No issue. Withdrawn.

---

## Stage 2: Expert Discussion

### Overlapping Concerns

1. **Architecture (A1) and Architecture (A2) compound on operational readiness.** The missing failover strategy (A1) and missing human override mechanism (A2) together mean the recipe describes a system with no graceful degradation: no fallback when the optimizer fails, and no mechanism for staff to correct the optimizer when it's wrong. For a clinical system where scheduling errors can mean missed treatment windows, this combination is the most important gap. The recipe's own "Honest Take" identifies both needs but the architecture doesn't implement either.

2. **Security (S1) and Networking (N1) both address access control gaps.** The incomplete IAM permissions (S1) and missing VPC endpoint enumeration (N1) are related: without explicit VPC endpoints, Lambda functions need broader network access (NAT Gateway), and without resource-scoped IAM, a compromised function has broader data access. Addressing both together creates defense in depth.

3. **Architecture (A3) and the pharmacy coordination narrative conflict.** The recipe's pharmacy coordination section is excellent prose, but the pseudocode constraint for drug stability is logically incomplete. The narrative correctly explains the tight coupling between prep timing and patient scheduling, but the mathematical formulation doesn't capture the real constraint (which is reactive, not planning-time).

### Priority Resolution

The human override mechanism (A2) is the highest-priority finding because the recipe explicitly identifies staff trust as critical ("If the system overrides their judgment without explanation, they'll route around it") but doesn't implement the architectural mechanism to support it. This is a gap between the recipe's advice and its architecture.

The failover strategy (A1) is second because clinical operations cannot tolerate scheduling system downtime without a defined fallback. The IAM permissions gap (S1) is third because it's a concrete security deficiency that's straightforward to fix but important for a PHI-handling system.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Entire recipe (missing) | No failover/degradation strategy when optimizer is unavailable. Patients still need scheduling when the system is down. No fallback to template-based or manual scheduling is described. | Add failover section: existing manual/template scheduling remains as fallback, define timeout thresholds (batch job must complete by 6 AM or fall back to template), route real-time failures to human scheduler queue, monitor optimizer availability. |
| 2 | HIGH | Architecture | Architecture diagram and "Honest Take" | No human override mechanism despite the recipe explicitly advising "Allow overrides." Architecture shows one-way flow from optimizer to dashboard with no feedback path for staff corrections. | Add bidirectional path between staff dashboard and scheduling engine. Implement: drag-and-drop reassignment, assignment locking, ad-hoc constraint addition, re-solve requests. Log all overrides. Track override frequency to identify missing model constraints. |
| 3 | HIGH | Security | Prerequisites table, IAM Permissions row | IAM permissions incomplete (missing CloudWatch Logs, Lambda invoke, KMS, API Gateway) and not resource-scoped. For a PHI system, unscoped permissions allow a compromised component to access unrelated patient data. | Enumerate all required permissions for all services in the architecture. Add resource-level ARN scoping for every permission. Example: `dynamodb:PutItem` scoped to `arn:aws:dynamodb:*:*:table/schedule-*`. |
| 4 | MEDIUM | Architecture | Step 4 pseudocode, drug stability constraint | Drug stability constraint logic is incomplete. `prep_completion_time(request)` is undefined. The real drug stability risk is reactive (patient delayed after prep), not planning-time. Current formulation is trivially satisfied for reasonable prep times. | Clarify that batch constraint ensures prep is scheduled close to start time with buffer. Add reactive check in Step 6: when patient is delayed, verify drug won't expire before new start time. Alert pharmacy if BUD will be exceeded. |
| 5 | MEDIUM | Security | Step 5 pseudocode, `send_patient_notification()` | Patient notifications contain PHI (treatment schedule) but no discussion of communication channel security, patient consent for electronic notifications, or content minimization. | Add guidance: use patient portal as default secure channel, minimize PHI in SMS/email ("appointment at 10:30" not "FOLFOX infusion at 10:30"), require explicit consent for text notifications, respect documented communication preferences. |
| 6 | MEDIUM | Security | Step 6 pseudocode, entire section | No authorization model for schedule modification events. Any component can fire disruption events that modify patient schedules. No role-based access control on who can trigger which modification types. | Define authorization roles: front-desk triggers arrivals/delays, clinical staff triggers duration changes/holds, system admin triggers resource unavailability. Validate event source authorization before executing changes. |
| 7 | MEDIUM | Networking | Prerequisites table, VPC row | VPC endpoints not enumerated. Without explicit SageMaker Runtime VPC endpoint, duration prediction calls (containing patient features) route through NAT Gateway over public internet. | List all required VPC endpoints: DynamoDB (gateway), S3 (gateway), SageMaker Runtime (interface), Step Functions (interface), EventBridge (interface), CloudWatch Logs (interface). State that no NAT Gateway is needed when all endpoints are configured. |
| 8 | MEDIUM | Voice | Additional Resources section | Three TODO items visible indicating unverified links/references. Violates "Only real, verified URLs" rule. Missing academic citations weakens credibility for an OR-focused recipe. | Remove TODOs. Add verified references: Hahn-Goldberg et al. (2014) for chemo scheduling optimization, Turkcan et al. (2012) for chemo operations planning, ONS staffing guidelines. For OR-Tools on Lambda, state it can be packaged as a layer or container image. |
| 9 | LOW | Architecture | "Where It Struggles" section | Multi-day regimens identified as limitation but no architectural guidance on handling them. FOLFOX (shown in sample output) is itself a multi-day protocol, making this a common case, not an edge case. | Add paragraph on multi-day handling: rolling optimization window, chair reservation carry-forward, pre-processing step to fix multi-day assignments before single-day optimization. |
| 10 | LOW | Networking | Architecture diagram, API Gateway | Staff dashboard (internal) and patient portal (internet-facing) served by same API Gateway with no discussion of different security postures for internal vs. external consumers. | Recommend separate API stages or APIs: private API with IAM auth for internal consumers (staff, pharmacy), public API with WAF + Cognito/OIDC for patient portal. |
| 11 | LOW | Security | "Why These Services", S3 paragraph | Solver logs contain PHI but no lifecycle policy, retention period, or access control discussion for this data. | Add: dedicated bucket for solver logs, S3 Object Lock for compliance retention (6+ years), lifecycle to Glacier after 90 days, bucket policy restricting access to scheduling service role. |
| 12 | LOW | Voice | "Why These Services", DynamoDB paragraph | First sentence leads with data structure description rather than the human need driving the architectural choice. Minor documentation-voice. | Lead with the operational need (nurses checking constantly, patient portal refreshing) before introducing DynamoDB's capabilities as the solution. |

---

## Summary

**Verdict: PASS**

This is one of the strongest recipes in the optimization chapter and possibly the entire book. The problem statement is compelling and financially grounded. The technology section is genuinely educational, covering constraint programming, solver selection, pharmacy coupling, and workload leveling with enough rigor for an OR practitioner while remaining accessible to a non-technical reader. The "Honest Take" section demonstrates authentic operational wisdom that can only come from real-world experience with clinical scheduling systems.

The three HIGH findings are all additive rather than structural:
1. **Failover strategy** (A1) is essential for any clinical system. A single paragraph establishing that manual/template scheduling remains as fallback, with defined timeout thresholds, addresses this.
2. **Human override mechanism** (A2) is the most important finding because the recipe's own prose identifies this need but the architecture contradicts it. Adding a bidirectional path between the staff dashboard and scheduling engine, with override logging, resolves the contradiction.
3. **IAM permissions** (S1) need to be complete and resource-scoped for a PHI-handling system. This is a straightforward expansion of the existing prerequisites table.

No CRITICAL findings. The recipe correctly handles HIPAA context (BAA, encryption, synthetic data for dev), the optimization formulation is mathematically sound, the solver selection guidance is accurate, and the clinical constraints (nursing ratios, drug stability, acuity-based monitoring) reflect real infusion center operations. The pharmacy coordination section is a standout contribution that most scheduling literature overlooks. With the HIGH findings addressed, this will be a flagship recipe for the chapter.
