# Expert Review: Recipe 14.6 - Patient Flow and Bed Assignment

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter14.06-patient-flow-bed-assignment.md`

---

## Overall Assessment

This is an outstanding recipe. The problem framing is one of the best in the book: the opening scenario (14 ED boarders, pending discharges, skill-mix mismatches, a direct admission arriving in 45 minutes) is viscerally real and immediately communicates why this problem is hard. The technology section is genuinely educational, covering the assignment problem formulation, constraint hierarchies, multi-objective optimization, solver selection for real-time problems, and the critical state estimation challenge. A reader on any cloud walks away understanding bed assignment optimization at a deep level.

The architecture is well-decomposed (five logical layers), the AWS implementation choices are justified, and the pseudocode is clear and well-commented. The "Honest Take" section delivers hard-won operational wisdom (data is 80% of the work, staff trust takes 6-12 months, cleaning time is the hidden bottleneck) that you won't find in vendor marketing materials.

The recipe correctly identifies that this is a dynamic, continuously re-solved problem (not a batch optimization), and the hybrid event-triggered-with-debouncing approach is the right architectural choice. The constraint formulation distinguishes hard safety constraints from operational constraints from soft preferences, which is exactly how real bed management works.

Issues found are primarily around security gaps in the real-time data handling (patient identifiers in WebSocket payloads, override audit completeness), one architectural concern around Redis as a single point of failure for the debounce/working-state layer, and minor completeness items. Nothing rises to CRITICAL.

**Verdict: PASS**

---

## Stage 1: Independent Expert Reviews

---

### Security Expert Review

#### What's Done Well

BAA requirement is correctly identified with a clear rationale: bed assignments reference patient identifiers, diagnoses, and isolation status. Encryption at rest (DynamoDB encryption, SSE-KMS) and in transit (TLS everywhere) are specified. CloudTrail is required for all assignment decisions and overrides. The "never use real PHI in dev" warning is present in the prerequisites. VPC is required for ElastiCache and EHR connectivity. The sample output uses a realistic but clearly synthetic patient identifier format.

#### Issue S1: WebSocket Payloads Contain PHI Without Content Minimization Guidance (HIGH)

**Location:** Step 5 pseudocode, `publish_recommendations` function; Expected Results sample JSON

**The problem:** The recommendation payload pushed via WebSocket includes `patient_name: "J. Martinez"`, `acuity: "STEP_DOWN"`, `isolation: "NONE"`, and clinical reasoning strings like "Nurse with cardiac drip certification available on shift" (which implies the patient needs a cardiac drip). This is PHI being pushed over a WebSocket connection to a browser-based dashboard.

While API Gateway WebSocket uses TLS in transit, the payload persists in browser memory, browser developer tools, and potentially browser local storage or session logs. The sample JSON shows more clinical detail than a bed coordinator needs to make an assignment decision. The reasoning array includes clinical information ("cardiac drip certification") that reveals the patient's treatment plan.

**Suggested fix:** Add guidance on PHI minimization in WebSocket payloads. The recommendation push should include: patient MRN (not name), bed assignment, confidence score, and a reasoning summary that references constraint categories ("clinical match: equipment requirement satisfied") rather than specific clinical details ("cardiac drip certification available"). Full clinical reasoning should be available on-demand via the REST API (authenticated, audited) when the coordinator clicks into a specific recommendation, not pushed proactively to all connected sessions.

#### Issue S2: Override Reason Free-Text Field Creates Unstructured PHI Risk (MEDIUM)

**Location:** Step 5 pseudocode, `handle_coordinator_response` function, `override_reason` parameter

**The problem:** When a coordinator overrides a recommendation, they provide a free-text `override_reason`. In practice, coordinators will write things like "Patient has history of violence, can't be near room 312" or "Family requested private room due to end-of-life care" or "Patient is a VIP (hospital board member)." This free-text field becomes an unstructured PHI repository that's harder to govern, audit, and redact than structured data.

The recipe stores this in DynamoDB and queues it for model review (`queue_for_model_review`). If this data is used for ML training or analytics, the PHI in override reasons needs to be identified and handled appropriately.

**Suggested fix:** Add a note recommending structured override reason codes (e.g., "SAFETY_CONCERN", "PATIENT_REQUEST", "EQUIPMENT_ISSUE", "STAFFING_CONSTRAINT", "OTHER") with an optional free-text field that is flagged as PHI-containing and subject to access controls and retention policies distinct from the structured assignment data. The model review pipeline should not ingest raw free-text override reasons without PHI scrubbing.

#### Issue S3: No Session Management or Authorization Model for WebSocket Connections (MEDIUM)

**Location:** Architecture section, "API Gateway + WebSocket API for the staff interface"

**The problem:** The recipe specifies WebSocket for real-time push to bed coordinators but doesn't address authentication, authorization, or session management. Questions unanswered: How are WebSocket connections authenticated? (API Gateway supports Lambda authorizers for WebSocket `$connect`.) Who can see which recommendations? (A charge nurse on 4-West should see only 4-West assignments, not the entire hospital.) How are stale connections handled? (A coordinator who walks away from their screen still has an open WebSocket receiving PHI.)

**Suggested fix:** Add a brief note in the architecture or prerequisites: WebSocket connections should use a Lambda authorizer on `$connect` that validates the user's session token and unit-level authorization. Implement connection TTLs (disconnect after 30 minutes of inactivity) and require re-authentication. Filter recommendation pushes by the coordinator's authorized units. This prevents a compromised or abandoned session from accumulating PHI.

#### Issue S4: Sample Output Includes Patient Name (LOW)

**Location:** Expected Results, sample JSON, `patient_name: "J. Martinez"`

**The problem:** The sample output includes a patient name field. While this is synthetic data in the recipe, it normalizes the pattern of including patient names in API responses. In production, bed management systems should use MRN or encounter ID as the identifier, with name resolution happening at the UI layer from a separate identity service. Including names in the optimization output means the optimization service has access to the patient identity service, which broadens its attack surface.

**Suggested fix:** Remove `patient_name` from the sample JSON or replace with a note: "// Name resolved at UI layer from MRN lookup." This models the principle of minimum necessary identifiers in service-to-service communication.

---

### Architecture Expert Review

#### What's Done Well

The five-layer architecture (State Ingestion, State Model, Optimization Engine, Recommendation Service, Staff Interface) is clean and well-decomposed. The hybrid event-triggered-with-debouncing approach is the correct choice for this problem class. The solver selection discussion (MIP vs. CP vs. greedy heuristics vs. hybrid) is excellent and correctly identifies CP as particularly well-suited for the heterogeneous constraint structure. The performance benchmarks (1-3 seconds for 400-bed hospital) are realistic for OR-Tools CP-SAT.

The state estimation discussion ("the current state of the hospital is surprisingly hard to know accurately") is one of the recipe's strongest sections and reflects genuine operational experience. The distinction between "soft availability" and actual availability is a real insight that most vendor presentations skip.

#### Issue A1: ElastiCache Redis as Single Point of Failure for Debounce and Working State (HIGH)

**Location:** Architecture section, ElastiCache role; Architecture diagram

**The problem:** Redis holds the debounce timers and in-flight recommendation state. If Redis becomes unavailable (node failure, failover, network partition), the system loses: (1) the ability to debounce state changes (every ADT event triggers a full optimization run, potentially overwhelming the solver), (2) knowledge of which recommendations are pending acceptance (coordinators see stale or duplicate recommendations), and (3) the working state that prevents re-recommending beds that are already in-flight.

The recipe doesn't mention Redis cluster mode, Multi-AZ replication, or a fallback strategy. A single-node Redis failure during a busy period (when the system is most needed) would degrade the entire optimization pipeline.

**Suggested fix:** Add a note specifying ElastiCache Redis with Multi-AZ replication (automatic failover) as the minimum production configuration. Additionally, the optimization Lambda should handle Redis unavailability gracefully: if the debounce timer can't be read, fall back to the periodic EventBridge schedule (every 5 minutes). If in-flight state can't be read, the solver should treat all beds as potentially available and flag recommendations with lower confidence. This degrades gracefully rather than failing completely.

#### Issue A2: No Dead Letter Queue for Kinesis Processing Failures (MEDIUM)

**Location:** Architecture diagram; Step 1 pseudocode, event processing

**The problem:** The Kinesis-to-Lambda event processing path has no error handling for events that fail processing. If an ADT event is malformed, references a bed ID that doesn't exist in DynamoDB, or triggers a Lambda error, the event is retried (Kinesis default behavior) and eventually ages out of the stream. There's no DLQ or error destination configured.

In a hospital environment, a lost ADT event means the state model diverges from reality. A discharge event that fails processing means a bed shows as occupied when it's actually empty. This is a silent failure that degrades optimization quality without any alert.

**Suggested fix:** Add Lambda event source mapping with a failure destination (SQS DLQ or SNS topic). Add a CloudWatch alarm on the DLQ depth. In the pseudocode, add a try/catch around event processing that sends failed events to the DLQ with the error context. Add a note: "Monitor the DLQ. Any event in it means your state model is diverging from reality. Investigate immediately."

#### Issue A3: Recommendation Expiry Without Re-Optimization Creates Gaps (MEDIUM)

**Location:** Step 5 pseudocode, `expires_at = NOW() + minutes(15)`

**The problem:** Recommendations expire after 15 minutes. If a coordinator doesn't act within 15 minutes, the recommendation disappears. But the recipe doesn't specify what happens next. Does the patient remain in the pending queue? Does the next optimization run automatically generate a new recommendation? What if the bed that was recommended is no longer available (assigned to someone else, or went into cleaning)?

The gap between "recommendation expired" and "next optimization run" could leave patients without recommendations if the system is in periodic mode and the next run isn't for several minutes.

**Suggested fix:** Add a note: expired recommendations should trigger an immediate re-optimization for the affected patient (not a full hospital re-solve, just a single-patient assignment). Alternatively, the periodic optimization run should always include patients whose previous recommendations expired without action. The patient should never silently fall out of the pending queue because a recommendation timed out.

#### Issue A4: No Capacity Planning Guidance for Kinesis Shard Count (LOW)

**Location:** Prerequisites, "Amazon Kinesis Data Streams for real-time state ingestion"

**The problem:** The recipe says Kinesis handles "hundreds to low thousands per hour" of ADT events. A single Kinesis shard supports 1,000 records/second (1 MB/second) write and 2 MB/second read. For the stated volume, a single shard is sufficient. But the recipe doesn't mention shard count, and a reader might over-provision (wasting money) or under-provision for a large health system with multiple facilities feeding the same stream.

**Suggested fix:** Add a brief note: "A single Kinesis shard is sufficient for most single-hospital deployments (up to ~3,600 events/hour). Multi-campus systems or those integrating real-time bed sensor data may need 2-4 shards. Partition by facility ID to maintain per-facility ordering."

---

### Networking Expert Review

#### What's Done Well

The prerequisites correctly specify VPC as required, with the rationale that ElastiCache must be in VPC and EHR integration likely requires VPC connectivity (Direct Connect or VPN). The architecture keeps PHI-containing data flows within the VPC boundary. TLS is specified for all connections. The ElastiCache in-transit encryption requirement is explicitly called out.

#### Issue N1: VPC Endpoint List Is Incomplete (MEDIUM)

**Location:** Prerequisites table, VPC row

**The problem:** The prerequisites state "ElastiCache must be in VPC. Lambda functions accessing Redis need VPC configuration. EHR integration likely requires VPC connectivity." But no VPC endpoints are listed. Lambda functions in a VPC need VPC endpoints to reach AWS services without a NAT gateway. The architecture uses DynamoDB, Kinesis, Step Functions, EventBridge, API Gateway (for WebSocket management API `execute-api:ManageConnections`), and CloudWatch Logs. Without endpoints, these calls either fail (no internet route) or traverse a NAT gateway (additional cost and a potential PHI egress path).

**Suggested fix:** Add to the VPC row: "Required VPC endpoints: DynamoDB (gateway), S3 (gateway, for any logging/artifacts), Kinesis (interface), Step Functions (interface), EventBridge (interface), CloudWatch Logs (interface), execute-api (interface, for WebSocket connection management), KMS (interface, for encryption operations). Interface endpoints cost ~$7-8/month each in a 3-AZ deployment; budget ~$50-60/month for the full set."

#### Issue N2: No Discussion of EHR Integration Network Path (MEDIUM)

**Location:** Architecture section, "State Ingestion" layer; Prerequisites, VPC row

**The problem:** The recipe mentions "EHR integration likely requires VPC connectivity (Direct Connect or VPN)" in passing but doesn't elaborate. The ADT event feed from the EHR is the most critical data path in the entire system. If this connection fails, the state model goes stale and the optimizer produces incorrect recommendations. The recipe should address: Is the EHR on-premises (requiring Direct Connect or Site-to-Site VPN)? Is it a cloud-hosted EHR (requiring VPC peering or PrivateLink)? What's the redundancy model for this connection?

**Suggested fix:** Add a brief paragraph in the State Ingestion section or prerequisites: "The ADT event feed is the system's lifeline. For on-premises EHRs, use AWS Direct Connect with a VPN backup for redundancy. For cloud-hosted EHRs (Epic on Azure, Cerner on AWS), use VPC peering or PrivateLink. Monitor the connection health and alert immediately on disconnection. If the ADT feed is down for more than 5 minutes, the system should surface a 'stale state' warning to coordinators and fall back to manual assignment."

#### Issue N3: WebSocket Connection Egress Path Not Specified (LOW)

**Location:** Architecture section, API Gateway WebSocket

**The problem:** The WebSocket API Gateway endpoint is internet-facing (coordinators connect from hospital workstations or mobile devices). The recipe doesn't discuss whether this should be a private API (accessible only from the hospital network) or a public API with authentication. For a system handling PHI-containing recommendations, the network exposure model matters.

**Suggested fix:** Add a note: "For hospitals with a defined network perimeter, deploy the WebSocket API as a private API accessible only via the hospital's VPN or Direct Connect path. For systems that need mobile access (coordinators on tablets throughout the hospital), use a public endpoint with mutual TLS or a WAF rule restricting source IPs to the hospital's network ranges."

---

### Voice Reviewer

#### What's Done Well

The voice is exceptional throughout. The opening scenario is one of the most vivid in the entire cookbook: it puts you in the charge nurse's shoes and makes you feel the chaos. The technology section maintains genuine enthusiasm ("This is where optimization gets interesting") without tipping into hype. The constraint taxonomy (hard/operational/preference) is taught with clear examples that a non-technical reader can follow. The "Honest Take" section is outstanding: "The data problem is 80% of the work," "Staff trust takes 6-12 months to build," and "Cleaning time is the hidden bottleneck" are all genuine operational insights delivered with CC's signature self-deprecating expertise.

The 70/30 vendor balance is well-maintained. The Technology section and General Architecture Pattern are entirely vendor-agnostic (approximately 65% of the recipe's prose). AWS services appear only in the implementation section. A reader on GCP or Azure would learn the full bed assignment optimization approach without needing to translate service names.

The pseudocode comments are accessible to non-coders while remaining technically accurate. The "If you skip this step" warnings before each pseudocode block are a nice touch that serves the mixed audience.

#### Issue V1: Zero Em Dashes Found

No em dashes anywhere in the recipe. Clean.

#### Issue V2: Two TODO Items in Additional Resources (LOW)

**Location:** Additional Resources section, "Healthcare Operations Research" subsection

**The problem:** Two entries read "TODO: Verify link for IHI patient flow resources" and "TODO: Verify link for AHRQ hospital capacity management toolkit." These are placeholder items that should not appear in a published recipe.

**Suggested fix:** Either verify and add the actual URLs, or remove these entries entirely before publication. The recipe already has sufficient resources from AWS docs and optimization library documentation.

#### Issue V3: "Where It Struggles" Section Could Be Slightly More Self-Deprecating (LOW)

**Location:** Expected Results, "Where It Struggles" subsection

**The problem:** The four bullet points in "Where It Struggles" are accurate and useful, but they read slightly more like documentation than CC's voice. Compare to the Honest Take section (which is perfectly voiced). The "Where It Struggles" bullets are factual but lack the personal "I learned this the hard way" energy that characterizes the rest of the recipe.

**Suggested fix:** Minor voice polish. For example, the behavioral health bullet could add: "We've seen 60%+ override rates for behavioral health placements. The model just doesn't have the context." The mass casualty bullet could add: "Don't try to optimize during a surge. Just place people safely and sort it out later." This is a polish item, not a structural issue.

---

## Stage 2: Expert Discussion

**S1 and N3 interaction:** The WebSocket PHI exposure (S1) and the WebSocket network path (N3) are related. If the WebSocket is internet-facing AND payloads contain clinical details, the risk surface is larger. If the WebSocket is restricted to the hospital network, the PHI exposure risk is reduced (though not eliminated, since hospital networks are not zero-trust). These should be addressed together: minimize payload content (S1) AND restrict network access (N3).

**A1 and A2 priority:** The Redis SPOF (A1) is HIGH because it affects the entire optimization pipeline during failure. The DLQ gap (A2) is MEDIUM because individual event failures are less catastrophic (the state model drifts slightly) but still need detection. A1 should be fixed first because Redis failure during peak hours (when the system is most needed) is a realistic scenario.

**S3 and the architecture:** The WebSocket authorization gap (S3) is a prerequisite for fixing S1. You can't minimize PHI in payloads effectively if you don't know who's receiving them. Unit-level authorization determines what each coordinator should see, which determines what the system should push.

**A3 and the operational model:** The recommendation expiry gap (A3) interacts with the "Honest Take" observation that coordinators are busy and may not respond immediately. A 15-minute expiry with no automatic re-queue means patients can fall through the cracks during busy periods, which is exactly when the system should be most helpful.

---

## Stage 3: Synthesized Feedback

**Verdict: PASS**

No CRITICAL findings. One HIGH finding (below the 3-HIGH threshold for FAIL). The recipe is architecturally sound, clinically grounded, exceptionally well-voiced, and deeply educational. The constraint formulation, solver selection guidance, and state estimation discussion are among the best technical teaching in the cookbook. The issues below improve production-readiness and security posture but don't indicate fundamental design flaws.

### Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | HIGH | Security | Step 5, WebSocket push; Expected Results JSON | WebSocket payloads contain patient names and clinical details (cardiac drip, isolation status) pushed to browser sessions without content minimization | Minimize payloads to MRN + bed + confidence; serve clinical reasoning on-demand via authenticated REST API |
| 2 | HIGH | Architecture | Architecture section, ElastiCache | Redis is SPOF for debounce timers and in-flight state; node failure during peak hours degrades entire pipeline | Specify Multi-AZ replication; add graceful degradation (fall back to periodic schedule if Redis unavailable) |
| 3 | MEDIUM | Security | Step 5, `handle_coordinator_response` | Override reason free-text field creates unstructured PHI repository used for model training without scrubbing | Add structured reason codes; flag free-text as PHI-containing with separate access controls and retention |
| 4 | MEDIUM | Security | Architecture, WebSocket API | No authentication, authorization, or session management model for WebSocket connections receiving PHI | Add Lambda authorizer on $connect; implement unit-level filtering; add connection TTLs |
| 5 | MEDIUM | Architecture | Architecture diagram, Kinesis-to-Lambda | No DLQ for failed ADT event processing; lost events cause silent state model divergence | Add SQS DLQ on Lambda event source mapping; alarm on DLQ depth; note that any DLQ message means state divergence |
| 6 | MEDIUM | Architecture | Step 5, recommendation expiry | 15-minute expiry with no automatic re-queue; patients can silently fall out of pending queue during busy periods | Expired recommendations trigger single-patient re-optimization or automatic re-queue for next batch run |
| 7 | MEDIUM | Networking | Prerequisites, VPC | No VPC endpoints listed; Lambda in VPC will fail to reach DynamoDB, Kinesis, Step Functions, EventBridge, CloudWatch without them | List all required endpoints (gateway and interface) with cost estimate (~$50-60/month) |
| 8 | MEDIUM | Networking | State Ingestion layer | EHR integration network path mentioned in passing but not elaborated; ADT feed is the system's lifeline with no redundancy discussion | Add paragraph on Direct Connect + VPN backup for on-premises EHR; monitoring and stale-state fallback |
| 9 | LOW | Security | Expected Results, sample JSON | `patient_name` field in sample output normalizes including names in service responses; should use MRN with UI-layer name resolution | Remove patient_name or replace with comment noting UI-layer resolution |
| 10 | LOW | Architecture | Prerequisites, Kinesis | No shard count guidance; readers may over- or under-provision | Add note: single shard sufficient for most single-hospital deployments; partition by facility for multi-campus |
| 11 | LOW | Networking | Architecture, WebSocket API | No discussion of whether WebSocket endpoint should be private (hospital network only) or public with restrictions | Add note on private API for network-perimeter hospitals; WAF/IP restriction for mobile access |
| 12 | LOW | Voice | Additional Resources | Two "TODO: Verify link" placeholders in published content | Verify and add URLs, or remove entries before publication |
| 13 | LOW | Voice | Expected Results, "Where It Struggles" | Bullets are accurate but slightly more doc-voice than the rest of the recipe; lacks CC's personal "learned this the hard way" energy | Minor voice polish: add personal observations to each bullet |

### Priority Actions Before Publication

1. **Fix S1/A1 (HIGH):** Address WebSocket PHI exposure and Redis SPOF together. Minimize WebSocket payloads to non-clinical identifiers and scores. Specify Redis Multi-AZ with graceful degradation. These are the two findings that could cause real problems in production.

2. **Fix S3 + S2 (MEDIUM):** Add WebSocket authorization model (Lambda authorizer, unit-level filtering, connection TTLs). Add structured override reason codes. These are security hygiene items that should be in place before any PHI flows through the system.

3. **Fix A2 + A3 (MEDIUM):** Add DLQ for Kinesis processing failures and automatic re-queue for expired recommendations. Both prevent silent failures that degrade system reliability during the busiest periods.

4. **Fix N1 + N2 (MEDIUM):** List VPC endpoints and elaborate on EHR integration network path. These are deployment blockers for anyone following the recipe in a production VPC.

5. **Remove TODOs (LOW):** Resolve or remove the two placeholder items in Additional Resources.

---

*Review complete. Recipe 14.6 is one of the strongest entries in the optimization chapter. The problem framing is visceral, the technology teaching is deep and genuinely vendor-agnostic, the constraint formulation reflects real clinical operations, and the Honest Take delivers operational wisdom that would take years to learn firsthand. The state estimation discussion ("the current state of the hospital is surprisingly hard to know accurately") is a standout section that should resonate with anyone who has tried to build real-time hospital systems. The fixes above harden the security and resilience posture for production deployment but don't diminish the recipe's exceptional educational value.*
