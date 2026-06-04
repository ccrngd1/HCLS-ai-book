# Recipe 8.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.4. It shows how you could extract medication mentions from clinical notes and normalize them to RxNorm codes using boto3. It is not production-ready. There's no error handling, no retry logic, no input validation. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy against real patient notes on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehendmedical:DetectEntitiesV2`
- `comprehendmedical:InferRxNorm`
- `s3:GetObject`, `s3:PutObject`
- `dynamodb:PutItem`, `dynamodb:Query`

---

## Config and Constants

Before we get into the logic, here are the configuration values that drive the pipeline. These live at the top of your module because they're the first thing you'll want to tune when you deploy this against your own clinical notes.

```python
import re
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for CloudWatch
# Logs Insights queries. Never log extracted medication text (it's PHI).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config: Comprehend Medical throttles under sustained load.
# Adaptive mode uses exponential backoff with jitter.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Clients
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")

# Table and bucket names. Replace with your actual resource names.
MEDICATIONS_TABLE = "patient-medications"
RESULTS_BUCKET = "clinical-nlp-results"

# RxNorm normalization confidence threshold.
# Below this score, the mapping is flagged for pharmacist review rather than
# being accepted automatically. 0.70 is conservative; you might push this
# higher (0.80+) if you'd rather over-flag than under-flag.
RXNORM_CONFIDENCE_THRESHOLD = 0.70

# Section header patterns for clinical note parsing.
# These cover the most common structured note formats from major EHR vendors.
# You'll add to this list as you encounter new note templates.
MEDICATION_HEADERS = [
    "medications", "current medications", "home medications",
    "medications on admission", "discharge medications",
    "medication list", "meds", "active medications",
]
ALLERGY_HEADERS = [
    "allergies", "drug allergies", "medication allergies",
    "allergy list", "adverse reactions",
]
HISTORY_HEADERS = [
    "past medications", "prior medications", "medication history",
    "discontinued medications", "previous medications",
]
```

---

## Step 1: Detect Note Sections

*The pseudocode calls this `detect_sections(note_text)`. Clinical notes have structure (section headers like "MEDICATIONS:" or "ALLERGIES:") that tells us how to interpret medication mentions. A drug under "ALLERGIES" is an allergy, not an active med.*

```python
def detect_sections(note_text: str) -> list[dict]:
    """
    Split a clinical note into sections by detecting header patterns.

    Clinical notes from EHR systems typically use patterns like:
      MEDICATIONS:
      **Current Medications**
      -- Allergies --

    We look for lines that match header-like patterns and use them as
    section boundaries. Each section gets a category (MEDICATION, ALLERGY,
    HISTORY, OTHER) that drives downstream context classification.

    Args:
        note_text: Raw clinical note text, possibly with embedded section headers.

    Returns:
        List of section dicts with keys: header, category, start, text.
        If no headers are detected, the entire note is returned as a single
        section with category "OTHER".
    """
    # Pattern: a line that looks like a header. Matches things like:
    #   "MEDICATIONS:" or "Current Medications:" or "**Allergies**"
    # Strips markdown bold markers and trailing colons/dashes for comparison.
    header_pattern = re.compile(
        r"^\s*[\*\-]*\s*([A-Za-z /]+?)\s*[\*\-]*\s*[:]*\s*$"
    )

    sections = []
    current_section = {
        "header": "PREAMBLE",
        "category": "OTHER",
        "start": 0,
        "text": "",
    }

    for line in note_text.split("\n"):
        match = header_pattern.match(line)
        if match:
            # Save the previous section if it has content.
            if current_section["text"].strip():
                sections.append(current_section)

            header_text = match.group(1).strip().lower()

            # Classify this header.
            if header_text in MEDICATION_HEADERS:
                category = "MEDICATION"
            elif header_text in ALLERGY_HEADERS:
                category = "ALLERGY"
            elif header_text in HISTORY_HEADERS:
                category = "HISTORY"
            else:
                category = "OTHER"

            current_section = {
                "header": header_text,
                "category": category,
                "start": note_text.index(line),  # TODO (TechWriter): Code review Finding 1 (WARNING). str.index() returns first occurrence; duplicate headers get wrong offset. Use running offset counter instead.
                "text": "",
            }
        else:
            current_section["text"] += line + "\n"

    # Don't forget the last section.
    if current_section["text"].strip():
        sections.append(current_section)

    return sections
```

---

## Step 2: Extract Medication Entities

*The pseudocode calls this `extract_medications(note_text)`. This is where Comprehend Medical does the heavy lifting. We send the note text and get back medication entities with their linked attributes (dose, route, frequency) and traits (negation, past history).*

```python
def extract_medications(note_text: str) -> list[dict]:
    """
    Call Amazon Comprehend Medical DetectEntitiesV2 to extract medication
    entities from clinical text.

    DetectEntitiesV2 returns entities across multiple categories (MEDICATION,
    MEDICAL_CONDITION, ANATOMY, etc.). We filter to MEDICATION entities and
    collect their associated attributes (DOSAGE, FREQUENCY, ROUTE_OR_MODE,
    FORM, DURATION, STRENGTH) and traits (NEGATION, PAST_HISTORY).

    The API handles attribute linking automatically: it knows that in
    "lisinopril 20mg PO QD," the 20mg belongs to lisinopril.

    Args:
        note_text: Clinical note text. Max 20,000 characters per call.
                   Longer notes must be chunked (not shown here).

    Returns:
        List of medication dicts with keys: text, begin, end, score,
        attributes, traits.
    """
    response = comprehend_medical.detect_entities_v2(Text=note_text)

    medications = []

    for entity in response.get("Entities", []):
        # Only process medication entities. Comprehend Medical also returns
        # MEDICAL_CONDITION, TEST_TREATMENT_PROCEDURE, ANATOMY, etc.
        if entity.get("Category") != "MEDICATION":
            continue

        med = {
            "text": entity["Text"],
            "begin": entity["BeginOffset"],
            "end": entity["EndOffset"],
            "score": entity["Score"],
            "attributes": {},
            "traits": [],
        }

        # Collect linked attributes: dose, frequency, route, form, etc.
        # Comprehend Medical associates attributes with their parent entity,
        # so "20mg" is already linked to "lisinopril" rather than floating free.
        for attr in entity.get("Attributes", []):
            med["attributes"][attr["Type"]] = {
                "text": attr["Text"],
                "score": attr["Score"],
            }

        # Collect traits: NEGATION means the patient is NOT taking this.
        # PAST_HISTORY means it's a historical medication, not current.
        for trait in entity.get("Traits", []):
            med["traits"].append(trait["Name"])

        medications.append(med)

    return medications
```

---

## Step 3: Normalize to RxNorm

*The pseudocode calls this `normalize_to_rxnorm(medication_text)`. This maps raw extracted text like "lisinopril 20mg" to a standard RxCUI (314077), enabling interoperability with pharmacy systems, formularies, and drug interaction databases.*

```python
def normalize_to_rxnorm(medication_text: str) -> dict:
    """
    Map extracted medication text to an RxNorm concept using InferRxNorm.

    InferRxNorm takes free-text medication mentions and returns ranked
    candidate RxNorm concepts with confidence scores. This is what turns
    "Zestril 20mg" and "lisinopril 20 mg tab" into the same RxCUI.

    The API handles brand-to-generic resolution, common abbreviations,
    and dose-form disambiguation. For ambiguous cases (combination drugs,
    non-standard abbreviations), it returns multiple candidates.

    Args:
        medication_text: Raw medication text from the extraction step.
                         e.g., "lisinopril 20mg" or "Lipitor 40"

    Returns:
        Dict with keys: rxcui, description, score, status.
        status is one of: MATCHED, NEEDS_REVIEW, UNMATCHED.
    """
    response = comprehend_medical.infer_rx_norm(Text=medication_text)

    # InferRxNorm returns entities, each with a list of RxNormConcepts.
    # We flatten and sort by score to find the best match.
    candidates = []
    for entity in response.get("Entities", []):
        for concept in entity.get("RxNormConcepts", []):
            candidates.append({
                "rxcui": concept["RxCUI"],
                "description": concept["Description"],
                "score": concept["Score"],
            })

    # Sort by confidence, highest first.
    candidates.sort(key=lambda c: c["score"], reverse=True)

    if candidates and candidates[0]["score"] >= RXNORM_CONFIDENCE_THRESHOLD:
        return {
            "rxcui": candidates[0]["rxcui"],
            "description": candidates[0]["description"],
            "score": candidates[0]["score"],
            "status": "MATCHED",
        }
    elif candidates:
        # Best guess exists but confidence is too low. Flag for pharmacist review.
        return {
            "rxcui": candidates[0]["rxcui"],
            "description": candidates[0]["description"],
            "score": candidates[0]["score"],
            "status": "NEEDS_REVIEW",
        }
    else:
        # No candidates at all. Could be a misspelling, unusual abbreviation,
        # or a non-medication entity that leaked through.
        return {
            "rxcui": None,
            "description": None,
            "score": 0.0,
            "status": "UNMATCHED",
        }
```

---

## Step 4: Classify Context and Assertion Status

*The pseudocode calls this `classify_medication_context(med, section_category)`. Not every medication mention belongs on the active list. This step combines NER traits and section context to determine if a medication is active, historical, negated, or an allergy.*

```python
def classify_medication_context(med: dict, section_category: str) -> str:
    """
    Determine the assertion status of an extracted medication mention.

    Uses two signals:
    1. NER traits from Comprehend Medical (NEGATION, PAST_HISTORY)
    2. Which note section the medication was found in

    This is what prevents your medication list from including drugs the patient
    explicitly said they don't take, or allergies that shouldn't be on the
    active med list.

    Args:
        med: A medication dict from extract_medications() with a "traits" list.
        section_category: The category of the note section where this med was
                          found (MEDICATION, ALLERGY, HISTORY, OTHER).

    Returns:
        One of: "ACTIVE", "NEGATED", "HISTORICAL", "ALLERGY".
    """
    # Negation trait overrides everything. "Denies taking metformin" or
    # "not currently on lisinopril" should never appear as active meds.
    if "NEGATION" in med["traits"]:
        return "NEGATED"

    # Past history trait: "was on," "previously took," "prior to admission."
    if "PAST_HISTORY" in med["traits"]:
        return "HISTORICAL"

    # Section-based classification for cases where traits alone are insufficient.
    if section_category == "ALLERGY":
        return "ALLERGY"

    if section_category == "HISTORY":
        return "HISTORICAL"

    # Default: medication found in active meds section or in narrative
    # without negation or historical markers. Conservative choice: treat
    # as active unless proven otherwise.
    return "ACTIVE"
```

---

## Step 5: Assemble and Store Structured Medication Records

*The pseudocode calls this `store_medication_extraction(patient_id, note_id, medications, sections)`. This combines everything into a final structured record and writes it to DynamoDB and S3.*

```python
def find_section_for_offset(sections: list[dict], offset: int) -> dict:
    """
    Determine which note section contains a given character offset.

    We walk the sections in reverse order (largest start offset first) and
    return the first section whose start position is at or before the offset.
    """
    # Sort sections by start position descending for lookup.
    sorted_sections = sorted(sections, key=lambda s: s["start"], reverse=True)

    for section in sorted_sections:
        if offset >= section["start"]:
            return section

    # Fallback: if no section matched, return a generic one.
    return {"header": "unknown", "category": "OTHER"}


def store_medication_extraction(
    patient_id: str,
    note_id: str,
    medications: list[dict],
    sections: list[dict],
) -> list[dict]:
    """
    For each extracted medication: normalize to RxNorm, classify context,
    build a structured record, and write to DynamoDB + S3.

    This is the final assembly step. Downstream systems (medication
    reconciliation, drug interaction checking, clinical decision support)
    consume these structured records rather than re-parsing notes.

    Args:
        patient_id: Unique patient identifier.
        note_id: Unique identifier for the source clinical note.
        medications: List of medication dicts from extract_medications().
        sections: List of section dicts from detect_sections().

    Returns:
        List of structured medication records that were stored.
    """
    table = dynamodb.Table(MEDICATIONS_TABLE)
    extraction_ts = datetime.datetime.now(timezone.utc).isoformat()

    structured_meds = []

    for med in medications:
        # Which section was this medication found in?
        section = find_section_for_offset(sections, med["begin"])

        # Classify assertion status (active, negated, historical, allergy).
        assertion = classify_medication_context(med, section["category"])

        # Normalize to RxNorm.
        rxnorm = normalize_to_rxnorm(med["text"])

        # Build the structured record.
        record = {
            "patient_id": patient_id,
            "sort_key": f"{extraction_ts}#{note_id}#{med['begin']}",
            "note_id": note_id,
            "medication_text": med["text"],
            "rxcui": rxnorm["rxcui"],
            "rxnorm_description": rxnorm["description"],
            # DynamoDB requires Decimal for numbers, not float.
            # Wrapping via str() avoids floating-point representation issues.
            "rxnorm_score": Decimal(str(round(rxnorm["score"], 4))),
            "rxnorm_status": rxnorm["status"],
            "dosage": med["attributes"].get("DOSAGE", {}).get("text"),
            "frequency": med["attributes"].get("FREQUENCY", {}).get("text"),
            "route": med["attributes"].get("ROUTE_OR_MODE", {}).get("text"),
            "form": med["attributes"].get("FORM", {}).get("text"),
            "duration": med["attributes"].get("DURATION", {}).get("text"),
            "strength": med["attributes"].get("STRENGTH", {}).get("text"),
            "assertion": assertion,
            "confidence": Decimal(str(round(med["score"], 4))),
            "source_section": section["header"],
            "extraction_ts": extraction_ts,
        }

        structured_meds.append(record)

        # Write to DynamoDB. Partition key: patient_id, sort key: composite.
        table.put_item(Item=record)

    # Write full extraction to S3 for audit trail and reprocessing.
    s3_key = f"results/{patient_id}/{note_id}/medications.json"
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=s3_key,
        Body=json.dumps(structured_meds, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    return structured_meds
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call when a new clinical note arrives.

```python
# Synthetic clinical note for demonstration.
# This covers the common scenarios: active meds, allergies, historical meds,
# and a negated medication. In production, this text comes from S3 or an
# HL7 message feed.
SAMPLE_NOTE = """
Patient: Jane Doe
Date: 2026-03-01
Provider: Dr. Smith

Current Medications:
Lisinopril 20mg oral daily
Metformin 500mg oral twice daily
Atorvastatin 40mg oral at bedtime

Allergies:
Penicillin (rash)
Sulfa drugs (anaphylaxis)

Past Medications:
Amlodipine 5mg - discontinued 2025-06 due to edema

Assessment:
Patient is well-controlled on current regimen. She is not taking aspirin
despite prior recommendation. Will continue current medications. Consider
adding low-dose aspirin at next visit.
"""


def process_clinical_note(patient_id: str, note_id: str, note_text: str) -> list[dict]:
    """
    Run the full medication extraction and normalization pipeline for one note.

    Steps:
    1. Detect note sections (medications, allergies, history, etc.)
    2. Extract medication entities with attributes and traits
    3. For each medication: normalize to RxNorm, classify context, store

    Args:
        patient_id: Unique patient identifier.
        note_id: Unique identifier for this clinical note.
        note_text: Raw text of the clinical note.

    Returns:
        List of structured medication records.
    """
    # Step 1: Section detection.
    logger.info("Step 1: Detecting note sections")
    sections = detect_sections(note_text)
    logger.info("  Found %d sections", len(sections))

    # Step 2: NER extraction.
    logger.info("Step 2: Extracting medication entities")
    medications = extract_medications(note_text)
    logger.info("  Found %d medication mentions", len(medications))

    # Steps 3-5: Normalize, classify, and store each medication.
    logger.info("Steps 3-5: Normalizing, classifying, and storing")
    results = store_medication_extraction(patient_id, note_id, medications, sections)
    logger.info("  Stored %d structured medication records", len(results))

    return results


if __name__ == "__main__":
    results = process_clinical_note(
        patient_id="PAT-2026-00482",
        note_id="NOTE-20260301-1422",
        note_text=SAMPLE_NOTE,
    )

    # Print results for inspection. In production, these would flow to
    # medication reconciliation workflows or clinical decision support.
    for med in results:
        print(f"  {med['medication_text']:25s} -> {med['rxnorm_description'] or 'UNMATCHED':40s} "
              f"[{med['assertion']:10s}] (RxNorm score: {med['rxnorm_score']})")
```

---

## The Gap Between This and Production

This example works. Point it at a real clinical note and Comprehend Medical will return structured medication extractions with RxNorm codes. But there's a meaningful distance between "works in a script" and "runs in a health system processing thousands of notes daily." Here's where that gap lives:

**Error handling.** Right now, if Comprehend Medical returns an error (throttling, service unavailability, malformed input), the script crashes. A production system wraps every API call in try/except blocks with specific handling for `ThrottlingException`, `TextSizeLimitExceededException`, and `InternalServerException`. You want graceful degradation and dead-letter queues, not silent note loss.

**Text size limits.** Comprehend Medical's DetectEntitiesV2 accepts a maximum of 20,000 UTF-8 characters per call. Clinical notes (especially discharge summaries) can exceed this. A production system chunks long notes at section boundaries, processes each chunk, and merges results with offset correction. The chunking logic isn't trivial because you can't split mid-sentence without risking attribute-linking errors.

**Retries and backoff.** The adaptive retry config handles basic throttling, but for batch processing (running through thousands of historical notes), you'll want a rate-limiting layer. Comprehend Medical has per-account transactions-per-second limits. Step Functions with a Map state and a concurrency limit is the standard pattern for controlled batch throughput.

**Input validation.** This code trusts that note_text is a valid UTF-8 string within size limits. A production system validates encoding, rejects binary content, strips null bytes, and checks character count before calling the API. Clinical text from HL7 feeds sometimes arrives with encoding issues or embedded control characters.

**Logging and observability.** The `logger.info()` calls here are placeholders. A real system emits structured metrics: medications extracted per note, RxNorm match rate, assertion distribution, processing latency. CloudWatch custom metrics or embedded metric format lets you build dashboards and alarms. Never log the actual medication text (it's PHI); log counts, scores, and statuses.

**IAM least-privilege.** The IAM role for this Lambda needs exactly: `comprehendmedical:DetectEntitiesV2` and `comprehendmedical:InferRxNorm` on all resources, `s3:GetObject` and `s3:PutObject` scoped to specific buckets, `dynamodb:PutItem` scoped to the specific table. No wildcards. No `AdministratorAccess`.

**VPC configuration.** Clinical notes contain PHI. In production, the Lambda runs in a VPC with private subnets and VPC endpoints for Comprehend Medical, S3, DynamoDB, and CloudWatch Logs. API traffic stays on the AWS backbone and never traverses the public internet.

**Encryption key management.** This example uses default encryption (`aws:kms`). Production uses customer-managed KMS keys (CMKs) with rotation enabled and CloudTrail logging of all key usage. S3, DynamoDB, and CloudWatch Logs each get their own CMK with appropriately scoped key policies.

**DynamoDB data types.** The code already wraps numeric values in `Decimal()` (see Step 5), but be aware that any new numeric field you add must also use `Decimal`. The boto3 DynamoDB resource layer raises a `TypeError` on raw Python floats in `put_item` calls. Converting via `str()` first avoids floating-point representation issues (e.g., `Decimal(0.1)` produces `0.100000000000000005551115...` while `Decimal("0.1")` produces `0.1`).

**RxNorm version management.** RxNorm is updated monthly by the NLM. AWS updates the version used by InferRxNorm on their own schedule. This means RxCUI mappings can shift between runs. A production system records the API version or response metadata with each extraction so you can trace which RxNorm version produced a given mapping.

**Combination drug handling.** "HCTZ/lisinopril 12.5/20" is a single mention of a combination drug. InferRxNorm handles many of these, but some require splitting into components and normalizing each ingredient separately. A production system has fallback logic for combination drugs that don't resolve cleanly.

**Pharmacist review workflow.** Medications with `NEEDS_REVIEW` or `UNMATCHED` status need a human review queue. This example stores the flag but doesn't implement the review UI or approval workflow. In practice, you'd send these to a pharmacist review queue (could be a FHIR Task, a work item in the EHR, or a custom review application) and update the record once adjudicated.

**Testing.** There are no tests here. A production pipeline has unit tests for `detect_sections` (with synthetic notes covering common EHR templates), integration tests against Comprehend Medical with known test notes, and a golden dataset of annotated medication mentions for measuring extraction accuracy over time. Never use real patient notes in your test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.4](chapter08.04-medication-extraction-normalization) for the full architectural walkthrough, pseudocode, and honest take on where medication extraction gets hard.*
