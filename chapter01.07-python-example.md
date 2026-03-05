# Recipe 1.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.7. It's meant to show one way you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a pharmacy benefits system on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a couple of standard library modules:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs `textract:AnalyzeDocument`, `comprehendmedical:DetectEntitiesV2`, `s3:GetObject`, `s3:PutObject`, and `dynamodb:PutItem`.

---

## Config and Constants

Before we get to the steps, here are the configuration tables this pipeline relies on. They live at the top of your module because they're really configuration disguised as code: lookup tables your team will update as they encounter new pharmacy layouts, new SIG abbreviations, and new edge cases. Get them visible and accessible.

### The SIG Abbreviation Codebook

```python
# SIG_CODES: maps pharmacy abbreviation shorthand to plain English.
#
# "SIG" comes from the Latin "signa" (label). Pharmacists have been using
# Latin shorthand for drug instructions since before aspirin was invented.
# The system never fully went away, which means every prescription directions
# field you'll encounter mixes English words with 2-5 character abbreviations
# that mean nothing to a downstream clinical system.
#
# This dict covers the most common abbreviations you'll see in practice.
# It is not exhaustive. Every pharmacy software system has its own quirks,
# and you will encounter tokens that aren't here. Build logging around
# unrecognized tokens (see the gap-to-production section) and expand this
# table as you go. This is ongoing maintenance, not a one-time setup.
#
# Keys are lowercase. The decode function handles case normalization before lookup.

SIG_CODES = {
    # --- Frequency codes ---
    # These tell you how often to take the medication.
    "qd":     "once daily",
    "qdaily": "once daily",
    "bid":    "twice daily",
    "tid":    "three times daily",
    "qid":    "four times daily",
    "qhs":    "at bedtime",
    "hs":     "at bedtime",
    "prn":    "as needed",
    "stat":   "immediately",
    "q4h":    "every 4 hours",
    "q6h":    "every 6 hours",
    "q8h":    "every 8 hours",
    "q12h":   "every 12 hours",
    "ud":     "as directed",
    "qod":    "every other day",
    "qw":     "once weekly",
    "biw":    "twice weekly",

    # --- Route codes ---
    # These tell you how to administer the medication.
    "po":     "by mouth",
    "sl":     "under the tongue",
    "pr":     "rectally",
    "top":    "topically",
    "inh":    "inhaled",
    "inj":    "by injection",
    "sq":     "subcutaneously",
    "subq":   "subcutaneously",
    "sc":     "subcutaneously",
    "im":     "intramuscularly",
    "iv":     "intravenously",
    "op":     "in the affected eye",
    "au":     "in both ears",
    "ad":     "in the right ear",
    "as":     "in the left ear",

    # --- Timing codes ---
    # These tell you when relative to meals or time of day.
    "ac":     "before meals",
    "pc":     "after meals",
    "cc":     "with meals",
    "am":     "in the morning",
    "pm":     "in the evening",

    # --- Dose form codes ---
    # These identify the physical form of the medication.
    "tab":    "tablet",
    "tabs":   "tablets",
    "cap":    "capsule",
    "caps":   "capsules",
    "ml":     "milliliter",
    "gtt":    "drop",
    "gtts":   "drops",
    "supp":   "suppository",
    "soln":   "solution",
    "susp":   "suspension",
    "oint":   "ointment",
    "crm":    "cream",
    "pch":    "patch",
    "inhlr":  "inhaler",
    "neb":    "nebulizer",
}

# RXNORM_CONFIDENCE_THRESHOLD: minimum Comprehend Medical confidence score
# to include a RxNorm concept in the output.
#
# 0.70 is a reasonable starting point for a member-facing informational display.
# For downstream clinical decision support (drug interaction checking, formulary
# matching), consider raising this to 0.85 or higher. A wrong RxNorm mapping
# in an interaction checker produces a false safety signal that a clinician
# has to investigate. Know your downstream use case before picking this number.
RXNORM_CONFIDENCE_THRESHOLD = 0.70

# CONFIDENCE_THRESHOLD: minimum Textract confidence score (0-100 scale) for
# a field to be written directly to the database without human review.
# Same threshold as Recipe 1.1. Adjust based on your actual error costs.
CONFIDENCE_THRESHOLD = 90.0
```

### The Pharmacy Field Map

```python
# RX_FIELD_MAP: maps canonical field names to the label variants
# that different pharmacy chains print on their labels.
#
# CVS prints "SIG". Walgreens prints "Directions". A regional independent
# prints "Instructions". They all mean the same field. This table is the
# operational knowledge base for handling that inconsistency.
#
# Like the FIELD_MAP in Recipe 1.1, treat this as a living document.
# Every time you see an unrecognized label in your logs, add it here.
# The list will grow. That's normal and expected.

RX_FIELD_MAP = {
    "drug_name": [
        "drug name", "medication", "medication name", "drug",
        "product", "item", "drug/product"
    ],
    "dosage": [
        "strength", "dosage", "dose", "potency", "drug strength"
    ],
    "quantity": [
        "qty", "quantity", "qty dispensed", "disp qty", "qty disp",
        "#", "quantity dispensed", "amount dispensed"
    ],
    "directions": [
        "sig", "directions", "instructions", "take", "use",
        "dir", "patient instructions", "dosage directions"
    ],
    "prescriber": [
        "prescriber", "doctor", "physician", "prescribed by",
        "dr.", "provider", "ordering provider", "written by"
    ],
    "pharmacy": [
        "pharmacy", "store", "dispensed by", "location",
        "dispensing pharmacy", "filled by"
    ],
    "rx_number": [
        "rx #", "rx number", "prescription #", "rx no",
        "prescription number", "rx", "rx num"
    ],
    "refills": [
        "refills", "refills remaining", "refills left",
        "rfl", "ref", "refills authorized", "remaining refills"
    ],
    "days_supply": [
        "days supply", "day supply", "days", "supply",
        "days supplied", "supply days"
    ],
    "date_filled": [
        "date filled", "fill date", "dispensed", "disp date",
        "date", "date dispensed", "filled on"
    ],
    "ndc": [
        "ndc", "ndc #", "national drug code", "ndc code",
        "ndc number", "drug code"
    ],
    "lot_number": [
        "lot", "lot #", "lot number", "lot no", "batch"
    ],
}
```

---

## Step 1: Call Textract

*The pseudocode calls this `extract_label(bucket, key)`. It sends the prescription label image to Amazon Textract and requests FORMS extraction, which returns structured key-value pairs rather than raw text.*

```python
import boto3

# Create the service clients we'll use throughout the pipeline.
# boto3 uses whatever credentials and region are configured in your environment.
textract_client = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")

def extract_label(bucket: str, key: str) -> dict:
    """
    Send a prescription label image from S3 to Textract and get back the
    raw analysis.

    Args:
        bucket: The S3 bucket name (e.g., "rx-labels-inbox")
        key:    The S3 object key (e.g., "rx-labels/2026/03/01/label-00182.jpg")

    Returns:
        The full Textract API response as a Python dictionary.
        We'll parse the structure in Step 2.
    """

    # Call Textract's AnalyzeDocument API with FORMS mode enabled.
    #
    # The FORMS feature type is the critical choice here. Without it, Textract
    # returns a flat list of every detected word with no sense of structure.
    # With FORMS, Textract understands the spatial layout of the label and
    # returns KEY_VALUE_SET blocks: it figures out that "SIG" is a label and
    # "Take 1 tab PO BID x 14d" is the value printed next to it.
    #
    # Prescription labels are single-page. We use the synchronous AnalyzeDocument
    # API, which returns results in under 3 seconds. Multi-page documents
    # (not applicable here) would require the async StartDocumentAnalysis path.
    response = textract_client.analyze_document(
        Document={
            "S3Object": {
                "Bucket": bucket,
                "Name": key,
            }
        },
        FeatureTypes=["FORMS"],
    )

    return response
```

---

## Step 2: Parse Key-Value Pairs

*The pseudocode calls this `parse_key_value_pairs(textract_response)`. Textract returns a flat list of "blocks" connected by ID references. This step walks that structure and assembles matched label-value pairs with confidence scores.*

This is the same block-walking logic as Recipe 1.1. Textract's response structure is consistent across document types, so the parsing code is reusable. The notes below repeat the key concepts for readers coming to this recipe first.

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: given a block and the block map, return the full text of that block
    by assembling it from its CHILD word blocks.

    Textract's text hierarchy goes PAGE > LINE > WORD. A KEY or VALUE block's
    actual text lives in its CHILD WORD blocks. We follow those links to get
    the complete string for each side of a matched pair.
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


def parse_key_value_pairs(textract_response: dict) -> dict:
    """
    Walk the Textract response and extract matched label-value pairs.

    Textract returns KEY_VALUE_SET blocks for both sides of each matched pair.
    The KEY block (the label) points to its paired VALUE block via a "VALUE"
    relationship. Both blocks point to WORD blocks for their actual text.

    This function builds a block index by ID, walks the KEY blocks, follows
    links to paired VALUE blocks, and assembles the text from each side.

    Returns:
        A dict mapping label text to {"value": ..., "confidence": ...}
        Example: {"SIG": {"value": "Take 1 tab PO BID", "confidence": 97.3}}
    """
    blocks = textract_response.get("Blocks", [])

    # Build a lookup index for O(1) block retrieval by ID.
    block_map = {block["Id"]: block for block in blocks}

    key_values = {}

    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue

        entity_types = block.get("EntityTypes", [])
        if "KEY" not in entity_types:
            continue  # skip VALUE blocks; we'll reach them via their KEY

        key_text = get_text_from_block(block, block_map)

        if not key_text:
            continue

        # Follow the "VALUE" relationship to find the paired value block.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                value_id = relationship["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue  # key with no value; skip

        value_text = get_text_from_block(value_block, block_map)

        # Use the lower of the two confidence scores.
        # If either the label or the value was hard to read, flag both.
        key_confidence = block.get("Confidence", 0.0)
        value_confidence = value_block.get("Confidence", 0.0)
        confidence = min(key_confidence, value_confidence)

        key_values[key_text] = {
            "value": value_text,
            "confidence": confidence,
        }

    return key_values
```

---

## Step 3: Normalize Pharmacy Fields

*The pseudocode calls this `normalize_rx_fields(raw_kv)`. It maps whatever labels Textract found on this particular label to consistent canonical field names, regardless of which pharmacy chain printed the label.*

```python
def normalize_rx_fields(raw_kv: dict) -> dict:
    """
    Translate raw Textract label text into canonical field names.

    Prescription labels are inconsistent across pharmacy chains. "SIG",
    "Directions", and "Instructions" all mean the patient instruction line.
    "Refills", "Refills Remaining", and "Rfl" all hold the same count.
    Without this step, downstream systems expecting a consistent "directions"
    field would come up empty whenever a label used a different variant.

    Args:
        raw_kv: The output of parse_key_value_pairs (raw label -> {value, confidence})

    Returns:
        A new dict keyed by canonical field names.
        Unrecognized label keys are dropped here. Log them so you can
        expand RX_FIELD_MAP over time as you encounter new pharmacy formats.
    """
    normalized = {}

    for canonical_name, variants in RX_FIELD_MAP.items():
        for raw_key, raw_val in raw_kv.items():
            # Case-insensitive, whitespace-stripped comparison.
            if raw_key.lower().strip() in variants:
                normalized[canonical_name] = {
                    "value": raw_val["value"].strip(),
                    "confidence": raw_val["confidence"],
                }
                break  # found a match for this canonical field; move on

    return normalized
```

---

## Step 4: Decode SIG Abbreviations

*The pseudocode calls this `decode_sig(raw_sig)`. It translates the pharmacy abbreviation shorthand in the directions field into plain language that downstream systems can display to members and parse for structured data.*

```python
def decode_sig(raw_sig: str) -> str:
    """
    Decode pharmacy SIG abbreviations into plain English.

    The directions field on a prescription label reads like:
        "Take 1 TAB PO BID x 14d PRN pain"

    This function produces:
        "Take 1 tablet by mouth twice daily x 14d as needed pain"

    The approach is word-level substitution: split on whitespace, check each
    token against the codebook, substitute if found, pass through if not.

    Tokens that aren't in the codebook (numbers, drug names, durations like
    "14d", free-text phrases) pass through unchanged. This is intentional:
    we don't want to corrupt data we don't understand.

    Args:
        raw_sig: The raw directions string from the prescription label.

    Returns:
        The decoded directions string with abbreviations expanded to plain English.
    """
    if not raw_sig:
        return ""

    words = raw_sig.split()
    decoded = []

    for word in words:
        # Normalize to lowercase for lookup, but preserve the original case
        # if no substitution is found.
        lookup_key = word.lower().strip(".,;:")  # strip trailing punctuation for lookup

        if lookup_key in SIG_CODES:
            decoded.append(SIG_CODES[lookup_key])
        else:
            # Pass through: not an abbreviation we know.
            # This preserves numbers ("1"), durations ("14d"), custom phrases.
            decoded.append(word)

    return " ".join(decoded)
```

---

## Step 5: Map to RxNorm via Comprehend Medical

*The pseudocode calls this `map_to_rxnorm(drug_name, dosage)`. It passes the medication text through Comprehend Medical's `DetectEntitiesV2` API to identify MEDICATION entities and return the corresponding RxNorm concept IDs.*

```python
def map_to_rxnorm(drug_name: str, dosage: str) -> list:
    """
    Use Comprehend Medical to detect medication entities and map them to
    RxNorm concept IDs.

    DetectEntitiesV2 is trained on clinical and pharmaceutical text. When you
    pass it "Lisinopril 10mg", it identifies the MEDICATION entity, pulls out
    dosage as an attribute, and returns RxNorm concept IDs for the detected
    medication. Those concept IDs are what downstream systems (formulary matchers,
    interaction checkers, FHIR resources) need for interoperability.

    Args:
        drug_name: The drug name extracted from the label (e.g., "Amoxicillin")
        dosage:    The dosage extracted from the label (e.g., "500mg")

    Returns:
        A list of RxNorm concept dicts, sorted by confidence descending.
        Each dict contains: detected_text, rxnorm_id, description, confidence.
        Returns an empty list if no MEDICATION entities are found above the threshold.
    """
    if not drug_name:
        return []

    # Combine drug name and dosage into one string. More context generally
    # improves entity detection accuracy for Comprehend Medical.
    medication_text = f"{drug_name} {dosage}".strip()

    response = comprehend_medical_client.detect_entities_v2(
        Text=medication_text
    )

    rxnorm_mappings = []

    for entity in response.get("Entities", []):
        # DetectEntitiesV2 returns several entity categories: MEDICATION,
        # MEDICAL_CONDITION, TEST_TREATMENT_PROCEDURE, ANATOMY, etc.
        # For this step we only want MEDICATION entities.
        if entity.get("Category") != "MEDICATION":
            continue

        # Each MEDICATION entity can carry one or more RxNorm concept candidates,
        # ranked by score. Walk them and keep the ones above our threshold.
        for concept in entity.get("RxNormConcepts", []):
            if concept.get("Score", 0.0) >= RXNORM_CONFIDENCE_THRESHOLD:
                rxnorm_mappings.append({
                    "detected_text": entity.get("Text", ""),  # what the model read
                    "rxnorm_id":     concept.get("Code", ""), # standard RxNorm concept ID
                    "description":   concept.get("Description", ""), # e.g., "amoxicillin 500 MG Oral Capsule"
                    "confidence":    round(concept.get("Score", 0.0), 3),
                })

    # Sort highest confidence first. The first entry is the best match.
    rxnorm_mappings.sort(key=lambda x: x["confidence"], reverse=True)

    return rxnorm_mappings
```

---

## Step 6: Validate NDC and Compute Refill Metrics

*The pseudocode splits this into `validate_ndc(ndc_raw)` and `compute_refill_metrics(refills_remaining_str, days_supply_str)`. These are two short functions that add real downstream value before writing the final record.*

```python
import re

def validate_ndc(ndc_raw: str) -> dict:
    """
    Validate the format of an extracted NDC code.

    NDC codes are 10-digit identifiers (sometimes represented with hyphens in
    the 5-4-1 or 5-3-2 format on labels). For basic format validation, we
    strip hyphens and check that the result is 10 or 11 numeric digits.

    Note: this validates format only. A well-formed NDC is not necessarily a
    real NDC. For full validation against actual drug products, cross-reference
    against the FDA NDC database. See the gap-to-production section for notes
    on that.

    Args:
        ndc_raw: The raw NDC string extracted from the label (e.g., "0071-0155-23")

    Returns:
        A dict with keys: valid (bool), ndc_normalized (str, if valid),
        ndc_raw (str, if invalid), error (str, if invalid).
    """
    if not ndc_raw:
        return {"valid": False, "ndc_raw": ndc_raw, "error": "NDC field is empty"}

    # Remove hyphens and whitespace before validation.
    ndc_clean = re.sub(r"[-\s]", "", ndc_raw)

    # Standard NDC is 10 digits. Some systems pad to 11.
    # Accept both. Only digits allowed.
    if re.match(r"^\d{10,11}$", ndc_clean):
        return {"valid": True, "ndc_normalized": ndc_clean}
    else:
        return {
            "valid": False,
            "ndc_raw": ndc_raw,
            "error": "NDC format not recognized (expected 10-11 digits)",
        }


def compute_refill_metrics(refills_remaining_str: str, days_supply_str: str) -> dict:
    """
    Compute medication coverage metrics from the refills and days supply fields.

    The formula is straightforward:
        total_days_remaining = (1 + refills_remaining) * days_supply

    The "+1" accounts for the current fill. If you have 3 refills at 30 days
    supply each, you have 4 fills total (1 current + 3 future) = 120 days.

    This calculation drives downstream adherence gap detection: a member with
    7 days of total coverage remaining on a chronic medication is a care gap.
    Centralizing the arithmetic here means every consumer of the record sees
    the same computed value, not their own independent calculation.

    Args:
        refills_remaining_str: Raw string from the label (e.g., "3")
        days_supply_str:       Raw string from the label (e.g., "30")

    Returns:
        A dict with refills_remaining, days_supply, and total_days_remaining.
        Returns None values for fields that can't be parsed (e.g., missing field).
    """
    refills_remaining = None
    days_supply = None
    total_days_remaining = None

    try:
        refills_remaining = int(refills_remaining_str.strip())
    except (ValueError, AttributeError):
        # The field was missing, empty, or contained non-numeric text.
        # Return None rather than crashing. The calling code handles missing fields.
        pass

    try:
        days_supply = int(days_supply_str.strip())
    except (ValueError, AttributeError):
        pass

    # Only compute total if both inputs parsed successfully.
    if refills_remaining is not None and days_supply is not None:
        total_days_remaining = (1 + refills_remaining) * days_supply

    return {
        "refills_remaining":    refills_remaining,
        "days_supply":          days_supply,
        "total_days_remaining": total_days_remaining,
    }
```

---

## Step 7: Assemble and Store the Medication Record

*The pseudocode calls this `store_medication_record(...)`. It assembles all pipeline outputs into a single record and writes it to DynamoDB with a confidence gate: fields below the threshold go into a flagged list for human review rather than being written as clean facts.*

```python
import datetime
from datetime import timezone
from decimal import Decimal

# Create a DynamoDB resource for the table write.
dynamodb = boto3.resource("dynamodb")

# Replace this with your actual DynamoDB table name.
TABLE_NAME = "medication-records"


def store_medication_record(
    image_key: str,
    normalized_fields: dict,
    directions_decoded: str,
    rxnorm_mappings: list,
    ndc_validation: dict,
    refill_metrics: dict,
) -> dict:
    """
    Apply the confidence gate, assemble the full medication record, and write
    it to DynamoDB.

    Every field carries its raw extracted value and its confidence score through
    the pipeline. This step separates fields by confidence: high-confidence
    fields go into the clean record; low-confidence fields go into a flagged
    list for human review. Any NDC validation failure is also flagged.

    The dual representation (raw + normalized for each field) is important for
    auditability. When a care coordinator reviews a record, they can see both
    what the label printed and how the system interpreted it.

    Args:
        image_key:          S3 object key of the original label image.
        normalized_fields:  Output of normalize_rx_fields (canonical name -> {value, confidence}).
        directions_decoded: Output of decode_sig (plain-English directions string).
        rxnorm_mappings:    Output of map_to_rxnorm (list of RxNorm concept dicts).
        ndc_validation:     Output of validate_ndc ({valid, ndc_normalized or error}).
        refill_metrics:     Output of compute_refill_metrics ({refills, days_supply, total_days}).

    Returns:
        The full record dict that was written to DynamoDB.
    """
    table = dynamodb.Table(TABLE_NAME)

    # Split fields by confidence threshold.
    clean_fields = {}
    flagged_fields = []

    for field_name, data in normalized_fields.items():
        if data["confidence"] >= CONFIDENCE_THRESHOLD:
            clean_fields[field_name] = data["value"]
        else:
            # Hold this for human review. Record both what was extracted and
            # how confident the system was, so the reviewer has full context.
            flagged_fields.append({
                "field":           field_name,
                "extracted_value": data["value"],
                "confidence":      Decimal(str(round(data["confidence"], 2))),
                # DynamoDB does not accept Python floats. Wrap in Decimal.
                # Use str() first to avoid floating-point precision artifacts.
                # See the gap-to-production section: this applies to any numeric
                # field you add to DynamoDB items.
            })

    # Flag NDC validation failures separately.
    # A bad NDC format doesn't affect field confidence; it's a structural issue.
    if not ndc_validation.get("valid"):
        flagged_fields.append({
            "field": "ndc",
            "issue": ndc_validation.get("error", "NDC validation failed"),
        })

    # Build the RxNorm mapping list with Decimal scores for DynamoDB.
    rxnorm_for_dynamo = [
        {
            "detected_text": m["detected_text"],
            "rxnorm_id":     m["rxnorm_id"],
            "description":   m["description"],
            "confidence":    Decimal(str(m["confidence"])),
        }
        for m in rxnorm_mappings
    ]

    # Build refill metrics with Decimal for any numeric values.
    refill_metrics_for_dynamo = {}
    for k, v in refill_metrics.items():
        if v is None:
            refill_metrics_for_dynamo[k] = None
        else:
            # int values are fine in DynamoDB, but wrap with Decimal to be safe
            # if the value type ever changes to float.
            refill_metrics_for_dynamo[k] = v  # these are ints from compute_refill_metrics

    record = {
        # Primary key: the S3 key of the source image.
        # Links this record back to the original for audit or reprocessing.
        "image_key": image_key,

        # Extraction timestamp in ISO 8601 UTC format.
        # Required for the HIPAA audit trail. Also useful for debugging.
        "extraction_timestamp": datetime.datetime.now(timezone.utc).isoformat(),

        # High-confidence extracted fields, ready for downstream use.
        "fields": clean_fields,

        # Plain-English directions string, decoded from SIG abbreviations.
        # Stored separately from clean_fields because it's a derived value,
        # not a direct label extraction.
        "directions_decoded": directions_decoded,

        # NDC validation result. Carries ndc_normalized if valid, error if not.
        "ndc_validated": ndc_validation,

        # RxNorm concept mappings. The first entry (highest confidence) is the
        # best match for downstream clinical use.
        "rxnorm_mappings": rxnorm_for_dynamo,

        # Refill coverage metrics derived from the label fields.
        "refill_metrics": refill_metrics_for_dynamo,

        # Fields that fell below the confidence threshold, plus any structural
        # validation failures. Empty list means the record came through clean.
        "flagged_fields": flagged_fields,

        # Simple boolean for downstream systems to check before using the record.
        "needs_review": len(flagged_fields) > 0,
    }

    # Write to DynamoDB. put_item creates or replaces the item.
    # See the gap-to-production section on adding an idempotency check here
    # to prevent duplicate records from S3 at-least-once event delivery.
    table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what your Lambda handler would call.

```python
def process_label(bucket: str, key: str) -> dict:
    """
    Run the full prescription label OCR pipeline for one label image.

    This is the main entry point. In a Lambda deployment, your handler
    parses the S3 event, extracts bucket and key, and calls this function.

    Args:
        bucket: S3 bucket name (e.g., "rx-labels-inbox")
        key:    S3 object key (e.g., "rx-labels/2026/03/01/label-00182.jpg")

    Returns:
        The stored medication record dict.
    """

    # Step 1: Send the label image to Textract for structured analysis.
    # FORMS mode returns key-value pairs, not raw text.
    print(f"Step 1: Calling Textract on s3://{bucket}/{key}")
    textract_response = extract_label(bucket, key)

    # Step 2: Walk the Textract block structure and assemble matched
    # label-value pairs with confidence scores.
    print("Step 2: Parsing key-value pairs from Textract response")
    raw_kv = parse_key_value_pairs(textract_response)
    print(f"  Found {len(raw_kv)} raw key-value pairs")

    # Step 3: Map raw label text to canonical field names.
    # "SIG", "Directions", "Instructions" all become "directions".
    print("Step 3: Normalizing pharmacy fields")
    normalized = normalize_rx_fields(raw_kv)
    print(f"  Matched {len(normalized)} canonical fields")

    # Step 4: Decode SIG abbreviations in the directions field.
    # "Take 1 TAB PO BID" becomes "Take 1 tablet by mouth twice daily".
    print("Step 4: Decoding SIG abbreviations")
    raw_directions = normalized.get("directions", {}).get("value", "")
    directions_decoded = decode_sig(raw_directions)
    print(f"  Raw:     {raw_directions}")
    print(f"  Decoded: {directions_decoded}")

    # Step 5: Map drug name and dosage to RxNorm via Comprehend Medical.
    # Returns ranked RxNorm concept candidates with confidence scores.
    print("Step 5: Mapping to RxNorm via Comprehend Medical")
    drug_name = normalized.get("drug_name", {}).get("value", "")
    dosage = normalized.get("dosage", {}).get("value", "")
    rxnorm_mappings = map_to_rxnorm(drug_name, dosage)
    print(f"  Found {len(rxnorm_mappings)} RxNorm concept(s) above confidence threshold")
    if rxnorm_mappings:
        best = rxnorm_mappings[0]
        print(f"  Best match: {best['description']} (RxNorm: {best['rxnorm_id']}, confidence: {best['confidence']})")

    # Step 6: Validate the NDC format and compute refill coverage metrics.
    print("Step 6: Validating NDC and computing refill metrics")
    ndc_raw = normalized.get("ndc", {}).get("value", "")
    ndc_validation = validate_ndc(ndc_raw)
    print(f"  NDC valid: {ndc_validation['valid']}")

    refills_str = normalized.get("refills", {}).get("value", "")
    days_supply_str = normalized.get("days_supply", {}).get("value", "")
    refill_metrics = compute_refill_metrics(refills_str, days_supply_str)
    print(f"  Refills remaining: {refill_metrics['refills_remaining']}, "
          f"days supply: {refill_metrics['days_supply']}, "
          f"total days remaining: {refill_metrics['total_days_remaining']}")

    # Step 7: Apply confidence gate, assemble the full record, and write to DynamoDB.
    print("Step 7: Storing medication record in DynamoDB")
    result = store_medication_record(
        image_key=key,
        normalized_fields=normalized,
        directions_decoded=directions_decoded,
        rxnorm_mappings=rxnorm_mappings,
        ndc_validation=ndc_validation,
        refill_metrics=refill_metrics,
    )

    print(f"Done. needs_review={result['needs_review']}, "
          f"flagged_fields={len(result['flagged_fields'])}")
    return result


# Example: run the pipeline against a test image.
if __name__ == "__main__":
    import json

    result = process_label(
        bucket="rx-labels-inbox",
        key="rx-labels/2026/03/01/label-00182.jpg",
    )

    # DynamoDB Decimal values aren't JSON serializable by default.
    # This helper converts them for printing.
    def decimal_to_float(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    print(json.dumps(result, indent=2, default=decimal_to_float))
```

---

## The Gap Between This and Production

This example works. Run it against a real label image and it will return a structured medication record with decoded directions, RxNorm concept IDs, and refill coverage metrics. But "works in a script" and "handles real member medication data in production" are meaningfully different. Here's where that distance lives:

**Error handling.** Every external call here (Textract, Comprehend Medical, DynamoDB) can fail, and none of them are wrapped in try/except blocks. A production system handles throttling errors, service unavailability, and malformed responses explicitly, with graceful degradation rather than a Lambda crash that silently drops the label.

**Retries and backoff.** AWS services return throttling errors under sustained load. boto3's default retry configuration is reasonable but worth tuning for Textract and Comprehend Medical specifically. Exponential backoff with jitter is the standard pattern. The `botocore` config object accepts a `retries` parameter.

**Dead Letter Queue.** Lambda on S3 events is asynchronous: failed invocations retry automatically, then the event disappears with no signal. In a medication management pipeline, a silently dropped label means a gap in the member's record with no visible indicator. Configure an SQS dead letter queue on the Lambda event source mapping. Set a CloudWatch alarm on queue depth so you know when labels are failing.

**Idempotency.** S3 delivers event notifications at least once. If the same label triggers two Lambda invocations, this code will write two records with the same `image_key`, overwriting the first. Add a DynamoDB `ConditionExpression` to the `put_item` call that checks for key non-existence: `attribute_not_exists(image_key)`. That turns a silent overwrite into an explicit check.

**SIG codebook coverage.** The 60-odd abbreviations in `SIG_CODES` cover the most common tokens you'll encounter. They do not cover everything. Real pharmacy labels will contain tokens that aren't here: less common Latin abbreviations, pharmacy-specific shorthand, and combinations you haven't seen. Build logging around unrecognized tokens in the directions field from day one. Capture them, review them regularly, and expand the codebook. Without that feedback loop, you'll never know which SIG tokens are passing through as-is instead of being decoded.

**RxNorm concept selection.** `map_to_rxnorm` returns all concept candidates above the confidence threshold, sorted by confidence descending. For many downstream use cases you actually want a single concept, not a list. Decide whether you need the most specific concept (matches strength and dose form exactly, used for formulary tier matching) or the ingredient-level concept (generalizes across package types, used for drug interaction checking). That choice is use-case specific and belongs in your consuming system, not buried in a generic sort.

**NDC validation goes further than format.** A 10-digit string in the right format is a well-formed NDC. Whether it corresponds to a real FDA-registered drug product requires a lookup against the FDA NDC database. The NDC dataset is available as a bulk download. For medication reconciliation programs, consider refreshing it monthly and validating extracted NDCs against a local copy. This catches OCR errors that happen to produce valid-looking but non-existent NDC codes.

**Days supply missing from label.** As noted in the recipe's honest take, some states don't require days supply to be printed on the label. `compute_refill_metrics` handles this gracefully by returning `None` for unparseable fields rather than throwing an exception. Downstream systems need to check for `None` before using `total_days_remaining` in any calculation or display.

**Input validation.** This code trusts its inputs completely. A production system validates that the S3 object exists and is a supported image format before calling Textract, checks that the image is within Textract's size limits (10MB), and rejects requests with malformed bucket or key values. It also verifies that the medication text string passed to Comprehend Medical is within the API's character limit.

**Logging.** The `print()` calls here are placeholders. A production system uses structured logging (the `logging` module or AWS Lambda Powertools) with consistent log levels and machine-parseable output. You want every invocation to emit a log entry with the image key, extraction timestamp, field counts, RxNorm match results, and any errors. This is what your on-call engineer looks at when a care coordinator reports a wrong medication record at 2am.

**IAM least-privilege.** The Lambda execution role should have exactly the permissions this pipeline needs: `textract:AnalyzeDocument` on all resources, `comprehendmedical:DetectEntitiesV2` on all resources, `s3:GetObject` scoped to the specific bucket, `dynamodb:PutItem` scoped to the specific table. Not `s3:*`. Not `AdministratorAccess` because it was convenient during development.

**VPC configuration.** In production, Lambda runs in a private VPC subnet with VPC endpoints for S3, Textract, Comprehend Medical, and DynamoDB. Prescription labels contain PHI. They should never transit the public internet, even though AWS encrypts everything in transit by default. Add the CloudWatch Logs VPC endpoint too: without it, Lambda cannot write logs from a private subnet.

**Encryption key management.** This example relies on default AWS-managed encryption. Production uses KMS customer-managed keys (CMKs) for the S3 bucket and DynamoDB table, with key rotation enabled and CloudTrail logging of every key usage. This is required for a HIPAA-compliant deployment.

**DynamoDB data types.** DynamoDB does not accept Python `float` values. This example wraps all floating-point values in `Decimal` (see Step 7), but be aware: any new numeric field you add to a DynamoDB `put_item` call must also use `Decimal`. The `boto3` DynamoDB resource layer raises a `TypeError` on raw floats with no particularly helpful error message. When in doubt, wrap it.

**Testing.** There are no tests here. A production pipeline has unit tests for `parse_key_value_pairs` (with mocked Textract responses), `decode_sig` (with a representative set of SIG strings), and `compute_refill_metrics` (edge cases: zero refills, missing days supply). Integration tests run against real Textract and Comprehend Medical calls with known synthetic test labels. Build a fixture library covering the pharmacy chains you support. Never use real member labels in your test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.7](chapter01.07-prescription-label-ocr.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
