# Recipe 1.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.1. It's meant to show one way you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a clinic on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python installed:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `textract:AnalyzeDocument`, `s3:GetObject`, `s3:PutObject`, and `dynamodb:PutItem`.

---

## The Field Mapping Table

Before we get to the steps, here's the normalization map referenced in Step 3. This lives at the top of your module so it's easy to find and update when you encounter a new payer layout. (You will encounter new payer layouts. This is a promise, not a warning.)

```python
# FIELD_MAP: maps canonical (standard) field names to the list of label variants
# that different payers print on their cards.
#
# The keys are the consistent names your downstream systems will always see.
# The values are lists of lowercase strings to match against whatever Textract
# actually read off the card.
#
# Treat this as a living document. Every time you see an unrecognized key in
# your logs, add it here. The list will grow. That's normal.

FIELD_MAP = {
    "member_id": [
        "member id", "mem id", "member #", "subscriber id",
        "id number", "member number", "mbr id", "mbi"
    ],
    "group_number": [
        "group #", "group number", "group", "grp #", "grp", "group no"
    ],
    "payer_name": [
        "insurance company", "plan name", "payer", "carrier",
        "insurance", "insurer"
    ],
    "plan_type": [
        "plan type", "plan", "product", "coverage type"
    ],
    "copay_pcp": [
        "pcp copay", "office visit", "copay", "pcp",
        "primary care", "primary care visit"
    ],
    "copay_specialist": [
        "specialist copay", "specialist", "specialist visit"
    ],
    "copay_er": [
        "er copay", "emergency room", "er", "emergency",
        "emergency room visit"
    ],
    "rx_bin": [
        "rx bin", "bin", "rx bin #"
    ],
    "rx_pcn": [
        "rx pcn", "pcn", "processor control number"
    ],
    "rx_group": [
        "rx group", "rx grp", "pharmacy group"
    ],
}

# Confidence threshold: fields below this percentage go to the human review
# queue rather than being written directly to the database.
# 90% is a reasonable starting point. Adjust based on your actual error costs.
CONFIDENCE_THRESHOLD = 90.0
```

---

## Step 1: Call Textract

*The pseudocode calls this `extract_card(bucket, key)`. It sends the image to Amazon Textract and requests FORMS extraction, which returns structured key-value pairs rather than raw text.*

```python
import boto3

# Create a Textract client. boto3 will use whatever credentials and region
# are configured in your environment.
textract_client = boto3.client("textract")


def extract_card(bucket: str, key: str) -> dict:
    """
    Send a card image from S3 to Textract and get back the raw analysis.

    Args:
        bucket: The S3 bucket name (e.g., "my-cards-inbox")
        key:    The S3 object key, which is the file path inside the bucket
                (e.g., "cards-inbox/2026/03/01/scan-00482.jpg")

    Returns:
        The full Textract API response as a Python dictionary.
        We'll parse this in the next step.
    """

    # Call Textract's AnalyzeDocument API.
    # The critical choice here is FeatureTypes=["FORMS"].
    #
    # Without FORMS, you'd get raw text: a jumbled list of every word Textract
    # detected, with no sense of which label goes with which value.
    #
    # With FORMS, Textract analyzes the spatial layout of the document and
    # returns KEY_VALUE_SET blocks: it figures out that "Member ID" is a label
    # and "XGP928471003" is the value sitting next to it.
    #
    # For single-page documents like insurance cards, this call is synchronous:
    # you get the results back immediately, usually in 1-3 seconds.
    # Multi-page documents would require the async StartDocumentAnalysis API.
    response = textract_client.analyze_document(
        Document={
            "S3Object": {
                "Bucket": bucket,   # where the image lives
                "Name": key,        # which image to analyze
            }
        },
        FeatureTypes=["FORMS"],     # request key-value pair extraction
    )

    return response
```

---

## Step 2: Parse Key-Value Pairs

*The pseudocode calls this `parse_key_value_pairs(textract_response)`. Textract returns a flat list of "blocks" connected by ID references. This step walks that structure and assembles matched label-value pairs with confidence scores.*

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: given a block and the block map, return the full text of that block
    by assembling it from its CHILD relationships.

    Textract breaks text into a hierarchy: PAGE > LINE > WORD.
    A KEY or VALUE block's actual text lives in its CHILD WORD blocks.
    We follow those links to get the complete string.
    """
    text = ""

    # Check if this block has any relationships (e.g., CHILD links to word blocks).
    if "Relationships" not in block:
        return text

    for relationship in block["Relationships"]:
        # We only care about CHILD relationships here (the word blocks that
        # make up this block's text content).
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child_block = block_map.get(child_id, {})

                # Only grab WORD blocks; skip SELECTION_ELEMENT (checkboxes, etc.)
                if child_block.get("BlockType") == "WORD":
                    # Add the word to our text string, with a space separator.
                    text += child_block.get("Text", "") + " "

    # strip() removes any trailing whitespace left by the loop above.
    return text.strip()


def parse_key_value_pairs(textract_response: dict) -> dict:
    """
    Walk the Textract response and extract matched label-value pairs.

    Textract returns a flat list of "blocks". Some blocks are KEY_VALUE_SET
    blocks (either the label side or the value side of a matched pair).
    The KEY block points to its corresponding VALUE block via a "VALUE"
    relationship. Both sides point to WORD blocks for their actual text content.

    This function builds an index of all blocks by ID, then walks through the
    KEY blocks, follows the links to their paired VALUE blocks, and assembles
    the text from each side.

    Returns:
        A dictionary mapping label text to a dict of {"value": ..., "confidence": ...}
        Example: {"Member ID": {"value": "XGP928471003", "confidence": 98.7}}
    """

    blocks = textract_response.get("Blocks", [])

    # Build a lookup index: block ID -> block data.
    # Textract connects blocks by referencing their IDs, so we need this to
    # follow links in O(1) time instead of scanning the full list each time.
    block_map = {block["Id"]: block for block in blocks}

    key_values = {}  # our output: label text -> {value, confidence}

    for block in blocks:
        # We only care about KEY_VALUE_SET blocks.
        # Textract uses this block type for both the label (KEY) and the
        # answer (VALUE). We start with the KEY side.
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue

        # Check the EntityTypes list to confirm this is the KEY (label) side.
        # Each KEY_VALUE_SET block has an EntityTypes list with either
        # ["KEY"] or ["VALUE"].
        entity_types = block.get("EntityTypes", [])
        if "KEY" not in entity_types:
            continue  # skip VALUE blocks here; we'll reach them via the KEY

        # Assemble the label text from this block's CHILD word blocks.
        # Example output: "Member ID" or "Group #"
        key_text = get_text_from_block(block, block_map)

        if not key_text:
            continue  # nothing to work with; skip this block

        # Find the paired VALUE block by following the "VALUE" relationship
        # on the KEY block. This is how Textract tells us which value belongs
        # with which label.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                # The first (and usually only) ID in this list is the VALUE block.
                value_id = relationship["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue  # KEY with no VALUE; skip (can happen for labels with blank values)

        # Assemble the value text from the VALUE block's CHILD word blocks.
        # Example output: "XGP928471003" or "84023"
        value_text = get_text_from_block(value_block, block_map)

        # Record the confidence as the lower of the two scores (key vs. value).
        # If either side was hard to read, we want to know. This score will
        # drive the quality gate in Step 4.
        key_confidence = block.get("Confidence", 0.0)
        value_confidence = value_block.get("Confidence", 0.0)
        confidence = min(key_confidence, value_confidence)

        # Store the matched pair.
        key_values[key_text] = {
            "value": value_text,
            "confidence": confidence,
        }

    return key_values
```

---

## Step 3: Normalize Field Names

*The pseudocode calls this `normalize_fields(raw_kv)`. It maps whatever labels Textract found on this particular card to a consistent set of canonical field names, regardless of which payer issued the card.*

```python
def normalize_fields(raw_kv: dict) -> dict:
    """
    Translate raw Textract label text into canonical (standardized) field names.

    Insurance cards are inconsistent. "Member ID", "Mem ID", "Subscriber #",
    and "ID Number" all mean the same thing. Without this step, downstream
    systems expecting a consistent "member_id" field would come up empty
    whenever a card used a different label variant.

    Args:
        raw_kv: The output of parse_key_value_pairs: raw label -> {value, confidence}

    Returns:
        A new dict with canonical field names as keys.
        Any raw label that doesn't match a known variant is dropped here.
        Those unmatched keys should be logged so you can add them to FIELD_MAP later.
    """
    normalized = {}

    # Walk through every canonical field name and its list of known label variants.
    for canonical_name, variants in FIELD_MAP.items():

        # Check every label Textract found on this card against this field's variants.
        for raw_key, raw_val in raw_kv.items():
            # Lowercase and strip before comparing.
            # This handles capitalization differences ("MEMBER ID" vs. "Member ID")
            # and any stray whitespace Textract may have included.
            if raw_key.lower().strip() in variants:

                # Match found. Store this field under its canonical name.
                normalized[canonical_name] = {
                    "value": raw_val["value"].strip(),  # clean up any whitespace
                    "confidence": raw_val["confidence"],
                }

                # Found a match for this canonical field. Stop checking variants.
                break

    return normalized
```

---

## Step 4: Flag Low-Confidence Fields

*The pseudocode calls this `flag_low_confidence(fields)`. It applies a quality gate: any field below the confidence threshold is held back for human review rather than written directly to the database.*

```python
def flag_low_confidence(fields: dict) -> tuple[dict, list]:
    """
    Split extracted fields into two groups: clean (high confidence) and
    flagged (low confidence, needs human review).

    Why this matters: a wrong member ID on a claim cascades into a denied
    reimbursement, a billing investigation, and an angry phone call. The cost
    of a human spending five seconds confirming a borderline value is far lower
    than the cost of a wrong value silently becoming a fact in your database.

    Args:
        fields: The output of normalize_fields: canonical name -> {value, confidence}

    Returns:
        A tuple of (clean_fields, flagged_fields):
        - clean_fields: dict of field_name -> value, safe for immediate use
        - flagged_fields: list of dicts describing each field that needs review
    """
    clean = {}    # high-confidence fields, ready to use
    flagged = []  # low-confidence fields, held for human review

    for field_name, data in fields.items():
        if data["confidence"] >= CONFIDENCE_THRESHOLD:
            # Confidence is high enough. Accept this value.
            # Note: we store just the value here (not the confidence score),
            # since that's what downstream systems actually need.
            clean[field_name] = data["value"]

        else:
            # Confidence is too low to trust automatically.
            # Don't discard the value: record it so a reviewer can confirm or
            # correct it. We never want a low-confidence extraction to become
            # a silent fact in the database.
            flagged.append({
                "field": field_name,
                "extracted_value": data["value"],       # what Textract thinks it saw
                "confidence": round(data["confidence"], 2),  # how sure it was
            })

    return clean, flagged
```

---

## Step 5: Store Results

*The pseudocode calls this `store_result(image_key, fields, flagged)`. It writes the extraction record to DynamoDB: the clean fields, the flagged fields awaiting review, and metadata for the audit trail.*

```python
import datetime

# Create a DynamoDB resource. boto3 will use your configured credentials.
dynamodb = boto3.resource("dynamodb")

# Replace this with your actual DynamoDB table name.
TABLE_NAME = "card-extractions"


def store_result(image_key: str, fields: dict, flagged: list) -> dict:
    """
    Write the extraction result to DynamoDB as a permanent record.

    This record is the authoritative output of the pipeline for this card scan.
    It includes: which image was processed, when, what was extracted cleanly,
    what needs human review, and a flag so downstream systems can easily check
    whether this card needs attention.

    Args:
        image_key: The S3 key of the original card image. Links this record
                   back to the source file for audit or reprocessing.
        fields:    High-confidence extracted fields (clean, ready to use).
        flagged:   Low-confidence fields held for human review.

    Returns:
        The full record that was written, so the caller can return it or log it.
    """
    table = dynamodb.Table(TABLE_NAME)

    # Build the record we'll write to the database.
    record = {
        # Which image was this? Stored as the S3 key so we can retrieve it later.
        "image_key": image_key,

        # When did we process this? ISO 8601 format in UTC.
        # This is your audit timestamp: required for HIPAA compliance and useful
        # for debugging ("why did this card get the wrong member ID?").
        "extraction_timestamp": datetime.datetime.utcnow().isoformat() + "Z",

        # High-confidence fields, ready for downstream use.
        "fields": fields,

        # Low-confidence fields, held for human review.
        # Empty list means the whole card came through cleanly.
        "flagged_fields": flagged,

        # Simple boolean flag: does this record need human attention?
        # Downstream systems (review queues, eligibility checks) check this
        # flag first before deciding what to do with the record.
        "needs_review": len(flagged) > 0,
    }

    # Write the record to DynamoDB.
    # put_item creates a new item or replaces an existing one with the same
    # primary key. If you want to protect against overwriting, add a
    # ConditionExpression that checks for key non-existence.
    table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call.

```python
def process_card(bucket: str, key: str) -> dict:
    """
    Run the full insurance card extraction pipeline for one image.

    This is the main entry point. In a Lambda deployment, your handler
    would parse the S3 event, extract the bucket and key, and call this function.

    Args:
        bucket: S3 bucket name
        key:    S3 object key (path to the card image)

    Returns:
        The stored extraction record.
    """

    # Step 1: Send the image to Textract and get the raw analysis back.
    print(f"Step 1: Calling Textract on s3://{bucket}/{key}")
    textract_response = extract_card(bucket, key)

    # Step 2: Walk the Textract response structure and assemble matched
    # label-value pairs with confidence scores.
    print("Step 2: Parsing key-value pairs from Textract response")
    raw_kv = parse_key_value_pairs(textract_response)
    print(f"  Found {len(raw_kv)} raw key-value pairs")

    # Step 3: Map the raw label text to canonical field names.
    # "Member ID", "Mem ID", "Subscriber #" all become "member_id".
    print("Step 3: Normalizing field names")
    normalized = normalize_fields(raw_kv)
    print(f"  Matched {len(normalized)} canonical fields")

    # Step 4: Split fields by confidence. High-confidence fields go straight
    # to the database. Low-confidence fields go to the human review queue.
    print("Step 4: Applying confidence gate")
    clean_fields, flagged_fields = flag_low_confidence(normalized)
    print(f"  Clean: {len(clean_fields)} fields, Flagged: {len(flagged_fields)} fields")

    # Step 5: Write the record to DynamoDB with all extracted data,
    # flagged fields, and a needs_review indicator.
    print("Step 5: Storing result in DynamoDB")
    result = store_result(key, clean_fields, flagged_fields)

    print(f"Done. needs_review={result['needs_review']}")
    return result


# Example: run the pipeline against a test image.
if __name__ == "__main__":
    result = process_card(
        bucket="my-cards-inbox",
        key="cards-inbox/2026/03/01/scan-00482.jpg",
    )

    import json
    print(json.dumps(result, indent=2))
```

---

## The Gap Between This and Production

This example works. Run it against a real card image and it will return a structured JSON record with extracted fields. But there's a meaningful distance between "works in a script" and "runs at a clinic handling real patient data." Here's where that gap lives:

**Error handling.** Right now, if Textract returns an error, the Lambda invocation crashes and the card is lost. A production system wraps every external call in try/except blocks with specific handling for throttling errors, service unavailability, and malformed responses. You want graceful degradation, not silent data loss.

**Retries and backoff.** AWS services occasionally return throttling errors under load. boto3 has built-in retry logic, but you'll want to tune the retry configuration for Textract calls specifically. Exponential backoff with jitter is the standard pattern. The `botocore` config accepts a `retries` parameter.

**Input validation.** This code trusts its inputs completely. A production system validates that the S3 object exists and is a supported image format before calling Textract, checks that the image size is within Textract's limits (10MB), and rejects requests with malformed bucket or key values.

**Logging.** The `print()` calls here are placeholders. A real system uses structured logging (via the `logging` module or AWS Lambda Powertools) with consistent log levels. You want every invocation to produce a machine-parseable log entry with the image key, extraction timestamp, field counts, and any errors. This is what your on-call engineer will look at at 2am.

**IAM least-privilege.** The IAM role for this Lambda should have exactly the permissions it needs and nothing else: `textract:AnalyzeDocument` on all resources, `s3:GetObject` scoped to the specific bucket, `dynamodb:PutItem` scoped to the specific table. Not `s3:*`. Not `dynamodb:*`. Not `AdministratorAccess` because it was convenient during development.

**VPC configuration.** In production, this Lambda runs inside a VPC with private subnets and VPC endpoints for S3, Textract, and DynamoDB. Card images contain PHI. They should never traverse the public internet, even though AWS encrypts everything in transit. VPC endpoints keep traffic on the AWS backbone.

**Encryption key management.** This example relies on default encryption. Production uses KMS customer-managed keys (CMKs) for both the S3 bucket and DynamoDB table, with key rotation enabled and CloudTrail logging of every key usage.

**The FIELD_MAP and unmatched keys.** When Textract reads a label that doesn't match any known variant, this code silently drops it. A production system logs those unrecognized keys so you can review them and add new variants to FIELD_MAP as you encounter new payer layouts. Without that feedback loop, you'll never know what you're missing.

**DynamoDB data types.** DynamoDB doesn't natively store Python floats well at all precision levels. The confidence scores in `flagged_fields` should be stored as `Decimal` rather than `float` in a real implementation. The `boto3` DynamoDB resource layer requires this. You'll hit a `TypeError` on the first float you try to write if you don't handle it.

**Testing.** There are no tests here. A production pipeline has unit tests for `parse_key_value_pairs` (with mocked Textract responses), integration tests against a real Textract call with a known test image, and a fixture library of card images that cover the payer layouts you support. Never use real patient cards in your test fixtures.

The recipe in 1.1 mentions a human review queue for flagged fields. That's Recipe 1.6. The `needs_review` flag this pipeline writes is what feeds it.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.1](chapter01.01-insurance-card-scanning.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
