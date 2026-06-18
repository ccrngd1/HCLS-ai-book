# Recipe 9.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the multi-modal imaging fusion pipeline from Recipe 9.10. It demonstrates the key concepts (DICOM handling, image registration, quality validation, and fusion output) using synthetic data and boto3 calls. It is not production-ready. Real clinical image registration involves validated algorithms, regulatory considerations, and integration with treatment planning systems that go far beyond what a cookbook example can cover. Consider it a starting point for understanding the pipeline shape, not something you'd deploy in a radiation oncology clinic.

---

## Setup

You'll need the AWS SDK for Python and several scientific computing libraries:

```bash
pip install boto3 numpy scipy SimpleITK nibabel
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `medical-imaging:GetImageSet`, `medical-imaging:GetImageFrame`, `medical-imaging:CreateImageSet` (AWS HealthImaging)
- `s3:GetObject`, `s3:PutObject` (processing bucket)
- `sagemaker:InvokeEndpoint` (registration model)
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:GetItem` (metadata table)
- `states:StartExecution` (Step Functions, if using orchestration)

---

## Config and Constants

Before we get to the pipeline steps, here's the configuration that drives the fusion process. Registration parameters, quality thresholds, and AWS resource names all live here so they're easy to tune without digging through logic.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
import numpy as np
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log patient identifiers or PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Medical imaging pipelines can hit
# throttling during batch processing of large study volumes.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# AWS clients
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
healthimaging_client = boto3.client("medical-imaging", config=BOTO3_RETRY_CONFIG)

# --- Pipeline Configuration ---

# S3 bucket for intermediate processing artifacts (preprocessed volumes,
# deformation fields, QA visualizations). Must have SSE-KMS encryption enabled.
PROCESSING_BUCKET = "my-imaging-fusion-processing"

# DynamoDB table for fusion job metadata and quality tracking.
METADATA_TABLE = "imaging-fusion-metadata"

# SageMaker endpoint hosting the registration model (VoxelMorph or similar).
REGISTRATION_ENDPOINT = "registration-model-endpoint"

# AWS HealthImaging datastore ID for DICOM storage.
HEALTHIMAGING_DATASTORE_ID = "ds-12345678abcdef"

# --- Registration Parameters ---

# Target voxel spacing for resampling before registration (in mm).
# 1mm isotropic works for brain. Use 2mm for abdomen/pelvis to manage
# memory and compute requirements.
TARGET_SPACING_MM = [1.0, 1.0, 1.0]

# Registration type selection by body region.
# Brain: rigid is usually sufficient (skull constrains deformation).
# Body: deformable is required (organ motion between scans).
REGISTRATION_CONFIG = {
    "brain": {"type": "rigid", "levels": 3, "metric": "mutual_information"},
    "body": {"type": "deformable", "levels": 3, "metric": "mutual_information"},
}

# --- Quality Thresholds ---

# Mutual information threshold for accepting registration.
# Well-registered cross-modal pairs typically score 1.0-2.0.
# Below this threshold triggers manual physics review.
MI_THRESHOLD = 1.0

# Maximum allowable fraction of voxels with negative Jacobian determinant.
# Negative Jacobian means the deformation folds tissue through itself,
# which is physically impossible. More than 0.1% is suspicious.
MAX_FOLDING_FRACTION = 0.001

# Mean target registration error threshold (in mm).
# AAPM recommends < 2mm for treatment planning. We alert at 3mm.
MAX_MEAN_TRE_MM = 3.0

# --- Modality-Specific Preprocessing Parameters ---

# CT Hounsfield unit clipping range. Values outside this are scanner artifacts.
CT_HU_MIN = -1024
CT_HU_MAX = 3071

# MRI intensity normalization percentiles. Clipping at 1st and 99th percentile
# removes outlier voxels (air, artifact) without affecting tissue contrast.
MRI_NORM_PERCENTILE_LOW = 1
MRI_NORM_PERCENTILE_HIGH = 99
```

---

## Step 1: Ingest and Validate DICOM Studies

*The pseudocode calls this `ingest_and_validate(study_notifications)`. It receives notifications about new imaging studies, groups them by patient, and identifies fusion-eligible pairs (at least two modalities for the same patient).*

```python
def ingest_and_validate(study_notifications: list[dict]) -> list[dict]:
    """
    Process incoming study notifications and create fusion jobs for eligible pairs.

    In a real system, these notifications come from AWS HealthImaging via
    EventBridge when new studies are imported. Here we expect a list of dicts
    with metadata about each study.

    Args:
        study_notifications: List of dicts, each containing:
            - patient_id: Patient identifier
            - modality: Imaging modality ("CT", "MR", "PT")
            - image_set_id: AWS HealthImaging image set ID
            - series_count: Number of series in the study
            - frame_count: Total number of image frames (slices)

    Returns:
        List of fusion job records (dicts) that were created and written
        to DynamoDB. Each job represents one registration pair (e.g., CT + MRI).
    """
    # Group studies by patient. We need at least two modalities per patient
    # to have anything worth fusing.
    from collections import defaultdict
    patient_studies = defaultdict(list)

    for notification in study_notifications:
        patient_studies[notification["patient_id"]].append(notification)

    created_jobs = []
    table = dynamodb.Table(METADATA_TABLE)

    for patient_id, studies in patient_studies.items():
        # Get the unique modalities available for this patient.
        modalities_present = set(s["modality"] for s in studies)

        if len(modalities_present) < 2:
            logger.info(
                "Patient %s has only one modality (%s), skipping fusion",
                patient_id, modalities_present
            )
            continue

        # For radiation therapy fusion, CT is the fixed (reference) image.
        # Dose calculation requires CT electron density data.
        ct_studies = [s for s in studies if s["modality"] == "CT"]
        if not ct_studies:
            logger.warning("Patient %s has no CT study, cannot proceed", patient_id)
            continue

        # Use the most recent CT as the fixed image.
        fixed_study = ct_studies[-1]

        # Everything else is a moving image to register to the CT.
        moving_studies = [s for s in studies if s["modality"] != "CT"]

        # Validate frame counts. Incomplete series produce garbage registration.
        for study in [fixed_study] + moving_studies:
            if study["frame_count"] < 10:
                logger.warning(
                    "Study %s has only %d frames, likely incomplete. Skipping.",
                    study["image_set_id"], study["frame_count"]
                )
                continue

        # Create a fusion job for each CT + moving modality pair.
        for moving_study in moving_studies:
            job_id = f"fusion-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{patient_id[-5:]}"

            job_record = {
                "job_id": job_id,
                "patient_id": patient_id,
                "fixed_image_set_id": fixed_study["image_set_id"],
                "moving_image_set_id": moving_study["image_set_id"],
                "fixed_modality": "CT",
                "moving_modality": moving_study["modality"],
                "status": "VALIDATED",
                "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                "quality_metrics": {},
            }

            # Write to DynamoDB. This record tracks the job through the pipeline.
            table.put_item(Item=json.loads(
                json.dumps(job_record), parse_float=Decimal
            ))

            created_jobs.append(job_record)
            logger.info("Created fusion job %s: %s + %s for patient %s",
                       job_id, "CT", moving_study["modality"], patient_id)

    return created_jobs
```

---

## Step 2: Preprocess Each Modality

*The pseudocode calls this `preprocess_study(study_id, modality, target_spacing)`. It retrieves DICOM data, converts to volumetric arrays, applies modality-specific corrections (bias field for MRI, SUV for PET, HU clipping for CT), and resamples to a common voxel spacing.*

```python
def create_synthetic_volume(modality: str, shape: tuple = (128, 128, 64)) -> tuple:
    """
    Generate a synthetic 3D medical image volume for demonstration purposes.

    Real volumes come from AWS HealthImaging via GetImageFrame API calls,
    then get assembled from DICOM slices into 3D arrays using libraries like
    pydicom or SimpleITK. Here we create synthetic data that mimics the
    intensity characteristics of each modality.

    Args:
        modality: One of "CT", "MR", "PT"
        shape: Volume dimensions (height, width, depth)

    Returns:
        Tuple of (volume as numpy array, affine matrix as 4x4 numpy array)
    """
    np.random.seed(42)  # Reproducible synthetic data

    if modality == "CT":
        # CT values are in Hounsfield units. Air = -1000, water = 0, bone = 1000+.
        # Simulate a head CT: mostly soft tissue (20-80 HU) with a skull rim (800-1200 HU).
        volume = np.random.normal(loc=40, scale=15, size=shape).astype(np.float32)
        # Add a "skull" ring at the edges.
        center = np.array(shape[:2]) / 2
        y, x = np.ogrid[:shape[0], :shape[1]]
        dist_from_center = np.sqrt((y - center[0])**2 + (x - center[1])**2)
        skull_mask = (dist_from_center > 45) & (dist_from_center < 55)
        for z in range(shape[2]):
            volume[skull_mask, z] = np.random.normal(loc=1000, scale=100,
                                                      size=skull_mask.sum())
        # Add a "tumor" region with slightly different density.
        volume[50:70, 50:70, 25:40] = np.random.normal(loc=55, scale=10,
                                                         size=(20, 20, 15))

    elif modality == "MR":
        # MRI T1-weighted: CSF is dark, white matter bright, gray matter intermediate.
        # Simulate with a bias field artifact (smooth intensity gradient).
        volume = np.random.normal(loc=150, scale=30, size=shape).astype(np.float32)
        # Add bias field: signal stronger on one side (mimics coil proximity).
        bias_field = np.linspace(0.7, 1.3, shape[0])[:, np.newaxis, np.newaxis]
        volume = volume * bias_field
        # Tumor: brighter on T1 post-contrast.
        volume[50:70, 50:70, 25:40] = np.random.normal(loc=220, scale=20,
                                                         size=(20, 20, 15))

    elif modality == "PT":
        # PET: metabolic activity measured in SUV. Background ~1-2, active tumor 5-15.
        volume = np.random.exponential(scale=1.5, size=shape).astype(np.float32)
        # Hot tumor: high SUV.
        volume[50:70, 50:70, 25:40] = np.random.normal(loc=8.0, scale=2.0,
                                                         size=(20, 20, 15))
        volume = np.clip(volume, 0, None)  # SUV cannot be negative

    else:
        volume = np.random.normal(loc=100, scale=20, size=shape).astype(np.float32)

    # Create a simple affine matrix (maps voxel indices to physical mm coordinates).
    # In real DICOM, this comes from ImagePositionPatient and ImageOrientationPatient.
    spacing = [1.0, 1.0, 2.0]  # mm per voxel (in-plane 1mm, slice thickness 2mm)
    affine = np.eye(4)
    affine[0, 0] = spacing[0]
    affine[1, 1] = spacing[1]
    affine[2, 2] = spacing[2]

    return volume, affine

def preprocess_volume(volume: np.ndarray, affine: np.ndarray,
                      modality: str, target_spacing: list[float]) -> tuple:
    """
    Apply modality-specific preprocessing and resample to target spacing.

    This is where the modality-specific physics shows up. Each imaging technology
    has its own artifacts and normalization requirements:
    - CT: Hounsfield unit range clipping
    - MRI: Bias field correction + intensity normalization
    - PET: SUV normalization (in real data; our synthetic data is already SUV-like)

    Args:
        volume: 3D numpy array of image intensities
        affine: 4x4 affine matrix mapping voxel indices to physical coordinates
        modality: "CT", "MR", or "PT"
        target_spacing: Desired output voxel spacing [x, y, z] in mm

    Returns:
        Tuple of (preprocessed volume, updated affine matrix)
    """
    if modality == "CT":
        # Clip to standard Hounsfield unit range.
        # Values outside this range are scanner table, air outside the patient,
        # or metal artifact. They don't help registration.
        volume = np.clip(volume, CT_HU_MIN, CT_HU_MAX)
        logger.info("  CT preprocessed: clipped to [%d, %d] HU", CT_HU_MIN, CT_HU_MAX)

    elif modality == "MR":
        # Bias field correction: the real version uses N4ITK algorithm from SimpleITK.
        # Here we approximate it by dividing out a smoothed version of the image.
        # This removes the low-frequency intensity gradient from coil proximity.
        from scipy.ndimage import gaussian_filter
        # Estimate the bias field as a heavily smoothed version of the volume.
        bias_estimate = gaussian_filter(volume, sigma=30)
        # Avoid division by zero in air regions.
        bias_estimate = np.maximum(bias_estimate, 1.0)
        volume = volume / bias_estimate * np.mean(bias_estimate)

        # Intensity normalization using percentile clipping.
        # This makes the intensity range consistent across different MRI scanners
        # and acquisition parameters.
        p_low = np.percentile(volume, MRI_NORM_PERCENTILE_LOW)
        p_high = np.percentile(volume, MRI_NORM_PERCENTILE_HIGH)
        volume = np.clip(volume, p_low, p_high)
        volume = (volume - p_low) / (p_high - p_low + 1e-8)  # normalize to [0, 1]
        logger.info("  MRI preprocessed: bias corrected, normalized to [0, 1]")

    elif modality == "PT":
        # In real data, this step converts raw PET counts to Standardized Uptake
        # Values using patient weight and injected dose from DICOM headers.
        # Our synthetic data is already in SUV-like units.
        volume = np.clip(volume, 0, None)  # SUV cannot be negative
        logger.info("  PET preprocessed: clipped negative values")

    # Resample to target isotropic spacing.
    # Both images need the same voxel dimensions for registration to work properly.
    current_spacing = [affine[0, 0], affine[1, 1], affine[2, 2]]
    zoom_factors = [
        current_spacing[i] / target_spacing[i] for i in range(3)
    ]

    from scipy.ndimage import zoom
    volume_resampled = zoom(volume, zoom_factors, order=1)  # linear interpolation

    # Update affine to reflect new spacing.
    new_affine = affine.copy()
    new_affine[0, 0] = target_spacing[0]
    new_affine[1, 1] = target_spacing[1]
    new_affine[2, 2] = target_spacing[2]

    logger.info("  Resampled from %s to %s mm, shape: %s -> %s",
               current_spacing, target_spacing, volume.shape, volume_resampled.shape)

    return volume_resampled, new_affine

def upload_preprocessed_volume(volume: np.ndarray, job_id: str,
                                role: str) -> str:
    """
    Save a preprocessed volume to S3 as a compressed numpy array.

    In production, you'd save as NIfTI format (.nii.gz) which preserves
    the affine matrix and is the standard for neuroimaging. Here we use
    numpy's native format for simplicity.

    Args:
        volume: Preprocessed 3D numpy array
        job_id: Fusion job identifier
        role: "fixed" or "moving" (for naming)

    Returns:
        S3 key where the volume was stored
    """
    import io

    s3_key = f"{job_id}/{role}_preprocessed.npy"

    # Serialize numpy array to bytes.
    buffer = io.BytesIO()
    np.save(buffer, volume)
    buffer.seek(0)

    s3_client.put_object(
        Bucket=PROCESSING_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
        ServerSideEncryption="aws:kms",
        # In production, specify your CMK: SSEKMSKeyId="arn:aws:kms:..."
    )

    logger.info("  Uploaded %s volume to s3://%s/%s", role, PROCESSING_BUCKET, s3_key)
    return s3_key
```

---

## Step 3: Compute Registration (Align Moving to Fixed)

*The pseudocode calls this `register_images(fixed_path, moving_path, registration_type)`. This is the computational core: it aligns the moving image (MRI or PET) to the fixed image (CT) by finding the spatial transformation that maximizes their statistical similarity.*

```python
def compute_rigid_registration(fixed: np.ndarray, moving: np.ndarray) -> dict:
    """
    Compute rigid registration between two volumes using mutual information.

    Rigid registration finds 6 parameters (3 translations + 3 rotations) that
    best align the moving image to the fixed image. Appropriate for brain imaging
    where the skull constrains soft tissue motion.

    This uses scipy's optimization to maximize mutual information. In production,
    you'd use SimpleITK's registration framework or a SageMaker-hosted model.

    Args:
        fixed: 3D numpy array (the reference, typically CT)
        moving: 3D numpy array (to be aligned, typically MRI or PET)

    Returns:
        Dict containing:
        - transform_params: The 6 rigid body parameters [tx, ty, tz, rx, ry, rz]
        - registered_moving: The moving image after applying the transform
        - mutual_information: MI score of the aligned pair
    """
    from scipy.ndimage import affine_transform
    from scipy.optimize import minimize

    def compute_mi(image1: np.ndarray, image2: np.ndarray, bins: int = 32) -> float:
        """
        Compute mutual information between two images.

        MI measures statistical dependence: if two images are well-aligned,
        knowing the intensity at a location in one image reduces your
        uncertainty about the intensity at the corresponding location in
        the other image.

        Higher MI = better alignment. This works across modalities because
        it doesn't assume intensities match, only that they're correlated.
        """
        # Downsample for speed during optimization (compute MI on a subsample).
        step = 2
        img1_flat = image1[::step, ::step, ::step].ravel()
        img2_flat = image2[::step, ::step, ::step].ravel()

        # Joint histogram.
        hist_2d, _, _ = np.histogram2d(img1_flat, img2_flat, bins=bins)
        # Normalize to probability distribution.
        pxy = hist_2d / hist_2d.sum()
        px = pxy.sum(axis=1)  # marginal for image 1
        py = pxy.sum(axis=0)  # marginal for image 2

        # MI = sum over all bins of p(x,y) * log(p(x,y) / (p(x) * p(y)))
        # Use masks to avoid log(0).
        nonzero = pxy > 0
        px_py = px[:, np.newaxis] * py[np.newaxis, :]
        mi = np.sum(pxy[nonzero] * np.log(pxy[nonzero] / (px_py[nonzero] + 1e-10)))
        return mi

    def apply_rigid_transform(volume: np.ndarray, params: np.ndarray) -> np.ndarray:
        """
        Apply a rigid body transformation to a 3D volume.

        params: [tx, ty, tz, rx, ry, rz]
        - tx, ty, tz: translation in voxels
        - rx, ry, rz: rotation in radians (small angles approximation)
        """
        tx, ty, tz, rx, ry, rz = params

        # Rotation matrix from Euler angles (small angle approximation for speed).
        cos_x, sin_x = np.cos(rx), np.sin(rx)
        cos_y, sin_y = np.cos(ry), np.sin(ry)
        cos_z, sin_z = np.cos(rz), np.sin(rz)

        # Combined rotation matrix (Rz * Ry * Rx).
        rot_matrix = np.array([
            [cos_y * cos_z, sin_x * sin_y * cos_z - cos_x * sin_z,
             cos_x * sin_y * cos_z + sin_x * sin_z],
            [cos_y * sin_z, sin_x * sin_y * sin_z + cos_x * cos_z,
             cos_x * sin_y * sin_z - sin_x * cos_z],
            [-sin_y, sin_x * cos_y, cos_x * cos_y]
        ])

        # Offset for rotation about volume center.
        center = np.array(volume.shape) / 2.0
        offset = center - rot_matrix @ center + np.array([tx, ty, tz])

        transformed = affine_transform(volume, rot_matrix, offset=offset, order=1)
        return transformed

    def neg_mi_objective(params):
        """Objective function: negative MI (minimize negative = maximize MI)."""
        transformed = apply_rigid_transform(moving, params)
        return -compute_mi(fixed, transformed)

    # Multi-resolution: start at coarse resolution for robustness,
    # then refine at full resolution.
    logger.info("  Running rigid registration (mutual information)...")

    # Initial parameters: no transformation.
    x0 = np.zeros(6)

    # Optimize with bounded search (translations within +/- 20 voxels,
    # rotations within +/- 15 degrees).
    bounds = [(-20, 20), (-20, 20), (-20, 20),
              (-0.26, 0.26), (-0.26, 0.26), (-0.26, 0.26)]

    result = minimize(neg_mi_objective, x0, method="L-BFGS-B",
                     bounds=bounds, options={"maxiter": 100, "ftol": 1e-6})

    # Apply the optimized transform to get the registered moving image.
    best_params = result.x
    registered_moving = apply_rigid_transform(moving, best_params)

    # Compute final MI score.
    final_mi = compute_mi(fixed, registered_moving)

    logger.info("  Rigid registration complete. MI: %.3f, params: %s",
               final_mi, np.round(best_params, 3))

    return {
        "transform_params": best_params.tolist(),
        "registered_moving": registered_moving,
        "mutual_information": final_mi,
        "registration_type": "rigid",
    }

def compute_deformable_registration_via_sagemaker(
    fixed: np.ndarray, moving: np.ndarray, job_id: str
) -> dict:
    """
    Invoke a SageMaker-hosted deep learning model for deformable registration.

    In production, this calls a VoxelMorph or TransMorph model that predicts
    a dense displacement field in a single forward pass. The model takes
    the fixed and moving volumes as input (concatenated along channel dimension)
    and outputs a 3-channel displacement field (dx, dy, dz per voxel).

    For this example, we simulate the model output since we can't actually
    invoke a trained endpoint without one deployed. The structure shows exactly
    how you'd interact with SageMaker Runtime.

    Args:
        fixed: Preprocessed fixed volume (CT)
        moving: Preprocessed moving volume (MRI), already rigidly aligned
        job_id: For tracking

    Returns:
        Dict with deformation_field, registered_moving, and quality info
    """
    # --- In production, this is the actual SageMaker invocation: ---
    #
    # # Prepare model input: stack fixed and moving as a 2-channel input.
    # model_input = np.stack([fixed, moving], axis=0)  # shape: (2, H, W, D)
    #
    # # Serialize to bytes for the endpoint.
    # import io
    # buffer = io.BytesIO()
    # np.save(buffer, model_input.astype(np.float32))
    # payload = buffer.getvalue()
    #
    # # Invoke the SageMaker endpoint.
    # response = sagemaker_runtime.invoke_endpoint(
    #     EndpointName=REGISTRATION_ENDPOINT,
    #     ContentType="application/x-npy",
    #     Accept="application/x-npy",
    #     Body=payload,
    # )
    #
    # # Parse the response: a displacement field of shape (3, H, W, D).
    # result_buffer = io.BytesIO(response["Body"].read())
    # deformation_field = np.load(result_buffer)

    # --- For demonstration, simulate a small deformation field ---
    logger.info("  Computing deformable registration via SageMaker endpoint...")
    logger.info("  (Simulating model inference for demonstration)")

    # Simulate a smooth, physically plausible deformation field.
    # In reality, the model would output learned displacements.
    from scipy.ndimage import gaussian_filter
    shape = fixed.shape

    # Random displacement field smoothed to be physically plausible.
    deformation_field = np.zeros((*shape, 3), dtype=np.float32)
    for axis in range(3):
        raw_displacement = np.random.normal(0, 0.5, shape)
        # Heavy smoothing ensures the deformation is diffeomorphic (no folding).
        deformation_field[..., axis] = gaussian_filter(raw_displacement, sigma=10)

    # Apply deformation field to moving image using grid sampling.
    registered_moving = apply_deformation_field(moving, deformation_field)

    # Compute MI on the result.
    # (Reusing the MI function from rigid registration for consistency.)
    hist_2d, _, _ = np.histogram2d(
        fixed[::2, ::2, ::2].ravel(),
        registered_moving[::2, ::2, ::2].ravel(),
        bins=32
    )
    pxy = hist_2d / hist_2d.sum()
    px = pxy.sum(axis=1)
    py = pxy.sum(axis=0)
    nonzero = pxy > 0
    px_py = px[:, np.newaxis] * py[np.newaxis, :]
    final_mi = float(np.sum(pxy[nonzero] * np.log(pxy[nonzero] / (px_py[nonzero] + 1e-10))))

    logger.info("  Deformable registration complete. MI: %.3f", final_mi)

    return {
        "deformation_field": deformation_field,
        "registered_moving": registered_moving,
        "mutual_information": final_mi,
        "registration_type": "deformable",
    }

def apply_deformation_field(volume: np.ndarray,
                            deformation_field: np.ndarray) -> np.ndarray:
    """
    Warp a volume using a dense displacement field.

    Each voxel in the output is sampled from the input at coordinates
    shifted by the displacement vector at that location.

    Args:
        volume: Input 3D volume to warp
        deformation_field: Shape (H, W, D, 3), displacement in voxels per axis

    Returns:
        Warped volume with same shape as input
    """
    from scipy.ndimage import map_coordinates

    shape = volume.shape
    # Create a regular coordinate grid.
    coords = np.mgrid[0:shape[0], 0:shape[1], 0:shape[2]].astype(np.float32)

    # Add displacement field to coordinates.
    # coords shape: (3, H, W, D), deformation_field needs to be transposed.
    displaced_coords = coords + deformation_field.transpose(3, 0, 1, 2)

    # Sample the volume at displaced coordinates using trilinear interpolation.
    warped = map_coordinates(volume, displaced_coords, order=1, mode="nearest")

    return warped
```

---

## Step 4: Validate Registration Quality

*The pseudocode calls this `validate_registration_quality(job_id, fixed_volume, registered_moving, deformation_field)`. This is the safety mechanism. A registration that looks plausible can still be subtly wrong, and in treatment planning a 3mm error means irradiating the wrong tissue.*

```python
def validate_registration_quality(
    job_id: str,
    fixed: np.ndarray,
    registered_moving: np.ndarray,
    deformation_field: Optional[np.ndarray] = None
) -> tuple[bool, dict]:
    """
    Run automated quality checks on a completed registration.

    Three checks are applied:
    1. Mutual information: is the statistical alignment good enough?
    2. Jacobian determinant (deformable only): is the deformation physically plausible?
    3. Overlap of automatically detected structures: do known landmarks align?

    If any check fails, the job is routed to a medical physicist for manual
    review rather than being silently accepted. In radiation therapy, the
    consequences of bad registration include irradiating the wrong anatomy.
    The quality gate is not optional.

    Args:
        job_id: Fusion job identifier
        fixed: The fixed (reference) volume
        registered_moving: The moving volume after registration
        deformation_field: Dense displacement field (None for rigid)

    Returns:
        Tuple of (passed: bool, quality_report: dict with all metrics)
    """
    quality_report = {}
    passed = True

    # --- Check 1: Mutual Information ---
    # Compute MI between fixed and registered moving.
    hist_2d, _, _ = np.histogram2d(
        fixed[::2, ::2, ::2].ravel(),
        registered_moving[::2, ::2, ::2].ravel(),
        bins=32
    )
    pxy = hist_2d / hist_2d.sum()
    px = pxy.sum(axis=1)
    py = pxy.sum(axis=0)
    nonzero = pxy > 0
    px_py = px[:, np.newaxis] * py[np.newaxis, :]
    mi_score = float(np.sum(pxy[nonzero] * np.log(pxy[nonzero] / (px_py[nonzero] + 1e-10))))

    quality_report["mutual_information"] = round(mi_score, 4)

    if mi_score < MI_THRESHOLD:
        passed = False
        quality_report["mi_failure"] = (
            f"MI ({mi_score:.3f}) below threshold ({MI_THRESHOLD}). "
            "Possible misregistration or poor image quality."
        )
        logger.warning("  QA FAILED: MI below threshold (%.3f < %.3f)",
                      mi_score, MI_THRESHOLD)

    # --- Check 2: Jacobian Determinant (deformable only) ---
    # The Jacobian determinant at each voxel measures local volume change.
    # det(J) = 1: no change. det(J) > 1: expansion. det(J) < 1: compression.
    # det(J) <= 0: folding (tissue passes through itself). Physically impossible.
    if deformation_field is not None:
        jacobian_det = compute_jacobian_determinant(deformation_field)

        folding_fraction = float(np.mean(jacobian_det <= 0))
        quality_report["folding_fraction"] = round(folding_fraction, 6)
        quality_report["jacobian_min"] = round(float(jacobian_det.min()), 4)
        quality_report["jacobian_max"] = round(float(jacobian_det.max()), 4)
        quality_report["jacobian_mean"] = round(float(jacobian_det.mean()), 4)

        if folding_fraction > MAX_FOLDING_FRACTION:
            passed = False
            quality_report["jacobian_failure"] = (
                f"Folding fraction ({folding_fraction:.4f}) exceeds "
                f"threshold ({MAX_FOLDING_FRACTION}). Deformation is "
                "physically implausible in some regions."
            )
            logger.warning("  QA FAILED: Excessive folding (%.4f > %.4f)",
                          folding_fraction, MAX_FOLDING_FRACTION)
    else:
        quality_report["folding_fraction"] = None
        quality_report["note"] = "Rigid registration: no deformation field to check"

    # --- Check 3: Structure overlap (simplified) ---
    # In production, you'd segment known structures (e.g., skull, ventricles)
    # in both images and compute Dice overlap after registration.
    # Here we use a simple intensity-based landmark check.
    # Threshold both images to find high-intensity regions and compute overlap.
    fixed_mask = fixed > np.percentile(fixed, 90)
    moving_mask = registered_moving > np.percentile(registered_moving, 90)

    # Dice coefficient: 2 * |intersection| / (|A| + |B|)
    intersection = np.sum(fixed_mask & moving_mask)
    dice = 2.0 * intersection / (np.sum(fixed_mask) + np.sum(moving_mask) + 1e-8)
    quality_report["high_intensity_dice"] = round(float(dice), 4)

    # Update status in DynamoDB.
    status = "QA_PASSED" if passed else "QA_FAILED_REVIEW_NEEDED"
    table = dynamodb.Table(METADATA_TABLE)
    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET #s = :status, quality_metrics = :qm",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": status,
            ":qm": json.loads(json.dumps(quality_report), parse_float=Decimal),
        },
    )

    logger.info("  Quality validation %s. MI=%.3f, Dice=%.3f",
               "PASSED" if passed else "FAILED", mi_score, dice)

    return passed, quality_report

def compute_jacobian_determinant(deformation_field: np.ndarray) -> np.ndarray:
    """
    Compute the Jacobian determinant of a displacement field.

    The Jacobian determinant at each voxel tells you whether the deformation
    is locally expanding (det > 1), compressing (0 < det < 1), or folding
    (det <= 0). Folding is physically impossible and indicates a registration
    failure.

    Args:
        deformation_field: Shape (H, W, D, 3), displacement per voxel

    Returns:
        3D array of Jacobian determinant values, same spatial shape as input
    """
    # Add identity to displacement to get the full coordinate mapping.
    # The Jacobian of the transformation is I + grad(displacement).
    dx = deformation_field[..., 0]
    dy = deformation_field[..., 1]
    dz = deformation_field[..., 2]

    # Compute spatial gradients of each displacement component.
    # Using central differences for interior points.
    ddx_dx = np.gradient(dx, axis=0)
    ddx_dy = np.gradient(dx, axis=1)
    ddx_dz = np.gradient(dx, axis=2)

    ddy_dx = np.gradient(dy, axis=0)
    ddy_dy = np.gradient(dy, axis=1)
    ddy_dz = np.gradient(dy, axis=2)

    ddz_dx = np.gradient(dz, axis=0)
    ddz_dy = np.gradient(dz, axis=1)
    ddz_dz = np.gradient(dz, axis=2)

    # Jacobian matrix at each voxel is I + gradient of displacement.
    # det(J) = det([[1+ddx/dx, ddx/dy, ddx/dz],
    #               [ddy/dx, 1+ddy/dy, ddy/dz],
    #               [ddz/dx, ddz/dy, 1+ddz/dz]])
    j11 = 1 + ddx_dx
    j12 = ddx_dy
    j13 = ddx_dz
    j21 = ddy_dx
    j22 = 1 + ddy_dy
    j23 = ddy_dz
    j31 = ddz_dx
    j32 = ddz_dy
    j33 = 1 + ddz_dz

    # 3x3 determinant formula.
    det = (j11 * (j22 * j33 - j23 * j32)
           - j12 * (j21 * j33 - j23 * j31)
           + j13 * (j21 * j32 - j22 * j31))

    return det
```

---

## Step 5: Generate Fused Output

*The pseudocode calls this `generate_fusion_output(...)`. After registration passes quality checks, this step creates the clinical deliverables: fused overlay visualizations, DICOM-compatible output, and summary metrics for the treatment planning team.*

```python
def generate_fusion_output(
    job_id: str,
    fixed: np.ndarray,
    registered_moving: np.ndarray,
    moving_modality: str,
    quality_report: dict,
) -> dict:
    """
    Generate fused visualization and clinical output from registered images.

    Creates two types of output:
    1. Checkerboard visualization: alternating tiles from fixed and moving,
       revealing misalignment at tile boundaries.
    2. Color overlay: fixed (CT) as grayscale base with registered moving
       (MRI/PET) as a colored wash on top.

    In production, this step also generates DICOM Registration Objects and
    resampled DICOM series for integration with PACS and treatment planning
    systems. That requires pydicom and DICOM UID generation which we skip here.

    Args:
        job_id: Fusion job identifier
        fixed: Fixed volume (CT)
        registered_moving: Moving volume after registration
        moving_modality: "MR" or "PT" (affects color scheme)
        quality_report: Quality metrics from validation step

    Returns:
        Dict with output locations and summary information
    """
    # --- Generate checkerboard visualization ---
    # Take a representative axial slice (middle of the volume).
    mid_slice = fixed.shape[2] // 2
    fixed_slice = fixed[:, :, mid_slice]
    moving_slice = registered_moving[:, :, mid_slice]

    checkerboard = generate_checkerboard_slice(fixed_slice, moving_slice, tile_size=16)

    # --- Generate color overlay ---
    overlay = generate_color_overlay_slice(fixed_slice, moving_slice, moving_modality)

    # --- Upload QA visualizations to S3 ---
    checkerboard_key = f"{job_id}/qa_checkerboard.npy"
    overlay_key = f"{job_id}/qa_color_overlay.npy"

    import io
    for array, key in [(checkerboard, checkerboard_key), (overlay, overlay_key)]:
        buffer = io.BytesIO()
        np.save(buffer, array)
        buffer.seek(0)
        s3_client.put_object(
            Bucket=PROCESSING_BUCKET,
            Key=key,
            Body=buffer.getvalue(),
            ServerSideEncryption="aws:kms",
        )

    # --- Update metadata with completion info ---
    table = dynamodb.Table(METADATA_TABLE)
    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression=(
            "SET #s = :status, completed_at = :ts, "
            "output_checkerboard = :cb, output_overlay = :ov"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "COMPLETED",
            ":ts": datetime.datetime.now(timezone.utc).isoformat(),
            ":cb": f"s3://{PROCESSING_BUCKET}/{checkerboard_key}",
            ":ov": f"s3://{PROCESSING_BUCKET}/{overlay_key}",
        },
    )

    output = {
        "job_id": job_id,
        "status": "COMPLETED",
        "qa_visualizations": {
            "checkerboard": f"s3://{PROCESSING_BUCKET}/{checkerboard_key}",
            "color_overlay": f"s3://{PROCESSING_BUCKET}/{overlay_key}",
        },
        "quality_metrics": quality_report,
        "moving_modality": moving_modality,
    }

    logger.info("  Fusion output generated for job %s", job_id)
    return output

def generate_checkerboard_slice(fixed_slice: np.ndarray,
                                 moving_slice: np.ndarray,
                                 tile_size: int = 16) -> np.ndarray:
    """
    Create a checkerboard comparison of two aligned image slices.

    Alternating tiles from the fixed and moving images let you visually
    assess alignment quality. Misregistration shows up as discontinuities
    at tile boundaries (edges that don't connect across tiles).

    Args:
        fixed_slice: 2D slice from fixed image
        moving_slice: 2D slice from registered moving image
        tile_size: Size of each checkerboard tile in pixels

    Returns:
        2D array containing the checkerboard composite
    """
    h, w = fixed_slice.shape[:2]
    result = np.zeros_like(fixed_slice)

    for i in range(0, h, tile_size):
        for j in range(0, w, tile_size):
            tile_row = (i // tile_size) % 2
            tile_col = (j // tile_size) % 2
            i_end = min(i + tile_size, h)
            j_end = min(j + tile_size, w)

            if (tile_row + tile_col) % 2 == 0:
                result[i:i_end, j:j_end] = fixed_slice[i:i_end, j:j_end]
            else:
                result[i:i_end, j:j_end] = moving_slice[i:i_end, j:j_end]

    return result

def generate_color_overlay_slice(fixed_slice: np.ndarray,
                                  moving_slice: np.ndarray,
                                  moving_modality: str,
                                  alpha: float = 0.4) -> np.ndarray:
    """
    Create a color overlay of the moving image on the fixed image.

    The fixed image (CT) is shown in grayscale. The registered moving image
    (MRI or PET) is shown as a colored wash on top. Clinicians use this
    to verify registration quality and to see both modalities simultaneously.

    Args:
        fixed_slice: 2D slice from fixed image (grayscale base)
        moving_slice: 2D slice from registered moving image (color overlay)
        moving_modality: "MR" or "PT" (determines color scheme)
        alpha: Transparency of the overlay (0 = invisible, 1 = opaque)

    Returns:
        3D array (H, W, 3) RGB image with the overlay
    """
    # Normalize both slices to [0, 1] for display.
    def normalize(img):
        mn, mx = img.min(), img.max()
        if mx - mn < 1e-8:
            return np.zeros_like(img)
        return (img - mn) / (mx - mn)

    fixed_norm = normalize(fixed_slice)
    moving_norm = normalize(moving_slice)

    # Create RGB output. Fixed as grayscale background.
    rgb = np.stack([fixed_norm, fixed_norm, fixed_norm], axis=-1)

    # Overlay color depends on modality.
    if moving_modality == "PT":
        # PET: hot colormap (red/yellow for high uptake).
        overlay_color = np.stack([moving_norm, moving_norm * 0.5, np.zeros_like(moving_norm)], axis=-1)
    else:
        # MRI: blue/cyan.
        overlay_color = np.stack([np.zeros_like(moving_norm), moving_norm * 0.7, moving_norm], axis=-1)

    # Blend with alpha compositing.
    rgb = (1 - alpha) * rgb + alpha * overlay_color

    return np.clip(rgb, 0, 1)
```

---

## Putting It All Together

Here's the full fusion pipeline assembled into a single callable function. In production, each step would be a separate task in an AWS Step Functions state machine. Here we run them sequentially for clarity.

```python
def run_fusion_pipeline(
    fixed_modality: str = "CT",
    moving_modality: str = "MR",
    body_region: str = "brain",
) -> dict:
    """
    Run the complete multi-modal imaging fusion pipeline.

    This demonstrates the end-to-end flow using synthetic data:
    1. Create synthetic study volumes (simulating HealthImaging retrieval)
    2. Preprocess each modality
    3. Compute registration (rigid for brain, deformable for body)
    4. Validate quality
    5. Generate fused output

    Args:
        fixed_modality: The reference modality (typically "CT")
        moving_modality: The modality to register ("MR" or "PT")
        body_region: "brain" (rigid) or "body" (deformable)

    Returns:
        Complete fusion result with quality metrics and output locations
    """
    job_id = f"fusion-demo-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    logger.info("=" * 60)
    logger.info("Starting fusion pipeline: job_id=%s", job_id)
    logger.info("  Fixed: %s, Moving: %s, Region: %s", fixed_modality, moving_modality, body_region)
    logger.info("=" * 60)

    # --- Step 1: Create/retrieve study volumes ---
    logger.info("\nStep 1: Ingesting study volumes")
    fixed_volume, fixed_affine = create_synthetic_volume(fixed_modality)
    moving_volume, moving_affine = create_synthetic_volume(moving_modality)
    logger.info("  Fixed shape: %s, Moving shape: %s", fixed_volume.shape, moving_volume.shape)

    # --- Step 2: Preprocess ---
    logger.info("\nStep 2: Preprocessing volumes")
    target_spacing = TARGET_SPACING_MM if body_region == "brain" else [2.0, 2.0, 2.0]

    fixed_processed, fixed_new_affine = preprocess_volume(
        fixed_volume, fixed_affine, fixed_modality, target_spacing
    )
    moving_processed, moving_new_affine = preprocess_volume(
        moving_volume, moving_affine, moving_modality, target_spacing
    )

    # Ensure volumes have the same shape for registration.
    # In production, this is handled by resampling to the fixed image's grid.
    min_shape = tuple(min(f, m) for f, m in zip(fixed_processed.shape, moving_processed.shape))
    fixed_processed = fixed_processed[:min_shape[0], :min_shape[1], :min_shape[2]]
    moving_processed = moving_processed[:min_shape[0], :min_shape[1], :min_shape[2]]

    # --- Step 3: Registration ---
    reg_config = REGISTRATION_CONFIG.get(body_region, REGISTRATION_CONFIG["brain"])
    logger.info("\nStep 3: Computing %s registration", reg_config["type"])

    if reg_config["type"] == "rigid":
        reg_result = compute_rigid_registration(fixed_processed, moving_processed)
        deformation_field = None
    else:
        # For deformable: rigid first, then deformable.
        rigid_result = compute_rigid_registration(fixed_processed, moving_processed)
        reg_result = compute_deformable_registration_via_sagemaker(
            fixed_processed, rigid_result["registered_moving"], job_id
        )
        deformation_field = reg_result["deformation_field"]

    registered_moving = reg_result["registered_moving"]

    # --- Step 4: Quality validation ---
    logger.info("\nStep 4: Validating registration quality")
    passed, quality_report = validate_registration_quality(
        job_id, fixed_processed, registered_moving, deformation_field
    )

    if not passed:
        logger.warning("  Registration failed QA. Routing to physics review.")
        return {
            "job_id": job_id,
            "status": "QA_FAILED_REVIEW_NEEDED",
            "quality_metrics": quality_report,
            "registration_type": reg_config["type"],
        }

    # --- Step 5: Generate output ---
    logger.info("\nStep 5: Generating fusion output")
    output = generate_fusion_output(
        job_id, fixed_processed, registered_moving, moving_modality, quality_report
    )

    logger.info("\n" + "=" * 60)
    logger.info("Pipeline complete: %s", output["status"])
    logger.info("  Quality: MI=%.3f", quality_report["mutual_information"])
    logger.info("=" * 60)

    return output

# --- Run the demonstration ---
if __name__ == "__main__":
    # Configure logging to stdout for local testing.
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Run brain PET-CT fusion (rigid registration).
    print("\n" + "=" * 70)
    print("DEMO 1: Brain PET-CT Fusion (Rigid Registration)")
    print("=" * 70)
    result_brain = run_fusion_pipeline(
        fixed_modality="CT",
        moving_modality="PT",
        body_region="brain",
    )
    print(f"\nResult: {json.dumps({k: v for k, v in result_brain.items() if k != 'quality_metrics'}, indent=2)}")
    print(f"Quality: {json.dumps(result_brain.get('quality_metrics', {}), indent=2, default=str)}")

    # Run body MRI-CT fusion (deformable registration).
    print("\n" + "=" * 70)
    print("DEMO 2: Body MRI-CT Fusion (Deformable Registration)")
    print("=" * 70)
    result_body = run_fusion_pipeline(
        fixed_modality="CT",
        moving_modality="MR",
        body_region="body",
    )
    print(f"\nResult: {json.dumps({k: v for k, v in result_body.items() if k != 'quality_metrics'}, indent=2)}")
    print(f"Quality: {json.dumps(result_body.get('quality_metrics', {}), indent=2, default=str)}")
```

---

## The Gap Between This and Production

This example demonstrates the shape of a multi-modal fusion pipeline. It runs, produces output, and illustrates the key concepts. But the distance between this and a system processing real patient imaging data is substantial. Here's where that gap lives:

**Real DICOM handling.** This example uses synthetic numpy arrays. A production system ingests actual DICOM data from AWS HealthImaging (using `GetImageFrame` API calls), handles varying slice thicknesses, non-uniform slice spacing, and all the quirks of real-world DICOM metadata. Libraries like pydicom and SimpleITK handle the parsing; the complexity is in the edge cases (missing metadata, non-standard private tags, compressed transfer syntaxes).

**Validated registration algorithms.** Our rigid registration uses a basic scipy optimizer with mutual information. Production systems use validated implementations from SimpleITK, ANTs (Advanced Normalization Tools), or trained deep learning models (VoxelMorph, TransMorph). These have been extensively tested against ground-truth registrations and have published accuracy benchmarks. You would not deploy a hand-rolled optimizer for clinical image registration.

**SageMaker model deployment.** The deformable registration step simulates model inference. In production, you'd train a VoxelMorph or TransMorph model on your institution's data, package it as a SageMaker endpoint with GPU inference (ml.g4dn.xlarge minimum), and handle model versioning, A/B testing, and rollback. Model validation against known-good registrations is essential before clinical use.

**Error handling and retry logic.** Every AWS API call can fail: HealthImaging can throttle during bulk retrieval, SageMaker endpoints can timeout on large volumes, S3 multipart uploads can fail mid-stream. Production wraps each call in structured retry logic with exponential backoff. Failed jobs need dead-letter queues and alerting, not silent failures.

**Step Functions orchestration.** This example runs sequentially. Production uses AWS Step Functions to orchestrate the pipeline with parallel preprocessing of multiple modalities, retry logic per step, timeout handling, and conditional branching (rigid vs. deformable based on body region). Step Functions provides visual monitoring and audit trails.

**DICOM output generation.** Clinical systems expect DICOM output: Spatial Registration Objects (encoding the transform), resampled DICOM series (moving modality in CT coordinate space), and RT Structure Sets (propagated contours). This requires generating proper DICOM UIDs, maintaining metadata chains, and conforming to DICOM standards. Libraries like pydicom handle the encoding; the hard part is getting the metadata right.

**IAM least-privilege.** The IAM role for this pipeline needs precise permissions: `medical-imaging:GetImageFrame` scoped to the specific datastore, `sagemaker:InvokeEndpoint` scoped to the registration endpoint, `s3:PutObject` scoped to the processing bucket with a specific KMS key. Not wildcards. Not admin access.

**VPC and network isolation.** Medical images are PHI. All compute (ECS tasks, SageMaker endpoints, Lambda functions) runs in private subnets with VPC endpoints for S3, DynamoDB, HealthImaging, SageMaker, and CloudWatch. No traffic traverses the public internet.

**Encryption at every layer.** S3 objects encrypted with customer-managed KMS keys (CMKs). DynamoDB encrypted at rest with CMKs. SageMaker endpoint volumes encrypted. HealthImaging uses its own encryption. Key rotation enabled. CloudTrail logs every key usage for audit.

**Quality validation rigor.** Our quality checks are simplified. Clinical registration validation includes: manual review by a medical physicist for complex cases, comparison against previous registrations for the same patient (consistency checks), automated landmark detection using atlas-based methods, and integration with institutional quality management workflows.

**Regulatory considerations.** If registration results directly influence treatment decisions (which they do in radiation oncology), the system may fall under FDA regulatory requirements as a medical device. This means formal validation protocols, documented testing, and potentially 510(k) or De Novo classification. The registration algorithm itself (not just the infrastructure) needs clinical validation.

**Audit trail and traceability.** Every fusion job needs a complete audit trail: which versions of the registration model were used, what preprocessing parameters were applied, who reviewed the quality output, and when the result was accepted for clinical use. DynamoDB records plus CloudTrail API logs provide the technical foundation, but the workflow integration (physicist sign-off, clinical acceptance) is organizational, not technical.

**Performance at scale.** A busy radiation oncology department might process 50-100 fusion cases per day. The pipeline needs to handle this throughput with acceptable latency (results available within 15-30 minutes of study arrival). This means right-sizing SageMaker endpoints, pre-warming ECS tasks, and potentially batching similar registrations.

The recipe in 9.10 discusses the clinical context, architecture patterns, and honest limitations in much more detail. This code gives you the skeleton; the clinical validation and regulatory work give you permission to use it on patients.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.10](chapter09.10-multi-modal-imaging-fusion-analysis.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
