# Recipe 12.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 12.10. It shows one way you could translate the physiological waveform analysis pipeline into working Python using boto3 against Amazon Kinesis Data Streams (mocked with `MockKinesisStream`), Amazon SageMaker (mocked with a pure-Python `MockWaveformClassifier` that stands in for a real CNN or transformer model), Amazon Timestream (mocked with `MockTimestream`), Amazon S3 (mocked with `MockS3`), Amazon SNS (mocked with `MockSNS`), and Amazon CloudWatch (mocked with `MockCloudWatch`). The demo runs on a synthetic single-patient ECG dataset: 60 seconds of simulated Lead II ECG at 250 Hz with a normal sinus rhythm baseline, a few injected premature ventricular complexes (PVCs), and a short run of simulated atrial fibrillation. You can see the bandpass filtering, the signal quality scoring, the windowed classification, the persistence-based alert logic with cooldown suppression, and the Timestream storage, end-to-end without provisioning anything. It is not production-ready. There is no real Kinesis stream, no real SageMaker endpoint, no real Timestream database, no real SNS topic, no real device integration engine, no real FDA-cleared classification model, no real HL7/IEEE 11073 parsing, no real multi-lead cross-validation, no real patient context from the EHR, no real clinical workflow integration, no per-Lambda IAM least privilege, no KMS customer-managed keys, no VPC endpoints, and no audit-trail compliance logging. Think of it as the sketchpad version: useful for understanding the shape of a waveform analysis pipeline that respects the preprocess-before-classify discipline, the quality-gate discipline, the persistence-before-alert discipline, and the suppress-known-conditions discipline this recipe demands. It is not something you would point at a real ICU on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five pseudocode steps from the main recipe: ingest waveform samples from bedside monitors into Kinesis with per-patient ordering and archive to S3 (Step 1); preprocess raw waveforms with bandpass filtering, notch filtering, signal quality scoring, and quality-gate rejection (Step 2); classify clean waveform windows via SageMaker endpoint invocation returning rhythm labels with confidence scores (Step 3); apply post-processing alert logic with persistence thresholds, patient context suppression, and cooldown enforcement (Step 4); store all classifications to Timestream and publish actionable alerts to SNS (Step 5). The synthetic ECG, the simplified filtering, the mock classifier, and the toy alert logic in the demo are fictional; nothing in this file should be interpreted as a real arrhythmia detection system, real clinical decision support, or real FDA-cleared software for any real patient population.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

The demo runs against the Python standard library plus boto3; no other packages are imported. Production deployments swap the demo's `MockWaveformClassifier` for a real trained deep learning model (a 1D CNN such as those described in [Hannun et al. 2019](https://www.nature.com/articles/s41591-018-0268-3) for ECG rhythm classification, or a transformer architecture for multi-lead fusion) hosted on a SageMaker real-time endpoint with GPU inference (ml.g4dn.xlarge or ml.g5.xlarge); replace the demo's simplified bandpass filter with a proper scipy.signal Butterworth or FIR filter with appropriate order and transition bands; replace the demo's signal quality index with a multi-metric SQI that incorporates template matching, spectral analysis, and learned artifact classifiers; replace the demo's mock patient context with a real EHR integration that pulls active diagnoses, pacemaker status, and medication lists. The Gap to Production section spells out the substitutions.

In production you would also configure an Amazon Kinesis Data Stream with sufficient shards for your waveform throughput (one shard per ~5 patients at 250 Hz ECG), Amazon ECS/Fargate tasks for the continuous preprocessing (Lambda cold starts are unacceptable for real-time waveform processing), an Amazon SageMaker real-time endpoint with auto-scaling based on inference latency, an Amazon Timestream database with separate tables for classifications and system metrics (memory store retention of 24 hours, magnetic store retention of 90 days for operational queries, longer for research), Amazon S3 with lifecycle policies (Standard for 30 days, then Glacier for long-term research archival), Amazon SNS topics with subscription filters by severity level, and Amazon CloudWatch dashboards monitoring ingestion-to-alert latency, signal quality rejection rates, alert rates per patient, and model inference latency.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `kinesis:PutRecord` and `kinesis:GetRecords` on the waveform ingestion stream
- `s3:PutObject` on the waveform archive bucket
- `sagemaker:InvokeEndpoint` on the waveform classification endpoint
- `timestream:WriteRecords` and `timestream:Select` on the classification and metrics tables
- `sns:Publish` on the clinical alerts topic
- `cloudwatch:PutMetricData` for pipeline health metrics
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys

Scope each service's IAM role to specific resource ARNs. The preprocessing container needs Kinesis read and Timestream write only. The classification Lambda needs SageMaker invoke only. The alert Lambda needs SNS publish and Timestream write only. Avoid wildcard actions and resources in production.

A few things worth knowing upfront:

- **Waveform data linked to patient identifiers is PHI.** Even raw voltage values become PHI when associated with a patient ID. Every storage and compute service must be on the HIPAA eligible services list, encrypted with KMS, and inside your institutional VPC.
- **The signal quality gate is your most important defense against false alarms.** In real ICU data, 20-40% of waveform segments are artifact-contaminated. Passing these to the classifier produces confident wrong answers. Reject early, reject often.
- **Persistence thresholds are the second defense.** A single 10-second window classified as "atrial fibrillation" at 72% confidence is not actionable. Six consecutive windows at 85%+ confidence is. Tune persistence thresholds per condition based on clinical urgency and acceptable false alarm rates.
- **Timestream requires string-typed dimensions and epoch-millisecond timestamps.** The demo converts ISO timestamps to epoch milliseconds for the `Time` field and coerces all dimension values to strings. Production code should use explicit type coercion everywhere.
- **The example collapses many ECS tasks, Lambdas, and SageMaker endpoints into a single Python file.** In production, ingestion, preprocessing, classification, alert logic, and storage are separate services with their own scaling, error handling, and IAM boundaries.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, filter parameters, quality thresholds, classification model settings, alert persistence thresholds, and cooldown durations are what you would change between environments.

```python
import json
import logging
import math
import random
import statistics
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. Never log raw waveform values
# (they are PHI when linked to patient IDs). Log structural
# metadata only: run_id, patient_id (hashed in logs), window_count,
# sqi_score, classification_label, alert_generated.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry for transient failures. Waveform pipelines are
# latency-sensitive; retries must be fast or you fall behind
# the real-time stream.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients. The demo uses mocks; production swaps
# these for real boto3 clients.
REGION = "us-east-1"
kinesis_client = boto3.client(
    "kinesis", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client(
    "s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client(
    "sagemaker-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sns_client = boto3.client(
    "sns", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client(
    "cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
KINESIS_STREAM = "waveform-ingestion"
S3_ARCHIVE_BUCKET = "waveform-archive"
SAGEMAKER_ENDPOINT = "ecg-rhythm-classifier-v2"
TIMESTREAM_DB = "waveform-analytics"
TIMESTREAM_TABLE_CLASSIFICATIONS = "classifications"
TIMESTREAM_TABLE_METRICS = "system-metrics"
SNS_ALERT_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:clinical-waveform-alerts"

# --- Waveform Processing Parameters ---
# These vary by waveform type. The demo focuses on ECG Lead II.
WAVEFORM_CONFIG = {
    "ecg_lead_ii": {
        "sample_rate": 250,           # Hz
        "bandpass_low": 0.5,          # Hz (removes baseline wander)
        "bandpass_high": 40.0,        # Hz (removes muscle artifact, keeps morphology)
        "notch_freq": 60.0,           # Hz (powerline interference, 60 Hz in US)
        "window_seconds": 10,         # seconds per analysis window
        "window_overlap": 0.5,        # 50% overlap between consecutive windows
        "quality_threshold": 0.7,     # SQI below this = reject segment
    },
    "eeg_fp1": {
        "sample_rate": 256,
        "bandpass_low": 0.5,
        "bandpass_high": 50.0,
        "notch_freq": 60.0,
        "window_seconds": 30,
        "window_overlap": 0.5,
        "quality_threshold": 0.6,
    },
    "art_bp": {
        "sample_rate": 125,
        "bandpass_low": 0.1,
        "bandpass_high": 20.0,
        "notch_freq": 60.0,
        "window_seconds": 60,
        "window_overlap": 0.5,
        "quality_threshold": 0.65,
    },
}

# --- Alert Logic Parameters ---
# Persistence thresholds: how many consecutive windows must agree
# before generating an alert. Higher = fewer false alarms but
# slower detection. Tune per condition based on clinical urgency.
PERSISTENCE_THRESHOLDS = {
    "ventricular_tachycardia": 2,   # urgent: alert fast
    "ventricular_fibrillation": 1,  # critical: alert immediately
    "atrial_fibrillation": 5,       # less urgent: need more certainty
    "bradycardia": 4,
    "asystole": 1,                  # critical: alert immediately
    "premature_ventricular_complex": 8,  # only alert on frequent PVCs
}

# Confidence threshold: minimum model confidence to count toward
# persistence. Below this, the classification is too uncertain.
ALERT_CONFIDENCE_THRESHOLD = 0.75

# Cooldown: minutes after an alert before the same condition
# can re-alert for the same patient. Prevents alert storms.
COOLDOWN_MINUTES = {
    "ventricular_tachycardia": 5,
    "ventricular_fibrillation": 2,
    "atrial_fibrillation": 30,
    "bradycardia": 15,
    "premature_ventricular_complex": 60,
}

# Clinical severity levels for alert routing.
SEVERITY_MAP = {
    "ventricular_fibrillation": "CRITICAL",
    "asystole": "CRITICAL",
    "ventricular_tachycardia": "HIGH",
    "bradycardia": "MEDIUM",
    "atrial_fibrillation": "MEDIUM",
    "premature_ventricular_complex": "LOW",
    "normal_sinus_rhythm": "NONE",
}
```

---

## Step 1: Waveform Ingestion

This step receives waveform samples from bedside monitors and pushes them into Kinesis for downstream processing. In production, a device integration engine handles the HL7/IEEE 11073 protocol translation. Here we simulate the ingestion of pre-digitized samples.

```python
# ─────────────────────────────────────────────────────────────────────
# STEP 1: Ingest waveform samples into Kinesis and archive to S3.
# Maps to pseudocode Step 1 in the main recipe.
# In production, a device integration engine (e.g., Capsule Medical
# Device Information System, Bernoulli Health, or a custom HL7v2/
# IEEE 11073 adapter) translates proprietary monitor protocols into
# structured records and pushes them here.
# ─────────────────────────────────────────────────────────────────────

def ingest_waveform_batch(patient_id, waveform_type, timestamp,
                          samples, kinesis=None, s3=None):
    """
    Push a batch of waveform samples to Kinesis and archive to S3.

    Parameters
    ----------
    patient_id : str
        Unique patient identifier for this ICU stay.
    waveform_type : str
        Signal type key (e.g., "ecg_lead_ii", "art_bp", "eeg_fp1").
    timestamp : str
        ISO 8601 timestamp of the first sample in this batch.
    samples : list[float]
        Raw ADC values from the bedside monitor.
    kinesis : mock or real Kinesis client
    s3 : mock or real S3 client
    """
    kin = kinesis or kinesis_client
    s3c = s3 or s3_client

    config = WAVEFORM_CONFIG[waveform_type]

    record = {
        "patient_id": patient_id,
        "waveform_type": waveform_type,
        "timestamp": timestamp,
        "sample_rate": config["sample_rate"],
        "values": samples,
    }

    # Kinesis partition key = patient + waveform type.
    # Guarantees ordering: all ECG samples from one patient
    # arrive in sequence within the same shard.
    partition_key = f"{patient_id}:{waveform_type}"

    kin.put_record(
        StreamName=KINESIS_STREAM,
        Data=json.dumps(record).encode("utf-8"),
        PartitionKey=partition_key,
    )

    # Archive raw data to S3 for long-term retention, retraining,
    # and regulatory audit. Time-partitioned key structure enables
    # efficient retrieval by patient and time range.
    ts_parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    s3_key = (
        f"{patient_id}/{waveform_type}/"
        f"{ts_parsed.strftime('%Y-%m-%d')}/"
        f"{ts_parsed.strftime('%H')}/"
        f"{ts_parsed.strftime('%H%M%S')}-{uuid.uuid4().hex[:8]}.json"
    )

    s3c.put_object(
        Bucket=S3_ARCHIVE_BUCKET,
        Key=s3_key,
        Body=json.dumps(record).encode("utf-8"),
    )

    logger.info(
        "Ingested %d samples for %s/%s at %s",
        len(samples), patient_id, waveform_type, timestamp,
    )
    return record
```

---

## Step 2: Preprocessing and Quality Control

Raw waveform data is noisy. This step applies bandpass filtering, notch filtering, computes a signal quality index, and rejects segments below the quality threshold. Segments that pass are segmented into fixed-length analysis windows for the classifier.

```python
# ─────────────────────────────────────────────────────────────────────
# STEP 2: Preprocess waveforms and gate on signal quality.
# Maps to pseudocode Step 2 in the main recipe.
# In production, this runs on ECS/Fargate containers consuming
# from Kinesis, not Lambda (cold starts are unacceptable for
# real-time waveform processing at 250 Hz).
# ─────────────────────────────────────────────────────────────────────

def apply_bandpass_filter(samples, low_hz, high_hz, sample_rate):
    """
    Simplified bandpass filter using a moving-average approximation.

    Production replacement: scipy.signal.butter + scipy.signal.filtfilt
    with a 4th-order Butterworth filter. The scipy version provides
    proper frequency-domain characteristics and zero-phase distortion.
    This demo approximation removes DC offset and very high frequency
    noise but does not have sharp cutoff characteristics.
    """
    # Remove DC offset (approximates high-pass at ~low_hz).
    # A real high-pass at 0.5 Hz with 250 Hz sampling needs a
    # filter with ~500-sample kernel. We approximate with a
    # simple mean subtraction per window.
    mean_val = statistics.mean(samples)
    centered = [s - mean_val for s in samples]

    # Simple moving average for low-pass (approximates low_hz cutoff).
    # Window size inversely proportional to cutoff frequency.
    window_size = max(1, int(sample_rate / high_hz))
    if window_size >= len(centered):
        return centered

    smoothed = []
    for i in range(len(centered)):
        start = max(0, i - window_size // 2)
        end = min(len(centered), i + window_size // 2 + 1)
        smoothed.append(statistics.mean(centered[start:end]))

    return smoothed


def apply_notch_filter(samples, notch_freq, sample_rate):
    """
    Simplified notch filter that attenuates a specific frequency.

    Production replacement: scipy.signal.iirnotch + filtfilt.
    The real version removes 60 Hz (or 50 Hz) powerline interference
    with a narrow stopband that preserves surrounding frequencies.
    This demo just subtracts an estimated sinusoidal component.
    """
    # Estimate and subtract the powerline component.
    # In practice, adaptive notch filters track the exact frequency
    # (which drifts slightly from nominal 60 Hz).
    n = len(samples)
    if n == 0:
        return samples

    # Estimate amplitude of the notch frequency component via
    # a simple correlation with a reference sinusoid.
    ref_sin = [math.sin(2 * math.pi * notch_freq * i / sample_rate)
               for i in range(n)]
    ref_cos = [math.cos(2 * math.pi * notch_freq * i / sample_rate)
               for i in range(n)]

    sin_corr = sum(s * r for s, r in zip(samples, ref_sin)) / n
    cos_corr = sum(s * r for s, r in zip(samples, ref_cos)) / n

    # Subtract the estimated interference.
    filtered = [
        samples[i] - 2 * (sin_corr * ref_sin[i] + cos_corr * ref_cos[i])
        for i in range(n)
    ]
    return filtered


def compute_signal_quality_index(samples, waveform_type, sample_rate):
    """
    Compute a 0-1 signal quality index combining multiple metrics.

    Production replacement: a multi-metric SQI that includes
    template-matching correlation (bSQI), spectral distribution
    analysis (pSQI), kurtosis (kSQI), and a learned artifact
    classifier trained on annotated ICU waveform segments.
    """
    if not samples or len(samples) < sample_rate:
        return 0.0

    # Metric 1: Amplitude range check.
    # Physiological ECG is typically +/- 2 mV (ADC units vary).
    # Signals outside physiological bounds indicate saturation or
    # electrode issues.
    amp_range = max(samples) - min(samples)
    if waveform_type == "ecg_lead_ii":
        # Expect amplitude range between 0.5 and 5.0 mV-equivalent
        amp_score = 1.0 if 0.3 < amp_range < 6.0 else 0.3
    else:
        amp_score = 1.0 if amp_range > 0.01 else 0.2

    # Metric 2: Flatline detection.
    # If the signal variance is near zero, the electrode is likely off.
    variance = statistics.variance(samples) if len(samples) > 1 else 0
    flatline_score = 0.1 if variance < 0.001 else 1.0

    # Metric 3: High-frequency noise power.
    # Excessive high-frequency content indicates EMG contamination
    # or electrical interference that the filters did not remove.
    # Approximate by looking at sample-to-sample differences.
    diffs = [abs(samples[i] - samples[i - 1])
             for i in range(1, len(samples))]
    mean_diff = statistics.mean(diffs) if diffs else 0
    # Normalize against expected physiological rate of change.
    noise_score = max(0.0, 1.0 - (mean_diff / 2.0))

    # Metric 4: Saturation detection.
    # Count samples at the extreme values (ADC clipping).
    if amp_range > 0:
        max_val = max(samples)
        min_val = min(samples)
        sat_count = sum(1 for s in samples
                        if abs(s - max_val) < 0.01 or abs(s - min_val) < 0.01)
        sat_ratio = sat_count / len(samples)
        sat_score = max(0.0, 1.0 - (sat_ratio * 10))
    else:
        sat_score = 0.1

    # Combine metrics with equal weighting.
    # Production systems learn optimal weights from annotated data.
    sqi = (amp_score + flatline_score + noise_score + sat_score) / 4.0
    return round(min(1.0, max(0.0, sqi)), 3)


def segment_into_windows(samples, window_size, overlap):
    """
    Split a sample array into fixed-length overlapping windows.

    Parameters
    ----------
    samples : list[float]
        Filtered waveform samples.
    window_size : int
        Number of samples per window.
    overlap : float
        Fraction of overlap between consecutive windows (0.0 to 0.9).
    """
    step = int(window_size * (1.0 - overlap))
    if step < 1:
        step = 1

    windows = []
    for start in range(0, len(samples) - window_size + 1, step):
        windows.append(samples[start:start + window_size])
    return windows


def preprocess_waveform(raw_record):
    """
    Full preprocessing pipeline: filter, score quality, segment.

    Returns None if the segment fails the quality gate.
    Returns a dict with clean windows and metadata if it passes.
    """
    waveform_type = raw_record["waveform_type"]
    config = WAVEFORM_CONFIG[waveform_type]
    samples = raw_record["values"]
    sample_rate = config["sample_rate"]

    # Step 2a: Bandpass filter.
    filtered = apply_bandpass_filter(
        samples, config["bandpass_low"], config["bandpass_high"], sample_rate)

    # Step 2b: Notch filter for powerline interference.
    filtered = apply_notch_filter(filtered, config["notch_freq"], sample_rate)

    # Step 2c: Signal quality index.
    sqi = compute_signal_quality_index(filtered, waveform_type, sample_rate)

    # Step 2d: Quality gate.
    if sqi < config["quality_threshold"]:
        logger.info(
            "Quality rejection: patient=%s type=%s sqi=%.3f (threshold=%.2f)",
            raw_record["patient_id"], waveform_type, sqi,
            config["quality_threshold"],
        )
        return None

    # Step 2e: Segment into analysis windows.
    window_samples = int(config["window_seconds"] * sample_rate)
    windows = segment_into_windows(
        filtered, window_samples, config["window_overlap"])

    if not windows:
        return None

    return {
        "patient_id": raw_record["patient_id"],
        "waveform_type": waveform_type,
        "timestamp": raw_record["timestamp"],
        "windows": windows,
        "sqi_score": sqi,
        "sample_rate": sample_rate,
    }
```

---

## Step 3: Model Inference

Clean waveform windows are sent to the SageMaker endpoint for classification. The model returns a rhythm label and confidence score for each window. In production, this is a trained deep learning model (CNN or transformer). The demo uses a mock classifier that simulates realistic output patterns.

```python
# ─────────────────────────────────────────────────────────────────────
# STEP 3: Classify waveform windows via SageMaker endpoint.
# Maps to pseudocode Step 3 in the main recipe.
# In production, the endpoint hosts a trained 1D CNN or transformer
# model on a GPU instance (ml.g4dn.xlarge). Inference latency
# target: < 150 ms per window for real-time monitoring.
# ─────────────────────────────────────────────────────────────────────

def classify_waveform_windows(preprocessed, classifier=None):
    """
    Send each analysis window to the classification model.

    Parameters
    ----------
    preprocessed : dict
        Output from preprocess_waveform() with clean windows.
    classifier : callable, optional
        Mock classifier for demo. Production uses sagemaker_runtime.

    Returns list of per-window classification results.
    """
    results = []

    for idx, window in enumerate(preprocessed["windows"]):
        # In production, invoke the SageMaker endpoint:
        #
        # response = sagemaker_runtime.invoke_endpoint(
        #     EndpointName=SAGEMAKER_ENDPOINT,
        #     ContentType="application/json",
        #     Body=json.dumps({
        #         "waveform_type": preprocessed["waveform_type"],
        #         "sample_rate": preprocessed["sample_rate"],
        #         "values": window,
        #         "signal_quality": preprocessed["sqi_score"],
        #     }),
        # )
        # prediction = json.loads(response["Body"].read())

        # Demo: use mock classifier.
        if classifier:
            prediction = classifier(window, preprocessed["waveform_type"])
        else:
            # Fallback: everything is normal sinus rhythm.
            prediction = {
                "classification": "normal_sinus_rhythm",
                "confidence": 0.95,
            }

        # Compute the timestamp for this specific window.
        # Each window starts at an offset from the batch timestamp.
        config = WAVEFORM_CONFIG[preprocessed["waveform_type"]]
        step_seconds = config["window_seconds"] * (1.0 - config["window_overlap"])
        window_offset = timedelta(seconds=idx * step_seconds)
        base_ts = datetime.fromisoformat(
            preprocessed["timestamp"].replace("Z", "+00:00"))
        window_ts = (base_ts + window_offset).isoformat()

        results.append({
            "window_index": idx,
            "classification": prediction["classification"],
            "confidence": prediction["confidence"],
            "window_timestamp": window_ts,
            "signal_quality": preprocessed["sqi_score"],
        })

    return {
        "patient_id": preprocessed["patient_id"],
        "waveform_type": preprocessed["waveform_type"],
        "results": results,
    }
```

---

## Step 4: Post-Processing and Alert Logic

Raw model outputs are not clinical alerts. This step applies persistence thresholds (multiple consecutive windows must agree), checks patient context (known conditions are suppressed), enforces cooldown periods, and routes actionable alerts to SNS.

```python
# ─────────────────────────────────────────────────────────────────────
# STEP 4: Apply clinical alert logic with suppression rules.
# Maps to pseudocode Step 4 in the main recipe.
# This is where you control your false alarm rate. Get this wrong
# and clinicians will disable your system within a week.
# ─────────────────────────────────────────────────────────────────────

# In-memory state for the demo. Production uses DynamoDB or Redis
# for cross-invocation state persistence.
_alert_cooldowns = {}       # {(patient_id, classification): expiry_datetime}
_detection_history = defaultdict(list)  # {patient_id: [recent classifications]}


def load_patient_context(patient_id):
    """
    Load patient-specific context for alert suppression.

    Production replacement: query the EHR (via FHIR API or HL7 ADT
    feed) for active diagnoses, pacemaker status, medication list,
    and care team preferences. A patient with documented chronic
    atrial fibrillation should not receive repeated AFib alerts.
    """
    # Demo: hardcoded patient contexts for illustration.
    known_contexts = {
        "ICU-BED-07": {
            "known_conditions": [],  # no known arrhythmias
            "has_pacemaker": False,
        },
        "ICU-BED-12": {
            "known_conditions": ["atrial_fibrillation"],  # chronic AFib
            "has_pacemaker": True,
        },
    }
    return known_contexts.get(
        patient_id,
        {"known_conditions": [], "has_pacemaker": False},
    )


def is_in_cooldown(patient_id, classification):
    """Check if this patient/condition pair is in cooldown."""
    key = (patient_id, classification)
    if key in _alert_cooldowns:
        if datetime.now(timezone.utc) < _alert_cooldowns[key]:
            return True
        else:
            del _alert_cooldowns[key]
    return False


def set_cooldown(patient_id, classification):
    """Set cooldown after generating an alert."""
    minutes = COOLDOWN_MINUTES.get(classification, 15)
    key = (patient_id, classification)
    _alert_cooldowns[key] = (
        datetime.now(timezone.utc) + timedelta(minutes=minutes))


def count_consecutive(results, classification, min_confidence):
    """
    Count trailing consecutive windows (from most recent backward)
    matching the given classification at or above the confidence
    threshold. We count from the end because the trailing run
    represents the patient's current state; a historical run that
    has since resolved is not actionable.
    """
    count = 0
    for r in reversed(results):
        if (r["classification"] == classification
                and r["confidence"] >= min_confidence):
            count += 1
        else:
            break
    return count


def apply_alert_logic(classification_results, sns=None):
    """
    Apply persistence, suppression, and cooldown rules.

    Returns a list of generated alerts (may be empty).
    """
    patient_id = classification_results["patient_id"]
    results = classification_results["results"]
    context = load_patient_context(patient_id)
    alerts_generated = []

    # Find all unique non-normal classifications in this batch.
    unique_classes = set(
        r["classification"] for r in results
        if r["classification"] != "normal_sinus_rhythm"
    )

    for classification in unique_classes:
        # Count consecutive high-confidence detections.
        consecutive = count_consecutive(
            results, classification, ALERT_CONFIDENCE_THRESHOLD)

        # Check persistence threshold.
        threshold = PERSISTENCE_THRESHOLDS.get(classification, 6)
        if consecutive < threshold:
            continue

        # Check suppression: known conditions.
        if classification in context["known_conditions"]:
            logger.info(
                "Suppressed alert: patient=%s condition=%s reason=known_condition",
                patient_id, classification,
            )
            continue

        # Check cooldown.
        if is_in_cooldown(patient_id, classification):
            logger.info(
                "Suppressed alert: patient=%s condition=%s reason=cooldown",
                patient_id, classification,
            )
            continue

        # Generate alert.
        matching = [r for r in results
                    if r["classification"] == classification
                    and r["confidence"] >= ALERT_CONFIDENCE_THRESHOLD]
        avg_confidence = statistics.mean(r["confidence"] for r in matching)

        alert = {
            "alert_id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "classification": classification,
            "severity": SEVERITY_MAP.get(classification, "MEDIUM"),
            "confidence": round(avg_confidence, 3),
            "consecutive_windows": consecutive,
            "onset_time": matching[0]["window_timestamp"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Publish to SNS.
        sns_client_to_use = sns or sns_client
        sns_client_to_use.publish(
            TopicArn=SNS_ALERT_TOPIC_ARN,
            Message=json.dumps(alert),
            MessageAttributes={
                "severity": {
                    "DataType": "String",
                    "StringValue": alert["severity"],
                },
                "patient_id": {
                    "DataType": "String",
                    "StringValue": patient_id,
                },
                "condition": {
                    "DataType": "String",
                    "StringValue": classification,
                },
            },
        )

        # Set cooldown.
        set_cooldown(patient_id, classification)
        alerts_generated.append(alert)

        logger.info(
            "ALERT generated: patient=%s condition=%s severity=%s confidence=%.3f",
            patient_id, classification, alert["severity"], avg_confidence,
        )

    return alerts_generated
```

---

## Step 5: Store Results

Every classification (alerting and non-alerting) is stored in Timestream for retrospective analysis, model performance monitoring, and clinical research. System-level metrics (quality rejection rates, alert rates, latency) go to a separate metrics table.

```python
# ─────────────────────────────────────────────────────────────────────
# STEP 5: Store all classifications and metrics to Timestream.
# Maps to pseudocode Step 5 in the main recipe.
# Timestream's time-partitioned storage makes "last N hours"
# queries fast for clinical review and operational dashboards.
# ─────────────────────────────────────────────────────────────────────

def store_classifications(classification_results, alerts_generated,
                          timestream=None):
    """
    Write all per-window classifications to Timestream.

    Parameters
    ----------
    classification_results : dict
        Output from classify_waveform_windows().
    alerts_generated : list
        Output from apply_alert_logic().
    timestream : mock or real Timestream write client.
    """
    ts = timestream  # mock for demo

    patient_id = classification_results["patient_id"]
    waveform_type = classification_results["waveform_type"]
    alert_ids = {a["classification"] for a in alerts_generated}

    records = []
    for result in classification_results["results"]:
        records.append({
            "Dimensions": [
                {"Name": "patient_id", "Value": patient_id},
                {"Name": "waveform_type", "Value": waveform_type},
                {"Name": "classification", "Value": result["classification"]},
            ],
            "MeasureName": "classification_metrics",
            "MeasureValueType": "MULTI",
            "MeasureValues": [
                {"Name": "confidence", "Value": str(result["confidence"]),
                 "Type": "DOUBLE"},
                {"Name": "signal_quality", "Value": str(result["signal_quality"]),
                 "Type": "DOUBLE"},
                {"Name": "alerted", "Value": str(
                    1 if result["classification"] in alert_ids else 0),
                 "Type": "BIGINT"},
            ],
            "Time": str(int(
                datetime.fromisoformat(
                    result["window_timestamp"].replace("Z", "+00:00")
                ).timestamp() * 1000)),
            "TimeUnit": "MILLISECONDS",
        })

    # Timestream accepts batches of up to 100 records.
    if ts:
        for i in range(0, len(records), 100):
            batch = records[i:i + 100]
            ts.write_records(
                DatabaseName=TIMESTREAM_DB,
                TableName=TIMESTREAM_TABLE_CLASSIFICATIONS,
                Records=batch,
            )
    else:
        logger.info(
            "Would write %d classification records to Timestream", len(records))

    return len(records)
```

---

## Full Pipeline

Assembles all steps into a single callable function and runs the demo on synthetic ECG data.

```python
# ─────────────────────────────────────────────────────────────────────
# FULL PIPELINE: End-to-end waveform analysis from ingestion to alert.
# ─────────────────────────────────────────────────────────────────────

def run_pipeline(raw_record, classifier=None, sns=None, timestream=None,
                 kinesis=None, s3=None):
    """
    Run the complete waveform analysis pipeline on a single batch.

    Returns a dict summarizing what happened: classifications,
    alerts generated, and records stored.
    """
    print(f"\n{'='*60}")
    print(f"  Processing: {raw_record['patient_id']} / "
          f"{raw_record['waveform_type']}")
    print(f"  Timestamp:  {raw_record['timestamp']}")
    print(f"  Samples:    {len(raw_record['values'])}")
    print(f"{'='*60}")

    # Step 1: Ingest (archive to S3, push to Kinesis).
    ingest_waveform_batch(
        raw_record["patient_id"],
        raw_record["waveform_type"],
        raw_record["timestamp"],
        raw_record["values"],
        kinesis=kinesis,
        s3=s3,
    )
    print("  [Step 1] Ingested and archived.")

    # Step 2: Preprocess.
    preprocessed = preprocess_waveform(raw_record)
    if preprocessed is None:
        print("  [Step 2] REJECTED: signal quality below threshold.")
        return {"status": "rejected", "reason": "quality_gate"}

    print(f"  [Step 2] Preprocessed: SQI={preprocessed['sqi_score']:.3f}, "
          f"windows={len(preprocessed['windows'])}")

    # Step 3: Classify.
    classification_results = classify_waveform_windows(
        preprocessed, classifier=classifier)
    class_summary = defaultdict(int)
    for r in classification_results["results"]:
        class_summary[r["classification"]] += 1
    print(f"  [Step 3] Classified: {dict(class_summary)}")

    # Step 4: Alert logic.
    alerts = apply_alert_logic(classification_results, sns=sns)
    if alerts:
        for a in alerts:
            print(f"  [Step 4] ALERT: {a['classification']} "
                  f"(severity={a['severity']}, confidence={a['confidence']:.3f})")
    else:
        print("  [Step 4] No alerts generated.")

    # Step 5: Store.
    records_stored = store_classifications(
        classification_results, alerts, timestream=timestream)
    print(f"  [Step 5] Stored {records_stored} records.")

    return {
        "status": "processed",
        "sqi": preprocessed["sqi_score"],
        "windows_classified": len(classification_results["results"]),
        "classifications": dict(class_summary),
        "alerts": alerts,
        "records_stored": records_stored,
    }


# ─────────────────────────────────────────────────────────────────────
# MOCK INFRASTRUCTURE AND SYNTHETIC DATA
# ─────────────────────────────────────────────────────────────────────

class MockKinesisStream:
    """Captures put_record calls without a real Kinesis stream."""
    def __init__(self):
        self.records = []

    def put_record(self, **kwargs):
        self.records.append(kwargs)
        return {"ShardId": "shard-0", "SequenceNumber": str(len(self.records))}


class MockS3:
    """Captures put_object calls without a real S3 bucket."""
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]
        return {"ETag": f"\"{uuid.uuid4().hex}\""}


class MockSNS:
    """Captures publish calls without a real SNS topic."""
    def __init__(self):
        self.messages = []

    def publish(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": str(uuid.uuid4())}


class MockTimestream:
    """Captures write_records calls without a real Timestream DB."""
    def __init__(self):
        self.records = []

    def write_records(self, **kwargs):
        self.records.extend(kwargs.get("Records", []))
        return {"RecordsIngested": {"Total": len(kwargs.get("Records", []))}}


def generate_synthetic_ecg(duration_seconds, sample_rate, scenario="normal"):
    """
    Generate synthetic ECG-like waveform data for demonstration.

    This is NOT a physiologically accurate ECG simulator. It produces
    a signal with periodic peaks (simulating QRS complexes) at a
    plausible heart rate, with noise and optional injected abnormalities.
    Real ECG simulators (e.g., ECGSYN from PhysioNet) produce much
    more realistic waveforms.

    Parameters
    ----------
    duration_seconds : int
        Length of the synthetic recording.
    sample_rate : int
        Samples per second.
    scenario : str
        "normal" = regular sinus rhythm
        "pvc" = normal with occasional PVCs
        "afib" = irregular rhythm simulating atrial fibrillation
        "noisy" = normal rhythm with heavy artifact contamination
    """
    n_samples = duration_seconds * sample_rate
    samples = []

    if scenario == "normal":
        # Regular sinus rhythm at ~72 bpm.
        beat_interval = sample_rate * 60 // 72  # samples between beats
        for i in range(n_samples):
            phase = i % beat_interval
            # Simulate QRS complex as a sharp peak.
            if beat_interval * 0.3 < phase < beat_interval * 0.35:
                samples.append(1.5 + random.gauss(0, 0.05))
            elif beat_interval * 0.35 <= phase < beat_interval * 0.38:
                samples.append(-0.3 + random.gauss(0, 0.03))
            else:
                samples.append(random.gauss(0, 0.08))

    elif scenario == "pvc":
        # Normal rhythm with PVCs injected every ~15 beats.
        beat_interval = sample_rate * 60 // 75
        beat_count = 0
        i = 0
        while i < n_samples:
            beat_count += 1
            is_pvc = (beat_count % 15 == 0)
            interval = int(beat_interval * 0.7) if is_pvc else beat_interval

            for j in range(min(interval, n_samples - i)):
                phase = j / interval
                if is_pvc:
                    # PVC: wider, taller, different morphology.
                    if 0.2 < phase < 0.35:
                        samples.append(2.5 + random.gauss(0, 0.1))
                    elif 0.35 <= phase < 0.5:
                        samples.append(-1.0 + random.gauss(0, 0.1))
                    else:
                        samples.append(random.gauss(0, 0.1))
                else:
                    if 0.3 < phase < 0.35:
                        samples.append(1.5 + random.gauss(0, 0.05))
                    elif 0.35 <= phase < 0.38:
                        samples.append(-0.3 + random.gauss(0, 0.03))
                    else:
                        samples.append(random.gauss(0, 0.08))
                i += 1

    elif scenario == "afib":
        # Irregular rhythm: variable R-R intervals, no clear P waves.
        i = 0
        while i < n_samples:
            # AFib: irregular beat intervals (60-120 bpm equivalent).
            beat_interval = int(sample_rate * random.uniform(0.5, 1.0))
            for j in range(min(beat_interval, n_samples - i)):
                phase = j / beat_interval
                if 0.28 < phase < 0.34:
                    samples.append(1.2 + random.gauss(0, 0.15))
                elif 0.34 <= phase < 0.38:
                    samples.append(-0.2 + random.gauss(0, 0.1))
                else:
                    # Fibrillatory baseline: more noise than sinus.
                    samples.append(random.gauss(0, 0.15))
                i += 1

    elif scenario == "noisy":
        # Normal rhythm buried in heavy artifact.
        beat_interval = sample_rate * 60 // 72
        for i in range(n_samples):
            phase = i % beat_interval
            if beat_interval * 0.3 < phase < beat_interval * 0.35:
                samples.append(1.5 + random.gauss(0, 0.5))
            else:
                # Heavy noise: simulates motion artifact.
                samples.append(random.gauss(0, 0.8))

    else:
        samples = [random.gauss(0, 0.1) for _ in range(n_samples)]

    return samples


def mock_ecg_classifier(window, waveform_type):
    """
    Mock classifier that returns plausible classifications based
    on simple signal statistics. NOT a real arrhythmia detector.

    Production replacement: a trained 1D CNN or transformer model
    hosted on SageMaker, validated against annotated datasets
    (MIT-BIH, MIMIC-III waveform), and cleared through the
    appropriate FDA pathway.
    """
    if not window:
        return {"classification": "normal_sinus_rhythm", "confidence": 0.5}

    # Use simple heuristics to simulate model behavior.
    max_val = max(window)
    min_val = min(window)
    amp_range = max_val - min_val
    variance = statistics.variance(window) if len(window) > 1 else 0

    # High amplitude peaks suggest PVCs.
    if max_val > 2.0:
        return {
            "classification": "premature_ventricular_complex",
            "confidence": min(0.95, 0.6 + max_val * 0.1),
        }

    # High variance with moderate amplitude suggests AFib.
    if variance > 0.05 and amp_range < 2.0:
        return {
            "classification": "atrial_fibrillation",
            "confidence": min(0.92, 0.5 + variance * 3),
        }

    # Very low variance suggests flatline/artifact.
    if variance < 0.001:
        return {"classification": "normal_sinus_rhythm", "confidence": 0.3}

    # Default: normal sinus rhythm.
    return {
        "classification": "normal_sinus_rhythm",
        "confidence": 0.90 + random.uniform(0, 0.08),
    }


# ─────────────────────────────────────────────────────────────────────
# DEMO EXECUTION
# ─────────────────────────────────────────────────────────────────────

def run_demo():
    """
    Run the full pipeline on synthetic ECG data demonstrating:
    1. Normal sinus rhythm (no alerts)
    2. ECG with PVCs (below persistence threshold, no alert)
    3. Sustained atrial fibrillation (triggers alert)
    4. Noisy/artifact-heavy signal (quality rejection)
    """
    print("\n" + "=" * 60)
    print("  PHYSIOLOGICAL WAVEFORM ANALYSIS PIPELINE DEMO")
    print("=" * 60)

    # Set up mocks.
    mock_kinesis = MockKinesisStream()
    mock_s3 = MockS3()
    mock_sns = MockSNS()
    mock_ts = MockTimestream()

    sample_rate = WAVEFORM_CONFIG["ecg_lead_ii"]["sample_rate"]
    base_time = datetime(2026, 3, 1, 14, 22, 0, tzinfo=timezone.utc)

    scenarios = [
        ("normal", 30, "Normal sinus rhythm (expect: no alerts)"),
        ("pvc", 30, "Occasional PVCs (expect: below persistence, no alert)"),
        ("afib", 60, "Sustained atrial fibrillation (expect: ALERT)"),
        ("noisy", 20, "Heavy artifact (expect: quality rejection)"),
    ]

    all_results = []
    for scenario, duration, description in scenarios:
        print(f"\n{'─'*60}")
        print(f"  Scenario: {description}")
        print(f"{'─'*60}")

        samples = generate_synthetic_ecg(duration, sample_rate, scenario)
        timestamp = (base_time + timedelta(
            minutes=len(all_results) * 2)).isoformat()

        raw_record = {
            "patient_id": "ICU-BED-07",
            "waveform_type": "ecg_lead_ii",
            "timestamp": timestamp,
            "sample_rate": sample_rate,
            "values": samples,
        }

        result = run_pipeline(
            raw_record,
            classifier=mock_ecg_classifier,
            sns=mock_sns,
            timestream=mock_ts,
            kinesis=mock_kinesis,
            s3=mock_s3,
        )
        all_results.append(result)

    # Summary.
    print(f"\n{'='*60}")
    print("  DEMO SUMMARY")
    print(f"{'='*60}")
    print(f"  Kinesis records ingested: {len(mock_kinesis.records)}")
    print(f"  S3 objects archived:      {len(mock_s3.objects)}")
    print(f"  Timestream records:       {len(mock_ts.records)}")
    print(f"  SNS alerts published:     {len(mock_sns.messages)}")
    print()

    for i, (scenario, _, desc) in enumerate(scenarios):
        r = all_results[i]
        status = r.get("status", "unknown")
        if status == "rejected":
            print(f"  [{scenario}] REJECTED (quality gate)")
        else:
            alerts = r.get("alerts", [])
            if alerts:
                for a in alerts:
                    print(f"  [{scenario}] ALERT: {a['classification']} "
                          f"(severity={a['severity']})")
            else:
                print(f"  [{scenario}] No alerts. "
                      f"Classifications: {r.get('classifications', {})}")

    print(f"\n{'='*60}")
    print("  Pipeline demo complete.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_demo()
```

---

## Gap to Production

The distance between this demo and something you would deploy in a real ICU is substantial. Here is what you would need to add:

**Signal processing.** Replace the demo's moving-average filter approximation with proper scipy.signal Butterworth or FIR filters designed for the specific waveform type. Use scipy.signal.filtfilt for zero-phase filtering (critical for preserving waveform morphology). Implement adaptive notch filtering that tracks the actual powerline frequency. Add proper resampling for devices that report at non-standard rates.

**Signal quality.** Replace the demo's four-metric SQI with a comprehensive quality assessment: template-matching SQI (bSQI) that correlates each beat against a learned template, spectral SQI (pSQI) that checks the power distribution is physiologically plausible, kurtosis SQI (kSQI) for detecting non-Gaussian artifact, and a trained artifact classifier (random forest or small CNN) that learns from annotated ICU waveform segments. Multi-lead cross-validation: if one ECG lead shows VT but the other four look normal, it is probably artifact on that lead.

**Classification model.** Replace the mock classifier with a trained deep learning model. For ECG rhythm classification, architectures like the 34-layer residual CNN from Hannun et al. (2019) or transformer-based models achieve cardiologist-level performance on curated datasets. Train on annotated datasets (MIT-BIH, MIMIC-III waveform, institutional data). Validate on held-out data from your target population. Address domain shift between training data and your specific monitors, patient population, and electrode placement practices.

**Device integration.** Build or procure a device integration engine that speaks HL7v2 (for older monitors), IEEE 11073 (for newer ones), or proprietary protocols (GE, Philips, Draeger each have their own). Handle device clock synchronization, reconnection after network drops, and the reality that some monitors buffer internally and dump data in bursts rather than streaming continuously.

**Error handling and retries.** Add exponential backoff with jitter for all AWS API calls. Implement dead-letter queues for records that fail processing. Handle Kinesis iterator expiration (resharding, throughput exceeded). Handle SageMaker endpoint throttling under load. Implement circuit breakers that degrade gracefully (stop classifying but keep archiving) when downstream services are unavailable.

**Input validation.** Validate sample rates match expected values. Validate amplitude ranges are physiologically plausible before processing. Validate timestamps are monotonically increasing within a patient stream. Reject records with missing or malformed fields before they reach the preprocessing step.

**Structured logging.** Replace print statements with JSON-structured logging to CloudWatch Logs. Include correlation IDs that trace a waveform batch from ingestion through classification to alert. Never log raw waveform values (PHI). Log only structural metadata: patient_id (hashed in logs), window_count, sqi_score, classification_label, confidence, alert_generated, latency_ms.

**IAM least privilege.** The demo uses a single set of credentials. Production separates: the ingestion service has Kinesis write and S3 write only; the preprocessing service has Kinesis read and Timestream write only; the classification service has SageMaker invoke only; the alert service has SNS publish and Timestream write only. Each service runs with its own IAM role scoped to specific resource ARNs.

**VPC and VPC endpoints.** All compute runs inside a VPC. Interface VPC endpoints for Kinesis, SageMaker, Timestream, SNS, S3, and CloudWatch Logs eliminate internet-bound traffic. The device integration engine connects via Direct Connect or site-to-site VPN from the hospital network.

**KMS customer-managed keys.** Separate CMKs per data classification: one for raw waveform archives, one for classification results, one for alert payloads. Key policies restrict which services can encrypt/decrypt. Automatic key rotation enabled.

**Testing.** Unit tests for each processing step with known-good and known-bad waveform segments. Integration tests against real boto3 with localstack or moto. Performance tests confirming end-to-end latency stays under 5 seconds at target throughput. Regression tests against annotated waveform databases (MIT-BIH) to catch model degradation.

**FDA regulatory pathway.** If the system makes diagnostic claims (e.g., "this patient has atrial fibrillation"), it requires FDA clearance as a Software as a Medical Device (SaMD). The 510(k) pathway requires identifying a predicate device, demonstrating substantial equivalence, and submitting clinical validation data. The De Novo pathway applies for novel intended uses without predicates. Either pathway requires a Quality Management System (QMS), design controls, risk management (ISO 14971), and post-market surveillance. Get regulatory counsel involved before you write the first line of production code.

**Model monitoring and retraining.** Track classification accuracy against clinician-adjudicated outcomes. Monitor for distribution drift (new patient populations, new monitor hardware, seasonal changes in artifact patterns). Implement a retraining pipeline that incorporates newly annotated data. Any model update in an FDA-cleared system requires a change-control process and potentially a new submission.

**Alert fatigue management.** Track alert-to-action ratios per clinician. If nurses are dismissing 90% of alerts without action, your thresholds are wrong. Implement feedback loops where clinicians can mark alerts as true positive, false positive, or clinically insignificant. Use this feedback to continuously tune persistence thresholds and suppression rules.

---

## Navigation

← [Recipe 12.9: Epidemic Forecasting](chapter12.09-epidemic-forecasting) | [Chapter 12 Index](chapter12-preface) | [Chapter 13: Knowledge Graphs](chapter13-preface) →
