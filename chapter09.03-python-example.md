# Recipe 9.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 9.3. It shows one way you could translate wound photography measurement concepts into working Python code. It is not production-ready. There's no error handling to speak of, no retry logic, no input validation beyond the basics. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a wound care clinic on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few image processing libraries:

```bash
pip install boto3 numpy pillow scipy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `s3:PutObject`, `s3:GetObject` (wound image storage)
- `sagemaker:InvokeEndpoint` (segmentation model inference)
- `dynamodb:PutItem`, `dynamodb:Query` (measurement storage)

For local testing without a trained SageMaker model, we'll include a synthetic segmentation function that simulates what a real U-Net endpoint would return.

---

## Config and Constants

These go at the top of your module. The reference marker specs and measurement thresholds are configuration, not logic. Readers should see these before the functions that use them.

```python
import io
import json
import logging
import datetime
from decimal import Decimal
from datetime import timezone

import boto3
import numpy as np
from PIL import Image, ImageDraw
from botocore.config import Config

# Configure logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (patient identifiers,
# wound images, or measurement values tied to a patient).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Adaptive mode uses exponential backoff
# with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Reference Marker Configuration ---
# We use a circular blue calibration sticker with a known physical diameter.
# The system detects this circle in the image to compute pixels-per-cm.
MARKER_DIAMETER_CM = 2.5  # Physical diameter of the reference marker
MARKER_COLOR_RANGE = {
    # HSV color range for detecting the blue marker.
    # These values work for the standard blue calibration stickers.
    # You'll need to tune these if you use a different colored marker.
    # NOTE: This config shows what a production implementation would use.
    # The simplified detect_reference_marker() below uses RGB thresholds
    # for readability. Wire this config into your detection logic in production.
    "hue_min": 100,
    "hue_max": 130,
    "sat_min": 100,
    "sat_max": 255,
    "val_min": 80,
    "val_max": 255,
}

# --- Measurement Thresholds ---
# Minimum pixels-per-cm for a valid scale factor. Below this, the marker
# is too small in the image (camera too far away) for reliable measurement.
MIN_PIXELS_PER_CM = 10
# Maximum pixels-per-cm. Above this, something is wrong (marker too close,
# or a false detection).
MAX_PIXELS_PER_CM = 100

# Segmentation confidence threshold. Below this, flag for human review.
SEGMENTATION_CONFIDENCE_THRESHOLD = 0.7

# Wound area change threshold for alerting (percentage increase).
WOUND_GROWTH_ALERT_THRESHOLD_PCT = 10.0

# --- AWS Resource Names ---
# Replace these with your actual resource names.
S3_BUCKET = "wound-images-bucket"
SAGEMAKER_ENDPOINT = "wound-segmentation-unet"
DYNAMODB_TABLE = "wound-measurements"

# --- Clients ---
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
```

---

## Synthetic Test Data

For testing without real wound images (which are PHI and require proper data governance), we generate synthetic images with a known "wound" region and reference marker. This lets you validate the measurement pipeline end-to-end.

```python
def generate_synthetic_wound_image(
    image_size=(1024, 768),
    wound_center=(500, 400),
    wound_axes=(80, 55),
    marker_center=(200, 600),
    marker_radius_px=53,
):
    """
    Generate a synthetic wound image for testing.

    Creates an image with:
    - A skin-toned background (simulating periwound tissue)
    - An elliptical red region (simulating a wound bed)
    - A blue circle (simulating the calibration marker)

    The known dimensions let us verify that our measurement pipeline
    produces correct results. If the marker is 53px radius and represents
    a 2.5cm diameter circle, then pixels_per_cm = (53*2) / 2.5 = 42.4.

    Returns:
        tuple: (PIL Image, dict of ground truth values)
    """
    img = Image.new("RGB", image_size, color=(210, 180, 160))  # skin tone
    draw = ImageDraw.Draw(img)

    # Draw the "wound" as a red ellipse
    wound_bbox = [
        wound_center[0] - wound_axes[0],
        wound_center[1] - wound_axes[1],
        wound_center[0] + wound_axes[0],
        wound_center[1] + wound_axes[1],
    ]
    draw.ellipse(wound_bbox, fill=(180, 40, 40))  # dark red, granulation tissue

    # Draw the reference marker as a blue circle
    marker_bbox = [
        marker_center[0] - marker_radius_px,
        marker_center[1] - marker_radius_px,
        marker_center[0] + marker_radius_px,
        marker_center[1] + marker_radius_px,
    ]
    draw.ellipse(marker_bbox, fill=(30, 60, 200))  # blue calibration marker

    # Compute ground truth measurements
    pixels_per_cm = (marker_radius_px * 2) / MARKER_DIAMETER_CM
    # Ellipse area = pi * a * b (in pixels), then convert to cm²
    area_px = np.pi * wound_axes[0] * wound_axes[1]
    area_cm2 = area_px / (pixels_per_cm ** 2)
    length_cm = (wound_axes[0] * 2) / pixels_per_cm
    width_cm = (wound_axes[1] * 2) / pixels_per_cm

    ground_truth = {
        "pixels_per_cm": round(pixels_per_cm, 2),
        "area_cm2": round(area_cm2, 2),
        "length_cm": round(length_cm, 2),
        "width_cm": round(width_cm, 2),
    }

    return img, ground_truth
```

---

## Step 1: Validate and Upload the Wound Image

*Maps to pseudocode Step 1 in the main recipe. We check basic image properties and upload to S3 with metadata for the audit trail.*

```python
def validate_and_upload(
    image: Image.Image,
    patient_id: str,
    wound_id: str,
    wound_location: str,
    clinician_id: str,
) -> str:
    """
    Validate image quality and upload to S3.

    Args:
        image: PIL Image of the wound photograph
        patient_id: Patient identifier
        wound_id: Unique wound identifier (patient can have multiple wounds)
        wound_location: Anatomical location (e.g., "sacrum", "left heel")
        clinician_id: Who took the photo

    Returns:
        The S3 key where the image was stored.

    Raises:
        ValueError: If image fails validation checks.
    """
    # Check minimum resolution. Below 640x640, wound boundary detection
    # becomes unreliable because there aren't enough pixels to distinguish
    # wound edge from periwound tissue.
    width, height = image.size
    if width < 640 or height < 640:
        raise ValueError(
            f"Image resolution {width}x{height} too low. "
            f"Minimum 640x640 required for reliable measurement."
        )

    # Generate the S3 key with a path structure that supports efficient
    # querying by patient and wound.
    timestamp = datetime.datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    s3_key = f"wound-images/{patient_id}/{wound_id}/{timestamp}.jpg"

    # Convert to bytes for upload
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    buffer.seek(0)

    # Upload with server-side encryption and metadata.
    # The metadata fields are NOT PHI themselves (they're identifiers),
    # but they link to PHI, so the bucket must be under BAA.
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
        ContentType="image/jpeg",
        ServerSideEncryption="aws:kms",
        Metadata={
            "patient_id": patient_id,
            "wound_id": wound_id,
            "wound_location": wound_location,
            "clinician_id": clinician_id,
            "capture_timestamp": timestamp,
        },
    )

    logger.info(f"Uploaded wound image to s3://{S3_BUCKET}/{s3_key}")
    return s3_key
```

---

## Step 2: Detect Reference Marker and Compute Scale

*Maps to pseudocode Step 2. We find the blue calibration circle in the image and compute how many pixels equal one centimeter.*

```python
def detect_reference_marker(image: Image.Image) -> dict:
    """
    Detect the circular reference marker and compute pixels-per-cm.

    This uses a simple color-based detection approach: find the largest
    cluster of blue pixels, fit a circle to it, and use the known physical
    diameter to compute scale.

    In production, you'd use a more robust approach (Hough circle transform,
    or a small trained detector). This simplified version works for the
    synthetic test images and demonstrates the concept.

    Args:
        image: PIL Image containing the wound and reference marker.

    Returns:
        dict with keys:
        - "detected": bool, whether a valid marker was found
        - "pixels_per_cm": float, the scale factor (if detected)
        - "marker_center": tuple (x, y) pixel coordinates of marker center
        - "marker_radius_px": float, detected radius in pixels
    """
    img_array = np.array(image)

    # Simple color thresholding for blue marker detection.
    # We work in RGB here for simplicity. A production system would
    # convert to HSV for more robust color detection under varying lighting.
    r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]

    # Blue marker: high blue channel, low red and green
    blue_mask = (b > 150) & (r < 100) & (g < 120)

    # Count blue pixels
    blue_pixel_count = np.sum(blue_mask)

    if blue_pixel_count < 100:
        # Not enough blue pixels to be a marker
        logger.warning("No reference marker detected in image.")
        return {"detected": False, "pixels_per_cm": None}

    # Find the centroid of blue pixels (marker center)
    blue_coords = np.argwhere(blue_mask)  # returns (row, col) pairs
    center_row = np.mean(blue_coords[:, 0])
    center_col = np.mean(blue_coords[:, 1])

    # Estimate radius from the area of blue pixels.
    # Area of circle = pi * r^2, so r = sqrt(area / pi)
    estimated_radius_px = np.sqrt(blue_pixel_count / np.pi)

    # Compute pixels per centimeter from the known marker diameter
    marker_diameter_px = estimated_radius_px * 2
    pixels_per_cm = marker_diameter_px / MARKER_DIAMETER_CM

    # Sanity check: is the scale factor in a reasonable range?
    if pixels_per_cm < MIN_PIXELS_PER_CM or pixels_per_cm > MAX_PIXELS_PER_CM:
        logger.warning(
            f"Scale factor {pixels_per_cm:.1f} px/cm outside expected range "
            f"[{MIN_PIXELS_PER_CM}, {MAX_PIXELS_PER_CM}]. "
            f"Check marker positioning and camera distance."
        )
        return {"detected": False, "pixels_per_cm": None}

    return {
        "detected": True,
        "pixels_per_cm": round(pixels_per_cm, 2),
        "marker_center": (int(center_col), int(center_row)),
        "marker_radius_px": round(estimated_radius_px, 1),
    }
```

---

## Step 3: Segment the Wound

*Maps to pseudocode Step 3. In production, this calls a SageMaker endpoint hosting a trained U-Net model. For testing, we include a synthetic segmentation function that uses color thresholding to simulate what the model would return.*

```python
def segment_wound_synthetic(image: Image.Image) -> tuple:
    """
    Synthetic wound segmentation for testing.

    In production, you'd call a SageMaker endpoint with a trained U-Net.
    This function simulates that by detecting the red wound region using
    color thresholding. It returns the same data structure a real model would.

    Args:
        image: PIL Image of the wound.

    Returns:
        tuple: (binary_mask as numpy array, confidence score)
    """
    img_array = np.array(image)
    r, g, b = img_array[:, :, 0], img_array[:, :, 1], img_array[:, :, 2]

    # Detect red wound region (high red, low green and blue)
    wound_mask = (r > 120) & (g < 100) & (b < 100)

    # Simulate a confidence score (in reality, this comes from the model's
    # output probabilities averaged over wound pixels)
    confidence = 0.91 if np.sum(wound_mask) > 500 else 0.45

    return wound_mask.astype(np.uint8), confidence


def segment_wound_sagemaker(image: Image.Image) -> tuple:
    """
    Call SageMaker endpoint for wound segmentation.

    This is what you'd use in production. The endpoint hosts a trained
    U-Net model that takes an image and returns a probability mask.

    Args:
        image: PIL Image of the wound.

    Returns:
        tuple: (binary_mask as numpy array, confidence score)
    """
    # Resize to model's expected input dimensions.
    # Most U-Net variants expect square inputs. 512x512 is common.
    original_size = image.size  # (width, height)
    resized = image.resize((512, 512))

    # Convert to bytes for the SageMaker endpoint
    buffer = io.BytesIO()
    resized.save(buffer, format="JPEG")
    payload = buffer.getvalue()

    # Invoke the SageMaker endpoint
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT,
        ContentType="image/jpeg",
        Accept="application/json",
        Body=payload,
    )

    # Parse the response. The model returns a probability mask as a
    # flattened array of floats (0.0 to 1.0 per pixel).
    result = json.loads(response["Body"].read().decode("utf-8"))
    probability_mask = np.array(result["mask"]).reshape((512, 512))

    # Threshold to binary
    binary_mask = (probability_mask > 0.5).astype(np.uint8)

    # Compute confidence: mean probability of pixels classified as wound
    wound_probs = probability_mask[binary_mask == 1]
    confidence = float(np.mean(wound_probs)) if len(wound_probs) > 0 else 0.0

    # Resize mask back to original image dimensions
    mask_image = Image.fromarray(binary_mask * 255)
    mask_resized = mask_image.resize(original_size, resample=Image.NEAREST)
    final_mask = (np.array(mask_resized) > 127).astype(np.uint8)

    return final_mask, confidence
```

---

## Step 4: Compute Wound Measurements

*Maps to pseudocode Step 4. Given the segmentation mask and scale factor, we compute area, length, width, perimeter, and circularity in real-world units.*

```python
def compute_measurements(segmentation_mask: np.ndarray, pixels_per_cm: float) -> dict:
    """
    Compute wound measurements from the segmentation mask.

    This is where pixels become centimeters. The scale factor from the
    reference marker converts pixel counts into physical dimensions that
    clinicians can use for treatment decisions.

    Args:
        segmentation_mask: Binary numpy array (1 = wound, 0 = background)
        pixels_per_cm: Scale factor from marker detection

    Returns:
        dict with area_cm2, length_cm, width_cm, perimeter_cm, circularity
    """
    # Count wound pixels for area
    wound_pixel_count = int(np.sum(segmentation_mask))

    if wound_pixel_count == 0:
        return {
            "area_cm2": 0.0,
            "length_cm": 0.0,
            "width_cm": 0.0,
            "perimeter_cm": 0.0,
            "circularity": 0.0,
        }

    # Convert pixel area to cm²
    # Each pixel represents (1/pixels_per_cm)² square centimeters
    area_cm2 = wound_pixel_count / (pixels_per_cm ** 2)

    # Find wound boundary pixels for perimeter calculation.
    # A boundary pixel is a wound pixel that has at least one non-wound neighbor.
    # We use a simple erosion approach: erode the mask by 1 pixel, then
    # subtract from original to get the boundary.
    from scipy import ndimage  # only needed for morphological operations

    eroded = ndimage.binary_erosion(segmentation_mask)
    boundary = segmentation_mask.astype(int) - eroded.astype(int)
    perimeter_px = int(np.sum(boundary))
    perimeter_cm = perimeter_px / pixels_per_cm

    # Find bounding box for length and width.
    # We use the minimum bounding rectangle of the wound region.
    wound_coords = np.argwhere(segmentation_mask == 1)  # (row, col) pairs
    # Simple approach: axis-aligned bounding box
    min_row, min_col = wound_coords.min(axis=0)
    max_row, max_col = wound_coords.max(axis=0)
    bbox_height_px = max_row - min_row
    bbox_width_px = max_col - min_col

    # Length = longer dimension, Width = shorter dimension
    length_px = max(bbox_height_px, bbox_width_px)
    width_px = min(bbox_height_px, bbox_width_px)
    length_cm = length_px / pixels_per_cm
    width_cm = width_px / pixels_per_cm

    # Circularity: how round is the wound? 1.0 = perfect circle.
    # Formula: 4 * pi * area / perimeter^2
    # Useful for tracking wound shape changes over time.
    if perimeter_px > 0:
        circularity = (4 * np.pi * wound_pixel_count) / (perimeter_px ** 2)
    else:
        circularity = 0.0

    return {
        "area_cm2": round(float(area_cm2), 2),
        "length_cm": round(float(length_cm), 2),
        "width_cm": round(float(width_cm), 2),
        "perimeter_cm": round(float(perimeter_cm), 2),
        "circularity": round(float(circularity), 3),
    }
```

---

## Step 5: Store Measurement and Compute Healing Trajectory

*Maps to pseudocode Step 5. We write the measurement to DynamoDB and compare against previous measurements to compute healing rate.*

```python
def store_measurement(
    patient_id: str,
    wound_id: str,
    measurements: dict,
    confidence: float,
    image_s3_key: str,
    metadata: dict,
) -> dict:
    """
    Store the wound measurement in DynamoDB and compute healing trajectory.

    The table uses a composite key:
    - Partition key: patient_id (groups all data for one patient)
    - Sort key: wound_id#timestamp (orders measurements chronologically per wound)

    This key design supports two access patterns efficiently:
    1. Get latest measurement for a specific wound (query with sort key prefix)
    2. Get full timeline for a wound (query with sort key begins_with)

    Args:
        patient_id: Patient identifier
        wound_id: Wound identifier
        measurements: Dict from compute_measurements()
        confidence: Segmentation confidence score
        image_s3_key: S3 key of the original image
        metadata: Additional context (clinician, location, device)

    Returns:
        The complete record that was stored, including healing trajectory.
    """
    table = dynamodb.Table(DYNAMODB_TABLE)
    now = datetime.datetime.now(timezone.utc)
    timestamp_str = now.isoformat()

    # Build the measurement record.
    # DynamoDB requires Decimal for numeric values, not float.
    # This is a common gotcha that causes TypeError at runtime.
    record = {
        "patient_id": patient_id,
        "wound_id_timestamp": f"{wound_id}#{timestamp_str}",
        "wound_id": wound_id,
        "measurement_date": timestamp_str,
        "area_cm2": Decimal(str(measurements["area_cm2"])),
        "length_cm": Decimal(str(measurements["length_cm"])),
        "width_cm": Decimal(str(measurements["width_cm"])),
        "perimeter_cm": Decimal(str(measurements["perimeter_cm"])),
        "circularity": Decimal(str(measurements["circularity"])),
        "confidence": Decimal(str(round(confidence, 3))),
        "image_s3_key": image_s3_key,
        # In production, you'd also store the segmentation mask to S3 for audit
        # and include mask_s3_key here. Omitted for simplicity in this example.
        "clinician_id": metadata.get("clinician_id", "unknown"),
        "wound_location": metadata.get("wound_location", "unspecified"),
        "device_info": metadata.get("device_info", "unknown"),
    }

    # Query for the most recent previous measurement of this wound
    # to compute healing trajectory.
    response = table.query(
        KeyConditionExpression="patient_id = :pid AND begins_with(wound_id_timestamp, :wid)",
        ExpressionAttributeValues={
            ":pid": patient_id,
            ":wid": wound_id,
        },
        ScanIndexForward=False,  # Descending order (most recent first)
        Limit=1,
    )

    healing_trajectory = None
    previous_items = response.get("Items", [])

    if previous_items:
        prev = previous_items[0]
        prev_area = float(prev["area_cm2"])
        prev_date = datetime.datetime.fromisoformat(prev["measurement_date"])
        days_elapsed = (now - prev_date).days

        if days_elapsed > 0 and prev_area > 0:
            current_area = measurements["area_cm2"]
            area_change_pct = ((current_area - prev_area) / prev_area) * 100
            healing_rate = (prev_area - current_area) / days_elapsed

            healing_trajectory = {
                "previous_area_cm2": Decimal(str(prev_area)),
                "area_change_pct": Decimal(str(round(area_change_pct, 1))),
                "days_since_last": days_elapsed,
                "healing_rate_cm2_per_day": Decimal(str(round(healing_rate, 4))),
            }

            # Alert if wound is growing significantly
            if area_change_pct > WOUND_GROWTH_ALERT_THRESHOLD_PCT:
                logger.warning(
                    f"ALERT: Wound {wound_id} growth detected: "
                    f"{area_change_pct:.1f}% over {days_elapsed} days. "
                    f"Review required."
                )

            record["healing_trajectory"] = healing_trajectory

    # Write to DynamoDB
    table.put_item(Item=record)
    logger.info(f"Stored measurement for {patient_id}/{wound_id}")

    return record
```

---

## Full Pipeline: End-to-End Wound Measurement

This assembles all the steps into a single callable function. The print statements show progress so you can trace execution during development.

```python
def measure_wound(
    image: Image.Image,
    patient_id: str,
    wound_id: str,
    wound_location: str,
    clinician_id: str,
    use_sagemaker: bool = False,
) -> dict:
    """
    Full wound measurement pipeline: validate, calibrate, segment, measure, store.

    Args:
        image: PIL Image of the wound with reference marker
        patient_id: Patient identifier
        wound_id: Unique wound identifier
        wound_location: Anatomical location
        clinician_id: Who captured the image
        use_sagemaker: If True, call real SageMaker endpoint. If False, use synthetic.

    Returns:
        Complete measurement record including healing trajectory.
    """
    print(f"\n{'='*60}")
    print(f"WOUND MEASUREMENT PIPELINE")
    print(f"Patient: {patient_id} | Wound: {wound_id} | Location: {wound_location}")
    print(f"{'='*60}\n")

    # Step 1: Validate and upload
    print("[Step 1] Validating image and uploading to S3...")
    s3_key = validate_and_upload(
        image=image,
        patient_id=patient_id,
        wound_id=wound_id,
        wound_location=wound_location,
        clinician_id=clinician_id,
    )
    print(f"  Uploaded to: s3://{S3_BUCKET}/{s3_key}")

    # Step 2: Detect reference marker
    print("\n[Step 2] Detecting reference marker...")
    marker_result = detect_reference_marker(image)

    if not marker_result["detected"]:
        print("  WARNING: No reference marker detected!")
        print("  Image flagged for manual review. Cannot produce calibrated measurement.")
        return {
            "status": "MARKER_NOT_DETECTED",
            "image_s3_key": s3_key,
            "message": "Reference marker not found. Manual review required.",
        }

    pixels_per_cm = marker_result["pixels_per_cm"]
    print(f"  Marker detected at {marker_result['marker_center']}")
    print(f"  Scale factor: {pixels_per_cm} pixels/cm")

    # Step 3: Segment the wound
    print("\n[Step 3] Segmenting wound region...")
    if use_sagemaker:
        mask, confidence = segment_wound_sagemaker(image)
    else:
        mask, confidence = segment_wound_synthetic(image)

    wound_pixel_count = int(np.sum(mask))
    print(f"  Wound pixels detected: {wound_pixel_count}")
    print(f"  Segmentation confidence: {confidence:.3f}")

    if confidence < SEGMENTATION_CONFIDENCE_THRESHOLD:
        print(f"  WARNING: Confidence below threshold ({SEGMENTATION_CONFIDENCE_THRESHOLD})")
        print("  Measurement will be flagged for review.")

    # Step 4: Compute measurements
    print("\n[Step 4] Computing wound measurements...")
    measurements = compute_measurements(mask, pixels_per_cm)
    print(f"  Area:        {measurements['area_cm2']} cm²")
    print(f"  Length:      {measurements['length_cm']} cm")
    print(f"  Width:       {measurements['width_cm']} cm")
    print(f"  Perimeter:   {measurements['perimeter_cm']} cm")
    print(f"  Circularity: {measurements['circularity']}")

    # Step 5: Store and compute trajectory
    print("\n[Step 5] Storing measurement and computing healing trajectory...")
    metadata = {
        "clinician_id": clinician_id,
        "wound_location": wound_location,
        "device_info": "synthetic_test",
    }

    record = store_measurement(
        patient_id=patient_id,
        wound_id=wound_id,
        measurements=measurements,
        confidence=confidence,
        image_s3_key=s3_key,
        metadata=metadata,
    )

    if "healing_trajectory" in record:
        traj = record["healing_trajectory"]
        print(f"  Previous area: {traj['previous_area_cm2']} cm²")
        print(f"  Area change:   {traj['area_change_pct']}%")
        print(f"  Days elapsed:  {traj['days_since_last']}")
        print(f"  Healing rate:  {traj['healing_rate_cm2_per_day']} cm²/day")
    else:
        print("  No previous measurement found (first measurement for this wound)")

    print(f"\n{'='*60}")
    print("MEASUREMENT COMPLETE")
    print(f"{'='*60}\n")

    return record


# --- Run the pipeline with synthetic data ---
if __name__ == "__main__":
    # Generate a synthetic wound image for testing
    print("Generating synthetic wound image...")
    image, ground_truth = generate_synthetic_wound_image()
    print(f"Ground truth: {ground_truth}")

    # Run the measurement pipeline
    # Note: This will fail on S3/DynamoDB calls unless you have
    # the actual AWS resources set up. For local testing, you'd
    # mock the AWS clients or use localstack.
    result = measure_wound(
        image=image,
        patient_id="PAT-TEST-001",
        wound_id="WND-001-sacral",
        wound_location="sacrum",
        clinician_id="RN-SMITH",
        use_sagemaker=False,
    )

    print("\nFinal result:")
    print(json.dumps(result, indent=2, default=str))
```

---

## Gap to Production

This example demonstrates the measurement pipeline's shape. Here's what you'd need to add before deploying to a wound care clinic:

**Error handling and retries.** Every AWS API call can fail. S3 uploads can timeout. SageMaker endpoints can return 5xx errors under load. DynamoDB can throttle writes. Wrap each call in try/except with exponential backoff. The `BOTO3_RETRY_CONFIG` handles transient errors, but you need application-level retry logic for cases where you want to retry the entire step (e.g., re-upload after a network timeout).

**Input validation.** Check image format (JPEG, PNG, HEIC), color space (RGB vs. CMYK), orientation (EXIF rotation), and file integrity before processing. Reject corrupted files early rather than letting them cause cryptic failures downstream.

**Robust marker detection.** The color-thresholding approach in this example is fragile. Production systems use Hough circle transforms, template matching, or small trained object detectors that handle varying lighting, partial occlusion, and marker rotation. Consider supporting multiple marker types (circular stickers, ruler strips, color calibration cards).

**Model versioning and A/B testing.** When you retrain your segmentation model, you need to deploy it alongside the existing model and compare performance before cutting over. SageMaker supports production variants for this. Track which model version produced each measurement so you can audit accuracy over time.

**Structured logging.** Replace print statements with structured JSON logging. Include correlation IDs that link the image upload, segmentation call, and measurement storage into a single traceable request. Never log PHI values (patient names, wound images, measurement data tied to identifiable patients).

**IAM least privilege.** The example uses broad permissions. In production, each Lambda function should have its own role with only the specific actions it needs. The upload function needs `s3:PutObject` on the specific bucket prefix. The segmentation function needs `sagemaker:InvokeEndpoint` on the specific endpoint ARN. The storage function needs `dynamodb:PutItem` and `dynamodb:Query` on the specific table.

**VPC and VPC endpoints.** SageMaker endpoints should run in a VPC. Use VPC endpoints for S3 and DynamoDB to keep PHI traffic off the public internet. This adds latency (usually negligible) but is required for HIPAA compliance in most interpretations.

**KMS customer-managed keys.** The example uses `aws:kms` (AWS-managed key). Production should use customer-managed KMS keys so you control key rotation, access policies, and can revoke access if needed. Each service (S3, DynamoDB, SageMaker) should use its own key.

**DynamoDB Decimal handling.** Already addressed in the code (wrapping floats in `Decimal(str(...))`), but worth emphasizing: DynamoDB's `put_item` raises `TypeError` if you pass Python floats. This is the single most common boto3 gotcha for numeric data. The `str()` wrapper avoids floating-point representation artifacts that `Decimal(0.1)` would introduce.

**Image retention and lifecycle policies.** Wound images are part of the medical record. Configure S3 lifecycle policies that match your organization's retention requirements (typically 7-10 years for medical records, varies by state). Use S3 Intelligent-Tiering or Glacier transitions for older images that are rarely accessed but must be retained.

**Concurrent measurement handling.** If two clinicians photograph the same wound within minutes (shift change, second opinion), you need idempotency or conflict resolution. The timestamp-based sort key handles this naturally (both measurements are stored), but your healing trajectory logic should handle the case where "previous measurement" was 5 minutes ago, not 7 days ago.

**Testing.** Unit tests for each function with mocked AWS clients. Integration tests with localstack or a dedicated test AWS account. Validation tests comparing pipeline output against clinician-traced ground truth on a held-out dataset. Regression tests that run automatically when the model is retrained.

---

[← Recipe 9.3: Wound Photography Measurement](chapter09.03-wound-photography-measurement) | [Chapter 9 Index](chapter09-index) | [Recipe 9.4: Dermatology Lesion Triage →](chapter09.04-dermatology-lesion-triage)
