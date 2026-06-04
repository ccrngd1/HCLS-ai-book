# Recipe 9.6: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 9.6. It shows one way you could translate those concepts into working Python code using boto3 and a few standard libraries. It is not production-ready. There's no real deep learning model here (we mock the inference), no EHR integration, no FDA-validated decision logic, and the "fundus images" are synthetic numpy arrays. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a screening program on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image-handling libraries:

```bash
pip install boto3 numpy Pillow scipy
```

`Pillow` handles image loading and basic manipulation. `numpy` handles array operations for preprocessing. `scipy` provides signal processing functions used in the image quality assessment (Laplacian convolution for sharpness detection). In a real deployment, you'd also need a deep learning framework (PyTorch or TensorFlow) for local preprocessing and potentially for running the quality assessment model locally. For this example, we keep it to standard libraries and let SageMaker handle the classification model.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `sagemaker:InvokeEndpoint`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, and `sns:Publish`.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the screening logic. These thresholds are the most important tunable parameters in the system. In production, you'd calibrate them on a clinical validation dataset with ophthalmologist input and regulatory review. The values below are reasonable starting points based on published literature, but your specific operating point depends on your population, camera hardware, and clinical workflow.

```python
import json
import uuid
import logging
from decimal import Decimal
from datetime import datetime, timezone

import boto3
import numpy as np
from botocore.config import Config
from PIL import Image
from io import BytesIO

# Configure structured logging. In production, use JSON-formatted output
# for CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry configuration for AWS API calls. Adaptive mode uses exponential
# backoff with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Clinical Decision Thresholds ---
# These thresholds determine when the system triggers a referral vs. clears a patient.
# They represent the operating point on the sensitivity/specificity curve.
# Lower REFERABLE_THRESHOLD = more sensitive (catch more disease, more false referrals).
# Higher REFERABLE_THRESHOLD = more specific (fewer false referrals, risk missing disease).
#
# In a screening program, you generally want HIGH sensitivity (don't miss disease)
# even at the cost of some specificity (extra referrals that turn out normal).
# These values should be validated on YOUR patient population before deployment.

REFERABLE_THRESHOLD = 0.80      # P(moderate+ DR) to trigger referral
DME_THRESHOLD = 0.70            # P(DME) to trigger referral independently
CONFIDENCE_THRESHOLD = 0.60     # Below this, defer to human grader (model uncertain)
URGENT_THRESHOLD = 0.70         # P(severe/PDR) to trigger urgent referral

# --- Image Quality Thresholds ---
# Minimum scores for each quality dimension. An image must pass ALL of these
# to be considered gradable. If any dimension fails, the image is rejected
# with a specific reason so the operator knows what to fix.

QUALITY_THRESHOLDS = {
    "field_of_view": 0.70,      # Must capture macula and optic disc
    "sharpness": 0.60,          # Must resolve microaneurysms (tiny lesions)
    "illumination": 0.65,       # Must have adequate dynamic range
    "artifact": 0.70,           # Must be free of dust, lashes, reflections
}

# --- Model Configuration ---
# SageMaker endpoint hosting the DR classification model.
# In production, this would be a validated, versioned model endpoint.
SAGEMAKER_ENDPOINT_NAME = "dr-screening-model-v2"

# Model input dimensions. Must match training specifications.
# 512x512 is common for retinal models; some use 1024x1024 for higher detail.
MODEL_INPUT_SIZE = (512, 512)

# --- Storage Configuration ---
S3_BUCKET = "retinal-screening-images"
DYNAMODB_TABLE = "screening-results"
READING_QUEUE_TABLE = "reading-queue"

# --- SNS Topics ---
SNS_URGENT_REFERRAL_TOPIC = "arn:aws:sns:us-east-1:123456789012:urgent-referrals"
SNS_ROUTINE_REFERRAL_TOPIC = "arn:aws:sns:us-east-1:123456789012:routine-referrals"
SNS_NORMAL_RESULT_TOPIC = "arn:aws:sns:us-east-1:123456789012:normal-results"
SNS_RECAPTURE_TOPIC = "arn:aws:sns:us-east-1:123456789012:recapture-required"

# --- ICDR Severity Scale ---
# International Clinical Diabetic Retinopathy severity levels.
# The model outputs a probability for each level.
SEVERITY_LEVELS = [
    "No DR",
    "Mild NPDR",
    "Moderate NPDR",
    "Severe NPDR",
    "Proliferative DR",
]
```

---

## AWS Clients

```python
# Create AWS service clients. boto3 uses whatever credentials and region
# are configured in your environment.
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sns_client = boto3.client("sns", config=BOTO3_RETRY_CONFIG)

results_table = dynamodb.Table(DYNAMODB_TABLE)
reading_queue_table = dynamodb.Table(READING_QUEUE_TABLE)
```

---

## Step 1: Image Quality Assessment

*The pseudocode calls this `assess_image_quality(bucket, image_key)`. Before the classification model ever sees an image, we confirm it's actually gradable. A blurry, poorly-centered, or underexposed fundus image will produce unreliable predictions. This gate prevents the most common source of false negatives in screening programs.*

```python
def download_image_from_s3(bucket: str, key: str) -> Image.Image:
    """
    Download a fundus image from S3 and return it as a PIL Image.

    Args:
        bucket: S3 bucket name
        key: S3 object key (path to the image file)

    Returns:
        PIL Image object ready for processing
    """
    response = s3_client.get_object(Bucket=bucket, Key=key)
    image_bytes = response["Body"].read()
    return Image.open(BytesIO(image_bytes))


def calculate_sharpness(image: Image.Image) -> float:
    """
    Estimate image sharpness using Laplacian variance.

    The Laplacian operator detects edges. A sharp image has many strong edges
    (high variance of the Laplacian). A blurry image has weak, diffuse edges
    (low variance). This is a standard focus quality metric.

    For retinal images, sharpness matters because microaneurysms (the earliest
    sign of diabetic retinopathy) are tiny dots. If the image is blurry enough
    to smear those dots into the background, the model will miss them.

    Returns:
        Normalized sharpness score between 0.0 and 1.0.
    """
    # Convert to grayscale for edge detection.
    gray = np.array(image.convert("L"), dtype=np.float64)

    # Laplacian kernel (approximation using second derivatives).
    # This highlights regions of rapid intensity change (edges).
    laplacian = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)

    # Convolve the image with the Laplacian kernel.
    from scipy.signal import convolve2d
    filtered = convolve2d(gray, laplacian, mode="same", boundary="symm")

    # Variance of the Laplacian response. Higher = sharper.
    variance = np.var(filtered)

    # Normalize to 0-1 range. These bounds are empirical for fundus images.
    # A variance below 100 is very blurry; above 1500 is very sharp.
    normalized = min(max((variance - 100) / 1400, 0.0), 1.0)
    return normalized


def calculate_illumination_uniformity(image: Image.Image) -> float:
    """
    Check whether the image has adequate and uniform illumination.

    Fundus images should have a bright central region (the retina illuminated
    by the camera flash) with gradual falloff toward the edges. Problems:
    - Underexposed: everything is dark, pathology invisible
    - Overexposed: washed out, no contrast between structures
    - Uneven: one side bright, other side dark (camera misalignment)

    Returns:
        Normalized illumination score between 0.0 and 1.0.
    """
    gray = np.array(image.convert("L"), dtype=np.float64)

    # Check overall brightness (mean pixel value).
    mean_brightness = np.mean(gray)

    # Check dynamic range (standard deviation of pixel values).
    # A good fundus image uses most of the 0-255 range.
    std_brightness = np.std(gray)

    # Penalize images that are too dark (mean < 50) or too bright (mean > 200).
    brightness_score = 1.0 - abs(mean_brightness - 125) / 125

    # Penalize images with low dynamic range (flat histogram).
    range_score = min(std_brightness / 50, 1.0)

    return (brightness_score + range_score) / 2


def calculate_field_of_view(image: Image.Image) -> float:
    """
    Estimate whether the image captures adequate retinal area.

    A proper fundus image should show the optic disc and macula within the
    field of view. If the patient blinked, the camera was misaligned, or
    the pupil was too small, you get a partial image that's ungradable.

    This is a simplified check based on the circular retinal area visible
    in the image. A real implementation would use landmark detection
    (find the optic disc and macula explicitly).

    Returns:
        Normalized field of view score between 0.0 and 1.0.
    """
    gray = np.array(image.convert("L"), dtype=np.float64)

    # Fundus images typically show a bright circular region (the retina)
    # against a dark background. Threshold to find the illuminated area.
    threshold = 30  # pixels brighter than this are "retina"
    retinal_pixels = np.sum(gray > threshold)
    total_pixels = gray.size

    # The illuminated area should be at least 60% of the image frame.
    # Less than that suggests partial capture or severe vignetting.
    coverage = retinal_pixels / total_pixels
    normalized = min(coverage / 0.60, 1.0)
    return normalized


def detect_artifacts(image: Image.Image) -> float:
    """
    Check for common artifacts: dust spots, eyelash shadows, reflections.

    Artifacts can mimic pathology (a dust spot looks like a hemorrhage) or
    hide pathology (an eyelash shadow obscures the macula). Either way,
    the image is unreliable for grading.

    This simplified version checks for unusually bright spots (reflections)
    and unusually dark linear features (eyelashes). A production system
    would use a trained artifact detection model.

    Returns:
        Normalized artifact-free score between 0.0 and 1.0.
        Higher = fewer artifacts = better quality.
    """
    gray = np.array(image.convert("L"), dtype=np.float64)

    # Check for specular reflections (very bright spots).
    bright_pixels = np.sum(gray > 250)
    bright_ratio = bright_pixels / gray.size

    # Check for very dark regions that shouldn't be there (eyelash shadows).
    # Exclude the natural dark border of the fundus image.
    center_region = gray[
        gray.shape[0] // 4 : 3 * gray.shape[0] // 4,
        gray.shape[1] // 4 : 3 * gray.shape[1] // 4,
    ]
    dark_in_center = np.sum(center_region < 20)
    dark_ratio = dark_in_center / center_region.size

    # Score: penalize for reflections and dark artifacts.
    reflection_penalty = min(bright_ratio * 50, 0.5)
    shadow_penalty = min(dark_ratio * 20, 0.5)

    return max(1.0 - reflection_penalty - shadow_penalty, 0.0)


def assess_image_quality(bucket: str, image_key: str) -> dict:
    """
    Run the full quality assessment pipeline on a fundus image.

    All four quality dimensions must pass their respective thresholds
    for the image to be considered gradable. If any dimension fails,
    the image is rejected with a specific reason so the camera operator
    knows what to fix (retake with better focus, ask patient to open
    eyes wider, clean the lens, etc.).

    Args:
        bucket: S3 bucket containing the image
        image_key: S3 key of the fundus image

    Returns:
        Dict with gradable (bool), quality_score (float), and if failed,
        the reason and recommendation for recapture.
    """
    image = download_image_from_s3(bucket, image_key)

    # Run each quality check independently.
    scores = {
        "field_of_view": calculate_field_of_view(image),
        "sharpness": calculate_sharpness(image),
        "illumination": calculate_illumination_uniformity(image),
        "artifact": detect_artifacts(image),
    }

    # Find any dimensions that failed their threshold.
    failures = {
        dim: score
        for dim, score in scores.items()
        if score < QUALITY_THRESHOLDS[dim]
    }

    # Overall quality is the minimum across all dimensions.
    # One bad dimension makes the whole image ungradable.
    overall_quality = min(scores.values())

    if failures:
        # Identify the worst-performing dimension for the recapture instruction.
        worst_dim = min(failures, key=failures.get)
        recommendations = {
            "field_of_view": "Reposition camera. Ensure optic disc and macula are visible.",
            "sharpness": "Refocus the camera. Ask patient to fixate on the target.",
            "illumination": "Adjust flash intensity. Check for media opacities (cataracts).",
            "artifact": "Clean the lens. Ask patient to open eyes wider. Check for reflections.",
        }

        logger.info(
            "Image quality FAILED",
            extra={"image_key": image_key, "worst_dimension": worst_dim,
                   "scores": scores},
        )

        return {
            "gradable": False,
            "quality_score": overall_quality,
            "scores": scores,
            "reason": f"Failed quality check: {worst_dim} ({failures[worst_dim]:.2f} < {QUALITY_THRESHOLDS[worst_dim]})",
            "recommendation": recommendations[worst_dim],
        }

    logger.info(
        "Image quality PASSED",
        extra={"image_key": image_key, "quality_score": overall_quality},
    )

    return {
        "gradable": True,
        "quality_score": overall_quality,
        "scores": scores,
    }
```

---

## Step 2: Model Inference (DR Classification)

*The pseudocode calls this `classify_retinal_image(bucket, image_key)`. The fundus image is preprocessed and sent to the SageMaker endpoint hosting the deep learning model. The model outputs probabilities for each ICDR severity level plus a separate DME probability.*

```python
def preprocess_for_model(image: Image.Image) -> bytes:
    """
    Preprocess a fundus image for model inference.

    The preprocessing must exactly match what was done during model training.
    Typical steps for retinal models:
    1. Resize to the model's expected input dimensions
    2. Normalize pixel values to [0, 1] or [-1, 1] range
    3. Apply any color normalization (some models expect specific color balance)
    4. Serialize to the format the endpoint expects

    Returns:
        Serialized image tensor as bytes, ready for the SageMaker endpoint.
    """
    # Resize to model input dimensions. Use LANCZOS for high-quality downsampling.
    # Fundus images are typically 2000x2000+; the model expects 512x512.
    resized = image.resize(MODEL_INPUT_SIZE, Image.LANCZOS)

    # Convert to numpy array and normalize to [0, 1] range.
    img_array = np.array(resized, dtype=np.float32) / 255.0

    # Some models expect channel-first format (C, H, W) instead of (H, W, C).
    # Check your model's documentation. We'll use channel-last here.
    # img_array shape: (512, 512, 3)

    # Serialize as JSON with the pixel values as a nested list.
    # Alternative formats: application/x-npy, application/x-image
    # JSON is verbose but universally supported by SageMaker endpoints.
    payload = json.dumps({"instances": [img_array.tolist()]})
    return payload.encode("utf-8")


def classify_retinal_image(bucket: str, image_key: str) -> dict:
    """
    Send a fundus image to the DR classification model and get predictions.

    The model outputs a probability distribution over the 5 ICDR severity
    levels plus a separate DME probability. This gives downstream logic
    the flexibility to apply different thresholds for different clinical
    contexts rather than being locked into a single hard classification.

    Args:
        bucket: S3 bucket containing the image
        image_key: S3 key of the fundus image

    Returns:
        Dict with per-level probabilities, DME probability, model version,
        and inference time.
    """
    image = download_image_from_s3(bucket, image_key)
    payload = preprocess_for_model(image)

    # Invoke the SageMaker endpoint.
    # This is a synchronous call; it blocks until inference completes.
    # Typical latency: 2-5 seconds for a single image on a GPU endpoint.
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=payload,
    )

    # Parse the model response.
    result = json.loads(response["Body"].read().decode("utf-8"))

    # Expected response structure from the model:
    # {
    #   "predictions": [[0.02, 0.05, 0.78, 0.12, 0.03]],  # ICDR probabilities
    #   "dme_predictions": [[0.85, 0.15]],                  # [no_dme, dme]
    #   "model_version": "v2.3.1"
    # }
    probabilities = result["predictions"][0]
    dme_probs = result["dme_predictions"][0]

    predictions = {
        "no_dr_probability": probabilities[0],
        "mild_npdr_probability": probabilities[1],
        "moderate_npdr_probability": probabilities[2],
        "severe_npdr_probability": probabilities[3],
        "pdr_probability": probabilities[4],
        "dme_probability": dme_probs[1],  # probability of DME present
        "model_version": result.get("model_version", "unknown"),
        "severity_levels": SEVERITY_LEVELS,
    }

    logger.info(
        "Model inference complete",
        extra={"image_key": image_key, "model_version": predictions["model_version"]},
    )

    return predictions
```

---

## Step 3: Clinical Decision Logic

*The pseudocode calls this `apply_clinical_decision(predictions)`. This is where model output becomes a clinical action. The mapping from probabilities to referral decisions is the most clinically sensitive part of the system.*

```python
def apply_clinical_decision(predictions: dict) -> dict:
    """
    Map model predictions to a clinical screening decision.

    The decision logic handles four scenarios:
    1. Model is uncertain (max probability below confidence threshold) -> human review
    2. High probability of sight-threatening disease (severe/PDR) -> urgent referral
    3. Referable DR detected (moderate+) -> routine referral
    4. DME detected (independent of DR severity) -> routine referral
    5. No referable disease -> clear for annual rescreening

    The thresholds here are configurable and MUST be validated on your specific
    patient population before clinical deployment. A screening program's operating
    point is a tradeoff between sensitivity (catching all disease) and specificity
    (not overwhelming ophthalmology with false referrals).

    Args:
        predictions: Output from classify_retinal_image()

    Returns:
        Dict with decision, urgency, severity_grade, and supporting probabilities.
    """
    # Calculate the probability of referable DR (moderate NPDR or worse).
    # This is the key metric for the referral decision.
    referable_probability = (
        predictions["moderate_npdr_probability"]
        + predictions["severe_npdr_probability"]
        + predictions["pdr_probability"]
    )

    # Calculate urgency: severe NPDR or PDR requires expedited referral
    # because these stages carry high risk of imminent vision loss.
    urgent_probability = (
        predictions["severe_npdr_probability"]
        + predictions["pdr_probability"]
    )

    # Determine the highest-probability severity grade for the record.
    prob_list = [
        predictions["no_dr_probability"],
        predictions["mild_npdr_probability"],
        predictions["moderate_npdr_probability"],
        predictions["severe_npdr_probability"],
        predictions["pdr_probability"],
    ]
    max_idx = prob_list.index(max(prob_list))
    severity_grade = SEVERITY_LEVELS[max_idx]
    max_probability = max(prob_list)

    # Decision logic with confidence gating.
    if max_probability < CONFIDENCE_THRESHOLD:
        # Model is not confident enough for an autonomous decision.
        # Route to a human grader (ophthalmologist or trained reader).
        # This is a SAFETY feature, not a failure mode.
        decision = "HUMAN_REVIEW_REQUIRED"
        urgency = "routine"

    elif urgent_probability >= URGENT_THRESHOLD:
        # High probability of sight-threatening disease. Urgent referral.
        # Patient needs ophthalmology within days, not weeks.
        decision = "URGENT_REFERRAL"
        urgency = "urgent"

    elif referable_probability >= REFERABLE_THRESHOLD:
        # Referable DR detected. Routine ophthalmology referral.
        # Patient needs to be seen within 2-4 weeks.
        decision = "ROUTINE_REFERRAL"
        urgency = "routine"

    elif predictions["dme_probability"] >= DME_THRESHOLD:
        # DME detected independent of DR severity.
        # Macular edema can occur at any DR stage and independently
        # threatens central vision. Requires referral.
        decision = "ROUTINE_REFERRAL"
        urgency = "routine"
        severity_grade = f"{severity_grade} with DME"

    else:
        # No referable disease detected.
        # Patient is safe to screen again in 12 months.
        decision = "NO_REFERRAL"
        urgency = "none"

    result = {
        "decision": decision,
        "urgency": urgency,
        "severity_grade": severity_grade,
        "referable_probability": round(referable_probability, 4),
        "dme_probability": round(predictions["dme_probability"], 4),
        "urgent_probability": round(urgent_probability, 4),
        "max_probability": round(max_probability, 4),
        "model_version": predictions["model_version"],
    }

    logger.info(
        "Clinical decision rendered",
        extra={"decision": decision, "severity": severity_grade},
    )

    return result
```

---

## Step 4: Store Results and Trigger Actions

*The pseudocode calls this `store_and_act(patient_id, image_key, quality_result, predictions, decision)`. Every screening event gets a complete audit record, and the appropriate downstream action is triggered based on the clinical decision.*

```python
def store_screening_result(
    patient_id: str,
    image_key: str,
    quality_result: dict,
    predictions: dict,
    decision: dict,
) -> dict:
    """
    Write the complete screening record to DynamoDB.

    This record is the authoritative output of the screening pipeline.
    It must contain everything needed for:
    - Clinical use (what was the result, what action was taken)
    - Regulatory audit (which model version, what were the raw predictions)
    - Quality monitoring (track performance over time)
    - Reprocessing (if a model is updated, rerun on stored images)

    DynamoDB requires Decimal for numeric values, not float.
    This is a known gotcha that will throw a TypeError if you forget.
    """
    screening_id = f"scr-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:5]}"

    record = {
        "patient_id": patient_id,
        "screening_id": screening_id,
        "screening_date": datetime.now(timezone.utc).isoformat(),
        "image_key": image_key,
        "quality_score": Decimal(str(round(quality_result["quality_score"], 3))),
        "severity_grade": decision["severity_grade"],
        "referable_probability": Decimal(str(decision["referable_probability"])),
        "dme_probability": Decimal(str(decision["dme_probability"])),
        "clinical_decision": decision["decision"],
        "urgency": decision["urgency"],
        "model_version": decision["model_version"],
        # Store raw predictions for audit trail. Convert all floats to Decimal.
        "raw_predictions": json.loads(
            json.dumps(predictions), parse_float=Decimal
        ),
        "status": "COMPLETE",
    }

    # DynamoDB key: patient_id (partition) + screening_date (sort)
    results_table.put_item(Item=record)

    logger.info(
        "Screening result stored",
        extra={"screening_id": screening_id, "patient_id": patient_id},
    )

    return record


def trigger_downstream_action(patient_id: str, screening_id: str, image_key: str, decision: dict):
    """
    Trigger the appropriate notification based on the clinical decision.

    - URGENT_REFERRAL: Immediate provider notification (SNS)
    - ROUTINE_REFERRAL: Standard referral notification (SNS)
    - HUMAN_REVIEW_REQUIRED: Add to reading queue (DynamoDB)
    - NO_REFERRAL: Patient notification of normal result (SNS)
    """
    message_base = {
        "patient_id": patient_id,
        "screening_id": screening_id,
        "image_key": image_key,
        "severity_grade": decision["severity_grade"],
        "decision": decision["decision"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if decision["decision"] == "URGENT_REFERRAL":
        sns_client.publish(
            TopicArn=SNS_URGENT_REFERRAL_TOPIC,
            Subject="URGENT: Diabetic Retinopathy Screening - Immediate Referral Required",
            Message=json.dumps(message_base),
        )
        logger.info("Urgent referral notification sent", extra={"patient_id": patient_id})

    elif decision["decision"] == "ROUTINE_REFERRAL":
        sns_client.publish(
            TopicArn=SNS_ROUTINE_REFERRAL_TOPIC,
            Subject="Diabetic Retinopathy Screening - Referral Recommended",
            Message=json.dumps(message_base),
        )
        logger.info("Routine referral notification sent", extra={"patient_id": patient_id})

    elif decision["decision"] == "HUMAN_REVIEW_REQUIRED":
        # Add to reading queue for a qualified human grader.
        reading_queue_table.put_item(
            Item={
                "screening_id": screening_id,
                "patient_id": patient_id,
                "image_key": image_key,
                "raw_predictions": json.loads(
                    json.dumps(decision), parse_float=Decimal
                ),
                "priority": "standard",
                "status": "PENDING_REVIEW",
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        logger.info("Added to human reading queue", extra={"screening_id": screening_id})

    else:
        # NO_REFERRAL: normal result, schedule next annual screening.
        message_base["next_screening_due"] = "12 months from screening date"
        sns_client.publish(
            TopicArn=SNS_NORMAL_RESULT_TOPIC,
            Subject="Diabetic Retinopathy Screening - Normal Result",
            Message=json.dumps(message_base),
        )
        logger.info("Normal result notification sent", extra={"patient_id": patient_id})
```

---

## Full Pipeline Function

This assembles all four steps into a single callable function. The print statements show progress so you can trace execution during development.

```python
def run_screening_pipeline(patient_id: str, bucket: str, image_key: str) -> dict:
    """
    Execute the complete diabetic retinopathy screening pipeline.

    Steps:
    1. Assess image quality (reject ungradable images immediately)
    2. Classify the retinal image (invoke DR model)
    3. Apply clinical decision logic (map predictions to actions)
    4. Store results and trigger downstream actions

    Args:
        patient_id: Unique patient identifier
        bucket: S3 bucket containing the fundus image
        image_key: S3 key of the fundus image

    Returns:
        Complete screening record dict, or quality failure dict if image rejected.
    """
    print(f"\n{'='*60}")
    print(f"DIABETIC RETINOPATHY SCREENING PIPELINE")
    print(f"Patient: {patient_id}")
    print(f"Image: s3://{bucket}/{image_key}")
    print(f"{'='*60}\n")

    # --- Step 1: Quality Assessment ---
    print("[Step 1/4] Assessing image quality...")
    quality_result = assess_image_quality(bucket, image_key)

    if not quality_result["gradable"]:
        print(f"  ❌ Image REJECTED: {quality_result['reason']}")
        print(f"  📋 Recommendation: {quality_result['recommendation']}")

        # Notify the capture site to retake the image.
        sns_client.publish(
            TopicArn=SNS_RECAPTURE_TOPIC,
            Subject="Retinal Image Recapture Required",
            Message=json.dumps({
                "patient_id": patient_id,
                "image_key": image_key,
                "reason": quality_result["reason"],
                "recommendation": quality_result["recommendation"],
            }),
        )

        return {
            "status": "QUALITY_REJECTED",
            "patient_id": patient_id,
            "image_key": image_key,
            "quality_result": quality_result,
        }

    print(f"  ✓ Image quality PASSED (score: {quality_result['quality_score']:.2f})")

    # --- Step 2: Model Inference ---
    print("[Step 2/4] Running DR classification model...")
    predictions = classify_retinal_image(bucket, image_key)
    print(f"  ✓ Model inference complete (version: {predictions['model_version']})")
    print(f"    No DR: {predictions['no_dr_probability']:.3f}")
    print(f"    Mild NPDR: {predictions['mild_npdr_probability']:.3f}")
    print(f"    Moderate NPDR: {predictions['moderate_npdr_probability']:.3f}")
    print(f"    Severe NPDR: {predictions['severe_npdr_probability']:.3f}")
    print(f"    PDR: {predictions['pdr_probability']:.3f}")
    print(f"    DME: {predictions['dme_probability']:.3f}")

    # --- Step 3: Clinical Decision ---
    print("[Step 3/4] Applying clinical decision logic...")
    decision = apply_clinical_decision(predictions)
    print(f"  ✓ Decision: {decision['decision']}")
    print(f"    Severity: {decision['severity_grade']}")
    print(f"    Urgency: {decision['urgency']}")
    print(f"    Referable probability: {decision['referable_probability']:.3f}")

    # --- Step 4: Store and Act ---
    print("[Step 4/4] Storing results and triggering actions...")
    record = store_screening_result(
        patient_id, image_key, quality_result, predictions, decision
    )
    trigger_downstream_action(patient_id, record["screening_id"], image_key, decision)
    print(f"  ✓ Screening record stored: {record['screening_id']}")

    print(f"\n{'='*60}")
    print(f"SCREENING COMPLETE")
    print(f"  Result: {decision['severity_grade']} -> {decision['decision']}")
    print(f"{'='*60}\n")

    return record
```

---

## Synthetic Test Data

For development and testing, here's how to generate synthetic screening scenarios without real patient images. This creates mock S3 events and simulates the model responses you'd see in production.

```python
def create_synthetic_screening_batch():
    """
    Generate a batch of synthetic screening scenarios for testing.

    These represent the range of outcomes you'd see in a real screening program:
    - Normal results (majority of screenings)
    - Mild NPDR (monitor, no referral)
    - Moderate NPDR (routine referral)
    - Severe/PDR (urgent referral)
    - DME detected (referral regardless of DR grade)
    - Low confidence (human review required)
    - Poor quality image (recapture required)
    """
    scenarios = [
        {
            "patient_id": "pat-001",
            "description": "Normal retina, no disease",
            "predictions": {
                "no_dr_probability": 0.92,
                "mild_npdr_probability": 0.05,
                "moderate_npdr_probability": 0.02,
                "severe_npdr_probability": 0.005,
                "pdr_probability": 0.005,
                "dme_probability": 0.03,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "NO_REFERRAL",
        },
        {
            "patient_id": "pat-002",
            "description": "Mild NPDR, below referral threshold",
            "predictions": {
                "no_dr_probability": 0.15,
                "mild_npdr_probability": 0.72,
                "moderate_npdr_probability": 0.08,
                "severe_npdr_probability": 0.03,
                "pdr_probability": 0.02,
                "dme_probability": 0.05,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "NO_REFERRAL",
        },
        {
            "patient_id": "pat-003",
            "description": "Moderate NPDR, routine referral",
            "predictions": {
                "no_dr_probability": 0.02,
                "mild_npdr_probability": 0.05,
                "moderate_npdr_probability": 0.78,
                "severe_npdr_probability": 0.12,
                "pdr_probability": 0.03,
                "dme_probability": 0.08,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "ROUTINE_REFERRAL",
        },
        {
            "patient_id": "pat-004",
            "description": "Proliferative DR, urgent referral",
            "predictions": {
                "no_dr_probability": 0.01,
                "mild_npdr_probability": 0.02,
                "moderate_npdr_probability": 0.05,
                "severe_npdr_probability": 0.22,
                "pdr_probability": 0.70,
                "dme_probability": 0.45,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "URGENT_REFERRAL",
        },
        {
            "patient_id": "pat-005",
            "description": "No DR but DME detected, referral needed",
            "predictions": {
                "no_dr_probability": 0.80,
                "mild_npdr_probability": 0.10,
                "moderate_npdr_probability": 0.05,
                "severe_npdr_probability": 0.03,
                "pdr_probability": 0.02,
                "dme_probability": 0.82,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "ROUTINE_REFERRAL",
        },
        {
            "patient_id": "pat-006",
            "description": "Model uncertain, needs human review",
            "predictions": {
                "no_dr_probability": 0.35,
                "mild_npdr_probability": 0.25,
                "moderate_npdr_probability": 0.20,
                "severe_npdr_probability": 0.12,
                "pdr_probability": 0.08,
                "dme_probability": 0.30,
                "model_version": "v2.3.1",
                "severity_levels": SEVERITY_LEVELS,
            },
            "expected_decision": "HUMAN_REVIEW_REQUIRED",
        },
    ]

    print("\n" + "=" * 70)
    print("SYNTHETIC SCREENING BATCH - Testing Clinical Decision Logic")
    print("=" * 70)

    for scenario in scenarios:
        print(f"\n--- {scenario['description']} (Patient: {scenario['patient_id']}) ---")
        decision = apply_clinical_decision(scenario["predictions"])

        status = "✓" if decision["decision"] == scenario["expected_decision"] else "✗"
        print(f"  {status} Decision: {decision['decision']}")
        print(f"    Severity: {decision['severity_grade']}")
        print(f"    Referable prob: {decision['referable_probability']:.3f}")
        print(f"    DME prob: {decision['dme_probability']:.3f}")

        if decision["decision"] != scenario["expected_decision"]:
            print(f"    ⚠️  MISMATCH: Expected {scenario['expected_decision']}")

    print("\n" + "=" * 70)
    print("BATCH COMPLETE")
    print("=" * 70)


# Run the synthetic test batch to verify decision logic.
if __name__ == "__main__":
    create_synthetic_screening_batch()
```

---

## Gap to Production

This example demonstrates the shape of a DR screening pipeline. Here's what you'd need to add before deploying to a real screening program:

**Error handling and retries.** Every AWS API call can fail. The `BOTO3_RETRY_CONFIG` handles transient throttling, but you also need application-level retries for SageMaker endpoint cold starts (which can take 30+ seconds if the endpoint scaled to zero), S3 eventual consistency edge cases, and DynamoDB conditional write conflicts. Wrap the full pipeline in a Step Functions state machine with per-step retry policies and a dead-letter queue for persistent failures.

**Input validation.** Validate image format (JPEG, PNG, TIFF, DICOM), file size (reject suspiciously small or large files), and metadata (patient ID format, required fields present) before processing. A malformed input should fail fast with a clear error, not propagate through the pipeline producing garbage results.

**Real model deployment.** This example mocks the SageMaker inference call. A real deployment requires: training or licensing a validated DR classification model, packaging it as a SageMaker model artifact, deploying to a GPU endpoint (ml.g4dn.xlarge minimum for acceptable latency), configuring auto-scaling policies, and implementing model versioning with A/B testing for updates.

**Clinical validation.** Before any patient-facing deployment, the system must be validated on a representative dataset from your target population. This means: collecting a validation set of fundus images graded by multiple ophthalmologists (gold standard), running the model on that set, calculating sensitivity/specificity/AUC at your chosen operating thresholds, and documenting the results for regulatory submission. The thresholds in this example are illustrative; your validated thresholds will differ.

**FDA regulatory pathway.** If the system makes autonomous referral decisions (no physician reviews the AI output), you need FDA clearance. If a physician reviews every result, the regulatory path is different but still exists. Either way, you need regulatory counsel involved early. The documentation requirements (design controls, risk analysis, clinical evidence) take months to prepare.

**Structured logging and monitoring.** Replace print statements with structured JSON logging. Build CloudWatch dashboards tracking: screening volume, ungradable rate, referral rate, model latency, and confidence score distributions. Set alarms for anomalies (sudden spike in ungradable rate might mean a camera is malfunctioning; sudden drop in referral rate might mean model drift).

**IAM least-privilege.** The example uses broad permissions. In production, each Lambda function gets only the specific actions it needs: the quality check Lambda can read from S3 but not invoke SageMaker; the inference Lambda can invoke the specific endpoint but not write to DynamoDB; the storage Lambda can write to DynamoDB but not publish to SNS. Use resource-level policies with specific ARNs.

**VPC and network isolation.** Place SageMaker endpoints and Lambda functions in a VPC. Use VPC endpoints for S3, DynamoDB, SageMaker Runtime, SNS, and CloudWatch Logs to keep all traffic off the public internet. This is a HIPAA requirement for PHI-handling workloads.

**KMS encryption.** Use customer-managed KMS keys (CMKs) for S3 bucket encryption, DynamoDB table encryption, and SageMaker endpoint data encryption. This gives you key rotation control and the ability to revoke access by disabling the key.

**EHR integration.** The screening result needs to flow back to the patient's electronic health record. This typically means HL7 FHIR or HL7v2 messaging to the EHR's results interface. The integration is often the hardest part of the project (not the AI) because EHR APIs are complex, vendor-specific, and require extensive testing with the health system's IT team.

**Patient communication.** Normal results need patient-friendly language (not "No DR probability 0.92"). Referral results need clear next-step instructions. Both need to comply with your organization's patient communication policies and potentially be available in multiple languages.

**DynamoDB Decimal requirement.** This example already handles the Decimal conversion (DynamoDB rejects Python floats), but it's worth calling out explicitly. If you forget this conversion anywhere in your pipeline, you'll get a `TypeError: Float types are not supported` that's confusing if you haven't seen it before. The `json.loads(..., parse_float=Decimal)` pattern handles nested structures cleanly.

---

## Navigation

[← 9.5: Chest X-Ray Triage (Python)](chapter09.05-python-example) | [Chapter 9 Index](chapter09-preface) | [9.7: Radiology AI Triage (Python) →](chapter09.07-python-example)
