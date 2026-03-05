# Recipe 1.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.10. It shows how you could translate those concepts into working Python using boto3. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire into a live migration program on Monday morning. A starting point, not a destination.
>
> This is the capstone companion file for Chapter 1. Every pattern from Recipes 1.1 through 1.6 shows up here in some form. The image preprocessing is from Recipe 1.6. The boundary detection and document segmentation code extends Recipe 1.5. The handwriting confidence tiering and A2I submission follows Recipe 1.6 exactly. If you haven't read those companions yet, start there; especially Recipe 1.5 for segmentation and Recipe 1.6 for the A2I plumbing. This file builds directly on top of them.
>
> What is new in this recipe is the outer-loop orchestration (AWS Batch manifest and job submission), the extended chart document taxonomy, the quality scoring framework that runs after extraction, the FHIR R4 resource mapping, and the HealthLake bulk import step. Those are the additions. Everything else is a pattern you have already seen assembled in a new configuration.
>
> In production, the outer loop is an AWS Batch array job distributing millions of charts across a Spot instance fleet. The inner loop is a Step Functions Standard Workflow for each chart. This script runs all ten steps sequentially in a single process so you can trace the logic from manifest generation through S3 archival without standing up any of that infrastructure first. The logic is the same; only the execution model differs.

---

## Setup

You will need the AWS SDK for Python and a handful of supporting libraries:

```bash
pip install boto3 Pillow
```

For production-quality image deskewing, also install:

```bash
pip install deskew opencv-python-headless
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `textract:StartDocumentAnalysis`
- `textract:GetDocumentAnalysis`
- `comprehendmedical:DetectEntitiesV2`
- `comprehendmedical:InferICD10CM`
- `comprehendmedical:InferRxNorm`
- `sagemaker:StartHumanLoop`
- `sagemaker:DescribeHumanLoop`
- `batch:SubmitJob`
- `batch:DescribeJobs`
- `healthlake:StartFHIRImportJob`
- `healthlake:DescribeFHIRImportJob`
- `s3:GetObject`
- `s3:PutObject`
- `s3:PutObjectTagging`
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:UpdateItem`
- `dynamodb:Query`
- `dynamodb:BatchWriteItem`
- `states:StartExecution`
- `sns:Publish`

The A2I runtime client uses the `sagemaker-a2i-runtime` service endpoint, not the main `sagemaker` endpoint. Two different boto3 clients. Easy to miss.

---

## Configuration and Constants

Everything that is really configuration rather than logic lives at the top. The document taxonomy, keyword signatures, quality weights, and FHIR mappings are living documents. They grow as you encounter new chart formats and new scanning vendor outputs. Keeping them here rather than buried inside functions makes them easy to update without touching logic.

```python
import boto3
from botocore.exceptions import ClientError
import csv
import datetime
import io
import json
import re
import time
import uuid
from datetime import timezone
from decimal import Decimal

from PIL import Image, ImageOps, ImageFilter


# -----------------------------------------------------------------------
# S3 bucket names
# -----------------------------------------------------------------------
CHARTS_RAW_BUCKET       = "charts-raw"         # scanning vendor drops source PDFs here
CHARTS_PROCESSED_BUCKET = "charts-processed"   # pre-processed PDFs written here
TEXTRACT_OUTPUT_BUCKET  = "textract-output"     # raw Textract block JSON lives here
FHIR_OUTPUT_BUCKET      = "fhir-output"         # FHIR NDJSON bundles and HL import manifests

# -----------------------------------------------------------------------
# DynamoDB table names
# -----------------------------------------------------------------------
MIGRATION_TABLE = "migration-tracking"   # per-chart state, quality scores, job IDs

# -----------------------------------------------------------------------
# A2I and FHIR configuration
# -----------------------------------------------------------------------
A2I_FLOW_ARN              = "arn:aws:sagemaker:us-east-1:ACCOUNT:flow-definition/chart-review"
HEALTHLAKE_DATASTORE_ID   = ""    # set from your HealthLake data store
HEALTHLAKE_IMPORT_ROLE_ARN = "arn:aws:iam::ACCOUNT:role/healthlake-import-role"
KMS_KEY_ARN               = "arn:aws:kms:us-east-1:ACCOUNT:key/YOUR-KEY-ID"

# -----------------------------------------------------------------------
# AWS Batch configuration
# -----------------------------------------------------------------------
BATCH_JOB_QUEUE      = "chart-migration-queue"
BATCH_JOB_DEFINITION = "chart-migration-job-def"

# -----------------------------------------------------------------------
# Handwriting confidence thresholds (from Recipe 1.6)
# Calibrate these after your first 500-chart sample run.
# These are starting points.
# -----------------------------------------------------------------------
HIGH_CONFIDENCE_THRESHOLD   = 0.85   # auto-accept; no A2I review needed
LOW_CONFIDENCE_THRESHOLD    = 0.60   # below this: send to A2I for human review
# Pages between 0.60 and 0.85: extract but mark as unconfirmed

# -----------------------------------------------------------------------
# Comprehend Medical limits
# -----------------------------------------------------------------------
COMPREHEND_MAX_CHARS = 18000   # stay well below the 20,000 char API limit
ICD10_MIN_CONFIDENCE = 0.80    # ICD-10 codes below this go to the flagged list

# -----------------------------------------------------------------------
# Quality scoring weights (must sum to 1.0)
# -----------------------------------------------------------------------
QUALITY_WEIGHTS = {
    "ocr_confidence":         0.30,
    "class_confidence":       0.25,
    "extraction_completeness": 0.25,
    "handwriting_review_rate": 0.20,
}

# -----------------------------------------------------------------------
# Minimum content expected per document type for completeness scoring
# -----------------------------------------------------------------------
EXPECTED_CONTENT = {
    "progress_note":       ["entities", "document_date"],
    "lab_result":          ["entities", "document_date"],
    "radiology_report":    ["entities", "document_date"],
    "discharge_summary":   ["icd10_accepted", "document_date"],
    "operative_report":    ["icd10_accepted", "document_date"],
    "medication_list":     ["entities"],
    "immunization_record": ["entities", "document_date"],
}

# -----------------------------------------------------------------------
# Document boundary detection: title line patterns
# Extends the pattern list from Recipe 1.5 with chart-specific document types.
# When you encounter a new document type that the segmenter consistently
# misses, add its title variants here first. That is usually all it takes.
# -----------------------------------------------------------------------
CHART_DOCUMENT_TITLE_PATTERNS = [
    # Clinical notes
    "progress note",        "office visit",          "follow-up visit",
    "return visit",         "new patient visit",     "annual exam",
    "history and physical", "h&p",
    # Reports
    "operative report",     "operative note",        "op report",
    "pathology report",     "histology report",
    "radiology report",     "x-ray report",          "mri report",
    "ct report",            "ultrasound report",
    "ecg report",           "ekg report",            "echocardiogram",
    # Hospital-based documents
    "discharge summary",    "discharge instructions",
    "hospital admission",   "inpatient note",
    "emergency department", "er visit",              "urgent care",
    # Specialty notes
    "referral letter",      "consultation report",   "consultant report",
    "physical therapy",     "occupational therapy",  "speech therapy",
    # Lists and summaries
    "problem list",         "medication list",       "active medications",
    "allergy list",         "drug allergies",
    "immunization record",  "vaccination record",    "vaccine history",
]

# -----------------------------------------------------------------------
# Document type classification signatures
# Each entry: keywords to match against the full segment text, and the
# minimum number of matches required to accept the classification.
# -----------------------------------------------------------------------
CHART_DOC_TYPE_SIGNATURES = {
    "progress_note": {
        "keywords": [
            "progress note", "office visit", "follow-up", "soap",
            "subjective", "objective", "assessment", "plan",
            "chief complaint", "history of present illness",
            "review of systems", "physical examination",
            "impression", "return in",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "history_and_physical": {
        "keywords": [
            "history and physical", "h&p", "chief complaint",
            "past medical history", "surgical history", "family history",
            "social history", "medications", "allergies",
            "review of systems", "physical exam", "assessment and plan",
        ],
        "min_matches": 4,
        "table_bonus": 0,
    },
    "lab_result": {
        "keywords": [
            "laboratory", "lab results", "specimen", "collected",
            "reference range", "result", "units", "flag",
            "complete blood count", "metabolic panel", "urinalysis",
            "culture", "sensitivity", "normal range",
        ],
        "min_matches": 3,
        "table_bonus": 2,   # lab results are almost always table-heavy
    },
    "radiology_report": {
        "keywords": [
            "radiology", "radiologist", "imaging", "impression",
            "findings", "technique", "clinical history",
            "x-ray", "mri", "ct scan", "ultrasound",
            "views", "comparison",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "discharge_summary": {
        "keywords": [
            "discharge summary", "admitting diagnosis",
            "discharge diagnosis", "hospital course",
            "discharge medications", "follow-up instructions",
            "length of stay", "attending physician",
            "discharge condition",
        ],
        "min_matches": 4,
        "table_bonus": 0,
    },
    "operative_report": {
        "keywords": [
            "operative report", "preoperative diagnosis",
            "postoperative diagnosis", "procedure performed",
            "anesthesia", "estimated blood loss",
            "operative technique", "findings", "specimen",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "consultation_report": {
        "keywords": [
            "consultation", "consultant", "referred by",
            "reason for consultation", "clinical summary",
            "recommendations", "thank you for referring",
            "your patient",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "immunization_record": {
        "keywords": [
            "immunization", "vaccine", "vaccination",
            "administered", "lot number", "manufacturer",
            "injection site", "influenza", "tetanus", "mmr",
        ],
        "min_matches": 2,
        "table_bonus": 1,
    },
    "problem_list": {
        "keywords": [
            "problem list", "active problems", "medical problems",
            "chronic conditions", "diagnosis list",
            "onset date", "resolved", "active",
        ],
        "min_matches": 2,
        "table_bonus": 0,
    },
    "medication_list": {
        "keywords": [
            "medication list", "current medications", "active medications",
            "prescription", "dose", "frequency", "refills",
            "sig:", "dispense", "pharmacy",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
}

# -----------------------------------------------------------------------
# FHIR LOINC codes for DocumentReference type by document category
# -----------------------------------------------------------------------
LOINC_BY_DOC_TYPE = {
    "progress_note":       ("11506-3", "Progress note"),
    "history_and_physical": ("34117-2", "History and physical note"),
    "lab_result":          ("11502-2", "Laboratory report"),
    "radiology_report":    ("18748-4", "Diagnostic imaging study"),
    "discharge_summary":   ("18842-5", "Discharge summary"),
    "operative_report":    ("11504-8", "Surgical operation note"),
    "consultation_report": ("11488-4", "Consult note"),
    "immunization_record": ("11369-6", "Immunization activity"),
    "problem_list":        ("11450-4", "Problem list"),
    "medication_list":     ("29549-3", "Medication administered"),
    "unclassified":        ("34133-9", "Summarization of episode note"),
}

# -----------------------------------------------------------------------
# CVX codes for common vaccines (subset for illustration)
# Expand from the CDC CVX code table for production use.
# -----------------------------------------------------------------------
CVX_LOOKUP = {
    "influenza":  "141",
    "flu":        "141",
    "tetanus":    "115",
    "tdap":       "115",
    "mmr":        "03",
    "varicella":  "21",
    "chickenpox": "21",
    "hepatitis b": "08",
    "hep b":      "08",
    "pneumococcal": "33",
    "pneumovax":  "33",
    "covid":      "212",
    "covid-19":   "212",
}

# -----------------------------------------------------------------------
# AWS clients (module-level for Lambda warm container reuse)
# -----------------------------------------------------------------------
textract_client    = boto3.client("textract")
comprehend_client  = boto3.client("comprehendmedical")
s3_client          = boto3.client("s3")
dynamodb           = boto3.resource("dynamodb")
batch_client       = boto3.client("batch")
sfn_client         = boto3.client("stepfunctions")
healthlake_client  = boto3.client("healthlake")
a2i_client         = boto3.client("sagemaker-a2i-runtime")
```

---

## Helper Functions

Shared utilities used across multiple steps. The boundary detection helpers (`extract_header_region`, `compute_jaccard_similarity`, `extract_primary_date_from_text`) are carried forward from Recipe 1.5 and are reproduced here for completeness.

```python
# Date format patterns (in preference order: more specific first)
_DATE_FORMATS = [
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
]

_DATE_PATTERNS = [
    r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",
    r"\b(\d{4}-\d{2}-\d{2})\b",
    r"\b((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4})\b",
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\.?\s+\d{1,2},?\s+\d{4})\b",
]


def extract_primary_date_from_text(text: str) -> datetime.date | None:
    """
    Find the first parseable date in a text string and return it as a date object.
    Returns None if no date is found. Used in boundary detection and FHIR mapping.
    """
    if not text:
        return None

    for pattern in _DATE_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        date_string = match.group(1).strip().rstrip(",")
        for fmt in _DATE_FORMATS:
            try:
                return datetime.datetime.strptime(date_string, fmt).date()
            except ValueError:
                continue

    return None


def extract_header_region(page_blocks: list) -> str:
    """
    Extract text from the top 15% of a page (bounding box Top < 0.15).
    This is where document titles, facility names, and date stamps live.
    Used by boundary detection to compare adjacent page headers.
    """
    header_lines = []
    for block in page_blocks:
        if block.get("BlockType") != "LINE":
            continue
        top = block.get("Geometry", {}).get("BoundingBox", {}).get("Top", 1.0)
        if top < 0.15:
            text = block.get("Text", "").strip()
            if text:
                header_lines.append(text)
    return "\n".join(header_lines).strip()


def compute_jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Compute word-level Jaccard similarity between two text strings.
    Returns 1.0 for identical texts, 0.0 for completely disjoint texts.
    Used in boundary detection to catch document type transitions via header changes.
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def split_text_with_overlap(text: str, max_chars: int = 18000, overlap: int = 500) -> list[str]:
    """
    Split a long text string into chunks with character overlap between them.
    The overlap prevents Comprehend Medical from dropping entities that fall
    at a chunk boundary. Returns a list of text strings.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start  = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start = end - overlap

    return chunks
```

---

## Step 1: Manifest Generation and Batch Job Submission

Before any chart gets processed, we need an inventory. The manifest is a CSV file with one row per chart. AWS Batch reads it to distribute work across the fleet. We also initialize a DynamoDB tracking record for each chart here, which becomes the idempotency guard: charts with `status = completed` are skipped.

```python
def generate_migration_manifest(
    s3_prefix: str,
    manifest_output_key: str,
) -> tuple[int, str]:
    """
    List all chart PDFs under s3_prefix, write a CSV manifest, and initialize
    DynamoDB tracking records for any charts not already completed.

    The manifest format (one row per chart) is what AWS Batch uses to assign
    work to individual array job children. Each child uses its array index to
    select its row from the manifest.

    Args:
        s3_prefix:           S3 key prefix for the batch of charts to process.
                             Example: "charts-raw/2024/batch-001/"
        manifest_output_key: S3 key where the CSV manifest should be written.
                             Example: "manifests/batch-001.csv"

    Returns:
        A tuple of (chart_count, manifest_s3_key) for use in the Batch submission.
    """
    migration_table = dynamodb.Table(MIGRATION_TABLE)

    # List all objects under the given prefix.
    paginator    = s3_client.get_paginator("list_objects_v2")
    chart_objects = []

    for page in paginator.paginate(Bucket=CHARTS_RAW_BUCKET, Prefix=s3_prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".pdf"):
                chart_objects.append(obj)

    manifest_rows  = []
    dynamo_batch   = []
    skipped        = 0

    for obj in chart_objects:
        key      = obj["Key"]
        # Convention: the scanning vendor encodes the chart ID in the filename.
        # Example key: charts-raw/2024/batch-001/CHT-2024-000421.pdf
        # Agree on this naming convention before scanning starts.
        chart_id = obj["Key"].split("/")[-1].replace(".pdf", "")

        # Idempotency check: skip charts that already completed.
        response  = migration_table.get_item(Key={"chart_id": chart_id})
        existing  = response.get("Item")
        if existing and existing.get("status") == "completed":
            skipped += 1
            continue

        manifest_rows.append({
            "bucket":   CHARTS_RAW_BUCKET,
            "key":      key,
            "chart_id": chart_id,
        })

        dynamo_batch.append({
            "PutRequest": {
                "Item": {
                    "chart_id":   chart_id,
                    "s3_key":     key,
                    "status":     "pending",
                    "created_at": datetime.datetime.now(timezone.utc).isoformat(),
                    "page_count": None,
                    "doc_count":  None,
                    "quality_score": None,
                }
            }
        })

    print(
        f"Manifest: {len(manifest_rows)} charts to process, "
        f"{skipped} already completed and skipped."
    )

    if not manifest_rows:
        return 0, ""

    # Write the CSV manifest to S3.
    csv_buffer = io.StringIO()
    writer     = csv.DictWriter(csv_buffer, fieldnames=["bucket", "key", "chart_id"])
    writer.writeheader()
    writer.writerows(manifest_rows)

    s3_client.put_object(
        Bucket=CHARTS_RAW_BUCKET,
        Key=manifest_output_key,
        Body=csv_buffer.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )

    # Batch-write DynamoDB records (25 items per batch_write_item call).
    for i in range(0, len(dynamo_batch), 25):
        chunk = dynamo_batch[i:i + 25]
        dynamodb.batch_write_item(RequestItems={MIGRATION_TABLE: chunk})

    print(f"Manifest written to s3://{CHARTS_RAW_BUCKET}/{manifest_output_key}")
    return len(manifest_rows), manifest_output_key


def submit_batch_migration_job(manifest_key: str, chart_count: int) -> str:
    """
    Submit an AWS Batch array job to process all charts in the manifest.

    An array job runs N identical copies of the same job definition. Each copy
    receives a unique AWS_BATCH_JOB_ARRAY_INDEX environment variable (0 to N-1)
    that the job handler uses to select its row from the manifest CSV.

    Args:
        manifest_key: S3 key of the manifest CSV (in CHARTS_RAW_BUCKET)
        chart_count:  number of charts in the manifest (sets the array size)

    Returns:
        The Batch array job ID.
    """
    response = batch_client.submit_job(
        jobName=f"chart-migration-{datetime.datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
        jobQueue=BATCH_JOB_QUEUE,
        jobDefinition=BATCH_JOB_DEFINITION,
        arrayProperties={"size": chart_count},
        parameters={"manifest_key": manifest_key},
    )

    job_id = response["jobId"]
    print(f"Submitted Batch array job {job_id} with {chart_count} child jobs.")
    return job_id
```

---

## Step 2: Image Quality Pre-Processing

Each page needs quality assessment and correction before Textract sees it. The fixes here are cheap. Discovering bad OCR output after paying for Textract on a 200-page chart and then paying to re-process it is not cheap. Fix the image first.

```python
def preprocess_chart(chart_pdf_key: str) -> tuple[str, dict]:
    """
    Download a chart PDF from S3, apply per-page quality corrections,
    reassemble, and write the processed PDF to the charts-processed bucket.

    Three operations per page: blank page detection (skip), rotation correction,
    and contrast enhancement. Deskew is noted but requires the deskew library
    for reliable angle estimation; see the Gap to Production section.

    Args:
        chart_pdf_key: S3 key of the source chart PDF in CHARTS_RAW_BUCKET

    Returns:
        A tuple of (processed_key, quality_report_dict).
        The processed key points to the enhanced PDF in CHARTS_PROCESSED_BUCKET.
    """
    # For a real deployment, use a PDF library (PyMuPDF or pdf2image) to
    # split the PDF into pages and convert to images. This stub illustrates
    # the per-page processing logic; replace load_pdf_pages with your PDF library.
    #
    # import fitz   # PyMuPDF
    # pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    # pages = [(i+1, pdf_doc[i].get_pixmap(dpi=300)) for i in range(len(pdf_doc))]

    response  = s3_client.get_object(Bucket=CHARTS_RAW_BUCKET, Key=chart_pdf_key)
    pdf_bytes = response["Body"].read()

    quality_report = {
        "total_pages":          0,
        "blank_pages_skipped":  0,
        "rotations_corrected":  0,
        "deskews_applied":      0,
        "low_dpi_warnings":     0,
    }

    # Stub: in real code, split the PDF into PIL Images here.
    # processed_pages is a list of PIL Image objects after correction.
    processed_pages = []

    # The actual per-page logic is shown below as a function you would call
    # inside your page iteration loop.
    processed_key = "charts-processed/" + chart_pdf_key.replace("charts-raw/", "")

    # After processing all pages and reassembling the PDF, upload to S3.
    # s3_client.put_object(
    #     Bucket=CHARTS_PROCESSED_BUCKET,
    #     Key=processed_key,
    #     Body=reassembled_pdf_bytes,
    # )

    return processed_key, quality_report


def is_blank_page(img: Image.Image, white_threshold: float = 0.98) -> bool:
    """
    Return True if more than white_threshold fraction of pixels are near-white.
    Catches blank pages and pure-white separator sheets. Works on grayscale
    and color images. Threshold of 0.98 allows for scanner noise at the edges.
    """
    grayscale    = img.convert("L")
    pixels       = list(grayscale.getdata())
    white_count  = sum(1 for p in pixels if p > 240)
    return (white_count / len(pixels)) > white_threshold


def enhance_page(img: Image.Image) -> Image.Image:
    """
    Apply contrast enhancement and noise reduction to a single page image.
    This is the Pillow-based version. See Gap to Production for the deskew upgrade.
    """
    # Convert to grayscale for consistent processing.
    img = img.convert("L")

    # Autocontrast: stretch the histogram so the darkest ink becomes black
    # and the background becomes white. The cutoff=1 ignores the extreme 1%
    # of pixels so a single dark smudge doesn't collapse the correction.
    img = ImageOps.autocontrast(img, cutoff=1)

    # Median filter: removes scanner noise and compression artifacts while
    # preserving the edges of handwritten letter strokes. Size=3 is conservative.
    img = img.filter(ImageFilter.MedianFilter(size=3))

    return img
```

---

## Step 3: Async Textract Extraction

Same async pattern as Recipe 1.2, with LAYOUT added to the feature types. LAYOUT is what gives us the title blocks that drive boundary detection in Step 4. We also store the Textract job ID in DynamoDB for debugging: when a 300-page chart produces unexpected output, you want to be able to pull up the raw blocks without re-running the job.

```python
def start_chart_extraction(processed_chart_key: str, chart_id: str) -> str:
    """
    Submit a processed chart PDF to Textract for async analysis.

    FORMS extracts key-value pairs from any structured form fields.
    TABLES extracts grid-structured lab results and medication tables.
    LAYOUT provides title blocks, headers, and paragraph markers used
    in document segmentation (Step 4). Including LAYOUT is what makes
    boundary detection reliable on charts with multiple document types.

    Args:
        processed_chart_key: S3 key in CHARTS_PROCESSED_BUCKET
        chart_id:            chart identifier for tracking

    Returns:
        The Textract job ID.
    """
    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": CHARTS_PROCESSED_BUCKET,
                "Name":   processed_chart_key,
            }
        },
        FeatureTypes=["FORMS", "TABLES", "LAYOUT"],
        NotificationChannel={
            "SNSTopicArn": "arn:aws:sns:us-east-1:ACCOUNT:textract-chart-jobs",
            "RoleArn":     "arn:aws:iam::ACCOUNT:role/textract-sns-role",
        },
        JobTag=chart_id,
    )

    job_id = response["JobId"]

    # Store the Textract job ID in DynamoDB for traceability and debugging.
    migration_table = dynamodb.Table(MIGRATION_TABLE)
    migration_table.update_item(
        Key={"chart_id": chart_id},
        UpdateExpression="SET textract_job_id = :jid, #s = :status",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":jid":    job_id,
            ":status": "extracting",
        },
    )

    print(f"Started Textract job {job_id} for chart {chart_id}")
    return job_id


def retrieve_textract_blocks(job_id: str, chart_id: str) -> tuple[list, dict]:
    """
    Wait for a Textract async job to complete and retrieve all result blocks.

    Textract paginates results. A 200-page chart can produce 50,000+ blocks
    across many result pages. We collect everything before any parsing begins.

    In production, do not poll here. Call this only after the SNS notification
    confirms the job succeeded. The polling loop is here for development only.

    Args:
        job_id:   Textract job ID from start_chart_extraction
        chart_id: chart identifier for tracking updates

    Returns:
        A tuple of (all_blocks, block_map) where block_map is a dict of
        block ID -> block for O(1) lookups during segmentation and extraction.
    """
    job_status = "IN_PROGRESS"
    attempts   = 0
    max_polls  = 120   # 120 * 5s = 10 minutes; large charts can take 5-8 minutes

    while job_status == "IN_PROGRESS" and attempts < max_polls:
        attempts  += 1
        response   = textract_client.get_document_analysis(JobId=job_id)
        job_status = response["JobStatus"]

        if job_status == "IN_PROGRESS":
            print(f"  Job {job_id} still running (attempt {attempts}/{max_polls})...")
            time.sleep(5)
        elif job_status == "FAILED":
            raise RuntimeError(
                f"Textract job {job_id} failed: "
                f"{response.get('StatusMessage', 'no message')}"
            )

    if job_status != "SUCCEEDED":
        raise TimeoutError(
            f"Textract job {job_id} did not complete after {max_polls} attempts."
        )

    all_blocks = []
    next_token = None

    while True:
        params = {"JobId": job_id}
        if next_token:
            params["NextToken"] = next_token

        response   = textract_client.get_document_analysis(**params)
        all_blocks.extend(response.get("Blocks", []))
        next_token = response.get("NextToken")

        if not next_token:
            break

    block_map  = {block["Id"]: block for block in all_blocks}
    page_count = max(
        (block.get("Page", 1) for block in all_blocks),
        default=0,
    )

    # Write raw blocks to S3. At 50,000+ blocks per chart, keeping them
    # in S3 rather than passing through Lambda memory is the right call.
    blocks_key = f"textract-output/{chart_id}/blocks.json"
    s3_client.put_object(
        Bucket=TEXTRACT_OUTPUT_BUCKET,
        Key=blocks_key,
        Body=json.dumps(all_blocks),
        ContentType="application/json",
    )

    # Update DynamoDB with page count and blocks key.
    dynamodb.Table(MIGRATION_TABLE).update_item(
        Key={"chart_id": chart_id},
        UpdateExpression=(
            "SET page_count = :pc, blocks_key = :bk, #s = :status"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":pc":     page_count,
            ":bk":     blocks_key,
            ":status": "segmenting",
        },
    )

    print(f"  Retrieved {len(all_blocks)} blocks across {page_count} pages.")
    return all_blocks, block_map


def group_blocks_by_page(all_blocks: list) -> dict:
    """
    Group Textract blocks by page number and extract per-page features.

    Adds header_text (top 15% of page) to each page entry, which the
    boundary detection step uses for Jaccard similarity comparison.
    Same structure as Recipe 1.5 with the header_text addition.

    Returns a dict of page_number -> page_data dict.
    """
    pages = {}

    for block in all_blocks:
        page_num = block.get("Page", 1)

        if page_num not in pages:
            pages[page_num] = {
                "blocks":        [],
                "text":          "",
                "header_text":   "",
                "has_tables":    False,
                "has_forms":     False,
                "layout_blocks": [],
                "word_confidences": [],
                "handwritten_word_count": 0,
                "total_word_count": 0,
            }

        pages[page_num]["blocks"].append(block)

        if block.get("BlockType") == "LINE":
            pages[page_num]["text"] += block.get("Text", "") + "\n"

        if block.get("BlockType") == "TABLE":
            pages[page_num]["has_tables"] = True

        if block.get("BlockType") == "KEY_VALUE_SET":
            pages[page_num]["has_forms"] = True

        if block.get("BlockType", "").startswith("LAYOUT_"):
            pages[page_num]["layout_blocks"].append(block)

        # Track word-level confidence and handwriting counts for quality scoring.
        if block.get("BlockType") == "WORD":
            conf = block.get("Confidence", 0.0) / 100.0
            pages[page_num]["word_confidences"].append(conf)
            pages[page_num]["total_word_count"] += 1
            if block.get("TextType") == "HANDWRITING":
                pages[page_num]["handwritten_word_count"] += 1

    # Extract header region for each page after all blocks are grouped.
    for page_data in pages.values():
        page_data["header_text"] = extract_header_region(page_data["blocks"])

    return pages
```

---

## Step 4: Document Segmentation

Same boundary detection algorithm as Recipe 1.5: four signals fire in priority order (title line, header discontinuity, page restart, date discontinuity). Extended here with the full chart document title pattern list. Review Recipe 1.5 for the detailed explanation of each signal.

```python
# Boundary detection thresholds (same as Recipe 1.5)
HEADER_SIMILARITY_THRESHOLD = 0.40
DATE_BOUNDARY_DAYS          = 30


def detect_document_boundaries(pages: dict) -> list:
    """
    Scan the page stream and find logical document boundaries.

    Returns a list of segment dicts, each with start_page, end_page,
    boundary_signal, and primary_date. These segments are the units
    the classifier and extractors operate on in Steps 5 and 6.

    This function is the same algorithm as Recipe 1.5 with the extended
    CHART_DOCUMENT_TITLE_PATTERNS list. See Recipe 1.5's companion for
    the detailed explanation of each boundary signal.
    """
    sorted_page_nums = sorted(pages.keys())
    if not sorted_page_nums:
        return []

    segments    = []
    seg_start   = sorted_page_nums[0]
    prev_header = None
    prev_date   = None

    for page_num in sorted_page_nums:
        page        = pages[page_num]
        header      = page["header_text"]
        text        = page["text"]
        first_lines = "\n".join(text.split("\n")[:5]).lower()

        is_boundary     = False
        boundary_signal = None

        # Signal 1: Document title line
        for pattern in CHART_DOCUMENT_TITLE_PATTERNS:
            if pattern in first_lines and page_num > seg_start:
                is_boundary     = True
                boundary_signal = "document_title"
                break

        # Signal 2: Header region discontinuity
        if not is_boundary and prev_header is not None and header.strip():
            similarity = compute_jaccard_similarity(header, prev_header)
            if similarity < HEADER_SIMILARITY_THRESHOLD:
                is_boundary     = True
                boundary_signal = "header_discontinuity"

        # Signal 3: Page number restart
        if not is_boundary and page_num > sorted_page_nums[0]:
            if re.search(r"\bpage\s+1\s+of\s+\d+\b|\b1\s+of\s+\d+\b", first_lines):
                is_boundary     = True
                boundary_signal = "page_restart"

        # Signal 4: Date discontinuity
        page_date = extract_primary_date_from_text(first_lines + "\n" + header)
        if not is_boundary and page_date is not None and prev_date is not None:
            if abs((page_date - prev_date).days) > DATE_BOUNDARY_DAYS:
                is_boundary     = True
                boundary_signal = "date_discontinuity"

        # Close current segment and start a new one.
        if is_boundary and page_num > seg_start:
            segments.append({
                "start_page":      seg_start,
                "end_page":        page_num - 1,
                "boundary_signal": boundary_signal,
                "primary_date":    prev_date,
            })
            seg_start = page_num

        if header.strip():
            prev_header = header
        if page_date is not None:
            prev_date = page_date

    # Close the final segment.
    segments.append({
        "start_page":      seg_start,
        "end_page":        sorted_page_nums[-1],
        "boundary_signal": "end_of_document",
        "primary_date":    prev_date,
    })

    print(f"  Boundary detection: {len(sorted_page_nums)} pages -> {len(segments)} segments")
    return segments
```

---

## Step 5: Document Classification and Content Routing

Each segment gets classified as a unit using the same keyword matching approach as Recipe 1.5, extended to the full chart document taxonomy. After classification, each segment is assigned an extraction path based on its document type and handwriting ratio.

```python
def classify_segment(segment: dict, pages: dict) -> tuple[str, int, float]:
    """
    Classify a document segment and compute its handwriting ratio.

    Aggregates text and structural features from all pages in the segment,
    runs keyword matching against CHART_DOC_TYPE_SIGNATURES, and computes
    the fraction of words that are handwritten (used for extraction routing).

    Returns:
        A tuple of (doc_type, class_score, handwriting_ratio).
        doc_type is "unclassified" if nothing met the minimum match threshold.
    """
    segment_text    = ""
    has_tables      = False
    total_words     = 0
    handwritten     = 0

    for page_num in range(segment["start_page"], segment["end_page"] + 1):
        if page_num not in pages:
            continue
        page         = pages[page_num]
        segment_text += page["text"] + "\n"
        if page["has_tables"]:
            has_tables = True
        total_words  += page["total_word_count"]
        handwritten  += page["handwritten_word_count"]

    handwriting_ratio  = (handwritten / total_words) if total_words > 0 else 0.0
    segment_text_lower = segment_text.lower()
    scores             = {}

    for doc_type, sig in CHART_DOC_TYPE_SIGNATURES.items():
        hits = sum(1 for kw in sig["keywords"] if kw in segment_text_lower)
        if hits < sig["min_matches"]:
            continue
        score = hits
        if has_tables and sig.get("table_bonus", 0) > 0:
            score += sig["table_bonus"]
        scores[doc_type] = score

    if not scores:
        return "unclassified", 0, handwriting_ratio

    best_type  = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]
    return best_type, best_score, handwriting_ratio


def classify_and_route_segments(segments: list, pages: dict) -> list:
    """
    Classify all segments and determine the extraction path for each.

    Extraction paths:
    - "handwriting_pipeline": segment is more than 50% handwritten words.
                              Follows Recipe 1.6 confidence tiering and A2I.
    - "table_extractor":      lab results or heavily table-structured segments.
    - "clinical_nlp":         typed clinical documents (Comprehend Medical).
    - "generic_text":         other typed text without a specific NLP path.
    - "unclassified_review":  no keyword match; route to human review queue.

    Returns the segments list with doc_type, class_score, handwriting_ratio,
    and extraction_path added to each entry.
    """
    classified = []

    for segment in segments:
        doc_type, class_score, hw_ratio = classify_segment(segment, pages)

        if hw_ratio > 0.50:
            extraction_path = "handwriting_pipeline"
        elif doc_type == "lab_result" or pages.get(segment["start_page"], {}).get("has_tables"):
            extraction_path = "table_extractor"
        elif doc_type in [
            "progress_note", "history_and_physical", "discharge_summary",
            "operative_report", "consultation_report", "radiology_report",
        ]:
            extraction_path = "clinical_nlp"
        elif doc_type == "unclassified":
            extraction_path = "unclassified_review"
        else:
            extraction_path = "generic_text"

        classified.append({
            **segment,
            "doc_type":         doc_type,
            "class_score":      class_score,
            "handwriting_ratio": hw_ratio,
            "extraction_path":  extraction_path,
        })

        print(
            f"  Pages {segment['start_page']}-{segment['end_page']}: "
            f"{doc_type} (score: {class_score}, hw_ratio: {hw_ratio:.2f}) "
            f"-> {extraction_path}"
        )

    return classified
```

---

## Step 6: Type-Specific Extraction with Handwriting Tiering

Clinical documents go to Comprehend Medical. Handwriting-dominant documents go through Recipe 1.6's confidence tiering with A2I for low-confidence pages. Lab results go to the table extractor. Each path returns a consistent result structure that the quality scorer and FHIR mapper can consume without caring which path was taken.

```python
def extract_clinical_document(classified_doc: dict, pages: dict) -> dict:
    """
    Extract clinical entities from a typed clinical document using Comprehend Medical.

    Runs DetectEntitiesV2 for clinical entities, InferICD10CM for diagnosis codes,
    and InferRxNorm for medications (where appropriate to the document type).
    Long documents are chunked with 500-character overlap to avoid entity loss at
    chunk boundaries.

    Args:
        classified_doc: segment dict from classify_and_route_segments
        pages:          full pages dict from group_blocks_by_page

    Returns:
        Extraction result dict with entities, ICD-10 codes, and document metadata.
    """
    doc_type = classified_doc["doc_type"]

    # Aggregate segment text.
    segment_text = ""
    for page_num in range(classified_doc["start_page"], classified_doc["end_page"] + 1):
        if page_num in pages:
            segment_text += pages[page_num]["text"] + "\n"

    text_chunks  = split_text_with_overlap(segment_text, max_chars=COMPREHEND_MAX_CHARS)
    all_entities = []
    all_icd10    = []

    for chunk in text_chunks:
        if not chunk.strip():
            continue

        # Clinical entity extraction
        ent_response = comprehend_client.detect_entities_v2(Text=chunk)
        all_entities.extend(ent_response.get("Entities", []))

        # ICD-10 inference for diagnosis-rich document types
        if doc_type in [
            "progress_note", "history_and_physical", "discharge_summary",
            "operative_report", "consultation_report",
        ]:
            icd_response = comprehend_client.infer_icd10_cm(Text=chunk)
            all_icd10.extend(icd_response.get("Entities", []))

        # RxNorm inference for medication-heavy document types
        if doc_type in ["medication_list", "progress_note", "history_and_physical"]:
            rxn_response = comprehend_client.infer_rxnorm(Text=chunk)
            for med in rxn_response.get("Entities", []):
                concepts = med.get("RxNormConcepts", [])
                if concepts:
                    all_entities.append({
                        "Text":     med["Text"],
                        "Category": "MEDICATION",
                        "Type":     "GENERIC_NAME",
                        "Score":    concepts[0].get("Score", 0.0),
                        "Traits":   [],
                        "RxNorm":   concepts[0].get("Code", ""),
                    })

    # Split ICD-10 codes by confidence.
    icd10_accepted = [
        e for e in all_icd10
        if e.get("ICD10CMConcepts") and
        e["ICD10CMConcepts"][0].get("Score", 0.0) >= ICD10_MIN_CONFIDENCE
    ]
    icd10_flagged = [
        e for e in all_icd10
        if not e.get("ICD10CMConcepts") or
        e["ICD10CMConcepts"][0].get("Score", 0.0) < ICD10_MIN_CONFIDENCE
    ]

    document_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"  Clinical NLP on pages {classified_doc['start_page']}-"
        f"{classified_doc['end_page']}: "
        f"{len(all_entities)} entities, {len(icd10_accepted)} ICD-10 accepted"
    )

    return {
        "doc_type":        doc_type,
        "start_page":      classified_doc["start_page"],
        "end_page":        classified_doc["end_page"],
        "document_date":   document_date.isoformat() if document_date else None,
        "entities":        all_entities,
        "icd10_accepted":  icd10_accepted,
        "icd10_flagged":   icd10_flagged,
        "raw_text":        segment_text,
        "confidence_path": "clinical_nlp",
        "pending_review":  False,
        "review_task_ids": [],
    }


def extract_table_document(classified_doc: dict, pages: dict, block_map: dict) -> dict:
    """
    Extract structured data from table-heavy documents (primarily lab results).

    Parses TABLE blocks to extract row-by-row values. Returns both the table
    data and any clinical entities found via Comprehend Medical on the surrounding
    narrative text.

    Args:
        classified_doc: segment dict with doc_type, start_page, end_page
        pages:          full pages dict
        block_map:      block ID -> block dict for relationship traversal
    """
    def get_cell_text(cell_block: dict) -> str:
        text = ""
        for rel in cell_block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for cid in rel["Ids"]:
                    child = block_map.get(cid, {})
                    if child.get("BlockType") == "WORD":
                        text += child.get("Text", "") + " "
        return text.strip()

    segment_text = ""
    all_tables   = []

    for page_num in range(classified_doc["start_page"], classified_doc["end_page"] + 1):
        if page_num not in pages:
            continue

        page         = pages[page_num]
        segment_text += page["text"] + "\n"

        for block in page["blocks"]:
            if block.get("BlockType") != "TABLE":
                continue

            cells = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] != "CHILD":
                    continue
                for cid in rel["Ids"]:
                    cell_block = block_map.get(cid, {})
                    if cell_block.get("BlockType") != "CELL":
                        continue
                    row = cell_block.get("RowIndex", 0)
                    col = cell_block.get("ColumnIndex", 0)
                    cells[(row, col)] = get_cell_text(cell_block)

            if not cells:
                continue

            max_row = max(r for r, c in cells)
            max_col = max(c for r, c in cells)
            table_rows = [
                [cells.get((r, c), "") for c in range(1, max_col + 1)]
                for r in range(1, max_row + 1)
            ]
            all_tables.append(table_rows)

    # Run Comprehend Medical on the text portion for any inline entity mentions.
    entities     = []
    icd10_accepted = []

    if segment_text.strip():
        chunk = segment_text[:COMPREHEND_MAX_CHARS]
        ent_response = comprehend_client.detect_entities_v2(Text=chunk)
        entities     = ent_response.get("Entities", [])

    document_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"  Table extraction on pages {classified_doc['start_page']}-"
        f"{classified_doc['end_page']}: {len(all_tables)} table(s)"
    )

    return {
        "doc_type":        classified_doc["doc_type"],
        "start_page":      classified_doc["start_page"],
        "end_page":        classified_doc["end_page"],
        "document_date":   document_date.isoformat() if document_date else None,
        "entities":        entities,
        "icd10_accepted":  icd10_accepted,
        "icd10_flagged":   [],
        "tables":          all_tables,
        "raw_text":        segment_text,
        "confidence_path": "table_extractor",
        "pending_review":  False,
        "review_task_ids": [],
    }


def extract_handwritten_document(
    classified_doc: dict,
    pages: dict,
    chart_id: str,
) -> dict:
    """
    Apply Recipe 1.6 confidence tiering to handwriting-dominant documents.

    Pages above HIGH_CONFIDENCE_THRESHOLD: extract text directly.
    Pages between thresholds: extract but mark as unconfirmed.
    Pages below LOW_CONFIDENCE_THRESHOLD: send to A2I for human review.

    A2I review is asynchronous. This function submits the review tasks and
    returns immediately with pending_review=True. The pipeline continues
    processing other documents while reviewers work through the queue.

    Args:
        classified_doc: segment dict from classify_and_route_segments
        pages:          full pages dict
        chart_id:       chart identifier (used to construct A2I loop names)

    Returns:
        Extraction result dict. If pending_review is True, review_task_ids
        is populated and the extracted text is incomplete until Step 7 resolves.
    """
    high_pages        = []
    review_pages      = []
    unconfirmed_pages = []

    for page_num in range(classified_doc["start_page"], classified_doc["end_page"] + 1):
        if page_num not in pages:
            continue

        page          = pages[page_num]
        word_confs    = page["word_confidences"]

        if not word_confs:
            continue

        avg_conf  = sum(word_confs) / len(word_confs)
        page_text = page["text"]

        if avg_conf >= HIGH_CONFIDENCE_THRESHOLD:
            high_pages.append({"page_num": page_num, "text": page_text, "confidence": avg_conf})
        elif avg_conf < LOW_CONFIDENCE_THRESHOLD:
            image_key = f"charts-processed/{chart_id}/page-{page_num}.png"
            review_pages.append({
                "page_num":   page_num,
                "text":       page_text,
                "confidence": avg_conf,
                "image_key":  image_key,
            })
        else:
            unconfirmed_pages.append({"page_num": page_num, "text": page_text, "confidence": avg_conf})

    # Submit low-confidence pages to A2I.
    # A2I is async; we record the task IDs and return immediately.
    # A downstream step checks for completion and applies corrections.
    review_task_ids = []

    for page_info in review_pages:
        loop_name = f"chart-{chart_id}-page-{page_info['page_num']}"[:63]

        try:
            a2i_client.start_human_loop(
                HumanLoopName=loop_name,
                FlowDefinitionArn=A2I_FLOW_ARN,
                HumanLoopInput={
                    "InputContent": json.dumps({
                        "image_s3_key": page_info["image_key"],
                        "ocr_text":     page_info["text"],
                        "chart_id":     chart_id,
                        "page_num":     page_info["page_num"],
                    })
                },
            )
            review_task_ids.append(loop_name)
        except ClientError as e:
            print(
                f"  WARNING: Could not start A2I loop {loop_name}: "
                f"{e.response['Error']['Code']}"
            )

    # Assemble the direct-path text from high and unconfirmed pages.
    direct_pages = sorted(high_pages + unconfirmed_pages, key=lambda p: p["page_num"])
    direct_text  = "\n".join(p["text"] for p in direct_pages)

    # Run Comprehend Medical on whatever text we have from the direct-path pages.
    entities    = []
    icd10_accepted = []

    if direct_text.strip():
        chunk        = direct_text[:COMPREHEND_MAX_CHARS]
        ent_response = comprehend_client.detect_entities_v2(Text=chunk)
        entities     = ent_response.get("Entities", [])

    document_date = extract_primary_date_from_text(
        "\n".join(direct_text.split("\n")[:10])
    )

    pending = len(review_task_ids) > 0
    print(
        f"  Handwriting extraction pages {classified_doc['start_page']}-"
        f"{classified_doc['end_page']}: "
        f"{len(high_pages)} direct, {len(unconfirmed_pages)} unconfirmed, "
        f"{len(review_pages)} sent to A2I"
    )

    return {
        "doc_type":          classified_doc["doc_type"],
        "start_page":        classified_doc["start_page"],
        "end_page":          classified_doc["end_page"],
        "document_date":     document_date.isoformat() if document_date else None,
        "entities":          entities,
        "icd10_accepted":    icd10_accepted,
        "icd10_flagged":     [],
        "raw_text":          direct_text,
        "confidence_path":   "handwriting_pipeline",
        "pending_review":    pending,
        "review_task_ids":   review_task_ids,
        "unconfirmed_page_count": len(unconfirmed_pages),
        "review_page_count": len(review_pages),
    }


def route_and_extract(classified_doc: dict, pages: dict, block_map: dict, chart_id: str) -> dict:
    """
    Route a classified document to its appropriate extraction function.
    Returns a consistent result structure regardless of which path was taken.
    """
    path = classified_doc["extraction_path"]

    if path == "handwriting_pipeline":
        return extract_handwritten_document(classified_doc, pages, chart_id)
    elif path == "table_extractor":
        return extract_table_document(classified_doc, pages, block_map)
    elif path in ("clinical_nlp", "generic_text"):
        return extract_clinical_document(classified_doc, pages)
    else:
        # Unclassified: store the raw text preview for human triage.
        segment_text = ""
        for pn in range(classified_doc["start_page"], classified_doc["end_page"] + 1):
            if pn in pages:
                segment_text += pages[pn]["text"] + "\n"

        return {
            "doc_type":        "unclassified",
            "start_page":      classified_doc["start_page"],
            "end_page":        classified_doc["end_page"],
            "document_date":   None,
            "entities":        [],
            "icd10_accepted":  [],
            "icd10_flagged":   [],
            "raw_text":        segment_text[:500],
            "confidence_path": "unclassified_review",
            "pending_review":  False,
            "review_task_ids": [],
        }
```

---

## Step 7: Quality Scoring Per Extracted Document

After extraction completes, every logical document gets a quality score. The composite score combines OCR confidence, classification confidence, extraction completeness, and handwriting review rate into a single 0.0-1.0 signal. This score determines whether the chart gets auto-promoted to FHIR loading or flagged for priority human review sampling.

```python
def score_extracted_document(
    extraction: dict,
    classified_doc: dict,
    pages: dict,
) -> dict:
    """
    Compute a quality score for one extracted logical document.

    Four dimensions, each normalized to 0.0-1.0, combined as a weighted average.

    OCR confidence: average word-level Textract confidence across the segment pages.
    Classification confidence: normalized keyword match score from Step 5.
    Extraction completeness: fraction of expected content fields that are populated.
    Handwriting review rate: inverted fraction of handwritten pages sent to A2I.

    Args:
        extraction:      result dict from route_and_extract (Step 6)
        classified_doc:  segment dict from classify_and_route_segments (Step 5)
        pages:           full pages dict from group_blocks_by_page (Step 3)

    Returns:
        A quality score dict with composite score, tier, and per-dimension breakdown.
    """
    scores = {}

    # OCR confidence: average word confidence across all pages in the segment.
    all_confs = []
    for page_num in range(classified_doc["start_page"], classified_doc["end_page"] + 1):
        if page_num in pages:
            all_confs.extend(pages[page_num]["word_confidences"])

    scores["ocr_confidence"] = (sum(all_confs) / len(all_confs)) if all_confs else 0.5

    # Classification confidence: normalize keyword match score.
    # A score of 8 or more matches is treated as maximum confidence.
    class_score_raw = classified_doc.get("class_score", 0)
    scores["class_confidence"] = min(class_score_raw / 8.0, 1.0)

    # Extraction completeness: what fraction of expected fields are populated?
    doc_type         = extraction.get("doc_type", "unclassified")
    expected_fields  = EXPECTED_CONTENT.get(doc_type, ["entities"])
    populated_count  = 0

    for field in expected_fields:
        value = extraction.get(field)
        if value:
            populated_count += 1

    scores["extraction_completeness"] = (
        populated_count / len(expected_fields) if expected_fields else 0.5
    )

    # Handwriting review rate (inverted).
    # A segment with no handwriting scores 1.0 here (no penalty).
    # A segment where 100% of handwritten pages went to A2I scores 0.0.
    if classified_doc.get("extraction_path") == "handwriting_pipeline":
        total_hw_pages  = max(
            classified_doc["end_page"] - classified_doc["start_page"] + 1, 1
        )
        review_pages    = extraction.get("review_page_count", 0)
        review_rate     = review_pages / total_hw_pages
        scores["handwriting_review_rate"] = 1.0 - review_rate
    else:
        scores["handwriting_review_rate"] = 1.0

    # Composite weighted score.
    composite = sum(
        QUALITY_WEIGHTS[dim] * scores[dim]
        for dim in QUALITY_WEIGHTS
    )

    if composite >= 0.80:
        tier = "high"
    elif composite >= 0.60:
        tier = "medium"
    else:
        tier = "low"

    return {
        "composite": round(composite, 3),
        "tier":      tier,
        "flagged":   (tier == "low"),
        "breakdown": {k: round(v, 3) for k, v in scores.items()},
    }


def compute_chart_quality_summary(document_scores: list, chart_id: str) -> dict:
    """
    Aggregate per-document quality scores into a chart-level summary.
    Updates the DynamoDB tracking record with the chart composite score.
    """
    if not document_scores:
        return {"chart_composite": 0.0, "tier": "low", "needs_review": True}

    composites   = [s["composite"] for s in document_scores]
    chart_comp   = sum(composites) / len(composites)

    tier_counts  = {"high": 0, "medium": 0, "low": 0}
    for s in document_scores:
        tier_counts[s["tier"]] += 1

    needs_review = tier_counts["low"] > 0 or chart_comp < 0.70

    summary = {
        "chart_composite": round(chart_comp, 3),
        "document_count":  len(document_scores),
        "high_count":      tier_counts["high"],
        "medium_count":    tier_counts["medium"],
        "low_count":       tier_counts["low"],
        "needs_review":    needs_review,
    }

    # Update DynamoDB.
    dynamodb.Table(MIGRATION_TABLE).update_item(
        Key={"chart_id": chart_id},
        UpdateExpression=(
            "SET quality_score = :qs, quality_tier = :qt, "
            "doc_count = :dc, needs_review = :nr"
        ),
        ExpressionAttributeValues={
            ":qs": Decimal(str(round(chart_comp, 3))),
            ":qt": "high" if chart_comp >= 0.80 else ("medium" if chart_comp >= 0.60 else "low"),
            ":dc": len(document_scores),
            ":nr": needs_review,
        },
    )

    return summary
```

---

## Step 8: FHIR R4 Resource Mapping

This is where extracted data becomes useful. Every document produces at least one `DocumentReference` (the provenance record: "this document was digitized"). Clinical documents produce additional FHIR resources from their extracted entities and ICD-10 codes. Every migrated resource carries quality metadata and a provenance note so downstream systems know exactly where the data came from and how much to trust it.

```python
def loinc_for_doc_type(doc_type: str) -> tuple[str, str]:
    """Return the LOINC code and display text for a document type."""
    return LOINC_BY_DOC_TYPE.get(doc_type, ("34133-9", "Summarization of episode note"))


def lookup_cvx_code(vaccine_text: str) -> str | None:
    """Return a CVX code for a vaccine name, or None if not found."""
    lower = vaccine_text.lower()
    for keyword, cvx in CVX_LOOKUP.items():
        if keyword in lower:
            return cvx
    return None


def map_document_to_fhir(
    chart_id: str,
    member_id: str,
    extraction: dict,
    quality_score: dict,
) -> list:
    """
    Map one extracted logical document to a list of FHIR R4 resources.

    Every document produces a DocumentReference. Clinical documents produce
    additional Condition, Observation, MedicationStatement, or Immunization
    resources based on their extracted entities and ICD-10 codes.

    All migrated resources use conservative FHIR status values (unconfirmed,
    unknown) because we cannot verify clinical facts from paper chart OCR.
    The provenance note on every resource documents the source, page range,
    and OCR confidence so downstream systems can apply appropriate skepticism.

    Args:
        chart_id:      chart identifier (used to construct source URIs)
        member_id:     FHIR Patient resource ID for this member
        extraction:    result dict from route_and_extract (Step 6)
        quality_score: result dict from score_extracted_document (Step 7)

    Returns:
        A list of FHIR R4 resource dicts (valid FHIR R4 JSON structures).
    """
    resources     = []
    doc_type      = extraction.get("doc_type", "unclassified")
    start_page    = extraction.get("start_page", 0)
    end_page      = extraction.get("end_page", 0)
    doc_date      = extraction.get("document_date")
    source_uri    = (
        f"s3://charts-archive/{chart_id}/"
        f"pages-{start_page}-{end_page}.pdf"
    )

    loinc_code, loinc_display = loinc_for_doc_type(doc_type)
    provenance_note = (
        f"Migrated from paper chart. "
        f"Chart: {chart_id}. "
        f"Pages {start_page}-{end_page}. "
        f"OCR confidence: {quality_score['breakdown'].get('ocr_confidence', 0):.3f}. "
        f"Quality tier: {quality_score['tier']}."
    )

    # ---- DocumentReference (always created) ----
    doc_ref = {
        "resourceType": "DocumentReference",
        "status":       "current",
        "subject":      {"reference": f"Patient/{member_id}"},
        "type": {
            "coding": [{
                "system":  "http://loinc.org",
                "code":    loinc_code,
                "display": loinc_display,
            }],
            "text": doc_type,
        },
        "content": [{
            "attachment": {
                "contentType": "application/pdf",
                "url":         source_uri,
            }
        }],
        "extension": [{
            "url":          "https://example.org/fhir/ext/migration-quality-score",
            "valueDecimal": quality_score["composite"],
        }],
        "note": [{"text": provenance_note}],
    }
    if doc_date:
        doc_ref["date"] = doc_date

    resources.append(doc_ref)

    # ---- Condition resources (from clinical notes) ----
    if doc_type in [
        "progress_note", "history_and_physical", "discharge_summary",
        "operative_report", "consultation_report",
    ]:
        for icd_entity in extraction.get("icd10_accepted", []):
            concepts = icd_entity.get("ICD10CMConcepts", [])
            if not concepts:
                continue

            condition = {
                "resourceType": "Condition",
                "clinicalStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                        "code":   "unknown",
                    }]
                    # Cannot reliably determine active vs. resolved from a paper chart.
                    # Use "unknown" rather than making a clinical claim we cannot support.
                },
                "verificationStatus": {
                    "coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                        "code":   "unconfirmed",
                    }]
                    # Migrated from paper with OCR; not clinician-verified in this system.
                    # Do not promote to "confirmed" without clinical review.
                },
                "subject": {"reference": f"Patient/{member_id}"},
                "code": {
                    "coding": [{
                        "system":  "http://hl7.org/fhir/sid/icd-10-cm",
                        "code":    concepts[0].get("Code", ""),
                        "display": concepts[0].get("Description", ""),
                    }],
                    "text": icd_entity.get("Text", ""),
                },
                "note": [{"text": provenance_note}],
            }
            if doc_date:
                condition["recordedDate"] = doc_date

            resources.append(condition)

    # ---- Observation resources (from lab results) ----
    if doc_type == "lab_result":
        # Parse lab values from table data when available.
        # A real implementation would apply column normalization (see Recipe 1.5)
        # to extract test name, result, unit, and reference range.
        for table in extraction.get("tables", []):
            if len(table) < 2:
                continue

            # Heuristic: treat the first row as a header and subsequent rows as data.
            header_row  = [cell.lower().strip() for cell in table[0]]
            name_col    = next((i for i, h in enumerate(header_row) if "test" in h or "name" in h), 0)
            result_col  = next((i for i, h in enumerate(header_row) if "result" in h or "value" in h), 1)
            unit_col    = next((i for i, h in enumerate(header_row) if "unit" in h), None)
            ref_col     = next((i for i, h in enumerate(header_row) if "range" in h or "ref" in h), None)

            for row in table[1:]:
                if not row or not row[name_col].strip():
                    continue

                observation = {
                    "resourceType": "Observation",
                    "status":       "final",
                    "subject":      {"reference": f"Patient/{member_id}"},
                    "code":         {"text": row[name_col] if name_col < len(row) else ""},
                    "note":         [{"text": provenance_note}],
                }

                if doc_date:
                    observation["effectiveDateTime"] = doc_date
                    observation["issued"]            = doc_date

                result_text = row[result_col].strip() if result_col < len(row) else ""
                if result_text:
                    # Try to parse a numeric result; fall back to string.
                    try:
                        num_val = float(result_text.replace(",", ""))
                        observation["valueQuantity"] = {
                            "value":  num_val,
                            "unit":   row[unit_col] if unit_col and unit_col < len(row) else "",
                            "system": "http://unitsofmeasure.org",
                        }
                    except ValueError:
                        observation["valueString"] = result_text

                if ref_col and ref_col < len(row) and row[ref_col].strip():
                    observation["referenceRange"] = [{"text": row[ref_col]}]

                resources.append(observation)

    # ---- MedicationStatement resources ----
    if doc_type in ["medication_list", "progress_note", "history_and_physical"]:
        seen_meds = set()
        for entity in extraction.get("entities", []):
            if entity.get("Category") != "MEDICATION":
                continue
            med_text = entity.get("Text", "").strip()
            if not med_text or med_text.lower() in seen_meds:
                continue
            seen_meds.add(med_text.lower())

            med_statement = {
                "resourceType": "MedicationStatement",
                "status":       "unknown",
                # Historical chart; cannot determine whether still current.
                "subject":      {"reference": f"Patient/{member_id}"},
                "medicationCodeableConcept": {"text": med_text},
                "note":         [{"text": provenance_note}],
            }

            # Add RxNorm code if available.
            rxnorm = entity.get("RxNorm", "")
            if rxnorm:
                med_statement["medicationCodeableConcept"]["coding"] = [{
                    "system":  "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code":    rxnorm,
                    "display": med_text,
                }]

            if doc_date:
                med_statement["effectiveDateTime"] = doc_date

            resources.append(med_statement)

    # ---- Immunization resources ----
    if doc_type == "immunization_record":
        for entity in extraction.get("entities", []):
            if entity.get("Category") not in ("TEST_TREATMENT_PROCEDURE", "MEDICATION"):
                continue
            vaccine_text = entity.get("Text", "").strip()
            if not vaccine_text:
                continue

            immunization = {
                "resourceType": "Immunization",
                "status":       "completed",
                "patient":      {"reference": f"Patient/{member_id}"},
                "vaccineCode":  {"text": vaccine_text},
                "note":         [{"text": provenance_note}],
            }

            cvx_code = lookup_cvx_code(vaccine_text)
            if cvx_code:
                immunization["vaccineCode"]["coding"] = [{
                    "system":  "http://hl7.org/fhir/sid/cvx",
                    "code":    cvx_code,
                    "display": vaccine_text,
                }]

            if doc_date:
                immunization["occurrenceDateTime"] = doc_date

            resources.append(immunization)

    return resources
```

---

## Step 9: FHIR Bundle Assembly and HealthLake Import

HealthLake's bulk FHIR import reads NDJSON files from S3 (one FHIR resource per line, no commas between objects). For large migration programs, we batch the import: accumulate completed chart bundles and submit one HealthLake import job per group of charts rather than one job per chart. Import jobs have setup overhead; batching amortizes that cost.

```python
def deduplicate_conditions(resources: list) -> list:
    """
    Remove duplicate Condition resources that share the same patient and ICD-10 code.
    When the same diagnosis appears in multiple documents within one chart,
    keep the resource with the most recent recordedDate.
    """
    seen = {}   # key: (member_id, icd10_code) -> best resource

    non_conditions = [r for r in resources if r.get("resourceType") != "Condition"]
    conditions     = [r for r in resources if r.get("resourceType") == "Condition"]

    for cond in conditions:
        subject  = cond.get("subject", {}).get("reference", "")
        codings  = cond.get("code", {}).get("coding", [])
        icd_code = codings[0].get("code", "") if codings else ""
        dedup_key = (subject, icd_code)

        existing = seen.get(dedup_key)
        if existing is None:
            seen[dedup_key] = cond
        else:
            # Keep the one with the more recent (or any) recordedDate.
            new_date = cond.get("recordedDate", "")
            old_date = existing.get("recordedDate", "")
            if new_date > old_date:
                seen[dedup_key] = cond

    return non_conditions + list(seen.values())


def assemble_fhir_bundle(
    chart_id: str,
    member_id: str,
    all_document_resources: list,
    quality_summary: dict,
) -> tuple[str, int]:
    """
    Flatten all per-document FHIR resources into a single chart bundle,
    deduplicate Condition and MedicationStatement resources, and write
    the bundle as NDJSON to S3.

    Also updates the DynamoDB tracking record with resource counts and
    quality summary, and sets the chart status to "fhir_ready".

    Args:
        chart_id:               chart identifier
        member_id:              FHIR Patient resource ID
        all_document_resources: list of per-document resource lists from Step 8
        quality_summary:        chart-level quality summary from Step 7

    Returns:
        A tuple of (bundle_s3_key, total_resource_count).
    """
    # Flatten all resource lists.
    all_resources = [r for doc_resources in all_document_resources for r in doc_resources]

    # Deduplicate Conditions (same ICD-10 code appearing in multiple documents).
    all_resources = deduplicate_conditions(all_resources)

    # Deduplicate MedicationStatements (same medication text appearing multiple times).
    seen_meds     = set()
    unique_meds   = []
    for r in all_resources:
        if r.get("resourceType") == "MedicationStatement":
            med_text = r.get("medicationCodeableConcept", {}).get("text", "").lower()
            subject  = r.get("subject", {}).get("reference", "")
            key      = (subject, med_text)
            if key not in seen_meds:
                seen_meds.add(key)
                unique_meds.append(r)
        else:
            unique_meds.append(r)
    all_resources = unique_meds

    # Write FHIR NDJSON to S3. One resource per line, no trailing commas.
    ndjson_content = "\n".join(json.dumps(r) for r in all_resources)
    bundle_key     = f"fhir-bundles/{chart_id}/bundle.ndjson"

    s3_client.put_object(
        Bucket=FHIR_OUTPUT_BUCKET,
        Key=bundle_key,
        Body=ndjson_content.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    # Count resources by type for the DynamoDB record.
    type_counts = {}
    for r in all_resources:
        rt = r.get("resourceType", "Unknown")
        type_counts[rt] = type_counts.get(rt, 0) + 1

    # Update DynamoDB.
    dynamodb.Table(MIGRATION_TABLE).update_item(
        Key={"chart_id": chart_id},
        UpdateExpression=(
            "SET #s = :status, fhir_bundle_key = :bk, "
            "fhir_resource_count = :rc, "
            "conditions_count = :cc, observations_count = :oc, "
            "med_statements_count = :mc, doc_references_count = :dc"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "fhir_ready",
            ":bk":     bundle_key,
            ":rc":     len(all_resources),
            ":cc":     type_counts.get("Condition", 0),
            ":oc":     type_counts.get("Observation", 0),
            ":mc":     type_counts.get("MedicationStatement", 0),
            ":dc":     type_counts.get("DocumentReference", 0),
        },
    )

    print(
        f"  FHIR bundle for {chart_id}: {len(all_resources)} resources "
        f"({type_counts})"
    )
    return bundle_key, len(all_resources)


def submit_healthlake_import_batch(
    datastore_id: str,
    batch_size: int = 1000,
) -> str | None:
    """
    Find charts with status "fhir_ready" and submit a HealthLake bulk import job.

    This function is called on a schedule (e.g., every hour via EventBridge),
    not per-chart. Batching reduces HealthLake import job overhead at scale.
    One job per 1,000 charts is a reasonable cadence for a large program.

    Scans DynamoDB for ready charts, writes an NDJSON manifest pointing to their
    bundle files, submits the HealthLake import job, and marks the charts as
    "import_submitted".

    Args:
        datastore_id: HealthLake data store ID
        batch_size:   maximum number of charts per import job

    Returns:
        The HealthLake import job ID, or None if no charts are ready.
    """
    migration_table = dynamodb.Table(MIGRATION_TABLE)

    # In production, use a DynamoDB GSI on status to avoid a scan.
    # For illustration, this scan works but is expensive at scale.
    response    = migration_table.scan(
        FilterExpression="attribute_exists(fhir_bundle_key) AND #s = :ready",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":ready": "fhir_ready"},
        Limit=batch_size,
    )
    ready_items = response.get("Items", [])

    if not ready_items:
        print("  No charts in fhir_ready status. Skipping import batch.")
        return None

    # Write the import manifest: one S3 URI per line in NDJSON format.
    manifest_lines = [
        json.dumps({"url": f"s3://{FHIR_OUTPUT_BUCKET}/{item['fhir_bundle_key']}"})
        for item in ready_items
    ]
    timestamp      = datetime.datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    manifest_key   = f"healthlake-imports/manifest-{timestamp}.ndjson"

    s3_client.put_object(
        Bucket=FHIR_OUTPUT_BUCKET,
        Key=manifest_key,
        Body="\n".join(manifest_lines).encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    # Submit the HealthLake FHIR import job.
    response = healthlake_client.start_fhir_import_job(
        InputDataConfig={
            "S3Uri": f"s3://{FHIR_OUTPUT_BUCKET}/{manifest_key}",
        },
        JobOutputDataConfig={
            "S3Configuration": {
                "S3Uri":    f"s3://{FHIR_OUTPUT_BUCKET}/import-results/{timestamp}/",
                "KmsKeyId": KMS_KEY_ARN,
            }
        },
        DatastoreId=datastore_id,
        DataAccessRoleArn=HEALTHLAKE_IMPORT_ROLE_ARN,
    )

    import_job_id = response["JobId"]

    # Mark charts as import_submitted.
    for item in ready_items:
        migration_table.update_item(
            Key={"chart_id": item["chart_id"]},
            UpdateExpression="SET #s = :status, healthlake_job_id = :jid",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":status": "import_submitted",
                ":jid":    import_job_id,
            },
        )

    print(
        f"  Submitted HealthLake import job {import_job_id} "
        f"for {len(ready_items)} charts."
    )
    return import_job_id
```

---

## Step 10: Source Chart Archival

Once a chart confirms successful import into HealthLake, the source PDF transitions to S3 Glacier. This is handled by an S3 Lifecycle policy rather than explicit API calls per chart: we tag the S3 object with `migration-status=completed`, and the lifecycle rule takes it from there.

```python
def mark_chart_archived(chart_id: str, source_s3_key: str) -> None:
    """
    Tag the source chart S3 object to trigger the Glacier lifecycle transition,
    and update the DynamoDB record to final completed status.

    The S3 Lifecycle policy on the charts-raw bucket watches for the tag
    "migration-status=completed" and transitions matching objects to
    S3 Glacier Instant Retrieval after 30 days. No per-chart API call
    to Glacier is needed; the tag is the trigger.

    Args:
        chart_id:      chart identifier
        source_s3_key: S3 key of the source PDF in CHARTS_RAW_BUCKET
    """
    # Set the S3 tag that triggers the lifecycle rule.
    try:
        s3_client.put_object_tagging(
            Bucket=CHARTS_RAW_BUCKET,
            Key=source_s3_key,
            Tagging={
                "TagSet": [
                    {
                        "Key":   "migration-status",
                        "Value": "completed",
                    }
                ]
            },
        )
        print(f"  Tagged s3://{CHARTS_RAW_BUCKET}/{source_s3_key} for Glacier archival.")
    except ClientError as e:
        print(
            f"  WARNING: Could not tag {source_s3_key} for archival: "
            f"{e.response['Error']['Code']}"
        )

    # Update DynamoDB to the terminal "completed" status.
    dynamodb.Table(MIGRATION_TABLE).update_item(
        Key={"chart_id": chart_id},
        UpdateExpression="SET #s = :status, completed_at = :ca",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":status": "completed",
            ":ca":     datetime.datetime.now(timezone.utc).isoformat(),
        },
    )

    print(f"  Chart {chart_id} marked completed.")


# -----------------------------------------------------------------------
# The S3 Lifecycle policy that makes archival automatic.
# Apply this to the charts-raw bucket once at bucket creation.
# The policy is shown here as a reference; deploy via the AWS console or CLI:
#   aws s3api put-bucket-lifecycle-configuration \
#     --bucket charts-raw \
#     --lifecycle-configuration file://lifecycle.json
# -----------------------------------------------------------------------
LIFECYCLE_POLICY_REFERENCE = {
    "Rules": [
        {
            "ID":     "archive-completed-charts",
            "Status": "Enabled",
            "Filter": {
                # Transitions only objects with this tag.
                "Tag": {"Key": "migration-status", "Value": "completed"}
            },
            "Transitions": [
                {
                    "Days":         30,
                    "StorageClass": "GLACIER_IR",
                    # Glacier Instant Retrieval: millisecond retrieval for legal
                    # discovery and member record requests. Costs more than
                    # Deep Archive but avoids the 12-hour retrieval wait.
                }
            ],
            # CMS requires 10-year retention for Medicare claims records.
            # Adjust for your member population and state requirements.
            "Expiration": {
                "Days": 3653   # 10 years plus 3 leap year days
            },
        }
    ]
}
```

---

## Putting It All Together

The full per-chart pipeline as a single callable function. In production, this logic runs inside an AWS Batch container job that receives a chart assignment from the manifest. In development, you can run it directly against a single chart PDF.

```python
def process_single_chart(
    chart_pdf_key: str,
    chart_id: str,
    member_id: str,
) -> dict:
    """
    Run the full 10-step migration pipeline for one chart.

    This function demonstrates the complete per-chart inner loop:
    from raw PDF in S3 through quality scoring, FHIR resource generation,
    and S3 archival tagging. In production, this logic runs inside an
    AWS Batch job container that selects its chart from the manifest CSV
    using the AWS_BATCH_JOB_ARRAY_INDEX environment variable.

    Step 9 (HealthLake import) is intentionally excluded here because
    it is a batched operation that runs on a schedule across many charts,
    not per-chart. See submit_healthlake_import_batch.

    Args:
        chart_pdf_key: S3 key in CHARTS_RAW_BUCKET
        chart_id:      chart identifier matching the DynamoDB record
        member_id:     FHIR Patient ID for the member

    Returns:
        A summary dict with quality metrics and FHIR resource counts.
    """

    print(f"\n{'='*60}")
    print(f"Processing chart {chart_id} ({chart_pdf_key})")
    print(f"{'='*60}")

    # Step 2: Image quality pre-processing
    print("\nStep 2: Image quality pre-processing...")
    processed_key, quality_report = preprocess_chart(chart_pdf_key)
    print(f"  Quality report: {quality_report}")

    # Step 3: Async Textract extraction
    print("\nStep 3: Submitting Textract async job...")
    job_id = start_chart_extraction(processed_key, chart_id)
    print(f"  Textract job ID: {job_id}")

    print("  Retrieving Textract blocks (waiting for job completion)...")
    all_blocks, block_map = retrieve_textract_blocks(job_id, chart_id)

    print("\n  Grouping blocks by page...")
    pages = group_blocks_by_page(all_blocks)
    print(f"  {len(pages)} pages total")

    # Step 4: Document segmentation
    print("\nStep 4: Detecting document boundaries...")
    segments = detect_document_boundaries(pages)
    print(f"  Found {len(segments)} logical document segment(s)")

    # Step 5: Classification and routing
    print("\nStep 5: Classifying document segments...")
    classified_docs = classify_and_route_segments(segments, pages)

    from collections import Counter
    type_dist = Counter(d["doc_type"] for d in classified_docs)
    print(f"  Document type distribution: {dict(type_dist)}")

    # Step 6: Type-specific extraction
    print("\nStep 6: Extracting data from each segment...")
    extraction_results = []

    for classified_doc in classified_docs:
        print(
            f"  Extracting {classified_doc['doc_type']} "
            f"(pages {classified_doc['start_page']}-{classified_doc['end_page']}, "
            f"path: {classified_doc['extraction_path']})..."
        )
        extraction = route_and_extract(classified_doc, pages, block_map, chart_id)
        extraction_results.append(extraction)

    pending_reviews = sum(1 for e in extraction_results if e.get("pending_review"))
    if pending_reviews > 0:
        print(
            f"  {pending_reviews} document(s) have pages in A2I review queue. "
            f"Pipeline continues; review is async."
        )

    # Step 7: Quality scoring
    print("\nStep 7: Computing quality scores...")
    document_scores = []

    for classified_doc, extraction in zip(classified_docs, extraction_results):
        score = score_extracted_document(extraction, classified_doc, pages)
        document_scores.append(score)
        print(
            f"  Pages {classified_doc['start_page']}-{classified_doc['end_page']}: "
            f"quality={score['composite']:.3f} ({score['tier']})"
        )

    chart_quality = compute_chart_quality_summary(document_scores, chart_id)
    print(
        f"  Chart quality: {chart_quality['chart_composite']:.3f} "
        f"| needs_review: {chart_quality['needs_review']}"
    )

    # Step 8: FHIR R4 resource mapping
    print("\nStep 8: Mapping extracted data to FHIR R4 resources...")
    all_document_resources = []

    for extraction, score in zip(extraction_results, document_scores):
        doc_resources = map_document_to_fhir(chart_id, member_id, extraction, score)
        all_document_resources.append(doc_resources)
        print(
            f"  Pages {extraction['start_page']}-{extraction['end_page']}: "
            f"{len(doc_resources)} FHIR resource(s)"
        )

    # Step 9 (partial): Assemble and write the FHIR bundle for this chart.
    # The HealthLake import job submission happens separately via
    # submit_healthlake_import_batch(), which batches across many charts.
    print("\nStep 9: Assembling FHIR bundle...")
    bundle_key, resource_count = assemble_fhir_bundle(
        chart_id,
        member_id,
        all_document_resources,
        chart_quality,
    )
    print(f"  Bundle written: {bundle_key} ({resource_count} resources)")

    # Step 10: Tag the source chart for Glacier archival.
    print("\nStep 10: Tagging source chart for archival...")
    mark_chart_archived(chart_id, chart_pdf_key)

    summary = {
        "chart_id":          chart_id,
        "member_id":         member_id,
        "pages":             len(pages),
        "documents_found":   len(segments),
        "quality_composite": chart_quality["chart_composite"],
        "needs_review":      chart_quality["needs_review"],
        "fhir_resources":    resource_count,
        "bundle_key":        bundle_key,
        "pending_a2i":       pending_reviews,
    }

    print(f"\nChart {chart_id} complete: {summary}")
    return summary


# -----------------------------------------------------------------------
# AWS Batch job handler
# When running inside an AWS Batch array job, this is the entry point.
# The handler reads its chart assignment from the manifest using
# AWS_BATCH_JOB_ARRAY_INDEX.
# -----------------------------------------------------------------------

def batch_job_handler() -> None:
    """
    AWS Batch job handler for a single chart in an array job.

    Each array job child reads this environment variable to select its row:
    AWS_BATCH_JOB_ARRAY_INDEX (0-indexed integer).

    Reads the manifest from S3, selects the row at the array index, and
    calls process_single_chart for that chart. In a production deployment,
    the job definition passes the manifest S3 key as a parameter.
    """
    import os

    array_index  = int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", "0"))
    manifest_key = os.environ.get("MANIFEST_KEY", "manifests/batch.csv")

    # Read the manifest from S3.
    response      = s3_client.get_object(
        Bucket=CHARTS_RAW_BUCKET,
        Key=manifest_key,
    )
    manifest_data = response["Body"].read().decode("utf-8")
    reader        = csv.DictReader(io.StringIO(manifest_data))
    rows          = list(reader)

    if array_index >= len(rows):
        print(
            f"Array index {array_index} out of range "
            f"(manifest has {len(rows)} rows). Exiting."
        )
        return

    row       = rows[array_index]
    chart_id  = row["chart_id"]
    chart_key = row["key"]

    # Member ID lookup: in production, map chart_id to member_id
    # via your member directory or a DynamoDB lookup table.
    # Here we use a placeholder.
    member_id = os.environ.get("DEFAULT_MEMBER_ID", f"member-{chart_id}")

    process_single_chart(
        chart_pdf_key=chart_key,
        chart_id=chart_id,
        member_id=member_id,
    )


if __name__ == "__main__":
    # Example: run the development pipeline against a single test chart.
    result = process_single_chart(
        chart_pdf_key="charts-raw/test/CHT-TEST-000001.pdf",
        chart_id="CHT-TEST-000001",
        member_id="MEMBER-12345",
    )

    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## The Gap Between This and Production

This file demonstrates every step in the Recipe 1.10 pipeline: manifest generation through Glacier archival tagging. Run it against a real chart PDF and you will see the shape of each transformation clearly. The distance from that to something you would run against three million charts is significant. Here is where it lives.

**PDF splitting and image conversion are not implemented.** The `preprocess_chart` function above comments out the PDF-to-image conversion step because it requires a real PDF library. Install `PyMuPDF` (`pip install pymupdf`) and use `fitz.open()` to split the PDF into per-page images. Alternatively, `pdf2image` (`pip install pdf2image`) wraps `poppler` and is simpler to use. Neither is included here to avoid native library dependencies in the example, but both are well-maintained and handle the edge cases you will encounter in real charts (password-protected PDFs, corrupt page streams, mixed orientation within a single document).

**Deskew requires the deskew library, not just Pillow.** The `enhance_page` function in Step 2 comments out the angle detection call. For reliable deskewing on production charts, add `pip install deskew` and call `determine_skew()` from the `deskew` package. It uses Hough line detection to measure the actual rotation angle. The difference between skipping deskew and applying it on moderately tilted pages can shift average OCR confidence by 5 to 8 points, which moves real pages across the A2I routing threshold.

**Textract quota increase is mandatory before you start.** The default `StartDocumentAnalysis` concurrency quota is 25 jobs in most regions. For a migration program running at any real scale, you need 100 to 500 concurrent jobs minimum. File the AWS Support quota increase request at least two to four weeks before the program start date. Include your expected peak concurrent job count and total job volume in the request. This is not a "file it and it happens immediately" process.

**Comprehend Medical chunking needs span-level deduplication in production.** The `split_text_with_overlap` function produces overlapping chunks, which means the same entity can appear in two adjacent chunks. The code above does not deduplicate entities across chunks. A production implementation uses the `BeginOffset` and `EndOffset` fields that Comprehend Medical returns with each entity to identify and drop duplicates. Without this, a medication mentioned at a chunk boundary appears twice in the entity list, which creates two MedicationStatement resources for the same reference.

**FHIR status values need clinical governance.** Every Condition in this code uses `clinicalStatus = unknown` and `verificationStatus = unconfirmed`. That is the correct conservative default for OCR-derived data from paper charts. It is not a technical decision you can make unilaterally; it requires sign-off from clinical leadership and whoever is responsible for the accuracy of the downstream FHIR data store. Some organizations use `unconfirmed` for all migrated conditions. Others use a custom extension to encode migration provenance. Both approaches are defensible. The wrong approach is silently promoting migrated data to `confirmed` status, which misleads every downstream system that consumes it.

**The DynamoDB status query in submit_healthlake_import_batch is a scan.** Scanning DynamoDB at migration scale (millions of charts) is expensive and slow. Add a GSI on the `status` attribute before running the program: `aws dynamodb update-table --table-name migration-tracking --attribute-definitions AttributeName=status,AttributeType=S --global-secondary-indexes ...`. With the GSI, the query becomes an index lookup rather than a full table scan. A full table scan on a migration tracking table with five million items costs real money in read capacity units. Add the GSI on day one.

**A2I review is async and the pipeline does not wait for it.** The `extract_handwritten_document` function submits A2I tasks and returns immediately with `pending_review=True`. The FHIR resources generated for those documents in Step 8 use whatever text was directly extractable from the high-confidence pages. The reviewed corrections are not automatically applied to the FHIR bundle after review completes. A production implementation has a separate Lambda that fires when A2I writes its output, reads the corrections, updates the extraction record, regenerates the affected FHIR resources, and updates the bundle. Wiring that loop is important for data quality on handwriting-heavy charts.

**DynamoDB Decimal requirement.** Every numeric value written to DynamoDB is wrapped with `Decimal(str(value))`. Raw Python floats in `put_item` or `update_item` calls raise a `TypeError` at runtime. Any new numeric field you add to a DynamoDB write needs the same treatment. This is one of those errors that will bite you in production on a field you added at 11pm.

**No VPC or KMS configuration in this example.** A production Lambda or Batch container handling chart migration data runs inside a VPC with private subnets and VPC endpoints for every service in the pipeline: S3, Textract, Comprehend Medical, DynamoDB, HealthLake, SageMaker A2I runtime, Step Functions, Batch, KMS, and CloudWatch Logs. Chart data is among the most sensitive PHI your organization holds: complete longitudinal clinical records going back decades. S3 SSE-KMS with customer-managed keys on every bucket. DynamoDB encryption at rest. HealthLake encryption at rest. All API calls over TLS. If you take one piece of guidance from the Gap section of this entire cookbook, let it be this: PHI does not leave your VPC boundary.

**Testing.** There are no tests in this example. A production migration program has unit tests for `detect_document_boundaries` with fixture chart segments, unit tests for each FHIR mapping function with known-good entity inputs, integration tests against real API calls using synthetic chart PDFs, and end-to-end validation runs that compare FHIR output against manually reviewed ground-truth records for a sample of 200 to 500 charts. The Synthea open-source tool generates realistic synthetic patient records and clinical notes for building test fixtures. Never use real patient charts in any non-production environment.

**Textract LAYOUT feature type is what makes segmentation work.** Without LAYOUT, the boundary detection algorithm relies entirely on text pattern matching. LAYOUT_TITLE blocks fire before any text pattern matching because they are structural, not lexical. Including LAYOUT in the FeatureTypes adds no per-page cost but meaningfully improves boundary detection precision on charts that do not consistently use recognizable title lines.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.10: Historical Chart Migration](chapter01.10-historical-chart-migration) for the full architectural walkthrough, pseudocode, performance benchmarks, and the honest take on where this program gets hard at scale.*
