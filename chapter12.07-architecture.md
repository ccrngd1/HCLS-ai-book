# Recipe 12.7 Architecture and Implementation: Vital Sign Trajectory Monitoring

*Companion to [Recipe 12.7: Vital Sign Trajectory Monitoring](chapter12.07-vital-sign-trajectory-monitoring). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon Kinesis Data Streams for vital sign ingestion.** Vital sign data from bedside monitors and nursing assessments arrives continuously and needs to be processed with low latency. Kinesis Data Streams provides the durable, ordered, scalable streaming layer that can handle thousands of data points per second across hundreds of patients. Each patient gets a partition key, ensuring their readings are processed in order. The 24-hour (extendable to 365 days) retention means you can reprocess data if your analysis logic changes.

**AWS Lambda for event-driven trajectory computation.** Each new vital sign reading triggers a trajectory update for that patient. Lambda handles the burst pattern well: quiet at 3am, heavy at shift-change assessment times. For floor patients with intermittent vitals, the invocation pattern is naturally sparse and Lambda's per-invocation pricing makes sense. For continuous monitoring scenarios with higher throughput, Kinesis Data Analytics (Apache Flink) is the alternative.

**Amazon Kinesis Data Analytics (Apache Flink) for continuous stream processing.** For ICU-level continuous monitoring, the stream processing needs stateful windowed computations: rolling averages, slope estimates, cross-parameter correlations computed over sliding windows. Apache Flink (managed via Kinesis Data Analytics) handles stateful stream processing with exactly-once semantics. It maintains per-patient state without external database calls on every event.

**Amazon DynamoDB for patient state storage.** Each patient's rolling baseline, current trajectory metrics, and alert history need to live in a low-latency store that can handle high write throughput. DynamoDB's single-digit millisecond reads and writes make it suitable for the stateful computations that reference and update patient state on every new reading. TTL support automatically ages out data for discharged patients.

<!-- TODO (TechWriter): Expert review M6 (MEDIUM). Add ADT event listener description: on discharge, immediately delete patient state (don't rely on TTL); on admission, initialize fresh state with baseline_stable=false; on transfer, preserve state but update unit context for alert routing. -->

**Amazon Timestream for historical trajectory storage.** The full history of vital sign readings and computed trajectory metrics goes into a time series database optimized for temporal queries. Timestream handles the time-based retention tiers (hot data for recent trajectories, cold data for research and retrospective analysis) and supports the temporal query patterns (give me this patient's heart rate slope over the last 12 hours) natively.

**Amazon SNS for alert routing.** When trajectory analysis produces an alert, it needs to reach the right person through the right channel. SNS handles fan-out to multiple subscribers: pager, EHR notification, nursing station dashboard, charge nurse summary. Topic-based routing allows different alert severities to reach different endpoints. All subscription endpoints (pager API, dashboard webhook, EHR integration) must be covered under your organization's BAA chain. An alert containing vital signs and patient identifiers is PHI regardless of the delivery channel.

<!-- TODO (TechWriter): Expert review M7 (MEDIUM). Add note: if alert delivery targets external endpoints (pager vendor API), configure a NAT gateway in a controlled subnet with outbound security group rules limited to vendor IP ranges. Prefer VPC-internal integrations (PrivateLink) to avoid PHI egress to the public internet. -->

**Amazon CloudWatch for system health monitoring.** You're building a clinical safety system. You need to know immediately if the pipeline falls behind, if Lambda errors spike, if Kinesis is throttling, or if alert delivery latency exceeds acceptable bounds. CloudWatch alarms on processing latency, error rates, and alert delivery confirmation close the operational monitoring loop.

### Architecture Diagram

```mermaid
flowchart TD
    A[Bedside Monitors\nHL7/FHIR] -->|Continuous| B[Kinesis Data Streams\npatient-vitals]
    C[Nursing Assessments\nEHR Events] -->|Intermittent| B
    D[MAR Events\nMedication Admin] -->|Event-driven| B

    B -->|Stream| E{Data Density?}
    E -->|ICU: Continuous| F[Kinesis Data Analytics\nApache Flink]
    E -->|Floor: Intermittent| G[Lambda\ntrajectory-processor]

    F -->|State Updates| H[DynamoDB\npatient-state]
    G -->|State Updates| H

    F -->|Trajectory Metrics| I[Timestream\nvital-trajectories]
    G -->|Trajectory Metrics| I

    F -->|Alert Triggers| J[Lambda\nalert-evaluator]
    G -->|Alert Triggers| J

    J -->|Fetch Context| H
    J -->|Threshold Check| K{Alert Level?}

    K -->|Watch| L[DynamoDB\nUpdate Status]
    K -->|Alert/Alarm| M[SNS\nclinical-alerts]
    M -->|Pager| N[Clinical Staff]
    M -->|Dashboard| O[Unit Board]
    M -->|EHR| P[In-Chart Notification]

    style B fill:#f9f,stroke:#333
    style H fill:#9ff,stroke:#333
    style I fill:#9ff,stroke:#333
    style M fill:#ff9,stroke:#333
```

The routing decision is implicit in the data source: continuous monitor feeds (sub-second frequency) route to the Flink application; EHR-documented assessments (multi-hour frequency) route to Lambda. A patient transferred to the ICU starts producing continuous data immediately, and the Flink path activates without manual intervention. Both paths write to the same patient state store, so trajectory history is preserved across transitions.

<!-- TODO (TechWriter): Expert review H2 (HIGH). Add dead-letter queue (SQS) on both Lambda functions and a side-output on the Flink application for failed events. Add CloudWatch alarms on DLQ depth > 0. In a clinical safety system, a silently dropped reading is a patient safety risk. Add brief prose and update the architecture diagram to include DLQ. -->

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Kinesis Data Streams, Kinesis Data Analytics (Flink), AWS Lambda, Amazon DynamoDB, Amazon Timestream, Amazon SNS, Amazon CloudWatch |
| **IAM Permissions** | Runtime role: `kinesis:PutRecord`, `kinesis:GetRecords`, `kinesisanalytics:DescribeApplication`, `lambda:InvokeFunction`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `timestream:WriteRecords`, `timestream:Select`, `sns:Publish`. Deployment role (separate, CI/CD only): `kinesisanalytics:CreateApplication`, `kinesisanalytics:UpdateApplication`, `kinesisanalytics:StartApplication`, `kinesisanalytics:StopApplication`. |
| **BAA** | AWS BAA signed (vital signs are PHI; all services must be HIPAA-eligible) |
| **Encryption** | Kinesis: server-side encryption with KMS; DynamoDB: encryption at rest (default); Timestream: encryption at rest (default); SNS: SSE-KMS encrypted topics (CMK), all subscribers must be BAA-covered endpoints; all transit over TLS |
| **VPC** | Production: Flink application and Lambda in VPC with VPC endpoints for DynamoDB, Timestream, SNS, CloudWatch Logs. Interface endpoints for Kinesis. Lambda and Flink subnets: private subnets with no NAT gateway. All AWS service access via VPC endpoints. No internet egress path for PHI-processing workloads. |
| **CloudTrail** | Enabled for all API calls. Critical for audit trail on alert generation and delivery. |
| **Data Integration** | HL7v2 or FHIR interface to bedside monitor data, EHR vital sign documentation, and medication administration records. This is often the hardest prerequisite. |
| **Sample Data** | MIMIC-III or MIMIC-IV (publicly available ICU datasets from MIT/PhysioNet) for development. Never use real patient data in dev environments. |
| **Cost Estimate** | Kinesis: ~$0.015/hr per shard (1 MB/s in). Lambda: negligible for intermittent vitals. Flink: ~$0.11/hr per KPU. DynamoDB: on-demand ~$1.25 per million writes. Timestream: ~$0.50/GB ingested. Total per patient-hour depends heavily on monitoring density. |

### Ingredients

| AWS Service | Role |
|-------------|------|
| **Amazon Kinesis Data Streams** | Ingests vital sign readings from all sources into an ordered, durable stream |
| **Amazon Kinesis Data Analytics** | Runs stateful Apache Flink application for continuous trajectory computation (ICU) |
| **AWS Lambda** | Processes intermittent vital sign events for floor patients; evaluates alert conditions |
| **Amazon DynamoDB** | Stores per-patient rolling state: baselines, current trajectory, alert history |
| **Amazon Timestream** | Stores full vital sign history and computed trajectory metrics for temporal queries |
| **Amazon SNS** | Routes clinical alerts to appropriate channels based on severity |
| **AWS KMS** | Manages encryption keys for all data stores and streams |
| **Amazon CloudWatch** | Monitors pipeline health, latency, error rates; alarms on processing delays |

### Code

#### Walkthrough

**Step 1: Ingest vital sign event.** A new vital sign reading arrives from any source: a bedside monitor transmitting continuous waveforms, a nurse entering assessment data into the EHR, or a connected device reporting a measurement. The ingestion layer normalizes this into a standard event format and places it onto the streaming layer, keyed by patient ID to ensure per-patient ordering. The normalization step matters because different sources use different units (Celsius vs. Fahrenheit), different measurement types (invasive vs. non-invasive blood pressure), and different timestamp formats. Without normalization here, every downstream component would need to handle these variations. Skip this step and you get a stream of incompatible data formats that no trajectory logic can reliably process.

```pseudocode
FUNCTION ingest_vital_sign(source_event):
    // Normalize the incoming event into our standard format.
    // Different sources send data in wildly different shapes.
    // A bedside monitor sends numeric arrays every second.
    // A nurse's EHR entry sends a single observation with free-text context.
    // We need one consistent format downstream.

    normalized = {
        patient_id: extract patient identifier from source_event,
        timestamp: convert source timestamp to UTC ISO-8601,
        parameter: standardize parameter name (e.g., "HR", "SBP", "DBP", "RR", "SpO2", "Temp"),
        value: numeric value in standard units (bpm, mmHg, breaths/min, %, Celsius),
        source_type: "continuous_monitor" | "nursing_assessment" | "device",
        measurement_method: "invasive" | "non_invasive" | "manual",
        confidence: data quality indicator (1.0 for nurse-entered, variable for devices)
    }

    // Write to the streaming layer, partitioned by patient_id.
    // This guarantees all readings for a single patient arrive in order
    // at the same processing node.
    write normalized to stream with partition_key = patient_id

    RETURN normalized
```

**Step 2: Retrieve and update patient state.** Before computing anything about a trajectory, we need to know what "normal" looks like for this patient right now. The patient state record holds rolling statistics computed from recent history: their median heart rate over the past 24 hours, the standard deviation of their blood pressure, their typical respiratory rate variability. On each new reading, we update these baselines using exponential moving averages, which weight recent readings more heavily while still incorporating longer-term history. This patient-specific baseline is what distinguishes "heart rate of 95 is concerning" (for a patient whose baseline is 68) from "heart rate of 95 is normal" (for a patient whose baseline is 92). Skip this step and you're comparing every patient against population norms, which generates massive false alert rates.

```pseudocode
FUNCTION update_patient_state(vital_event):
    // Fetch this patient's current state from the state store.
    // If no state exists (new admission), initialize with defaults.
    state = fetch state for vital_event.patient_id from state_store

    IF state is NULL:
        // New patient. Initialize with the first reading as a provisional baseline.
        // The baseline will stabilize after 4-6 hours of data collection.
        state = {
            patient_id: vital_event.patient_id,
            admitted_at: vital_event.timestamp,
            baselines: {},     // will be populated per-parameter
            trajectory: {},     // will hold slope, acceleration per-parameter
            last_readings: [],     // rolling window of recent values
            alert_history: [],     // track recent alerts to avoid flooding
            baseline_stable: false   // flag: not enough data yet for reliable alerts
        }

    parameter = vital_event.parameter
    value     = vital_event.value

    // Update the rolling window for this parameter.
    // Keep the last N readings (N depends on data density).
    // For continuous monitors: last 60 minutes of readings.
    // For intermittent assessments: last 10 readings.
    append {value: value, timestamp: vital_event.timestamp} to state.last_readings[parameter]
    trim state.last_readings[parameter] to max window size

    // Update baseline using exponential moving average (EMA).
    // Alpha controls responsiveness: smaller alpha = more stable baseline.
    // We use alpha=0.05 for baselines (slow-moving) so short-term changes
    // don't immediately shift what we consider "normal."
    // Production note: Clip values > 4 sigma from current baseline before
    // updating. EMA has infinite memory, so a single outlier (e.g., transient
    // SVT producing HR=180) would permanently bias the baseline upward.
    alpha = 0.05
    IF state.baselines[parameter] exists:
        // Skip baseline update if this reading is a likely outlier.
        IF baseline_std > 0 AND abs(value - state.baselines[parameter].mean) > 4 * state.baselines[parameter].std:
            // Outlier: include in trajectory computation (Step 3) but not baseline.
            skip_baseline_update = true
        ELSE:
            skip_baseline_update = false

        IF NOT skip_baseline_update:
            state.baselines[parameter].mean = (1 - alpha) * state.baselines[parameter].mean + alpha * value
            // Update rolling standard deviation estimate (Welford's method simplified)
            deviation = abs(value - state.baselines[parameter].mean)
            state.baselines[parameter].std = (1 - alpha) * state.baselines[parameter].std + alpha * deviation
    ELSE:
        state.baselines[parameter] = { mean: value, std: 0.0 }

    // Check if we have enough data to consider baselines stable.
    // Require at least 4 hours of data (or 10 intermittent readings).
    hours_since_admission = (vital_event.timestamp - state.admitted_at) in hours
    IF hours_since_admission >= 4 AND NOT state.baseline_stable:
        state.baseline_stable = true

    // Persist updated state.
    write state to state_store for vital_event.patient_id

    RETURN state
```

**Step 3: Compute trajectory features.** This is the core math. Given the rolling window of recent readings and the patient's established baseline, compute the trajectory: the slope (is it going up or down?), the acceleration (is the slope steepening?), the deviation from baseline (how far from normal?), and the variability (is the signal more erratic than usual?). These features capture the "shape" of the patient's recent physiological history. A simple linear regression over the recent window gives you the slope. The difference between the current slope and the slope from the prior window gives you acceleration. These are straightforward calculations, but they need to be robust to outliers and missing data. Skip this step and you have individual readings with no contextual meaning.

```pseudocode
FUNCTION compute_trajectory(state, parameter):
    readings = state.last_readings[parameter]

    IF length(readings) < 3:
        // Not enough data to estimate a meaningful trajectory.
        RETURN { slope: null, acceleration: null, deviation: null, variability: null }

    // Compute slope via simple linear regression over the recent window.
    // X = time offsets from first reading (in minutes).
    // Y = vital sign values.
    times  = [minutes_since(readings[0].timestamp, r.timestamp) for r in readings]
    values = [r.value for r in readings]

    slope = linear_regression_slope(times, values)
    // slope is in units-per-minute (e.g., bpm per minute for heart rate)

    // Compute acceleration: compare current slope to slope from the earlier half of the window.
    midpoint = length(readings) / 2
    early_slope = linear_regression_slope(times[0:midpoint], values[0:midpoint])
    late_slope  = linear_regression_slope(times[midpoint:], values[midpoint:])
    acceleration = late_slope - early_slope
    // Positive acceleration = trend is steepening. Getting worse faster.

    // Deviation from patient baseline (in standard deviations).
    current_value = readings[last].value
    baseline_mean = state.baselines[parameter].mean
    baseline_std  = state.baselines[parameter].std
    IF baseline_std > 0:
        deviation = (current_value - baseline_mean) / baseline_std
    ELSE:
        deviation = 0  // can't compute deviation without variability estimate

    // Variability: coefficient of variation over the recent window.
    // High variability can indicate instability even if the trend is flat.
    window_mean = mean(values)
    window_std  = standard_deviation(values)
    variability = window_std / window_mean IF window_mean > 0 ELSE 0

    trajectory = {
        parameter: parameter,
        slope: slope,           // units per minute
        acceleration: acceleration,    // change in slope (second derivative)
        deviation: deviation,       // standard deviations from patient baseline
        variability: variability,     // coefficient of variation (instability indicator)
        current: current_value,
        baseline: baseline_mean,
        window_minutes: times[last]    // how much time this trajectory covers
    }

    RETURN trajectory
```

**Step 4: Multi-parameter correlation check.** Vital signs don't move independently. The body's compensatory mechanisms create correlated patterns. When multiple parameters move in a coordinated way that matches a known deterioration signature, that's much more concerning than any single parameter drifting. This step checks whether the current set of trajectories across all monitored parameters matches any known clinical pattern: the sepsis signature (rising HR + rising RR, then falling BP), the hemorrhage pattern (rising HR + falling BP + narrowing pulse pressure), the respiratory failure pattern (falling SpO2 + rising RR + rising HR). Pattern matching here dramatically improves specificity: instead of alerting on "heart rate trending up," you alert on "heart rate trending up in the context of respiratory rate also trending up, which matches the early sepsis signature." Skip this step and you're monitoring each vital sign in isolation, missing the inter-parameter signals that experienced clinicians recognize instantly.

```pseudocode
// Known deterioration signatures. Each defines expected trajectory directions
// for multiple parameters that, when seen together, suggest a specific clinical concern.
DETERIORATION_SIGNATURES = {
    "early_sepsis": {
        required: { "HR": slope > 0, "RR": slope > 0 },
        supporting: { "Temp": deviation > 1.5 OR deviation < -1.5, "SBP": slope < 0 },
        min_required: 2,
        min_supporting: 1,
        severity: "alert",
        message: "Coordinated HR/RR rise with hemodynamic compromise consistent with early sepsis"
    },
    "hemorrhage": {
        required: { "HR": slope > 0, "SBP": slope < 0 },
        supporting: { "DBP": slope < 0, "RR": slope > 0 },
        min_required: 2,
        min_supporting: 1,
        severity: "alarm",
        message: "Tachycardia with falling blood pressure suggests active hemorrhage"
    },
    "respiratory_failure": {
        required: { "SpO2": slope < 0, "RR": slope > 0 },
        supporting: { "HR": slope > 0 },
        min_required: 2,
        min_supporting: 0,
        severity: "alert",
        message: "Falling oxygenation with compensatory tachypnea"
    },
    "cardiac_decompensation": {
        required: { "HR": slope > 0, "SpO2": slope < 0 },
        supporting: { "RR": slope > 0, "SBP": slope < 0 },
        min_required: 2,
        min_supporting: 1,
        severity: "alert",
        message: "Multi-parameter pattern consistent with cardiac decompensation"
    }
}

FUNCTION check_multi_parameter_patterns(all_trajectories):
    matched_patterns = []

    FOR each pattern_name, signature in DETERIORATION_SIGNATURES:
        required_met = 0
        supporting_met = 0

        FOR each param, condition in signature.required:
            IF param in all_trajectories:
                traj = all_trajectories[param]
                IF evaluate_condition(traj, condition):
                    required_met += 1

        FOR each param, condition in signature.supporting:
            IF param in all_trajectories:
                traj = all_trajectories[param]
                IF evaluate_condition(traj, condition):
                    supporting_met += 1

        IF required_met >= signature.min_required AND supporting_met >= signature.min_supporting:
            append {
                pattern: pattern_name,
                severity: signature.severity,
                message: signature.message,
                evidence: { required_met, supporting_met, trajectories: all_trajectories }
            } to matched_patterns

    RETURN matched_patterns
```

**Step 5: Alert evaluation and suppression.** Not every trajectory anomaly should generate an alert. This step applies the intelligence layer: Should this alert fire? Has the patient recently received a medication that explains the trend? Was a similar alert generated in the last hour (avoid flooding)? Is the patient's baseline still stabilizing (first few hours of admission)? Is this a known post-procedure recovery pattern? The suppression logic is arguably more important than the detection logic. A system that fires correctly but too often is worse than a system that fires less often but is always meaningful. Clinical staff will tune out within days if your signal-to-noise ratio is poor. Skip this step and you'll achieve technically correct trajectory detection that nobody looks at.

```pseudocode
FUNCTION evaluate_alert(patient_state, trajectories, pattern_matches):
    // Suppression checks (any of these can block an alert)

    // 1. Baseline not yet stable (early admission period)
    IF NOT patient_state.baseline_stable:
        RETURN { action: "suppress", reason: "Baseline still stabilizing" }

    // 2. Recent alert for same pattern (cooldown period)
    FOR each recent_alert in patient_state.alert_history:
        IF recent_alert.pattern == pattern_matches[0].pattern
           AND minutes_since(recent_alert.timestamp) < 60:
            RETURN { action: "suppress", reason: "Same alert within cooldown window" }

    // 3. Medication effect window
    // Check if a medication administered in the last 2 hours has an expected
    // effect that explains the observed trajectory.
    // NOTE: This requires read access to the MAR via HL7/FHIR interface.
    // Separate service account with audit logging. MAR data is PHI.
    recent_meds = fetch recent medications for patient_state.patient_id (last 2 hours)
    FOR each med in recent_meds:
        expected_effects = lookup_expected_effects(med.medication_code)
        IF current trajectory matches expected_effects:
            RETURN { action: "suppress", reason: "Expected medication effect: " + med.name }

    // 4. Artifact detection
    // If a single reading caused a dramatic spike/drop that recovered within 2 minutes,
    // it's likely measurement artifact.
    FOR each param, traj in trajectories:
        IF traj.variability > ARTIFACT_THRESHOLD AND traj.window_minutes < 2:
            RETURN { action: "suppress", reason: "Probable measurement artifact" }

    // All suppression checks passed. Determine alert level.
    IF length(pattern_matches) > 0:
        // Multi-parameter pattern detected. Use the pattern's severity.
        highest_severity = max severity across pattern_matches
        RETURN {
            action: highest_severity,  // "alert" or "alarm"
            patterns: pattern_matches,
            trajectories: trajectories
        }

    // No multi-parameter pattern, but check individual parameter thresholds.
    // Single-parameter alerts require higher deviation to fire (reduce noise).
    FOR each param, traj in trajectories:
        IF abs(traj.deviation) > 3.0 AND abs(traj.slope) > SLOPE_THRESHOLD[param]:
            RETURN {
                action: "watch",
                reason: param + " deviating significantly with consistent slope",
                trajectories: trajectories
            }

    RETURN { action: "none" }
```

**Step 6: Persist trajectory metrics and route alerts.** The final step stores the computed trajectory data for historical analysis and research, then routes any active alerts to the appropriate clinical channels. Every trajectory computation is stored regardless of whether it triggered an alert, because retrospective analysis ("show me this patient's trajectory for the 12 hours before the code") is one of the most valuable use cases. Alert routing depends on severity: "watch" updates the patient's dashboard status, "alert" pages the assigned nurse, "alarm" triggers immediate clinical escalation. Each alert includes the trajectory visualization data so the clinician receiving it can see the pattern, not just a number.

```pseudocode
FUNCTION persist_and_route(patient_state, trajectories, alert_decision):
    // Store trajectory metrics in time series database (always, regardless of alert)
    FOR each param, traj in trajectories:
        write to time_series_store:
            patient_id: patient_state.patient_id,
            timestamp: current_time,
            parameter: param,
            slope: traj.slope,
            acceleration: traj.acceleration,
            deviation: traj.deviation,
            variability: traj.variability,
            current: traj.current,
            baseline: traj.baseline

    // Route alert based on decision
    IF alert_decision.action == "none" OR alert_decision.action == "suppress":
        RETURN  // nothing to route

    IF alert_decision.action == "watch":
        // Update patient dashboard status. No active paging.
        update patient_state.status = "watching"
        update unit_dashboard for patient_state.patient_id with trajectories
        RETURN

    IF alert_decision.action == "alert":
        // Clinical alert: notify assigned nurse via preferred channel
        alert_payload = {
            patient_id: patient_state.patient_id,
            severity: "alert",
            timestamp: current_time,
            summary: alert_decision.patterns[0].message,
            trajectories: format_for_display(trajectories),
            recommended: "Assess patient. Consider increasing monitoring frequency."
        }
        publish alert_payload to clinical_alerts_topic (filtered by unit + severity)
        append alert_payload to patient_state.alert_history
        RETURN

    IF alert_decision.action == "alarm":
        // High-priority clinical alarm: immediate escalation
        alarm_payload = {
            patient_id: patient_state.patient_id,
            severity: "alarm",
            timestamp: current_time,
            summary: alert_decision.patterns[0].message,
            trajectories: format_for_display(trajectories),
            recommended: "Immediate bedside assessment required. Consider rapid response activation."
        }
        publish alarm_payload to clinical_alerts_topic (filtered by unit + severity)
        append alarm_payload to patient_state.alert_history
        RETURN
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter12.07-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample trajectory alert output:**

```json
{
  "patient_id": "P-00847291",
  "alert_timestamp": "2026-03-15T14:32:08Z",
  "severity": "alert",
  "summary": "Coordinated HR/RR rise with hemodynamic compromise consistent with early sepsis",
  "pattern": "early_sepsis",
  "trajectories": {
    "HR": {
      "current": 98,
      "baseline": 74,
      "slope_per_hour": 3.2,
      "deviation_sigma": 2.4,
      "window_hours": 6
    },
    "RR": {
      "current": 22,
      "baseline": 16,
      "slope_per_hour": 0.8,
      "deviation_sigma": 2.1,
      "window_hours": 6
    },
    "SBP": {
      "current": 108,
      "baseline": 128,
      "slope_per_hour": -2.1,
      "deviation_sigma": -1.8,
      "window_hours": 6
    }
  },
  "recommended_action": "Assess patient. Consider lactate, blood cultures, and fluid resuscitation per sepsis protocol.",
  "alert_id": "ALT-20260315-143208-P00847291"
}
```

In production, pager notifications typically contain location identifiers (room/bed) rather than patient IDs, with a link to the authenticated clinical display for full trajectory detail. The payload above is the internal representation; the pager-facing message would be something like: "Rm 412-B: Trajectory alert. See unit board for details."

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency (continuous) | 5-15 seconds from reading to alert |
| End-to-end latency (intermittent) | 30-60 seconds from EHR entry to alert |
| Sensitivity (deterioration detection) | 70-85% (depends on population and event definition) |
| Specificity | 85-95% (with suppression logic active) |
| Alert rate (per patient per day) | 0.5-2 alerts (clinically meaningful trajectory changes) |
| False alert rate | Target < 20% of all alerts (critical for adoption) |
| Cost per patient-hour (ICU, continuous) | ~$0.30-0.40 |
| Cost per patient-hour (floor, intermittent) | ~$0.03-0.05 |

**Where it struggles:** Patients with highly variable baselines (atrial fibrillation patients whose HR naturally swings 30+ bpm). Post-operative patients where expected recovery trajectories are hard to distinguish from deterioration. Patients on multiple vasoactive medications where vital signs are being actively managed. And the first 4-6 hours of any admission, where the system doesn't yet know what "normal" is for this patient.

---

## Variations and Extensions

**Integration with early warning scores.** Rather than replacing NEWS/MEWS, augment them. Compute the trajectory of the composite score itself. A NEWS score that went from 2 to 3 to 4 to 5 over four assessments has a trajectory that's more informative than the current score of 5 alone. Overlay trajectory features onto the existing EWS framework rather than asking clinical teams to adopt an entirely new scoring paradigm.

**Post-discharge remote monitoring.** The same trajectory engine works for remote patient monitoring (RPM) use cases: patients discharged with a connected blood pressure cuff or pulse oximeter. The data density is lower (1-3 readings per day) and the clinical response pathways are different (telehealth nurse callback rather than bedside response), but the core pattern of baseline, trajectory, deviation, and alert routing is identical. The alert thresholds need to be wider for outpatient populations where less frequent monitoring is expected.

**Retrospective trajectory research.** Store all trajectory computations (not just alerts) in your time series database. Clinicians and quality teams can then run retrospective analyses: "For every rapid response event in the last year, show me the trajectory of all vital signs for the preceding 24 hours." This creates a feedback loop where real clinical events validate and refine your deterioration signatures over time.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html)
- [Amazon Kinesis Data Analytics for Apache Flink](https://docs.aws.amazon.com/kinesisanalytics/latest/java/what-is.html)
- [Amazon Timestream Developer Guide](https://docs.aws.amazon.com/timestream/latest/developerguide/what-is-timestream.html)
- [Amazon Timestream Pricing](https://aws.amazon.com/timestream/pricing/)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**Clinical and Research References:**
- [MIMIC-IV Dataset (PhysioNet)](https://physionet.org/content/mimiciv/): Publicly available ICU patient data for development and validation
- [National Early Warning Score (NEWS2) Specification](https://www.england.nhs.uk/ourwork/clinical-policy/sepsis/nationalearlywarningscore/): The current UK NHS early warning scoring standard

**AWS Sample Repos:**
- [`amazon-kinesis-data-analytics-examples`](https://github.com/aws-samples/amazon-kinesis-data-analytics-examples): Apache Flink application patterns for streaming analytics
- [`amazon-timestream-tools`](https://github.com/awslabs/amazon-timestream-tools): Sample code for writing to and querying Amazon Timestream

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| **Basic** (single parameter, threshold alerts, intermittent data) | 4-6 weeks |
| **Production-ready** (multi-parameter, trajectory + correlation, suppression logic, EHR integration) | 4-6 months |
| **With variations** (continuous monitoring, medication-aware suppression, retrospective research platform) | 8-12 months |

---


---

*← [Main Recipe 12.7](chapter12.07-vital-sign-trajectory-monitoring) · [Python Example](chapter12.07-python-example) · [Chapter Preface](chapter12-preface)*
