# Recipe 1.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.9. It demonstrates the core patterns: synchronous Textract with FORMS and SIGNATURES, HIPAA authorization element validation, keyword-based request classification, and SQS routing. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a release-of-information team on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a date parsing library:

```bash
pip install boto3 python-dateutil
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role needs these permissions:

- `textract:AnalyzeDocument` on all resources
- `s3:GetObject` scoped to your records-requests bucket
- `dynamodb:PutItem` scoped to your records-requests table
- `sqs:SendMessage` on each routing queue
- `sns:Publish` on the deficiency notification topic
- `kms:Decrypt` and `kms:GenerateDataKey` for the customer-managed key

---

## Config and Constants

Before the functions, here are the field maps, thresholds, and routing tables. These live at the top of the module because they are configuration, not logic. When you encounter a new form template with different field labels (and you will), you update this section.

```python
import os
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from dateutil import parser as dateutil_parser

# ---------------------------------------------------------------------------
# Field map: canonical field name -> list of label variants seen on real forms.
# Medical records request forms vary widely. There is no industry-standard
# template. Every hospital, health system, and payer ROI department has their
# own version. This list covers the most common patterns. Treat it as a living
# document: whenever a form produces an unrecognized key in your logs, add the
# variant here.
# ---------------------------------------------------------------------------

REQUEST_FIELD_MAP = {
    "patient_name": [
        "patient name", "member name", "name of individual", "name of patient",
        "patient", "name",
    ],
    "patient_dob": [
        "date of birth", "dob", "birth date", "patient dob", "member dob",
    ],
    "patient_id": [
        "medical record number", "medical record #", "mrn", "member id",
        "patient id", "patient number", "id",
    ],
    "requestor_name": [
        "requesting party", "requestor", "requested by", "authorized by",
        "name of requestor", "name of authorized representative",
    ],
    "requestor_org": [
        "organization", "facility name", "practice name", "firm name",
        "organization name", "employer",
    ],
    "requestor_fax": [
        "fax", "fax number", "fax #", "fax no",
    ],
    "records_requested": [
        "records requested", "information requested", "type of records",
        "specific information to be disclosed", "records needed",
        "description of information", "what records",
    ],
    "date_range": [
        "date range", "dates of treatment", "dates of service", "from",
        "period of treatment", "treatment dates", "from date",
    ],
    "purpose": [
        "purpose", "purpose of disclosure", "reason for request",
        "reason", "intended use", "purpose of use",
    ],
    "authorization_date": [
        "date signed", "authorization date", "signature date", "date of signature",
        "date", "signed on",
    ],
    "expiration_date": [
        "expiration date", "expiration", "this authorization expires",
        "authorization expires on", "expires", "valid through",
    ],
    "requestor_npi": [
        "npi", "national provider identifier", "provider npi",
    ],
}

# ---------------------------------------------------------------------------
# HIPAA authorization required elements.
# Under 45 CFR 164.508(c)(1), a valid authorization must include all of these.
# The key is used internally; the value is the human-readable description
# used in deficiency letters.
# ---------------------------------------------------------------------------

REQUIRED_AUTH_ELEMENTS = {
    "patient_or_rep_signature": (
        "Signature of patient or authorized representative "
        "(45 CFR 164.508(c)(1)(vi))"
    ),
    "authorization_date": (
        "Date the authorization was signed "
        "(45 CFR 164.508(c)(1)(vi))"
    ),
    "records_requested": (
        "Description of information to be used or disclosed "
        "(45 CFR 164.508(c)(1)(i))"
    ),
    "purpose": (
        "Purpose of the requested disclosure "
        "(45 CFR 164.508(c)(1)(iv))"
    ),
    "expiration_date": (
        "Expiration date or event "
        "(45 CFR 164.508(c)(1)(v))"
    ),
}

# ---------------------------------------------------------------------------
# Signature confidence threshold.
# Textract's SIGNATURES classifier returns a confidence score from 0 to 100.
# Any detected signature with confidence >= this threshold is accepted as
# present. Signatures below this threshold trigger a needs_review flag rather
# than an outright deficiency.
#
# 70.0 is a reasonable starting point for fax-quality documents. Raise to 80
# for clean digital PDFs. This is a policy decision: your compliance team
# should set the final value, not this file.
# ---------------------------------------------------------------------------

SIGNATURE_CONFIDENCE_THRESHOLD = 70.0

# ---------------------------------------------------------------------------
# Request type keyword signatures.
# Each entry maps a request type to the vocabulary that signals it.
# The purpose field gets double weight in the search corpus (see Step 5).
# min_matches is how many keyword hits are required before that type scores.
# ---------------------------------------------------------------------------

REQUEST_TYPE_SIGNATURES = {
    "care_coordination": {
        "keywords": [
            "continuity of care", "transfer of care", "new treating",
            "treating physician", "referral", "care coordination",
            "new provider", "specialist referral", "transferred care",
        ],
        "min_matches": 1,
    },
    "legal": {
        "keywords": [
            "attorney", "attorney at law", "law firm", "subpoena",
            "court order", "legal proceedings", "litigation", "deposition",
            "plaintiff", "defendant", "personal injury", "workers compensation",
            "workers comp",
        ],
        "min_matches": 1,
    },
    "underwriting": {
        "keywords": [
            "underwriting", "life insurance", "disability",
            "disability insurance", "insurance application",
            "insurance underwriting", "long term disability", "ltd",
            "short term disability",
        ],
        "min_matches": 1,
    },
    "utilization_review": {
        "keywords": [
            "utilization review", "utilization management", "case management",
            "disease management", "health management", "managed care review",
            "independent medical exam", "ime",
        ],
        "min_matches": 1,
    },
    "patient_access": {
        "keywords": [
            "patient request", "personal copy", "right of access",
            "my records", "self", "personal use", "own records", "patient copy",
        ],
        "min_matches": 1,
    },
}

# Tie-breaking order for request type classification.
# When two types score equally, the first one in this list wins.
CLASSIFICATION_PRIORITY = [
    "care_coordination",
    "legal",
    "underwriting",
    "utilization_review",
    "patient_access",
]

# ---------------------------------------------------------------------------
# SQS queue URLs for routing.
# Loaded from environment variables so nothing is hardcoded in the function.
# In a Lambda deployment, set these as environment variables in the function
# configuration.
# ---------------------------------------------------------------------------

FULFILLMENT_QUEUES = {
    "care_coordination":  os.environ.get("CARE_COORDINATION_QUEUE_URL", ""),
    "legal":              os.environ.get("LEGAL_QUEUE_URL", ""),
    "underwriting":       os.environ.get("UNDERWRITING_QUEUE_URL", ""),
    "utilization_review": os.environ.get("UR_QUEUE_URL", ""),
    "patient_access":     os.environ.get("PATIENT_ACCESS_QUEUE_URL", ""),
    "general":            os.environ.get("GENERAL_REVIEW_QUEUE_URL", ""),
}

# SNS topic ARN for deficiency notifications.
DEFICIENCY_TOPIC_ARN = os.environ.get("DEFICIENCY_TOPIC_ARN", "")

# DynamoDB table name.
TABLE_NAME = os.environ.get("RECORDS_REQUESTS_TABLE", "records-requests")

# ---------------------------------------------------------------------------
# AWS clients. Created once at module load time, reused across invocations.
# ---------------------------------------------------------------------------

textract_client = boto3.client("textract")
dynamodb        = boto3.resource("dynamodb")
sqs_client      = boto3.client("sqs")
sns_client      = boto3.client("sns")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
```

---

## Step 1: Synchronous Textract Extraction with FORMS and SIGNATURES

*The pseudocode calls this `extract_records_request(bucket, document_key)`. It sends the request form to Textract with both the FORMS and SIGNATURES feature types and splits the response into the three block categories we need downstream.*

The key difference from Recipe 1.1 is `"SIGNATURES"` in the `FeatureTypes` list. That single addition instructs Textract to run a second-pass classifier specifically looking for handwritten signature regions. The results come back as `SIGNATURE` blocks alongside the `KEY_VALUE_SET` and `LINE` blocks we already know how to handle.

Medical records request forms are one to two pages, so we use `analyze_document` (synchronous) rather than `start_document_analysis` (asynchronous). Synchronous is simpler: one API call, one response, no polling loop. The sync API handles documents up to 10 MB and 1,000 pages, which covers every real-world records request form without issue.

```python
def extract_records_request(bucket: str, document_key: str) -> dict:
    """
    Call Textract AnalyzeDocument with FORMS and SIGNATURES feature types.

    The FORMS feature extracts labeled key-value pairs from the form fields.
    The SIGNATURES feature detects handwritten signature regions.

    Args:
        bucket:       S3 bucket containing the request form PDF or image.
        document_key: S3 object key (path to the file within the bucket).

    Returns:
        A dict with four keys:
          kv_blocks   - KEY_VALUE_SET blocks for field extraction (Step 2)
          sig_blocks  - SIGNATURE blocks for signature detection (Step 3)
          line_blocks - LINE blocks containing page text (Step 5, classification)
          block_map   - All blocks indexed by ID (used by key-value parsing)
    """
    logger.info("Calling Textract AnalyzeDocument on s3://%s/%s", bucket, document_key)

    response = textract_client.analyze_document(
        Document={
            "S3Object": {
                "Bucket": bucket,
                "Name":   document_key,
            }
        },
        FeatureTypes=["FORMS", "SIGNATURES"],
        # FORMS  -> extracts KEY_VALUE_SET blocks (labeled field pairs)
        # SIGNATURES -> adds a second detection pass for handwritten signatures,
        #              returning SIGNATURE blocks with confidence scores and
        #              bounding boxes. This is what we use for authorization
        #              validation in Step 4.
    )

    all_blocks = response.get("Blocks", [])

    # Separate blocks by type. Each type serves a different downstream purpose.
    kv_blocks   = [b for b in all_blocks if b["BlockType"] == "KEY_VALUE_SET"]
    sig_blocks  = [b for b in all_blocks if b["BlockType"] == "SIGNATURE"]
    line_blocks = [b for b in all_blocks if b["BlockType"] == "LINE"]

    # Build a block index: ID -> block. We need this to follow the child
    # relationships that connect KEY blocks to VALUE blocks and to WORD blocks.
    # See Step 2 for how this is used.
    block_map = {b["Id"]: b for b in all_blocks}

    logger.info(
        "Textract returned %d kv_blocks, %d sig_blocks, %d line_blocks",
        len(kv_blocks), len(sig_blocks), len(line_blocks),
    )

    return {
        "kv_blocks":   kv_blocks,
        "sig_blocks":  sig_blocks,
        "line_blocks": line_blocks,
        "block_map":   block_map,
    }
```

---

## Step 2: Parse and Normalize Request Fields

*The pseudocode calls this `parse_and_normalize_fields(kv_blocks, block_map)`. It does two things: first, it assembles raw label-value pairs from Textract's KEY_VALUE_SET blocks (the same traversal pattern from Recipe 1.1); then it maps those raw labels to canonical field names using REQUEST_FIELD_MAP.*

This step includes two helpers that you'll recognize from Recipe 1.1: `get_text_from_block` and `parse_key_value_pairs`. They're reproduced here for completeness.

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: follow a block's CHILD relationships to assemble its full text.

    Textract stores text in WORD blocks. KEY and VALUE blocks point to their
    WORD blocks via CHILD relationships. This function follows those links
    and joins the words into a single string.
    """
    text = ""

    if "Relationships" not in block:
        return text

    for relationship in block.get("Relationships", []):
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child = block_map.get(child_id, {})
                if child.get("BlockType") == "WORD":
                    text += child.get("Text", "") + " "

    return text.strip()


def parse_key_value_pairs(kv_blocks: list, block_map: dict) -> dict:
    """
    Walk KEY_VALUE_SET blocks and assemble matched label-value pairs.

    Textract's FORMS output connects KEY blocks to VALUE blocks through
    a "VALUE" relationship. Each KEY block points to the VALUE block that
    contains the answer. Both sides point to WORD blocks for their actual text.

    Returns:
        A dict mapping raw label text -> {"value": str, "confidence": float}
        Example: {"Patient Name": {"value": "David Park", "confidence": 96.2}}
    """
    key_values = {}

    for block in kv_blocks:
        # We only process the KEY side here; VALUE blocks are reached
        # through the KEY's relationships.
        if "KEY" not in block.get("EntityTypes", []):
            continue

        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue

        # Find the paired VALUE block.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                value_id = relationship["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue

        value_text = get_text_from_block(value_block, block_map)

        # Use the lower of the two confidence scores (key vs. value).
        # If either side was hard to read, we want the conservative number.
        key_conf   = block.get("Confidence", 0.0)
        value_conf = value_block.get("Confidence", 0.0)

        key_values[key_text] = {
            "value":      value_text,
            "confidence": min(key_conf, value_conf),
        }

    return key_values


def parse_and_normalize_fields(kv_blocks: list, block_map: dict) -> dict:
    """
    Extract key-value pairs from Textract blocks and normalize field names.

    Takes the raw output of Textract's FORMS analysis and maps it to a
    consistent set of canonical field names, regardless of which form
    template was used. A field labeled "Requesting Party" on one form and
    "Requestor" on another both become "requestor_name" here.

    Args:
        kv_blocks: KEY_VALUE_SET blocks from the Textract response.
        block_map: All blocks indexed by ID (from Step 1).

    Returns:
        A dict of canonical_field_name -> {"value": str, "confidence": float}
    """
    # First pass: assemble all raw label-value pairs.
    raw_kv = parse_key_value_pairs(kv_blocks, block_map)
    logger.info("Extracted %d raw key-value pairs from Textract", len(raw_kv))

    # Second pass: normalize using the field map.
    normalized = {}

    for canonical_name, label_variants in REQUEST_FIELD_MAP.items():
        for raw_key, raw_val in raw_kv.items():
            # Lowercase both sides before comparing.
            # This handles capitalization differences and any stray whitespace
            # that Textract may have included in the label text.
            if raw_key.lower().strip() in label_variants:
                normalized[canonical_name] = {
                    "value":      raw_val["value"].strip(),
                    "confidence": raw_val["confidence"],
                }
                # Found a match for this canonical field; move to the next one.
                break

    logger.info(
        "Normalized %d canonical fields from %d raw pairs",
        len(normalized), len(raw_kv),
    )
    return normalized
```

---

## Step 3: Extract Signature Data

*The pseudocode calls this `extract_signatures(sig_blocks)`. It reads the SIGNATURE blocks that Textract returned and organizes them into a list sorted by document position (page, then vertical location).*

Each `SIGNATURE` block contains three things we care about: a confidence score (how certain Textract is that this region contains a handwritten signature), the page number it appeared on, and a bounding box showing exactly where on the page it was. We capture all of these. The authorization validator in Step 4 decides what to do with them.

```python
def extract_signatures(sig_blocks: list) -> list:
    """
    Parse SIGNATURE blocks from the Textract response.

    Textract's SIGNATURES classifier identifies regions of the document that
    contain handwritten signature marks. It returns one SIGNATURE block per
    detected region with a confidence score and a bounding box.

    Note what this does NOT tell you: it does not identify whose signature it
    is, whether the signature matches any reference, or whether it is legally
    binding. It only answers: "Does this region look like a handwritten
    signature?" That binary question is what we need for authorization
    validation.

    Args:
        sig_blocks: SIGNATURE blocks from the Textract response.

    Returns:
        A list of dicts, each describing one detected signature:
          {
            "confidence":   float (0-100),
            "page":         int (1-indexed),
            "bounding_box": {"top": float, "left": float,
                             "width": float, "height": float}
          }
        Sorted by page then by vertical position (top-to-bottom reading order).
    """
    signatures = []

    for block in sig_blocks:
        bbox = block.get("Geometry", {}).get("BoundingBox", {})

        signatures.append({
            "confidence":   block.get("Confidence", 0.0),
            "page":         block.get("Page", 1),
            "bounding_box": {
                "top":    bbox.get("Top", 0.0),
                "left":   bbox.get("Left", 0.0),
                "width":  bbox.get("Width", 0.0),
                "height": bbox.get("Height", 0.0),
            },
        })

    # Sort by page first, then by vertical position within the page.
    # This puts signatures in document reading order, which is convenient
    # when reasoning about multi-page forms (e.g., authorization on page 2).
    signatures.sort(key=lambda s: (s["page"], s["bounding_box"]["top"]))

    logger.info(
        "Detected %d signature block(s) from Textract", len(signatures)
    )
    return signatures
```

---

## Step 4: Validate HIPAA Authorization Elements

*The pseudocode calls this `validate_hipaa_authorization(normalized_fields, signatures)`. It checks each of the five required elements from 45 CFR 164.508(c)(1), plus the signature requirement that applies to all of them. The validation returns a structured result showing which elements are present, which are missing, and whether any expiration date has passed.*

This is the compliance core of the pipeline. Read the comments carefully. Two things to keep in mind: first, a `valid: True` result means all required elements are present and unexpired. It does not mean the authorization is legally sufficient; that judgment belongs to your privacy officer. Second, the `needs_review` flag can be `True` even when `valid` is `True`, for edge cases like event-based expirations that require human evaluation.

```python
def _attempt_date_parse(date_string: str):
    """
    Try to parse a string as a date using dateutil's fuzzy parser.

    Returns a datetime.date object if parsing succeeds, or None if the
    string doesn't look like a date (suggesting it's an event description
    like "upon resolution of litigation").

    Args:
        date_string: The expiration value extracted from the form.

    Returns:
        datetime.date or None
    """
    try:
        # fuzzy=True allows dateutil to extract a date from strings that
        # include extra text (e.g., "Expires 02/28/2027" or "valid thru 2027").
        return dateutil_parser.parse(date_string, fuzzy=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


def validate_hipaa_authorization(
    normalized_fields: dict,
    signatures: list,
) -> dict:
    """
    Check each required HIPAA authorization element from 45 CFR 164.508(c)(1).

    The six required elements are:
      1. Signature of the individual (or authorized representative)
      2. Date the authorization was signed
      3. Description of information to be used or disclosed
      4. Person(s) authorized to make the disclosure (from the covered entity)
         -- we check for records_requested as the practical proxy for this
      5. Purpose of the disclosure
      6. Expiration date or event

    Args:
        normalized_fields: Output of parse_and_normalize_fields (Step 2).
        signatures:        Output of extract_signatures (Step 3).

    Returns:
        A validation result dict:
          {
            "valid":          bool,   # False if any required element is missing/expired
            "elements":       dict,   # element_key -> bool (present/absent)
            "missing":        list,   # human-readable descriptions for deficiency letter
            "expired":        bool,   # True if the authorization date is in the past
            "needs_review":   bool,   # True for edge cases requiring human judgment
            "review_reasons": list    # explanations for each needs_review flag
          }
    """
    validation = {
        "valid":          True,
        "elements":       {},
        "missing":        [],
        "expired":        False,
        "needs_review":   False,
        "review_reasons": [],
    }

    # -----------------------------------------------------------------------
    # Check 1: Patient or authorized representative signature.
    # Accept a signature if Textract detected at least one with confidence
    # >= SIGNATURE_CONFIDENCE_THRESHOLD. If something was detected but is
    # below the threshold, flag for human review rather than auto-rejecting.
    # -----------------------------------------------------------------------
    high_conf_sigs = [
        s for s in signatures
        if s["confidence"] >= SIGNATURE_CONFIDENCE_THRESHOLD
    ]
    has_signature = len(high_conf_sigs) > 0

    validation["elements"]["patient_or_rep_signature"] = has_signature

    if not has_signature:
        if not signatures:
            # Nothing detected at all.
            validation["valid"] = False
            validation["missing"].append(
                REQUIRED_AUTH_ELEMENTS["patient_or_rep_signature"]
            )
        else:
            # Something was detected but below the threshold.
            # Could be a faint fax signature. A human should confirm.
            max_conf = max(s["confidence"] for s in signatures)
            validation["valid"] = False
            validation["needs_review"] = True
            validation["review_reasons"].append(
                f"Possible signature detected with low confidence "
                f"({max_conf:.1f}%). Manual review required to confirm."
            )

    # -----------------------------------------------------------------------
    # Check 2: Date signed.
    # The authorization must include the date the patient signed it.
    # -----------------------------------------------------------------------
    auth_date_entry = normalized_fields.get("authorization_date")
    has_auth_date   = bool(
        auth_date_entry and auth_date_entry.get("value", "").strip()
    )

    validation["elements"]["authorization_date"] = has_auth_date
    if not has_auth_date:
        validation["valid"] = False
        validation["missing"].append(REQUIRED_AUTH_ELEMENTS["authorization_date"])

    # -----------------------------------------------------------------------
    # Check 3: Description of records requested.
    # The authorization must identify the information to be disclosed.
    # -----------------------------------------------------------------------
    records_entry = normalized_fields.get("records_requested")
    has_records   = bool(
        records_entry and records_entry.get("value", "").strip()
    )

    validation["elements"]["records_requested"] = has_records
    if not has_records:
        validation["valid"] = False
        validation["missing"].append(REQUIRED_AUTH_ELEMENTS["records_requested"])

    # -----------------------------------------------------------------------
    # Check 4: Purpose of disclosure.
    # The authorization must state why the information is being released.
    # -----------------------------------------------------------------------
    purpose_entry = normalized_fields.get("purpose")
    has_purpose   = bool(
        purpose_entry and purpose_entry.get("value", "").strip()
    )

    validation["elements"]["purpose"] = has_purpose
    if not has_purpose:
        validation["valid"] = False
        validation["missing"].append(REQUIRED_AUTH_ELEMENTS["purpose"])

    # -----------------------------------------------------------------------
    # Check 5: Expiration date or event.
    # The authorization cannot be open-ended. Either a specific date or
    # an event description must be present.
    # If it's a parseable date, we also check whether it has already passed.
    # If it's an event description ("upon resolution of litigation"), we flag
    # for human review since we cannot evaluate it automatically.
    # -----------------------------------------------------------------------
    exp_entry = normalized_fields.get("expiration_date")
    has_expiration = bool(
        exp_entry and exp_entry.get("value", "").strip()
    )

    validation["elements"]["expiration_date"] = has_expiration

    if not has_expiration:
        validation["valid"] = False
        validation["missing"].append(REQUIRED_AUTH_ELEMENTS["expiration_date"])
    else:
        exp_value = exp_entry["value"].strip()
        exp_date  = _attempt_date_parse(exp_value)

        if exp_date is not None:
            # Parseable date: check whether it has already passed.
            today = datetime.datetime.now(timezone.utc).date()
            if exp_date < today:
                validation["valid"]   = False
                validation["expired"] = True
                validation["missing"].append(
                    f"Authorization expired on {exp_date.isoformat()}. "
                    "A renewed authorization is required."
                )
        else:
            # Non-date expiration string: requires human judgment to evaluate.
            validation["needs_review"] = True
            validation["review_reasons"].append(
                f'Expiration is event-based, not date-based: "{exp_value}". '
                "Manual review required to determine whether the authorization "
                "is still valid."
            )

    logger.info(
        "Authorization validation: valid=%s, missing=%d elements, "
        "expired=%s, needs_review=%s",
        validation["valid"],
        len(validation["missing"]),
        validation["expired"],
        validation["needs_review"],
    )
    return validation
```

---

## Step 5: Classify Request Type

*The pseudocode calls this `classify_request_type(normalized_fields, line_blocks)`. It scores the document against keyword lists for each request type and returns the best match, or "general" if nothing clearly signals a specific type.*

The purpose field gets double weight by including it twice in the search corpus. This is intentional: the purpose is the most reliable signal, and we want a strong purpose match to outweigh incidental keyword hits elsewhere in the document. When two types score equally, `CLASSIFICATION_PRIORITY` breaks the tie.

```python
def classify_request_type(normalized_fields: dict, line_blocks: list) -> str:
    """
    Classify the request into one of five fulfillment types (or general).

    The classification uses keyword scoring: we count how many keywords from
    each type's signature appear in the document text. The purpose field gets
    double weight. The type with the highest score above its minimum threshold
    wins. Ties break by CLASSIFICATION_PRIORITY order.

    Supported types:
      care_coordination  - New treating physician, referral, continuity of care
      legal              - Attorney, subpoena, litigation, workers comp
      underwriting       - Life insurance, disability, insurance underwriting
      utilization_review - Utilization review, case management, IME
      patient_access     - Patient's own request under HIPAA Right of Access
      general            - No recognized type; route to general review queue

    Args:
        normalized_fields: Output of parse_and_normalize_fields (Step 2).
        line_blocks:        LINE blocks from the Textract response (Step 1).

    Returns:
        A string request type: one of the five types above or "general".
    """
    # Build the search corpus.
    # Include the purpose field twice to give it double weight.
    purpose_text = normalized_fields.get("purpose", {}).get("value", "")
    full_text    = " ".join(b.get("Text", "") for b in line_blocks)
    search_text  = (purpose_text + " " + purpose_text + " " + full_text).lower()

    scores = {}

    for req_type, signature in REQUEST_TYPE_SIGNATURES.items():
        hits = sum(
            1 for kw in signature["keywords"]
            if kw in search_text
        )
        if hits >= signature["min_matches"]:
            scores[req_type] = hits

    if not scores:
        logger.info("Request classification: no type signals found, routing to general")
        return "general"

    # Find the highest score, breaking ties by CLASSIFICATION_PRIORITY order.
    max_score = max(scores.values())
    candidates = [t for t in CLASSIFICATION_PRIORITY if scores.get(t) == max_score]

    # candidates is already in priority order because we iterated
    # CLASSIFICATION_PRIORITY to build it.
    request_type = candidates[0] if candidates else "general"

    logger.info(
        "Request classification: type=%s, score=%d, all_scores=%s",
        request_type, max_score, scores,
    )
    return request_type
```

---

## Step 6: Assemble the Record and Route

*The pseudocode calls this `assemble_and_route(document_key, normalized_fields, signatures, validation, request_type)`. It builds the structured request record, writes it to DynamoDB, and either routes the request to the appropriate SQS fulfillment queue or triggers the deficiency notification workflow.*

Two paths diverge here based on `validation["valid"]`. Deficient authorizations go to SNS for deficiency letter generation and never touch the fulfillment queues. Valid authorizations go to the type-specific SQS queue for the fulfillment team.

```python
def _safe_value(normalized_fields: dict, field_name: str) -> str:
    """
    Helper: safely extract a field value, returning None if absent.
    Avoids repeated None-guard boilerplate in assemble_and_route.
    """
    entry = normalized_fields.get(field_name)
    if entry is None:
        return None
    return entry.get("value") or None


def assemble_and_route(
    document_key:      str,
    normalized_fields: dict,
    signatures:        list,
    validation:        dict,
    request_type:      str,
) -> dict:
    """
    Build the structured request record, write it to DynamoDB, and route it.

    DynamoDB record uses document_key as the partition key. A conditional
    write (attribute_not_exists) prevents overwriting if the same document
    is processed twice (basic idempotency).

    Args:
        document_key:      S3 key for the original request form.
        normalized_fields: Output of parse_and_normalize_fields (Step 2).
        signatures:        Output of extract_signatures (Step 3).
        validation:        Output of validate_hipaa_authorization (Step 4).
        request_type:      Output of classify_request_type (Step 5).

    Returns:
        The complete record dict that was written to DynamoDB.
    """
    # Determine record status.
    if not validation["valid"]:
        status = "deficient"
    elif validation["needs_review"]:
        status = "pending_review"
    else:
        status = "routed"

    # Compute the max signature confidence (0.0 if no signatures detected).
    sig_max_confidence = (
        max(s["confidence"] for s in signatures) if signatures else 0.0
    )

    # Build the record.
    # All numeric values stored in DynamoDB use Decimal.
    # DynamoDB's boto3 resource layer raises TypeError on raw Python floats.
    # str() first to avoid floating-point representation artifacts in Decimal.
    record = {
        "document_key":  document_key,
        "processed_at":  datetime.datetime.now(timezone.utc).isoformat(),

        # Patient demographics
        "patient": {
            "name":      _safe_value(normalized_fields, "patient_name"),
            "dob":       _safe_value(normalized_fields, "patient_dob"),
            "member_id": _safe_value(normalized_fields, "patient_id"),
        },

        # Requesting party
        "requestor": {
            "name":         _safe_value(normalized_fields, "requestor_name"),
            "organization": _safe_value(normalized_fields, "requestor_org"),
            "fax":          _safe_value(normalized_fields, "requestor_fax"),
            "npi":          _safe_value(normalized_fields, "requestor_npi"),
        },

        # What was requested
        "request_details": {
            "records_requested": _safe_value(normalized_fields, "records_requested"),
            "date_range":        _safe_value(normalized_fields, "date_range"),
            "purpose":           _safe_value(normalized_fields, "purpose"),
        },

        # Classification
        "request_type": request_type,

        # Authorization validation results
        "authorization": {
            "valid":                 validation["valid"],
            "elements":              validation["elements"],
            "missing":               validation["missing"],
            "expired":               validation["expired"],
            "needs_review":          validation["needs_review"],
            "review_reasons":        validation["review_reasons"],
            "auth_date":             _safe_value(normalized_fields, "authorization_date"),
            "expiration_date":       _safe_value(normalized_fields, "expiration_date"),
            "signatures_detected":   len(signatures),
            # Decimal wrapper required for DynamoDB; see the note in "Gap to Production"
            "signature_max_confidence": Decimal(str(round(sig_max_confidence, 2))),
        },

        "status": status,
    }

    # Write to DynamoDB with a conditional expression to prevent duplicates.
    # If the document_key already exists in the table, this call raises
    # ConditionalCheckFailedException. A production system catches that and
    # handles it gracefully (log and skip rather than crash).
    table = dynamodb.Table(TABLE_NAME)
    table.put_item(
        Item=record,
        ConditionExpression="attribute_not_exists(document_key)",
    )
    logger.info("Wrote request record to DynamoDB: %s (status=%s)", document_key, status)

    # Route based on authorization validity.
    if not validation["valid"]:
        # Deficient authorization: notify the deficiency letter workflow.
        # Never route to a fulfillment queue without a valid authorization.
        _send_deficiency_notification(document_key, record, validation)
        return record

    # Valid authorization: send to the type-specific fulfillment queue.
    queue_url = FULFILLMENT_QUEUES.get(request_type) or FULFILLMENT_QUEUES["general"]

    routing_message = {
        "document_key":      document_key,
        "request_type":      request_type,
        "patient_name":      record["patient"]["name"],
        "requestor":         (
            record["requestor"]["name"]
            or record["requestor"]["organization"]
        ),
        "records_requested": record["request_details"]["records_requested"],
        "needs_review":      validation["needs_review"],
    }

    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(routing_message),
    )
    logger.info(
        "Routed request %s to %s queue (needs_review=%s)",
        document_key, request_type, validation["needs_review"],
    )

    return record


def _send_deficiency_notification(
    document_key: str,
    record: dict,
    validation: dict,
) -> None:
    """
    Publish a deficiency notification to the SNS topic.

    The downstream subscriber (typically a letter-generation Lambda) reads
    this event and drafts a deficiency letter to the requestor identifying
    the missing authorization elements.
    """
    notification = {
        "document_key": document_key,
        "patient_name": record["patient"]["name"],
        "requestor":    (
            record["requestor"]["name"]
            or record["requestor"]["organization"]
        ),
        "missing":      validation["missing"],
        "expired":      validation["expired"],
    }

    sns_client.publish(
        TopicArn=DEFICIENCY_TOPIC_ARN,
        Subject="Records Request Authorization Deficiency",
        Message=json.dumps(notification),
    )
    logger.info(
        "Published deficiency notification for %s (%d missing elements)",
        document_key, len(validation["missing"]),
    )
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In a Lambda deployment, your handler parses the S3 event notification, extracts the bucket and key, and calls `process_records_request`.

```python
def process_records_request(bucket: str, document_key: str) -> dict:
    """
    Run the full records request triage pipeline for one form.

    Steps:
      1. Synchronous Textract extraction with FORMS + SIGNATURES
      2. Parse and normalize request fields
      3. Extract signature data
      4. Validate HIPAA authorization elements
      5. Classify request type
      6. Assemble the record and route

    Args:
        bucket:       S3 bucket containing the request form.
        document_key: S3 object key (path to the form within the bucket).

    Returns:
        The complete structured record written to DynamoDB.
    """
    print(f"Processing records request: s3://{bucket}/{document_key}")

    # Step 1: Call Textract with FORMS and SIGNATURES.
    print("Step 1: Extracting form with Textract (FORMS + SIGNATURES)")
    extraction = extract_records_request(bucket, document_key)

    # Step 2: Parse and normalize the request fields.
    print("Step 2: Parsing and normalizing request fields")
    normalized_fields = parse_and_normalize_fields(
        extraction["kv_blocks"],
        extraction["block_map"],
    )
    print(f"  Matched {len(normalized_fields)} canonical fields")

    # Step 3: Extract signature blocks.
    print("Step 3: Extracting signature data")
    signatures = extract_signatures(extraction["sig_blocks"])
    print(f"  Detected {len(signatures)} signature block(s)")

    # Step 4: Validate HIPAA authorization elements.
    # This is the compliance gate: missing elements trigger the deficiency path.
    print("Step 4: Validating HIPAA authorization elements")
    validation = validate_hipaa_authorization(normalized_fields, signatures)
    print(
        f"  valid={validation['valid']}, "
        f"missing={len(validation['missing'])}, "
        f"expired={validation['expired']}, "
        f"needs_review={validation['needs_review']}"
    )

    # Step 5: Classify the request type.
    # Only reached if we have data to classify; deficient requests still
    # get classified so the record is complete for audit purposes.
    print("Step 5: Classifying request type")
    request_type = classify_request_type(normalized_fields, extraction["line_blocks"])
    print(f"  Classified as: {request_type}")

    # Step 6: Assemble the record and route.
    print("Step 6: Assembling record and routing")
    result = assemble_and_route(
        document_key,
        normalized_fields,
        signatures,
        validation,
        request_type,
    )
    print(f"Done. status={result['status']}, request_type={result['request_type']}")

    return result


# Lambda handler entry point.
def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda handler. Triggered by an S3 event notification when a new
    request form is uploaded to the records-requests bucket.
    """
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    result = process_records_request(bucket, key)
    return {"statusCode": 200, "body": json.dumps(result, default=str)}


# Local test entry point.
if __name__ == "__main__":
    result = process_records_request(
        bucket="my-records-requests-bucket",
        document_key="records-requests/2026/03/01/fax-00519.pdf",
    )
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the full pipeline. It calls the real Textract API, validates the real authorization elements, and routes to real SQS queues. But there's meaningful distance between "works on a test form" and "runs in a release-of-information operation handling real patient requests." Here's where that gap lives:

**Error handling.** If Textract returns a service error, the function raises an exception and the Lambda invocation fails. A production system wraps every external call (`analyze_document`, `put_item`, `send_message`, `publish`) in specific exception handling: Textract throttling gets retried with backoff; a DynamoDB `ConditionalCheckFailedException` (duplicate document) gets logged and skipped rather than surfacing as a 500. You want deliberate handling at each failure point, not a blanket try/except.

**The signature confidence threshold is a policy decision.** `70.0` is a reasonable starting point for fax-quality documents. The right value depends on your error costs: too high and you generate deficiency letters for valid but faint signatures; too low and you accept scanning artifacts as evidence of consent. Your compliance and legal teams need to set this number. It should live in a configuration store (AWS AppConfig or Parameter Store) so it can be adjusted without a code deployment.

**Authorization elements are checked for presence, not adequacy.** The HIPAA Privacy Rule requires a description of information to be disclosed that is "specific enough to reasonably identify" it. A value of "all records" passes this check. Whether "all records" meets your organization's legal standard for specificity is a question your privacy officer needs to answer. The pipeline is not a lawyer. It checks that something is there; it does not evaluate whether that something is legally sufficient.

**Expiration validation for event-based authorizations requires integration.** An authorization that says "valid until resolution of the workers' compensation claim" is flagged for human review here. Handling it properly in an automated pipeline would require a real-time lookup against your claims management system. The flag is the mechanism; your operations team needs to build the lookup.

**Duplicate detection across different fax instances.** The `attribute_not_exists` condition on `put_item` prevents double-processing the exact same S3 object. It does not catch "same form, faxed twice, two different S3 keys." A near-duplicate detection step that hashes patient ID, requestor fax, and records description before writing would catch most re-submissions. Straightforward to add, important for operational cleanliness.

**No PHI in logs.** The logger calls in this example log `document_key`, counts, and status flags. They do not log patient names, member IDs, or authorization details. That discipline needs to hold across every log statement you add. Check your CloudWatch log groups before going to production. Enable CloudWatch log data protection on every log group that receives output from this pipeline. It is easy to accidentally include PHI in a debug log.

**Retries and backoff.** `boto3` has built-in retry logic, but you should tune it for each client. Textract's synchronous API can return throttling errors under sustained load. Configure the `botocore.config.Config` retry settings on the Textract client with `mode="adaptive"` and a sensible `max_attempts` value.

**DynamoDB Decimal.** This example uses `Decimal(str(round(value, 2)))` for the `signature_max_confidence` field. Any numeric field you add to the DynamoDB record must follow the same pattern. The `boto3` resource layer raises `TypeError` on any raw Python `float`. The `str()` conversion prevents floating-point representation artifacts that would otherwise cause `Decimal("67.99999999999")` instead of `Decimal("68.0")`.

**VPC and KMS.** In production, this Lambda runs inside a VPC with private subnets. All four service calls (Textract, DynamoDB, SQS, SNS) go through VPC endpoints to stay off the public internet. The S3 bucket, DynamoDB table, and SQS queues use KMS customer-managed keys with rotation enabled. The Lambda execution role has `kms:Decrypt` and `kms:GenerateDataKey` scoped to that specific key ARN.

**Testing.** There are no tests here. A production pipeline has unit tests for `validate_hipaa_authorization` with mocked field sets covering all failure combinations (missing signature, missing expiration, expired date, event-based expiration), unit tests for `classify_request_type` against sample text from each request category, and integration tests against real Textract calls using synthetic request forms. HHS publishes a model HIPAA authorization form; build synthetic test fixtures from it. Never use real patient authorizations in test data.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.9](chapter01.09-medical-records-request-extraction.md) for the full architectural walkthrough, pseudocode, expected results, and honest take on where authorization validation gets complicated.*
