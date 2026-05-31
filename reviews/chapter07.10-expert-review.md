# Expert Review: Recipe 7.10 - Optimal Intervention Timing Prediction

**Reviewer:** TechCodeReviewer
**Date:** 2026-05-31
**Recipe:** `chapter07.10-optimal-intervention-timing-prediction.md`
**Verdict:** PASS

---

## Summary

This recipe tackles one of the most clinically impactful and technically challenging problems in population health: predicting not just who is at risk, but when to intervene. The recipe is architecturally sound, clinically grounded, and refreshingly honest about the difficulty of the problem. It correctly positions the work as research/pilot phase and provides a pragmatic hybrid approach (dynamic survival model + decision rules) rather than overselling a full causal/RL solution. The findings below are improvements, not blockers.

---

## Clinical Accuracy

### HIGH-1: Ethical holdout strategy needs stronger guardrails

**Finding:** The "Honest Take" section mentions randomly withholding intervention from flagged patients to maintain training signal, and correctly notes this "raises ethical questions." However, it doesn't provide guidance on how to handle this responsibly.

**Clinical concern:** Randomly withholding a care management phone call from a patient predicted to be at rising risk is ethically distinct from withholding a medication. The recipe should distinguish between intervention types and their ethical implications for holdout designs.

**Remediation:** Add a paragraph clarifying: (1) holdout designs are only appropriate for low-intensity interventions (outreach calls, reminders) where standard of care is already met without the model; (2) IRB review is required; (3) alternative approaches exist (e.g., natural variation in care manager capacity creates quasi-experimental conditions without deliberate withholding); (4) never withhold clinical interventions (medication changes, referrals) for model training purposes.

---

### MEDIUM-1: Medication gap feature assumes single-fill dispensing model

**Finding:** The temporal feature `med_gap_days` computes gap as `observation_date - (last_fill_date + days_supply)`. This assumes retail pharmacy dispensing with discrete fills. Many chronic disease patients use 90-day mail-order, auto-refill programs, or specialty pharmacy with different dispensing patterns.

**Clinical concern:** Auto-refill patients may show no gap signal even when non-adherent (they receive but don't take medication). Specialty medications with REMS programs have different refill timing. The feature as described would produce false negatives for these populations.

**Remediation:** Add a note in the feature engineering section acknowledging dispensing model variation. Suggest supplementing pharmacy fill data with claims-based PDC (proportion of days covered) calculations and, where available, smart pill bottle or patient-reported adherence data.

---

### MEDIUM-2: No discussion of clinical validation requirements before deployment

**Finding:** The recipe describes model training and deployment but doesn't address the clinical validation pathway. For a model that directly influences care delivery timing, clinical stakeholders need to validate that the model's recommendations align with clinical judgment before go-live.

**Remediation:** Add a brief section or note covering: (1) silent/shadow mode deployment where recommendations are generated but not surfaced, compared against actual care team decisions; (2) clinical advisory board review of recommendation logic and thresholds; (3) prospective pilot with defined success metrics before full rollout.

---

### LOW-1: Sudden-onset exclusion could be more specific

**Finding:** The "Where it struggles" section mentions "sudden-onset events (trauma, stroke)" as inherently unpredictable. This is correct but could be more nuanced. Some strokes (those preceded by TIA, atrial fibrillation, or progressive carotid stenosis) do have detectable risk trajectories.

**Remediation:** Refine to: "Truly sudden-onset events without prodromal signals (traumatic injuries, embolic strokes without prior TIA, sudden cardiac arrest in patients without known cardiac disease)." This helps readers understand which conditions might still benefit from timing models even if they seem "sudden."

---

## Architectural Soundness

### HIGH-2: No model monitoring or drift detection in the architecture

**Finding:** The architecture diagram and service descriptions include CloudWatch for latency/throughput monitoring but don't address prediction drift detection. For a survival model trained on historical outcomes, distribution shift in the input features (e.g., new EHR system changes coding patterns, pandemic changes utilization patterns) can silently degrade timing accuracy.

**Remediation:** Add to the architecture: (1) SageMaker Model Monitor for input feature distribution tracking; (2) periodic recalibration checks comparing predicted vs. observed event rates within predicted time windows; (3) alerting when C-index on recent holdout data drops below a threshold (e.g., 0.65). This is especially critical for timing models because degradation manifests as systematically early or late recommendations, which is harder to detect than binary classification drift.

---

### MEDIUM-3: DynamoDB TTL strategy for recommendation expiration is implicit

**Finding:** The recommendation record includes `expires_at` but the architecture doesn't describe how expired recommendations are handled. If a care manager doesn't act within the action window, the recommendation should be removed from the worklist and the patient re-scored.

**Remediation:** Explicitly describe: (1) DynamoDB TTL on the `expires_at` field to auto-delete stale recommendations; (2) a DynamoDB Streams trigger on TTL deletions to log "expired without action" events for model feedback; (3) re-scoring logic that runs when a recommendation expires to determine if a new window has opened or the risk has resolved.

---

### MEDIUM-4: Real-time path latency budget is tight for VPC-bound Lambda

**Finding:** The recipe states 2-5 second end-to-end scoring latency for the real-time path. Lambda in VPC with cold starts, plus a SageMaker endpoint invocation, plus DynamoDB reads/writes, makes 2 seconds optimistic. VPC-attached Lambda cold starts alone can be 5-10 seconds.

**Remediation:** Add a note about: (1) provisioned concurrency for the scoring Lambda to eliminate cold starts; (2) SageMaker serverless inference as an alternative for bursty workloads (with the tradeoff of higher cold-start latency); (3) realistic latency expectation of 3-8 seconds for the real-time path, with the batch path handling the majority of scoring.

---

### LOW-2: No discussion of multi-region or disaster recovery

**Finding:** For a system that influences clinical care delivery timing, availability matters. If the scoring pipeline is down for a day, care managers lose their timing intelligence and revert to static risk lists.

**Remediation:** Add a brief note in prerequisites or architecture: for production, consider active-passive failover for the SageMaker endpoint and DynamoDB global tables for the recommendation store. Acknowledge that this is a decision-support system (not life-critical) so RPO/RTO requirements are moderate (hours, not minutes).

---

## Security Considerations

### HIGH-3: No data minimization guidance for the recommendation delivery layer

**Finding:** The recommendation record includes clinical details in the explanation field ("A1C increased from 7.8 to 9.1", "Missed medication refill (metformin, 12 days overdue)"). This PHI flows to the care management platform. The recipe doesn't discuss access controls on the delivery layer or data minimization principles.

**Remediation:** Add guidance on: (1) the recommendation store should enforce row-level access control (care managers only see their assigned patients); (2) the explanation field contains PHI and must be treated accordingly in the delivery platform; (3) consider whether the full clinical detail is needed in the recommendation or whether a coded explanation ("medication adherence gap detected") with a link to the full patient record in the EHR is sufficient to minimize PHI exposure in the worklist.

---

### MEDIUM-5: Kinesis stream encryption and access patterns need specificity

**Finding:** The prerequisites table mentions "Kinesis: server-side encryption with KMS" but doesn't address: (1) whether enhanced fan-out is needed for the real-time scoring consumer; (2) IAM policies scoping which consumers can read which streams; (3) data retention period for the stream (relevant for PHI minimization).

**Remediation:** Add to prerequisites: (1) Kinesis data retention should be set to minimum needed (24 hours default is usually sufficient for this use case); (2) use separate streams for different data sensitivity levels if mixing clinical and operational events; (3) consumer IAM policies should follow least-privilege per Lambda function.

---

### LOW-3: CloudTrail logging scope could be more specific

**Finding:** Prerequisites state "log all SageMaker, S3, DynamoDB, and Kinesis API calls." This is correct but should also explicitly include Lambda invocation logging and API Gateway access logs if the care team interface is API-based.

**Remediation:** Expand CloudTrail scope to include Lambda and any API-facing services. Note that CloudWatch Logs for Lambda should have a retention policy (not indefinite) to comply with data minimization.

---

## Completeness and Pedagogy

### LOW-4: Cost estimate doesn't include data transfer or Kinesis enhanced fan-out

**Finding:** The cost table is reasonable but omits data transfer costs (VPC endpoints, cross-AZ traffic for Lambda-to-SageMaker calls) and potential Kinesis enhanced fan-out costs if multiple consumers need the real-time stream.

**Remediation:** Add a line item for "Data transfer and VPC endpoints: ~$50-150/month" and note that Kinesis costs increase with enhanced fan-out consumers.

---

### LOW-5: Implementation timeline could note team composition assumptions

**Finding:** The 8-12 week "Basic" phase and 16-24 week "Production-ready" phase are reasonable but don't state team size or composition assumptions.

**Remediation:** Add a brief note: "Assumes a team of 2-3 ML engineers, 1 data engineer, 1 clinical informaticist, and part-time clinical advisory support. Smaller teams should extend timelines proportionally."

---

## Prioritized Findings Summary

| Priority | ID | Category | Finding |
|----------|-----|----------|---------|
| HIGH | HIGH-1 | Clinical | Ethical holdout strategy needs guardrails |
| HIGH | HIGH-2 | Architecture | No model monitoring or drift detection |
| HIGH | HIGH-3 | Security | No data minimization guidance for delivery layer |
| MEDIUM | MEDIUM-1 | Clinical | Medication gap feature assumes single-fill model |
| MEDIUM | MEDIUM-2 | Clinical | No clinical validation pathway described |
| MEDIUM | MEDIUM-3 | Architecture | DynamoDB TTL and expiration handling implicit |
| MEDIUM | MEDIUM-4 | Architecture | Real-time latency budget optimistic for VPC Lambda |
| MEDIUM | MEDIUM-5 | Security | Kinesis encryption and access patterns underspecified |
| LOW | LOW-1 | Clinical | Sudden-onset exclusion could be more nuanced |
| LOW | LOW-2 | Architecture | No DR/availability discussion |
| LOW | LOW-3 | Security | CloudTrail scope incomplete |
| LOW | LOW-4 | Completeness | Cost estimate missing data transfer |
| LOW | LOW-5 | Completeness | Timeline missing team composition |

---

## Strengths

- **Exceptional problem framing.** The opening scenario (care manager with 200 patients, 8 call slots) immediately grounds the technical content in clinical reality. This is the best problem statement in Chapter 7.
- **Honest complexity acknowledgment.** The recipe correctly positions this as research/pilot, doesn't oversell causal inference capabilities, and recommends starting with the hybrid approach.
- **Self-fulfilling prophecy discussion.** Calling out how successful intervention erodes training signal is a sophisticated insight that most healthcare ML content ignores.
- **Intervention fatigue modeling.** Including dampening factors for recent contact and declined outreach shows real-world operational awareness.
- **Architecture matches the problem.** The split between batch (model training, daily features) and real-time (event-driven scoring) paths is appropriate for the latency requirements.
- **The "Honest Take" section is genuinely honest.** It doesn't hedge with corporate language; it tells the reader what will actually happen when they try to build this.

---

## Verdict

**PASS.** The recipe is clinically sound, architecturally appropriate, and provides actionable guidance for a genuinely difficult problem. The HIGH findings (ethical holdout guardrails, model monitoring, data minimization) are important additions but don't represent errors in the current content. They represent gaps that should be filled before a reader treats this as a complete implementation guide. The recipe's explicit "Research/Pilot" phase designation and honest discussion of limitations appropriately set expectations.

---

*Reviewed 2026-05-31. 3 HIGH, 5 MEDIUM, 5 LOW findings. Verdict: PASS.*
