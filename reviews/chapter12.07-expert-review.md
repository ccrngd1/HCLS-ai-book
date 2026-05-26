# Expert Review: Recipe 12.7 - Vital Sign Trajectory Monitoring

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-26
**Recipe file:** `chapter12.07-vital-sign-trajectory-monitoring.md` (NOT FOUND)
**Python companion:** `chapter12.07-python-example.md` (NOT FOUND)

---

## Overall Assessment

**Verdict: FAIL**

The expert review for recipe 12.7 cannot proceed because the upstream draft has not been produced. The pipeline contract for this recipe is:

1. `ch12-r07-draft` (TechWriter) produces `chapter12.07-vital-sign-trajectory-monitoring.md`
2. `ch12-r07-python` (TechWriter) produces `chapter12.07-python-example.md`
3. `ch12-r07-code-review` (TechCodeReviewer) reviews the Python companion
4. `ch12-r07-expert-review` (TechExpertReviewer) reviews the recipe (this task)
5. `ch12-r07-edit` (TechEditor) polishes the final version

Status snapshot at review time:

- `chapter12.01-appointment-volume-forecasting.md` (present)
- `chapter12.02-supply-inventory-forecasting.md` (present)
- `chapter12.03-ed-arrival-forecasting.md` (present)
- `chapter12.04-lab-result-trend-analysis.md` (present)
- `chapter12.05-hospital-census-forecasting.md` (present)
- `chapter12.06-revenue-cycle-cash-flow-forecasting.md` (**missing**)
- `chapter12.06-python-example.md` (present)
- `chapter12.07-vital-sign-trajectory-monitoring.md` (**missing**)
- `chapter12.07-python-example.md` (**missing**)
- `reviews/chapter12.07-code-review.md` (**missing**)

The expert-review task spec declares `depends_on: [ch12-r07-draft]`, and that dependency has not produced its output file. There is no Python companion either, so the panel does not even have a code-level scaffold to triangulate the recipe's intended scope (as it had for recipe 12.6, where the Python companion landed before the main recipe).

Issuing PASS on a non-existent draft would corrupt the pipeline state and propagate an empty artifact into the TechEditor queue. The correct disposition is FAIL with a single CRITICAL finding: the recipe draft does not exist.

Because this recipe is the single highest-stakes recipe in chapter 12 (real-time clinical deterioration detection, alert fatigue is the dominant operational failure mode, and the FDA SaMD boundary is genuinely close enough to graze), the panel is also recording substantive forward-looking expert commentary so the TechWriter has the full benchmark on the first pass. This is the same approach the panel took for recipe 12.6 and the chapter pattern that emerged in 12.4 and 12.5.

Priority breakdown: 1 CRITICAL, 0 HIGH, 0 MEDIUM, 0 LOW. **Verdict: FAIL** because there is 1 CRITICAL finding (the recipe draft does not exist).

---

## Stage 1: Independent Expert Reviews

### Security Expert Review (OWASP, CIS, NIST SP 800-66 for HIPAA)

No artifact to review. When the draft lands the panel will check:

- **Continuous vital-sign streams are PHI in the strongest sense.** Bedside monitor output (heart rate, respiratory rate, SpO2, NIBP, IBP, temperature, end-tidal CO2, ECG-derived rhythm classifications, telemetry packets) is keyed by a monitor-bed-assignment that maps directly to a patient via the ADT feed. Every byte that flows from a bedside monitor or a wearable to the cloud is PHI at the moment it leaves the bedside. The recipe must elevate this in Prerequisites and must not soft-pedal "we are processing physiologic signals" as if signal data were de-identified.
- **The HL7 v2 over MLLP integration is the operational PHI ingress path.** Most US hospitals push monitor and ADT data over HL7 v2.x ORU (results), ADT (admit-discharge-transfer), and SIU (scheduling) messages framed in MLLP (Minimum Lower Layer Protocol, ASCII control characters wrapping each message). MLLP is plaintext over TCP by default. The recipe must specify MLLP-over-TLS (the standard term is "MLLPS") or an equivalent VPN / mTLS posture; an unencrypted HL7 v2 feed leaving a hospital is a HIPAA breach in transit. FHIR-based integrations (FHIR Observation, FHIR DeviceMetric, FHIR Encounter via SMART-on-FHIR or FHIR Subscription) are emerging but are not yet the dominant pattern for live-monitor data; the recipe must acknowledge both.
- **Bedside monitor vendor BAA inventory.** Philips IntelliVue, GE CARESCAPE, Mindray, Masimo, Nihon Kohden, Spacelabs, Welch Allyn, and Drager are the dominant inpatient monitor vendors; each has its own integration server (often a hospital-deployed appliance like Philips IntelliBridge or GE Unity Network IC) that brokers between the bedside monitor and the EHR or downstream systems. Wearable platforms (BioIntelliSense BioButton, Current Health, Masimo Radius PPG, VitalConnect VitalPatch) add another layer. Every one of these vendors is a Business Associate. The recipe must call out that the BAA-and-data-flow inventory is a prerequisite, not an afterthought, and must specify whether the integration is direct-from-monitor or brokered-through-a-vendor-aggregator.
- **The Epic Sepsis Model precedent is mandatory framing.** The 2021 JAMA Internal Medicine study on the Epic Sepsis Model (Wong et al., 2021) showed an AUC of 0.63 in external validation against the vendor's claimed 0.76, and the Sentinel Initiative and CDS literature have cited it as a paradigmatic example of an early-warning system that did not generalize across institutions. Any recipe on continuous deterioration detection must acknowledge this class of failure mode in The Honest Take. The recipe must not promise sepsis-prediction accuracy; it can promise a trajectory-monitoring pattern that surfaces concerning trends and routes them to a clinician for adjudication.
- **NEWS2, MEWS, qSOFA, SIRS, PEWS are the operative clinical scoring frameworks.** A trajectory-monitoring recipe that does not orient itself against the scoring systems clinicians actually use is reinventing the wheel and is unlikely to be adopted. NEWS2 (National Early Warning Score 2) is the UK NHS standard for adult ward patients. MEWS (Modified Early Warning Score) is the older US equivalent. qSOFA (quick Sequential Organ Failure Assessment) is the sepsis-specific bedside score. SIRS (Systemic Inflammatory Response Syndrome) is the older sepsis screen. PEWS (Pediatric Early Warning Score) is the pediatric equivalent. The CMS SEP-1 measure (Severe Sepsis and Septic Shock Management Bundle) bakes early recognition into the regulatory and quality-reporting layer. The recipe must position the trajectory model relative to these, not in competition with them; the trajectory model should be the layer that catches what the rule-based scores miss (slow drifts that stay below threshold but are clearly degrading from the patient's own baseline).
- **Customer-managed KMS keys per data class.** Continuing the chapter-12 pattern: separate CMKs for the raw HL7 v2 feeds, the FHIR Observation feeds, the harmonized vital-sign time-series, the per-patient baseline state, the trajectory-feature stream, the alert-event store, the model artifacts, the DynamoDB serving table, the alert-suppression configuration, and CloudWatch logs. The model-artifact CMKs should be flagged for high integrity-and-availability concern; a tampered trajectory model produces wrong alerts that drive wrong clinical responses.
- **CloudTrail data events on PHI-bearing buckets and tables.** Management events on the Step Functions or Kinesis-and-Lambda orchestration plane. Object Lock in compliance mode for the alert-event store (HIPAA audit trail and regulatory-defense posture against "the alert was suppressed" claims).
- **Per-stage IAM least privilege.** The stream-ingestion Lambda has `kinesis:GetRecords` and `kms:Decrypt` on the raw-feed CMK; the harmonization Lambda has `kms:Decrypt` on the raw-feed CMK and `kms:Encrypt` on the harmonized-feed CMK; the trajectory-inference Lambda has `sagemaker:InvokeEndpoint` and `kms:Decrypt`/`kms:Encrypt` on the appropriate CMKs; the alert-routing Lambda has `sns:Publish` to the paging SNS topic, `dynamodb:PutItem` on the alert-event table, and `kms:Encrypt` on the alert-event CMK. The paging-credential Secrets Manager entry (PagerDuty / VocallyCorect / Voalte / TigerConnect / Spok credentials) is scoped to the alert-routing Lambda only.
- **Synthetic-data discipline for development.** Real continuous vital signs are PHI; the dev pipeline must use de-identified physiologic datasets. The MIMIC-IV waveform companion (MIMIC-IV-WDB), the eICU Collaborative Research Database, the PhysioNet challenge datasets, and the Physiological Open Source Database (POSD) are the canonical de-identified options, all available through PhysioNet credentialing. Synthea does not produce continuous vital-sign waveforms; it produces FHIR Observation snapshots, which is sufficient for trajectory-style modeling but not for waveform-level work.
- **Model versioning and integrity.** The trajectory model artifact must be checksum-verified at load time, signed at training time, and pinned to a known-good version. A silent model swap in a deterioration-alerting pipeline is an alert-distribution incident that propagates wrong clinical signals across an entire institution.
- **Regulatory framing is the most sensitive item in the recipe.** A pure "we surface trends, the clinician adjudicates" framing is operational decision support and stays inside the CDS Hooks / non-device CDS exception under FDA's 2022 Clinical Decision Support guidance and the 21st Century Cures Act §3060. A "we predict sepsis 6 hours before onset" framing is a Software as a Medical Device (SaMD) claim and pulls the entire pipeline into FDA-cleared-device territory (510(k) at minimum, possibly De Novo). The recipe must position itself unambiguously on the operational side of this line and must state explicitly that diagnostic claims, treatment-decision claims, and "predict X" framings move the pipeline out of the chapter's scope.

### Architecture Expert Review

No artifact to review. When the draft lands the panel will check:

- **The recipe is a streaming pipeline, not a batch pipeline.** This is the chapter's first true streaming recipe (12.1 through 12.6 are all batch or near-real-time). The architecture must be Kinesis Data Streams (or MSK / Kafka) at ingest, Kinesis Data Firehose to S3 for the durable raw-message archive, Lambda or Kinesis Data Analytics (Apache Flink) for harmonization and trajectory feature extraction, SageMaker async inference or a SageMaker real-time endpoint for the trajectory model, EventBridge or SNS for alert routing, DynamoDB for the alert-event store and the patient-state store, and CloudWatch for the operational telemetry plane. The recipe must articulate why streaming is mandatory (clinical responsiveness; the alert latency budget is single-digit minutes from physiologic-event-onset to bedside-page) and why batch alternatives miss the use case.
- **Patient-specific baselines are the architectural insight that distinguishes trajectory monitoring from threshold-based alerting.** Population thresholds (HR > 130, RR > 24, SpO2 < 90) catch the obvious cases and miss the patient who runs a baseline HR of 95 because of beta-blockade or congestive heart failure and starts trending toward 115. A trajectory-monitoring pipeline must build per-patient baselines (rolling median / IQR over the prior 24 to 72 hours, conditioned on activity state where available) and must score deviation from the patient's own baseline rather than only against population norms. The recipe must elevate this as a first-class architectural choice and must specify how baselines are bootstrapped on admission (population priors decayed in as patient-specific data accrues), how they are updated (rolling-window estimator with outlier rejection), and how they are reset on clinical-state-change events (post-op, post-sedation, transfer between units).
- **Multivariate trajectory modeling beats univariate per-vital alerting.** A 1-point drop in SpO2 is rarely concerning. A 1-point drop in SpO2 plus a 10-bpm rise in HR plus a 4-bpm rise in RR over 30 minutes is the classic early-deterioration signature. The recipe must specify a multivariate trajectory model (LSTM, Transformer, temporal convolutional network, or a Gaussian-process state-space model) that consumes the joint vital-sign vector at each time step, not a per-vital ensemble of independent univariate models. The Python companion will likely need to demonstrate this with a small enough toy example to be runnable; the main recipe must articulate the choice and explain the tradeoffs (interpretability suffers; cohort-specific calibration is harder; the model is more sample-efficient but harder to debug).
- **Artifact rejection is the silent killer of trajectory-monitoring pipelines.** A loose ECG lead produces a sudden HR drop to zero, a motion artifact during patient repositioning produces a 30-bpm spike, a malpositioned SpO2 probe reads 70% on a healthy patient. A naive trajectory model alerts on every artifact and trains the nursing staff to ignore the alert system inside two weeks. The recipe must elevate artifact rejection as a first-class pipeline stage and must specify the techniques: lead-disconnect detection (HR or ECG amplitude flat for > 5 seconds), physiologic-plausibility filters (HR > 250 or < 20 in an adult is artifact unless corroborated by other signals), inter-vital corroboration (HR drop without SpO2 or BP corroboration is suspect), motion-state awareness if accelerometer data is available. The PhysioNet 2010 Challenge on robust detection of heart beats in multimodal data is the canonical reference for this problem.
- **Alert fatigue is the dominant operational failure mode of the entire recipe.** A 2014 ECRI Institute Top 10 Health Technology Hazards list put alarm fatigue as the #1 hazard. The Joint Commission National Patient Safety Goal NPSG.06.01.01 codifies clinical alarm management as a Tier 1 patient safety priority. The recipe must specify alert-suppression mechanisms (per-patient alert quiet periods, per-clinician escalation thresholds, alert-acknowledgment workflows that train the system on which alerts the clinician deemed actionable), alert-batching at the unit level (one consolidated alert per 5-minute window per patient instead of one per crossing-event), and alert-burden monitoring (a per-unit alerts-per-hour metric that triggers a recipe-wide review when it crosses a threshold). The Honest Take must elevate this to first-class status; a deterioration-alerting recipe that treats alert fatigue as a footnote is not credible.
- **Alert routing is recipe-specific.** The SNS-to-PagerDuty or SNS-to-Voalte or SNS-to-TigerConnect or SNS-to-Spok pager integration is the operational moment where the alert leaves the data plane and enters the clinical workflow. The recipe must specify the paging-platform integration, the on-call-schedule lookup (the alert routes to the bedside RN, the charge nurse, the rapid response team, the medical resident, or some combination depending on severity and unit), the acknowledgment-and-escalation workflow (if the bedside RN does not acknowledge in 60 seconds, escalate to the charge nurse; if the charge nurse does not acknowledge in 120 seconds, escalate to the RRT), and the closed-loop-acknowledgment audit. Pager integration without acknowledgment-tracking is the chapter-pattern failure mode.
- **Step Functions or EventBridge orchestration with retry and DLQ semantics.** The streaming pipeline runs on Kinesis or MSK rather than Step Functions, but the alert-routing fan-out and the model-retraining schedule should run on Step Functions or EventBridge. The recipe must specify retry strategies for transient SNS-publish failures, DLQs per stage, and the recovery posture for missed-alert detection (every alert that was generated must have either an acknowledgment or an escalation-to-RRT outcome recorded; gaps in the audit trail trigger a separate alert).
- **Backpressure handling and schema versioning.** Kinesis shard-level capacity (1 MB/sec or 1000 records/sec per shard) and MSK partition-level capacity must be sized for the institutional peak: a 600-bed hospital with a continuous-monitoring posture on 80% of beds is producing 480 patients * 6 vitals * 1 sample/minute (low-sampling-rate floor) to 480 patients * 6 vitals * 60 samples/minute (continuous telemetry on the floor) to 80 patients * 240 samples/sec (ICU waveform-grade telemetry, where waveform pipelines exist). The recipe must size the streaming layer for the peak and must specify the backpressure posture (graceful degradation to a lower sampling rate vs. shedding load with an operational alert). HL7 v2 schema versioning across monitor vendors (Philips XDS-Hb-x vs GE Unity Network message structure vs Mindray Direct vs FHIR Observation R4 vs FHIR Observation R5) is a pipeline-versioning concern that must be specified.
- **Outage handling.** The bedside monitor never stops; the streaming pipeline cannot lose data. The recipe must specify the durable-archive posture (Kinesis Data Firehose to S3 with KMS encryption and Object Lock), the replay capability (replay from the durable archive when a downstream component recovers), and the operational-incident posture (the institution must have a named operational owner, a runbook, and a defined recovery time objective for the trajectory-alerting service; the runbook must include "how does the institution operate without trajectory alerting" because the answer is "the same way they did before the system existed, with manual NEWS2 charting on paper if necessary").
- **Cohort-stratified accuracy monitoring.** Continuing the chapter-12 pattern from recipes 12.4 and 12.5: the trajectory-model accuracy must be tracked per ward type (med-surg, telemetry, step-down, ICU), per age cohort (adult vs pediatric vs geriatric), per primary-condition cohort (post-op surgical, medical, oncology, post-CV-procedure), and per shift (day vs night, where night-time deterioration patterns differ). An aggregate AUC that hides systematic miscalibration on the post-op surgical cohort is worse than no monitoring at all.

### Networking Expert Review

No artifact to review. When the draft lands the panel will evaluate:

- **VPC posture and VPC endpoint enumeration.** Kinesis (or MSK), Kinesis Data Firehose, S3 (gateway), DynamoDB (gateway), KMS, Lambda, Step Functions, EventBridge, SNS, SageMaker (interface), Secrets Manager, CloudWatch Logs, CloudWatch Monitoring. Compute resources in private subnets only; no NAT egress for PHI-touching workloads.
- **HL7 v2 ingress posture.** The bedside-monitor data path is the most network-sensitive element of the recipe. Two patterns exist: (a) a hospital-deployed integration appliance (Mirth Connect, Cloverleaf, Rhapsody, NextGen Connect Integration Engine) terminates HL7 v2 over MLLP from the monitor or aggregator and forwards over MLLPS or HTTPS to the AWS account through Direct Connect or Site-to-Site VPN; (b) an AWS-hosted HL7 v2 listener (typically a Network Load Balancer fronting a fleet of Fargate or EC2 HL7 receivers) terminates MLLPS directly from the institution's integration appliance over Direct Connect or VPN. The recipe must call out both patterns, must call out that direct-from-monitor-to-AWS is rarely the right pattern (the institutional integration engine is the one place that already has the BAA-covered data flow inventory), and must specify the encryption posture (MLLPS / mTLS) for the institution-to-AWS hop.
- **Wearable / remote-patient-monitoring ingress posture.** For wearable platforms (BioButton, Current Health, VitalPatch, Masimo Radius), the data flow is typically vendor-cloud-to-AWS over HTTPS (often via AWS PrivateLink or vendor-published API endpoints). The recipe must call out that the wearable vendor's cloud is itself a Business Associate and the BAA-and-data-flow inventory extends to the wearable vendor's network and storage posture.
- **TLS posture.** TLS 1.2 minimum (TLS 1.3 preferred) for every leg of the pipeline. mTLS for the institution-to-AWS hop. Kinesis, S3, KMS, DynamoDB calls go over the AWS service VPC endpoint, never over the internet. The pager integration (SNS-to-PagerDuty or equivalent) leaves the AWS account over HTTPS to the paging vendor; the recipe must call out that this hop is BAA-covered and that the paging vendor's outbound delivery (SMS, push notification, in-app message) is part of the data-flow inventory.
- **Egress controls.** Restrictive egress on all Lambda VPCs and SageMaker endpoint subnets. The only allowed outbound destinations are the AWS service VPC endpoints, the institution's integration appliance (for the rare reverse-direction message flow such as alert-acknowledgment back to the EHR), and the paging vendor's published HTTPS endpoint. No general internet egress from the PHI plane.
- **No public endpoints.** The Kinesis stream, the MSK cluster (if used), the SageMaker endpoints, the DynamoDB tables, the S3 buckets, the Step Functions state machines, the SNS topics, and the EventBridge buses must be private. The clinician-facing alert acknowledgment UI may be a private API Gateway endpoint or an internal-only ALB-fronted service, but the underlying data plane stays inside the VPC.
- **Multi-AZ posture.** This is a clinical-availability pipeline. The recipe must specify multi-AZ Kinesis (built-in), multi-AZ Lambda, multi-AZ SageMaker endpoints, multi-AZ DynamoDB (Global Tables if multi-region), and a documented RTO/RPO. A single-AZ posture for a continuous-monitoring pipeline is a regulatory and clinical-safety incident waiting to happen.
- **Time synchronization posture.** Continuous vital-sign trajectories are time-keyed; clock skew between the bedside monitor, the institutional integration appliance, the AWS ingest layer, and the model-inference layer corrupts the trajectory. The recipe must specify NTP (or Amazon Time Sync Service for AWS-hosted components) and must call out that time-zone handling for the `observed_at` timestamp is institution-local-time at the bedside but UTC in the durable archive and the inference layer.

### Voice Reviewer

No artifact to review. When the draft lands the panel will evaluate against STYLE-GUIDE.md and against the chapter-12 voice pattern established in 12.1 through 12.5:

- **CC voice consistency throughout.** The recipe must sound like an engineer who has been on a Code Blue at 03:00 and has watched a deterioration pattern play out in the chart afterward, not a vendor brochure or a documentation manual. The opening vignette should set the operational stake at the bedside or the rapid response team activation, not at a conference table.
- **Opening vignette candidates.** The 03:00 RRT call where the patient had been gently drifting for the prior 4 hours and nobody saw it on the every-4-hour vitals charting; the day shift handoff where the off-going RN says "she looked fine when I checked her at 06:00" and the on-coming RN finds the patient hypotensive and hypoxic at 07:30; the post-op floor patient who codes 14 hours after a routine cholecystectomy because nobody noticed that the heart rate had been climbing 2 bpm per hour since 18:00 the prior evening; the sepsis case that the Epic Sepsis Model missed because the patient's baseline HR was 105 and the system was tuned to alert at 110 institution-wide. Any of these earns the opening sentence; the panel will evaluate that the chosen vignette is concrete enough to be lived rather than abstract enough to be read past.
- **Zero em dashes.** The chapter-12 pattern through 12.5 is zero em dashes (verified by U+2014 codepoint scan in each prior recipe). The recipe must match.
- **70/30 vendor balance.** Roughly 70% vendor-agnostic technology and architecture, 30% AWS-specific implementation. The chapter-12 pattern through 12.5 has held this balance.
- **Honest Take with at least four observations.** The chapter-12 pattern. For this recipe the panel expects observations about: alert fatigue is the dominant operational failure mode (and the single biggest reason these systems get turned off after rollout); the Epic Sepsis Model precedent and the broader external-validation collapse of vendor-claimed AUCs; the patient-specific-baseline insight is the architectural insight that distinguishes trajectory monitoring from threshold alerting; the regulatory boundary between operational decision support and SaMD is closer than most teams realize; the political dimension of "whose alert is this" inside a hospital (the bedside RN, the charge nurse, the RRT, the rounding hospitalist, the ICU consultant) is underestimated and shapes adoption; and the existing rule-based scoring systems (NEWS2, MEWS, qSOFA, SIRS, PEWS) are the layer the trajectory model complements rather than replaces.
- **Why-This-Isn't-Production-Ready section.** Calling out the recipe's specific failure modes: artifact rejection is hard and gets harder under real-world conditions; patient-specific baseline drift on long admissions degrades trajectory features; cohort-specific calibration matters and the recipe does not specify the calibration cadence; alert-routing integration is institution-specific and the recipe cannot prescribe the workflow; the regulatory framing is genuinely close to the SaMD line and an institution must validate its own positioning.
- **No marketing-voice creep.** Phrases like "powerful," "seamless," "robust," "AI-driven," "real-time" (without latency numbers) should be absent or used sparingly with concrete justification. "AI-powered early warning" is the canonical doc-voice failure mode for this recipe; the panel will reject it on sight.
- **CC-voice markers expected.** Parenthetical asides about the operational reality ("yes, you really do see HR readings of 250 from a wiggly toddler whose lead came loose"); self-deprecating expertise ("the first version of this I built alerted on every 5-second flatline from a loose ECG lead, which is how I learned about artifact rejection"); the chapter pattern of "the modeling math is the easy part; the data plumbing and the workflow integration is closer to 50/30/20 of the engineering effort" (the chapter-12 thesis, established in 12.5's Honest Take and reinforced in every subsequent recipe).

---

## Stage 2: Expert Discussion

There is no artifact for the experts to discuss. The single conflict the panel can articulate is the prioritization between the FDA SaMD framing and the alert-fatigue framing, both of which the panel believes the recipe must elevate to first-class status.

The Security expert and the Architecture expert agree that the regulatory framing is the single most sensitive item in the recipe; a pure "we surface trends, the clinician adjudicates" framing is operational decision support and stays inside the FDA Clinical Decision Support guidance non-device CDS exception under the 21st Century Cures Act §3060, while a "we predict sepsis 6 hours before onset" framing is SaMD and pulls the entire pipeline into 510(k) territory. The recipe must position itself unambiguously on the operational side of this line.

The Architecture expert and the Voice reviewer agree that alert fatigue is the dominant operational failure mode and must be elevated to a Honest Take observation, a first-class architectural pipeline stage (alert suppression, batching, escalation), and an operational-monitoring metric (per-unit alerts-per-hour). A recipe that treats alert fatigue as a footnote is not a credible recipe regardless of how technically sophisticated the trajectory model is.

The Security expert and the Networking expert agree that the HL7 v2 over MLLP integration path is the recipe's most network-sensitive element and that MLLPS (MLLP-over-TLS) or an equivalent VPN posture is non-negotiable. The recipe must call out that direct-from-monitor-to-AWS is rarely the right pattern; the institutional integration engine (Mirth, Cloverleaf, Rhapsody, NextGen Connect) is the right network terminator on the institution side.

The Voice reviewer notes that this recipe carries a higher prose risk than any prior chapter-12 recipe because the vendor-marketing language for early-warning systems is dense and seductive ("AI-powered sepsis prediction," "real-time deterioration alerting," "predictive health intelligence"). The recipe must reject this register and stay in the engineer-explaining-something-cool register the chapter has established.

There are no other inter-expert conflicts because there is no draft to evaluate. When the draft lands the panel will run the standard discussion stage.

---

## Stage 3: Synthesized Findings

### Finding C1: Recipe Draft Does Not Exist

- **Severity:** CRITICAL
- **Expert:** All four (panel cannot perform its function without an artifact)
- **Location:** `chapter12.07-vital-sign-trajectory-monitoring.md` is missing from the repository root.
- **Problem:** The expert review depends on the recipe draft existing. The pipeline contract is `ch12-r07-draft -> ch12-r07-python -> ch12-r07-code-review -> ch12-r07-expert-review -> ch12-r07-edit`. Without the draft the panel cannot evaluate clinical accuracy, architectural soundness, security posture, networking posture, or voice register, and a downstream PASS would propagate an empty artifact into the TechEditor queue.
- **Fix:** Run the `ch12-r07-draft` task to produce `chapter12.07-vital-sign-trajectory-monitoring.md`. The TechWriter should treat the forward-looking commentary in this review as the benchmark for the first pass. In particular, the draft should:
  1. Open with a concrete bedside or RRT vignette (see Voice Reviewer for candidates).
  2. Position the trajectory model relative to NEWS2, MEWS, qSOFA, SIRS, and PEWS rather than in competition with them.
  3. Acknowledge the Epic Sepsis Model precedent (Wong et al., JAMA Internal Medicine 2021) in The Technology section as the canonical external-validation-collapse example and shape the recipe's claims accordingly.
  4. Elevate patient-specific baselines as the architectural insight that distinguishes trajectory monitoring from threshold alerting, and specify how baselines are bootstrapped, updated, and reset on clinical-state-change events.
  5. Specify the multivariate trajectory model (LSTM / Transformer / TCN / GP-state-space) over a per-vital ensemble of independent univariate models.
  6. Elevate artifact rejection as a first-class pipeline stage, not a footnote, with specific techniques (lead-disconnect detection, physiologic-plausibility filters, inter-vital corroboration, motion-state awareness).
  7. Elevate alert fatigue as the dominant operational failure mode in The Honest Take, with specific suppression / batching / escalation mechanisms in the architecture.
  8. Specify the HL7 v2 over MLLPS (or FHIR Subscription) ingest pattern through an institutional integration engine (Mirth, Cloverleaf, Rhapsody, NextGen Connect), not direct-from-monitor-to-AWS.
  9. Specify a streaming architecture (Kinesis Data Streams or MSK at ingest, Kinesis Data Firehose to S3 for the durable archive, Lambda or Kinesis Data Analytics for harmonization and feature extraction, SageMaker endpoint for the trajectory model, EventBridge or SNS for alert routing, DynamoDB for the alert-event store and the patient-state store) with multi-AZ posture and documented RTO/RPO.
  10. Specify customer-managed CMKs per data class (raw HL7 feeds, FHIR Observation feeds, harmonized vital-sign time-series, per-patient baseline state, trajectory-feature stream, alert-event store, model artifacts, DynamoDB serving table, alert-suppression configuration, CloudWatch logs).
  11. Specify per-stage IAM least privilege with explicit `kms:Decrypt` / `kms:Encrypt` / `sagemaker:InvokeEndpoint` / `sns:Publish` / `dynamodb:PutItem` scoping.
  12. Specify VPC endpoints (Kinesis, Kinesis Firehose, S3 gateway, DynamoDB gateway, KMS, Lambda, Step Functions, EventBridge, SNS, SageMaker interface, Secrets Manager, CloudWatch Logs, CloudWatch Monitoring) and the egress-restricted posture.
  13. Specify cohort-stratified accuracy monitoring (per ward type, per age cohort, per primary-condition cohort, per shift) consistent with the chapter-12 pattern.
  14. Position the regulatory framing unambiguously on the operational decision support side of the FDA SaMD line, with explicit reference to the FDA 2022 Clinical Decision Support guidance and the 21st Century Cures Act §3060.
  15. Hold to zero em dashes (verified by U+2014 codepoint scan), the 70/30 vendor balance, and the chapter-12 voice pattern established in 12.1 through 12.5.

When the draft lands, re-run `ch12-r07-expert-review`. The panel will perform the full Stage 1 / Stage 2 / Stage 3 review against the draft, with the expectation of finding 0 CRITICAL, no more than 3 HIGH, and the typical chapter-12 pattern of MEDIUM and LOW findings on architectural specificity (CMK granularity, IAM scoping, retry policy, drift detection, time synchronization), inline TODOs that must be tracked through to publication, and en-dash-versus-em-dash hygiene. Recipe 12.7 is the highest-stakes recipe in chapter 12; the panel will hold it to the chapter's highest bar.

### Verdict

**FAIL** because there is 1 CRITICAL finding (the recipe draft does not exist).

Re-run `ch12-r07-draft` (and `ch12-r07-python`, and `ch12-r07-code-review`), then re-run this review.

---

## Appendix: Forward-looking Reference Inventory for the TechWriter

The panel has assembled the canonical reference set the recipe should cite or align against. None of these are required to be linked from the recipe (the resources section enforces verified URLs only), but the technology and architecture choices in the draft should be congruent with this body of work.

**Clinical scoring frameworks**

- NEWS2: Royal College of Physicians, "National Early Warning Score (NEWS) 2," 2017 (UK NHS standard for adult ward patients).
- MEWS: Subbe et al., "Validation of a modified Early Warning Score in medical admissions," QJM 2001 (the older US-equivalent score).
- qSOFA: Singer et al., "The Third International Consensus Definitions for Sepsis and Septic Shock (Sepsis-3)," JAMA 2016 (the bedside sepsis screen).
- SIRS: Bone et al., "Definitions for sepsis and organ failure...," Chest 1992 (the older sepsis screen, deprecated for diagnosis but still in use as a trigger).
- PEWS: Pediatric Early Warning Score variants; Monaghan, "Detecting and managing deterioration in children," Paediatric Nursing 2005 is one canonical reference.
- CMS SEP-1: the Severe Sepsis and Septic Shock Management Bundle measure, the regulatory anchor for early sepsis recognition in US hospitals.

**External-validation precedent**

- Wong et al., "External Validation of a Widely Implemented Proprietary Sepsis Prediction Model in Hospitalized Patients," JAMA Internal Medicine 2021 (the Epic Sepsis Model external-validation paper showing AUC 0.63 vs vendor-claimed 0.76).
- Habib et al., "The Epic sepsis model falls short," Lancet Digital Health 2021 (commentary).
- Adler-Milstein et al., "Next-generation artificial intelligence for diagnosis: from predicting diagnostic labels to wider impact," BMJ 2022 (broader external-validation collapse pattern).

**Alert fatigue and clinical alarm management**

- ECRI Institute Top 10 Health Technology Hazards, multiple years (alarm fatigue has been #1 multiple times since 2012).
- The Joint Commission National Patient Safety Goal NPSG.06.01.01: clinical alarm management.
- Sendelbach and Funk, "Alarm fatigue: a patient safety concern," AACN Advanced Critical Care 2013.
- Cvach, "Monitor alarm fatigue: an integrative review," Biomedical Instrumentation & Technology 2012.

**Regulatory framing**

- FDA Clinical Decision Support Software Guidance, September 2022.
- 21st Century Cures Act, Section 3060 (clarification of medical software provisions).
- FDA Software as a Medical Device (SaMD) framework, IMDRF SaMD Working Group documents.

**Datasets for development**

- MIMIC-IV-WDB (waveform companion to MIMIC-IV) on PhysioNet.
- eICU Collaborative Research Database on PhysioNet.
- PhysioNet 2010 Challenge: robust detection of heart beats in multimodal data (canonical reference for artifact rejection).

**Integration standards**

- HL7 v2.x messaging, MLLP framing (HL7 Implementation Guide: MLLP, Release 2).
- HL7 FHIR R4 / R5 Observation, DeviceMetric, Encounter resources.
- IHE PCD (Patient Care Device) profile family.
- Mirth Connect, Cloverleaf, Rhapsody, NextGen Connect (institutional integration engines).

**AWS services and reference architectures (forward-looking; verify URLs at recipe-publication time)**

- Amazon Kinesis Data Streams, Amazon MSK (Apache Kafka).
- Amazon Kinesis Data Firehose for durable raw-message archive to S3.
- AWS Lambda or Amazon Kinesis Data Analytics (Apache Flink) for stream processing.
- Amazon SageMaker real-time endpoints or async inference for the trajectory model.
- Amazon EventBridge / Amazon SNS for alert fan-out.
- Amazon DynamoDB for alert-event store and patient-state store.
- AWS HealthLake for the FHIR datastore where the trajectory pipeline integrates with the broader EHR-data plane.
- AWS Site-to-Site VPN or AWS Direct Connect for the institution-to-AWS integration hop.
- AWS HIPAA Eligible Services list (BAA verification at deployment time).

The TechWriter should treat this appendix as a starting set, not a prescriptive list, and should add or substitute references that match the specific recipe framing chosen on the first pass.
