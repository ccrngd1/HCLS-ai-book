# Recipe 9.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of patient photo verification using face comparison. It's meant to show one way you could translate the concepts from Recipe 9.2 into working Python code. It is not production-ready. There's no liveness detection, no anti-spoofing, no multi-angle enrollment. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a hospital check-in kiosk on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3 pillow
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `rekognition:CompareFaces`, `rekognition:CreateCollection`, `rekognition:IndexFaces`, `rekognition:SearchFacesByImage`, `s3:GetObject`, `s3:PutObject`, and `dynamodb:PutItem` / `dynamodb:GetItem`.

Pillow is optional here but useful for image validation before sending to Rekognition. You don't want to burn API calls on corrupt or undersized images.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the verification logic. Thresholds are the heart of any face verification system. Too strict and you reject legitimate patients. Too lenient and you let the wrong person through.

```python
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. Never log PHI (patient names, MRNs, photos).
# Log patient_id references only, never the biometric data itself.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for AWS API calls. Face comparison is fast but can throttle
# under burst load (think: 200 patients checking in at 8am Monday).
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Verification Thresholds ---
#
# SIMILARITY_THRESHOLD: minimum confidence (0-100) that two faces are the same person.
# Rekognition returns a similarity score for each face comparison.
# 95% is conservative. You'll reject some legitimate patients who look different
# from their enrollment photo (new glasses, weight change, aging). But you'll
# catch almost all mismatches.
#
# In practice, most healthcare orgs start at 90% and tune upward based on
# false-accept rates. The cost of a false accept (wrong patient gets treatment)
# is much higher than a false reject (patient re-verifies with staff).
SIMILARITY_THRESHOLD = 95.0

# MINIMUM_FACE_CONFIDENCE: minimum confidence that Rekognition actually detected
# a face in the image. Below this, the image quality is too poor to trust.
MINIMUM_FACE_CONFIDENCE = 99.0

# IMAGE_QUALITY_THRESHOLDS: brightness and sharpness minimums.
# Rekognition returns quality metrics for each detected face.
# These catch the "photo taken in a dark hallway" and "blurry selfie" cases.
IMAGE_QUALITY_BRIGHTNESS_MIN = 40.0
IMAGE_QUALITY_SHARPNESS_MIN = 40.0

# Maximum age (in days) for an enrollment photo before requiring re-enrollment.
# Faces change. A 5-year-old enrollment photo is unreliable.
ENROLLMENT_PHOTO_MAX_AGE_DAYS = 730  # ~2 years

# S3 bucket for patient photos (enrollment and verification attempts).
PHOTO_BUCKET = "patient-photos-hipaa"

# DynamoDB table for verification audit records.
AUDIT_TABLE = "patient-photo-verifications"

# Rekognition collection for indexed patient faces.
# Collections let you search across enrolled faces without re-uploading reference images.
FACE_COLLECTION_ID = "patient-faces"
```

---

## Step 1: Validate the Verification Image

*Before calling Rekognition, check that the captured image is usable. This catches garbage inputs early and saves API costs.*

```python
rekognition_client = boto3.client("rekognition", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")


def validate_verification_image(bucket: str, key: str) -> dict:
    """
    Check that the verification image contains exactly one face with
    acceptable quality metrics.

    Why exactly one face? If there are zero faces, the image is useless.
    If there are multiple faces, we don't know which one is the patient.
    Both cases require a retake.

    Args:
        bucket: S3 bucket containing the verification image
        key: S3 object key for the verification image

    Returns:
        Dict with 'valid' (bool), 'face_detail' (if valid), and 'reason' (if invalid).
    """
    # DetectFaces gives us face count, quality metrics, and bounding boxes
    # without comparing to anything. It's our pre-flight check.
    response = rekognition_client.detect_faces(
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        Attributes=["QUALITY", "DEFAULT"],
    )

    faces = response.get("FaceDetails", [])

    # Check: exactly one face present
    if len(faces) == 0:
        return {"valid": False, "reason": "no_face_detected"}
    if len(faces) > 1:
        return {"valid": False, "reason": "multiple_faces_detected", "face_count": len(faces)}

    face = faces[0]

    # Check: face detection confidence
    if face.get("Confidence", 0) < MINIMUM_FACE_CONFIDENCE:
        return {
            "valid": False,
            "reason": "low_face_confidence",
            "confidence": face["Confidence"],
        }

    # Check: image quality (brightness and sharpness)
    quality = face.get("Quality", {})
    brightness = quality.get("Brightness", 0)
    sharpness = quality.get("Sharpness", 0)

    if brightness < IMAGE_QUALITY_BRIGHTNESS_MIN:
        return {"valid": False, "reason": "too_dark", "brightness": brightness}
    if sharpness < IMAGE_QUALITY_SHARPNESS_MIN:
        return {"valid": False, "reason": "too_blurry", "sharpness": sharpness}

    return {"valid": True, "face_detail": face}
```

---

## Step 2: Compare Faces

*This is the core of the verification. We compare the check-in photo against the patient's enrolled reference photo. Rekognition does the heavy lifting: it extracts face embeddings (128-dimensional vectors representing facial geometry) and computes similarity.*

```python
def compare_faces(source_bucket: str, source_key: str,
                  target_bucket: str, target_key: str) -> dict:
    """
    Compare two face images and return a similarity score.

    The 'source' is the verification image (just captured at check-in).
    The 'target' is the enrollment image (stored when the patient registered).

    Rekognition compares the largest face in the source against all faces in
    the target. Since we validated both images have exactly one face, we expect
    exactly one comparison result.

    Args:
        source_bucket: Bucket for the verification (check-in) image
        source_key: Key for the verification image
        target_bucket: Bucket for the enrollment (reference) image
        target_key: Key for the enrollment image

    Returns:
        Dict with 'match' (bool), 'similarity' (float 0-100), and metadata.
    """
    response = rekognition_client.compare_faces(
        SourceImage={"S3Object": {"Bucket": source_bucket, "Name": source_key}},
        TargetImage={"S3Object": {"Bucket": target_bucket, "Name": target_key}},
        SimilarityThreshold=SIMILARITY_THRESHOLD,
        # QualityFilter removes low-quality faces from comparison.
        # AUTO lets Rekognition decide. For healthcare identity verification,
        # you want this on. A blurry reference photo shouldn't produce a match.
        QualityFilter="AUTO",
    )

    face_matches = response.get("FaceMatches", [])
    unmatched_faces = response.get("UnmatchedFaces", [])

    if face_matches:
        # Match found above our threshold
        best_match = face_matches[0]
        similarity = best_match["Similarity"]
        return {
            "match": True,
            "similarity": similarity,
            "face_matches_count": len(face_matches),
        }
    else:
        # No match above threshold. The face in the source image doesn't
        # look enough like the face in the target image.
        # UnmatchedFaces tells us Rekognition DID find a face in the target,
        # it just didn't match. This distinguishes "wrong person" from
        # "couldn't find a face in the reference photo."
        return {
            "match": False,
            "similarity": 0.0,
            "unmatched_count": len(unmatched_faces),
            "reason": "below_threshold",
        }
```

---

## Step 3: Search by Face Collection (Alternative Path)

*For organizations with many patients, comparing against individual S3 images doesn't scale. Rekognition Collections let you index faces once and search against the entire collection in a single API call. This is the "search a million faces in 500ms" approach.*

```python
def enroll_patient_face(patient_id: str, bucket: str, key: str) -> dict:
    """
    Index a patient's enrollment photo into the Rekognition collection.

    This stores a face embedding (not the image itself) in the collection,
    tagged with the patient_id as external metadata. Future searches can
    find this patient by face without knowing their ID in advance.

    Args:
        patient_id: Unique patient identifier (MRN or similar)
        bucket: S3 bucket containing the enrollment photo
        key: S3 key for the enrollment photo

    Returns:
        Dict with face_id (Rekognition's internal ID) and status.
    """
    response = rekognition_client.index_faces(
        CollectionId=FACE_COLLECTION_ID,
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        # ExternalImageId links this face back to your patient record.
        # Max 255 chars. Use the patient_id so you can resolve matches later.
        ExternalImageId=patient_id,
        # Only index the largest face in the image.
        MaxFaces=1,
        QualityFilter="AUTO",
        DetectionAttributes=["DEFAULT"],
    )

    indexed_faces = response.get("FaceRecords", [])
    if not indexed_faces:
        return {"success": False, "reason": "no_face_indexed"}

    face_record = indexed_faces[0]
    return {
        "success": True,
        "face_id": face_record["Face"]["FaceId"],
        "patient_id": patient_id,
        "confidence": face_record["Face"]["Confidence"],
    }


def search_patient_by_face(bucket: str, key: str) -> dict:
    """
    Search the patient face collection for a match to the verification image.

    This is the scalable alternative to compare_faces. Instead of comparing
    against one known patient's photo, we search the entire enrolled population.
    Useful for scenarios where the patient hasn't identified themselves yet
    (walk-up kiosk, no appointment context).

    Args:
        bucket: S3 bucket containing the verification image
        key: S3 key for the verification image

    Returns:
        Dict with match results. If matched, includes patient_id and similarity.
    """
    response = rekognition_client.search_faces_by_image(
        CollectionId=FACE_COLLECTION_ID,
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        FaceMatchThreshold=SIMILARITY_THRESHOLD,
        MaxFaces=3,  # return top 3 matches for audit purposes
    )

    matches = response.get("FaceMatches", [])

    if not matches:
        return {"match": False, "reason": "no_match_in_collection"}

    # Best match is first (sorted by similarity descending)
    best = matches[0]
    return {
        "match": True,
        "patient_id": best["Face"]["ExternalImageId"],
        "similarity": best["Similarity"],
        "face_id": best["Face"]["FaceId"],
        "total_candidates": len(matches),
    }
```

---

## Step 4: Record the Verification Attempt

*Every verification attempt gets an audit record. This is non-negotiable in healthcare. You need to know who was verified, when, whether it succeeded, and what the confidence was. This feeds compliance reporting and fraud investigation.*

```python
def record_verification_attempt(
    patient_id: str,
    verification_key: str,
    result: dict,
    method: str,
) -> dict:
    """
    Write an audit record for this verification attempt to DynamoDB.

    Args:
        patient_id: The patient being verified
        verification_key: S3 key of the check-in photo
        result: The comparison/search result dict
        method: "compare" (1:1) or "search" (1:N)

    Returns:
        The audit record that was written.
    """
    table = dynamodb.Table(AUDIT_TABLE)

    record = {
        "patient_id": patient_id,
        "verification_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "verification_image_key": verification_key,
        "method": method,
        "match": result.get("match", False),
        # DynamoDB requires Decimal for numbers, not float.
        "similarity_score": Decimal(str(round(result.get("similarity", 0.0), 2))),
        "outcome": "verified" if result.get("match") else "failed",
    }

    # Add failure reason if present
    if not result.get("match") and "reason" in result:
        record["failure_reason"] = result["reason"]

    table.put_item(Item=record)
    return record
```

---

## Putting It All Together

Here's the full verification pipeline assembled into a single function. This is what your check-in kiosk application or Lambda handler would call.

```python
def verify_patient(patient_id: str, verification_bucket: str,
                   verification_key: str, enrollment_bucket: str,
                   enrollment_key: str) -> dict:
    """
    Run the full patient photo verification pipeline.

    This is the 1:1 comparison path: we know who the patient claims to be
    (they scanned their badge, entered their MRN, etc.) and we're confirming
    their face matches their enrollment photo.

    Args:
        patient_id: Who the patient claims to be
        verification_bucket: Bucket with the just-captured check-in photo
        verification_key: Key for the check-in photo
        enrollment_bucket: Bucket with the stored enrollment photo
        enrollment_key: Key for the enrollment photo

    Returns:
        Dict with verification outcome, similarity score, and audit record.
    """

    # Step 1: Validate the verification image before wasting a comparison call.
    logger.info("Step 1: Validating verification image for patient %s", patient_id)
    validation = validate_verification_image(verification_bucket, verification_key)

    if not validation["valid"]:
        logger.info("  Image validation failed: %s", validation["reason"])
        result = {"match": False, "similarity": 0.0, "reason": validation["reason"]}
        audit = record_verification_attempt(patient_id, verification_key, result, "compare")
        return {"verified": False, "reason": validation["reason"], "audit": audit}

    # Step 2: Compare the verification image against the enrollment image.
    logger.info("Step 2: Comparing faces")
    comparison = compare_faces(
        source_bucket=verification_bucket,
        source_key=verification_key,
        target_bucket=enrollment_bucket,
        target_key=enrollment_key,
    )
    logger.info("  Match: %s, Similarity: %.1f%%", comparison["match"], comparison["similarity"])

    # Step 3: Record the attempt for audit trail.
    logger.info("Step 3: Recording verification attempt")
    audit = record_verification_attempt(patient_id, verification_key, comparison, "compare")

    return {
        "verified": comparison["match"],
        "similarity": comparison["similarity"],
        "patient_id": patient_id,
        "audit": audit,
    }


# Example: verify a patient at check-in
if __name__ == "__main__":
    import json

    result = verify_patient(
        patient_id="MRN-00482931",
        verification_bucket="patient-photos-hipaa",
        verification_key="verifications/2026/05/31/kiosk-03/capture-001.jpg",
        enrollment_bucket="patient-photos-hipaa",
        enrollment_key="enrollments/MRN-00482931/primary.jpg",
    )

    # Never print the actual image data or biometric embeddings.
    # Only print the verification decision and metadata.
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Point it at two face images in S3 and it will tell you whether they match. But there's a meaningful distance between "works in a script" and "runs at a hospital check-in kiosk handling real patients." Here's where that gap lives:

**Liveness detection.** This code compares two static images. A production system needs to confirm the person is physically present, not holding up a printed photo or a phone screen showing someone else's face. AWS Rekognition Face Liveness (released 2023) handles this with a short video challenge that detects depth, texture, and motion. Without liveness detection, your system is trivially spoofable.

**Anti-spoofing beyond liveness.** Even with liveness detection, sophisticated attacks exist: 3D-printed masks, deepfake video feeds, high-resolution displays. A production system layers multiple signals: device attestation (is this our kiosk hardware?), session binding (is this the same device that started the check-in flow?), and behavioral signals (did the person interact naturally with the kiosk?).

**Enrollment quality control.** This code assumes the enrollment photo is good. In reality, enrollment photos are often terrible: taken years ago, poor lighting, wrong angle, patient wearing sunglasses. A production system validates enrollment photos at capture time using the same quality checks we apply to verification images, and prompts re-enrollment when photos age past the threshold.

**Bias testing and fairness.** Face recognition systems have well-documented accuracy disparities across demographics (skin tone, age, gender). A production deployment must measure false-accept and false-reject rates across demographic groups and ensure the system doesn't systematically disadvantage any patient population. This isn't optional. It's both an ethical requirement and, increasingly, a regulatory one.

**Fallback workflows.** What happens when verification fails? A production system needs graceful degradation: staff-assisted verification, alternative identity methods (ID card scan, knowledge-based questions), and clear escalation paths. The face check is one factor in a multi-factor identity workflow, not the sole gatekeeper.

**Consent management.** Biometric data collection requires explicit patient consent in most jurisdictions. Illinois BIPA, Texas CUBI, Washington state law, and GDPR all have specific requirements for biometric data. Your system needs consent capture, storage, and revocation workflows before collecting any face data.

**Photo storage and retention.** Enrollment photos and verification captures are biometric PHI. They need encryption at rest (KMS CMK), access logging (CloudTrail), retention policies (auto-delete after consent withdrawal or account closure), and geographic restrictions (some regulations require biometric data stay in-jurisdiction).

**Error handling and retries.** Rekognition can throttle under load, return transient errors, or timeout on large images. A production system handles each failure mode specifically: retry throttling with backoff, fail gracefully on service errors, and resize oversized images before submission.

**VPC and network isolation.** Patient photos are PHI. They should never traverse the public internet. Production deployments use VPC endpoints for S3 and Rekognition, keeping all traffic on the AWS backbone. The kiosk itself connects via a private network path.

**Performance at scale.** The 1:1 comparison path (compare_faces) works when you know who the patient is. For walk-up scenarios or large populations, the collection-based search (search_faces_by_image) scales to millions of enrolled faces. But collection management (adding faces, removing faces on consent withdrawal, handling duplicates) is its own operational challenge.

**Testing with synthetic data.** Never use real patient photos in development or testing. Generate synthetic face images or use publicly available face datasets (with appropriate licensing). Your test suite should cover: matching pairs, non-matching pairs, poor quality images, multiple faces, no faces, and edge cases like twins or patients with significant appearance changes.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 9.2](chapter09.02-patient-photo-verification.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
