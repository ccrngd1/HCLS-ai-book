# Recipe 9.4: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 9.4. It shows one way you could wire up the dermatology lesion triage pipeline using boto3 and basic image processing. It is not production-ready. There's no real trained model here (we simulate inference for demonstration), no FDA-compliant validation suite, and no clinical workflow integration. Think of it as the wiring diagram: useful for understanding how the pieces connect, not something you'd point at real patient photos on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image processing libraries:

```bash
pip install boto3 pillow numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `sagemaker:InvokeEndpoint` (for the classification model)
- `s3:PutObject`, `s3:GetObject` (for image storage)
- `dynamodb:PutItem`, `dynamodb:GetItem` (for case tracking)
- `sns:Publish` (for urgent case notifications)

---

## Config and Constants

Before we get to the pipeline steps, here's the configuration that drives triage decisions. These thresholds are clinical decisions made in collaboration with dermatology leadership, not engineering choices. They determine the sensitivity/specificity tradeoff and will need adjustment as you gather real-world outcome data.

```python
# TRIAGE_THRESHOLDS: Clinical decision thresholds for routing.
# These numbers determine how aggressively the system escalates.
# Lower URGENT_THRESHOLD = more cases flagged urgent = higher sensitivity but more false alarms.
# Higher URGENT_THRESHOLD = fewer urgent flags = fewer false alarms but risk of missed melanomas.
#
# Set these with your dermatology department. Review quarterly against outcome data.
# The values below are illustrative starting points, not validated clinical thresholds.

TRIAGE_THRESHOLDS = {
    "urgent": 0.70,       # Above this: immediate dermatology review
    "suspicious": 0.40,   # Above this: expedited scheduling (within 2 weeks)
    # Below suspicious: standard follow-up recommendation
}

# IMAGE_QUALITY_THRESHOLDS: Minimum quality requirements before running inference.
# Rejecting bad images early saves compute cost and prevents garbage predictions
# from eroding clinician trust in the system.

IMAGE_QUALITY_THRESHOLDS = {
    "min_dimension": 224,       # Pixels. Model input size; below this there's not enough detail.
    "blur_threshold": 100.0,    # Laplacian variance. Below this = too blurry to trust.
    "min_brightness": 40,       # Mean pixel value. Below this = too dark.
    "max_brightness": 220,      # Mean pixel value. Above this = overexposed.
}

# MODEL_CONFIG: SageMaker endpoint configuration.
# Replace these with your actual endpoint name and input specifications.

MODEL_CONFIG = {
    "endpoint_name": "lesion-classifier-v2",    # Your SageMaker endpoint
    "input_size": 224,                          # Model expects 224x224 input
    "content_type": "application/x-npy",        # NumPy array format for this example
    # ImageNet normalization parameters (standard for models pre-trained on ImageNet)
    "normalize_mean": [0.485, 0.456, 0.406],
    "normalize_std": [0.229, 0.224, 0.225],
}

# TRIAGE_CATEGORIES: Maps model output indices to human-readable category names.
# The model outputs a probability for each class in this order.

TRIAGE_CATEGORIES = ["benign", "suspicious", "urgent"]

# AWS resource names. Replace with your actual resource names.
S3_BUCKET = "lesion-images-phi"
DYNAMODB_TABLE = "triage-cases"
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:urgent-derm-triage"
```

---

## Step 1: Image Quality Validation

*The pseudocode calls this `validate_image_quality(image_bytes)`. Before spending compute on inference, verify the submitted image is actually usable. A blurry bathroom selfie with bad lighting will produce meaningless predictions.*

```python
import io
import logging
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def validate_image_quality(image_bytes: bytes) -> dict:
    """
    Check whether a lesion photo meets minimum quality requirements.

    This is a fast, cheap gate that runs before the expensive ML inference step.
    It catches the most common failure modes: blurry photos, too dark, too bright,
    or too low resolution to be useful.

    Args:
        image_bytes: Raw bytes of the uploaded image (JPEG or PNG).

    Returns:
        A dict with:
        - "valid": bool indicating whether the image passes all checks
        - "reason": human-readable explanation if invalid (for user feedback)
        - "metrics": the computed quality metrics (for logging/debugging)
    """
    # Decode the image bytes into a PIL Image object.
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    # Convert to numpy array for numerical analysis.
    pixels = np.array(image, dtype=np.float32)

    # Check 1: Resolution.
    # The classification model expects 224x224 input. If the source image is
    # smaller than that, we'd be upscaling (inventing pixels), which degrades
    # accuracy. Require at least the model's input size.
    if width < IMAGE_QUALITY_THRESHOLDS["min_dimension"] or height < IMAGE_QUALITY_THRESHOLDS["min_dimension"]:
        return {
            "valid": False,
            "reason": "Image resolution too low. Please move closer to the lesion.",
            "metrics": {"width": width, "height": height},
        }

    # Check 2: Blur detection using Laplacian variance.
    # The Laplacian operator highlights edges. A sharp image has lots of strong
    # edges (high variance). A blurry image has weak, smeared edges (low variance).
    # We compute this on the grayscale version of the image.
    gray = np.mean(pixels, axis=2)  # Simple grayscale conversion
    # Laplacian kernel (approximation): highlights second-order intensity changes.
    # scipy would be cleaner here, but we keep dependencies minimal.
    laplacian = (
        gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
        - 4 * gray[1:-1, 1:-1]
    )
    blur_score = float(np.var(laplacian))

    if blur_score < IMAGE_QUALITY_THRESHOLDS["blur_threshold"]:
        return {
            "valid": False,
            "reason": "Image appears blurry. Please hold steady and ensure the camera is focused.",
            "metrics": {"blur_score": blur_score},
        }

    # Check 3: Brightness.
    # Too dark = lost detail in shadows. Too bright = washed out, lost color info.
    mean_brightness = float(np.mean(pixels))

    if mean_brightness < IMAGE_QUALITY_THRESHOLDS["min_brightness"]:
        return {
            "valid": False,
            "reason": "Image too dark. Please improve lighting.",
            "metrics": {"mean_brightness": mean_brightness},
        }

    if mean_brightness > IMAGE_QUALITY_THRESHOLDS["max_brightness"]:
        return {
            "valid": False,
            "reason": "Image too bright or overexposed. Reduce direct light on the lesion.",
            "metrics": {"mean_brightness": mean_brightness},
        }

    return {
        "valid": True,
        "reason": None,
        "metrics": {
            "width": width,
            "height": height,
            "blur_score": blur_score,
            "mean_brightness": mean_brightness,
        },
    }
```

---

## Step 2: Image Preprocessing

*The pseudocode calls this `preprocess_image(image_bytes, target_size)`. The classification model expects a specific input format: fixed dimensions, normalized pixel values, channel-wise standardization matching the training pipeline. If you preprocess differently than the training data was preprocessed, accuracy degrades silently.*

```python
def preprocess_image(image_bytes: bytes) -> bytes:
    """
    Transform a raw lesion photo into the format the classification model expects.

    This must exactly match the preprocessing used during model training.
    Differences in resize interpolation, normalization range, or channel ordering
    will silently degrade accuracy without any error message.

    Args:
        image_bytes: Raw bytes of the validated image.

    Returns:
        Serialized numpy array ready to send to the SageMaker endpoint.
    """
    target_size = MODEL_CONFIG["input_size"]
    mean = np.array(MODEL_CONFIG["normalize_mean"], dtype=np.float32)
    std = np.array(MODEL_CONFIG["normalize_std"], dtype=np.float32)

    # Load and resize to model input dimensions.
    # LANCZOS resampling preserves detail better than bilinear for downscaling.
    # Most training pipelines use bilinear or bicubic; match yours.
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image = image.resize((target_size, target_size), Image.LANCZOS)

    # Convert to float32 numpy array and normalize to [0, 1].
    # Raw pixel values are 0-255 integers. Neural networks expect small floats.
    pixels = np.array(image, dtype=np.float32) / 255.0

    # Apply ImageNet channel-wise normalization.
    # This centers each color channel around zero with unit variance,
    # matching what the pre-trained backbone (EfficientNet, ResNet, etc.)
    # was trained on. Without this, the first layers produce wrong activations.
    pixels = (pixels - mean) / std

    # Serialize as numpy bytes. SageMaker endpoints can accept various formats;
    # numpy is straightforward for image data. Your endpoint's input handler
    # must match this serialization.
    buffer = io.BytesIO()
    np.save(buffer, pixels)
    return buffer.getvalue()
```

---

## Step 3: Model Inference

*The pseudocode calls this `classify_lesion(preprocessed_payload, endpoint_name)`. Send the preprocessed image to the SageMaker endpoint and get back a probability distribution across triage categories.*

```python
import json
import boto3
from botocore.config import Config

# Adaptive retry handles transient throttling from SageMaker under load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)

def classify_lesion(preprocessed_payload: bytes) -> dict:
    """
    Invoke the SageMaker endpoint to classify a preprocessed lesion image.

    The endpoint hosts a trained CNN (e.g., EfficientNet fine-tuned on ISIC data)
    that outputs a probability distribution across triage categories.

    Args:
        preprocessed_payload: Serialized numpy array from preprocess_image().

    Returns:
        Dict mapping category names to probabilities.
        Example: {"benign": 0.22, "suspicious": 0.68, "urgent": 0.10}
    """
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=MODEL_CONFIG["endpoint_name"],
        ContentType=MODEL_CONFIG["content_type"],
        Body=preprocessed_payload,
    )

    # Parse the model's response. The exact format depends on your model server
    # (TorchServe, TensorFlow Serving, custom inference.py, etc.).
    # This assumes the endpoint returns a JSON array of probabilities
    # in the same order as TRIAGE_CATEGORIES.
    result_body = response["Body"].read().decode("utf-8")
    probabilities = json.loads(result_body)

    # Map the raw probability array to named categories.
    predictions = {}
    for i, category in enumerate(TRIAGE_CATEGORIES):
        predictions[category] = float(probabilities[i])

    return predictions
```

---

## Step 4: Triage Decision Logic

*The pseudocode calls this `determine_triage(predictions)`. Translate raw model probabilities into an actionable triage decision. The thresholds here are clinical decisions, not engineering ones.*

```python
def determine_triage(predictions: dict) -> dict:
    """
    Apply clinical thresholds to model predictions and produce a triage decision.

    The logic is simple: check urgent first (highest priority), then suspicious,
    then default to routine. If both urgent and suspicious are above threshold,
    urgent wins because patient safety takes priority over queue efficiency.

    Args:
        predictions: Dict of category -> probability from classify_lesion().

    Returns:
        Dict with:
        - "category": URGENT, SUSPICIOUS, or ROUTINE
        - "action": Human-readable recommendation for the clinician
        - "confidence": The probability score for the assigned category
        - "all_scores": Full probability distribution (for audit trail)
    """
    urgent_score = predictions.get("urgent", 0.0)
    suspicious_score = predictions.get("suspicious", 0.0)
    benign_score = predictions.get("benign", 0.0)

    # Check urgent first. A high urgent score means the model sees features
    # consistent with melanoma or other aggressive lesions.
    if urgent_score >= TRIAGE_THRESHOLDS["urgent"]:
        return {
            "category": "URGENT",
            "action": "Immediate dermatology review recommended",
            "confidence": urgent_score,
            "all_scores": predictions,
        }

    # Check suspicious next. Features that don't scream "urgent" but warrant
    # closer inspection sooner than the standard 30-90 day wait.
    if suspicious_score >= TRIAGE_THRESHOLDS["suspicious"]:
        return {
            "category": "SUSPICIOUS",
            "action": "Expedited dermatology appointment recommended (within 2 weeks)",
            "confidence": suspicious_score,
            "all_scores": predictions,
        }

    # Default: the model's highest confidence is in the benign category.
    # Standard monitoring with instructions to return if changes are observed.
    return {
        "category": "ROUTINE",
        "action": "Standard monitoring. Follow up if changes observed.",
        "confidence": benign_score,
        "all_scores": predictions,
    }
```

---

## Step 5: Store Results and Notify

*The pseudocode calls this `store_and_notify(case_id, patient_id, image_key, triage_result)`. Every triage case gets a permanent record for the dermatologist review queue, audit trail, and outcome tracking.*

```python
import datetime
import uuid
from datetime import timezone
from decimal import Decimal

dynamodb = boto3.resource("dynamodb")
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)

def store_and_notify(patient_id: str, image_key: str, triage_result: dict) -> dict:
    """
    Write the triage record to DynamoDB and send notifications for urgent cases.

    This record serves three purposes:
    1. The dermatology review queue pulls cases by priority.
    2. The audit trail shows what the AI recommended and when.
    3. Outcome tracking (dermatologist's actual diagnosis) enables model monitoring.

    Args:
        patient_id: De-identified patient identifier.
        image_key:  S3 key of the original lesion image.
        triage_result: Output from determine_triage().

    Returns:
        The complete case record that was written.
    """
    table = dynamodb.Table(DYNAMODB_TABLE)

    # Generate a unique case ID. In production, you might use a more structured
    # format that encodes date and facility for easier querying.
    case_id = f"TRIAGE-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}"

    # DynamoDB requires Decimal for numeric values, not float.
    # Wrap all scores in Decimal via string conversion to avoid floating-point artifacts.
    all_scores_decimal = {
        k: Decimal(str(round(v, 4))) for k, v in triage_result["all_scores"].items()
    }

    record = {
        "case_id": case_id,
        "patient_id": patient_id,
        "image_key": image_key,
        "triage_category": triage_result["category"],
        "triage_action": triage_result["action"],
        "model_confidence": Decimal(str(round(triage_result["confidence"], 4))),
        "all_scores": all_scores_decimal,
        "submitted_at": datetime.datetime.now(timezone.utc).isoformat(),
        "reviewed_by": None,            # Populated when dermatologist reviews
        "dermatologist_dx": None,       # Populated with actual diagnosis
        "status": "PENDING_REVIEW",
    }

    table.put_item(Item=record)
    logger.info("Stored triage case %s with category %s", case_id, triage_result["category"])

    # For urgent cases, send an immediate notification.
    # Don't rely on someone polling the queue for time-sensitive findings.
    if triage_result["category"] == "URGENT":
        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"URGENT Lesion Triage: {case_id}",
            Message=(
                f"Urgent lesion triage case requires immediate review.\n\n"
                f"Case ID: {case_id}\n"
                f"Patient: {patient_id}\n"
                f"Model confidence: {triage_result['confidence']:.2%}\n"
                f"Action: {triage_result['action']}\n"
            ),
        )
        logger.info("Sent urgent notification for case %s", case_id)

    return record
```

---

## Step 6: Upload Image to S3

*Before running the pipeline, the original image needs to land in encrypted S3 storage. This gives us a durable, auditable record of exactly what was submitted.*

```python
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

def upload_image(image_bytes: bytes, patient_id: str, filename: str) -> str:
    """
    Store the original lesion image in S3 with server-side KMS encryption.

    The S3 key structure organizes images by date and patient for easy retrieval.
    The original image is preserved exactly as submitted (no preprocessing)
    so the dermatologist sees what the patient actually photographed.

    Args:
        image_bytes: Raw image bytes as submitted.
        patient_id:  De-identified patient identifier.
        filename:    Original filename (for extension detection).

    Returns:
        The S3 object key where the image was stored.
    """
    today = datetime.date.today().isoformat()
    # Structure: lesion-images/{date}/{patient_id}/{unique_id}.{ext}
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "jpg"
    unique_id = uuid.uuid4().hex[:12]
    key = f"lesion-images/{today}/{patient_id}/{unique_id}.{ext}"

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentType=f"image/{ext}",
        ServerSideEncryption="aws:kms",
        # In production, specify your KMS key ID explicitly:
        # SSEKMSKeyId="arn:aws:kms:us-east-1:123456789012:key/your-key-id"
    )

    logger.info("Uploaded image to s3://%s/%s", S3_BUCKET, key)
    return key
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler or API endpoint would call.

```python
def triage_lesion(image_bytes: bytes, patient_id: str, filename: str) -> dict:
    """
    Run the full dermatology lesion triage pipeline for one submitted image.

    This is the main entry point. In a Lambda deployment, your handler would
    parse the API Gateway event, extract the image bytes and patient ID,
    and call this function.

    Args:
        image_bytes: Raw bytes of the submitted lesion photo.
        patient_id:  De-identified patient identifier.
        filename:    Original filename of the uploaded image.

    Returns:
        Dict with either:
        - A triage result (case_id, category, action, confidence) on success
        - A rejection reason if the image fails quality checks
    """
    # Step 1: Quality validation. Reject unusable images before spending
    # compute on inference. Return actionable feedback so the user can retake.
    logger.info("Step 1: Validating image quality")
    quality = validate_image_quality(image_bytes)
    if not quality["valid"]:
        logger.info("  Image rejected: %s", quality["reason"])
        return {
            "status": "REJECTED",
            "reason": quality["reason"],
            "metrics": quality["metrics"],
        }
    logger.info("  Quality OK: %s", quality["metrics"])

    # Step 2: Upload the original image to S3 for audit trail and dermatologist review.
    logger.info("Step 2: Uploading image to S3")
    image_key = upload_image(image_bytes, patient_id, filename)

    # Step 3: Preprocess the image to match model input requirements.
    logger.info("Step 3: Preprocessing image for model input")
    preprocessed = preprocess_image(image_bytes)

    # Step 4: Run inference on the SageMaker endpoint.
    logger.info("Step 4: Invoking classification model")
    predictions = classify_lesion(preprocessed)
    logger.info("  Predictions: %s", predictions)

    # Step 5: Apply clinical thresholds to determine triage category.
    logger.info("Step 5: Determining triage category")
    triage_result = determine_triage(predictions)
    logger.info("  Triage: %s (confidence: %.2f)", triage_result["category"], triage_result["confidence"])

    # Step 6: Store the case record and notify if urgent.
    logger.info("Step 6: Storing result and sending notifications")
    record = store_and_notify(patient_id, image_key, triage_result)

    logger.info("Done. Case %s -> %s", record["case_id"], record["triage_category"])
    return {
        "status": "TRIAGED",
        "case_id": record["case_id"],
        "triage_category": record["triage_category"],
        "triage_action": record["triage_action"],
        "model_confidence": float(record["model_confidence"]),
        "all_scores": {k: float(v) for k, v in record["all_scores"].items()},
    }

# Example usage with a local test image.
if __name__ == "__main__":
    # Load a test image (never use real patient photos in development).
    # Use synthetic or public dataset images (ISIC archive) for testing.
    import sys

    if len(sys.argv) < 2:
        print("Usage: python triage_pipeline.py <image_path> [patient_id]")
        sys.exit(1)

    image_path = sys.argv[1]
    patient_id = sys.argv[2] if len(sys.argv) > 2 else "TEST-PATIENT-001"

    with open(image_path, "rb") as f:
        image_data = f.read()

    result = triage_lesion(image_data, patient_id, image_path.split("/")[-1])
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example shows how the pieces connect. Run it against a test image with a deployed SageMaker endpoint and it will return a triage decision. But there's a meaningful distance between "works in a script" and "runs in a clinic triaging real patient photos." Here's where that gap lives:

**Model training and validation.** This example assumes you have a trained model deployed to a SageMaker endpoint. Actually training that model is a significant effort: curating a balanced dataset across skin tones and lesion types, implementing proper train/validation/test splits stratified by patient (not just by image), validating performance across Fitzpatrick skin types I-VI, and documenting the model card with intended use, limitations, and performance metrics. The model training pipeline is a separate project.

**Bias validation.** Before deploying to any patient population, you must measure and document model performance stratified by skin tone. If sensitivity drops below acceptable thresholds for any Fitzpatrick type, the model is not ready for that population. This isn't a nice-to-have. It's an equity requirement with real clinical consequences. Build a validation dataset that's representative of your actual patient demographics.

**Error handling and graceful degradation.** This code lets exceptions propagate. A production system catches specific failure modes: SageMaker endpoint throttling (retry with backoff), endpoint model errors (return "unable to triage, routing to manual review"), S3 upload failures (retry, then queue for later), DynamoDB write failures (dead-letter queue). The system should never silently lose a submission.

**Input validation and security.** This code trusts its inputs. A production system validates: file size limits (reject multi-GB uploads), file type verification (check magic bytes, not just extension), image dimension bounds, and patient ID format. Malformed inputs should be rejected at the API Gateway level before reaching Lambda.

**Capture UX and guidance.** The quality gate rejects bad images, but the real solution is preventing bad images in the first place. A production system includes a capture interface with: real-time focus and lighting feedback, positioning guides (distance, angle), reference markers for scale, and clear instructions. The capture UX is as important as the model.

**Regulatory documentation.** If this system's output influences clinical decisions (even as "triage only"), you need: a clear intended use statement, a clinical validation study, a model card documenting performance and limitations, a risk analysis (what happens when the model is wrong?), and regulatory counsel's sign-off on whether this constitutes a medical device under FDA guidance.

**Outcome tracking and model monitoring.** The `dermatologist_dx` field in the case record exists for a reason. You need a process for dermatologists to record their actual diagnosis back to the triage record. Without this feedback loop, you can't measure real-world model performance, detect drift, or know if your thresholds are calibrated correctly. Build the outcome recording workflow before you deploy the model.

**Threshold calibration.** The thresholds in this example (0.70 for urgent, 0.40 for suspicious) are illustrative. Real thresholds must be calibrated on a held-out validation set with known outcomes, in collaboration with dermatology leadership. They represent a clinical decision about the sensitivity/specificity tradeoff, and they'll need periodic adjustment as you gather outcome data.

**VPC and network isolation.** Lesion photographs are PHI. In production, Lambda and the SageMaker endpoint run inside a VPC with private subnets. VPC endpoints for S3, DynamoDB, SageMaker Runtime, and SNS keep all traffic on the AWS backbone. No PHI traverses the public internet, even though TLS encrypts everything in transit.

**Encryption key management.** This example uses default SSE-KMS encryption. Production uses customer-managed KMS keys with: key rotation enabled, CloudTrail logging of every key usage, separate keys for different data classifications, and key policies that restrict access to specific IAM roles.

**Logging and audit.** The `logger.info()` calls here are a starting point. Production logging uses structured JSON output (AWS Lambda Powertools is excellent for this) with consistent fields: case_id, patient_id (hashed), step name, duration, and outcome. Never log the image content, model predictions with patient identifiers, or any data that could reconstruct PHI from logs alone.

**Testing.** There are no tests here. A production pipeline has: unit tests for each step with mocked AWS calls, integration tests against a real SageMaker endpoint with known test images from public datasets, performance tests measuring end-to-end latency under load, and a regression test suite that runs against every model version before deployment. Never use real patient photos in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.4](chapter09.04-dermatology-lesion-triage.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
