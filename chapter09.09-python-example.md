# Recipe 9.9: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 9.9. Real surgical video analysis involves multi-day GPU training runs, transformer architectures processing thousands of frames, and months of expert annotation. This example demonstrates the *shape* of the pipeline using synthetic data and simulated model outputs. It shows how you'd orchestrate the AWS pieces (S3, MediaConvert, SageMaker, DynamoDB, OpenSearch) with boto3. Think of it as a map of the territory, not the territory itself. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few numerical libraries:

```bash
pip install boto3 numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject`, `s3:PutObject` (video and frame storage)
- `mediaconvert:CreateJob`, `mediaconvert:GetJob` (frame extraction)
- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` (model inference)
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` (procedure index)
- `es:ESHttpPost`, `es:ESHttpGet` (OpenSearch indexing and search)
- `states:StartExecution` (pipeline orchestration)

---

## Config and Constants

These go at the top of your module. They define the frame sampling parameters, model configuration, phase definitions, and AWS resource names. In production, most of these would come from environment variables or SSM Parameter Store.

```python
# Frame sampling configuration.
# 1 fps is standard for phase recognition. Phase transitions happen over seconds,
# not milliseconds, so higher rates just burn GPU time without improving accuracy.
# For instrument detection, you'd bump this to 5 fps.
SAMPLE_RATE_FPS = 1

# Model input resolution.
# Most surgical video models expect 224x224 or 384x384.
# Higher resolution captures more detail but costs more GPU memory per frame.
MODEL_INPUT_SIZE = (224, 224)

# Feature extraction output dimension.
# ResNet-50 backbone produces 2048-dimensional feature vectors.
# These get fed into the temporal model.
FEATURE_DIM = 2048

# Batch size for GPU inference.
# How many frames to process in one forward pass.
# Depends on GPU memory; 32 is safe for most g5 instances.
BATCH_SIZE = 32

# Phase definitions for laparoscopic cholecystectomy.
# These are the surgical phases the temporal model predicts.
# Other procedure types would have different phase sets.
CHOLECYSTECTOMY_PHASES = [
    "port_placement",
    "initial_dissection",
    "calot_triangle_dissection",
    "clipping_and_cutting",
    "gallbladder_separation",
    "extraction_and_inspection",
]

# Instrument classes the model can detect.
# Multi-label: multiple instruments can be present simultaneously.
INSTRUMENT_CLASSES = [
    "grasper",
    "hook_cautery",
    "scissors",
    "clip_applier",
    "irrigator",
    "specimen_bag",
]

# Event types the model flags.
EVENT_TYPES = [
    "bleeding_minor",
    "bleeding_major",
    "clip_placement",
    "specimen_extraction",
    "conversion_to_open",
]

# Post-processing parameters.
# Minimum phase duration in seconds. No surgical phase lasts less than 30 seconds.
MIN_PHASE_DURATION_SEC = 30
# Median filter window for phase smoothing (in frames at SAMPLE_RATE_FPS).
PHASE_SMOOTH_WINDOW = 15
# Gap fill for instrument detection: brief disappearances shorter than this
# are likely occlusion, not actual instrument removal.
INSTRUMENT_GAP_FILL_SEC = 3

# Confidence thresholds.
# Below these, predictions are marked low-confidence in the output.
PHASE_CONFIDENCE_THRESHOLD = 0.70
EVENT_CONFIDENCE_THRESHOLD = 0.50

# AWS resource names. In production, pull these from environment variables.
RAW_VIDEO_BUCKET = "surgical-video-raw"
FRAMES_BUCKET = "surgical-frames"
FEATURES_BUCKET = "surgical-features"
PROCEDURE_INDEX_TABLE = "procedure-index"
PROCEDURE_REGISTRY_TABLE = "procedure-registry"
OPENSEARCH_DOMAIN = "https://vpc-surgical-search-xxxxx.us-east-1.es.amazonaws.com"
SAGEMAKER_FEATURE_MODEL = "surgical-feature-extractor"
SAGEMAKER_TEMPORAL_MODEL = "surgical-temporal-model"
MEDIACONVERT_ROLE_ARN = "arn:aws:iam::123456789012:role/MediaConvertRole"
MEDIACONVERT_QUEUE_ARN = "arn:aws:mediaconvert:us-east-1:123456789012:queues/Default"
```

---

## Step 1: Video Ingestion and Metadata Registration

*Maps to pseudocode Step 1: `ingest_video(video_file, metadata)`. When a surgical video arrives from the OR recording system, this function uploads it to encrypted S3 storage, registers it in the procedure tracking table, and returns the procedure ID that links everything together downstream.*

```python
import json
import uuid
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry configuration. Surgical video processing involves long-running jobs
# and large file transfers. Adaptive retry handles throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
mediaconvert_client = boto3.client("mediaconvert", config=BOTO3_RETRY_CONFIG)
stepfunctions_client = boto3.client("stepfunctions", config=BOTO3_RETRY_CONFIG)


def ingest_video(video_s3_key: str, metadata: dict) -> str:
    """
    Register a surgical video that has landed in S3 and trigger the analysis pipeline.

    In practice, the video is uploaded by the OR recording system (or a transfer
    agent) before this function runs. This function handles the metadata registration
    and pipeline trigger, not the upload itself.

    Args:
        video_s3_key: S3 key where the video already exists in RAW_VIDEO_BUCKET.
                      Example: "uploads/2026-05-15/OR3-case-morning.mp4"
        metadata: Dict with procedure_type, surgeon_id, procedure_date,
                  duration_seconds.

    Returns:
        procedure_id: Unique identifier linking all downstream artifacts.
    """
    procedure_id = f"proc-{uuid.uuid4().hex[:12]}"

    # Register in the procedure tracking table.
    # Status progresses: ingested -> extracting_frames -> analyzing -> complete (or failed).
    registry_table = dynamodb.Table(PROCEDURE_REGISTRY_TABLE)
    registry_table.put_item(Item={
        "procedure_id": procedure_id,
        "status": "ingested",
        "procedure_type": metadata["procedure_type"],
        "surgeon_id": metadata["surgeon_id"],
        "procedure_date": metadata["procedure_date"],
        "video_duration_seconds": Decimal(str(metadata["duration_seconds"])),
        "video_s3_key": video_s3_key,
        "ingested_at": datetime.datetime.now(timezone.utc).isoformat(),
    })

    logger.info(
        "Registered procedure %s: %s, %d seconds",
        procedure_id,
        metadata["procedure_type"],
        metadata["duration_seconds"],
    )

    return procedure_id
```

---

## Step 2: Frame Extraction with MediaConvert

*Maps to pseudocode Step 2: `extract_frames(procedure_id, video_key, sample_rate_fps)`. This step uses AWS Elemental MediaConvert to extract frames at the target sample rate. MediaConvert handles the variety of video formats and codecs that different OR recording systems produce, so you don't have to run FFmpeg on EC2.*

```python
def create_frame_extraction_job(procedure_id: str, video_s3_key: str) -> str:
    """
    Submit a MediaConvert job to extract frames from the surgical video.

    MediaConvert transcodes the video and outputs individual JPEG frames
    at the configured sample rate. This handles format normalization
    (different OR systems use different codecs) and frame rate conversion
    in a single managed operation.

    Args:
        procedure_id: Links this job to the procedure record.
        video_s3_key: S3 key of the raw video in RAW_VIDEO_BUCKET.

    Returns:
        job_id: MediaConvert job ID for status polling.
    """
    output_prefix = f"s3://{FRAMES_BUCKET}/{procedure_id}/frames/"

    # MediaConvert job settings for frame extraction.
    # The key trick: set the output frame rate to our sample rate (1 fps)
    # and output as individual JPEG files. MediaConvert handles the decimation.
    job_settings = {
        "Inputs": [{
            "FileInput": f"s3://{RAW_VIDEO_BUCKET}/{video_s3_key}",
            "VideoSelector": {},
            "AudioSelector": {"DefaultSelection": "DEFAULT"},
        }],
        "OutputGroups": [{
            "Name": "FrameExtraction",
            "OutputGroupSettings": {
                "Type": "FILE_GROUP_SETTINGS",
                "FileGroupSettings": {
                    "Destination": output_prefix,
                },
            },
            "Outputs": [{
                "VideoDescription": {
                    "Width": MODEL_INPUT_SIZE[0],
                    "Height": MODEL_INPUT_SIZE[1],
                    "CodecSettings": {
                        "Codec": "FRAME_CAPTURE",
                        "FrameCaptureSettings": {
                            "FramerateNumerator": SAMPLE_RATE_FPS,
                            "FramerateDenominator": 1,
                            "Quality": 80,
                        },
                    },
                },
                "ContainerSettings": {
                    "Container": "RAW",
                },
            }],
        }],
    }

    response = mediaconvert_client.create_job(
        Role=MEDIACONVERT_ROLE_ARN,
        Queue=MEDIACONVERT_QUEUE_ARN,
        Settings=job_settings,
        Tags={"procedure_id": procedure_id},
    )

    job_id = response["Job"]["Id"]
    logger.info("Created MediaConvert job %s for procedure %s", job_id, procedure_id)

    return job_id


def filter_valid_frames(procedure_id: str) -> list:
    """
    After frame extraction, filter out non-informative frames.

    Black frames (camera disconnected), completely white frames (lens fogging),
    and uniform-color frames (light source off) are useless for analysis.
    We detect these by checking pixel statistics.

    In this simplified version, we simulate the filtering logic since we don't
    have actual frame pixel data. In production, you'd load each JPEG from S3,
    compute mean/std of pixel values, and discard frames that fail the checks.

    Args:
        procedure_id: Identifies which frames to filter.

    Returns:
        List of valid frame S3 keys.
    """
    # List all extracted frames for this procedure.
    paginator = s3_client.get_paginator("list_objects_v2")
    frame_keys = []

    for page in paginator.paginate(
        Bucket=FRAMES_BUCKET,
        Prefix=f"{procedure_id}/frames/",
    ):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".jpg") or obj["Key"].endswith(".jpeg"):
                frame_keys.append(obj["Key"])

    frame_keys.sort()  # ensure temporal order

    # In production, you'd download each frame (or a sample) and check:
    #   mean_pixel < 10  -> black frame, skip
    #   std_pixel < 5    -> uniform frame (fog/cap), skip
    # For this example, we assume all frames pass (real filtering would
    # typically remove 2-5% of frames from a typical procedure).
    valid_frames = frame_keys

    logger.info(
        "Procedure %s: %d total frames, %d valid after filtering",
        procedure_id,
        len(frame_keys),
        len(valid_frames),
    )

    # Write the manifest so downstream steps know which frames to process.
    manifest = {"procedure_id": procedure_id, "valid_frames": valid_frames}
    s3_client.put_object(
        Bucket=FRAMES_BUCKET,
        Key=f"{procedure_id}/manifest.json",
        Body=json.dumps(manifest),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    return valid_frames
```

---

## Step 3: Feature Extraction via SageMaker Batch Transform

*Maps to pseudocode Step 3: `extract_features(procedure_id, frame_manifest)`. Each valid frame passes through a CNN backbone (ResNet-50 fine-tuned on surgical video) to produce a compact feature vector. SageMaker Batch Transform handles this at scale without you managing GPU instances directly.*

```python
import time


def launch_feature_extraction(procedure_id: str, valid_frames: list) -> str:
    """
    Launch a SageMaker Batch Transform job to extract features from all frames.

    The feature extraction model is a ResNet-50 backbone (pretrained on ImageNet,
    fine-tuned on surgical video) with the final classification layer removed.
    It takes a 224x224 image and outputs a 2048-dimensional feature vector.

    Batch Transform processes all frames in parallel across the instance(s),
    writing feature vectors back to S3.

    Args:
        procedure_id: Links this job to the procedure.
        valid_frames: List of S3 keys for frames to process.

    Returns:
        transform_job_name: For polling job status.
    """
    sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)

    transform_job_name = f"feat-{procedure_id}"

    # The input is the frames prefix in S3.
    # Batch Transform will process every object under this prefix.
    input_prefix = f"s3://{FRAMES_BUCKET}/{procedure_id}/frames/"
    output_prefix = f"s3://{FEATURES_BUCKET}/{procedure_id}/"

    sagemaker_client.create_transform_job(
        TransformJobName=transform_job_name,
        ModelName=SAGEMAKER_FEATURE_MODEL,
        TransformInput={
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": input_prefix,
                },
            },
            "ContentType": "application/x-image",
            "SplitType": "None",  # each file is one input
        },
        TransformOutput={
            "S3OutputPath": output_prefix,
            "AssembleWith": "None",
        },
        TransformResources={
            "InstanceType": "ml.g5.xlarge",  # GPU instance for CNN inference
            "InstanceCount": 1,
        },
        MaxPayloadInMB=6,  # each frame is well under 6 MB
        BatchStrategy="SingleRecord",
        Tags=[{"Key": "procedure_id", "Value": procedure_id}],
    )

    logger.info(
        "Launched feature extraction job %s for %d frames",
        transform_job_name,
        len(valid_frames),
    )

    return transform_job_name


def wait_for_transform_job(job_name: str, poll_interval: int = 30) -> str:
    """
    Poll a SageMaker Batch Transform job until it completes or fails.

    Args:
        job_name: The transform job name.
        poll_interval: Seconds between status checks.

    Returns:
        Final job status: "Completed" or "Failed".
    """
    sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)

    while True:
        response = sagemaker_client.describe_transform_job(
            TransformJobName=job_name
        )
        status = response["TransformJobStatus"]

        if status in ("Completed", "Failed", "Stopped"):
            logger.info("Transform job %s finished with status: %s", job_name, status)
            return status

        logger.info("Transform job %s status: %s, waiting...", job_name, status)
        time.sleep(poll_interval)
```

---

## Step 4: Temporal Modeling and Multi-Task Prediction

*Maps to pseudocode Step 4: `temporal_prediction(procedure_id, features)`. This is where the system reasons across time. The sequence of frame features passes through a temporal model (transformer or TCN) that considers the full procedure context to predict phase, instruments, and events at each time point.*

In production, this would be another SageMaker endpoint or batch transform job running the temporal model. For this example, we simulate the temporal model's output to demonstrate the downstream pipeline.

```python
def run_temporal_prediction(procedure_id: str, num_frames: int) -> dict:
    """
    Run temporal model inference on the feature sequence.

    In production, this loads the feature vectors from S3, sends them to a
    SageMaker endpoint running the temporal model (transformer or TCN), and
    gets back per-frame predictions for phase, instruments, and events.

    For this example, we generate synthetic predictions that look like a
    realistic cholecystectomy. The structure of the output is what matters
    for understanding the downstream pipeline.

    Args:
        procedure_id: Identifies which features to load.
        num_frames: Number of frames in the sequence (at SAMPLE_RATE_FPS).

    Returns:
        Dict with phase_predictions, instrument_predictions, event_predictions.
    """
    # In production, you'd load features and call the temporal model:
    #
    #   features = np.load(f"s3://{FEATURES_BUCKET}/{procedure_id}/features.npy")
    #   endpoint_response = sagemaker_runtime.invoke_endpoint(
    #       EndpointName=SAGEMAKER_TEMPORAL_MODEL,
    #       Body=features.tobytes(),
    #       ContentType="application/x-npy",
    #   )
    #   predictions = parse_response(endpoint_response)
    #
    # Instead, we generate synthetic predictions for a ~47-minute cholecystectomy.

    np.random.seed(42)  # reproducible synthetic data

    # Simulate phase predictions.
    # A typical cholecystectomy has phases of varying duration.
    # We assign frames to phases proportionally.
    phase_proportions = [0.065, 0.15, 0.26, 0.065, 0.31, 0.15]
    phase_boundaries = np.cumsum([int(p * num_frames) for p in phase_proportions])
    phase_boundaries[-1] = num_frames  # ensure we cover all frames

    phase_predictions = np.zeros(num_frames, dtype=int)
    phase_confidences = np.zeros(num_frames)
    start = 0
    for phase_idx, end in enumerate(phase_boundaries):
        phase_predictions[start:end] = phase_idx
        # High confidence in the middle of phases, lower at boundaries.
        for f in range(start, end):
            dist_from_boundary = min(f - start, end - f - 1)
            # Confidence ramps up from 0.7 at boundaries to 0.95 in the middle.
            phase_confidences[f] = min(0.95, 0.70 + 0.25 * (dist_from_boundary / 30))
        start = end

    # Add some noise at phase boundaries (realistic: models struggle at transitions).
    for boundary in phase_boundaries[:-1]:
        noise_range = min(5, num_frames - boundary)
        for offset in range(-3, noise_range):
            idx = boundary + offset
            if 0 <= idx < num_frames:
                if np.random.random() < 0.3:
                    # Flip to adjacent phase with low confidence.
                    phase_predictions[idx] = max(0, phase_predictions[idx] - 1)
                    phase_confidences[idx] = 0.45 + np.random.random() * 0.2

    # Simulate instrument predictions (multi-label, per frame).
    # Grasper is almost always present. Others appear in specific phases.
    instrument_predictions = np.zeros((num_frames, len(INSTRUMENT_CLASSES)))
    # Grasper: present ~90% of the time.
    instrument_predictions[:, 0] = (np.random.random(num_frames) < 0.90).astype(float)
    # Hook cautery: present during dissection phases (phases 1, 2, 4).
    for phase_idx in [1, 2, 4]:
        mask = phase_predictions == phase_idx
        instrument_predictions[mask, 1] = (np.random.random(mask.sum()) < 0.75).astype(float)
    # Clip applier: present during clipping phase (phase 3).
    mask = phase_predictions == 3
    instrument_predictions[mask, 3] = (np.random.random(mask.sum()) < 0.85).astype(float)
    # Scissors: brief appearances during clipping.
    instrument_predictions[mask, 2] = (np.random.random(mask.sum()) < 0.4).astype(float)

    instrument_confidences = np.clip(
        instrument_predictions * (0.7 + np.random.random((num_frames, len(INSTRUMENT_CLASSES))) * 0.25),
        0, 1,
    )

    # Simulate event detections (sparse, specific moments).
    event_predictions = []
    # Minor bleeding during Calot's triangle dissection.
    calot_start = int(phase_boundaries[1])
    calot_end = int(phase_boundaries[2])
    bleeding_frame = calot_start + int((calot_end - calot_start) * 0.4)
    event_predictions.append({
        "event_type": "bleeding_minor",
        "frame": bleeding_frame,
        "confidence": 0.72,
    })
    # Clip placements during clipping phase.
    clip_start = int(phase_boundaries[2])
    clip_end = int(phase_boundaries[3])
    clip_frame_1 = clip_start + int((clip_end - clip_start) * 0.3)
    clip_frame_2 = clip_start + int((clip_end - clip_start) * 0.6)
    event_predictions.append({
        "event_type": "clip_placement",
        "frame": clip_frame_1,
        "confidence": 0.96,
    })
    event_predictions.append({
        "event_type": "clip_placement",
        "frame": clip_frame_2,
        "confidence": 0.94,
    })
    # Specimen extraction near the end.
    extract_start = int(phase_boundaries[4])
    event_predictions.append({
        "event_type": "specimen_extraction",
        "frame": extract_start + 60,
        "confidence": 0.88,
    })

    return {
        "phase_predictions": phase_predictions,
        "phase_confidences": phase_confidences,
        "instrument_predictions": instrument_predictions,
        "instrument_confidences": instrument_confidences,
        "event_predictions": event_predictions,
        "num_frames": num_frames,
    }
```

---

## Step 5: Temporal Post-Processing

*Maps to pseudocode Step 5: `post_process(raw_predictions, sample_rate_fps)`. Raw per-frame predictions are noisy at phase boundaries. This step applies median filtering, minimum duration constraints, and instrument gap-filling to produce a clean, usable timeline.*

```python
def median_filter_1d(signal: np.ndarray, window: int) -> np.ndarray:
    """
    Apply a 1D median filter to smooth phase predictions.

    Median filtering is ideal for phase smoothing because it removes
    isolated outlier frames (single-frame phase flickers) without
    blurring the actual transitions. A mean filter would create
    impossible fractional phase values.

    Args:
        signal: 1D array of integer phase labels.
        window: Filter window size (must be odd for symmetric filtering).

    Returns:
        Smoothed signal with same shape.
    """
    if window % 2 == 0:
        window += 1  # ensure odd window

    padded = np.pad(signal, window // 2, mode="edge")
    result = np.zeros_like(signal)

    for i in range(len(signal)):
        result[i] = int(np.median(padded[i:i + window]))

    return result


def enforce_min_phase_duration(phases: np.ndarray, min_frames: int) -> np.ndarray:
    """
    Merge short phase segments into their longer neighbors.

    No surgical phase lasts less than 30 seconds. If the model predicts
    a 5-second phase segment, it's almost certainly a misclassification.
    We merge it into whichever adjacent phase is longer.

    Args:
        phases: 1D array of phase labels (already median-filtered).
        min_frames: Minimum segment length in frames.

    Returns:
        Phases with short segments merged.
    """
    result = phases.copy()

    # Identify contiguous segments.
    changes = np.where(np.diff(result) != 0)[0] + 1
    boundaries = np.concatenate([[0], changes, [len(result)]])

    for i in range(len(boundaries) - 1):
        seg_start = boundaries[i]
        seg_end = boundaries[i + 1]
        seg_length = seg_end - seg_start

        if seg_length < min_frames:
            # This segment is too short. Merge into the longer neighbor.
            left_length = seg_start - boundaries[max(0, i - 1)] if i > 0 else 0
            right_length = boundaries[min(len(boundaries) - 1, i + 2)] - seg_end if i < len(boundaries) - 2 else 0

            if left_length >= right_length and i > 0:
                # Merge into left neighbor.
                result[seg_start:seg_end] = result[seg_start - 1]
            elif i < len(boundaries) - 2:
                # Merge into right neighbor.
                result[seg_start:seg_end] = result[seg_end]

    return result


def post_process_predictions(raw_predictions: dict) -> dict:
    """
    Clean up raw model predictions into a usable procedure timeline.

    Applies:
    1. Median filtering to remove single-frame phase flickers.
    2. Minimum duration enforcement to eliminate impossibly short phases.
    3. Instrument gap-filling to handle brief occlusions.
    4. Timeline construction with start/end timestamps.

    Args:
        raw_predictions: Output from run_temporal_prediction().

    Returns:
        Dict with phase_timeline, instrument_log, and events.
    """
    num_frames = raw_predictions["num_frames"]
    phases = raw_predictions["phase_predictions"].copy()
    phase_confs = raw_predictions["phase_confidences"].copy()

    # Step 5a: Median filter to remove phase flickers.
    phases = median_filter_1d(phases, PHASE_SMOOTH_WINDOW)

    # Step 5b: Enforce minimum phase duration.
    min_frames = MIN_PHASE_DURATION_SEC * SAMPLE_RATE_FPS
    phases = enforce_min_phase_duration(phases, min_frames)

    # Step 5c: Build phase timeline from contiguous segments.
    phase_timeline = []
    changes = np.where(np.diff(phases) != 0)[0] + 1
    boundaries = np.concatenate([[0], changes, [num_frames]])

    for i in range(len(boundaries) - 1):
        seg_start = boundaries[i]
        seg_end = boundaries[i + 1]
        phase_idx = int(phases[seg_start])

        # Average confidence across the segment.
        seg_confidence = float(np.mean(phase_confs[seg_start:seg_end]))

        phase_timeline.append({
            "phase_name": CHOLECYSTECTOMY_PHASES[phase_idx],
            "start_time": float(seg_start / SAMPLE_RATE_FPS),
            "end_time": float(seg_end / SAMPLE_RATE_FPS),
            "duration": float((seg_end - seg_start) / SAMPLE_RATE_FPS),
            "confidence": round(seg_confidence, 3),
        })

    # Step 5d: Build instrument usage log.
    # For each instrument, find contiguous presence intervals.
    instrument_log = []
    inst_preds = raw_predictions["instrument_predictions"]

    for inst_idx, inst_name in enumerate(INSTRUMENT_CLASSES):
        presence = inst_preds[:, inst_idx] > 0.5

        # Gap-fill: brief absences are likely occlusion.
        gap_fill_frames = INSTRUMENT_GAP_FILL_SEC * SAMPLE_RATE_FPS
        filled = presence.copy()
        # Find gaps (False runs) shorter than threshold and fill them.
        in_gap = False
        gap_start = 0
        for f in range(len(filled)):
            if not filled[f] and not in_gap:
                in_gap = True
                gap_start = f
            elif filled[f] and in_gap:
                if f - gap_start < gap_fill_frames:
                    filled[gap_start:f] = True
                in_gap = False

        # Extract intervals where instrument is present.
        changes_inst = np.where(np.diff(filled.astype(int)) != 0)[0] + 1
        inst_boundaries = np.concatenate([[0], changes_inst, [num_frames]])

        for i in range(len(inst_boundaries) - 1):
            seg_start = inst_boundaries[i]
            seg_end = inst_boundaries[i + 1]
            if filled[seg_start]:
                instrument_log.append({
                    "instrument": inst_name,
                    "start_time": float(seg_start / SAMPLE_RATE_FPS),
                    "end_time": float(seg_end / SAMPLE_RATE_FPS),
                    "duration": float((seg_end - seg_start) / SAMPLE_RATE_FPS),
                })

    # Step 5e: Convert event frame indices to timestamps.
    events = []
    for event in raw_predictions["event_predictions"]:
        timestamp = event["frame"] / SAMPLE_RATE_FPS
        # Find which phase this event falls in.
        phase_context = "unknown"
        for phase in phase_timeline:
            if phase["start_time"] <= timestamp < phase["end_time"]:
                phase_context = phase["phase_name"]
                break

        events.append({
            "event_type": event["event_type"],
            "timestamp": float(timestamp),
            "confidence": event["confidence"],
            "phase_context": phase_context,
        })

    return {
        "phase_timeline": phase_timeline,
        "instrument_log": instrument_log,
        "events": events,
        "total_duration": float(num_frames / SAMPLE_RATE_FPS),
    }
```

---

## Step 6: Store Results in DynamoDB and OpenSearch

*Maps to pseudocode Step 6: `store_results(procedure_id, analysis_results)`. The structured analysis goes to two places: DynamoDB for fast procedure-level lookups, and OpenSearch for cross-procedure search queries.*

```python
import requests
from requests_aws4auth import AWS4Auth


def store_results_dynamodb(procedure_id: str, metadata: dict, analysis: dict) -> None:
    """
    Write the full procedure analysis to DynamoDB.

    This supports the primary access pattern: "give me everything about
    procedure X." The phase timeline, instrument log, and events all live
    in a single item for fast retrieval.

    Args:
        procedure_id: Partition key for the record.
        metadata: Procedure metadata (type, surgeon, date).
        analysis: Output from post_process_predictions().
    """
    table = dynamodb.Table(PROCEDURE_INDEX_TABLE)

    # DynamoDB doesn't accept Python floats. Convert all numeric values to Decimal.
    # This is a common gotcha that will crash your Lambda at 2am if you forget.
    def decimalize(obj):
        if isinstance(obj, float):
            return Decimal(str(round(obj, 4)))
        if isinstance(obj, dict):
            return {k: decimalize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [decimalize(item) for item in obj]
        return obj

    record = decimalize({
        "procedure_id": procedure_id,
        "status": "analyzed",
        "analyzed_at": datetime.datetime.now(timezone.utc).isoformat(),
        "procedure_type": metadata["procedure_type"],
        "surgeon_id": metadata["surgeon_id"],
        "procedure_date": metadata["procedure_date"],
        "total_duration": analysis["total_duration"],
        "phase_timeline": analysis["phase_timeline"],
        "instrument_log": analysis["instrument_log"],
        "events": analysis["events"],
        "model_version": "cholec-phase-v2.3",
    })

    table.put_item(Item=record)
    logger.info("Stored analysis for procedure %s in DynamoDB", procedure_id)


def index_results_opensearch(procedure_id: str, metadata: dict, analysis: dict) -> None:
    """
    Index the procedure analysis in OpenSearch for cross-procedure search.

    This supports queries like "find all procedures where bleeding occurred
    during Calot's triangle dissection" or "show me cases where the clipping
    phase took longer than 5 minutes."

    We index phases and events as separate documents so they're independently
    searchable with their own timestamps and attributes.

    Args:
        procedure_id: Links documents back to the procedure.
        metadata: Procedure metadata for filtering.
        analysis: Output from post_process_predictions().
    """
    # In production, use requests-aws4auth for SigV4 signing to the
    # VPC-internal OpenSearch domain. This example shows the structure.
    #
    # credentials = boto3.Session().get_credentials()
    # auth = AWS4Auth(
    #     credentials.access_key,
    #     credentials.secret_key,
    #     "us-east-1",
    #     "es",
    #     session_token=credentials.token,
    # )
    # headers = {"Content-Type": "application/json"}

    # Index each phase as a searchable document.
    for phase in analysis["phase_timeline"]:
        doc = {
            "procedure_id": procedure_id,
            "procedure_type": metadata["procedure_type"],
            "surgeon_id": metadata["surgeon_id"],
            "procedure_date": metadata["procedure_date"],
            "phase_name": phase["phase_name"],
            "start_time": phase["start_time"],
            "end_time": phase["end_time"],
            "duration": phase["duration"],
            "confidence": phase["confidence"],
        }
        # In production:
        # requests.post(
        #     f"{OPENSEARCH_DOMAIN}/procedure-phases/_doc",
        #     json=doc, auth=auth, headers=headers,
        # )
        logger.info("Indexed phase: %s (%.0fs)", phase["phase_name"], phase["duration"])

    # Index each event as a searchable document.
    for event in analysis["events"]:
        doc = {
            "procedure_id": procedure_id,
            "procedure_type": metadata["procedure_type"],
            "surgeon_id": metadata["surgeon_id"],
            "procedure_date": metadata["procedure_date"],
            "event_type": event["event_type"],
            "timestamp": event["timestamp"],
            "confidence": event["confidence"],
            "phase_context": event["phase_context"],
        }
        # In production:
        # requests.post(
        #     f"{OPENSEARCH_DOMAIN}/procedure-events/_doc",
        #     json=doc, auth=auth, headers=headers,
        # )
        logger.info("Indexed event: %s at %.0fs", event["event_type"], event["timestamp"])

    logger.info(
        "Indexed %d phases and %d events for procedure %s",
        len(analysis["phase_timeline"]),
        len(analysis["events"]),
        procedure_id,
    )
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, each step would be a separate Lambda function orchestrated by Step Functions, with error handling and retries at each stage. This version runs sequentially to show the complete flow.

```python
def analyze_surgical_video(video_s3_key: str, metadata: dict) -> dict:
    """
    Run the full surgical video analysis pipeline for one procedure.

    In a Step Functions deployment, each step would be a separate state
    with its own error handling, retries, and timeout. This function
    shows the logical flow as a single callable.

    Args:
        video_s3_key: S3 key of the raw surgical video.
        metadata: Dict with procedure_type, surgeon_id, procedure_date,
                  duration_seconds.

    Returns:
        The complete analysis result.
    """
    print(f"\n{'='*60}")
    print(f"SURGICAL VIDEO ANALYSIS PIPELINE")
    print(f"{'='*60}")

    # Step 1: Register the procedure.
    print("\n[Step 1] Ingesting video and registering procedure...")
    procedure_id = ingest_video(video_s3_key, metadata)
    print(f"  Procedure ID: {procedure_id}")
    print(f"  Type: {metadata['procedure_type']}")
    print(f"  Duration: {metadata['duration_seconds']}s ({metadata['duration_seconds']/60:.1f} min)")

    # Step 2: Extract frames.
    # In production, this triggers MediaConvert and waits for completion.
    # Here we simulate the frame count based on video duration and sample rate.
    print("\n[Step 2] Extracting frames...")
    num_frames = int(metadata["duration_seconds"] * SAMPLE_RATE_FPS)
    print(f"  Sample rate: {SAMPLE_RATE_FPS} fps")
    print(f"  Expected frames: {num_frames}")
    # Simulate ~3% frame rejection from filtering.
    num_valid_frames = int(num_frames * 0.97)
    print(f"  Valid frames after filtering: {num_valid_frames}")

    # Step 3: Feature extraction.
    # In production, this is a SageMaker Batch Transform job.
    print("\n[Step 3] Extracting features (SageMaker Batch Transform)...")
    print(f"  Model: {SAGEMAKER_FEATURE_MODEL}")
    print(f"  Feature dimension: {FEATURE_DIM}")
    print(f"  Estimated time: ~{num_valid_frames * 0.05:.0f}s on ml.g5.xlarge")

    # Step 4: Temporal prediction.
    print("\n[Step 4] Running temporal model...")
    raw_predictions = run_temporal_prediction(procedure_id, num_valid_frames)
    print(f"  Predicted {len(CHOLECYSTECTOMY_PHASES)} phase types")
    print(f"  Detected {len(raw_predictions['event_predictions'])} events")

    # Step 5: Post-processing.
    print("\n[Step 5] Post-processing predictions...")
    analysis = post_process_predictions(raw_predictions)
    print(f"  Phase timeline: {len(analysis['phase_timeline'])} segments")
    print(f"  Instrument intervals: {len(analysis['instrument_log'])}")
    print(f"  Events: {len(analysis['events'])}")

    # Print the phase timeline.
    print("\n  Phase Timeline:")
    for phase in analysis["phase_timeline"]:
        minutes = phase["duration"] / 60
        conf_marker = "✓" if phase["confidence"] >= PHASE_CONFIDENCE_THRESHOLD else "?"
        print(f"    {conf_marker} {phase['phase_name']}: "
              f"{phase['start_time']:.0f}s - {phase['end_time']:.0f}s "
              f"({minutes:.1f} min, conf={phase['confidence']:.2f})")

    print("\n  Events Detected:")
    for event in analysis["events"]:
        print(f"    [{event['event_type']}] at {event['timestamp']:.0f}s "
              f"(conf={event['confidence']:.2f}, during {event['phase_context']})")

    # Step 6: Store results.
    print("\n[Step 6] Storing results...")
    store_results_dynamodb(procedure_id, metadata, analysis)
    index_results_opensearch(procedure_id, metadata, analysis)
    print(f"  Written to DynamoDB table: {PROCEDURE_INDEX_TABLE}")
    print(f"  Indexed in OpenSearch: {OPENSEARCH_DOMAIN}")

    print(f"\n{'='*60}")
    print(f"PIPELINE COMPLETE: {procedure_id}")
    print(f"{'='*60}\n")

    return {
        "procedure_id": procedure_id,
        "analysis": analysis,
    }


# Example: run the pipeline against a simulated surgical video.
if __name__ == "__main__":
    result = analyze_surgical_video(
        video_s3_key="uploads/2026-05-15/OR3-cholecystectomy-morning.mp4",
        metadata={
            "procedure_type": "laparoscopic_cholecystectomy",
            "surgeon_id": "surgeon-dr-chen",
            "procedure_date": "2026-05-15",
            "duration_seconds": 2847,  # ~47 minutes
        },
    )

    # Pretty-print the analysis result.
    print(json.dumps(result["analysis"], indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the pipeline structure and data flow. It generates synthetic predictions to show what the output looks like. But there's a significant distance between this sketch and a system processing real surgical video at a hospital. Here's where that gap lives:

**The ML models don't exist in this example.** The feature extraction backbone and temporal model are the core of the system, and training them requires: (1) hundreds of annotated surgical videos, (2) weeks of GPU training time, (3) surgical domain expertise for annotation and validation. The Cholec80 dataset is a starting point for cholecystectomy, but you'll need local fine-tuning for your institution's cameras, surgeons, and patient population.

**Error handling and retries.** Every external call (MediaConvert, SageMaker, DynamoDB, OpenSearch) can fail. A production pipeline wraps each step in try/except with specific handling for throttling, timeouts, and transient failures. Step Functions provides built-in retry with exponential backoff at the state machine level, which is why this pipeline belongs in Step Functions rather than a single Lambda.

**Video format handling.** OR recording systems output video in a variety of formats and codecs. Some use MPEG-4, some use proprietary formats, some record at non-standard frame rates. MediaConvert handles most of this, but you'll encounter edge cases that require custom preprocessing. Test with actual video from your OR systems early.

**Storage cost management.** A single procedure generates 50-100 GB of raw video. At scale (20 procedures/day), that's 1-2 TB per day. S3 Intelligent-Tiering or lifecycle policies that move older video to Glacier are essential. The extracted frames and features are much smaller (~500 MB per procedure) but still add up.

**IAM least-privilege.** The IAM roles in this example are described generically. In production, each component (the ingestion Lambda, the MediaConvert role, the SageMaker execution role, the post-processing Lambda) gets its own role with exactly the permissions it needs. The SageMaker role needs S3 read on the frames bucket and S3 write on the features bucket, nothing else.

**VPC configuration.** Surgical video is PHI. The entire pipeline runs in a VPC with private subnets. SageMaker training and inference instances, OpenSearch domain, and Lambda functions all live in the VPC. VPC endpoints for S3, DynamoDB, and CloudWatch Logs keep traffic off the public internet.

**Encryption.** All S3 buckets use SSE-KMS with customer-managed keys. DynamoDB tables use encryption at rest. OpenSearch uses both encryption at rest and node-to-node encryption. SageMaker instances use encrypted volumes. KMS key policies restrict access to the specific roles that need each key.

**Monitoring and alerting.** A production pipeline has CloudWatch metrics for: processing latency per procedure, GPU utilization during inference, frame extraction success rate, model confidence distributions, and queue depth (how many procedures are waiting). Alarms fire when the backlog grows or when confidence scores drop (indicating model degradation or a new camera system producing unfamiliar images).

**Model versioning and drift detection.** Surgical video models degrade over time as cameras change, surgical techniques evolve, and the patient population shifts. Track model version with every prediction. Monitor confidence score distributions over time. When average confidence drops below a threshold, it's time to retrain with recent data.

**De-identification.** Even for quality improvement use cases, surgical video may need de-identification before analysis. Patient faces (visible during intubation or positioning), name labels on drapes, and monitor displays showing patient information all need to be detected and redacted. This is a separate preprocessing step not covered in this example.

**Surgeon consent and governance.** This is not a technical gap but it will block your deployment faster than any engineering challenge. Surgeons must consent to having their procedures analyzed. The governance framework (who sees the results, how they're used, whether they're tied to performance reviews) must be established before the first video is processed. Build the governance model before you build the pipeline.

The recipe in 9.9 covers the full architectural context, the honest take on where this technology stands today, and the variations you might consider. This Python example shows one way the AWS orchestration pieces fit together.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.9](chapter09.09-surgical-video-analysis.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
