# Recipe 1.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.5. It shows how you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire into a live adjudication queue on Monday morning. A starting point, not a destination.
>
> This is the most complex companion file in Chapter 1. It builds directly on every pattern from Recipes 1.1 through 1.4. If you haven't read those companions yet, start there, especially Recipe 1.4. The new work in this recipe is document boundary detection, document-level (not page-level) classification, six type-specific extractors, and claim line item matching. Those four additions are what make the claims attachment problem tractable.
>
> In production, the fan-out step runs as parallel branches inside an AWS Step Functions Standard Workflow. This script runs the same extraction functions sequentially, in a single process, so you can trace each step without standing up a state machine first. The logic is identical; only the concurrency model differs.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `textract:StartDocumentAnalysis`
- `textract:GetDocumentAnalysis`
- `comprehendmedical:InferICD10CM`
- `comprehendmedical:DetectEntitiesV2`
- `s3:GetObject`
- `s3:PutObject`
- `s3:PutObjectRetention` (for S3 Object Lock on the final claims records)
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`
- `sqs:SendMessage`
- `states:StartExecution`
- `iam:PassRole`

The S3 Object Lock permissions deserve a specific note. `s3:PutObjectRetention` applies to the claims-attachment-records bucket only. That bucket must have Object Lock enabled at creation time; you cannot enable it retroactively. Enable it with GOVERNANCE mode during development, COMPLIANCE mode in production.

---

## Configuration and Constants

Everything that is really configuration rather than logic lives here, at the top. The title pattern lists, document type signatures, section header maps, and CPT description tables belong in version control, not buried inside functions. They are living documents that grow as you see more payer templates and more document formats.

```python
import boto3
import datetime
import json
import re
import time
from datetime import timezone
from decimal import Decimal


# -----------------------------------------------------------------------
# Document boundary detection: title line patterns
# -----------------------------------------------------------------------
# These strings are tested against the first 5 lines of each page (lowercased).
# A match is a strong signal that a new logical document is starting.
# When you encounter a document type your pipeline consistently misses,
# add its title variants here first. That's usually all it takes.

DOCUMENT_TITLE_PATTERNS = [
    "operative report",     "operative note",        "op note",
    "surgical report",
    "pathology report",     "cytology report",        "histology report",
    "pathologic diagnosis", "surgical pathology",
    "explanation of benefits", "eob",
    "discharge summary",    "discharge instructions", "hospital summary",
    "discharge note",
    "progress note",        "office visit note",      "outpatient visit",
    "physical therapy",     "occupational therapy",   "speech therapy",
    "therapy note",         "treatment note",         "rehabilitation",
    "itemized statement",   "itemized billing",       "billing statement",
    "patient statement",    "patient account statement",
    "radiology report",     "imaging report",         "diagnostic imaging",
    "laboratory report",    "lab report",             "laboratory results",
    "consultation report",  "referral note",
]


# -----------------------------------------------------------------------
# Document-level classification signatures
# -----------------------------------------------------------------------
# These run against the aggregated text of a full logical document segment
# (all pages in the segment concatenated), not individual pages.
# That's the core difference from Recipe 1.4's page-level signatures.
# A higher min_matches threshold is appropriate here because we have more text.

DOCUMENT_TYPE_SIGNATURES = {
    "operative_report": {
        "keywords": [
            "preoperative diagnosis", "postoperative diagnosis", "procedure performed",
            "anesthesia", "estimated blood loss", "specimen", "operative technique",
            "findings", "intraoperative", "attending surgeon", "procedure description",
            "preop", "postop",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "pathology_report": {
        "keywords": [
            "specimen", "gross description", "microscopic description",
            "diagnosis", "pathologist", "accession number", "histologic",
            "margins", "lymph node", "tumor", "pathologic staging",
            "tissue", "biopsy",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "eob": {
        "keywords": [
            "explanation of benefits", "allowed amount", "patient responsibility",
            "deductible", "coinsurance", "claim number", "paid amount",
            "billed amount", "plan paid", "coordination of benefits",
            "member id", "remittance",
        ],
        "min_matches": 3,
        "table_bonus": 2,   # EOBs are always table-heavy; tables strongly confirm this type
    },
    "discharge_summary": {
        "keywords": [
            "discharge diagnosis", "admitting diagnosis", "hospital course",
            "discharge medications", "follow-up", "discharge condition",
            "length of stay", "discharge instructions", "attending physician",
            "admission date", "discharge date",
        ],
        "min_matches": 3,
        "table_bonus": 0,
    },
    "therapy_notes": {
        "keywords": [
            "physical therapy", "occupational therapy", "speech therapy",
            "treatment session", "exercises", "range of motion", "functional status",
            "goals", "plan of care", "progress toward goals", "visit number",
            "therapeutic", "rehabilitation", "modalities",
        ],
        "min_matches": 2,
        "table_bonus": 0,
    },
    "billing_statement": {
        "keywords": [
            "charges", "total charges", "balance due", "account number",
            "payment", "invoice", "amount due", "itemized", "revenue code",
            "date of service", "procedure", "description of service",
            "facility charges", "statement date",
        ],
        "min_matches": 3,
        "table_bonus": 2,   # Billing statements are table-heavy like EOBs
    },
}


# -----------------------------------------------------------------------
# Section header maps for clinical extractors
# -----------------------------------------------------------------------
# Each extractor uses these to locate named sections in its document type.
# Same pattern as Recipe 1.4's IMAGING_SECTION_HEADERS, extended per type.

OPERATIVE_SECTIONS = {
    "preop_diagnosis":      ["preoperative diagnosis", "pre-op diagnosis", "preop dx"],
    "postop_diagnosis":     ["postoperative diagnosis", "post-op diagnosis", "postop dx",
                             "final diagnosis"],
    "procedure":            ["procedure performed", "operation performed", "procedures",
                             "operative procedure", "operation"],
    "findings":             ["findings", "intraoperative findings", "operative findings"],
    "technique":            ["operative technique", "description of procedure",
                             "procedure details", "operative description"],
    "complications":        ["complications", "intraoperative complications"],
    "specimens":            ["specimens", "specimen submitted",
                             "specimens sent to pathology", "specimen(s)"],
    "estimated_blood_loss": ["estimated blood loss", "ebl"],
}

PATHOLOGY_SECTIONS = {
    "specimen_description": ["specimen description", "gross description", "gross",
                              "specimen"],
    "microscopic":          ["microscopic description", "microscopic", "microscopic findings"],
    "diagnosis":            ["diagnosis", "pathologic diagnosis", "final diagnosis"],
    "comments":             ["comments", "note", "addendum"],
}

DISCHARGE_SECTIONS = {
    "admitting_diagnosis":   ["admitting diagnosis", "admission diagnosis", "reason for admission"],
    "hospital_course":       ["hospital course", "clinical course", "course in hospital"],
    "procedures_performed":  ["procedures performed", "procedures", "operations performed"],
    "discharge_diagnosis":   ["discharge diagnosis", "final diagnosis", "discharge diagnoses"],
    "discharge_medications": ["discharge medications", "medications on discharge",
                              "medications at discharge"],
    "follow_up":             ["follow-up", "follow up instructions", "discharge instructions",
                              "outpatient follow-up"],
    "discharge_condition":   ["condition at discharge", "discharge condition",
                              "patient condition"],
}

THERAPY_SECTIONS = {
    "subjective":       ["subjective", "patient report", "patient complaints"],
    "objective":        ["objective", "physical findings", "assessment findings"],
    "assessment":       ["assessment", "clinical assessment", "functional assessment"],
    "treatment":        ["treatment", "treatment provided", "interventions", "procedures"],
    "plan":             ["plan", "treatment plan", "goals", "home program"],
    "response":         ["response to treatment", "patient response", "progress"],
}


# -----------------------------------------------------------------------
# EOB field maps
# -----------------------------------------------------------------------
# Same normalization pattern as Recipe 1.1's FIELD_MAP, scoped to EOB documents.
# Payer EOB layouts vary enormously; these cover the most common label variants.

EOB_HEADER_FIELDS = {
    "claim_number":          ["claim number", "claim #", "claim id", "edi claim number",
                               "internal claim number"],
    "payer_name":            ["plan name", "insurance company", "payer", "carrier",
                               "health plan"],
    "check_date":            ["check date", "payment date", "eob date", "processed date",
                               "date of payment"],
    "member_id":             ["member id", "subscriber id", "member number",
                               "insurance id", "id number"],
}

EOB_SERVICE_LINE_COLUMNS = {
    "service_date":           ["date of service", "dos", "service date", "date"],
    "procedure_code":         ["procedure", "cpt", "procedure code", "service code",
                                "hcpcs", "code"],
    "billed_amount":          ["billed", "billed amount", "charge", "submitted amount",
                                "charges"],
    "allowed_amount":         ["allowed", "allowed amount", "contracted rate",
                                "negotiated rate", "approved amount"],
    "plan_paid":              ["plan paid", "paid", "insurance paid", "plan payment",
                                "amount paid"],
    "patient_responsibility": ["patient responsibility", "patient owes",
                                "your responsibility", "deductible + coinsurance",
                                "amount you owe", "patient amount"],
}


# -----------------------------------------------------------------------
# Billing statement field maps
# -----------------------------------------------------------------------
# Billing statements have different column naming conventions than EOBs.
# Both are table-structured financial documents; the column normalization
# approach is the same, but the vocabulary is provider-side rather than payer-side.

BILLING_HEADER_FIELDS = {
    "account_number":    ["account number", "account #", "patient account",
                           "account id", "encounter number"],
    "statement_date":    ["statement date", "date of statement", "billing date",
                           "invoice date"],
    "patient_name":      ["patient name", "patient", "name"],
    "total_charges":     ["total charges", "total amount", "balance due",
                           "amount due", "total balance"],
}

BILLING_SERVICE_LINE_COLUMNS = {
    "service_date":   ["date of service", "dos", "service date", "date"],
    "procedure_code": ["cpt", "procedure code", "procedure", "hcpcs", "code"],
    "revenue_code":   ["revenue code", "rev code", "rev cd"],
    "description":    ["description", "service description", "procedure description",
                        "description of service"],
    "charge_amount":  ["charge", "charges", "amount", "billed amount", "unit charge"],
}


# -----------------------------------------------------------------------
# CPT procedure description lookup
# -----------------------------------------------------------------------
# Maps CPT codes to the plain-text procedure descriptions that appear in
# operative notes. Used in Step 7 for procedure description matching when
# no explicit CPT code is written in the document.
#
# Build this table from your actual claims portfolio. Start with the top 50
# CPT codes by volume, find how they appear in your operative notes corpus,
# and populate. This is a maintenance burden with real value.

CPT_PROCEDURE_DESCRIPTIONS = {
    "27447": ["total knee arthroplasty", "total knee replacement",
              "tka", "knee replacement"],
    "27130": ["total hip arthroplasty", "total hip replacement",
              "tha", "hip replacement", "total hip"],
    "29881": ["knee arthroscopy", "arthroscopic knee", "meniscectomy",
              "arthroscopic meniscectomy"],
    "47562": ["laparoscopic cholecystectomy", "lap chole", "cholecystectomy"],
    "27245": ["femur fracture repair", "intramedullary nailing femur",
              "im nail femur", "femoral nail"],
    "23472": ["total shoulder arthroplasty", "total shoulder replacement",
              "shoulder replacement", "shoulder arthroplasty"],
    "63047": ["lumbar laminectomy", "laminectomy", "spinal decompression",
              "lumbar decompression"],
    "29827": ["shoulder arthroscopy", "arthroscopic rotator cuff repair",
              "rotator cuff repair"],
    "97110": ["therapeutic exercises", "therapeutic exercise", "strengthening"],
    "97140": ["manual therapy", "manual physical therapy", "joint mobilization"],
    "97001": ["physical therapy evaluation", "pt evaluation", "initial evaluation"],
    "99213": ["office visit", "established patient visit", "follow-up visit"],
    "88305": ["surgical pathology", "tissue examination", "pathologic examination"],
}


# -----------------------------------------------------------------------
# Thresholds and pipeline config
# -----------------------------------------------------------------------

# How similar two page headers need to be (Jaccard score 0.0-1.0) before we
# consider them the "same document." Below this threshold, the header change
# is significant enough to trigger a boundary signal.
HEADER_SIMILARITY_THRESHOLD = 0.40

# How many days difference between adjacent page dates triggers a boundary signal.
DATE_BOUNDARY_DAYS = 30

# Document classification score below this goes to the low-confidence list for review.
MIN_CLASSIFICATION_SCORE = 3

# Claim line matching: date delta tolerance in days. 1 day covers timezone and
# documentation-timing edge cases.
DATE_MATCH_TOLERANCE_DAYS = 1

# Surgical CPT code range for filtering regex matches from procedure text.
SURGICAL_CPT_MIN = 10000
SURGICAL_CPT_MAX = 69999

# Comprehend Medical character limits per API call.
# Stay well below 20,000 to avoid silent truncation.
COMPREHEND_MAX_CHARS = 10000

# ICD-10 confidence threshold: below this, codes go to the flagged list.
ICD10_CONFIDENCE_THRESHOLD = 0.70

# DynamoDB and S3 table/bucket names.
JOBS_TABLE_NAME              = "textract-jobs"
CLAIMS_ATTACHMENT_TABLE      = "claims-attachment-records"
CLAIMS_TABLE                 = "claims"              # where claim line items live
CLAIMS_ATTACHMENT_BUCKET     = "claims-attachments"
REVIEW_QUEUE_URL             = ""                    # set via environment variable

# Polling config for the development script.
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS     = 36    # 36 * 5s = 3 minutes. Large attachments can take 90+ seconds.
```

---

## Helper Functions

Shared utilities used across multiple steps. Most of these are identical to Recipe 1.4. The three new ones specific to Recipe 1.5 are `extract_header_region`, `compute_jaccard_similarity`, and `extract_primary_date_from_text`.

```python
# Module-level clients. Created once at module scope for Lambda warm container reuse.
textract_client          = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")
s3_client                = boto3.client("s3")
sqs_client               = boto3.client("sqs")
sfn_client               = boto3.client("stepfunctions")
dynamodb                 = boto3.resource("dynamodb")


def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Assemble the full text of a block by following its CHILD WORD relationships.

    Textract KEY and VALUE blocks store text in WORD children, not directly.
    This helper follows those links and concatenates the words.
    Same function as Recipe 1.4; included here for completeness.
    """
    text = ""
    if "Relationships" not in block:
        return text

    for relationship in block["Relationships"]:
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child_block = block_map.get(child_id, {})
                if child_block.get("BlockType") == "WORD":
                    text += child_block.get("Text", "") + " "

    return text.strip()


def extract_section_text(full_text: str, target_headers: list, all_section_starters: list = None) -> str:
    """
    Find a named section in a clinical document and return its text content.

    Scans the document line by line for a header that matches any string in
    target_headers. Once found, accumulates lines until the next recognized
    section boundary appears.

    Same function as Recipe 1.4 except the caller can supply their own
    section starter list (each document type has different section vocabulary).
    Falls back to a generic list if none is provided.
    """
    generic_starters = [
        "preoperative diagnosis", "postoperative diagnosis", "procedure performed",
        "anesthesia", "findings", "technique", "complications", "specimens",
        "gross description", "microscopic description", "diagnosis",
        "admitting diagnosis", "hospital course", "discharge diagnosis",
        "discharge medications", "follow-up", "subjective", "objective",
        "assessment", "plan", "treatment", "response",
        "chief complaint", "history of present illness", "impression",
    ]
    section_starters = all_section_starters or generic_starters

    lines             = full_text.split("\n")
    in_target_section = False
    section_lines     = []

    for line in lines:
        line_lower = line.lower().strip()

        if any(header in line_lower for header in target_headers):
            in_target_section = True
            continue

        if in_target_section:
            is_new_section = any(
                starter in line_lower
                for starter in section_starters
                if not any(header in line_lower for header in target_headers)
            )
            if is_new_section and line_lower:
                break

        if in_target_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def parse_tables_from_blocks(page_blocks: list, block_map: dict) -> list:
    """
    Extract TABLE blocks and convert them to row-by-row string lists.

    Same function as Recipe 1.4. Returns a list of tables; each table is
    a list of rows; each row is a list of cell text strings.
    """
    tables = []

    for block in page_blocks:
        if block.get("BlockType") != "TABLE":
            continue

        cells = {}

        for relationship in block.get("Relationships", []):
            if relationship["Type"] != "CHILD":
                continue
            for cell_id in relationship["Ids"]:
                cell_block = block_map.get(cell_id, {})
                if cell_block.get("BlockType") != "CELL":
                    continue
                row_idx   = cell_block.get("RowIndex", 0)
                col_idx   = cell_block.get("ColumnIndex", 0)
                cell_text = get_text_from_block(cell_block, block_map)
                cells[(row_idx, col_idx)] = cell_text

        if not cells:
            continue

        max_row = max(r for r, c in cells)
        max_col = max(c for r, c in cells)

        table_rows = []
        for row_idx in range(1, max_row + 1):
            row = [
                cells.get((row_idx, col_idx), "")
                for col_idx in range(1, max_col + 1)
            ]
            table_rows.append(row)

        tables.append(table_rows)

    return tables


# -----------------------------------------------------------------------
# NEW for Recipe 1.5: boundary detection helpers
# -----------------------------------------------------------------------

def extract_header_region(page_blocks: list) -> str:
    """
    Extract the text from the top 15% of a page (the header region).

    Textract bounding boxes are normalized: Top=0.0 is the top of the page,
    Top=1.0 is the bottom. The header region is everything with Top < 0.15.
    That's where facility names, document titles, patient identifiers, and
    date stamps typically live.

    This is one of the two key inputs to the boundary detection step.
    The header text on consecutive pages is compared using Jaccard similarity.
    When adjacent pages have very different headers, a document boundary is likely.

    Args:
        page_blocks: all blocks for this page

    Returns:
        Text content of the header region (may be empty for image-heavy pages).
    """
    header_lines = []

    for block in page_blocks:
        if block.get("BlockType") != "LINE":
            continue
        bounding_box = block.get("Geometry", {}).get("BoundingBox", {})
        top_position = bounding_box.get("Top", 1.0)

        if top_position < 0.15:
            line_text = block.get("Text", "").strip()
            if line_text:
                header_lines.append(line_text)

    return "\n".join(header_lines).strip()


def compute_jaccard_similarity(text_a: str, text_b: str) -> float:
    """
    Compute word-level Jaccard similarity between two text strings.

    Jaccard similarity: size of word intersection divided by size of word union.
    Returns 1.0 for identical texts, 0.0 for completely disjoint texts.

    This is the "compute_text_similarity" function referenced in the pseudocode.
    No fuzzy matching library needed: the word-set approach handles the common
    cases (same facility name with slightly different abbreviations, date changes
    in the header, minor formatting differences) without false negatives.

    A header of "Memorial Hospital Operative Report 03/15/2026" and
    "Valley Pathology Laboratory 03/15/2026" share "03/15/2026" but not the
    facility or document type words. Jaccard will be around 0.17. That's below
    the 0.40 threshold, which correctly fires a boundary signal.

    A header of "Memorial Hospital Operative Report 03/15/2026" and
    "Memorial Hospital Operative Report 03/16/2026" share most words.
    Jaccard will be around 0.80. No boundary triggered. Correct.

    Args:
        text_a: first text string
        text_b: second text string

    Returns:
        Jaccard similarity score between 0.0 and 1.0.
    """
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    if not words_a and not words_b:
        return 1.0   # both empty: treat as identical
    if not words_a or not words_b:
        return 0.0   # one empty, one not: treat as fully different

    intersection = words_a & words_b
    union        = words_a | words_b

    return len(intersection) / len(union)


# Date formats to attempt when parsing dates found in page text.
# Order matters: more specific formats first to avoid ambiguous matches.
_DATE_FORMATS = [
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y-%m-%d",
    "%B %d, %Y",    # January 15, 2026
    "%b %d, %Y",    # Jan 15, 2026
    "%B %d %Y",     # January 15 2026
    "%b %d %Y",     # Jan 15 2026
    "%d %B %Y",     # 15 January 2026
]

# Regex patterns to find candidate date strings in text.
# Each pattern group should produce a string parseable by one of _DATE_FORMATS.
_DATE_PATTERNS = [
    r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",                   # MM/DD/YYYY or MM/DD/YY
    r"\b(\d{4}-\d{2}-\d{2})\b",                           # YYYY-MM-DD
    r"\b((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)"
        r"\s+\d{1,2},?\s+\d{4})\b",                       # Month DD, YYYY
    r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\.?\s+\d{1,2},?\s+\d{4})\b",                    # Mon DD, YYYY
]


def extract_primary_date_from_text(text: str) -> datetime.date | None:
    """
    Find the most prominent date in a text string and return it as a date object.

    "Most prominent" means the first date found when scanning the text from
    the beginning. In healthcare documents, the service date or report date
    is almost always in the header or the first few lines.

    Used in boundary detection for date discontinuity analysis.

    Args:
        text: page text or header region text

    Returns:
        A datetime.date object, or None if no parseable date was found.
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
                parsed = datetime.datetime.strptime(date_string, fmt)
                return parsed.date()
            except ValueError:
                continue

    return None


def days_between(date_a: datetime.date, date_b: datetime.date) -> int:
    """
    Return the absolute number of days between two date objects.
    """
    return abs((date_a - date_b).days)
```

---

## Steps 1 and 2: Async Textract Extraction and Result Retrieval

These steps are nearly identical to Recipe 1.4. Include `LAYOUT` in `FeatureTypes`. The one meaningful addition for claims attachments: include the `claim_id` when starting the Step Functions state machine. The claim ID is what links this attachment package to the specific claim line items for the matching step in Step 7.

```python
def submit_extraction_job(
    bucket: str,
    key: str,
    claim_id: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> str:
    """
    Submit a claims attachment PDF to Textract for async multi-page analysis.

    Same as Recipe 1.4's submit_extraction_job with one addition:
    we store the claim_id alongside the job context in DynamoDB so the
    retrieve step can pass it through to the Step Functions state machine.

    Args:
        bucket:             S3 bucket containing the claims attachment PDF
        key:                S3 object key (path to the PDF)
        claim_id:           identifier linking this attachment to its claim record
        sns_topic_arn:      SNS topic ARN for Textract completion notification
        textract_role_arn:  IAM role ARN Textract uses to publish to SNS

    Returns:
        The Textract job ID.
    """
    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": bucket,
                "Name":   key,
            }
        },
        # FORMS:  key-value pairs for administrative fields in EOBs and billing statements
        # TABLES: structured grids for service line tables in EOBs and billing statements
        # LAYOUT: structural page organization (title blocks, headers, body text)
        #         LAYOUT_TITLE blocks are the primary signal for boundary detection
        FeatureTypes=["FORMS", "TABLES", "LAYOUT"],
        NotificationChannel={
            "SNSTopicArn": sns_topic_arn,
            "RoleArn":     textract_role_arn,
        },
    )

    job_id = response["JobId"]

    # Store job context in DynamoDB. The SNS notification contains only the job ID,
    # not the original S3 path or claim ID. We need all three in the retrieve step.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    jobs_table.put_item(
        Item={
            "job_id":       job_id,
            "bucket":       bucket,
            "key":          key,
            "claim_id":     claim_id,    # the addition for Recipe 1.5
            "submitted_at": datetime.datetime.now(timezone.utc).isoformat(),
            "status":       "PENDING",
        }
    )

    print(f"Submitted Textract job {job_id} for s3://{bucket}/{key} (claim_id={claim_id})")
    return job_id


def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Wait for a Textract async job to complete and retrieve all extracted blocks.

    Identical to Recipe 1.4. Textract paginates results for multi-page documents.
    A 38-page claims attachment can produce 10,000+ blocks across multiple result pages.
    We collect everything before any parsing begins.

    In production, skip the polling loop. Call this only after the SNS notification
    confirms the job succeeded.

    Args:
        job_id: Textract job ID from submit_extraction_job

    Returns:
        A tuple of (all_blocks, block_map):
        - all_blocks: flat list of every extracted block
        - block_map:  dict of block ID -> block for O(1) lookups
    """
    job_status = "IN_PROGRESS"
    attempts   = 0

    while job_status == "IN_PROGRESS" and attempts < MAX_POLL_ATTEMPTS:
        attempts  += 1
        response   = textract_client.get_document_analysis(JobId=job_id)
        job_status = response["JobStatus"]

        if job_status == "IN_PROGRESS":
            print(f"  Job {job_id} still running (attempt {attempts}/{MAX_POLL_ATTEMPTS})...")
            time.sleep(POLL_INTERVAL_SECONDS)
        elif job_status == "FAILED":
            raise RuntimeError(
                f"Textract job {job_id} failed. "
                f"StatusMessage: {response.get('StatusMessage', 'no message')}"
            )

    if job_status != "SUCCEEDED":
        raise TimeoutError(
            f"Textract job {job_id} did not complete after {MAX_POLL_ATTEMPTS} attempts. "
            f"Last status: {job_status}"
        )

    all_blocks = []
    next_token = None

    while True:
        params = {"JobId": job_id}
        if next_token is not None:
            params["NextToken"] = next_token

        response   = textract_client.get_document_analysis(**params)
        all_blocks.extend(response.get("Blocks", []))

        next_token = response.get("NextToken")
        if next_token is None:
            break

    print(f"  Retrieved {len(all_blocks)} total blocks")
    block_map = {block["Id"]: block for block in all_blocks}

    return all_blocks, block_map
```

---

## Step 3: Group Textract Blocks by Page

Same as Recipe 1.4, with one addition. We also extract the header region for each page using `extract_header_region`. The boundary detection step in Step 4 needs this separately from the full page text.

```python
def group_blocks_by_page(all_blocks: list) -> dict:
    """
    Group Textract blocks by page number and pre-compute structural features.

    Adds `header_text` to each page's data structure compared to Recipe 1.4.
    The boundary detector uses header text to detect document transitions
    via Jaccard similarity between adjacent pages.

    Args:
        all_blocks: flat block list from retrieve_all_blocks

    Returns:
        A dict of page_number (int) -> page_data dict containing:
        - blocks:        all blocks on this page
        - text:          full page text from LINE blocks
        - header_text:   text from the top 15% of the page (the header region)
        - has_tables:    True if any TABLE block is on this page
        - has_forms:     True if any KEY_VALUE_SET block is on this page
        - layout_blocks: LAYOUT_* blocks for structural signals
    """
    pages = {}

    for block in all_blocks:
        page_num = block.get("Page", 1)

        if page_num not in pages:
            pages[page_num] = {
                "blocks":        [],
                "text":          "",
                "header_text":   "",    # new for Recipe 1.5
                "has_tables":    False,
                "has_forms":     False,
                "layout_blocks": [],
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

    # Extract the header region for each page now that all blocks are grouped.
    for page_num, page_data in pages.items():
        page_data["header_text"] = extract_header_region(page_data["blocks"])

    print(f"  Grouped blocks across {len(pages)} pages")
    return pages
```

---

## Step 4: Document Boundary Detection

This is the novel step in Recipe 1.5. We scan the page stream looking for signals that indicate a new logical document has started. The output is a list of document segments, each defined by a start page, end page, and the signal that triggered the boundary.

Four signals fire in priority order. The first match on any page wins; we don't double-count. The logic is a single left-to-right pass with a small amount of rolling state.

```python
def detect_document_boundaries(pages: dict) -> list:
    """
    Analyze the page stream to find where logical document boundaries fall.

    Runs four boundary signals in priority order on each page. When a signal
    fires, the current segment closes and a new one opens. The result is a list
    of document segments that the classifier and extractors operate on.

    Signal priority (strongest to weakest):
      1. Document title line: a recognized document type title in the first 5 lines
      2. Header region discontinuity: Jaccard similarity < threshold vs. previous page
      3. Page number restart: "Page 1 of N" appearing after page 1
      4. Date discontinuity: more than DATE_BOUNDARY_DAYS between adjacent page dates

    Args:
        pages: dict from group_blocks_by_page

    Returns:
        A list of segment dicts, each containing:
        - start_page:       first page number in this segment (inclusive)
        - end_page:         last page number in this segment (inclusive)
        - boundary_signal:  the signal that closed this segment (or "end_of_document")
        - primary_date:     the most recent date seen in this segment (may be None)
    """
    sorted_page_nums = sorted(pages.keys())
    if not sorted_page_nums:
        return []

    segments      = []
    seg_start     = sorted_page_nums[0]
    prev_header   = None
    prev_date     = None

    for page_num in sorted_page_nums:
        page   = pages[page_num]
        header = page["header_text"]
        text   = page["text"]

        is_boundary     = False
        boundary_signal = None

        # Collect the first 5 lines for title and page-restart detection.
        first_lines = "\n".join(text.split("\n")[:5]).lower()

        # ---- Signal 1: Document title line ----
        # The strongest signal. When present, we're almost certainly seeing
        # the first page of a new logical document.
        for pattern in DOCUMENT_TITLE_PATTERNS:
            if pattern in first_lines:
                # Suppress this signal on page 1 of the PDF: every document has a
                # first page. We only want to split when we encounter a title AFTER
                # the very beginning of the package.
                if page_num > seg_start:
                    is_boundary     = True
                    boundary_signal = "document_title"
                break

        # ---- Signal 2: Header region discontinuity ----
        # If the page header changed meaningfully from the previous page,
        # we may have crossed a document boundary.
        # Skip if Signal 1 already fired, or if we don't have a previous header yet.
        if not is_boundary and prev_header is not None and header.strip():
            similarity = compute_jaccard_similarity(header, prev_header)
            if similarity < HEADER_SIMILARITY_THRESHOLD:
                is_boundary     = True
                boundary_signal = "header_discontinuity"

        # ---- Signal 3: Page number restart ----
        # Look for "Page 1 of N" or "1 of N" patterns in the first lines.
        # A "Page 1" appearing after the opening page is a reliable boundary.
        if not is_boundary and page_num > sorted_page_nums[0]:
            restart_match = re.search(
                r"\bpage\s+1\s+of\s+\d+\b|\b1\s+of\s+\d+\b",
                first_lines
            )
            if restart_match:
                is_boundary     = True
                boundary_signal = "page_restart"

        # ---- Signal 4: Date discontinuity ----
        # Extract the primary date from this page. If it's more than
        # DATE_BOUNDARY_DAYS from the previous page's date, flag a boundary.
        # 30 days is generous enough to not split multi-day hospital stays
        # while still catching cross-episode document transitions.
        page_date = extract_primary_date_from_text(first_lines + "\n" + header)

        if not is_boundary and page_date is not None and prev_date is not None:
            delta = days_between(page_date, prev_date)
            if delta > DATE_BOUNDARY_DAYS:
                is_boundary     = True
                boundary_signal = "date_discontinuity"

        # ---- Close the current segment and start a new one ----
        if is_boundary and page_num > seg_start:
            segments.append({
                "start_page":       seg_start,
                "end_page":         page_num - 1,
                "boundary_signal":  boundary_signal,
                "primary_date":     prev_date,
            })
            print(
                f"  Segment pages {seg_start}-{page_num - 1} closed "
                f"(signal: {boundary_signal})"
            )
            seg_start = page_num

        # Update rolling state.
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
    print(
        f"  Segment pages {seg_start}-{sorted_page_nums[-1]} closed "
        f"(signal: end_of_document)"
    )

    print(f"  Boundary detection found {len(segments)} document segment(s)")
    return segments
```

---

## Step 5: Document-Level Classification

Each segment gets classified as a unit by aggregating its page text and running keyword matching against `DOCUMENT_TYPE_SIGNATURES`. This is more accurate than Recipe 1.4's page-level approach because the full document's vocabulary is pooled.

```python
def classify_segment(segment: dict, pages: dict) -> tuple[str, int]:
    """
    Classify a single document segment using keyword and structure signals.

    Aggregates text from all pages in the segment, counts keyword hits
    against each document type signature, applies structure bonuses
    (for EOBs and billing statements, which are always table-heavy),
    and returns the highest-scoring type.

    Args:
        segment: a segment dict from detect_document_boundaries
        pages:   the full pages dict from group_blocks_by_page

    Returns:
        A tuple of (doc_type_string, score).
        doc_type_string is "unclassified" if nothing met the minimum threshold.
    """
    # Aggregate text and structural features from all pages in this segment.
    segment_text = ""
    has_tables   = False

    for page_num in range(segment["start_page"], segment["end_page"] + 1):
        if page_num in pages:
            segment_text += pages[page_num]["text"] + "\n"
            if pages[page_num]["has_tables"]:
                has_tables = True

    segment_text_lower = segment_text.lower()
    scores             = {}

    for doc_type, sig in DOCUMENT_TYPE_SIGNATURES.items():
        hits = sum(
            1 for keyword in sig["keywords"]
            if keyword in segment_text_lower
        )

        if hits < sig["min_matches"]:
            continue

        score = hits
        if has_tables and sig.get("table_bonus", 0) > 0:
            score += sig["table_bonus"]

        scores[doc_type] = score

    if not scores:
        return "unclassified", 0

    best_type  = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]

    return best_type, best_score


def classify_all_segments(segments: list, pages: dict) -> list:
    """
    Classify all document segments and return the enriched segment list.

    Args:
        segments: list from detect_document_boundaries
        pages:    the full pages dict from group_blocks_by_page

    Returns:
        The input segments list with doc_type and class_score added to each entry.
    """
    classified = []

    for segment in segments:
        doc_type, score = classify_segment(segment, pages)

        classified_segment = {
            **segment,
            "doc_type":    doc_type,
            "class_score": score,
        }

        print(
            f"  Segment pages {segment['start_page']}-{segment['end_page']}: "
            f"classified as '{doc_type}' (score: {score})"
        )
        classified.append(classified_segment)

    return classified
```

---

## Step 6: Fan-Out to Type-Specific Extractors

Six extractors, one for each document type. The clinical extractors (operative report, pathology, discharge summary, therapy notes) use Comprehend Medical. The financial extractors (EOB, billing statement) use table parsing. No clinical NLP on financial documents: it adds cost and produces no useful signal.

First, the Comprehend Medical helpers (same as Recipe 1.4):

```python
def infer_icd10_codes(diagnosis_text: str) -> tuple[list, list]:
    """
    Run Comprehend Medical InferICD10CM on a text string.

    Returns (accepted, flagged) split at ICD10_CONFIDENCE_THRESHOLD.
    Same function as Recipe 1.4.
    """
    if not diagnosis_text.strip():
        return [], []

    text = diagnosis_text[:9800]   # InferICD10CM limit is 10,000 chars

    response = comprehend_medical_client.infer_icd10_cm(Text=text)
    accepted = []
    flagged  = []

    for entity in response.get("Entities", []):
        concepts = entity.get("ICD10CMConcepts", [])
        if not concepts:
            continue

        top   = concepts[0]
        score = top.get("Score", 0.0)

        entry = {
            "text":        entity.get("Text", ""),
            "icd10_code":  top["Code"],
            "description": top["Description"],
            "confidence":  Decimal(str(round(score, 3))),
        }

        if score >= ICD10_CONFIDENCE_THRESHOLD:
            accepted.append(entry)
        else:
            flagged.append(entry)

    return accepted, flagged


def detect_clinical_entities(text: str) -> dict:
    """
    Run Comprehend Medical DetectEntitiesV2 on a text string.

    Returns a dict of category -> list of entity records.
    Same function as Recipe 1.4.
    """
    if not text.strip():
        return {}

    text = text[:COMPREHEND_MAX_CHARS]

    response             = comprehend_medical_client.detect_entities_v2(Text=text)
    entities_by_category = {}

    for entity in response.get("Entities", []):
        category = entity.get("Category", "UNKNOWN")
        record   = {
            "text":       entity.get("Text", ""),
            "type":       entity.get("Type", ""),
            "confidence": round(entity.get("Score", 0.0), 3),
            "traits": [
                t["Name"]
                for t in entity.get("Traits", [])
                if t.get("Score", 0.0) >= 0.75
            ],
        }
        entities_by_category.setdefault(category, []).append(record)

    return entities_by_category


def find_explicit_cpt_codes(procedure_text: str) -> list:
    """
    Extract 5-digit CPT code candidates from procedure text.

    Filters to the surgical CPT range (10000-69999) to reduce false positives
    from other 5-digit numbers. E/M codes (99000-99499) and radiology codes
    (70000-79999) are excluded because they don't appear as primary procedure
    codes in operative reports.

    Args:
        procedure_text: text from the procedure/technique sections

    Returns:
        List of CPT code strings in the surgical range.
    """
    candidates = re.findall(r"\b(\d{5})\b", procedure_text)
    return [
        code for code in candidates
        if SURGICAL_CPT_MIN <= int(code) <= SURGICAL_CPT_MAX
    ]


# -----------------------------------------------------------------------
# Operative Report Extractor
# -----------------------------------------------------------------------

def extract_operative_report(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from an operative report document segment.

    The operative report is the most important clinical document for claim
    support purposes. The procedure section is what links the report to a
    specific CPT code. We extract named sections explicitly, run Comprehend
    Medical on the diagnosis-rich sections, and look for any explicit CPT
    codes written in the procedure or technique sections.

    Args:
        segment_text:           aggregated text from all pages in this segment
        segment_blocks_by_page: dict of page_num -> blocks list (not used here;
                                 operative reports don't need table parsing)
        start_page:             first page of this segment in the PDF
        end_page:               last page of this segment in the PDF
        block_map:              full block ID -> block dict

    Returns:
        Extraction result dict.
    """
    # Extract named sections from the operative report.
    sections = {}
    all_section_names = list(OPERATIVE_SECTIONS.keys())
    all_section_starters = [
        h for headers in OPERATIVE_SECTIONS.values() for h in headers
    ]

    for section_name, headers in OPERATIVE_SECTIONS.items():
        extracted = extract_section_text(segment_text, headers, all_section_starters)
        if extracted.strip():
            sections[section_name] = extracted

    # ICD-10 inference from the diagnosis sections.
    # Postop diagnosis is richer than preop for code specificity.
    diagnosis_text = (
        sections.get("postop_diagnosis", "") + "\n" +
        sections.get("preop_diagnosis",  "") + "\n" +
        sections.get("findings",         "")
    ).strip()
    if not diagnosis_text:
        diagnosis_text = segment_text[:5000]   # fallback: beginning of report

    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)

    # Clinical entity extraction from the full segment text.
    # We cap at COMPREHEND_MAX_CHARS. In production, chunk long documents
    # and merge results. See the Gap to Production section.
    clinical_entities = detect_clinical_entities(segment_text[:COMPREHEND_MAX_CHARS])

    # Look for explicit CPT codes in the procedure and technique sections.
    procedure_text = (
        sections.get("procedure", "") + "\n" +
        sections.get("technique", "")
    )
    explicit_cpt_codes = find_explicit_cpt_codes(procedure_text)

    primary_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])   # dates typically in first 10 lines
    )

    print(
        f"    Operative report (pages {start_page}-{end_page}): "
        f"{len(icd10_accepted)} ICD-10 codes, "
        f"{len(explicit_cpt_codes)} explicit CPT codes"
    )

    return {
        "doc_type":           "operative_report",
        "start_page":         start_page,
        "end_page":           end_page,
        "sections":           sections,
        "icd10_codes":        icd10_accepted,
        "icd10_flagged":      icd10_flagged,
        "clinical_entities":  clinical_entities,
        "explicit_cpt_codes": explicit_cpt_codes,
        "primary_date":       primary_date.isoformat() if primary_date else None,
    }


# -----------------------------------------------------------------------
# Pathology Report Extractor
# -----------------------------------------------------------------------

def extract_pathology_report(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from a pathology or histology report.

    Follows the same pattern as the operative report extractor. Section
    extraction, then Comprehend Medical on the diagnosis section.
    Pathology reports link to the operative report's specimen section:
    the specimens described in the operative note should correspond to
    accession numbers in the pathology report.

    The accession number extraction is a simple regex here. In production,
    accession number formats vary by lab and you'd expand the pattern.
    """
    sections              = {}
    all_section_starters  = [h for headers in PATHOLOGY_SECTIONS.values() for h in headers]

    for section_name, headers in PATHOLOGY_SECTIONS.items():
        extracted = extract_section_text(segment_text, headers, all_section_starters)
        if extracted.strip():
            sections[section_name] = extracted

    # ICD-10 inference from the diagnosis section.
    diagnosis_text = sections.get("diagnosis", segment_text[:5000])
    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)

    # Entity extraction from the full report.
    clinical_entities = detect_clinical_entities(segment_text[:COMPREHEND_MAX_CHARS])

    # Extract accession number. Common format: one or two letters followed by
    # 6-10 digits. Examples: S26-00483, C2026-00123, H-123456.
    accession_match = re.search(r"\b([A-Z]{1,2}[-]?\d{2}[-]\d{4,6})\b", segment_text)
    accession_number = accession_match.group(1) if accession_match else None

    primary_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"    Pathology report (pages {start_page}-{end_page}): "
        f"{len(icd10_accepted)} ICD-10 codes, "
        f"accession: {accession_number}"
    )

    return {
        "doc_type":           "pathology_report",
        "start_page":         start_page,
        "end_page":           end_page,
        "sections":           sections,
        "accession_number":   accession_number,
        "icd10_codes":        icd10_accepted,
        "icd10_flagged":      icd10_flagged,
        "clinical_entities":  clinical_entities,
        "explicit_cpt_codes": [],    # pathology doesn't directly contain CPT codes
        "primary_date":       primary_date.isoformat() if primary_date else None,
    }


# -----------------------------------------------------------------------
# EOB Extractor
# -----------------------------------------------------------------------

def normalize_columns(header_row: list, column_map: dict) -> dict:
    """
    Map a table's header row labels to canonical column names.

    Returns a dict of column_index (0-based) -> canonical_name.
    Same pattern as Recipe 1.4's normalize_lab_columns.
    """
    col_mapping = {}
    for col_idx, header_text in enumerate(header_row):
        header_lower = header_text.lower().strip()
        for canonical_name, variants in column_map.items():
            if header_lower in variants:
                col_mapping[col_idx] = canonical_name
                break
    return col_mapping


def parse_key_value_pairs_from_blocks(blocks: list, block_map: dict) -> dict:
    """
    Extract key-value text pairs from a list of blocks.

    Same as Recipe 1.4's parse_key_value_pairs_for_page but accepts
    a flat block list instead of a page-scoped block list. Used when
    we need to scan key-value pairs across all pages in a segment.
    """
    kv_pairs = {}

    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        if "KEY" not in block.get("EntityTypes", []):
            continue

        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue

        value_block = None
        for rel in block.get("Relationships", []):
            if rel["Type"] == "VALUE":
                value_id    = rel["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue

        value_text = get_text_from_block(value_block, block_map)
        kv_pairs[key_text.lower().strip()] = value_text.strip()

    return kv_pairs


def normalize_kv_fields(raw_kv: dict, field_map: dict) -> dict:
    """
    Map raw key-value pairs to canonical field names using a field map.

    Walks the field_map; for each canonical name, searches raw_kv for a
    matching label. Returns a dict of canonical_name -> extracted_value.
    """
    normalized = {}
    for canonical_name, variants in field_map.items():
        for raw_label, value in raw_kv.items():
            if raw_label in [v.lower() for v in variants]:
                normalized[canonical_name] = value
                break
    return normalized


def extract_eob(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from an Explanation of Benefits document.

    EOBs are financial documents, not clinical ones. No Comprehend Medical.
    The value is in pulling out the service line table (what was billed,
    allowed, paid, and the patient's responsibility) and the payer's claim
    number, which may differ from the provider's claim number.

    Aggregates blocks from all pages in the segment before parsing.

    Args:
        segment_text:           aggregated page text (used for header field extraction)
        segment_blocks_by_page: dict of page_num -> block list
        start_page:             first page of this segment
        end_page:               last page of this segment
        block_map:              full block ID -> block dict

    Returns:
        Extraction result dict with header fields and service line table.
    """
    # Aggregate all blocks from all pages in this segment.
    all_segment_blocks = []
    for page_num in range(start_page, end_page + 1):
        all_segment_blocks.extend(segment_blocks_by_page.get(page_num, []))

    # Extract header fields (claim number, payer name, dates, member ID).
    raw_kv       = parse_key_value_pairs_from_blocks(all_segment_blocks, block_map)
    header_fields = normalize_kv_fields(raw_kv, EOB_HEADER_FIELDS)

    # Parse service line tables.
    all_tables    = []
    for page_num in range(start_page, end_page + 1):
        page_blocks = segment_blocks_by_page.get(page_num, [])
        all_tables.extend(parse_tables_from_blocks(page_blocks, block_map))

    service_lines = []

    for table in all_tables:
        if len(table) < 2:
            continue   # needs at least a header row and one data row

        col_mapping = normalize_columns(table[0], EOB_SERVICE_LINE_COLUMNS)
        if not col_mapping:
            continue   # couldn't recognize column headers

        for row in table[1:]:
            line_item = {}
            for col_idx, canonical_name in col_mapping.items():
                if col_idx < len(row) and row[col_idx].strip():
                    line_item[canonical_name] = row[col_idx].strip()

            # Keep rows with at minimum a service date and a billed amount.
            if "service_date" in line_item and "billed_amount" in line_item:
                service_lines.append(line_item)

    primary_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"    EOB (pages {start_page}-{end_page}): "
        f"{len(service_lines)} service line(s)"
    )

    return {
        "doc_type":      "eob",
        "start_page":    start_page,
        "end_page":      end_page,
        "claim_number":  header_fields.get("claim_number"),
        "payer_name":    header_fields.get("payer_name"),
        "check_date":    header_fields.get("check_date"),
        "member_id":     header_fields.get("member_id"),
        "service_lines": service_lines,
        "primary_date":  primary_date.isoformat() if primary_date else None,
        # EOBs don't produce ICD-10 codes or clinical entities.
        # The assembler checks for these keys; always include them.
        "icd10_codes":        [],
        "explicit_cpt_codes": [],
        "clinical_entities":  {},
    }


# -----------------------------------------------------------------------
# Discharge Summary Extractor
# -----------------------------------------------------------------------

def extract_discharge_summary(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from a hospital discharge summary.

    Follows the operative report pattern: section extraction + Comprehend Medical.
    The discharge summary adds two important things the operative report doesn't have:
    the admission date and the discharge date. These are critical for DRG-based
    facility claims, where the entire episode of care is billed as one claim.

    Admission and discharge dates are extracted via regex rather than relying on
    section extraction, because they appear in many different positions depending
    on the EHR template.
    """
    sections             = {}
    all_section_starters = [h for headers in DISCHARGE_SECTIONS.values() for h in headers]

    for section_name, headers in DISCHARGE_SECTIONS.items():
        extracted = extract_section_text(segment_text, headers, all_section_starters)
        if extracted.strip():
            sections[section_name] = extracted

    # ICD-10 from discharge diagnosis (richer and more specific than admitting).
    diagnosis_text = (
        sections.get("discharge_diagnosis",  "") + "\n" +
        sections.get("admitting_diagnosis",  "") + "\n" +
        sections.get("hospital_course",      "")[:2000]   # hospital course is long; cap it
    ).strip()
    if not diagnosis_text:
        diagnosis_text = segment_text[:5000]

    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)
    clinical_entities = detect_clinical_entities(segment_text[:COMPREHEND_MAX_CHARS])

    # Extract admission and discharge dates explicitly.
    # These label-value patterns appear in virtually every discharge summary.
    admission_date = None
    discharge_date = None

    admission_match = re.search(
        r"(?:admission date|admit date|date of admission)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        segment_text,
        re.IGNORECASE,
    )
    if admission_match:
        admission_date = extract_primary_date_from_text(admission_match.group(1))

    discharge_match = re.search(
        r"(?:discharge date|date of discharge)[:\s]+(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        segment_text,
        re.IGNORECASE,
    )
    if discharge_match:
        discharge_date = extract_primary_date_from_text(discharge_match.group(1))

    primary_date = discharge_date or admission_date or extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"    Discharge summary (pages {start_page}-{end_page}): "
        f"{len(icd10_accepted)} ICD-10 codes, "
        f"admit={admission_date}, discharge={discharge_date}"
    )

    return {
        "doc_type":           "discharge_summary",
        "start_page":         start_page,
        "end_page":           end_page,
        "sections":           sections,
        "admission_date":     admission_date.isoformat() if admission_date else None,
        "discharge_date":     discharge_date.isoformat() if discharge_date else None,
        "icd10_codes":        icd10_accepted,
        "icd10_flagged":      icd10_flagged,
        "clinical_entities":  clinical_entities,
        "explicit_cpt_codes": [],
        "primary_date":       primary_date.isoformat() if primary_date else None,
    }


# -----------------------------------------------------------------------
# Therapy Notes Extractor
# -----------------------------------------------------------------------

def extract_therapy_notes(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from physical or occupational therapy notes.

    The critical difference from other clinical extractors: therapy claims have
    one claim line per visit. A claims attachment may contain multiple visit notes
    concatenated. We extract the date of service for each visit separately, because
    date of service matching in Step 7 needs to link individual claim lines to
    individual visit notes, not to the segment as a whole.

    We find visit dates by scanning for patterns that typically appear at the
    start of each visit note (date-like strings near the beginning of recognizable
    section headers). This is heuristic and will miss some visits in poorly formatted
    notes. See the Gap to Production section.

    Sections follow THERAPY_SECTIONS. Comprehend Medical runs on the combined
    assessment and treatment text.
    """
    sections             = {}
    all_section_starters = [h for headers in THERAPY_SECTIONS.values() for h in headers]

    for section_name, headers in THERAPY_SECTIONS.items():
        extracted = extract_section_text(segment_text, headers, all_section_starters)
        if extracted.strip():
            sections[section_name] = extracted

    # Run Comprehend Medical on the assessment and treatment sections.
    clinical_text = (
        sections.get("assessment", "") + "\n" +
        sections.get("treatment",  "") + "\n" +
        sections.get("objective",  "")
    ).strip() or segment_text[:5000]

    icd10_accepted, icd10_flagged = infer_icd10_codes(clinical_text)
    clinical_entities = detect_clinical_entities(clinical_text[:COMPREHEND_MAX_CHARS])

    # Extract per-visit dates by scanning for date-like patterns near visit
    # separators. Many therapy note formats start each visit with the date
    # on a line by itself or as the first element of a "Date of Service:" label.
    visit_dates = []
    date_of_service_pattern = re.compile(
        r"(?:date of service|dos|visit date|treatment date)[:\s]+"
        r"(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})",
        re.IGNORECASE,
    )
    for match in date_of_service_pattern.finditer(segment_text):
        parsed = extract_primary_date_from_text(match.group(1))
        if parsed and parsed.isoformat() not in visit_dates:
            visit_dates.append(parsed.isoformat())

    # Fallback: if we found no labeled dates, try to extract all dates from the
    # segment header region. Not as reliable, but better than returning nothing.
    if not visit_dates:
        primary_date = extract_primary_date_from_text(
            "\n".join(segment_text.split("\n")[:15])
        )
        if primary_date:
            visit_dates = [primary_date.isoformat()]

    primary_date_value = datetime.date.fromisoformat(visit_dates[0]) if visit_dates else None

    print(
        f"    Therapy notes (pages {start_page}-{end_page}): "
        f"{len(visit_dates)} visit date(s) found"
    )

    return {
        "doc_type":           "therapy_notes",
        "start_page":         start_page,
        "end_page":           end_page,
        "sections":           sections,
        "visit_dates":        visit_dates,    # per-visit date list for line matching
        "icd10_codes":        icd10_accepted,
        "icd10_flagged":      icd10_flagged,
        "clinical_entities":  clinical_entities,
        "explicit_cpt_codes": [],
        "primary_date":       primary_date_value.isoformat() if primary_date_value else None,
    }


# -----------------------------------------------------------------------
# Billing Statement Extractor
# -----------------------------------------------------------------------

def extract_billing_statement(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Extract structured data from a provider billing statement.

    Follows the same table-parsing approach as the EOB extractor.
    Billing statements are provider-generated (not payer-generated like EOBs)
    and show the full charge breakdown at the line-item level. No clinical NLP.

    The distinction from EOBs: billing statements have revenue codes alongside
    CPT codes, and the amounts are the provider's charges, not the payer's
    allowed amounts.
    """
    all_segment_blocks = []
    for page_num in range(start_page, end_page + 1):
        all_segment_blocks.extend(segment_blocks_by_page.get(page_num, []))

    raw_kv         = parse_key_value_pairs_from_blocks(all_segment_blocks, block_map)
    header_fields  = normalize_kv_fields(raw_kv, BILLING_HEADER_FIELDS)

    all_tables = []
    for page_num in range(start_page, end_page + 1):
        page_blocks = segment_blocks_by_page.get(page_num, [])
        all_tables.extend(parse_tables_from_blocks(page_blocks, block_map))

    service_lines = []

    for table in all_tables:
        if len(table) < 2:
            continue

        col_mapping = normalize_columns(table[0], BILLING_SERVICE_LINE_COLUMNS)
        if not col_mapping:
            continue

        for row in table[1:]:
            line_item = {}
            for col_idx, canonical_name in col_mapping.items():
                if col_idx < len(row) and row[col_idx].strip():
                    line_item[canonical_name] = row[col_idx].strip()

            if "service_date" in line_item and "charge_amount" in line_item:
                service_lines.append(line_item)

    primary_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"    Billing statement (pages {start_page}-{end_page}): "
        f"{len(service_lines)} service line(s)"
    )

    return {
        "doc_type":       "billing_statement",
        "start_page":     start_page,
        "end_page":       end_page,
        "account_number": header_fields.get("account_number"),
        "statement_date": header_fields.get("statement_date"),
        "patient_name":   header_fields.get("patient_name"),
        "total_charges":  header_fields.get("total_charges"),
        "service_lines":  service_lines,
        "primary_date":   primary_date.isoformat() if primary_date else None,
        "icd10_codes":        [],
        "explicit_cpt_codes": [],
        "clinical_entities":  {},
    }


# -----------------------------------------------------------------------
# Unclassified Document Handler
# -----------------------------------------------------------------------

def extract_unclassified(
    segment_text: str,
    segment_blocks_by_page: dict,
    start_page: int,
    end_page: int,
    block_map: dict,
) -> dict:
    """
    Store raw text preview for segments that didn't classify to any known type.

    No semantic extraction. Running clinical NLP on an unknown document type
    produces noise. The examiner needs to look at this segment directly.
    A 200-character preview is enough to let a human triage quickly.
    """
    preview = segment_text[:200].strip()
    primary_date = extract_primary_date_from_text(
        "\n".join(segment_text.split("\n")[:10])
    )

    print(
        f"    Unclassified segment (pages {start_page}-{end_page}): "
        f"no type matched. Routing to human review."
    )

    return {
        "doc_type":           "unclassified",
        "start_page":         start_page,
        "end_page":           end_page,
        "raw_text_preview":   preview,
        "primary_date":       primary_date.isoformat() if primary_date else None,
        "icd10_codes":        [],
        "explicit_cpt_codes": [],
        "clinical_entities":  {},
    }


# -----------------------------------------------------------------------
# Routing Table and Fan-Out
# -----------------------------------------------------------------------

EXTRACTION_ROUTER = {
    "operative_report":  extract_operative_report,
    "pathology_report":  extract_pathology_report,
    "eob":               extract_eob,
    "discharge_summary": extract_discharge_summary,
    "therapy_notes":     extract_therapy_notes,
    "billing_statement": extract_billing_statement,
    "unclassified":      extract_unclassified,
}


def route_and_extract(
    classified_segment: dict,
    pages: dict,
    block_map: dict,
) -> dict:
    """
    Route a classified document segment to its extraction function.

    Assembles the segment text and per-page block dict before calling the extractor.
    Each extractor receives consistent arguments regardless of type.

    Args:
        classified_segment: segment dict from classify_all_segments
        pages:              full pages dict from group_blocks_by_page
        block_map:          full block ID -> block dict

    Returns:
        Extraction result dict from the appropriate extractor.
    """
    doc_type   = classified_segment["doc_type"]
    start_page = classified_segment["start_page"]
    end_page   = classified_segment["end_page"]

    # Aggregate segment text from all pages.
    segment_text = ""
    segment_blocks_by_page = {}

    for page_num in range(start_page, end_page + 1):
        if page_num in pages:
            segment_text += pages[page_num]["text"] + "\n"
            segment_blocks_by_page[page_num] = pages[page_num]["blocks"]

    extractor = EXTRACTION_ROUTER.get(doc_type, extract_unclassified)

    return extractor(
        segment_text,
        segment_blocks_by_page,
        start_page,
        end_page,
        block_map,
    )
```

---

## Step 7: Claim Line Item Matching

This step links the extracted document data back to the specific claim line items from the 837 transaction. The matching works across three dimensions: CPT code, procedure description, and date of service. We need all three because any one alone is insufficient.

```python
def get_claim_lines(claim_id: str) -> list:
    """
    Retrieve the line items for a claim from DynamoDB.

    In a real deployment, this reads from a claims database that was populated
    by the EDI intake process (the X12 837 transaction from the provider).
    Here it returns a stub for illustration. Replace this with your actual
    claims data access pattern.

    A claim line item has this shape:
    {
        "line_number":    1,
        "cpt_code":       "27447",
        "procedure_desc": "Total Knee Arthroplasty",
        "date_of_service": "2026-03-15",
        "billing_npi":    "1982374650",
        "billed_amount":  45000.00
    }

    Args:
        claim_id: identifier from the attachment trigger event

    Returns:
        List of claim line item dicts.
    """
    # In production: read from DynamoDB or your claims database.
    # claims_table = dynamodb.Table(CLAIMS_TABLE)
    # response = claims_table.query(
    #     KeyConditionExpression=boto3.dynamodb.conditions.Key("claim_id").eq(claim_id)
    # )
    # return response.get("Items", [])

    # Development stub: returns example line items.
    print(f"  WARNING: get_claim_lines using stub data for claim_id={claim_id}")
    return [
        {
            "line_number":    1,
            "cpt_code":       "27447",
            "procedure_desc": "Total Knee Arthroplasty",
            "date_of_service": "2026-03-15",
            "billing_npi":    "1982374650",
            "billed_amount":  45000.00,
        },
        {
            "line_number":    2,
            "cpt_code":       "88305",
            "procedure_desc": "Surgical Pathology, Level IV",
            "date_of_service": "2026-03-15",
            "billing_npi":    "1982374650",
            "billed_amount":  850.00,
        },
    ]


def match_to_claim_lines(
    claim_id: str,
    extraction_results: list,
) -> dict:
    """
    Match extracted document data to the claim's line items.

    For each claim line, attempts to find supporting documentation in the
    extraction results. Matching works across three dimensions:

    1. CPT code match: a document explicitly contains the claim line's CPT code.
       Confidence: "high". Requires date match to be "supported"; without it,
       goes to "needs_review" with confidence "low".

    2. Procedure description match: the document's procedure section describes
       a procedure consistent with the claim line's CPT code. Uses the
       CPT_PROCEDURE_DESCRIPTIONS lookup table. Confidence: "medium".
       Also requires date match to be "supported".

    3. Date of service match: the document's primary date (or, for therapy notes,
       any visit date) is within DATE_MATCH_TOLERANCE_DAYS of the claim line's
       date of service. This is a required dimension rather than a standalone match.

    Args:
        claim_id:           claim identifier
        extraction_results: list of extraction result dicts from route_and_extract

    Returns:
        Dict of line_number (int) -> match result dict:
        {
            "status": "supported" | "needs_review" | "no_documentation",
            "supporting_docs": [...]
        }
    """
    claim_lines  = get_claim_lines(claim_id)
    line_support = {}

    for claim_line in claim_lines:
        line_num        = claim_line["line_number"]
        cpt_code        = claim_line.get("cpt_code", "")
        dos_str         = claim_line.get("date_of_service")
        supporting_docs = []

        # Parse the claim line's date of service.
        try:
            claim_dos = datetime.date.fromisoformat(dos_str) if dos_str else None
        except ValueError:
            claim_dos = None

        for extraction in extraction_results:
            match_type = None
            date_match = False

            # ---- CPT code match ----
            explicit_codes = extraction.get("explicit_cpt_codes", [])
            if cpt_code and cpt_code in explicit_codes:
                match_type = "exact_cpt_match"

            # ---- Procedure description match ----
            # Only check if no exact CPT match and we have a procedure section.
            if match_type is None and extraction.get("sections"):
                procedure_text = (
                    extraction["sections"].get("procedure", "") + " " +
                    extraction["sections"].get("technique",  "")
                ).lower()
                known_descriptions = CPT_PROCEDURE_DESCRIPTIONS.get(cpt_code, [])
                if any(desc in procedure_text for desc in known_descriptions):
                    match_type = "procedure_description_match"

            # ---- Date of service match ----
            # For therapy notes: check all visit dates, not just primary_date.
            # A therapy segment covering three visits has three candidate dates.
            if claim_dos is not None:
                doc_dates_to_check = []

                if extraction.get("doc_type") == "therapy_notes":
                    for vd_str in extraction.get("visit_dates", []):
                        try:
                            doc_dates_to_check.append(datetime.date.fromisoformat(vd_str))
                        except ValueError:
                            pass
                else:
                    primary_str = extraction.get("primary_date")
                    if primary_str:
                        try:
                            doc_dates_to_check.append(datetime.date.fromisoformat(primary_str))
                        except ValueError:
                            pass

                    # EOBs and billing statements also have service dates in their tables.
                    # Check those too for date matching purposes.
                    for svc_line in extraction.get("service_lines", []):
                        svc_date_str = svc_line.get("service_date")
                        if svc_date_str:
                            parsed = extract_primary_date_from_text(svc_date_str)
                            if parsed:
                                doc_dates_to_check.append(parsed)
                                # Also check CPT codes from EOB service lines
                                eob_code = svc_line.get("procedure_code", "").strip()
                                if eob_code and eob_code == cpt_code:
                                    match_type = "exact_cpt_match"   # override with exact

                date_match = any(
                    days_between(claim_dos, doc_date) <= DATE_MATCH_TOLERANCE_DAYS
                    for doc_date in doc_dates_to_check
                )
            else:
                # No date of service on the claim line: skip date matching.
                date_match = True

            # ---- Record the match ----
            if match_type is not None and date_match:
                confidence = "high" if match_type == "exact_cpt_match" else "medium"
                supporting_docs.append({
                    "doc_type":   extraction["doc_type"],
                    "pages":      f"{extraction['start_page']}-{extraction['end_page']}",
                    "match_type": match_type,
                    "confidence": confidence,
                })
            elif match_type is not None and not date_match:
                supporting_docs.append({
                    "doc_type":   extraction["doc_type"],
                    "pages":      f"{extraction['start_page']}-{extraction['end_page']}",
                    "match_type": f"{match_type}_date_unconfirmed",
                    "confidence": "low",
                })

        # ---- Determine overall support status for this claim line ----
        if any(d["confidence"] in ("high", "medium") for d in supporting_docs):
            status = "supported"
        elif any(d["confidence"] == "low" for d in supporting_docs):
            status = "needs_review"
        else:
            status = "no_documentation"

        line_support[line_num] = {
            "status":          status,
            "supporting_docs": supporting_docs,
        }

        print(
            f"  Claim line {line_num} (CPT {cpt_code}): status={status}, "
            f"{len(supporting_docs)} supporting document(s)"
        )

    return line_support
```

---

## Step 8: Assemble and Store the Claims Attachment Record

The assembler collects all segment extraction results and the claim line matching output, deduplicates clinical entities across documents, and writes the final record to DynamoDB. It also sets the S3 Object Lock retention on the original PDF.

```python
def assemble_claims_attachment_record(
    attachment_key: str,
    claim_id: str,
    page_count: int,
    classified_segments: list,
    extraction_results: list,
    line_support: dict,
    pages: dict,
) -> dict:
    """
    Merge all extraction and matching results into a unified claims attachment record.

    Deduplicates ICD-10 codes across all clinical documents (keeping highest
    confidence per code), deduplicates conditions and procedures by normalized
    text, collects EOB data separately, and sets the needs_review flag.

    Args:
        attachment_key:       S3 key of the original claims attachment PDF
        claim_id:             claim identifier
        page_count:           total page count of the attachment
        classified_segments:  list from classify_all_segments
        extraction_results:   parallel list of extraction result dicts
        line_support:         dict from match_to_claim_lines
        pages:                pages dict (used for unclassified text previews)

    Returns:
        The assembled claims attachment record (not yet stored to DynamoDB).
    """
    record = {
        "attachment_key":    attachment_key,
        "claim_id":          claim_id,
        "extracted_at":      datetime.datetime.now(timezone.utc).isoformat(),
        "page_count":        page_count,
        "needs_review":      False,

        "documents_found":   len(classified_segments),
        "document_inventory": [],

        "all_icd10_codes":  [],
        "all_conditions":   [],
        "all_procedures":   [],

        "eob_data":         [],

        "claim_line_support": line_support,

        "unclassified_segments":    [],
        "low_confidence_segments":  [],
    }

    # Deduplication trackers.
    seen_icd10      = {}   # code string -> best entry (highest confidence)
    seen_conditions = set()
    seen_procedures = set()

    for segment, extraction in zip(classified_segments, extraction_results):
        # Add to document inventory.
        record["document_inventory"].append({
            "doc_type":    segment["doc_type"],
            "pages":       f"{segment['start_page']}-{segment['end_page']}",
            "class_score": segment["class_score"],
            "primary_date": segment.get("primary_date"),
        })

        # Aggregate ICD-10 codes: keep the highest-confidence entry per code.
        for code_entry in extraction.get("icd10_codes", []):
            code = code_entry["icd10_code"]
            existing = seen_icd10.get(code)
            if existing is None or float(code_entry["confidence"]) > float(existing["confidence"]):
                seen_icd10[code] = code_entry

        # Aggregate clinical entities with deduplication.
        ce = extraction.get("clinical_entities", {})

        for entity in ce.get("MEDICAL_CONDITION", []):
            normalized = entity["text"].lower().strip()
            if normalized not in seen_conditions:
                seen_conditions.add(normalized)
                record["all_conditions"].append(entity)

        for entity in ce.get("TEST_TREATMENT_PROCEDURE", []):
            normalized = entity["text"].lower().strip()
            if normalized not in seen_procedures:
                seen_procedures.add(normalized)
                record["all_procedures"].append(entity)

        # Collect EOB data.
        if extraction["doc_type"] == "eob":
            record["eob_data"].append({
                "claim_number": extraction.get("claim_number"),
                "payer_name":   extraction.get("payer_name"),
                "check_date":   extraction.get("check_date"),
                "member_id":    extraction.get("member_id"),
                "service_lines": extraction.get("service_lines", []),
            })

        # Flag unclassified and low-confidence segments.
        if segment["doc_type"] == "unclassified":
            record["unclassified_segments"].append({
                "pages":   f"{segment['start_page']}-{segment['end_page']}",
                "preview": extraction.get("raw_text_preview", ""),
            })
            record["needs_review"] = True

        elif segment["class_score"] < MIN_CLASSIFICATION_SCORE:
            record["low_confidence_segments"].append({
                "pages":      f"{segment['start_page']}-{segment['end_page']}",
                "doc_type":   segment["doc_type"],
                "class_score": segment["class_score"],
            })
            record["needs_review"] = True

    # Flag if any claim line has no documentation.
    no_doc_lines = [
        line_num for line_num, support in line_support.items()
        if support["status"] == "no_documentation"
    ]
    if no_doc_lines:
        record["needs_review"] = True
        print(
            f"  WARNING: no documentation found for claim line(s): {no_doc_lines}"
        )

    # Finalize deduplicated ICD-10 list, sorted by confidence descending.
    record["all_icd10_codes"] = sorted(
        seen_icd10.values(),
        key=lambda e: float(e["confidence"]),
        reverse=True,
    )

    return record


def store_attachment_record(record: dict) -> dict:
    """
    Write the assembled claims attachment record to DynamoDB and lock the source PDF.

    DynamoDB write uses a conditional expression to prevent duplicate records
    from at-least-once event delivery.

    S3 Object Lock in GOVERNANCE mode during development.
    Switch to COMPLIANCE mode in production. Read the Gap to Production section
    before you do. COMPLIANCE mode retention cannot be undone.

    After storing, routes to either the review queue (if needs_review is True)
    or the event bus for downstream adjudication.

    Args:
        record: assembled claims attachment record

    Returns:
        The record that was written.
    """
    def to_decimal(value):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(round(float(value), 3)))

    def convert_numerics(obj):
        """Recursively convert floats to Decimal for DynamoDB put_item calls."""
        if isinstance(obj, dict):
            return {k: convert_numerics(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_numerics(item) for item in obj]
        if isinstance(obj, float):
            return to_decimal(obj)
        return obj

    record_for_db = convert_numerics(record)

    claims_table = dynamodb.Table(CLAIMS_ATTACHMENT_TABLE)

    # Conditional write: partition key is claim_id, sort key is attachment_key.
    # This allows one claim to have multiple attachment packages (initial + supplemental)
    # while preventing duplicate writes for the same package.
    try:
        claims_table.put_item(
            Item={
                "claim_id":       record_for_db["claim_id"],
                "attachment_key": record_for_db["attachment_key"],
                **record_for_db,
            },
            ConditionExpression=(
                "attribute_not_exists(claim_id) AND attribute_not_exists(attachment_key)"
            ),
        )
        print(f"  Stored claims attachment record for {record['attachment_key']}")
    except claims_table.meta.client.exceptions.ConditionalCheckFailedException:
        print(
            f"  Record for {record['attachment_key']} already exists. "
            f"Skipping write (idempotent)."
        )
        return record

    # Set S3 Object Lock on the original PDF.
    # CMS mandates 10-year retention for Medicare claims records.
    # GOVERNANCE mode here: can be overridden during testing.
    # Change to COMPLIANCE in production (then you can't override it).
    retain_until = datetime.datetime.now(timezone.utc) + datetime.timedelta(days=365 * 10)

    try:
        s3_client.put_object_retention(
            Bucket=CLAIMS_ATTACHMENT_BUCKET,
            Key=record["attachment_key"],
            Retention={
                "Mode":            "GOVERNANCE",   # change to COMPLIANCE in production
                "RetainUntilDate": retain_until,
            },
        )
        print(f"  S3 Object Lock set (GOVERNANCE mode, retain until {retain_until.date()})")
    except s3_client.exceptions.NoSuchKey:
        print(
            f"  WARNING: Could not set Object Lock on {record['attachment_key']}. "
            f"Key not found. Was the PDF deleted before the lock was set?"
        )

    # Route to review queue or downstream adjudication.
    if record["needs_review"]:
        if REVIEW_QUEUE_URL:
            sqs_client.send_message(
                QueueUrl=REVIEW_QUEUE_URL,
                MessageBody=json.dumps({
                    "claim_id":       record["claim_id"],
                    "attachment_key": record["attachment_key"],
                    "unclassified_count":    len(record["unclassified_segments"]),
                    "low_confidence_count":  len(record["low_confidence_segments"]),
                    "no_doc_lines": [
                        ln for ln, s in record["claim_line_support"].items()
                        if s["status"] == "no_documentation"
                    ],
                }),
            )
            print(f"  Routed to review queue: {record['attachment_key']}")
        else:
            print("  WARNING: REVIEW_QUEUE_URL not set. Cannot route to review queue.")
    else:
        # In production, publish to EventBridge for downstream adjudication.
        # events_client.put_events(Entries=[{
        #     "Source":       "claims-attachment-pipeline",
        #     "DetailType":   "attachment_processed",
        #     "Detail":       json.dumps({
        #         "claim_id":       record["claim_id"],
        #         "attachment_key": record["attachment_key"],
        #     }),
        #     "EventBusName": os.environ["EVENT_BUS_NAME"],
        # }])
        print(
            f"  All claim lines supported. Ready for downstream adjudication: "
            f"{record['claim_id']}"
        )

    return record
```

---

## Putting It All Together

The full pipeline as a single callable function. Sequential execution here; Step Functions parallel branches in production.

```python
def process_claims_attachment(
    bucket: str,
    key: str,
    claim_id: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> dict:
    """
    Run the full claims attachment extraction pipeline for one multi-document PDF.

    Covers all eight steps from the Recipe 1.5 pseudocode:
      1+2. Submit async Textract job (FORMS + TABLES + LAYOUT) and retrieve blocks
      3.   Group blocks by page, extract header regions
      4.   Detect document boundaries (title lines, header changes, date discontinuity)
      5.   Classify each document segment
      6.   Fan out to type-specific extractors (sequential here; parallel in prod)
      7.   Match extracted data to claim line items
      8.   Assemble unified claims attachment record and store to DynamoDB

    Args:
        bucket:             S3 bucket containing the claims attachment PDF
        key:                S3 object key (path to the PDF)
        claim_id:           claim identifier linking this attachment to its claim record
        sns_topic_arn:      SNS topic ARN for Textract completion notifications
        textract_role_arn:  IAM role ARN Textract uses to publish to SNS

    Returns:
        The assembled claims attachment record.
    """

    # Steps 1 and 2: Submit Textract job and retrieve all blocks.
    print(f"\nSteps 1-2: Submitting Textract job for s3://{bucket}/{key}")
    job_id = submit_extraction_job(
        bucket, key, claim_id, sns_topic_arn, textract_role_arn
    )
    print(f"  Job ID: {job_id}")

    print("  Waiting for Textract and retrieving all blocks...")
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Step 3: Group blocks by page and extract header regions.
    print("\nStep 3: Grouping blocks by page...")
    pages      = group_blocks_by_page(all_blocks)
    page_count = len(pages)
    print(f"  {page_count} pages total")

    # Step 4: Document boundary detection.
    print("\nStep 4: Detecting document boundaries...")
    segments = detect_document_boundaries(pages)
    print(f"  Found {len(segments)} logical document segment(s)")

    # Step 5: Document-level classification.
    print("\nStep 5: Classifying document segments...")
    classified_segments = classify_all_segments(segments, pages)

    from collections import Counter
    type_dist = Counter(s["doc_type"] for s in classified_segments)
    print(f"  Document types found: {dict(type_dist)}")

    # Step 6: Fan out to type-specific extractors.
    # In production, Step Functions runs these as parallel branches.
    print("\nStep 6: Extracting data from each document segment...")
    extraction_results = []

    for classified_segment in classified_segments:
        print(
            f"  Extracting {classified_segment['doc_type']} "
            f"(pages {classified_segment['start_page']}-{classified_segment['end_page']})..."
        )
        extraction = route_and_extract(classified_segment, pages, block_map)
        extraction_results.append(extraction)

    # Step 7: Claim line item matching.
    print("\nStep 7: Matching extracted data to claim line items...")
    line_support = match_to_claim_lines(claim_id, extraction_results)

    # Step 8: Assemble and store the unified claims attachment record.
    print("\nStep 8: Assembling and storing claims attachment record...")
    record = assemble_claims_attachment_record(
        attachment_key=key,
        claim_id=claim_id,
        page_count=page_count,
        classified_segments=classified_segments,
        extraction_results=extraction_results,
        line_support=line_support,
        pages=pages,
    )

    stored_record = store_attachment_record(record)

    # Summary.
    supported_lines = sum(
        1 for s in line_support.values() if s["status"] == "supported"
    )
    total_lines = len(line_support)

    print(
        f"\nDone. pages={page_count}, segments={len(classified_segments)}, "
        f"icd10_codes={len(record['all_icd10_codes'])}, "
        f"claim_lines={supported_lines}/{total_lines} supported, "
        f"needs_review={record['needs_review']}"
    )

    return stored_record


# Run directly against a test attachment PDF.
if __name__ == "__main__":
    import json

    result = process_claims_attachment(
        bucket="my-claims-attachments",
        key="claims-attachments/2026/03/15/CLM-2026-0847291-attach-001.pdf",
        claim_id="CLM-2026-0847291",
        sns_topic_arn="arn:aws:sns:us-east-1:123456789012:textract-jobs",
        textract_role_arn="arn:aws:iam::123456789012:role/TextractServiceRole",
    )

    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## Lambda Handler Versions

In production, the pipeline splits across multiple Lambda functions. Steps 1-2 are `claim-start` and `claim-retrieve`. Steps 3-8 run inside a Step Functions Standard Workflow, with Step 6's six extractors as parallel branches. The handler skeletons below show the entry points.

```python
import os


def lambda_handler_claim_start(event: dict, context) -> None:
    """
    claim-start Lambda: triggered by S3 upload event for a new claims attachment.

    Submits the Textract job and records the context. Everything else
    waits for the SNS completion notification.

    The claim_id needs to arrive in the S3 object metadata or in a companion
    DynamoDB record keyed by S3 key. The S3 event alone doesn't carry it.
    """
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    # In production: extract claim_id from S3 object metadata or a lookup table.
    # s3_meta = s3_client.head_object(Bucket=bucket, Key=key)
    # claim_id = s3_meta["Metadata"].get("claim-id", "UNKNOWN")
    claim_id = os.environ.get("DEFAULT_CLAIM_ID", "UNKNOWN")   # replace with real lookup

    sns_topic_arn     = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
    textract_role_arn = os.environ["TEXTRACT_ROLE_ARN"]

    job_id = submit_extraction_job(bucket, key, claim_id, sns_topic_arn, textract_role_arn)
    print(f"Submitted job {job_id} for s3://{bucket}/{key} claim_id={claim_id}")


def lambda_handler_claim_retrieve(event: dict, context) -> None:
    """
    claim-retrieve Lambda: triggered by SNS notification from Textract.

    Retrieves all blocks, writes them to S3 (to stay under Step Functions'
    256 KB payload limit), then starts the Step Functions state machine with
    the S3 key and the claim_id.
    """
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id      = sns_message["JobId"]
    job_status  = sns_message["Status"]

    if job_status != "SUCCEEDED":
        print(f"Job {job_id} finished with status {job_status}. Skipping.")
        return

    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    response   = jobs_table.get_item(Key={"job_id": job_id})
    job_item   = response.get("Item", {})

    bucket   = job_item.get("bucket")
    key      = job_item.get("key")
    claim_id = job_item.get("claim_id")

    if not bucket or not key:
        print(f"No job context found for job_id={job_id}. Cannot process.")
        return

    all_blocks, _ = retrieve_all_blocks(job_id)

    textract_output_key = f"textract-outputs/{job_id}/blocks.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=textract_output_key,
        Body=json.dumps(all_blocks),
        ContentType="application/json",
    )

    state_machine_arn = os.environ["STATE_MACHINE_ARN"]

    sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        # Derive an idempotency token from the attachment key so a double-delivery
        # of the SNS notification doesn't start two parallel executions.
        name=re.sub(r"[^a-zA-Z0-9_-]", "_", key)[:80],
        input=json.dumps({
            "attachment_key":      key,
            "bucket":              bucket,
            "textract_output_key": textract_output_key,
            "textract_job_id":     job_id,
            "claim_id":            claim_id,
        }),
    )
    print(f"Started Step Functions execution for {key} claim_id={claim_id}")


def lambda_handler_claim_assembler(event: dict, context) -> dict:
    """
    claim-assembler Lambda: final stage in the Step Functions workflow.

    Receives the classified segments and extraction results from the parallel
    fan-out branches, runs the matching step, assembles the record, and stores it.

    In the Step Functions version, each extraction branch writes its result
    to S3 and passes the S3 key. This handler reads those results from S3
    before assembling.
    """
    attachment_key       = event["attachment_key"]
    claim_id             = event["claim_id"]
    page_count           = event["page_count"]
    classified_segments  = event["classified_segments"]
    extraction_result_keys = event["extraction_result_keys"]   # S3 keys from parallel branches

    # Read extraction results from S3 (parallel branch outputs).
    extraction_results = []
    for s3_key in extraction_result_keys:
        obj = s3_client.get_object(
            Bucket=event["bucket"],
            Key=s3_key,
        )
        extraction_results.append(json.loads(obj["Body"].read()))

    line_support = match_to_claim_lines(claim_id, extraction_results)

    record = assemble_claims_attachment_record(
        attachment_key=attachment_key,
        claim_id=claim_id,
        page_count=page_count,
        classified_segments=classified_segments,
        extraction_results=extraction_results,
        line_support=line_support,
        pages={},   # pages not needed at this stage; used only in assembly for previews
    )

    store_attachment_record(record)

    return {
        "claim_id":       claim_id,
        "attachment_key": attachment_key,
        "needs_review":   record["needs_review"],
    }
```

---

## The Gap Between This and Production

This example demonstrates the full boundary-detect, classify, fan-out-extract, match, assemble pipeline. Run it against a real claims attachment PDF and it produces a structured record with document inventory, deduplicated ICD-10 codes, clinical entities, EOB service lines, and per-claim-line support status. The distance from that to a production deployment is considerable. Here is where it lives.

**Boundary detection accuracy compounds with classification accuracy.** If boundary detection is 85% accurate and segment classification is 90% accurate over correctly segmented documents, the overall pipeline accuracy is around 76%. In a batch of 500,000 attachments, that is 120,000 packages with at least one error. Some of those errors are benign. Some are not. Build measurement infrastructure first. You cannot improve a pipeline you cannot measure.

**The boundary detection feedback loop needs to be operational on day one.** When a claims examiner corrects a segmentation error in the review queue, that correction is a labeled example. Record it. After six months of corrections, you will know which signal type causes the most errors. Is it missed title lines (a new document type you haven't added to DOCUMENT_TITLE_PATTERNS)? False positives from header discontinuity (a document with variable headers within the same type)? The signal thresholds are tunable. The pattern lists are extensible. The feedback loop is what turns an 80% pipeline into a 92% pipeline.

**Comprehend Medical character limits apply per API call.** `DetectEntitiesV2` and `InferICD10CM` both have a 20,000 character limit per request. A 6-page operative report aggregated into one string can easily exceed this. The code above clips at `COMPREHEND_MAX_CHARS` (10,000). A production implementation splits long documents into overlapping chunks (overlap by 500 characters to avoid dropping entities at chunk boundaries), runs each chunk separately, and merges results with deduplication by text span position.

**The CPT procedure description lookup table needs your data.** `CPT_PROCEDURE_DESCRIPTIONS` covers about a dozen CPT codes as an example. A production system needs the top 50 to 100 codes by claim volume in your portfolio. Pull those codes from your claims database, find how each procedure is described in your existing operative notes corpus, and populate. This is a maintenance burden. Plan for it. A recipe variant (covered in the "Variations and Extensions" section of Recipe 1.5) uses a language model for semantic CPT matching and handles the long tail better than a lookup table.

**S3 Object Lock in COMPLIANCE mode is irrevocable.** The `store_attachment_record` function above uses GOVERNANCE mode. GOVERNANCE mode can be overridden by users with `s3:BypassGovernanceRetention`. Switch to COMPLIANCE mode only in production, only on the right bucket, and only after you have confirmed your retention period is correct. A COMPLIANCE lock set on a test object with a typo in the retain-until date cannot be undone until that date. Read the Object Lock documentation before you flip this switch.

**Therapy visit date extraction is heuristic and will miss some visits.** The `extract_therapy_notes` function looks for "Date of Service:" labels and similar patterns. Therapy note templates vary. Some use "Visit Date:" or "Treatment Date:". Some print the date at the top of each note with no label at all. The pattern in the code covers the most common cases. Monitor the "no_documentation" rate for therapy CPT codes (97001, 97110, 97140, etc.) after deployment; that rate tells you how often visit date matching is failing.

**get_claim_lines is a stub.** Replace it. The claims line data comes from your EDI intake process (the X12 837 transaction). That data lives somewhere in your infrastructure: a DynamoDB table, a claims database, a data warehouse. Wire `get_claim_lines` to your actual data source before running this in any environment with real claim IDs. The stub returns hardcoded test data and will match incorrectly against real extractions.

**Dead letter queues on every Lambda.** Configure SQS DLQs on all Lambda functions in the pipeline. A claims attachment that disappears into a failed invocation silently delays adjudication of a real claim. The DLQ alarm is your safety net. If you build only one monitoring piece before going live, make it this.

**DynamoDB Decimal requirement.** Every numeric value in the record must be `Decimal`-wrapped before writing to DynamoDB. The `convert_numerics` function in `store_attachment_record` handles this recursively. Any new numeric field you add must go through the same treatment. A raw Python float in a `put_item` call raises a `TypeError` with a message that doesn't obviously point to the float.

**VPC, KMS, and encryption.** This example makes API calls without VPC configuration. A production Lambda handling claims attachments runs inside a VPC with private subnets and VPC endpoints for S3, Textract, DynamoDB, SNS, SQS, Comprehend Medical, Step Functions, KMS, and CloudWatch Logs. Claims attachments contain some of the most sensitive PHI categories: surgical operative notes, pathology results with oncologic diagnoses, full-episode discharge summaries, and financial responsibility data. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest. Step Functions execution history encrypted with SSE. Every API call over TLS.

**Testing.** There are no tests here. A production pipeline has unit tests for `detect_document_boundaries` and `classify_segment` with known-good fixture documents, integration tests against real API calls with synthetic multi-document PDFs, and a test fixture library built from the document types you actually receive. CMS publishes sample 837 transaction data. Build test fixtures from those. X12 EDI sample files provide claim line item structures. Never use real patient submissions in any non-production environment.

**Step Functions Standard Workflow execution history.** The recipe specifies Standard Workflows rather than Express Workflows. The reason: a 40-page package with a boundary detection error is only debuggable if you can inspect the execution history step by step. Standard Workflows retain execution history in the console. When the boundary detector merges two documents into one segment and the extractor produces garbage output, the execution graph shows you exactly which step produced what and what the segment boundaries were. That audit trail also satisfies CMS claims processing requirements. Do not use Express Workflows here.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.5: Claims Attachment Processing](chapter01.05-claims-attachment-processing) for the full architectural walkthrough, pseudocode, performance benchmarks, and the honest take on where this breaks in practice.*
