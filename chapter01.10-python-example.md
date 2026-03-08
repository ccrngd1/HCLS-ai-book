# Recipe 1.10: Python Example: Historical Chart Migration

> **This is an illustrative sample, not a production-ready implementation.**
>
> The code below demonstrates the patterns from Recipe 1.10 using boto3. It walks through
> Bedrock batch inference setup, prompt caching, vision model calls, FHIR bundle assembly,
> and HealthLake import. Use it to understand the API surface and data structures. Treat it
> as a starting point, not a destination. The "Gap to Production" section at the end lists
> what you'd need to add before deploying this in a real migration program.

---

## Setup

```bash
pip install boto3 botocore pillow pypdf2 python-dateutil
```

**IAM permissions needed (Lambda execution role or Batch job role):**
```
bedrock:InvokeModel
bedrock:CreateModelInvocationJob
bedrock:GetModelInvocationJob
bedrock:ListModelInvocationJobs
textract:StartDocumentTextDetection
textract:GetDocumentTextDetection
comprehendmedical:InferICD10CM
comprehendmedical:InferRxNorm
healthlake:StartFHIRImportJob
healthlake:DescribeFHIRImportJob
s3:GetObject
s3:PutObject
s3:CopyObject
s3:DeleteObject
dynamodb:GetItem
dynamodb:PutItem
dynamodb:UpdateItem
dynamodb:Query
```

---

## Configuration and Constants

```python
import boto3
import json
import base64
import re
import time
import uuid
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
from botocore.config import Config

# ---------------------------------------------------------------------------------
# Logging setup: structured, PHI-safe
# CRITICAL: Never log extracted text, LLM response content, or reasoning strings.
# Lambda stdout goes to CloudWatch Logs. If CloudWatch log groups are not encrypted
# with KMS (Lambda does not do this automatically), any clinical content in logs
# is uncontrolled PHI. Log only structural metadata.
# ---------------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# Model IDs: cross-region inference profiles for capacity routing
#
# The "us." prefix routes across us-east-1, us-east-2, and us-west-2 automatically.
# AWS routes your API call through the VPC endpoint in your region; PHI does not
# traverse the public internet even when the backend processes in another region.
#
# PRODUCTION NOTE: Cross-region inference profile IDs can be updated by AWS to
# point to new underlying model versions. For a migration program running over
# months, pin to explicit foundation model ARNs for consistent behavior:
#   arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0
# Check the Bedrock Model IDs documentation for your region's ARN format.
# ---------------------------------------------------------------------------------
MODEL_TIER1_CLASSIFY = "us.amazon.nova-lite-v1:0"
MODEL_TIER2_EXTRACT  = "us.amazon.nova-pro-v1:0"
MODEL_TIER3_SONNET   = "us.anthropic.claude-sonnet-4-6-20260217-v1:0"
MODEL_TIER4_OPUS     = "us.anthropic.claude-opus-4-6-20260204-v1:0"

# Confidence thresholds for tier routing
TEXTRACT_VISION_THRESHOLD = 0.65   # below this, route to vision model
TEXTRACT_OPUS_THRESHOLD   = 0.45   # below this, escalate to Tier 4 Opus

# S3 buckets
BUCKET_CHARTS_RAW     = "charts-raw"
BUCKET_CHARTS_PROCESSED = "charts-processed"
BUCKET_TEXTRACT_OUTPUT = "textract-output"
BUCKET_BATCH_INFERENCE = "batch-inference"
BUCKET_FHIR_OUTPUT     = "fhir-output"
BUCKET_FHIR_STAGING    = "fhir-import-staging"

# DynamoDB
TABLE_MIGRATION = "migration-tracking"

# ARNs (replace with your actual values)
KMS_KEY_ARN             = "arn:aws:kms:us-east-1:ACCOUNT:key/KEY-ID"
BEDROCK_BATCH_ROLE_ARN  = "arn:aws:iam::ACCOUNT:role/bedrock-batch-inference-role"
HEALTHLAKE_IMPORT_ROLE_ARN = "arn:aws:iam::ACCOUNT:role/healthlake-import-role"
HEALTHLAKE_DATASTORE_ID = "DATASTORE-ID"
TEXTRACT_SNS_TOPIC_ARN  = "arn:aws:sns:us-east-1:ACCOUNT:textract-chart-jobs"
TEXTRACT_SNS_ROLE_ARN   = "arn:aws:iam::ACCOUNT:role/textract-sns-role"


# ---------------------------------------------------------------------------------
# Boto3 client factory with retry configuration
#
# ALWAYS configure retries on clients that call Bedrock or Comprehend Medical.
# ThrottlingException is not an edge case at healthcare volume. It is expected.
# "adaptive" mode implements exponential backoff with jitter and is the right
# default for any Bedrock-calling Lambda or Batch container.
# ---------------------------------------------------------------------------------
_retry_config = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}
)

def get_bedrock_client(region: str = "us-east-1"):
    return boto3.client("bedrock-runtime", region_name=region, config=_retry_config)

def get_bedrock_control_client(region: str = "us-east-1"):
    # For CreateModelInvocationJob (batch inference control plane)
    return boto3.client("bedrock", region_name=region, config=_retry_config)

def get_textract_client(region: str = "us-east-1"):
    return boto3.client("textract", region_name=region, config=_retry_config)

def get_comprehend_medical_client(region: str = "us-east-1"):
    # IMPORTANT: Comprehend Medical is not available in all regions.
    # Verify availability before selecting your deployment region:
    # https://docs.aws.amazon.com/general/latest/gr/comprehend-medical.html
    return boto3.client("comprehendmedical", region_name=region, config=_retry_config)

def get_healthlake_client(region: str = "us-east-1"):
    return boto3.client("healthlake", region_name=region, config=_retry_config)

def get_s3_client():
    return boto3.client("s3", config=_retry_config)

def get_dynamodb_resource():
    return boto3.resource("dynamodb", config=_retry_config)


# ---------------------------------------------------------------------------------
# S3 lifecycle configuration for the batch-inference bucket
#
# CALL THIS ONCE during infrastructure setup, not on every run.
# The recipe promises 30-day expiry for batch JSONL files as a data governance
# control. Without this lifecycle policy, PHI-containing JSONL files accumulate
# indefinitely in S3 Standard storage.
#
# batch-input/  contains classification requests with OCR-extracted page text (PHI)
# batch-output/ contains classification/extraction results with clinical content (PHI)
#
# Both paths expire after 30 days. The FHIR output bucket and DynamoDB are the
# durable stores; batch JSONL is ephemeral staging data.
# [EDITOR: review fix - P1 S3 lifecycle. The recipe promised 30-day JSONL expiry but
#  provided no implementation. This function fulfills that governance control.]
# ---------------------------------------------------------------------------------
def configure_batch_inference_bucket_lifecycle(region: str = "us-east-1") -> None:
    """
    Apply a 30-day expiry lifecycle policy to the batch-inference S3 bucket.
    Run once during initial infrastructure setup.

    Also configures the policy so the Bedrock batch service role can access
    the bucket without a VPC endpoint condition (see note in function body).
    """
    s3 = get_s3_client()

    lifecycle_policy = {
        "Rules": [
            {
                "ID":     "expire-batch-input-files",
                "Status": "Enabled",
                "Filter": {"Prefix": "batch-input/"},
                "Expiration": {"Days": 30}
            },
            {
                "ID":     "expire-batch-output-results",
                "Status": "Enabled",
                "Filter": {"Prefix": "batch-output/"},
                "Expiration": {"Days": 30}
            }
        ]
    }

    s3.put_bucket_lifecycle_configuration(
        Bucket=BUCKET_BATCH_INFERENCE,
        LifecycleConfiguration=lifecycle_policy
    )

    logger.info(
        "Batch-inference bucket lifecycle configured: 30-day expiry on input and output prefixes",
        extra={"bucket": BUCKET_BATCH_INFERENCE}
    )

    # NOTE on bucket policy for Bedrock batch inference access:
    # Bedrock batch inference reads input JSONL and writes output JSONL using
    # BEDROCK_BATCH_ROLE_ARN on AWS's internal network -- NOT through your VPC's
    # S3 gateway endpoint. If your bucket policy includes an aws:SourceVpc or
    # aws:SourceVpcEndpoint condition, the batch service S3 access will be denied
    # and batch jobs will fail with S3 access errors.
    #
    # Ensure your bucket policy has an explicit allow for BEDROCK_BATCH_ROLE_ARN
    # that is NOT subject to a VPC endpoint condition. Your Lambda's JSONL uploads
    # can continue using VPC endpoint access; only the Bedrock service role needs
    # the exemption. Example bucket policy statement to add:
    #
    # {
    #   "Effect": "Allow",
    #   "Principal": {"AWS": BEDROCK_BATCH_ROLE_ARN},
    #   "Action": ["s3:GetObject", "s3:PutObject"],
    #   "Resource": f"arn:aws:s3:::{BUCKET_BATCH_INFERENCE}/*"
    #   # No aws:SourceVpc condition on this statement.
    # }
    # [EDITOR: review fix - P1 VPC/S3. Added bucket policy note for Bedrock batch role.]
```

---

## Step 1: Manifest Generation and DynamoDB Initialization

```python
def generate_migration_manifest(s3_prefix: str, output_key: str) -> tuple[int, str]:
    """
    List all chart PDFs under s3_prefix, build a CSV manifest for AWS Batch,
    and initialize DynamoDB tracking records for each chart.

    Idempotency guard: charts already marked 'completed' or 'import_submitted'
    in DynamoDB are skipped. This makes it safe to re-run manifest generation
    if a wave fails partway through.
    """
    s3  = get_s3_client()
    ddb = get_dynamodb_resource().Table(TABLE_MIGRATION)

    # List all chart objects under the prefix
    paginator = s3.get_paginator("list_objects_v2")
    pages     = paginator.paginate(Bucket=BUCKET_CHARTS_RAW, Prefix=s3_prefix)

    manifest_rows    = []
    dynamodb_records = []

    for page in pages:
        for obj in page.get("Contents", []):
            if not obj["Key"].endswith(".pdf"):
                continue

            chart_id = extract_chart_id_from_key(obj["Key"])

            # Check idempotency
            existing = ddb.get_item(Key={"chart_id": chart_id}).get("Item")
            if existing and existing.get("status") in ["completed", "import_submitted"]:
                # Safe to log the chart_id (not PHI) but not any clinical content
                logger.info("Skipping already-processed chart", extra={"chart_id": chart_id})
                continue

            manifest_rows.append({
                "bucket":   BUCKET_CHARTS_RAW,
                "key":      obj["Key"],
                "chart_id": chart_id
            })

            dynamodb_records.append({
                "chart_id":    chart_id,
                "s3_key":      obj["Key"],
                "status":      "pending",
                "created_at":  datetime.now(timezone.utc).isoformat(),
                # Initialize tier counters as Decimals (boto3 requires Decimal for numerics)
                "tier1_pages": Decimal("0"),
                "tier2_pages": Decimal("0"),
                "tier3_pages": Decimal("0"),
                "tier4_pages": Decimal("0")
            })

    # Write manifest CSV to S3
    manifest_csv = "bucket,key,chart_id\n" + "\n".join(
        f"{r['bucket']},{r['key']},{r['chart_id']}" for r in manifest_rows
    )
    s3.put_object(
        Bucket="manifests",
        Key=output_key,
        Body=manifest_csv.encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    # Batch-write DynamoDB records (25 per call, as required by batch_writer)
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)
    with table.batch_writer() as batch:
        for record in dynamodb_records:
            batch.put_item(Item=record)

    logger.info(
        "Manifest generated",
        extra={"chart_count": len(manifest_rows), "manifest_key": output_key}
    )
    return len(manifest_rows), output_key


def extract_chart_id_from_key(s3_key: str) -> str:
    """
    Extract the chart ID from the S3 object key.
    Convention: 'charts-raw/YYYY/MM/CHARTID.pdf'
    Agree on this naming convention with your scanning vendor before scanning starts.
    """
    filename = s3_key.rsplit("/", 1)[-1]
    return filename.replace(".pdf", "")
```

---

## Step 2: Image Pre-Processing

```python
def preprocess_chart(chart_pdf_key: str, chart_id: str) -> tuple[str, dict]:
    """
    Download the chart PDF, detect and correct rotation, deskew pages,
    filter blank pages, and upload the processed version to charts-processed/.

    Also stores individual page PNG images in page-images/ for the vision path.
    """
    s3 = get_s3_client()

    # Download the source PDF
    response   = s3.get_object(Bucket=BUCKET_CHARTS_RAW, Key=chart_pdf_key)
    pdf_bytes  = response["Body"].read()

    # In production: use a library like PyMuPDF (fitz) or pypdf for splitting.
    # This example uses pseudo-functions for clarity.
    pages = split_pdf_into_page_images(pdf_bytes)   # returns list of (page_num, PIL.Image)

    quality_report = {
        "total_pages":         len(pages),
        "blank_pages_skipped": 0,
        "rotations_corrected": 0,
        "low_dpi_warnings":    0
    }

    processed_pages = []

    for page_num, img in pages:
        # Blank page detection: skip pages with > 98% white pixels
        if is_blank_page(img, white_threshold=0.98):
            quality_report["blank_pages_skipped"] += 1
            continue

        # Orientation correction
        # (use a library like pytesseract OSD or a vision model for orientation detection)
        orientation = detect_orientation(img)
        if orientation != 0:
            img = img.rotate(-orientation, expand=True)
            quality_report["rotations_corrected"] += 1

        # DPI check: log metric only, never log page content
        dpi = getattr(img, "info", {}).get("dpi", (0, 0))[0]
        if dpi and dpi < 200:
            quality_report["low_dpi_warnings"] += 1
            # Emit a CloudWatch custom metric, not a log message with page data
            emit_cloudwatch_metric("low_dpi_page_count", 1,
                                   dimensions=[{"Name": "chart_id", "Value": chart_id}])

        processed_pages.append((page_num, img))

        # Store individual page PNG for the vision extraction path
        page_png_bytes = image_to_png_bytes(img)
        page_image_key = f"page-images/{chart_id}/page-{page_num}.png"
        s3.put_object(
            Bucket=BUCKET_CHARTS_PROCESSED,
            Key=page_image_key,
            Body=page_png_bytes,
            ContentType="image/png",
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=KMS_KEY_ARN
        )

    # Reassemble processed pages as a PDF
    processed_pdf_bytes = assemble_pdf_from_images(processed_pages)
    processed_key       = f"processed/{chart_id}/chart.pdf"
    s3.put_object(
        Bucket=BUCKET_CHARTS_PROCESSED,
        Key=processed_key,
        Body=processed_pdf_bytes,
        ContentType="application/pdf",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    logger.info(
        "Pre-processing complete",
        extra={
            "chart_id":    chart_id,
            "total_pages": quality_report["total_pages"],
            "blank_skipped": quality_report["blank_pages_skipped"],
            "rotations":   quality_report["rotations_corrected"]
            # Do NOT include any page text, OCR output, or image content here
        }
    )
    return processed_key, quality_report


def is_blank_page(img, white_threshold: float = 0.98) -> bool:
    """
    Returns True if more than white_threshold fraction of pixels are near-white.
    Handles both grayscale and color images.
    """
    import numpy as np
    from PIL import Image

    gray = img.convert("L")
    arr  = np.array(gray)
    white_pixels = np.sum(arr > 240)
    total_pixels = arr.size
    return (white_pixels / total_pixels) > white_threshold
```

---

## Step 3: Textract Base OCR

```python
def start_textract_ocr(processed_chart_key: str, chart_id: str) -> str:
    """
    Start async Textract text detection on the processed chart PDF.
    Returns the Textract job ID.

    We use StartDocumentTextDetection (not StartDocumentAnalysis) for the initial
    pass because it is 44x cheaper ($0.0015 vs $0.065/page). We only need raw text
    and word-level confidence scores at this stage. If Nova Lite classifies a page
    as structured (lab results, forms), we run a second AnalyzeDocument call on
    just those pages.
    """
    textract = get_textract_client()

    response = textract.start_document_text_detection(
        DocumentLocation={
            "S3Object": {
                "Bucket": BUCKET_CHARTS_PROCESSED,
                "Name":   processed_chart_key
            }
        },
        NotificationChannel={
            "SNSTopicArn": TEXTRACT_SNS_TOPIC_ARN,
            "RoleArn":     TEXTRACT_SNS_ROLE_ARN
        },
        JobTag=chart_id  # ties the SNS notification back to this chart
    )

    job_id = response["JobId"]

    # Record the job ID in DynamoDB for debugging and status tracking
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)
    table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression="SET textract_job_id = :jid, #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":jid": job_id, ":status": "ocr_in_progress"}
    )

    logger.info("Textract job started", extra={"chart_id": chart_id, "job_id": job_id})
    return job_id


def retrieve_ocr_results(job_id: str, chart_id: str) -> str:
    """
    Retrieve all Textract blocks (paginated) and compute per-page quality signals.
    Writes raw blocks and quality signals to S3.

    Returns the S3 key for the quality signals JSON file.
    """
    textract = get_textract_client()
    s3       = get_s3_client()

    # Retrieve all blocks via paginated API
    all_blocks = []
    next_token = None

    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token

        response = textract.get_document_text_detection(**kwargs)
        all_blocks.extend(response.get("Blocks", []))

        next_token = response.get("NextToken")
        if not next_token:
            break

    # Compute per-page quality signals
    pages_data = {}
    for block in all_blocks:
        page_num = block.get("Page")
        if page_num is None:
            continue

        if page_num not in pages_data:
            pages_data[page_num] = {"words": [], "text_parts": []}

        if block["BlockType"] == "WORD":
            pages_data[page_num]["words"].append({
                "text":       block.get("Text", ""),
                "confidence": block.get("Confidence", 0.0) / 100.0,
                "text_type":  block.get("TextType", "PRINTED")
            })

    page_quality = {}
    for page_num, data in pages_data.items():
        words = data["words"]
        if not words:
            page_quality[page_num] = {
                "avg_confidence":  None,
                "handwriting_pct": 0.0,
                "word_count":      0,
                "page_text":       "",
                "is_blank":        True
            }
            continue

        confidences    = [w["confidence"] for w in words]
        avg_confidence = sum(confidences) / len(confidences)
        hw_count       = sum(1 for w in words if w["text_type"] == "HANDWRITING")
        page_text      = " ".join(w["text"] for w in words)

        page_quality[page_num] = {
            "avg_confidence":  round(avg_confidence, 3),
            "handwriting_pct": round(hw_count / len(words), 3),
            "word_count":      len(words),
            "page_text":       page_text,   # stored in S3, not logged
            "is_blank":        False
        }

    # Write to S3. These files contain PHI and are covered by SSE-KMS.
    quality_key = f"textract-output/{chart_id}/page-quality.json"
    s3.put_object(
        Bucket=BUCKET_TEXTRACT_OUTPUT,
        Key=quality_key,
        Body=json.dumps(page_quality).encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    # Update DynamoDB with page count (not page text, just the count)
    page_count = max(page_quality.keys()) if page_quality else 0
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)
    table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression="SET page_count = :pc, #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":pc":     Decimal(str(page_count)),
            ":status": "classifying"
        }
    )

    logger.info(
        "OCR results retrieved",
        extra={"chart_id": chart_id, "page_count": page_count}
    )
    return quality_key
```

---

## Step 4: Nova Lite Classification Batch Job

```python
# ---------------------------------------------------------------------------------
# Classification system prompt: cached across all batch inference requests.
# With a 1-hour TTL cache, and 10% cost for cache reads, this prompt is effectively
# free after the first call. At 3 billion pages with the same classification schema,
# prompt caching on this system prompt saves hundreds of thousands of dollars.
# ---------------------------------------------------------------------------------
CLASSIFICATION_SYSTEM_PROMPT = """You are a healthcare document classifier. You are reading text extracted from
scanned historical medical charts spanning 1970-2010. Your task is to classify
each page as one of the following document types and assess its quality.

Document types:
- progress_note: Clinical progress note or office visit note (SOAP format or similar)
- history_and_physical: History and physical examination
- discharge_summary: Hospital discharge summary
- operative_report: Surgical or operative report
- consultation_report: Specialist consultation letter or report
- lab_result: Laboratory results or pathology report
- radiology_report: Imaging report (X-ray, MRI, CT, ultrasound)
- medication_list: Medication list or prescription record
- immunization_record: Immunization or vaccination record
- problem_list: Problem list or diagnosis summary
- other_clinical: Other clinical document type
- administrative: Administrative forms, authorizations, demographic pages
- blank_or_artifact: Blank page, fax cover sheet, scanner separator

Return a JSON object with:
{
  "doc_type": "<one of the types above>",
  "confidence": <0.0-1.0>,
  "handwriting_heavy": <true if >50% of content appears handwritten>,
  "structured_content": <true if the page contains tables or form fields>,
  "extraction_tier": <2, 3, or 4>
}

Tier guidance:
- Tier 2 (nova-pro): clean typed clinical text, printed lab results, typed forms
- Tier 3 (sonnet): handwritten pages with avg OCR confidence >0.65, complex narrative
- Tier 4 (opus): severely degraded images with avg OCR confidence <0.45

Return ONLY valid JSON. No explanation. No markdown."""


def sanitize_page_text(text: str) -> str:
    """
    Strip content that could be used for prompt injection before including
    OCR-extracted page text in an LLM request.

    Strips:
    - Null bytes and C0/C1 control characters (except newline, tab, carriage return)
    - Unicode Private Use Area code points (U+E000-U+F8FF)
    - Patterns that look like instruction overrides

    This is a first-line defense. Bedrock Guardrails (configured via guardrailConfig
    in the Converse call) provides a second line of defense.
    """
    if not text:
        return ""

    # Strip null bytes and dangerous control characters
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

    # Strip Unicode Private Use Area
    text = re.sub(r"[\uE000-\uF8FF]", "", text)

    # Strip common injection trigger patterns (case-insensitive)
    injection_patterns = [
        r"(?i)\bIGNORE\s+(PREVIOUS|ALL|ABOVE)\b",
        r"(?i)\bSYSTEM\s*:",
        r"(?i)\bassistant\s*:",
        r"(?i)\b(OVERRIDE|BYPASS|DISREGARD)\s+(INSTRUCTIONS|RULES|PROMPT)\b"
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, "[FILTERED]", text)

    return text


def generate_classification_batch_jsonl(
    chart_id: str,
    quality_key: str
) -> str:
    """
    Generate a JSONL file for Nova Lite classification batch inference.
    One line per non-blank page. Each line includes the page's OCR text and
    quality signals. The system prompt is marked for caching.

    Returns the S3 key of the generated JSONL file.
    """
    s3 = get_s3_client()

    # Load page quality data
    response     = s3.get_object(Bucket=BUCKET_TEXTRACT_OUTPUT, Key=quality_key)
    page_quality = json.loads(response["Body"].read())

    requests = []

    for page_num_str, quality in page_quality.items():
        page_num = int(page_num_str)

        if quality.get("is_blank") or quality.get("word_count", 0) == 0:
            continue  # Skip blank pages

        # Sanitize the page text before including in the LLM request
        clean_text = sanitize_page_text(quality.get("page_text", ""))

        request = {
            "recordId": f"{chart_id}-page-{page_num}",
            "modelInput": {
                "schemaVersion": "messages-v1",
                "system": [
                    {
                        "text": CLASSIFICATION_SYSTEM_PROMPT,
                        "cachePoint": {
                            "type": "default"
                            # "default" = 5-minute TTL cache.
                            # For a batch job running over many hours against the same
                            # classification schema, use an explicit long-TTL cache
                            # by setting type to "ephemeral" with a 1-hour TTL.
                            # Check the Bedrock Prompt Caching docs for the current
                            # long-TTL syntax as the API evolves.
                        }
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": (
                                    f"Chart: {chart_id} | Page: {page_num}\n"
                                    f"OCR confidence: {quality.get('avg_confidence', 'unknown')}\n"
                                    f"Handwriting detected: {quality.get('handwriting_pct', 0):.1%}\n\n"
                                    f"Page text:\n{clean_text[:4000]}"
                                    # Truncate to avoid exceeding Nova Lite's context.
                                    # Pages > 4000 chars are unusual for single pages.
                                )
                            }
                        ]
                    }
                ],
                "inferenceConfig": {
                    "maxTokens":   256,
                    "temperature": 0   # Deterministic output for classification
                }
                # ---- PRODUCTION: Add Guardrails config here ----
                # "guardrailConfig": {
                #     "guardrailIdentifier": "GUARDRAIL-ID",
                #     "guardrailVersion":    "DRAFT",
                #     "trace":               "disabled"
                # }
            }
        }
        requests.append(json.dumps(request))

    # Write JSONL to S3
    jsonl_key = f"batch-input/{chart_id}/classify.jsonl"
    jsonl_content = "\n".join(requests) + "\n"
    s3.put_object(
        Bucket=BUCKET_BATCH_INFERENCE,
        Key=jsonl_key,
        Body=jsonl_content.encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    logger.info(
        "Classification JSONL generated",
        extra={"chart_id": chart_id, "request_count": len(requests)}
    )
    return jsonl_key


def submit_bedrock_batch_job(
    input_s3_prefix: str,
    output_s3_prefix: str,
    model_id: str,
    job_name: str
) -> str:
    """
    Submit a Bedrock batch inference job.

    The batch pricing is 50% of on-demand rates. For chart migration at scale,
    this is the most important cost lever after model tiering.

    Returns the job ARN.
    """
    bedrock_control = get_bedrock_control_client()

    response = bedrock_control.create_model_invocation_job(
        jobName=job_name,
        modelId=model_id,
        inputDataConfig={
            "s3InputDataConfig": {
                "s3Uri":         f"s3://{BUCKET_BATCH_INFERENCE}/{input_s3_prefix}",
                "s3InputFormat": "JSONLines"
                # s3BucketOwner: omit for same-account buckets. Include only if
                # [EDITOR: Removed explicit None values for s3BucketOwner. Passing None
                # includes the key with a null value in the API call, which can cause
                # unexpected validation behavior. Omitting the key entirely is correct
                # for same-account buckets.]
                # the S3 bucket is owned by a different AWS account.
            }
        },
        outputDataConfig={
            "s3OutputDataConfig": {
                "s3Uri":    f"s3://{BUCKET_BATCH_INFERENCE}/{output_s3_prefix}",
                "kmsKeyId": KMS_KEY_ARN
                # s3BucketOwner: omit for same-account buckets (see above)
            }
        },
        roleArn=BEDROCK_BATCH_ROLE_ARN
        # The role needs: bedrock:InvokeModel, s3:GetObject (input), s3:PutObject (output)
    )

    job_arn = response["jobArn"]
    logger.info("Batch inference job submitted", extra={"job_arn": job_arn, "model": model_id})
    return job_arn


def wait_for_batch_job(job_arn: str, poll_interval_seconds: int = 300) -> str:
    """
    Poll for batch inference job completion.
    Returns "Completed" or "Failed".

    Batch jobs complete within 24 hours typically. For production, use
    EventBridge scheduled rules to check job status rather than polling
    in a loop. This function is for illustrative purposes and testing.
    """
    bedrock_control = get_bedrock_control_client()

    while True:
        response = bedrock_control.get_model_invocation_job(jobIdentifier=job_arn)
        status   = response["status"]

        logger.info("Batch job status", extra={"job_arn": job_arn, "status": status})

        if status in ("Completed", "Failed", "Stopped"):
            return status

        time.sleep(poll_interval_seconds)
```

---

## Step 5: Route Pages by Tier

```python
def process_classification_results(
    results_s3_prefix: str,
    chart_id: str
) -> dict:
    """
    Parse Nova Lite classification results and route each page to its extraction tier.

    Returns a dict with keys: "tier2_nova", "tier3_sonnet_text",
    "tier3_sonnet_vision", "tier4_opus_vision", "tier1_skip"
    """
    s3 = get_s3_client()

    # Load the quality signals to override tier based on Textract confidence
    quality_key      = f"textract-output/{chart_id}/page-quality.json"
    quality_response = s3.get_object(Bucket=BUCKET_TEXTRACT_OUTPUT, Key=quality_key)
    page_quality     = json.loads(quality_response["Body"].read())

    # Load batch inference results (one JSONL result file per job)
    result_obj = s3.get_object(
        Bucket=BUCKET_BATCH_INFERENCE,
        Key=f"{results_s3_prefix}/{chart_id}/classify.jsonl.out"
        # Actual output path format varies; check Bedrock batch output docs
    )
    result_lines = result_obj["Body"].read().decode("utf-8").strip().split("\n")

    routing = {
        "tier1_skip":           [],
        "tier2_nova":           [],
        "tier3_sonnet_text":    [],
        "tier3_sonnet_vision":  [],
        "tier4_opus_vision":    []
    }

    for line in result_lines:
        if not line.strip():
            continue

        result = json.loads(line)
        record_id = result["recordId"]

        # Parse: "{chart_id}-page-{page_num}"
        page_num = int(record_id.rsplit("-page-", 1)[-1])

        # Parse the LLM output safely
        try:
            output_text    = result["modelOutput"]["output"]["message"]["content"][0]["text"]
            classification = json.loads(output_text)
        except (KeyError, json.JSONDecodeError, IndexError):
            # Malformed output: escalate to Tier 3 for a second attempt
            # IMPORTANT: Do NOT log the output_text. It may contain clinical content.
            logger.warning(
                "Classification parse error, escalating to Tier 3",
                extra={"chart_id": chart_id, "page_num": page_num}
            )
            routing["tier3_sonnet_text"].append({"page_num": page_num, "doc_type": "unknown"})
            continue

        # Get Textract quality signal for this page
        quality    = page_quality.get(str(page_num), {})
        avg_conf   = quality.get("avg_confidence") or 1.0  # Default to high if missing

        # Determine final tier (LLM suggestion + Textract override)
        llm_tier   = classification.get("extraction_tier", 2)
        doc_type   = classification.get("doc_type", "unknown")
        class_conf = classification.get("confidence", 0.5)

        # Textract confidence overrides: escalate if image quality is low
        if avg_conf < TEXTRACT_OPUS_THRESHOLD:
            assigned_tier   = 4
            use_vision      = True
        elif avg_conf < TEXTRACT_VISION_THRESHOLD:
            assigned_tier   = max(llm_tier, 3)
            use_vision      = True
        else:
            assigned_tier   = llm_tier
            use_vision      = False

        entry = {
            "page_num":   page_num,
            "doc_type":   doc_type,
            "class_conf": class_conf,
            "avg_conf":   avg_conf
        }

        if doc_type in ("blank_or_artifact", "administrative") and class_conf >= 0.85:
            routing["tier1_skip"].append(entry)
        elif assigned_tier == 4 and use_vision:
            routing["tier4_opus_vision"].append(entry)
        elif assigned_tier >= 3 and use_vision:
            routing["tier3_sonnet_vision"].append(entry)
        elif assigned_tier >= 3:
            routing["tier3_sonnet_text"].append(entry)
        else:
            routing["tier2_nova"].append(entry)

    # Update DynamoDB tier counts (use Decimal for all numerics)
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)
    table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression=(
            "SET tier1_pages = :t1, tier2_pages = :t2, "
            "tier3_pages = :t3, tier4_pages = :t4, #s = :status"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":t1":     Decimal(str(len(routing["tier1_skip"]))),
            ":t2":     Decimal(str(len(routing["tier2_nova"]))),
            ":t3":     Decimal(str(
                len(routing["tier3_sonnet_text"]) + len(routing["tier3_sonnet_vision"])
            )),
            ":t4":     Decimal(str(len(routing["tier4_opus_vision"]))),
            ":status": "extracting"
        }
    )

    return routing
```

---

## Step 6: Vision Extraction (Tier 3 and Tier 4)

```python
def generate_vision_extraction_jsonl(
    vision_pages: list,
    model_tier: int,
    chart_id: str
) -> str:
    """
    Generate a JSONL file for vision extraction batch inference.
    Sends the raw page PNG image to Sonnet or Opus, which reads
    the handwriting or degraded content directly from the image.

    This is significantly more expensive per page than text-based extraction
    (~10-20x more tokens for the image), so it's reserved for pages where
    Textract confidence signals that the OCR output is unreliable.

    File size warning: each base64-encoded page image adds 1.3-4 MB per request
    line. A wave of 10,000 vision-path pages produces a 13-40 GB JSONL file.
    Before submitting large vision batches:
      - Split into multiple JSONL files (2,000-3,000 pages each).
      - Use S3 multipart upload for files >5 GB (boto3 TransferConfig handles this
        automatically when multipart_threshold is set).
      - Verify each request line stays within Bedrock's per-request payload limit.
      - Consider downsampling 600 DPI images to 300 DPI before embedding (75% size
        reduction with negligible accuracy impact per Recipe 1.6 benchmarks).
    [EDITOR: review fix - P1 vision JSONL file sizes. Added size guidance to docstring.]
    """
    s3 = get_s3_client()

    model_id   = MODEL_TIER3_SONNET if model_tier == 3 else MODEL_TIER4_OPUS
    tier_label = f"tier{model_tier}"

    VISION_PROMPT = """Read this handwritten or degraded medical record page. Extract all clinical information visible.

The page is from a historical paper medical chart. Focus on:
- Diagnoses, conditions, or problems mentioned
- Medications and doses
- Dates (visit date, document date, any dates mentioned in context)
- Lab values, vital signs, or test results
- Procedures or treatments mentioned

Return JSON:
{
  "document_date": "<YYYY-MM-DD or null>",
  "doc_type_confirmed": "<document type>",
  "diagnoses": [{"description": "...", "icd_concept": "...", "date": "..."}],
  "medications": [{"name": "...", "dose": "...", "frequency": "..."}],
  "procedures": [{"description": "...", "date": "..."}],
  "lab_values": [{"test": "...", "value": "...", "unit": "...", "ref_range": "..."}],
  "allergies": ["..."],
  "vital_signs": [{"type": "...", "value": "...", "unit": "...", "date": "..."}],
  "legibility": <0.0-1.0>,
  "extraction_notes": "<anything unclear, partially legible, or uncertain>"
}

Return ONLY valid JSON."""

    requests = []

    for page_info in vision_pages:
        page_num  = page_info["page_num"]
        image_key = f"page-images/{chart_id}/page-{page_num}.png"

        # Load the page image
        img_response = s3.get_object(Bucket=BUCKET_CHARTS_PROCESSED, Key=image_key)
        image_bytes  = img_response["Body"].read()

        # IMPORTANT: batch inference JSONL requires base64-encoded strings for image bytes.
        # Unlike the synchronous Converse API (where boto3 handles encoding transparently),
        # batch JSONL is raw JSON -- you must encode manually.
        # list(image_bytes) produces a JSON integer array the Bedrock service cannot
        # deserialize, causing silent failures for every vision-tier batch request.
        # [EDITOR: review fix - P0 image encoding. Fixed base64 encoding. list(image_bytes)
        #  serializes as a JSON integer array and silently fails. base64.b64encode(image_bytes)
        #  .decode("utf-8") produces the base64 string Bedrock batch inference requires.]
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Vision JSONL file size note: each base64-encoded page image adds 1.3-4MB
        # to the JSONL. A 10,000-page vision wave produces a 13-40GB file.
        # See generate_vision_extraction_jsonl docstring for splitting guidance.
        # [EDITOR: review fix - P1 vision JSONL file sizes. Added inline size note.]

        request = {
            "recordId": f"{chart_id}-{tier_label}-page-{page_num}",
            "modelInput": {
                "schemaVersion": "messages-v1",
                "system": [
                    {
                        "text": VISION_PROMPT,
                        "cachePoint": {"type": "default"}
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "image": {
                                    "format": "png",
                                    "source": {
                                        "bytes": image_b64
                                        # base64-encoded string as required for batch JSONL.
                                    }
                                }
                            },
                            {
                                "text": f"Chart: {chart_id} | Page: {page_num}"
                                # Do NOT include OCR text here. The whole point of
                                # the vision path is that the OCR text was unreliable.
                                # Give the model only the image and structural metadata.
                            }
                        ]
                    }
                ],
                "inferenceConfig": {
                    "maxTokens":   1024,
                    "temperature": 0
                }
            }
        }
        requests.append(json.dumps(request))

    jsonl_key = f"batch-input/{chart_id}/{tier_label}-vision.jsonl"
    s3.put_object(
        Bucket=BUCKET_BATCH_INFERENCE,
        Key=jsonl_key,
        Body=("\n".join(requests) + "\n").encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    logger.info(
        "Vision extraction JSONL generated",
        extra={
            "chart_id":    chart_id,
            "tier":        tier_label,
            "page_count":  len(vision_pages)
        }
    )
    return jsonl_key
```

---

## Step 7: Code Validation with Comprehend Medical

```python
def validate_codes_comprehend_medical(
    diagnoses: list[dict],
    medications: list[dict],
    region: str = "us-east-1"
) -> dict:
    """
    Validate ICD-10-CM codes for diagnoses and RxNorm CUIs for medications.

    LLMs understand clinical language but should not be trusted for exact code
    generation. Comprehend Medical maps extracted text descriptions to validated
    codes from authoritative reference data.

    Returns:
        {
            "diagnoses_coded":   [{"description": ..., "icd10_code": ..., "score": ...}],
            "medications_coded": [{"name": ..., "rxnorm_cui": ..., "score": ...}]
        }
    """
    cm      = get_comprehend_medical_client(region=region)
    results = {"diagnoses_coded": [], "medications_coded": []}

    # ICD-10-CM inference
    if diagnoses:
        # Join all diagnosis descriptions for a single API call (up to 20,000 chars)
        diagnosis_text = "\n".join(
            d.get("description", "") for d in diagnoses if d.get("description")
        )[:20000]

        if diagnosis_text:
            response = cm.infer_icd10_cm(Text=diagnosis_text)
            for entity in response.get("Entities", []):
                concepts = entity.get("ICD10CMConcepts", [])
                if concepts and concepts[0].get("Score", 0) >= 0.80:
                    results["diagnoses_coded"].append({
                        "description":   entity.get("Text"),
                        "icd10_code":    concepts[0]["Code"],
                        "icd10_display": concepts[0]["Description"],
                        "score":         concepts[0]["Score"]
                    })

    # RxNorm inference
    if medications:
        medication_text = "\n".join(
            m.get("name", "") for m in medications if m.get("name")
        )[:20000]

        if medication_text:
            response = cm.infer_rxnorm(Text=medication_text)
            for entity in response.get("Entities", []):
                concepts = entity.get("RxNormConcepts", [])
                if concepts and concepts[0].get("Score", 0) >= 0.80:
                    results["medications_coded"].append({
                        "name":         entity.get("Text"),
                        "rxnorm_cui":   concepts[0]["Code"],
                        "rxnorm_name":  concepts[0]["Description"],
                        "score":        concepts[0]["Score"]
                    })

    return results
```

---

## Step 8 and 9: FHIR Resource Assembly and HealthLake Import

```python
def generate_fallback_document_reference(
    chart_id: str,
    member_id: str,
    result: dict
) -> dict:
    """
    Generate a minimal valid FHIR DocumentReference when structured FHIR mapping fails.

    Called in assemble_fhir_bundle when the LLM FHIR mapping output is malformed or
    unparseable. Without this function, the fallback call raises a NameError, turning
    a graceful degradation into an unhandled exception.

    The generated resource records that the chart segment was digitized (the "we have
    this document" record) and flags it for manual review. It does NOT drop the chart.
    A non-zero fallback rate in CloudWatch is a signal worth investigating.
    [EDITOR: review fix - P1 undefined function. generate_fallback_document_reference
     was called in assemble_fhir_bundle but never defined. NameError here turned graceful
     fallback into an unhandled exception. Implemented with minimal valid FHIR output.]
    """
    segment_id = result.get("recordId", "unknown-segment")
    return {
        "resourceType": "DocumentReference",
        "status":       "current",
        "subject":      {"reference": f"Patient/{member_id}"},
        "type": {
            "coding": [{
                "system":  "http://loinc.org",
                "code":    "34133-9",
                "display": "Summary of episode note"
            }]
        },
        "note": [{
            "text": (
                f"FHIR mapping failed for chart {chart_id}, segment {segment_id}. "
                f"DocumentReference generated as fallback. Manual review recommended. "
                f"Original chart content preserved in S3 at "
                f"s3://{BUCKET_CHARTS_PROCESSED}/{chart_id}/chart.pdf."
            )
        }]
    }


def assemble_fhir_bundle(
    chart_id: str,
    member_id: str,
    extraction_results: list[dict]
) -> dict:
    """
    Assemble a FHIR R4 bundle from extraction results across all pages/tiers.

    Key FHIR rules for migrated records:
    1. verificationStatus = "unconfirmed" on all Condition resources (always)
    2. clinicalStatus is OMITTED entirely (no "unknown" code in condition-clinical ValueSet)
    3. MedicationStatement.status = "unknown" (historical, can't determine active/inactive)
    4. Every resource includes a note with provenance: chart ID, page range, OCR confidence
    5. Deduplicate: same ICD-10 code from multiple pages -> one Condition resource
    """
    all_resources = []

    # Always generate a DocumentReference for each document segment
    # This is the "we digitized this" record, even if structured extraction failed
    for seg in extraction_results:
        doc_ref = {
            "resourceType": "DocumentReference",
            "status":       "current",
            "subject":      {"reference": f"Patient/{member_id}"},
            "type": {
                "coding": [{"system": "http://loinc.org", "code": "34133-9",
                             "display": "Summary of episode note"}],
                "text": seg.get("doc_type", "clinical document")
            },
            "date": seg.get("document_date"),
            "content": [{
                "attachment": {
                    "contentType": "application/pdf",
                    "url": f"s3://{BUCKET_CHARTS_PROCESSED}/{chart_id}/chart.pdf"
                }
            }],
            "note": [{
                "text": (
                    f"Migrated from paper chart. Chart: {chart_id}. "
                    f"Pages {seg.get('start_page', '?')}-{seg.get('end_page', '?')}. "
                    f"OCR confidence: {seg.get('avg_confidence', 'unknown')}. "
                    f"Extraction tier: {seg.get('model_tier', 'unknown')}."
                )
            }]
        }
        all_resources.append(doc_ref)

        # Generate Condition resources for validated diagnoses
        for dx in seg.get("validated_codes", {}).get("diagnoses_coded", []):
            condition = {
                "resourceType": "Condition",
                # clinicalStatus intentionally omitted.
                # FHIR R4 does not require it, and the condition-clinical ValueSet
                # has no "unknown" code. HealthLake validates this and will reject
                # resources with invalid clinicalStatus values. Omitting is correct.
                "verificationStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code":   "unconfirmed",
                        "display": "Unconfirmed"
                    }]
                    # verificationStatus = unconfirmed for all OCR-derived records.
                    # Do NOT use "confirmed". These are historical OCR extractions,
                    # not clinician-verified entries.
                },
                "subject":      {"reference": f"Patient/{member_id}"},
                "code": {
                    "coding": [{
                        "system":  "http://hl7.org/fhir/sid/icd-10-cm",
                        "code":    dx["icd10_code"],
                        "display": dx["icd10_display"]
                    }],
                    "text": dx["description"]
                },
                "recordedDate": seg.get("document_date"),
                "note": [{
                    "text": (
                        f"Migrated from paper chart {chart_id}, "
                        f"pages {seg.get('start_page', '?')}-{seg.get('end_page', '?')}. "
                        f"ICD-10 mapping confidence: {dx.get('score', 'unknown'):.2f}."
                    )
                }]
            }
            all_resources.append(condition)

        # Generate MedicationStatement resources for validated medications
        for med in seg.get("validated_codes", {}).get("medications_coded", []):
            med_statement = {
                "resourceType": "MedicationStatement",
                "status":       "unknown",  # Historical record; cannot determine current status
                "subject":      {"reference": f"Patient/{member_id}"},
                "medicationCodeableConcept": {
                    "coding": [{
                        "system":  "http://www.nlm.nih.gov/research/umls/rxnorm",
                        "code":    med["rxnorm_cui"],
                        "display": med["rxnorm_name"]
                    }],
                    "text": med["name"]
                },
                "effectiveDateTime": seg.get("document_date"),
                "note": [{"text": f"Migrated from paper chart {chart_id}."}]
            }
            all_resources.append(med_statement)

    # Deduplicate Conditions: same ICD-10 code for the same member -> keep one
    seen_conditions = {}
    deduplicated    = []
    for resource in all_resources:
        if resource["resourceType"] != "Condition":
            deduplicated.append(resource)
            continue
        coding = resource.get("code", {}).get("coding", [{}])[0]
        key    = (member_id, coding.get("code", ""))
        if key not in seen_conditions:
            seen_conditions[key] = True
            deduplicated.append(resource)

    resource_counts = {}
    for r in deduplicated:
        rtype = r["resourceType"]
        resource_counts[rtype] = resource_counts.get(rtype, 0) + 1

    return {
        "resources":       deduplicated,
        "resource_counts": resource_counts,
        "total":           len(deduplicated)
    }


def write_fhir_bundle_and_update_dynamo(
    chart_id: str,
    bundle: dict
) -> str:
    """
    Write the FHIR bundle as NDJSON to S3 and update DynamoDB.
    Uses Decimal for all numeric DynamoDB values (boto3 requires this;
    Python float values will raise a TypeError on DynamoDB writes).
    """
    s3    = get_s3_client()
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)

    # Write FHIR NDJSON (one resource per line, no trailing comma, no array brackets)
    ndjson_content = "\n".join(json.dumps(r) for r in bundle["resources"]) + "\n"
    bundle_key     = f"fhir-bundles/{chart_id}/bundle.ndjson"

    s3.put_object(
        Bucket=BUCKET_FHIR_OUTPUT,
        Key=bundle_key,
        Body=ndjson_content.encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=KMS_KEY_ARN
    )

    # Update DynamoDB. ALL numeric values must be Decimal, never float.
    counts = bundle["resource_counts"]
    table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression=(
            "SET #s = :status, fhir_bundle_key = :key, "
            "fhir_total = :total, conditions_count = :cond, "
            "obs_count = :obs, med_count = :med, docref_count = :docref"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "fhir_ready",
            ":key":    bundle_key,
            ":total":  Decimal(str(bundle["total"])),
            ":cond":   Decimal(str(counts.get("Condition", 0))),
            ":obs":    Decimal(str(counts.get("Observation", 0))),
            ":med":    Decimal(str(counts.get("MedicationStatement", 0))),
            ":docref": Decimal(str(counts.get("DocumentReference", 0)))
        }
    )

    logger.info(
        "FHIR bundle written",
        extra={
            "chart_id":    chart_id,
            "total":       bundle["total"],
            "conditions":  counts.get("Condition", 0),
            "medications": counts.get("MedicationStatement", 0)
            # Resource counts are not PHI; safe to log
        }
    )
    return bundle_key


def submit_healthlake_import_batch(
    batch_size: int = 2000,
    datastore_id: str = HEALTHLAKE_DATASTORE_ID
) -> Optional[str]:
    """
    Aggregate fhir_ready charts and submit a HealthLake bulk FHIR import job.

    Strategy: copy all FHIR NDJSON files for the batch to a timestamped import
    prefix, then submit StartFHIRImportJob pointing to that prefix.

    HealthLake's StartFHIRImportJob takes an S3 URI pointing to a prefix or file
    of FHIR NDJSON resources, not a manifest listing other manifests. This is a
    common confusion. The input is the FHIR data itself, not a list of S3 keys.
    """
    s3    = get_s3_client()
    ddb   = get_dynamodb_resource().Table(TABLE_MIGRATION)
    hlake = get_healthlake_client()

    # Find charts ready for import
    response   = ddb.scan(
        FilterExpression="attribute_exists(chart_id) AND #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "fhir_ready"},
        Limit=batch_size
    )
    ready_charts = response.get("Items", [])

    if not ready_charts:
        logger.info("No charts ready for HealthLake import")
        return None

    # Stage FHIR NDJSON files in an import-specific prefix
    timestamp      = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    import_prefix  = f"fhir-imports/{timestamp}/"

    for chart in ready_charts:
        chart_id   = chart["chart_id"]
        bundle_key = chart.get("fhir_bundle_key")
        if not bundle_key:
            continue

        dest_key = f"{import_prefix}{chart_id}.ndjson"
        s3.copy_object(
            CopySource={"Bucket": BUCKET_FHIR_OUTPUT, "Key": bundle_key},
            Bucket=BUCKET_FHIR_STAGING,
            Key=dest_key,  # [EDITOR: Fixed boto3 bug. "Destination" is not a valid copy_object parameter; the correct kwarg is "Key". Using "Destination" raises a TypeError at runtime.]
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=KMS_KEY_ARN
        )

    # Submit HealthLake import job
    response = hlake.start_fhir_import_job(
        InputDataConfig={
            "S3Uri": f"s3://{BUCKET_FHIR_STAGING}/{import_prefix}"
        },
        JobOutputDataConfig={
            "S3Configuration": {
                "S3Uri":    f"s3://{BUCKET_FHIR_OUTPUT}/import-results/{timestamp}/",
                "KmsKeyId": KMS_KEY_ARN
            }
        },
        DatastoreId=datastore_id,
        DataAccessRoleArn=HEALTHLAKE_IMPORT_ROLE_ARN
    )

    import_job_id = response["JobId"]

    # Mark charts as import_submitted
    with ddb.batch_writer() as writer:
        for chart in ready_charts:
            writer.put_item(Item={
                **chart,
                "status":            "import_submitted",
                "healthlake_job_id": import_job_id
            })

    logger.info(
        "HealthLake import submitted",
        extra={"job_id": import_job_id, "chart_count": len(ready_charts)}
    )
    return import_job_id
```

---

## Step 10: Source Chart Archival

```python
def mark_chart_archived(chart_id: str, s3_key: str) -> None:
    """
    Tag the source chart S3 object to trigger the S3 Lifecycle rule that
    transitions it to Glacier Instant Retrieval after 30 days.

    The lifecycle rule (configured once at bucket creation) moves tagged objects
    to Glacier IR after 30 days and expires them after 10 years (3,653 days).
    This is automated. No per-chart API calls to Glacier are needed.
    """
    s3    = get_s3_client()
    table = get_dynamodb_resource().Table(TABLE_MIGRATION)

    # Tag the S3 object to trigger the lifecycle transition
    s3.put_object_tagging(
        Bucket=BUCKET_CHARTS_RAW,
        Key=s3_key,
        Tagging={
            "TagSet": [
                {"Key": "migration-status", "Value": "completed"}
            ]
        }
    )

    # Update DynamoDB to final status
    table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression="SET #s = :status, completed_at = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "completed",
            ":ts":     datetime.now(timezone.utc).isoformat()
        }
    )

    logger.info("Chart archived", extra={"chart_id": chart_id})
```

---

## Full Pipeline Orchestration

```python
def run_chart_migration_wave(
    s3_prefix:   str,
    wave_label:  str,
    region:      str = "us-east-1"
) -> dict:
    """
    Run a complete migration wave for all charts under s3_prefix.

    A "wave" is a batch of charts processed together. In production, you run
    many waves over the course of the migration program. Each wave:
    1. Generates a manifest and initializes DynamoDB records
    2. Starts Textract OCR on all charts (async, returns quickly)
    3. Waits for OCR completion, then generates classification JSONL
    4. Submits Nova Lite classification batch job
    5. Waits for classification results, routes pages to tiers
    6. Generates extraction JSONL for all tiers
    7. Submits extraction batch jobs (Tier 2, Tier 3 vision, Tier 4 vision)
    8. Waits for extraction results, runs Comprehend Medical code validation
    9. Assembles FHIR bundles, writes to S3
    10. Submits HealthLake import batch
    11. Tags source charts for Glacier archival

    Note: in production this orchestration lives in AWS Step Functions, not a
    single Python function. Each step is a Lambda or ECS task. The Step Functions
    execution history is how you debug failures across a multi-month program.
    This function is for illustrative/testing purposes.
    """
    print(f"\n=== Starting migration wave: {wave_label} ===")

    # Step 1: Manifest
    manifest_key_output = f"manifests/{wave_label}.csv"
    chart_count, manifest_key = generate_migration_manifest(s3_prefix, manifest_key_output)
    print(f"Manifest generated: {chart_count} charts")

    if chart_count == 0:
        print("No new charts to process. Wave complete.")
        return {"wave_label": wave_label, "charts": 0}

    # Step 2+3: Pre-process and OCR (per chart, in parallel via AWS Batch in production)
    # For illustration: process the first chart synchronously
    s3 = get_s3_client()
    response = s3.get_object(Bucket="manifests", Key=manifest_key)
    csv_lines = response["Body"].read().decode("utf-8").strip().split("\n")

    for line in csv_lines[1:2]:  # Process just the first chart for illustration
        _, chart_key, chart_id = line.split(",")

        print(f"\nProcessing chart: {chart_id}")

        # Pre-process
        processed_key, preprocess_report = preprocess_chart(chart_key, chart_id)
        print(f"  Pre-processed: {preprocess_report['total_pages']} pages, "
              f"{preprocess_report['blank_pages_skipped']} blank skipped")

        # OCR
        textract_job_id = start_textract_ocr(processed_key, chart_id)
        print(f"  Textract job started: {textract_job_id}")
        print("  [In production: wait for SNS notification, then proceed]")
        print("  [This example assumes OCR is complete and quality data exists in S3]")

        # Assume OCR results exist for illustration
        quality_key = f"textract-output/{chart_id}/page-quality.json"

        # Classification JSONL generation
        classify_jsonl_key = generate_classification_batch_jsonl(chart_id, quality_key)
        print(f"  Classification JSONL: {classify_jsonl_key}")

        # Submit classification batch job
        classify_job_arn = submit_bedrock_batch_job(
            input_s3_prefix=f"batch-input/{chart_id}/",
            output_s3_prefix=f"batch-output/{chart_id}/classify/",
            model_id=MODEL_TIER1_CLASSIFY,
            job_name=f"classify-{chart_id}-{wave_label}"
        )
        print(f"  Classification job: {classify_job_arn}")
        print("  [In production: await EventBridge event for job completion]")
        print("  [Batch jobs complete within 24h at 50% of on-demand pricing]")

        # In production, the Step Functions state machine pauses here and resumes
        # when the batch job completion event fires. For illustration, we skip
        # forward to the extraction steps.
        print("\n  [Skipping to extraction illustration. See recipe for full flow.]")

    return {
        "wave_label":   wave_label,
        "charts":       chart_count,
        "manifest_key": manifest_key
    }


if __name__ == "__main__":
    # Example usage: process charts from a specific scanning vendor batch
    result = run_chart_migration_wave(
        s3_prefix="2026/03/scanning-vendor-batch-001/",
        wave_label="march-2026-wave-001"
    )
    print(f"\nWave complete: {result}")
```

---

## Gap to Production

This example demonstrates the API patterns and data structures. A production chart migration program needs everything below.

**Retry configuration.** Every boto3 client must use `Config(retries={"max_attempts": 3, "mode": "adaptive"})`. This is already shown in the factory functions above. Make sure it is not removed in production refactoring. Throttling from Bedrock and Comprehend Medical is expected under load, not an edge case.

**Lambda timeouts.** Set all Lambda timeouts significantly above the default 3 seconds:
- Functions calling Bedrock synchronously: 5 to 15 minutes
- Functions loading Textract block output for large charts: 10 minutes minimum
- Functions assembling FHIR bundles for large charts: 10 minutes minimum
- Memory: 512MB minimum for functions loading Textract block data; 1GB for large charts

**PHI-safe logging.** Every `print()` and `logger` call in this example uses structured metadata only (chart IDs, page counts, job ARNs, status codes). Never log `output_text`, `page_text`, extracted clinical content, or LLM reasoning strings. CloudWatch log groups for Lambda functions are not encrypted by default; configure KMS encryption on every log group that may receive any derivative of PHI.

**Prompt injection sanitization.** The `sanitize_page_text()` function above is a starting point. Add Bedrock Guardrails with PII detection and content filtering via the `guardrailConfig` parameter in every Converse API call. The commented-out stub in `generate_classification_batch_jsonl()` shows where to wire it in.

**DynamoDB Decimal requirement.** All numeric values stored in DynamoDB must be `Decimal`, not Python `float`. This example uses `Decimal(str(value))` throughout. The `floats_to_decimal()` helper is a common pattern; implement it as a utility function and call it on any nested structure before DynamoDB writes. Floating-point DynamoDB writes raise `TypeError: Float types are not supported. Use Decimal types instead` at runtime.

**Bedrock batch inference JSONL format.** The exact JSONL schema for batch inference differs between Nova models (using `schemaVersion: "messages-v1"`) and the Converse API format. Check the Bedrock batch inference documentation for the current per-model input schema. The schemas are close but not identical, and mixing them causes silent job failures where all records return error status.

**Batch inference result file streaming.** Result JSONL files for jobs with 100,000+ requests can be multi-gigabyte. Do not load them entirely into memory. Use `get_object` with streaming and process line by line:
```python
response = s3.get_object(Bucket=..., Key=...)
for line in response["Body"].iter_lines():
    result = json.loads(line)
    # process one record at a time
```

**AWS Batch array job size limit.** Array jobs cap at 10,000 child jobs. For millions of charts, either submit multiple manifests in 10,000-chart chunks or switch to an SQS-based model where Batch workers pull chart IDs from a queue without relying on array indexing. The SQS model is more flexible for large programs but requires more orchestration infrastructure.

**Model version pinning.** Replace cross-region inference profile IDs with explicit foundation model ARNs before production:
```python
# Development (cross-region, may update)
MODEL_TIER1_CLASSIFY = "us.amazon.nova-lite-v1:0"

# Production (pinned version ARN, verify format in Bedrock docs for your region)
MODEL_TIER1_CLASSIFY = "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
```
Run a regression test on a sample of charts after any model update before continuing bulk processing.

**VPC endpoints.** All Lambda functions and Batch containers must be in a VPC with no public internet egress. Ensure you have both `com.amazonaws.REGION.bedrock-runtime` (for Converse API calls) and `com.amazonaws.REGION.bedrock` (for batch job control plane) as VPC interface endpoints. These are two separate endpoints; deploying only one will cause API calls to the other to fail in a no-egress VPC.

**Bedrock batch inference and S3 bucket policies.** Bedrock batch inference reads input JSONL and writes output JSONL using `BEDROCK_BATCH_ROLE_ARN` on AWS's internal network, not through your VPC S3 gateway endpoint. If your `batch-inference` bucket policy restricts access to VPC traffic via `aws:SourceVpc` or `aws:SourceVpcEndpoint` conditions, batch jobs will fail with S3 access denied errors. Add an explicit bucket policy statement allowing `BEDROCK_BATCH_ROLE_ARN` without a VPC condition, or structure your bucket access control through IAM role policies rather than bucket VPC conditions for the `batch-inference` bucket. The `configure_batch_inference_bucket_lifecycle()` function includes a comment showing the required policy statement. <!-- [EDITOR: review fix - P1 VPC/S3. Added Gap to Production entry matching the prerequisite note in the recipe.] -->

**Vision JSONL file sizes.** A 300 DPI PNG page runs 1 to 3 MB raw, which becomes 1.3 to 4 MB base64-encoded in the batch JSONL. For a wave with 10,000 vision-path pages, the input JSONL reaches 13 to 40 GB. Do not write the entire wave into one JSONL file. Split vision batches into files of 2,000 to 3,000 pages before submission. For files over 5 GB, configure boto3 `TransferConfig(multipart_threshold=5 * 1024**3, multipart_chunksize=500 * 1024**2)` on the `put_object` call. Consider downsampling 600 DPI source images to 300 DPI before embedding; this cuts base64 payload size by approximately 75% with negligible vision model accuracy impact. <!-- [EDITOR: review fix - P1 vision JSONL file sizes. Added Gap to Production entry with concrete boto3 guidance.] -->

**Comprehend Medical regional availability.** Comprehend Medical is not available in all regions. If your target region is unsupported, implement a fallback using a Bedrock-based code extraction prompt. Note that LLMs are less reliable than Comprehend Medical for exact ICD-10/RxNorm code generation; add a code lookup validation step against an authoritative reference dataset.

**FHIR resource validation before HealthLake import.** Run generated FHIR NDJSON through a FHIR validator (the `fhir.resources` Python library or the HAPI FHIR validator) before submitting to HealthLake. The two most common issues: Condition resources with `clinicalStatus` included (HealthLake validates against the condition-clinical ValueSet and rejects resources with codes not in the set, including any attempt to use "unknown") and MedicationStatement resources missing required fields. Validation failures produce silent import errors in HealthLake that can be difficult to diagnose after the fact.

**Testing.** Use synthetic data (Synthea) or fully de-identified charts for all development and QA environments. Never use real PHI in any environment below production. Configure separate Bedrock models, DynamoDB tables, S3 buckets, and HealthLake data stores per environment. Use infrastructure-as-code (CDK or CloudFormation) to keep environments consistent.

---

*[← Recipe 1.9 Python Example](chapter01.09-medical-records-python-v1) · [↑ Recipe 1.10 Main](chapter01.10-chart-migration-v1) · [Chapter 1 Index →](chapter01-index)*
