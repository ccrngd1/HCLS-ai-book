# Expert Review: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter12.07-vital-sign-trajectory-monitoring.md` (PRESENT)
**Python companion:** `chapter12.07-python-example.md` (NOT PRESENT)
**Code review:** `reviews/chapter12.07-code-review.md` (FAIL, upstream missing at time of code review)

---

## Overall Assessment

**Verdict: PASS**

This is an excellent recipe. The opening vignette (a patient whose heart rate creeps up 3-4 bpm/hour for six hours with no threshold crossing, then codes) is the most clinically visceral opening in chapter 12 to date and immediately establishes why trajectory matters more than threshold. The technology section is genuinely pedagogical: patient-specific baselines, trend decomposition, slope estimation, multi-variate correlation, and changepoint detection are each explained as first-class concepts before any vendor name appears. The "Why This Is Hard" subsection is unusually honest and specific: alert fatigue, artifact vs. real change, medication effects, intermittent vs. continuous data, and clinical actionability are each a paragraph of hard-earned production wisdom. The architecture pattern (six-component pipeline from sources through clinical display) is sound and the AWS implementation maps cleanly onto it with appropriate service choices. The pseudocode is well-structured across six steps with clear business justifications for each. The "Honest Take" section reads like lived experience.

The voice is consistent throughout: engineer-explaining-over-lunch, no documentation-voice, no marketing language. Em dash count is zero (confirmed via U+2014 codepoint scan). The 70/30 vendor balance is well-maintained: the Technology section runs approximately 2,800 words vendor-free before AWS services appear. The General Architecture Pattern subsection is fully vendor-agnostic.

The recipe has two unresolved TODO items (one in the Technology section about verifying deterioration prediction improvement statistics, one in Additional Resources about verifying GitHub repo links). These are flagged as findings below but are appropriately marked by the author for pre-publication resolution.

Priority breakdown: 0 CRITICAL, 2 HIGH, 4 MEDIUM, 3 LOW. **Verdict: PASS** (under the FAIL threshold of >0 CRITICAL or >3 HIGH).

---

## Stage 1: Independent Expert Reviews

### Security Expert Review (OWASP, CIS, NIST SP 800-66 for HIPAA)

**Strengths.**

- BAA requirement is explicitly stated in the Prerequisites table: "AWS BAA signed (vital signs are PHI; all services must be HIPAA-eligible)." This is correct. Continuous vital sign data is PHI under HIPAA.
- Encryption posture is specified per service: Kinesis server-side encryption with KMS, DynamoDB encryption at rest (default), Timestream encryption at rest (default), SNS encrypted topics, all transit over TLS. This matches the chapter-12 pattern.
- CloudTrail is required for all API calls with the note "Critical for audit trail on alert generation and delivery." This is the right framing for a clinical safety system where audit of when alerts fired and when they were delivered is a regulatory requirement.
- The Prerequisites table specifies VPC deployment with VPC endpoints for DynamoDB, Timestream, SNS, CloudWatch Logs, and interface endpoints for Kinesis.
- Sample data guidance is explicit: MIMIC-III/MIMIC-IV from PhysioNet for development, "Never use real patient data in dev environments."
- IAM permissions are enumerated with specific actions rather than wildcard grants.

**Gaps.**

- **IAM permissions include `kinesisanalytics:*` which is not least-privilege.** The Prerequisites table lists `kinesisanalytics:*` as a required permission. This is a wildcard grant on the entire Kinesis Data Analytics API surface, which includes `CreateApplication`, `DeleteApplication`, `UpdateApplication`, and administrative actions that should not be available to the runtime execution role. The recipe should scope this to the specific actions needed: `kinesisanalytics:DescribeApplication`, `kinesisanalytics:ListApplications`, and the runtime actions needed by the Flink application itself. The deployment role (used by CI/CD to create/update the application) is separate from the execution role (used by the running Flink application). (See Finding H1.)
- **SNS alert payloads contain PHI but the encryption-at-rest posture for SNS is understated.** The alert routing publishes payloads containing patient_id, vital sign values, and clinical recommendations to SNS topics. The recipe says "SNS: encrypted topics" in the Prerequisites but does not specify that these must be SSE-KMS encrypted topics (not just TLS in transit). SNS topic encryption with KMS CMKs is required for PHI payloads. Additionally, any downstream subscribers (pager systems, dashboard endpoints) must be within the BAA perimeter. The recipe does not articulate this subscriber-BAA constraint. (See Finding M1.)
- **Alert payload in Expected Results contains patient_id in cleartext.** The sample JSON output shows `"patient_id": "P-00847291"` and clinical data flowing through SNS to pagers, dashboards, and EHR notifications. While the recipe correctly specifies encryption, it does not discuss whether the pager notification (which may transit public cellular networks as an SMS/page) should contain the full patient identifier or a de-identified reference that the clinician resolves at the bedside terminal. Many production implementations use room/bed identifiers on pagers rather than MRN/patient IDs to reduce PHI exposure on unencrypted channels. (See Finding M2.)
- **Medication data integration (MAR) creates a secondary PHI access surface not modeled in the IAM section.** The alert suppression logic in Step 5 fetches "recent medications for patient_state.patient_id (last 2 hours)" which requires read access to the medication administration record. This is a separate data source with its own access controls, consent model, and audit requirements. The recipe discusses the integration challenge in "The Honest Take" but the IAM/security model for accessing MAR data is not specified in the Prerequisites. (See Finding M3.)

### Architecture Expert Review

**Strengths.**

- The dual-path architecture (Kinesis Data Analytics/Flink for ICU continuous monitoring, Lambda for floor intermittent vitals) is the correct design. These are fundamentally different workload patterns and the recipe correctly identifies that "a system designed for ICU-density data will not work on floor-density data without significant architectural changes."
- DynamoDB as the patient state store with per-patient partition key is the right choice for the access pattern (high-frequency read-modify-write on a per-patient basis with single-digit millisecond latency requirements).
- Timestream for historical trajectory storage is architecturally appropriate: the recipe correctly leverages its time-based retention tiers (hot/cold) and native temporal query support.
- The six-step pseudocode pipeline is well-decomposed with clear data dependencies between steps.
- The Patient State Engine concept (maintaining rolling baselines per patient) is the architecturally correct approach and the recipe explains why this is superior to population-based norms with the right clinical reasoning.
- The suppression logic (Step 5) is elevated as a first-class architectural concern, not an afterthought. The recipe explicitly states "The suppression logic is arguably more important than the detection logic," which is correct for production clinical alerting systems.
- The multi-parameter correlation patterns (DETERIORATION_SIGNATURES) are clinically sound: the sepsis signature (HR up + RR up, then BP down), hemorrhage (HR up + BP down), respiratory failure (SpO2 down + RR up), and cardiac decompensation patterns are well-established clinical deterioration signatures.
- The cost estimates are stratified by monitoring density (ICU vs. floor), which is the right granularity.

**Gaps.**

- **No dead-letter queue (DLQ) for failed trajectory computations.** The architecture routes vital sign events from Kinesis through Lambda or Flink to DynamoDB/Timestream, but there is no specification for what happens when a trajectory computation fails (Lambda timeout, DynamoDB throttle, malformed event). In a clinical safety system, silently dropping a vital sign reading is a patient safety concern: if the system fails to process a critically abnormal reading, no alert fires. The architecture should specify a DLQ on the Lambda functions and a side-output on the Flink application for failed events, with CloudWatch alarms on DLQ depth and an operational runbook for replaying failed events. (See Finding H2.)
- **The architecture diagram shows a binary routing decision ("Data Density?") but doesn't specify who makes this decision or when.** A patient admitted to a general floor may get transferred to the ICU mid-stay, or may have continuous telemetry monitoring ordered on the floor. The architectural question is: does the routing decision happen at admission and remain static, or does it dynamically re-evaluate as monitoring modality changes? The recipe should specify that the routing is determined by the data source characteristics (continuous monitor feed vs. periodic EHR entries) rather than by a static per-patient classification. (See Finding M4.)
- **Exponential moving average for baseline (alpha=0.05) creates a specific failure mode with outliers that is not documented.** In Step 2, the baseline uses EMA with alpha=0.05. A single extremely abnormal reading (say, HR=180 during a brief SVT episode that self-resolves) will permanently shift the baseline upward. The EMA never fully recovers to the pre-outlier level because EMA has infinite memory. The recipe should either specify a clipping/winsorization step before baseline update, or document this as a known limitation. Robust alternatives (trimmed means, median-based estimators) are standard in production vital sign systems. (See Finding M5.)
- **No specification for patient discharge/transfer state cleanup.** The DynamoDB table stores per-patient state with TTL "automatically ages out data for discharged patients." But the TTL duration is not specified, and TTL in DynamoDB is approximate (items can persist up to 48 hours past expiry). If a patient is discharged and a new patient is admitted to the same bed with the same monitoring equipment, there's no explicit state reset mechanism. The architecture should specify an ADT (Admission/Discharge/Transfer) event listener that explicitly clears patient state on discharge and initializes fresh state on admission. (See Finding M6.)

### Networking Expert Review

**Strengths.**

- VPC deployment is specified for production: "Flink application and Lambda in VPC with VPC endpoints for DynamoDB, Timestream, SNS, CloudWatch Logs. Interface endpoints for Kinesis."
- The recipe correctly distinguishes between gateway endpoints (DynamoDB, S3) and interface endpoints (Kinesis, Timestream, SNS) which require ENIs and security group configuration.
- TLS is specified for all transit ("all transit over TLS" in Prerequisites).
- The architecture maintains PHI within the VPC perimeter for all computation and storage operations.

**Gaps.**

- **No explicit egress restriction statement.** The recipe specifies VPC endpoints for AWS services but does not explicitly state that Lambda and Flink subnets should have no NAT gateway / no internet egress. For a clinical safety system processing continuous vital sign PHI, the network posture should be explicit: no egress path except through VPC endpoints to specified AWS services. The chapter-12 pattern (seen in 12.8) names this explicitly. (See Finding L1.)
- **SNS delivery to external endpoints (pagers, unit boards) creates an egress path that is not network-modeled.** The alert routing publishes to SNS, which then delivers to "pager," "unit board," and "EHR notification." If the pager system is an external SaaS (many hospitals use external paging services), that delivery creates a VPC egress path for PHI. The recipe should specify that SNS subscriptions targeting endpoints outside the VPC must traverse a NAT gateway in a controlled subnet with network ACLs limiting the destination to the known pager service IPs, or alternatively that alert delivery happens through a VPC-internal integration (e.g., the pager system has a PrivateLink endpoint). (See Finding M7.)
- **Multi-AZ posture is not specified.** This is a clinical safety system where downtime means missed deterioration alerts. The recipe should specify multi-AZ deployment for Lambda (automatic), Flink (configure availability zone redundancy), DynamoDB (automatic with global tables or standard multi-AZ replication), and Kinesis (automatically multi-AZ). The recipe should state the target RTO/RPO for the alerting pipeline. For a system detecting acute deterioration, even 5-minute outages are clinically significant. (See Finding L2.)

### Voice Reviewer

**Strengths.**

- The opening vignette is visceral and specific: "Six hours later, the patient is coding." This is the signature CC move of making the reader feel the problem before explaining the solution.
- The technology section teaches from first principles without condescension. Concepts are introduced with clear analogies: "If heart rate is 95, that's information. If heart rate was 72 yesterday and is 95 now, that's more information."
- Self-deprecating expertise is present throughout: "Let me be straight about the failure modes, because this is one of those problems where the engineering isn't the hard part. The clinical integration is."
- The Honest Take section reads like lived experience: "Alert fatigue will kill your project faster than any technical limitation."
- Parenthetical asides are used naturally: "(ok, this is a gross oversimplification, but stay with me)" energy without being that exact phrase.
- Em dash count: **zero** (confirmed via codepoint scan for U+2014, U+2013, U+2012).
- No documentation-voice detected. No "This recipe demonstrates how to leverage..." patterns.
- No marketing language or hype.
- Short-to-medium sentences throughout. Good momentum through accumulation.

**Vendor balance:**
- Vendor-agnostic content (Problem + Technology + General Architecture Pattern): approximately 3,500 words.
- AWS-specific content (Why These Services + Architecture Diagram + Prerequisites + Ingredients + Code): approximately 5,500 words.
- Ratio is approximately 39/61 rather than the target 70/30.

This is the one structural concern. The AWS section is longer than typical because the pseudocode walkthrough (which lives in the AWS section per RECIPE-GUIDE.md) is extensive (six steps with heavy comments). The pseudocode itself is conceptually vendor-agnostic (it references "state_store," "stream," "time_series_store" generically), but it lives in the AWS Implementation section. If you count the pseudocode as implementation-neutral teaching (which it mostly is), the effective ratio is closer to 60/40. Still not 70/30, but within tolerance given the pseudocode placement convention. (See Finding L3.)

**Other voice observations:**
- Two TODO comments remain in the text: one in the Technology section ("TODO: Verify this range against specific published studies; common citation is Churpek et al.") and one in Additional Resources ("TODO: Verify all GitHub repo links are current and accessible"). These should not ship to readers. (See Finding M8.)

---

## Stage 2: Expert Discussion

**Conflict 1: Security (H1) vs. Architecture scope.** The `kinesisanalytics:*` wildcard is both a security issue (over-privileged IAM) and an architecture pattern issue (conflating deployment-time and runtime permissions). Resolution: treat as a security finding because the fix is IAM scoping, not architectural redesign. Priority: HIGH.

**Conflict 2: Architecture (H2) vs. Security (operational safety).** The missing DLQ is both an architecture anti-pattern (no error handling in a distributed pipeline) and a patient safety concern (silently dropped readings). Resolution: treat as an architecture finding because the fix is adding infrastructure components. The patient safety dimension elevates it to HIGH rather than MEDIUM.

**Overlap: Networking (M7) and Security (M2) on alert delivery PHI exposure.** Both experts flagged the same fundamental concern: PHI leaving the controlled perimeter via alert notifications. The networking expert frames it as an egress path issue; the security expert frames it as a PHI-on-unencrypted-channel issue. These are two facets of the same problem. Resolution: keep both findings because they require different fixes (network controls vs. payload de-identification).

**Non-conflict: Voice (L3) vendor balance.** The 60/40 ratio is a known consequence of RECIPE-GUIDE.md placing pseudocode in the AWS section. The pseudocode in this recipe is largely vendor-neutral in substance. No action required beyond noting it.

---

## Stage 3: Synthesized Findings

### Finding H1 - IAM Wildcard on Kinesis Data Analytics

**Severity:** HIGH
**Expert source:** Security
**Location:** Prerequisites table, IAM Permissions row
**Problematic text:** `kinesisanalytics:*`
**Issue:** Wildcard grant violates least-privilege. The runtime execution role for the Flink application should not have `CreateApplication`, `DeleteApplication`, or `UpdateApplication` permissions. These are deployment-time actions that belong on a CI/CD role, not the application's runtime role.
**Fix:** Replace `kinesisanalytics:*` with the specific runtime actions needed: `kinesisanalytics:DescribeApplication`, `kinesisanalytics:ListApplicationSnapshots`. Add a note that the deployment role (separate) needs `kinesisanalytics:CreateApplication`, `kinesisanalytics:UpdateApplication`, `kinesisanalytics:StartApplication`, `kinesisanalytics:StopApplication`. This follows the chapter-12 pattern of separating deployment-time from runtime-time IAM.

---

### Finding H2 - No Dead-Letter Queue for Failed Events

**Severity:** HIGH
**Expert source:** Architecture
**Location:** Architecture Diagram and Step 6 (persist_and_route)
**Issue:** The pipeline has no error handling path for failed trajectory computations. A Lambda timeout, DynamoDB throttle, or malformed event causes the reading to be silently dropped. In a clinical safety system, a dropped reading during rapid deterioration means no alert fires. This is a patient safety concern disguised as an architecture anti-pattern.
**Fix:** Add a DLQ (SQS) on both Lambda functions (trajectory-processor and alert-evaluator). Add a side-output stream on the Flink application for failed events. Add CloudWatch alarms on DLQ message count > 0 with severity "alarm" (immediate ops response). Add a brief note in the architecture description: "Failed events route to a dead-letter queue with operational alerting. In a clinical safety system, a silently dropped reading is a patient safety risk. The DLQ alarm should page the on-call engineer, not just increment a dashboard counter."

---

### Finding M1 - SNS PHI Encryption and Subscriber BAA

**Severity:** MEDIUM
**Expert source:** Security
**Location:** Prerequisites table, Encryption row; Ingredients table, SNS entry
**Issue:** The recipe says "SNS: encrypted topics" but does not specify SSE-KMS encryption (required for PHI at rest in SNS) or that all downstream subscribers must be within BAA coverage. An SNS subscription to an HTTP endpoint at a non-BAA pager vendor would violate HIPAA.
**Fix:** In the Prerequisites table, change "SNS: encrypted topics" to "SNS: SSE-KMS encrypted topics (CMK); all subscribers must be BAA-covered endpoints." Add a one-sentence note in the "Why These Services" section for SNS: "All subscription endpoints (pager API, dashboard webhook, EHR integration) must be covered under your organization's BAA chain. An alert containing vital signs and patient identifiers is PHI regardless of the delivery channel."

---

### Finding M2 - Alert Payload PHI on Pager Channels

**Severity:** MEDIUM
**Expert source:** Security
**Location:** Expected Results section, sample JSON output; Step 6 pseudocode
**Issue:** The sample alert payload contains `patient_id` and specific vital sign values. If delivered via SMS/pager to a device that displays messages on a lock screen, this is PHI visible to unauthorized viewers. Production implementations typically use room/bed identifiers on pagers and require clinician authentication to see full clinical details.
**Fix:** Add a note after the Expected Results JSON: "In production, pager notifications typically contain location identifiers (room/bed) rather than patient IDs, with a link to the authenticated clinical display for full trajectory detail. The payload above is the internal representation; the pager-facing message would be: 'Rm 412-B: Trajectory alert. See unit board for details.'"

---

### Finding M3 - MAR Integration Security Model

**Severity:** MEDIUM
**Expert source:** Security
**Location:** Step 5 pseudocode (evaluate_alert), line "recent_meds = fetch recent medications..."
**Issue:** The medication suppression logic requires read access to MAR data, which is a separate PHI data source with its own access controls. The IAM Permissions table does not include permissions for the MAR data source, and the security model for this cross-system data access is unspecified.
**Fix:** Add to the Prerequisites table: "MAR Integration: Read access to medication administration records via HL7/FHIR interface. Separate service account with audit logging. MAR data is PHI requiring the same encryption and access controls as vital sign data." This is also a good opportunity to reinforce the Honest Take point that "getting real-time medication data flowing into your pipeline requires an HL7 interface to the pharmacy/EHR system, which is a 3-6 month integration project on its own."

---

### Finding M4 - Static vs. Dynamic Stream Routing

**Severity:** MEDIUM
**Expert source:** Architecture
**Location:** Architecture Diagram, "Data Density?" decision node
**Issue:** The diagram shows a binary routing decision but doesn't specify the mechanism. A patient can transition between monitoring modalities mid-stay (floor to ICU transfer, telemetry ordered on floor). The routing should be event-driven based on data source characteristics, not a static assignment at admission.
**Fix:** Add a sentence in the Architecture Diagram section: "The routing decision is implicit in the data source: continuous monitor feeds (sub-second frequency) route to the Flink application; EHR-documented assessments (multi-hour frequency) route to Lambda. A patient transferred to the ICU starts producing continuous data immediately, and the Flink path activates without manual intervention. Both paths write to the same patient state store, so trajectory history is preserved across transitions."

---

### Finding M5 - EMA Outlier Sensitivity

**Severity:** MEDIUM
**Expert source:** Architecture
**Location:** Step 2 pseudocode, baseline update with alpha=0.05
**Problematic text:** `state.baselines[parameter].mean = (1 - alpha) * state.baselines[parameter].mean + alpha * value`
**Issue:** EMA with alpha=0.05 has infinite memory. A single extreme outlier (transient SVT producing HR=180 that self-resolves in 30 seconds) permanently shifts the baseline upward. The baseline never fully recovers. This creates a drift toward permissiveness over time if outlier events occur.
**Fix:** Add a clipping step before the EMA update: "If the new value is more than 4 standard deviations from the current baseline, exclude it from the baseline update (but still include it in the trajectory computation in Step 3, where outlier detection is a feature, not a bug)." Alternatively, add a comment in the pseudocode noting this limitation: "// Production note: Consider clipping values > 4 sigma from baseline before EMA update. // EMA has infinite memory; a single outlier permanently biases the baseline."

---

### Finding M6 - Missing ADT Event Handler for State Lifecycle

**Severity:** MEDIUM
**Expert source:** Architecture
**Location:** "Why These Services" section for DynamoDB; Step 2 pseudocode
**Issue:** DynamoDB TTL is specified for aging out discharged patient data, but TTL is approximate (up to 48 hours late). There's no explicit mechanism for resetting patient state on discharge or initializing clean state on admission. If a patient is discharged and the bed is reassigned within hours, residual state from the prior patient could contaminate the new patient's trajectory.
**Fix:** Add to the architecture: "An ADT (Admission/Discharge/Transfer) event listener subscribes to the hospital's ADT feed (HL7 ADT messages or FHIR Encounter events). On discharge: immediately delete the patient's state record from DynamoDB (don't wait for TTL). On admission: initialize a fresh state record with baseline_stable=false. On transfer: preserve state but update unit context for alert routing."

---

### Finding M7 - SNS Egress Path for External Alert Delivery

**Severity:** MEDIUM
**Expert source:** Networking
**Location:** Architecture Diagram, SNS to Clinical Staff/Unit Board/EHR
**Issue:** If any SNS subscriber is an external endpoint (SaaS pager service, external dashboard), PHI transits outside the VPC without explicit network controls. The recipe does not specify whether alert delivery targets are VPC-internal or external, or what network controls apply to external delivery.
**Fix:** Add a brief note in the VPC Prerequisites row or in the "Why These Services" SNS section: "If alert delivery targets external endpoints (pager vendor API, external notification service), configure a NAT gateway in a controlled subnet with outbound security group rules limited to the vendor's IP ranges. Prefer VPC-internal integrations (PrivateLink to the pager vendor, or an internal SMTP relay for email notifications) to avoid PHI egress to the public internet."

---

### Finding M8 - Unresolved TODO Items

**Severity:** MEDIUM
**Expert source:** Voice
**Location:** Technology section, paragraph beginning "Research systems have demonstrated..."; Additional Resources section, final line
**Problematic text:** "TODO: Verify this range against specific published studies; common citation is Churpek et al. and similar deterioration prediction research." and "TODO: Verify all GitHub repo links are current and accessible."
**Issue:** TODO items must not ship to readers. These are author notes that should be resolved before publication.
**Fix:** For the first TODO: Either verify against Churpek et al. (2016, Critical Care Medicine) and cite specifically, or soften the claim to "Research systems have demonstrated improvements in deterioration prediction when trajectory features are added to point-in-time models, though the magnitude varies by population and event definition." For the second TODO: Verify the four GitHub links in Additional Resources are current. The `amazon-kinesis-data-analytics-examples` and `amazon-timestream-tools` repos are stable AWS-maintained repos that should be valid.

---

### Finding L1 - No Explicit Egress Restriction

**Severity:** LOW
**Expert source:** Networking
**Location:** Prerequisites table, VPC row
**Issue:** The recipe specifies VPC endpoints but does not explicitly state "no internet egress" for Lambda and Flink subnets. The chapter-12 pattern (12.8) names this explicitly.
**Fix:** Add to VPC Prerequisites: "Lambda and Flink subnets: private subnets with no NAT gateway. All AWS service access via VPC endpoints. No internet egress path for PHI-processing workloads."

---

### Finding L2 - Multi-AZ and RTO/RPO Not Specified

**Severity:** LOW
**Expert source:** Networking
**Location:** Prerequisites table (absent)
**Issue:** This is a clinical safety system. The recipe should specify multi-AZ deployment and target availability. DynamoDB and Kinesis are automatically multi-AZ. Lambda is automatically multi-AZ. Flink on Kinesis Data Analytics supports AZ redundancy but it should be called out.
**Fix:** Add a row to Prerequisites: "Availability: Multi-AZ deployment. Target: 99.9% uptime for the alerting pipeline. RTO < 5 minutes. Kinesis, DynamoDB, Lambda are natively multi-AZ. Configure Flink application with multiple AZs. CloudWatch alarm on processing lag > 60 seconds."

---

### Finding L3 - Vendor Balance Ratio

**Severity:** LOW
**Expert source:** Voice
**Location:** Overall recipe structure
**Issue:** The effective vendor balance is approximately 60/40 (agnostic/AWS) rather than the target 70/30. The pseudocode walkthrough is largely vendor-neutral in substance but lives in the AWS section per RECIPE-GUIDE.md convention, inflating the AWS word count.
**Fix:** No action required. The pseudocode placement is per the recipe guide's specification. The conceptual content is vendor-neutral even though it's physically located in the AWS section. A reader on GCP or Azure would still learn from the pseudocode. Note for future: if the TechEditor wants to improve the ratio, moving the "General Architecture Pattern" section's prose expansion (the six-component pipeline description) higher could help, but this is cosmetic.

---

## Summary

| Severity | Count | Findings |
|----------|-------|----------|
| CRITICAL | 0 | - |
| HIGH | 2 | H1 (IAM wildcard), H2 (missing DLQ) |
| MEDIUM | 8 | M1-M8 |
| LOW | 3 | L1-L3 |

**Verdict: PASS** (0 CRITICAL, 2 HIGH, within thresholds)

The recipe is strong. The two HIGH findings are both fixable without structural changes: H1 is a one-line IAM correction, H2 requires adding a DLQ and associated alarms (approximately 2-3 sentences of prose plus a node in the architecture diagram). The MEDIUM findings are production-hardening concerns that improve the recipe's fidelity to real-world deployment without changing its pedagogical structure. The TODO items (M8) must be resolved before publication.

Note: The Python companion (`chapter12.07-python-example.md`) does not yet exist. The expert review above covers only the main recipe file. Once the Python companion is produced and code-reviewed, a supplementary review pass may be warranted to verify alignment between pseudocode and Python implementation.
