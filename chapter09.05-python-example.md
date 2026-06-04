# Recipe 9.5: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 9.5. It shows one way you could translate those concepts into working Python code using boto3 and a few standard libraries. It is not production-ready. There's no PACS integration, no real DICOM routing, and the "model" here is a mock that returns synthetic predictions. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a radiology department on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image-handling libraries:

```bash
pip install boto3 numpy Pillow pydicom
```

`pydicom` handles DICOM file parsing (the standard format for medical images). `Pillow` and `numpy` handle image manipulation and array operations. In a real deployment, you'd also want a deep learning framework (PyTorch or TensorFlow) for local preprocessing, but for this example we keep it to standard libraries and let SageMaker handle the model.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, and `dynamodb:GetItem`.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the triage logic. These thresholds and weights are the most important tunable parameters in the system. In production, you'd calibrate them on your institution's validation data with radiologist input. The values below are reasonable starting points based on published literature, but your mileage will vary.

```python
# FINDING_THRESHOLDS: probability thresholds per finding category.
# If the model's predicted probability exceeds this threshold, the finding
# is considered "triggered" and contributes to the triage priority.
#
# Lower threshold = more sensitive (fewer misses, more false alarms).
# Higher threshold = more specific (fewer false alarms, more misses).
#
# These are NOT arbitrary. They should be calibrated on a validation set
# from your institution, targeting a specific sensitivity/specificity tradeoff
# that your radiologists agree is acceptable.

FINDING_THRESHOLDS = {
    "pneumothorax": 0.60,       # life-threatening; err on the side of alerting
    "tension_pneumo": 0.50,     # immediately life-threatening; very low threshold
    "large_effusion": 0.70,     # clinically significant but less emergent
    "pulmonary_edema": 0.70,    # urgent but not immediately life-threatening
    "mass_or_nodule": 0.75,     # important but not time-critical in minutes
    "cardiomegaly": 0.80,       # relevant but rarely emergent
}

# SEVERITY_WEIGHTS: how much each finding contributes to the composite score.
# Higher weight = more influence on the final priority decision.
# A tension pneumothorax (weight 10) dominates the score; cardiomegaly (weight 2)
# barely moves the needle unless combined with other findings.

SEVERITY_WEIGHTS = {
    "tension_pneumo": 10,
    "pneumothorax": 8,
    "large_effusion": 6,
    "pulmonary_edema": 6,
    "mass_or_nodule": 4,
    "cardiomegaly": 2,
}

# Model input dimensions. The preprocessing step resizes all images to this size.
# Must match what the model was trained on. Common choices: 224x224, 512x512.
# Larger inputs preserve more detail but increase inference latency.
MODEL_INPUT_SIZE = (512, 512)

# SageMaker endpoint name. This identifies which deployed model to call.
SAGEMAKER_ENDPOINT_NAME = "cxr-triage-model-v2"

# DynamoDB table for storing triage results.
DYNAMODB_TABLE_NAME = "cxr-triage-results"

# S3 bucket for incoming DICOM files.
DICOM_BUCKET = "radiology-dicom-inbox"
```

---

## Step 1: Receive and Filter DICOM Studies

*The pseudocode calls this `route_study(bucket, key)`. It reads DICOM metadata from the file header and checks whether this study is a chest X-ray. Non-chest studies are skipped entirely.*

```python
import logging
import boto3
import numpy as np
from botocore.config import Config
from io import BytesIO

# pydicom reads DICOM files: the standard format for medical images.
# DICOM files contain both metadata (patient info, study type, acquisition
# parameters) and pixel data (the actual image).
import pydicom

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# PHI Safety: Never log patient identifiers, accession numbers, or pixel data.

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)


def load_dicom_from_s3(bucket: str, key: str) -> pydicom.Dataset:
    """
    Download a DICOM file from S3 and parse it into a pydicom Dataset.

    Args:
        bucket: S3 bucket name
        key:    S3 object key (path to the DICOM file)

    Returns:
        A pydicom Dataset containing both metadata and pixel data.
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    dicom_bytes = response["Body"].read()

    # pydicom.dcmread can read from a file-like object.
    # We wrap the bytes in BytesIO to give it a file interface.
    dataset = pydicom.dcmread(BytesIO(dicom_bytes))
    return dataset


def is_chest_xray(dataset: pydicom.Dataset) -> bool:
    """
    Check DICOM metadata to determine if this study is a chest X-ray.

    We filter on two criteria:
    1. Modality must be CR (Computed Radiography) or DX (Digital Radiography).
       These are the two modality codes used for plain X-rays.
    2. BodyPartExamined must be CHEST (or a close variant).

    This prevents us from running knee X-rays, hand films, or CT scans
    through a model trained exclusively on chest radiographs.
    """
    # DICOM tag (0008,0060) = Modality
    modality = getattr(dataset, "Modality", "").upper()

    # DICOM tag (0018,0015) = BodyPartExamined
    body_part = getattr(dataset, "BodyPartExamined", "").upper()

    is_xray = modality in ("CR", "DX")
    is_chest = body_part in ("CHEST", "THORAX")

    return is_xray and is_chest


def route_study(bucket: str, key: str) -> dict | None:
    """
    Load a DICOM file and decide whether it should be triaged.

    Returns:
        A dict with study metadata if this is a chest X-ray, or None if skipped.
    """
    dataset = load_dicom_from_s3(bucket, key)

    if not is_chest_xray(dataset):
        logger.info("Skipping non-chest study: %s (Modality=%s, BodyPart=%s)",
                    key,
                    getattr(dataset, "Modality", "unknown"),
                    getattr(dataset, "BodyPartExamined", "unknown"))
        return None

    # Extract metadata we'll need downstream.
    # StudyInstanceUID is the globally unique identifier for this imaging study.
    # AccessionNumber is the local identifier used by the radiology department.
    study_metadata = {
        "study_instance_uid": str(getattr(dataset, "StudyInstanceUID", "")),
        "accession_number": str(getattr(dataset, "AccessionNumber", "")),
        "patient_id": str(getattr(dataset, "PatientID", "")),
        "modality": str(getattr(dataset, "Modality", "")),
        "view_position": str(getattr(dataset, "ViewPosition", "")),
        "s3_bucket": bucket,
        "s3_key": key,
    }

    logger.info("Chest X-ray identified: accession=%s", study_metadata["accession_number"])
    return study_metadata
```

---

## Step 2: Preprocess the DICOM Image for Model Input

*The pseudocode calls this `preprocess_for_inference(bucket, key)` and loads from S3 internally. Here we accept a pre-loaded `pydicom.Dataset` to avoid a redundant S3 read, since the full pipeline function already has the dataset in memory from Step 1. The preprocessing logic is identical.*

```python
from PIL import Image


def preprocess_for_inference(dataset: pydicom.Dataset) -> np.ndarray:
    """
    Convert raw DICOM pixel data into a normalized, resized array ready for
    the inference model.

    The preprocessing pipeline:
    1. Extract pixel array from DICOM
    2. Handle photometric interpretation (invert if MONOCHROME1)
    3. Apply windowing if specified in DICOM headers
    4. Normalize to [0, 1] range
    5. Resize to model input dimensions

    This MUST match the preprocessing used during model training.
    Even small differences (different interpolation method, different
    normalization range) can degrade model accuracy significantly.
    """
    # Extract the raw pixel array. This is typically a 2D numpy array
    # of integers (12-bit or 16-bit depending on the equipment).
    pixel_array = dataset.pixel_array.astype(np.float32)

    # Handle photometric interpretation.
    # MONOCHROME1: high pixel values = dark (air appears white, bone appears dark).
    # MONOCHROME2: high pixel values = bright (the standard for display and most models).
    # Most chest X-ray models expect MONOCHROME2 convention.
    photometric = getattr(dataset, "PhotometricInterpretation", "MONOCHROME2")
    if photometric == "MONOCHROME1":
        # Invert: subtract from max value so high = bright.
        pixel_array = pixel_array.max() - pixel_array

    # Apply windowing if the DICOM file specifies window center/width.
    # Windowing maps the full dynamic range to a clinically relevant subset.
    # This mimics what the radiologist sees on their display.
    window_center = getattr(dataset, "WindowCenter", None)
    window_width = getattr(dataset, "WindowWidth", None)

    if window_center is not None and window_width is not None:
        # Handle the case where these are stored as lists (multi-value).
        if isinstance(window_center, pydicom.multival.MultiValue):
            window_center = float(window_center[0])
            window_width = float(window_width[0])
        else:
            window_center = float(window_center)
            window_width = float(window_width)

        # Apply the window: clip values outside the window range.
        lower = window_center - window_width / 2
        upper = window_center + window_width / 2
        pixel_array = np.clip(pixel_array, lower, upper)

    # Normalize to [0, 1] range.
    # Neural networks expect inputs in a small, consistent numeric range.
    pmin, pmax = pixel_array.min(), pixel_array.max()
    if pmax > pmin:
        pixel_array = (pixel_array - pmin) / (pmax - pmin)
    else:
        # Completely uniform image (shouldn't happen with real data, but be safe).
        pixel_array = np.zeros_like(pixel_array)

    # Resize to model input dimensions using Pillow.
    # We convert to a PIL Image, resize with bilinear interpolation,
    # then convert back to numpy. Bilinear is the standard choice for
    # medical imaging (preserves detail better than nearest-neighbor,
    # less blurring than bicubic at these resolutions).
    img = Image.fromarray((pixel_array * 255).astype(np.uint8), mode="L")
    img_resized = img.resize(MODEL_INPUT_SIZE, resample=Image.BILINEAR)
    pixel_array = np.array(img_resized, dtype=np.float32) / 255.0

    return pixel_array
```

---

## Step 3: Run Inference on the SageMaker Endpoint

*The pseudocode calls this `run_inference(preprocessed_image, study_id)`. The preprocessed image is serialized and sent to the SageMaker real-time endpoint. The model returns probability scores for each finding category.*

```python
import json

sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)


def run_inference(preprocessed_image: np.ndarray, study_id: str) -> dict:
    """
    Send the preprocessed image to the SageMaker endpoint and get predictions.

    The endpoint hosts a trained CNN (e.g., DenseNet-121 or EfficientNet)
    that outputs a probability score for each finding category.

    Args:
        preprocessed_image: A 2D numpy array, normalized to [0, 1], resized
                           to MODEL_INPUT_SIZE.
        study_id:          The StudyInstanceUID for logging/audit.

    Returns:
        A dict mapping finding names to probability scores.
        Example: {"pneumothorax": 0.92, "cardiomegaly": 0.06, ...}
    """
    # Serialize the image as a numpy array in bytes format.
    # The SageMaker endpoint expects the raw bytes of a float32 array.
    # We add a batch dimension (1, H, W) because the model expects batched input
    # even for a single image.
    # Note: We use raw bytes with application/x-npy content type. If your endpoint's
    # inference container expects proper .npy format (with shape/dtype header),
    # serialize with np.save() to a BytesIO buffer instead.
    image_batch = preprocessed_image.reshape(1, *MODEL_INPUT_SIZE).astype(np.float32)
    payload = image_batch.tobytes()

    # Call the SageMaker real-time inference endpoint.
    # ContentType tells the endpoint how to deserialize our input.
    # Accept tells it what format we want the response in.
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/x-npy",
        Accept="application/json",
        Body=payload,
    )

    # Parse the JSON response body.
    # Expected format: {"predictions": {"pneumothorax": 0.92, ...}}
    result = json.loads(response["Body"].read().decode("utf-8"))
    predictions = result.get("predictions", {})

    logger.info("Inference complete for study %s: %d findings scored",
                study_id, len(predictions))

    return predictions
```

---

## Step 4: Calculate Priority Score

*The pseudocode calls this `calculate_priority(predictions)`. This converts raw probability scores into a clinical triage decision by applying finding-specific thresholds and severity weights.*

```python
def calculate_priority(predictions: dict) -> dict:
    """
    Convert model predictions into a triage priority decision.

    Logic:
    1. For each finding, check if its probability exceeds the threshold.
    2. Triggered findings contribute to a composite score (probability * weight).
    3. The composite score and the maximum severity of triggered findings
       determine the final priority level.

    Priority levels:
    - CRITICAL: Immediate radiologist attention (pneumothorax, tension)
    - URGENT:   Move to top of worklist (significant composite score)
    - ELEVATED: Slight priority boost (minor findings flagged)
    - ROUTINE:  Normal queue order (nothing above threshold)

    Returns:
        A dict with priority level, composite score, and triggered findings.
    """
    triggered_findings = []
    composite_score = 0.0

    for finding, probability in predictions.items():
        threshold = FINDING_THRESHOLDS.get(finding)
        if threshold is None:
            # Finding not in our threshold map; skip it.
            continue

        if probability >= threshold:
            severity = SEVERITY_WEIGHTS.get(finding, 1)
            triggered_findings.append({
                "finding": finding,
                "probability": round(probability, 4),
                "severity": severity,
            })
            composite_score += probability * severity

    # Determine priority level.
    max_severity = max((f["severity"] for f in triggered_findings), default=0)

    if max_severity >= 8:
        priority = "CRITICAL"
    elif composite_score >= 5.0:
        priority = "URGENT"
    elif len(triggered_findings) > 0:
        priority = "ELEVATED"
    else:
        priority = "ROUTINE"

    return {
        "priority": priority,
        "composite_score": round(composite_score, 2),
        "triggered_findings": triggered_findings,
    }
```

---

## Step 5: Store Results in DynamoDB

*The pseudocode calls this `store_and_notify(study_id, accession_number, patient_id, priority_result)`. Every inference result is persisted for audit and compliance. Critical/urgent findings also trigger a worklist update.*

```python
import datetime
from datetime import timezone
from decimal import Decimal

dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def store_triage_result(
    study_metadata: dict,
    predictions: dict,
    priority_result: dict,
    inference_latency_ms: float,
) -> dict:
    """
    Write the triage result to DynamoDB for audit and downstream consumption.

    This record is the authoritative output of the pipeline for this study.
    It captures: what was analyzed, what the model predicted, what priority
    was assigned, how long inference took, and when. This supports both
    HIPAA audit requirements and FDA post-market surveillance.

    Args:
        study_metadata:     Metadata from the DICOM file (study ID, accession, etc.)
        predictions:        Raw model predictions (all finding probabilities)
        priority_result:    Output of calculate_priority (priority level, score, findings)
        inference_latency_ms: How long the SageMaker call took

    Returns:
        The complete record that was written.
    """
    table = dynamodb.Table(DYNAMODB_TABLE_NAME)

    # DynamoDB does not accept Python floats. You must wrap numeric values
    # in Decimal() or put_item will raise a TypeError.
    # Convert via string to avoid floating-point representation artifacts.
    def to_decimal(val):
        return Decimal(str(round(val, 4)))

    record = {
        "study_id": study_metadata["study_instance_uid"],
        "accession_number": study_metadata["accession_number"],
        "patient_id": study_metadata["patient_id"],
        "s3_key": study_metadata["s3_key"],
        "model_version": "cxr-triage-v2.1",
        "inference_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "inference_latency_ms": to_decimal(inference_latency_ms),
        "priority": priority_result["priority"],
        "composite_score": to_decimal(priority_result["composite_score"]),
        "triggered_findings": [
            {
                "finding": f["finding"],
                "probability": to_decimal(f["probability"]),
                "severity": f["severity"],
            }
            for f in priority_result["triggered_findings"]
        ],
        "all_predictions": {
            finding: to_decimal(prob)
            for finding, prob in predictions.items()
        },
    }

    table.put_item(Item=record)
    logger.info("Stored triage result: study=%s priority=%s",
                record["study_id"], record["priority"])

    return record
```

---

## Full Pipeline Function

This assembles all steps into a single callable function. In production, this would be triggered by an S3 event notification (new DICOM file lands in the inbox bucket) routed through Lambda.

```python
import time


def triage_chest_xray(bucket: str, key: str) -> dict | None:
    """
    Full triage pipeline: receive DICOM, filter, preprocess, infer, score, store.

    Args:
        bucket: S3 bucket containing the DICOM file
        key:    S3 object key for the DICOM file

    Returns:
        The triage result record if the study was processed, or None if skipped.
    """
    print(f"[1/5] Loading and filtering study: s3://{bucket}/{key}")
    study_metadata = route_study(bucket, key)

    if study_metadata is None:
        print("      Not a chest X-ray. Skipping.")
        return None

    print(f"      Chest X-ray confirmed. Accession: {study_metadata['accession_number']}")

    # Reload the full DICOM for pixel data (route_study already parsed it,
    # but in a Lambda architecture these would be separate invocations).
    dataset = load_dicom_from_s3(bucket, key)

    print("[2/5] Preprocessing DICOM image for model input...")
    preprocessed = preprocess_for_inference(dataset)
    print(f"      Image resized to {MODEL_INPUT_SIZE}, normalized to [0,1]")

    print("[3/5] Running inference on SageMaker endpoint...")
    start_time = time.time()
    predictions = run_inference(preprocessed, study_metadata["study_instance_uid"])
    inference_latency_ms = (time.time() - start_time) * 1000
    print(f"      Inference complete in {inference_latency_ms:.0f}ms")
    print(f"      Predictions: {predictions}")

    print("[4/5] Calculating triage priority...")
    priority_result = calculate_priority(predictions)
    print(f"      Priority: {priority_result['priority']} "
          f"(composite score: {priority_result['composite_score']})")

    if priority_result["triggered_findings"]:
        for f in priority_result["triggered_findings"]:
            print(f"      -> {f['finding']}: {f['probability']} "
                  f"(severity {f['severity']})")

    print("[5/5] Storing result to DynamoDB...")
    record = store_triage_result(
        study_metadata, predictions, priority_result, inference_latency_ms
    )
    print(f"      Stored. Study ID: {record['study_id']}")

    if priority_result["priority"] in ("CRITICAL", "URGENT"):
        print(f"\n      *** ALERT: {priority_result['priority']} finding detected! ***")
        print(f"      Worklist update would be sent for accession "
              f"{study_metadata['accession_number']}")

    return record


# Example usage (you'd replace this with your actual S3 event trigger):
if __name__ == "__main__":
    result = triage_chest_xray(
        bucket=DICOM_BUCKET,
        key="inbox/2026/03/15/study-048291.dcm",
    )
    if result:
        print(f"\nFinal priority: {result['priority']}")
```

---

## Synthetic Test Data

Since you can't (and shouldn't) use real patient DICOM files for development, here's how to generate a synthetic chest X-ray DICOM file for testing the pipeline. This creates a valid DICOM file with proper metadata but random pixel data. The model will produce meaningless predictions on random noise, but the pipeline mechanics (routing, preprocessing, endpoint invocation, storage) can all be validated.

```python
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import generate_uid
import tempfile
import os


def create_synthetic_chest_xray_dicom() -> str:
    """
    Generate a synthetic DICOM file that looks like a chest X-ray to the pipeline.

    The pixel data is random noise (not a real chest X-ray), but the DICOM
    metadata is set correctly so the routing logic identifies it as a chest
    X-ray and the preprocessing handles it properly.

    Returns:
        Path to the temporary DICOM file.
    """
    filename = os.path.join(tempfile.gettempdir(), "synthetic_cxr.dcm")

    # Create the DICOM file dataset.
    file_meta = pydicom.Dataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"  # Digital X-Ray
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian

    ds = FileDataset(filename, {}, file_meta=file_meta, preamble=b"\x00" * 128)

    # Set metadata that our routing logic checks.
    ds.Modality = "DX"
    ds.BodyPartExamined = "CHEST"
    ds.ViewPosition = "PA"
    ds.PhotometricInterpretation = "MONOCHROME2"

    # Patient/study identifiers (synthetic, not real PHI).
    ds.PatientID = "SYNTH-001"
    ds.StudyInstanceUID = generate_uid()
    ds.AccessionNumber = "CXR-TEST-001"

    # Image dimensions and pixel data.
    ds.Rows = 1024
    ds.Columns = 1024
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1

    # Random pixel data (noise, not a real image).
    ds.PixelData = np.random.randint(0, 4096, (1024, 1024), dtype=np.uint16).tobytes()

    ds.save_as(filename)
    return filename
```

---

## Gap to Production

This example demonstrates the pipeline shape. Here's what you'd need to add before deploying to a radiology department:

**Error handling and retries.** The SageMaker endpoint can throttle, timeout, or return errors. Wrap the `invoke_endpoint` call in retry logic with exponential backoff. If inference fails, the study should fall back to normal queue ordering (never block a study from being read because the AI is down).

**DICOM routing at scale.** In production, you'd use a DICOM router (like Orthanc or a commercial solution) that forwards studies to S3 via a DICOM-to-S3 bridge. The S3 event notification triggers a Lambda function. This example skips the DICOM networking layer entirely.

**PACS worklist integration.** The hardest part of the real system. You need to send priority updates back to your PACS/RIS. This typically involves HL7 ORM messages via an interface engine (Mirth Connect, Rhapsody) or vendor-specific APIs. Every PACS installation is different. Budget 2-3 months for this integration alone.

**Model serving.** This example assumes a SageMaker endpoint is already deployed. In practice, you need: model packaging (container with inference code), endpoint configuration (instance type, auto-scaling policy), model registry (version tracking), and A/B testing infrastructure for model updates.

**Input validation.** Validate DICOM files before processing: check for corrupt pixel data, unsupported transfer syntaxes, missing required tags, and unexpected image dimensions. Malformed DICOM files should be quarantined, not crash the pipeline.

**Structured logging.** Replace print statements with structured JSON logging (using `aws_lambda_powertools` or similar). Log inference latency, prediction distributions, and error rates. Never log PHI (patient IDs, accession numbers should be hashed or omitted from logs in production).

**IAM least-privilege.** The example uses broad permissions. In production, scope IAM policies to specific resources: the exact S3 bucket and prefix, the exact DynamoDB table, the exact SageMaker endpoint ARN.

**VPC and VPC endpoints.** Lambda and SageMaker should run in a VPC with no internet access. Use VPC endpoints for S3, DynamoDB, SageMaker Runtime, and CloudWatch Logs. This prevents PHI from traversing the public internet.

**KMS customer-managed keys.** Use CMKs (not AWS-managed keys) for S3, DynamoDB, and SageMaker volume encryption. This gives you key rotation control and the ability to revoke access by disabling the key.

**Model monitoring and drift detection.** Track the distribution of prediction scores over time. If the model suddenly starts predicting pneumothorax at 2x the historical rate, something changed (new equipment, different patient population, model degradation). CloudWatch custom metrics and alarms catch this.

**FDA compliance (if building in-house).** If you're deploying this as a medical device (not buying a commercial product), you need: 510(k) submission, Quality Management System, design controls documentation, risk analysis (ISO 14971), software lifecycle documentation (IEC 62304), and a post-market surveillance plan. This is 12-18 months of regulatory work.

**Radiologist feedback loop.** Capture whether the radiologist agreed with the triage decision. Store agreement/disagreement in DynamoDB alongside the original prediction. Use disagreements to identify systematic errors and inform model retraining.

**Testing.** Unit tests for preprocessing (known DICOM inputs produce expected arrays). Integration tests against a SageMaker endpoint with known test images. End-to-end tests with synthetic DICOM files through the full pipeline. Performance tests to verify sub-5-second latency under load.

---

*← [Recipe 9.5: Chest X-Ray Triage](chapter09.05-chest-xray-triage) · [Chapter 9 Index](chapter09-preface) · [Next: Recipe 9.6: Diabetic Retinopathy Screening →](chapter09.06-diabetic-retinopathy-screening)*
