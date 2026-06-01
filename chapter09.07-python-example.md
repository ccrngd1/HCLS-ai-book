# Recipe 9.7: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the multi-modality radiology AI triage pipeline from Recipe 9.7. It demonstrates the orchestration patterns (study classification, model routing, inference invocation, priority assignment) using boto3 calls to SageMaker, S3, DynamoDB, and SNS. It does not include actual trained radiology AI models, DICOM parsing libraries, or real HL7/DICOM worklist integration. Think of it as the control plane skeleton: the part that decides what to run, runs it, and acts on the results. The actual deep learning inference is a black box behind a SageMaker endpoint. Consider it a starting point, not a destination.

---

## Setup

```bash
pip install boto3 pydicom numpy
```

`pydicom` handles DICOM metadata parsing. `numpy` handles pixel array manipulation for preprocessing. The actual model inference happens on SageMaker endpoints; you don't need TensorFlow or PyTorch locally.

Your environment needs credentials configured with these IAM permissions:

- `sagemaker:InvokeEndpoint`
- `s3:GetObject`, `s3:PutObject`
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem`
- `sns:Publish`
- `states:StartExecution` (if triggering Step Functions externally)
- `medical-imaging:SearchImageSets`, `medical-imaging:GetImageFrame` (for HealthImaging)

---

## Configuration and Constants

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
import numpy as np
from botocore.config import Config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients. Module-level for Lambda container reuse.
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)

# ----- Deployment Configuration -----
# Replace these with your actual resource names.

DICOM_BUCKET = "radiology-dicom-store"
PREPROCESSED_BUCKET = "radiology-preprocessed"
RESULTS_TABLE_NAME = "radiology-triage-results"
STUDY_TRACKING_TABLE_NAME = "radiology-study-tracking"
CRITICAL_ALERT_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:radiology-critical-alerts"

# ----- Model Endpoint Configuration -----
# Each model has a SageMaker endpoint name and preprocessing parameters.
# In production, these come from a configuration service or SSM Parameter Store.

MODEL_ENDPOINTS = {
    "ich_detection": {
        "endpoint_name": "radiology-ich-detection-v2",
        "modality": "CT",
        "body_parts": ["HEAD", "BRAIN"],
        "input_shape": (256, 256, 32),       # H x W x slices (downsampled)
        "window_center": 40,                  # Brain window
        "window_width": 80,
        "voxel_spacing_mm": 1.0,             # Resample to isotropic
        "findings": ["intracranial_hemorrhage", "midline_shift", "mass_effect"],
    },
    "cxr_critical": {
        "endpoint_name": "radiology-cxr-critical-v3",
        "modality": "CR",  # Also matches "DX"
        "body_parts": ["CHEST"],
        "input_shape": (512, 512, 1),         # Single 2D image
        "findings": ["pneumothorax", "tension_pneumothorax", "large_pleural_effusion",
                     "widened_mediastinum"],
    },
    "pe_detection": {
        "endpoint_name": "radiology-pe-detection-v1",
        "modality": "CT",
        "body_parts": ["CHEST"],
        "input_shape": (256, 256, 64),
        "window_center": 100,                 # Mediastinal/PE window
        "window_width": 700,
        "voxel_spacing_mm": 1.5,
        "findings": ["pulmonary_embolism", "saddle_pe", "aortic_dissection"],
    },
    "cervical_fracture": {
        "endpoint_name": "radiology-cspine-fracture-v1",
        "modality": "CT",
        "body_parts": ["SPINE", "CSPINE", "C-SPINE"],
        "input_shape": (256, 256, 48),
        "window_center": 400,                 # Bone window
        "window_width": 1800,
        "voxel_spacing_mm": 1.0,
        "findings": ["cervical_fracture", "unstable_spine_injury"],
    },
}

# ----- Priority Rules -----
# Clinically defined by radiology medical directors.
# Each rule: finding name, minimum confidence to trigger, priority level.
# STAT = read within 15 minutes. URGENT = read within 1 hour. ROUTINE = standard queue.

PRIORITY_RULES = [
    # STAT findings: life-threatening, need immediate attention
    {"finding": "intracranial_hemorrhage", "min_confidence": 0.85, "priority": "STAT"},
    {"finding": "midline_shift", "min_confidence": 0.80, "priority": "STAT"},
    {"finding": "tension_pneumothorax", "min_confidence": 0.80, "priority": "STAT"},
    {"finding": "saddle_pe", "min_confidence": 0.85, "priority": "STAT"},
    {"finding": "aortic_dissection", "min_confidence": 0.85, "priority": "STAT"},
    # URGENT findings: significant but not immediately life-threatening
    {"finding": "pneumothorax", "min_confidence": 0.80, "priority": "URGENT"},
    {"finding": "pulmonary_embolism", "min_confidence": 0.80, "priority": "URGENT"},
    {"finding": "cervical_fracture", "min_confidence": 0.80, "priority": "URGENT"},
    {"finding": "large_pleural_effusion", "min_confidence": 0.85, "priority": "URGENT"},
    {"finding": "mass_effect", "min_confidence": 0.80, "priority": "URGENT"},
    {"finding": "unstable_spine_injury", "min_confidence": 0.80, "priority": "URGENT"},
]

# Priority ordering for comparison (higher index = higher priority).
PRIORITY_LEVELS = {"ROUTINE": 0, "URGENT": 1, "STAT": 2}

# Confidence threshold below which we discard a finding entirely.
# Findings between this and the priority rule threshold are logged but don't trigger.
MINIMUM_FINDING_CONFIDENCE = 0.50

# Study completion timeout: seconds of silence before declaring a study complete.
STUDY_COMPLETION_TIMEOUT_SECONDS = 60
```

---

## Step 1: Classify the Study and Select Models

*Maps to pseudocode Step 2 in the main recipe. Given a study's DICOM metadata, determine which AI models should analyze it. The routing logic handles the inconsistency of real-world DICOM metadata by checking multiple fields and normalizing values.*

```python
def classify_study_and_select_models(study_metadata: dict) -> list[dict]:
    """
    Examine DICOM metadata and determine which AI models apply to this study.

    Real-world DICOM metadata is messy. BodyPartExamined might be "HEAD",
    "BRAIN", "Head", or empty. StudyDescription might say "CT HEAD W/O"
    or "CT Brain Non-Con" or "TRAUMA CT HEAD NECK". This function normalizes
    the metadata and matches against the model configuration.

    Args:
        study_metadata: dict with keys from DICOM headers:
            - Modality (str): "CT", "MR", "CR", "DX"
            - BodyPartExamined (str): varies wildly
            - StudyDescription (str): free text
            - ProtocolName (str): sometimes more specific

    Returns:
        List of model config dicts from MODEL_ENDPOINTS that should run.
        Empty list if no models match (study type not covered by triage).
    """
    modality = study_metadata.get("Modality", "").upper().strip()
    body_part = study_metadata.get("BodyPartExamined", "").upper().strip()
    description = study_metadata.get("StudyDescription", "").upper().strip()
    protocol = study_metadata.get("ProtocolName", "").upper().strip()

    # CR and DX are both plain radiographs. Normalize to match either.
    xray_modalities = {"CR", "DX"}

    selected_models = []

    for model_name, config in MODEL_ENDPOINTS.items():
        model_modality = config["modality"]

        # Check modality match. Handle CR/DX equivalence.
        modality_match = False
        if model_modality in xray_modalities:
            modality_match = modality in xray_modalities
        else:
            modality_match = modality == model_modality

        if not modality_match:
            continue

        # Check body part match. Also search the study description and protocol
        # for body part keywords, because BodyPartExamined is often empty or wrong.
        body_part_match = False
        for bp in config["body_parts"]:
            if bp in body_part or bp in description or bp in protocol:
                body_part_match = True
                break

        if body_part_match:
            selected_models.append({"model_name": model_name, **config})

    if not selected_models:
        logger.info(
            "No models matched for study: modality=%s, body_part=%s, desc=%s",
            modality, body_part, description
        )

    return selected_models
```

---

## Step 2: Preprocess Pixel Data for a Specific Model

*Maps to the preprocessing portion of pseudocode Step 3. Each model expects input in a specific format. CT models need windowing, resampling, and volume extraction. X-ray models need 2D resizing and normalization. This function dispatches to the correct preprocessing based on model configuration.*

```python
def preprocess_for_model(
    pixel_array: np.ndarray,
    model_config: dict,
    original_spacing: tuple[float, float, float],
) -> np.ndarray:
    """
    Transform raw pixel data into the format expected by a specific model.

    For CT volumes: apply windowing, resample to target voxel spacing,
    resize to model input dimensions, normalize to [0, 1].

    For X-ray (2D): resize to target dimensions, normalize to [0, 1].

    Args:
        pixel_array: raw pixel data as numpy array.
            CT: shape (slices, height, width) in Hounsfield Units.
            X-ray: shape (height, width) in raw pixel values.
        model_config: model configuration dict from MODEL_ENDPOINTS.
        original_spacing: (slice_spacing, row_spacing, col_spacing) in mm.
            For X-ray, only (row_spacing, col_spacing) matters.

    Returns:
        Preprocessed numpy array matching model_config["input_shape"],
        dtype float32, values in [0, 1].
    """
    target_shape = model_config["input_shape"]

    if len(pixel_array.shape) == 3:
        # 3D volume (CT or MRI)
        preprocessed = _preprocess_volume(pixel_array, model_config, original_spacing)
    else:
        # 2D image (X-ray)
        preprocessed = _preprocess_2d(pixel_array, model_config)

    return preprocessed.astype(np.float32)


def _preprocess_volume(
    volume: np.ndarray,
    model_config: dict,
    original_spacing: tuple[float, float, float],
) -> np.ndarray:
    """
    Preprocess a 3D CT/MRI volume for model inference.

    Steps:
    1. Apply HU windowing (converts raw HU to visible range)
    2. Resample to isotropic voxel spacing
    3. Resize/crop to model input dimensions
    4. Normalize to [0, 1]
    """
    # Step 1: Windowing. Maps the relevant HU range to [0, 1].
    # Brain window (W:80, L:40) shows soft tissue.
    # Bone window (W:1800, L:400) shows fractures.
    # The model was trained on a specific window; use the same one.
    window_center = model_config.get("window_center", 40)
    window_width = model_config.get("window_width", 80)

    lower = window_center - (window_width / 2)
    upper = window_center + (window_width / 2)

    windowed = np.clip(volume, lower, upper)
    windowed = (windowed - lower) / (upper - lower)  # Now in [0, 1]

    # Step 2: Resample to target voxel spacing.
    # Real CT scans have non-isotropic voxels (e.g., 0.5mm x 0.5mm x 2.5mm).
    # Models expect isotropic input. We resample using simple nearest-neighbor
    # here; production would use scipy.ndimage.zoom with order=1 or 3.
    target_spacing = model_config.get("voxel_spacing_mm", 1.0)
    zoom_factors = (
        original_spacing[0] / target_spacing,
        original_spacing[1] / target_spacing,
        original_spacing[2] / target_spacing,
    )

    # Simplified resampling: just resize to target shape.
    # In production, use scipy.ndimage.zoom(windowed, zoom_factors, order=1)
    # then center-crop or pad to target dimensions.
    target_h, target_w, target_slices = model_config["input_shape"]

    # Resize each slice to target H x W, then select/pad slices.
    from numpy.lib.stride_tricks import as_strided  # noqa: avoid heavy imports

    # Simple approach: uniformly sample target_slices from the volume.
    num_slices = windowed.shape[0]
    if num_slices >= target_slices:
        # Uniformly sample slices
        indices = np.linspace(0, num_slices - 1, target_slices, dtype=int)
        sampled = windowed[indices]
    else:
        # Pad with zeros if fewer slices than expected
        pad_amount = target_slices - num_slices
        sampled = np.pad(windowed, ((0, pad_amount), (0, 0), (0, 0)), mode="constant")

    # Resize spatial dimensions (simple nearest-neighbor via slicing).
    # Production: use cv2.resize or scipy for proper interpolation.
    h, w = sampled.shape[1], sampled.shape[2]
    row_step = max(1, h // target_h)
    col_step = max(1, w // target_w)
    resized = sampled[:, ::row_step, ::col_step][:, :target_h, :target_w]

    # Pad if smaller than target
    if resized.shape[1] < target_h or resized.shape[2] < target_w:
        pad_h = target_h - resized.shape[1]
        pad_w = target_w - resized.shape[2]
        resized = np.pad(resized, ((0, 0), (0, pad_h), (0, pad_w)), mode="constant")

    # Transpose to (H, W, slices) to match model input convention.
    result = np.transpose(resized, (1, 2, 0))

    return result


def _preprocess_2d(image: np.ndarray, model_config: dict) -> np.ndarray:
    """
    Preprocess a 2D X-ray image for model inference.

    Steps:
    1. Normalize pixel values to [0, 1]
    2. Resize to model input dimensions
    """
    target_h, target_w, _ = model_config["input_shape"]

    # Normalize to [0, 1] based on actual pixel range.
    img_min = image.min()
    img_max = image.max()
    if img_max > img_min:
        normalized = (image - img_min) / (img_max - img_min)
    else:
        normalized = np.zeros_like(image, dtype=np.float32)

    # Simple resize via uniform sampling.
    h, w = normalized.shape
    row_indices = np.linspace(0, h - 1, target_h, dtype=int)
    col_indices = np.linspace(0, w - 1, target_w, dtype=int)
    resized = normalized[np.ix_(row_indices, col_indices)]

    # Add channel dimension: (H, W) -> (H, W, 1)
    return resized[:, :, np.newaxis]
```

---

## Step 3: Invoke SageMaker Endpoint for Inference

*Maps to the inference call in pseudocode Step 3. Sends the preprocessed array to the appropriate SageMaker endpoint and parses the response into structured findings.*

```python
def invoke_model(model_config: dict, preprocessed_array: np.ndarray) -> list[dict]:
    """
    Call a SageMaker endpoint with preprocessed image data and parse findings.

    The endpoint expects a numpy array serialized as bytes. The response is
    JSON containing a list of detected findings with confidence scores.

    Args:
        model_config: model configuration dict with endpoint_name and findings list.
        preprocessed_array: numpy float32 array matching model input_shape.

    Returns:
        List of finding dicts: [{"finding": str, "confidence": float, ...}]
        Only findings above MINIMUM_FINDING_CONFIDENCE are returned.
    """
    endpoint_name = model_config["endpoint_name"]

    # Serialize the numpy array for transmission.
    # SageMaker endpoints accept various content types.
    # application/x-npy is efficient for numpy arrays.
    payload = preprocessed_array.tobytes()

    # Include shape metadata in a custom header so the endpoint can reconstruct.
    # Alternative: use application/json with the array as a nested list (slower).
    custom_attributes = json.dumps({
        "shape": list(preprocessed_array.shape),
        "dtype": "float32",
    })

    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="application/x-npy",
        Body=payload,
        CustomAttributes=custom_attributes,
    )

    # Parse the response body. Expected format:
    # {
    #   "findings": [
    #     {"finding": "intracranial_hemorrhage", "confidence": 0.94,
    #      "subtype": "subdural", "location": {"slice_range": [45, 62]}},
    #     {"finding": "midline_shift", "confidence": 0.87, "shift_mm": 6.2}
    #   ],
    #   "model_version": "v2.3.1",
    #   "inference_time_ms": 1240
    # }
    result = json.loads(response["Body"].read().decode("utf-8"))

    findings = result.get("findings", [])

    # Filter out low-confidence noise.
    filtered = [
        f for f in findings
        if f.get("confidence", 0) >= MINIMUM_FINDING_CONFIDENCE
    ]

    logger.info(
        "Model %s returned %d findings (%d above threshold)",
        endpoint_name, len(findings), len(filtered)
    )

    return filtered
```

---

## Step 4: Assign Priority Based on Findings

*Maps to pseudocode Step 4. Takes the combined findings from all models that ran on a study and determines the highest applicable priority level.*

```python
def assign_priority(all_findings: list[dict]) -> tuple[str, list[dict]]:
    """
    Map combined model findings to a clinical priority level.

    Iterates through PRIORITY_RULES (ordered STAT first, then URGENT).
    The highest matching priority wins. A study with both a STAT finding
    and an URGENT finding gets STAT priority.

    Args:
        all_findings: combined list of findings from all models.

    Returns:
        Tuple of (priority_level, triggering_findings):
        - priority_level: "STAT", "URGENT", or "ROUTINE"
        - triggering_findings: list of findings that triggered the assigned priority
    """
    highest_priority = "ROUTINE"
    triggering_findings = []

    for finding in all_findings:
        finding_name = finding.get("finding", "")
        confidence = finding.get("confidence", 0.0)

        for rule in PRIORITY_RULES:
            if finding_name == rule["finding"] and confidence >= rule["min_confidence"]:
                rule_priority = rule["priority"]

                if PRIORITY_LEVELS[rule_priority] > PRIORITY_LEVELS[highest_priority]:
                    highest_priority = rule_priority
                    triggering_findings = [finding]
                elif PRIORITY_LEVELS[rule_priority] == PRIORITY_LEVELS[highest_priority]:
                    triggering_findings.append(finding)

    return highest_priority, triggering_findings
```

---

## Step 5: Store Results and Send Alerts

*Maps to the result storage and notification portions of the pseudocode. Writes the triage result to DynamoDB and fires an SNS alert for STAT findings.*

```python
def store_triage_result(
    study_uid: str,
    study_metadata: dict,
    priority: str,
    all_findings: list[dict],
    triggering_findings: list[dict],
    models_invoked: list[str],
) -> dict:
    """
    Write the triage result to DynamoDB and send alerts for critical findings.

    The record includes everything needed for audit: which models ran,
    what they found, what priority was assigned, and why. This is critical
    for FDA audit trail requirements on medical device software.

    Args:
        study_uid: DICOM StudyInstanceUID (unique study identifier).
        study_metadata: original DICOM metadata dict.
        priority: assigned priority level ("STAT", "URGENT", "ROUTINE").
        all_findings: complete list of findings from all models.
        triggering_findings: subset of findings that triggered the priority.
        models_invoked: list of model names that were run.

    Returns:
        The stored record dict.
    """
    results_table = dynamodb.Table(RESULTS_TABLE_NAME)

    # Convert floats to Decimal for DynamoDB.
    def decimal_findings(findings_list):
        converted = []
        for f in findings_list:
            entry = {}
            for k, v in f.items():
                if isinstance(v, float):
                    entry[k] = Decimal(str(round(v, 4)))
                else:
                    entry[k] = v
            converted.append(entry)
        return converted

    record = {
        "study_uid": study_uid,
        "triaged_at": datetime.datetime.now(timezone.utc).isoformat(),
        "priority": priority,
        "patient_id": study_metadata.get("PatientID", "UNKNOWN"),
        "accession_number": study_metadata.get("AccessionNumber", ""),
        "modality": study_metadata.get("Modality", ""),
        "study_description": study_metadata.get("StudyDescription", ""),
        "models_invoked": models_invoked,
        "all_findings": decimal_findings(all_findings),
        "triggering_findings": decimal_findings(triggering_findings),
        "acknowledged": False,
        "acknowledged_by": None,
        "acknowledged_at": None,
    }

    results_table.put_item(Item=record)
    logger.info("Stored triage result for %s: priority=%s", study_uid, priority)

    # Send SNS alert for STAT findings.
    if priority == "STAT":
        _send_critical_alert(study_uid, study_metadata, triggering_findings)

    return record


def _send_critical_alert(
    study_uid: str,
    study_metadata: dict,
    triggering_findings: list[dict],
) -> None:
    """
    Publish a critical finding alert via SNS.

    The message goes to the on-call radiologist and the referring physician.
    It contains enough context to act on without opening the full study:
    what was found, how confident the AI is, and where to find the study.

    Never include patient name or MRN in the SNS message body.
    Use accession number (which maps to the study in PACS) as the identifier.
    """
    finding_summaries = []
    for f in triggering_findings:
        summary = f"{f['finding']} (confidence: {f.get('confidence', 'N/A')})"
        if "subtype" in f:
            summary += f" [{f['subtype']}]"
        finding_summaries.append(summary)

    message = {
        "alert_type": "STAT_RADIOLOGY_FINDING",
        "accession_number": study_metadata.get("AccessionNumber", "UNKNOWN"),
        "modality": study_metadata.get("Modality", ""),
        "study_description": study_metadata.get("StudyDescription", ""),
        "findings": finding_summaries,
        "study_uid": study_uid,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "action_required": "Immediate radiologist review required",
    }

    sns_client.publish(
        TopicArn=CRITICAL_ALERT_TOPIC_ARN,
        Subject="STAT: Critical Radiology Finding Detected",
        Message=json.dumps(message, indent=2),
        MessageAttributes={
            "priority": {"DataType": "String", "StringValue": "STAT"},
            "modality": {"DataType": "String", "StringValue": study_metadata.get("Modality", "")},
        },
    )

    logger.info("Published STAT alert for accession %s", study_metadata.get("AccessionNumber"))
```

---

## Putting It All Together

```python
def triage_study(study_uid: str, study_metadata: dict, pixel_data: np.ndarray,
                 voxel_spacing: tuple[float, float, float]) -> dict:
    """
    Run the full multi-modality triage pipeline for one imaging study.

    Steps:
      1. Classify the study and select applicable models
      2. For each model: preprocess and invoke inference
      3. Aggregate all findings and assign priority
      4. Store results and alert if critical

    Args:
        study_uid: DICOM StudyInstanceUID.
        study_metadata: dict of DICOM header fields.
        pixel_data: numpy array of pixel/voxel data.
        voxel_spacing: (slice_spacing, row_spacing, col_spacing) in mm.

    Returns:
        Triage result record from DynamoDB.
    """
    logger.info("Starting triage for study %s", study_uid)

    # Step 1: Determine which models to run.
    selected_models = classify_study_and_select_models(study_metadata)

    if not selected_models:
        logger.info("No applicable models for study %s. Assigning ROUTINE.", study_uid)
        return store_triage_result(
            study_uid=study_uid,
            study_metadata=study_metadata,
            priority="ROUTINE",
            all_findings=[],
            triggering_findings=[],
            models_invoked=[],
        )

    logger.info("Selected %d model(s): %s",
                len(selected_models),
                [m["model_name"] for m in selected_models])

    # Step 2: Preprocess and invoke each model.
    all_findings = []
    models_invoked = []

    for model_config in selected_models:
        model_name = model_config["model_name"]
        logger.info("  Running model: %s", model_name)

        try:
            preprocessed = preprocess_for_model(pixel_data, model_config, voxel_spacing)
            findings = invoke_model(model_config, preprocessed)

            # Tag each finding with the model that produced it (for audit).
            for f in findings:
                f["source_model"] = model_name

            all_findings.extend(findings)
            models_invoked.append(model_name)

        except Exception as e:
            # Model failure should not block triage of other models.
            # Log the error, continue with remaining models.
            logger.error("Model %s failed for study %s: %s", model_name, study_uid, str(e))
            continue

    # Step 3: Assign priority based on combined findings.
    priority, triggering_findings = assign_priority(all_findings)
    logger.info("  Priority assigned: %s (%d triggering findings)",
                priority, len(triggering_findings))

    # Step 4: Store and alert.
    result = store_triage_result(
        study_uid=study_uid,
        study_metadata=study_metadata,
        priority=priority,
        all_findings=all_findings,
        triggering_findings=triggering_findings,
        models_invoked=models_invoked,
    )

    return result


# ----- Example: Simulate a triage run with synthetic data -----

if __name__ == "__main__":
    # Synthetic CT Head study metadata (mimics what you'd parse from DICOM headers).
    synthetic_metadata = {
        "StudyInstanceUID": "1.2.840.113619.2.55.3.12345.2026.05.31.12.00.00",
        "Modality": "CT",
        "BodyPartExamined": "HEAD",
        "StudyDescription": "CT HEAD W/O CONTRAST",
        "ProtocolName": "CT Head Routine",
        "PatientID": "SYNTH-001",
        "AccessionNumber": "ACC-2026-0531-001",
        "ReferringPhysicianName": "Dr. Smith",
    }

    # Synthetic pixel data: random noise shaped like a CT head volume.
    # 200 slices, 512x512 pixels each. Values in Hounsfield Units range.
    synthetic_volume = np.random.randint(-1000, 1000, size=(200, 512, 512)).astype(np.float32)

    # Typical CT head spacing: 0.5mm slice thickness, 0.5mm x 0.5mm pixel spacing.
    synthetic_spacing = (0.5, 0.5, 0.5)

    print("=" * 60)
    print("Radiology AI Triage: Synthetic CT Head Study")
    print("=" * 60)

    # Step 1: Classify
    models = classify_study_and_select_models(synthetic_metadata)
    print(f"\nSelected models: {[m['model_name'] for m in models]}")

    # Step 2: Preprocess (demonstrate without calling SageMaker)
    if models:
        model = models[0]
        preprocessed = preprocess_for_model(synthetic_volume, model, synthetic_spacing)
        print(f"Preprocessed shape for {model['model_name']}: {preprocessed.shape}")
        print(f"Value range: [{preprocessed.min():.3f}, {preprocessed.max():.3f}]")

    # Step 3: Simulate findings (since we can't call real endpoints here)
    simulated_findings = [
        {"finding": "intracranial_hemorrhage", "confidence": 0.92,
         "subtype": "subdural", "location": {"hemisphere": "left", "slice_range": [45, 62]}},
        {"finding": "midline_shift", "confidence": 0.78, "shift_mm": 3.1},
    ]

    # Step 4: Priority assignment
    priority, triggers = assign_priority(simulated_findings)
    print(f"\nSimulated findings: {len(simulated_findings)}")
    print(f"Assigned priority: {priority}")
    print(f"Triggering findings: {[t['finding'] for t in triggers]}")

    # Note: store_triage_result and _send_critical_alert would require
    # actual AWS resources. Uncomment below to run against real infrastructure.
    #
    # result = triage_study(
    #     study_uid=synthetic_metadata["StudyInstanceUID"],
    #     study_metadata=synthetic_metadata,
    #     pixel_data=synthetic_volume,
    #     voxel_spacing=synthetic_spacing,
    # )
    # print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the orchestration skeleton: classify a study, route to models, invoke endpoints, aggregate findings, assign priority, store results, and alert. The distance between this and a production radiology AI triage system is substantial. Here's where it lives.

**DICOM ingestion and study completion detection.** This example starts with pixel data already in a numpy array. In production, you need a DICOM receiver (C-STORE SCP) that accepts incoming instances from scanners, buffers them by StudyInstanceUID, detects when a study is complete (no standard "done" signal exists in DICOM), and then triggers the pipeline. AWS HealthImaging handles much of this, but the study completion logic (timeout-based or instance-count-based) is yours to build. Getting this wrong means either processing incomplete studies (missing slices produce wrong inference) or waiting too long (defeating the purpose of fast triage).

**Real model deployment and versioning.** The SageMaker endpoint calls here assume models are already deployed. Training, validating, and deploying radiology AI models is its own multi-month effort per clinical indication. Each model needs FDA 510(k) clearance (or De Novo if novel). Model versioning must be traceable: when a finding is produced, you need to know exactly which model version produced it, months or years later. SageMaker Model Registry handles versioning, but the regulatory documentation around each version is manual work.

**Preprocessing fidelity.** The preprocessing in this example is deliberately simplified (nearest-neighbor resampling, basic windowing). Production preprocessing must handle: DICOM photometric interpretation (MONOCHROME1 vs MONOCHROME2), rescale slope/intercept for HU conversion, varying bit depths (12-bit vs 16-bit), different reconstruction kernels (soft tissue vs bone), multi-frame DICOM objects, and compressed transfer syntaxes (JPEG2000, JPEG-LS). Use `pydicom` with `gdcm` or `pillow` plugins for decompression. Every preprocessing inconsistency between training and inference degrades model performance silently.

**PACS/RIS worklist integration.** This example stores results in DynamoDB and sends SNS alerts. A real deployment needs to modify the radiologist's worklist priority in their PACS system. This happens via HL7 ORM messages (for RIS-managed worklists) or DICOM Modality Worklist modifications (for PACS-managed worklists). The integration is vendor-specific: Epic Radiant, GE Centricity, Sectra, Fuji Synapse all have different interfaces. Some support FHIR-based worklist APIs. Most require custom integration work with the PACS vendor's professional services team. Budget 3-6 months for this integration alone.

**False positive management and threshold tuning.** The confidence thresholds in PRIORITY_RULES are starting points. In production, you need a feedback loop: when a radiologist reads a study that was flagged as STAT, did they agree with the finding? Track true positive rate, false positive rate, and time-to-read for flagged vs unflagged studies. If false positive rate exceeds 5-10%, radiologists will ignore the system within weeks. Threshold tuning is ongoing, not a one-time configuration.

**Multi-model latency and parallelism.** This example runs models sequentially. A study that needs three models (PE + pneumothorax + aortic dissection for a CT chest) would take 3x the inference time. Production runs applicable models in parallel using Step Functions parallel states or Lambda fan-out. Target total pipeline latency under 2 minutes from study completion to worklist update. Monitor P95 latency, not just average.

**Error handling and graceful degradation.** If one model's endpoint is down, the pipeline should still run the other models and triage based on available results. The example catches exceptions per model, but production needs: circuit breakers on endpoints, fallback to lower-priority models, alerting on sustained model failures, and clear documentation of which findings are covered when a model is degraded. A triage system that goes fully offline during a model deployment is a patient safety gap.

**Audit trail and regulatory compliance.** FDA-cleared medical device software requires complete audit trails. Every inference must be traceable: input data, model version, preprocessing parameters, raw model output, post-processing logic, final priority assignment, and radiologist acknowledgment. The DynamoDB record in this example captures most of this, but production also needs: immutable storage (S3 with Object Lock for inference inputs/outputs), CloudTrail for all API calls, and retention policies aligned with medical record retention requirements (typically 7-10 years, longer for pediatric cases).

**Monitoring and drift detection.** Model performance degrades over time as scanner hardware changes, patient populations shift, and imaging protocols evolve. Monitor: inference confidence distributions (a sudden drop in average confidence suggests distribution shift), false positive rates (from radiologist feedback), latency percentiles, and endpoint error rates. Set CloudWatch alarms on all of these. Retrain and revalidate models on a regular cadence (quarterly is common for radiology AI).

**Testing with realistic data.** The synthetic random noise in the example produces meaningless inference results. For development testing, use public radiology datasets: NIH ChestX-ray14, RSNA Intracranial Hemorrhage Detection Challenge, CQ500, LIDC-IDRI for lung CT. For integration testing, create synthetic DICOM studies with realistic metadata and known findings. Never use real patient imaging outside of production environments with full HIPAA controls.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.7: Radiology AI Triage (Multi-Modality)](chapter09.07-radiology-ai-triage-multi-modality) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
