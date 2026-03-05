# Recipe 1.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.8. It is meant to show one way you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a claims adjudication system on Monday morning. Consider it a starting point, not a destination.
>
> One important note on the async flow: Recipe 1.8 describes a two-Lambda architecture connected by SNS. This example implements the same logic as a polling loop so you can run it as a single script during development without provisioning SNS topics and Lambda triggers. The polling approach works fine for experimentation. For production, replace the polling loop with the SNS-triggered Lambda pair described in the main recipe. The parsing and financial validation logic is identical either way.
>
> One more thing worth calling out up front: unlike the clinical document recipes in this chapter, EOBs are financial documents. There is no Comprehend Medical anywhere in this pipeline. We're not extracting entities or detecting PHI categories. We're reading dollar amounts off a table, mapping column headers to canonical names, and checking whether the math adds up. The tooling reflects that.

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
- `dynamodb:GetItem`
- `sqs:SendMessage`
- `iam:PassRole` (so Lambda can pass the Textract service role to the `StartDocumentAnalysis` call)

You also need a Textract service role: a dedicated IAM role that Textract can assume to publish job completion notifications to your SNS topic. This is separate from your Lambda execution role. See the Prerequisites section in the main recipe for details.

---

## Configuration and Constants

The payer signatures, layout profiles, and thresholds live here at the top of the module. These are configuration, not logic. They're what you'll edit as you add payers, encounter layout refreshes, or tune the financial validation tolerances.

Treating the profiles as first-class configuration (rather than scattering them through function bodies) matters for a reason beyond cleanliness: payer EOB formats change. UHC refreshed their EOB template twice in the last three years. Anthem rebranded from their previous identity and updated their document headers. When a profile goes stale, you want to find and fix it in one place, not hunt through a codebase for every reference to "What Your Plan Paid."

```python
# PAYER_SIGNATURES: keyword patterns used to identify the issuing payer from the
# document header. Order matters within each list: more specific strings before
# more general ones.
#
# The detection logic checks the full header text (first-page blocks, lowercased)
# against these patterns in order. The first match wins.
#
# This list covers the major national payers. Expand it with regional plans,
# Medicare Advantage variants, and any payers prominent in your specific market.

PAYER_SIGNATURES = {
    "medicare": [
        "centers for medicare",
        "medicare summary notice",
        "department of health and human services",
        "medicare.gov",
        "cms",
    ],
    "unitedhealthcare": [
        "unitedhealthcare",
        "united health",
        "uhc",
        "optum",
    ],
    "anthem": [
        "anthem blue cross",
        "anthem bcbs",
        "elevance health",
        "wellpoint",
        "anthem",
    ],
    "aetna": [
        "aetna life insurance",
        "cvs health",
        "aetna",
    ],
    "cigna": [
        "cigna healthcare",
        "evernorth",
        "cigna",
    ],
    "humana": [
        "humana insurance",
        "humana health",
        "humana",
    ],
    "bcbs": [
        "blue cross blue shield",
        "bluecross",
        "blue cross",
        "blueshield",
        "blue shield",
    ],
    "kaiser": [
        "kaiser permanente",
        "kaiser foundation",
    ],
}


# LAYOUT_PROFILES: maps payer-specific column header text and key-value field labels
# to canonical field names. One profile per payer, plus an "unknown" fallback.
#
# Canonical field names used consistently across all payer outputs:
#   claim_number, member_name, member_id, group_number, provider_name, service_period
#   date_of_service, service_description, procedure_code
#   billed_amount, allowed_amount, adjustment, plan_paid, member_responsibility
#   deductible_applied, copay, coinsurance, non_covered
#
# Each profile has two sections:
#   table_headers  maps payer-specific column labels to canonical field names
#   kv_fields      maps payer-specific key-value labels to canonical header names
#
# Keys are lowercased strings. The lookup normalizes input the same way.
# Do not add regex or wildcard patterns here: this is a flat lookup, not a matcher.
# Fuzzy matching is the job of the "unknown" fallback profile.

LAYOUT_PROFILES = {

    "medicare": {
        "table_headers": {
            "service date":                  "date_of_service",
            "services provided":             "service_description",
            "amount charged":                "billed_amount",
            "medicare approved":             "allowed_amount",
            "medicare paid provider":        "plan_paid",
            "you may be billed":             "member_responsibility",
            "non-covered amount":            "non_covered",
        },
        "kv_fields": {
            "claim number":                  "claim_number",
            "patient name":                  "member_name",
            "health insurance claim number": "member_id",
            "hicn":                          "member_id",
            "medicare id":                   "member_id",
            "date received":                 "received_date",
        },
    },

    "unitedhealthcare": {
        "table_headers": {
            "date of service":               "date_of_service",
            "service":                       "service_description",
            "procedure code":                "procedure_code",
            "what your provider billed":     "billed_amount",
            "amount allowed":                "allowed_amount",
            "what your plan allows":         "allowed_amount",
            "network discount":              "adjustment",
            "what your plan paid":           "plan_paid",
            "what you owe":                  "member_responsibility",
            "deductible":                    "deductible_applied",
            "copayment":                     "copay",
            "coinsurance":                   "coinsurance",
        },
        "kv_fields": {
            "claim #":                       "claim_number",
            "claim number":                  "claim_number",
            "member":                        "member_name",
            "member id":                     "member_id",
            "group number":                  "group_number",
            "date of service":               "service_period",
            "provider":                      "provider_name",
        },
    },

    "anthem": {
        "table_headers": {
            "date(s) of service":            "date_of_service",
            "description":                   "service_description",
            "procedure":                     "procedure_code",
            "amount billed":                 "billed_amount",
            "allowed amount":                "allowed_amount",
            "eligible amount":               "allowed_amount",
            "plan discount":                 "adjustment",
            "plan paid amount":              "plan_paid",
            "your responsibility":           "member_responsibility",
            "applied to deductible":         "deductible_applied",
        },
        "kv_fields": {
            "claim number":                  "claim_number",
            "member name":                   "member_name",
            "member id":                     "member_id",
            "group number":                  "group_number",
            "provider name":                 "provider_name",
        },
    },

    # The "unknown" fallback profile uses a broader set of synonyms for each
    # canonical field. It catches payers not in the library and handles layout
    # variants within known payers that don't match the primary profile.
    #
    # Less precise than a dedicated profile. Financial validation catches most
    # errors that slip through from ambiguous column mapping.
    "unknown": {
        "table_headers": {
            "date":                          "date_of_service",
            "service date":                  "date_of_service",
            "date of service":               "date_of_service",
            "billed":                        "billed_amount",
            "charges":                       "billed_amount",
            "amount billed":                 "billed_amount",
            "amount charged":                "billed_amount",
            "what your provider billed":     "billed_amount",
            "allowed":                       "allowed_amount",
            "approved":                      "allowed_amount",
            "allowed amount":                "allowed_amount",
            "medicare approved":             "allowed_amount",
            "paid":                          "plan_paid",
            "plan paid":                     "plan_paid",
            "plan paid amount":              "plan_paid",
            "what your plan paid":           "plan_paid",
            "medicare paid provider":        "plan_paid",
            "you owe":                       "member_responsibility",
            "your responsibility":           "member_responsibility",
            "what you owe":                  "member_responsibility",
            "you may be billed":             "member_responsibility",
            "member responsibility":         "member_responsibility",
            "patient responsibility":        "member_responsibility",
            "adjustment":                    "adjustment",
            "discount":                      "adjustment",
            "network discount":              "adjustment",
            "plan discount":                 "adjustment",
            "procedure":                     "procedure_code",
            "procedure code":                "procedure_code",
            "cpt":                           "procedure_code",
            "service":                       "service_description",
            "description":                   "service_description",
            "services provided":             "service_description",
        },
        "kv_fields": {
            "claim":                         "claim_number",
            "claim #":                       "claim_number",
            "claim number":                  "claim_number",
            "claim id":                      "claim_number",
            "member":                        "member_name",
            "member name":                   "member_name",
            "patient name":                  "member_name",
            "member id":                     "member_id",
            "subscriber id":                 "member_id",
            "id number":                     "member_id",
            "health insurance claim number": "member_id",
            "provider":                      "provider_name",
            "provider name":                 "provider_name",
        },
    },
}


# Financial validation tolerances.
#
# EOB dollar amounts are frequently printed with rounding. A contractual
# adjustment calculated as 36.2314% of billed doesn't round evenly. Small
# residuals are expected; large ones are errors.
#
# ROUNDING_TOLERANCE: maximum acceptable difference (in dollars) between
# a calculated expected value and the extracted value before flagging.
# $0.01 covers normal rounding (one cent); use $0.02 if you see false positives
# on Medicare claims with specific adjustment methodologies.
ROUNDING_TOLERANCE = 0.01

# MEMBER_RESP_TOLERANCE: the member responsibility validation is deliberately
# looser than the rounding tolerance. Copays, deductibles, COB adjustments,
# and coordination of benefits rules can shift the member amount by a few
# dollars without indicating an error. $1.00 is a reasonable starting point.
# Tighten this if your payer mix has straightforward cost-sharing structures.
MEMBER_RESP_TOLERANCE = 1.00


# Polling configuration for the development loop.
# In production, replace the polling loop with the SNS-triggered Lambda pattern.
POLL_INTERVAL_SECONDS = 5
MAX_POLL_ATTEMPTS = 24   # 24 * 5 = 120 seconds maximum wait


# DynamoDB and SQS resource names.
JOBS_TABLE_NAME = "textract-jobs"      # tracks in-flight async jobs
EOB_TABLE_NAME  = "eob-records"        # stores completed EOB extraction records
EOB_REVIEW_QUEUE_URL = (               # review queue for flagged documents
    "https://sqs.us-east-1.amazonaws.com/123456789012/eob-review"
)
```

---

## Step 1: Submit the Async Textract Job

*The pseudocode calls this `submit_eob_extraction(bucket, key, sns_topic_arn, textract_role_arn)`. An EOB PDF lands in S3 and triggers the eob-start Lambda. We call `StartDocumentAnalysis` requesting both FORMS and TABLES in one job, save the job context to DynamoDB, and exit. The extraction happens in the background.*

```python
import boto3
import datetime
import json
from datetime import timezone
from decimal import Decimal, ROUND_HALF_UP

# Clients. Module-level so they survive across warm Lambda invocations.
textract_client = boto3.client("textract")
dynamodb        = boto3.resource("dynamodb")
sqs_client      = boto3.client("sqs")


def submit_eob_extraction(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> str:
    """
    Submit an EOB PDF to Textract for async analysis.

    This is the function your eob-start Lambda calls when an S3 upload event fires.
    It starts the Textract job and saves context to DynamoDB, then exits.
    The eob-process Lambda picks up when Textract signals completion via SNS.

    Args:
        bucket:             S3 bucket name where the EOB PDF lives
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      ARN of the SNS topic for job completion notifications
        textract_role_arn:  ARN of the IAM role Textract uses to publish to SNS

    Returns:
        The Textract job ID.
    """

    # StartDocumentAnalysis accepts multi-page PDFs and TIFFs from S3.
    # We request both FORMS and TABLES in a single job:
    #   FORMS:  extracts the claim header fields (claim number, member ID, etc.)
    #   TABLES: extracts the line item grid (procedure codes and dollar amounts)
    #
    # One job, one cost, one set of results to parse. Don't submit two jobs.
    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": bucket,
                "Name": key,
            }
        },
        FeatureTypes=["FORMS", "TABLES"],
        NotificationChannel={
            # Textract publishes a message to this topic when the job finishes.
            "SNSTopicArn": sns_topic_arn,
            # Textract needs its own IAM role to publish to SNS. It cannot use
            # your Lambda's execution role. If jobs complete silently without
            # triggering the eob-process Lambda, this role is the first thing
            # to check. See The Honest Take in the main recipe for the full story.
            "RoleArn": textract_role_arn,
        },
    )

    job_id = response["JobId"]

    # Save job context. When the SNS notification fires and wakes the second Lambda,
    # it will have the job ID but not the original document path. We record
    # the mapping here so the second Lambda can reconstruct the full context.
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
```

---

## Step 2: Retrieve All Result Pages

*The pseudocode calls this `retrieve_all_blocks(job_id)`. Textract paginates results for multi-page documents. A three-page EOB with a dense line item table can produce several hundred blocks across multiple response pages. We must collect every block before parsing begins. Stopping at the first page leaves you with a partial document, and you won't know it until the line items don't add up.*

```python
def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Retrieve all extracted blocks from a completed Textract async job.

    Textract returns up to 1,000 blocks per API call. Multi-page EOBs can
    produce well over 1,000 blocks. We loop through all result pages, collect
    every block, and build a lookup index before any parsing begins.

    In production, call this function only after the SNS notification tells you
    the job has SUCCEEDED. The polling loop here is for development convenience.

    Args:
        job_id: The Textract job ID from submit_eob_extraction.

    Returns:
        A tuple of (all_blocks, block_map):
        - all_blocks: flat list of every block Textract extracted
        - block_map:  dict of block ID -> block, for O(1) lookups
    """
    import time

    # Polling loop: wait for job completion.
    # In production this entire loop is replaced by the SNS trigger pattern.
    job_status = "IN_PROGRESS"
    attempts   = 0

    while job_status == "IN_PROGRESS" and attempts < MAX_POLL_ATTEMPTS:
        attempts += 1
        status_response = textract_client.get_document_analysis(JobId=job_id)
        job_status = status_response["JobStatus"]

        if job_status == "IN_PROGRESS":
            print(f"  Job {job_id} still running (attempt {attempts}/{MAX_POLL_ATTEMPTS})...")
            time.sleep(POLL_INTERVAL_SECONDS)
        elif job_status == "FAILED":
            # Textract couldn't process the document. Common causes on EOBs:
            # corrupted PDF from a degraded fax transmission, file size exceeding
            # Textract's limits, or a permissions issue reading from S3.
            raise RuntimeError(
                f"Textract job {job_id} failed. "
                f"StatusMessage: {status_response.get('StatusMessage', 'no message')}"
            )

    if job_status != "SUCCEEDED":
        raise TimeoutError(
            f"Textract job {job_id} did not complete in time. Last status: {job_status}"
        )

    # Job succeeded. Collect ALL result pages via pagination.
    all_blocks = []
    next_token = None

    while True:
        params = {"JobId": job_id}
        if next_token is not None:
            params["NextToken"] = next_token

        response = textract_client.get_document_analysis(**params)

        page_blocks = response.get("Blocks", [])
        all_blocks.extend(page_blocks)

        next_token = response.get("NextToken")
        if next_token is None:
            break

    print(f"  Retrieved {len(all_blocks)} total blocks across all result pages")

    # Build the ID-to-block lookup. Nearly every parsing operation below follows
    # cross-references between blocks by ID. O(1) dict lookups make that fast.
    block_map = {block["Id"]: block for block in all_blocks}

    return all_blocks, block_map
```

---

## Step 3: Extract the EOB Header Fields

*The pseudocode calls this `extract_header_fields(all_blocks, block_map)`. The claim header contains the document-identifying fields: claim number, member name, member ID, service period, and sometimes the total payment summary. These come from Textract's KEY_VALUE_SET blocks. The parsing logic is the same as Recipe 1.1 and Recipe 1.2. The output is a raw label-to-value dictionary that gets mapped to canonical names in Step 5.*

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: assemble the full text of a block from its CHILD WORD blocks.

    Textract stores text in a hierarchy. A KEY or VALUE block has CHILD
    relationships pointing to individual WORD blocks. We follow those links
    and concatenate the words to reconstruct the full string.

    This helper is identical to the one in Recipe 1.1 and Recipe 1.2.
    The block structure is the same across all Textract document types.
    """
    text = ""

    for relationship in block.get("Relationships", []):
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child_block = block_map.get(child_id, {})
                if child_block.get("BlockType") == "WORD":
                    text += child_block.get("Text", "") + " "

    return text.strip()


def extract_header_fields(all_blocks: list, block_map: dict) -> dict:
    """
    Extract key-value pairs from the EOB header using FORMS output.

    EOBs don't have checkboxes. Every KEY_VALUE_SET block is a text field:
    claim identifiers, member info, dates, sometimes a payment summary total.
    We collect them all as raw label-to-value pairs with confidence scores.
    The layout profile in Step 5 maps these raw labels to canonical names.

    Args:
        all_blocks: all blocks from retrieve_all_blocks
        block_map:  block ID -> block dict from retrieve_all_blocks

    Returns:
        Dict of raw label -> {"value": str, "confidence": float}
    """
    raw_header = {}

    for block in all_blocks:

        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        if "KEY" not in block.get("EntityTypes", []):
            continue

        # Assemble the label text.
        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue

        # Follow the VALUE relationship to the paired value block.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                value_block = block_map.get(relationship["Ids"][0])
                break

        if value_block is None:
            continue

        value_text = get_text_from_block(value_block, block_map)

        # Use the lower of the two confidence scores: key or value.
        # If Textract was uncertain about either side, we flag the whole pair.
        confidence = min(
            block.get("Confidence", 0.0),
            value_block.get("Confidence", 0.0),
        )

        raw_header[key_text] = {
            "value":      value_text.strip(),
            "confidence": confidence,
        }

    return raw_header
```

---

## Step 4: Detect the Payer from the Header Text

*The pseudocode calls this `detect_payer(all_blocks)`. We read the extracted text from the first page's blocks, normalize to lowercase, and check against the keyword signatures in PAYER_SIGNATURES. This is string matching, not ML. EOB headers are highly formulaic: the payer name and document title appear prominently, reliably, in every document they issue. The exception cases (regional plan rebrands, Medicare Advantage plan names) are handled by expanding the keyword set and flagging low-confidence detections for human review.*

```python
def detect_payer(all_blocks: list) -> str:
    """
    Identify the payer that issued this EOB from the document header text.

    The header is the most reliable place to find the payer's identity.
    We collect all text from first-page blocks, lowercase it, and check
    for keyword signatures from PAYER_SIGNATURES.

    The order of signatures matters. PAYER_SIGNATURES is ordered so that
    more specific patterns come before more general ones within each payer.
    The outer payer dict is also ordered: more specific payer identities
    (Medicare, with its distinctive "Centers for Medicare" language) before
    more general ones (BCBS, which shares some language with sub-plans).

    Args:
        all_blocks: all blocks from retrieve_all_blocks

    Returns:
        A payer ID string: one of the keys in PAYER_SIGNATURES, or "unknown".
    """

    # Collect text from the first page only.
    # Payer identity lives in the header; we avoid false matches on provider
    # names or employer names that appear in the document body.
    first_page_text = " ".join(
        block.get("Text", "")
        for block in all_blocks
        if block.get("BlockType") == "WORD" and block.get("Page") == 1
    ).lower()

    for payer_id, keywords in PAYER_SIGNATURES.items():
        for keyword in keywords:
            if keyword in first_page_text:
                print(f"  Payer detected: {payer_id} (matched '{keyword}')")
                return payer_id

    # No match. The "unknown" profile handles this with fuzzy label matching.
    # Log the first 200 characters of the header text to help diagnose what
    # the document actually says. You'll use this to build new profiles.
    print(f"  Payer not recognized. Header preview: '{first_page_text[:200]}'")
    print("  Falling back to generic layout profile.")
    return "unknown"
```

---

## Step 5: Apply the Payer Layout Profile

*The pseudocode calls this `apply_layout_profile(all_blocks, block_map, raw_header, payer_id)`. This is the heart of what makes EOB processing different from generic table extraction. The profile maps payer-specific column labels to canonical names, and payer-specific key-value labels to canonical header names. After this step, downstream code sees `plan_paid` regardless of whether the document said "What Your Plan Paid," "Medicare Paid Provider," or "Plan Paid Amount."*

```python
def build_grid_from_table_block(table_block: dict, block_map: dict) -> dict:
    """
    Helper: reconstruct a table's row-column grid from a TABLE block's CELLs.

    Textract represents tables as TABLE blocks with CELL block children.
    Each CELL has RowIndex and ColumnIndex (both 1-based integers).
    We rebuild the grid as a nested dict: {row: {col: cell_text}}.

    This is the same grid-building logic from Recipe 1.2 Step 4,
    pulled out as a helper since we need it per-table in apply_layout_profile.
    """
    grid = {}

    for relationship in table_block.get("Relationships", []):
        if relationship["Type"] != "CHILD":
            continue

        for cell_id in relationship["Ids"]:
            cell_block = block_map.get(cell_id, {})
            if cell_block.get("BlockType") != "CELL":
                continue

            row = cell_block.get("RowIndex", 0)
            col = cell_block.get("ColumnIndex", 0)

            # Assemble cell text from the CELL's WORD children.
            cell_text = ""
            for cell_rel in cell_block.get("Relationships", []):
                if cell_rel["Type"] == "CHILD":
                    for word_id in cell_rel["Ids"]:
                        word_block = block_map.get(word_id, {})
                        if word_block.get("BlockType") == "WORD":
                            cell_text += word_block.get("Text", "") + " "
            cell_text = cell_text.strip()

            if row not in grid:
                grid[row] = {}
            grid[row][col] = cell_text

    return grid


def apply_layout_profile(
    all_blocks: list,
    block_map: dict,
    raw_header: dict,
    payer_id: str,
) -> tuple[dict, list]:
    """
    Map payer-specific field labels to canonical names using the layout profile.

    Two mappings happen here:
      1. Key-value header fields: "Claim #" -> "claim_number"
      2. Table column headers: "What Your Plan Paid" -> "plan_paid"

    After this step, all output uses canonical names. Downstream code never
    needs to know whether it's looking at a UHC or Medicare document.

    Unrecognized table column headers keep their raw label rather than being
    silently dropped. Unrecognized key-value labels are not included in the
    output (there are usually many irrelevant ones in the header region).

    Args:
        all_blocks:  all blocks from retrieve_all_blocks
        block_map:   block ID -> block dict
        raw_header:  output from extract_header_fields
        payer_id:    output from detect_payer

    Returns:
        A tuple of (header_fields, line_items):
        - header_fields: dict of canonical name -> {"value": str, "confidence": float}
        - line_items:    list of dicts, one per data row, with canonical field names
    """

    # Select the profile. Fall back to "unknown" for unrecognized payers.
    profile = LAYOUT_PROFILES.get(payer_id, LAYOUT_PROFILES["unknown"])

    # Map key-value header fields through the profile.
    header_fields = {}
    for raw_label, data in raw_header.items():
        canonical = profile["kv_fields"].get(raw_label.lower().strip())
        if canonical:
            header_fields[canonical] = data

    # Map table column headers and build line items.
    line_items = []

    for block in all_blocks:
        if block.get("BlockType") != "TABLE":
            continue

        grid = build_grid_from_table_block(block, block_map)

        if not grid:
            continue

        max_row = max(grid.keys())
        if max_row < 2:
            # Need at least a header row and one data row to be useful.
            continue

        # Get column indices in order.
        header_row = grid.get(1, {})
        sorted_cols = sorted(header_row.keys())

        # Map each column header to a canonical name.
        # Unrecognized headers keep their raw label (lowercased) rather than
        # being dropped silently. You can see them in the output and decide
        # whether to add them to the profile.
        canonical_headers = []
        for col in sorted_cols:
            raw_col_header = header_row.get(col, "").lower().strip()
            canonical       = profile["table_headers"].get(raw_col_header, raw_col_header)
            canonical_headers.append(canonical)

        # Build one dict per data row.
        for r in range(2, max_row + 1):
            item = {}
            for i, canonical_name in enumerate(canonical_headers):
                col_index   = sorted_cols[i]
                cell_value  = grid.get(r, {}).get(col_index, "").strip()
                item[canonical_name] = cell_value
            line_items.append(item)

    print(f"  Applied '{payer_id}' profile: "
          f"{len(header_fields)} header fields, {len(line_items)} line items")

    return header_fields, line_items
```

---

## Step 6: Parse Currency Values and Validate the Financials

*The pseudocode calls these `parse_currency(text)` and `validate_eob_financials(header_fields, line_items)`. Currency strings come out of Textract as text: "$185.00", "1,234.56", "(23.60)" for negative values in some payer formats. We parse them to Decimal (not float) for financial precision. Then we apply the mathematical constraints that every well-formed EOB must satisfy.*

```python
def parse_currency(text: str):
    """
    Parse an EOB currency string to a Decimal value.

    Handles: $185.00  185  $1,234.56  (23.60) for negative amounts.
    Returns None for blank, non-numeric, or unparseable values.

    We use Decimal throughout this pipeline for financial calculations.
    Float arithmetic introduces rounding errors that compound when you're
    checking whether line items sum to a header total. One cent of float
    drift can produce spurious validation failures at high claim volumes.
    Decimal avoids that entirely.

    Args:
        text: raw cell text from a Textract extraction

    Returns:
        Decimal value, or None if the text can't be parsed.
    """
    if not text or not text.strip():
        return None

    cleaned = text.strip()

    # Some payers print negative amounts as parenthesized values: (23.60)
    # This is an accounting convention, not an error. Detect and handle it.
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]

    # Strip dollar signs and commas.
    cleaned = cleaned.replace("$", "").replace(",", "").strip()

    # Attempt the conversion. If it fails (e.g., the cell contains "N/A" or
    # a dash), return None gracefully rather than raising an exception.
    try:
        value = Decimal(cleaned)
        return -value if negative else value
    except Exception:
        return None


def validate_eob_financials(
    header_fields: dict,
    line_items: list,
) -> list:
    """
    Apply financial math constraints to the extracted EOB data.

    Every well-formed EOB satisfies a set of mathematical relationships.
    These constraints give us a validation oracle that operates on the
    extracted numbers themselves, independent of any OCR confidence score.
    A cell read with 96% confidence can still contain a transposed digit.
    The math catches what the confidence score misses.

    Validation rules checked:
      1. Billed >= Allowed (contractual rate can't exceed submitted charge)
      2. Allowed >= Plan Paid (plan can't pay more than the allowed amount)
      3. Member responsibility approximates Allowed minus Plan Paid
      4. Line item plan payments sum to the header total (if present)

    Errors don't mean we discard the record. They mean we route it to the
    review queue with specific error context attached.

    Args:
        header_fields: canonical header dict from apply_layout_profile
        line_items:    canonical line item list from apply_layout_profile

    Returns:
        List of error dicts. Empty list means the financials check out.
    """
    errors = []

    for index, item in enumerate(line_items):
        row_num = index + 1   # 1-indexed for human-readable error messages

        billed  = parse_currency(item.get("billed_amount", ""))
        allowed = parse_currency(item.get("allowed_amount", ""))
        paid    = parse_currency(item.get("plan_paid", ""))
        member  = parse_currency(item.get("member_responsibility", ""))

        # Rule 1: Billed must be >= Allowed.
        # The allowed amount is the contractual rate negotiated between the payer
        # and the provider. It can't exceed what the provider actually billed.
        # If it does, either the billed amount was misread or the allowed amount
        # mapped to the wrong column.
        if billed is not None and allowed is not None:
            tolerance = Decimal(str(ROUNDING_TOLERANCE))
            if allowed > billed + tolerance:
                errors.append({
                    "row":    row_num,
                    "rule":   "allowed_exceeds_billed",
                    "detail": (
                        f"Row {row_num}: allowed {allowed} > billed {billed}. "
                        "Possible column mapping error or OCR transposition."
                    ),
                })

        # Rule 2: Allowed must be >= Plan Paid.
        # The plan can't pay more than the allowed amount.
        if allowed is not None and paid is not None:
            tolerance = Decimal(str(ROUNDING_TOLERANCE))
            if paid > allowed + tolerance:
                errors.append({
                    "row":    row_num,
                    "rule":   "paid_exceeds_allowed",
                    "detail": (
                        f"Row {row_num}: paid {paid} > allowed {allowed}. "
                        "Plan payment can't exceed the allowed amount."
                    ),
                })

        # Rule 3: Member responsibility should approximate Allowed minus Plan Paid.
        # We use MEMBER_RESP_TOLERANCE (default $1.00) because copays, deductibles,
        # and COB adjustments create small legitimate differences that aren't errors.
        # This is deliberately looser than the rounding tolerance above.
        if allowed is not None and paid is not None and member is not None:
            expected_member = (allowed - paid).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            diff = abs(member - expected_member)
            if diff > Decimal(str(MEMBER_RESP_TOLERANCE)):
                errors.append({
                    "row":    row_num,
                    "rule":   "member_resp_mismatch",
                    "detail": (
                        f"Row {row_num}: member responsibility {member} != "
                        f"allowed {allowed} - paid {paid} = {expected_member} "
                        f"(diff: {diff})"
                    ),
                })

    # Rule 4: Line item plan payments should sum to the header total, if present.
    # This cross-check catches cases where line items parsed correctly but the
    # header summary total didn't, or vice versa.
    header_paid_raw = header_fields.get("plan_paid", {})
    if isinstance(header_paid_raw, dict):
        header_paid_raw = header_paid_raw.get("value", "")
    header_total_paid = parse_currency(str(header_paid_raw))

    if header_total_paid is not None:
        line_total_paid = sum(
            parse_currency(item.get("plan_paid", ""))
            for item in line_items
            if parse_currency(item.get("plan_paid", "")) is not None
        )

        diff = abs(line_total_paid - header_total_paid)
        if diff > Decimal("0.10"):   # ten cents tolerance for header-vs-line rounding
            errors.append({
                "row":    "header",
                "rule":   "line_total_mismatch",
                "detail": (
                    f"Line items sum to {line_total_paid}, "
                    f"header shows {header_total_paid} "
                    f"(diff: {diff})"
                ),
            })

    return errors
```

---

## Step 7: Assemble the Record and Route It

*The pseudocode calls this `assemble_and_route(document_key, payer_id, header_fields, line_items, validation_errors)`. We combine the payer identity, header fields, line items, and validation results into a canonical EOB record. Valid records go to DynamoDB. Flagged records go to DynamoDB AND to the SQS review queue, so adjusters have everything they need to work the item without opening the source PDF.*

```python
def to_decimal(value) -> Decimal:
    """
    Convert a float or numeric string to Decimal for DynamoDB.

    DynamoDB's Python SDK (boto3) does not accept Python float values.
    It requires Decimal for all numeric types. This helper converts safely
    by going through str() first to avoid floating-point representation
    artifacts in the Decimal conversion.

    This applies to any numeric field being written to DynamoDB, not just
    the financial amounts. Confidence scores, item counts, everything.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def assemble_and_route(
    document_key: str,
    payer_id: str,
    header_fields: dict,
    line_items: list,
    validation_errors: list,
) -> dict:
    """
    Assemble the canonical EOB record and write it to DynamoDB and/or SQS.

    Every record goes to DynamoDB: valid and flagged alike. The record is the
    source of truth. Flagged records additionally go to the SQS review queue
    with enough context that an adjuster can work the item without having to
    find and open the original PDF.

    Records are also flagged when payer detection returned "unknown." Unknown
    layout means unvalidated extraction. Unvalidated financial data in an
    adjudication system is a liability.

    Args:
        document_key:       S3 object key of the source EOB PDF
        payer_id:           output from detect_payer
        header_fields:      canonical header dict from apply_layout_profile
        line_items:         canonical line items from apply_layout_profile
        validation_errors:  output from validate_eob_financials

    Returns:
        The full record dict (as written to DynamoDB).
    """

    def get_header_value(field_name: str):
        """Extract just the value string from a header field dict."""
        data = header_fields.get(field_name, {})
        if isinstance(data, dict):
            return data.get("value")
        return data

    # Determine the overall status.
    is_valid    = len(validation_errors) == 0 and payer_id != "unknown"
    status      = "valid" if is_valid else "flagged"

    # Serialize line items, converting any Decimal currency values for DynamoDB.
    # The raw line item values are still strings at this point (as extracted from
    # Textract). We store them as strings in DynamoDB to preserve original
    # formatting. If you want to store parsed Decimal amounts, convert here.
    now_iso = datetime.datetime.now(timezone.utc).isoformat()

    record = {
        "document_key":   document_key,
        "extracted_at":   now_iso,
        "payer_id":       payer_id,
        "payer_confidence": "detected" if payer_id != "unknown" else "fallback_profile",

        "header": {
            "claim_number":  get_header_value("claim_number"),
            "member_name":   get_header_value("member_name"),
            "member_id":     get_header_value("member_id"),
            "group_number":  get_header_value("group_number"),
            "provider_name": get_header_value("provider_name"),
            "service_period": get_header_value("service_period"),
        },

        # Line items are stored as a list of string-valued dicts.
        # DynamoDB handles mixed-type nested structures well.
        "line_items": line_items,

        "financial_validation": {
            "errors":       validation_errors,
            "status":       status,
            "validated_at": now_iso,
        },
    }

    # Write to DynamoDB.
    # All numeric values in the record are strings or nested dicts at this point.
    # If you add any Python float values to the record structure above, wrap
    # them in to_decimal() before this write. A float will raise a TypeError.
    eob_table = dynamodb.Table(EOB_TABLE_NAME)
    eob_table.put_item(Item=record)
    print(f"  Wrote record to DynamoDB. status={status}")

    # Route flagged records to the SQS review queue.
    # Include the specific validation errors and the document key so the adjuster
    # has everything they need to work the item without hunting for context.
    if not is_valid:
        reason = "unknown_payer_layout" if payer_id == "unknown" else "financial_validation_failed"

        review_message = {
            "document_key":      document_key,
            "payer_id":          payer_id,
            "claim_number":      get_header_value("claim_number"),
            "member_id":         get_header_value("member_id"),
            "validation_errors": validation_errors,
            "reason":            reason,
            "queued_at":         now_iso,
        }

        # SQS message bodies must be strings.
        # Validation error dicts contain only strings and ints; no special encoder needed.
        sqs_client.send_message(
            QueueUrl=EOB_REVIEW_QUEUE_URL,
            MessageBody=json.dumps(review_message),
        )
        print(f"  Sent to review queue. reason={reason}")

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is the polling-based version for development and scripts. The Lambda handler versions follow.

```python
def process_eob(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> dict:
    """
    Run the complete EOB extraction pipeline for one document.

    Implements all seven steps from the Recipe 1.8 pseudocode walkthrough.
    Uses a polling loop here for development convenience. In a production
    two-Lambda deployment, Steps 1 and 2-7 live in separate functions
    triggered by S3 events and SNS notifications respectively.

    Args:
        bucket:             S3 bucket containing the EOB PDF
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      SNS topic ARN for Textract completion notifications
        textract_role_arn:  IAM role ARN Textract can assume to publish to SNS

    Returns:
        The stored EOB record (as written to DynamoDB).
    """

    # Step 1: Submit the async Textract job.
    print(f"\nStep 1: Submitting Textract job for s3://{bucket}/{key}")
    job_id = submit_eob_extraction(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"  Job ID: {job_id}")

    # Step 2: Wait for job completion and retrieve all result pages.
    # In production, your eob-process Lambda is triggered by SNS instead of this loop.
    print("\nStep 2: Retrieving all result blocks...")
    all_blocks, block_map = retrieve_all_blocks(job_id)

    page_count = sum(1 for b in all_blocks if b.get("BlockType") == "PAGE")
    print(f"  Document: {page_count} page(s), {len(all_blocks)} total blocks")

    # Step 3: Extract the EOB header fields (claim number, member info, etc.)
    print("\nStep 3: Extracting header key-value fields...")
    raw_header = extract_header_fields(all_blocks, block_map)
    print(f"  Found {len(raw_header)} raw header fields")

    # Step 4: Detect the payer from the document header text.
    print("\nStep 4: Detecting payer...")
    payer_id = detect_payer(all_blocks)

    # Step 5: Apply the payer layout profile to get canonical field names.
    print("\nStep 5: Applying layout profile...")
    header_fields, line_items = apply_layout_profile(
        all_blocks, block_map, raw_header, payer_id
    )

    # Step 6: Parse currency values and validate the financial math.
    print("\nStep 6: Validating financials...")
    validation_errors = validate_eob_financials(header_fields, line_items)
    if validation_errors:
        print(f"  Validation found {len(validation_errors)} error(s):")
        for err in validation_errors:
            print(f"    [{err['rule']}] {err['detail']}")
    else:
        print("  Financials check out.")

    # Step 7: Assemble the record and route it to DynamoDB and/or SQS.
    print("\nStep 7: Assembling and routing record...")
    result = assemble_and_route(
        document_key=key,
        payer_id=payer_id,
        header_fields=header_fields,
        line_items=line_items,
        validation_errors=validation_errors,
    )

    status = result["financial_validation"]["status"]
    print(f"\nDone. status={status}, payer={payer_id}, line_items={len(line_items)}")
    return result


# Run directly against a test EOB for development.
if __name__ == "__main__":

    result = process_eob(
        bucket="my-eobs-inbox",
        key="eobs-inbox/unitedhealthcare/2026/03/01/eob-00423.pdf",
        sns_topic_arn="arn:aws:sns:us-east-1:123456789012:textract-jobs",
        textract_role_arn="arn:aws:iam::123456789012:role/TextractServiceRole",
    )

    # Decimal values aren't JSON-serializable by default.
    # This encoder converts them to float for display purposes only.
    # Do not use this pattern when writing data to downstream systems.
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## Lambda Handler Versions

In a production deployment, the two-Lambda architecture looks like this. The parsing and validation logic is unchanged. Only the entry points differ.

```python
def lambda_handler_start(event: dict, context) -> None:
    """
    Lambda 1 (eob-start): triggered by S3 upload events.

    Submits the Textract job and exits. Its only job is to start the work
    and record the job context. Everything else happens in the second Lambda.
    """
    import os

    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    # Pull ARNs from environment variables. Never hardcode them in function code.
    sns_topic_arn     = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
    textract_role_arn = os.environ["TEXTRACT_ROLE_ARN"]

    job_id = submit_eob_extraction(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"Submitted job {job_id} for s3://{bucket}/{key}")


def lambda_handler_process(event: dict, context) -> None:
    """
    Lambda 2 (eob-process): triggered by SNS notifications from Textract.

    Receives the job completion signal, retrieves results, runs the full
    extraction and validation pipeline, writes to DynamoDB, and routes
    flagged documents to the SQS review queue.

    Default Lambda timeout is 3 seconds. Set this to at least 60 seconds.
    A complex multi-page EOB with many line items takes 15-30 seconds
    to process through all seven steps.
    """

    # The SNS notification is JSON-encoded inside the event envelope.
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id      = sns_message["JobId"]
    job_status  = sns_message["Status"]

    if job_status != "SUCCEEDED":
        print(f"Job {job_id} finished with status {job_status}. Skipping.")
        return

    # Look up the original document path from the jobs tracking table.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    response   = jobs_table.get_item(Key={"job_id": job_id})
    job_item   = response.get("Item", {})

    bucket = job_item.get("bucket")
    key    = job_item.get("key")

    if not bucket or not key:
        print(f"No job context found for job_id={job_id}. Cannot process.")
        return

    print(f"Processing completed job {job_id} for s3://{bucket}/{key}")

    # Steps 2 through 7. Step 1 already happened in eob-start.
    all_blocks, block_map = retrieve_all_blocks(job_id)
    raw_header            = extract_header_fields(all_blocks, block_map)
    payer_id              = detect_payer(all_blocks)
    header_fields, line_items = apply_layout_profile(
        all_blocks, block_map, raw_header, payer_id
    )
    validation_errors = validate_eob_financials(header_fields, line_items)
    result = assemble_and_route(
        document_key=key,
        payer_id=payer_id,
        header_fields=header_fields,
        line_items=line_items,
        validation_errors=validation_errors,
    )

    status = result["financial_validation"]["status"]
    print(f"Stored record for {key}. status={status}, payer={payer_id}")
```

---

## The Gap Between This and Production

This example works. Run it against a real EOB PDF and it will produce a structured record with canonical header fields, mapped line items, and financial validation results. But the distance between "works as a script" and "runs in a COB adjudication workflow handling real claims" is significant. Here's where that gap lives.

**The SNS wiring.** This example uses polling. A production deployment replaces the polling loop with the SNS-triggered two-Lambda architecture from the main recipe. The parsing code is identical. The operational difference is substantial: polling burns Lambda execution time and API credits. SNS triggers cost essentially nothing while the Textract job runs.

**The Textract service role.** This is the most common first-time setup failure. Textract needs a dedicated IAM role it can assume to publish to your SNS topic. It cannot use the Lambda execution role. The role needs `sns:Publish` on your specific topic ARN. Your eob-start Lambda needs `iam:PassRole` to pass this role to Textract. If jobs submit successfully but the eob-process Lambda never fires, check this role first. The Textract async documentation has the exact IAM configuration.

**Decimal for DynamoDB.** This example uses `Decimal` throughout for financial calculations, which is the right call for precision regardless of the DynamoDB requirement. But be aware: if you add any Python `float` anywhere in the record structure before the `put_item` call, boto3 will raise a `TypeError` at runtime. The `to_decimal()` helper is there for exactly that. Use it on any value coming from external computation (confidence scores, intermediate sums, anything touching `float`).

**Lambda timeout.** The `eob-process` Lambda does real work: pagination loop, header extraction, payer detection, profile application, financial validation, DynamoDB write, optional SQS send. For a complex multi-page EOB with many line items, this takes 15-30 seconds. The Lambda default timeout is 3 seconds. Set it to at least 60 seconds and tune based on observed p99 in your environment.

**Idempotency.** SNS delivers at least once. The eob-process Lambda can be invoked twice for the same document, which currently produces a silent overwrite in DynamoDB. Add a conditional write (`ConditionExpression=Attr("document_key").not_exists()`) to `put_item` if you need to protect existing records from re-processing. If your pipeline can legitimately re-process an EOB (for example, after a payer profile update), keep the overwrite behavior but log it.

**Dead letter queues.** Both Lambdas receive asynchronous invocations: eob-start from S3 events, eob-process from SNS. Both have default retry behavior: up to three retries on failure, then silent discard. A lost EOB in a COB workflow means a pending secondary claim that never gets adjudicated. Attach SQS dead letter queues to both Lambdas and set a CloudWatch alarm on queue depth.

**The profile library is code. Test it like code.** The layout profiles are the core business logic of this recipe. A wrong mapping in the UHC profile means every UHC EOB produces incorrect canonical output, quietly, with no errors. Write unit tests that supply sample column headers and assert the canonical mapping. Test each payer profile independently. Payers change their EOB layouts without notice; your unit tests are how you detect drift.

**COB-specific validation.** The financial validation in Step 6 handles standard EOB math. Coordination of benefits adds complexity: the secondary payer's liability is calculated against the primary's allowed amount under coordination rules (standard, maintenance of benefits, or carve-out). If you're processing secondary claims in a COB workflow, add validation logic that cross-references the primary EOB record. The standard rules are well-documented in CAQH CORE operating rules; the carve-out variants are payer-contract-specific.

**Fuzzy matching for the unknown profile.** The "unknown" profile relies on exact lowercase string matching for the broader synonym set. For genuinely novel payer formats, even the fallback profile may miss columns. One practical improvement: after financial validation flags a record with unknown payer, log all unrecognized column headers. Review them periodically to find patterns that warrant a new dedicated profile. The cost of an unrecognized column is a flagged record and manual review. The cost of a wrong mapping is incorrect data written to your adjudication system. When in doubt, flag rather than guess.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling EOBs runs inside a VPC with private subnets and VPC endpoints for S3, Textract, DynamoDB, SNS, and SQS. Don't forget the CloudWatch Logs endpoint if your Lambda is in a private subnet without NAT. EOBs contain member PHI (name, ID, service dates) and financial data. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest. SQS SSE-KMS on the review queue. All API calls over TLS. KMS key rotation enabled.

**Error handling and retries.** Every external call can fail. Textract throttles `StartDocumentAnalysis` at high volume. DynamoDB can throttle `put_item` on burst writes. SQS `send_message` can fail if the queue is misconfigured. A production system wraps each call in try/except with specific handling per error type, exponential backoff with jitter on throttling errors, and structured logging that captures document key, job ID, and error details for ops.

**Testing.** There are no tests here. A production pipeline has unit tests for `parse_currency()` covering all the edge cases ($-signs, commas, parenthesized negatives, blank cells, non-numeric values), unit tests for `validate_eob_financials()` with known-good and known-bad line item sets, and integration tests using synthetic EOB fixtures (one per payer in your profile library). Never use real PHI in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.8: Explanation of Benefits Processing](chapter01.08-eob-processing) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard in practice.*
