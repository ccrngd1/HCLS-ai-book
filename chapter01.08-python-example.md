# Recipe 1.8: EOB Processing: Python Example

> **This is a trivial, illustrative implementation. Not production-ready.**
> It demonstrates the patterns from Recipe 1.8 using real boto3 API calls. It won't handle edge cases, doesn't have full error handling, and isn't optimized for throughput. Use it as a starting point, not a destination.
>
> You'll need to fill in resource names (DynamoDB table names, SQS queue URLs, SNS topic ARNs, Lambda function names) and add the production hardening described at the bottom of this file.

---

## Setup

```bash
pip install boto3
```

IAM permissions required (attach to your Lambda execution role):
- `textract:StartDocumentAnalysis`
- `textract:GetDocumentAnalysis`
- `s3:GetObject`
- `bedrock:InvokeModel`: scope to `arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0` and/or the Haiku 4.5 ARN
- `dynamodb:PutItem`, `dynamodb:GetItem`
- `sqs:SendMessage`
- `iam:PassRole` (for passing the Textract SNS notification role)

---

## Configuration

```python
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Optional

import boto3
from botocore.config import Config

# --- AWS Clients ---
# Retry configuration: adaptive mode implements exponential backoff with jitter.
# This is critical for Bedrock, which will throttle at volume.
# Without this, ThrottlingException and ServiceUnavailableException will surface
# as hard errors during peak load instead of being transparently retried.
RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}
)

REGION = "us-east-1"

textract_client = boto3.client("textract", region_name=REGION, config=RETRY_CONFIG)
bedrock_client  = boto3.client("bedrock-runtime", region_name=REGION, config=RETRY_CONFIG)
dynamodb        = boto3.resource("dynamodb", region_name=REGION, config=RETRY_CONFIG)
sqs_client      = boto3.client("sqs", region_name=REGION, config=RETRY_CONFIG)

# --- Resource Names (fill these in) ---
TEXTRACT_JOBS_TABLE = "textract-jobs"
EOB_RECORDS_TABLE   = "eob-records"
EOB_REVIEW_QUEUE    = "https://sqs.us-east-1.amazonaws.com/123456789012/eob-review"
TEXTRACT_ROLE_ARN   = "arn:aws:iam::123456789012:role/TextractSNSPublishRole"
SNS_TOPIC_ARN       = "arn:aws:sns:us-east-1:123456789012:textract-jobs"

# ⚠️ REPLACE BEFORE DEPLOYING: The constants above use AWS documentation example
# values (account 123456789012). These must be replaced with your actual AWS
# account ID, queue URLs, and role ARNs before deployment.
assert "123456789012" not in EOB_REVIEW_QUEUE, \
    "Deploy-time constant not replaced: EOB_REVIEW_QUEUE still uses example account ID"
assert "123456789012" not in TEXTRACT_ROLE_ARN, \
    "Deploy-time constant not replaced: TEXTRACT_ROLE_ARN still uses example account ID"

# --- Bedrock Model ---
# Nova Pro is the right tier for structured schema mapping: good accuracy at $0.80/MTok input.
# Claude Haiku 4.5 is an equally valid choice at $1.00/MTok input with slightly different
# strengths. For strict version pinning in production, use full model ARNs:
#   Amazon Nova Pro ARN: arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0
#   Cross-region inference profile ID used below routes to the nearest available region.
#   When using cross-region inference profiles with a VPC: your Lambda's API call goes to
#   the bedrock-runtime VPC endpoint in your deployment region; AWS routes internally to
#   the backend region. PHI does not traverse the public internet.
# [EDITOR: review fix: P1 #7 cross-region inference + VPC: added the comment above
# so readers referencing the Python file have the same callout as the recipe Prerequisites.]
BEDROCK_MODEL_ID = "us.amazon.nova-pro-v1:0"

# --- High-Volume Payer Profiles ---
# Maintain static profiles for your top payers by volume.
# These skip the Bedrock call entirely: cheaper, faster, fully deterministic.
# Everything not in this dict routes through Bedrock automatically.
HIGH_VOLUME_PROFILES = {
    "unitedhealthcare": {
        "table_headers": {
            "date of service":           "date_of_service",
            "procedure code":            "procedure_code",
            "service":                   "service_description",
            "what your provider billed": "billed_amount",
            "network discount":          "adjustment",
            "what your plan paid":       "plan_paid",
            # [EDITOR: review fix: P1 #3 UHC allowed_amount: added plan_allowed and
            # allowed_amount mappings. Without allowed_amount, financial validation
            # Rules 1, 2, and 3 all silently skip for UHC (the highest-volume payer).
            # UHC EOBs vary by template: check your specific EOB samples and keep
            # whichever label matches. If UHC genuinely omits an explicit allowed column,
            # derive it in validate_eob_financials: allowed = billed - adjustment.]
            "plan allowed":              "allowed_amount",
            "allowed amount":            "allowed_amount",
            "what you owe":              "member_responsibility",
            "deductible":                "deductible_applied",
            "copayment":                 "copay",
            "coinsurance":               "coinsurance",
        },
        "kv_fields": {
            "claim #":       "claim_number",
            "claim number":  "claim_number",
            "member":        "member_name",
            "member id":     "member_id",
            "group number":  "group_number",
            "provider":      "provider_name",
        }
    },
    "medicare": {
        "table_headers": {
            "service date":           "date_of_service",
            "services provided":      "service_description",
            "amount charged":         "billed_amount",
            "medicare approved":      "allowed_amount",
            "medicare paid provider": "plan_paid",
            "you may be billed":      "member_responsibility",
            "non-covered amount":     "non_covered",
        },
        "kv_fields": {
            "claim number":                   "claim_number",
            "patient name":                   "member_name",
            "health insurance claim number":  "member_id",
            "hicn":                           "member_id",
            "medicare id":                    "member_id",
        }
    },
    # Add Anthem, Aetna, Cigna, Humana, BCBS profiles here as you build them.
    # Validate each profile against real sample documents before deploying.
    # Write unit tests for each profile (see Gap to Production).
}

# --- Canonical EOB Schema ---
# This is sent to the LLM with the schema mapping prompt so it knows what to map to.
# Keeping this as a constant (rather than inline in the prompt) lets you cache it
# and makes it easy to extend when you add new canonical fields.
CANONICAL_SCHEMA = {
    "table_fields": {
        "date_of_service":       "Date the medical service was provided",
        "procedure_code":        "CPT or HCPCS billing code for the service",
        "service_description":   "Description of the service or procedure",
        "billed_amount":         "Dollar amount submitted by the provider (before adjustments)",
        "allowed_amount":        "Contractual allowed amount (after network discount)",
        "adjustment":            "Dollar amount of network discount or contractual adjustment",
        "plan_paid":             "Dollar amount paid by the insurance plan",
        "member_responsibility": "Dollar amount the member owes",
        "deductible_applied":    "Portion of member responsibility applied to deductible",
        "copay":                 "Fixed copayment amount",
        "coinsurance":           "Percentage-based member cost share",
        "non_covered":           "Amount for non-covered services",
    },
    "header_fields": {
        "claim_number":    "Unique claim identifier",
        "member_name":     "Name of the insured member",
        "member_id":       "Member's insurance ID number",
        "group_number":    "Group or plan number",
        "provider_name":   "Name of the treating provider",
        "service_period":  "Date or date range of the service period",
    }
}

# Pre-compute canonical sets for fast membership checks in _map_with_llm.
# [EDITOR: review fix: P1 #6 canonical field validation: these sets are used to filter
# Bedrock output values, ensuring only valid canonical names enter the pipeline.]
_VALID_TABLE_FIELDS  = set(CANONICAL_SCHEMA["table_fields"].keys())
_VALID_HEADER_FIELDS = set(CANONICAL_SCHEMA["header_fields"].keys())

# --- PHI Safety: Content to Strip from Prompts and Logs ---
# Regex for detecting potential injection attempts in extracted cell values.
# Crude but catches the most obvious manipulation patterns.
_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+previous|system:|assistant:|<\|im_start\|>|<\|im_end\|>)",
    re.IGNORECASE
)

# --- Control Characters to Strip ---
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")
```

---

## Step 1: Submit the Textract Job (eob-start Lambda)

```python
def submit_eob_extraction(bucket: str, key: str) -> str:
    """
    S3 event handler: submits an EOB PDF to Textract for async analysis.
    Called by eob-start Lambda when a new PDF lands in the eobs-inbox/ prefix.

    Returns the Textract job ID.
    """
    # Extract a payer hint from the S3 key if your intake pipeline uses per-payer prefixes.
    # e.g., "eobs-inbox/unitedhealthcare/2026/03/01/eob-00423.pdf" → "unitedhealthcare"
    # If you don't use per-payer prefixes, payer_hint will be None throughout the pipeline
    # and all documents will route through Bedrock. Add _detect_payer_from_header() in
    # map_to_canonical_schema as a fallback if needed (see that function's docstring).
    payer_hint = _extract_payer_from_key(key)

    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {"Bucket": bucket, "Name": key}
        },
        FeatureTypes=["FORMS", "TABLES"],   # Both in one job; Textract bills per page
        NotificationChannel={
            "SNSTopicArn": SNS_TOPIC_ARN,
            "RoleArn": TEXTRACT_ROLE_ARN,   # NOT the Lambda execution role.
                                             # Must be a separate role with a trust policy
                                             # for textract.amazonaws.com and sns:Publish.
                                             # Lambda execution role needs iam:PassRole.
        }
    )

    job_id = response["JobId"]

    # Store job context so eob-process Lambda can reconstruct it when SNS fires.
    table = dynamodb.Table(TEXTRACT_JOBS_TABLE)
    table.put_item(Item={
        "job_id":     job_id,
        "bucket":     bucket,
        "key":        key,
        "payer_hint": payer_hint or "unknown",
        "status":     "PENDING",
    })

    # Log only structural metadata; no document content in logs.
    print(f"Textract job submitted: job_id={job_id}, key={key}, payer_hint={payer_hint}")
    return job_id


def _extract_payer_from_key(key: str) -> Optional[str]:
    """
    Parses an S3 key like 'eobs-inbox/unitedhealthcare/2026/...' and returns
    the payer segment if present, or None if the prefix doesn't follow that pattern.
    """
    parts = key.split("/")
    # Expect prefix format: eobs-inbox/{payer}/{year}/{...}
    # The payer segment is parts[1] if parts[0] == "eobs-inbox" and len(parts) >= 3.
    if len(parts) >= 3 and parts[0] == "eobs-inbox":
        candidate = parts[1].lower().strip()
        # Don't return a year as a payer hint.
        if candidate and not candidate.isdigit():
            return candidate
    return None


# [EDITOR: review fix: P1 #4 payer detection: added _detect_payer_from_header() as the
# keyword fallback for pipelines that don't use per-payer S3 prefixes. Called in
# map_to_canonical_schema after _extract_payer_from_key returns None. Scans raw header
# label keys (not values) for known payer name strings. Zero Bedrock cost. Extend the
# keyword dict as you add static profiles.]
def _detect_payer_from_header(raw_header: dict) -> Optional[str]:
    """
    Scans raw extracted header label keys for known payer name strings.
    Falls back to None if no known payer is detected.

    This is the secondary payer detection method for pipelines that don't use
    per-payer S3 prefixes. It runs before the Bedrock call and costs nothing.

    Note: this scans label keys, not values. The label "Member ID" is in raw_header
    as a key; the actual member ID number is the value. We never send values here.
    """
    # Join all header label keys into a single lowercase string for substring matching.
    header_text = " ".join(raw_header.keys()).lower()

    if "unitedhealthcare" in header_text or "united health" in header_text:
        return "unitedhealthcare"
    if "medicare summary" in header_text or "medicare explanation" in header_text:
        return "medicare"
    # Add other known payers here as you build and validate their profiles.
    # Keep keyword patterns specific enough to avoid false matches.
    return None
```

---

## Step 2: Retrieve All Result Blocks (eob-process Lambda)

```python
def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Paginates through all GetDocumentAnalysis result pages.
    Returns (all_blocks, block_map) where block_map is {block_id: block}.

    A multi-page EOB can produce hundreds of blocks. Textract returns at most
    1000 per API call. Missing a page means missing data. Always paginate.
    """
    all_blocks = []
    next_token = None

    while True:
        params = {"JobId": job_id}
        if next_token:
            params["NextToken"] = next_token

        response = textract_client.get_document_analysis(**params)

        if response["JobStatus"] == "FAILED":
            # Log only the status and reason; not any block content.
            reason = response.get("StatusMessage", "unknown")
            print(f"Textract job failed: job_id={job_id}, reason={reason}")
            raise RuntimeError(f"Textract job {job_id} failed: {reason}")

        all_blocks.extend(response.get("Blocks", []))
        next_token = response.get("NextToken")

        if not next_token:
            break

    # Build an O(1) lookup: block_id -> block. Nearly every parsing operation below
    # follows CHILD or VALUE relationships by block ID, so this pays off quickly.
    block_map = {b["Id"]: b for b in all_blocks}

    print(f"Retrieved {len(all_blocks)} blocks for job {job_id}")
    return all_blocks, block_map
```

---

## Step 3: Extract Raw Header Fields and Raw Table Data

```python
def extract_raw_content(
    all_blocks: list,
    block_map: dict
) -> tuple[dict, list]:
    """
    Extracts raw key-value pairs from FORMS output and raw table grids from TABLES output.
    Returns:
        raw_header: {label: {"value": str, "confidence": float}}
        raw_tables: [{"headers": [str], "rows": [[str]], "avg_confidence": float}]
    """
    raw_header = {}
    raw_tables  = []

    # --- FORMS: extract KEY_VALUE_SET blocks ---
    for block in all_blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        if "KEY" not in block.get("EntityTypes", []):
            continue

        key_text = _assemble_text(block, block_map)

        # Follow the VALUE relationship to the paired value block.
        value_block = None
        for rel in block.get("Relationships", []):
            if rel["Type"] == "VALUE":
                for vid in rel["Ids"]:
                    value_block = block_map.get(vid)
                    break

        if not value_block:
            continue

        value_text = _assemble_text(value_block, block_map)
        confidence = min(
            block.get("Confidence", 0.0),
            value_block.get("Confidence", 0.0)
        )
        raw_header[key_text.strip()] = {
            "value": value_text.strip(),
            "confidence": confidence
        }

    # --- TABLES: extract TABLE and CELL blocks ---
    for block in all_blocks:
        if block.get("BlockType") != "TABLE":
            continue

        # Build the row/column grid from CELL children.
        grid = {}   # {row_index: {col_index: {"text": str, "confidence": float}}}
        all_cell_confidences = []

        for rel in block.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue
            for cell_id in rel["Ids"]:
                cell = block_map.get(cell_id)
                if not cell or cell.get("BlockType") != "CELL":
                    continue

                r = cell.get("RowIndex", 0)
                c = cell.get("ColumnIndex", 0)
                cell_text = _assemble_text(cell, block_map)
                conf = cell.get("Confidence", 0.0)
                all_cell_confidences.append(conf)

                col_span = cell.get("ColumnSpan", 1)
                if col_span > 1:
                    # Merged header cell: fill all spanned columns with the same text.
                    # Without this, subsequent column indices are off by (span - 1).
                    for offset in range(col_span):
                        grid.setdefault(r, {})[c + offset] = {
                            "text": cell_text, "confidence": conf
                        }
                else:
                    grid.setdefault(r, {})[c] = {"text": cell_text, "confidence": conf}

        if not grid or max(grid.keys()) < 2:
            continue   # Need at least a header row and one data row.

        # Row 1 is the header row.
        max_col = max(
            col for row_cells in grid.values() for col in row_cells.keys()
        )
        headers = [
            grid.get(1, {}).get(c, {}).get("text", "").strip()
            for c in range(1, max_col + 1)
        ]

        # Rows 2+ are data rows.
        rows = []
        for r in range(2, max(grid.keys()) + 1):
            row = [
                grid.get(r, {}).get(c, {}).get("text", "").strip()
                for c in range(1, max_col + 1)
            ]
            rows.append(row)

        avg_conf = sum(all_cell_confidences) / len(all_cell_confidences) if all_cell_confidences else 0.0
        raw_tables.append({
            "headers":        headers,
            "rows":           rows,
            "avg_confidence": avg_conf,
        })

    return raw_header, raw_tables


def _assemble_text(block: dict, block_map: dict) -> str:
    """
    Assembles the text content of a block by following its CHILD word relationships.
    Returns a space-joined string of all WORD block texts in order.
    """
    words = []
    for rel in block.get("Relationships", []):
        if rel["Type"] != "CHILD":
            continue
        for child_id in rel["Ids"]:
            child = block_map.get(child_id)
            if child and child.get("BlockType") == "WORD":
                words.append(child.get("Text", ""))
    return " ".join(words)
```

---

## Step 4: Map to Canonical Schema

```python
def map_to_canonical_schema(
    raw_header: dict,
    raw_tables: list,
    document_key: str,
    payer_hint: Optional[str]
) -> tuple[dict, str]:
    """
    Maps raw extracted content to the canonical EOB schema.

    Performs an early idempotency check before any expensive LLM call.

    Returns (mapping, mapping_path) where mapping_path is:
        "static_profile"  # used a known high-volume payer profile
        "bedrock_mapping" # used Bedrock LLM mapping
        "mapping_failed"  # Bedrock call failed; route to review

    mapping has shape:
        {
            "table_mapping":  {raw_header_label: canonical_field_name_or_None},
            "header_mapping": {raw_kv_label: canonical_field_name_or_None}
        }
    """
    # [EDITOR: review fix: P1 #5 idempotency check ordering: moved pre-Bedrock.
    # The v2 code placed the idempotency check inside assemble_and_route (after the
    # Bedrock call). SNS delivers at least once, so a Lambda retry fires the full
    # pipeline again including the Bedrock call. Moving the check here avoids paying
    # for redundant schema mapping on duplicate deliveries.
    # This aligns the code with the guidance stated in "Why This Isn't Production-Ready."]
    eob_table = dynamodb.Table(EOB_RECORDS_TABLE)
    existing = eob_table.get_item(
        Key={"document_key": document_key},
        ProjectionExpression="document_key, financial_validation"
    ).get("Item")
    if existing and existing.get("financial_validation", {}).get("status") == "valid":
        print(f"Already processed successfully: {document_key}, skipping")
        raise AlreadyProcessedError(document_key)

    # Check the high-volume profile list first.
    if payer_hint and payer_hint.lower() in HIGH_VOLUME_PROFILES:
        profile = HIGH_VOLUME_PROFILES[payer_hint.lower()]
        mapping = _apply_static_profile(raw_header, raw_tables, profile)
        return mapping, "static_profile"

    # [EDITOR: review fix: P1 #4 payer detection fallback: if S3 prefix didn't yield a
    # payer hint, scan the header labels for known payer keywords before calling Bedrock.
    # The static profile shortcut fires only when per-payer S3 prefixes are in place;
    # this fallback catches the common case where the intake pipeline uses flat prefixes.]
    if payer_hint is None:
        payer_hint = _detect_payer_from_header(raw_header)
        if payer_hint and payer_hint.lower() in HIGH_VOLUME_PROFILES:
            profile = HIGH_VOLUME_PROFILES[payer_hint.lower()]
            mapping = _apply_static_profile(raw_header, raw_tables, profile)
            return mapping, "static_profile"

    # Unknown or unprofiled payer: call Bedrock.
    try:
        mapping = _map_with_llm(raw_header, raw_tables)
        return mapping, "bedrock_mapping"
    except AlreadyProcessedError:
        raise
    except Exception as e:
        # Do NOT log the exception message if it may contain document content.
        print(f"Bedrock schema mapping failed: routing to review (error_type={type(e).__name__})")
        return {"table_mapping": {}, "header_mapping": {}}, "mapping_failed"


class AlreadyProcessedError(Exception):
    """Raised when a document has already been successfully processed (idempotency guard)."""
    pass


# [EDITOR: review fix: P0 #2 _apply_static_profile processes all tables: replaced the
# loop over raw_tables[0]["headers"] with a loop over all elements of raw_tables.
# A 2-page EOB produces multiple Textract TABLE blocks: typically a summary section
# on page 1 and the line item grid on page 2. The v2 code only mapped headers from
# the first table; all subsequent tables kept raw column labels and bypassed financial
# validation silently. This fix iterates all tables, merging mappings across all of them.
# The static profile path is supposed to be the reliable path for high-volume payers;
# it must handle multi-table documents correctly.]
def _apply_static_profile(raw_header: dict, raw_tables: list, profile: dict) -> dict:
    """
    Applies a static payer profile to the extracted raw content.
    Pure dictionary lookup. No external calls.

    Iterates all extracted tables (not just raw_tables[0]) so multi-page EOBs
    with summary + line item sections both get their headers mapped.
    """
    # Map table column headers across ALL extracted tables.
    table_mapping = {}
    for table in raw_tables:    # was: raw_tables[0]["headers"] in v2
        for header in table["headers"]:
            canonical = profile["table_headers"].get(header.strip().lower())
            table_mapping[header] = canonical  # None if not in profile

    # Map key-value header labels.
    header_mapping = {}
    for label in raw_header.keys():
        canonical = profile["kv_fields"].get(label.strip().lower())
        header_mapping[label] = canonical

    return {"table_mapping": table_mapping, "header_mapping": header_mapping}


def _sanitize_for_prompt(text: str) -> str:
    """
    Strips control characters and obvious injection patterns from text before
    including it in a Bedrock prompt. EOB cell values generally don't contain
    these, but a crafted document could try to inject instructions.
    """
    # Remove control characters (keep tab and newline).
    cleaned = _CONTROL_CHARS.sub("", text)
    # Remove any injection-pattern text.
    cleaned = _INJECTION_PATTERNS.sub("[REDACTED]", cleaned)
    # Truncate to a reasonable length; column headers are never this long.
    return cleaned[:200].strip()


def _map_with_llm(raw_header: dict, raw_tables: list) -> dict:
    """
    Calls Bedrock (Nova Pro or Haiku 4.5) to map raw extracted column headers
    to canonical EOB field names.

    Sends:
    - Column headers and first 2 sample rows from each extracted table
    - Raw key-value header labels (not values; we don't need PHI in the prompt)
    - The canonical schema with field descriptions
    Returns the JSON mapping dict with all values validated against the canonical set.
    """
    # Build table samples for the prompt.
    # Send headers + sample rows so the LLM can infer semantics from context.
    # Sanitize all content before including in the prompt.
    # Note: sample rows contain PHI (dates, dollar amounts, procedure codes).
    # Transmission to Bedrock is covered by the BAA; AWS does not retain this data.
    # We include sample rows (despite containing PHI) because value patterns help the LLM
    # infer column semantics (e.g., "$185.00" disambiguates "What Your Plan Paid" from a
    # running total column). This differs from the header section, where label semantics
    # alone are sufficient for mapping and values are not needed.
    table_samples = []
    for table in raw_tables:
        sanitized_headers = [_sanitize_for_prompt(h) for h in table["headers"]]
        sanitized_rows    = [
            [_sanitize_for_prompt(cell) for cell in row]
            for row in table["rows"][:2]    # first 2 rows only for inference context
        ]
        table_samples.append({
            "headers":      sanitized_headers,
            "sample_rows":  sanitized_rows
        })

    # Send only the label keys from the header (not the values; values are PHI).
    sanitized_header_labels = [_sanitize_for_prompt(label) for label in raw_header.keys()]

    prompt_payload = {
        "task": (
            "Map the extracted EOB table column headers and form field labels "
            "to the canonical field names in the provided schema. "
            "Return a JSON object with exactly two keys: "
            "'table_mapping' (maps each extracted column header to a canonical field name or null) "
            "and 'header_mapping' (maps each extracted form field label to a canonical field name or null). "
            "Use only the canonical field names from the schema. "
            "Return only valid JSON. No markdown formatting. No explanation."
        ),
        "extracted_tables": table_samples,
        "extracted_header_labels": sanitized_header_labels,
        "canonical_schema": CANONICAL_SCHEMA,
    }

    user_message = json.dumps(prompt_payload, ensure_ascii=False)

    system_prompt = (
        "You are a healthcare data normalization assistant. "
        "Map EOB document fields to the canonical schema provided. "
        "Return only valid JSON. Never include PHI in your response."
    )

    def _call_bedrock(extra_suffix: str = "") -> str:
        resp = bedrock_client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": system_prompt}],
            messages=[{
                "role": "user",
                "content": [{"text": user_message + extra_suffix}]
            }],
            inferenceConfig={
                "maxTokens":   1024,
                "temperature": 0,   # Deterministic output for schema mapping
            }
        )
        return resp["output"]["message"]["content"][0]["text"]

    # First attempt.
    response_text = _call_bedrock()

    try:
        mapping = json.loads(response_text)
    except json.JSONDecodeError:
        # One retry with an explicit JSON reminder.
        # Log only that a retry happened, not the response content (may echo PHI).
        print("Bedrock returned non-JSON on first attempt, retrying with JSON reminder")
        response_text = _call_bedrock(
            extra_suffix="\n\nYou MUST return only valid JSON. No markdown. No explanation."
        )
        mapping = json.loads(response_text)  # Raises on second failure; caught in caller

    # Validate that the mapping has the expected structure.
    if "table_mapping" not in mapping or "header_mapping" not in mapping:
        raise ValueError("Bedrock mapping response missing required keys")

    # [EDITOR: review fix: P1 #6 canonical field name validation: filter mapping values
    # against the known canonical sets. The LLM is instructed to use only canonical names,
    # but it can produce plausible-sounding variants (e.g., "total_paid" instead of
    # "plan_paid") or -- for crafted column headers -- injection-influenced field names.
    # Non-canonical values are treated as None (unmapped) rather than written to DynamoDB.
    # This enforces the schema trust boundary between the LLM step and all downstream steps:
    # validation, assembly, and storage all assume only canonical field names are present.]
    mapping["table_mapping"] = {
        k: (v if v in _VALID_TABLE_FIELDS else None)
        for k, v in mapping["table_mapping"].items()
    }
    mapping["header_mapping"] = {
        k: (v if v in _VALID_HEADER_FIELDS else None)
        for k, v in mapping["header_mapping"].items()
    }

    return mapping
```

---

## Step 5: Assemble Canonical Line Items

```python
def assemble_line_items(
    raw_header: dict,
    raw_tables: list,
    mapping: dict
) -> tuple[dict, list]:
    """
    Applies the schema mapping to produce canonical header fields and line items.
    """
    table_mapping  = mapping.get("table_mapping", {})
    header_mapping = mapping.get("header_mapping", {})

    # Apply header mapping: keep only successfully mapped fields.
    header_fields = {}
    for raw_label, data in raw_header.items():
        canonical = header_mapping.get(raw_label)
        if canonical:
            header_fields[canonical] = data["value"]

    # Apply table mapping: build canonical line items.
    line_items = []
    for table in raw_tables:
        headers = table["headers"]
        # Map each column header to its canonical name.
        # Unmapped columns keep their raw label rather than being silently dropped.
        canonical_headers = [
            table_mapping.get(h) or h   # fall back to raw label if not mapped
            for h in headers
        ]

        for row in table["rows"]:
            item = {}
            for col_idx, canonical_name in enumerate(canonical_headers):
                item[canonical_name] = row[col_idx] if col_idx < len(row) else ""
            # Skip entirely empty rows (sometimes Textract extracts blank trailing rows).
            if any(v.strip() for v in item.values()):
                line_items.append(item)

    return header_fields, line_items
```

---

## Step 5a: Minimum Coverage Check

```python
# [EDITOR: review fix: P0 #1 minimum coverage assertion: added check_mapping_coverage()
# to enforce the trust boundary between LLM/static-profile mapping and financial validation.
# When Bedrock fails to map financial columns (or a static profile has gaps), the validation
# rules receive None for every financial field and silently skip. The record then exits as
# "valid" with zero financial data, indistinguishable from a correctly validated record.
# This function runs after assemble_line_items and before validate_eob_financials.
# If minimum coverage is not met, the record routes to "mapping_incomplete" rather
# than passing validation silently. Applies to both Bedrock and static profile paths.]
def check_mapping_coverage(line_items: list) -> tuple[bool, Optional[str]]:
    """
    Verifies that the assembled line items include at least the core financial fields
    needed for meaningful validation: billed_amount and plan_paid.

    Returns (ok, reason):
        (True, None)                  # minimum fields present; proceed to validation
        (False, "no_line_items")      # no line items at all (extraction failure or empty doc)
        (False, "required_fields_missing")  # financial columns absent from mapping
    """
    if not line_items:
        return False, "no_line_items"

    has_billed    = any(item.get("billed_amount") for item in line_items)
    has_plan_paid = any(item.get("plan_paid") for item in line_items)

    if not has_billed or not has_plan_paid:
        return False, "required_fields_missing"

    return True, None
```

---

## Step 6: Financial Validation

```python
def parse_currency(text: Optional[str]) -> Optional[float]:
    """
    Parses a dollar string like "$185.00", "1,234.56", "185" into a float.
    Returns None if the string is empty or unparseable.
    """
    if not text or not text.strip():
        return None
    # Remove $, commas, and whitespace.
    cleaned = text.strip().replace("$", "").replace(",", "").strip()
    # Match integer or decimal number.
    match = re.fullmatch(r"\d+(\.\d+)?", cleaned)
    if match:
        return float(cleaned)
    return None


def validate_eob_financials(header_fields: dict, line_items: list) -> list:
    """
    Applies arithmetic validation rules to the canonical line items.
    Returns a list of validation error dicts. Empty list = valid.

    These rules are deterministic. LLMs do not perform financial validation.
    Math is math; the constraints either hold or they don't.

    Call check_mapping_coverage() before this function. If coverage is not met,
    skip this function entirely and route to mapping_incomplete.
    """
    errors = []

    for idx, item in enumerate(line_items):
        row_num = idx + 1  # 1-indexed for human-readable messages

        billed  = parse_currency(item.get("billed_amount"))
        allowed = parse_currency(item.get("allowed_amount"))
        paid    = parse_currency(item.get("plan_paid"))
        member  = parse_currency(item.get("member_responsibility"))

        # Rule 1: Billed >= allowed.
        if billed is not None and allowed is not None:
            if billed < allowed - 0.01:
                errors.append({
                    "row":    row_num,
                    "rule":   "allowed_exceeds_billed",
                    # Do not include extracted dollar amounts in the error detail
                    # if this dict will be logged outside PHI-controlled storage.
                    # For DynamoDB (encrypted at rest), dollar amounts are fine to store.
                    "detail": f"Allowed exceeds billed on line {row_num}"
                })

        # Rule 2: Allowed >= plan paid.
        if allowed is not None and paid is not None:
            if paid > allowed + 0.01:
                errors.append({
                    "row":    row_num,
                    "rule":   "paid_exceeds_allowed",
                    "detail": f"Plan paid exceeds allowed on line {row_num}"
                })

        # Rule 3: Member responsibility reconciles with allowed minus paid.
        # $0.05 tolerance for rounding.
        # Tighten this in COB workflows where exact reconciliation matters.
        # Note: this formula breaks for secondary EOBs in COB scenarios.
        # Add COB-specific validation logic if processing secondary claims.
        if allowed is not None and paid is not None and member is not None:
            expected = round(allowed - paid, 2)
            if abs(member - expected) > 0.05:
                errors.append({
                    "row":    row_num,
                    "rule":   "member_resp_mismatch",
                    "detail": f"Member responsibility does not reconcile on line {row_num}"
                })

    # Rule 4: Line item plan payments sum to header total.
    header_total = parse_currency(header_fields.get("plan_paid"))
    if header_total is not None:
        line_total = sum(
            parse_currency(item.get("plan_paid") or "0") or 0.0
            for item in line_items
        )
        if abs(line_total - header_total) > 0.10:
            errors.append({
                "row":    "header",
                "rule":   "line_total_mismatch",
                "detail": "Line item plan payments do not sum to header total"
            })

    return errors
```

---

## Step 7: Assemble and Route

```python
def _floats_to_decimal(obj):
    """
    Recursively converts Python floats to Decimal for DynamoDB.
    DynamoDB's numeric type is Decimal, not float. boto3 raises TypeError on float values.
    This is a known gotcha. Fix it here rather than discovering it in production.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(i) for i in obj]
    return obj


def assemble_and_route(
    document_key: str,
    payer_hint: Optional[str],
    header_fields: dict,
    line_items: list,
    validation_errors: list,
    mapping_path: str,
    coverage_reason: Optional[str] = None,
) -> dict:
    """
    Assembles the final EOB record and routes it to DynamoDB (all records)
    and SQS (flagged records only).

    mapping_path values:
        "static_profile"    -- high-volume payer; no Bedrock call
        "bedrock_mapping"   -- LLM mapping used
        "mapping_failed"    -- Bedrock call itself failed
        "mapping_incomplete" -- mapping ran but produced no financial fields
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # Determine record status.
    # [EDITOR: review fix: P0 #1 mapping_incomplete status: added explicit status for
    # records that failed the minimum coverage check. "mapping_incomplete" is distinct
    # from "flagged" (validation ran and found math errors) and "valid" (all math passed).]
    if mapping_path == "mapping_incomplete":
        fin_status = "mapping_incomplete"
    elif not validation_errors:
        fin_status = "valid"
    else:
        fin_status = "flagged"

    record = {
        "document_key":  document_key,     # DynamoDB partition key
        "extracted_at":  now,
        "payer_hint":    payer_hint or "unknown",
        "mapping_path":  mapping_path,

        "header": {
            "claim_number":   header_fields.get("claim_number"),
            "member_name":    header_fields.get("member_name"),
            "member_id":      header_fields.get("member_id"),
            "group_number":   header_fields.get("group_number"),
            "provider_name":  header_fields.get("provider_name"),
            "service_period": header_fields.get("service_period"),
        },

        "line_items": line_items,

        "financial_validation": {
            "errors":       validation_errors,
            "status":       fin_status,
            "validated_at": now,
        }
    }

    # Convert floats to Decimal before writing to DynamoDB.
    # If you skip this, boto3 raises: TypeError: Float types are not supported.
    record_for_dynamo = _floats_to_decimal(record)

    # Write every record to DynamoDB: valid, flagged, and mapping_incomplete.
    # The primary idempotency check already ran before the Bedrock call in
    # map_to_canonical_schema. Use attribute_not_exists here as a final guard
    # against race conditions (two concurrent Lambda invocations for the same document).
    eob_table = dynamodb.Table(EOB_RECORDS_TABLE)
    try:
        eob_table.put_item(
            Item=record_for_dynamo,
            ConditionExpression="attribute_not_exists(document_key)"
        )
    except eob_table.meta.client.exceptions.ConditionalCheckFailedException:
        # Already written: idempotent, not an error.
        print(f"Record already exists for document_key={document_key}, skipping write")
        return record

    # Route flagged records to SQS for human review.
    # mapping_incomplete: mapping ran but financial fields were absent.
    # mapping_failed: Bedrock call itself failed.
    # validation errors: financial math didn't check out.
    # All three need human eyes before the record can be trusted.
    needs_review = (
        bool(validation_errors)
        or mapping_path in ("mapping_failed", "mapping_incomplete")
    )
    if needs_review:
        if validation_errors:
            reason = "financial_validation_failed"
        else:
            reason = "schema_mapping_failed"

        review_message = {
            "document_key":      document_key,
            "payer_hint":        payer_hint or "unknown",
            "claim_number":      record["header"].get("claim_number"),
            "validation_errors": validation_errors,
            "mapping_path":      mapping_path,
            "reason":            reason,
        }
        sqs_client.send_message(
            QueueUrl=EOB_REVIEW_QUEUE,
            MessageBody=json.dumps(review_message),
        )
        print(f"Flagged for review: document_key={document_key}, reason={reason}")

    print(f"Processed: document_key={document_key}, status={fin_status}, "
          f"mapping_path={mapping_path}, line_items={len(line_items)}")
    return record
```

---

## Full Pipeline Function (eob-process Lambda Handler)

```python
def process_eob_document(job_id: str, document_key: str, payer_hint: Optional[str]) -> dict:
    """
    Full pipeline for a completed Textract job.
    This is the core of the eob-process Lambda, called after SNS fires.

    Args:
        job_id:       Textract job ID from the SNS notification
        document_key: Original S3 key of the EOB PDF
        payer_hint:   Optional payer name from S3 prefix or header check

    Returns the assembled EOB record dict.
    """
    print(f"Starting EOB processing: job_id={job_id}, key={document_key}")

    # Step 2: Retrieve all Textract blocks via pagination.
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Step 3: Extract raw header key-value pairs and raw table grids.
    raw_header, raw_tables = extract_raw_content(all_blocks, block_map)
    print(f"Extracted: {len(raw_header)} header fields, {len(raw_tables)} tables")

    # Step 4: Map to canonical schema.
    # Includes pre-Bedrock idempotency check (raises AlreadyProcessedError if duplicate).
    # High-volume payers use static profiles (no Bedrock call).
    # All others route through Bedrock for adaptive schema mapping.
    # [EDITOR: review fix: P1 #5 idempotency check ordering: document_key passed in so
    # the pre-Bedrock DynamoDB check can run inside map_to_canonical_schema before any
    # LLM call. See map_to_canonical_schema docstring for details.]
    try:
        mapping, mapping_path = map_to_canonical_schema(
            raw_header, raw_tables, document_key, payer_hint
        )
    except AlreadyProcessedError:
        print(f"Duplicate delivery detected for {document_key}, returning early")
        eob_table = dynamodb.Table(EOB_RECORDS_TABLE)
        return eob_table.get_item(Key={"document_key": document_key}).get("Item", {})

    print(f"Schema mapping complete: path={mapping_path}")

    # Step 5: Assemble canonical line items using the mapping.
    header_fields, line_items = assemble_line_items(raw_header, raw_tables, mapping)
    print(f"Assembled {len(line_items)} line items")

    # Step 5a: Minimum coverage check.
    # [EDITOR: review fix: P0 #1 minimum coverage assertion: added before financial
    # validation. If billed_amount or plan_paid are absent, route to mapping_incomplete
    # rather than running validation against empty fields (which would silently pass).]
    coverage_ok, coverage_reason = check_mapping_coverage(line_items)
    if not coverage_ok:
        print(f"Coverage check failed: reason={coverage_reason}, routing to mapping_incomplete")
        return assemble_and_route(
            document_key=document_key,
            payer_hint=payer_hint,
            header_fields=header_fields,
            line_items=line_items,
            validation_errors=[],
            mapping_path="mapping_incomplete",
            coverage_reason=coverage_reason,
        )

    # Step 6: Financial validation: rule-based, deterministic.
    # LLMs do not perform financial validation.
    validation_errors = validate_eob_financials(header_fields, line_items)
    if validation_errors:
        print(f"Financial validation: {len(validation_errors)} error(s)")
    else:
        print("Financial validation: passed")

    # Step 7: Assemble the record and route.
    record = assemble_and_route(
        document_key=document_key,
        payer_hint=payer_hint,
        header_fields=header_fields,
        line_items=line_items,
        validation_errors=validation_errors,
        mapping_path=mapping_path,
    )

    return record


def lambda_handler(event: dict, context) -> dict:
    """
    eob-process Lambda entry point.
    Triggered by SNS when Textract completes a document analysis job.

    The SNS message contains the job completion notification from Textract.
    The job context (bucket, key, payer_hint) was stored in DynamoDB by eob-start.
    """
    for record in event.get("Records", []):
        sns_message = json.loads(record["Sns"]["Message"])

        job_id     = sns_message.get("JobId")
        job_status = sns_message.get("Status")

        if job_status != "SUCCEEDED":
            print(f"Job did not succeed: job_id={job_id}, status={job_status}")
            continue

        # Retrieve the job context stored by eob-start.
        jobs_table  = dynamodb.Table(TEXTRACT_JOBS_TABLE)
        job_context = jobs_table.get_item(Key={"job_id": job_id}).get("Item", {})

        document_key = job_context.get("key")
        payer_hint   = job_context.get("payer_hint")
        if payer_hint == "unknown":
            payer_hint = None

        if not document_key:
            print(f"No job context found for job_id={job_id}: cannot process")
            continue

        try:
            process_eob_document(job_id, document_key, payer_hint)
        except Exception as e:
            # Log only the error type and job ID; not document content.
            print(f"Processing failed: job_id={job_id}, error_type={type(e).__name__}")
            raise  # Re-raise so Lambda retry logic fires; dead letter queue catches exhausted retries.

    return {"statusCode": 200}
```

---

## Gap to Production

This example works for illustrative purposes. Here's what you'd need to add before deploying it.

**Retry configuration for Bedrock throttling.** Already included above via `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` on the Bedrock client. This handles `ThrottlingException` and `ServiceUnavailableException` with exponential backoff and jitter. Without it, the first time Bedrock throttles your Lambda (and at EOB volume, it will), you get a hard error instead of a transparent retry.

**Lambda timeout.** The default Lambda timeout is 3 seconds. eob-process does paginated Textract retrieval, an optional Bedrock call, financial validation, a DynamoDB write, and an optional SQS send. For a complex multi-page EOB, this runs 15 to 45 seconds. Set eob-process to at minimum 3 minutes in your function configuration. Set eob-start to 30 seconds (it just submits a job).

**VPC endpoints.** If your Lambdas run in a private VPC (which they should in production for HIPAA), you need interface endpoints for: Textract, `bedrock-runtime` (not just `bedrock`; these are different endpoints), SNS, SQS, KMS, and CloudWatch Logs. S3 and DynamoDB use gateway endpoints (free). Missing any of these causes either timeout failures or connection refused, often with confusing error messages. `bedrock-runtime` in particular is easy to miss because the model management endpoint (`bedrock`) and the inference endpoint (`bedrock-runtime`) have different service names. When using cross-region inference profiles, the Lambda call goes to the `bedrock-runtime` VPC endpoint in your deployment region; PHI does not traverse the public internet.

**PHI in logs.** This example logs only structural metadata (document_key, job_id, line item counts, error types). In production, audit every `print` and `logger.error` call to confirm no extracted document content is included. The `_call_bedrock` function's retry path intentionally does not log the Bedrock response because it may contain echoed PHI from the prompt's sample rows. CloudWatch log groups for all Lambda functions should have KMS encryption configured; Lambda does not do this automatically.

**Lambda CloudWatch log group KMS encryption.** Add to your IaC:
```python
# CDK example
from aws_cdk import aws_logs as logs
log_group = logs.LogGroup(
    self, "EobProcessLogGroup",
    log_group_name="/aws/lambda/eob-process",
    encryption_key=eob_kms_key,   # your customer-managed KMS key
    retention=logs.RetentionDays.ONE_YEAR,
)
```

**Dead letter queues.** Both Lambdas receive asynchronous invocations that can fail silently. Wire SQS dead letter queues to both Lambda functions and set CloudWatch alarms on queue depth. A lost EOB in a COB workflow means a pending secondary claim that never resolves.

**Unit tests for static profiles.** The `HIGH_VOLUME_PROFILES` dict is core business logic. Write unit tests that feed sample column headers and assert the canonical output is correct for each payer. A wrong entry in the UHC profile means every UHC EOB produces incorrect output, silently. When a payer updates their template, your tests will catch the drift before your review queue does. Include tests for multi-table EOBs: verify that `_apply_static_profile` maps headers from both a summary table and a line item table correctly.

**Bedrock TPM limits at EOB scale.** The schema mapping call consumes approximately 400–900 tokens per document. At default Nova Pro TPM limits (~800K TPM), you can sustain roughly 900–2,000 Bedrock-path EOBs per minute before throttling. The adaptive retry config handles transient throttling, but for sustained workloads above 500 Bedrock-path EOBs per minute, file a quota increase request before go-live. Batch claim windows (Monday morning, end-of-month) are the relevant planning scenario.

**Bedrock model version pinning.** This example uses cross-region inference profile IDs (`us.amazon.nova-pro-v1:0`). These profiles are AWS-managed mappings that may be updated to point to new model versions. For strict version pinning, use the full foundation model ARN for your region. Check the Bedrock Model IDs documentation for current ARN format. In production, you want to know exactly which model version mapped your EOB schemas.

**COB-specific financial validation.** The `validate_eob_financials` function handles standard single-payer EOBs. For secondary claims in a COB workflow, the `member_responsibility = allowed - paid` identity doesn't hold: the secondary's member responsibility depends on what the primary already paid. Add COB-aware validation logic that accepts the primary EOB record as input and validates the secondary payment against your coordination methodology.

**Prompt injection defense.** The `_sanitize_for_prompt` function strips obvious injection patterns from cell values before including them in the Bedrock prompt. The canonical field name validation in `_map_with_llm` provides a second layer: even if injection produces a plausible-sounding field name, it won't match the canonical set and will be treated as unmapped. In production, add Bedrock Guardrails with content filter type `PROMPT_ATTACK` for a third defense layer:
```python
response = bedrock_client.converse(
    modelId=BEDROCK_MODEL_ID,
    guardrailConfig={
        "guardrailIdentifier": "your-guardrail-id",
        "guardrailVersion":    "DRAFT",
        "trace":               "disabled",  # don't log trace content (may contain PHI)
    },
    ...
)
```

**Bedrock model accuracy testing.** Before relying on the Bedrock mapping path for production EOBs, build a test corpus: save 20-30 sample raw table extractions from diverse payers and assert that the LLM produces correct canonical mappings for each. Specifically test cases with non-obvious column labels, merged header cells, and payers that use abbreviations rather than descriptive labels. Accuracy gaps show up in your review queue; it's better to find them in testing.

**Structured logging.** Replace `print()` calls with `structlog` or Python's `logging` module configured for JSON output. Include `document_key`, `job_id`, and `mapping_path` as structured fields on every log entry. This makes CloudWatch Insights queries tractable when debugging production issues.

**Textract jobs table TTL.** The `textract-jobs` DynamoDB table accumulates records indefinitely without TTL. Add a `ttl` attribute to each job context item and enable TTL on the table. Seven days is a reasonable expiry; completed jobs don't need their context after processing:
```python
import time
table.put_item(Item={
    "job_id":     job_id,
    ...
    "ttl":        int(time.time()) + (7 * 24 * 3600),
})
```
