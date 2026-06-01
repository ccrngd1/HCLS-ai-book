# Expert Review: Recipe 14.8 - Ambulance Routing and Dispatch

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter14.08-ambulance-routing-dispatch.md`

---

## Overall Assessment

This is an outstanding recipe. The problem statement is visceral and immediately communicates the life-safety stakes. The technology section is genuinely educational: the VRP formulation, the distinction between real-time dispatch and batch repositioning, the coverage problem explanation, and the solver selection taxonomy are all excellent. The "Honest Take" section is one of the best in the book, with the insight that "coverage model is where the real value lives" and the dispatcher resistance discussion showing genuine operational awareness.

The architecture is well-designed with appropriate separation of the latency-critical dispatch path from the background optimization. The dual-layer approach (fast heuristic for immediate dispatch, heavier solver for repositioning) is the correct pattern for this domain.

However: there are gaps in human override mechanisms for the dispatch decision, the ElastiCache IAM permission is overly broad, the recipe lacks discussion of failover behavior when the optimization system is unavailable (dispatchers must still dispatch), and there are two TODO items in the Additional Resources section indicating unverified links. The GPS data stream carries location data that constitutes PHI in context but the Kinesis encryption discussion could be more explicit about key management.

Priority breakdown: 0 must-fix factual errors, 3 significant gaps, 6 improvement recommendations.

---

## Verdict: **PASS**

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

The prerequisites table correctly identifies BAA requirement with clear reasoning ("Patient location, call details, and destination hospital are PHI under HIPAA"). DynamoDB encryption at rest, ElastiCache in-transit and at-rest encryption, Kinesis server-side encryption with KMS, and TLS for all API calls are all specified. VPC placement with VPC endpoints for DynamoDB, Kinesis, SageMaker, and CloudWatch Logs is correct. CloudTrail is enabled with the note that "Dispatch decisions are auditable events." The "Never use real patient data in dev" warning is present with a reference to NEMSIS de-identified datasets.

### Issue S1: ElastiCache IAM Permission Is Wildcard-Scoped (HIGH)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The IAM permissions list includes `elasticache:*` with only "(cluster-scoped)" as a parenthetical qualifier. This is the broadest permission in the list and contradicts least-privilege principles. The dispatch Lambda only needs to read from and write to the Redis cache. It does not need permissions to create clusters, modify replication groups, or delete snapshots. A compromised Lambda with `elasticache:*` could destroy the cache infrastructure.

Additionally, the other permissions are listed at the action level (`geo:CalculateRoute`, `dynamodb:GetItem`, etc.) but ElastiCache breaks this pattern with a wildcard. This inconsistency suggests the author wasn't sure which specific ElastiCache actions were needed.

**Suggested fix:** Replace `elasticache:*` with the specific actions needed: for Redis data access via the ElastiCache API, the Lambda needs network access to the Redis endpoint (which is controlled by security groups, not IAM). If using IAM-based Redis authentication (ElastiCache Redis 7.0+), specify `elasticache:Connect` scoped to the specific replication group ARN. Add a note: "ElastiCache Redis access is primarily controlled via security groups (Lambda in the same VPC/subnet with appropriate SG rules). If using IAM-based authentication, scope `elasticache:Connect` to the specific replication group ARN."

### Issue S2: GPS Stream Contains PHI but Key Rotation Strategy Not Discussed (MEDIUM)

**Location:** Prerequisites table, Encryption row; Fleet Tracking section of architecture

**The problem:** The recipe correctly states "Kinesis: server-side encryption with KMS" but doesn't discuss key management specifics. The GPS stream contains unit locations correlated with dispatch events, which in context constitutes PHI (you can determine which patient is being transported where). For a high-throughput stream (GPS updates every 5-15 seconds across a fleet), the KMS key policy and rotation strategy matter:
- Is this a customer-managed CMK or AWS-managed key?
- Who has `kms:Decrypt` access to read the stream?
- Is automatic key rotation enabled?

The recipe also doesn't mention that the Kinesis consumer (GPS processor Lambda) needs `kms:Decrypt` permission on the stream's encryption key.

**Suggested fix:** Add to the Encryption row: "Kinesis: server-side encryption with customer-managed KMS CMK (automatic annual rotation enabled). The GPS processor Lambda role needs `kms:Decrypt` on the stream's CMK. Restrict `kms:Decrypt` grants to only the Lambda execution role and authorized administrative principals. Use a separate CMK for the GPS stream versus other data stores to enable independent access control."

### Issue S3: Dispatch Decision Audit Trail Content Not Specified (MEDIUM)

**Location:** Prerequisites table, CloudTrail row; Expected Results section

**The problem:** The recipe says "Dispatch decisions are auditable events" and the sample output JSON shows a complete decision record. But it doesn't specify where this audit trail is stored, how long it's retained, or what fields are logged. CloudTrail captures API calls, not application-level decisions. The dispatch decision (which unit was assigned, why, what alternatives were considered) is an application event that needs its own audit mechanism.

For EMS systems, dispatch records are legal documents. They're subpoenaed in malpractice cases. "Why did you send Unit 7 instead of Unit 3?" is a question that gets asked in court. The system needs to log not just the decision but the reasoning (scores for all candidates, fleet state at decision time, travel time estimates used).

**Suggested fix:** Add a paragraph after the Expected Results section or in the Prerequisites: "Every dispatch decision must be logged as an immutable audit record. Store the full decision payload (all candidate scores, fleet state snapshot, travel times used, final assignment, and timestamp) in a dedicated DynamoDB table or S3 bucket with object lock. Retention: minimum 7 years (state EMS record retention requirements vary; some require 10 years). These records are legal documents and may be subpoenaed. Include the dispatcher's accept/reject action if the system operates in recommendation mode."

### Issue S4: No Authentication Discussion for API Gateway Dispatch Endpoint (LOW)

**Location:** Architecture diagram, `[911 Call / CAD] -->|Dispatch Request| [API Gateway]`

**The problem:** The API Gateway endpoint that receives dispatch requests from the CAD system has no authentication mechanism discussed. This endpoint triggers immediate ambulance dispatch. An unauthenticated or poorly authenticated endpoint could allow spoofed dispatch requests, denial-of-service attacks on the fleet, or injection of false call data.

**Suggested fix:** Add a note: "The dispatch API Gateway endpoint should use mutual TLS (mTLS) with the CAD system's client certificate, or IAM authentication with SigV4 signing from the CAD integration layer. Rate limiting should be configured to prevent abuse while allowing burst capacity during multi-casualty events. The API should validate that incoming dispatch requests conform to the expected schema (valid coordinates within service area, valid priority codes, valid nature codes)."

---

## Architecture Expert Review

### What's Done Well

The dual-layer architecture (real-time dispatch in under 2 seconds, background repositioning every 2-5 minutes) is exactly the right pattern. The separation of concerns is clean: Kinesis for GPS ingestion, DynamoDB for state, ElastiCache for pre-computed lookups, Lambda for stateless scoring, Step Functions for the multi-step repositioning workflow, SageMaker for demand forecasting. Each service choice is well-justified in the "Why These Services" section.

The scoring function design (weighted composite with priority-based override for Priority 1 calls) is operationally sound. The coverage model explanation is excellent and correctly identifies it as the higher-value optimization layer. The travel time estimation discussion (static, historical, real-time, emergency vehicle adjustments) shows genuine domain knowledge.

### Issue A1: No Failover/Degradation Strategy When Optimization System Is Unavailable (HIGH)

**Location:** Entire recipe (missing section)

**The problem:** The recipe describes a sophisticated optimization system but never addresses what happens when it's down. Lambda cold starts, DynamoDB throttling, ElastiCache node failure, Location Service outage, or a bug in the scoring function could all make the dispatch optimizer unavailable. During that time, 911 calls still come in. People still have cardiac arrests.

Every production EMS dispatch system needs a degradation path: when the optimizer is unavailable, fall back to proximity-based dispatch (closest available unit). The CAD system must be able to operate without the optimization layer. This is not optional for a life-safety system.

The recipe mentions "Most dispatch systems today still rely on CAD software that does basic proximity matching" but never explicitly states that this existing capability must remain as the fallback.

**Suggested fix:** Add a subsection (perhaps after the architecture diagram or in the "Honest Take"): "The optimization layer is an enhancement to existing CAD dispatch, not a replacement for it. The CAD system must retain its native proximity-based dispatch capability as a fallback. If the optimization API returns an error or times out (>3 seconds), the CAD automatically falls back to closest-available-unit dispatch. The system should track fallback rate as a key operational metric. Target: <1% of dispatches use fallback in steady state. Alert if fallback rate exceeds 5% in any 15-minute window, indicating a systemic issue with the optimization layer."

### Issue A2: No Discussion of Dispatcher Override/Recommendation Mode (HIGH)

**Location:** "The Honest Take" section mentions dispatcher resistance but no architectural mechanism

**The problem:** The "Honest Take" section correctly identifies that "Dispatchers will resist" and recommends "Build the system as a recommendation engine, not an override. Let dispatchers accept or reject suggestions." This is excellent operational advice. But the architecture and code sections describe a system that produces an assignment and sends it directly to the CAD/MDT: `C -->|Assignment| H[CAD System / MDT]`. There's no architectural representation of the dispatcher-in-the-loop.

The scoring function returns a ranked list of candidates, which is good. But the architecture doesn't show:
- How the recommendation is presented to the dispatcher
- How the dispatcher accepts, rejects, or modifies the recommendation
- How rejections are logged and fed back into model improvement
- What happens if the dispatcher doesn't act within N seconds (auto-dispatch for Priority 1?)

**Suggested fix:** Add to the architecture diagram a "Dispatcher Console" component between the optimizer output and the CAD/MDT assignment. Add a paragraph: "For Priority 1 calls, the system can auto-dispatch (configurable per agency) with dispatcher notification, or present the top 3 candidates with scores and let the dispatcher confirm within 10 seconds (auto-dispatch if no response). For Priority 2-5 calls, always present as recommendation. The dispatcher console shows: recommended unit, travel time, coverage impact, and the next-best alternative. Dispatcher accept/reject actions are logged with optional free-text reason. Rejection reasons feed quarterly model tuning."

### Issue A3: Lambda Cold Start Risk for Life-Safety Dispatch Function (MEDIUM)

**Location:** "Why These Services" section, Lambda paragraph

**The problem:** The recipe mentions "with provisioned concurrency for the dispatch function, you eliminate cold starts entirely" in a parenthetical. This is correct but understated for a life-safety system. A cold start on the dispatch Lambda could add 1-3 seconds to a Priority 1 cardiac arrest dispatch. The recipe should be more explicit about this being a hard requirement, not an optimization.

Additionally, the recipe doesn't discuss what provisioned concurrency level is appropriate. A metro EMS system might handle 200-500 calls per day, but they're bursty (multi-casualty events can generate 10+ simultaneous dispatch requests). The provisioned concurrency needs to handle the burst, not just the average.

**Suggested fix:** Strengthen the Lambda paragraph: "Provisioned concurrency is mandatory for the dispatch function, not optional. A cold start adding 2 seconds to a cardiac arrest dispatch is unacceptable. Set provisioned concurrency to handle your peak simultaneous dispatch rate (typically 3-5x your average concurrent dispatches to handle MCI bursts). Monitor the `ProvisionedConcurrencySpilloverInvocations` metric; any spillover means a dispatch request hit a cold start. Target: zero spillover invocations."

### Issue A4: DynamoDB Conditional Write in GPS Processor Could Silently Drop Updates (LOW)

**Location:** Step 1 pseudocode, `AND last_gps_time < timestamp`

**The problem:** The conditional write `AND last_gps_time < timestamp` correctly handles out-of-order GPS fixes. But if the condition fails (older fix arrives after a newer one), the write is silently dropped. In DynamoDB, a failed conditional write throws `ConditionalCheckFailedException`. The pseudocode doesn't show handling this exception. If the GPS processor Lambda doesn't catch this exception, it will retry the message from Kinesis (Lambda retries on unhandled exceptions), creating an infinite retry loop on out-of-order messages.

**Suggested fix:** Add a comment in the pseudocode: "// If conditional write fails (out-of-order fix), catch the exception and discard. // This is expected behavior, not an error. Log at DEBUG level for troubleshooting. // Do NOT retry or raise; the newer fix is already in the table."

---

## Networking Expert Review

### What's Done Well

The VPC section correctly specifies Lambda functions in VPC with VPC endpoints for DynamoDB, Kinesis, SageMaker, and CloudWatch Logs. ElastiCache in VPC (mandatory) is noted. The Location Service access path (VPC endpoint or NAT Gateway) is mentioned. The GPS ingestion via Kinesis with Lambda consumer is a clean pattern that avoids exposing the fleet state store directly to external GPS devices.

### Issue N1: GPS Device to Kinesis Ingestion Path Not Secured (MEDIUM)

**Location:** Architecture diagram, `[Ambulance GPS] -->|Location Stream| [Kinesis Data Streams]`

**The problem:** The architecture shows ambulance GPS devices sending data directly to Kinesis. But ambulance GPS/AVL (Automatic Vehicle Location) systems are typically cellular-connected devices in moving vehicles. The recipe doesn't discuss how these devices authenticate to Kinesis or how the data path is secured:
- Do the GPS devices have IAM credentials? (Problematic: rotating credentials on hundreds of mobile devices)
- Is there an IoT gateway or API intermediary?
- Is the cellular connection encrypted beyond carrier-level encryption?
- What prevents a spoofed GPS device from injecting false position data?

False position data could cause the optimizer to dispatch the wrong unit (believing a unit is close when it's actually far away), directly impacting patient outcomes.

**Suggested fix:** Add a note in the Fleet Tracking section: "GPS/AVL devices typically connect through a vendor-provided gateway (e.g., the AVL vendor's cloud platform) which then forwards to Kinesis via an authenticated API. Use API Gateway with API keys or IAM auth as the ingestion endpoint rather than direct Kinesis PutRecord from devices. Validate GPS coordinates (within service area bounds, speed physically plausible, timestamp recent). Flag and quarantine position reports that show impossible movement (teleportation, speeds >200 mph) as potential device malfunction or spoofing."

### Issue N2: Location Service Fallback Path Through NAT Gateway Creates PHI Egress (LOW)

**Location:** Prerequisites table, VPC row: "Location Service accessed via VPC endpoint or NAT Gateway"

**The problem:** The recipe offers NAT Gateway as an alternative to VPC endpoint for Location Service access. When the dispatch Lambda calls Location Service through a NAT Gateway, the request (containing origin/destination coordinates that may constitute PHI in context) traverses the public internet to reach the Location Service endpoint. While TLS encrypts the payload, the NAT Gateway path means PHI-adjacent data leaves the VPC boundary.

For a HIPAA-regulated system, the VPC endpoint path should be the recommendation, not an alternative. NAT Gateway should only be mentioned as a fallback if the VPC endpoint is unavailable in the region.

**Suggested fix:** Change "Location Service accessed via VPC endpoint or NAT Gateway" to "Location Service accessed via VPC endpoint (preferred; keeps all traffic within the AWS network). Use NAT Gateway only if the Location Service VPC endpoint is not available in your region."

---

## Voice Reviewer

### What's Done Well

The voice is excellent throughout. The opening paragraph ("A 911 call comes in. Chest pain, 67-year-old male...") immediately puts the reader in the dispatcher's seat. The cascading questions build tension effectively. The technology section maintains the teaching energy without becoming dry. Parenthetical asides are well-placed and natural. The "Honest Take" section is genuinely insightful, particularly the observation about data integration being 70% of the project and the dispatcher resistance discussion. The 70/30 vendor balance is well-maintained: the entire first half (Problem, Technology, General Architecture) is vendor-agnostic.

### Issue V1: Two TODO Comments in Additional Resources (MEDIUM)

**Location:** Additional Resources, Industry References section

**The problem:** Two TODO items are visible:
- "TODO: Verify link for NAEMD response time standards documentation"
- "TODO: Verify link for specific OR papers on ambulance dispatch optimization (Gendreau et al., Brotcorne et al.)"

These indicate unfinished work and violate the "Only real, verified URLs" rule. The recipe references specific authors (Gendreau, Brotcorne) in the TODO but doesn't provide the actual citations. For a recipe that discusses operations research extensively, academic references would strengthen credibility.

**Suggested fix:** Either verify and add the specific links, or remove the TODOs and replace with verified references. For NAEMD standards, link to the publicly available NAEMD position papers. For OR papers, cite: Gendreau, M., Laporte, G., & Semet, F. (2001). "A dynamic model and parallel tabu search heuristic for real-time ambulance relocation." Parallel Computing, 27(12), 1641-1653. Brotcorne, L., Laporte, G., & Semet, F. (2003). "Ambulance location and relocation models." European Journal of Operational Research, 147(3), 451-463. Provide DOI links rather than potentially unstable URLs.

### Issue V2: One Instance of Documentation-Voice Creep (LOW)

**Location:** "Why These Services" section, first sentence of the Amazon Location Service paragraph

**The problem:** "Location Service provides route calculation with real-time traffic awareness." This is a product description sentence. It reads like AWS documentation rather than an engineer explaining a choice. Compare with the Lambda paragraph which starts with "The dispatch decision is a short-lived, stateless computation:" which immediately explains the architectural reasoning.

**Suggested fix:** Rewrite to lead with the architectural need: "You need road-network travel times that account for current traffic conditions. Amazon Location Service gives you this: route calculations between arbitrary points with real-time traffic awareness, including route matrices (many-to-many travel times) which is exactly what you need when evaluating multiple candidate units against a call location."

---

## Stage 2: Expert Discussion

### Overlapping Concerns

1. **Architecture (A1) and Architecture (A2) compound on operational readiness.** The missing failover strategy (A1) and missing dispatcher override mechanism (A2) together mean the recipe describes a system that has no graceful degradation at any level: no fallback when the optimizer fails, and no human override when the optimizer makes a bad recommendation. For a life-safety system, this combination is the most important gap to address.

2. **Security (S3) and Architecture (A2) overlap on the audit trail.** The dispatch decision audit (S3) and the dispatcher accept/reject logging (A2) are the same system. The audit trail needs to capture both the optimizer's recommendation AND the dispatcher's action on that recommendation. Design these together.

3. **Security (S4) and Networking (N1) both address the system boundary.** The API Gateway authentication for CAD integration (S4) and the GPS device ingestion security (N1) are both about securing inbound data paths. A comprehensive "integration security" section would address both.

### Priority Resolution

The failover/degradation strategy (A1) is the highest-priority finding because this is a life-safety system. An optimization system that fails without fallback could delay ambulance dispatch during the failure window. The dispatcher override mechanism (A2) is second because it determines whether the system is operationally adoptable. The GPS ingestion security (N1) is elevated because false position data directly impacts dispatch accuracy and patient outcomes.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Architecture | Entire recipe (missing) | No failover/degradation strategy. When the optimization system is unavailable, 911 calls still come in. No fallback to proximity-based dispatch is described. | Add failover section: CAD retains native dispatch as fallback, 3-second timeout triggers fallback, monitor fallback rate, alert on >5% fallback in 15-minute window. |
| 2 | HIGH | Architecture | "Honest Take" mentions dispatcher resistance but architecture shows direct assignment to MDT | No dispatcher-in-the-loop mechanism. Architecture shows optimizer output going directly to CAD/MDT with no human confirmation step. Contradicts the recipe's own advice about recommendation mode. | Add dispatcher console to architecture, define auto-dispatch vs. recommendation mode by priority level, log accept/reject actions, feed rejections into model improvement. |
| 3 | HIGH | Security | Prerequisites, IAM Permissions row | `elasticache:*` is wildcard-scoped, contradicts least-privilege. Inconsistent with the action-level specificity of other permissions in the same table. | Replace with specific actions or clarify that Redis data access is SG-controlled. If using IAM auth, scope `elasticache:Connect` to specific replication group ARN. |
| 4 | MEDIUM | Networking | Architecture diagram, Fleet Tracking | GPS device to Kinesis ingestion path has no authentication or validation discussion. Spoofed GPS data could cause wrong unit dispatch with patient safety impact. | Add API Gateway intermediary for GPS ingestion, validate coordinates (bounds, speed, timestamp), flag impossible movement patterns. |
| 5 | MEDIUM | Security | Prerequisites, Encryption row | GPS stream KMS key management not specified (CMK vs. AWS-managed, rotation, decrypt grants). High-throughput PHI stream needs explicit key policy. | Specify customer-managed CMK with auto-rotation, restrict kms:Decrypt to GPS processor Lambda role only. |
| 6 | MEDIUM | Security | Expected Results section (missing) | Dispatch decision audit trail not specified. Dispatch records are legal documents subpoenaed in malpractice cases. Need immutable storage with 7-10 year retention. | Add audit trail specification: full decision payload, immutable storage (S3 object lock or DynamoDB), 7-10 year retention, include all candidate scores and fleet state snapshot. |
| 7 | MEDIUM | Architecture | "Why These Services", Lambda paragraph | Provisioned concurrency mentioned as parenthetical but is a hard requirement for life-safety dispatch. No guidance on concurrency level for burst handling. | Strengthen to mandatory requirement, specify sizing for MCI bursts (3-5x average), monitor spillover metric with zero-tolerance target. |
| 8 | MEDIUM | Voice | Additional Resources, Industry References | Two TODO comments visible indicating unverified links. Violates "Only real, verified URLs" rule. | Remove TODOs, add verified academic citations (Gendreau 2001, Brotcorne 2003) with DOI links. |
| 9 | LOW | Security | Architecture diagram, API Gateway | No authentication mechanism discussed for the dispatch API endpoint. Unauthenticated endpoint could allow spoofed dispatch requests. | Add mTLS or IAM SigV4 auth for CAD integration, rate limiting, schema validation. |
| 10 | LOW | Architecture | Step 1 pseudocode | Conditional write failure (out-of-order GPS) not handled. Could cause infinite Lambda retry loop on Kinesis. | Add exception handling comment: catch ConditionalCheckFailedException, discard gracefully, log at DEBUG. |
| 11 | LOW | Networking | Prerequisites, VPC row | NAT Gateway offered as equal alternative to VPC endpoint for Location Service. NAT path sends PHI-adjacent coordinates over public internet. | Recommend VPC endpoint as primary, NAT Gateway only as regional fallback. |
| 12 | LOW | Voice | "Why These Services", Location Service paragraph | First sentence reads like product documentation rather than architectural reasoning. | Lead with the architectural need, then introduce the service as the solution. |

---

## Summary

**Verdict: PASS**

This is one of the strongest recipes in the book. The problem statement is compelling, the technology explanation is genuinely educational (the VRP formulation, solver taxonomy, and coverage problem discussion would be valuable in an OR textbook), and the "Honest Take" section demonstrates real operational wisdom. The architecture is sound and the service choices are well-justified.

The three HIGH findings are all additive rather than structural:
1. **Failover strategy** (A1) is the most critical for a life-safety system. A single paragraph establishing that the CAD's native dispatch remains as fallback addresses this.
2. **Dispatcher override** (A2) is needed for operational adoption. The recipe's own "Honest Take" identifies this need but the architecture doesn't implement it. Adding a dispatcher console component and defining auto-dispatch vs. recommendation mode by priority level resolves this.
3. **ElastiCache wildcard permission** (S3) is a straightforward fix to align with the least-privilege pattern used for all other services in the recipe.

No CRITICAL findings. Three HIGH findings (within the PASS threshold). The recipe demonstrates excellent domain knowledge of EMS operations, operations research, and real-time systems architecture. With the HIGH findings addressed, this will be a standout recipe in the optimization chapter.
