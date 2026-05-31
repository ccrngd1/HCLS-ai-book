# Recipe 9.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 9.1. It shows one way you could translate those concepts into working Python code. It is not production-ready. There's no DICOM parsing from a real modality, no trained model weights, and the "ML inference" is simulated. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a radiology department on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image processing libraries:

```bash
pip install boto3 numpy
```

For real DICOM parsing you'd also want `pydicom` and for production image processing `opencv-python`, but this example uses numpy directly to keep dependencies minimal and demonstrate the core concepts.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `s3:GetObject`, `dynamodb:PutItem`, and `sns:Publish`.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the quality assessment decisions. Thresholds live at the top of your module because they're the first thing you'll tune per deployment site. (You will tune them. Every imaging department has different equipment, different standards, and different tolerance for false positives.)

```python
# QUALITY_THRESHOLDS: per-modality decision boundaries.
#
# Each modality/body_part combination gets its own thresholds because
# what counts as "acceptable" varies wildly. A chest X-ray needs to be
# sharp enough to see interstitial markings. A bone density scan has
# completely different requirements.
#
# "accept": images scoring above this pass automatically.
# "review": images between "review" and "accept" get flagged for tech review.
# Below "review": immediate reject, retake recommended.
#
# These numbers are starting points. Calibrate them against your
# radiologists' actual rejection patterns during a shadow-mode period.

QUALITY_THRESHOLDS = {
    "CR_CHEST": {"accept": 0.85, "review": 0.65},
    "CR_EXTREMITY": {"accept": 0.80, "review": 0.60},
    "CT_HEAD": {"accept": 0.90, "review": 0.70},
    "CT_ABDOMEN": {"accept": 0.85, "review": 0.65},
    "MR_KNEE": {"accept": 0.80, "review": 0.60},
    "MR_BRAIN": {"accept": 0.90, "review": 0.70},
    "DEFAULT": {"accept": 0.85, "review": 0.65},
}

# BLUR_THRESHOLD: minimum Laplacian variance for an image to be considered sharp.
# Below this, the image is definitely blurry regardless of what the ML model says.
# This is the "fast reject" gate for obvious motion blur.
# Typical range: 100-500 depending on modality and image resolution.
BLUR_THRESHOLD = 100.0

# DYNAMIC_RANGE_MINIMUM: minimum difference between 5th and 95th percentile
# pixel values. Below this, the image is essentially blank or saturated.
DYNAMIC_RANGE_MINIMUM = 50

# SAGEMAKER_ENDPOINT_NAME: the deployed model endpoint for ML-based assessment.
# This model was trained on your institution's historical PACS rejection data.
SAGEMAKER_ENDPOINT_NAME = "image-quality-model"

# SNS_TOPIC_ARN: where quality failure alerts go.
SNS_TOPIC_ARN = "arn:aws:sns:us-east-1:123456789012:quality-alerts"

# DYNAMODB_TABLE: where assessment results are stored.
DYNAMODB_TABLE = "quality-assessments"
```

---

## Step 1: Receive and Parse the Image

*The pseudocode calls this `receive_image(bucket, key)`. It downloads the DICOM file from S3 and extracts the pixel data and metadata. In a real deployment, you'd use pydicom for proper DICOM parsing. Here we simulate the structure to show the pipeline shape.*

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import numpy as np
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log pixel data or patient identifiers.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles burst throttling from SageMaker and other services.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)


def receive_image(bucket: str, key: str) -> dict:
    """
    Download a DICOM image from S3 and extract pixel data + metadata.

    In production, you'd use pydicom to parse the DICOM file properly:
        import pydicom
        ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
        pixel_array = ds.pixel_array
        modality = ds.Modality

    Here we simulate the parsed output to demonstrate the pipeline flow
    without requiring actual DICOM files or pydicom as a dependency.

    Args:
        bucket: S3 bucket containing the DICOM file
        key:    S3 object key (path to the .dcm file)

    Returns:
        Dictionary with pixel_array (numpy), modality, study/series UIDs,
        body_part, and the source key for audit trail linkage.
    """
    # Download the DICOM file from S3.
    # In production, this is a real DICOM file from your modality/router.
    response = s3_client.get_object(Bucket=bucket, Key=key)
    dicom_bytes = response["Body"].read()

    # --- SIMULATED DICOM PARSING ---
    # In production, replace this block with pydicom:
    #   ds = pydicom.dcmread(io.BytesIO(dicom_bytes))
    #   pixel_array = ds.pixel_array.astype(np.float64)
    #   modality = str(ds.Modality)
    #   study_uid = str(ds.StudyInstanceUID)
    #   series_uid = str(ds.SeriesInstanceUID)
    #   body_part = str(getattr(ds, 'BodyPartExamined', 'UNKNOWN'))
    #
    # For this example, we generate a synthetic chest X-ray image:
    # a 512x512 grayscale image with realistic intensity distribution.
    np.random.seed(hash(key) % (2**32))
    pixel_array = np.random.normal(loc=2048, scale=500, size=(512, 512))
    pixel_array = np.clip(pixel_array, 0, 4095).astype(np.float64)

    modality = "CR"
    study_uid = "1.2.840.113619.2.55.3.604688.2026.03.15.09.42.31"
    series_uid = "1.2.840.113619.2.55.3.604688.2026.03.15.09.42.31.1"
    body_part = "CHEST"
    # --- END SIMULATION ---

    return {
        "pixel_array": pixel_array,
        "modality": modality,
        "study_uid": study_uid,
        "series_uid": series_uid,
        "body_part": body_part,
        "source_key": key,
    }
```

---

## Step 2: Compute Rule-Based Quality Metrics

*The pseudocode calls this `compute_basic_metrics(pixel_array)`. These are fast, deterministic checks that catch obvious failures before you spend compute on ML inference. The Laplacian variance for blur, histogram statistics for exposure, and noise estimation are the workhorses here.*

```python
def compute_laplacian_variance(pixel_array: np.ndarray) -> float:
    """
    Compute the variance of the Laplacian as a sharpness/blur metric.

    The Laplacian operator computes the second spatial derivative of the image.
    Sharp images have lots of edges, which produce high values in the Laplacian.
    Blurry images are smooth, so the Laplacian output is mostly near zero.
    The variance of the Laplacian output is a single number that summarizes
    how much edge content exists in the image.

    High variance = sharp image (good).
    Low variance = blurry image (bad, likely motion artifact).

    This is the classic Pech-Pacheco et al. blur detection method.
    Simple, fast, and surprisingly effective for catching motion blur.
    """
    # The Laplacian kernel (3x3 approximation of the second derivative).
    # This responds to intensity changes in all directions.
    # We apply it via convolution (here, a simple numpy implementation).
    #
    # In production, use cv2.Laplacian(image, cv2.CV_64F) for speed.
    # This manual implementation shows what's actually happening.
    kernel = np.array([[0, 1, 0],
                       [1, -4, 1],
                       [0, 1, 0]], dtype=np.float64)

    # Pad the image to handle borders (replicate edge pixels).
    padded = np.pad(pixel_array, pad_width=1, mode="edge")

    # Apply the Laplacian kernel via convolution.
    # For each pixel, multiply the 3x3 neighborhood by the kernel and sum.
    laplacian = np.zeros_like(pixel_array)
    for i in range(pixel_array.shape[0]):
        for j in range(pixel_array.shape[1]):
            region = padded[i:i+3, j:j+3]
            laplacian[i, j] = np.sum(region * kernel)

    # The variance of the Laplacian output is our blur metric.
    return float(np.var(laplacian))


def compute_basic_metrics(pixel_array: np.ndarray) -> dict:
    """
    Compute rule-based quality metrics from the raw pixel data.

    These metrics catch the obvious failures fast (milliseconds) without
    needing ML inference. They also serve as input features to the ML model,
    giving it both raw pixels and computed statistics.

    Returns a dictionary of metric names to values. Each metric has a clear
    physical interpretation tied to image quality.
    """
    metrics = {}

    # --- Blur Detection (Laplacian Variance) ---
    metrics["blur_score"] = compute_laplacian_variance(pixel_array)

    # --- Exposure / Brightness Analysis ---
    # A well-exposed medical image uses the available dynamic range appropriately.
    # Underexposed: pixel values cluster at the low end (dark, no detail in soft tissue).
    # Overexposed: pixel values cluster at the high end (washed out, no bone detail).
    metrics["mean_intensity"] = float(np.mean(pixel_array))
    metrics["std_intensity"] = float(np.std(pixel_array))
    metrics["percentile_5"] = float(np.percentile(pixel_array, 5))
    metrics["percentile_95"] = float(np.percentile(pixel_array, 95))
    metrics["dynamic_range"] = metrics["percentile_95"] - metrics["percentile_5"]

    # --- Noise Estimation ---
    # Estimate noise using the median absolute deviation (MAD) of pixel differences.
    # In a homogeneous region, adjacent pixels should have similar values.
    # High variation between neighbors suggests noise.
    # This is a simplified estimator; production would use wavelet-based methods.
    horizontal_diff = np.diff(pixel_array, axis=1)
    noise_estimate = float(np.median(np.abs(horizontal_diff)) * 1.4826)
    # The 1.4826 factor converts MAD to an estimate of standard deviation
    # (assuming Gaussian noise). It's a robust noise estimator that isn't
    # fooled by edges the way simple std() would be.
    metrics["noise_level"] = noise_estimate

    # --- Sanity Checks ---
    # These catch hardware failures: detector malfunction (blank image),
    # stuck exposure (saturated image).
    metrics["is_blank"] = metrics["dynamic_range"] < 10
    metrics["is_saturated"] = metrics["percentile_95"] >= 4000  # near 12-bit max

    return metrics
```

---

## Step 3: Invoke the ML Quality Model

*The pseudocode calls this `assess_quality_ml(pixel_array, basic_metrics, modality)`. The ML model handles nuanced quality issues that rule-based metrics miss: subtle motion blur, positioning errors, complex artifact patterns. It takes the preprocessed image and computed metrics as input and returns quality scores.*

```python
def assess_quality_ml(pixel_array: np.ndarray, basic_metrics: dict, modality: str) -> dict:
    """
    Invoke the SageMaker-hosted quality assessment model.

    The model is a CNN trained on historical PACS rejection data from your
    institution. It learned what your radiologists consider "acceptable" vs.
    "reject" quality. The input is a resized, normalized image plus the
    computed metrics as auxiliary features.

    In production, the model architecture would be something like:
    - ResNet-18 or EfficientNet-B0 for the image branch (small, fast)
    - A small MLP for the tabular metrics branch
    - Concatenated features fed to a classification head

    Returns overall quality score (0-1) and per-category breakdowns.
    """
    # Preprocess: resize to model's expected input size and normalize to [0, 1].
    # Most quality models use 512x512 or 256x256 input. Larger isn't necessarily
    # better here because quality assessment doesn't need fine anatomical detail.
    target_size = (512, 512)

    # Simple resize via nearest-neighbor interpolation.
    # In production, use cv2.resize with INTER_AREA for downsampling.
    if pixel_array.shape != target_size:
        # Crude resize for demonstration. Production uses proper interpolation.
        row_indices = np.linspace(0, pixel_array.shape[0] - 1, target_size[0]).astype(int)
        col_indices = np.linspace(0, pixel_array.shape[1] - 1, target_size[1]).astype(int)
        resized = pixel_array[np.ix_(row_indices, col_indices)]
    else:
        resized = pixel_array

    # Normalize to [0, 1] range.
    img_min = resized.min()
    img_max = resized.max()
    if img_max > img_min:
        normalized = (resized - img_min) / (img_max - img_min)
    else:
        normalized = np.zeros_like(resized)

    # Build the payload for the SageMaker endpoint.
    # The model expects a JSON payload with the image as a flattened array
    # and the metrics as a separate field.
    payload = {
        "image": normalized.flatten().tolist(),
        "image_shape": list(target_size),
        "metrics": basic_metrics,
        "modality": modality,
    }

    # Invoke the SageMaker real-time endpoint.
    # The endpoint runs the trained model and returns quality scores.
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=json.dumps(payload),
    )

    # Parse the model's response.
    result = json.loads(response["Body"].read().decode("utf-8"))

    # Expected response structure from the model:
    # {
    #   "overall_quality": 0.72,
    #   "sharpness_score": 0.45,
    #   "exposure_score": 0.91,
    #   "positioning_score": 0.83,
    #   "artifact_score": 0.88
    # }
    return {
        "overall_score": result["overall_quality"],
        "category_scores": {
            "sharpness": result["sharpness_score"],
            "exposure": result["exposure_score"],
            "positioning": result["positioning_score"],
            "artifacts": result["artifact_score"],
        },
    }
```

---

## Step 4: Apply Decision Thresholds

*The pseudocode calls this `apply_decision(quality_result, modality, body_part)`. This translates continuous quality scores into discrete clinical actions: accept, review, or reject. The thresholds are configurable per modality and body part because "acceptable" means different things for different exam types.*

```python
def apply_decision(quality_result: dict, modality: str, body_part: str) -> dict:
    """
    Apply configurable thresholds to convert quality scores into actions.

    Three-tier decision:
    - ACCEPT: image passes, route to PACS normally.
    - REVIEW: borderline, flag for technologist review while patient is still there.
    - REJECT: clear failure, alert technologist for immediate retake.

    The thresholds are stored in QUALITY_THRESHOLDS (top of this file) and
    looked up by modality + body_part. This separation of model output from
    decision logic means you can tune sensitivity without retraining the model.
    """
    # Look up thresholds for this modality/body_part combination.
    threshold_key = f"{modality}_{body_part}"
    thresholds = QUALITY_THRESHOLDS.get(threshold_key, QUALITY_THRESHOLDS["DEFAULT"])

    overall = quality_result["overall_score"]
    category_scores = quality_result["category_scores"]

    # Apply the three-tier decision logic.
    if overall >= thresholds["accept"]:
        decision = "ACCEPT"
        action = "Route to PACS normally"

    elif overall >= thresholds["review"]:
        decision = "REVIEW"
        action = "Flag for technologist review before patient leaves"

    else:
        decision = "REJECT"
        # Find the worst-scoring category to give actionable feedback.
        # "Retake recommended" is useless without telling the tech WHY.
        worst_category = min(category_scores, key=category_scores.get)
        action = f"Alert technologist: retake recommended (primary issue: {worst_category})"

    return {
        "decision": decision,
        "action": action,
        "overall_score": overall,
        "category_scores": category_scores,
        "thresholds_used": thresholds,
    }
```

---

## Step 5: Store Results and Alert

*The pseudocode calls this `store_and_alert(image_info, decision_result)`. It writes the assessment record to DynamoDB for audit and analytics, and fires an SNS alert if the image failed or needs review. Every assessment is stored regardless of outcome because you need the full history for model retraining and compliance audits.*

```python
def store_and_alert(image_info: dict, decision_result: dict) -> str:
    """
    Persist the quality assessment and notify on failures.

    The DynamoDB record is the audit trail: what was assessed, when, what
    was decided, and why. HIPAA requires you to be able to trace any
    clinical decision back to its inputs. This record provides that linkage.

    SNS alerts go to the technologist's console or department dashboard.
    The alert includes enough context for the tech to act without looking
    up the full record.
    """
    table = dynamodb.Table(DYNAMODB_TABLE)

    # Build the assessment record.
    # DynamoDB requires Decimal for numeric values, not float.
    # This is a known boto3 gotcha that will raise TypeError if you forget.
    record = {
        "study_uid": image_info["study_uid"],
        "series_uid": image_info["series_uid"],
        "source_key": image_info["source_key"],
        "modality": image_info["modality"],
        "body_part": image_info["body_part"],
        "assessment_time": datetime.datetime.now(timezone.utc).isoformat(),
        "decision": decision_result["decision"],
        "overall_score": Decimal(str(round(decision_result["overall_score"], 4))),
        "category_scores": {
            k: Decimal(str(round(v, 4)))
            for k, v in decision_result["category_scores"].items()
        },
        "action": decision_result["action"],
    }

    table.put_item(Item=record)

    # Alert on failures. ACCEPT images flow silently to PACS.
    # REVIEW and REJECT images need human attention while the patient is still there.
    if decision_result["decision"] in ("REJECT", "REVIEW"):
        alert_message = {
            "study_uid": image_info["study_uid"],
            "modality": image_info["modality"],
            "body_part": image_info["body_part"],
            "decision": decision_result["decision"],
            "action": decision_result["action"],
            "score": decision_result["overall_score"],
        }

        sns_client.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"Image Quality {decision_result['decision']}: {image_info['modality']} {image_info['body_part']}",
            Message=json.dumps(alert_message, indent=2),
        )

    return decision_result["decision"]
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call when an S3 event fires for a new DICOM image.

```python
def assess_image_quality(bucket: str, key: str) -> dict:
    """
    Run the full image quality assessment pipeline for one DICOM image.

    Pipeline flow:
    1. Download and parse the DICOM image from S3
    2. Compute rule-based metrics (blur, exposure, noise) for fast rejection
    3. If basic checks pass, invoke the ML model for nuanced assessment
    4. Apply decision thresholds to get ACCEPT/REVIEW/REJECT
    5. Store the result and alert on failures

    Args:
        bucket: S3 bucket containing the DICOM file
        key:    S3 object key (path to the .dcm file)

    Returns:
        The complete assessment result including decision and scores.
    """
    # Step 1: Get the image and metadata.
    logger.info("Step 1: Receiving image from s3://%s/%s", bucket, key)
    image_info = receive_image(bucket, key)
    logger.info("  Modality: %s, Body part: %s", image_info["modality"], image_info["body_part"])

    # Step 2: Compute rule-based metrics.
    logger.info("Step 2: Computing basic quality metrics")
    basic_metrics = compute_basic_metrics(image_info["pixel_array"])
    logger.info("  Blur score: %.1f, Dynamic range: %.1f, Noise: %.2f",
                basic_metrics["blur_score"], basic_metrics["dynamic_range"],
                basic_metrics["noise_level"])

    # Fast reject: if the image is blank, saturated, or severely blurred,
    # skip the ML model entirely. No point spending inference compute on
    # an image that's obviously unusable.
    if basic_metrics["is_blank"] or basic_metrics["is_saturated"]:
        logger.info("  FAST REJECT: image is blank or saturated")
        quality_result = {
            "overall_score": 0.0,
            "category_scores": {
                "sharpness": 0.0 if basic_metrics["blur_score"] < BLUR_THRESHOLD else 0.5,
                "exposure": 0.0,
                "positioning": 0.5,  # can't assess positioning on a blank image
                "artifacts": 0.5,
            },
        }
    elif basic_metrics["blur_score"] < BLUR_THRESHOLD:
        logger.info("  FAST REJECT: severe blur detected (score %.1f < threshold %.1f)",
                    basic_metrics["blur_score"], BLUR_THRESHOLD)
        quality_result = {
            "overall_score": 0.2,
            "category_scores": {
                "sharpness": 0.1,
                "exposure": 0.8 if basic_metrics["dynamic_range"] > DYNAMIC_RANGE_MINIMUM else 0.3,
                "positioning": 0.5,
                "artifacts": 0.7,
            },
        }
    else:
        # Step 3: Image passes basic checks. Invoke the ML model for nuanced assessment.
        logger.info("Step 3: Invoking ML quality model")
        quality_result = assess_quality_ml(
            image_info["pixel_array"],
            basic_metrics,
            image_info["modality"],
        )
        logger.info("  ML overall score: %.3f", quality_result["overall_score"])

    # Step 4: Apply decision thresholds.
    logger.info("Step 4: Applying decision thresholds")
    decision_result = apply_decision(
        quality_result,
        image_info["modality"],
        image_info["body_part"],
    )
    logger.info("  Decision: %s (score: %.3f)", decision_result["decision"], decision_result["overall_score"])

    # Step 5: Store and alert.
    logger.info("Step 5: Storing result and alerting if needed")
    store_and_alert(image_info, decision_result)

    logger.info("Done. Decision: %s", decision_result["decision"])
    return decision_result


# Example: run the pipeline against a test image.
if __name__ == "__main__":
    result = assess_image_quality(
        bucket="imaging-inbox",
        key="imaging-inbox/2026/03/15/study-00891.dcm",
    )

    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the pipeline shape and the key decisions at each step. But there's a meaningful distance between "runs in a script" and "assesses images in a radiology department." Here's where that gap lives:

**DICOM parsing.** This example simulates pixel extraction with random numpy arrays. A real deployment uses `pydicom` to parse actual DICOM files, handling the dozens of transfer syntaxes, photometric interpretations, and pixel representations that exist in the wild. DICOM is a 30-year-old standard with extensive backwards compatibility baggage. Budget time for edge cases.

**Model training and deployment.** The SageMaker endpoint call assumes a trained model exists. Training that model requires: extracting your institution's historical rejection data from the PACS, pairing rejected images with rejection reasons, handling class imbalance (most images pass), and validating against held-out radiologist judgments. This is weeks of work, not hours.

**The Laplacian implementation.** The manual convolution loop in `compute_laplacian_variance` is correct but slow. For production, use `cv2.Laplacian(image, cv2.CV_64F)` from OpenCV, which runs the same operation in optimized C++ and is orders of magnitude faster. The numpy version here is for clarity, not performance.

**Error handling.** If the SageMaker endpoint is down, this code crashes. A production system catches endpoint errors and falls back to rule-based-only assessment (which is still useful). If S3 returns an error, you need retry logic with dead-letter queuing for images that repeatedly fail. Never silently lose a medical image.

**Input validation.** This code trusts that the S3 object is a valid DICOM file. Production validates: is it actually DICOM? Is the pixel data extractable? Is the modality one we support? Is the file size within expected bounds? Malformed files should be quarantined and logged, not crash the pipeline.

**Latency optimization.** The whole point of quality assessment is catching bad images while the patient is still on the table. That means sub-3-second end-to-end latency. In production, you'd: keep the SageMaker endpoint warm (no cold starts), use a compiled model (TorchScript or ONNX), minimize S3 round-trips, and potentially run the rule-based checks on an edge device before even uploading to the cloud.

**VPC and encryption.** Medical images are PHI. In production, Lambda runs in a VPC with VPC endpoints for S3, SageMaker, DynamoDB, and SNS. Traffic never touches the public internet. S3 uses SSE-KMS with a customer-managed key. DynamoDB encryption at rest is enabled by default but you want your own CMK for key rotation control.

**IAM least-privilege.** The IAM role for this Lambda needs exactly: `s3:GetObject` on the imaging bucket, `sagemaker:InvokeEndpoint` on the specific endpoint ARN, `dynamodb:PutItem` on the specific table, and `sns:Publish` on the specific topic. Not wildcards. Not `AdministratorAccess`.

**Threshold management.** The `QUALITY_THRESHOLDS` dict is hardcoded here. Production stores thresholds in DynamoDB or AWS Systems Manager Parameter Store so they can be updated without redeploying the Lambda. Different sites, different modalities, and different clinical contexts all need different thresholds. Make them configurable from day one.

**Monitoring and drift detection.** Track the distribution of quality scores over time. If the average score suddenly drops, it might mean a new piece of equipment was installed (different noise characteristics) or the model is drifting. CloudWatch metrics on score distributions, decision rates, and override rates are essential for operational health.

**The DynamoDB Decimal requirement.** This example already wraps scores in `Decimal(str(round(value, 4)))`. If you add new numeric fields, they must also use Decimal. The boto3 DynamoDB resource layer raises `TypeError` on raw floats. The `str()` wrapper avoids floating-point representation artifacts that Decimal would otherwise inherit.

**Testing.** There are no tests here. A production pipeline has: unit tests for `compute_basic_metrics` with known synthetic images (a perfectly sharp image should score high, a Gaussian-blurred image should score low), integration tests against the SageMaker endpoint with a fixture set of images, and a calibration test suite that verifies threshold behavior against labeled examples from your radiologists.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.1](chapter09.01-image-quality-assessment) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
