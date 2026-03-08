# Recipe 1.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.2. It is meant to show one way you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a clinic on Monday morning. Consider it a starting point, not a destination.
>
> One important note on the async flow: Recipe 1.2 describes a two-Lambda architecture connected by SNS. This example implements the same logic as a polling loop so you can run it as a single script during development without provisioning SNS topics and Lambda triggers. The polling approach works fine for experimentation. For production, replace the polling loop with the SNS-triggered Lambda pair described in the main recipe. The parsing and storage logic is identical either way.

---

## Setup

You'll need the AWS SDK for Python installed:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `textract:StartDocumentAnalysis`
- `textract:GetDocumentAnalysis`
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `iam:PassRole` (so Lambda can pass the Textract service role to the `StartDocumentAnalysis` call)

You also need a Textract service role: a dedicated IAM role that Textract can assume to publish job completion notifications to your SNS topic. This is separate from your Lambda execution role. See the Prerequisites section in the main recipe for details.

---

## Configuration and Constants

The field map and thresholds live here, at the top of the module. These are configuration, not logic. They're what you'll edit as you encounter new form layouts.

```python
# FIELD_MAP: maps canonical (standard) field names to the label variants
# that different intake form designs use for the same field.
#
# Intake forms are not standardized across EHR vendors or specialty practices.
# A cardiology practice's intake form looks different from a pediatrics intake.
# Both will have a "date of birth" field, but one might label it "DOB" and
# the other "Birthdate". This map is what makes the output consistent.
#
# Treat this as a living document. Every time you encounter an unrecognized
# key in your logs, add it here.

FIELD_MAP = {
    "first_name": [
        "first name", "patient first name", "fname", "given name",
        "first", "patient first", "forename"
    ],
    "last_name": [
        "last name", "patient last name", "lname", "family name",
        "surname", "last", "patient last"
    ],
    "date_of_birth": [
        "date of birth", "dob", "birth date", "birthdate",
        "date of birth (mm/dd/yyyy)", "patient dob", "born"
    ],
    "ssn": [
        "social security number", "ssn", "social security #",
        "social security no", "ss#", "soc sec #"
    ],
    "phone": [
        "phone", "phone number", "home phone", "cell phone",
        "telephone", "mobile", "contact number", "primary phone"
    ],
    "address": [
        "address", "home address", "street address", "mailing address",
        "patient address", "residential address"
    ],
    "member_id": [
        "member id", "mem id", "member #", "subscriber id",
        "id number", "member number", "mbr id", "mbi",
        "insurance id", "policy number"
    ],
    "group_number": [
        "group #", "group number", "group", "grp #",
        "grp", "group no", "group id"
    ],
    "payer_name": [
        "insurance company", "plan name", "payer", "carrier",
        "insurance", "insurer", "health plan", "insurance carrier"
    ],
}

# How confident does Textract need to be before we write a field directly
# to the database? Fields below this threshold are held for human review.
# 90% is a reasonable starting point for printed text on intake forms.
# Handwritten fields will frequently fall below this. That is expected behavior,
# not a bug. The confidence gate is doing its job.
CONFIDENCE_THRESHOLD = 90.0

# How long to wait between polling calls to GetDocumentAnalysis.
# Textract jobs for a 3-page form typically complete in 8-15 seconds.
# Polling every 3 seconds gives a good balance of responsiveness vs. API calls.
# In production, replace this polling loop with SNS-triggered Lambda invocations.
POLL_INTERVAL_SECONDS = 3

# Maximum number of polling attempts before giving up.
# 20 attempts * 3 seconds = 60 seconds maximum wait.
MAX_POLL_ATTEMPTS = 20

# DynamoDB table names.
# Replace these with your actual table names from your infrastructure setup.
JOBS_TABLE_NAME = "textract-jobs"         # tracks in-flight async jobs
RESULTS_TABLE_NAME = "intake-extractions"  # stores completed extraction records
```

---

## Step 1: Submit the Async Textract Job

*The pseudocode calls this `submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)`. This is the entry point for the first Lambda: an intake form PDF lands in S3, and we submit it to Textract for multi-page analysis. The call returns immediately with a job ID. The actual extraction work happens in the background.*

```python
import logging
import boto3
import datetime
from datetime import timezone
from botocore.config import Config

# Configure structured logging for Lambda. In production, use JSON-formatted
# log output for CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# PHI Safety: Never log extracted field values, diagnosis text, or patient identifiers.

# Textract and other AWS services throttle under sustained load. Adaptive retry mode
# uses exponential backoff with jitter, which handles burst throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# boto3 clients. These are module-level so they're reused across invocations
# inside a warm Lambda container rather than re-created on every call.
textract_client = boto3.client("textract", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")


def submit_extraction_job(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> str:
    """
    Submit a multi-page intake form PDF (or TIFF) to Textract for async analysis.

    This is the function your first Lambda calls when an S3 upload event fires.
    It starts the Textract job and saves the job context to DynamoDB, then exits.
    The second Lambda picks up when Textract signals completion via SNS.

    Args:
        bucket:             S3 bucket name where the intake form lives
        key:                S3 object key (path to the PDF inside the bucket)
        sns_topic_arn:      ARN of the SNS topic for job completion notifications
        textract_role_arn:  ARN of the IAM role Textract uses to publish to SNS
                            (this must be a role Textract can assume, separate from
                            the Lambda execution role; see Prerequisites in the recipe)

    Returns:
        The Textract job ID. Save this: it's how you retrieve results later.
    """

    # Call StartDocumentAnalysis.
    #
    # This is the key difference from Recipe 1.1's AnalyzeDocument call.
    # StartDocumentAnalysis accepts multi-page PDF and TIFF files stored in S3.
    # It does NOT return results immediately. It starts a background job and
    # gives you back a job ID to check later.
    #
    # We request both FORMS and TABLES in a single job:
    #   FORMS:  extracts labeled key-value pairs AND checkbox selection elements
    #   TABLES: extracts row-and-column structure from grids and tables
    #
    # You can't add feature types after the job starts, so request everything
    # you need upfront.
    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": bucket,   # the S3 bucket
                "Name": key,        # the PDF or TIFF file path
            }
        },
        FeatureTypes=["FORMS", "TABLES"],   # extract both key-value pairs AND table structure
        NotificationChannel={
            # When the job finishes, Textract publishes a message to this SNS topic.
            # The message contains the job ID and final status (SUCCEEDED or FAILED).
            "SNSTopicArn": sns_topic_arn,
            # Textract needs an IAM role it can assume to publish to your SNS topic.
            # It cannot use the Lambda's execution role. You must create a separate
            # "Textract service role" with sns:Publish on your topic, and pass it here.
            # Forgetting this is the single most common reason jobs complete silently
            # without triggering your second Lambda.
            "RoleArn": textract_role_arn,
        },
    )

    job_id = response["JobId"]

    # Save job context to the tracking table.
    # When the SNS notification fires and wakes up the second Lambda, it will
    # receive the job ID but not the original document path. We save that
    # mapping here so the second Lambda can look up the source document.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    jobs_table.put_item(
        Item={
            "job_id": job_id,
            "bucket": bucket,
            "key": key,                                                      # path to the original PDF
            "submitted_at": datetime.datetime.now(timezone.utc).isoformat(),   # audit timestamp
            "status": "PENDING",
        }
    )

    logger.info("Submitted Textract job %s for s3://%s/%s", job_id, bucket, key)
    return job_id
```

---

## Step 2: Retrieve All Result Pages

*The pseudocode calls this `retrieve_all_blocks(job_id)`. Textract paginates the extraction results for multi-page documents. A five-page intake form can produce hundreds of blocks across multiple response pages. This step loops through all pages and builds a complete block index before any parsing begins.*

```python
def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Retrieve all extracted blocks from a completed Textract async job.

    Textract returns results in pages of up to 1,000 blocks each. If the document
    has many pages or many detected elements, there will be multiple result pages.
    We must collect every block before we start parsing. Stopping at the first
    page gives you a partial document, and you won't know it.

    This function also handles the polling loop for development use. In production,
    replace the poll loop by calling this function only after receiving the SNS
    completion notification (which gives you the job ID directly).

    Args:
        job_id: The Textract job ID returned by submit_extraction_job.

    Returns:
        A tuple of (all_blocks, block_map):
        - all_blocks: flat list of every block Textract extracted
        - block_map:  dict of block ID -> block, for O(1) lookups by ID
    """
    import time

    # Polling loop: check job status until it completes or we give up.
    # In production with SNS, you skip this loop entirely: you only call
    # GetDocumentAnalysis after SNS tells you the job is SUCCEEDED.
    job_status = "IN_PROGRESS"
    attempts = 0

    while job_status == "IN_PROGRESS" and attempts < MAX_POLL_ATTEMPTS:
        attempts += 1
        # Fetch the first page of results. This also gives us the current job status.
        status_response = textract_client.get_document_analysis(JobId=job_id)
        job_status = status_response["JobStatus"]

        if job_status == "IN_PROGRESS":
            logger.info("  Job %s still running (attempt %d/%d)...", job_id, attempts, MAX_POLL_ATTEMPTS)
            time.sleep(POLL_INTERVAL_SECONDS)
        elif job_status == "FAILED":
            # Textract couldn't process the document. Common causes: corrupted PDF,
            # unsupported file format, permissions issue reading from S3.
            raise RuntimeError(
                f"Textract job {job_id} failed. "
                f"StatusMessage: {status_response.get('StatusMessage', 'no message')}"
            )

    if job_status != "SUCCEEDED":
        raise TimeoutError(f"Textract job {job_id} did not complete in time. Last status: {job_status}")

    # Job succeeded. Now collect ALL result pages.
    # The polling loop above only checked status; it did not save blocks.
    # We fetch all results fresh here using the pagination cursor.
    all_blocks = []
    next_token = None   # None means "start from the beginning"

    while True:
        # Build the API call. Include NextToken only when we have one.
        params = {"JobId": job_id}
        if next_token is not None:
            params["NextToken"] = next_token

        response = textract_client.get_document_analysis(**params)

        # Add this response page's blocks to our running collection.
        page_blocks = response.get("Blocks", [])
        all_blocks.extend(page_blocks)

        # Check whether there are more pages of results.
        next_token = response.get("NextToken")   # None if this was the last page
        if next_token is None:
            break    # we have everything; exit the loop

    logger.info("  Retrieved %d total blocks across all result pages", len(all_blocks))

    # Build a lookup index: block ID -> block data.
    # Nearly every operation in the parsing steps below needs to follow
    # cross-references between blocks by ID. An O(1) dict lookup is
    # much faster than scanning the flat list each time.
    block_map = {block["Id"]: block for block in all_blocks}

    return all_blocks, block_map
```

---

## Step 3: Parse Key-Value Pairs and Checkboxes

*The pseudocode calls this `parse_forms(all_blocks, block_map)`. This step handles both text fields and checkboxes. Textract uses the same KEY_VALUE_SET block structure for both: the difference is that a checkbox value block contains a SELECTION_ELEMENT child instead of WORD children. We detect that distinction here and route each field into the right output structure.*

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: assemble the full text of a block from its CHILD WORD blocks.

    Textract stores actual text in a hierarchy: the KEY or VALUE block has
    CHILD relationships pointing to individual WORD blocks. We follow those
    links and concatenate the words to reconstruct the full text string.

    This is the same helper from Recipe 1.1. It works identically here
    because the KEY_VALUE_SET block structure is the same for multi-page docs.
    """
    text = ""

    if "Relationships" not in block:
        return text

    for relationship in block["Relationships"]:
        # CHILD relationships link to the word blocks that make up this block's text.
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child_block = block_map.get(child_id, {})
                # Only grab WORD blocks here. SELECTION_ELEMENT blocks (checkboxes)
                # are handled separately in parse_forms below.
                if child_block.get("BlockType") == "WORD":
                    text += child_block.get("Text", "") + " "

    return text.strip()


def parse_forms(all_blocks: list, block_map: dict) -> tuple[dict, dict]:
    """
    Walk the block list and extract key-value pairs and checkbox states.

    Text fields and checkboxes both come through as KEY_VALUE_SET blocks.
    The difference is in the value side:
    - Text fields: the VALUE block has WORD children we concatenate into a string.
    - Checkboxes:  the VALUE block has a SELECTION_ELEMENT child with SelectionStatus.

    We separate these into two output maps so downstream code can handle each type
    appropriately without needing to know which came from which block type.

    Args:
        all_blocks: all extracted blocks from retrieve_all_blocks
        block_map:  block ID -> block dict, from retrieve_all_blocks

    Returns:
        A tuple of (text_key_values, checkbox_fields):
        - text_key_values: label -> {"value": str, "confidence": float}
        - checkbox_fields: label -> {"selected": bool, "confidence": float}
    """
    text_key_values = {}   # text fields: label -> {value text, confidence}
    checkbox_fields = {}   # checkbox fields: label -> {selected bool, confidence}

    for block in all_blocks:

        # We only want KEY_VALUE_SET blocks, and only the KEY (label) side.
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue

        entity_types = block.get("EntityTypes", [])
        if "KEY" not in entity_types:
            continue   # this is a VALUE block; we'll reach it via its KEY

        # Assemble the label text from this KEY block's WORD children.
        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue   # empty label; nothing to work with

        # Follow the VALUE relationship on this KEY block to find its paired VALUE block.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                value_id = relationship["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue   # KEY with no VALUE; skip (can happen for blank fields)

        # Determine whether this is a checkbox or a text field by looking at
        # the VALUE block's children. A checkbox value has a SELECTION_ELEMENT child.
        # A text value has WORD children.
        selection_child = None
        for relationship in value_block.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                for child_id in relationship["Ids"]:
                    child_block = block_map.get(child_id, {})
                    if child_block.get("BlockType") == "SELECTION_ELEMENT":
                        selection_child = child_block
                        break
            if selection_child:
                break

        if selection_child is not None:
            # This is a checkbox field.
            # SelectionStatus is either "SELECTED" (checked) or "NOT_SELECTED" (unchecked).
            is_selected = selection_child.get("SelectionStatus") == "SELECTED"
            # Use the SELECTION_ELEMENT's confidence score for gating.
            confidence = selection_child.get("Confidence", 0.0)
            checkbox_fields[key_text] = {
                "selected": is_selected,
                "confidence": confidence,
            }

        else:
            # This is a regular text field.
            value_text = get_text_from_block(value_block, block_map)
            # Use the lower of the two confidence scores (key vs value).
            # If Textract was uncertain about either side, we want to know.
            key_confidence = block.get("Confidence", 0.0)
            value_confidence = value_block.get("Confidence", 0.0)
            confidence = min(key_confidence, value_confidence)

            text_key_values[key_text] = {
                "value": value_text,
                "confidence": confidence,
            }

    return text_key_values, checkbox_fields
```

---

## Step 4: Parse Tables

*The pseudocode calls this `parse_tables(all_blocks, block_map)`. This step has no equivalent in Recipe 1.1. Tables require a completely different parsing approach because the structure is two-dimensional: each cell belongs to a specific row and column. Textract represents tables as a hierarchy of TABLE, CELL, and WORD blocks. We reassemble that hierarchy into a list of lists.*

```python
def parse_tables(all_blocks: list, block_map: dict) -> list[list[list[str]]]:
    """
    Extract all tables from the document and return them as row-by-column grids.

    A medication table in the Textract response looks like this in block form:
      TABLE block
        CELL block (row=1, col=1): "Medication"
        CELL block (row=1, col=2): "Dosage"
        CELL block (row=2, col=1): "Metformin"
        CELL block (row=2, col=2): "500mg"
        ...

    We rebuild that into a Python list of lists:
      [
        ["Medication", "Dosage", "Frequency", "Prescribing Physician"],
        ["Metformin",  "500mg",  "Twice daily", "Dr. Chen"],
        ["Lisinopril", "10mg",   "Once daily",  "Dr. Chen"],
      ]

    The first row is typically the column headers. The caller can use
    tables[0][0] to get the header row, tables[0][1:] for the data rows.

    Args:
        all_blocks: all extracted blocks from retrieve_all_blocks
        block_map:  block ID -> block dict, from retrieve_all_blocks

    Returns:
        A list of tables. Each table is a list of rows. Each row is a list of
        cell text strings. Tables are returned in document order.
    """
    tables = []   # final output: list of (list of rows)

    for block in all_blocks:

        # Find TABLE-type blocks. Each one is the root of one extracted table.
        if block.get("BlockType") != "TABLE":
            continue

        # Build a nested dict: row_index -> column_index -> cell text.
        # We use a dict (not a list) because row/column indices are 1-based
        # and we don't know the table dimensions until we've visited all cells.
        grid = {}   # { row_int: { col_int: str } }

        # Walk the TABLE block's CHILD relationships to find all its CELL blocks.
        for relationship in block.get("Relationships", []):
            if relationship["Type"] != "CHILD":
                continue
            for cell_id in relationship["Ids"]:
                cell_block = block_map.get(cell_id, {})

                if cell_block.get("BlockType") != "CELL":
                    continue

                # RowIndex and ColumnIndex are 1-based integers.
                row = cell_block.get("RowIndex", 0)
                col = cell_block.get("ColumnIndex", 0)

                # Assemble cell text from the CELL block's WORD children.
                # Cells with no WORD children (blank cells) will return "".
                cell_text = ""
                for cell_rel in cell_block.get("Relationships", []):
                    if cell_rel["Type"] == "CHILD":
                        for word_id in cell_rel["Ids"]:
                            word_block = block_map.get(word_id, {})
                            if word_block.get("BlockType") == "WORD":
                                cell_text += word_block.get("Text", "") + " "
                cell_text = cell_text.strip()

                # Store into the grid. Initialize the row dict if needed.
                if row not in grid:
                    grid[row] = {}
                grid[row][col] = cell_text

        # Skip empty tables (can happen if Textract detected a table-like border
        # but found no content inside it).
        if not grid:
            continue

        # Convert the nested dict to a list of lists.
        # Determine the actual dimensions of the table first.
        max_row = max(grid.keys())
        max_col = max(
            col
            for row_data in grid.values()
            for col in row_data.keys()
        )

        table_rows = []
        for r in range(1, max_row + 1):
            row_data = []
            for c in range(1, max_col + 1):
                # Use empty string for cells the patient left blank.
                row_data.append(grid.get(r, {}).get(c, ""))
            table_rows.append(row_data)

        tables.append(table_rows)

    logger.info("  Extracted %d table(s)", len(tables))
    return tables
```

---

## Step 5: Normalize Fields and Apply Confidence Gating

*The pseudocode calls this `normalize_and_gate(raw_kv, checkbox_fields, tables)`. The same normalization logic from Recipe 1.1 applies here: map raw Textract labels to canonical field names. The confidence gating is also the same, but applied separately to text fields and checkbox fields. Tables pass through as-is: their structure is already well-defined.*

```python
from decimal import Decimal  # DynamoDB requires Decimal, not float


def normalize_fields(raw_kv: dict) -> dict:
    """
    Map raw Textract label text to canonical field names.

    Reused from Recipe 1.1, extended here with the intake-form field map.
    See FIELD_MAP at the top of this file for the full list of variants.

    Args:
        raw_kv: text_key_values output from parse_forms: label -> {value, confidence}

    Returns:
        Dict with canonical field names as keys, same value/confidence structure.
        Labels that don't match any known variant are silently dropped.
        Log unmatched keys in production so you can add them to FIELD_MAP later.
    """
    normalized = {}

    for canonical_name, variants in FIELD_MAP.items():
        for raw_key, raw_val in raw_kv.items():
            if raw_key.lower().strip() in variants:
                normalized[canonical_name] = {
                    "value": raw_val["value"].strip(),
                    "confidence": raw_val["confidence"],
                }
                break   # found the right canonical field; stop checking variants

    return normalized


def normalize_and_gate(
    raw_kv: dict,
    checkbox_fields: dict,
    tables: list,
) -> tuple[dict, dict, list, list]:
    """
    Normalize field names and split both text fields and checkboxes by confidence.

    Fields above CONFIDENCE_THRESHOLD go into the clean output.
    Fields below it go into the flagged list for human review.
    Tables pass through unchanged: their row-and-column structure is the
    normalized form already.

    Args:
        raw_kv:         text_key_values from parse_forms
        checkbox_fields: checkbox field data from parse_forms
        tables:          table grids from parse_tables

    Returns:
        A tuple of (clean_fields, clean_checkboxes, tables, flagged):
        - clean_fields:     canonical_name -> value string (high-confidence only)
        - clean_checkboxes: label -> bool (high-confidence only)
        - tables:           list of table grids, passed through unchanged
        - flagged:          list of dicts describing each field held for review
    """
    # Normalize text field names to canonical labels.
    normalized = normalize_fields(raw_kv)

    clean_fields = {}
    flagged = []

    # Gate text fields by confidence.
    for canonical_name, data in normalized.items():
        if data["confidence"] >= CONFIDENCE_THRESHOLD:
            clean_fields[canonical_name] = data["value"]
        else:
            flagged.append({
                "field": canonical_name,
                "extracted_value": data["value"],
                # DynamoDB requires Decimal, not float.
                # str() first avoids floating-point artifacts in the Decimal conversion.
                "confidence": Decimal(str(round(data["confidence"], 2))),
            })

    # Gate checkboxes by confidence.
    # Checkbox detection is generally more reliable than text for printed forms
    # (97-99% accuracy), but borderline cases still exist. We gate them the
    # same way as text fields to be consistent.
    clean_checkboxes = {}
    for label, data in checkbox_fields.items():
        if data["confidence"] >= CONFIDENCE_THRESHOLD:
            clean_checkboxes[label] = data["selected"]
        else:
            flagged.append({
                "field": label,
                # Store the boolean state as a string for readability in the review UI.
                "extracted_value": "SELECTED" if data["selected"] else "NOT_SELECTED",
                "confidence": Decimal(str(round(data["confidence"], 2))),
            })

    return clean_fields, clean_checkboxes, tables, flagged
```

---

## Step 6: Assemble the Record and Store It

*The pseudocode calls this `assemble_and_store(document_key, page_count, clean_fields, clean_checkboxes, tables, flagged)`. The final step: combine everything into the unified intake record and write it to DynamoDB. Note the SSN handling: we store last-four only, even if the form captured the full number.*

```python
def assemble_and_store(
    document_key: str,
    page_count: int,
    clean_fields: dict,
    clean_checkboxes: dict,
    tables: list,
    flagged: list,
) -> dict:
    """
    Assemble the structured intake record and write it to DynamoDB.

    The record is organized into logical sections: demographics, insurance,
    medical history (checkboxes), and structured tables (medications, allergies).
    Fields that didn't make the confidence threshold are in flagged_fields.

    The needs_review flag is set whenever any field was flagged. Downstream
    systems check this flag first before deciding what to do with the record.
    Flagged records should route to a human review queue (see Recipe 1.6).

    Args:
        document_key:    S3 object key of the source PDF (for audit linkage)
        page_count:      Number of pages Textract processed
        clean_fields:    High-confidence text fields from normalize_and_gate
        clean_checkboxes: High-confidence checkbox fields from normalize_and_gate
        tables:          Table grids from parse_tables
        flagged:         Low-confidence fields held for human review

    Returns:
        The full record that was written to DynamoDB.
    """
    results_table = dynamodb.Table(RESULTS_TABLE_NAME)

    # SSN handling: store last four digits only.
    # Even if the form captured the full SSN, storing it in an operational
    # database when last-four suffices for patient matching is an unnecessary
    # liability. Truncate here, before the record is written anywhere.
    raw_ssn = clean_fields.get("ssn", "")
    ssn_last4 = raw_ssn[-4:] if len(raw_ssn) >= 4 else ""

    # Assemble the record.
    # Sections mirror the logical structure of the intake form:
    # demographics first, then insurance, then medical history.
    record = {
        # Primary key and audit fields.
        "document_key": document_key,                                   # links back to S3 source
        "extracted_at": datetime.datetime.now(timezone.utc).isoformat(),  # audit timestamp
        "page_count": page_count,                                       # pages Textract saw

        # needs_review is the single most important flag for downstream routing.
        # Any record with flagged fields gets routed to human review.
        "needs_review": len(flagged) > 0,

        # Demographics section.
        "demographics": {
            "first_name":    clean_fields.get("first_name"),
            "last_name":     clean_fields.get("last_name"),
            "date_of_birth": clean_fields.get("date_of_birth"),
            "ssn_last4":     ssn_last4,    # last 4 only; never store full SSN here
            "address":       clean_fields.get("address"),
            "phone":         clean_fields.get("phone"),
        },

        # Insurance section.
        "insurance": {
            "member_id":    clean_fields.get("member_id"),
            "group_number": clean_fields.get("group_number"),
            "payer_name":   clean_fields.get("payer_name"),
        },

        # Medical history: checkboxes become booleans.
        # {"Diabetes": True, "Hypertension": True, "Heart Disease": False, ...}
        "medical_history": {
            "conditions": clean_checkboxes,
        },

        # Tables, in the order Textract found them in the document.
        # The first table is usually the medication list.
        # The second is usually the allergy list.
        # The exact order depends on form layout; don't hardcode this for production.
        "medications": tables[0] if len(tables) >= 1 else [],
        "allergies":   tables[1] if len(tables) >= 2 else [],

        # Low-confidence fields: held for human review.
        # These are NOT in the sections above. They are deliberately withheld
        # until a human confirms or corrects them.
        "flagged_fields": flagged,
    }

    # Write to DynamoDB.
    # put_item creates or replaces the item at the document_key partition key.
    # If the same form is re-processed (e.g., after a quality rescan), this
    # will overwrite the previous record. Add a ConditionExpression if you
    # need to protect existing records.
    results_table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is the polling-based version suitable for scripts and development. The Lambda handler versions are shown below.

```python
def process_intake_form(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> dict:
    """
    Run the full intake form extraction pipeline for one multi-page document.

    This function implements the complete flow from Step 1 through Step 6,
    using a polling loop to wait for Textract completion. In a production
    two-Lambda deployment, Steps 1 and 2-6 live in separate functions
    triggered by S3 events and SNS notifications respectively.

    Args:
        bucket:             S3 bucket containing the intake form PDF
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      SNS topic ARN for Textract completion notifications
        textract_role_arn:  IAM role ARN Textract can assume to publish to SNS

    Returns:
        The stored extraction record from DynamoDB.
    """

    # Step 1: Submit the async Textract job.
    # The call returns immediately with a job ID. The work happens in the background.
    logger.info("Step 1: Submitting Textract job for s3://%s/%s", bucket, key)
    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    logger.info("  Job ID: %s", job_id)

    # Step 2: Wait for completion (polling) and retrieve all result pages.
    # In production, your second Lambda is triggered by SNS instead of this loop.
    logger.info("Step 2: Waiting for job completion and retrieving all blocks...")
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Determine page count from the PAGE blocks in the response.
    page_count = sum(1 for b in all_blocks if b.get("BlockType") == "PAGE")
    logger.info("  Document had %d page(s)", page_count)

    # Step 3: Parse key-value pairs and checkbox selection elements.
    logger.info("Step 3: Parsing forms (key-value pairs and checkboxes)...")
    text_kv, checkbox_fields = parse_forms(all_blocks, block_map)
    logger.info("  Found %d text fields, %d checkbox fields", len(text_kv), len(checkbox_fields))

    # Step 4: Parse tables (medication lists, allergy grids, procedure history).
    logger.info("Step 4: Parsing tables...")
    tables = parse_tables(all_blocks, block_map)

    # Step 5: Normalize field names and apply confidence gating.
    # Fields below the threshold go to flagged_fields, not into the record.
    logger.info("Step 5: Normalizing fields and applying confidence gate...")
    clean_fields, clean_checkboxes, tables, flagged = normalize_and_gate(
        text_kv, checkbox_fields, tables
    )
    logger.info("  Clean fields: %d, Flagged: %d", len(clean_fields), len(flagged))

    # Step 6: Assemble the structured record and write it to DynamoDB.
    logger.info("Step 6: Assembling and storing record...")
    result = assemble_and_store(
        document_key=key,
        page_count=page_count,
        clean_fields=clean_fields,
        clean_checkboxes=clean_checkboxes,
        tables=tables,
        flagged=flagged,
    )

    logger.info("Done. needs_review=%s, flagged_fields=%d", result['needs_review'], len(result['flagged_fields']))
    return result


# Example: run the pipeline directly against a test PDF.
if __name__ == "__main__":
    import json

    result = process_intake_form(
        bucket="my-intake-forms",
        key="intake-forms/2026/03/01/patient-00291.pdf",
        sns_topic_arn="arn:aws:sns:us-east-1:123456789012:textract-jobs",
        textract_role_arn="arn:aws:iam::123456789012:role/TextractServiceRole",
    )

    # DynamoDB Decimal objects aren't JSON-serializable by default.
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

In a production deployment, the two-Lambda architecture from the recipe looks like this. The parsing logic is unchanged; only the entry points differ.

```python
import json


def lambda_handler_start(event: dict, context) -> None:
    """
    Lambda 1 (intake-start): triggered by S3 upload events.

    Submits the Textract job and exits. Its only job is to start the work
    and record the job context. Everything else happens in the second Lambda.
    """
    # Parse the S3 event to get the bucket and key.
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"]

    # These would come from environment variables in a real deployment.
    # Never hardcode ARNs in Lambda code.
    import os
    sns_topic_arn = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
    textract_role_arn = os.environ["TEXTRACT_ROLE_ARN"]

    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    logger.info("Submitted job %s for s3://%s/%s", job_id, bucket, key)


def lambda_handler_process(event: dict, context) -> None:
    """
    Lambda 2 (intake-process): triggered by SNS notifications from Textract.

    Receives the job completion signal, retrieves the full results,
    runs the parsing pipeline, and stores the output. In a production
    system this function would also forward flagged records to a review queue.
    """
    # The SNS message payload contains the Textract completion notification.
    # It's JSON-encoded as the "Message" field inside the SNS envelope.
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id = sns_message["JobId"]
    job_status = sns_message["Status"]   # "SUCCEEDED" or "FAILED"

    if job_status != "SUCCEEDED":
        logger.warning("Job %s finished with status %s. Skipping processing.", job_id, job_status)
        return

    # Look up the original document path from the jobs tracking table.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    response = jobs_table.get_item(Key={"job_id": job_id})
    job_item = response.get("Item", {})

    bucket = job_item.get("bucket")
    key = job_item.get("key")

    if not bucket or not key:
        logger.warning("No job context found for job_id=%s. Cannot process.", job_id)
        return

    # Run steps 2 through 6. Step 1 already happened in the first Lambda.
    logger.info("Processing completed job %s for s3://%s/%s", job_id, bucket, key)

    all_blocks, block_map = retrieve_all_blocks(job_id)
    page_count = sum(1 for b in all_blocks if b.get("BlockType") == "PAGE")

    text_kv, checkbox_fields = parse_forms(all_blocks, block_map)
    tables = parse_tables(all_blocks, block_map)
    clean_fields, clean_checkboxes, tables, flagged = normalize_and_gate(
        text_kv, checkbox_fields, tables
    )
    result = assemble_and_store(
        document_key=key,
        page_count=page_count,
        clean_fields=clean_fields,
        clean_checkboxes=clean_checkboxes,
        tables=tables,
        flagged=flagged,
    )

    logger.info("Stored record for %s. needs_review=%s", key, result['needs_review'])
    # Production next step: if result["needs_review"], send the document_key
    # to your SQS review queue for Recipe 1.6 to pick up.
```

---

## The Gap Between This and Production

This example works: run it against a real intake form PDF and it will produce a structured JSON record with demographics, insurance fields, medical history checkboxes, and medication tables. But the distance between "works as a script" and "runs at a clinic handling real patient data" is significant. Here's where that gap lives.

**The SNS wiring.** This example uses polling. A production deployment replaces the polling loop with the SNS-triggered two-Lambda architecture described in the main recipe. The parsing code is identical. The operational difference is substantial: polling burns Lambda execution time and API calls. SNS triggers are event-driven and cost essentially nothing while the Textract job runs.

**The Textract service role.** Easy to get wrong. Textract needs a dedicated IAM role it can assume to publish to your SNS topic. It cannot use the Lambda execution role. The role needs `sns:Publish` on your specific topic ARN. The Lambda that submits the job needs `iam:PassRole` to pass this role to Textract. If jobs submit successfully but the second Lambda never fires, check this role first.

**Error handling.** Every external call here can fail. Textract can return a throttling error on `StartDocumentAnalysis` at high volume. `GetDocumentAnalysis` can return `PARTIAL_SUCCESS` if some pages couldn't be processed. `put_item` on DynamoDB can fail if the table doesn't exist or the record exceeds the item size limit (400KB). A production system wraps all of these in try/except with specific handling for each error type, structured logging, and dead-letter queues for documents that fail after retries.

**Retries and backoff.** The polling loop here is naive: fixed interval, fixed maximum attempts. A production polling loop (or better, a Step Functions state machine) uses exponential backoff with jitter. More importantly, the Textract job submission should retry on throttling errors with backoff rather than failing immediately.

**Input validation.** This code trusts its inputs. A production system validates that the S3 object exists before submitting a Textract job, checks that the file extension is a supported format (PDF or TIFF for async analysis), and verifies the file size is within Textract's limits. An unsupported format submitted to `StartDocumentAnalysis` produces a FAILED job status rather than an error on submission, which is harder to debug.

**The FIELD_MAP and unmatched labels.** When Textract reads a label that doesn't match any known variant, this code silently drops it. A production system logs every unrecognized label so you can review them and expand FIELD_MAP as you encounter new form layouts. The intake form landscape is not standardized. You will see layouts you didn't expect.

**Table ordering assumptions.** The pipeline stores `tables[0]` as medications and `tables[1]` as allergies. That's a convention based on common intake form layouts, not a guarantee. A more robust implementation uses the column headers from the first row of each table to identify what kind of data it contains. A medication table's headers include words like "Medication", "Dosage", and "Frequency". An allergy table's headers include "Allergen" and "Reaction". Match on headers, not on position.

**DynamoDB data types.** This example already wraps confidence scores in `Decimal` (see Step 5), but be aware: if you add any new numeric field to the DynamoDB record, wrap it in `Decimal(str(value))` before writing. A plain Python float will raise a `TypeError` from boto3 at runtime.

**Handwriting.** This pipeline handles handwritten fields at best effort and confidence-gates them conservatively. If your patient population frequently fills intake forms in cursive, expect a higher flagged field rate than the benchmarks in the main recipe suggest. That's not a failure: it's the confidence gating routing uncertain extractions to human review instead of writing wrong data silently. Build the review queue from Recipe 1.6 before this goes to production.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling PHI runs inside a VPC with private subnets and VPC endpoints for S3, Textract, DynamoDB, and SNS. Intake forms contain substantially more PHI than insurance cards: full demographics, SSNs, medical history, medication lists. The encryption and network isolation posture should reflect that. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest. All API calls over TLS. KMS key rotation enabled.

**Testing.** There are no tests here. A production pipeline has unit tests for each parsing function with mocked Textract responses, integration tests against real Textract calls using synthetic patient data, and a fixture library covering the intake form layouts you actually receive. Never use real patient forms in test fixtures, even for non-production environments.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.2: Patient Intake Form Digitization](chapter01.02-patient-intake-digitization) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
