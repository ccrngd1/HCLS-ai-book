# Recipe 1.6: Handwritten Clinical Note Digitization: Python Example

> **This is a simplified, illustrative implementation.** It is not production-ready. It demonstrates the patterns from Recipe 1.6 using boto3 and the Bedrock Converse API. Think of it as a working sketch: the right shape, the right API calls, the right logic flow. What you'd need to add for a real deployment is covered in the "Gap to Production" section at the end.

---

## Setup

```bash
pip install boto3 pillow opencv-python-headless numpy
```

You'll also need:
- AWS credentials configured (`aws configure` or an instance/task role)
- Bedrock model access granted in your AWS account for `anthropic.claude-haiku-4-5-v1:0` and `anthropic.claude-sonnet-4-6-v1:0`
- IAM permissions: `textract:AnalyzeDocument`, `bedrock:InvokeModel`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `sagemaker:StartHumanLoop` 

---

## Configuration

These constants drive routing decisions and API calls. Tune the confidence thresholds against your actual document population before going live.

```python
import json
import uuid
import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import cv2
import numpy as np
from PIL import Image

# -------------------------------------------------------------------
# Routing thresholds
# -------------------------------------------------------------------
# Average Textract handwriting confidence thresholds for model tier selection.
# >= TIER_1_THRESHOLD → Haiku (fast, cost-efficient)
# [DIRECT_REVIEW_THRESHOLD, TIER_1_THRESHOLD) → Sonnet (handles hard cases)
# < DIRECT_REVIEW_THRESHOLD → skip vision extraction, route directly to human review
TIER_1_THRESHOLD = 70.0
DIRECT_REVIEW_THRESHOLD = 40.0

# -------------------------------------------------------------------
# Composite confidence tiering thresholds
# -------------------------------------------------------------------
# Composite = min(OCR confidence, vision model confidence)
# >= HIGH_ACCEPT_THRESHOLD → auto-accept
# [MEDIUM_FLAG_THRESHOLD, HIGH_ACCEPT_THRESHOLD) → accept with flag
# < MEDIUM_FLAG_THRESHOLD → human review required
HIGH_ACCEPT_THRESHOLD = 80.0
MEDIUM_FLAG_THRESHOLD = 60.0

# -------------------------------------------------------------------
# Vision model confidence → numeric mapping
# -------------------------------------------------------------------
# The vision model returns HIGH/MEDIUM/LOW. Map these to numeric values
# for composite score computation. These values are tuned to reflect
# that vision model self-reported confidence is less precisely calibrated
# than Textract's numeric scores.
VISION_CONFIDENCE_MAP = {
    "HIGH": 90.0,
    "MEDIUM": 65.0,
    "LOW": 35.0,
}

# -------------------------------------------------------------------
# Bedrock model IDs
# -------------------------------------------------------------------
# Use the "us." cross-region prefix for global inference routing.
# This provides automatic fallback across us-east-1, us-east-2, us-west-2.
# Cross-region profiles may be updated by AWS over time. For strict version
# pinning, use the full foundation model ARN for your target region and
# check the Bedrock Model IDs documentation for the current ARN format.
HAIKU_MODEL_ID = "us.anthropic.claude-haiku-4-5-v1:0"
SONNET_MODEL_ID = "us.anthropic.claude-sonnet-4-6-v1:0"

# -------------------------------------------------------------------
# Boto3 retry configuration
# -------------------------------------------------------------------
# adaptive mode implements exponential backoff with jitter. This is the
# right default for Bedrock: ThrottlingException and ServiceUnavailableException
# are expected at any meaningful production volume.
# Apply this Config to every boto3 client that makes calls carrying PHI.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# [EDITOR: Added BOTO3_RETRY_CONFIG constant. This was a P0 finding in the 1.4 review:
# no retry logic in pseudocode or Python for Bedrock throttling. Applied to all
# AWS clients below. Do not retry at the Lambda invocation level for Bedrock errors:
# that would generate a new task_token hash and risk an A2I HumanLoopName collision.]

# -------------------------------------------------------------------
# S3 buckets (substitute your actual bucket names)
# -------------------------------------------------------------------
INTAKE_BUCKET = "notes-intake"
ENHANCED_BUCKET = "notes-enhanced"
REVIEW_OUTPUT_BUCKET = "notes-review-output"
PROMPT_LIBRARY_BUCKET = "notes-prompt-library"

# -------------------------------------------------------------------
# DynamoDB table names
# -------------------------------------------------------------------
ENTITIES_TABLE = "clinical-note-entities"
COMPLETED_TABLE = "completed-extractions"

# -------------------------------------------------------------------
# The extraction system prompt
# -------------------------------------------------------------------
# This goes into the Bedrock Converse API 'system' parameter.
# In production, the FEW-SHOT EXAMPLES section would contain 3-5 examples
# from your prompt library. Prompt caching makes this affordable:
# the first call writes the cache; subsequent calls read it at 10% cost.
#
# ⚠ PHI CROSS-CONTAMINATION WARNING:
# Examples inserted in this prompt MUST use synthetic or de-identified images
# ONLY. NEVER insert real patient document images here.
# When this system prompt is sent to Bedrock for Patient B's note, everything
# in it (including any embedded images) is part of that API call.
# Using a real patient's note image as a few-shot example sends that patient's
# PHI to Bedrock during every other patient's extraction call. This is a HIPAA
# disclosure under the minimum-necessary standard.
# All examples must pass _validate_example_is_synthetic() before entering this prompt.
# [EDITOR: review fix] Added PHI cross-contamination warning to EXTRACTION_SYSTEM_PROMPT.
EXTRACTION_SYSTEM_PROMPT = """
You are a clinical document analysis assistant. You will receive a handwritten
clinical note image and an OCR transcript. The OCR may contain transcription
errors due to difficult handwriting. Use the image as your primary source.
Use the OCR transcript only as a supplementary guide.

Extract all clinical entities from the handwritten portions of the note.
Return a JSON object in exactly this format:

{
  "entities": [
    {
      "text": "extracted text exactly as written in the note",
      "normalized": "standardized clinical term if different from handwritten text",
      "category": "MEDICATION | MEDICAL_CONDITION | DOSAGE | LAB_VALUE | PROCEDURE | OTHER",
      "confidence": "HIGH | MEDIUM | LOW",
      "confidence_reason": "brief explanation of your confidence level",
      "is_handwritten": true
    }
  ],
  "page_quality": "GOOD | FAIR | POOR",
  "notes": "observations about unusual abbreviations, illegible sections, or ambiguities"
}

Confidence levels:
- HIGH: You are certain about the extraction and its clinical meaning.
- MEDIUM: You can read the text but are uncertain about clinical interpretation,
          OR you are confident about the meaning but uncertain about an ambiguous letterform.
- LOW: The handwriting is illegible or the clinical meaning is unclear.

Return only the JSON object. Do not include any explanation outside the JSON.
"""
```

---

## PHI Validation Stub

```python
def _validate_example_is_synthetic(example: dict) -> bool:
    """
    Gate function: confirm a prompt example candidate uses a synthetic
    de-identified image before it is eligible for the active prompt library.

    FAILURE BEHAVIOR: This function MUST raise an exception (not log a warning,
    not return False silently) if it cannot positively confirm the example is
    synthetic. Returning False or logging a warning allows a caller to ignore
    the result and proceed. An exception forces the issue: the caller cannot
    continue without explicitly handling it. Any deployment path that catches
    this exception and promotes the example anyway is non-compliant.

    "Positively confirm" means one of:
      (a) a metadata tag set only by a designated de-identification workflow,
      (b) a hash check against an approved synthetic image registry, or
      (c) a cryptographic signature from the de-identification pipeline.

    This is a stub. In production, implement the validation logic appropriate
    for your de-identification workflow and raise ValueError (or a custom
    exception type) with a descriptive message if validation fails.

    Returns True only if the example has been confirmed de-identified.
    Never promote an example that does not pass this check to the active
    system prompt.

    [EDITOR: review fix] Updated _validate_example_is_synthetic() to document
    the hard-failure requirement. The stub previously returned False on failure,
    which a caller could silently ignore. This function MUST raise an exception
    on failure so the validation gate is non-bypassable. The prompt library
    bucket should use a separate S3 prefix (prompt-library/synthetic/) with IAM
    PutObject access restricted to the designated prompt engineer role only.
    Run this function on all embedded images as a required CI/CD step before
    any prompt deployment. Fail the deployment if any image fails validation.
    """
    # Check the explicit de-identification flag set during capture.
    if not example.get("deidentified", False):
        raise ValueError(
            f"Example validation failed: 'deidentified' flag is not True. "
            f"image_key={example.get('image_key', 'unknown')}. "
            "The source image must be replaced with a synthetic de-identified "
            "equivalent before this example is eligible for the prompt library. "
            "This is not optional."
        )

    # Additional check: synthetic images should live in a designated prefix,
    # never in the original enhanced-images bucket path.
    image_key = example.get("image_key", "")
    if image_key.startswith("notes-enhanced/") and not image_key.startswith("notes-enhanced/synthetic/"):
        # Image is from the live enhanced-images path, not the synthetic prefix.
        # This is a real patient image. Raise hard to prevent promotion.
        raise ValueError(
            f"Example validation failed: image_key '{image_key}' is in the live "
            "enhanced-images path, not the designated synthetic prefix "
            "(notes-enhanced/synthetic/). Real patient images must not enter "
            "the prompt library. Replace with a synthetic de-identified equivalent."
        )

    # TODO: add your organization-specific de-identification verification here.
    # For example: query a de-identification audit table, check for an
    # approval record from the prompt engineer's review tool, or verify the
    # image hash against a registry of approved synthetic examples.
    # This check MUST raise ValueError (not return False) if it cannot
    # positively confirm the example is synthetic.

    return True
```

---

## Step 1: Image Pre-Processing

```python
def preprocess_image(input_s3_key: str) -> str:
    """
    Download a handwritten note image from S3, improve its quality,
    and save the enhanced version back to S3.

    Returns the S3 key of the enhanced image.

    Why this matters: even though vision models are more tolerant of imperfect
    input than OCR engines, better input still produces better output.
    Deskewing, contrast enhancement, noise reduction, and size normalization
    measurably improve Textract confidence scores and vision model accuracy on
    marginal images. Size normalization also controls Bedrock image token costs:
    a 4000px phone photograph uses ~3-4x the tokens of a normalized 1800px scan.
    """
    s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

    # Download the image from the intake bucket.
    response = s3.get_object(Bucket=INTAKE_BUCKET, Key=input_s3_key)
    image_bytes = response["Body"].read()

    # Decode to OpenCV format (numpy array) for processing.
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    # --- Deskew ---
    # Estimate the rotation angle from horizontal text lines and correct it.
    # Even a 2-3 degree tilt degrades OCR confidence measurably.
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray_inv = cv2.bitwise_not(gray)
    thresh = cv2.threshold(gray_inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]

    coords = np.column_stack(np.where(thresh > 0))
    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect returns angles in [-90, 0); correct to [-45, 45) range.
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    image = cv2.warpAffine(
        image, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )

    # --- Contrast enhancement with CLAHE ---
    # Contrast Limited Adaptive Histogram Equalization handles uneven lighting
    # (e.g., shadows across part of the page) better than global normalization.
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    image = cv2.merge((l_channel, a_channel, b_channel))
    image = cv2.cvtColor(image, cv2.COLOR_LAB2BGR)

    # --- Bilateral filter for noise reduction ---
    # Removes high-frequency noise from compression artifacts and paper grain
    # while preserving the fine edges of handwritten strokes.
    # d=9 means a 9-pixel diameter neighborhood. Larger values slow processing.
    image = cv2.bilateralFilter(image, d=9, sigmaColor=75, sigmaSpace=75)

    # --- Size normalization ---
    # Normalize to a maximum dimension of 1800px to control Bedrock image token costs.
    # A 4000px phone photograph uses ~3-4x the tokens of a 1800px scan.
    # Monitor per-call token usage in CloudWatch and adjust this target if costs spike.
    max_dimension = 1800
    (h, w) = image.shape[:2]
    if max(h, w) > max_dimension:
        scale = max_dimension / max(h, w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # Encode to PNG bytes for storage and API calls.
    _, encoded_bytes = cv2.imencode(".png", image)
    enhanced_key = input_s3_key.replace("notes-intake/", "notes-enhanced/", 1)

    s3.put_object(
        Bucket=ENHANCED_BUCKET,
        Key=enhanced_key,
        Body=encoded_bytes.tobytes(),
        ContentType="image/png",
        ServerSideEncryption="aws:kms",  # SSE-KMS required for PHI content
    )

    print(f"[preprocess] Enhanced image saved: s3://{ENHANCED_BUCKET}/{enhanced_key}")
    return enhanced_key
```

---

## Step 2: Textract Quality Signal

```python
def compute_quality_signal(enhanced_image_key: str) -> dict:
    """
    Run Textract AnalyzeDocument to generate a quality signal for routing.

    Textract's role in this pipeline is NOT primary extraction.
    Its job is to tell us:
      1. How legible is the handwriting on this page? (avg confidence)
      2. Which words are handwritten vs. printed? (TextType flags)
      3. What is the raw OCR text? (supplementary input for the vision model prompt)

    Returns a dict with routing signal and word-level data.
    """
    textract = boto3.client("textract", config=BOTO3_RETRY_CONFIG)
    s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

    # Retrieve the enhanced image for the Textract call.
    response_s3 = s3.get_object(Bucket=ENHANCED_BUCKET, Key=enhanced_image_key)
    image_bytes = response_s3["Body"].read()

    # AnalyzeDocument with FORMS and LAYOUT.
    # FORMS: extracts key-value pairs from any structured form fields on the page.
    # LAYOUT: provides reading-order metadata for text reconstruction.
    response = textract.analyze_document(
        Document={"Bytes": image_bytes},
        FeatureTypes=["FORMS", "LAYOUT"],
    )

    handwritten_words = []
    printed_words = []
    lines = []

    for block in response["Blocks"]:
        if block["BlockType"] == "WORD":
            word = {
                "text": block["Text"],
                "confidence": block["Confidence"],
                "text_type": block.get("TextType", "PRINTED"),
                # BoundingBox: Left, Top, Width, Height as fractions of page size
                "bounding_box": block["Geometry"]["BoundingBox"],
            }
            if block.get("TextType") == "HANDWRITING":
                handwritten_words.append(word)
            else:
                printed_words.append(word)

        elif block["BlockType"] == "LINE":
            lines.append(block["Text"])

    # Compute average handwriting confidence. This is our routing signal.
    if handwritten_words:
        avg_hw_confidence = sum(w["confidence"] for w in handwritten_words) / len(handwritten_words)
    else:
        # No handwritten words: all printed. High-quality signal by default.
        avg_hw_confidence = 100.0

    # Determine routing tier based on average handwriting confidence.
    if avg_hw_confidence >= TIER_1_THRESHOLD:
        model_tier = "TIER_1"
    elif avg_hw_confidence >= DIRECT_REVIEW_THRESHOLD:
        model_tier = "TIER_2"
    else:
        model_tier = "DIRECT_REVIEW"

    ocr_text = "\n".join(lines)

    print(
        f"[quality_signal] Avg HW confidence: {avg_hw_confidence:.1f}% "
        f"| HW words: {len(handwritten_words)} "
        f"| Routed to: {model_tier}"
    )

    return {
        "avg_hw_confidence": avg_hw_confidence,
        "model_tier": model_tier,
        "handwritten_words": handwritten_words,
        "printed_words": printed_words,
        "ocr_text": ocr_text,
        "textract_response": response,
    }
```

---

## Step 3: Vision Model Extraction

```python
def extract_with_vision(
    enhanced_image_key: str,
    ocr_text: str,
    model_tier: str,
) -> dict:
    """
    Send the page image to Bedrock for clinical entity extraction.

    This is the core of Recipe 1.6. The vision model reads the handwriting
    in context: it sees the image and the surrounding text simultaneously,
    which enables disambiguation that OCR + NLP pipelines cannot perform.

    Model selection:
      TIER_1 → Claude Haiku 4.5 (fast, ~$0.004/page, handles clean handwriting)
      TIER_2 → Claude Sonnet 4.6 (accurate, ~$0.012/page, handles difficult cases)

    Returns parsed entity list plus metadata.
    """
    # Configure with adaptive retry mode. Bedrock ThrottlingException and
    # ServiceUnavailableException are expected at production volume.
    # Retry at the API call level here (not Lambda invocation level) to avoid
    # generating a new task_token on each attempt, which would cause an A2I
    # HumanLoopName collision if a review loop had already been created.
    bedrock = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
    s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

    # [EDITOR: Added BOTO3_RETRY_CONFIG to the Bedrock client. The v1 example had no retry
    # logic, which is a P0 production failure mode. Bedrock vision calls can take 15+ seconds
    # under load; throttling under burst traffic is expected at healthcare volume.]

    # Select model based on tier routing from Step 2.
    if model_tier == "TIER_1":
        model_id = HAIKU_MODEL_ID
    else:
        model_id = SONNET_MODEL_ID

    # Load the enhanced image for the Bedrock call.
    response_s3 = s3.get_object(Bucket=ENHANCED_BUCKET, Key=enhanced_image_key)
    image_bytes = response_s3["Body"].read()

    # Build the Converse API message content.
    # Content is a list: the image comes first, then the text prompt.
    # Bedrock encodes image bytes directly; no base64 needed for the Converse API.
    messages = [
        {
            "role": "user",
            "content": [
                {
                    # Image block: send the page image directly to the vision model.
                    # This is the key difference from Recipe 1.4 and 1.5:
                    # we're not sending extracted text, we're sending the image itself.
                    "image": {
                        "format": "png",
                        "source": {"bytes": image_bytes},
                    }
                },
                {
                    # Text block: include OCR as a supplementary signal.
                    # The model is instructed to use the image as primary source.
                    "text": (
                        "OCR transcript (may contain errors due to difficult handwriting):\n\n"
                        + ocr_text
                        + "\n\nPlease extract clinical entities from the handwritten "
                        "content in the image."
                    )
                },
            ],
        }
    ]

    print(f"[vision_extract] Calling {model_id} for extraction...")

    # Converse API call.
    # temperature=0 for maximum determinism in structured extraction output.
    # maxTokens=2048 is sufficient for most clinical note extraction results.
    response = bedrock.converse(
        modelId=model_id,
        system=[{"text": EXTRACTION_SYSTEM_PROMPT}],
        messages=messages,
        inferenceConfig={"maxTokens": 2048, "temperature": 0},
    )

    raw_output = response["output"]["message"]["content"][0]["text"]

    # Parse the JSON response. The model is instructed to return only JSON,
    # but validate defensively since model output is never guaranteed to parse.
    try:
        # Strip any markdown code fences the model might have added.
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
            cleaned = cleaned.strip()

        parsed = json.loads(cleaned)

        entities = parsed.get("entities", [])
        page_quality = parsed.get("page_quality", "UNKNOWN")
        notes = parsed.get("notes", "")
        parse_error = False

    except json.JSONDecodeError as e:
        # Parsing failure routes to human review; don't let bad output propagate.
        # IMPORTANT: do NOT log raw_output here. The model response may echo
        # clinical content from the input image (medication names, diagnoses,
        # patient context). Log only structural metadata.
        parse_error_detail = (
            f"JSONDecodeError: {type(e).__name__}. "
            f"Response length: {len(raw_output)} chars. "
            "Raw content omitted from logs (may contain PHI)."
        )
        print(f"[vision_extract] Parse error. {parse_error_detail} Routing to human review.")
        entities = []
        page_quality = "UNKNOWN"
        notes = parse_error_detail
        parse_error = True

        # [EDITOR: Fixed PHI exposure in error logging. The v1 example logged
        # raw_output[:200] in the JSONDecodeError handler, which could contain
        # clinical entities echoed from the input image. Now logs only structural
        # metadata (error type, response length). This was a P1 finding in the
        # 1.4 review. Same fix applied to the notes field stored to DynamoDB.]

    print(
        f"[vision_extract] Extracted {len(entities)} entities "
        f"| Page quality: {page_quality} "
        f"| Model: {model_id}"
    )

    return {
        "entities": entities,
        "page_quality": page_quality,
        "notes": notes,
        "parse_error": parse_error,
        "model_tier": model_tier,
        "model_id": model_id,
    }
```

---

## Step 4: Composite Scoring and Tiering

```python
def find_ocr_confidence_for_entity(entity_text: str, handwritten_words: list) -> float:
    """
    Find the Textract word-level confidence for the words that make up this entity.

    This is an approximate text matching: we look for handwritten words whose
    text matches tokens in the entity string. For multi-word entities
    (e.g., "Type 2 diabetes mellitus"), we find all matching words and return
    the minimum confidence. The minimum is intentional: if any word in a
    medication name was read poorly, the whole name is suspect.

    Returns a default of 80.0 if no match is found (entity likely came from
    printed text, which has a higher confidence baseline).
    """
    entity_tokens = set(entity_text.lower().split())
    matched_confidences = []

    for word in handwritten_words:
        if word["text"].lower() in entity_tokens:
            matched_confidences.append(word["confidence"])

    if matched_confidences:
        return min(matched_confidences)
    else:
        return 80.0  # Conservative default when no handwritten match found


def composite_score_and_tier(vision_result: dict, handwritten_words: list) -> dict:
    """
    Compute a composite confidence score for each extracted entity and
    assign it to a routing tier.

    Composite score = min(Textract OCR confidence, vision model confidence as numeric)

    Tiering:
      >= HIGH_ACCEPT_THRESHOLD (80): auto-accept
      [MEDIUM_FLAG_THRESHOLD (60), 80): accept with flag
      < 60: human review required
    """
    tiered = {"high": [], "medium": [], "low": []}

    for entity in vision_result.get("entities", []):
        # Map the vision model's confidence string to a numeric value.
        vision_numeric = VISION_CONFIDENCE_MAP.get(
            entity.get("confidence", "LOW").upper(), 35.0
        )

        # Get the Textract OCR confidence for this entity's text span.
        ocr_confidence = find_ocr_confidence_for_entity(
            entity.get("text", ""), handwritten_words
        )

        # Composite: minimum of both signals.
        composite = min(ocr_confidence, vision_numeric)

        enriched = {
            "id": str(uuid.uuid4()),
            "text": entity.get("text", ""),
            "normalized": entity.get("normalized", entity.get("text", "")),
            "category": entity.get("category", "OTHER"),
            "is_handwritten": entity.get("is_handwritten", True),
            "ocr_confidence": round(ocr_confidence, 1),
            "vision_confidence": entity.get("confidence", "LOW"),
            "vision_numeric": vision_numeric,
            "composite_confidence": round(composite, 1),
            "confidence_reason": entity.get("confidence_reason", ""),
        }

        if composite >= HIGH_ACCEPT_THRESHOLD:
            tiered["high"].append(enriched)
        elif composite >= MEDIUM_FLAG_THRESHOLD:
            tiered["medium"].append(enriched)
        else:
            tiered["low"].append(enriched)

    high_count = len(tiered["high"])
    medium_count = len(tiered["medium"])
    low_count = len(tiered["low"])
    print(
        f"[tiering] Auto-accept: {high_count} | Flagged: {medium_count} | Human review: {low_count}"
    )

    return tiered
```

---

## Step 5: Store Auto-Accepted Entities

```python
def store_auto_accepted(document_key: str, tiered_entities: dict) -> None:
    """
    Write high and medium confidence entities to DynamoDB immediately.

    High confidence: auto_accepted. Safe for downstream use.
    Medium confidence: accepted_flagged. Usable but flagged for downstream review.

    Note: DynamoDB requires float values to be stored as Decimal.
    boto3 will throw a TypeError if you try to store a Python float directly.

    Idempotency: the ConditionExpression="attribute_not_exists(sk)" ensures
    that a Lambda retry does not create duplicate entity records. If the item
    already exists (same sk), the write is skipped rather than overwriting.
    The ConditionalCheckFailedException is caught and treated as a no-op.
    """
    # [EDITOR: review fix] Added ConditionExpression for idempotent writes.
    # Previously, store_auto_accepted used put_item with no condition. If the
    # Lambda was retried by Step Functions after a partial write, composite_score_and_tier
    # would run again and generate new UUIDs, writing duplicate entity records.
    # assemble_final_record queries by partition key and returns all items including
    # duplicates, inflating final entity counts. The condition prevents this.
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(ENTITIES_TABLE)

    all_auto = tiered_entities.get("high", []) + tiered_entities.get("medium", [])

    for entity in all_auto:
        review_status = (
            "auto_accepted" if entity in tiered_entities["high"] else "accepted_flagged"
        )
        try:
            table.put_item(
                Item={
                    "pk": document_key,
                    "sk": entity["id"],
                    "entity_text": entity["text"],
                    "normalized": entity["normalized"],
                    "category": entity["category"],
                    # DynamoDB gotcha: Decimal required for all float/int numeric values.
                    "composite_confidence": Decimal(str(entity["composite_confidence"])),
                    "ocr_confidence": Decimal(str(entity["ocr_confidence"])),
                    "vision_confidence": entity["vision_confidence"],
                    "review_status": review_status,
                    "is_handwritten": entity["is_handwritten"],
                    "stored_at": datetime.now(timezone.utc).isoformat(),
                },
                # Idempotent write: skip if this entity ID already exists.
                # On Lambda retry, this prevents duplicate records without error.
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                # Entity already written on a previous attempt. This is expected
                # on retry: the item exists and is correct. Skip silently.
                print(f"[store_auto] Entity {entity['id']} already exists, skipping (idempotent retry).")
            else:
                raise

    print(f"[store_auto] Wrote {len(all_auto)} auto-accepted entities to DynamoDB")
```

---

## Step 6: Start A2I Human Review

```python
def start_human_review(
    document_key: str,
    enhanced_image_key: str,
    textract_ocr_text: str,
    tiered_entities: dict,
    task_token: str,
    flow_definition_arn: str,
) -> bool:
    """
    Bundle low-confidence entities into an A2I human review task.

    Full-page review case: if ALL tiers are empty (parse error or DIRECT_REVIEW
    path), a sentinel entity is inserted to force A2I creation. These pages most
    need human review. The reviewer sees the raw image and OCR text and performs
    extraction from scratch.

    If only high/medium confidence entities exist and low is empty, call
    SendTaskSuccess immediately and return False (no review needed).

    Otherwise, create the human loop and return True (Step Functions execution
    is now suspended).

    [EDITOR: review fix] Previously, this function checked `if not low_confidence`
    and called SendTaskSuccess immediately when tiered_entities had no "low" items.
    This silently bypassed A2I for parse errors and DIRECT_REVIEW paths, which are the two
    cases that most need human review. The sentinel entity logic below fixes this.
    """
    # [EDITOR: review fix] Full-page review detection: if ALL tiers are empty,
    # vision extraction failed entirely (parse error) or Textract confidence
    # was below DIRECT_REVIEW_THRESHOLD. Insert a sentinel entity to force A2I
    # creation. The reviewer performs manual extraction from the page image.
    all_empty = not any([
        tiered_entities.get("high", []),
        tiered_entities.get("medium", []),
        tiered_entities.get("low", []),
    ])

    if all_empty:
        # Force human review with a full-page sentinel entity.
        tiered_entities = {
            "high": [],
            "medium": [],
            "low": [
                {
                    "id": str(uuid.uuid4()),
                    "text": "[FULL PAGE REVIEW REQUIRED]",
                    "category": "OTHER",
                    "ocr_confidence": 0.0,
                    "vision_confidence": "LOW",
                    "confidence_reason": (
                        "Vision extraction failed or handwriting quality is below the "
                        "automated extraction threshold. Manual extraction from the "
                        "page image is required."
                    ),
                }
            ],
        }
        print(
            "[a2i] Full-page review: vision extraction failed or DIRECT_REVIEW path. "
            "Forcing A2I with sentinel entity. Reviewer will extract from scratch."
        )

    low_confidence = tiered_entities.get("low", [])

    # If nothing needs review (only high/medium entities), resume immediately.
    if not low_confidence:
        stepfunctions = boto3.client("stepfunctions", config=BOTO3_RETRY_CONFIG)
        stepfunctions.send_task_success(
            taskToken=task_token,
            output=json.dumps({"document_key": document_key, "reviewed_count": 0}),
        )
        print("[a2i] No low-confidence entities. Resumed Step Functions immediately.")
        return False

    # Generate a pre-signed URL for the reviewer to view the document image.
    # 48-hour expiry handles queues that back up overnight.
    # In production, consider a Lambda proxy that validates the reviewer's Cognito
    # session and regenerates the URL on demand for longer-lived queues.
    # Note: pre-signed URLs point to the public S3 endpoint. Reviewer browsers
    # fetch the image over HTTPS from the public internet. For organizations
    # requiring all PHI traffic to stay on internal networks, use a Lambda proxy
    # behind API Gateway instead.
    s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
    image_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": ENHANCED_BUCKET, "Key": enhanced_image_key},
        ExpiresIn=48 * 3600,
    )

    # Build the review task input.
    task_input = {
        "document_image_uri": image_url,
        "textract_ocr_text": textract_ocr_text,
        "document_key": document_key,
        "task_token": task_token,
        "entities_to_review": [
            {
                "id": entity["id"],
                "vision_text": entity["text"],
                "category": entity["category"],
                "ocr_confidence": entity["ocr_confidence"],
                "vision_confidence": entity["vision_confidence"],
                "confidence_reason": entity["confidence_reason"],
            }
            for entity in low_confidence
        ],
    }

    # A2I InputContent is limited to 100KB. Check payload size before sending.
    # Dense clinical notes with many low-confidence entities can approach this limit.
    # If over limit, truncate OCR text (supplementary context, not primary source)
    # to fit within the limit. Failing to check raises ValidationException from
    # the A2I API, which propagates as an unhandled Lambda error.
    # [EDITOR: review fix] Added A2I 100KB payload size check. Previously there was
    # no guard; large payloads would raise ValidationException at runtime.
    input_json = json.dumps(task_input)
    if len(input_json.encode("utf-8")) > 90_000:  # 10KB safety margin under 100KB limit
        task_input["textract_ocr_text"] = (
            task_input["textract_ocr_text"][:2000]
            + " [truncated: full OCR text available in S3 at enhanced image key]"
        )
        input_json = json.dumps(task_input)
        print(
            f"[a2i] Payload exceeded 90KB; OCR text truncated to fit A2I 100KB limit. "
            f"Final payload: {len(input_json.encode('utf-8'))} bytes."
        )

    # Create the A2I human loop.
    # HumanLoopName must be unique per loop. Including the task_token hash
    # ensures retries on the same document generate distinct names,
    # avoiding ConflictException from A2I.
    loop_name = "note-review-" + hashlib.md5(
        (document_key + task_token).encode()
    ).hexdigest()[:16]

    sagemaker = boto3.client("sagemaker-a2i-runtime", config=BOTO3_RETRY_CONFIG)
    sagemaker.start_human_loop(
        HumanLoopName=loop_name,
        FlowDefinitionArn=flow_definition_arn,
        HumanLoopInput={"InputContent": input_json},
    )

    # [EDITOR: Added BOTO3_RETRY_CONFIG to sagemaker-a2i-runtime client. Also removed
    # the `import hashlib` that was inside the function body in v1 (it's now at the top
    # of the module with the other imports).]

    print(
        f"[a2i] Started human loop '{loop_name}' "
        f"for {len(low_confidence)} low-confidence entities. "
        f"Step Functions execution suspended."
    )
    return True
```

---

## Step 7: Process Review Results (A2I Completion Lambda)

```python
def process_review_completion(review_output_s3_key: str) -> None:
    """
    Triggered by an S3 event when A2I writes the review output.

    Reads the reviewer's corrections, writes reviewed entities to DynamoDB,
    and calls StepFunctions.SendTaskSuccess to resume the execution.

    This Lambda must have low error rates. If SendTaskSuccess fails, the
    Step Functions execution stays suspended until the heartbeat timeout fires.
    Monitor this function's error rate and set a DLQ.
    """
    s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
    dynamodb = boto3.resource("dynamodb")
    stepfunctions = boto3.client("stepfunctions", config=BOTO3_RETRY_CONFIG)
    table = dynamodb.Table(ENTITIES_TABLE)

    # Load the A2I review output from S3.
    response = s3.get_object(Bucket=REVIEW_OUTPUT_BUCKET, Key=review_output_s3_key)
    review_data = json.loads(response["Body"].read().decode("utf-8"))

    # Extract metadata from the review input (passed through from Step 6).
    input_content = json.loads(review_data["inputContent"])
    task_token = input_content["task_token"]
    document_key = input_content["document_key"]
    entities_to_review = input_content["entities_to_review"]

    # A2I writes multiple answers if you configure multiple reviewers per task.
    # For a single-reviewer workflow, index [0] is the answer.
    answers = review_data.get("humanAnswers", [{}])[0]
    answer_content = answers.get("answerContent", {})

    reviewed_count = 0
    corrections_made = 0

    for entity_input in entities_to_review:
        entity_id = entity_input["id"]
        original_text = entity_input["vision_text"]

        # The reviewer's corrected text for this entity.
        # Key format matches the 'name' attribute in the crowd-input HTML template.
        corrected_text = answer_content.get(f"corrected_text_{entity_id}", original_text)
        was_corrected = corrected_text != original_text

        if was_corrected:
            corrections_made += 1

        table.put_item(
            Item={
                "pk": document_key,
                "sk": entity_id,
                "entity_text": corrected_text,
                "original_text": original_text,      # preserve for prompt example capture
                "category": entity_input["category"],
                "review_status": "human_reviewed",
                "was_corrected": was_corrected,
                "reviewer_id": answers.get("workerId", "unknown"),
                "reviewed_at": review_data.get("completionTime", datetime.now(timezone.utc).isoformat()),
            }
        )
        reviewed_count += 1

    print(
        f"[review_completion] Document: {document_key} "
        f"| Reviewed: {reviewed_count} | Corrections: {corrections_made}"
    )

    # Resume the Step Functions execution. This wakes up the workflow.
    stepfunctions.send_task_success(
        taskToken=task_token,
        output=json.dumps({
            "document_key": document_key,
            "reviewed_count": reviewed_count,
            "corrections_made": corrections_made,
        }),
    )
```

---

## Step 8: Merge Final Record and Capture Prompt Examples

```python
def assemble_final_record(document_key: str, execution_id: str, enhanced_image_key: str) -> dict:
    """
    Retrieve all entity records from DynamoDB (auto-accepted and human-reviewed),
    assemble the final extraction record, and capture corrected extractions as
    prompt improvement CANDIDATES.

    IMPORTANT: PHI cross-contamination risk:
    The prompt_examples captured here reference real patient document images
    (enhanced_image_key points to a photo of a real clinical note). These
    candidates MUST NOT be embedded directly in EXTRACTION_SYSTEM_PROMPT.
    Before any candidate is promoted to the active prompt library:
      1. The source image must be replaced with a synthetic de-identified
         equivalent that preserves handwriting characteristics but removes PHI.
      2. The candidate must pass _validate_example_is_synthetic() → True.
    Using a real patient image as a few-shot example sends that patient's PHI
    to Bedrock during every other patient's extraction call: a HIPAA disclosure.
    [EDITOR: review fix] Added de-identification requirement and _validate_example_is_synthetic()
    call. Previously the only note was "store with SSE-KMS". That addressed storage
    security but not the cross-patient contamination risk in the active prompt.
    """
    dynamodb = boto3.resource("dynamodb")
    s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
    entities_table = dynamodb.Table(ENTITIES_TABLE)
    completed_table = dynamodb.Table(COMPLETED_TABLE)

    # Query all entity records for this document.
    # In production, use a GSI or pagination for documents with many entities.
    response = entities_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(document_key)
    )
    all_records = response.get("Items", [])

    final_entities = []
    prompt_candidates = []  # renamed from prompt_examples to emphasize these need curation
    auto_accepted = 0
    human_reviewed = 0
    corrections = 0

    for record in all_records:
        entity = {
            "text": record.get("entity_text", ""),
            "normalized": record.get("normalized", record.get("entity_text", "")),
            "category": record.get("category", "OTHER"),
            "review_status": record.get("review_status", "unknown"),
        }
        final_entities.append(entity)

        status = record.get("review_status", "")
        if status in ("auto_accepted", "accepted_flagged"):
            auto_accepted += 1
        elif status == "human_reviewed":
            human_reviewed += 1
            if record.get("was_corrected", False):
                corrections += 1

                # Capture as a prompt improvement CANDIDATE.
                # This is NOT ready for the active prompt.
                # deidentified=False signals the curation workflow that this
                # example must be de-identified before promotion.
                # A prompt engineer must: replace enhanced_image_key with a
                # synthetic equivalent, then flip deidentified=True and run
                # _validate_example_is_synthetic() before adding to the prompt.
                candidate = {
                    "image_key": enhanced_image_key,   # PHI: real patient image, NOT for prompt
                    "original_text": record.get("original_text", ""),
                    "corrected_text": record.get("entity_text", ""),
                    "category": record.get("category", "OTHER"),
                    "document_key": document_key,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "deidentified": False,   # MUST be True before prompt library promotion
                }

                # Validate before capturing. At this stage, deidentified is always
                # False (just captured from a real document). This call will return
                # False and we still store the candidate. The validation gate fires
                # during the curation workflow when deidentified is flipped to True.
                # The call here documents the required check point.
                if _validate_example_is_synthetic(candidate):
                    # This branch is not expected during normal capture.
                    # If it fires, something set deidentified=True prematurely.
                    print(
                        f"[assemble] WARNING: candidate passed synthetic validation at capture time. "
                        f"Verify de-identification workflow for document {document_key}."
                    )

                prompt_candidates.append(candidate)

    # Write the final completed record to DynamoDB.
    completed_table.put_item(
        Item={
            "document_key": document_key,
            "execution_id": execution_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "entities": final_entities,
            "processing_summary": {
                "total_entities": len(all_records),
                "auto_accepted": auto_accepted,
                "human_reviewed": human_reviewed,
                "corrections": corrections,
            },
        }
    )

    # Write prompt improvement candidates to S3.
    # These are stored for curation review, NOT for direct prompt insertion.
    # The curation workflow must de-identify images before promotion.
    if prompt_candidates:
        partition = datetime.now(timezone.utc).strftime("%Y/%m/%d")
        candidate_key = f"candidates/{partition}/{uuid.uuid4()}.json"
        s3.put_object(
            Bucket=PROMPT_LIBRARY_BUCKET,
            Key=candidate_key,
            Body=json.dumps(prompt_candidates, indent=2).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )
        print(
            f"[assemble] Wrote {len(prompt_candidates)} prompt candidates to S3. "
            "These require de-identification before prompt library promotion."
        )

    print(
        f"[assemble] Final record written. "
        f"Total entities: {len(all_records)} "
        f"| Auto: {auto_accepted} | Reviewed: {human_reviewed} | Corrections: {corrections}"
    )

    return {
        "document_key": document_key,
        "total_entities": len(all_records),
        "entities": final_entities,
    }
```

---

## Full Pipeline

```python
def process_handwritten_note(
    document_s3_key: str,
    flow_definition_arn: str,
    execution_id: str,
    task_token: str,
) -> dict:
    """
    Full pipeline for handwritten clinical note digitization.

    In production, this logic is distributed across Step Functions states and
    Lambda functions. Here it's assembled as a single callable function
    to make the execution flow easy to trace.

    Args:
        document_s3_key:    S3 key of the intake image (in INTAKE_BUCKET)
        flow_definition_arn: A2I flow definition ARN for human review routing
        execution_id:       Step Functions execution ID for audit trail
        task_token:         Step Functions callback task token for A2I resume

    Returns:
        Summary dict from the final record assembly.
    """
    document_key = document_s3_key  # use S3 key as the DynamoDB partition key

    print(f"\n=== Processing: {document_key} ===")

    # Step 1: Pre-process image
    print("\n[Step 1] Pre-processing image...")
    enhanced_key = preprocess_image(document_s3_key)

    # Step 2: Textract quality signal
    print("\n[Step 2] Computing Textract quality signal...")
    quality = compute_quality_signal(enhanced_key)

    # Handle direct-to-review case (very low handwriting confidence).
    # start_human_review detects the empty tiered_entities and forces A2I creation
    # with a sentinel entity. The reviewer performs extraction from scratch.
    # [EDITOR: review fix] Previously returned "routed_to_human_review" while actually
    # calling SendTaskSuccess and bypassing A2I. Now start_human_review handles the
    # empty entity case and returns True (A2I started). Status reflects reality.
    if quality["model_tier"] == "DIRECT_REVIEW":
        print("\n[Step 2] Very low confidence. Routing directly to human review (full-page).")
        start_human_review(
            document_key=document_key,
            enhanced_image_key=enhanced_key,
            textract_ocr_text=quality["ocr_text"],
            tiered_entities={"high": [], "medium": [], "low": []},
            task_token=task_token,
            flow_definition_arn=flow_definition_arn,
        )
        return {"document_key": document_key, "status": "full_page_review_required"}

    # Step 3: Vision model extraction
    print(f"\n[Step 3] Vision extraction ({quality['model_tier']})...")
    vision_result = extract_with_vision(
        enhanced_image_key=enhanced_key,
        ocr_text=quality["ocr_text"],
        model_tier=quality["model_tier"],
    )

    # Handle vision parsing failure.
    # start_human_review detects empty tiered_entities and forces A2I creation.
    # [EDITOR: review fix] Same fix as DIRECT_REVIEW path above. Previously this
    # returned "routed_to_human_review" while SendTaskSuccess was called immediately,
    # leaving the document with no review and an empty entity record.
    if vision_result["parse_error"]:
        print("\n[Step 3] Vision parse error. Routing to human review (full-page).")
        start_human_review(
            document_key=document_key,
            enhanced_image_key=enhanced_key,
            textract_ocr_text=quality["ocr_text"],
            tiered_entities={"high": [], "medium": [], "low": []},
            task_token=task_token,
            flow_definition_arn=flow_definition_arn,
        )
        return {"document_key": document_key, "status": "full_page_review_required"}

    # Step 4: Composite scoring and tiering
    print("\n[Step 4] Composite scoring and tiering...")
    tiered = composite_score_and_tier(
        vision_result=vision_result,
        handwritten_words=quality["handwritten_words"],
    )

    # Step 5: Store auto-accepted entities
    print("\n[Step 5] Storing auto-accepted entities...")
    store_auto_accepted(document_key, tiered)

    # Step 6: Route low-confidence entities to A2I (or resume immediately)
    print("\n[Step 6] Routing low-confidence entities...")
    needs_review = start_human_review(
        document_key=document_key,
        enhanced_image_key=enhanced_key,
        textract_ocr_text=quality["ocr_text"],
        tiered_entities=tiered,
        task_token=task_token,
        flow_definition_arn=flow_definition_arn,
    )

    if needs_review:
        # Pipeline suspends here in production (Step Functions wait state).
        # Steps 7 and 8 run after reviewer submits via process_review_completion().
        print("\n[Step 6] Execution suspended pending A2I review.")
        return {"document_key": document_key, "status": "awaiting_review"}

    # If no review needed, proceed directly to final assembly.
    print("\n[Step 8] Assembling final record...")
    result = assemble_final_record(document_key, execution_id, enhanced_key)

    print(f"\n=== Complete: {document_key} ===\n")
    return result
```

---

## Gap to Production

This example demonstrates the patterns. Here is what stands between this code and something you'd deploy to process real clinical notes.

**Retry logic.** This example now includes `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` on all AWS clients. `adaptive` mode implements exponential backoff with jitter appropriate for throttling scenarios. That handles transient Bedrock `ThrottlingException` and `ServiceUnavailableException` automatically. What it does not handle: Bedrock TPM (tokens-per-minute) quota limits under sustained burst load. Monitor `bedrock:InvokeModel` throttle metrics in CloudWatch and file a service quota increase before go-live at healthcare volume. Also note: retry at the API call level (as done here), not the Lambda invocation level. Retrying the Lambda invocation after a review loop was already started would generate a new `task_token`, causing an A2I `HumanLoopName` collision.

**Lambda timeouts.** Lambda's default 3-second timeout will fail on the first Bedrock vision API call. Configure each function with a timeout that comfortably exceeds worst-case execution including retry backoff: `preprocess-image` 2 min; `compute-quality-signal` 2 min; vision extraction Lambda 10 min (Bedrock vision calls take 5-15 seconds normally; under throttling with adaptive retry, budget more); `composite-score-and-tier` 1 min; `merge-and-finalize` 2 min; `process-review-completion` 2 min. Set a heartbeat timeout on the A2I wait state in Step Functions (2 hours is a reasonable starting point) to surface stuck executions.

**PHI in error logs.** This example omits raw Bedrock response content from all log messages. The model may echo clinical content from the input image in its output; logging that to CloudWatch creates a PHI exposure. Log only structural metadata: response length, error type, model tier. In addition: configure Lambda CloudWatch log groups with KMS encryption. Lambda does not do this automatically. Any Lambda function in this pipeline that processes page images or model responses should have its log group encrypted.

**PHI cross-contamination in the prompt library.** The `prompt_candidates` written in Step 8 contain PHI (the `image_key` points to a real patient's clinical note). They must not be inserted into `EXTRACTION_SYSTEM_PROMPT` without de-identification. The curation workflow must: replace each candidate image with a synthetic de-identified equivalent, flip `deidentified=True`, and pass `_validate_example_is_synthetic()` before promotion. Treat prompt curation as a PHI-handling workflow: HIPAA training required, HIPAA-covered tooling only (not personal laptops or email), CloudTrail logging for prompt library S3 access.

**Idempotent writes.** `store_auto_accepted` now uses `ConditionExpression="attribute_not_exists(sk)"` to prevent duplicate entity records on Lambda retry. The `ConditionalCheckFailedException` is caught and treated as a no-op (item already exists from a prior attempt). This pattern matches Recipe 1.4's approach. Apply the same pattern to any other DynamoDB write function in this pipeline.

**A2I payload size.** `start_human_review` now checks the serialized `InputContent` size before calling `start_human_loop`. If it exceeds 90KB, the OCR text is truncated. For notes with very many low-confidence entities, consider batching entities across multiple review loops as an alternative to truncation.

**Structured logging.** Replace `print()` statements with structured JSON logging (`logging` module plus a JSON formatter, or `aws-lambda-powertools` Logger). Log document keys, processing times, model tier used, entity counts, and confidence distributions. CloudWatch metrics derived from structured logs let you alarm on unusual patterns: sudden drop in auto-accept rate, spike in A2I queue depth, unusual correction rate.

**Input validation.** Validate S3 object existence and content type before processing. Check image dimensions and file size before calling Bedrock. Reject obviously corrupt images early rather than letting them propagate to the API calls. An invalid image sent to Bedrock returns an error response; validate before sending.

**IAM least privilege.** Each Lambda function should have a specific role with exactly the permissions it needs. The extraction Lambda needs `bedrock:InvokeModel` and `s3:GetObject` on the enhanced bucket. The A2I completion Lambda needs `dynamodb:PutItem` on the entities table and `states:SendTaskSuccess`. Do not share roles across Lambda functions.

**VPC and VPC endpoints.** Lambda functions should run in a VPC with no NAT gateway path to the internet. Provision VPC endpoints for: Bedrock Runtime (`com.amazonaws.{region}.bedrock-runtime` (the Converse API endpoint, distinct from `com.amazonaws.{region}.bedrock`), Textract, S3 (gateway endpoint, free), DynamoDB (gateway endpoint, free), SageMaker API (for A2I), Step Functions, KMS, and CloudWatch Logs. When using cross-region inference profiles (`us.` prefix): your Lambda calls the `bedrock-runtime` endpoint in your region; AWS routes to backend regions internally. PHI does not traverse the public internet through this path.

**KMS CMK for all PHI storage.** Use a customer-managed KMS key (CMK) in the `put_object` calls: `SSEKMSKeyId=YOUR_KMS_KEY_ARN`. Apply the same CMK to DynamoDB tables and Lambda CloudWatch log groups. CMKs give you key rotation control, per-operation CloudTrail entries, and the ability to revoke access.

**Bedrock PHI handling.** Amazon Bedrock is a HIPAA-eligible service under the AWS BAA. Model inference is transient: AWS does not retain customer data sent to Bedrock for training or logging under the BAA. Confirm your BAA covers Bedrock before sending real PHI. The page images you send via the Converse API are processed in memory and not persisted by the service.

**DynamoDB Decimal requirement.** The code already handles this (see `store_auto_accepted`). boto3 does not automatically convert Python floats to DynamoDB Decimal, and passing a float raises `TypeError: Float types are not supported`. Always convert float values with `Decimal(str(value))` before writing.

**Image size normalization.** The pre-processing step normalizes to 1800px on the long edge. Verify this is sufficient for your document population. High-resolution clinical photographs can be 4000-6000px and consume 3-4x the Bedrock image tokens of a normalized scan. Monitor per-call token usage in CloudWatch and adjust the normalization target if costs spike.

**Prompt library management.** The `prompt_candidates` written in Step 8 are candidates, not final additions. Someone needs to review them periodically, de-identify the source images, validate with `_validate_example_is_synthetic()`, format passing examples as demonstrations in `EXTRACTION_SYSTEM_PROMPT`, and redeploy. Assign this task explicitly. If nobody owns it, the feedback loop closes. The de-identification step is non-negotiable before any example enters the production prompt.

**Testing without real PHI.** Use synthetic handwritten notes during development. The IAM Handwriting Database and similar public datasets provide realistic samples. Generate test cases with known ground-truth extractions to measure extraction accuracy against a fixed benchmark. Never use real patient data in non-production environments.

---

*← [Recipe 1.6 Main](chapter01.06-handwritten-notes-v3) · [Chapter 1 Index](chapter01-index)*
