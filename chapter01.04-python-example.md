# Recipe 1.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.4. It is meant to show how you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire into a payer UM queue on Monday morning. Consider it a starting point, not a destination.
>
> This is the most complex companion file in Chapter 1. It builds directly on patterns from Recipes 1.1 (key-value forms parsing), 1.2 (async Textract and table extraction), and 1.3 (Comprehend Medical NLP). If you haven't read those companions yet, start there. The new work in this recipe is the page classification logic, the fan-out to specialized extractors, and the assembler that merges everything back together.
>
> In production, the fan-out step runs as parallel branches inside an AWS Step Functions Express Workflow. This script runs the same extraction functions sequentially, in a single process, so you can trace each step without standing up a state machine first. The logic is identical; only the concurrency model differs.

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
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `states:StartExecution` (if you wire up the Step Functions handoff)
- `iam:PassRole` (so Lambda can pass the Textract service role for SNS notifications)

Note the Comprehend Medical permissions: `InferICD10CM` and `DetectEntitiesV2` are distinct IAM actions. You need both.

---

## Configuration and Constants

Everything that is really configuration rather than logic lives here, at the top of the module. The page signatures, field maps, and column name tables belong in your version control history, not buried inside functions. They are living documents. Every time a new payer cover sheet template arrives with a field label you haven't seen before, you update the map here, re-deploy, and move on.

```python
# PAGE_SIGNATURES: keyword and structure signals for each page type.
#
# For each page type, this defines:
#   keywords:     words or phrases that appear on pages of this type
#   min_matches:  how many keyword hits are required before we trust the classification
#   form_bonus:   extra score points if the page has KEY_VALUE_SET blocks (form fields)
#   table_bonus:  extra score points if the page has TABLE blocks
#
# The threshold is deliberately low (2-3 keywords) because faxed pages often
# have sparse text due to scanning quality. A careful set of distinctive phrases
# compensates for quantity. "HISTORY OF PRESENT ILLNESS" on a page means
# something very specific even if you only find it once.
#
# You'll want to expand these lists over time. Start here, run against your
# actual submission corpus, and add keywords that show up on mis-classified pages.

PAGE_SIGNATURES = {
    "cover_sheet": {
        "keywords": [
            "prior authorization", "authorization request", "member name",
            "member id", "subscriber", "requesting provider", "npi",
            "requested service", "date of service", "procedure code", "cpt",
        ],
        "min_matches": 3,
        "form_bonus":  3,   # cover sheets are form documents
        "table_bonus": 0,
    },
    "clinical_note": {
        "keywords": [
            "history of present illness", "assessment", "plan", "chief complaint",
            "physical examination", "review of systems", "subjective", "objective",
            "impression", "hpi", "social history", "family history", "medications",
        ],
        "min_matches": 2,
        "form_bonus":  0,   # clinical notes are prose, not forms
        "table_bonus": 0,
    },
    "lab_results": {
        "keywords": [
            "reference range", "result", "specimen", "collected", "reported",
            "abnormal", "critical", "units", "flag", "reference interval",
            "out of range",
        ],
        "min_matches": 3,
        "form_bonus":  0,
        "table_bonus": 3,   # lab results are almost always tabular
    },
    "imaging_report": {
        "keywords": [
            "findings", "impression", "technique", "comparison", "indication",
            "radiology", "mri", "ct", "x-ray", "ultrasound", "nuclear",
            "no acute", "unremarkable",
        ],
        "min_matches": 2,
        "form_bonus":  0,
        "table_bonus": 0,
    },
    "physician_letter": {
        "keywords": [
            "dear", "to whom it may concern", "medical necessity", "i am writing",
            "requesting approval", "patient has", "sincerely", "respectfully",
            "on behalf of", "this letter",
        ],
        "min_matches": 2,
        "form_bonus":  0,
        "table_bonus": 0,
    },
}

# PA_COVER_FIELD_MAP: canonical field name -> list of label variants.
#
# This is the same pattern as Recipe 1.1's FIELD_MAP, extended for prior auth
# cover sheets. Cover sheets from different payers call the same field different
# things. "Member Name," "Patient Name," "Subscriber Name," and "Insured Name"
# all mean the same thing and all need to land in the same field in the record.
#
# Treat this as a living document. Every time a payer sends a new cover sheet
# template with a label variant you haven't seen, add it here.

PA_COVER_FIELD_MAP = {
    "member_name": [
        "member name", "patient name", "subscriber name", "insured name",
        "beneficiary name",
    ],
    "member_id": [
        "member id", "subscriber id", "member #", "id number",
        "insurance id", "member number", "beneficiary id",
    ],
    "member_dob": [
        "date of birth", "dob", "member dob", "patient dob",
        "birth date", "birthdate",
    ],
    "requesting_provider": [
        "requesting provider", "ordering physician", "rendering provider",
        "treating physician", "provider name", "ordering provider",
    ],
    "provider_npi": [
        "npi", "provider npi", "npi number", "national provider",
        "national provider identifier",
    ],
    "requesting_facility": [
        "facility", "practice name", "clinic name", "hospital",
        "ordering facility", "place of service",
    ],
    "requested_cpt": [
        "cpt code", "procedure code", "procedure", "service code",
        "requested procedure", "requested service",
    ],
    "diagnosis_code": [
        "diagnosis code", "icd-10", "icd code", "dx", "icd-10-cm",
        "diagnosis", "primary diagnosis",
    ],
    "date_of_service": [
        "date of service", "dos", "requested date", "service date",
        "anticipated date of service",
    ],
    "urgency": [
        "urgency", "urgent", "priority", "expedited", "stat",
        "request type",
    ],
}

# LAB_COLUMN_MAP: canonical column name -> list of header label variants.
#
# Printed lab result reports vary widely in their column header labels.
# Quest uses different headers than LabCorp, which uses different headers
# than a hospital system's internal lab. This map normalizes them.

LAB_COLUMN_MAP = {
    "test_name":       ["test", "test name", "analyte", "component", "description"],
    "result":          ["result", "value", "result value", "your result"],
    "units":           ["units", "unit"],
    "reference_range": [
        "reference range", "normal range", "reference interval",
        "normal values", "expected range",
    ],
    "flag":            ["flag", "abnormal flag", "indicator", "h/l"],
}

# IMAGING_SECTION_HEADERS: section names to extract from imaging reports.
# Keys are canonical section names; values are the header labels to look for.

IMAGING_SECTION_HEADERS = {
    "findings":   ["findings", "report findings"],
    "impression": ["impression", "conclusions", "summary"],
    "indication": ["indication", "clinical history", "reason for exam"],
}

# DIAGNOSIS_SECTION_HEADERS: headers that signal diagnosis-rich text in clinical notes.
# We run InferICD10CM on the text under these headers rather than on the full page,
# which keeps the API call targeted and the results more relevant.

DIAGNOSIS_SECTION_HEADERS = [
    "assessment", "assessment and plan", "diagnosis", "impression",
    "diagnoses", "dx", "problems", "active problems",
]

# CLINICAL_SECTION_STARTERS: common section headers across any clinical note.
# Used by extract_section_text to know when a section ends.
# This list could be much longer in production; this covers the common ones.

CLINICAL_SECTION_STARTERS = [
    "chief complaint", "hpi", "history of present illness", "past medical history",
    "medications", "allergies", "social history", "family history",
    "review of systems", "ros", "physical examination", "assessment",
    "assessment and plan", "plan", "diagnosis", "diagnoses", "impression",
    "problems", "active problems", "objective", "subjective",
]

# Confidence thresholds.
#
# FIELD_CONFIDENCE_THRESHOLD: Textract key-value pair confidence below this
# means the extracted field value goes to the flagged list instead of the clean record.
#
# ICD10_CONFIDENCE_THRESHOLD: Comprehend Medical inference score below this
# means the code goes to the flagged list for coder review.
#
# PAGE_REVIEW_THRESHOLD: overall page confidence below this flags the entire page
# for human review. Lower than FIELD_CONFIDENCE_THRESHOLD because some page types
# (handwritten physician letters, low-quality fax copies) legitimately produce
# lower confidence and we don't want to flag every clinical note as suspicious.

FIELD_CONFIDENCE_THRESHOLD = 85.0
ICD10_CONFIDENCE_THRESHOLD = 0.70
PAGE_REVIEW_THRESHOLD      = 75.0

# Polling config for the development script.
# In production, replace the polling loop with SNS-triggered Lambda invocations.
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS     = 20

# DynamoDB table names.
JOBS_TABLE_NAME     = "textract-jobs"         # tracks in-flight Textract jobs
PA_RECORDS_TABLE    = "prior-auth-records"    # stores completed PA records
```

---

## Helper Functions

A few small functions used across multiple steps. They live at the top rather than buried inside specific extractors.

```python
import boto3
import datetime
import json
import time
from datetime import timezone
from decimal import Decimal  # DynamoDB requires Decimal for any numeric value


# Module-level clients. Creating these once at module scope means they're
# reused across invocations inside a warm Lambda container.
textract_client          = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")
s3_client                = boto3.client("s3")
dynamodb                 = boto3.resource("dynamodb")


def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Assemble the full text of a block by following its CHILD WORD blocks.

    Textract KEY and VALUE blocks don't store text directly. They have CHILD
    relationships that point to individual WORD blocks. This helper follows
    those links and concatenates the words. Used everywhere we need to read
    text from a KEY_VALUE_SET or CELL block.
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


def get_page_text_from_blocks(page_blocks: list) -> str:
    """
    Assemble the full text of a page by concatenating its LINE blocks in order.

    LINE blocks are Textract's view of a logical text line. They already have
    their text in block["Text"], so this is simpler than get_text_from_block.
    The result is what the page classifier and clinical NLP functions receive.
    """
    lines = [
        block.get("Text", "")
        for block in page_blocks
        if block.get("BlockType") == "LINE"
    ]
    return "\n".join(lines)


def extract_section_text(page_text: str, target_headers: list) -> str:
    """
    Find a specific named section in a clinical document and return its text.

    Clinical pages have headers like "ASSESSMENT AND PLAN" or "FINDINGS"
    followed by the content of that section. This function locates the first
    matching header, then collects the text that follows it until the next
    section header appears (or the page ends).

    Args:
        page_text:       full text of the page
        target_headers:  list of header label variants to look for

    Returns:
        The text content of the matching section, or an empty string if not found.
    """
    lines             = page_text.split("\n")
    in_target_section = False
    section_lines     = []

    for line in lines:
        line_lower = line.lower().strip()

        # Check if this line is one of the target section headers
        if any(header in line_lower for header in target_headers):
            in_target_section = True
            continue   # skip the header line itself

        # Check if this line starts a new, different section
        if in_target_section:
            is_new_section = any(
                starter in line_lower
                for starter in CLINICAL_SECTION_STARTERS
                if not any(header in line_lower for header in target_headers)
            )
            if is_new_section and line_lower:
                break  # stop accumulating at the next section boundary

        if in_target_section:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def parse_tables_from_blocks(page_blocks: list, block_map: dict) -> list:
    """
    Extract TABLE blocks from a page and convert them to row-by-row text lists.

    Textract TABLE blocks contain CELL children, each with a RowIndex and
    ColumnIndex. This function collects those cells, arranges them by position,
    and returns a list of tables: each table is a list of rows, each row is a
    list of strings. The first row is assumed to be column headers.

    Args:
        page_blocks:  all blocks for this page
        block_map:    full block ID -> block lookup dict

    Returns:
        A list of tables. Each table is a list of rows.
        Each row is a list of cell text strings.
    """
    tables = []

    for block in page_blocks:
        if block.get("BlockType") != "TABLE":
            continue

        # Collect cells from this TABLE's CHILD relationships
        cells = {}  # (row_index, col_index) -> cell text

        for relationship in block.get("Relationships", []):
            if relationship["Type"] != "CHILD":
                continue
            for cell_id in relationship["Ids"]:
                cell_block = block_map.get(cell_id, {})
                if cell_block.get("BlockType") != "CELL":
                    continue
                row_idx  = cell_block.get("RowIndex", 0)
                col_idx  = cell_block.get("ColumnIndex", 0)
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
```

---

## Steps 1 and 2: Async Textract Extraction and Result Retrieval

Steps 1 and 2 follow the Recipe 1.2 pattern with one meaningful addition: include `LAYOUT` in the `FeatureTypes` list. LAYOUT blocks capture the structural organization of each page (headers, body paragraphs, key-value regions, figure captions) and those structural signals feed directly into the page classifier in Step 4.

> **Note on botocore version:** The `LAYOUT` FeatureType requires botocore 1.31.0 or later. If you're running an older version (check with `python3 -c "import botocore; print(botocore.__version__)"`), you'll get a `ParamValidationError`. Upgrade with `pip install --upgrade boto3 botocore`.

In a production deployment, `pa-start` submits the job and exits. `pa-retrieve` fires on the SNS completion notification, retrieves all result pages, writes the raw blocks to S3 (to stay under Step Functions payload limits), and starts the state machine. The script version here does all of this in sequence with a polling loop instead.

```python
def submit_extraction_job(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> str:
    """
    Submit a prior auth PDF from S3 to Textract for async multi-page analysis.

    This is what the pa-start Lambda runs when the S3 upload event fires.
    The call returns immediately with a job ID. Actual extraction happens
    in the background. Everything else waits for the SNS completion notification.

    The key difference from Recipe 1.2: we add LAYOUT to the FeatureTypes list.
    LAYOUT blocks capture the structural organization of each page and that
    structural information is what the page classifier uses in Step 4.

    Args:
        bucket:             S3 bucket where the faxed PA submission PDF lives
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      ARN of the SNS topic for job completion notifications
        textract_role_arn:  ARN of the IAM role Textract can assume to publish to SNS

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
        # FORMS:  key-value pairs (cover sheet fields, checkboxes)
        # TABLES: structured grids (lab results tables)
        # LAYOUT: structural page organization (headers, body text, key-value regions)
        #         LAYOUT is what makes page classification practical.
        #         Without it, you're classifying on keywords alone.
        FeatureTypes=["FORMS", "TABLES", "LAYOUT"],
        NotificationChannel={
            "SNSTopicArn": sns_topic_arn,
            "RoleArn":     textract_role_arn,
        },
    )

    job_id = response["JobId"]

    # Record job context in DynamoDB so pa-retrieve can look up the source
    # document when the SNS notification arrives. The SNS message contains
    # only the job ID, not the original S3 path.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    jobs_table.put_item(
        Item={
            "job_id":       job_id,
            "bucket":       bucket,
            "key":          key,
            "submitted_at": datetime.datetime.now(timezone.utc).isoformat(),
            "status":       "PENDING",
        }
    )

    print(f"Submitted Textract job {job_id} for s3://{bucket}/{key}")
    return job_id


def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Wait for a Textract async job to complete and retrieve all extracted blocks.

    Textract paginates results for multi-page documents in pages of up to 1,000
    blocks each. A 15-page prior auth submission can produce thousands of blocks
    across multiple result pages. We collect everything before any parsing begins.

    In production, skip the polling loop. Call this only after the SNS notification
    confirms the job succeeded.

    Args:
        job_id: Textract job ID from submit_extraction_job

    Returns:
        A tuple of (all_blocks, block_map):
        - all_blocks: flat list of every block Textract extracted
        - block_map:  dict of block ID -> block, for O(1) lookups by ID
    """
    # Poll until the job completes (for development scripts without SNS).
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
            f"Textract job {job_id} did not complete in time. "
            f"Last status: {job_status}"
        )

    # Collect all result pages via the pagination cursor.
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

    # Build the lookup index. Parsing follows cross-references between blocks
    # by ID constantly. Dict lookup is much faster than scanning the flat list.
    block_map = {block["Id"]: block for block in all_blocks}

    return all_blocks, block_map
```

---

## Step 3: Group Textract Blocks by Page

The Textract result is a flat list of blocks for the entire document. Every block has a `Page` attribute indicating which page it belongs to. This step groups those blocks so each page can be classified and extracted independently.

It also pre-computes the structural features the classifier needs: whether the page has form fields, whether it has tables, and the full text assembled from LINE blocks.

```python
def group_blocks_by_page(all_blocks: list) -> dict:
    """
    Group Textract blocks by page number and pre-compute structural features.

    This step prepares the per-page data structures that the classifier and
    extractors consume. By pre-computing has_tables, has_forms, and the full
    page text here, we avoid repeating that logic inside every extractor.

    Args:
        all_blocks: flat block list from retrieve_all_blocks

    Returns:
        A dict of page_number (int) -> page_data dict containing:
        - blocks:        all blocks on this page
        - text:          full page text assembled from LINE blocks
        - has_tables:    True if any TABLE block is on this page
        - has_forms:     True if any KEY_VALUE_SET block is on this page
        - layout_blocks: LAYOUT_* blocks for structural classification signals
    """
    pages = {}

    for block in all_blocks:
        page_num = block.get("Page", 1)  # Textract page numbers are 1-indexed

        if page_num not in pages:
            pages[page_num] = {
                "blocks":        [],
                "text":          "",
                "has_tables":    False,
                "has_forms":     False,
                "layout_blocks": [],
            }

        pages[page_num]["blocks"].append(block)

        # Assemble page text from LINE blocks.
        # LINE blocks are Textract's view of logical text lines. They have
        # their text in block["Text"] directly, no child traversal needed.
        if block.get("BlockType") == "LINE":
            pages[page_num]["text"] += block.get("Text", "") + "\n"

        # Note structural features for the classifier.
        if block.get("BlockType") == "TABLE":
            pages[page_num]["has_tables"] = True

        if block.get("BlockType") == "KEY_VALUE_SET":
            pages[page_num]["has_forms"] = True

        # Collect LAYOUT blocks. These signal structural organization:
        # LAYOUT_TITLE, LAYOUT_HEADER, LAYOUT_TEXT, LAYOUT_TABLE,
        # LAYOUT_FIGURE, LAYOUT_KEY_VALUE, LAYOUT_PAGE_NUMBER, etc.
        if block.get("BlockType", "").startswith("LAYOUT_"):
            pages[page_num]["layout_blocks"].append(block)

    print(f"  Grouped blocks across {len(pages)} pages")
    return pages
```

---

## Step 4: Classify Each Page

This is the step that makes the whole pipeline work. For each page, we score it against the keyword and structure signatures defined in PAGE_SIGNATURES, then assign the highest-scoring type. A page that doesn't hit the minimum threshold for any type gets labeled "other."

The classifier deliberately uses a low minimum match threshold. Faxed pages often have sparse text because of scanning quality. Two or three distinctive phrases, combined with structural signals from Textract's LAYOUT and TABLE blocks, is enough to make a reliable call on the vast majority of pages.

```python
def classify_page(page_text: str, has_tables: bool, has_forms: bool) -> str:
    """
    Classify a single page using keyword heuristics and structural signals.

    The scoring logic:
    1. Count how many keywords from each page type's signature appear in the text.
    2. If keyword hits reach the minimum match threshold, score this type.
    3. Apply structure bonuses: a page with form fields scores higher as a
       cover_sheet, a page with tables scores higher as a lab_results page.
    4. Return the highest-scoring type, or "other" if nothing matched.

    This classifier achieves roughly 85-92% accuracy on real prior auth
    submissions without any trained ML model. See the "Honest Take" section
    of Recipe 1.4 for where it falls short and what to do about it.

    Args:
        page_text:  full text of the page (from group_blocks_by_page)
        has_tables: True if the page contains TABLE blocks
        has_forms:  True if the page contains KEY_VALUE_SET blocks

    Returns:
        A page type string: one of the keys in PAGE_SIGNATURES, or "other".
    """
    text_lower = page_text.lower()
    scores     = {}

    for page_type, sig in PAGE_SIGNATURES.items():
        keyword_hits = sum(
            1 for keyword in sig["keywords"]
            if keyword in text_lower
        )

        if keyword_hits < sig["min_matches"]:
            continue  # didn't hit the minimum threshold; skip this type

        score = keyword_hits

        if has_tables and sig.get("table_bonus", 0) > 0:
            score += sig["table_bonus"]

        if has_forms and sig.get("form_bonus", 0) > 0:
            score += sig["form_bonus"]

        scores[page_type] = score

    if not scores:
        return "other"

    # Return the page type with the highest score.
    return max(scores, key=lambda t: scores[t])


def classify_all_pages(pages: dict) -> dict:
    """
    Classify every page in the submission and return a page_num -> type map.

    Args:
        pages: dict from group_blocks_by_page

    Returns:
        A dict of page_number -> page_type string.
    """
    classifications = {}

    for page_num, page_data in sorted(pages.items()):
        page_type = classify_page(
            page_data["text"],
            page_data["has_tables"],
            page_data["has_forms"],
        )
        classifications[page_num] = page_type
        print(f"  Page {page_num}: classified as '{page_type}'")

    return classifications
```

---

## Step 5: Fan-Out Extractors

Each page type goes to a different extraction function. The cover sheet uses key-value forms parsing (Recipe 1.1 pattern). Clinical notes and physician letters go through Comprehend Medical (Recipe 1.3 pattern). Lab results use table parsing (Recipe 1.2 pattern). Imaging reports use entity extraction from narrative prose.

In production, Step Functions runs these as parallel branches. Here, we call them sequentially. The logic inside each extractor is identical either way.

```python
# ------------------------------------------------------------------
# Cover Sheet Extractor
# ------------------------------------------------------------------
# Builds on Recipe 1.1's key-value parsing and field normalization pattern.
# The main additions: a prior auth specific FIELD_MAP and urgency detection.
# ------------------------------------------------------------------

def parse_key_value_pairs_for_page(page_blocks: list, block_map: dict) -> dict:
    """
    Extract key-value text pairs from a page's KEY_VALUE_SET blocks.

    This is the same logic as Recipe 1.1's forms parser, restricted to
    blocks on a single page rather than the full document.

    Returns:
        A dict of label_text -> {"value": str, "confidence": float}.
    """
    key_value_pairs = {}

    for block in page_blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue

        if "KEY" not in block.get("EntityTypes", []):
            continue   # skip VALUE blocks; we'll reach them via the KEY

        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue

        # Follow the VALUE relationship to find the paired VALUE block
        value_block = None
        for rel in block.get("Relationships", []):
            if rel["Type"] == "VALUE":
                value_id    = rel["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue

        value_text = get_text_from_block(value_block, block_map)

        # Use the lower of key confidence and value confidence as the pair score.
        # A low-confidence key label or value read means we should flag the field.
        key_confidence   = block.get("Confidence", 0.0)
        value_confidence = value_block.get("Confidence", 0.0)
        confidence       = min(key_confidence, value_confidence)

        key_value_pairs[key_text] = {
            "value":      value_text,
            "confidence": confidence,
        }

    return key_value_pairs


def normalize_cover_fields(
    raw_kv: dict,
    field_map: dict,
) -> tuple[dict, list]:
    """
    Map raw Textract label variants to canonical cover sheet field names.

    Walks the field_map. For each canonical name, looks for a matching
    label in the raw key-value pairs. Fields above FIELD_CONFIDENCE_THRESHOLD
    go into the clean output. Fields below it go to the flagged list.

    Returns:
        A tuple of (clean_fields, flagged_fields).
    """
    clean_fields   = {}
    flagged_fields = []

    for canonical_name, variants in field_map.items():
        for raw_label, data in raw_kv.items():
            if raw_label.lower().strip() in variants:
                if data["confidence"] >= FIELD_CONFIDENCE_THRESHOLD:
                    clean_fields[canonical_name] = data["value"].strip()
                else:
                    flagged_fields.append({
                        "field":           canonical_name,
                        "extracted_value": data["value"].strip(),
                        # Decimal wrapping is required: DynamoDB won't accept
                        # raw Python floats in put_item calls.
                        "confidence": Decimal(str(round(data["confidence"], 2))),
                    })
                break   # stop at the first matching label variant

    return clean_fields, flagged_fields


def extract_cover_sheet(page_data: dict, block_map: dict) -> dict:
    """
    Extract administrative fields from a prior auth cover sheet page.

    Uses key-value pair parsing and field normalization from the Recipe 1.1
    pattern, with a PA-specific field map. Returns clean fields, flagged
    low-confidence fields, and the average confidence for this page.

    Args:
        page_data:  page dict from group_blocks_by_page
        block_map:  full block ID -> block lookup dict

    Returns:
        An extraction result dict with: confidence, data, flagged.
    """
    raw_kv = parse_key_value_pairs_for_page(page_data["blocks"], block_map)

    clean_fields, flagged_fields = normalize_cover_fields(raw_kv, PA_COVER_FIELD_MAP)

    # Average confidence across all key-value pairs on this page.
    # If no pairs found, use a low default that will trigger review.
    if raw_kv:
        avg_confidence = sum(d["confidence"] for d in raw_kv.values()) / len(raw_kv)
    else:
        avg_confidence = 0.0

    return {
        "confidence": round(avg_confidence, 1),
        "data":       clean_fields,
        "flagged":    flagged_fields,
    }


# ------------------------------------------------------------------
# Clinical Page Extractor
# ------------------------------------------------------------------
# Used for both clinical_note and physician_letter page types.
# Runs InferICD10CM on the diagnosis-dense section and
# DetectEntitiesV2 on the full page text.
# Builds on Recipe 1.3's clinical NLP pattern.
# ------------------------------------------------------------------

def infer_icd10_codes(diagnosis_text: str) -> tuple[list, list]:
    """
    Use Comprehend Medical to map diagnosis text to ICD-10-CM codes.

    Same function as Recipe 1.3 Step 5. InferICD10CM returns ranked
    code candidates for each clinical entity it detects. We split at
    ICD10_CONFIDENCE_THRESHOLD: codes above it go into accepted, codes
    below it go to flagged for coder review.

    Args:
        diagnosis_text: clinical text to infer codes from

    Returns:
        A tuple of (accepted, flagged) code lists.
    """
    if not diagnosis_text.strip():
        return [], []

    response = comprehend_medical_client.infer_icd10_cm(Text=diagnosis_text)
    accepted = []
    flagged  = []

    for entity in response.get("Entities", []):
        evidence_text = entity.get("Text", "")
        concepts      = entity.get("ICD10CMConcepts", [])
        if not concepts:
            continue

        top = concepts[0]
        score = top.get("Score", 0.0)

        if score >= ICD10_CONFIDENCE_THRESHOLD:
            accepted.append({
                "text":        evidence_text,
                "icd10_code":  top["Code"],
                "description": top["Description"],
                "confidence":  Decimal(str(round(score, 3))),
            })
        else:
            flagged.append({
                "text":          evidence_text,
                "top_candidate": {
                    "icd10_code":  top["Code"],
                    "description": top["Description"],
                    "confidence":  Decimal(str(round(score, 3))),
                },
            })

    return accepted, flagged


def detect_clinical_entities(text: str) -> dict:
    """
    Extract clinical entities from text using Comprehend Medical DetectEntitiesV2.

    Same function as Recipe 1.3 Step 6. Returns a dict of
    category -> list of entity records. Includes semantic traits
    (NEGATION, PERTAINS_TO_FAMILY, PAST_HISTORY) on each entity.

    Args:
        text: clinical text up to 20,000 characters

    Returns:
        Dict of category -> list of entity dicts. Empty dict if text is empty.
    """
    if not text.strip():
        return {}

    # DetectEntitiesV2 accepts up to 20,000 characters per request.
    # Clip well below that to avoid silent truncation. In production,
    # split at sentence boundaries and merge results for long pages.
    text = text[:19500]

    response = comprehend_medical_client.detect_entities_v2(Text=text)
    entities_by_category = {}

    for entity in response.get("Entities", []):
        category = entity.get("Category", "UNKNOWN")
        record   = {
            "text":       entity.get("Text", ""),
            "type":       entity.get("Type", ""),
            "confidence": round(entity.get("Score", 0.0), 3),
            # Keep traits with high enough confidence to trust.
            # NEGATION and PERTAINS_TO_FAMILY at low confidence are noisy.
            "traits": [
                t["Name"]
                for t in entity.get("Traits", [])
                if t.get("Score", 0.0) >= 0.75
            ],
        }
        entities_by_category.setdefault(category, []).append(record)

    return entities_by_category


def get_average_line_confidence(page_blocks: list) -> float:
    """
    Calculate the average OCR confidence across LINE blocks on this page.

    This is used as the Textract-side confidence estimate for narrative pages.
    Low line confidence means the OCR quality was poor, which in turn means
    the Comprehend Medical inputs are unreliable even if the NLP score looks good.
    """
    line_confidences = [
        block.get("Confidence", 0.0)
        for block in page_blocks
        if block.get("BlockType") == "LINE"
    ]
    if not line_confidences:
        return 0.0
    return sum(line_confidences) / len(line_confidences)


def extract_clinical_page(page_data: dict, block_map: dict) -> dict:
    """
    Extract clinical evidence from a clinical note or physician letter page.

    The steps:
    1. Find the diagnosis-dense section (assessment, plan, impression) and
       run InferICD10CM on it. Using targeted text keeps costs down and
       keeps code inference results relevant.
    2. Run DetectEntitiesV2 on the full page text to capture conditions,
       medications, procedures, and semantic traits.
    3. Calculate page confidence as the minimum of Textract line confidence
       and the average NLP entity confidence (normalized to 0-100).
       OCR quality directly affects NLP accuracy: bad OCR means bad NLP input,
       so we don't let a high NLP score mask a low OCR score.

    Args:
        page_data:  page dict from group_blocks_by_page
        block_map:  full block ID -> block lookup dict

    Returns:
        An extraction result dict with: confidence, data, flagged.
    """
    page_text = page_data["text"]

    # Find the diagnosis-rich section for ICD-10 inference.
    # Fall back to the first 5,000 characters of the full page text if
    # no recognizable section header was found.
    diagnosis_text = extract_section_text(page_text, DIAGNOSIS_SECTION_HEADERS)
    if len(diagnosis_text.strip()) < 20:
        # Section was empty or too short; use the beginning of the page.
        diagnosis_text = page_text[:5000]

    # Limit: InferICD10CM accepts up to 10,000 characters.
    if len(diagnosis_text) > 9800:
        diagnosis_text = diagnosis_text[:9800]

    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)

    # DetectEntitiesV2 on the full page for conditions, medications, procedures.
    clinical_entities = detect_clinical_entities(page_text)

    # Composite confidence: min of Textract OCR confidence and NLP confidence.
    # NLP confidence is on a 0-1 scale; multiply by 100 to normalize.
    textract_confidence = get_average_line_confidence(page_data["blocks"])
    if icd10_accepted:
        # Average the confidence values (convert from Decimal back to float for math)
        nlp_confidence = sum(float(c["confidence"]) for c in icd10_accepted) / len(icd10_accepted)
    else:
        nlp_confidence = 1.0   # no inferences doesn't mean poor quality; use neutral value

    page_confidence = min(textract_confidence, nlp_confidence * 100)

    print(
        f"    Clinical page: {len(icd10_accepted)} ICD-10 codes accepted, "
        f"{len(icd10_flagged)} flagged. "
        f"Confidence: {page_confidence:.1f}"
    )

    return {
        "confidence": round(page_confidence, 1),
        "data": {
            "icd10_accepted":   icd10_accepted,
            "clinical_entities": clinical_entities,
        },
        "flagged": {
            "icd10_flagged": icd10_flagged,
        },
    }


# ------------------------------------------------------------------
# Lab Results Extractor
# ------------------------------------------------------------------
# Parses Textract TABLE blocks from the page into structured lab value rows.
# Builds on the table parsing pattern from Recipe 1.2.
# ------------------------------------------------------------------

def normalize_lab_columns(header_row: list, column_map: dict) -> dict:
    """
    Map header row labels to canonical column names using LAB_COLUMN_MAP.

    Returns:
        A dict of column_index (0-based) -> canonical_name.
        Only columns whose headers matched are included.
    """
    col_mapping = {}
    for col_idx, header_text in enumerate(header_row):
        header_lower = header_text.lower().strip()
        for canonical_name, variants in column_map.items():
            if header_lower in variants:
                col_mapping[col_idx] = canonical_name
                break
    return col_mapping


def extract_lab_page(page_data: dict, block_map: dict) -> dict:
    """
    Extract lab result rows from a lab results page.

    Finds TABLE blocks on the page, identifies the header row, normalizes
    column names against LAB_COLUMN_MAP, and extracts each data row as a
    structured dict. Rows missing both test_name and result are skipped.

    Args:
        page_data:  page dict from group_blocks_by_page
        block_map:  full block ID -> block lookup dict

    Returns:
        An extraction result dict with: confidence, data, flagged.
    """
    tables     = parse_tables_from_blocks(page_data["blocks"], block_map)
    lab_values = []

    for table in tables:
        if len(table) < 2:
            # A table with only a header row (or no rows) isn't lab results.
            continue

        header_row  = table[0]
        col_mapping = normalize_lab_columns(header_row, LAB_COLUMN_MAP)

        if not col_mapping:
            # We couldn't recognize any column headers. Skip this table.
            # In production, log this for table header vocabulary expansion.
            continue

        for row in table[1:]:   # skip the header row
            lab_entry = {}
            for col_idx, canonical_name in col_mapping.items():
                if col_idx < len(row):
                    cell_value = row[col_idx].strip()
                    if cell_value:
                        lab_entry[canonical_name] = cell_value

            # Only keep rows with at minimum a test name and a result value.
            if "test_name" in lab_entry and "result" in lab_entry:
                lab_values.append(lab_entry)

    # Page confidence for lab pages: average TABLE CELL confidence.
    # (CELL blocks have their own confidence scores from Textract.)
    cell_confidences = [
        block.get("Confidence", 0.0)
        for block in page_data["blocks"]
        if block.get("BlockType") == "CELL"
    ]
    if cell_confidences:
        avg_confidence = sum(cell_confidences) / len(cell_confidences)
    else:
        avg_confidence = get_average_line_confidence(page_data["blocks"])

    print(f"    Lab page: {len(lab_values)} result rows extracted")

    return {
        "confidence": round(avg_confidence, 1),
        "data":       {"lab_values": lab_values},
        "flagged":    [],
    }


# ------------------------------------------------------------------
# Imaging Report Extractor
# ------------------------------------------------------------------
# Extracts named sections (findings, impression, indication) from imaging
# report prose, then runs DetectEntitiesV2 on those sections.
# ------------------------------------------------------------------

def extract_imaging_page(page_data: dict, block_map: dict) -> dict:
    """
    Extract sections and clinical entities from an imaging report page.

    Imaging reports are narrative prose organized into recognizable sections.
    We extract those sections by name (findings, impression, indication) and
    run entity detection on the combined text to surface clinical findings.
    The raw section text is also stored so downstream systems can display it.

    Args:
        page_data:  page dict from group_blocks_by_page
        block_map:  full block ID -> block lookup dict (unused but kept consistent)

    Returns:
        An extraction result dict with: confidence, data, flagged.
    """
    page_text = page_data["text"]
    sections  = {}

    for section_name, headers in IMAGING_SECTION_HEADERS.items():
        section_text = extract_section_text(page_text, headers)
        if section_text.strip():
            sections[section_name] = section_text

    # Run entity detection on the sections where clinical findings live.
    # If no sections were found, fall back to the full page text.
    if sections:
        relevant_text = "\n\n".join(sections.values())
    else:
        relevant_text = page_text[:5000]

    clinical_entities = detect_clinical_entities(relevant_text)

    textract_confidence = get_average_line_confidence(page_data["blocks"])

    print(
        f"    Imaging page: {len(sections)} sections extracted, "
        f"confidence: {textract_confidence:.1f}"
    )

    return {
        "confidence": round(textract_confidence, 1),
        "data": {
            "sections":          sections,
            "clinical_entities": clinical_entities,
        },
        "flagged": [],
    }


# ------------------------------------------------------------------
# Other Page Handler
# ------------------------------------------------------------------
# Pages that didn't match any known type. We store their raw text only.
# No semantic extraction is attempted: running NLP on an unknown page type
# produces noisy results, not useful data.
# ------------------------------------------------------------------

def extract_other_page(page_data: dict, block_map: dict) -> dict:
    """
    Return raw text only for pages that didn't match a known type.

    Used for "other" classified pages. Raw text is preserved for human
    review. No Comprehend Medical calls are made: running NLP on pages
    of unknown type produces noise, not signal.
    """
    textract_confidence = get_average_line_confidence(page_data["blocks"])

    return {
        "confidence": round(textract_confidence, 1),
        "data":       {"raw_text": page_data["text"]},
        "flagged":    [],
    }


# ------------------------------------------------------------------
# Routing Function
# ------------------------------------------------------------------

# Dispatch table: page type string -> extractor function
EXTRACTION_ROUTER = {
    "cover_sheet":      extract_cover_sheet,
    "clinical_note":    extract_clinical_page,
    "physician_letter": extract_clinical_page,   # same extractor as clinical_note
    "lab_results":      extract_lab_page,
    "imaging_report":   extract_imaging_page,
    "other":            extract_other_page,
}


def route_and_extract(
    page_num: int,
    page_type: str,
    page_data: dict,
    block_map: dict,
) -> dict:
    """
    Route a classified page to its extraction function and return the result.

    The result always includes page_num, page_type, confidence, data, and flagged.
    These consistent keys are what the assembler in Step 6 expects.

    Args:
        page_num:   page number (1-indexed)
        page_type:  classification string from classify_all_pages
        page_data:  page dict from group_blocks_by_page
        block_map:  full block ID -> block lookup dict

    Returns:
        An extraction result dict.
    """
    extractor = EXTRACTION_ROUTER.get(page_type, extract_other_page)
    result    = extractor(page_data, block_map)

    return {
        "page_num":   page_num,
        "page_type":  page_type,
        "confidence": result["confidence"],
        "data":       result["data"],
        "flagged":    result["flagged"],
    }
```

---

## Step 6: Assemble the Structured Prior Auth Record

The assembler collects extraction results from all pages and merges them into a single prior auth record. The interesting problems here are deduplication (the same ICD-10 code might be extracted from three different pages), confidence aggregation, and handling absent page types gracefully.

```python
def assemble_prior_auth_record(
    document_key: str,
    page_count: int,
    page_extractions: dict,
) -> dict:
    """
    Merge per-page extraction results into a single structured prior auth record.

    The deduplication logic deserves attention. The same ICD-10 code might
    appear on the cover sheet (as a printed code), in a clinical note (inferred
    from diagnosis text), and in a physician letter (inferred again). We want
    one canonical entry per code, keeping the highest-confidence instance.
    The same principle applies to clinical entities.

    After deduplication, the assembler sets needs_review=True if any page was
    low-confidence, any field was flagged, or essential administrative fields
    (member ID or CPT code) are missing. Those conditions mean a human needs
    to verify the record before it drives a downstream decision.

    Args:
        document_key:     S3 key of the source PDF
        page_count:       total number of pages in the submission
        page_extractions: dict of page_num -> extraction result dict

    Returns:
        The assembled prior auth record (not yet stored to DynamoDB).
    """
    record = {
        "document_key": document_key,
        "extracted_at": datetime.datetime.now(timezone.utc).isoformat(),
        "page_count":   page_count,
        "needs_review": False,

        # page_num (str) -> page_type, for audit and downstream consumption
        "page_classifications": {},

        "demographics": {
            "member_name": None,
            "member_id":   None,
            "member_dob":  None,
        },
        "requested_service": {
            "cpt_code":        None,
            "procedure":       None,
            "date_of_service": None,
            "urgency":         "routine",
        },
        "requesting_provider": {
            "name":     None,
            "npi":      None,
            "facility": None,
        },
        "clinical_evidence": {
            "icd10_codes":        [],   # deduplicated; highest confidence per code
            "conditions":         [],
            "medications":        [],
            "procedures":         [],
            "lab_values":         [],
            "imaging_sections":   {},
        },

        # Confidence and review metadata
        "page_confidence": {},      # page_num -> confidence score
        "flagged_pages":   [],      # pages below PAGE_REVIEW_THRESHOLD
        "flagged_fields":  {},      # page_num -> flagged field list
    }

    # Deduplication trackers
    seen_icd10    = {}   # code string -> best entry dict (we keep highest confidence)
    seen_conditions  = set()
    seen_medications = set()
    seen_procedures  = set()

    for page_num, extraction in sorted(page_extractions.items()):
        page_type  = extraction["page_type"]
        confidence = extraction["confidence"]
        page_key   = str(page_num)   # JSON keys are strings; be consistent

        # Track classification and confidence
        record["page_classifications"][page_key] = page_type
        record["page_confidence"][page_key]      = confidence

        # Flag pages below the review confidence threshold
        if confidence < PAGE_REVIEW_THRESHOLD:
            record["flagged_pages"].append(page_num)
            record["needs_review"] = True

        # Track flagged fields from within the page's extraction
        flagged = extraction.get("flagged", {})
        if flagged:
            # flagged can be a list (cover sheet) or a dict (clinical page)
            # Normalize both to the same structure in the record
            if isinstance(flagged, list) and len(flagged) > 0:
                record["flagged_fields"][page_key] = flagged
                record["needs_review"] = True
            elif isinstance(flagged, dict):
                # Clinical pages return {"icd10_flagged": [...]}
                icd_flagged = flagged.get("icd10_flagged", [])
                if icd_flagged:
                    record["flagged_fields"][page_key] = icd_flagged
                    record["needs_review"] = True

        data = extraction.get("data", {})

        # --- Cover sheet ---
        if page_type == "cover_sheet":
            # First cover sheet wins for most fields.
            # (Two-page cover sheets: if the first page left a field null,
            # we'd want to fill it from the second. That case is noted in
            # the Gap to Production section.)
            if record["demographics"]["member_name"] is None:
                record["demographics"]["member_name"] = data.get("member_name")
                record["demographics"]["member_id"]   = data.get("member_id")
                record["demographics"]["member_dob"]  = data.get("member_dob")

            if record["requested_service"]["cpt_code"] is None:
                record["requested_service"]["cpt_code"]        = data.get("requested_cpt")
                record["requested_service"]["procedure"]       = data.get("requested_cpt")
                record["requested_service"]["date_of_service"] = data.get("date_of_service")

                urgency_text = (data.get("urgency") or "").lower()
                if "urgent" in urgency_text or "stat" in urgency_text or "expedited" in urgency_text:
                    record["requested_service"]["urgency"] = "urgent"

            if record["requesting_provider"]["npi"] is None:
                record["requesting_provider"]["name"]     = data.get("requesting_provider")
                record["requesting_provider"]["npi"]      = data.get("provider_npi")
                record["requesting_provider"]["facility"] = data.get("requesting_facility")

        # --- Clinical note and physician letter ---
        elif page_type in ("clinical_note", "physician_letter"):
            # Deduplicate ICD-10 codes: keep the highest-confidence entry per code.
            for code_entry in data.get("icd10_accepted", []):
                code = code_entry["icd10_code"]
                existing = seen_icd10.get(code)
                if existing is None or float(code_entry["confidence"]) > float(existing["confidence"]):
                    seen_icd10[code] = code_entry

            # Deduplicate clinical entities by normalized text.
            ce = data.get("clinical_entities", {})

            for entity in ce.get("MEDICAL_CONDITION", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_conditions:
                    seen_conditions.add(normalized)
                    record["clinical_evidence"]["conditions"].append(entity)

            for entity in ce.get("MEDICATION", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_medications:
                    seen_medications.add(normalized)
                    record["clinical_evidence"]["medications"].append(entity)

            for entity in ce.get("TEST_TREATMENT_PROCEDURE", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_procedures:
                    seen_procedures.add(normalized)
                    record["clinical_evidence"]["procedures"].append(entity)

        # --- Imaging report ---
        elif page_type == "imaging_report":
            # Imaging reports contribute section text and clinical entities.
            for section_name, section_text in data.get("sections", {}).items():
                if section_name not in record["clinical_evidence"]["imaging_sections"]:
                    record["clinical_evidence"]["imaging_sections"][section_name] = section_text

            # Also merge any clinical entities found in the imaging report.
            # Imaging reports can mention medications (contrast agents, current meds)
            # and procedures (prior surgeries noted in history sections).
            ce = data.get("clinical_entities", {})
            for entity in ce.get("MEDICAL_CONDITION", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_conditions:
                    seen_conditions.add(normalized)
                    record["clinical_evidence"]["conditions"].append(entity)
            for entity in ce.get("MEDICATION", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_medications:
                    seen_medications.add(normalized)
                    record["clinical_evidence"]["medications"].append(entity)
            for entity in ce.get("TEST_TREATMENT_PROCEDURE", []):
                normalized = entity["text"].lower().strip()
                if normalized not in seen_procedures:
                    seen_procedures.add(normalized)
                    record["clinical_evidence"]["procedures"].append(entity)

        # --- Lab results ---
        elif page_type == "lab_results":
            # Lab values are additive: different pages may be different test runs.
            # No deduplication here by design.
            record["clinical_evidence"]["lab_values"].extend(
                data.get("lab_values", [])
            )

    # Finalize the deduplicated ICD-10 code list, sorted by confidence descending.
    record["clinical_evidence"]["icd10_codes"] = sorted(
        seen_icd10.values(),
        key=lambda e: float(e["confidence"]),
        reverse=True,
    )

    # Flag if essential fields are missing.
    # A record without member ID or CPT code cannot drive a downstream decision.
    if record["demographics"]["member_id"] is None:
        record["needs_review"] = True
        print("  WARNING: member_id not found. Flagging for review.")

    if record["requested_service"]["cpt_code"] is None:
        record["needs_review"] = True
        print("  WARNING: requested CPT code not found. Flagging for review.")

    return record


def store_prior_auth_record(record: dict) -> dict:
    """
    Write the assembled prior auth record to DynamoDB.

    Uses the document_key as the primary key. Conditional write prevents
    overwriting a record that already exists (idempotency: S3 events and SNS
    are both at-least-once; the same submission can trigger this function twice).

    If the record doesn't need human review, this is also where you'd publish
    to the event bus to trigger clinical criteria matching (Recipe 2.4).

    Args:
        record: assembled prior auth record from assemble_prior_auth_record

    Returns:
        The record that was written.
    """
    pa_table = dynamodb.Table(PA_RECORDS_TABLE)

    # Decimal conversion for all numeric fields.
    # DynamoDB does not accept Python floats in put_item calls.
    # Any float-valued field added later must get this treatment.
    def to_decimal(value) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(round(float(value), 3)))

    def convert_numerics(obj):
        """Recursively convert floats to Decimal for DynamoDB."""
        if isinstance(obj, dict):
            return {k: convert_numerics(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_numerics(item) for item in obj]
        if isinstance(obj, float):
            return to_decimal(obj)
        return obj

    record_for_db = convert_numerics(record)

    # Conditional write: only write if this document_key doesn't already exist.
    # This prevents duplicate records from at-least-once delivery.
    try:
        pa_table.put_item(
            Item=record_for_db,
            ConditionExpression="attribute_not_exists(document_key)",
        )
        print(f"  Stored record for {record['document_key']}")
    except pa_table.meta.client.exceptions.ConditionalCheckFailedException:
        print(f"  Record for {record['document_key']} already exists. Skipping.")

    # If no human review needed, this is where you'd publish to the event bus
    # to trigger downstream clinical criteria matching (Recipe 2.4).
    # In production:
    #   if not record["needs_review"]:
    #       events_client.put_events(Entries=[{
    #           "Source":       "pa-pipeline",
    #           "DetailType":   "prior_auth_extracted",
    #           "Detail":       json.dumps({"document_key": record["document_key"]}),
    #           "EventBusName": os.environ["EVENT_BUS_NAME"],
    #       }])

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is the sequential, polling-based version for development scripts and learning. In production, Steps 1-2 live in `pa-start` and `pa-retrieve` Lambdas, and Step 5's fan-out runs as parallel branches inside an AWS Step Functions Express Workflow.

```python
def process_prior_auth_submission(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> dict:
    """
    Run the full prior auth extraction pipeline for one faxed multi-page PDF.

    Covers all six steps from the Recipe 1.4 pseudocode:
      1+2. Submit async Textract job (FORMS + TABLES + LAYOUT) and retrieve blocks
      3.   Group blocks by page
      4.   Classify each page using keyword heuristics and structural signals
      5.   Fan out to specialized extractors per page type (sequential here;
           parallel branches in the Step Functions version)
      6.   Assemble deduplicated prior auth record and store to DynamoDB

    Args:
        bucket:             S3 bucket containing the prior auth PDF
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      SNS topic ARN for Textract completion notifications
        textract_role_arn:  IAM role ARN Textract can assume to publish to SNS

    Returns:
        The assembled prior auth record.
    """

    # Steps 1 and 2: Submit the Textract job and retrieve all blocks.
    # LAYOUT is included in FeatureTypes alongside FORMS and TABLES.
    print(f"Steps 1-2: Submitting Textract job for s3://{bucket}/{key}")
    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"  Job ID: {job_id}")

    print("  Waiting for job completion and retrieving all blocks...")
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Step 3: Group blocks by page. Pre-compute structural features.
    print("Step 3: Grouping blocks by page...")
    pages = group_blocks_by_page(all_blocks)
    page_count = len(pages)
    print(f"  {page_count} pages in submission")

    # Step 4: Classify each page using keyword heuristics.
    print("Step 4: Classifying pages...")
    classifications = classify_all_pages(pages)

    # Summarize the classification distribution for tracing.
    from collections import Counter
    type_counts = Counter(classifications.values())
    print(f"  Classification summary: {dict(type_counts)}")

    # Step 5: Fan out to specialized extractors per page type.
    # In production, Step Functions runs these in parallel branches.
    # Here, we run them sequentially and collect results in a dict.
    print("Step 5: Extracting data from each page...")
    page_extractions = {}

    for page_num in sorted(pages.keys()):
        page_type = classifications[page_num]
        page_data = pages[page_num]

        print(f"  Page {page_num} ({page_type})...")
        extraction = route_and_extract(page_num, page_type, page_data, block_map)
        page_extractions[page_num] = extraction

    # Step 6: Assemble the structured record from all page extractions.
    print("Step 6: Assembling prior auth record...")
    record = assemble_prior_auth_record(
        document_key=key,
        page_count=page_count,
        page_extractions=page_extractions,
    )

    # Store to DynamoDB.
    stored_record = store_prior_auth_record(record)

    # Summary output.
    icd10_count   = len(record["clinical_evidence"]["icd10_codes"])
    flagged_pages = record["flagged_pages"]
    print(
        f"\nDone. pages={page_count}, ICD-10 codes={icd10_count}, "
        f"needs_review={record['needs_review']}, "
        f"flagged_pages={flagged_pages}"
    )

    return stored_record


# Example: run the pipeline directly against a test prior auth PDF.
if __name__ == "__main__":
    import json

    result = process_prior_auth_submission(
        bucket="my-prior-auth-inbox",
        key="prior-auth-inbox/2026/03/01/fax-00847.pdf",
        sns_topic_arn="arn:aws:sns:us-east-1:123456789012:textract-jobs",
        textract_role_arn="arn:aws:iam::123456789012:role/TextractServiceRole",
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

## Lambda Handler Versions

In a production deployment, the pipeline splits across multiple Lambda functions. The pa-start Lambda fires on the S3 upload event. The pa-retrieve Lambda fires on the SNS notification from Textract, then hands off to Step Functions for the classify-extract-assemble stages. The extraction functions themselves run as separate Lambdas inside a Step Functions Express Workflow.

For brevity, the handlers below show the entry point logic. The extraction functions are unchanged from above.

```python
import json
import os


def lambda_handler_pa_start(event: dict, context) -> None:
    """
    pa-start Lambda: triggered by S3 upload events.

    One job: submit the Textract analysis job and record the context.
    Everything downstream waits for the SNS completion notification.
    """
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    sns_topic_arn     = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
    textract_role_arn = os.environ["TEXTRACT_ROLE_ARN"]

    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"Submitted job {job_id} for s3://{bucket}/{key}")


def lambda_handler_pa_retrieve(event: dict, context) -> None:
    """
    pa-retrieve Lambda: triggered by SNS notifications from Textract.

    Retrieves all blocks, writes them to S3 (to stay under Step Functions'
    256 KB payload limit), then starts the Step Functions state machine with
    the S3 location of the blocks rather than the blocks themselves.
    """
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id      = sns_message["JobId"]
    job_status  = sns_message["Status"]

    if job_status != "SUCCEEDED":
        print(f"Job {job_id} finished with status {job_status}. Skipping.")
        # Production: move the source PDF to failed-documents/, fire a CloudWatch alarm.
        return

    # Look up the original S3 path from the jobs tracking table.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    response   = jobs_table.get_item(Key={"job_id": job_id})
    job_item   = response.get("Item", {})
    bucket     = job_item.get("bucket")
    key        = job_item.get("key")

    if not bucket or not key:
        print(f"No job context for job_id={job_id}. Cannot process.")
        return

    # Retrieve all Textract blocks.
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Write blocks to S3 rather than passing them through Step Functions.
    # A 15-page submission can produce thousands of blocks, easily exceeding
    # Step Functions' 256 KB input/output size limit.
    textract_output_key = f"textract-outputs/{job_id}/blocks.json"
    s3_client.put_object(
        Bucket=bucket,
        Key=textract_output_key,
        Body=json.dumps(all_blocks),
        ContentType="application/json",
    )

    # Start the Step Functions state machine.
    # The state machine reads from S3 rather than receiving raw blocks.
    state_machine_arn = os.environ["STATE_MACHINE_ARN"]
    sfn_client        = boto3.client("stepfunctions")

    sfn_client.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps({
            "document_key":        key,
            "bucket":              bucket,
            "textract_output_key": textract_output_key,
            "textract_job_id":     job_id,
        }),
    )
    print(f"Started Step Functions execution for {key}")


def lambda_handler_pa_assembler(event: dict, context) -> dict:
    """
    pa-assembler Lambda: the final stage inside the Step Functions workflow.

    Receives the map of per-page extraction results from the parallel fan-out
    branches, assembles the prior auth record, and stores it.

    In Step Functions, this Lambda receives the combined output of the parallel
    extraction branches as its input.
    """
    document_key     = event["document_key"]
    page_count       = event["page_count"]
    # In the Step Functions version, page_extractions is assembled from the
    # parallel branch outputs before this Lambda is invoked.
    page_extractions = event["page_extractions"]

    record = assemble_prior_auth_record(document_key, page_count, page_extractions)
    stored = store_prior_auth_record(record)

    print(f"Assembled and stored record for {document_key}. needs_review={record['needs_review']}")

    # If the record needs human review, the Step Functions workflow would route
    # to an SNS publish or SQS send to enqueue it for Recipe 1.6.
    return {
        "document_key": document_key,
        "needs_review": record["needs_review"],
    }
```

---

## The Gap Between This and Production

This example demonstrates the full classify-fan-out-assemble pipeline. Run it against a real prior auth PDF and it will produce a structured record with classified pages, extracted administrative fields, deduplicated ICD-10 codes, clinical entities, lab values, and imaging sections. The distance from that to something you'd deploy in a payer UM environment is significant. Here's where it lives.

**Step Functions payload size limits.** Step Functions caps state input and output at 256 KB. A 20-page document's Textract blocks can easily exceed that. The production pattern is to write blocks to S3 from `pa-retrieve` and pass the S3 key rather than the raw block list through the state machine. Every downstream Lambda reads from S3. This adds an S3 read to each extraction step and requires cleanup of intermediate objects after the pipeline completes. The `lambda_handler_pa_retrieve` example above already implements this pattern.

**Concurrent Textract job limits.** Textract async jobs run against account-level concurrency limits (default: 2 concurrent jobs per account in most regions, adjustable via service quota increase). A burst of incoming faxes will queue behind each other once that limit is reached. The `pa-start` Lambda should check a DynamoDB counter for in-flight job count before submitting a new Textract job, implementing backpressure rather than letting submissions queue silently.

**Page classification is a heuristic, not a guarantee.** This classifier misclassifies 8 to 15% of pages in practice. Most failures are safe: a clinical note routed to the lab results extractor finds no tables and returns an empty result. But some produce confident-looking bad output. Build a mechanism to record classifications alongside extraction results, and use human reviewer corrections to track accuracy over time. When a reviewer corrects a misclassified page, that correction adds a labeled example to your training dataset. The path to a trained classifier (which pushes accuracy to 93-97%) runs through exactly this feedback loop.

**Cover sheets that span two pages.** Many payer cover sheet templates are two pages long. The assembler's "first cover sheet wins" logic leaves the second page on the floor if the first page already populated those fields. A production implementation checks whether a second cover_sheet page contains fields that were null after the first and merges the non-null values.

**ICD-10 codes written as codes, not as text.** `InferICD10CM` expects natural language input: "severe osteoarthritis, right knee" not "M17.11." When a clinical note has "Dx: M17.11" written directly, the inference step returns nothing useful. A production implementation detects ICD-10 code format via regex (one letter + 2 digits + optional decimal + 2-4 alphanumeric characters), extracts those directly, and skips the NLP inference for those entries.

**ICD-10 code specificity.** `InferICD10CM` tends toward the least-specific valid code: E11.9 rather than E11.65, even when the clinical text supports the more specific form. Some payer medical policies require the specific code to support coverage. A production system captures the full ranked candidate list (not just `concepts[0]`), compares specificity against payer policy requirements, and routes low-specificity results to coder review when the downstream policy demands it.

**Dead Letter Queues on all Lambda functions.** Every Lambda in this pipeline receives asynchronous invocations. Configure an SQS DLQ on each, with CloudWatch alarms on queue depth. A prior auth submission that disappears into a failed Lambda invocation is a patient care delay waiting to happen. The Step Functions workflow catches state-level errors, but the DLQ catches Lambda invocation failures before the state machine ever sees the result.

**Step Functions per-state error handling.** Express Workflows catch failures at the state machine level by default. Configure per-state error handling so that a failure in the lab results extractor doesn't abort the clinical note extractor. The assembler should handle partial extraction results: a submission where lab extraction failed still produces a useful record with the lab section empty and needs_review set.

**Idempotency on the assembler.** S3 event notifications and SNS from Textract are both at-least-once. The `pa-retrieve` Lambda can be invoked twice for the same submission. The conditional DynamoDB write in `store_prior_auth_record` prevents duplicate records on the primary key, but the Step Functions execution itself may also be started twice. Use an idempotency token derived from the document key when calling `start_execution` to prevent duplicate workflow runs.

**Negation and family history traits in clinical entities.** `detect_clinical_entities` captures semantic traits like NEGATION and PERTAINS_TO_FAMILY on each entity. This example stores them in the record but doesn't use them to filter ICD-10 inferences. In production, if `InferICD10CM` returns a condition that `detect_entities_v2` flagged with NEGATION (the text said "denies chest pain"), that's a signal to route the ICD-10 code to coder review rather than accepting it automatically. Wiring those two steps together requires cross-referencing entities by text span, which is non-trivial but catches a meaningful class of coding errors.

**DynamoDB Decimal requirement.** Every numeric value in the record uses `Decimal` wrapping. The `convert_numerics` function in `store_prior_auth_record` handles this recursively. Any new numeric field you add must go through the same treatment. A raw Python float in a `put_item` call raises `TypeError` at runtime with a less-than-helpful error message.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling prior auth submissions runs inside a VPC with private subnets and VPC endpoints for S3, Textract, DynamoDB, SNS, Comprehend Medical, Step Functions, KMS, and CloudWatch Logs. Prior auth submissions contain dense PHI: diagnoses, treatment history, procedure requests, member demographics. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest. Step Functions execution history encrypted with SSE. All API calls over TLS.

**Testing.** There are no tests here. A production pipeline has unit tests for each extractor with mocked Textract and Comprehend Medical responses, integration tests against real API calls with synthetic submissions, and a fixture library covering the cover sheet templates you actually receive. CMS publishes the CMS-1500 form and sample ICD-10-CM data. Build test fixtures from those. Never use real patient submissions in any non-production environment.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.4: Prior Authorization Document Processing](chapter01.04-prior-auth-document-processing) for the full architectural walkthrough, pseudocode, performance benchmarks, and the honest take on where this gets hard in practice.*
