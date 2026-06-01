# Expert Review: Recipe 15.2 - Notification Timing Optimization

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter15.02-notification-timing-optimization.md`

---

## Overall Assessment

This is a well-crafted recipe that correctly identifies notification timing as a contextual bandit problem and explains the distinction from full RL clearly. The problem statement is compelling, the MDP formulation is clinically appropriate, and the safety constraints section addresses the most important guardrails. The "Honest Take" section is genuinely insightful (fatigue modeling mattering more than timing optimization is a real finding).

However: there are gaps in PHI handling around engagement tracking, the IAM permissions list is overly broad without resource-scoping guidance, the offline evaluation methodology is entirely absent (a significant gap for a recipe that claims to teach RL deployment), and the FDA/regulatory framing is insufficient for a system that influences clinical behavior (medication adherence). The architecture is sound for the stated scale but has a silent failure mode in the EventBridge Scheduler path.

Priority breakdown: 0 must-fix, 4 high-severity, 6 medium, 3 low.

---

## Verdict: FAIL

Rationale: 4 HIGH findings exceed the 3 HIGH threshold for PASS.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

BAA requirement is explicitly stated. Encryption at rest is specified for DynamoDB, SQS (SSE-KMS), Kinesis, and S3. TLS in transit is noted. CloudTrail is required. The quiet hours constraint respects TCPA. The VPC recommendation for production Lambda is correct.

#### Finding SEC-1: Engagement Tracking Creates a PHI Behavioral Profile Without Access Controls

**Severity:** HIGH
**Location:** Step 5 (Track engagement and compute reward), DynamoDB Patient Context Store
**The problem:** The patient context store accumulates a detailed behavioral profile: open rates, action rates, preferred hours, fatigue scores, messages ignored, app activity patterns. This is a behavioral health profile derived from PHI (patient identity + health communication engagement patterns). The recipe treats DynamoDB as a simple feature store with no discussion of:
- Who can read these behavioral profiles (IAM conditions on `dynamodb:GetItem`)
- Whether engagement patterns constitute a new category of PHI requiring separate consent
- Retention policy on behavioral data (the TTL mention is vague: "TTL on engagement history entries keeps the table from growing unbounded" but no specific duration)
- Whether patients can request deletion of their engagement profile (HIPAA right of access/amendment)

**Fix:** Add a security section or prerequisite note: (1) Scope DynamoDB read access to the timing engine Lambda role only, not to broader analytics roles. (2) Define a TTL of 90-180 days on engagement history items. (3) Note that behavioral engagement profiles derived from health communications may constitute PHI under HIPAA's broad definition and should be included in the facility's Notice of Privacy Practices. (4) Implement a patient profile deletion endpoint for right-of-access requests.

#### Finding SEC-2: IAM Permissions Are Listed Without Resource Scoping

**Severity:** MEDIUM
**Location:** Prerequisites table, IAM Permissions row
**The problem:** The IAM permissions list includes `personalize:GetRecommendations`, `sqs:ReceiveMessage`, `dynamodb:GetItem`, etc. without any resource ARN scoping. A builder following this list literally creates a policy with `Resource: "*"` for all these actions. The timing decision Lambda does not need `dynamodb:PutItem` on every DynamoDB table in the account; it needs it on the specific patient context table.

**Fix:** Add a note: "All permissions should be scoped to specific resource ARNs (queue ARN, table ARN, campaign ARN, etc.). The list above shows required actions; production IAM policies must include resource conditions." Alternatively, show a sample policy snippet with ARN placeholders.

#### Finding SEC-3: Kinesis Stream Contains PHI Without Explicit Encryption Key Specification

**Severity:** MEDIUM
**Location:** Architecture diagram, Kinesis Data Stream
**The problem:** Engagement events flowing through Kinesis contain patient_id + message_type + engagement behavior. The prerequisites mention "Kinesis: server-side encryption" but don't specify whether this is the default AWS-managed key or a customer-managed KMS key. For a stream carrying PHI-linked behavioral data, customer-managed keys provide audit trail visibility (CloudTrail logs key usage) and revocation capability.

**Fix:** Specify "Kinesis: server-side encryption with customer-managed KMS key" in the prerequisites, consistent with the SQS SSE-KMS specification.

#### Finding SEC-4: Reward Signal Feedback to Personalize Lacks Input Validation

**Severity:** LOW
**Location:** Step 5, `process_engagement_event` function
**The problem:** The `process_engagement_event` function maps event types to reward values and feeds them to Personalize via `PutEvents`. There's no validation that the event actually corresponds to a legitimate message send. A malformed or injected engagement event (from a compromised Pinpoint callback or a misconfigured Kinesis producer) could feed arbitrary reward signals to the model, poisoning the learned policy.

**Fix:** Add a validation step: verify that `message_id` exists in the decision log and that the event timestamp is within the expected reward window (0-48 hours after send). Discard events that fail validation and log them for investigation.

---

### Architecture Expert Review

#### What's Done Well

The contextual bandit formulation is correct and well-motivated. The distinction from full RL is clearly explained. The decoupling of message generation from timing optimization is a clean architectural pattern. The use of EventBridge Scheduler for one-time delivery is appropriate. The cold start discussion is honest. The "Honest Take" insight about fatigue modeling is genuinely valuable.

#### Finding ARCH-1: No Offline Policy Evaluation Methodology

**Severity:** HIGH
**Location:** "Offline Learning: Starting Without Exploration" section
**The problem:** The recipe describes offline training (bootstrap from historical data) but provides zero guidance on offline policy evaluation (OPE). Before deploying a learned policy, you need to estimate its performance without actually sending messages. The recipe mentions inverse propensity scoring in passing but doesn't explain:
- How to compute propensity scores when the historical policy is deterministic (always sent at 9am)
- How to handle the resulting infinite variance in IPS estimates
- What OPE estimators to use (IPS, doubly-robust, SNIPS)
- What confidence intervals are acceptable before deployment
- How to detect when the offline model is worse than the baseline

This is a critical gap. A builder following this recipe will train a model on biased historical data, have no way to evaluate it offline, and deploy it hoping the online A/B test catches problems. The A/B test infrastructure is itself listed as "not production-ready."

**Fix:** Add a subsection under "Offline Learning" covering offline policy evaluation. At minimum: (1) Explain that deterministic historical policies make IPS impossible without some historical randomization or a logged exploration component. (2) Recommend doubly-robust estimation with a direct method (reward model) as the variance-reduction approach. (3) Note that if historical data has zero coverage of certain time slots, OPE cannot evaluate those slots and online exploration is the only path. (4) Suggest a deployment gate: only deploy if the OPE estimate exceeds the baseline by a statistically significant margin.

#### Finding ARCH-2: EventBridge Scheduler Has a Silent Failure Mode for Expired Schedules

**Severity:** HIGH
**Location:** Step 4 (Schedule delivery), EventBridge Scheduler usage
**The problem:** EventBridge Scheduler creates one-time schedules. If the selected time slot is in the past (due to processing delay, clock skew, or a race condition where the timing decision takes longer than expected), EventBridge Scheduler will either fail silently or fire immediately depending on the `FlexibleTimeWindow` configuration. The recipe doesn't address this edge case.

More critically: if the Lambda that creates the schedule experiences a transient failure after the timing decision but before the schedule is created, the message is lost. It's been dequeued from SQS (visibility timeout expired or it was deleted), the timing decision was made, but no schedule exists. The message never sends.

**Fix:** Add: (1) A check in `schedule_delivery` that the selected time is in the future (with a minimum buffer, e.g., 2 minutes). If not, send immediately. (2) SQS message deletion should happen after schedule creation confirmation, not after timing decision. Use SQS visibility timeout extension during processing, and only delete the message after EventBridge Scheduler returns a successful `CreateSchedule` response. (3) Add a DLQ on the SQS queue for messages that fail scheduling after retries.

#### Finding ARCH-3: No Model Rollback or Canary Deployment Strategy

**Severity:** MEDIUM
**Location:** General architecture, deployment considerations
**The problem:** The recipe describes training and deploying the Personalize campaign but provides no guidance on:
- How to roll back to the previous model version if engagement drops
- How to canary-deploy a new model (send 5% of traffic to the new model, 95% to the old)
- What metrics trigger an automatic rollback (opt-out rate spike, engagement drop below baseline)
- How to handle the transition period when a new model is learning

For a system that directly affects patient communication, deploying a bad model could increase opt-outs (losing the communication channel permanently) before anyone notices.

**Fix:** Add a paragraph in "Why This Isn't Production-Ready" or as a variation: describe a canary deployment pattern where new Personalize campaigns receive a small traffic percentage, with automatic rollback if opt-out rate exceeds 2x baseline or engagement drops below 80% of the previous model's performance over a 48-hour window.

#### Finding ARCH-4: Multi-Message Coordination Gap Is Understated

**Severity:** MEDIUM
**Location:** "Why This Isn't Production-Ready" section
**The problem:** The recipe acknowledges multi-message coordination as a gap but frames it as a future enhancement. In practice, this is a day-one problem. A patient with a pending refill reminder, an appointment reminder, and an educational message will have all three independently optimized to the same time slot (their "best" time). Without coordination, the patient receives three messages at 6:30pm. This is worse than the baseline (which at least spaces messages across days).

The recipe's frequency cap (max N messages per day) partially addresses this, but the cap is checked per-message at decision time. If three messages are queued simultaneously and processed in parallel, all three pass the frequency cap check (messages_today = 0 for all three) and all three get scheduled for the same slot.

**Fix:** Elevate this from a "not production-ready" footnote to a documented limitation with a mitigation: implement a per-patient scheduling lock or a coordination queue that serializes timing decisions for the same patient. Alternatively, add a deduplication check at schedule creation time: before creating a new schedule, check if another schedule already exists for this patient within a 2-hour window.

---

### Networking Expert Review

#### What's Done Well

VPC recommendation for production Lambda is stated. The prerequisite mentions VPC endpoints for DynamoDB, SQS, Kinesis, and Personalize. TLS in transit is noted for all services.

#### Finding NET-1: VPC Endpoint List Is Incomplete

**Severity:** HIGH
**Location:** Prerequisites table, VPC row
**The problem:** The prerequisites state "Production: Lambda in VPC with endpoints for DynamoDB, SQS, Kinesis, and Personalize." This is missing several required endpoints:
- **EventBridge Scheduler** (`com.amazonaws.{region}.scheduler`): The Lambda creates schedules via the Scheduler API. Without this endpoint, the timing decision Lambda cannot create delivery schedules from within the VPC.
- **Pinpoint** (`com.amazonaws.{region}.mobiletargeting`): The delivery Lambda sends messages via Pinpoint. Without this endpoint, message delivery fails from within the VPC.
- **KMS** (`com.amazonaws.{region}.kms`): Required for any service using SSE-KMS (SQS, Kinesis, DynamoDB with CMK). Without it, decryption/encryption calls fail from within the VPC.
- **CloudWatch Logs** (`com.amazonaws.{region}.logs`): Lambda execution logs require this endpoint from within a VPC.

A builder who deploys Lambda in a VPC with only the four listed endpoints will experience silent failures on schedule creation, message delivery, encryption operations, and logging.

**Fix:** Expand the VPC endpoint list to include all required endpoints: DynamoDB (gateway), S3 (gateway), SQS, Kinesis, Personalize, EventBridge Scheduler, Pinpoint (mobiletargeting), KMS, and CloudWatch Logs. Note the per-AZ cost (~$7-8/month per interface endpoint in a 3-AZ deployment; approximately $50-60/month total for this recipe's endpoint set).

#### Finding NET-2: No Egress Control Discussion for PHI-Carrying Lambda Functions

**Severity:** MEDIUM
**Location:** Architecture, Lambda functions
**The problem:** The Lambda functions in this architecture handle patient IDs, engagement patterns, and message content (which may reference conditions, medications, or appointments). The recipe recommends VPC deployment but doesn't discuss egress controls. Without a restrictive security group or network ACL, a compromised Lambda function (or a misconfigured dependency) could exfiltrate PHI to arbitrary internet endpoints.

**Fix:** Add a note: "Lambda security groups should restrict outbound traffic to VPC endpoints only (no internet egress). If internet access is required for any dependency, route through a NAT gateway with VPC flow logs enabled. For this architecture, all AWS service calls can be routed through VPC endpoints, eliminating the need for internet egress entirely."

#### Finding NET-3: Pinpoint Engagement Callbacks Arrive from AWS Service Network

**Severity:** LOW
**Location:** Architecture, engagement event flow
**The problem:** Pinpoint engagement events (opens, clicks) are delivered via Kinesis or event streams from the AWS service network, not from within the customer's VPC. The recipe's architecture shows Pinpoint feeding into Kinesis Data Stream, but doesn't clarify that this is a service-side integration (Pinpoint writes to Kinesis using a service role) rather than a VPC-internal data flow. A builder might incorrectly assume the Kinesis producer is their own Lambda and configure VPC endpoints accordingly.

**Fix:** Add a brief note: "Pinpoint engagement event delivery to Kinesis is a service-side integration. Pinpoint writes to the Kinesis stream using an IAM role you configure, from the AWS service network. This does not traverse your VPC. Ensure the Kinesis stream's resource policy (if using a CMK) grants the Pinpoint service principal decrypt access to the KMS key."

---

### Voice Reviewer

#### What's Done Well

The recipe nails CC's voice throughout. The problem statement builds momentum through accumulation ("These aren't bad messages. The content is relevant. The patients genuinely need the information. But..."). The parenthetical asides are natural ("yes, really; engagement patterns shift on rainy days"). The "Honest Take" section is genuinely self-deprecating and insightful. The 70/30 vendor balance is well-maintained: the Technology section is entirely vendor-agnostic, and AWS appears only in the implementation half.

#### Finding VOICE-1: No Em Dashes Found

**Severity:** N/A (PASS)
**Location:** Full document
**Details:** Zero em dashes detected. Correct use of colons, periods, and parentheses throughout.

#### Finding VOICE-2: Minor Doc-Voice Creep in Prerequisites Table

**Severity:** LOW
**Location:** Prerequisites table, Sample Data row
**The problem:** "Minimum 1,000 interactions per message type for reasonable model quality. Synthetic data acceptable for development." This reads slightly clinical/documentation-voice compared to the rest of the recipe. The rest of the recipe would say something like "You need at least 1,000 interactions per message type before the model learns anything useful. Synthetic data works fine for development."

**Fix:** Minor tone adjustment to match the conversational register of the surrounding prose.

#### Finding VOICE-3: "Related Recipes" Section References Non-Existent Recipes

**Severity:** LOW
**Location:** Related Recipes section
**The problem:** References Recipe 4.1, 4.5, 15.1, and 7.1. These recipes may not exist yet (Chapter 4 and 7 are not started per the project brief). While cross-references are expected in a cookbook, the specific descriptions ("Closely related; focuses on channel selection rather than timing") imply these recipes exist with specific content. If they don't exist yet, these descriptions are speculative.

**Fix:** Verify these recipes exist or will exist with the described content. If they're planned but not written, add a note or ensure the descriptions are generic enough to accommodate whatever those recipes eventually contain.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

1. **SEC-1 and ARCH-4 overlap:** Both identify the patient context store as problematic but from different angles. SEC-1 focuses on access controls and retention; ARCH-4 focuses on coordination race conditions. Both point to the DynamoDB patient context table needing more architectural attention than it currently receives.

2. **NET-1 and ARCH-2 interact:** The missing EventBridge Scheduler VPC endpoint (NET-1) would cause the same silent failure described in ARCH-2 (schedule creation fails). NET-1 is the networking root cause; ARCH-2 is the application-level consequence. Both need fixing, but NET-1 is the more fundamental issue.

3. **SEC-1 and regulatory gap:** The behavioral profiling concern in SEC-1 connects to a broader regulatory gap. The recipe doesn't discuss whether a notification timing system that influences medication adherence behavior could be considered a Clinical Decision Support (CDS) tool under FDA guidance. If the system's timing decisions measurably affect whether patients take medications, there's an argument it falls under FDA's CDS framework (specifically, the "intended to be used" criterion). This is a gray area, but the recipe should at least acknowledge it exists.

### Priority Resolution

The regulatory/FDA gap is not called out as a separate finding because it's genuinely ambiguous (notification timing is far from the FDA's current enforcement focus), but it should be noted in the review. The four HIGH findings are all independently actionable and don't conflict with each other.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Step 5, DynamoDB Patient Context | Engagement tracking creates PHI behavioral profile without access controls, retention policy, or deletion capability | Scope IAM, define TTL (90-180d), note PHI classification, implement deletion endpoint |
| 2 | HIGH | Architecture | Offline Learning section | No offline policy evaluation methodology; builders cannot assess model quality before deployment | Add OPE subsection covering doubly-robust estimation, coverage limitations, and deployment gates |
| 3 | HIGH | Architecture | Step 4, EventBridge Scheduler | Silent failure mode: past-time schedules and message loss between SQS dequeue and schedule creation | Add time validation, defer SQS deletion until schedule confirmed, add DLQ |
| 4 | HIGH | Networking | Prerequisites, VPC row | VPC endpoint list missing EventBridge Scheduler, Pinpoint, KMS, and CloudWatch Logs; deployment will fail silently | Expand to full endpoint list with service names and cost note |
| 5 | MEDIUM | Security | Prerequisites, IAM row | IAM permissions listed without resource ARN scoping guidance | Add resource-scoping note or sample policy snippet |
| 6 | MEDIUM | Security | Prerequisites, Kinesis | Kinesis encryption not specified as customer-managed KMS key | Specify CMK consistent with other PHI-carrying services |
| 7 | MEDIUM | Architecture | "Not Production-Ready" section | Multi-message coordination is a day-one problem, not a future enhancement; parallel processing creates race condition | Elevate to documented limitation with per-patient scheduling lock mitigation |
| 8 | MEDIUM | Architecture | General | No model rollback or canary deployment strategy for a system affecting patient communications | Add canary deployment pattern with automatic rollback triggers |
| 9 | MEDIUM | Networking | Architecture, Lambda | No egress control discussion for PHI-carrying Lambda functions | Add security group guidance restricting outbound to VPC endpoints only |
| 10 | LOW | Security | Step 5, reward processing | No input validation on engagement events before feeding to model | Add message_id verification and timestamp window check |
| 11 | LOW | Voice | Prerequisites table | Minor doc-voice creep in Sample Data row | Adjust tone to match conversational register |
| 12 | LOW | Voice | Related Recipes | References potentially non-existent recipes with specific descriptions | Verify existence or genericize descriptions |
| 13 | LOW | Networking | Architecture, Pinpoint events | Pinpoint-to-Kinesis is service-side integration, not VPC-internal; could confuse VPC endpoint planning | Add clarifying note about service-side event delivery |

---

## Regulatory Note (Not Scored)

The recipe does not address whether a notification timing system that measurably influences medication adherence could fall under FDA's Clinical Decision Support (CDS) guidance. The 2022 FDA draft guidance on CDS distinguishes between tools that "inform" clinical decisions (exempt) and tools that "drive" clinical actions (potentially regulated). A system that optimizes timing specifically to increase medication refill completion rates is closer to "driving" adherence behavior than passively "informing" a patient.

This is genuinely ambiguous (FDA has not enforced against notification timing systems), but the recipe should acknowledge the gray area. A single sentence in the Safety Constraints section noting that systems designed to influence medication-taking behavior may warrant FDA CDS classification review would be sufficient. This is especially relevant given the recipe's explicit reward signal of +1.0 for "patient refills prescription."

---

## Priority Actions Before Publication

1. **Fix NET-1 (HIGH):** Expand VPC endpoint list. This is a deployment blocker; Lambda in VPC will fail to reach EventBridge Scheduler, Pinpoint, KMS, and CloudWatch Logs without the missing endpoints.

2. **Fix ARCH-2 (HIGH):** Address the EventBridge Scheduler silent failure mode. Message loss between SQS dequeue and schedule creation is a data integrity issue. Defer SQS message deletion until schedule creation is confirmed.

3. **Fix ARCH-1 (HIGH):** Add offline policy evaluation guidance. The recipe teaches how to train a model but not how to evaluate it before deployment. This is a significant pedagogical gap for an RL recipe.

4. **Fix SEC-1 (HIGH):** Address PHI behavioral profiling. The engagement tracking system creates a sensitive data store that needs explicit access controls, retention policy, and deletion capability.

5. **Fix ARCH-4 and ARCH-3 (MEDIUM):** Elevate multi-message coordination from footnote to documented limitation, and add model rollback guidance. Both affect production safety.

6. **Fix SEC-2 and SEC-3 (MEDIUM):** Tighten IAM and encryption specifications. These are compliance hygiene items that reviewers will flag in any enterprise deployment.

---

*Review complete. Recipe 15.2 is well-written and pedagogically strong. The RL formulation is appropriate, the voice is excellent, and the architecture is sound at a conceptual level. The failures are in deployment-level details (VPC endpoints, message delivery reliability, offline evaluation) and PHI governance (behavioral profiling, access controls) rather than in the core technical approach. All HIGH findings are addressable without restructuring the recipe.*
