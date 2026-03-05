# Recipe 1.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.6. It is meant to show how these concepts translate into working Python code using boto3. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire into a clinical records queue on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline in this recipe has a natural break in the middle. Steps 1 through 5 run synchronously: image preprocessing, OCR, clinical NLP, confidence tiering, and A2I task creation. Then the workflow suspends and waits while a human reviewer works through the flagged extractions. Steps 7 and 8 resume after that review completes. This file reflects that structure: two Lambda-style handler functions bracket the async gap, with a full pipeline function at the end that runs Steps 1 through 5 sequentially so you can trace the logic end-to-end in a single script.
>
> The new AWS SDK work in this recipe is the Amazon A2I integration: `start_human_loop()`, `describe_human_loop()`, and the Step Functions `send_task_success()` callback that resumes the workflow when a reviewer submits their corrections. The Textract and Comprehend Medical calls will be familiar from earlier recipes. The new part is the confidence tiering logic and the composite scoring model that combines OCR and NLP confidence into a single signal for routing decisions.

---

## Setup

You will need the AWS SDK for Python and a few image processing libraries for the preprocessing step:

```bash
pip install boto3 Pillow
```

For production-quality image deskewing, you will also want:

```bash
pip install deskew opencv-python-headless
```

The basic example below uses Pillow only. The deskew and OpenCV imports are noted as upgrades in the "Gap to Production" section.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `textract:AnalyzeDocument`
- `comprehendmedical:DetectEntitiesV2`
- `sagemaker:StartHumanLoop`
- `sagemaker:DescribeHumanLoop`
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `dynamodb:UpdateItem`
- `states:SendTaskSuccess`
- `states:SendTaskFailure`

The A2I API is accessed through the `sagemaker-a2i-runtime` service endpoint, not the main `sagemaker` endpoint. These are two different boto3 clients. The IAM action namespace is `sagemaker:StartHumanLoop` and `sagemaker:DescribeHumanLoop` regardless.

---

## Configuration and Constants

Everything that is really configuration rather than logic lives here. The confidence thresholds, bucket names, and table names belong in your version control history and your parameter store, not scattered through function bodies.

```python
import boto3
from boto3.dynamodb.conditions import Key  # for DynamoDB query expressions
import datetime
import io
import json
import uuid
from datetime import timezone
from decimal import Decimal  # DynamoDB requires Decimal for all numeric values

from PIL import Image, ImageOps, ImageFilter


# -----------------------------------------------------------------------
# Adaptive confidence thresholds
#
# These values reflect the fundamental difference between handwriting and
# printed text OCR. Handwriting sits in a lower confidence band overall:
# 85% from Textract on a handwritten word means something different (and
# more reliable) than 85% on a printed word. Printed text at 85% is
# a likely error. Handwriting at 85% is usually right.
#
# These are starting points, not universal truths. Calibrate them against
# your own document population after the first 200-300 processed notes.
# See the "Honest Take" section of Recipe 1.6 for how to do that.
# -----------------------------------------------------------------------
HIGH_CONFIDENCE_HANDWRITING   = 85.0   # auto-accept threshold for handwritten words
HIGH_CONFIDENCE_PRINTED       = 92.0   # auto-accept threshold for printed words
MEDIUM_CONFIDENCE_HANDWRITING = 60.0   # below this: human review required (handwriting)
MEDIUM_CONFIDENCE_PRINTED     = 75.0   # below this: human review required (print)

# -----------------------------------------------------------------------
# S3 bucket names (replace with your actual bucket names or env vars)
# -----------------------------------------------------------------------
INTAKE_BUCKET   = "notes-intake"       # where uploaded handwritten notes land
ENHANCED_BUCKET = "notes-enhanced"     # pre-processed images written here
REVIEW_BUCKET   = "notes-review-output" # A2I writes completed review results here
TRAINING_BUCKET = "notes-training-data" # labeled training pairs accumulate here

# -----------------------------------------------------------------------
# DynamoDB table names
# -----------------------------------------------------------------------
ENTITIES_TABLE   = "clinical-note-entities"    # per-entity records at each pipeline stage
COMPLETED_TABLE  = "completed-extractions"     # final assembled records

# -----------------------------------------------------------------------
# A2I flow definition ARN
# Configure this in the AWS console or via CloudFormation.
# This ARN identifies which workforce, task template, and review criteria
# will be used when a human loop is started.
# -----------------------------------------------------------------------
FLOW_DEFINITION_ARN = "arn:aws:sagemaker:us-east-1:123456789012:flow-definition/clinical-note-review"

# -----------------------------------------------------------------------
# Presigned URL expiry for the reviewer interface.
# 4 hours gives reviewers time to complete tasks without the image link
# expiring mid-session. Match this to your A2I task timeout configuration.
# -----------------------------------------------------------------------
PRESIGNED_URL_EXPIRY_SECONDS = 4 * 3600


# -----------------------------------------------------------------------
# AWS clients
# Creating these at module scope means they are reused across invocations
# inside a warm Lambda container, avoiding per-call connection overhead.
# -----------------------------------------------------------------------
textract_client   = boto3.client("textract")
comprehend_client = boto3.client("comprehendmedical")
s3_client         = boto3.client("s3")
dynamodb          = boto3.resource("dynamodb")
sfn_client        = boto3.client("stepfunctions")

# The A2I runtime client is separate from the SageMaker client.
# The service identifier is "sagemaker-a2i-runtime", not "sagemaker".
a2i_client = boto3.client("sagemaker-a2i-runtime")
```

---

## Step 1: Image Pre-Processing

Before sending anything to OCR, improve the image. This step sounds optional. It is not. Handwritten clinical notes arrive at every level of quality: faxed twice, photographed with a phone, scanned slightly crooked, pencil on thermal paper. Each artifact degrades OCR confidence in ways that push more extractions into the human review queue unnecessarily. Fixing the image first means more auto-accepted extractions, less reviewer load, and better data quality overall.

```python
def preprocess_image(bucket: str, source_key: str) -> str:
    """
    Retrieve a handwritten note image from S3, apply pre-processing, and
    save the enhanced version to the notes-enhanced bucket.

    The three operations here correspond directly to the three preprocessing
    steps in the Recipe 1.6 pseudocode:
      1. Deskew: correct slight rotations from scanning or photography
      2. Contrast enhancement: make faded ink and pencil legible
      3. Noise reduction: remove compression artifacts and paper grain

    The Pillow-based implementation here handles straightforward cases.
    For more reliable deskewing on mixed-orientation batches, upgrade to
    the deskew library (pip install deskew) or OpenCV. See "Gap to Production."

    Args:
        bucket:     S3 bucket containing the source image
        source_key: S3 object key for the original handwritten note

    Returns:
        The S3 key of the enhanced image in the notes-enhanced bucket.
    """
    # Retrieve the image bytes from S3.
    response    = s3_client.get_object(Bucket=bucket, Key=source_key)
    image_bytes = response["Body"].read()

    # Load into Pillow.
    image = Image.open(io.BytesIO(image_bytes)).convert("L")  # convert to grayscale

    # Step 1a: Deskew.
    # Pillow does not have native deskew support. The basic approach is to use
    # Pillow's getbbox() after threshold to estimate whether the image is rotated.
    # For production, replace this block with the deskew library or OpenCV's
    # minAreaRect approach on the binary image. Those give you the precise angle.
    #
    # Here we illustrate the intent: detect a skew angle and rotate to correct it.
    # The angle variable would come from your deskew library in a real deployment.
    #
    # from deskew import determine_skew
    # angle = determine_skew(image)
    # if angle is not None and abs(angle) > 0.5:
    #     image = image.rotate(angle, expand=True, fillcolor=255)
    #
    # Placeholder: no rotation applied in this basic example.
    # Remove the comment above and add the deskew import for a real deployment.

    # Step 1b: Enhance contrast.
    # ImageOps.autocontrast stretches the histogram so the darkest pixels in the
    # image become black and the lightest become white. The cutoff=1 parameter
    # ignores the top and bottom 1% of pixel values, which prevents a single
    # bright reflection or dark shadow from collapsing the contrast adjustment.
    # This reliably improves legibility of faded ink and light pencil marks.
    image = ImageOps.autocontrast(image, cutoff=1)

    # Step 1c: Reduce noise.
    # A median filter removes isolated pixel noise (scanner dust, compression
    # artifacts, paper grain) while preserving the edges of handwritten strokes.
    # Size=3 is conservative: enough to remove sensor noise without blurring
    # letter forms. Increase to 5 only for images with severe noise artifacts.
    image = image.filter(ImageFilter.MedianFilter(size=3))

    # Save the enhanced image to the notes-enhanced bucket.
    # A2I reviewers will see this image in their review interface.
    # Enhanced images are meaningfully easier for reviewers to read.
    enhanced_buffer = io.BytesIO()
    image.save(enhanced_buffer, format="JPEG", quality=95)
    enhanced_buffer.seek(0)

    # Preserve the original key structure under the new bucket.
    # notes-intake/2026/03/01/note-00291.jpg
    #   -> notes-enhanced/2026/03/01/note-00291.jpg
    enhanced_key = source_key  # same key, different bucket

    s3_client.put_object(
        Bucket=ENHANCED_BUCKET,
        Key=enhanced_key,
        Body=enhanced_buffer.getvalue(),
        ContentType="image/jpeg",
        # ServerSideEncryption and SSEKMSKeyId belong here in production.
        # See "Gap to Production" section.
    )

    print(f"  Pre-processing complete. Enhanced image at s3://{ENHANCED_BUCKET}/{enhanced_key}")
    return enhanced_key
```

---

## Step 2: Textract Handwriting OCR

The OCR call itself is a single API call. The work is in what you do with the response. The key post-processing step is separating HANDWRITING and PRINTED word populations: they live in different confidence bands, and they need different thresholds downstream.

```python
def extract_text_with_confidence(enhanced_key: str) -> dict:
    """
    Run Textract AnalyzeDocument on the pre-processed image and separate
    the response into HANDWRITING and PRINTED word populations.

    Textract's AnalyzeDocument API handles handwriting natively. No special
    feature flag or mode is needed. The `TextType` field on each WORD block
    tells you whether it was printed or handwritten, so mixed documents
    (printed form with handwritten fill-ins) are handled in a single call.

    FORMS is included in FeatureTypes to extract structured key-value pairs
    from any form fields on the page. The bounding box on each word block is
    preserved: it tells the A2I reviewer interface exactly where on the image
    each extracted word appears.

    Args:
        enhanced_key: S3 key of the pre-processed image in ENHANCED_BUCKET

    Returns:
        A dict containing the full text, separated word lists, and confidence
        summary metrics for monitoring and threshold calibration.
    """
    response = textract_client.analyze_document(
        Document={
            "S3Object": {
                "Bucket": ENHANCED_BUCKET,
                "Name":   enhanced_key,
            }
        },
        # FORMS: extract key-value pairs from any form structure on the page.
        # Handwriting recognition is native; it does not require a separate flag.
        FeatureTypes=["FORMS"],
    )

    handwritten_words = []
    printed_words     = []

    for block in response["Blocks"]:
        if block["BlockType"] != "WORD":
            continue

        word = {
            "text":         block["Text"],
            "confidence":   block["Confidence"],
            "text_type":    block.get("TextType", "PRINTED"),  # PRINTED or HANDWRITING
            "bounding_box": block["Geometry"]["BoundingBox"],
            # BoundingBox fields: Left, Top, Width, Height (all 0.0-1.0, relative to image)
        }

        if block.get("TextType") == "HANDWRITING":
            handwritten_words.append(word)
        else:
            printed_words.append(word)

    # Reconstruct the full document text from LINE blocks.
    # LINE blocks are Textract's assembly of WORD blocks into logical text lines.
    # Using LINE gives you cleaner concatenation than joining WORD blocks manually,
    # because Textract's line detection handles multi-word clinical abbreviations
    # (q.i.d., b.i.d., PRN) and hyphenated values better than a naive join.
    lines     = [b["Text"] for b in response["Blocks"] if b["BlockType"] == "LINE"]
    full_text = "\n".join(lines)

    # Compute confidence summaries for monitoring dashboards and threshold calibration.
    # These averages are what you track over time to see whether confidence is
    # trending up (model improving on your document population) or down (data drift).
    avg_hw_confidence = (
        sum(w["confidence"] for w in handwritten_words) / len(handwritten_words)
        if handwritten_words else 0.0
    )
    avg_pt_confidence = (
        sum(w["confidence"] for w in printed_words) / len(printed_words)
        if printed_words else 0.0
    )

    print(
        f"  OCR complete. {len(handwritten_words)} handwritten words "
        f"(avg confidence: {avg_hw_confidence:.1f}), "
        f"{len(printed_words)} printed words "
        f"(avg confidence: {avg_pt_confidence:.1f})."
    )

    return {
        "full_text":                full_text,
        "handwritten_words":        handwritten_words,
        "printed_words":            printed_words,
        "avg_handwriting_confidence": avg_hw_confidence,
        "avg_printed_confidence":     avg_pt_confidence,
    }
```

---

## Step 3: Clinical Entity Extraction with Composite Confidence

With OCR text in hand, Comprehend Medical extracts structured clinical entities: medications, diagnoses, dosages, frequencies, lab values. The critical addition here is the composite confidence score that combines OCR confidence with NLP confidence into a single routing signal.

The rule is simple: take the minimum of the two. An entity is only as trustworthy as its weakest link. A medication name the OCR struggled to read but the NLP identified confidently is still a risky extraction. A clearly scanned word that the NLP is uncertain about is equally suspect. Composite confidence catches both failure modes with a single threshold comparison downstream.

```python
def find_ocr_confidence_for_entity(
    entity_text: str,
    handwritten_words: list,
) -> tuple[float, bool]:
    """
    Find the Textract confidence for the words underlying a Comprehend Medical entity.

    An entity might span multiple words ("Type 2 diabetes mellitus"). For
    multi-word entities, we want the minimum confidence among all constituent
    words: if any word in a medication name was read poorly, the whole name
    is suspect.

    We check only against handwritten_words. If no handwritten words match the
    entity text, the entity came from a printed region of the page and gets a
    high default confidence (printed text is reliably read).

    Args:
        entity_text:       the text string of the clinical entity
        handwritten_words: list of handwritten word dicts from Step 2

    Returns:
        A tuple of (ocr_confidence, is_handwritten).
        ocr_confidence: min confidence among matching words, or 90.0 for printed.
        is_handwritten: True if any matching word was HANDWRITING type.
    """
    entity_lower = entity_text.lower()

    # Find handwritten words whose text appears in the entity string.
    # Substring matching handles partial word matches (e.g., "Metformin" in
    # "Metformin 500mg"). This is approximate but practical for clinical text.
    matching_words = [
        w for w in handwritten_words
        if w["text"].lower() in entity_lower
    ]

    if not matching_words:
        # No handwritten word matched: entity is from printed text.
        # Printed text has a higher confidence baseline; use a safe default.
        return 90.0, False

    ocr_confidence = min(w["confidence"] for w in matching_words)
    return ocr_confidence, True


def extract_clinical_entities(ocr_result: dict) -> list:
    """
    Extract clinical entities from OCR text and compute composite confidence scores.

    Calls Comprehend Medical DetectEntitiesV2 on the full text assembled in
    Step 2. For each returned entity, cross-references the NLP confidence
    with the OCR confidence of the underlying words to produce a composite score.

    Composite confidence = min(ocr_confidence, nlp_confidence)

    This is the signal the confidence tiering step uses to route extractions.
    Using the minimum instead of an average ensures that a weak link in either
    direction (bad OCR or uncertain NLP) results in a conservative routing
    decision. Clinical entity routing errors are expensive; conservative is right.

    Args:
        ocr_result: the dict returned by extract_text_with_confidence (Step 2)

    Returns:
        A list of entity dicts, each with composite confidence and metadata.
    """
    full_text         = ocr_result["full_text"]
    handwritten_words = ocr_result["handwritten_words"]

    if not full_text.strip():
        return []

    # DetectEntitiesV2 accepts up to 20,000 characters per request.
    # Clip well below that to avoid silent truncation on long notes.
    # In production, split at sentence boundaries for notes exceeding this limit.
    text_for_nlp = full_text[:19500]

    response = comprehend_client.detect_entities_v2(Text=text_for_nlp)

    enriched_entities = []

    for entity in response["Entities"]:
        entity_text    = entity["Text"]
        # Comprehend Medical returns Score as 0.0-1.0; scale to 0-100 to
        # match Textract's confidence range for consistent threshold comparisons.
        nlp_confidence = entity["Score"] * 100.0

        ocr_confidence, is_handwritten = find_ocr_confidence_for_entity(
            entity_text, handwritten_words
        )

        # Composite confidence: the chain is only as strong as its weakest link.
        composite_confidence = min(ocr_confidence, nlp_confidence)

        enriched_entities.append({
            "text":                entity_text,
            "category":            entity["Category"],   # MEDICATION, MEDICAL_CONDITION, etc.
            "entity_type":         entity["Type"],       # GENERIC_NAME, DX_NAME, etc.
            "traits":              [t["Name"] for t in entity.get("Traits", [])],
            "nlp_confidence":      round(nlp_confidence, 1),
            "ocr_confidence":      round(ocr_confidence, 1),
            "composite_confidence": round(composite_confidence, 1),
            "is_handwritten":      is_handwritten,
        })

    print(
        f"  Clinical NLP complete. {len(enriched_entities)} entities extracted. "
        f"Composite confidence range: "
        f"{min(e['composite_confidence'] for e in enriched_entities):.1f} - "
        f"{max(e['composite_confidence'] for e in enriched_entities):.1f}"
        if enriched_entities else "  Clinical NLP complete. No entities found."
    )

    return enriched_entities
```

---

## Step 4: Confidence Tiering and Routing

Every entity gets assigned to exactly one of three buckets. The routing logic is a straight threshold comparison, but the thresholds are adaptive: handwritten entities go against the handwriting thresholds, printed entities against the printed thresholds. This is a subtle but important distinction that the pseudocode describes carefully, and it's worth understanding why before you implement it.

A handwritten medication name at 82% composite confidence is likely correct. A printed field label at 82% composite confidence has a meaningful chance of error. Applying the same threshold to both would either over-route reliable handwritten extractions to human review, or under-route risky printed extractions. Adaptive thresholds let each population be evaluated against its own accuracy baseline.

```python
def tier_entities(enriched_entities: list) -> dict:
    """
    Assign each clinical entity to a confidence tier using adaptive thresholds.

    Three tiers:
    - high:   composite confidence above the high threshold for this text type.
              Automatically accepted. No human review needed.
    - medium: composite confidence between medium and high thresholds.
              Accepted and stored, but flagged for downstream verification.
              Does not block the workflow.
    - low:    composite confidence below the medium threshold.
              Human review required before this value is used clinically.

    Thresholds are selected based on whether the entity came from handwritten
    or printed text. Handwriting and print have different accuracy baselines
    and need different confidence cutoffs. See the constants section for
    the starting threshold values and the calibration guidance in Recipe 1.6.

    Args:
        enriched_entities: list of entity dicts from extract_clinical_entities (Step 3)

    Returns:
        A dict with keys 'high', 'medium', 'low', each containing a list of entities.
    """
    high_confidence   = []
    medium_confidence = []
    low_confidence    = []

    for entity in enriched_entities:
        score = entity["composite_confidence"]

        # Select the appropriate threshold pair for this entity's text type.
        if entity["is_handwritten"]:
            high_threshold   = HIGH_CONFIDENCE_HANDWRITING    # 85.0
            medium_threshold = MEDIUM_CONFIDENCE_HANDWRITING  # 60.0
        else:
            high_threshold   = HIGH_CONFIDENCE_PRINTED        # 92.0
            medium_threshold = MEDIUM_CONFIDENCE_PRINTED      # 75.0

        if score >= high_threshold:
            high_confidence.append(entity)
        elif score >= medium_threshold:
            medium_confidence.append(entity)
        else:
            low_confidence.append(entity)

    print(
        f"  Confidence tiering: {len(high_confidence)} auto-accept, "
        f"{len(medium_confidence)} accept-with-flag, "
        f"{len(low_confidence)} human review required."
    )

    return {
        "high":   high_confidence,
        "medium": medium_confidence,
        "low":    low_confidence,
    }
```

---

## Step 5: Store Auto-Accepted Entities and Start Human Review

High and medium confidence entities are written to DynamoDB immediately. They are available for downstream processing now. Low confidence entities are bundled into an A2I human loop. The Step Functions workflow suspends at this step using a task token: a unique callback identifier passed to A2I that A2I will return when the review completes.

If there are no low-confidence entities, the task token is sent back immediately and the workflow continues without any human-paced wait.

```python
def generate_entity_id() -> str:
    """Generate a unique sortable ID for a DynamoDB entity record."""
    return str(uuid.uuid4())


def route_entities(
    document_key: str,
    tiered_entities: dict,
    task_token: str,
) -> None:
    """
    Write auto-accepted entities to DynamoDB and start an A2I human loop
    for low-confidence entities.

    High and medium confidence entities are stored immediately with their
    tier status. Medium entities carry a review_status of 'accepted_flagged'
    to signal that downstream systems should treat them with some skepticism.

    Low confidence entities are bundled into an A2I StartHumanLoop call.
    The task_token is embedded in the A2I input payload. When the reviewer
    submits their corrections, a Lambda reads that token from the A2I output
    and calls StepFunctions.SendTaskSuccess to resume the workflow.

    If there are no low-confidence entities, SendTaskSuccess is called directly
    so the Step Functions execution does not suspend unnecessarily.

    Args:
        document_key:     S3 key of the source note (used as DynamoDB partition key)
        tiered_entities:  dict of {high, medium, low} entity lists from Step 4
        task_token:       Step Functions task token for the wait-for-callback state
    """
    entities_table = dynamodb.Table(ENTITIES_TABLE)

    # Write auto-accepted entities (high and medium confidence) to DynamoDB.
    for entity in tiered_entities["high"] + tiered_entities["medium"]:
        review_status = (
            "auto_accepted"
            if entity in tiered_entities["high"]
            else "accepted_flagged"
        )
        entities_table.put_item(Item={
            "pk":              document_key,
            "sk":              generate_entity_id(),
            "entity_text":     entity["text"],
            "category":        entity["category"],
            "entity_type":     entity["entity_type"],
            "traits":          entity["traits"],
            "confidence":      Decimal(str(entity["composite_confidence"])),
            "ocr_confidence":  Decimal(str(entity["ocr_confidence"])),
            "nlp_confidence":  Decimal(str(entity["nlp_confidence"])),
            "review_status":   review_status,
            "is_handwritten":  entity["is_handwritten"],
            "created_at":      datetime.datetime.now(timezone.utc).isoformat(),
        })

    # If there are no low-confidence entities, no human review is needed.
    # Return the task token immediately so Step Functions continues.
    if not tiered_entities["low"]:
        print("  No low-confidence entities. Sending task success immediately.")
        sfn_client.send_task_success(
            taskToken=task_token,
            output=json.dumps({
                "document_key":   document_key,
                "reviewed_count": 0,
                "corrections":    0,
            }),
        )
        return

    # Generate a presigned URL so the A2I reviewer interface can display
    # the original document image without requiring direct S3 access.
    # The expiry should be long enough for the review to complete;
    # 4 hours is a reasonable starting point for typical queue depths.
    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": ENHANCED_BUCKET, "Key": document_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
    )

    # Bundle the low-confidence entities into the A2I task input.
    # The bounding_box is included so the reviewer interface can highlight
    # the relevant region on the document image for each entity being reviewed.
    entities_for_review = []
    for entity in tiered_entities["low"]:
        entity_id = generate_entity_id()

        # Write a placeholder record to DynamoDB so the merge step in Step 8
        # can find all entity IDs for this document, including those pending review.
        entities_table.put_item(Item={
            "pk":              document_key,
            "sk":              entity_id,
            "entity_text":     entity["text"],   # will be updated after review
            "original_ocr":    entity["text"],   # preserve original for training data
            "category":        entity["category"],
            "entity_type":     entity["entity_type"],
            "traits":          entity["traits"],
            "confidence":      Decimal(str(entity["composite_confidence"])),
            "ocr_confidence":  Decimal(str(entity["ocr_confidence"])),
            "nlp_confidence":  Decimal(str(entity["nlp_confidence"])),
            "review_status":   "pending_review",
            "is_handwritten":  entity["is_handwritten"],
            "created_at":      datetime.datetime.now(timezone.utc).isoformat(),
        })

        entities_for_review.append({
            "id":             entity_id,
            "text":           entity["text"],
            "category":       entity["category"],
            "ocr_confidence": round(entity["ocr_confidence"], 1),
            "nlp_confidence": round(entity["nlp_confidence"], 1),
            # bounding_box is passed through to the task template, where it
            # can be used to draw a highlight box over the relevant word.
            "bounding_box":   entity.get("bounding_box", {}),
        })

    # The A2I task input is the payload that appears in the reviewer's interface.
    # The task_token is embedded here so the completion Lambda can resume the
    # Step Functions execution when the review is submitted.
    review_task_input = {
        "document_key":       document_key,
        "document_image_uri": presigned_url,
        "task_token":         task_token,
        "entities_to_review": entities_for_review,
    }

    # Start the A2I human loop.
    # HumanLoopName must be unique per loop. Using a hash of the document key
    # makes it deterministic and idempotent for the same document.
    import hashlib
    loop_name = "note-review-" + hashlib.md5(document_key.encode()).hexdigest()[:16]

    a2i_client.start_human_loop(
        HumanLoopName=loop_name,
        FlowDefinitionArn=FLOW_DEFINITION_ARN,
        HumanLoopInput={
            # InputContent must be a JSON string, not a dict.
            "InputContent": json.dumps(review_task_input)
        },
    )

    print(
        f"  A2I human loop started: {loop_name}. "
        f"{len(tiered_entities['low'])} entities sent for review. "
        f"Step Functions workflow is now suspended."
    )
    # The Step Functions execution stays paused here until the review Lambda
    # calls sfn_client.send_task_success() with task_token. See Step 7.
```

---

## Step 6: The Reviewer Interface

The worker task template is defined once in the AWS console or via CloudFormation as part of the A2I flow definition. It renders in the A2I worker portal. The template is HTML with Liquid-style template variables that A2I fills in from the `InputContent` passed in Step 5.

The template is included in the main Recipe 1.6 walkthrough. The Python side of this step is just the `start_human_loop` call in Step 5. There is no additional Python code here. The template itself is reproduced below for reference so you can see how the `entities_to_review` list from Step 5 maps to the reviewer's view.

```html
<!-- Reference: A2I Worker Task Template for Recipe 1.6 -->
<!-- Deploy this in the A2I console as the worker task template for your flow definition. -->
<!-- This is the same template shown in the main recipe pseudocode. -->

<script src="https://assets.crowd.aws/crowd-html-elements.js"></script>

<crowd-form>
  <h2>Handwritten Clinical Note Review</h2>
  <p>
    The system identified the following extractions as uncertain.
    Compare each one against the document image and correct any errors.
    Leave the text field unchanged if the OCR is correct.
  </p>

  <div style="border: 1px solid #ccc; padding: 8px; margin-bottom: 20px;">
    <img src="{{ task.input.document_image_uri }}"
         style="max-width: 100%; display: block;" />
  </div>

  {% for entity in task.input.entities_to_review %}
  <div style="border: 1px solid #ddd; border-radius: 4px;
              padding: 12px; margin-bottom: 12px; background: #fafafa;">
    <p><strong>Category:</strong> {{ entity.category }}</p>
    <p>
      <strong>OCR extracted:</strong>
      <code>{{ entity.text | escape }}</code>
      &nbsp;&nbsp;
      <span style="color: #888; font-size: 0.9em;">
        (OCR confidence: {{ entity.ocr_confidence }}%,
         NLP confidence: {{ entity.nlp_confidence }}%)
      </span>
    </p>
    <crowd-input
      name="corrected_text_{{ entity.id }}"
      label="Correct text (edit if OCR is wrong)"
      value="{{ entity.text | escape }}"
      required>
    </crowd-input>
  </div>
  {% endfor %}

  <crowd-text-area
    name="reviewer_notes"
    label="Notes for QA team (optional)"
    rows="2"
    placeholder="Observations about document quality, unusual abbreviations, etc.">
  </crowd-text-area>
</crowd-form>
```

---

## Step 7: Process Review Results and Resume Workflow

This function is triggered by an S3 event when A2I writes the completed review output. It reads the reviewer's corrections, updates the DynamoDB entity records, and sends the task success to Step Functions to resume the workflow.

The task token is the critical link. Calling `send_task_success()` with the original token is what wakes up the Step Functions execution. If this Lambda fails or is misconfigured, the Step Functions execution stays suspended indefinitely. Monitor this function's error rate and set a heartbeat timeout on the wait state so stuck executions surface as alarms rather than silent delays.

```python
def process_review_completion(review_output_bucket: str, review_output_key: str) -> dict:
    """
    Process a completed A2I review and resume the Step Functions workflow.

    Triggered by the S3 event when A2I writes review output to REVIEW_BUCKET.
    Reads the reviewer's corrections from the A2I output JSON, updates the
    DynamoDB entity records with the corrected text, then calls
    StepFunctions.SendTaskSuccess with the task token to resume the workflow.

    A2I writes one JSON file per completed human loop. The file structure is:
    {
      "flowDefinitionArn": "...",
      "humanLoopName":     "...",
      "inputContent": {
        "document_key":       "...",
        "task_token":         "...",
        "entities_to_review": [{"id": "...", "text": "...", ...}, ...]
      },
      "humanAnswers": [
        {
          "answerContent": {
            "corrected_text_<entity_id>": "<reviewer's text>",
            ...
            "reviewer_notes": "..."
          },
          "submissionTime": "...",
          "workerId":       "..."
        }
      ]
    }

    Args:
        review_output_bucket: S3 bucket where A2I wrote the review output
        review_output_key:    S3 key of the A2I review output JSON file

    Returns:
        A summary dict for logging and Step Functions output.
    """
    # Load the A2I review output from S3.
    response    = s3_client.get_object(Bucket=review_output_bucket, Key=review_output_key)
    review_data = json.loads(response["Body"].read())

    # Pull the task token and document key from the embedded input content.
    input_content = review_data["inputContent"]
    task_token    = input_content["task_token"]
    document_key  = input_content["document_key"]

    # The first (and typically only) human answer contains the reviewer's responses.
    # A2I flow definitions can require multiple reviewers; this example expects one.
    # For consensus-based review (multiple reviewers, majority vote), you would
    # iterate over all humanAnswers and reconcile. See "Gap to Production."
    answer         = review_data["humanAnswers"][0]
    answer_content = answer["answerContent"]
    worker_id      = answer.get("workerId", "unknown")
    reviewed_at    = answer.get("submissionTime", datetime.datetime.now(timezone.utc).isoformat())

    entities_table = dynamodb.Table(ENTITIES_TABLE)
    corrections_made = 0
    reviewed_count   = 0

    for entity_input in input_content["entities_to_review"]:
        entity_id     = entity_input["id"]
        original_text = entity_input["text"]

        # Retrieve the reviewer's input for this specific entity.
        # The crowd-input element in the task template submits with the key
        # "corrected_text_<entity_id>". If the reviewer left it unchanged,
        # the value equals the original OCR text.
        answer_key     = f"corrected_text_{entity_id}"
        corrected_text = answer_content.get(answer_key, original_text).strip()
        was_corrected  = corrected_text != original_text

        if was_corrected:
            corrections_made += 1

        reviewed_count += 1

        # Update the DynamoDB entity record with the reviewer's corrected text.
        # The original_ocr field was set in Step 5 and is preserved here
        # so the training data capture in Step 8 has both the OCR output
        # and the ground-truth correction.
        entities_table.update_item(
            Key={
                "pk": document_key,
                "sk": entity_id,
            },
            UpdateExpression=(
                "SET entity_text   = :corrected, "
                "    review_status = :status, "
                "    was_corrected = :corrected_flag, "
                "    reviewer_id   = :reviewer, "
                "    reviewed_at   = :reviewed_at"
            ),
            ExpressionAttributeValues={
                ":corrected":      corrected_text,
                ":status":         "human_reviewed",
                ":corrected_flag": was_corrected,
                ":reviewer":       worker_id,   # A2I worker IDs are anonymized by default
                ":reviewed_at":    reviewed_at,
            },
        )

    # Resume the Step Functions execution.
    # This is the action that wakes up the workflow from the wait state it
    # entered when start_human_loop was called in Step 5.
    summary = {
        "document_key":   document_key,
        "reviewed_count": reviewed_count,
        "corrections":    corrections_made,
    }

    sfn_client.send_task_success(
        taskToken=task_token,
        output=json.dumps(summary),
    )

    print(
        f"  Review complete for {document_key}. "
        f"{reviewed_count} entities reviewed, {corrections_made} corrections. "
        f"Step Functions workflow resumed."
    )

    return summary
```

---

## Step 8: Assemble the Final Record and Capture Training Data

With all entities in DynamoDB (auto-accepted from Step 5 and human-reviewed from Step 7), this step assembles the complete extraction record and writes it to the completed-extractions table. Every reviewed extraction is also written to the training data bucket as a labeled example.

Capturing the training data at this point costs essentially nothing: the reviewed records are already in DynamoDB. The alternative is reconstructing them later from logs, which is possible but tedious. Capture it now.

```python
def assemble_final_record(document_key: str, execution_id: str) -> dict:
    """
    Query all entity records for a document and assemble the final authoritative
    extraction record.

    Queries DynamoDB for every entity associated with this document key,
    regardless of review status. Auto-accepted and human-reviewed entities
    are merged into a single final record. Reviewed corrections replace the
    original OCR text. Training data pairs (original OCR vs. corrected text)
    are written to S3 for future model fine-tuning.

    Args:
        document_key:  S3 key of the source note (partition key in DynamoDB)
        execution_id:  Step Functions execution ARN for audit trail linkage

    Returns:
        The assembled final record dict (also written to DynamoDB).
    """
    entities_table   = dynamodb.Table(ENTITIES_TABLE)
    completed_table  = dynamodb.Table(COMPLETED_TABLE)

    # Query all entity records for this document.
    # In production, add a GSI on pk to avoid a full table scan.
    # This Query uses the partition key directly, which is efficient.
    response    = entities_table.query(
        KeyConditionExpression=Key("pk").eq(document_key)
    )
    all_records = response["Items"]

    final_entities  = []
    training_pairs  = []
    auto_accepted   = 0
    human_reviewed  = 0
    corrections     = 0

    for record in all_records:
        # Skip any entities still in pending_review status.
        # In production this should not happen if the workflow is correctly
        # sequenced: Step 8 runs only after the A2I callback in Step 7.
        # Guard anyway to avoid storing incomplete records.
        if record.get("review_status") == "pending_review":
            print(f"  WARNING: entity {record['sk']} still pending. Skipping.")
            continue

        # Build the final entity for the completed record.
        # Use entity_text, which holds the corrected text for reviewed entities
        # and the original OCR text for auto-accepted ones.
        final_entities.append({
            "text":          record["entity_text"],
            "category":      record.get("category", ""),
            "entity_type":   record.get("entity_type", ""),
            "traits":        record.get("traits", []),
            "review_status": record.get("review_status", ""),
            "confidence":    record.get("confidence", Decimal("0")),  # keep as Decimal for DynamoDB
        })

        # Tally by review path.
        if record["review_status"] in ("auto_accepted", "accepted_flagged"):
            auto_accepted += 1
        elif record["review_status"] == "human_reviewed":
            human_reviewed += 1
            if record.get("was_corrected"):
                corrections += 1

            # Capture this reviewed pair as a training data example.
            # Every correction teaches the model where it went wrong.
            # Every confirmation teaches it where it was right.
            # Both are valuable; both are captured here.
            training_pairs.append({
                "original_ocr":   record.get("original_ocr", record["entity_text"]),
                "corrected_text": record["entity_text"],
                "category":       record.get("category", ""),
                "was_correction": record.get("was_corrected", False),
                "document_key":   document_key,
                "timestamp":      datetime.datetime.now(timezone.utc).isoformat(),
            })

    # Write the final authoritative extraction record to DynamoDB.
    # This is the record downstream systems consume. It is the output of
    # the pipeline and the source of truth for this document's extractions.
    final_record = {
        "document_key": document_key,
        "execution_id": execution_id,
        "completed_at": datetime.datetime.now(timezone.utc).isoformat(),
        "entities":     final_entities,
        "processing_summary": {
            "total_entities": len(all_records),
            "auto_accepted":  auto_accepted,
            "human_reviewed": human_reviewed,
            "corrections":    corrections,
        },
    }

    # Conditional write: prevent overwriting a record that already exists.
    # S3 events are at-least-once, so this Lambda can fire twice for the same
    # document. The conditional expression makes the write idempotent.
    try:
        completed_table.put_item(
            Item=final_record,
            ConditionExpression="attribute_not_exists(document_key)",
        )
        print(f"  Final record written for {document_key}.")
    except completed_table.meta.client.exceptions.ConditionalCheckFailedException:
        print(f"  Record for {document_key} already exists. Skipping duplicate write.")

    # Write training pairs to S3 for future model fine-tuning.
    # Partitioned by date for efficient batch access during training jobs.
    # If no entities were reviewed (all auto-accepted), training_pairs is empty
    # and we skip the S3 write.
    if training_pairs:
        date_partition = datetime.datetime.now(timezone.utc).strftime("%Y/%m/%d")
        training_key   = f"training-data/{date_partition}/{uuid.uuid4()}.json"

        s3_client.put_object(
            Bucket=TRAINING_BUCKET,
            Key=training_key,
            Body=json.dumps(training_pairs, indent=2),
            ContentType="application/json",
            # SSEKMSKeyId should be set in production. See "Gap to Production."
        )
        print(
            f"  {len(training_pairs)} training pairs written to "
            f"s3://{TRAINING_BUCKET}/{training_key}"
        )

    print(
        f"  Assembly complete. total={len(all_records)}, "
        f"auto_accepted={auto_accepted}, "
        f"human_reviewed={human_reviewed}, "
        f"corrections={corrections}."
    )

    return final_record
```

---

## Putting It All Together

The full pipeline in one callable function. This is the sequential, single-process version for development and learning. In production, Steps 1 through 5 run inside a Step Functions Standard Workflow. Steps 7 and 8 run in separate Lambda functions triggered by the A2I completion event and the Step Functions callback respectively.

This version simulates the async A2I step by polling `describe_human_loop()` until the review completes. In production, you replace that polling loop with the event-driven callback pattern described above.

```python
def digitize_handwritten_note(
    bucket: str,
    image_key: str,
    task_token: str = "dev-simulation-token",
) -> dict:
    """
    Run the full handwritten clinical note digitization pipeline for one image.

    Covers all eight steps from the Recipe 1.6 pseudocode:
      1. Pre-process the image (deskew, contrast, noise reduction)
      2. Textract OCR (separate HANDWRITING and PRINTED word populations)
      3. Comprehend Medical entity extraction with composite confidence scoring
      4. Confidence tiering (adaptive thresholds by text type)
      5. Store auto-accepted entities and start A2I human review
      6. (A2I task template renders in the reviewer portal; no Python here)
      7. Process review results and resume Step Functions workflow
      8. Assemble the final record and capture training data

    In production:
    - Steps 1-5 run as the first half of a Step Functions Standard Workflow.
    - The workflow suspends at Step 5 waiting for the A2I callback.
    - Step 7 runs in a Lambda triggered by the S3 event when A2I writes output.
    - Step 8 runs as the final state in the Step Functions workflow.

    This function runs all eight steps sequentially and polls A2I for the
    review result rather than waiting for an S3 event. Use it to trace
    the full pipeline end-to-end in a development environment.

    Args:
        bucket:      S3 bucket containing the source handwritten note image
        image_key:   S3 object key of the source image
        task_token:  Step Functions task token (use a placeholder for dev runs)

    Returns:
        The final assembled extraction record.
    """
    import time

    print(f"\nStep 1: Pre-processing image s3://{bucket}/{image_key}")
    enhanced_key = preprocess_image(bucket, image_key)

    print("\nStep 2: Running Textract handwriting OCR...")
    ocr_result = extract_text_with_confidence(enhanced_key)

    print("\nStep 3: Extracting clinical entities with composite confidence scoring...")
    enriched_entities = extract_clinical_entities(ocr_result)

    if not enriched_entities:
        print("  No clinical entities found. Pipeline complete with empty record.")
        return {"document_key": image_key, "entities": [], "processing_summary": {}}

    print("\nStep 4: Tiering entities by confidence...")
    tiered = tier_entities(enriched_entities)

    print("\nStep 5: Storing auto-accepted entities and starting A2I human review...")
    route_entities(image_key, tiered, task_token)

    # In production, the Step Functions execution is now suspended and
    # execution continues in Step 7 when A2I calls the resume Lambda.
    #
    # In this development script, we poll describe_human_loop() until the
    # reviewer submits their corrections, then simulate the Step 7 Lambda
    # by calling process_review_completion directly.
    #
    # Note: this polling approach is only appropriate for a development script.
    # Running it in production would hold a Lambda open for the entire review
    # duration, which can be hours. Use event-driven callbacks in production.

    if tiered["low"]:
        import hashlib
        loop_name = "note-review-" + hashlib.md5(image_key.encode()).hexdigest()[:16]
        print(
            f"\nStep 6: Waiting for reviewer to complete the A2I task '{loop_name}'..."
        )

        # Poll until the human loop reaches a terminal status.
        max_polls     = 120     # 10 minutes at 5-second intervals
        poll_interval = 5
        loop_status   = "IN_PROGRESS"
        polls         = 0

        while loop_status == "IN_PROGRESS" and polls < max_polls:
            polls    += 1
            response  = a2i_client.describe_human_loop(HumanLoopName=loop_name)
            loop_status = response["HumanLoopStatus"]

            if loop_status == "IN_PROGRESS":
                print(f"  Review in progress (poll {polls}/{max_polls})...")
                time.sleep(poll_interval)
            elif loop_status == "COMPLETED":
                print(f"  Review complete.")
            else:
                # FAILED or STOPPED
                raise RuntimeError(f"A2I human loop ended with status: {loop_status}")

        if loop_status != "COMPLETED":
            raise TimeoutError(
                f"A2I review did not complete within "
                f"{max_polls * poll_interval} seconds."
            )

        # Find the review output in S3.
        # A2I writes output to:
        # s3://<bucket>/<flow-definition-name>/<loop-name>/output.json
        # The exact path depends on your flow definition's output configuration.
        # Check the FlowDefinition's HumanLoopActivationConditionsConfig for the
        # output S3 path pattern, or look for the output key in describe_human_loop().
        review_output_key = (
            f"a2i-output/{loop_name}/output.json"
        )

        print("\nStep 7: Processing review results and resuming workflow...")
        process_review_completion(REVIEW_BUCKET, review_output_key)

    else:
        print("\nStep 7: Skipped (no entities required human review).")

    # Step 8: Assemble the final record.
    # Use a placeholder execution ID for the development script.
    execution_id = f"dev-run-{uuid.uuid4()}"
    print("\nStep 8: Assembling final record and capturing training data...")
    final_record = assemble_final_record(image_key, execution_id)

    print(f"\nPipeline complete for {image_key}.")
    print(json.dumps(final_record, indent=2, default=str))

    return final_record


# Lambda handler: Steps 1-5 (the first half of the Step Functions workflow)
def lambda_handler_process_note(event: dict, context) -> dict:
    """
    Lambda handler for the note processing steps (1 through 5).

    Triggered by an S3 upload event when a new handwritten note arrives in
    the intake bucket. Runs pre-processing, OCR, NLP, confidence tiering,
    and routes entities to DynamoDB or A2I.

    The task_token is passed in from the Step Functions state machine input
    using the wait-for-callback pattern ($$.Task.Token in the state definition).

    Args:
        event:   Step Functions state input. Must contain:
                 - bucket:      S3 bucket of the source image
                 - image_key:   S3 object key of the source image
                 - task_token:  Step Functions task token for callback
        context: Lambda context (unused)

    Returns:
        A summary dict (stored in Step Functions execution history).
    """
    bucket      = event["bucket"]
    image_key   = event["image_key"]
    task_token  = event["task_token"]  # injected by Step Functions

    print(f"Processing {image_key} from {bucket}")

    enhanced_key      = preprocess_image(bucket, image_key)
    ocr_result        = extract_text_with_confidence(enhanced_key)
    enriched_entities = extract_clinical_entities(ocr_result)
    tiered            = tier_entities(enriched_entities) if enriched_entities else {"high": [], "medium": [], "low": []}

    route_entities(image_key, tiered, task_token)

    return {
        "image_key":     image_key,
        "entity_count":  len(enriched_entities),
        "review_needed": len(tiered["low"]) > 0,
    }


# Lambda handler: Step 7 (triggered by S3 event when A2I writes review output)
def lambda_handler_review_complete(event: dict, context) -> None:
    """
    Lambda handler for review completion (Step 7).

    Triggered by an S3 event notification when A2I writes the completed
    review JSON to the review output bucket. Reads reviewer corrections,
    updates DynamoDB, and sends the task success to resume Step Functions.

    Args:
        event:   S3 event notification. The Records[0].s3 fields contain
                 the bucket name and object key of the A2I output file.
        context: Lambda context (unused)
    """
    record = event["Records"][0]["s3"]
    bucket = record["bucket"]["name"]
    key    = record["object"]["key"]

    print(f"Processing A2I review output: s3://{bucket}/{key}")
    process_review_completion(bucket, key)


# Lambda handler: Step 8 (the final state in the Step Functions workflow)
def lambda_handler_finalize(event: dict, context) -> dict:
    """
    Lambda handler for final record assembly (Step 8).

    Runs after the Step Functions workflow resumes from the A2I callback.
    Queries all entity records for the document, assembles the final record,
    and captures training data to S3.

    Args:
        event:   Step Functions state input. Must contain:
                 - document_key:  S3 key of the source note
                 - execution_id:  Step Functions execution ARN
        context: Lambda context (unused)

    Returns:
        The assembled final record.
    """
    document_key = event["document_key"]
    execution_id = event.get("execution_id", "unknown")

    print(f"Assembling final record for {document_key}")
    return assemble_final_record(document_key, execution_id)


# Example: run the development pipeline against a test image.
if __name__ == "__main__":
    result = digitize_handwritten_note(
        bucket="notes-intake",
        image_key="notes-intake/2026/03/01/note-00291.jpg",
    )

    # DynamoDB Decimal values are not JSON-serializable by default.
    # This encoder converts them to float for display purposes only.
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## The Gap Between This and Production

This example demonstrates the full eight-step pipeline. Run it against a real handwritten note image and it will produce a structured record with confidence-tiered clinical entities, A2I review integration for low-confidence extractions, and training data capture. The distance from that to something you would deploy for a clinical records program is significant. Here is where it lives.

**Image preprocessing quality matters more than you expect.** The Pillow-based preprocessing here handles basic cases. For production-quality deskewing on a mixed batch of scanned notes and phone photographs, you want the `deskew` library (`pip install deskew`) and OpenCV. The `determine_skew()` function from deskew uses Hough line detection to measure the actual rotation angle, which is meaningfully more accurate than Pillow's inferred approach. On marginal images, the difference between a 2-degree rotation correction and a 4-degree one can move a page from 68% average OCR confidence to 79%, which changes how many entities end up in the human review queue.

**Textract FORMS pricing.** The `AnalyzeDocument` call with `FeatureTypes=["FORMS"]` is priced at $0.05 per page. For a program processing 10,000 pages per month, that is $500 per month in Textract costs before Comprehend Medical. Factor this into your per-page cost estimates alongside the human review costs. If most of your pages are pure prose notes without form fields, you can drop FORMS from the FeatureTypes and fall back to plain text extraction, which is priced lower. The tradeoff is losing the key-value pair structure on pages that do have form elements.

**The A2I output S3 key path.** The `review_output_key` constructed in the development pipeline is a placeholder. A2I writes output to a path determined by the flow definition's output configuration and the human loop name. When you configure your flow definition in the console, you specify the S3 output path prefix. The actual key that A2I writes follows the pattern your flow definition specifies, not one you invent. In production, trigger the Step 7 Lambda via an S3 event notification on the review output bucket with a prefix filter matching your flow definition's output path pattern.

**Consensus review for high-stakes extractions.** This example uses `humanAnswers[0]` and assumes a single reviewer per task. A2I flow definitions can require multiple reviewers and accept a voting threshold (majority, unanimous) before marking a loop complete. For medication names and dosages, requiring two independent reviewers and taking the answer only when both agree reduces the error rate significantly but increases cost and latency. The `humanAnswers` list contains one entry per reviewer. Implement a consensus check before trusting `humanAnswers[0]` if your flow definition routes tasks to multiple reviewers.

**Step Functions payload size limits.** Step Functions Standard Workflows cap state input and output at 256 KB. The enriched entity list for a note with many clinical entities can approach that limit. The production pattern is to write intermediate results to S3 after each Lambda stage and pass S3 keys through the state machine rather than passing the entity lists directly. This adds a small S3 read overhead at each step but keeps the state machine payload well within limits and makes the intermediate results inspectable for debugging.

**Heartbeat timeout on the A2I wait state.** The Step Functions wait state in Step 5 can suspend indefinitely if the resume Lambda in Step 7 fails. Configure a `HeartbeatSeconds` on the A2I wait state (something in the range of 8-24 hours, depending on your review SLA) so that stuck executions surface as `HeartbeatTimedOut` errors with CloudWatch alarms. Without this, a Lambda error in the review completion handler leaves the Step Functions execution waiting silently, and the document never gets a final record.

**DynamoDB Decimal requirement.** Every numeric value written to DynamoDB uses `Decimal` wrapping. Python floats in a `put_item` call raise a `TypeError` at runtime with a message that is less informative than you would like. The `Decimal(str(value))` pattern converts via string to avoid floating-point representation issues in the stored value. Any new numeric field you add to a DynamoDB item needs the same treatment.

**OCR entity-to-word matching is approximate.** The `find_ocr_confidence_for_entity` function uses substring matching to find which Textract words underlie a Comprehend Medical entity. This works for most cases but fails on two classes of input. First, multi-word entities where the Comprehend Medical span does not exactly match any Textract word boundary (for example, "Metformin 500mg twice daily" where Textract treats "500mg" as one word and Comprehend Medical's span starts mid-word). Second, entities that span hyphenated terms or abbreviations with periods. A production implementation cross-references character offset ranges from both APIs rather than using text matching. Both Textract (via `SelectedData`) and Comprehend Medical (via `BeginOffset`, `EndOffset`) provide offset information that enables precise span alignment.

**Training data key management.** Training data is partitioned by date but not by document type, provider, or handwriting quality tier. When you eventually fine-tune a Textract custom adapter, you will want to filter training examples by document type and quality level. Adding those fields to the training pair records now (even if you do not use them immediately) makes that filtering straightforward later. Retrofitting schema onto months of accumulated training data is possible but annoying.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling handwritten clinical notes runs inside a VPC with private subnets and VPC endpoints for S3, Textract, Comprehend Medical, DynamoDB, SageMaker A2I runtime, Step Functions, KMS, and CloudWatch Logs. All S3 buckets use SSE-KMS with customer-managed keys. The training data bucket in particular should be treated as carefully as the intake documents: it contains OCR text from clinical notes, which is PHI regardless of the format.

**Testing.** There are no tests in this example. A production deployment has unit tests for each step with mocked Textract, Comprehend Medical, and A2I responses. It has integration tests using synthetic handwritten note images with known ground-truth transcriptions so you can measure the pipeline's accuracy on your specific document population before deploying. The IAB handwriting datasets and publicly available synthetic clinical note generators can produce realistic test fixtures. Never use real patient notes in any non-production environment.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.6: Handwritten Clinical Note Digitization](chapter01.06-handwritten-clinical-note-digitization) for the full architectural walkthrough, pseudocode, performance benchmarks, and the honest take on where this gets hard in practice.*
