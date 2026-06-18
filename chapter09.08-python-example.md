# Recipe 9.8: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the pseudocode walkthrough from Recipe 9.8. Whole slide image analysis in production involves gigapixel images, GPU clusters, and months of model training. This example demonstrates the *shape* of the pipeline using synthetic data and simulated model inference. It shows how you'd orchestrate the AWS pieces (S3, SageMaker, DynamoDB, Step Functions) with boto3. Think of it as a map of the territory, not the territory itself. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image processing libraries:

```bash
pip install boto3 numpy pillow
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `s3:GetObject`, `s3:PutObject` (slide storage and feature output)
- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` (batch inference)
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:GetItem` (metadata and results)
- `sqs:SendMessage`, `sqs:ReceiveMessage` (work queue)
- `states:StartExecution` (pipeline orchestration)

---

## Config and Constants

These go at the top of your module. They define the patch extraction parameters, model configuration, and AWS resource names. In production, most of these would come from environment variables or SSM Parameter Store.

```python
# Patch extraction parameters.
# 256x256 at 20x magnification is the standard for most pathology foundation models.
# Larger patches (512x512) capture more context but require more GPU memory per batch.
# Smaller patches (128x128) are faster but lose architectural context.
PATCH_SIZE = 256
TARGET_MAGNIFICATION = 20
TISSUE_THRESHOLD = 0.5  # minimum fraction of patch that must be tissue to include it

# Feature extraction model configuration.
# The feature dimension depends on your chosen foundation model.
# Most pathology foundation models output 768-2048 dimensional vectors.
FEATURE_DIM = 1024
BATCH_SIZE = 64  # patches per GPU inference batch

# Confidence threshold for flagging uncertain predictions.
# Below this, the result goes to a pathologist review queue rather than
# being presented as a confident AI finding.
CONFIDENCE_THRESHOLD = 0.80

# AWS resource names. In production, pull these from environment variables.
SLIDE_BUCKET = "pathology-slides"
FEATURE_BUCKET = "pathology-features"
RESULTS_TABLE = "pathology-analysis-results"
METADATA_TABLE = "pathology-slide-metadata"
ANALYSIS_QUEUE = "pathology-analysis-queue"
SAGEMAKER_MODEL_NAME = "pathology-feature-extractor"

# Stain normalization reference values (Macenko method).
# These are the target stain vectors for H&E normalization.
# Derived from a reference slide that represents your "ideal" staining.
# Different labs will need different reference values.
STAIN_REF_MATRIX = {
    "hematoxylin": [0.65, 0.70, 0.29],
    "eosin": [0.07, 0.99, 0.11],
}
MAX_CONCENTRATION = [1.9, 1.0]
```

---

## Step 1: Slide Ingestion and Metadata Extraction

*Maps to pseudocode Step 1: `ingest_slide(bucket, key)`. When a new whole slide image lands in S3, this function registers it, extracts header metadata, and queues it for analysis.*

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

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
sqs_client = boto3.client("sqs", config=BOTO3_RETRY_CONFIG)

def ingest_slide(bucket: str, key: str) -> str:
    """
    Register a new whole slide image and queue it for analysis.

    In a real system, this reads the WSI file header (SVS, NDPI, TIFF, or DICOM)
    to extract scanner metadata, magnification, and dimensions without downloading
    the entire multi-gigabyte file. Here we simulate that with S3 head_object
    metadata and assume the uploader tagged the object with relevant info.

    Args:
        bucket: S3 bucket containing the slide
        key:    S3 object key (e.g., "incoming/2026/05/case-4821/slide-01.svs")

    Returns:
        The generated slide_id for tracking this slide through the pipeline.
    """
    # Get object metadata. In production, you'd use a library like openslide
    # to read the WSI header via byte-range requests. Here we use S3 object
    # metadata as a stand-in.
    head_response = s3_client.head_object(Bucket=bucket, Key=key)
    file_size = head_response["ContentLength"]
    content_type = head_response.get("ContentType", "")

    # Extract custom metadata tags set during upload.
    # Your slide scanner integration would populate these.
    user_metadata = head_response.get("Metadata", {})
    scanner_model = user_metadata.get("scanner-model", "unknown")
    magnification = int(user_metadata.get("objective-power", "40"))
    width = int(user_metadata.get("slide-width", "100000"))
    height = int(user_metadata.get("slide-height", "80000"))
    stain_type = user_metadata.get("stain-type", "H&E")

    # Basic validation. A real WSI at 20x+ should be at least 10K pixels per side
    # and at least 500MB. Anything smaller is likely a thumbnail or corrupted upload.
    if width < 10000 or height < 10000:
        raise ValueError(
            f"Slide dimensions {width}x{height} are suspiciously small. "
            f"Expected at least 10000x10000 for a whole slide image."
        )

    if file_size < 500_000_000:  # 500MB minimum
        logger.warning(
            "Slide %s is only %d bytes. Real WSIs are typically 2-5GB. "
            "Proceeding but flagging for review.",
            key, file_size
        )

    # Generate a unique slide ID for tracking
    slide_id = f"WSI-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}"

    # Register in the metadata table
    table = dynamodb.Table(METADATA_TABLE)
    table.put_item(Item={
        "slide_id": slide_id,
        "s3_path": f"s3://{bucket}/{key}",
        "scanner_model": scanner_model,
        "magnification": magnification,
        "width": width,
        "height": height,
        "stain_type": stain_type,
        "file_size_bytes": file_size,
        "status": "QUEUED",
        "ingested_at": datetime.datetime.now(timezone.utc).isoformat(),
    })

    # Queue for analysis
    sqs_client.send_message(
        QueueUrl=ANALYSIS_QUEUE,
        MessageBody=json.dumps({
            "slide_id": slide_id,
            "s3_path": f"s3://{bucket}/{key}",
            "magnification": magnification,
            "width": width,
            "height": height,
        }),
    )

    logger.info("Ingested slide %s (%dx%d, %s)", slide_id, width, height, stain_type)
    return slide_id
```

---

## Step 2: Tissue Detection

*Maps to pseudocode Step 2: `detect_tissue(slide_id, s3_path)`. Identifies which regions of the slide contain tissue vs. empty glass. Uses a low-resolution thumbnail to avoid loading the full gigapixel image.*

```python
from PIL import Image
import io

def detect_tissue(slide_id: str, thumbnail_bytes: bytes) -> tuple[np.ndarray, float]:
    """
    Generate a binary tissue mask from a low-resolution slide thumbnail.

    In production, you'd read the lowest pyramid level of the WSI file using
    openslide or a similar library. Here we accept pre-extracted thumbnail bytes
    (which you'd get via a byte-range read of the WSI's lowest resolution level).

    The approach: convert to HSV color space, threshold on saturation.
    H&E-stained tissue has distinct saturation (pink/purple) compared to
    background glass (white, near-zero saturation). Otsu's method finds the
    optimal threshold automatically.

    Args:
        slide_id:        Slide identifier for logging
        thumbnail_bytes: Raw image bytes of the slide thumbnail (lowest pyramid level)

    Returns:
        Tuple of (tissue_mask as numpy array, tissue_fraction as float)
    """
    # Load the thumbnail image
    image = Image.open(io.BytesIO(thumbnail_bytes)).convert("RGB")
    img_array = np.array(image)

    # Convert RGB to HSV. We care about the saturation channel.
    # Tissue (stained pink/purple) has high saturation.
    # Background glass (white/clear) has near-zero saturation.
    # This is more robust than simple grayscale thresholding because it
    # handles slides with varying brightness levels.
    from PIL import ImageFilter

    hsv_image = image.convert("HSV")
    hsv_array = np.array(hsv_image)
    saturation = hsv_array[:, :, 1]  # saturation channel

    # Otsu thresholding: automatically find the optimal threshold that
    # separates the two populations (tissue vs. background).
    # This is a histogram-based method that minimizes intra-class variance.
    threshold = _otsu_threshold(saturation)
    tissue_mask = saturation > threshold

    # Morphological cleanup.
    # Close small gaps (a tiny hole in tissue is still tissue).
    # Remove small isolated specks (dust, scanner artifacts).
    tissue_mask = _morphological_close(tissue_mask, kernel_size=5)
    tissue_mask = _remove_small_objects(tissue_mask, min_pixels=100)

    # Calculate tissue fraction
    tissue_fraction = float(np.sum(tissue_mask)) / tissue_mask.size

    if tissue_fraction < 0.05:
        logger.warning(
            "Slide %s has only %.1f%% tissue. Possible blank slide or failed scan.",
            slide_id, tissue_fraction * 100
        )

    logger.info(
        "Tissue detection for %s: %.1f%% tissue, mask shape %s",
        slide_id, tissue_fraction * 100, tissue_mask.shape
    )

    return tissue_mask, tissue_fraction

def _otsu_threshold(channel: np.ndarray) -> int:
    """
    Compute Otsu's threshold for a single-channel image.

    Finds the threshold that minimizes the weighted sum of intra-class variances
    for the two groups (foreground and background). This is the standard approach
    for automatic thresholding when you have a bimodal histogram.
    """
    # Build histogram (256 bins for 8-bit image)
    hist, _ = np.histogram(channel.ravel(), bins=256, range=(0, 256))
    total_pixels = channel.size

    # Compute cumulative sums and means for all possible thresholds
    sum_total = np.sum(np.arange(256) * hist)
    sum_background = 0.0
    weight_background = 0
    max_variance = 0.0
    best_threshold = 0

    for t in range(256):
        weight_background += hist[t]
        if weight_background == 0:
            continue

        weight_foreground = total_pixels - weight_background
        if weight_foreground == 0:
            break

        sum_background += t * hist[t]
        mean_background = sum_background / weight_background
        mean_foreground = (sum_total - sum_background) / weight_foreground

        # Between-class variance
        variance = weight_background * weight_foreground * (mean_background - mean_foreground) ** 2

        if variance > max_variance:
            max_variance = variance
            best_threshold = t

    return best_threshold

def _morphological_close(mask: np.ndarray, kernel_size: int) -> np.ndarray:
    """
    Morphological closing: dilate then erode. Fills small holes in tissue regions.
    """
    from scipy import ndimage
    structure = np.ones((kernel_size, kernel_size))
    closed = ndimage.binary_dilation(mask, structure=structure)
    closed = ndimage.binary_erosion(closed, structure=structure)
    return closed

def _remove_small_objects(mask: np.ndarray, min_pixels: int) -> np.ndarray:
    """
    Remove connected components smaller than min_pixels.
    Eliminates dust specks and scanner artifacts.
    """
    from scipy import ndimage
    labeled, num_features = ndimage.label(mask)
    for i in range(1, num_features + 1):
        if np.sum(labeled == i) < min_pixels:
            mask[labeled == i] = False
    return mask
```

---

## Step 3: Patch Coordinate Generation

*Maps to pseudocode Step 3: `generate_patch_coordinates(slide_id, tissue_mask, slide_metadata)`. Determines which patches to extract from the full-resolution image based on the tissue mask.*

```python
def generate_patch_coordinates(
    slide_id: str,
    tissue_mask: np.ndarray,
    slide_width: int,
    slide_height: int,
) -> list[dict]:
    """
    Generate a list of (x, y) coordinates for patches that overlap with tissue.

    Maps the low-resolution tissue mask back to full-resolution coordinates
    and produces a manifest of patches to extract. Only patches where at least
    TISSUE_THRESHOLD fraction is tissue get included.

    A typical slide produces 10,000-50,000 patch coordinates. Each one will
    become a separate inference call in the feature extraction step.

    Args:
        slide_id:     Slide identifier for logging
        tissue_mask:  Binary mask from detect_tissue (low-resolution)
        slide_width:  Full-resolution slide width in pixels
        slide_height: Full-resolution slide height in pixels

    Returns:
        List of patch coordinate dicts with x, y, width, height fields.
    """
    mask_h, mask_w = tissue_mask.shape

    # Scale factors between mask coordinates and full-resolution coordinates
    scale_x = slide_width / mask_w
    scale_y = slide_height / mask_h

    # How many mask pixels correspond to one patch at full resolution?
    patch_mask_w = max(1, int(PATCH_SIZE / scale_x))
    patch_mask_h = max(1, int(PATCH_SIZE / scale_y))

    coordinates = []

    # Walk a grid across the tissue mask
    for mask_y in range(0, mask_h, patch_mask_h):
        for mask_x in range(0, mask_w, patch_mask_w):
            # Extract the mask region corresponding to this patch
            region = tissue_mask[
                mask_y : mask_y + patch_mask_h,
                mask_x : mask_x + patch_mask_w
            ]

            # Check tissue overlap
            if region.size == 0:
                continue
            tissue_overlap = float(np.sum(region)) / region.size

            if tissue_overlap >= TISSUE_THRESHOLD:
                # Convert back to full-resolution coordinates
                full_x = int(mask_x * scale_x)
                full_y = int(mask_y * scale_y)

                coordinates.append({
                    "x": full_x,
                    "y": full_y,
                    "width": PATCH_SIZE,
                    "height": PATCH_SIZE,
                })

    logger.info(
        "Generated %d patch coordinates for slide %s (from %dx%d mask)",
        len(coordinates), slide_id, mask_w, mask_h
    )

    return coordinates
```

---

## Step 4: Feature Extraction via SageMaker Batch Transform

*Maps to pseudocode Step 4: `extract_features(slide_id, s3_path, patch_coordinates)`. This is the GPU-intensive step. In production, you'd use SageMaker Batch Transform to process thousands of patches through a pre-trained pathology foundation model. Here we show how to set up and monitor that job.*

```python
import time

sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)

def prepare_patch_manifest(slide_id: str, coordinates: list[dict]) -> str:
    """
    Write the patch coordinate manifest to S3 as input for SageMaker Batch Transform.

    The manifest tells SageMaker which patches to extract and process.
    Each line is a JSON object with the patch location. The SageMaker
    inference container reads these, extracts the corresponding image region
    from the WSI, runs it through the model, and writes feature vectors.

    Returns:
        The S3 URI of the manifest file.
    """
    manifest_key = f"manifests/{slide_id}/patch-manifest.jsonl"

    # Write as JSON Lines (one JSON object per line)
    lines = [json.dumps(coord) for coord in coordinates]
    manifest_body = "\n".join(lines)

    s3_client.put_object(
        Bucket=FEATURE_BUCKET,
        Key=manifest_key,
        Body=manifest_body.encode("utf-8"),
        ContentType="application/jsonl",
        ServerSideEncryption="aws:kms",
    )

    return f"s3://{FEATURE_BUCKET}/{manifest_key}"

def start_feature_extraction(slide_id: str, manifest_uri: str) -> str:
    """
    Launch a SageMaker Batch Transform job to extract features from all patches.

    Batch Transform is more cost-effective than a real-time endpoint for pathology
    because: (1) slides arrive in bursts, not continuously, (2) latency requirements
    are minutes not milliseconds, and (3) you can use spot instances for batch jobs.

    The inference container is expected to:
    1. Read patch coordinates from the manifest
    2. Extract each patch from the WSI (via byte-range reads to S3)
    3. Apply stain normalization
    4. Run the patch through the feature extractor model
    5. Write feature vectors to the output location

    Returns:
        The SageMaker transform job name for status polling.
    """
    job_name = f"pathology-features-{slide_id}"
    output_uri = f"s3://{FEATURE_BUCKET}/features/{slide_id}/"

    sagemaker_client.create_transform_job(
        TransformJobName=job_name,
        ModelName=SAGEMAKER_MODEL_NAME,
        TransformInput={
            "DataSource": {
                "S3DataSource": {
                    "S3DataType": "S3Prefix",
                    "S3Uri": manifest_uri,
                }
            },
            "ContentType": "application/jsonl",
            "SplitType": "Line",  # each line is one inference request
        },
        TransformOutput={
            "S3OutputPath": output_uri,
            "AssembleWith": "Line",
            "KmsKeyId": "alias/pathology-data-key",  # encrypt output at rest
        },
        TransformResources={
            "InstanceType": "ml.g4dn.xlarge",  # NVIDIA T4 GPU, good price/performance
            "InstanceCount": 1,
            # For large slides (50K+ patches), increase to 2-4 instances.
            # SageMaker distributes the manifest across instances automatically.
        },
        MaxPayloadInMB=6,  # each patch is small; keep payload size reasonable
        BatchStrategy="MultiRecord",  # process multiple patches per request
    )

    logger.info("Started SageMaker transform job: %s", job_name)
    return job_name

def wait_for_feature_extraction(job_name: str, timeout_minutes: int = 30) -> str:
    """
    Poll the SageMaker Batch Transform job until completion.

    In production, you'd use Step Functions with a Wait state and a
    DescribeTransformJob task rather than polling in a loop. This is
    the simplified version for illustration.

    Returns:
        The S3 URI where feature vectors were written.
    """
    deadline = time.time() + (timeout_minutes * 60)

    while time.time() < deadline:
        response = sagemaker_client.describe_transform_job(
            TransformJobName=job_name
        )
        status = response["TransformJobStatus"]

        if status == "Completed":
            output_uri = response["TransformOutput"]["S3OutputPath"]
            logger.info("Feature extraction complete: %s", output_uri)
            return output_uri

        if status == "Failed":
            reason = response.get("FailureReason", "Unknown")
            raise RuntimeError(
                f"Feature extraction job {job_name} failed: {reason}"
            )

        if status == "Stopped":
            raise RuntimeError(f"Feature extraction job {job_name} was stopped")

        # Still running. Wait before polling again.
        logger.info("Job %s status: %s. Waiting...", job_name, status)
        time.sleep(30)

    raise TimeoutError(
        f"Feature extraction job {job_name} did not complete within {timeout_minutes} minutes"
    )
```

---

## Step 5: MIL Aggregation and Classification

*Maps to pseudocode Step 5: `aggregate_and_classify(slide_id, features, patch_coordinates)`. Takes the bag of patch features and produces a slide-level prediction using attention-based Multiple Instance Learning. The attention weights tell us which patches the model considers most diagnostic.*

```python
def load_features_from_s3(slide_id: str, features_uri: str) -> np.ndarray:
    """
    Load the feature vectors produced by SageMaker Batch Transform.

    The output is a numpy array of shape [num_patches, FEATURE_DIM].
    Each row is the feature vector for one patch.
    """
    # List all output files in the features directory
    prefix = f"features/{slide_id}/"
    response = s3_client.list_objects_v2(Bucket=FEATURE_BUCKET, Prefix=prefix)

    all_features = []
    for obj in response.get("Contents", []):
        # Read each output file (SageMaker may split across multiple files)
        body = s3_client.get_object(Bucket=FEATURE_BUCKET, Key=obj["Key"])["Body"]
        content = body.read().decode("utf-8")

        # Each line is a JSON array representing one feature vector
        for line in content.strip().split("\n"):
            if line:
                feature_vector = json.loads(line)
                all_features.append(feature_vector)

    features = np.array(all_features, dtype=np.float32)
    logger.info("Loaded features: shape %s", features.shape)
    return features

def attention_mil_aggregate(features: np.ndarray) -> tuple[dict, np.ndarray]:
    """
    Attention-based Multiple Instance Learning aggregation.

    This is a simplified version of the Ilse et al. (2018) attention MIL mechanism.
    In production, this would be a trained PyTorch/TensorFlow model loaded from
    a model artifact. Here we simulate the forward pass to show the data flow.

    The key idea: each patch gets an attention weight (0 to 1) indicating how
    important it is for the slide-level prediction. The final prediction is a
    weighted sum of patch features, where the weights are learned during training.

    In a real deployment, this model is small enough to run on CPU (it's just
    matrix multiplications over the pre-computed features). The GPU-heavy work
    was done in Step 4.

    Args:
        features: numpy array of shape [num_patches, FEATURE_DIM]

    Returns:
        Tuple of (prediction_dict, attention_weights)
        - prediction_dict: {"benign": prob, "malignant": prob}
        - attention_weights: array of shape [num_patches] with values 0-1
    """
    num_patches = features.shape[0]

    # --- Simulated MIL forward pass ---
    # In production, these weight matrices come from a trained model checkpoint.
    # The attention mechanism learns which morphological features (encoded in the
    # feature vectors) are most indicative of malignancy.

    # Attention network: projects features to attention scores
    # Real architecture: features -> tanh(V * features) -> w^T -> softmax
    np.random.seed(42)  # deterministic for illustration
    attention_v = np.random.randn(FEATURE_DIM, 128).astype(np.float32) * 0.01
    attention_w = np.random.randn(128, 1).astype(np.float32) * 0.01

    # Compute attention scores
    hidden = np.tanh(features @ attention_v)  # [num_patches, 128]
    raw_attention = (hidden @ attention_w).squeeze()  # [num_patches]

    # Softmax to get normalized attention weights (sum to 1)
    exp_attention = np.exp(raw_attention - np.max(raw_attention))
    attention_weights = exp_attention / np.sum(exp_attention)

    # Weighted aggregation: slide-level representation
    slide_representation = attention_weights @ features  # [FEATURE_DIM]

    # Classification head: slide representation -> class probabilities
    classifier_w = np.random.randn(FEATURE_DIM, 2).astype(np.float32) * 0.01
    classifier_b = np.array([0.1, -0.1], dtype=np.float32)

    logits = slide_representation @ classifier_w + classifier_b

    # Softmax for class probabilities
    exp_logits = np.exp(logits - np.max(logits))
    probabilities = exp_logits / np.sum(exp_logits)

    prediction = {
        "benign": float(round(probabilities[0], 4)),
        "malignant": float(round(probabilities[1], 4)),
    }

    return prediction, attention_weights

def generate_heatmap(
    patch_coordinates: list[dict],
    attention_weights: np.ndarray,
    top_k_percentile: float = 95.0,
) -> list[dict]:
    """
    Map attention weights back to slide coordinates for visualization.

    The heatmap shows the pathologist which regions the model focused on.
    Patches in the top 5% of attention are marked as "regions of interest" (ROIs).
    These are the areas the pathologist should examine first.

    Returns:
        List of dicts with x, y, attention, and is_roi fields.
    """
    threshold = float(np.percentile(attention_weights, top_k_percentile))

    heatmap = []
    for i, coord in enumerate(patch_coordinates):
        weight = float(attention_weights[i])
        heatmap.append({
            "x": coord["x"],
            "y": coord["y"],
            "width": coord["width"],
            "height": coord["height"],
            "attention": round(weight, 6),
            "is_roi": weight >= threshold,
        })

    num_rois = sum(1 for h in heatmap if h["is_roi"])
    logger.info("Heatmap: %d total patches, %d ROIs (top %.0f%%)",
                len(heatmap), num_rois, 100 - top_k_percentile)

    return heatmap
```

---

## Step 6: Store Results

*Writes the final prediction, confidence, and heatmap to DynamoDB. Updates the slide status to COMPLETED.*

```python
def store_results(
    slide_id: str,
    prediction: dict,
    attention_weights: np.ndarray,
    heatmap: list[dict],
    num_patches: int,
    tissue_fraction: float,
    processing_start: datetime.datetime,
) -> dict:
    """
    Write analysis results to DynamoDB and update slide status.

    The results record is what the pathologist viewer queries to display
    AI findings alongside the slide image.

    Args:
        slide_id:          Unique slide identifier
        prediction:        Class probability dict (e.g., {"benign": 0.08, "malignant": 0.92})
        attention_weights: Raw attention array (stored as S3 reference, not inline)
        heatmap:           List of patch coordinates with attention and ROI flags
        num_patches:       Total patches analyzed
        tissue_fraction:   Fraction of slide that was tissue
        processing_start:  When processing began (for latency tracking)

    Returns:
        The stored result record.
    """
    # Determine the predicted class and confidence
    predicted_class = max(prediction, key=prediction.get)
    confidence = prediction[predicted_class]

    # Extract just the ROI patches for the summary (full heatmap stored separately)
    top_regions = [h for h in heatmap if h["is_roi"]]

    # Store the full heatmap as a separate S3 object (too large for DynamoDB item)
    heatmap_key = f"heatmaps/{slide_id}/attention-heatmap.json"
    s3_client.put_object(
        Bucket=FEATURE_BUCKET,
        Key=heatmap_key,
        Body=json.dumps(heatmap).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    processing_time = (datetime.datetime.now(timezone.utc) - processing_start).total_seconds()

    # Write the results record
    # DynamoDB requires Decimal for numeric values, not float.
    results_table = dynamodb.Table(RESULTS_TABLE)
    result_record = {
        "slide_id": slide_id,
        "prediction": predicted_class,
        "confidence": Decimal(str(round(confidence, 4))),
        "class_probabilities": {
            k: Decimal(str(round(v, 4))) for k, v in prediction.items()
        },
        "num_patches_analyzed": num_patches,
        "tissue_fraction": Decimal(str(round(tissue_fraction, 4))),
        "processing_time_seconds": Decimal(str(round(processing_time, 1))),
        "top_regions": top_regions[:10],  # store top 10 ROIs inline
        "heatmap_path": f"s3://{FEATURE_BUCKET}/{heatmap_key}",
        "model_version": SAGEMAKER_MODEL_NAME,
        "needs_review": confidence < CONFIDENCE_THRESHOLD,
        "completed_at": datetime.datetime.now(timezone.utc).isoformat(),
    }

    results_table.put_item(Item=result_record)

    # Update slide status in metadata table
    metadata_table = dynamodb.Table(METADATA_TABLE)
    metadata_table.update_item(
        Key={"slide_id": slide_id},
        UpdateExpression="SET #s = :status, completed_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "COMPLETED",
            ":ts": datetime.datetime.now(timezone.utc).isoformat(),
        },
    )

    logger.info(
        "Stored results for %s: %s (confidence %.2f, %d patches, %.0fs)",
        slide_id, predicted_class, confidence, num_patches, processing_time
    )

    return result_record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In production, each step would be a separate Lambda function orchestrated by Step Functions. This single-function version is useful for local testing and understanding the data flow.

```python
def analyze_slide(bucket: str, key: str) -> dict:
    """
    Run the full pathology slide analysis pipeline for one slide.

    This orchestrates all five steps: ingest, tissue detection, patch extraction,
    feature extraction, and MIL classification.

    In a real deployment, Step Functions would orchestrate these as separate
    Lambda/SageMaker steps with error handling, retries, and timeouts at each stage.
    This single function shows the end-to-end flow.

    Args:
        bucket: S3 bucket containing the slide
        key:    S3 object key for the WSI file

    Returns:
        The analysis result record.
    """
    processing_start = datetime.datetime.now(timezone.utc)

    # Step 1: Ingest and register the slide
    print(f"Step 1: Ingesting slide s3://{bucket}/{key}")
    slide_id = ingest_slide(bucket, key)
    print(f"  Registered as {slide_id}")

    # Step 2: Tissue detection
    # In production, you'd read the lowest pyramid level from the WSI.
    # Here we simulate with a synthetic thumbnail.
    print("Step 2: Detecting tissue regions")
    synthetic_thumbnail = _generate_synthetic_thumbnail()
    tissue_mask, tissue_fraction = detect_tissue(slide_id, synthetic_thumbnail)
    print(f"  Tissue fraction: {tissue_fraction:.1%}")

    # Step 3: Generate patch coordinates
    print("Step 3: Generating patch coordinates")
    # Use metadata from ingestion (in production, read from DynamoDB)
    slide_width = 100000
    slide_height = 80000
    coordinates = generate_patch_coordinates(
        slide_id, tissue_mask, slide_width, slide_height
    )
    print(f"  Generated {len(coordinates)} patch coordinates")

    # Step 4: Feature extraction via SageMaker
    print("Step 4: Extracting features (SageMaker Batch Transform)")
    manifest_uri = prepare_patch_manifest(slide_id, coordinates)
    job_name = start_feature_extraction(slide_id, manifest_uri)
    features_uri = wait_for_feature_extraction(job_name)
    features = load_features_from_s3(slide_id, features_uri)
    print(f"  Extracted features: {features.shape}")

    # Step 5: MIL aggregation and classification
    print("Step 5: Running MIL aggregation")
    prediction, attention_weights = attention_mil_aggregate(features)
    heatmap = generate_heatmap(coordinates, attention_weights)
    predicted_class = max(prediction, key=prediction.get)
    print(f"  Prediction: {predicted_class} (confidence: {prediction[predicted_class]:.3f})")
    print(f"  ROIs identified: {sum(1 for h in heatmap if h['is_roi'])}")

    # Step 6: Store results
    print("Step 6: Storing results")
    result = store_results(
        slide_id=slide_id,
        prediction=prediction,
        attention_weights=attention_weights,
        heatmap=heatmap,
        num_patches=len(coordinates),
        tissue_fraction=tissue_fraction,
        processing_start=processing_start,
    )
    print(f"  Done. needs_review={result['needs_review']}")

    return result

def _generate_synthetic_thumbnail() -> bytes:
    """
    Generate a synthetic slide thumbnail for testing.

    Creates a 500x400 image with a simulated tissue region (colored area)
    surrounded by background (white). This stands in for the lowest pyramid
    level of a real WSI.
    """
    # Create a white background (simulating glass)
    img = Image.new("RGB", (500, 400), color=(240, 240, 245))
    pixels = np.array(img)

    # Add a simulated tissue region (pink/purple, like H&E staining)
    # Tissue occupies roughly the center 60% of the slide
    tissue_y_start, tissue_y_end = 80, 320
    tissue_x_start, tissue_x_end = 100, 400

    # Simulate H&E stained tissue: pink-purple with some variation
    np.random.seed(123)
    tissue_region = np.random.randint(
        low=[180, 100, 160],
        high=[220, 160, 200],
        size=(tissue_y_end - tissue_y_start, tissue_x_end - tissue_x_start, 3),
        dtype=np.uint8,
    )
    pixels[tissue_y_start:tissue_y_end, tissue_x_start:tissue_x_end] = tissue_region

    # Convert back to image and then to bytes
    result_img = Image.fromarray(pixels)
    buffer = io.BytesIO()
    result_img.save(buffer, format="PNG")
    return buffer.getvalue()

# Run the pipeline against a test slide
if __name__ == "__main__":
    # NOTE: This will fail without real AWS resources configured.
    # For local testing, mock the AWS calls or use localstack.
    result = analyze_slide(
        bucket="pathology-slides",
        key="incoming/2026/05/case-9921/slide-01.svs",
    )
    print("\n--- Final Result ---")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example shows the shape of a pathology slide analysis pipeline. It demonstrates the orchestration pattern, the data flow between steps, and how the AWS services fit together. But there's a significant distance between this and something you'd deploy in a clinical lab. Here's where that gap lives:

**The feature extraction model.** This example simulates model inference with random weights. A real deployment uses a pathology foundation model (trained on millions of patches via self-supervised learning) that produces meaningful feature representations. Training or fine-tuning that model is a separate, substantial effort. You'd typically start with a pre-trained checkpoint and fine-tune the MIL classifier on your specific task (cancer type, grading system).

**Whole slide image I/O.** Reading patches from a gigapixel WSI requires specialized libraries (openslide, tifffile, or DICOM WSI readers) that handle the pyramidal file format and byte-range access. This example sidesteps that complexity entirely. In production, your SageMaker inference container needs these libraries installed and configured for each scanner format you support.

**Stain normalization.** The Macenko or Reinhard stain normalization methods are critical for cross-lab generalization. Without them, a model trained on slides from one lab will underperform on slides stained differently. This example mentions normalization but doesn't implement it. The implementation involves optical density decomposition and stain vector estimation, which adds meaningful complexity.

**Error handling and retries.** A 20-minute GPU job that fails at minute 19 because of a transient S3 error is expensive. Production pipelines need checkpoint/resume capability, idempotent processing (so retrying a failed slide doesn't produce duplicate results), and dead-letter queues for slides that repeatedly fail.

**Step Functions orchestration.** This example runs everything sequentially in one function. Production uses Step Functions to manage the pipeline as a state machine with: parallel processing of multiple slides, wait states for SageMaker jobs, error handling with retries at each step, and timeout protection. The Step Functions definition is a separate artifact.

**Cost optimization.** Feature extraction dominates cost. Production optimizations include: using spot instances for batch transform (60-70% savings), batching multiple slides into a single transform job, caching features for slides that need re-analysis with updated classifiers, and right-sizing GPU instances based on actual patch counts.

**Multi-scanner support.** Different WSI scanners (Aperio, Hamamatsu, Leica, Philips) produce different file formats with different color profiles. A production system needs format-specific readers and scanner-aware stain normalization. Testing across scanner types is essential before deployment.

**Pathologist viewer integration.** The heatmap and predictions need to appear in the pathologist's existing slide viewer (e.g., Sectra, Proscia, PathAI viewer). This requires integration with the viewer's API, overlay rendering at the correct coordinates and zoom levels, and a UX that doesn't disrupt the pathologist's workflow.

**Regulatory considerations.** If your system's output influences diagnostic decisions (even as "decision support"), you're likely in FDA-regulated territory. The regulatory pathway (510(k), De Novo, or Breakthrough Device) requires clinical validation studies, quality management systems, and ongoing post-market surveillance. This is a 12-18 month process per indication.

**Audit trail and versioning.** HIPAA requires a complete audit trail. Every slide processed, every model version used, every prediction made, and every pathologist action (confirmed, overridden, ignored) must be logged immutably. Model version tracking is critical: when you update the model, you need to know which predictions were made by which version.

**Testing with real WSI data.** Unit tests with synthetic thumbnails (like this example) verify the pipeline logic. But you also need integration tests with real whole slide images from public datasets (TCGA, Camelyon) to validate that the full pipeline produces clinically meaningful results. Never use patient slides in development without IRB approval and proper de-identification.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.8](chapter09.08-pathology-slide-analysis.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
